"""
runbook_releases.py
Purpose: Release guarded deletes of a deploy root from the ops center after the owner approves and merges a
         pull request that removes objects from it (opscenter/DESIGN.md section 12.3, item 15). The root is
         applied by its own deploy workflow, never by the generic destroy workflow, so the push run on main
         stops on its destroy guard and waits for a dispatch with allow_destroy=true. This module:
           - records the delete set the owner approved (from the PR's plan job)
           - follows the deploy workflow's runs on main after the merge
           - offers Release deletes only when the newest main run failed on the destroy guard alone and its
             plan deletes exactly the approved set and nothing else changes
           - dispatches allow_destroy=true on main after re-checking all of that live, then tracks the
             dispatched run and verifies what it destroyed
         The environment has no reviewers, so the dispatch applies at once. The button is the sign-off.
Parameters (environment, or local/params.json `releases`):
  RELEASE_REPO        owner/name of the repo [repo]
  RELEASE_SELF_LOGIN  the owner's login, recorded as the dispatcher [self_login]
  RELEASE_WORKFLOW    the deploy workflow file, default deploy-runbooks.yml [workflow]
  RELEASE_PLAN_JOB    the pull request plan job name, with {tier} [plan_job]
  RELEASE_TIER        the tier whose deletes this module releases, default prod [tier]
  RELEASE_WATCH       JSON list of paths whose change would alter what a dispatch plans [watch]
  OPRG_STATE_DIR, OPRG_CACHE_DIR, OPRG_GH_BIN  state, cache and the gh binary
"""

import datetime as dt
import fcntl
import json
import os
import re
import subprocess
import time
from pathlib import Path

import paths
import swr

STATE = Path(os.environ.get("OPRG_STATE_DIR", str(paths.state_dir() / "review")))
CACHE = Path(os.environ.get("OPRG_CACHE_DIR", str(paths.agent_home() / "cache" / "pr-review")))
STORE = CACHE / "runbook-releases.json"
STORE_LOCK = CACHE / "runbook-releases.lock"
RUN_CACHE = CACHE / "runbook-release-runs.json"  # completed run id -> parsed plan (immutable)
DECISIONS = STATE / "decisions.jsonl"
GH = os.environ.get("OPRG_GH_BIN", paths.which("gh"))
REPO = os.environ.get("RELEASE_REPO", "owner/repo")
SELF = os.environ.get("RELEASE_SELF_LOGIN", "owner-login")
WORKFLOW = os.environ.get("RELEASE_WORKFLOW", "deploy-runbooks.yml")
PR_PLAN_JOB = os.environ.get("RELEASE_PLAN_JOB", "terraform plan (runbooks {tier})")
TIER = os.environ.get("RELEASE_TIER", "prod")
DEPLOY_JOB = "deploy / deploy"
# Paths whose change between the checked run and main would change what a dispatch plans.
WATCH = tuple(
    json.loads(os.environ["RELEASE_WATCH"])
    if os.environ.get("RELEASE_WATCH")
    else (
        "runbooks/",
        "infrastructure/terraform/runbooks/",
        ".github/workflows/deploy-runbooks.yml",
        ".github/workflows/_deploy-runbook.yml",
    )
)
DONE_SHOW_S = 86400  # finished releases stay visible for a day
TTL_S = 30

PLAN_LINE = re.compile(
    r"Plan: (\d+) to import, (\d+) to add, (\d+) to change, (\d+) to destroy|Plan: (\d+) to add, (\d+) to change, (\d+) to destroy"
)
RES_LINE = re.compile(
    r"#\s+(\S+)\s+(will be created|will be destroyed|will be updated in-place|must be replaced)"
)
DESTROYED_LINE = re.compile(r"^(\S+): Destruction complete")
RB_GUARD = "Plan destroys runbook objects"
CI_GUARD = "Plan destroys resources. Destroys need a reviewed change"
GUARD_EXIT = "Process completed with exit code 1"

_mem = {"at": 0.0, "items": None}
_touch_mem = {}
_cmp_mem = {}


def touches(files):
    """True when any of these paths would start (or change) a runbook deploy run."""
    return any(f.startswith(w) or f == w for f in files or [] for w in WATCH)


def _pr_touches(pr):
    if pr not in _touch_mem:
        files = (_gh(["pr", "view", str(pr), "-R", REPO, "--json", "files"]) or {}).get(
            "files"
        ) or []
        _touch_mem[pr] = touches([f.get("path") or "" for f in files])
    return _touch_mem[pr]


def _main_moved_watch(base):
    """Runbook paths main changed since the run's commit ([] when main is that commit). Cached per pair."""
    main = _gh(["api", f"repos/{REPO}/commits/main", "--jq", ".sha"], raw=True).strip()
    if main == base:
        return []
    k = (base, main)
    if k not in _cmp_mem:
        cmp_ = _gh(["api", f"repos/{REPO}/compare/{base}...{main}", "--jq", "[.files[].filename]"])
        _cmp_mem[k] = [f for f in cmp_ or [] if touches([f])]
    return _cmp_mem[k]


