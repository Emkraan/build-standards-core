#!/usr/bin/env python3
"""The checks behind the overlay's core-ci.yml workflow, one subcommand per job. Standard library only.

Usage (run from the consumer repo root; the overlay may sit in a subfolder):
  python3 scripts/core-ci.py params [--github-output]       parameters the workflow needs, from
                                                             standards-local/parameters.md
  python3 scripts/core-ci.py pr-title [TITLE]                Conventional Commit PR title (PR_TITLE)
  python3 scripts/core-ci.py commitlint BASE HEAD            every commit subject in BASE..HEAD
  python3 scripts/core-ci.py attribution BASE HEAD           no tool attribution in commits, PR title
                                                             and body (PR_TITLE, PR_BODY), plus the
                                                             hashed private term guard when the overlay
                                                             has standards-local/denylist.sha256
  python3 scripts/core-ci.py identity BASE HEAD              author and committer emails of BASE..HEAD
  python3 scripts/core-ci.py changelog BASE HEAD             a version bump has its changelog heading
  python3 scripts/core-ci.py changelog-entries BASE HEAD     one new entry per pull request, fixed
                                                             heading, newest first, older entries byte
                                                             for byte (parameter "Changelog entries"
                                                             per-pr; an overlay-only sync is exempt;
                                                             an unknown base fails in CI)
  python3 scripts/core-ci.py workflow-lint [DIR ...]         pinned actions, permissions, digests,
                                                             frozen installs (default .github/workflows);
                                                             warns when a workflow_run trigger lists
                                                             workflows but not core-ci
  python3 scripts/core-ci.py ascii                           no byte above 127 in any tracked text file
                                                             (binaries, synced copies and lockfiles
                                                             skipped); the ASCII patterns parameter
                                                             narrows it, an active exception for
                                                             pr-review-and-merge.md 1.19 excepts a path
  python3 scripts/core-ci.py node-pin                        one Node major across the pin files and
                                                             every workflow
  python3 scripts/core-ci.py python-config                   a committed ruff config targets the floor
  python3 scripts/core-ci.py ruff-requirements               the hash-pinned ruff requirement line
  python3 scripts/core-ci.py install-gitleaks DIR            the pinned scanner, checksum verified
  python3 scripts/core-ci.py secret-scan BASE HEAD [--gitleaks BIN]
                                                             scan BASE..HEAD with the base commit's
                                                             config, ignore files and allow comments off
  python3 scripts/core-ci.py kit-peers [DIR]                 the kit copy (default kit-core) typechecks
                                                             without its optional peers: no root file
                                                             imports one, every tsconfig that includes
                                                             the copy excludes an entry whose peer the
                                                             app does not declare, and tsc (when the
                                                             repo has it) passes with the peers blocked
  python3 scripts/core-ci.py required-checks [--repo R] [--branch B] [--api-json FILE] [--fix [--no-write]]
                                                             which core-ci.yml jobs the merge gate does
                                                             not require (branch protection, rulesets,
                                                             or a REQUIRED_CHECKS list in a workflow);
                                                             --fix rewrites a REQUIRED_CHECKS list in a
                                                             gate workflow (or prints the exact line and
                                                             file:line) and prints the ruleset commands;
                                                             --lists-only checks only such a list; exits
                                                             1 on any mismatch
  python3 scripts/core-ci.py required-names [--github-output]
                                                             the core-ci job names a merge gate requires,
                                                             read from the synced core-ci.yml
  python3 scripts/core-ci.py wait-checks SHA [--repo R] [--timeout MIN] [--interval SEC] [--progress MIN]
                                                             wait until every check on SHA completed
                                                             green (exit 0) or one failed or the wait
                                                             timed out (exit 1); core-update.yml merges
                                                             only after it; a progress line (done,
                                                             pending, failed) at most every 5 min
  python3 scripts/core-ci.py install-psscriptanalyzer DIR    the pinned analyzer, checksum verified
  python3 scripts/core-ci.py powershell [--analyzer DIR]     parser errors and PSUseCompatibleSyntax
                                                             (5.1 and 7) in tracked PowerShell files

A BASE of all zeros (a new branch push) scans or checks the whole history up to HEAD.
Exit codes: 0 pass (or a clean skip, which prints a line starting "skip"), 1 findings, 2 usage or
setup error. Findings name the place and the kind, never a matched secret or banned term.
"""

from __future__ import annotations

import fnmatch
import hashlib
import io
import json
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
# The overlay folder whose standards-local/ and synced copies the checks read. It is the folder above
# this script, unless the reusable workflow runs a pinned copy of the core's scripts against the caller's
# repo: it then sets CORE_CI_OVERLAY to the caller's overlay folder.
ROOT = (
    pathlib.Path(os.environ["CORE_CI_OVERLAY"]).resolve()
    if os.environ.get("CORE_CI_OVERLAY")
    else HERE.parent
)
PARAMETERS = ROOT / "standards-local" / "parameters.md"
DENYLIST = ROOT / "standards-local" / "denylist.sha256"
ZERO = "0" * 40

# Every third-party binary the workflow runs, pinned by version and checksum. Change them together
# with the CHANGELOG entry that says why.
GITLEAKS_VERSION = "8.30.1"
GITLEAKS_SHA256 = {
    "x64": "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb",
    "arm64": "e4a487ee7ccd7d3a7f7ec08657610aa3606637dab924210b3aee62570fb4b080",
}
RUFF_VERSION = "0.16.10"
RUFF_SHA256 = (
    "f33f43a864a8483eebd160e713336c8bab02c934feaff0a33cf5ccb41546d09a",  # manylinux x86_64
    "494401c86df4c4c25f69b9419605d944467ee98c42fb6ad405ef4fa40b8fb67d",  # manylinux aarch64
)
PSSA_VERSION = "1.25.0"
PSSA_SHA256 = "14e634c828eb98efb9f40b2918ba90f139ed5eccdf663a2a747736d996995d60"

TYPES = (
    "feat",
    "fix",
    "chore",
    "ci",
    "docs",
    "refactor",
    "perf",
    "test",
    "style",
    "build",
    "revert",
)
CC = re.compile(r"^(" + "|".join(TYPES) + r")(\([A-Za-z0-9._/-]+\))?!?: \S")
NOREPLY = ("*@users.noreply.github.com", "noreply@github.com")
STACKS = ("web", "wpf", "local-ops", "powershell", "python", "iac")

# Attribution terms are assembled from fragments, so this file never carries them whole.
WORDS = [
    a + b
    for a, b in (
        ("Cla", "ude"),
        ("Anthr", "opic"),
        ("Chat", "GPT"),
        ("Co", "pilot"),
        ("GPT", "-4"),
        ("LLM", "-generated"),
    )
]
VENDOR_MAIL = "noreply@" + "anthr" + "opic.com"
WORD_RE = re.compile(
    r"(?<![A-Za-z0-9./])("
    + "|".join(re.escape(w) for w in WORDS)
    + r")(?![A-Za-z0-9])(?!\.md)(?!/)",
    re.I,
)
COAUTHOR = re.compile(r"^\s*co-authored-by:(.*)$", re.I | re.M)
GENERATED = re.compile(r"^[^A-Za-z0-9]*generated with\b", re.I | re.M)


def say(msg: str) -> None:
    print(msg, flush=True)


def git(*args: str, check: bool = True) -> str:
    r = subprocess.run(["git", *args], capture_output=True, text=True, timeout=300)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout


def rev_range(base: str, head: str) -> str:
    return head if not base or base == ZERO else f"{base}..{head}"


