"""cron_pulse.py - which scheduled job owns a card, when it runs next, and Run now.

Purpose: Read the agent home/cron/jobs.json (read only) into a registry of the jobs that act on what the
         Reviews page shows. Each job is mapped to cards two ways:
           1. AUTO: PR numbers and <ticket key>-<slug> branch patterns found in the job's monitor script
              (or script) and prompt. A new watcher that names PRs needs no config.
           2. OVERRIDE: state/dashboard/cron-card-map.json for jobs that cannot be parsed (the review
              gates and the own-PR merge lane act on every PR of a lane, there is nothing to parse).
         Exposes pulse() for GET /api/cron-pulse, decorate_primary()/decorate_secondary() that attach a
         `watcher` object to every card, and run() for POST /api/cron-pulse/<id>/run.

Running-now detection (verified against the Hermes scheduler source, cron/jobs.py + executions.db):
  1. the agent home/cron/executions.db table `executions`, opened read only. A row for the job with status
     claimed or running and no finished_at is an in-flight run. This covers scheduled ticks, manual
     runs (source `direct`) and background dispatches, because every path claims an execution row.
     Rows older than STALE_RUN_S are ignored (an orphaned row must never pin a card as working).
  2. jobs.json `manual_run_at` set means a manual run is queued for the next scheduler tick (the
     scheduler clears it when the run is recorded). Shown as queued, which counts as working.
  3. A run this server just asked for, until Hermes shows the row (hand-off to the gateway ticker takes
     up to a minute). Bounded by PENDING_S.
Last tick: monitor-gated jobs write a one-line ledger doc `**Status:** no_change (agent run
suppressed)` into the agent home/cron/output/<id>/ on every quiet tick. The newest doc tells whether the last
tick was a silent no-change or a real run.

Run now goes through the supported Hermes paths, never by editing jobs.json. Without a note it is
`hermes cron run <id>`, which queues the job for the next scheduler tick (manual_run_at, up to about a
minute) with the job's own prompt and deliver target. The CLI has no flag for a transient note, so with a
note it calls tools.cronjob_tools.execute_job_for_event(id, extra_prompt=note) in Hermes's venv, the public
claimed-run entry the webhook adapter uses: same at-most-once claim, delivery and [SILENT] handling as a
scheduled run, runs now, and the note is per-fire context Hermes never persists (prompt and deliver
target untouched). The child process is detached and stays alive for the run. A claim already taken by
another run comes back as a non-zero exit and shows as a request error on the card.
"""

from __future__ import annotations

import datetime as dt
import fnmatch
import json
import os
import re
import sqlite3
import subprocess
import threading
import time
from pathlib import Path

import paths
import swr

HOME = Path.home()
JOBS = Path(os.environ.get("CRONPULSE_JOBS", str(paths.agent_home() / "cron/jobs.json")))
EXEC_DB = Path(os.environ.get("CRONPULSE_EXEC_DB", str(paths.agent_home() / "cron/executions.db")))
OUTPUT = Path(os.environ.get("CRONPULSE_OUTPUT", str(paths.agent_home() / "cron/output")))
SCRIPTS = Path(os.environ.get("CRONPULSE_SCRIPTS", str(paths.agent_home() / "scripts")))
CARD_MAP = Path(
    os.environ.get("CRONPULSE_CARD_MAP", str(paths.dashboard_dir() / "cron-card-map.json"))
)
HERMES_BIN = os.environ.get("CRONPULSE_HERMES_BIN", str(HOME / ".local/bin/hermes"))
HERMES_PY = os.environ.get(
    "CRONPULSE_HERMES_PY", str(paths.agent_home() / "hermes-agent/venv/bin/python")
)
HERMES_SRC = os.environ.get("CRONPULSE_HERMES_SRC", str(paths.agent_home() / "hermes-agent"))
RUN_LOG_DIR = Path(
    os.environ.get("CRONPULSE_RUN_LOGS", str(paths.agent_home() / "logs/cron-pulse"))
)

STALE_RUN_S = 6 * 3600  # an in-flight row older than this is an orphan
STALE_CLAIM_S = 900  # a claimed row that never started
PENDING_S = 180  # how long a requested run counts as queued before Hermes shows it
NOTE_MAX = 600
TTL_S = 3

