"""
infra.py - the Infrastructure page's server half.

Purpose: Serve the code host view (open PRs with their check summary, recent runs, workflows red on main), the CI runner
         fleet (registered runners, queued and running runs, the live job and step progress) and, from an optional
         provider the consumer supplies, the pieces that live in its own runtime: LLM spend, scheduled jobs, the runner
         VM, a running step's log, backup status and health checks. Read only.
Date:    2026-10-05

Configuration (environment, all optional, nothing names an estate):
  INFRA_REPOS             comma separated owner/name list for the code host view (none: an empty view)
  INFRA_RUNNER_REPO       owner/name whose runners and runs the fleet and live views read (none: empty views)
  INFRA_BILLING_USER      the account whose hosted Actions minutes are shown (none: no minutes), INFRA_INCLUDED_MINUTES (2000)
  OPSCENTER_INFRA_PROVIDER  `path/to/file.py:ClassName`. Every method is optional; a missing one answers the empty state:
        spend() -> the Spend payload   cron() -> the Cron payload   vm() -> {name, status, cpus, memory_gib, disk_gib}
        backup() -> a backup status dict   job_log(runner, lines) -> [line]   health() -> [(level, detail)] with level "OK"
        for a passing check (anything else is a problem on the badge)   fallback_active() -> bool
"""

import datetime as dt
import importlib.util
import json
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import paths
import swr

GH = os.environ.get("GH_BIN", paths.which("gh"))
_lock = threading.Lock()


class ProviderRefused(Exception):
    status = 403


class NotConfigured(Exception):
    """A read that needs a value or provider the consumer has not supplied (501)."""

    status = 501


def _repos():
    return [r.strip() for r in os.environ.get("INFRA_REPOS", "").split(",") if "/" in r]


def _runner_repo():
    return os.environ.get("INFRA_RUNNER_REPO", "").strip()


_provider = {"spec": None, "obj": None}


def provider():
    """The configured provider object, or None (the null default)."""
    spec = os.environ.get("OPSCENTER_INFRA_PROVIDER", "").strip()
    with _lock:
        if _provider["spec"] == spec:
            return _provider["obj"]
    obj = None
    if spec:
        path, _, cls_name = spec.rpartition(":")
        if not path or not cls_name:
            raise ProviderRefused("provider must be `path/to/file.py:ClassName`")
        file = Path(path)
        if not file.is_file():
            raise ProviderRefused(f"provider file not found: {file.name}")
        ms = importlib.util.spec_from_file_location(f"infra_provider_{file.stem}", file)
        mod = importlib.util.module_from_spec(ms)
        try:
            ms.loader.exec_module(mod)
            obj = getattr(mod, cls_name)()
        except (OSError, ImportError, AttributeError, TypeError, SyntaxError) as exc:
            raise ProviderRefused(f"provider could not be loaded: {type(exc).__name__}") from exc
    with _lock:
        _provider.update(spec=spec, obj=obj)
    return obj


def _call(name, *args):
    """A provider method's answer, or (None, False) when there is no provider or it lacks the method."""
    p = provider()
    fn = getattr(p, name, None) if p is not None else None
    if not callable(fn):
        return None, False
    return fn(*args), True


def _cached(key, ttl, fn):
    # Stale-while-revalidate (swr.py): an expired entry is served at once and refreshed in the background.
    return swr.cached(f"infra:{key}", ttl, fn)


def _utc_now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gh(args, timeout=25):
    p = subprocess.run([GH, *args], capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).strip()[:300])
    return json.loads(p.stdout or "[]")


def _checks_summary(rollup):
    s = {"pass": 0, "fail": 0, "pending": 0, "failing": []}
    # Re-runs leave older check results in the rollup; keep only the newest per check.
    newest = {}
    for c in rollup or []:
        k = (c.get("workflowName") or "", c.get("name") or c.get("context") or "")
        ts = c.get("startedAt") or c.get("completedAt") or ""
        if k not in newest or ts >= (
            newest[k].get("startedAt") or newest[k].get("completedAt") or ""
        ):
            newest[k] = c
    for c in newest.values():
        concl = (c.get("conclusion") or c.get("state") or "").upper()
        status = (c.get("status") or "").upper()
        name = c.get("name") or c.get("context") or "check"
        if status and status != "COMPLETED":
            s["pending"] += 1
        elif concl in ("SUCCESS", "NEUTRAL", "SKIPPED"):
            s["pass"] += 1
        elif concl in ("CANCELLED", "STALE"):
            continue
        elif concl == "PENDING":
            s["pending"] += 1
        else:
            s["fail"] += 1
            s["failing"].append(name)
    return s