def parameter(prefix: str) -> str:
    """The value cell of the parameters row whose first cell starts with prefix (case-insensitive)."""
    if not PARAMETERS.is_file():
        return ""
    for line in PARAMETERS.read_text(encoding="utf8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[0].lower().startswith(prefix.lower()):
            return cells[1].strip("`").strip()
    return ""


def listed(value: str) -> list:
    return [v.strip().strip("`") for v in value.replace(";", ",").split(",") if v.strip()]


def tracked() -> list:
    return [f for f in git("ls-files", "-z").split("\0") if f]


# ---------------------------------------------------------------- params


JS_LOCKS = ("pnpm-lock.yaml", "yarn.lock", "bun.lockb", "bun.lock", "package-lock.json")


def app_dir(files: list | None = None) -> str:
    """The folder the web toolchain lives in, for lint-sweep.yml: the parameters row "App directory"
    when set, else the repo root when it carries a JS lockfile, else the first folder one level down
    (sorted) that tracks one, else the root. Always a relative path with no '..'."""
    want = parameter("App directory").strip().strip("/")
    if want and want != "." and ".." not in want.split("/") and not want.startswith("/"):
        return want
    files = tracked() if files is None else files
    if any(f in JS_LOCKS for f in files):
        return "."
    for f in sorted(files):
        parts = f.split("/")
        if len(parts) == 2 and parts[1] in JS_LOCKS and not parts[0].startswith("."):
            return parts[0]
    return "."


def params() -> dict:
    stacks = [s.lower() for s in listed(parameter("Stacks"))]
    stacks = [s for s in stacks if s in STACKS]
    files = tracked()
    has = {
        "python": any(f.endswith(".py") for f in files),
        "powershell": any(f.endswith((".ps1", ".psm1", ".psd1")) for f in files),
        "web": "package.json" in files,
    }

    def on(*names: str, probe: str) -> bool:
        return any(n in stacks for n in names) if stacks else has[probe]

    floor = parameter("Python interpreter floor")
    floor = re.match(r"\d+\.\d+", floor).group(0) if re.match(r"\d+\.\d+", floor) else "3.9"
    return {
        "stacks": ",".join(stacks),
        "python": str(on("python", probe="python")).lower(),
        "powershell": str(on("powershell", "wpf", probe="powershell")).lower(),
        "web": str(on("web", probe="web")).lower(),
        "kit": str((ROOT / "kit-core").is_dir()).lower(),
        "python_floor": floor,
        "python_test": parameter("Python test command") or "python -m unittest discover",
        # The repo's own full-tree lint for lint-sweep.yml (empty: only the overlay lints run).
        "lint_sweep": parameter("Lint sweep command"),
        # Node major for jobs that set up Node (lint-sweep.yml); empty: the workflow takes lts/*.
        "node": node_major(),
        # Where lint-sweep.yml installs and runs the sweep command: the App directory row, else the
        # root when it has a lockfile, else the first folder one level down that has one.
        "app_dir": app_dir(files),
        # true when a Node toolchain is needed: a web stack, or a package.json in the app directory.
        "sweep_web": str(
            on("web", probe="web") or (app_dir(files) + "/package.json").lstrip("./") in files
        ).lower(),
    }


def node_major() -> str:
    """The Node major: the parameters row, else .nvmrc, .node-version or package.json engines.node."""
    want = major(parameter("Node major"))
    if want:
        return want
    for name in (".nvmrc", ".node-version"):
        p = ROOT / name
        if p.is_file() and major(p.read_text(encoding="utf8")):
            return major(p.read_text(encoding="utf8"))
    pkg = ROOT / "package.json"
    if pkg.is_file():
        try:
            eng = (json.loads(pkg.read_text(encoding="utf8")).get("engines") or {}).get("node")
        except ValueError:
            eng = None
        if major(eng or ""):
            return major(eng)
    return ""


def cmd_params(argv: list) -> int:
    p = params()
    lines = [f"{k}={v}" for k, v in p.items()]
    out = os.environ.get("GITHUB_OUTPUT")
    if "--github-output" in argv and out:
        with open(out, "a", encoding="utf8") as fh:
            fh.write("\n".join(lines) + "\n")
    say("\n".join(lines))
    return 0


# ---------------------------------------------------------------- PR hygiene


def cmd_pr_title(argv: list) -> int:
    title = argv[0] if argv else os.environ.get("PR_TITLE", "")
    if CC.match(title.strip()):
        say("pr-title: ok")
        return 0
    say(
        f'::error::pr-title: not a Conventional Commit title; use "<type>[(scope)][!]: <subject>" '
        f"with a type from {', '.join(TYPES)}"
    )
    return 1


def commits(base: str, head: str) -> list:
    """(sha, subject, full message, author email, committer email) for each non-merge commit."""
    raw = git(
        "log", "--no-merges", "-z", "--format=%H%x1f%s%x1f%B%x1f%ae%x1f%ce", rev_range(base, head)
    )
    out = []
    for rec in raw.split("\0"):
        parts = rec.strip("\n").split("\x1f")
        if len(parts) == 5:
            out.append(tuple(parts))
    return out


def cmd_commitlint(argv: list) -> int:
    if len(argv) < 2:
        say("usage: core-ci.py commitlint BASE HEAD")
        return 2
    bad = [c for c in commits(argv[0], argv[1]) if not CC.match(c[1])]
    for c in bad:
        say(f"::error::commitlint: commit {c[0][:8]} subject is not a Conventional Commit")
    say(f"commitlint: {len(bad)} bad subject(s)")
    return 1 if bad else 0


def attribution_hits(text: str) -> list:
    """Kinds of attribution found in a text (never the matched words)."""
    kinds = []
    for m in COAUTHOR.finditer(text):
        if "dependabot[bot]" not in m.group(1).lower():
            kinds.append("Co-authored-by trailer")
    if GENERATED.search(text):
        kinds.append("generated-by line")
    if VENDOR_MAIL in text.lower():
        kinds.append("vendor no-reply address")
    if WORD_RE.search(text):
        kinds.append("assistant or tool name")
    return kinds


def denylist_hashes() -> set:
    if not DENYLIST.is_file():
        return set()
    return {
        ln.strip()
        for ln in DENYLIST.read_text(encoding="utf8").splitlines()
        if ln.strip() and not ln.startswith("#")
    }


SPAN_WORD = re.compile(r"[a-z0-9]+")


def term_hit(line: str, hashes: set) -> bool:
    """True when a span of one to four words in the lowercased line hashes to a private term."""
    low = line.lower()
    words = [(m.start(), m.end()) for m in SPAN_WORD.finditer(low)]
    for i in range(len(words)):
        for j in range(i, min(i + 4, len(words))):
            if hashlib.sha256(low[words[i][0] : words[j][1]].encode("utf8")).hexdigest() in hashes:
                return True
    return False


def cmd_attribution(argv: list) -> int:
    if len(argv) < 2:
        say("usage: core-ci.py attribution BASE HEAD")
        return 2
    texts = [
        ("PR title", os.environ.get("PR_TITLE", "")),
        ("PR body", os.environ.get("PR_BODY", "")),
    ]
    texts += [(f"commit {c[0][:8]}", c[2]) for c in commits(argv[0], argv[1])]
    bad = []
    for where, text in texts:
        for kind in attribution_hits(text):
            bad.append(f"{where}: {kind}")
    hashes = denylist_hashes()
    if hashes:
        for where, text in texts:
            for i, line in enumerate(text.splitlines(), 1):
                if term_hit(line, hashes):
                    bad.append(f"{where} line {i}: private term")
        for f in tracked():
            if f.endswith("denylist.sha256"):
                continue
            try:
                lines = pathlib.Path(f).read_text(encoding="utf8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for i, line in enumerate(lines, 1):
                if term_hit(line, hashes):
                    bad.append(f"{f} line {i}: private term")
    for b in bad:
        say(f"::error::attribution: {b}")
    say(f"attribution: {len(bad)} finding(s), {len(hashes)} private term hash(es) checked")
    return 1 if bad else 0


def cmd_identity(argv: list) -> int:
    if len(argv) < 2:
        say("usage: core-ci.py identity BASE HEAD")
        return 2
    allowed = list(NOREPLY) + [p.lower() for p in listed(parameter("Commit emails"))]
    bad = []
    for sha, _, _, author, committer in commits(argv[0], argv[1]):
        for role, email in (("author", author), ("committer", committer)):
            if not any(fnmatch.fnmatch(email.lower(), p) for p in allowed):
                domain = email.rsplit("@", 1)[-1] if "@" in email else "(none)"
                bad.append(f"commit {sha[:8]} {role} email on {domain} is not allowed")
    for b in bad:
        say(f"::error::identity: {b}")
    say(f"identity: {len(bad)} finding(s)")
    return 1 if bad else 0


# ---------------------------------------------------------------- changelog

VERSION_FILES = ("package.json", "pyproject.toml", "VERSION")


def version_of(name: str, text: str | None) -> str | None:
    if text is None:
        return None
    if name.endswith("package.json"):
        try:
            v = json.loads(text).get("version")
        except (ValueError, AttributeError):
            return None
        return v if isinstance(v, str) else None
    if name.endswith("pyproject.toml"):
        section = ""
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("["):
                section = s
            m = re.match(r'version\s*=\s*["\']([^"\']+)["\']', s)
            if m and section in ("[project]", "[tool.poetry]"):
                return m.group(1)
        return None
    return text.strip().splitlines()[0].strip() if text.strip() else None


def show(rev: str, path: str) -> str | None:
    r = subprocess.run(["git", "show", f"{rev}:{path}"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def cmd_changelog(argv: list) -> int:
    if len(argv) < 2:
        say("usage: core-ci.py changelog BASE HEAD")
        return 2
    base, head = argv
    if not base or base == ZERO:
        say("skip changelog: no base commit to compare a version against")
        return 0
    name = parameter("Changelog file") or "CHANGELOG.md"
    files = listed(parameter("Version files")) or list(VERSION_FILES)
    bumps = []
    for f in files:
        old, new = version_of(f, show(base, f)), version_of(f, show(head, f))
        if new and old != new:
            bumps.append((f, new.lstrip("v")))
    if not bumps:
        say("changelog: no version bump, nothing to check")
        return 0
    log = show(head, name)
    if log is None:
        say(f"::error::changelog: the version moved but {name} does not exist at the head commit")
        return 1
    bad = []
    for f, v in bumps:
        rx = re.compile(r"^## \d{4}-\d{2}-\d{2} \(v" + re.escape(v) + r"[,)]", re.M)
        if not rx.search(log):
            bad.append(f'{f} moved to {v} but {name} has no "## YYYY-MM-DD (v{v}" heading')
    for b in bad:
        say(f"::error::changelog: {b}")
    say(f"changelog: {len(bumps)} bump(s), {len(bad)} without a heading")
    return 1 if bad else 0


# One entry per pull request (docs-and-changelog.md 1.9): on when the parameters row "Changelog
# entries" says per-pr. The entry heading is the 1.3 heading, or a dated "no version change" one.
ENTRY_HEAD = re.compile(
    r"^## (\d{4}-\d{2}-\d{2}) \((?:v\d+\.\d+\.\d+|no version change)(?:, [^)]+)?\)\s*$"
)
# What a core sync writes, relative to the overlay folder. A pull request that touches nothing else
# is a sync and needs no entry of its own.
SYNC_PATHS = (
    "standards-core/",
    "tokens-core/",
    "lint-core/",
    "kit-core/",
    "scripts/",
    "standards.lock",
)


def split_entries(text: str) -> tuple:
    """(preamble, [entry, ...]): each entry runs from its "## " heading to the next one, bytes kept."""
    parts = re.split(r"(?m)^(?=## )", text)
    return parts[0], parts[1:]


def overlay_prefix() -> str:
    top = git("rev-parse", "--show-toplevel").strip()
    rel = os.path.relpath(str(ROOT), top).replace(os.sep, "/")
    return "" if rel == "." else rel + "/"


def cmd_changelog_entries(argv: list) -> int:
    if len(argv) < 2:
        say("usage: core-ci.py changelog-entries BASE HEAD")
        return 2
    base, head = argv
    if parameter("Changelog entries").lower() != "per-pr":
        say('skip changelog-entries: the parameters row "Changelog entries" is not per-pr')
        return 0
    in_ci = bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))
    if (
        not base
        or base == ZERO
        or subprocess.run(
            ["git", "cat-file", "-e", f"{base}^{{commit}}"], capture_output=True
        ).returncode
        != 0
    ):
        if in_ci:
            say(
                "::error::changelog-entries: the base commit is unknown, so the append-only rule cannot be "
                "proved; failing closed (check out with fetch-depth 0)"
            )
            return 1
        say("skip changelog-entries: the base commit is unknown (local run)")
        return 0
    name = parameter("Changelog file") or "CHANGELOG.md"
    files = [f for f in git("diff", "--name-only", f"{base}...{head}").splitlines() if f.strip()]
    pre = overlay_prefix()
    if files and all(f.startswith(pre) and f[len(pre) :].startswith(SYNC_PATHS) for f in files):
        say(f"changelog-entries: overlay-only sync ({len(files)} file(s)), no entry needed")
        return 0
    old, new = show(base, name), show(head, name)
    if new is None:
        say(f"::error::changelog-entries: {name} does not exist at the head commit")
        return 1
    if old is None:
        say(f"changelog-entries: {name} is new, nothing to compare against")
        return 0
    bad = []
    old_pre, old_entries = split_entries(old)
    new_pre, new_entries = split_entries(new)
    added = len(new_entries) - len(old_entries)
    if name not in files or added != 1:
        bad.append(f"add exactly one entry for this pull request (found {max(added, 0)} new)")
    elif new_entries[1:] != old_entries:
        bad.append(
            "older entries changed: the changelog is append-only and every older entry stays byte for byte"
        )
    elif new_pre != old_pre:
        bad.append(
            "the text above the entries changed: add the new entry directly under it, newest first"
        )
    else:
        entry = new_entries[0]
        first = entry.splitlines()[0]
        m = ENTRY_HEAD.match(first)
        if not m:
            bad.append(
                f'entry heading "{first[:80]}" is not "## YYYY-MM-DD (vX.Y.Z[, theme])" or '
                '"## YYYY-MM-DD (no version change[, theme])"'
            )
        elif not re.search(r"(?m)^- \S", entry):
            bad.append('the entry has no "- " bullet saying what changed')
        if m and old_entries:
            prev = ENTRY_HEAD.match(old_entries[0].splitlines()[0])
            if prev and m.group(1) < prev.group(1):
                bad.append(f"entry dated {m.group(1)} sits above {prev.group(1)}: newest first")
    for b in bad:
        say(f"::error::changelog-entries: {b}")
    say(f"changelog-entries: {len(bad)} problem(s)")
    return 1 if bad else 0


# ---------------------------------------------------------------- workflow lint

USES = re.compile(r'^\s*(?:-\s*)?uses:\s*["\']?([^\s"\'#]+)["\']?\s*(#.*)?$')
IMAGE = re.compile(r'^\s*(?:-\s*)?image:\s*["\']?([^\s"\'#]+)')
SHA40 = re.compile(r"^[0-9a-f]{40}$")
INSTALLS = (
    (
        re.compile(r"\bpnpm\s+(?:install|i)\b(?!.*--frozen-lockfile)"),
        "pnpm install without --frozen-lockfile",
    ),
    (re.compile(r"\bnpm\s+(?:install|i)\b"), "npm install (use npm ci)"),
    (
        re.compile(r"\byarn\s+install\b(?!.*(?:--frozen-lockfile|--immutable))"),
        "yarn install without a frozen lockfile",
    ),
)


KEYLINE = re.compile(r"^(\s*)(?:-\s+)?[A-Za-z0-9_.\"'-]+:\s+(\S.*)$")


def yaml_colon_scalars(text: str) -> list:
    """Line numbers of `key: value` lines whose unquoted (plain) value contains ': '. YAML cannot parse
    that ("mapping values are not allowed here"), and GitHub then rejects the whole workflow file and
    reports a failed run on every push, so a text rule is not enough to catch it. Block scalars
    (`run: |`), quoted values, flow collections and comments are skipped."""
    bad = []
    skip_col = None
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if skip_col is not None:
            if not stripped or indent > skip_col:
                continue
            skip_col = None
        if not stripped or stripped.startswith("#"):
            continue
        m = KEYLINE.match(line)
        if not m:
            continue
        value = re.sub(r"\s+#.*$", "", m.group(2)).strip()
        if value[:1] in "|>":
            skip_col = indent + (2 if stripped.startswith("- ") else 0)
            continue
        if value[:1] in "\"'[{&*!%@`":
            continue
        if re.search(r":(\s|$)", value):
            bad.append(i)
    return bad


def lint_workflow(path: pathlib.Path) -> list:
    bad = []
    text = path.read_text(encoding="utf8")
    if not re.search(r"^permissions:", text, re.M):
        bad.append((0, "no top-level permissions block"))
    if "actions/setup-python@" in text:
        for i, line in enumerate(text.splitlines(), 1):
            if "ubuntu-latest" in line and not line.lstrip().startswith("#"):
                bad.append(
                    (
                        i,
                        "ubuntu-latest in a workflow that sets up Python: newer images lack old Pythons "
                        "(no 3.9 on 26.04); pin ubuntu-24.04",
                    )
                )
    for i in yaml_colon_scalars(text):
        bad.append(
            (i, "unquoted value contains ': ' (invalid YAML, GitHub rejects the file); quote it")
        )
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        m = USES.match(line)
        if m:
            ref = m.group(1)
            if ref.startswith("./"):
                pass
            elif ref.startswith("docker://"):
                if "@sha256:" not in ref:
                    bad.append((i, "docker image not pinned by digest"))
            elif "@" not in ref or not SHA40.match(ref.rsplit("@", 1)[1]):
                bad.append((i, "action not pinned by a full commit sha"))
            elif not (m.group(2) and re.search(r"#\s*v?\d", m.group(2))):
                bad.append((i, "pinned action has no version comment"))
        m = IMAGE.match(line)
        if m and "${{" not in m.group(1) and "@sha256:" not in m.group(1):
            bad.append((i, "image not pinned by digest"))
        for rx, kind in INSTALLS:
            if rx.search(line):
                bad.append((i, kind))
    return bad


def workflow_run_sources(text: str) -> list | None:
    """The workflows a workflow_run trigger lists (inline list or block list), or None when the file has no
    workflow_run trigger with a workflows key."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)workflow_run:\s*(#.*)?$", line)
        if not m:
            continue
        indent = len(m.group(1))
        for j in range(i + 1, len(lines)):
            nxt = lines[j]
            if (
                nxt.strip()
                and not nxt.lstrip().startswith("#")
                and len(nxt) - len(nxt.lstrip()) <= indent
            ):
                break
            w = re.match(r"^(\s*)workflows:\s*(.*?)\s*(#.*)?$", nxt)
            if not w:
                continue
            value = w.group(2)
            if value.startswith("["):
                return [v.strip().strip("'\"") for v in value.strip("[]").split(",") if v.strip()]
            if value:
                return [value.strip("'\"")]
            out, wi = [], len(w.group(1))
            for k in range(j + 1, len(lines)):
                item = re.match(r"^(\s*)-\s*(.+?)\s*(#.*)?$", lines[k])
                if item and len(item.group(1)) >= wi:
                    out.append(item.group(2).strip("'\""))
                elif lines[k].strip():
                    break
            return out
    return None


CORE_WORKFLOW_NAMES = ("core-ci",)


def gate_trigger_warnings(path: pathlib.Path) -> list:
    """A workflow_run-triggered workflow (a merge gate) that lists workflows but not core-ci never runs
    when core-ci finishes last, so a pull request whose last check is a core-ci job waits for a rerun."""
    if path.name == "core-ci.yml":
        return []
    listed_ = workflow_run_sources(path.read_text(encoding="utf8"))
    if not listed_:
        return []
    if any(n in listed_ for n in CORE_WORKFLOW_NAMES):
        return []
    return [
        f"workflow_run lists {', '.join(listed_)} but not core-ci: a merge gate triggered this way must list "
        f"every workflow whose checks it waits for (ci-cd-release.md section 5)"
    ]


def cmd_workflow_lint(argv: list) -> int:
    dirs = [pathlib.Path(a) for a in argv] or [pathlib.Path(".github/workflows")]
    files = sorted(
        p for d in dirs for p in (d.glob("*.y*ml") if d.is_dir() else [d]) if p.is_file()
    )
    if not files:
        say("::error::workflow-lint: no workflow files found")
        return 1
    n = 0
    warned = 0
    for f in files:
        for line, kind in lint_workflow(f):
            n += 1
            say(f"::error file={f},line={line}::workflow-lint: {kind}")
        for kind in gate_trigger_warnings(f):
            warned += 1
            say(f"::warning file={f}::workflow-lint: {kind}")
    say(
        f"workflow-lint: {len(files)} file(s), {n} finding(s)"
        + (f", {warned} warning(s)" if warned else "")
    )
    return 1 if n else 0


# ---------------------------------------------------------------- ascii, node, python

LOCKFILES = {
    "package-lock.json",
    "npm-shrinkwrap.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lock",
    "bun.lockb",
    "poetry.lock",
    "uv.lock",
    "Pipfile.lock",
    "Cargo.lock",
    "Gemfile.lock",
    "composer.lock",
    "packages.lock.json",
    "go.sum",
    "flake.lock",
}
# The every-file ASCII rule. An exception for it covers a path, never a script or XAML file: those
# stay under their own rules (scripting-powershell.md 1.7, wpf-design-system.md 6.1).
ASCII_RULE = "pr-review-and-merge.md 1.19"
SCRIPT_PATTERNS = ("*.ps1", "*.psm1", "*.psd1", "*.xaml")


def matches(path: str, patterns) -> bool:
    return any(
        fnmatch.fnmatch(pathlib.PurePath(path).name, p) or fnmatch.fnmatch(path, p)
        for p in patterns
    )


def target_destinations(root: pathlib.Path) -> list:
    """Resolved targets.map destinations (copies the sync keeps equal to the core), relative to root."""
    f = root / "targets.map"
    if not f.is_file():
        return []
    out = []
    for line in f.read_text(encoding="utf8").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            out.append((root / line.split("=", 1)[1].strip()).resolve())
    return out


def ascii_candidates(files: list, patterns=None, root: pathlib.Path = ROOT) -> tuple:
    """(files to check, count skipped) from a list of repo-relative paths: text files only (a NUL byte in
    the first 8 KiB marks a binary), never a synced copy, a targets.map destination or a lockfile, and
    only those matching patterns when patterns are given."""
    dests = target_destinations(root)
    keep, skipped = [], 0
    for f in files:
        p = pathlib.Path(f)
        parts = pathlib.PurePosixPath(f).parts
        if (
            set(parts) & SYNCED_COPIES
            or parts[-1] in LOCKFILES
            or (patterns and not matches(f, patterns))
            or not p.is_file()
        ):
            skipped += 1
            continue
        if dests:
            rp = p.resolve()
            if any(rp == d or d in rp.parents for d in dests):
                skipped += 1
                continue
        try:
            with open(p, "rb") as fh:
                head = fh.read(8192)
        except OSError:
            skipped += 1
            continue
        if b"\0" in head:
            skipped += 1
            continue
        keep.append(f)
    return keep, skipped


def ascii_hits(files: list) -> list:
    """(file, line number) for every line holding a byte above 127."""
    hits = []
    for f in files:
        try:
            data = pathlib.Path(f).read_bytes()
        except OSError:
            continue
        for i, line in enumerate(data.split(b"\n"), 1):
            if any(b > 127 for b in line):
                hits.append((f, i))
    return hits


def ascii_exceptions(root: pathlib.Path = ROOT) -> list:
    """(id, scopes) of every active exception to the every-file ASCII rule in standards-local/exceptions.md.
    The exceptions checker owns the table's validation; an expired row excepts nothing."""
    checker = (HERE if root == ROOT else root / "scripts") / "check-exceptions.py"
    if not checker.is_file() or not (root / "standards-local" / "exceptions.md").is_file():
        return []
    r = subprocess.run(
        [sys.executable, str(checker), "--json"], capture_output=True, text=True, timeout=120
    )
    try:
        rows = json.loads(r.stdout).get("exceptions", [])
    except ValueError:
        return []
    out = []
    for e in rows:
        if e.get("rule") == ASCII_RULE and (e.get("days_left") is None or e["days_left"] >= 0):
            out.append((e.get("id", "?"), listed(e.get("scope", ""))))
    return out


def excepted_by(path: str, exceptions: list) -> str | None:
    if matches(path, SCRIPT_PATTERNS):
        return None
    for eid, scopes in exceptions:
        for sc in scopes:
            sc = sc.rstrip("/")
            if path == sc or path.startswith(sc + "/") or fnmatch.fnmatch(path, sc):
                return eid
    return None


def ascii_ignore_rows(path: pathlib.Path | None = None) -> tuple:
    """([(path, reason)], [problem]) from the `ascii_ignore` section of standards-local/parameters.md: the
    table under a heading that starts with ascii_ignore, columns Path and Reason. A row with no reason is
    a problem and ignores nothing. Absent section: nothing ignored (the default)."""
    f = path or PARAMETERS
    if not f.is_file():
        return [], []
    rows, problems, inside = [], [], False
    for line in f.read_text(encoding="utf8").splitlines():
        if line.lstrip().startswith("#"):
            inside = line.lstrip("# ").strip().lower().startswith("ascii_ignore")
            continue
        s = line.strip()
        if not inside or not (s.startswith("|") and s.endswith("|")):
            continue
        cells = [c.strip().strip("`") for c in s.strip("|").split("|")]
        if len(cells) < 2 or set(cells[0]) <= set("-: ") or cells[0].lower() == "path":
            continue
        if not cells[0]:
            continue
        if not cells[1] or cells[1].startswith("<!--"):
            problems.append(f"ascii_ignore row {cells[0]!r} has no reason")
        else:
            rows.append((cells[0], cells[1]))
    return rows, problems


def ascii_ignored(path: str, rows: list) -> str | None:
    """The reason a listed path is ignored, else None. A listed directory covers what is under it; a
    script or XAML file is never ignorable (it stays under its own rule)."""
    if matches(path, SCRIPT_PATTERNS):
        return None
    for pat, reason in rows:
        pat = pat.rstrip("/")
        if path == pat or path.startswith(pat + "/") or fnmatch.fnmatch(path, pat):
            return reason
    return None


def cmd_ascii(argv: list) -> int:
    """Every tracked text file is plain ASCII (pr-review-and-merge.md 1.19). The ASCII patterns parameter
    narrows the files; a narrowed list is printed on every run so it is never silent."""
    patterns = listed(parameter("ASCII check patterns"))
    files, skipped = ascii_candidates(tracked(), patterns or None)
    ignore, ignore_problems = ascii_ignore_rows()
    for pr in ignore_problems:
        say(f"::error::ascii: {pr} (an ascii_ignore row needs a reason)")
    kept = []
    for f in files:
        why = ascii_ignored(f, ignore)
        if why:
            skipped += 1
            say(f"ascii: {f} ignored by ascii_ignore ({why})")
        else:
            kept.append(f)
    files = kept
    exceptions = ascii_exceptions()
    n, excused = len(ignore_problems), 0
    for f, i in ascii_hits(files):
        eid = excepted_by(f, exceptions)
        if eid:
            excused += 1
            say(f"::warning file={f},line={i}::ascii: byte above 127 (excepted by {eid})")
        else:
            n += 1
            say(f"::error file={f},line={i}::ascii: byte above 127")
    scope = (
        f"matching {', '.join(patterns)} (narrowed by the ASCII patterns parameter)"
        if patterns
        else "tracked text"
    )
    say(
        f"ascii: {len(files)} {scope} file(s), {skipped} skipped (binary, synced copy, lockfile"
        + (" or outside the patterns" if patterns else "")
        + "), "
        f"{n} line(s) with a byte above 127, {excused} excepted"
    )
    return 1 if n else 0


def major(v: str) -> str | None:
    m = re.search(r"(\d+)", v or "")
    return m.group(1) if m else None


def cmd_node_pin(argv: list) -> int:
    seen = []  # (place, major)
    want = major(parameter("Node major"))
    for name in (".nvmrc", ".node-version"):
        p = pathlib.Path(name)
        if p.is_file():
            seen.append((name, major(p.read_text(encoding="utf8"))))
    pkg = pathlib.Path("package.json")
    if pkg.is_file():
        try:
            eng = (json.loads(pkg.read_text(encoding="utf8")).get("engines") or {}).get("node")
        except ValueError:
            eng = None
        if eng:
            seen.append(("package.json engines.node", major(eng)))
    for wf in sorted(pathlib.Path(".github/workflows").glob("*.y*ml")):
        for i, line in enumerate(wf.read_text(encoding="utf8").splitlines(), 1):
            m = re.match(r'^\s*node-version:\s*["\']?([^"\'#\s]+)', line)
            if m and "${{" not in m.group(1):
                seen.append((f"{wf}:{i}", major(m.group(1))))
    if not seen and not want:
        say(
            "::error::node-pin: no Node pin found (.nvmrc, .node-version, engines.node or a workflow node-version)"
        )
        return 1
    want = want or seen[0][1]
    bad = [(place, v) for place, v in seen if v != want]
    for place, v in bad:
        say(f"::error::node-pin: {place} pins Node {v}, expected {want}")
    say(f"node-pin: Node {want}, {len(seen)} pin(s), {len(bad)} mismatch(es)")
    return 1 if bad else 0


SYNCED_COPIES = {"standards-core", "tokens-core", "lint-core", "kit-core"}


def ruff_configs() -> list:
    """Every tracked ruff config at any depth: ruff.toml, .ruff.toml, or a pyproject.toml with [tool.ruff].
    A monorepo keeps one per app, so the root alone is not enough."""
    out = subprocess.run(["git", "ls-files", "-z"], capture_output=True, text=True).stdout.split(
        "\0"
    )
    found = []
    for name in sorted(f for f in out if f):
        parts = pathlib.PurePosixPath(name).parts
        base = parts[-1]
        if set(parts) & SYNCED_COPIES:
            continue  # the core's own lint fixtures in a synced copy are not this repo's config
        if base not in ("ruff.toml", ".ruff.toml", "pyproject.toml"):
            continue
        p = pathlib.Path(name)
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf8")
        if base == "pyproject.toml" and "[tool.ruff" not in text:
            continue
        found.append((name, text))
    return found


def cmd_python_config(argv: list) -> int:
    floor = params()["python_floor"]
    want = "py" + floor.replace(".", "")
    configs = ruff_configs()
    if not configs:
        say(
            "::error::python-config: no committed ruff config (ruff.toml or [tool.ruff] in pyproject.toml)"
        )
        return 1
    bad = 0
    for name, text in configs:
        m = re.search(r'^\s*target-version\s*=\s*["\']([^"\']+)["\']', text, re.M)
        if not m:
            say(
                f"::error file={name}::python-config: {name} sets no ruff target-version (want {want})"
            )
            bad += 1
        elif m.group(1) != want:
            say(
                f"::error file={name}::python-config: {name} ruff target-version is {m.group(1)}, the floor is {want}"
            )
            bad += 1
    say(f"python-config: {len(configs)} ruff config(s), {bad} not targeting {want}")
    return 1 if bad else 0


def cmd_ruff_requirements(argv: list) -> int:
    say(f"ruff=={RUFF_VERSION} " + " ".join(f"--hash=sha256:{h}" for h in RUFF_SHA256))
    return 0


# ---------------------------------------------------------------- downloads

# A download is retried when the failure is transient: these HTTP codes (the gallery API answers 404
# once in a while for a package that exists), a network error or a timeout. Any other answer is final
# for that URL. A checksum mismatch is never retried, it means the bytes are wrong.
TRANSIENT_HTTP = frozenset({404, 408, 429, 500, 502, 503, 504})
FETCH_BACKOFF = (5, 15)  # seconds to wait after attempt 1 and 2, so 3 attempts per URL


class ChecksumError(RuntimeError):
    pass


def _reason(e: Exception) -> str:
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code} {e.reason}"
    if isinstance(e, urllib.error.URLError):
        return f"network error: {e.reason}"
    return f"{type(e).__name__}: {e}"


def _transient(e: Exception) -> bool:
    if isinstance(e, urllib.error.HTTPError):
        return e.code in TRANSIENT_HTTP
    return isinstance(e, (urllib.error.URLError, TimeoutError, OSError))


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as r:  # noqa: S310 - fixed https URL
        return r.read()


def fetch(url: str, sha256: str, fallback: str = "", label: str = "download") -> bytes:
    """Download url (then fallback, when given) and verify the checksum. Transient failures are retried
    with a short backoff. The checksum is checked once on the bytes received and a mismatch fails at
    once, with no retry and no fallback."""
    errors = []
    for target in [u for u in (url, fallback) if u]:
        tries = len(FETCH_BACKOFF) + 1
        for n in range(1, tries + 1):
            try:
                data = _get(target)
            except Exception as e:  # noqa: BLE001 - classified below, anything unexpected is re-raised
                if not _transient(e):
                    if not isinstance(e, urllib.error.HTTPError):
                        raise
                    say(f"{label}: {target} failed: {_reason(e)} (not retryable)")
                    errors.append(f"{target}: {_reason(e)}")
                    break
                say(f"{label}: attempt {n} of {tries} failed: {_reason(e)} ({target})")
                errors.append(f"{target}: {_reason(e)}")
                if n < tries:
                    time.sleep(FETCH_BACKOFF[n - 1])
                continue
            got = hashlib.sha256(data).hexdigest()
            if got != sha256:
                raise ChecksumError(f"checksum mismatch for {target}: got {got}")
            return data
        if target != fallback and fallback:
            say(f"{label}: falling back to {fallback}")
    raise RuntimeError(f"{label}: every attempt failed ({len(errors)} in all), last: {errors[-1]}")


def cmd_install_gitleaks(argv: list) -> int:
    if not argv:
        say("usage: core-ci.py install-gitleaks DIR")
        return 2
    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    if platform.system() != "Linux":
        say("::error::install-gitleaks: the pinned binary is for Linux runners")
        return 2
    url = (
        f"https://github.com/gitleaks/gitleaks/releases/download/v{GITLEAKS_VERSION}/"
        f"gitleaks_{GITLEAKS_VERSION}_linux_{arch}.tar.gz"
    )
    data = fetch(url, GITLEAKS_SHA256[arch], label="install-gitleaks")
    dest = pathlib.Path(argv[0])
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        member = tf.getmember("gitleaks")
        src = tf.extractfile(member)
        (dest / "gitleaks").write_bytes(src.read() if src else b"")
    (dest / "gitleaks").chmod(0o755)
    say(f"install-gitleaks: {GITLEAKS_VERSION} ({arch}) checksum ok")
    return 0


def cmd_install_pssa(argv: list) -> int:
    if not argv:
        say("usage: core-ci.py install-psscriptanalyzer DIR")
        return 2
    url = f"https://www.powershellgallery.com/api/v2/package/PSScriptAnalyzer/{PSSA_VERSION}"
    cdn = f"https://cdn.powershellgallery.com/packages/psscriptanalyzer.{PSSA_VERSION}.nupkg"
    data = fetch(url, PSSA_SHA256, fallback=cdn, label="install-psscriptanalyzer")
    dest = pathlib.Path(argv[0]) / "PSScriptAnalyzer"
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            name = info.filename
            if name.startswith(("_rels/", "package/")) or name.endswith(
                (".nuspec", "[Content_Types].xml")
            ):
                continue
            target = (dest / name).resolve()
            if dest.resolve() not in target.parents:
                raise RuntimeError(f"unsafe path in package: {name}")
            if name.endswith("/"):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(info))
    say(f"install-psscriptanalyzer: {PSSA_VERSION} checksum ok")
    return 0


