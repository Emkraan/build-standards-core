"""The runtime slot: starting an agent session for an item and following it (Tackle now, Discuss, the session list).

The core owns the store, the prompt, the routes and the states the app shows. What a session is, and how one starts, is the consumer's: a
command (`OPSCENTER_RUNTIME_CMD`, a JSON list or a shell-split string, default none). With no command every start answers 501 with
"no runtime configured" and the session list is empty, so the pages render and say so.

Command contract (arguments after the command; JSON on stdout; 60 s timeout, nonzero exit is a failure):
  start '<json>'    in:  {fp, kind (item, jira, pr, doc), title, prompt, context, mode}
                    out: {session_id, pid?, log?, surface?}
  prompt '<json>'   in:  {fp, session_id, text}   out: {}   (optional: sends the owner's line into the running session; a runtime without it answers 501)
  status '<json>'   in:  {session_ids: [...]}   (optional; a command that cannot answer exits nonzero and the stored states stay)
                    out: {session_id: {state (running|finished|failed), last_active (ISO), archived}}

Store `<state>/dashboard/action-tackle.json`: {fp: {title, session, pid, state, resolved?, archived?, started, log, surface, session_id,
has_context, error?, ticket?, last_active?}}. State is launching, running, finished, failed or resolved. The owner or the session resolves
with POST /api/tackle/resolve {fp, summary}; the prompt tells the session how (`OPSCENTER_PUBLIC_URL`, default the local server).
A start for an fp whose session is live returns that session instead of a second one.
"""

import datetime as dt
import hashlib
import json
import os
import secrets
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


class Busy(RuntimeError):
    """Another launch is still running past the hold time: the caller retries, nothing was started."""

    status = 429


class Refused(RuntimeError):
    status = 403


def hold_s():
    """How long a start waits for the one launch in flight (OPSCENTER_LAUNCH_HOLD_S, default 90). Launches go one at a time."""
    try:
        return max(1.0, float(os.environ.get("OPSCENTER_LAUNCH_HOLD_S") or 90))
    except ValueError:
        return 90.0


def _hash(token):
    return hashlib.sha256(str(token).encode()).hexdigest()


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
    # The claim token's hash never leaves the store.
    return dict({k: v for k, v in rec.items() if k != "claim_hash"}, live=_live(rec))


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


def _prompt(kind, fp, title, item, context, claim=""):
    base = os.environ.get("OPSCENTER_PUBLIC_URL") or "http://127.0.0.1:8766"
    lines = [f"Work this {kind} item: {title}", f"Reference: {fp}"]
    summary = (item or {}).get("summary") or (item or {}).get("description")
    if summary:
        lines.append(str(summary)[:2000])
    if context:
        lines.append(f"Owner's note: {context}")
    lines.append(
        f'Report progress now and then: POST {base}/api/tackle/report with {{"fp": "{fp}", "claim": "{claim}", "text": "<one line>"}}.'
    )
    lines.append(
        f'When you have finished, record it: POST {base}/api/tackle/resolve with {{"fp": "{fp}", "claim": "{claim}", "summary": "<one or two sentences>"}}.'
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
    # One launch at a time. A second start waits up to the hold time for the one in flight, then gives up with Busy and starts nothing.
    if not _lock.acquire(timeout=hold_s()):
        raise Busy("another launch is still starting, try again shortly")
    try:
        store = _load()
        cur = store.get(fp)
        if cur and _live(cur):
            return _public(cur)
        # The claim token binds a resolve to this item: the session is told it in its prompt, the store keeps only its hash.
        claim = secrets.token_urlsafe(18)
        rec = {
            "title": title,
            "session": "",
            "pid": 0,
            "state": "launching",
            "started": _now(),
            "log": "",
            "surface": "desktop",
            "has_context": bool(context),
            "claim_hash": _hash(claim),
        }
        try:
            out = _run(
                cmd,
                "start",
                {
                    "fp": fp,
                    "kind": kind,
                    "title": title,
                    "prompt": _prompt(kind, fp, title, item, context, claim),
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
    finally:
        _lock.release()
    return _public(rec)


def _check_claim(rec, claim, owner):
    """A record started with a claim token is resolved or reported on only with that token, or by the owner from the app (owner true)."""
    want = rec.get("claim_hash")
    if want and not owner and (not claim or not secrets.compare_digest(_hash(claim), want)):
        raise Refused("the claim token does not match this item")


def resolve(fp, summary="", claim=None, owner=False):
    fp = str(fp or "").strip()
    with _lock:
        store = _load()
        rec = store.get(fp)
        if not rec:
            raise KeyError(f"no session for {fp}")
        _check_claim(rec, claim, owner)
        rec.update(state="resolved", resolved=str(summary or "")[:500], last_active=_now())
        _save(store)
    return _public(rec)


def bind(fp, session_id, surface=None):
    """Bind a session the runtime opened on its own (a desktop session the owner started from the item) to the item, so the list follows it."""
    fp, session_id = str(fp or "").strip(), str(session_id or "").strip()
    if not fp or not session_id:
        raise ValueError("fp and session_id are required")
    with _lock:
        store = _load()
        rec = store.get(fp)
        if not rec:
            raise KeyError(f"no session for {fp}")
        rec.update(session=session_id, session_id=session_id, state="running", last_active=_now())
        if surface:
            rec["surface"] = str(surface)[:30]
        _save(store)
    return _public(rec)


def report(fp, text, claim=None, owner=False, pct=None):
    """A progress line from the session. The last five are kept; a record without a claim token takes none from a stranger."""
    fp = str(fp or "").strip()
    text = " ".join(str(text or "").split())[:300]
    if not text:
        raise ValueError("text is required")
    with _lock:
        store = _load()
        rec = store.get(fp)
        if not rec:
            raise KeyError(f"no session for {fp}")
        _check_claim(rec, claim, owner)
        entry = {"at": _now(), "text": text}
        if isinstance(pct, int) and not isinstance(pct, bool) and 0 <= pct <= 100:
            entry["pct"] = pct
        rec["reports"] = ([entry] + list(rec.get("reports") or []))[:5]
        rec["last_active"] = entry["at"]
        _save(store)
    return _public(rec)


def prompt(fp, text):
    """Send a line of the owner's into the running session through the runtime's optional `prompt` verb. A runtime without it answers 501."""
    cmd = command()
    if cmd is None:
        raise NoRuntime(NO_RUNTIME)
    fp = str(fp or "").strip()
    text = str(text or "").strip()[:4000]
    if not text:
        raise ValueError("text is required")
    store = _load()
    rec = store.get(fp)
    if not rec or not _live(rec):
        raise KeyError(f"no live session for {fp}")
    try:
        _run(
            cmd,
            "prompt",
            {"fp": fp, "session_id": rec.get("session_id") or rec.get("session"), "text": text},
        )
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        raise NoRuntime(f"the runtime could not take the prompt: {str(exc)[:200]}") from None
    return {"fp": fp, "sent": True}


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
    return resolve(
        payload.get("fp"),
        payload.get("summary"),
        payload.get("claim"),
        payload.get("owner") is True,
    )


def post_bind(payload):
    return bind(payload.get("fp"), payload.get("session_id"), payload.get("surface"))


def post_report(payload):
    return report(
        payload.get("fp"),
        payload.get("text"),
        payload.get("claim"),
        payload.get("owner") is True,
        payload.get("pct"),
    )


def post_prompt(payload):
    return prompt(payload.get("fp"), payload.get("text"))


if __name__ == "__main__":
    print(json.dumps(sessions(), indent=1))