class ReleaseError(Exception):
    def __init__(self, msg, code=502):
        super().__init__(msg)
        self.code = code


def _now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts(s):
    try:
        return (
            dt.datetime.strptime((s or "")[:19], "%Y-%m-%dT%H:%M:%S")
            .replace(tzinfo=dt.timezone.utc)
            .timestamp()
        )
    except ValueError:
        return 0


def _gh(args, timeout=60, raw=False):
    try:
        p = subprocess.run([GH] + args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ReleaseError(f"gh failed: {e}") from e
    if p.returncode != 0:
        raise ReleaseError(f"gh {' '.join(args[:3])}: {p.stderr.strip()[:300]}")
    if raw:
        return p.stdout
    return json.loads(p.stdout) if p.stdout.strip() else {}


def _load(p, default):
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return default


def _write(p, data):
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(p) + ".tmp")
    tmp.write_text(json.dumps(data, indent=1) + "\n")
    os.replace(tmp, p)


def _log(rec):
    STATE.mkdir(parents=True, exist_ok=True)
    with open(DECISIONS, "a") as f:
        f.write(json.dumps(dict({"ts": _now(), "lane": "runbook-release"}, **rec)) + "\n")


class _Locked:
    def __enter__(self):
        CACHE.mkdir(parents=True, exist_ok=True)
        self.f = open(STORE_LOCK, "w")
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


def parse_log(text):
    """Plan counts, planned deletes, applied deletes and error lines from one job log."""
    out = {
        "add": 0,
        "change": 0,
        "destroy": 0,
        "import": 0,
        "planned": [],
        "destroyed": [],
        "errors": [],
        "plan_seen": False,
    }
    for line in (text or "").splitlines():
        body = re.sub(r"\x1b\[[0-9;]*m", "", re.sub(r"^\S+Z ", "", line)).strip()
        if "grep" in body or body.startswith("echo ") or "SUMMARY=" in body:
            continue
        m = PLAN_LINE.search(body)
        if m:
            g = [int(x) for x in m.groups() if x is not None]
            imp, a, c, d = g if len(g) == 4 else [0] + g
            out.update({"import": imp, "add": a, "change": c, "destroy": d, "plan_seen": True})
            continue
        r = RES_LINE.search(body)
        if r:
            if r.group(2) == "will be destroyed":
                out["planned"].append(r.group(1))
            elif r.group(2) == "must be replaced":
                out["planned"].append(r.group(1) + " (replace)")
            continue
        d = DESTROYED_LINE.match(body)
        if d:
            out["destroyed"].append(d.group(1))
        if body.startswith("##[error]") or body.startswith("Error:"):
            out["errors"].append(body[:300])
    out["planned"] = sorted(set(out["planned"]))
    out["destroyed"] = sorted(set(out["destroyed"]))
    return out


def _guard_only(parsed, guard):
    errs = parsed["errors"]
    return (
        bool(errs)
        and parsed["destroy"] > 0
        and any(guard in e for e in errs)
        and all(guard in e or GUARD_EXIT in e for e in errs)
    )


def _job_log(run_id, job_name):
    jobs = _gh(["api", f"repos/{REPO}/actions/runs/{run_id}/jobs?per_page=100"]) or {}
    job = next((j for j in jobs.get("jobs", []) if j.get("name") == job_name), None)
    if not job:
        raise ReleaseError(f"run {run_id} has no job named {job_name}", 409)
    text = _gh(
        ["api", f"repos/{REPO}/actions/jobs/{job['id']}/logs", "--allow-escape-sequences"],
        raw=True,
        timeout=90,
    )
    return job, text


def _run_plan(run):
    """Parsed plan for one completed deploy-runbooks run (cached by run id)."""
    cache = _load(RUN_CACHE, {})
    key = str(run["id"])
    if key in cache:
        return cache[key]
    _, text = _job_log(run["id"], DEPLOY_JOB)
    parsed = parse_log(text)
    parsed["guard_only"] = run.get("conclusion") == "failure" and _guard_only(parsed, RB_GUARD)
    cache[key] = parsed
    if len(cache) > 200:
        for k in sorted(cache, key=int)[:-200]:
            cache.pop(k, None)
    _write(RUN_CACHE, cache)
    return parsed


