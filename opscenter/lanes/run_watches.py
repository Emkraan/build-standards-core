#!/usr/bin/env python3
"""
run_watches.py

Purpose: Two watches on the CI runs of a repository, each raising one Action Center item while its condition holds and clearing it
         when a later run succeeds, so red never hides for days in a job nobody opens.
           main   The newest completed run of a watched deploy or apply workflow on main decides. A failure or a timeout raises one
                  item with the workflow, the failed job, its first error line and the run link. A later success closes it.
                  Cancelled and skipped runs do not count either way (a cancelled run says nothing).
           drift  A nightly drift workflow. When the newest `min_streak` (default 2) scheduled runs on main all failed, one item
                  names each failing job and its error lines; it updates while the streak grows and closes when a scheduled run
                  succeeds. A manual run (workflow_dispatch) and a run on any other branch never count, so a fix tried by hand does
                  not hide a red night and a red branch does not raise one.
         An item exists only while the condition holds (its key is stable), so the board's key guard never shows a duplicate. A watch
         that cannot be read is itself an item ("unknown", never clear): a source that cannot be read never reads as good.
Date:    2026-11-06

Config:  OPSCENTER_RUN_WATCHES, a JSON file:
           {"watches": [{"kind": "main" | "drift", "repo": "owner/name", "workflow": "apply.yml", "label": "Platform apply",
                         "branch": "main", "min_streak": 2, "owner": "Owner name"}]}
         No file, or no watches: no items.
Usage:   run_watches.py items       print the items as JSON (a cron or the server calls collect())
Slots:   the code host read is `gh(args) -> parsed JSON` (or text with raw=True); nothing here names an estate.
"""

import contextlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gh_run_jobs import run_jobs  # noqa: E402

FAILED = {"failure", "timed_out", "startup_failure"}
IGNORED = {"cancelled", "skipped", "neutral", "stale"}
ERR_LINE = re.compile(r"##\[error\]|(?:^|\s)(?:Error|FATAL|fatal)\b|Traceback|failed", re.I)


def real_runs(runs, branch="main", events=None):
    """Completed runs on `branch`, newest first, without the cancelled and skipped ones (they say nothing). `events` keeps only
    those triggers (the drift watch keeps `schedule`)."""
    out = [
        r
        for r in runs
        if r.get("status") == "completed"
        and (r.get("headBranch") or branch) == branch
        and (r.get("conclusion") or "") not in IGNORED
        and (events is None or r.get("event") in events)
    ]
    return sorted(out, key=lambda r: r.get("createdAt") or "", reverse=True)


def first_error(log_text, limit=2):
    """The first error line(s) of a job log, without timestamps and annotations."""
    out = []
    for ln in (log_text or "").splitlines():
        if ERR_LINE.search(ln):
            ln = re.sub(r"^\d{4}-\d\d-\d\dT[\d:.]+Z\s*", "", ln).replace("##[error]", "").strip()
            if ln and ln not in out:
                out.append(ln[:240])
        if len(out) >= limit:
            break
    return out


def failed_jobs(gh, repo, run_id):
    """[{name, steps, errors}] for the failed jobs of a run: the failed step names and the first error lines of the log."""
    out = []
    for j in run_jobs(gh, repo, run_id):
        if (j.get("conclusion") or "") not in FAILED:
            continue
        errs = []
        with contextlib.suppress(
            Exception
        ):  # a log that cannot be read leaves the job without error lines
            errs = first_error(gh(["api", f"repos/{repo}/actions/jobs/{j['id']}/logs"], raw=True))
        steps = [
            s.get("name") for s in j.get("steps") or [] if (s.get("conclusion") or "") in FAILED
        ]
        out.append({"name": j.get("name"), "steps": steps, "errors": errs})
    return out


def _item(w, key, title, why, action, runs):
    owner = w.get("owner") or ""
    return {
        "key": key,
        "priority": "high",
        "title": title,
        "why": why,
        "action": action,
        "owner": owner,
        "refs": [f"run {r['databaseId']}" for r in runs if r.get("databaseId")][:4],
        "sources": ["Run watches"],
        "links": [
            {"label": f"run {r['databaseId']}", "url": r.get("url")} for r in runs if r.get("url")
        ][:4],
    }


