#!/usr/bin/env python3
"""
docs_write_guard.py - the scope proof for a docs home whose pages live behind an API (opscenter/DESIGN.md sections 5.2 and 12.3,
item 7). It is the `docs_home` slot's `api` variant guard: the ONLY sanctioned path for any docs mutation an automation makes.

A write is permitted ONLY when the target page's ancestor chain reaches an allowed root and never passes through an excluded
root. Anything the guard cannot POSITIVELY prove in scope is REFUSED (fail closed). Deletes and every tool outside the mutation
allowlist are hard blocked. Scope is resolved on the SAME connector the write executes on (JSON-RPC over streamable HTTP with a
bearer token from the sign-in slot), so validation and execution can never disagree about tenant or auth.

Usage:
  docs_write_guard.py check   <tool> '<json-args>'
  docs_write_guard.py execute <tool> '<json-args>'
  check   validate scope only, print a verdict JSON, never writes. exit 0 = ALLOW, 3 = REFUSE, 2 = usage or other error.
  execute validate scope; if ALLOW, perform the write and print the result (exit 4 if the write fails); if REFUSE, exit 3 and
          write nothing.

Allowlisted tools (mutations): createConfluencePage, updateConfluencePage. Everything else is REFUSED.
Every decision (ALLOW and REFUSE) is appended to the guard log.

Parameters (a JSON file named by DOCS_GUARD_CONFIG, or the environment; local/params.json `docs`):
  allowed_roots     {page or folder id: label}: a write must land inside one of them (required; none means every write is refused)
  excluded_roots    {id: label}: never write inside these, even under an allowed root
  cloud_id          the tenant id the connector calls take
  endpoint          the connector URL
  forbidden         list of regexes: a write body or title that matches one is refused (for example a retired wiki's links)
  log_path          the decision log (default <state>/dashboard/docs-guard.log)
Credentials: set_token_provider(fn) with fn() -> bearer token. No provider means every write is refused. A secret never appears in a
parameter or a log.
"""

import contextlib
import datetime as dt
import json
import os
import re
import ssl
import sys
import urllib.request

ALLOWED_TOOLS = {"createConfluencePage", "updateConfluencePage"}
MAX_DEPTH = 20


def load_config():
    path = os.environ.get("DOCS_GUARD_CONFIG")
    cfg = {}
    if path:
        try:
            with open(path, encoding="utf-8") as fh:
                cfg = json.load(fh)
        except (OSError, ValueError):
            cfg = {}
    cfg = dict(cfg) if isinstance(cfg, dict) else {}
    state = os.environ.get("OPSCENTER_STATE_DIR") or os.path.expanduser("~/.opscenter/state")
    return {
        "allowed_roots": {str(k): str(v) for k, v in (cfg.get("allowed_roots") or {}).items()},
        "excluded_roots": {str(k): str(v) for k, v in (cfg.get("excluded_roots") or {}).items()},
        "cloud_id": str(cfg.get("cloud_id") or os.environ.get("DOCS_CLOUD_ID") or ""),
        "endpoint": str(cfg.get("endpoint") or os.environ.get("DOCS_ENDPOINT") or ""),
        "forbidden": [re.compile(p, re.I) for p in (cfg.get("forbidden") or [])],
        "log_path": str(cfg.get("log_path") or os.path.join(state, "dashboard", "docs-guard.log")),
    }


_token_provider = None


def set_token_provider(fn):
    """Plug in the sign-in slot: fn() returns the bearer token (or raises)."""
    global _token_provider
    _token_provider = fn


def _log(cfg, verdict, tool, target, detail):
    try:
        ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        os.makedirs(os.path.dirname(cfg["log_path"]), exist_ok=True)
        with open(cfg["log_path"], "a", encoding="utf-8") as f:
            f.write(f"{ts} {verdict:7} tool={tool} target={target} {detail}\n")
    except OSError:
        pass


def _parse(raw):
    raw = raw.strip()
    if not raw:
        return None
    if raw.startswith("{"):
        return json.loads(raw)
    obj = None
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload and payload != "[DONE]":
                with contextlib.suppress(json.JSONDecodeError):
                    obj = json.loads(payload)
    return obj


