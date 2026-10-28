"""
cron_catalog_gate.py

Purpose: Wake gate for self-correcting scheduled job names and descriptions. Runs the catalog scan tool
         and wakes the model only when an enabled job has a name outside "<Area> - <what it does>" or no
         catalog description. Quiet nights cost no model run.
Config:  CRON_CATALOG_TOOL (the scan tool, default ~/.opscenter/scripts/cron-catalog-fix/catalog_fix.py).
         Findings are written to <GATE_STATE_DIR>/cron-catalog-findings.json.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gatelib  # noqa: E402
from gatelib import clear_failures, failure_should_wake, gate_silent, run, wake  # noqa: E402

NAME = "cron-catalog"
TOOL = os.environ.get("CRON_CATALOG_TOOL") or os.path.expanduser(
    "~/.opscenter/scripts/cron-catalog-fix/catalog_fix.py"
)


def out_path():
    return os.path.join(gatelib.STATE_DIR, "cron-catalog-findings.json")


def main():
    rc, out, err = run([sys.executable, TOOL, "scan"], timeout=60)
    try:
        data = json.loads(out.strip().splitlines()[-1]) if out.strip() else {}
    except ValueError:
        data = {"ok": False, "error": f"unparseable scan output: {out[:200]}"}
    if rc != 0 or not data.get("ok"):
        detail = data.get("error") or (err or out)[:300]
        if failure_should_wake(NAME, detail, backoff_first=3, cooldown=86400):
            wake(
                f"[CRON-CATALOG GATE ALERT] The job scan is failing: {detail}",
                "Reply with one line naming the error. Do not rename or describe anything this run.",
            )
        gate_silent()
    clear_failures(NAME)
    found = data["findings"]
    if not found:
        gate_silent()
    out = out_path()
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(data, f, indent=2)
    wake(
        "[CRON-CATALOG GATE] %d enabled job(s) need a name or description fix." % len(found),  # noqa: UP031
        "Areas already in use: {}".format(", ".join(data["areas"])),
        f"Full findings (prompt, script path, reasons) are in {out}. Read it, do not re-run the scan.",
        "Jobs: {}".format(
            " | ".join(
                "{} {!r} ({})".format(x["id"], x["name"], "+".join(x["reasons"])) for x in found
            )
        ),
    )


if __name__ == "__main__":
    main()
