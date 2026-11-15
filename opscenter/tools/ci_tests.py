#!/usr/bin/env python3
"""
ci_tests.py - run the unit tests of a tree for CI, one process per test file.

Purpose: Each file runs alone, so module-level fixtures (environment variables, patched modules, a reloaded module) never leak into
         the next file. Files in the live-state list read this machine's live state (policy files, a scratch cache, sibling modules
         outside the repo), so they are skipped in CI and run only in a local gate until they are made hermetic; the skip list is
         printed on every run, so the gap is visible and never silent. Proof tests that live outside the scanned folders are listed
         and run too, and a listed file that is missing fails the run, so a rename cannot silently drop a proof from CI.
Date:    2026-11-06

Usage:   python3 ci_tests.py [--root DIR] [--config FILE]
Config:  a JSON file (default `ci-tests.json` in the root; optional):
           {"folders": ["app", "server"],            folders (relative to the root) scanned for test files; default: the root
            "patterns": ["*_test.py"],               file name patterns; default: *_test.py
            "live_state": ["slow_live_test.py"],     file names skipped in CI, listed on every run
            "proofs": ["scripts/proof_test.py"],     files run from their own folder as plain scripts, a missing one fails
            "timeout_s": 600}
Exit codes: 0 every file passed, 1 a file failed or a listed proof is missing, 2 the config cannot be read.
"""

import json
import subprocess
import sys
from pathlib import Path


def load_config(root, config_file=None):
    f = Path(config_file) if config_file else Path(root) / "ci-tests.json"
    if not f.exists():
        return {}
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"cannot read {f}: {e}") from e
    if not isinstance(d, dict):
        raise ValueError(f"{f} must hold a JSON object")
    return d


def find_tests(root, folders, patterns):
    seen, out = set(), []
    for folder in folders or ["."]:
        base = Path(root) / folder
        for pat in patterns or ["*_test.py"]:
            for p in sorted(base.glob(pat)):
                if p.is_file() and p not in seen:
                    seen.add(p)
                    out.append(p)
    return out


def run(root, config, out=print):
    """Run everything the config names. Returns (ran, failed names, skipped names)."""
    root = Path(root)
    timeout = int(config.get("timeout_s") or 600)
    live = set(config.get("live_state") or [])
    failed, skipped, ran = [], [], 0
    for f in find_tests(root, config.get("folders"), config.get("patterns")):
        rel = f.relative_to(root)
        if f.name in live:
            skipped.append(f.name)
            out(f"skip {rel}: needs live machine state, runs in the local gate")
            continue
        ran += 1
        try:
            r = subprocess.run(
                [sys.executable, "-m", "unittest", f.stem],
                cwd=f.parent,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            ok, tail = r.returncode == 0, r.stderr[-4000:]
        except subprocess.TimeoutExpired:
            ok, tail = False, f"timed out after {timeout}s"
        out(f"{'ok  ' if ok else 'FAIL'} {rel}")
        if not ok:
            failed.append(f.name)
            out(tail)
    for rel in config.get("proofs") or []:
        f = root / rel
        ran += 1
        if not f.is_file():
            out(f"FAIL {rel}: listed in proofs but missing")
            failed.append(rel)
            continue
        try:
            r = subprocess.run(
                [sys.executable, f.name],
                cwd=f.parent,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            ok, tail = r.returncode == 0, (r.stdout + r.stderr)[-4000:]
        except subprocess.TimeoutExpired:
            ok, tail = False, f"timed out after {timeout}s"
        out(f"{'ok  ' if ok else 'FAIL'} {rel}")
        if not ok:
            failed.append(rel)
            out(tail)
    out(
        f"ci_tests: {ran} file(s) run, {len(failed)} failed, {len(skipped)} live-state file(s) skipped"
    )
    for name in sorted(live - set(skipped)):
        out(f"note: {name} is in the live-state list but no such test file was found")
    return ran, failed, skipped


def main(argv):
    root, config_file = Path.cwd(), None
    args = list(argv)
    while args:
        a = args.pop(0)
        if a == "--root" and args:
            root = Path(args.pop(0))
        elif a == "--config" and args:
            config_file = args.pop(0)
        else:
            print(__doc__)
            return 2
    try:
        config = load_config(root, config_file)
    except ValueError as e:
        print(f"ci_tests: {e}")
        return 2
    _, failed, _ = run(root, config)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
