#!/usr/bin/env python3
"""Every --token a standards doc names must exist.

A doc that names a custom property nobody declares sends readers to a token that resolves to
nothing (the retired palette is the classic case). This check collects the custom properties
declared by the token sheet generated from tokens/tokens.json, by tokens/hub-layer.css and by the
kit's stylesheets (kit/src/**/*.css), then reads every standards/*.md and fails on a token name
that is not declared.

A token reference in a doc is any of:
  var(--name)                      anywhere in the doc
  `--name`                         an inline code span holding only the name
  `--name-*`, `--name-<part>`      a pattern: some declared token must start with the prefix
  --name: value                    a declaration inside a fenced css block
Command-line flags written with their command (`build.py --check`) sit inside longer code spans and
are never read as tokens. A flag a doc names on its own (`--dry-run`) must be listed in FLAGS.

Usage: python3 checks/check-token-names.py [DOC ...]   (default: standards/*.md)
Exit codes: 0 every named token exists, 1 unknown tokens.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DECL = re.compile(r"(?<![\w-])(--[A-Za-z0-9_-]+)\s*:")
NAME = r"--[a-z][a-z0-9-]*[a-z0-9]"
VAR_REF = re.compile(rf"var\(\s*({NAME})")
SPAN_REF = re.compile(rf"`({NAME})(-\*|-?<[a-z-]+>[a-z0-9-]*|\*)?`")
# Command-line flags the docs name on their own in a code span. They are options, not tokens.
FLAGS = {
    "--body-file",
    "--check",
    "--dry-run",
    "--error",
    "--fallback-icon",
    "--force",
    "--json",
    "--latest",
    "--self-test",
    "--server",
    "--squash",
    "--rebase",
    "--force-with-lease",
}
FENCE = re.compile(r"^\s*(```|~~~)\s*([A-Za-z0-9_-]*)")


def json_tokens() -> set[str]:
    """Token names from tokens.json, so the check does not depend on the generated sheet being current."""
    out: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, dict) and "$value" in value:
                    out.add(f"--{key}")
                else:
                    walk(value)

    path = ROOT / "tokens" / "tokens.json"
    if path.is_file():
        walk(json.loads(path.read_text(encoding="utf8")))
    return out


def declared() -> set[str]:
    names = json_tokens()
    sheets = [ROOT / "tokens" / "tokens.css", ROOT / "tokens" / "hub-layer.css"]
    sheets += sorted((ROOT / "kit" / "src").rglob("*.css"))
    for f in sheets:
        if f.is_file() and "node_modules" not in f.parts:
            text = re.sub(r"/\*.*?\*/", " ", f.read_text(encoding="utf8"), flags=re.S)
            names.update(DECL.findall(text))
    return names


def references(text: str):
    """Yield (line, name, is_prefix) for every token reference in a markdown doc."""
    fence_lang = None
    for i, line in enumerate(text.split("\n"), 1):
        m = FENCE.match(line)
        if m:
            fence_lang = None if fence_lang is not None else (m.group(2).lower() or "text")
            continue
        for v in VAR_REF.finditer(line):
            yield i, v.group(1), False
        if fence_lang is None:
            for s in SPAN_REF.finditer(line):
                yield (
                    i,
                    s.group(1) + ("-" if s.group(2) and s.group(2).startswith("-") else ""),
                    bool(s.group(2)),
                )
        elif fence_lang == "css":
            for d in DECL.finditer(line):
                yield i, d.group(1), False


def main(argv: list[str]) -> int:
    known = declared()
    docs = [pathlib.Path(a) for a in argv] if argv else sorted((ROOT / "standards").glob("*.md"))
    bad, seen = [], 0
    for doc in docs:
        text = doc.read_text(encoding="utf8")
        for line, name, is_prefix in references(text):
            if name in FLAGS and not is_prefix:
                continue
            seen += 1
            ok = any(k.startswith(name) for k in known) if is_prefix else name in known
            if not ok:
                rel = doc.resolve().relative_to(ROOT) if doc.resolve().is_relative_to(ROOT) else doc
                kind = "no declared token starts with" if is_prefix else "unknown token"
                bad.append(
                    f"::error file={rel},line={line}::{kind} {name} (not in tokens.json, hub-layer.css or kit/src, a command-line flag goes in FLAGS)"
                )
    for b in bad:
        print(b)
    print(
        f"check-token-names: {len(docs)} doc(s), {seen} token reference(s), {len(known)} declared, {len(bad)} unknown"
    )
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