_PR_LOOP = re.compile(r"\bfor\s+\w+\s+in\s+((?:\d{2,5}\s*)+);")
_PR_REF = re.compile(r"(?:#|\bPR\s+#?|\bpull/)(\d{2,5})\b")
# Parameters (environment, or local/params.json `cron_pulse` through the server):
#   CRONPULSE_BRANCH_KEY  regex of the ticket key at the start of a branch name (default any PROJECT-1234)
#   CRONPULSE_REPOS       JSON {repo key: "owner/name"}: the repositories whose Reviews pages carry a jobs strip
_BRANCH = re.compile(
    r"\b("
    + os.environ.get("CRONPULSE_BRANCH_KEY", r"[A-Z][A-Z0-9]+-\d{3,5}")
    + r")-[a-z0-9][a-z0-9-]*"
)
REPOS = json.loads(
    os.environ.get("CRONPULSE_REPOS")
    or '{"primary": "owner/primary", "secondary": "owner/secondary"}'
)
_REPO = re.compile("(" + "|".join(re.escape(v) for v in REPOS.values()) + ")", re.I)
_REPO_KEY = {v.lower(): k for k, v in REPOS.items()}

CARD_LANES = ("my_pr", "engineer_pr", "tfplan", "privileged", "runbook_release", "owner_root")

_pending = {}  # job id -> {at, pid, rc, note, error}
_plock = threading.Lock()