# ---------------------------------------------------------------- secret scan


def gitleaks_config(base: str, work: pathlib.Path) -> pathlib.Path:
    """The scanner config from the base commit, or the default rules plus a path allowlist for the
    core-owned vendored copies. Never the config in the tree under scan."""
    cfg = work / "gitleaks.toml"
    text = None
    if base and base != ZERO:
        for name in (".gitleaks.toml", ".github/gitleaks.toml"):
            text = show(base, name)
            if text is not None:
                break
    if text is None:
        text = (
            "[extend]\nuseDefault = true\n\n[[allowlists]]\n"
            'description = "core-owned vendored copies, scanned in the core before release"\n'
            "paths = ['''(^|/)tokens-core/wpf/''']\n"
        )
    cfg.write_text(text, encoding="utf8")
    return cfg


def cmd_secret_scan(argv: list) -> int:
    args = list(argv)
    binary = os.environ.get("GITLEAKS") or "gitleaks"
    if "--gitleaks" in args:
        i = args.index("--gitleaks")
        binary = args[i + 1]
        del args[i : i + 2]
    if len(args) < 2:
        say("usage: core-ci.py secret-scan BASE HEAD [--gitleaks BIN]")
        return 2
    base, head = args
    if not shutil.which(binary) and not pathlib.Path(binary).is_file():
        say(f"::error::secret-scan: scanner {binary} not found; run install-gitleaks first")
        return 2
    with tempfile.TemporaryDirectory(dir=os.environ.get("RUNNER_TEMP") or None) as tmp:
        work = pathlib.Path(tmp)
        empty = work / "no-ignore"
        empty.mkdir()
        cfg = gitleaks_config(base, work)
        cmd = [
            binary,
            "git",
            ".",
            "--no-banner",
            "--redact",
            "--exit-code",
            "1",
            "--config",
            str(cfg),
            "--gitleaks-ignore-path",
            str(empty),
            "--ignore-gitleaks-allow",
            "--log-opts",
            rev_range(base, head),
        ]
        env = {k: v for k, v in os.environ.items() if not k.startswith("GITLEAKS_CONFIG")}
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=1800)
    sys.stdout.write(r.stdout)
    sys.stdout.write(r.stderr)
    if r.returncode == 1:
        say(
            "::error::secret-scan: the scanner found a secret (redacted above); rotate it, then rewrite the branch"
        )
        return 1
    if r.returncode != 0:
        say(f"::error::secret-scan: the scanner failed with exit {r.returncode}")
        return 2
    say(f"secret-scan: clean ({rev_range(base, head)})")
    return 0