class Connector:
    """Minimal JSON-RPC session: initialize once, then reuse for calls."""

    def __init__(self, cfg, token):
        self.cfg = cfg
        self.token = token
        self.ctx = ssl.create_default_context()
        self.sid = None
        self._init()

    def _rpc(self, payload, notify=False):
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": "docs-write-guard/1.0",
            "MCP-Protocol-Version": "2024-11-05",
        }
        if self.sid:
            headers["Mcp-Session-Id"] = self.sid
        req = urllib.request.Request(
            self.cfg["endpoint"], data=json.dumps(payload).encode(), headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, context=self.ctx, timeout=90) as resp:
            self.sid = resp.headers.get("Mcp-Session-Id", self.sid)
            raw = resp.read().decode("utf-8")
            return None if notify else _parse(raw)

    def _init(self):
        init = self._rpc(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "docs-write-guard", "version": "1.0"},
                },
            }
        )
        if not init or "result" not in init:
            raise RuntimeError(f"connector initialize failed: {init}")
        self._rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}, notify=True)

    def call(self, tool, args):
        return self._rpc(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": tool, "arguments": args},
            }
        )

    def get_page(self, page_id):
        """(ok, dict-or-errmsg). ok False when the id is not a fetchable page (a folder 404s) or any error occurs."""
        out = self.call(
            "getConfluencePage", {"cloudId": self.cfg["cloud_id"], "pageId": str(page_id)}
        )
        try:
            obj = json.loads(out["result"]["content"][0]["text"])
        except (KeyError, IndexError, TypeError, ValueError):
            return False, f"unparseable response for {page_id}"
        if isinstance(obj, dict) and obj.get("error"):
            return False, obj.get("message", "error")[:120]
        return True, obj

    def descendant_ids(self, ancestor_id, node_type):
        """The set of ids of {node_type} under ancestor_id via a query, or None on failure. Used to prove FOLDER containment
        downward, because folders 404 on the pages call and cannot be walked upward."""
        args = {
            "cloudId": self.cfg["cloud_id"],
            "cql": f"ancestor = {ancestor_id} AND type = {node_type}",
            "limit": 100,
        }
        out = self.call("searchConfluenceUsingCql", args)
        try:
            obj = json.loads(out["result"]["content"][0]["text"])
        except (KeyError, IndexError, TypeError, ValueError):
            return None
        found = set()
        for r in obj.get("results", []):
            c = r.get("content", r)
            if c.get("id"):
                found.add(str(c["id"]))
        return found

    def folder_in_scope(self, folder_id):
        """Prove a FOLDER is in scope by downward containment: a descendant folder of an allowed root that is neither an excluded
        root nor a descendant of one. Fail closed: a failed query means not in scope. Returns (bool, reason)."""
        fid = str(folder_id)
        if fid in self.cfg["excluded_roots"]:
            return False, f"target IS the excluded folder {self.cfg['excluded_roots'][fid]}"
        inside = False
        for root in self.cfg["allowed_roots"]:
            under = self.descendant_ids(root, "folder")
            if under is None:
                return False, "could not enumerate the allowed root's folders (failing closed)"
            if fid in under:
                inside = True
                break
        if not inside:
            return False, f"folder {fid} is not a descendant of an allowed root"
        for ex in self.cfg["excluded_roots"]:
            under_ex = self.descendant_ids(ex, "folder")
            if under_ex is None:
                return False, "could not enumerate an excluded root's folders (failing closed)"
            if fid in under_ex:
                return (
                    False,
                    f"folder {fid} is inside the excluded folder {self.cfg['excluded_roots'][ex]}",
                )
        return True, "folder is under an allowed root and outside every excluded root"


