#!/usr/bin/env python3
"""
Purpose: The consumer upgrade step of the ops center: copy the built app and the server into a service location, restart the service and run a smoke
         check, so a nightly sync can finish an upgrade with no manual copying (a launch agent often cannot read the folder a clone lives in, so the
         service runs from a copy). Stdlib Python 3.9.
Usage:   upgrade.py --target <service dir> [--source <opscenter dir>] [--restart-cmd "<command>"] [--smoke-url <url> | --base-url <url> [--min-routes <n>]] [--timeout <s>] [--allow-protected] [--dry-run]
         --source       the opscenter folder of the clone (default: the folder beside this file's parent); it must hold app/dist (run the app build first)
         --target       where the service reads it from; it gets `opscenter/` (the new copy) and `opscenter.prev/` (the one it replaced)
         --restart-cmd  a shell command that restarts the service (default none: the copy is made and the caller restarts)
         --smoke-url    polled until it answers 200 with JSON, for up to --timeout seconds (default 60), after the restart
         --base-url     the full smoke check against the server root, for up to --timeout seconds: GET /api/health answers 200 with JSON, GET /api/routes
                        reports at least --min-routes routes (default 1, a module that failed to load shows as fewer), and GET / renders the page (HTML with
                        a root element) and every /assets/ file it names answers 200
         --allow-protected  go on when --target is inside a macOS protected folder (Documents, Desktop, Downloads), which a launch agent cannot read
Steps:   1 stage the copy beside the target (tests, sources, node_modules and caches left out)  2 swap it in, keeping the old copy as opscenter.prev
         3 restart  4 smoke check. A failed restart or smoke check puts the old copy back, restarts again and exits 1; nothing is left half swapped.
Exit:    0 upgraded (or dry run), 1 the new copy failed and the old one was restored, 2 nothing to copy, a bad argument, or a protected target
"""

import argparse
import json
import re
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
PLATFORM = sys.platform
# macOS asks the user before a process outside their session reads these, and a launch agent is never asked, so it sees them empty or denied.
PROTECTED = ("Documents", "Desktop", "Downloads")


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


def protected_folder(target, home=None, platform=None):
    """The macOS protected folder `target` is inside, or None. Only macOS has them, so any other platform answers None."""
    if (platform or PLATFORM) != "darwin":
        return None
    home, target = Path(home or Path.home()).resolve(), Path(target).resolve()
    for name in PROTECTED:
        folder = (
            home / name
        ).resolve()  # a synced Documents folder is a link to somewhere else, the target resolves the same way
        if target == folder or folder in target.parents:
            return name
    return None


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


def _get(url, timeout_s=5):
    """(status, content type, body bytes) for a GET, or None when nothing answered."""
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as r:  # noqa: S310 - the operator's own loopback url
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except (urllib.error.URLError, OSError, ValueError):
        return None


def site_problem(base, min_routes):
    """None when the server at `base` is healthy, else one line saying what is wrong: health, the route count, the page and its assets."""
    base = base.rstrip("/")
    got = _get(base + "/api/health")
    if not got or got[0] != 200:
        return "/api/health did not answer 200"
    try:
        json.loads(got[2] or b"null")
    except ValueError:
        return "/api/health did not answer JSON"
    got = _get(base + "/api/routes")
    try:
        count = json.loads(got[2])["count"] if got and got[0] == 200 else None
    except (ValueError, KeyError, TypeError):
        count = None
    if not isinstance(count, int):
        return "/api/routes did not report a route count"
    if count < min_routes:
        return f"/api/routes reports {count} routes, expected at least {min_routes}"
    got = _get(base + "/")
    if not got or got[0] != 200 or "html" not in got[1].lower():
        return "/ did not render the page"
    html = got[2].decode("utf-8", "replace")
    if 'id="root"' not in html and "id='root'" not in html:
        return "/ is HTML without the app root element"
    for asset in sorted(set(re.findall(r"""(?:src|href)=["'](/assets/[^"'?#]+)""", html))):
        got = _get(base + asset)
        if not got or got[0] != 200:
            return f"{asset} did not answer 200"
    return None


def smoke_site(base, min_routes, timeout_s):
    """Poll site_problem until it is None. A slow start is waited for. The last problem is printed when time runs out."""
    end = time.time() + timeout_s
    problem = "no answer"
    while time.time() < end:
        problem = site_problem(base, min_routes)
        if problem is None:
            return True
        time.sleep(1)
    print(f"upgrade: smoke check failed: {problem}", file=sys.stderr)
    return False


def main(argv=None):
    ap = argparse.ArgumentParser(prog="upgrade.py", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--target", required=True)
    ap.add_argument("--source", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--restart-cmd", default="")
    ap.add_argument("--smoke-url", default="")
    ap.add_argument("--base-url", default="")
    ap.add_argument("--min-routes", type=int, default=1)
    ap.add_argument("--allow-protected", action="store_true")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    source, target = Path(a.source).resolve(), Path(a.target).resolve()
    held = protected_folder(target)
    if held and not a.allow_protected:
        print(
            f"upgrade: {target} is inside {held}, which a launch agent cannot read on macOS. Choose a service location outside Documents, "
            "Desktop and Downloads, or pass --allow-protected if the service has been granted that access.",
            file=sys.stderr,
        )
        return 2
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
    if ok and a.base_url:
        ok = smoke_site(a.base_url, a.min_routes, a.timeout)
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
