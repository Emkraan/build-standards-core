#!/usr/bin/env python3
"""Fail a pull request that changes shipped content without a changelog entry.

The convention (CONTRIBUTING.md) is that every change to a standard ships with a dated
CHANGELOG.md entry. PR 78 broke it while CI stayed green: the rule existed only as prose,
so the release history silently went incomplete. This check draws the line mechanically:
any diff touching shipped content must also touch CHANGELOG.md. CI plumbing (checks/,
.github/) and the changelog itself are exempt.

Usage: python3 checks/check-changelog.py <base-ref>
In CI (CI or GITHUB_ACTIONS set) a base ref that does not resolve, or a diff that cannot be taken,
fails: a check that cannot see the change proves nothing, and a skipped check once passed a pull
request it should have stopped. Dependency bumps are the one other exemption: a pull request from
a `renovate/` branch whose every changed file is a dependency manifest or lockfile changes no
standard, so it needs no entry (2026-11-15: five Renovate pull requests sat red for weeks on this
check). Run locally, the same case prints "skipped" and passes, so a clone
without the base branch fetched stays usable.
"""

import os
import subprocess
import sys

CONTENT_EXEMPT_DIRS = ("checks/", ".github/")
CONTENT_EXEMPT_FILES = ("CHANGELOG.md",)
DEPENDENCY_FILES = (
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "requirements.txt",
    "requirements-dev.txt",
)


def changed_files(base):
    out = subprocess.run(
        ["git", "diff", "--name-only", base + "...HEAD"], capture_output=True, text=True
    )
    if out.returncode != 0:
        return None
    return [line for line in out.stdout.splitlines() if line.strip()]


def is_content(path):
    return not (path.startswith(CONTENT_EXEMPT_DIRS) or path in CONTENT_EXEMPT_FILES)


def is_dependency_bump(files, head_ref):
    """True for a Renovate branch that changes only dependency manifests and lockfiles."""
    return (
        head_ref.startswith("renovate/")
        and bool(files)
        and all(os.path.basename(f) in DEPENDENCY_FILES for f in files if is_content(f))
    )


def in_ci():
    return bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))


def unknown(msg):
    if in_ci():
        print(f"check-changelog: {msg}; failing closed in CI (fetch the base with fetch-depth 0)")
        return 1
    print(f"check-changelog: {msg}; skipped (local run)")
    return 0


def main():
    if len(sys.argv) != 2:
        print("usage: check-changelog.py <base-ref>", file=sys.stderr)
        return 2
    base = sys.argv[1]
    verify = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", base], capture_output=True, text=True
    )
    if verify.returncode != 0:
        return unknown(f"base ref {base} unknown")
    files = changed_files(base)
    if files is None:
        return unknown(f"cannot diff against {base}")
    touched = [f for f in files if is_content(f)]
    if is_dependency_bump(files, os.environ.get("GITHUB_HEAD_REF", "")):
        print(f"check-changelog: ok (dependency bump, {len(touched)} manifest file(s))")
        return 0
    if touched and "CHANGELOG.md" not in files:
        print(
            "check-changelog: this change touches shipped content but adds no "
            "CHANGELOG.md entry (CONTRIBUTING.md):"
        )
        for f in touched[:20]:
            print("  " + f)
        if len(touched) > 20:
            print(f"  ...and {len(touched) - 20} more")
        print('Add a dated entry under a new "## <date> (vX.Y.Z, slug)" heading.')
        return 1
    print(f"check-changelog: ok ({len(touched)} content file(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
