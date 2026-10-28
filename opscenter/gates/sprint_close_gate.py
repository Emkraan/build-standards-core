"""
sprint_close_gate.py

Purpose: Wake gate for the nightly sprint close-out. Runs the sprint evidence scanner once (read only,
         fingerprints not committed) and wakes the agent only when an open ticket of the owner's in the
         active sprint picked up new work evidence since the last committed scan, or when the owner
         answered a Needs me ask on the work tracker page that the close-out has not applied yet. Quiet
         nights cost no model run.
Config:  SPRINT_CLOSE_SCANNER (the scanner script, default ~/.opscenter/scripts/sprint-close-scan.py),
         OPSCENTER_STATE_DIR (default ~/.opscenter/state).
"""

import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gatelib import clear_failures, failure_should_wake, gate_silent, run, wake  # noqa: E402

NAME = "sprint-close"
SCANNER = os.environ.get("SPRINT_CLOSE_SCANNER") or os.path.expanduser(
    "~/.opscenter/scripts/sprint-close-scan.py"
)
ROOT = os.environ.get("OPSCENTER_STATE_DIR") or os.path.expanduser("~/.opscenter/state")
PAYLOAD = os.path.join(ROOT, "sprint-close-payload.json")
STATE = os.path.join(ROOT, "sprint-close-state.json")
DECISIONS = os.path.join(ROOT, "dashboard", "tracker-needs-me.json")


def _load(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}


def pending_decisions(open_keys):
    """The owner's Needs me answers the close-out has not applied yet, for tickets still open."""
    tickets = _load(STATE).get("tickets") or {}
    out = []
    for key, dec in sorted(_load(DECISIONS).items()):
        if not isinstance(dec, dict) or key not in open_keys:
            continue
        rec = tickets.get(key) or {}
        nm = rec.get("needs_me") or {}
        if dec.get("question") != nm.get("question"):
            continue  # answered an older question, the Ops Center asks again
        if (rec.get("decision_applied") or {}).get("at") == dec.get("at"):
            continue
        out.append(dict(dec, key=key))
    return out


def main():
    rc, out, err = run([sys.executable, SCANNER], timeout=900)
    if rc != 0:
        detail = f"scanner rc={rc} {(err or out)[:200]}"
        if failure_should_wake(NAME, detail, backoff_first=2, cooldown=86400):
            wake(
                "[SPRINT-CLOSE GATE ALERT] The sprint evidence scanner is failing.",
                f"Detail: {detail}",
            )
        gate_silent()
    try:
        data = json.loads(out)
    except ValueError as exc:
        detail = f"unparseable scanner output: {exc} :: {out[:200]}"
        if failure_should_wake(NAME, detail, backoff_first=2, cooldown=86400):
            wake("[SPRINT-CLOSE GATE ALERT] Scanner output is not JSON.", f"Detail: {detail}")
        gate_silent()
    if data.get("error"):
        detail = str(data["error"])
        if failure_should_wake(NAME, detail, backoff_first=2, cooldown=86400):
            wake(
                f"[SPRINT-CLOSE GATE ALERT] The tracker read failed: {detail}",
                "Check the tracker connector and the scanner's driver.",
            )
        gate_silent()
    clear_failures(NAME)

    changed = [
        t
        for t in data.get("tickets", [])
        if t["key"] in data.get("fingerprint_changed", []) and not t.get("skip_reason")
    ]
    open_keys = {t["key"] for t in data.get("tickets", []) if not t.get("skip_reason")}
    decided = pending_decisions(open_keys)
    if not changed and not decided:
        gate_silent()
    data["needs_me_decisions"] = decided

    with open(PAYLOAD, "w") as fh:
        json.dump(data, fh, indent=2)
    lines = [
        "[SPRINT-CLOSE GATE] %s - sprint %s, %d ticket(s) with new evidence: %s"  # noqa: UP031
        % (
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            data.get("sprint"),
            len(changed),
            ", ".join(t["key"] for t in changed) or "none",
        ),
        f"Full scan payload: {PAYLOAD} (read it, do not re-run the scanner before deciding).",
        "After every disposition is done, run: {} {} --commit".format("python3", SCANNER),
    ]
    for d in decided:
        lines.append(
            "- OWNER DECISION {}: {} (decided {}){}".format(
                d["key"],
                d.get("decision"),
                d.get("at"),
                (" | owner note: {}".format(d["note"])) if d.get("note") else "",
            )
        )
    for t in changed:
        cands = t.get("candidate_evidence") or []
        lines.append(
            "- %s [%s] %s | commits %d | PRs %d (open %d) | decision lines %d | last disposition: %s%s"  # noqa: UP031
            % (
                t["key"],
                t["status"],
                t["summary"],
                len(t["commits"]),
                len(t["prs"]),
                len(t["open_prs"]),
                len(t["decision_lines"]),
                t.get("last_disposition"),
                (
                    " | POSSIBLE EVIDENCE under other keys (verify, then add to evidence_from or candidate_ignore): {}".format(
                        ", ".join("%s (%d commits)" % (c["key"], c["commits"]) for c in cands)  # noqa: UP031
                    )
                )
                if cands
                else "",
            )
        )
    wake(*lines)


if __name__ == "__main__":
    main()