class PulseError(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.code = code


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _parse(s):
    try:
        t = dt.datetime.fromisoformat(str(s))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def _iso(t):
    return t.isoformat() if t else None


def _load(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def load_jobs():
    d = _load(JOBS, {})
    jobs = d.get("jobs") if isinstance(d, dict) else d
    return [j for j in (jobs or []) if isinstance(j, dict) and j.get("id")]


def load_map():
    d = _load(CARD_MAP, {})
    return d if isinstance(d, dict) else {}


# --------------------------------------------------------------------------- parsing


def _script_text(job):
    name = job.get("monitor_script") or job.get("script")
    if not name:
        return ""
    p = Path(os.path.expanduser(str(name)))
    if not p.is_absolute():
        p = SCRIPTS / p
    try:
        return p.read_text(errors="replace")[:200000]
    except OSError:
        return ""


def parse_job(job):
    """PR numbers, branch globs and repo a job names. Pure function of its script and prompt text."""
    script = _script_text(job)
    prompt = job.get("prompt") or ""
    prs = set()
    for m in _PR_LOOP.finditer(script):
        prs.update(int(n) for n in m.group(1).split())
    for text in (script, prompt):
        prs.update(int(n) for n in _PR_REF.findall(text))
    branches = sorted({f"{m}-*" for m in _BRANCH.findall(prompt + "\n" + script)})
    repos = {_REPO_KEY[m.lower()] for m in _REPO.findall(script + "\n" + prompt)}
    if not job.get("monitor_script") and not repos:
        # A prompt that names no repo and has no monitor is not a PR watcher: a stray "#20" is no card.
        return {"prs": [], "branches": [], "repo": None}
    return {
        "prs": sorted(prs),
        "branches": branches,
        "repo": repos.pop() if len(repos) == 1 else None,
    }


def _entry(job, cmap):
    """Registry row for one job: auto-derived mapping merged with its override."""
    ov = (cmap.get("jobs") or {}).get(job["id"]) or {}
    auto = {"prs": [], "branches": [], "repo": None} if ov.get("auto") is False else parse_job(job)
    prs = sorted(set(auto["prs"]) | {int(n) for n in ov.get("prs") or []})
    branches = sorted(set(auto["branches"]) | set(ov.get("branches") or []))
    lanes = [x for x in ov.get("lanes") or [] if x in CARD_LANES]
    repo = ov.get("repo") or auto["repo"]
    src = "override" if ov and not (auto["prs"] or auto["branches"]) else ("both" if ov else "auto")
    return {
        "prs": prs,
        "branches": branches,
        "lanes": lanes,
        "repo": repo,
        "source": src,
        "all_mine": bool(ov.get("all_mine")),
    }


# --------------------------------------------------------------------------- state


def _ro_rows(sql, args=()):
    if not EXEC_DB.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{EXEC_DB}?mode=ro", uri=True, timeout=2)
        try:
            con.row_factory = sqlite3.Row
            return [dict(r) for r in con.execute(sql, args)]
        finally:
            con.close()
    except sqlite3.Error:
        return None


def inflight_runs():
    """job id -> {source, since} for every execution row Hermes shows as in flight."""
    rows = _ro_rows(
        "SELECT job_id, source, status, claimed_at, started_at FROM executions "
        "WHERE status IN ('claimed','running') AND finished_at IS NULL"
    )
    out = {}
    now = _now()
    for r in rows or []:
        since = _parse(r.get("started_at") or r.get("claimed_at"))
        if not since:
            continue
        age = (now - since).total_seconds()
        limit = STALE_RUN_S if r["status"] == "running" else STALE_CLAIM_S
        if age > limit:
            continue
        old = out.get(r["job_id"])
        if not old or since < old["since"]:
            out[r["job_id"]] = {"source": r["source"], "since": since, "status": r["status"]}
    return out


def last_tick(job_id):
    """Newest ledger doc for a job: {at, kind} with kind no_change or ran."""
    d = OUTPUT / job_id
    try:
        docs = [e for e in os.scandir(d) if e.name.endswith(".md")]
    except OSError:
        return None
    if not docs:
        return None
    newest = max(docs, key=lambda e: e.name)
    try:
        with open(newest.path, errors="replace") as f:
            head = f.read(600)
    except OSError:
        return None
    m = re.search(r"\*\*Status:\*\*\s*([^\n]+)", head)
    status = (m.group(1) if m else "").strip().lower()
    kind = (
        "no_change"
        if status.startswith("no_change")
        else ("failed" if "failed" in status else "ran")
    )
    stamp = re.match(r"(\d{4}-\d\d-\d\d)_(\d\d)-(\d\d)-(\d\d)", newest.name)
    at = None
    if stamp:
        naive = dt.datetime.strptime(
            f"{stamp.group(1)} {stamp.group(2)}:{stamp.group(3)}:{stamp.group(4)}",
            "%Y-%m-%d %H:%M:%S",
        )
        at = naive.astimezone()  # ledger names are local time (the host's local zone)
    return {"at": _iso(at), "kind": kind, "status": status}


def _pending_state(job_id, inflight_ids, last_run_at):
    """A run this server asked for. Ends when Hermes shows it in flight and then finished, when the job's
    last_run_at moves past the request (a fast quiet tick never shows in flight), or after PENDING_S."""
    with _plock:
        p = _pending.get(job_id)
        if not p:
            return None
        if p.get("rc") not in (None, 0):
            return {"queued": False, "error": p.get("error") or f"exit {p['rc']}", "at": p["at"]}
        if job_id in inflight_ids:
            p["seen"] = True
            return None
        done_at = _parse(last_run_at)
        if (
            p.get("seen")
            or time.time() - p["at"] > PENDING_S
            or (done_at and done_at.timestamp() > p["at"])
        ):
            _pending.pop(job_id, None)
            return None
        return {"queued": True, "at": p["at"]}


def _row(job, cmap, inflight, now):
    e = _entry(job, cmap)
    sched = job.get("schedule") or {}
    enabled = bool(job.get("enabled", True)) and job.get("state") not in ("completed", "paused")
    gated = bool(job.get("monitor_script"))
    run = inflight.get(job["id"])
    manual_queued = bool(job.get("manual_run_at")) and not run
    pend = _pending_state(job["id"], inflight, job.get("last_run_at"))
    queued = manual_queued or bool(pend and pend.get("queued") and not run)
    tick = last_tick(job["id"])
    mon = job.get("monitor_state") or {}
    return {
        "id": job["id"],
        "name": job.get("name") or job["id"],
        "cadence": sched.get("display") or job.get("schedule_display") or "",
        "enabled": enabled,
        "state": job.get("state"),
        "next_run_at": job.get("next_run_at") if enabled else None,
        "last_run_at": job.get("last_run_at"),
        "last_status": job.get("last_status"),
        "last_error": (job.get("last_error") or "")[:200] or None,
        "monitor_gated": gated,
        "last_changed_at": mon.get("last_changed_at") if gated else None,
        "last_tick": tick if gated else (tick and {"at": tick["at"], "kind": "ran"}),
        "silent_no_change": bool(gated and tick and tick["kind"] == "no_change"),
        "running": bool(run),
        "queued": queued,
        "running_since": _iso(run["since"]) if run else None,
        "run_source": run["source"] if run else None,
        "request_error": pend.get("error") if pend and pend.get("error") else None,
        "prs": e["prs"],
        "branches": e["branches"],
        "lanes": e["lanes"],
        "repo": e["repo"],
        "all_mine": e["all_mine"],
        "mapping": e["source"],
        "runnable": enabled,
    }


def _build():
    now = _now()
    cmap = load_map()
    inflight = inflight_runs()
    rows = []
    for job in load_jobs():
        r = _row(job, cmap, inflight, now)
        if r["prs"] or r["branches"] or r["lanes"] or r["all_mine"]:
            rows.append(r)
    return {
        "generated_utc": _iso(now),
        "now": _iso(now),
        "jobs": rows,
        "server_owned": cmap.get("server_owned") or {},
    }


def snapshot(fresh=False):
    return swr.cached("cron-pulse", TTL_S, _build, fresh=fresh)


def invalidate():
    swr.invalidate("cron-pulse")


# --------------------------------------------------------------------------- card ownership


def owners_for(snap, repo, lane, pr=None, branch=None):
    """Jobs that act on one card, most specific first. Disabled jobs never watch. lane is one lane name
    or a tuple of them (a card can be an engineer PR and a held plan at once)."""
    lanes = (lane,) if isinstance(lane, str) else tuple(lane)
    hits = []
    for j in snap["jobs"]:
        if j["repo"] and j["repo"] != repo:
            continue
        specific = bool(
            (pr is not None and pr in j["prs"])
            or (branch and any(fnmatch.fnmatch(branch, g) for g in j["branches"]))
        )
        lane_hit = any(x in j["lanes"] for x in lanes) or ("my_pr" in lanes and j["all_mine"])
        if specific or lane_hit:
            hits.append((0 if specific else 1, j))
    hits.sort(key=lambda x: (x[0], not x[1]["enabled"], x[1]["name"]))
    return [j for _, j in hits]


def _view(j):
    keys = (
        "id",
        "name",
        "cadence",
        "enabled",
        "next_run_at",
        "last_run_at",
        "last_status",
        "monitor_gated",
        "last_tick",
        "silent_no_change",
        "running",
        "queued",
        "running_since",
        "request_error",
    )
    return {k: j.get(k) for k in keys}


def watcher_for(snap, repo, lane, pr=None, branch=None):
    owners = owners_for(snap, repo, lane, pr, branch)
    live = [o for o in owners if o["enabled"]]
    if live:
        w = _view(live[0])
        w["also"] = [{"id": o["id"], "name": o["name"]} for o in live[1:]]
        return {"watcher": w, "unwatched": False}
    owned = next(
        (
            o
            for o in (
                (snap.get("server_owned") or {}).get(x)
                for x in ((lane,) if isinstance(lane, str) else lane)
            )
            if o
        ),
        None,
    )
    if owned:
        return {
            "watcher": {
                "id": None,
                "name": owned.get("name") or "Ops Center server",
                "cadence": owned.get("cadence") or "",
                "server": True,
                "running": False,
                "queued": False,
                "also": [],
            },
            "unwatched": False,
        }
    paused = [o for o in owners if not o["enabled"]]
    return {"watcher": None, "unwatched": True, "paused_job": paused[0]["name"] if paused else None}


def _decorate_list(snap, repo, items, lane_fn, mine):
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            out.append(it)
            continue
        pr = it.get("pr")
        pr = int(pr) if str(pr).isdigit() else None
        branch = it.get("branch") or it.get("head_branch")
        lane = lane_fn(it, pr, mine)
        out.append(dict(it, **watcher_for(snap, repo, lane, pr, branch)))
    return out


def decorate_primary(data, snap=None):
    if not isinstance(data, dict):
        return data
    try:
        snap = snap or snapshot()
    except (OSError, ValueError, KeyError):
        return data
    d = dict(data)
    mine = {
        int(x["pr"])
        for x in data.get("my_prs") or []
        if isinstance(x, dict) and str(x.get("pr")).isdigit()
    }

    def pr_lane(it, pr, m):
        if pr in m:
            return "my_pr"
        srcs = it.get("sources") or []
        lanes = ["engineer_pr"] if (not srcs or "review" in srcs) else []
        if any(x != "review" for x in srcs):
            lanes.append("tfplan")
        return tuple(lanes) or ("engineer_pr",)

    for key in (
        "my_prs",
        "needs_me",
        "needs_in_flight",
        "needs_waiting",
        "in_progress",
        "held_for_window",
    ):
        if isinstance(data.get(key), list):
            d[key] = _decorate_list(snap, "primary", data[key], pr_lane, mine)
    d["privileged"] = _decorate_list(
        snap, "primary", data.get("privileged"), lambda *_: "privileged", mine
    )
    d["runbook_releases"] = _decorate_list(
        snap, "primary", data.get("runbook_releases"), lambda *_: "runbook_release", mine
    )
    own = data.get("owner_roots")
    if isinstance(own, dict):
        d["owner_roots"] = dict(
            own,
            items=_decorate_list(snap, "primary", own.get("items"), lambda *_: "owner_root", mine),
        )
    d["cron_pulse"] = page_strip(snap, "primary")
    return d


def decorate_secondary(data, snap=None):
    if not isinstance(data, dict):
        return data
    try:
        snap = snap or snapshot()
    except (OSError, ValueError, KeyError):
        return data
    d = dict(data)
    for key in ("needs_me", "in_progress"):
        if isinstance(data.get(key), list):
            d[key] = _decorate_list(
                snap,
                "secondary",
                data[key],
                lambda it, pr, m: "my_pr" if it.get("mine") else "engineer_pr",
                set(),
            )
    d["cron_pulse"] = page_strip(snap, "secondary")
    return d


def decorate_repos(data, snap=None):
    """Other repos (one Reviews tab each): watcher per PR row and the jobs strip per repo slug."""
    if not isinstance(data, dict):
        return data
    try:
        snap = snap or snapshot()
    except (OSError, ValueError, KeyError):
        return data
    d = dict(data)
    repos = []
    for r in data.get("repos") or []:
        if not isinstance(r, dict):
            repos.append(r)
            continue
        slug = r.get("slug")
        e = dict(r)
        for key in ("needs_me", "in_progress"):
            if isinstance(r.get(key), list):
                e[key] = _decorate_list(
                    snap,
                    slug,
                    r[key],
                    lambda it, pr, m: "my_pr" if it.get("mine") else "engineer_pr",
                    set(),
                )
        e["cron_pulse"] = page_strip(snap, slug)
        repos.append(e)
    d["repos"] = repos
    return d


def page_strip(snap, repo):
    """Jobs that feed one repo's Reviews page, for the compact strip."""
    jobs = [j for j in snap["jobs"] if (not j["repo"] or j["repo"] == repo) and j["enabled"]]
    return {"jobs": [_view(j) for j in sorted(jobs, key=lambda x: x["next_run_at"] or "9")]}


def pulse(fresh=False):
    snap = snapshot(fresh=fresh)
    return dict(snap, jobs=[dict(j) for j in snap["jobs"]])


# --------------------------------------------------------------------------- run now


def _cmd(job_id, note):
    if note:
        code = (
            "import sys\n"
            "from tools.cronjob_tools import execute_job_for_event\n"
            "r = execute_job_for_event(sys.argv[1], extra_prompt=sys.argv[2])\n"
            "print(r)\n"
            "sys.exit(0 if r.get('claimed') and r.get('success') else 3)\n"
        )
        return [HERMES_PY, "-c", code, job_id, note], HERMES_SRC
    return [HERMES_BIN, "cron", "run", job_id], str(HOME)


def _spawn(argv, cwd, log_path):
    """Detached child so a server restart never kills a run. One seam so tests patch it."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "ab") as log:
        return subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )


def _reap(job_id, proc, log_path):
    rc = proc.wait()
    with _plock:
        p = _pending.get(job_id)
        if not p or p.get("pid") != proc.pid:
            return
        p["rc"] = rc
        if rc != 0:
            try:
                tail = log_path.read_text(errors="replace")[-300:].strip().replace("\n", " ")
            except OSError:
                tail = ""
            p["error"] = tail or f"hermes cron run exited {rc}"
    invalidate()


def run(job_id, note=None, spawn=None):
    """Trigger a job now through the Hermes cron API. Returns {started, job}. Never edits jobs.json."""
    job_id = str(job_id or "").strip()
    if not re.fullmatch(r"[0-9a-f]{12}", job_id):
        raise PulseError("bad job id", 400)
    note = (note or "").strip()
    if len(note) > NOTE_MAX:
        raise PulseError(f"note too long (max {NOTE_MAX})", 400)
    if note and not note.isascii():
        raise PulseError("note must be plain ASCII", 400)
    snap = snapshot(fresh=True)
    row = next((j for j in snap["jobs"] if j["id"] == job_id), None)
    if row is None:
        raise PulseError("unknown job (not a job that feeds the Reviews page)", 404)
    if not row["enabled"]:
        raise PulseError("job is paused or finished, resume it in Hermes first", 409)
    if row["running"] or row["queued"]:
        return {"started": False, "already": True, "job": _view(row)}
    argv, cwd = _cmd(job_id, note)
    log_path = RUN_LOG_DIR / f"{job_id}.log"
    proc = (spawn or _spawn)(argv, cwd, log_path)
    with _plock:
        _pending[job_id] = {
            "at": time.time(),
            "pid": getattr(proc, "pid", None),
            "rc": None,
            "note": note,
        }
    if hasattr(proc, "wait"):
        threading.Thread(target=_reap, args=(job_id, proc, log_path), daemon=True).start()
    invalidate()
    row = dict(row, queued=True)
    return {"started": True, "already": False, "with_note": bool(note), "job": _view(row)}
