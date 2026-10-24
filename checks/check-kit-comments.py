#!/usr/bin/env python3
"""Fail if a comment in the kit source names a standards doc by file name (for example a `.md` file).

Why: a consumer that vendors the kit scrubs core names and then denies leftovers. A comment that
names a doc survives the scrub and either holds that consumer's sync or forces a local rewrite rule.
A kit comment says "the UI standard" and the section number, never the doc's file name.

Checks every line of kit/src (ts and tsx) for a word ending in `.md`. --file PATH ... checks the
given files instead. Exit 1 on a hit.
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOC = re.compile(r"(?<![A-Za-z0-9_/.-])[A-Za-z0-9_-]+\.md\b")


def scan(files):
    hits = []
    for f in files:
        try:
            lines = pathlib.Path(f).read_text(encoding="utf8").split("\n")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(lines, 1):
            m = DOC.search(line)
            if m:
                hits.append(
                    f'::error file={f},line={i}::comment names a doc ({m.group(0)}); say "the UI standard" instead'
                )
    return hits


def main(argv):
    if argv[:1] == ["--file"]:
        files = argv[1:]
    else:
        files = sorted(
            str(p.relative_to(ROOT))
            for p in (ROOT / "kit" / "src").rglob("*")
            if p.suffix in (".ts", ".tsx")
        )
    hits = scan(files)
    print("\n".join(hits))
    print(f"check-kit-comments: {len(hits)} hit(s) in {len(files)} file(s)")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
