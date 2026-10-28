"""The runtime slot: starting an agent session for an item and following it (Tackle now, Discuss, the session list).

The core owns the store, the prompt, the routes and the states the app shows. What a session is, and how one starts, is the consumer's: a
command (`OPSCENTER_RUNTIME_CMD`, a JSON list or a shell-split string, default none). With no command every start answers 501 with
"no runtime configured" and the session list is empty, so the pages render and say so.

Command contract (arguments after the command; JSON on stdout; 60 s timeout, nonzero exit is a failure):
  start '<json>'    in:  {fp, kind (item, jira, pr, doc), title, prompt, context, mode}
                    out: {session_id, pid?, log?, surface?}
  status '<json>'   in:  {session_ids: [...]}   (optional; a command that cannot answer exits nonzero and the stored states stay)
                    out: {session_id: {state (running|finished|failed), last_active (ISO), archived}}

Store `<state>/dashboard/action-tackle.json`: {fp: {title, session, pid, state, resolved?, archived?, started, log, surface, session_id,
has_context, error?, ticket?, last_active?}}. State is launching, running, finished, failed or resolved. The owner or the session resolves
with POST /api/tackle/resolve {fp, summary}; the prompt tells the session how (`OPSCENTER_PUBLIC_URL`, default the local server).
A start for an fp whose session is live returns that session instead of a second one.
"""

import datetime as dt
import json
import os
import shlex
import subprocess
import threading
import time

import stores

TIMEOUT_S = 60
LIVE_WINDOW_S = 72 * 3600
NO_RUNTIME = "no runtime configured"

_lock = threading.Lock()


class NoRuntime(RuntimeError):
    status = 501


def _store():
    return stores.dash() / "action-tackle.json"


def _now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def command():
    raw = (os.environ.get("OPSCENTER_RUNTIME_CMD") or "").strip()
    if not raw:
        return None
    if raw.startswith("["):
        try:
            cmd = json.loads(raw)
        except ValueError:
            return None
        return [str(c) for c in cmd] if isinstance(cmd, list) and cmd else None
    return shlex.split(raw) or None


def _load():
    return stores._load_json(_store(), {}) or {}


def _save(sessions):
    stores._write_json(_store(), sessions)


def _run(cmd, verb, payload):
    proc = subprocess.run(
        [*cmd, verb, json.dumps(payload)],
        capture_output=True,
        text=True,
        timeout=TIMEOUT_S,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()[:300])
    out = json.loads(proc.stdout)
    if not isinstance(out, dict):
        raise ValueError("the runtime command did not return a JSON object")
    return out


def _epoch(iso):
    try:
        return dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _live(rec, now=None):
    if rec.get("archived") or rec.get("state") not in ("launching", "running"):
        return False
    last = _epoch(rec.get("last_active") or rec.get("started")) or 0
    return (now or time.time()) - last < LIVE_WINDOW_S


def _public(rec):
    return dict(rec, live=_live(rec))


def sessions():
    """The session list: the store, refreshed from the runtime's status when it can answer. {sessions, runtime}."""
    cmd = command()
    with _lock:
        store = _load()
        ids = [
            r["session_id"]
            for r in store.values()
            if r.get("session_id") and r.get("state") in ("launching", "running")
        ]
        if cmd and ids:
            try:
                status = _run(cmd, "status", {"session_ids": ids})
            except (RuntimeError, ValueError, OSError, subprocess.SubprocessError):
                status = {}
            changed = False
            for rec in store.values():
                st = (
                    status.get(rec.get("session_id"))
                    if isinstance(status.get(rec.get("session_id")), dict)
                    else None
                )
                if st:
                    for k_out, k_in in (
                        ("state", "state"),
                        ("last_active", "last_active"),
                        ("archived", "archived"),
                    ):
                        if st.get(k_in) is not None and st.get(k_in) != rec.get(k_out):
                            rec[k_out] = st[k_in]
                            changed = True
            if changed:
                _save(store)
    runtime = {"configured": cmd is not None}
    if cmd is None:
        runtime["state"] = NO_RUNTIME
    return {"sessions": {fp: _public(r) for fp, r in store.items()}, "runtime": runtime}


