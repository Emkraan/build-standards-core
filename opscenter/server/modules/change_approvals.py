"""
change_approvals.py
Purpose: Approve or decline a change that waits on the owner, with a live switch that decides whether the decision is really written or only logged
         as a dry run (cutover comment capability 2). The core owns the decision log, the switch and the rules; the consumer owns the write, as a
         command. Nothing is written to a change system until the owner turns the switch on, and the switch starts off.
Date:    2026-11-21
Store:   <state>/dashboard/change-approvals.json   {"live": false, "switched": {"at", "live"}, "decisions": [{key, decision, note, at, mode, ok, detail}]}
         the last 200 decisions; written atomically under a lock, never edited in place.
Command: OPSCENTER_APPROVALS_CMD (a JSON list or a shell split string, default none). `decide '<json {key, decision, note}>'` prints JSON `{ok, detail?}`
         (60 s timeout, a nonzero exit or a non JSON answer is a failure). With no command the log still works as a dry run and the switch cannot go live (409).
Rules:   a key looks like ABC-123; a decision is approve or decline; every write needs `confirm: true`; going live needs `confirm: true` and a command.
         A live decision first asks the tracker (when it is on) whether the change still waits on the owner and refuses (409) when it does not or cannot be read,
         so a change already decided elsewhere is never decided twice. A dry run records what would have been done and calls nothing.
Routes:  GET  /api/approvals/queue     {live, can_go_live, decisions (newest 50), error?}
         POST /api/approvals/decide    {key, decision, note?, confirm: true} -> {key, decision, mode, ok, detail}
         POST /api/approvals/switch    {live, confirm: true} -> {live}
"""

import datetime as dt
import fcntl
import json
import os
import re
import shlex
import subprocess

import stores

KEY = re.compile(r"^[A-Z][A-Z0-9]{1,9}-\d{1,7}$")
KEEP = 200
SHOW = 50
TIMEOUT_S = 60


class Refused(Exception):
    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


def _path():
    return stores.dash() / "change-approvals.json"


def _now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def command():
    raw = (os.environ.get("OPSCENTER_APPROVALS_CMD") or "").strip()
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
    d = stores._load_json(_path(), {})
    return d if isinstance(d, dict) else {}


def _locked(fn):
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p.with_suffix(".lock"), "w") as lock:  # noqa: PTH123
        fcntl.flock(lock, fcntl.LOCK_EX)
        d = _load()
        d.setdefault("live", False)
        d.setdefault("decisions", [])
        out = fn(d)
        d["decisions"] = d["decisions"][:KEEP]
        stores._write_json(p, d)
        return out


def queue():
    d = _load()
    return {
        "live": bool(d.get("live")),
        "can_go_live": command() is not None,
        "decisions": (d.get("decisions") or [])[:SHOW],
    }


def switch(payload):
    if payload.get("confirm") is not True:
        raise ValueError("confirm must be true")
    want = payload.get("live")
    if not isinstance(want, bool):
        raise ValueError("live must be true or false")
    if want and command() is None:
        raise Refused("no approvals command is configured, so the switch cannot go live", 409)

    def go(d):
        d["live"] = want
        d["switched"] = {"at": _now(), "live": want}
        return {"live": want}

    return _locked(go)


def _still_waiting(key):
    """True when the tracker still lists the change as waiting on the owner; None when the tracker is off (nothing to check); raises when it cannot be read."""
    if os.environ.get("OPSCENTER_TRACKER", "").strip().lower() in ("", "0", "false", "off", "no"):
        return None
    import work

    pending = (work.approvals() or {}).get("pending") or []
    return any(r.get("key") == key for r in pending)


def _apply(cmd, key, decision, note):
    p = subprocess.run(  # noqa: S603
        [*cmd, "decide", json.dumps({"key": key, "decision": decision, "note": note})],
        capture_output=True,
        text=True,
        timeout=TIMEOUT_S,
    )
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or f"exit {p.returncode}").strip()[:200])
    out = json.loads(p.stdout.strip().splitlines()[-1] if p.stdout.strip() else "")
    return bool(out.get("ok")), str(out.get("detail") or "")[:200]


def decide(payload):
    if payload.get("confirm") is not True:
        raise ValueError("confirm must be true")
    key, decision = str(payload.get("key") or ""), str(payload.get("decision") or "")
    if not KEY.match(key):
        raise ValueError("key must look like ABC-123")
    if decision not in ("approve", "decline"):
        raise ValueError("decision must be approve or decline")
    note = " ".join(str(payload.get("note") or "").split())[:300]
    live = bool(_load().get("live"))
    mode, ok, detail = "dry_run", True, f"would {decision} {key}"
    if live:
        cmd = command()
        if cmd is None:
            raise Refused("the switch is live but no approvals command is configured", 409)
        try:
            waiting = _still_waiting(key)
        except Exception as exc:  # noqa: BLE001 - fail closed: an unreadable tracker never lets a write through
            raise Refused(
                f"could not check that {key} still waits on you ({type(exc).__name__})", 409
            ) from None
        if waiting is False:
            raise Refused(f"{key} no longer waits on your approval", 409)
        mode = "live"
        try:
            ok, detail = _apply(cmd, key, decision, note)
        except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
            ok, detail = False, f"the approvals command failed: {str(exc)[:160]}"
    entry = {
        "key": key,
        "decision": decision,
        "note": note,
        "at": _now(),
        "mode": mode,
        "ok": ok,
        "detail": detail,
    }

    def go(d):
        d["decisions"].insert(0, entry)
        return entry

    return _locked(go)