# ---------------------------------------------------------------- kit optional peers

# Each optional kit entry and the peer it needs. The kit root never imports one, so an app that does
# not install a peer excludes its entry from the typecheck (kit/MIGRATION.md step 0). A new optional
# entry is added here in the same change that adds it to the kit.
OPTIONAL_ENTRIES = {
    "charts": ("recharts",),
    "graph": ("@xyflow/react",),
    "api-reference": ("@scalar/api-reference-react",),
}
IMPORT_RE = re.compile(
    r"""(?:\bfrom\s*|\bimport\s*\(?\s*|@import\s+(?:url\()?\s*)["']([^"']+)["']"""
)
TS_SOURCES = (".ts", ".tsx", ".mts", ".cts", ".css")


def peer_of(spec: str) -> str | None:
    for entry, peers in OPTIONAL_ENTRIES.items():
        for peer in peers:
            if spec == peer or spec.startswith(peer + "/"):
                return entry
    return None


def resolve_import(src: pathlib.Path, spec: str) -> pathlib.Path | None:
    base = src.parent / spec
    for cand in (
        base,
        *(base.with_name(base.name + e) for e in TS_SOURCES),
        *(base / ("index" + e) for e in TS_SOURCES),
    ):
        if cand.is_file():
            return cand.resolve()
    return None


