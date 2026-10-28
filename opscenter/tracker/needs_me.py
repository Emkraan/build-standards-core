"""
needs_me.py

Purpose: The tracker hub "Needs me" tab. Lists the owner's active-sprint tickets the nightly sprint close-out could not
         settle on its own (it was unsure the work is done), so they never sit open with nobody deciding. The owner
         answers each one here: Close it (the next close-out closes it, the owner's click is the sign-off) or Keep open
         (stays off this list until the close-out's reason changes). The owner's decisions live in their own file, which
         this module is the only writer of. The close-out reads it and records what it applied in
         sprint-close-state.json, which it alone writes.

Parameters: tracker/params.py (the work tracker adapter), `close_out_cmd` (a command list that starts the close-out job
         now; none means the scheduler's gate picks the decision up on its next tick). NEEDS_ME_STATE and
         NEEDS_ME_DECISIONS override the two files.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "server" / "modules"))
import params  # noqa: E402
import paths  # noqa: E402
import work  # noqa: E402

STATE = Path(os.environ.get("NEEDS_ME_STATE", str(paths.state_dir() / "sprint-close-state.json")))
DECISIONS = Path(
    os.environ.get("NEEDS_ME_DECISIONS", str(paths.dashboard_dir() / "needs-me-decisions.json"))
)
DECISION_KINDS = ("close", "keep")
CLOSE_OUT_CMD = [
    str(a) for a in params.get("close_out_cmd", [])
]  # starts the nightly close-out now (optional)
NOTE_MAX = 1000
_LOCK = threading.Lock()
_HELD_DATE = re.compile(r"^(?:held|needs me)\s+(\d{4}-\d{2}-\d{2})\s*:?\s*", re.I)


def _now():
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _read_json(path, default):
    try:
        with open(path) as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".jnm-")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:  # noqa: SIM105
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _ask(key, rec):
    """The open question for one ticket, or None when the close-out is not asking the owner.

    The close-out writes tickets[KEY].needs_me = {question, since}. A ticket that is simply
    not done yet (not started, PR still open) carries no needs_me and never lists here."""
    nm = rec.get("needs_me")
    if not isinstance(nm, dict) or not str(nm.get("question") or "").strip():
        return None
    since = str(nm.get("since") or "")
    if not since:
        m = _HELD_DATE.match(str(rec.get("disposition") or ""))
        since = m.group(1) if m else ""
    return {"question": str(nm["question"]).strip(), "since": since[:10]}


def _days(since):
    try:
        d = datetime.date.fromisoformat(since)
    except ValueError:
        return None
    return max(0, (datetime.date.today() - d).days)


def items(fresh=False):
    """GET /api/tracker/needs-me. Unknown never hides: when the live sprint read fails the
    asks still list (live_ok false) and the decide handler re-checks at click time."""
    state = _read_json(STATE, {})
    decisions = _read_json(DECISIONS, {})
    tickets = state.get("tickets") or {}
    live, live_ok, live_err = {}, True, ""
    try:
        for it in work.sprint(fresh).get("items") or []:
            if it.get("mine") and it.get("status_category") != "done":
                live[it["key"]] = it
    except work.TrackerError as e:
        live_ok, live_err = False, str(e)
    rows = []
    for key, rec in sorted(tickets.items()):
        ask = _ask(key, rec if isinstance(rec, dict) else {})
        if not ask:
            continue
        if live_ok and key not in live:
            continue  # closed, moved out of the sprint, or reassigned
        dec = decisions.get(key) if isinstance(decisions.get(key), dict) else None
        applied = rec.get("decision_applied") or {}
        if not isinstance(applied, dict):
            applied = {}
        phase = "needs_me"
        if dec and dec.get("question") != ask["question"]:
            dec = None  # the close-out's reason changed since the owner answered: ask again
        if dec and dec.get("decision") == "keep":
            continue
        if dec and dec.get("decision") == "close" and applied.get("at") != dec.get("at"):
            phase = "closing"
        row = live.get(key) or {}
        rows.append(
            {
                "key": key,
                "summary": row.get("summary") or "",
                "status": row.get("status") or "",
                "url": row.get("url") or work.BROWSE + key,
                "question": ask["question"],
                "since": ask["since"],
                "days": _days(ask["since"]),
                "phase": phase,
                "decision": dec,
            }
        )
    rows.sort(key=lambda r: (r["phase"] != "needs_me", -(r["days"] or 0), r["key"]))
    return {
        "generated_utc": _now(),
        "live_ok": live_ok,
        "live_error": live_err,
        "count": sum(1 for r in rows if r["phase"] == "needs_me"),
        "items": rows,
    }


def run_close_out():
    """Fire the close-out job now (next scheduler tick). Its gate sees the owner's unapplied decision and
    wakes the agent, which closes the ticket with a full closure comment. Returns an error text
    or "" so the caller can report a trigger that did not start."""
    if not CLOSE_OUT_CMD:
        return ""  # the scheduler's gate wakes the close-out on the unapplied decision
    try:
        subprocess.Popen(
            CLOSE_OUT_CMD,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        return f"could not start the close-out: {exc}"
    return ""


def decide(key, decision, question, note="", what_if=False):
    """POST /api/tracker/needs-me/decide. decision close|keep|undo. `question` is the ask
    the owner saw on screen: when the close-out rewrote it since, refuse with 409 so the owner decides on
    the current reason. Undo of a decision that is already gone is an idempotent success."""
    key = work._key(key)
    if decision not in DECISION_KINDS + ("undo",):
        raise work.TrackerError("decision must be close, keep or undo", 400)
    if not isinstance(note, str) or len(note) > NOTE_MAX:
        raise work.TrackerError(f"note must be text up to {NOTE_MAX} characters", 400)
    with _LOCK:
        decisions = _read_json(DECISIONS, {})
        if decision == "undo":
            prev = decisions.pop(key, None)
            if not what_if and prev is not None:
                _write_json(DECISIONS, decisions)
            return {"key": key, "decision": None, "already": prev is None, "what_if": what_if}
        rec = (_read_json(STATE, {}).get("tickets") or {}).get(key) or {}
        ask = _ask(key, rec)
        if not ask:
            raise work.TrackerError(f"{key} is not waiting on me", 404)
        if question != ask["question"]:
            raise work.TrackerError("The close-out updated this item. Refresh first.", 409)
        # Re-verify live right before the write: still mine, still open, still in the sprint.
        live = work.sprint(True).get("items") or []
        if not any(
            i.get("key") == key and i.get("mine") and i.get("status_category") != "done"
            for i in live
        ):
            raise work.TrackerError(
                f"{key} is no longer an open item of mine in the active sprint", 409
            )
        entry = {
            "decision": decision,
            "note": note.strip(),
            "question": ask["question"],
            "at": _now(),
        }
        prev = decisions.get(key)
        if isinstance(prev, dict) and all(
            prev.get(k) == entry[k] for k in ("decision", "note", "question")
        ):
            return {"key": key, "decision": prev, "already": True, "what_if": what_if}
        if not what_if:
            decisions[key] = entry
            _write_json(DECISIONS, decisions)
    trigger_error = run_close_out() if decision == "close" and not what_if else ""
    return {
        "key": key,
        "decision": entry,
        "already": False,
        "what_if": what_if,
        "trigger_error": trigger_error,
    }