def _repo(repo):
    res = {"repo": repo, "prs": [], "runs": [], "error": None}
    try:
        prs = _gh(
            [
                "pr",
                "list",
                "-R",
                repo,
                "--state",
                "open",
                "-L",
                "30",
                "--json",
                "number,title,author,isDraft,reviewDecision,statusCheckRollup,updatedAt,url,headRefName,mergeStateStatus",
            ]
        )
        for p in prs:
            res["prs"].append(
                {
                    "repo": repo,
                    "number": p["number"],
                    "title": p["title"],
                    "url": p["url"],
                    "author": (p.get("author") or {}).get("login"),
                    "draft": p.get("isDraft"),
                    "review": p.get("reviewDecision") or "",
                    "merge_state": p.get("mergeStateStatus") or "",
                    "branch": p.get("headRefName"),
                    "updated": p.get("updatedAt"),
                    "checks": _checks_summary(p.get("statusCheckRollup")),
                }
            )
        runs = _gh(
            [
                "run",
                "list",
                "-R",
                repo,
                "-L",
                "20",
                "--json",
                "databaseId,workflowName,displayTitle,status,conclusion,event,headBranch,createdAt,updatedAt,url",
            ]
        )
        for r in runs:
            res["runs"].append(
                {
                    "repo": repo,
                    "id": r["databaseId"],
                    "workflow": r.get("workflowName"),
                    "title": r.get("displayTitle"),
                    "status": r.get("status"),
                    "conclusion": r.get("conclusion") or "",
                    "event": r.get("event"),
                    "branch": r.get("headBranch"),
                    "created": r.get("createdAt"),
                    "updated": r.get("updatedAt"),
                    "url": r.get("url"),
                }
            )
    except (RuntimeError, subprocess.TimeoutExpired, ValueError, OSError) as exc:
        res["error"] = str(exc)
    return res


def _github():
    repo_list = _repos()
    with ThreadPoolExecutor(max_workers=len(repo_list) or 1) as ex:
        repos = list(ex.map(_repo, repo_list))
    prs = [p for r in repos for p in r["prs"]]
    runs = sorted(
        (x for r in repos for x in r["runs"]), key=lambda x: x["created"] or "", reverse=True
    )
    # A workflow is "red on main" when its newest main/push run failed.
    latest = {}
    for x in runs:
        if x["branch"] in ("main", "master") and x["status"] == "completed":
            latest.setdefault((x["repo"], x["workflow"]), x)
    red = [
        x
        for x in latest.values()
        if x["conclusion"] not in ("success", "skipped", "neutral", "cancelled")
    ]
    return {
        "generated_utc": _utc_now(),
        "repos": repo_list,
        "errors": {r["repo"]: r["error"] for r in repos if r["error"]},
        "prs": sorted(prs, key=lambda p: p["updated"] or "", reverse=True),
        "runs": runs[:40],
        "red_on_main": red,
        "in_progress": [x for x in runs if x["status"] != "completed"],
    }


def _runners():
    """CI runner fleet (the VM when the provider names it, the code host's runner registrations), queued and running runs,
    hosted Actions minutes when an account is configured, backup status when the provider has it."""
    repo = _runner_repo()
    out = {
        "generated_utc": _utc_now(),
        "repo": repo,
        "vm": None,
        "runners": [],
        "queued": [],
        "running": [],
        "minutes": None,
        "backup": None,
        "errors": [],
        "links": {
            "actions": f"https://github.com/{repo}/actions",
            "runners": f"https://github.com/{repo}/settings/actions/runners",
            "pulls": f"https://github.com/{repo}/pulls",
        }
        if repo
        else {},
    }
    try:
        out["vm"], _ = _call("vm")
    except (OSError, ValueError, subprocess.SubprocessError, ProviderRefused) as exc:
        out["errors"].append(f"vm: {exc}")
    if not repo:
        return out
    try:
        reg = _gh(["api", f"repos/{repo}/actions/runners"])
        out["runners"] = [
            {
                "name": r["name"],
                "status": r["status"],
                "busy": r["busy"],
                "labels": [lab["name"] for lab in r.get("labels", [])],
            }
            for r in reg.get("runners", [])
        ]
        for state, key in (("queued", "queued"), ("in_progress", "running")):
            runs = _gh(["api", f"repos/{repo}/actions/runs?status={state}&per_page=20"])
            out[key] = [
                {
                    "id": r["id"],
                    "name": r.get("display_title") or r.get("name"),
                    "workflow": r.get("name"),
                    "branch": r.get("head_branch"),
                    "created": r.get("created_at"),
                    "url": r.get("html_url"),
                }
                for r in runs.get("workflow_runs", [])
            ]
    except (RuntimeError, subprocess.TimeoutExpired, ValueError, OSError) as exc:
        out["errors"].append(f"github: {exc}")
    user = os.environ.get("INFRA_BILLING_USER", "").strip()
    if user:
        try:
            usage = _gh(["api", f"users/{user}/settings/billing/usage/summary"])
            mins = [
                u
                for u in usage.get("usageItems", [])
                if u.get("product") == "actions" and u.get("unitType") == "Minutes"
            ]
            out["minutes"] = {
                "hosted_used": round(sum(u.get("grossQuantity", 0) for u in mins)),
                "included": int(os.environ.get("INFRA_INCLUDED_MINUTES", "2000")),
            }
        except (RuntimeError, subprocess.TimeoutExpired, ValueError, OSError):
            out["minutes"] = None  # the billing API needs a scope we may not hold
    try:
        out["backup"], _ = _call("backup")
    except (OSError, ValueError, ProviderRefused):
        out["backup"] = None
    return out


