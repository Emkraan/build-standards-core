#!/usr/bin/env python3
"""Fail on a relative markdown link whose target file or heading anchor does not exist.

Scans the same file set as check-ascii.py and check-sanitised.py (git ls-files: tracked plus
untracked files that are not ignored), so installed dependencies such as kit/node_modules never
count. An anchor (`doc.md#4-auth` or `#4-auth` in the same file) must match a heading of the target,
slugged the way GitHub renders it: lower case, punctuation dropped, spaces to hyphens, and a
`-1`, `-2` suffix for repeated headings.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

LINK = re.compile(r"\]\(([^)#\s]+\.md)(?:#([^)\s]*))?\)")
SAME = re.compile(r"\]\(#([^)\s]+)\)")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")


def markdown_files():
    r = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "*.md"], capture_output=True, text=True
    )
    if r.returncode != 0:
        sys.exit(f"check-links: git ls-files failed: {r.stderr.strip()}")
    return [pathlib.Path(p) for p in r.stdout.splitlines() if p]


def slug(text: str) -> str:
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = text.replace("`", "").strip().lower()
    text = re.sub(r"[^a-z0-9 _-]", "", text)
    return text.replace(" ", "-")


_anchors: dict = {}


def anchors(path: pathlib.Path) -> set:
    key = path.resolve()
    if key not in _anchors:
        found, counts, fenced = set(), {}, False
        for line in path.read_text(encoding="utf8").split("\n"):
            if FENCE.match(line):
                fenced = not fenced
                continue
            m = None if fenced else HEADING.match(line)
            if m:
                base = slug(m.group(2))
                n = counts.get(base, 0)
                counts[base] = n + 1
                found.add(base if n == 0 else f"{base}-{n}")
        _anchors[key] = found
    return _anchors[key]


def main():
    bad = []
    for f in markdown_files():
        if not f.is_file():
            continue
        for i, line in enumerate(f.read_text(encoding="utf8").split("\n"), 1):
            for m in LINK.finditer(line):
                target, frag = m.group(1), m.group(2)
                if target.startswith("http"):
                    continue
                dest = f.parent / target
                if not dest.exists():
                    bad.append(f"::error file={f},line={i}::broken link {target}")
                elif frag and dest.is_file() and frag not in anchors(dest):
                    bad.append(f"::error file={f},line={i}::broken anchor {target}#{frag}")
            for m in SAME.finditer(line):
                if m.group(1) not in anchors(f):
                    bad.append(f"::error file={f},line={i}::broken anchor #{m.group(1)}")
    for b in bad:
        print(b)
    print(f"check-links: {len(bad)} broken")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
