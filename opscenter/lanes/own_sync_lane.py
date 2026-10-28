#!/usr/bin/env python3
"""
own_sync_lane.py
Purpose: Auto-fix lane for the owner's nightly sync PRs on a repository (the policy "repo"). The sync opens a PR
         every night from the live install, and GitHub auto-merge lands it once CI is green. When
         CI is red (lint findings in new live scripts, a conflict), nothing fixed it until the owner opened
         a session. Every pass this lane lists the owner's open sync PRs, classifies each one, and hands
         held ones to autofix.consider(), which starts ONE fix session at once for a fixable
         problem (red checks, merge conflict) under the same caps as primary and secondary.
         This lane never merges, approves, labels or comments. GitHub auto-merge merges.
         Only the owner's PRs (author the owner's account) on a branch matching branch_prefixes (default sync/, an empty
         prefix "" takes every branch of mine, so feature PRs get the same auto-fix). Everything else
         is skipped.
         Stuck green (2026-10-22): a PR green for stale_ready_min (default 20) that the CI gate never
         merged gets its latest ci run re-run once per head (the gate merges on the re-run). Still open
         one more window later, or waiting with no checks that long, prints one line per head.
Date:    2026-10-14

Usage:   own_sync_lane.py tick          (cron, every 5 min, prints only what needs me)
         own_sync_lane.py status        (prints the state file)
         own_sync_lane.py check <pr>    (read-only: prints the decision, starts nothing)
Policy:  <state dir>/sync-review/own-pr-policy.json (kill switch own_pr_merge.enabled and
         own_pr_merge.autofix.enabled, caps in own_pr_merge.autofix). A missing file means the
         defaults below. An unreadable file fails closed (no session, counted as a lane error).
Output:  tick prints [sync the owner's PR] lines only when an auto-fix gave up or the lane keeps failing.
Exit:    0 always for tick (the cron must stay quiet), 2 on bad usage.
Test hooks: MXLANE_GH_BIN, MXLANE_CACHE_DIR, MXLANE_POLICY, MXLANE_NOW (ISO UTC),
            OWNPR_FIX_SPAWN=record and OWNPR_STATE_DB (the fixer's own hooks).
System python3 is 3.9: no 3.10+ syntax.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import paths

HOME = Path.home()
TARGET = "sync"
TAG = "[sync the owner's PR]"
FIXER_PY = Path(os.environ.get("MXLANE_FIXER", str(Path(__file__).resolve().parent / "autofix.py")))
POLICY_FILE = Path(
    os.environ.get("MXLANE_POLICY", str(paths.state_dir() / "sync-review" / "own-pr-policy.json"))
)
CACHE_DIR = Path(
    os.environ.get("MXLANE_CACHE_DIR", str(paths.agent_home() / "cache" / "sync-own-pr"))
)
STATE_FILE = CACHE_DIR / "own-pr-merge.json"
DECISIONS = CACHE_DIR / "decisions.jsonl"
LOCK_FILE = CACHE_DIR / "lane.lock"
GH = os.environ.get("MXLANE_GH_BIN") or shutil.which("gh") or paths.which("gh")
DEFAULTS = {
    "repo": "owner/sync-repo",
    "self_login": "owner-account",
    "branch_prefixes": ["sync/"],
    "own_pr_merge": {
        "enabled": True,
        "hold_labels": ["do-not-merge", "hold"],
        "autofix": {"enabled": True, "max_sessions_per_day": 3, "run_budget_s": 5400},
    },
    "stale_ready_min": 20,
    "ci_workflow": "ci.yml",
}
# Aggregate jobs only restate the others. They count only when nothing else is red.
AGGREGATE = {"gate", "changes"}
OK = {"SUCCESS", "NEUTRAL", "SKIPPED", "STALE"}
RED = {"FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE", "ERROR"}
ALERT_AT = (3, 20)  # consecutive lane errors that print one line each


class GhError(Exception):
    pass


class PolicyError(Exception):
    pass


def now_utc():
    raw = os.environ.get("MXLANE_NOW")
    if raw:
        return dt.datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    return dt.datetime.now(dt.timezone.utc)


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def gh(args, timeout=60):
    """Parsed JSON from gh. Any failure (missing binary, timeout, non-zero exit, bad JSON) raises."""
    try:
        p = subprocess.run([GH] + list(args), capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        raise GhError(f"gh {' '.join(args[:2])}: {type(e).__name__}: {e}")  # noqa: B904
    if p.returncode != 0:
        raise GhError(f"gh {' '.join(args[:2])} exit {p.returncode}: {p.stderr.strip()[:300]}")
    try:
        return json.loads(p.stdout) if p.stdout.strip() else None
    except ValueError as e:
        raise GhError(f"gh {' '.join(args[:2])}: unreadable JSON: {e}")  # noqa: B904


def load_policy():
    pol = json.loads(json.dumps(DEFAULTS))
    if not POLICY_FILE.exists():
        return pol
    try:
        raw = json.loads(POLICY_FILE.read_text())
    except (OSError, ValueError) as e:
        raise PolicyError(f"policy {POLICY_FILE} unreadable: {e}")  # noqa: B904
    if not isinstance(raw, dict):
        raise PolicyError(f"policy {POLICY_FILE} is not an object")
    own = dict(pol["own_pr_merge"])
    own.update(raw.get("own_pr_merge") or {})
    af = dict(DEFAULTS["own_pr_merge"]["autofix"])
    af.update((raw.get("own_pr_merge") or {}).get("autofix") or {})
    own["autofix"] = af
    pol.update({k: v for k, v in raw.items() if k != "own_pr_merge"})
    pol["own_pr_merge"] = own
    return pol


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def write_json(path, data):
    """Atomic write: temp file in the same folder, fsync, replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=1, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, str(path))
    except BaseException:
        try:  # noqa: SIM105
            os.unlink(tmp)
        except OSError:
            pass
        raise


