#!/usr/bin/env python3
"""Move the overlay to the newest core release, if it is behind.

Usage: python3 scripts/update-core.py
Prints the new tag on stdout when files changed (empty when already current), so a workflow or cron
job can open a pull request only when there is something to review. Needs gh with read access to the
core (GH_TOKEN in CI, a signed-in gh on a developer machine). Does no git work itself.
"""

import subprocess
import sys

import corehash as ch

cfg = ch.read_lock()
latest = ch.latest_tag(ch.core_repo())
if latest == cfg.get("ref"):
    sys.exit(0)
subprocess.run(
    [sys.executable, str(ch.ROOT / "scripts" / "sync-core.py"), latest],
    check=True,
    stdout=sys.stderr,
)
print(latest)