def approved_set(plan_run_id, tier):
    """The deletes the owner approved: the runbooks plan job of the PR's terraform-ci run."""
    job, text = _job_log(plan_run_id, PR_PLAN_JOB.format(tier=tier))
    parsed = parse_log(text)
    if not (job.get("conclusion") == "failure" and _guard_only(parsed, CI_GUARD)):
        raise ReleaseError(
            f"the PR's runbooks plan job did not stop on the destroy guard alone (run {plan_run_id})",
            409,
        )
    if parsed["add"] or parsed["change"] or any(a.endswith("(replace)") for a in parsed["planned"]):
        raise ReleaseError("the PR's runbooks plan also adds, changes or replaces objects", 409)
    return parsed["planned"]


def record(pr, title, url, tier, plan_run_id, head):
    """Called right after Approve and merge on a PR whose runbooks root routes to the applier."""
    if tier != TIER:
        return f"runbooks ({tier}) deletes are applied from the branch, nothing recorded"
    rec = {
        "pr": pr,
        "title": title,
        "url": url,
        "tier": tier,
        "head_sha": head,
        "plan_run_id": plan_run_id,
        "approved_at": _now(),
        "approved": None,
        "error": None,
    }
    try:
        rec["approved"] = approved_set(plan_run_id, tier)
    except ReleaseError as e:
        rec["error"] = str(e)
    with _Locked():
        store = _load(STORE, {})
        store[str(pr)] = rec
        _write(STORE, store)
    _mem["items"] = None
    _log(
        {
            "pr": pr,
            "decision": "runbook_deletes_recorded",
            "tier": tier,
            "approved": rec["approved"],
            "error": rec["error"],
        }
    )
    if rec["error"]:
        return f"could not read the approved runbook deletes ({rec['error']}), see Needs me"
    return f"{len(rec['approved'])} runbook delete(s) wait for Release deletes under Needs me"


def _runs(since_iso):
    data = (
        _gh(["api", f"repos/{REPO}/actions/workflows/{WORKFLOW}/runs?branch=main&per_page=30"])
        or {}
    )
    runs = [
        r for r in data.get("workflow_runs", []) if _ts(r.get("created_at")) >= _ts(since_iso) - 5
    ]
    runs.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return runs


def _status(rec):
    """Live status for one record. state:
    error     = the approved set could not be read (no button, needs direction)
    waiting   = no finished main run after the merge yet (push run queued or running)
    ready     = newest main run stopped on the guard alone and deletes exactly the approved set
    mismatch  = newest main run failed some other way or plans a different set (no button)
    releasing = the owner's dispatch is queued or running
    released  = the dispatched run applied, destroyed set checked against the approved set
    failed    = the dispatched run failed
    done      = a later main run succeeded without the owner's dispatch (someone released it or nothing left)"""
    out = dict(rec)
    if not rec.get("dispatched_at") and not _pr_touches(rec["pr"]):
        # Recorded before the router knew this: the PR changes no runbook files, so no runbook deploy
        # runs for it and nothing here can ever be released. Not mine to act on.
        out.update(
            state="not_applicable",
            why="the PR changes no runbook files, so no runbook deploy runs for it",
        )
        return out
    if rec.get("error") or rec.get("approved") is None:
        out.update(state="error", why=rec.get("error") or "approved set unknown")
        return out
    approved = sorted(rec["approved"])
    runs = _runs(rec["approved_at"])
    if rec.get("dispatched_at"):
        mine = [
            r
            for r in runs
            if r.get("event") == "workflow_dispatch"
            and _ts(r.get("created_at")) >= _ts(rec["dispatched_at"]) - 10
        ]
        run = mine[-1] if mine else None  # oldest dispatch after mine = mine
        if not run or run.get("status") != "completed":
            out.update(
                state="releasing",
                run=_brief(run),
                why="the release run is starting"
                if not run
                else f"release run is {run.get('status')}",
            )
            return out
        p = _run_plan(run)
        out["run"] = _brief(run)
        if run.get("conclusion") != "success":
            out.update(
                state="failed",
                why=f"the release run ended {run.get('conclusion')}",
                errors=p["errors"][:5],
            )
            return out
        extra = sorted(set(p["destroyed"]) - set(approved))
        missing = sorted(set(approved) - set(p["destroyed"]))
        out.update(state="released", destroyed=p["destroyed"], extra=extra, missing=missing)
        out["why"] = (
            "applied"
            if not extra and not missing
            else "applied, but the destroyed set differs from what the owner approved"
        )
        return out
    done = [r for r in runs if r.get("status") == "completed"]
    if any(r.get("status") != "completed" for r in runs) or not done:
        out.update(
            state="waiting",
            why="the deploy-runbooks run on main has not finished yet",
            run=_brief(runs[0] if runs else None),
        )
        return out
    newest = done[0]
    out["run"] = _brief(newest)
    if newest.get("conclusion") == "success":
        out.update(state="done", why="a later main run succeeded, nothing waits on me")
        return out
    p = _run_plan(newest)
    out["plan"] = {k: p[k] for k in ("add", "change", "destroy", "import", "planned")}
    if not p["guard_only"]:
        out.update(
            state="mismatch",
            why="the newest main run failed on something other than the destroy guard",
            errors=p["errors"][:5],
        )
        return out
    if p["add"] or p["change"] or p["import"] or sorted(p["planned"]) != approved:
        out.update(
            state="mismatch",
            why="the main plan does not match what the owner approved",
            extra=sorted(set(p["planned"]) - set(approved)),
            missing=sorted(set(approved) - set(p["planned"])),
        )
        return out
    moved = _main_moved_watch(newest.get("head_sha"))
    if moved:
        # release() refuses this, so the card must not offer it: the next main run re-plans.
        out.update(
            state="waiting",
            why=f"main changed runbook files since that run ({', '.join(moved[:3])}), the next main run re-plans",
        )
        return out
    out.update(
        state="ready",
        why="the main run stopped on the destroy guard and deletes exactly what the owner approved",
    )
    return out