# Completed jobs never change, so their job/step detail is cached for the process lifetime.
_done_jobs = {}


def _job_view(j):
    steps = [
        {
            "n": st.get("number"),
            "name": st.get("name"),
            "status": st.get("status"),
            "conclusion": st.get("conclusion"),
            "started": st.get("started_at"),
            "completed": st.get("completed_at"),
        }
        for st in j.get("steps") or []
    ]
    return {
        "id": j["id"],
        "name": j.get("name"),
        "status": j.get("status"),
        "conclusion": j.get("conclusion"),
        "runner": j.get("runner_name"),
        "started": j.get("started_at"),
        "completed": j.get("completed_at"),
        "url": j.get("html_url"),
        "steps": steps,
    }


def _live_jobs():
    """Recent workflow runs on the runner repo with per-job and per-step progress, for the live view."""
    repo = _runner_repo()
    out = {"generated_utc": _utc_now(), "repo": repo, "runs": [], "errors": [], "active": False}
    if not repo:
        return out
    try:
        runs = _gh(["api", f"repos/{repo}/actions/runs?per_page=8"]).get("workflow_runs", [])
    except (RuntimeError, subprocess.TimeoutExpired, ValueError, OSError) as exc:
        out["errors"].append(f"github: {exc}")
        return out

    def jobs_for(r):
        key = (r["id"], r.get("run_attempt"))
        if key in _done_jobs:
            return _done_jobs[key]
        # A run whose updated_at has not moved has the same jobs: reuse them (saves one gh call per run per poll).
        seen = _live_jobs_seen.get(key)
        if seen and seen[0] == r.get("updated_at") and time.time() - seen[2] < 30:
            return seen[1]
        data = _gh(["api", f"repos/{repo}/actions/runs/{r['id']}/jobs?per_page=50"])
        jobs = [_job_view(j) for j in data.get("jobs", [])]
        if r.get("status") == "completed":
            _done_jobs[key] = jobs
        else:
            _live_jobs_seen[key] = (r.get("updated_at"), jobs, time.time())
        return jobs

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda r: _safe(jobs_for, r), runs))
    for r, (jobs, err) in zip(runs, results):
        if err:
            out["errors"].append(f"jobs {r['id']}: {err}")
        out["runs"].append(
            {
                "id": r["id"],
                "title": r.get("display_title"),
                "workflow": r.get("name"),
                "branch": r.get("head_branch"),
                "event": r.get("event"),
                "status": r.get("status"),
                "conclusion": r.get("conclusion"),
                "created": r.get("created_at"),
                "updated": r.get("updated_at"),
                "url": r.get("html_url"),
                "jobs": jobs or [],
            }
        )
    out["active"] = any(r["status"] != "completed" for r in out["runs"])
    return out


def _safe(fn, *args):
    try:
        return fn(*args), None
    except (RuntimeError, subprocess.TimeoutExpired, ValueError, OSError) as exc:
        return None, str(exc)[:200]


_live_jobs_seen = {}


def job_log(runner, lines=60):
    """Tail the in-progress step log of a runner (the code host only serves logs after completion), through the provider."""
    if not __import__("re").fullmatch(r"[A-Za-z0-9._-]{1,64}", runner or ""):
        raise ValueError("unknown runner")
    lines = max(10, min(int(lines), 200))
    got, have = _call("job_log", runner, lines)
    if not have:
        raise NotConfigured("no runner log source configured (OPSCENTER_INFRA_PROVIDER job_log)")
    text = "\n".join(str(x) for x in (got or []))
    text = __import__("re").sub(r"\x1b\[[0-9;]*m", "", text)  # ANSI colors are not for display
    return {
        "generated_utc": _utc_now(),
        "runner": runner,
        "live": bool(text.strip()),
        "lines": text.splitlines()[-lines:],
    }


