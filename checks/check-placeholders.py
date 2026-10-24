#!/usr/bin/env python3
"""Fail when a tracked markdown file carries patch-placeholder text.

A fuzzy edit that meant to insert a section once replaced a whole README with the line
"... (other sections unchanged) ..." and CI stayed green, because every link still resolved.
Placeholder prose is how a clobbering patch survives review: the diff looks like an
insertion, the removal hides behind the placeholder. When editing a document, rewrite the
full file; never summarise existing content away.

Usage: python3 checks/check-placeholders.py
"""

import re
import subprocess
import sys

PATTERNS = [
    re.compile(
        r"\(\s*(?:other|remaining)\s+(?:sections?|content|text)\s+unchanged\s*\)", re.IGNORECASE
    ),
    re.compile(r"^\s*\.{3}\s*\(.*unchanged.*\)\s*\.{3}\s*$", re.IGNORECASE),
    re.compile(
        r"\[\s*(?:rest of|the rest of)?\s*(?:the\s+)?(?:file|document|content)\s+(?:omitted|unchanged|same)\s*\]",
        re.IGNORECASE,
    ),
]


def main():
    files = subprocess.run(
        ["git", "ls-files", "*.md"], capture_output=True, text=True
    ).stdout.split()
    bad = []
    for path in files:
        try:
            with open(path, encoding="utf-8") as fh:
                for n, line in enumerate(fh, 1):
                    if any(p.search(line) for p in PATTERNS):
                        bad.append(
                            f"::error::{path}:{n}: placeholder text hides removed content; "
                            "rewrite the document in full instead"
                        )
        except (UnicodeDecodeError, OSError):
            continue
    print("\n".join(bad))
    print(f"check-placeholders: {len(files)} file(s), {len(bad)} problem(s)")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