def log(rec, now):
    DECISIONS.parent.mkdir(parents=True, exist_ok=True)
    with open(DECISIONS, "a") as fh:
        fh.write(json.dumps(dict({"at": iso(now), "lane": "sync-own-pr"}, **rec)) + "\n")


def checks(rollup):
    """(red, pending) check names from a statusCheckRollup, newest result per (workflow, check)."""
    best = {}
    for c in rollup or []:
        name = c.get("name") or c.get("context") or "?"
        key = (c.get("workflowName") or "", name)
        when = c.get("completedAt") or c.get("startedAt") or ""
        val = (c.get("conclusion") or c.get("state") or c.get("status") or "PENDING").upper()
        if key not in best or when >= best[key][0]:
            best[key] = (when, val)
    red = sorted({k[1] for k, (_, v) in best.items() if v in RED})
    pending = sorted({k[1] for k, (_, v) in best.items() if v not in RED and v not in OK})
    own_red = [n for n in red if n not in AGGREGATE]
    return (own_red or red), pending, len(best)


def classify(pr, pol):
    """(status, reason). status: skip (not this lane), held, waiting, or ready (GitHub merges it)."""
    author = (pr.get("author") or {}).get("login")
    if author != pol["self_login"]:
        return "skip", f"not my PR (author {author})"
    branch = pr.get("headRefName") or ""
    if not any(branch.startswith(p) for p in pol.get("branch_prefixes") or []):
        return "skip", f"not a sync branch ({branch})"
    if pr.get("isDraft"):
        return "held", "draft"
    labels = {(lbl.get("name") or "").lower() for lbl in pr.get("labels") or []}
    hit = sorted(labels & {h.lower() for h in pol["own_pr_merge"].get("hold_labels") or []})
    if hit:
        return "held", f"label {hit[0]}"
    if pr.get("mergeable") == "CONFLICTING":
        return "held", "merge conflict with main"
    red, pending, total = checks(pr.get("statusCheckRollup"))
    if red:
        return "held", "checks red: " + ", ".join(red)[:200]
    if pending:
        return "waiting", f"{len(pending)} check(s) running"
    if not total:
        return "waiting", "no checks reported yet"
    return "ready", "all checks green, GitHub auto-merge lands it"


def list_mine(pol):
    prs = gh(
        [
            "pr",
            "list",
            "-R",
            pol["repo"],
            "--author",
            pol["self_login"],
            "--state",
            "open",
            "--limit",
            "50",
            "--json",
            "number,title,url,author,headRefOid,headRefName,isDraft,mergeable,statusCheckRollup,labels,updatedAt",
        ]
    )
    if not isinstance(prs, list):
        raise GhError("gh pr list returned no list")
    return prs


def _age_min(since, now):
    try:
        t = dt.datetime.strptime(since, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return 0
    return (now - t).total_seconds() / 60


def unstick(pr, rec, pol, now):
    """A green PR the gate never merged: re-run its latest ci run once per head, then report once.
    A PR that never got checks gets the report only. Returns a line to print, or None."""
    stale = float(pol.get("stale_ready_min") or 20)
    n = pr["number"]
    if rec.get("status") not in ("ready", "waiting") or _age_min(rec.get("since"), now) < stale:
        return None
    if rec.get("status") == "waiting" and rec.get("reason") != "no checks reported yet":
        return None
    if rec.get("status") == "ready" and not rec.get("kicked"):
        runs = gh(
            [
                "run",
                "list",
                "-R",
                pol["repo"],
                "--workflow",
                pol.get("ci_workflow") or "ci.yml",
                "--commit",
                pr["headRefOid"],
                "--json",
                "databaseId,status",
                "--limit",
                "1",
            ]
        )
        rec["kicked"] = iso(now)
        if runs and runs[0].get("status") == "completed":
            gh(["run", "rerun", str(runs[0]["databaseId"]), "-R", pol["repo"]])
            rec["kicked_run"] = runs[0]["databaseId"]
            log(
                {
                    "pr": n,
                    "decision": "gate-rerun",
                    "sha": pr["headRefOid"],
                    "detail": runs[0]["databaseId"],
                },
                now,
            )
        return None
    if rec.get("status") == "ready" and _age_min(rec.get("kicked"), now) < stale:
        return None
    if rec.get("stuck_reported"):
        return None
    rec["stuck_reported"] = iso(now)
    what = (
        "green but the gate has not merged it after a re-run"
        if rec["status"] == "ready"
        else "no checks ran"
    )
    log({"pr": n, "decision": "stuck", "sha": pr["headRefOid"], "detail": what}, now)
    return f"{TAG} PR #{n} {what} ({int(_age_min(rec.get('since'), now))} min): {pr.get('url')}"


def _fixer():
    spec = importlib.util.spec_from_file_location("autofix", str(FIXER_PY))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def tick():
    now = now_utc()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOCK_FILE, "w") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("sync own-PR lane: another pass is running, skipped", file=sys.stderr)
            return
        _tick_locked(now)