def _brief(run):
    if not run:
        return None
    return {
        "id": run.get("id"),
        "url": run.get("html_url"),
        "event": run.get("event"),
        "status": run.get("status"),
        "conclusion": run.get("conclusion"),
        "head_sha": run.get("head_sha"),
        "created_at": run.get("created_at"),
    }


def items(force=False):
    """Records still worth showing, each with its live status."""
    if not force and _mem["items"] is not None:
        age = time.time() - _mem["at"]
        if age < TTL_S:
            return _mem["items"]
        if age < swr.MAX_STALE_S:
            swr.kick("runbook_releases", lambda: items(force=True))  # refresh off the request path
            return _mem["items"]
    store = _load(STORE, {})
    out = []
    for rec in store.values():
        try:
            st = _status(rec)
        except ReleaseError as e:
            st = dict(rec, state="unknown", why=f"could not read the runs: {e}")
        if st["state"] == "not_applicable":
            continue
        if (
            st["state"] in ("done", "released")
            and time.time() - _ts(rec.get("released_at") or rec.get("approved_at")) > DONE_SHOW_S
        ):
            continue
        out.append(st)
    out.sort(key=lambda x: x.get("approved_at") or "")
    _mem.update(at=time.time(), items=out)
    return out


def needs_me(its):
    """Items that need me: a release to sign off, or one that went wrong."""
    return [
        i
        for i in its
        if i.get("state") in ("ready", "mismatch", "error", "failed")
        or (i.get("state") == "released" and (i.get("extra") or i.get("missing")))
    ]


def release(payload):
    """Release deletes: dispatch deploy-runbooks on main with allow_destroy=true."""
    try:
        pr = int(payload.get("pr"))
        run_id = int(payload.get("run_id"))
    except (TypeError, ValueError):
        raise ReleaseError("pr and run_id required", 400) from None
    with _Locked():
        store = _load(STORE, {})
        rec = store.get(str(pr))
        if not rec:
            raise ReleaseError(f"no runbook release recorded for #{pr}", 404)
        if rec.get("dispatched_at"):
            raise ReleaseError(f"#{pr} was already released at {rec['dispatched_at']}", 409)
        st = _status(rec)
        if st["state"] != "ready":
            raise ReleaseError(f"#{pr} is not ready to release: {st.get('why')}", 409)
        if (st.get("run") or {}).get("id") != run_id:
            raise ReleaseError("a newer deploy run exists. Refresh first.", 409)
        main = _gh(["api", f"repos/{REPO}/commits/main", "--jq", ".sha"], raw=True).strip()
        base = st["run"]["head_sha"]
        if main != base:
            cmp_ = _gh(
                ["api", f"repos/{REPO}/compare/{base}...{main}", "--jq", "[.files[].filename]"]
            )
            moved = [f for f in cmp_ or [] if any(f.startswith(w) or f == w for w in WATCH)]
            if moved:
                raise ReleaseError(
                    f"main changed runbook files since that plan ({', '.join(moved[:3])}). Wait for the next run.",
                    409,
                )
        _gh(
            ["workflow", "run", WORKFLOW, "-R", REPO, "--ref", "main", "-f", "allow_destroy=true"],
            raw=True,
        )
        rec["dispatched_at"] = _now()
        rec["dispatched_by"] = SELF
        rec["dispatched_main"] = main
        rec["released_at"] = rec["dispatched_at"]
        store[str(pr)] = rec
        _write(STORE, store)
    _mem["items"] = None
    _log(
        {
            "pr": pr,
            "decision": "runbook_deletes_released",
            "by": SELF,
            "main": main,
            "approved": rec["approved"],
            "checked_run": run_id,
        }
    )
    return {
        "pr": pr,
        "done": [
            f"started deploy-runbooks on main with allow_destroy for {len(rec['approved'])} runbook delete(s)"
        ],
    }
