#!/usr/bin/env python3
"""Every var() the core's own CSS uses must resolve.

A var() with no fallback that names a custom property nobody declares is invalid at computed-value
time, so the whole declaration silently drops (a transition that never runs, a shadow that never
paints). This check collects every declared custom property in the core CSS and fails on any
var(--name) with no fallback whose name is never declared. Runtime variables set from script
(--i, --hue) must carry a fallback where they are read, or be declared on their component.

Usage: python3 checks/check-css-vars.py [FILE_OR_DIR ...]   (default: tokens/ and kit/src/)
Exit codes: 0 every reference resolves, 1 unresolved references.
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT = ["tokens", "kit/src"]
DECL = re.compile(r"(?<![\w-])(--[A-Za-z0-9_-]+)\s*:")
REF = re.compile(r"var\(\s*(--[A-Za-z0-9_-]+)\s*(,)?")


def css_files(args):
    out = []
    for a in args or DEFAULT:
        p = (ROOT / a) if not pathlib.Path(a).is_absolute() else pathlib.Path(a)
        if p.is_file() and p.suffix == ".css":
            out.append(p)
        elif p.is_dir():
            out.extend(
                f
                for f in sorted(p.rglob("*.css"))
                if "node_modules" not in f.parts and "dist" not in f.parts
            )
    return out


def main(argv):
    files = css_files(argv)
    declared, refs = set(), []
    for f in files:
        text = re.sub(
            r"/\*.*?\*/",
            lambda m: re.sub(r"[^\n]", " ", m.group(0)),
            f.read_text(encoding="utf8"),
            flags=re.S,
        )
        declared.update(DECL.findall(text))
        for m in REF.finditer(text):
            if not m.group(2):
                refs.append((f, text.count("\n", 0, m.start()) + 1, m.group(1)))
    bad = [(f, line, name) for f, line, name in refs if name not in declared]
    for f, line, name in bad:
        rel = f.relative_to(ROOT) if f.is_relative_to(ROOT) else f
        print(f"::error file={rel},line={line}::var({name}) has no fallback and is never declared")
    print(
        f"check-css-vars: {len(files)} file(s), {len(refs)} reference(s) without a fallback, {len(bad)} unresolved"
    )
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
