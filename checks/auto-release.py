#!/usr/bin/env python3
"""Tag and publish a release when a commit introduces a new top CHANGELOG entry.

Used by .github/workflows/release.yml on every push to main. The decision is a pure function
(decide) so it is unit tested; main() only gathers git state and acts on the decision.

Usage:
  auto-release.py [--sha SHA] [--dry-run] [--ignore-tag vX.Y.Z ...] [--backfill vX.Y.Z]
--dry-run prints the decision and changes nothing. --ignore-tag (repeatable) pretends tags do not exist
(for replaying history, for example "would this have tagged v1.12.0?"). --backfill tags a version the
release step missed (a heading that was unreadable when it merged) on --sha, with the notes of its
entry on HEAD: it needs a readable entry, no existing tag and a commit that is part of HEAD.
Outputs in GITHUB_OUTPUT: action (tag | noop), tag, notes_file.
"""

import argparse
import os
import re
import subprocess
import sys

HEADING = re.compile(r"^## (\d{4}-\d{2}-\d{2}) \(v(\d+)\.(\d+)\.(\d+)(?:, [^)]*)?\)\s*$")
TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def parse_entries(text):
    """Return [(version_tuple, heading, body)] in file order (newest first by convention)."""
    entries = []
    cur = None
    for line in text.splitlines():
        if line.startswith("## "):
            m = HEADING.match(line)
            cur = None
            if m:
                cur = [tuple(int(g) for g in m.groups()[1:]), line, []]
                entries.append(cur)
        elif cur is not None:
            cur[2].append(line)
    return [(v, h, "\n".join(b).strip("\n") + "\n") for v, h, b in entries]


def top_entry(text):
    entries = parse_entries(text)
    return entries[0] if entries else None


def fmt(version):
    return "v{}.{}.{}".format(*version)


def decide(top, prev_top, tags, sha):
    """top/prev_top: version tuple or None. tags: {version_tuple: commit sha}.

    Returns (action, message). action is tag, noop or fail.
    """
    if top is None:
        return "noop", "no CHANGELOG entry on this commit"
    name = fmt(top)
    if top in tags:
        if tags[top] == sha:
            return "noop", f"{name} already tagged on this commit"
        if prev_top == top:
            return "noop", f"no new entry; {name} was released earlier"
        return "fail", f"{name} already exists on {tags[top]}, not on {sha}; a tag is never moved"
    latest = max(tags) if tags else None
    if latest is not None and top <= latest:
        return "fail", f"top version {name} is not greater than the latest tag {fmt(latest)}"
    why = "introduced by this commit" if prev_top != top else "top entry has no tag yet"
    return "tag", f"{name} {why}; tag and release it"


def decide_backfill(version, entries, tags, sha_is_ancestor):
    """Tag a version the release step missed (a heading that never got its tag).

    Only for a version that has a readable CHANGELOG entry, no tag yet and a commit that is part of
    main. It is the one case where a tag below the newest one is allowed, and an existing tag is
    still never moved. Returns (action, message, entry) with action tag, noop or fail.
    """
    name = fmt(version)
    if version in tags:
        return "noop", f"{name} is already tagged", None
    entry = next((e for e in entries if e[0] == version), None)
    if entry is None:
        return "fail", f"no readable CHANGELOG entry for {name}", None
    if not sha_is_ancestor:
        return "fail", f"the commit is not part of the current branch, {name} not tagged", None
    return "tag", f"{name} was missed by the release step, so tag and release it", entry


def git(*args, check=True):
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip() if r.returncode == 0 else None


def read_tags(ignore):
    tags = {}
    for line in git(
        "for-each-ref", "--format=%(refname:short) %(*objectname) %(objectname)", "refs/tags"
    ).splitlines():
        parts = line.split()
        m = TAG.match(parts[0])
        if not m or parts[0] in ignore:
            continue
        tags[tuple(int(g) for g in m.groups())] = parts[
            1
        ]  # peeled commit if annotated, else the object itself
    return tags


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sha", default="HEAD")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--ignore-tag", action="append", default=[])
    ap.add_argument(
        "--backfill",
        metavar="vX.Y.Z",
        help="tag a version the release step missed, on --sha, with the notes of its entry on HEAD",
    )
    args = ap.parse_args(argv)
    sha = git("rev-parse", args.sha)
    if args.backfill:
        m = TAG.match(args.backfill)
        if not m:
            print(f"auto-release: fail: {args.backfill} is not a version tag")
            return 1
        version = tuple(int(g) for g in m.groups())
        ancestor = git("merge-base", "--is-ancestor", sha, "HEAD", check=False) is not None
        action, msg, top = decide_backfill(
            version,
            parse_entries(git("show", "HEAD:CHANGELOG.md")),
            read_tags(args.ignore_tag),
            ancestor,
        )
        print(f"auto-release: {action}: {msg}")
        if action == "fail":
            return 1
    else:
        top = top_entry(git("show", f"{sha}:CHANGELOG.md"))
        parent = git("rev-parse", "--verify", "--quiet", f"{sha}^", check=False)
        prev = (
            top_entry(git("show", f"{parent}:CHANGELOG.md", check=False) or "") if parent else None
        )
        action, msg = decide(
            top[0] if top else None, prev[0] if prev else None, read_tags(args.ignore_tag), sha
        )
        print(f"auto-release: {action}: {msg}")
        if action == "fail":
            return 1
    if args.dry_run:
        return 0
    out = os.environ.get("GITHUB_OUTPUT")
    if action == "tag":
        notes = os.path.join(os.environ.get("RUNNER_TEMP", "."), "release-notes.md")
        with open(notes, "w") as f:
            f.write(top[2])
    lines = [f"action={action}"]
    if action == "tag":
        lines += [f"tag={fmt(top[0])}", f"notes_file={notes}", f"sha={sha}"]
    if out:
        with open(out, "a") as f:
            f.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