def kit_root_imports(kit: pathlib.Path) -> list:
    """(file, line, kind) for every peer import reachable from the kit root: the files outside the
    optional entries and every file they import, at any depth. An entry's own files may import its peer;
    a helper inside an entry folder that the root imports (the chart theme) must not."""
    top = kit.resolve()
    files = sorted(
        f.resolve()
        for f in kit.rglob("*")
        if f.is_file() and f.suffix in TS_SOURCES and "node_modules" not in f.parts
    )
    todo = [f for f in files if f.relative_to(top).parts[0] not in OPTIONAL_ENTRIES]
    seen, bad = set(todo), []
    while todo:
        f = todo.pop()
        for i, line in enumerate(f.read_text(encoding="utf8", errors="replace").splitlines(), 1):
            for spec in IMPORT_RE.findall(line):
                if peer_of(spec):
                    bad.append(
                        (f, i, f"imports the optional peer {spec}, reachable from the kit root")
                    )
                elif spec.startswith("."):
                    t = resolve_import(f, spec)
                    if t and t not in seen and top in t.parents:
                        seen.add(t)
                        todo.append(t)
    return sorted(bad)


def load_jsonc(text: str):
    """JSON with // and /* */ comments and trailing commas (a tsconfig), comments outside strings only."""
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
            out.append(c)
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        else:
            out.append(c)
        i += 1
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", "".join(out)))


def declared_packages(start: pathlib.Path, stop: pathlib.Path) -> set:
    """Every dependency name in the package.json files from start up to stop (a workspace root counts)."""
    names = set()
    d, stop = start.resolve(), stop.resolve()
    while True:
        pkg = d / "package.json"
        if pkg.is_file():
            try:
                data = json.loads(pkg.read_text(encoding="utf8"))
            except ValueError:
                data = {}
            for key in (
                "dependencies",
                "devDependencies",
                "peerDependencies",
                "optionalDependencies",
            ):
                names |= set((data.get(key) or {}).keys())
        if d == stop or d == d.parent or stop not in d.parents:
            break
        d = d.parent
    return names


def clean_glob(p: str) -> str:
    p = p.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    for tail in ("/**/*", "/**", "/*", "/"):
        if p.endswith(tail):
            p = p[: -len(tail)]
    return p


def tsconfig_gaps(repo: pathlib.Path, kit: pathlib.Path) -> list:
    """(tsconfig, entry) for each tsconfig that includes the whole kit copy without excluding an optional
    entry whose peer the app's package.json files do not declare."""
    gaps = []
    for name in tracked():
        parts = pathlib.PurePosixPath(name).parts
        if (
            not (parts[-1].startswith("tsconfig") and parts[-1].endswith(".json"))
            or set(parts) & SYNCED_COPIES
        ):
            continue
        cfg = repo / name
        try:
            data = load_jsonc(cfg.read_text(encoding="utf8"))
        except (OSError, ValueError):
            continue
        base = cfg.parent.resolve()
        kit_rel = clean_glob(os.path.relpath(kit.resolve(), base))
        if not any(
            isinstance(p, str) and clean_glob(p) == kit_rel for p in data.get("include") or []
        ):
            continue
        excludes = [clean_glob(str(x)) for x in data.get("exclude") or []]
        have = declared_packages(base, repo)
        for entry, peers in OPTIONAL_ENTRIES.items():
            if not all(p in have for p in peers) and f"{kit_rel}/{entry}" not in excludes:
                gaps.append((name, entry))
    return gaps


def find_tsc(start: pathlib.Path, stop: pathlib.Path) -> pathlib.Path | None:
    d, stop = start.resolve(), stop.resolve()
    while True:
        cand = d / "node_modules" / ".bin" / "tsc"
        if cand.is_file():
            return cand
        if d == stop or d == d.parent:
            return None
        d = d.parent


