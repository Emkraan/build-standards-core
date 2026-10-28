#!/usr/bin/env python3
"""
retro_row_gate.py

Purpose: Wake gate for the retro row drafter. Runs retro_row.py scan, which finds the
         newest retro page and gathers the owner's sprint facts only when the owner's row is blank and no
         draft exists yet. Quiet ticks cost no LLM run.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gatelib import clear_failures, failure_should_wake, gate_silent, run, wake  # noqa: E402

NAME = "retro-row"
TOOL = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tracker", "retro_row.py"
)


def main():
    rc, out, err = run([sys.executable, TOOL, "scan"], timeout=600)
    try:
        data = json.loads(out.strip().splitlines()[-1]) if out.strip() else {}
    except ValueError:
        data = {"ok": False, "error": "unparseable scan output: %s" % out[:200]}  # noqa: UP031
    if rc != 0 or data.get("ok") is False:
        detail = data.get("error") or (err or out)[:300]
        if failure_should_wake(NAME, detail, backoff_first=3, cooldown=86400):
            wake(
                "[RETRO-ROW GATE ALERT] The retro page scan is failing: %s" % detail,  # noqa: UP031
                "Raise one Action Center item (automation_actions.py raise --id retro-row-scan-failing) with the error, then reply [SILENT].",
            )
        gate_silent()
    clear_failures(NAME)
    if not data.get("wake"):
        gate_silent()
    f = data
    t = f["totals"]
    wake(
        "[RETRO-ROW GATE] New retro page with the owner's row blank: %s (page %s, %s)"  # noqa: UP031
        % (data["title"], data["pid"], f["page"]["url"]),
        "Sprint %s (%s to %s). The owner's sprint tickets: %s (%s done, %s open, %s added mid-sprint). Merged PRs: %s."  # noqa: UP031
        % (
            f["sprint"]["name"],
            f["sprint"]["start"],
            f["sprint"]["end"],
            t["tickets"],
            t["done"],
            t["open"],
            t["added_mid_sprint"],
            ", ".join("%s %s" % (k, v) for k, v in t["merged_prs"].items()),  # noqa: UP031
        ),
        "Closures owed (open tickets with merged PR evidence): %s"
        % (", ".join(f["closures_owed"]) or "none"),
        "Rolled over and still open: %s" % (", ".join(f["rolled_over_open"]) or "none"),
        "Full facts file: %s (read it, do not re-run the scan)." % data["path"],  # noqa: UP031
        "Page id for propose: %s" % data["pid"],  # noqa: UP031
    )


if __name__ == "__main__":
    main()
