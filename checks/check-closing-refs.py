#!/usr/bin/env python3
"""Fail a pull request whose body or commits would close a consumer-report issue on merge.

A consumer-report issue is the account's single upward channel (CONTRIBUTING.md, "Reporting from a
consumer"). A core pull request links it, but a GitHub closing keyword in front of the link
("Closes #117") closes the report when the pull request merges, and the account loses its open
issue. That happened once. This check reads the pull request's title and body (from the event file
GitHub Actions passes, or --event FILE) and every commit message in BASE..HEAD, finds each closing
keyword (close, closes, closed, fix, fixes, fixed, resolve, resolves, resolved, any case, optional
colon) followed by an issue reference (#N, OWNER/REPO#N or an issues URL), and reads that issue's
labels. A reference to an issue labelled consumer-report fails. A label that cannot be read fails
too, in CI: a check that cannot see the label proves nothing. Write "Refs #N" or "for #N" instead.

Usage: python3 checks/check-closing-refs.py [BASE] [--event FILE] [--labels-json FILE]
  --labels-json FILE   {"<number>" or "<owner>/<repo>#<number>": ["label", ...]} instead of gh (tests)
Exit codes: 0 pass, 1 a closing reference to a consumer-report issue (or an unreadable label in CI).
"""

import json
import os
import re
import subprocess
import sys

LABEL = "consumer-report"
KEYWORD = re.compile(
    r"\b(?:close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)\b:?\s+"
    r"(?:(?P<repo>[\w.-]+/[\w.-]+)?#(?P<num>\d+)"
    r"|https?://github\.com/(?P<urlrepo>[\w.-]+/[\w.-]+)/issues/(?P<urlnum>\d+))",
    re.I,
)


def take(args, flag):
    if flag in args:
        i = args.index(flag)
        value = args[i + 1] if i + 1 < len(args) else ""
        del args[i : i + 2]
        return value
    return ""


def references(text):
    """[(repo or '', number)] for every closing keyword followed by an issue reference."""
    out = []
    for m in KEYWORD.finditer(text or ""):
        repo = m.group("repo") or m.group("urlrepo") or ""
        out.append((repo, int(m.group("num") or m.group("urlnum"))))
    return out


def texts(base, event):
    """(source, text) pairs: the pull request's title and body, then each commit message."""
    out = []
    if event:
        try:
            with open(event, encoding="utf8") as fh:
                pr = (json.loads(fh.read()) or {}).get("pull_request") or {}
        except (OSError, ValueError):
            pr = {}
        out.append(("pull request title", pr.get("title") or ""))
        out.append(("pull request body", pr.get("body") or ""))
    if base:
        r = subprocess.run(
            ["git", "log", "--format=%H%x00%B%x01", f"{base}..HEAD"], capture_output=True, text=True
        )
        if r.returncode == 0:
            for chunk in r.stdout.split("\x01"):
                if "\x00" in chunk:
                    sha, msg = chunk.strip().split("\x00", 1)
                    out.append((f"commit {sha[:12]}", msg))
    return out


def labels_of(repo, number, fixture):
    """The issue's label names, or None when they cannot be read."""
    if fixture is not None:
        hit = fixture.get(f"{repo}#{number}") if repo else None
        return hit if hit is not None else fixture.get(str(number), [])
    if not repo:
        return None
    r = subprocess.run(
        ["gh", "api", f"repos/{repo}/issues/{number}", "--jq", "[.labels[].name]"],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout or "[]")
    except ValueError:
        return None


def main(argv):
    args = list(argv)
    event = take(args, "--event") or os.environ.get("GITHUB_EVENT_PATH", "")
    fixture_file = take(args, "--labels-json")
    fixture = None
    if fixture_file:
        with open(fixture_file, encoding="utf8") as fh:
            fixture = json.loads(fh.read())
    base = args[0] if args else ""
    here = os.environ.get("GITHUB_REPOSITORY", "")
    if not here and fixture is None:
        r = subprocess.run(
            ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
            capture_output=True,
            text=True,
        )
        here = r.stdout.strip() if r.returncode == 0 else ""
    in_ci = bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))
    bad, unread, seen = [], [], 0
    for source, text in texts(base, event):
        for repo, number in references(text):
            seen += 1
            target = repo or here
            labels = labels_of(target, number, fixture)
            ref = f"{target}#{number}" if target else f"#{number}"
            if labels is None:
                unread.append(f"{source}: cannot read the labels of {ref}")
            elif LABEL in labels:
                bad.append(f"{source}: a closing keyword in front of {ref}, a {LABEL} issue")
    for line in bad:
        print(
            f'check-closing-refs: {line}; merging would close the report. Write "Refs #N" instead.'
        )
    for line in unread:
        print(f"check-closing-refs: {line}" + ("" if in_ci else " (skipped outside CI)"))
    if bad or (unread and in_ci):
        return 1
    print(f"check-closing-refs: ok ({seen} closing reference(s), none to a {LABEL} issue)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
