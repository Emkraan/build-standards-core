#!/usr/bin/env python3
"""Fail when CHANGELOG.md version headings and release tags disagree.

Every release is one top CHANGELOG entry (checks/auto-release.py), so the file and the tag list must
map one to one. Two PRs once both took v1.168.0: the second never got a tag, and the change it described
shipped inside a later release under a heading that claimed a number it never had. Rules, for versions
from 1.0.0 (the 0.x headings predate tagging and are left alone):

  1. a version appears in at most one heading;
  2. a heading has a tag, except an unreleased one: a version above every existing tag (the entry a pull
     request adds, which auto-release tags when it lands);
  3. a tag has a heading.

Usage: python3 checks/check-changelog-versions.py
In CI (CI or GITHUB_ACTIONS set) a clone with no release tags fails: a check that cannot see the tags
proves nothing (fetch with fetch-depth 0). Run locally, that case prints "skipped" and passes.
"""

import os
import re
import subprocess
import sys

HEADING = re.compile(r"^## \d{4}-\d{2}-\d{2} \(v(\d+)\.(\d+)\.(\d+)")
TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def headings(text):
    """Version tuples of the 1.x headings, in file order."""
    out = []
    for line in text.splitlines():
        m = HEADING.match(line)
        if m and int(m.group(1)) >= 1:
            out.append(tuple(int(g) for g in m.groups()))
    return out


def problems(versions, tags):
    """versions: heading versions in file order; tags: set of version tuples (1.x only)."""
    out = []
    seen = set()
    for v in versions:
        if v in seen:
            out.append("v{}.{}.{} has more than one heading".format(*v))
        seen.add(v)
    newest = max(tags) if tags else None
    for v in sorted(seen):
        if v not in tags and newest is not None and v <= newest:
            out.append("v{}.{}.{} has a heading but no tag (a number at or below the newest tag is not an unreleased entry)".format(*v))
    for t in sorted(tags):
        if t not in seen:
            out.append("v{}.{}.{} is a tag with no heading".format(*t))
    return out


def read_tags():
    r = subprocess.run(["git", "tag", "--list", "v*"], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    tags = set()
    for name in r.stdout.split():
        m = TAG.match(name)
        if m and int(m.group(1)) >= 1:
            tags.add(tuple(int(g) for g in m.groups()))
    return tags


def main():
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    with open(os.path.join(root, "CHANGELOG.md"), encoding="utf-8") as f:
        versions = headings(f.read())
    tags = read_tags()
    in_ci = bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))
    if not tags:
        msg = "no release tags visible"
        if in_ci:
            print(f"check-changelog-versions: {msg}; failing closed in CI (fetch with fetch-depth 0)")
            return 1
        print(f"check-changelog-versions: {msg}; skipped (local run)")
        return 0
    bad = problems(versions, tags)
    for p in bad:
        print("::error file=CHANGELOG.md::" + p)
    print(f"check-changelog-versions: {len(versions)} heading(s), {len(tags)} tag(s), {len(bad)} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
