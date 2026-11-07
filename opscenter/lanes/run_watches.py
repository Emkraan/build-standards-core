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
         Error lines: the first `Error:` line of the failed job's log, else its first `##[error]` annotation; the runner's
         exit code line is never one, and the word failed in ordinary output never matches.
         API budget: a failed run's jobs and logs are read once and cached by repo, run id and attempt (bounded, newest 20),
         so a run that stays red costs one runs list per collect. A log that could not be read is read again next time.
Date:    2026-11-06, 2026-11-07 (error line rule and jobs cache)

Config:  OPSCENTER_RUN_WATCHES, a JSON file:
           {"watches": [{"kind": "main" | "drift", "repo": "owner/name", "workflow": "apply.yml", "label": "Platform apply",
                         "branch": "main", "min_streak": 2, "owner": "Owner name"}],
            "cache_file": "/path/run-watches-cache.json"}
         No file, or no watches: no items. cache_file is optional: without it the cache lives as long as the process (a
         server calling collect() keeps it, the `items` CLI reads afresh each time).
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
ERR_LIMIT = (
    3  # error lines kept per job (the main item shows the first, the drift item all of them)
)
LINE_MAX = 240
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
STAMP = re.compile(r"^\S*\d{4}-\d\d-\d\dT[\d:.]+Z\s?")
ERROR = re.compile(r"\bError:\s*(\S.*)")
ANNOT = "##[error]"
NOISE = re.compile(r"Process completed with exit code \d+\.?")
CACHE_KEEP = 20  # failed runs whose jobs are kept in the cache


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


def first_error(log_text, limit=ERR_LIMIT):
    """The error lines of a job log, best first, without timestamps, colour codes and annotations.

    The first is the first `Error:` line outside an annotation (terraform prints `| Error: ...`, the box prefix is dropped);
    with none, the first `##[error]` annotation. The other `##[error]` annotations follow. The runner's own
    `Process completed with exit code N.` line is never returned, so a log with only that line gives []. Nothing else matches:
    the word failed in ordinary output is not an error line."""
    best, annots = "", []
    for raw in (log_text or "").splitlines():
        line = STAMP.sub("", ANSI.sub("", raw))
        if ANNOT in line:
            msg = line.split(ANNOT, 1)[1].strip()
            if msg and not NOISE.fullmatch(msg) and msg[:LINE_MAX] not in annots:
                annots.append(msg[:LINE_MAX])
            continue
        m = ERROR.search(line)
        if m and not best:
            best = ("Error: " + m.group(1).strip())[:LINE_MAX]
    out = [best] if best else []
    out += [a for a in annots if a != best]
    return out[:limit]


def _job_log(gh, repo, job_id):
    """The raw log of one job. gh refuses a log with terminal escape sequences unless told to allow them; a gh too old to know
    that flag is asked again without it."""
    path = f"repos/{repo}/actions/jobs/{job_id}/logs"
    try:
        return gh(["api", "--allow-escape-sequences", path], raw=True)
    except Exception as e:  # noqa: BLE001 - each caller has its own gh error class
        if "unknown flag" not in str(e):
            raise
        return gh(["api", path], raw=True)


def read_failed_jobs(gh, repo, run_id):
    """([{name, steps, errors}], logs_ok) for the failed jobs of a run: the failed step names and the error lines of the log.
    A log that cannot be read leaves its job without error lines (the job is still listed) and logs_ok false. A jobs read
    that fails raises, so it is never mistaken for a run without failed jobs."""
    out, ok = [], True
    for j in run_jobs(gh, repo, run_id):
        if (j.get("conclusion") or "") not in FAILED:
            continue
        errs = []
        try:
            errs = first_error(_job_log(gh, repo, j["id"]))
        except Exception:  # noqa: BLE001 - an unread log is read again on the next collect
            ok = False
        steps = [
            s.get("name") for s in j.get("steps") or [] if (s.get("conclusion") or "") in FAILED
        ]
        out.append({"name": j.get("name"), "steps": steps, "errors": errs})
    return out, ok


def failed_jobs(gh, repo, run_id):
    """[{name, steps, errors}] for the failed jobs of a run (see read_failed_jobs)."""
    return read_failed_jobs(gh, repo, run_id)[0]


