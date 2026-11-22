#!/usr/bin/env python3
"""
Purpose: The consumer upgrade step of the ops center: copy the built app and the server into a service location, restart the service and run a smoke
         check, so a nightly sync can finish an upgrade with no manual copying (a launch agent often cannot read the folder a clone lives in, so the
         service runs from a copy). Stdlib Python 3.9.
Usage:   upgrade.py --target <service dir> [--source <opscenter dir>] [--restart-cmd "<command>"] [--smoke-url <url>] [--timeout <s>] [--dry-run]
         --source       the opscenter folder of the clone (default: the folder beside this file's parent); it must hold app/dist (run the app build first)
         --target       where the service reads it from; it gets `opscenter/` (the new copy) and `opscenter.prev/` (the one it replaced)
         --restart-cmd  a shell command that restarts the service (default none: the copy is made and the caller restarts)
         --smoke-url    polled until it answers 200 with JSON, for up to --timeout seconds (default 60), after the restart
Steps:   1 stage the copy beside the target (tests, sources, node_modules and caches left out)  2 swap it in, keeping the old copy as opscenter.prev
         3 restart  4 smoke check. A failed restart or smoke check puts the old copy back, restarts again and exits 1; nothing is left half swapped.
Exit:    0 upgraded (or dry run), 1 the new copy failed and the old one was restored, 2 nothing to copy or a bad argument
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SKIP_DIRS = {
    "node_modules",
    "__pycache__",
    ".git",
    "src",
    "kit",
    "tests",
    ".pytest_cache",
    "testing",
}
SKIP_FILES = ("_test.py",)


def _ignore(directory, names):
    """Names left out of the copy: build sources, caches, tests, the python test files and the lock file."""
    return {
        n
        for n in names
        if n in SKIP_DIRS
        or n.endswith(SKIP_FILES)
        or n.endswith(".pyc")
        or n == "package-lock.json"
    }


def stage(source, target):
    """Copy `source` into `<target>/opscenter.new`. The app folder keeps only dist, public assets are inside it already."""
    dist = source / "app" / "dist"
    if not (dist / "index.html").is_file():
        raise FileNotFoundError(f"{dist} has no index.html: build the app first")
    new = target / "opscenter.new"
    shutil.rmtree(new, ignore_errors=True)
    shutil.copytree(source, new, ignore=_ignore)
    # The ignore list drops `src` everywhere, which also removes nothing the server needs; app/ keeps only its dist.
    for child in (new / "app").iterdir() if (new / "app").is_dir() else []:
        if child.name != "dist":
            shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink()
    return new


def swap(target):
    """Put opscenter.new in place, keeping the replaced copy as opscenter.prev. Returns True when there was a copy to keep."""
    live, prev, new = target / "opscenter", target / "opscenter.prev", target / "opscenter.new"
    had = live.exists()
    shutil.rmtree(prev, ignore_errors=True)
    if had:
        live.rename(prev)
    new.rename(live)
    return had


def rollback(target, had):
    live, prev = target / "opscenter", target / "opscenter.prev"
    shutil.rmtree(live, ignore_errors=True)
    if had and prev.exists():
        prev.rename(live)


def restart(cmd):
    if not cmd:
        return True
    return subprocess.run(cmd, shell=True, timeout=120).returncode == 0  # noqa: S602 - the operator's own restart command


def smoke(url, timeout_s):
    """Poll until the url answers 200 with a JSON body. A slow start is waited for, never an immediate failure."""
    if not url:
        return True
    end = time.time() + timeout_s
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=5) as r:  # noqa: S310 - the operator's own loopback url
                if r.status == 200:
                    json.loads(r.read() or b"null")
                    return True
        except (urllib.error.URLError, OSError, ValueError):
            pass
        time.sleep(1)
    return False


def main(argv=None):
    ap = argparse.ArgumentParser(prog="upgrade.py", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--target", required=True)
    ap.add_argument("--source", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--restart-cmd", default="")
    ap.add_argument("--smoke-url", default="")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    source, target = Path(a.source).resolve(), Path(a.target).resolve()
    try:
        new = stage(source, target.mkdir(parents=True, exist_ok=True) or target)
    except FileNotFoundError as e:
        print(f"upgrade: {e}", file=sys.stderr)
        return 2
    if a.dry_run:
        files = sum(1 for p in new.rglob("*") if p.is_file())
        shutil.rmtree(new, ignore_errors=True)
        print(f"upgrade: dry run, {files} files would be copied to {target / 'opscenter'}")
        return 0
    had = swap(target)
    ok = restart(a.restart_cmd) and smoke(a.smoke_url, a.timeout)
    if ok:
        print(
            f"upgrade: {target / 'opscenter'} is live"
            + (" (the previous copy is opscenter.prev)" if had else "")
        )
        return 0
    print(
        "upgrade: the new copy failed its restart or smoke check, putting the previous copy back",
        file=sys.stderr,
    )
    rollback(target, had)
    restart(a.restart_cmd)
    return 1


if __name__ == "__main__":
    sys.exit(main())