def _prompt(kind, fp, title, item, context):
    base = os.environ.get("OPSCENTER_PUBLIC_URL") or "http://127.0.0.1:8766"
    lines = [f"Work this {kind} item: {title}", f"Reference: {fp}"]
    summary = (item or {}).get("summary") or (item or {}).get("description")
    if summary:
        lines.append(str(summary)[:2000])
    if context:
        lines.append(f"Owner's note: {context}")
    lines.append(
        f'When you have finished, record it: POST {base}/api/tackle/resolve with {{"fp": "{fp}", "summary": "<one or two sentences>"}}.'
    )
    return "\n".join(lines)


def start(fp, kind="item", title="", item=None, context="", mode=None):
    """Start (or return the live) session for fp. Raises NoRuntime when no command is configured."""
    cmd = command()
    if cmd is None:
        raise NoRuntime(NO_RUNTIME)
    fp = str(fp or "").strip()
    if not fp:
        raise ValueError("fp is required")
    title = title or (item or {}).get("title") or fp
    with _lock:
        store = _load()
        cur = store.get(fp)
        if cur and _live(cur):
            return _public(cur)
        rec = {
            "title": title,
            "session": "",
            "pid": 0,
            "state": "launching",
            "started": _now(),
            "log": "",
            "surface": "desktop",
            "has_context": bool(context),
        }
        try:
            out = _run(
                cmd,
                "start",
                {
                    "fp": fp,
                    "kind": kind,
                    "title": title,
                    "prompt": _prompt(kind, fp, title, item, context),
                    "context": context,
                    "mode": mode,
                },
            )
            rec.update(
                session=str(out.get("session_id") or ""),
                session_id=str(out.get("session_id") or ""),
                pid=int(out.get("pid") or 0),
                log=str(out.get("log") or ""),
                state="running",
                last_active=_now(),
            )
            if out.get("surface"):
                rec["surface"] = out["surface"]
        except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
            rec.update(state="failed", error=str(exc)[:300])
        if item and (item.get("refs") or item.get("key")):
            rec["ticket"] = item.get("key") or (item.get("refs") or [None])[0]
        store[fp] = rec
        _save(store)
    return _public(rec)


def resolve(fp, summary=""):
    fp = str(fp or "").strip()
    with _lock:
        store = _load()
        rec = store.get(fp)
        if not rec:
            raise KeyError(f"no session for {fp}")
        rec.update(state="resolved", resolved=str(summary or "")[:500], last_active=_now())
        _save(store)
    return _public(rec)


# ---- the routes' entry points -----------------------------------------------------------------------------------------------


def get():
    return sessions()


def _need():
    if command() is None:
        raise NoRuntime(NO_RUNTIME)


def post_tackle(payload):
    _need()
    fp = str(payload.get("fp") or "")
    item = stores.find_item(fp)
    if item is None:
        raise KeyError(f"no board item {fp}")
    return start(
        fp,
        "item",
        item.get("title") or "",
        item,
        str(payload.get("context") or ""),
        payload.get("mode"),
    )


def post_jira(payload):
    _need()
    import work

    key = str(payload.get("key") or "")
    item = work.my_open_item(key)
    fp = f"jira-{item['key']}"
    return dict(
        start(
            fp,
            "jira",
            f"{item['key']} {item.get('summary') or ''}".strip(),
            item,
            str(payload.get("context") or ""),
        ),
        fp=fp,
    )


def post_discuss(payload):
    _need()
    repo, pr = str(payload.get("repo") or ""), payload.get("pr")
    if not repo or not str(pr or "").isdigit():
        raise ValueError("repo and a numeric pr are required")
    fp = f"pr-{repo.replace('/', '-')}-{int(pr)}"
    return dict(
        start(fp, "pr", f"{repo}#{int(pr)}", None, str(payload.get("context") or "")), fp=fp
    )


def post_resolve(payload):
    return resolve(payload.get("fp"), payload.get("summary"))


if __name__ == "__main__":
    print(json.dumps(sessions(), indent=1))