def resolve_scope(conn, start_id):
    """Walk the ancestor chain upward from start_id. Returns (verdict, reason, chain), verdict ALLOW or REFUSE. Fail closed: any
    ambiguity is a REFUSE. start_id is the page being modified (update) or the intended parent of a new page (create)."""
    cfg = conn.cfg
    chain = []
    node = str(start_id)
    if node in cfg["excluded_roots"]:
        return "REFUSE", f"target IS the excluded root {cfg['excluded_roots'][node]}", chain
    if node in cfg["allowed_roots"]:
        return "ALLOW", f"target is the {cfg['allowed_roots'][node]} itself", [node]
    depth = 0
    while node and depth < MAX_DEPTH:
        depth += 1
        ok, obj = conn.get_page(node)
        if not ok:
            if node in cfg["excluded_roots"]:
                return (
                    "REFUSE",
                    f"chain passes through the excluded root {cfg['excluded_roots'][node]}",
                    chain,
                )
            return "REFUSE", f"cannot resolve node {node} ({obj}); failing closed", chain
        chain.append((obj.get("id"), obj.get("title")))
        parent = obj.get("parentId")
        if parent in cfg["excluded_roots"] or obj.get("id") in cfg["excluded_roots"]:
            return "REFUSE", "chain passes through an excluded root", chain
        if parent in cfg["allowed_roots"]:
            chain.append((parent, cfg["allowed_roots"][parent]))
            return "ALLOW", f"chain reaches the {cfg['allowed_roots'][parent]}", chain
        if not parent:
            return "REFUSE", "reached the top of the space without hitting an allowed root", chain
        node = str(parent)
    return "REFUSE", f"exceeded max depth {MAX_DEPTH} without proving scope", chain


def _body_text(args):
    """The writable body text from the args regardless of shape, plus the title (published content too)."""
    b = args.get("body")
    parts = []
    if isinstance(b, str):
        parts.append(b)
    elif isinstance(b, dict):
        for k in ("value", "markdown", "storage", "atlas_doc_format", "representation"):
            v = b.get(k)
            if isinstance(v, str):
                parts.append(v)
            elif isinstance(v, dict) and isinstance(v.get("value"), str):
                parts.append(v["value"])
    if isinstance(args.get("title"), str):
        parts.append(args["title"])
    return "\n".join(parts)


def check_forbidden(cfg, args):
    """(leaked, matched text) when the write body or title matches a forbidden pattern."""
    text = _body_text(args)
    if not text:
        return False, None
    for pat in cfg["forbidden"]:
        m = pat.search(text)
        if m:
            return True, m.group(0)
    return False, None


def validate(conn, tool, args):
    """(verdict, reason, target, chain)."""
    cfg = conn.cfg
    if tool not in ALLOWED_TOOLS:
        return "REFUSE", f"tool '{tool}' is not in the mutation allowlist", None, []
    leaked, hit = check_forbidden(cfg, args)
    if leaked:
        return "REFUSE", f"write body matches a forbidden pattern ('{hit}')", None, []
    if tool == "createConfluencePage":
        parent = args.get("parentId")
        if not parent:
            return (
                "REFUSE",
                "createConfluencePage without a parentId (would land at the space root)",
                None,
                [],
            )
        v, reason, chain = resolve_scope(conn, parent)
        return v, reason, f"create under {parent}", chain
    page_id = args.get("pageId") or args.get("id")
    if not page_id:
        return "REFUSE", "updateConfluencePage without a pageId", None, []
    v, reason, chain = resolve_scope(conn, page_id)
    if v != "ALLOW":
        return v, reason, f"update {page_id}", chain
    new_parent = args.get("parentId")
    if new_parent:
        # A move: BOTH the page and the destination must pass. Try the upward walk; if the destination is a FOLDER
        # (folders 404 on the pages call) fall back to the downward containment proof.
        v2, reason2, chain2 = resolve_scope(conn, new_parent)
        if v2 != "ALLOW":
            fok, freason = conn.folder_in_scope(new_parent)
            if fok:
                return (
                    "ALLOW",
                    f"source in scope; move-destination folder verified: {freason}",
                    f"move {page_id} -> {new_parent}",
                    chain + [(str(new_parent), "folder (verified by query)")],
                )
            return (
                "REFUSE",
                f"move destination out of scope: {reason2}; folder check: {freason}",
                f"move {page_id} -> {new_parent}",
                chain2,
            )
        return (
            "ALLOW",
            "source and move-destination both in scope",
            f"move {page_id} -> {new_parent}",
            chain + chain2,
        )
    return "ALLOW", reason, f"update {page_id}", chain


