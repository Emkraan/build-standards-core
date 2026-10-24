"""Keep a one-line core pin current in a repo that records the core as a single line in a file.

Some repos consume the core through a pin line only, for example a deploy repo whose host syncs the
pinned release at deploy time (`KEY=v1.2.3` in a plain file). Mode "pin-file" keeps that line on the
newest release. The class is approval-gated (README "Direction"): the bump arrives as a pull request
and the repo's own merge path takes it; nothing is applied to a host here.

Consumer entry (hermes/setup.py --ui OWNER/REPO=pin-file:PATH, then the keys below in the file):
  "path"     the local clone, used only for git plumbing and a throwaway worktree
  "file"     the pin file, relative to the repo root
  "key"      the line's key (default CORE_VERSION); the line is KEY=<tag>
  "after"    commands run from the worktree root after the rewrite, each a list (for example a script
             that regenerates a checksum file); a failure stops the bump
  "add"      extra paths committed with the pin (the files the "after" commands write)
  "message"  the commit and pull request title; {latest} is replaced (default
             "chore(standards): bump the core pin to {latest}")
  "metrics"  optional {"url", "job", "instance", "prefix"}: two gauges pushed to a Pushgateway in the
             text format after every check, <prefix>core_pin_behind{repo,pinned,latest} and
             <prefix>core_pin_last_check_timestamp_seconds{repo}, so a stuck bump is an alert, never
             silence. A failed push is an info line, never a failure of the bump.

What it does on each run:
  1. fetches the default branch and reads the pin from it (never from a working tree)
  2. when it equals the newest release, pushes metrics and stops
  3. when a pull request for branch chore/core-pin-<latest> is open, reports it (red CI is a problem)
  4. otherwise, in a throwaway worktree of the default branch: rewrites the line, runs "after",
     commits as the clone's git identity (refused unless it is a GitHub noreply address), pushes the
     branch with retry (ops_center.push) and opens the pull request
The worktree is always removed. Python 3.9, stdlib only.
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
from pathlib import Path
from typing import Callable

import consumption
import ops_center

Sh = Callable[..., "tuple[int, str]"]
NOREPLY = "@users.noreply.github.com"


def read_pin(text: str, key: str) -> str:
    m = re.search(rf"^{re.escape(key)}=(\S+)[ \t]*$", text, flags=re.M)
    return m.group(1) if m else ""


def rewrite(text: str, key: str, latest: str) -> str:
    return re.sub(rf"^{re.escape(key)}=\S+[ \t]*$", f"{key}={latest}", text, count=1, flags=re.M)


def metrics_body(prefix: str, repo: str, pinned: str, latest: str, now: int) -> str:
    behind = 0 if pinned == latest else 1
    return (
        f"# TYPE {prefix}core_pin_behind gauge\n"
        f'{prefix}core_pin_behind{{repo="{repo}",pinned="{pinned}",latest="{latest}"}} {behind}\n'
        f"# TYPE {prefix}core_pin_last_check_timestamp_seconds gauge\n"
        f'{prefix}core_pin_last_check_timestamp_seconds{{repo="{repo}"}} {now}\n'
    )


def push_metrics(
    m: dict, repo: str, pinned: str, latest: str, opener=urllib.request.urlopen
) -> str:
    """ "" when pushed, else one line saying why not."""
    name = repo.split("/")[-1]
    url = f"{m['url'].rstrip('/')}/metrics/job/{m.get('job', 'core_pin')}/instance/{m.get('instance', name)}"
    body = metrics_body(m.get("prefix", ""), name, pinned, latest, int(time.time())).encode()
    try:
        opener(urllib.request.Request(url, data=body, method="PUT"), timeout=10)
        return ""
    except Exception as exc:  # metrics never fail the bump
        return f"metrics not pushed ({exc})"


def apply(c: dict, latest: str, sh: Sh, check: bool = False) -> tuple[list, list]:
    """(info lines, problem lines) for one pin-file consumer."""
    repo = c["repo"]
    if not c.get("path") or not c.get("file"):
        raise RuntimeError(
            'mode "pin-file" needs "path" (the local clone) and "file" (the pin file)'
        )
    clone, key = Path(c["path"]).expanduser(), c.get("key", "CORE_VERSION")
    info: list = []
    problems: list = []
    branch = ops_center.default_branch(clone, sh)
    rc, out = sh(["git", "-C", str(clone), "fetch", "--quiet", "origin", branch])
    if rc != 0:
        return info, [f"ui {repo}: cannot fetch {branch}: {out[-200:]}"]
    rc, text = sh(["git", "-C", str(clone), "show", f"origin/{branch}:{c['file']}"])
    pinned = read_pin(text, key) if rc == 0 else ""
    if not pinned:
        return info, [f"ui {repo}: no {key}= line in {c['file']} on {branch}"]

    def metrics() -> None:
        if c.get("metrics") and not check:
            why = push_metrics(c["metrics"], repo, pinned, latest)
            if why:
                info.append(f"ui {repo}: {why}")

    if pinned == latest:
        metrics()
        return info, problems
    head = f"chore/core-pin-{latest}"
    rc, out = sh(
        [
            "gh",
            "pr",
            "list",
            "-R",
            repo,
            "--head",
            head,
            "--state",
            "open",
            "--json",
            "url,statusCheckRollup",
        ]
    )
    prs = json.loads(out) if rc == 0 and out else []
    if prs:
        ci = consumption.ci_state(prs[0].get("statusCheckRollup") or [])
        (problems if ci == "fail" else info).append(
            f"ui {repo}: pin {pinned} -> {latest} pull request open (CI {ci}): {prs[0]['url']}"
        )
        metrics()
        return info, problems
    if check:
        info.append(f"ui {repo}: pin behind ({pinned}, core is {latest}); would open {head}")
        return info, problems
    email = sh(["git", "-C", str(clone), "config", "user.email"])[1]
    if not email.endswith(NOREPLY):
        metrics()
        return info, [
            f"ui {repo}: git user.email of {clone} is not a GitHub noreply address; set it for the clone"
        ]
    wt = clone.parent / f"{clone.name}.core-pin"
    sh(["git", "-C", str(clone), "worktree", "remove", "--force", str(wt)])
    try:
        rc, out = sh(
            [
                "git",
                "-C",
                str(clone),
                "worktree",
                "add",
                "--quiet",
                "--detach",
                str(wt),
                f"origin/{branch}",
            ]
        )
        if rc != 0:
            return info, [f"ui {repo}: cannot make a worktree: {out[-200:]}"]
        pin = wt / c["file"]
        pin.write_text(rewrite(pin.read_text(encoding="utf8"), key, latest), encoding="utf8")
        for cmd in c.get("after", []):
            rc, out = sh(list(cmd), cwd=wt)
            if rc != 0:
                return info, [
                    f"ui {repo}: {' '.join(cmd)} failed after the pin rewrite: {out[-200:]}"
                ]
        msg = c.get("message", "chore(standards): bump the core pin to {latest}").replace(
            "{latest}", latest
        )
        sh(["git", "-C", str(wt), "add", "--", c["file"], *c.get("add", [])])
        rc, out = sh(["git", "-C", str(wt), "commit", "--quiet", "-m", msg])
        if rc != 0:
            return info, [f"ui {repo}: commit failed: {out[-200:]}"]
        new = sh(["git", "-C", str(wt), "rev-parse", "HEAD"])[1]
        rc, out = ops_center.push(sh, clone, "--quiet", "origin", f"{new}:refs/heads/{head}")
        if rc != 0:
            return info, [f"ui {repo}: cannot push {head}: {out[-200:]}"]
        body = (
            f"Automated pin bump: the core published {latest}. The {key} line in {c['file']}"
            + (" plus the files its regeneration writes." if c.get("after") else ".")
            + f" See the core CHANGELOG for {latest}."
        )
        body_file = clone.parent / f"{clone.name}.core-pin-body.md"
        body_file.write_text(body + "\n", encoding="utf8")
        rc, out = sh(
            [
                "gh",
                "pr",
                "create",
                "-R",
                repo,
                "--base",
                branch,
                "--head",
                head,
                "--title",
                msg,
                "--body-file",
                str(body_file),
            ]
        )
        body_file.unlink()
        if rc != 0:
            return info, [
                f"ui {repo}: pushed {head} but the pull request did not open: {out[-200:]}"
            ]
        info.append(f"ui {repo}: pin {pinned} -> {latest}, opened {out.splitlines()[-1]}")
    finally:
        sh(["git", "-C", str(clone), "worktree", "remove", "--force", str(wt)])
        metrics()
    return info, problems