def _describe(jobs):
    lines = []
    for j in jobs:
        step = f" (step {', '.join(j['steps'])})" if j["steps"] else ""
        err = f": {j['errors'][0]}" if j["errors"] else ""
        lines.append(f"{j['name']}{step}{err}")
    return "; ".join(lines) or "no failed job could be read"


def main_item(w, runs, gh):
    """The main watch item for one workflow, or None when the newest counted run succeeded (or none exists)."""
    rs = real_runs(runs, w.get("branch") or "main")
    if not rs or rs[0].get("conclusion") not in FAILED:
        return None
    run = rs[0]
    jobs = failed_jobs(gh, w["repo"], run["databaseId"])
    word = "timed out" if run.get("conclusion") == "timed_out" else "failed"
    return _item(
        w,
        f"main-watch-{w['workflow']}",
        f"{w.get('label') or w['workflow']} {word} on {w.get('branch') or 'main'}",
        f"The newest completed run of {w['workflow']} on {w.get('branch') or 'main'} {word}: {_describe(jobs)}. A later green run closes this.",
        "Open the run, fix the cause and re-run it, or revert the change that broke it.",
        [run],
    )


def drift_item(w, runs, gh):
    """The drift watch item, or None when fewer than `min_streak` scheduled runs in a row failed."""
    need = int(w.get("min_streak") or 2)
    rs = real_runs(runs, w.get("branch") or "main", events={"schedule"})
    streak = []
    for r in rs:
        if r.get("conclusion") in FAILED:
            streak.append(r)
        else:
            break
    if len(streak) < need:
        return None
    jobs = failed_jobs(gh, w["repo"], streak[0]["databaseId"])
    return _item(
        w,
        f"drift-watch-{w['workflow']}",
        f"{w.get('label') or w['workflow']} has been red for {len(streak)} nights",
        f"The last {len(streak)} scheduled runs of {w['workflow']} on {w.get('branch') or 'main'} failed. Newest: {_describe(jobs)}. A scheduled run that succeeds closes this.",
        "Open the newest run, find what drifted and fix it; a manual run does not clear it, only a scheduled success does.",
        streak[:4],
    )


def list_runs(gh, repo, workflow, branch):
    return (
        gh(
            [
                "run",
                "list",
                "-R",
                repo,
                "--workflow",
                workflow,
                "--branch",
                branch,
                "--limit",
                "30",
                "--json",
                "databaseId,status,conclusion,event,headBranch,createdAt,url",
            ]
        )
        or []
    )


def collect(config, gh, runs_for=None):
    """Every item the configured watches raise now. `runs_for(w)` replaces the code host read (tests)."""
    out = []
    for w in (config or {}).get("watches") or []:
        try:
            if w.get("kind") not in ("main", "drift") or not w.get("repo") or not w.get("workflow"):
                raise ValueError("a watch needs kind main or drift, a repo and a workflow")
            runs = (
                runs_for(w)
                if runs_for
                else list_runs(gh, w["repo"], w["workflow"], w.get("branch") or "main")
            )
            it = (main_item if w["kind"] == "main" else drift_item)(w, runs, gh)
        except Exception as e:  # noqa: BLE001 - a watch that cannot be read is never clear
            it = _item(
                w if isinstance(w, dict) else {},
                f"run-watch-unread-{(w or {}).get('workflow', 'x') if isinstance(w, dict) else 'x'}",
                f"The watch on {(w or {}).get('workflow', 'a workflow') if isinstance(w, dict) else 'a workflow'} could not be read",
                f"Its runs could not be read ({str(e)[:160]}), so it is unknown, not fine.",
                "Check the code host sign-in and the watch config.",
                [],
            )
            it["priority"] = "medium"
        if it:
            out.append(it)
    return out


def load_config():
    f = os.environ.get("OPSCENTER_RUN_WATCHES", "").strip()
    if not f:
        return {}
    try:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {
            "watches": [{"kind": "unreadable-config"}]
        }  # a config that cannot be read is an item, not silence
    return d if isinstance(d, dict) else {}


def _gh(args, raw=False):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise RuntimeError((r.stderr or r.stdout).strip()[:200])
    return r.stdout if raw else json.loads(r.stdout or "null")


def main(argv):
    if argv[:1] == ["items"]:
        print(json.dumps(collect(load_config(), _gh), indent=2))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