def _tick_locked(now):
    st = load_json(STATE_FILE, {})
    prs_state = st.setdefault("prs", {})
    fix_state = st.setdefault("fix", {})
    out = []
    try:
        pol = load_policy()
        own = pol["own_pr_merge"]
        if not own.get("enabled", True):
            st["disabled"] = True
            return
        st.pop("disabled", None)
        fixer = _fixer()
        mine = list_mine(pol)
        open_nums = set()
        for pr in mine:
            n = str(pr["number"])
            status, reason = classify(pr, pol)
            if status == "skip":
                prs_state.pop(n, None)
                continue
            open_nums.add(n)
            rec = prs_state.setdefault(n, {})
            if rec.get("head") != pr["headRefOid"]:
                rec.clear()
                rec["head"] = pr["headRefOid"]
            rec.update({"title": pr.get("title"), "url": pr.get("url")})
            if rec.get("status") != status or rec.get("reason") != reason:
                for k in ("kicked", "kicked_run", "stuck_reported"):
                    rec.pop(k, None)
                rec.update({"status": status, "reason": reason, "since": iso(now)})
                if status == "held":
                    log(
                        {
                            "pr": pr["number"],
                            "decision": "held",
                            "sha": pr["headRefOid"],
                            "detail": reason,
                        },
                        now,
                    )
            try:
                stuck = unstick(pr, rec, pol, now)
            except GhError as e:
                stuck = None
                rec["unstick_error"] = str(e)[:200]
            if stuck:
                out.append(stuck)
            frec = fix_state.setdefault(n, {})
            try:
                line = fixer.consider(
                    TARGET,
                    TAG,
                    pol["repo"],
                    pol["self_login"],
                    pr,
                    status,
                    reason,
                    frec,
                    own,
                    CACHE_DIR / "autofix",
                    now,
                )
            except Exception as e:  # noqa: BLE001 - one PR's fixer error must not stop the lane
                line = None
                frec["error"] = f"{type(e).__name__}: {str(e)[:200]}"
            run = frec.get("running")
            if run and run.get("started") == iso(now):
                log(
                    {
                        "pr": pr["number"],
                        "decision": "autofix-started",
                        "sha": pr["headRefOid"],
                        "detail": run.get("problem"),
                        "pid": run.get("pid"),
                    },
                    now,
                )
            if line:
                log(
                    {
                        "pr": pr["number"],
                        "decision": "autofix-gave-up",
                        "sha": pr["headRefOid"],
                        "detail": line,
                    },
                    now,
                )
                out.append(line)
        for n in list(prs_state):
            if n not in open_nums:
                del prs_state[n]
        for n in list(fix_state):
            if n not in open_nums and not fixer.run_alive(fix_state[n].get("running")):
                del fix_state[n]
        st["error_count"] = 0
        st.pop("last_error", None)
    except (GhError, PolicyError, OSError, ValueError, KeyError, ImportError) as e:
        # Fail closed: nothing is started on a failed read, and the error is counted and shown.
        st["error_count"] = int(st.get("error_count", 0)) + 1
        st["last_error"] = f"{type(e).__name__}: {str(e)[:300]}"
        if st["error_count"] in ALERT_AT:
            out.append(
                f"{TAG} auto-fix lane failing ({st['error_count']} passes in a row): {st['last_error']}"
            )
    finally:
        st["updated"] = iso(now)
        write_json(STATE_FILE, st)
        if out:
            print("\n".join(out))


def check_one(n):
    pol = load_policy()
    prs = [p for p in list_mine(pol) if int(p["number"]) == n]
    if not prs:
        print(json.dumps({"pr": n, "status": "not an open PR of mine"}))
        return
    status, reason = classify(prs[0], pol)
    print(
        json.dumps(
            {"pr": n, "head": prs[0]["headRefOid"], "status": status, "reason": reason}, indent=2
        )
    )


def main(argv):
    cmd = argv[0] if argv else "tick"
    if cmd == "tick":
        tick()
        return 0
    if cmd == "status":
        print(json.dumps(load_json(STATE_FILE, {}), indent=2))
        return 0
    if cmd == "check" and len(argv) == 2 and argv[1].isdigit():
        try:
            check_one(int(argv[1]))
        except (GhError, PolicyError) as e:
            print(f"check failed: {e}", file=sys.stderr)
            return 1
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