def live_jobs():
    # Code host rate budget: 6 s while a run is active, 30 s when idle.
    last = swr.peek("infra:live_jobs")
    ttl = 6 if (last is None or last.get("active")) else 30
    return swr.cached("infra:live_jobs", ttl, _live_jobs)


def _empty_spend():
    zero = {
        k: 0
        for k in (
            "today",
            "d7",
            "d30",
            "mtd",
            "cron_d7",
            "interactive_d7",
            "projected_month",
            "billed_rate_per_day",
            "billed_projected_month",
        )
    }
    for b in ("billed", "included", "unattributed"):
        for w in ("today", "d7", "mtd"):
            zero[f"{b}_{w}"] = 0
        for k in ("cron", "interactive"):
            zero[f"{k}_{b}_d7"] = 0
    return {
        "generated_utc": _utc_now(),
        "months": [],
        "totals": zero,
        "daily": [],
        "jobs": [],
        "sessions": 0,
        "estimated_sessions": 0,
        "ledger_since_utc": None,
        "rate_basis_days": 0,
    }


def _spend():
    got, have = _call("spend")
    return got if have and isinstance(got, dict) else _empty_spend()


def _cron():
    got, have = _call("cron")
    if have and isinstance(got, dict):
        return got
    return {"generated_utc": _utc_now(), "scheduler_heartbeat_age_s": None, "jobs": []}


def spend():
    return _cached("spend", 120, _spend)


def cron():
    return _cached("cron", 20, _cron)


def github():
    return _cached("github", 30, _github)


def runners():
    return _cached("runners", 30, _runners)


def _health():
    got, have = _call("health")
    return list(got) if have and got else []


def configured():
    """True when the page has anything to read: a provider, watched repos, a runner repo or maintenance tasks."""
    return bool(
        os.environ.get("OPSCENTER_INFRA_PROVIDER", "").strip()
        or _repos()
        or _runner_repo()
        or Path(os.environ.get("INFRA_TASKS") or paths.state_dir() / "infra-tasks.json").is_file()
    )


def badge_problems():
    """The Infrastructure part of the single problem list. {count, items, areas, looks}:
    `areas` are the lines that NEED the owner, by tab: jobs (failing or overdue scheduled jobs, a silent scheduler), spend (an
    active model fallback) and ci (the provider's failed health checks); `items` is every area's lines in one list and `count` its
    length. `looks` are lines worth a look, never red: runners offline and workflows red on main in the repos the page watches,
    read from the cache only so a badge never waits on the code host. Nothing client side decides what counts."""
    areas = {"jobs": [], "spend": [], "ci": []}
    try:
        c = _cron()
        for j in c.get("jobs") or []:
            if j.get("health") in ("failing", "overdue"):
                areas["jobs"].append(f"{j.get('name')}: {j.get('health')}")
        hb = c.get("scheduler_heartbeat_age_s")
        if c.get("jobs") and (hb is None or hb > 600):
            areas["jobs"].append(
                "Scheduler heartbeat " + ("unreadable" if hb is None else f"{hb // 60} min old")
            )
    except (OSError, ValueError, KeyError, ProviderRefused) as exc:
        areas["jobs"].append(f"Scheduled jobs unreadable: {exc}")
    try:
        active, have = _call("fallback_active")
        if have and active:
            areas["spend"].append("Model fallback active")
    except (OSError, ValueError, ProviderRefused) as exc:
        areas["spend"].append(f"Fallback state unreadable: {exc}")
    try:
        for level, detail in swr.cached("infra:health", 600, _health) or []:
            if level != "OK":
                areas["ci"].append(str(detail))
    except Exception as exc:  # noqa: BLE001 - a broken check is reported, never hidden
        areas["ci"].append(f"Health checks could not run: {exc}")
    looks = {"ci": []}
    fleet = swr.peek("infra:runners") or {}
    offline = [r.get("name") for r in fleet.get("runners") or [] if r.get("status") != "online"]
    if offline:
        looks["ci"].append("Runners offline: " + ", ".join(str(n) for n in offline[:4]))
    red = (swr.peek("infra:github") or {}).get("red_on_main") or []
    for x in red[:4]:
        looks["ci"].append(f"{x.get('repo')}: {x.get('workflow')} is red on main")
    items = areas["jobs"] + areas["spend"] + areas["ci"]
    return {"count": len(items), "items": items, "areas": areas, "looks": looks}


if __name__ == "__main__":
    import sys

    fn = {"spend": spend, "cron": cron, "github": github, "runners": runners}[
        sys.argv[1] if len(sys.argv) > 1 else "spend"
    ]
    print(json.dumps(fn(), indent=1)[:4000])