def cmd_kit_peers(argv: list) -> int:
    kit = pathlib.Path(argv[0]) if argv else ROOT / "kit-core"
    if not kit.is_dir():
        say(f"skip kit-peers: no kit copy at {kit}")
        return 0
    repo = pathlib.Path(git("rev-parse", "--show-toplevel").strip() or ".")
    bad = 0
    for f, i, kind in kit_root_imports(kit):
        bad += 1
        say(
            f"::error file={f},line={i}::kit-peers: {kind}; the kit root never imports an optional entry or peer"
        )
    for name, entry in tsconfig_gaps(repo, kit):
        bad += 1
        say(
            f"::error file={name}::kit-peers: {name} includes the kit copy but the app does not declare the "
            f'{entry} peer ({", ".join(OPTIONAL_ENTRIES[entry])}); add the {entry} entry to "exclude" '
            f"(kit/MIGRATION.md step 0)"
        )
    tsc = find_tsc(kit, repo)
    note = "tsc not found under the repo, static checks only"
    if tsc and not bad:
        with tempfile.TemporaryDirectory(dir=os.environ.get("RUNNER_TEMP") or None) as tmp:
            stub = pathlib.Path(tmp) / "no-peer.ts"
            stub.write_text("export {};\n", encoding="utf8")
            cfg = pathlib.Path(tmp) / "tsconfig.json"
            cfg.write_text(
                json.dumps(
                    {
                        "compilerOptions": {
                            "target": "ES2022",
                            "lib": ["ES2022", "DOM", "DOM.Iterable"],
                            "module": "ESNext",
                            "moduleResolution": "Bundler",
                            "jsx": "react-jsx",
                            "strict": True,
                            "resolveJsonModule": True,
                            "isolatedModules": True,
                            "skipLibCheck": True,
                            "noEmit": True,
                            "types": [],
                            "paths": {
                                p: [str(stub)] for peers in OPTIONAL_ENTRIES.values() for p in peers
                            },
                        },
                        "include": [str(kit.resolve())],
                        "exclude": [str((kit / e).resolve()) for e in OPTIONAL_ENTRIES],
                    }
                ),
                encoding="utf8",
            )
            r = subprocess.run(
                [str(tsc), "-p", str(cfg)], capture_output=True, text=True, timeout=600
            )
        note = "tsc passed with the optional entries excluded and their peers blocked"
        if r.returncode != 0:
            sys.stdout.write(r.stdout + r.stderr)
            bad += 1
            say(
                "::error::kit-peers: the kit copy fails tsc with the optional entries excluded and their peers blocked"
            )
    say(f"kit-peers: {bad} finding(s); {note}")
    return 1 if bad else 0


# ---------------------------------------------------------------- required checks and the merge wait


def gh_api(path: str, paginate: bool = False) -> tuple:
    """(status, data) with status 'ok', 'missing' (a 404, for example a branch with no protection) or
    'denied' (any other error, for example a plan that does not offer branch protection)."""
    cmd = ["gh", "api", "-H", "Accept: application/vnd.github+json"] + (
        ["--paginate", "--slurp"] if paginate else []
    )
    r = subprocess.run(cmd + [path], capture_output=True, text=True, timeout=120)
    if r.returncode == 0:
        try:
            return "ok", json.loads(r.stdout or "null")
        except ValueError:
            return "denied", None
    text = r.stdout + r.stderr
    return ("missing" if "HTTP 404" in text or "not protected" in text.lower() else "denied"), None


def repo_and_branch(repo: str = "", branch: str = "") -> tuple:
    if repo and branch:
        return repo, branch
    r = subprocess.run(
        [
            "gh",
            "repo",
            "view",
            *([repo] if repo else []),
            "--json",
            "nameWithOwner,defaultBranchRef",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if r.returncode != 0:
        raise RuntimeError(
            f"cannot read the repository through gh: {(r.stderr or r.stdout).strip()[:200]}"
        )
    data = json.loads(r.stdout)
    return repo or data["nameWithOwner"], branch or data["defaultBranchRef"]["name"]


def workflow_job_ids(path: pathlib.Path) -> list | None:
    """Job ids of a workflow file, or None when it does not exist."""
    if not path.is_file():
        return None
    jobs, inside = [], False
    for line in path.read_text(encoding="utf8").splitlines():
        if re.match(r"^jobs:\s*$", line):
            inside = True
            continue
        if inside and re.match(r"^\S", line):
            inside = False
        m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line) if inside else None
        if m:
            jobs.append(m.group(1))
    return jobs


# The reusable form of core-ci.yml (.github/workflows/core-ci-reusable.yml in the core): a caller job's check
# name is "<caller job name or id> / core-checks", the name GitHub gives a job that calls a reusable workflow.
REUSABLE_JOB = "core-checks"
REUSABLE_CALL = re.compile(
    r"^\s+uses:\s*[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/\.github/workflows/core-ci-reusable\.yml@\S+"
)


def is_reusable_caller(text: str) -> bool:
    """True when a workflow file calls the core's reusable core-ci workflow."""
    return any(REUSABLE_CALL.match(line) for line in text.splitlines())


def workflow_check_names(path: pathlib.Path) -> list | None:
    """The check name of every job of a workflow file (its name: when set, else its id), or None when the
    file does not exist. A name with an expression in it is kept as written."""
    if not path.is_file():
        return None
    names, inside, current, calls = [], False, None, set()
    for line in path.read_text(encoding="utf8").splitlines():
        if re.match(r"^jobs:\s*$", line):
            inside = True
            continue
        if inside and re.match(r"^\S", line):
            inside = False
        if not inside:
            continue
        m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if m:
            current = len(names)
            names.append(m.group(1))
            continue
        if current is not None and REUSABLE_CALL.match(line):
            calls.add(current)
        m = re.match(r"^    name:\s*(.+?)\s*(#.*)?$", line)
        if m and current is not None:
            names[current] = m.group(1).strip("'\"")
    # A job that calls the reusable workflow reports as "<caller job> / <called job>".
    return [f"{n} / {REUSABLE_JOB}" if i in calls else n for i, n in enumerate(names)]


# Every core-ci.yml job id and check name carries this prefix (v0.77.0), so no core-ci check shares a
# name with a job of the repo's own workflows (a merge gate keyed on check names read two jobs called
# python as one).
JOB_PREFIX = "core-"
SETUP_JOBS = ("setup", JOB_PREFIX + "setup")


def core_ci_jobs(repo_root: pathlib.Path) -> list | None:
    """The check names of the core-ci.yml jobs a merge gate must require: every job but the setup helper."""
    jobs = workflow_check_names(repo_root / ".github" / "workflows" / "core-ci.yml")
    return None if jobs is None else [j for j in jobs if j not in SETUP_JOBS]


def required_checks_value(text: str) -> list:
    """Check names from a REQUIRED_CHECKS value in a workflow: one line (space or comma separated, quoted
    or not) or a block scalar (| or >) on the lines below it."""
    names, lines = [], text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)REQUIRED_CHECKS:\s*(.*?)\s*(#.*)?$", line)
        if not m:
            continue
        value = m.group(2).strip("'\"")
        if value[:1] in ("|", ">"):
            indent, value = len(m.group(1)), ""
            for nxt in lines[i + 1 :]:
                if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= indent:
                    break
                value += " " + nxt.strip()
        names += [n for n in re.split(r"[\s,]+", value) if n]
    return names


def gate_lists(repo_root: pathlib.Path) -> dict:
    """{workflow file: [check names]} from a REQUIRED_CHECKS value in any workflow: the merge gate a repo
    runs as a workflow where its plan has no branch protection."""
    out = {}
    for wf in sorted((repo_root / ".github" / "workflows").glob("*.y*ml")):
        names = required_checks_value(wf.read_text(encoding="utf8"))
        if names:
            out[wf.relative_to(repo_root).as_posix()] = names
    return out


GATE_LINE = re.compile(r"^(\s*)REQUIRED_CHECKS:\s*(.*?)\s*(#.*)?$")
DYNAMIC_GATE = re.compile(r"core-ci\.py[\"']?\s+required-names")


def dynamic_gates(repo_root: pathlib.Path) -> list:
    """Workflows that read the required core job names from the synced core-ci.yml at run time
    (`core-ci.py required-names`) instead of a copied list: such a gate follows a rename by itself."""
    out = []
    for wf in sorted((repo_root / ".github" / "workflows").glob("*.y*ml")):
        if DYNAMIC_GATE.search(wf.read_text(encoding="utf8")):
            out.append(wf.relative_to(repo_root).as_posix())
    return out


def fix_names(names: list, replace: dict, drop: set, add: list) -> list:
    """names with each old name swapped in place for its new one, the dropped names removed and the
    missing ones appended; order kept, no duplicates."""
    out = []
    for n in names:
        n = replace.get(n, n)
        if n not in drop and n not in out:
            out.append(n)
    return out + [a for a in add if a not in out]


def wrap_names(names: list, indent: str, width: int = 100) -> list:
    lines, cur = [], ""
    for n in names:
        if cur and len(indent) + len(cur) + 1 + len(n) > width:
            lines.append(indent + cur)
            cur = ""
        cur = f"{cur} {n}" if cur else n
    return lines + ([indent + cur] if cur else [])


def rewrite_gates(text: str, replace: dict, drop: set, add: list) -> tuple:
    """Rewrite every REQUIRED_CHECKS value in a workflow's text: (new text, [(line, replacement line)]
    for the values it cannot edit safely, e.g. an expression). A one-line value keeps its quoting and
    separator; a block scalar (| or >) keeps its indicator and indent."""
    lines = text.splitlines()
    out, manual, i = [], [], 0
    while i < len(lines):
        line = lines[i]
        m = GATE_LINE.match(line)
        if not m:
            out.append(line)
            i += 1
            continue
        pad, value, comment = m.group(1), m.group(2), m.group(3)
        tail = f"  {comment}" if comment else ""
        quote = value[0] if value[:1] in ("'", '"') and value[-1:] == value[:1] else ""
        bare = value.strip("'\"")
        if bare[:1] in ("|", ">"):
            j = i + 1
            while j < len(lines) and (
                not lines[j].strip() or len(lines[j]) - len(lines[j].lstrip()) > len(pad)
            ):
                j += 1
            body = lines[i + 1 : j]
            while body and not body[-1].strip():
                body.pop()
            names = re.split(r"[\s,]+", " ".join(b.strip() for b in body).strip())
            names = [n for n in names if n]
            if "${{" in " ".join(body):
                manual.append((i + 1, line))
                out.extend(lines[i:j])
            else:
                new = fix_names(names, replace, drop, add)
                ind = body[0][: len(body[0]) - len(body[0].lstrip())] if body else pad + "  "
                out.append(line)
                out.extend(wrap_names(new, ind))
                out.extend(lines[i + 1 + len(body) : j])
            i = j
            continue
        if "${{" in bare or "$(" in bare:
            manual.append((i + 1, line))
            out.append(line)
            i += 1
            continue
        names = [n for n in re.split(r"[\s,]+", bare) if n]
        sep = ", " if "," in bare else " "
        new = fix_names(names, replace, drop, add)
        out.append(f"{pad}REQUIRED_CHECKS: {quote}{sep.join(new)}{quote}{tail}")
        i += 1
    return "\n".join(out) + ("\n" if text.endswith("\n") else ""), manual


def remote_gate_lists(repo: str) -> dict:
    """gate_lists for a repo read through gh (its default branch), for a machine with no clone."""
    import base64

    st, listing = gh_api(f"repos/{repo}/contents/.github/workflows")
    out = {}
    for item in listing if st == "ok" and isinstance(listing, list) else []:
        name = item.get("path", "")
        if not name.endswith((".yml", ".yaml")):
            continue
        st, data = gh_api(f"repos/{repo}/contents/{name}")
        if st == "ok" and data and data.get("content"):
            names = required_checks_value(
                base64.b64decode(data["content"]).decode("utf8", "replace")
            )
            if names:
                out[name] = names
    return out


def required_contexts(repo: str, branch: str, api: dict | None = None) -> tuple:
    """(contexts, sources, notes): every check name the branch requires through branch protection or an
    active ruleset. api, when given, stands in for gh: {"protection": <the required_status_checks object
    or null>, "rules": [<the rules for the branch>]}."""
    contexts, sources, notes = set(), [], []
    if api is not None:
        prot, rules = ("ok", api.get("protection")), ("ok", api.get("rules") or [])
    else:
        prot = gh_api(f"repos/{repo}/branches/{branch}/protection/required_status_checks")
        rules = gh_api(f"repos/{repo}/rules/branches/{branch}", paginate=True)
    if prot[0] == "ok" and prot[1]:
        contexts |= set(prot[1].get("contexts") or [])
        contexts |= {c.get("context") for c in prot[1].get("checks") or [] if c.get("context")}
        sources.append("branch protection")
    elif prot[0] == "denied":
        notes.append("branch protection is not readable (the plan or the token does not allow it)")
    if rules[0] == "ok":
        flat = [
            r for page in (rules[1] or []) for r in (page if isinstance(page, list) else [page])
        ]
        for r in flat:
            if isinstance(r, dict) and r.get("type") == "required_status_checks":
                params_ = r.get("parameters") or {}
                contexts |= {
                    c.get("context")
                    for c in params_.get("required_status_checks") or []
                    if c.get("context")
                }
                if "ruleset" not in sources:
                    sources.append("ruleset")
    else:
        notes.append("rulesets are not readable")
    return contexts, sources, notes


def ruleset_command(repo: str, names: list) -> str:
    body = {
        "name": "core-ci required checks",
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": [
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": False,
                    "required_status_checks": [{"context": n} for n in names],
                },
            }
        ],
    }
    return (
        f"gh api -X POST repos/{repo}/rulesets --input - <<'EOF'\n{json.dumps(body, indent=2)}\nEOF"
    )