class JobsCache:
    """The failed jobs of a finished run, read once. Keyed by repo, run id and attempt, so a different run (or a re-run of
    the same one) is never answered from another run's entry. Only a fully read answer is kept: a run whose job log could
    not be read is read again next time. Bounded to the newest `keep` entries. With `path` the entries survive the process
    (a JSON file, written only when it changed); a file that cannot be read starts empty, it only costs a read."""

    def __init__(self, path=None, keep=CACHE_KEEP):
        self.path, self.keep, self.entries, self.dirty = path, keep, {}, False
        if path:
            with contextlib.suppress(OSError, ValueError):
                d = json.loads(Path(path).read_text(encoding="utf-8"))
                if isinstance(d, dict) and isinstance(d.get("runs"), dict):
                    self.entries = {k: v for k, v in d["runs"].items() if isinstance(v, list)}

    @staticmethod
    def key(repo, run):
        return f"{repo}#{run.get('databaseId')}#{run.get('attempt') or 1}"

    def jobs(self, gh, repo, run):
        k = self.key(repo, run)
        if k in self.entries:
            return self.entries[k]
        jobs, ok = read_failed_jobs(gh, repo, run["databaseId"])
        if ok:
            self.entries.pop(k, None)
            self.entries[k] = jobs
            while len(self.entries) > self.keep:
                self.entries.pop(next(iter(self.entries)))
            self.dirty = True
        return jobs

    def save(self):
        if not (self.path and self.dirty):
            return
        p = Path(self.path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps({"runs": self.entries}, indent=1) + "\n", encoding="utf-8")
        os.replace(tmp, p)
        self.dirty = False


def _jobs(gh, repo, run, cache):
    return (
        cache.jobs(gh, repo, run) if cache is not None else failed_jobs(gh, repo, run["databaseId"])
    )


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


def _describe(jobs, all_errors=False):
    lines = []
    for j in jobs:
        step = f" (step {', '.join(j['steps'])})" if j["steps"] else ""
        errs = j["errors"] if all_errors else j["errors"][:1]
        err = f": {' | '.join(errs)}" if errs else ""
        lines.append(f"{j['name']}{step}{err}")
    return "; ".join(lines) or "no failed job could be read"


def main_item(w, runs, gh, cache=None):
    """The main watch item for one workflow, or None when the newest counted run succeeded (or none exists). With a
    JobsCache the failed run's jobs and logs are read once, not on every collect."""
    rs = real_runs(runs, w.get("branch") or "main")
    if not rs or rs[0].get("conclusion") not in FAILED:
        return None
    run = rs[0]
    jobs = _jobs(gh, w["repo"], run, cache)
    word = "timed out" if run.get("conclusion") == "timed_out" else "failed"
    return _item(
        w,
        f"main-watch-{w['workflow']}",
        f"{w.get('label') or w['workflow']} {word} on {w.get('branch') or 'main'}",
        f"The newest completed run of {w['workflow']} on {w.get('branch') or 'main'} {word}: {_describe(jobs)}. A later green run closes this.",
        "Open the run, fix the cause and re-run it, or revert the change that broke it.",
        [run],
    )


def drift_item(w, runs, gh, cache=None):
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
    jobs = _jobs(gh, w["repo"], streak[0], cache)
    return _item(
        w,
        f"drift-watch-{w['workflow']}",
        f"{w.get('label') or w['workflow']} has been red for {len(streak)} nights",
        f"The last {len(streak)} scheduled runs of {w['workflow']} on {w.get('branch') or 'main'} failed. Newest: {_describe(jobs, all_errors=True)}. A scheduled run that succeeds closes this.",
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
                "databaseId,attempt,status,conclusion,event,headBranch,createdAt,url",
            ]
        )
        or []
    )


_MEMORY = JobsCache()  # the in-process cache when the config names no cache file


def collect(config, gh, runs_for=None, cache=None):
    """Every item the configured watches raise now. `runs_for(w)` replaces the code host read (tests). `cache` is the
    JobsCache the failed runs' jobs are read through; by default the config's `cache_file` (kept between processes) or,
    without one, a cache that lives as long as this process."""
    config = config or {}
    if cache is None:
        cache = JobsCache(config["cache_file"]) if config.get("cache_file") else _MEMORY
    out = []
    for w in config.get("watches") or []:
        try:
            if w.get("kind") not in ("main", "drift") or not w.get("repo") or not w.get("workflow"):
                raise ValueError("a watch needs kind main or drift, a repo and a workflow")
            runs = (
                runs_for(w)
                if runs_for
                else list_runs(gh, w["repo"], w["workflow"], w.get("branch") or "main")
            )
            it = (main_item if w["kind"] == "main" else drift_item)(w, runs, gh, cache)
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
    with contextlib.suppress(OSError):  # a cache that cannot be written only costs a read next time
        cache.save()
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
