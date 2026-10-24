#!/usr/bin/env python3
"""Fail on any byte above 127 in a tracked (or new, unignored) text file: em dashes, curly quotes, NBSP,
arrows. The same rule and the same file selection as the overlay's `core-ci.py ascii`
(pr-review-and-merge.md 1.19): every text file, binaries (a NUL byte in the first 8 KiB), synced copies
and lockfiles skipped. The core narrows nothing and records no exception."""

import importlib.util
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "core_ci", ROOT / "templates" / "overlay" / "scripts" / "core-ci.py"
)
core_ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core_ci)

out = subprocess.run(
    ["git", "ls-files", "-co", "--exclude-standard", "-z"],
    capture_output=True,
    text=True,
    cwd=ROOT,
    check=True,
).stdout
os.chdir(ROOT)
files, skipped = core_ci.ascii_candidates([f for f in out.split("\0") if f], root=ROOT)
hits = core_ci.ascii_hits(files)
for f, i in hits:
    print(f"::error file={f},line={i}::non-ASCII character")
print(f"check-ascii: {len(files)} text file(s), {skipped} skipped, {len(hits)} hit(s)")
sys.exit(1 if hits else 0)