def required_report(
    repo_root: pathlib.Path, repo: str = "", branch: str = "", api: dict | None = None
) -> dict | None:
    """None when core-ci.yml is not installed; else its jobs, what requires checks, and the jobs nothing
    requires."""
    jobs = core_ci_jobs(repo_root)
    if jobs is None:
        return None
    if api is None:
        repo, branch = repo_and_branch(repo, branch)
    contexts, sources, notes = required_contexts(repo or "OWNER/REPO", branch or "main", api)
    gates = gate_lists(repo_root)
    dynamic = dynamic_gates(repo_root)
    gated = set(contexts)
    for names in gates.values():
        gated |= set(names)
    if dynamic:
        gated |= set(jobs)  # a gate that reads core-ci.yml itself requires every job in it
    legacy = [
        j for j in jobs if not j.startswith(JOB_PREFIX) and not j.endswith(" / " + REUSABLE_JOB)
    ]
    if any(j.endswith(" / " + REUSABLE_JOB) for j in jobs):
        notes.append(
            f"core-ci.yml calls the reusable workflow: its check reports as "
            f"{', '.join(j for j in jobs if j.endswith(' / ' + REUSABLE_JOB))}, so the gate requires that "
            f"name, not the bare {REUSABLE_JOB} of the synced template"
        )
    if legacy:
        notes.append(
            f"core-ci.yml predates the core- job names ({', '.join(legacy)}): copy the template "
            f"workflow again, then require the new names"
        )
    missing = [j for j in jobs if j not in gated]
    # A gate that still lists the old bare name of a renamed job: replace it, do not keep both.
    stale = {
        j[len(JOB_PREFIX) :]: j
        for j in missing
        if j.startswith(JOB_PREFIX) and j[len(JOB_PREFIX) :] in gated
    }
    # Per-check job names of an older core-ci.yml (each check became a step of core-checks): a gate that
    # still requires them waits for checks that no longer report, so they must be removed.
    obsolete = sorted(n for n in gated if n.startswith(JOB_PREFIX) and n not in jobs)
    if obsolete:
        notes.append(
            "the merge gate requires core-ci check names that no longer exist ("
            + ", ".join(obsolete)
            + "): require core-checks instead and remove them"
        )
    return {
        "repo": repo or "OWNER/REPO",
        "branch": branch or "main",
        "jobs": jobs,
        "sources": sources + sorted(set(gates) | set(dynamic)),
        "dynamic": dynamic,
        "notes": notes,
        "protected": "branch protection" in sources,
        "gates": gates,
        "missing": missing,
        "stale": stale,
        "obsolete": obsolete,
    }


def take(args: list, name: str, default: str = "") -> str:
    """Remove `name VALUE` from args and return VALUE (default when absent)."""
    if name not in args:
        return default
    i = args.index(name)
    if i + 1 >= len(args):
        raise RuntimeError(f"{name} needs a value")
    value = args[i + 1]
    del args[i : i + 2]
    return value


def cmd_required_names(argv: list) -> int:
    """Print the check names a merge gate must require from the synced core-ci.yml, one line, space
    separated; --github-output also writes names=... for a workflow step. A gate that reads them here
    follows a core-ci job rename with no edit of its own."""
    root = pathlib.Path(git("rev-parse", "--show-toplevel").strip() or ".")
    jobs = core_ci_jobs(root)
    if jobs is None:
        say("::error::required-names: .github/workflows/core-ci.yml is not installed")
        return 1
    line = " ".join(jobs)
    out = os.environ.get("GITHUB_OUTPUT")
    if "--github-output" in argv and out:
        with open(out, "a", encoding="utf8") as fh:
            fh.write(f"names={line}\n")
    sys.stdout.write(line + "\n")
    return 0


def fix_gate_lists(root: pathlib.Path, rep: dict) -> tuple:
    """Rewrite the REQUIRED_CHECKS list of every gate workflow to the current core-ci jobs. Returns
    (files rewritten, [(file, line, replacement line)] the script could not safely edit)."""
    replace = dict(rep["stale"])
    drop = set(rep["obsolete"]) | set(replace)
    drop -= set(replace.values())
    add = [j for j in rep["missing"] if j not in replace.values()]
    written, manual = [], []
    for wf in rep["gates"]:
        path = root / wf
        text = path.read_text(encoding="utf8")
        new, hard = rewrite_gates(text, replace, drop, add)
        if new != text:
            path.write_text(new, encoding="utf8")
            written.append(wf)
        for lineno, _ in hard:
            names = fix_names(rep["gates"][wf], replace, drop, add)
            manual.append((wf, lineno, "REQUIRED_CHECKS: " + " ".join(names)))
    return written, manual


def cmd_required_checks(argv: list) -> int:
    """Exit 0 only when every core-ci job is required. --fix rewrites a REQUIRED_CHECKS list in a
    workflow (the gate of a repo whose plan has no rulesets) and prints the branch-ruleset commands;
    --lists-only reads no remote gate and checks only a workflow list, for the offline CI step."""
    args = list(argv)
    repo, branch, api_file = take(args, "--repo"), take(args, "--branch"), take(args, "--api-json")
    lists_only = "--lists-only" in args
    api = json.loads(pathlib.Path(api_file).read_text(encoding="utf8")) if api_file else None
    if lists_only and api is None:
        api = {"protection": None, "rules": []}
    root = pathlib.Path(git("rev-parse", "--show-toplevel").strip() or ".")
    rep = required_report(root, repo, branch, api)
    if rep is None:
        say("skip required-checks: .github/workflows/core-ci.yml is not installed")
        return 0
    if lists_only and not rep["gates"] and not rep["dynamic"]:
        say("skip required-checks: no REQUIRED_CHECKS list in a workflow (the gate is a ruleset)")
        return 0
    for n in rep["notes"]:
        say(f"required-checks: note: {n}")
    if not rep["missing"] and not rep["obsolete"]:
        say(
            f"required-checks: all {len(rep['jobs'])} core-ci jobs are required ({', '.join(rep['sources'])})"
        )
        return 0
    if rep["missing"]:
        say(
            f"::error::required-checks: core-ci jobs the merge gate of {rep['repo']} ({rep['branch']}) does not "
            f"require: {', '.join(rep['missing'])}"
        )
    if rep["obsolete"]:
        say(
            f"::error::required-checks: the merge gate of {rep['repo']} ({rep['branch']}) requires core-ci "
            f"check names that no longer exist: {', '.join(rep['obsolete'])}"
        )
    if "--fix" not in args:
        say(
            "required-checks: --fix rewrites the REQUIRED_CHECKS list in a gate workflow and prints the "
            "commands that correct a ruleset or branch protection"
        )
        return 1
    if "--no-write" in args:
        # Report only: the exact replacement line of each gate list, no file changed.
        replace = dict(rep["stale"])
        drop = (set(rep["obsolete"]) | set(replace)) - set(replace.values())
        add = [j for j in rep["missing"] if j not in replace.values()]
        for wf in rep["gates"]:
            names = fix_names(rep["gates"][wf], replace, drop, add)
            say(
                f"required-checks: not rewritten ({wf}); replace the list with: REQUIRED_CHECKS: "
                + " ".join(names)
            )
        return 1
    written, manual = fix_gate_lists(root, rep) if rep["gates"] else ([], [])
    for wf in written:
        say(f"required-checks: rewrote REQUIRED_CHECKS in {wf} (review the diff and commit it)")
    for wf, lineno, line in manual:
        say(
            f"required-checks: cannot safely edit REQUIRED_CHECKS at {wf}:{lineno} (not a plain list); "
            f"replace it with: {line}"
        )
    if lists_only:
        return 1 if manual else 0
    say("Run the rest yourself; this script never changes a ruleset or branch protection.")
    if rep["obsolete"] and rep["protected"]:
        for n in rep["obsolete"]:
            say(
                f"gh api -X DELETE repos/{rep['repo']}/branches/{rep['branch']}/protection/required_status_checks/contexts "
                f"-f 'contexts[]={n}'"
            )
    if rep["stale"] and not written:
        say(
            "The gate still requires the old core-ci job names. Replace each, and remove the old one once no "
            "open pull request needs it (a repo job with the same name keeps its own entry):"
        )
        for old, new in sorted(rep["stale"].items()):
            say(f"  {old} -> {new}")
    if rep["protected"] and rep["missing"]:
        say(
            f"gh api -X POST repos/{rep['repo']}/branches/{rep['branch']}/protection/required_status_checks/contexts "
            + " ".join(f"-f 'contexts[]={n}'" for n in rep["missing"])
        )
    if not rep["gates"] or not written:
        say("Or a ruleset that requires every core-ci job:")
        say(ruleset_command(rep["repo"], rep["jobs"]))
    say(
        "Order: a job the gate newly requires must already run on the default branch, or every pull "
        "request waits on a check that never reports. Merge the workflow that adds the job first, then "
        "the gate change."
    )
    after = required_report(root, repo, branch, api)
    return 1 if manual or (after and (after["missing"] or after["obsolete"])) else 0