def _derive_space(conn, args, result, target):
    """createConfluencePage needs a spaceId: take it from the proven parent, else from a page under an allowed root (a folder
    parent 404s). Returns True when args now carry it."""
    parent = args.get("parentId")
    ok, pobj = conn.get_page(parent)
    if not ok:
        for root in conn.cfg["allowed_roots"]:
            for pid in sorted(conn.descendant_ids(root, "page") or set())[:3]:
                ok, pobj = conn.get_page(pid)
                if ok and isinstance(pobj, dict) and pobj.get("spaceId"):
                    result["space_from"] = (
                        f"page {pid} under an allowed root (parent {parent} is a folder)"
                    )
                    break
            if ok:
                break
    if not ok or not isinstance(pobj, dict) or not pobj.get("spaceId"):
        result["verdict"] = "WRITE_FAILED"
        result["write_error"] = f"could not derive spaceId from parent {parent}: {pobj}"
        return False
    args["spaceId"] = pobj["spaceId"]
    result["derived_space_id"] = pobj["spaceId"]
    return True


def run(mode, tool, args, cfg=None, conn=None):
    """The whole guard for one call. Returns (result dict, exit code). `conn` is injectable for tests."""
    cfg = cfg or load_config()
    args = dict(args)
    args.setdefault("cloudId", cfg["cloud_id"])
    if conn is None:
        if not cfg["allowed_roots"] or not cfg["endpoint"]:
            return {
                "verdict": "REFUSE",
                "reason": "the guard has no allowed roots or no endpoint configured",
            }, 3
        if _token_provider is None:
            return {"verdict": "REFUSE", "reason": "no sign-in slot token provider plugged in"}, 3
        try:
            conn = Connector(cfg, _token_provider())
        except Exception as e:  # noqa: BLE001 - any session failure refuses the write
            return {"verdict": "REFUSE", "reason": f"connector session failed: {e}"}, 3
    verdict, reason, target, chain = validate(conn, tool, args)
    result = {
        "verdict": verdict,
        "mode": mode,
        "tool": tool,
        "target": target,
        "reason": reason,
        "chain": chain,
    }
    _log(cfg, verdict, tool, target, reason)
    if verdict != "ALLOW":
        return result, 3
    if mode == "check":
        result["note"] = "check-only: no write performed"
        return result, 0
    if (
        tool == "createConfluencePage"
        and not args.get("spaceId")
        and not _derive_space(conn, args, result, target)
    ):
        _log(cfg, "WRITEERR", tool, target, result["write_error"])
        return result, 4
    out = conn.call(tool, args)
    # A tool level failure is result.isError with the text in content[0].text; a success carries the page as a JSON string
    # there. NEVER fall back to the raw JSON-RPC envelope (that yields a bogus "success").
    tool_result = out.get("result") if isinstance(out, dict) else None
    text = None
    if isinstance(tool_result, dict):
        try:
            text = tool_result["content"][0]["text"]
        except (KeyError, IndexError, TypeError):
            text = None
    is_error = bool(isinstance(tool_result, dict) and tool_result.get("isError"))
    written = None
    if text is not None:
        try:
            written = json.loads(text)
        except (ValueError, TypeError):
            written = {"error": True, "message": str(text)}
    if is_error or written is None or (isinstance(written, dict) and written.get("error")):
        msg = (
            (written.get("message", "") or str(text or out)[:300])
            if isinstance(written, dict)
            else str(text or out)[:300]
        )
        result["verdict"] = "WRITE_FAILED"
        result["write_error"] = msg[:400]
        _log(cfg, "WRITEERR", tool, target, result["write_error"])
        return result, 4
    result["written"] = (
        {k: written.get(k) for k in ("id", "title", "status", "version")}
        if isinstance(written, dict)
        else written
    )
    _log(cfg, "WROTE", tool, target, str(result["written"]))
    return result, 0


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    if len(argv) < 4 or argv[1] not in ("check", "execute"):
        print("usage: docs_write_guard.py {check|execute} <tool> '<json-args>'", file=sys.stderr)
        return 2
    try:
        args = json.loads(argv[3])
    except json.JSONDecodeError as e:
        print(json.dumps({"verdict": "REFUSE", "reason": f"bad json args: {e}"}))
        return 2
    result, code = run(argv[1], argv[2], args)
    print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
