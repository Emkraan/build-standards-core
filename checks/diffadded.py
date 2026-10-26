"""Added lines of a diff, for the checks that run in diff mode.

`added_lines(root, base=None, staged=False)` returns {path: [(line number, text), ...]} for the lines a
change adds: `git diff BASE...HEAD` when a base is given, the index against HEAD when `staged` is true.
Only added lines are returned, so a hit that already sits in a historical file (a changelog entry that
quotes an old term) is not the change's to fix, while a new hit on an added line is. Deleted files and
binary files contribute nothing. Not a check itself.
"""

import re
import subprocess

HUNK = re.compile(r"^@@ -\S+ \+(\d+)(?:,\d+)? @@")


def diff_text(root, base=None, staged=False):
    cmd = ["git", "-C", str(root), "-c", "core.quotepath=off", "diff", "--no-color", "--no-renames"]
    cmd += ["--unified=0", "--no-ext-diff", "--diff-filter=AMCR"]
    cmd += ["--cached"] if staged else [f"{base}...HEAD"]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError("git diff failed: " + r.stderr.strip())
    return r.stdout


def parse(text):
    out = {}
    path = None
    lineno = 0
    for raw in text.split("\n"):
        if raw.startswith("+++ "):
            tgt = raw[4:].split("\t")[0]
            path = tgt[2:] if tgt.startswith("b/") else None
            continue
        if raw.startswith("--- ") or raw.startswith("diff --git"):
            continue
        m = HUNK.match(raw)
        if m:
            lineno = int(m.group(1))
            continue
        if path and raw.startswith("+"):
            out.setdefault(path, []).append((lineno, raw[1:]))
            lineno += 1
    return out


def added_lines(root, base=None, staged=False):
    if not staged and not base:
        raise ValueError("diff mode needs a base ref or --staged")
    return parse(diff_text(root, base, staged))


def parse_args(argv):
    """Return (base, staged, rest) for `--diff BASE` or `--staged` at argv[0]; (None, False, None) otherwise."""
    if argv[:1] == ["--staged"]:
        return None, True, argv[1:]
    if argv[:1] == ["--diff"]:
        if len(argv) < 2:
            raise SystemExit("--diff needs a base ref")
        return argv[1], False, argv[2:]
    return None, False, None
