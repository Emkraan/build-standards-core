#!/usr/bin/env python3
"""Fail if the synced copies were edited by hand or no longer match the lock.

Default (offline): recompute the content hash of standards-core/ and tokens-core/ and compare it
with content_sha256 in standards.lock. Needs no network, no gh and no secret.

targets.map (optional): every listed destination must equal its synced copy, so a consumer cannot
drift from the core by editing a generated file. Fix by changing the core and syncing, not by hand.

--latest: print the pinned release, the latest core release and the command to move up. Needs gh.
Exit 0 when current, 3 when behind. Not part of CI by default.

--remote: also clone the core at the pinned release and compare file by file. Needs gh (locally) or
GH_TOKEN (in CI) with read access to the core. The release is found by its tag (ref=), and the pinned
commit is only a hint: a rewritten core history gives the tag a new commit id, so the comparison is by
tag and content, never by a commit id that may no longer exist.
"""

import filecmp
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

import corehash as ch

cfg = ch.read_lock()
bad = []

# The lock must not name the source: an account or repo name in a consumer is a leak.
lock_body = "".join(ln for ln in ch.LOCK.read_text().splitlines(True) if not ln.startswith("#"))
if "repo" in cfg or re.search(r"github\.com", lock_body):
    bad.append(
        "standards.lock names the core source; run scripts/sync-core.py, which rewrites it without"
    )

if "--latest" in sys.argv:
    latest = ch.latest_tag(ch.core_repo())
    pinned = cfg.get("ref")
    if latest == pinned:
        print(f"pinned {pinned}, latest {latest}: current")
        sys.exit(0)
    print(f"pinned {pinned}, latest {latest}, run sync-core.py {latest}")
    sys.exit(3)

want = cfg.get("content_sha256")
if not want:
    print(
        "core sync: standards.lock has no content_sha256 (older lock); run scripts/sync-core.py to add it"
    )
    if "--remote" not in sys.argv:
        sys.exit(0)
else:
    got = ch.content_hash()
    if got != want:
        bad.append(f"content hash {got[:12]} does not match the lock {want[:12]}")

if "--remote" in sys.argv:
    if not cfg.get("commit") and cfg.get("ref", "main") == "main":
        sys.exit(
            "core sync: standards.lock has no commit and no release ref; run scripts/sync-core.py first"
        )
    tmp = pathlib.Path(tempfile.mkdtemp())
    try:
        ch.clone(ch.core_repo(), tmp / "core")
        subprocess.run(
            ["git", "-C", str(tmp / "core"), "fetch", "--quiet", "--tags", "--force"], check=False
        )
        how = ch.checkout_pinned(tmp / "core", cfg)
        if how != "commit":
            print(f"core sync: {how}")
        for src, dst in (("standards", "standards-core"), ("tokens", "tokens-core")):
            if (tmp / "core" / src).is_dir():
                c = filecmp.dircmp(tmp / "core" / src, ch.ROOT / dst)
                bad += [f"{dst}/{n}" for n in sorted(c.left_only + c.right_only + c.diff_files)]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

for src, dst in ch.read_targets():
    if not dst.is_file() or src.read_bytes().replace(b"\r\n", b"\n") != dst.read_bytes().replace(
        b"\r\n", b"\n"
    ):
        bad.append(
            f"{dst.relative_to(ch.ROOT.parent) if ch.ROOT.parent in dst.parents else dst} differs from {src.relative_to(ch.ROOT)}; change the core and run sync-core.py, do not edit it here"
        )

print("core sync:", "clean" if not bad else "DRIFT: " + "; ".join(bad))
sys.exit(1 if bad else 0)
