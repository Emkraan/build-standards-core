"""
proposal_rewrite_gate.py - wake gate for "rewrite sent-back proposals".

Purpose: When the owner sends a staged docs proposal back for rewrite on the Knowledge page, the ops
         center writes the note to <state_dir>/dashboard/proposal-feedback.json. This gate runs every
         minute and wakes the rewrite agent only when an open send-back exists, so the rewrite starts
         within a minute and an idle minute costs nothing.

         It claims each entry (status rewriting, claimed_at) before waking so two ticks never rewrite the
         same proposal. A claim older than 20 minutes without a result is treated as a failed run and
         re-offered.
Config:  OPSCENTER_STATE_DIR (default ~/.opscenter/state).
"""

import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gatelib import gate_silent, wake  # noqa: E402

DASH = os.path.join(
    os.environ.get("OPSCENTER_STATE_DIR") or os.path.expanduser("~/.opscenter/state"), "dashboard"
)
FEEDBACK = os.path.join(DASH, "proposal-feedback.json")
PROPOSALS = os.path.join(DASH, "docs-proposals.json")
STALE_CLAIM = dt.timedelta(minutes=20)


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def main():
    now = dt.datetime.now(dt.timezone.utc)
    fb = load(FEEDBACK, {"feedback": {}})
    props = {p.get("fp"): p for p in load(PROPOSALS, {}).get("proposals", [])}
    todo = []
    for fp, e in fb.get("feedback", {}).items():
        st = e.get("status")
        p = props.get(fp)
        if not p or e.get("body_sha") != p.get("body_sha"):
            continue  # proposal gone, or already re-staged
        if st == "rewriting":
            try:
                claimed = dt.datetime.fromisoformat(e.get("claimed_at", "").replace("Z", "+00:00"))
            except ValueError:
                claimed = now - STALE_CLAIM
            if now - claimed < STALE_CLAIM:
                continue
        elif st != "open":
            continue
        e["status"] = "rewriting"
        e["claimed_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        todo.append((fp, p, e))
    if not todo:
        gate_silent()
    tmp = FEEDBACK + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(fb, f, indent=2, ensure_ascii=True)
        f.write("\n")
    os.replace(tmp, FEEDBACK)
    lines = ["SEND-BACKS TO REWRITE NOW (claimed by the gate, status rewriting):"]
    for fp, p, e in todo:
        lines.append(
            json.dumps(
                {
                    "fp": fp,
                    "title": p.get("target_title"),
                    "kind": p.get("kind"),
                    "target_id": p.get("target_id"),
                    "parent_id": p.get("parent_id"),
                    "new_parent_id": p.get("new_parent_id"),
                    "origin": p.get("origin", "nightly"),
                    "ticket": p.get("ticket"),
                    "body_file": os.path.join(DASH, "proposals", fp + ".body"),
                    "note_from_owner": e.get("reason"),
                }
            )
        )
    wake(*lines)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # fail open: a gate error must not swallow a send-back
        wake(
            f"PROPOSAL REWRITE GATE ERROR ({exc}). Read dashboard/proposal-feedback.json in the state dir yourself and handle every open entry."
        )