GREEN = {"success", "skipped", "neutral"}


def checks_verdict(runs: list, statuses: list, expect: list) -> tuple:
    """('wait' | 'fail' | 'green', detail) for the check runs [(name, status, conclusion)] and commit
    statuses [(context, state)] on one sha. Green needs at least one check, every check completed as
    success, skipped or neutral, and every expected name present."""
    failed = [n for n, st, c in runs if st == "completed" and (c or "") not in GREEN]
    failed += [n for n, state in statuses if state in ("failure", "error")]
    if failed:
        return "fail", "failed: " + ", ".join(sorted(set(failed)))
    pending = [n for n, st, _ in runs if st != "completed"] + [
        n for n, state in statuses if state == "pending"
    ]
    if pending:
        return "wait", "running: " + ", ".join(sorted(set(pending)))
    names = {n for n, _, _ in runs} | {n for n, _ in statuses}
    if not names:
        return "wait", "no check has started yet"
    absent = [e for e in expect if e not in names]
    if absent:
        return "wait", "not started yet: " + ", ".join(absent)
    return "green", f"{len(names)} check(s) green"


def read_checks(repo: str, sha: str) -> tuple:
    """The newest check run per name, and the commit statuses, on one sha."""
    st, pages = gh_api(f"repos/{repo}/commits/{sha}/check-runs?per_page=100", paginate=True)
    if st != "ok":
        raise RuntimeError(f"cannot read the check runs of {sha[:12]}")
    latest = {}
    for page in pages if isinstance(pages, list) else [pages]:
        for c in (page or {}).get("check_runs", []):
            name = c.get("name")
            if name not in latest or (c.get("id") or 0) > latest[name][0]:
                latest[name] = (c.get("id") or 0, c.get("status"), c.get("conclusion"))
    st, data = gh_api(f"repos/{repo}/commits/{sha}/status")
    statuses = (
        [(s.get("context"), s.get("state")) for s in (data or {}).get("statuses", [])]
        if st == "ok"
        else []
    )
    return [(k, v[1], v[2]) for k, v in latest.items()], statuses


def check_counts(runs: list, statuses: list) -> tuple:
    """(done, pending, failed) over the check runs and commit statuses of one sha."""
    done = pending = failed = 0
    for _, st, c in runs:
        if st != "completed":
            pending += 1
        elif (c or "") in GREEN:
            done += 1
        else:
            failed += 1
    for _, state in statuses:
        if state == "pending":
            pending += 1
        elif state in ("failure", "error"):
            failed += 1
        else:
            done += 1
    return done, pending, failed


PROGRESS_EVERY = 300.0


def wait_loop(
    read,
    expect: list,
    timeout: float,
    interval: float,
    settle: int,
    sleep=None,
    clock=None,
    every: float = PROGRESS_EVERY,
) -> int:
    """Poll until green on settle consecutive reads of the same set of checks (a workflow that registers
    late restarts the count), until a check fails, or until the timeout. While it waits it prints one
    progress line at most every `every` seconds (done, pending, failed), so a long wait is visible in a
    caller that streams the output (the nightly)."""
    import time

    sleep = sleep or time.sleep
    clock = clock or time.monotonic
    start, seen, streak = clock(), None, 0
    last_progress = start
    while True:
        runs, statuses = read()
        verdict, detail = checks_verdict(runs, statuses, expect)
        now = clock()
        if verdict == "wait" and every and now - last_progress >= every:
            done, pending, failed = check_counts(runs, statuses)
            say(
                f"wait-checks: progress {int((now - start) // 60)} min: {done} done, {pending} pending, "
                f"{failed} failed"
            )
            sys.stdout.flush()
            last_progress = now
        if verdict == "fail":
            say(f"::error::wait-checks: {detail}; not merging")
            return 1
        names = frozenset([n for n, _, _ in runs] + [n for n, _ in statuses])
        if verdict == "green":
            streak = streak + 1 if names == seen else 1
            seen = names
            if streak >= settle:
                say(f"wait-checks: {detail}")
                return 0
        else:
            streak, seen = 0, None
        if clock() - start >= timeout:
            say(f"::error::wait-checks: timed out ({detail}); not merging")
            return 1
        sleep(interval)


def cmd_wait_checks(argv: list) -> int:
    args = list(argv)
    repo = take(args, "--repo", os.environ.get("GITHUB_REPOSITORY", ""))
    timeout = float(take(args, "--timeout", "60")) * 60
    interval = float(take(args, "--interval", "30"))
    settle = int(take(args, "--settle", "2"))
    every = float(take(args, "--progress", str(PROGRESS_EVERY / 60))) * 60
    if not args:
        say(
            "usage: core-ci.py wait-checks SHA [--repo R] [--timeout MIN] [--interval SEC] [--settle N] "
            "[--progress MIN]"
        )
        return 2
    sha = args[0]
    repo = repo or repo_and_branch()[0]
    root = pathlib.Path(git("rev-parse", "--show-toplevel", check=False).strip() or ".")
    expect = core_ci_jobs(root) or []
    say(
        f"wait-checks: {repo}@{sha[:12]}, expecting {', '.join(expect) or 'any check'}, timeout {int(timeout // 60)} min"
    )
    return wait_loop(lambda: read_checks(repo, sha), expect, timeout, interval, settle, every=every)


# ---------------------------------------------------------------- powershell

PS_SCRIPT = r"""
param([string]$List, [string]$Analyzer)
$ErrorActionPreference = 'Stop'
$bad = 0
$files = Get-Content -LiteralPath $List
foreach ($f in $files) {
  $tokens = $null; $errs = $null
  [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path -LiteralPath $f).Path, [ref]$tokens, [ref]$errs) | Out-Null
  foreach ($e in $errs) { $bad++; Write-Output ("::error file={0},line={1}::powershell: parser error" -f $f, $e.Extent.StartLineNumber) }
}
if ($Analyzer) {
  Import-Module (Join-Path $Analyzer 'PSScriptAnalyzer/PSScriptAnalyzer.psd1') -Force
  $settings = @{ IncludeRules = @('PSUseCompatibleSyntax'); Rules = @{ PSUseCompatibleSyntax = @{ Enable = $true; TargetVersions = @('5.1', '7.0') } } }
  foreach ($f in $files) {
    foreach ($d in (Invoke-ScriptAnalyzer -Path $f -Settings $settings)) {
      $bad++; Write-Output ("::error file={0},line={1}::powershell: {2}" -f $f, $d.Line, $d.RuleName)
    }
  }
}
Write-Output ("powershell: {0} file(s), {1} finding(s)" -f $files.Count, $bad)
if ($bad) { exit 1 } else { exit 0 }
"""


def cmd_powershell(argv: list) -> int:
    analyzer = ""
    if "--analyzer" in argv:
        analyzer = argv[argv.index("--analyzer") + 1]
    files = [
        f for f in tracked() if f.endswith((".ps1", ".psm1", ".psd1")) and pathlib.Path(f).is_file()
    ]
    if not files:
        say("powershell: no tracked PowerShell files")
        return 0
    pwsh = shutil.which("pwsh")
    if not pwsh:
        say("::error::powershell: pwsh is not on the runner")
        return 2
    with tempfile.TemporaryDirectory(dir=os.environ.get("RUNNER_TEMP") or None) as tmp:
        script = pathlib.Path(tmp) / "check.ps1"
        script.write_text(PS_SCRIPT, encoding="utf8")
        lst = pathlib.Path(tmp) / "files.txt"
        lst.write_text("\n".join(files) + "\n", encoding="utf8")
        cmd = [pwsh, "-NoProfile", "-NonInteractive", "-File", str(script), "-List", str(lst)]
        if analyzer:
            cmd += ["-Analyzer", str(pathlib.Path(analyzer).resolve())]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    sys.stdout.write(r.stdout)
    sys.stdout.write(r.stderr)
    return 0 if r.returncode == 0 else 1


COMMANDS = {
    "params": cmd_params,
    "pr-title": cmd_pr_title,
    "commitlint": cmd_commitlint,
    "attribution": cmd_attribution,
    "identity": cmd_identity,
    "changelog": cmd_changelog,
    "changelog-entries": cmd_changelog_entries,
    "workflow-lint": cmd_workflow_lint,
    "ascii": cmd_ascii,
    "node-pin": cmd_node_pin,
    "python-config": cmd_python_config,
    "ruff-requirements": cmd_ruff_requirements,
    "install-gitleaks": cmd_install_gitleaks,
    "secret-scan": cmd_secret_scan,
    "install-psscriptanalyzer": cmd_install_pssa,
    "powershell": cmd_powershell,
    "kit-peers": cmd_kit_peers,
    "required-checks": cmd_required_checks,
    "required-names": cmd_required_names,
    "wait-checks": cmd_wait_checks,
}


def main(argv: list) -> int:
    if not argv or argv[0] not in COMMANDS:
        say(__doc__ or "")
        return 2
    try:
        return COMMANDS[argv[0]](argv[1:])
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as e:
        say(f"::error::core-ci {argv[0]}: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
