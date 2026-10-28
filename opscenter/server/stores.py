"""The two small stores the server writes itself: the action handled store and the approvals inbox.

handled   <state>/dashboard/action-handled.json   {"handled": {fp: {act, at, until?, item?, via?, summary?}}}. The app writes through on every
          Resolve, Snooze and Ignore; the analysis reads it to stop re-emitting what the owner handled. Last writer wins per fp, which
          matches the single user loopback model. act "restore" deletes the fp. Every act snapshots the item so Completed and Dismissed
          can show a title after the analysis stops emitting it.
inbox     <state>/dashboard/approve-inbox.jsonl     decisions {fp, act approved|rejected, body_sha, title, reason?} appended under the
          same lock the applier (lanes/queued_approvals.py) takes. act "changes" (send back for a rewrite) never goes to the inbox, because
          the applier treats any act other than rejected as an approval: it goes to proposal-feedback.json, and an optional rewrite
          command (OPSCENTER_REWRITE_CMD, a JSON list) is started detached so the rewrite runs now.
"""

import datetime as dt
import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path

STATE = Path(
    os.environ.get("OPSCENTER_STATE_DIR")
    or Path(os.environ.get("OPSCENTER_ROOT") or Path.home() / ".opscenter") / "state"
)


def dash():
    return STATE / "dashboard"


def _now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(p, data):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(p)


# ---------------------------------------------------------------- handled
def load_handled():
    d = _load_json(dash() / "action-handled.json", {})
    h = d.get("handled") if isinstance(d, dict) else None
    return h if isinstance(h, dict) else {}


def find_item(fp):
    """The board item with this fingerprint, from the served board (OPSCENTER_SERVED_BOARD, default <state>/public-data/action-center.json)."""
    p = os.environ.get("OPSCENTER_SERVED_BOARD") or str(
        STATE / "public-data" / "action-center.json"
    )
    for it in (_load_json(p, {}) or {}).get("items") or []:
        if isinstance(it, dict) and it.get("fp") == fp:
            return it
    return None


def merge_handled(entry):
    """Apply one handled decision {fp, act, at?, until?, summary?, via?} and persist; returns the handled map."""
    fp = entry.get("fp")
    handled = load_handled()
    if not fp:
        return handled
    act = entry.get("act", "resolved")
    if act == "restore":
        handled.pop(fp, None)
    else:
        rec = {"act": act, "at": entry.get("at") or _now()}
        if entry.get("until"):
            rec["until"] = entry["until"]
        prev = handled.get(fp) or {}
        it = find_item(fp) or prev.get("item")
        if it:
            # key, refs and cids let engine/handled.py match a re-keyed or reworded repeat to this decision.
            rec["item"] = {
                k: it.get(k)
                for k in (
                    "key",
                    "priority",
                    "title",
                    "why",
                    "action",
                    "owner",
                    "refs",
                    "sources",
                    "cids",
                )
            }
        if act == "resolved":
            if prev.get("session_id"):
                rec["session_id"] = prev["session_id"]
            rec["via"] = entry.get("via") or "ops-center"
            if entry.get("summary") or prev.get("summary"):
                rec["summary"] = (entry.get("summary") or prev.get("summary"))[:2000]
        handled[fp] = rec
    _write_json(dash() / "action-handled.json", {"handled": handled})
    return handled


# ---------------------------------------------------------------- approvals inbox
def _trigger_rewrite():
    try:
        cmd = json.loads(os.environ.get("OPSCENTER_REWRITE_CMD") or "[]")
    except ValueError:
        cmd = []
    if not cmd or not isinstance(cmd, list):
        return
    try:
        subprocess.Popen(
            [str(a) for a in cmd],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        print(f"rewrite trigger failed: {exc}", file=sys.stderr, flush=True)


def queue_decisions(decisions):
    """Append decisions to the inbox in the shape the applier expects. Returns the number queued."""
    ts = _now()
    wrote = 0
    d = dash()
    changes = [
        x for x in decisions if isinstance(x, dict) and x.get("fp") and x.get("act") == "changes"
    ]
    if changes:
        fb = _load_json(d / "proposal-feedback.json", {"feedback": {}})
        for x in changes:
            reason = str(x.get("reason") or "").strip()[:2000]
            if not reason:
                continue
            fb.setdefault("feedback", {})[x["fp"]] = {
                "title": x.get("title", ""),
                "reason": reason,
                "body_sha": x.get("body_sha", ""),
                "at": ts,
                "status": "open",
            }
            wrote += 1
        _write_json(d / "proposal-feedback.json", fb)
        _trigger_rewrite()
    d.mkdir(parents=True, exist_ok=True)
    # The same lock the applier takes before it rewrites the inbox, so no decision is lost.
    with (
        open(d / ".approve-inbox.lock", "w") as lk,
        open(d / "approve-inbox.jsonl", "a", encoding="utf-8") as f,
    ):
        fcntl.flock(lk, fcntl.LOCK_EX)
        for x in decisions:
            if not isinstance(x, dict) or not x.get("fp") or x.get("act") == "changes":
                continue
            act = x.get("act", "approved")
            if act not in ("approved", "rejected"):
                continue
            rec = {
                "queued_utc": ts,
                "fp": x["fp"],
                "act": act,
                "body_sha": x.get("body_sha", ""),
                "title": x.get("title", ""),
            }
            if act == "rejected" and x.get("reason"):
                rec["reason"] = str(x["reason"]).strip()[:2000]
            f.write(json.dumps(rec) + "\n")
            wrote += 1
    return wrote
