#!/usr/bin/env python3
"""Fail if a commit in the range carries a real author or committer email.

Usage: python3 checks/check-authors.py [<base>]
Checks <base>..HEAD (default: origin/main..HEAD, or the HEAD commit alone when that range is empty).
Merge commits are skipped: GitHub builds the pull request merge commit with the opener's account email, which is
not history anyone authored and never lands (squash merges carry the branch commit author).
Allowed: *@users.noreply.github.com and GitHub's own noreply@github.com (web-flow merges). Anything
else, a work or personal address, would put an employer or a person into the shared history.
Set the clone identity once: git config user.email <id>+<login>@users.noreply.github.com
"""

import re
import subprocess
import sys

ALLOWED_SUFFIX = "@users.noreply.github.com"
ALLOWED_EXACT = {"noreply@github.com"}
# Commits already in main before this guard could stop them (a squash merge wrote the opener's primary
# email). Fixing them needs a force-push to main, which is not done, so they are recorded here by full
# hash. Never add a new entry: fix the merge instead (pr-review-and-merge.md 1.18).
KNOWN_HISTORY = {
    "8f64feba0537cbefeccd3c7b706102fa674f8436",
    "243e9256d5544b2d9aa532a1751f4d6bc377b527",
    "b574af4f5e43e67fc729dfa5a75435f9c43c1a2e",
}

# CONTRIBUTING: "No attribution to any tool or assistant in commits, PR text or files."
ASSISTANT_IDENTITY = re.compile(
    r"(?:claude|anthropic|openai|gpt-|copilot|assistant|kratos|\bai\b)", re.IGNORECASE
)
CO_AUTHOR = re.compile(r"^\s*co-authored-by:\s*(.+)$", re.IGNORECASE | re.MULTILINE)


def run(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True)


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "origin/main"
    rng = f"{base}..HEAD"
    r = run("log", "--no-merges", "--format=%H %ae %ce", rng)
    if r.returncode != 0 or not r.stdout.strip():
        r = run("log", "-1", "--format=%H %ae %ce")
    bad = []
    for line in r.stdout.splitlines():
        sha, *emails = line.split()
        if sha in KNOWN_HISTORY:
            continue
        for e in emails:
            el = e.lower()
            if not (el.endswith(ALLOWED_SUFFIX) or el in ALLOWED_EXACT):
                bad.append(
                    f"::error::commit {sha[:8]} uses email on domain {el.split('@')[-1]}; use your GitHub noreply address"
                )
    # A co-author trailer naming an assistant puts tool attribution into the shared history.
    b = run("log", "--no-merges", "--format=%H%x1e%b", rng)
    if b.returncode != 0 or not b.stdout.strip():
        b = run("log", "-1", "--format=%H%x1e%b")
    for record in b.stdout.split("\x1e"):
        lines = record.strip("\n").split("\n", 1)
        if len(lines) != 2:
            continue
        sha, body = lines
        for m in CO_AUTHOR.finditer(body):
            if ASSISTANT_IDENTITY.search(m.group(1)):
                bad.append(
                    f"::error::commit {sha[:8]} carries a Co-authored-by trailer naming an "
                    "assistant or tool; commit messages must show only the human author"
                )
    print("\n".join(bad))
    print(f"check-authors: {len(r.stdout.splitlines())} commit(s), {len(bad)} problem(s)")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
