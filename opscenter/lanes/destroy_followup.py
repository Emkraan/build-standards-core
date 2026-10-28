#!/usr/bin/env python3
"""Destroy follow-up.

Purpose: When the Ops Center Approve and merge dispatches terraform-destroy for a root, the push
         to main starts terraform-apply at the same moment. That apply plans the pending deletes,
         hits the destroy guard and fails, so main shows a red deploy even though the destroy
         lands a minute later. This tick watches each dispatched destroy and, once it succeeded,
         re-runs the failed jobs of the NEWEST terraform-apply run on main, but only when that run
         failed on nothing except the destroy guard for roots a successful destroy has covered.
         The re-run plans again (0 deletes now) and main goes green.
Date:    2026-10-13

Usage:   destroy_followup.py tick     (called from the review gate script every 3 min)
         destroy_followup.py status

Output:  silent unless a re-run failed, the newest main apply failed for another reason, or the
         tick itself failed 3 times in a row. Each of those prints one [primary DESTROY] line once.
Env:     OPRG_GH_BIN (gh path), OPRG_STATE_DIR (decisions.jsonl dir), OPRG_CACHE_DIR (state file
         dir), OPRG_DRY_RUN=1 (log would_rerun, never POST), OPRG_NOW (ISO time, tests only).
Kill:    policy.json destroy_followup.enabled = false.
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import paths
from gh_run_jobs import run_jobs

REPO = os.environ.get("OPSCENTER_REPO", "owner/primary-repo")
PROD_TIER = os.environ.get("OPSCENTER_PROD_TIER", "prod")
TIERS = os.environ.get(
    "OPSCENTER_TIERS", "prod|dev"
)  # tier names in the apply job titles, as a regex alternation
HOME = Path.home()
GH = os.environ.get("OPRG_GH_BIN", "gh")
STATE_DIR = Path(os.environ.get("OPRG_STATE_DIR", str(paths.state_dir() / "review")))
CACHE_DIR = Path(
    os.environ.get("OPRG_CACHE_DIR", str(paths.agent_home() / "cache/primary-pr-review"))
)
DECISIONS = STATE_DIR / "decisions.jsonl"
POLICY = STATE_DIR / "policy.json"
STATE = CACHE_DIR / "destroy-followup.json"
DRY = os.environ.get("OPRG_DRY_RUN") == "1"

WINDOW = timedelta(hours=48)  # dispatches older than this are expired, never acted on
MATCH_BEFORE = timedelta(minutes=2)  # a destroy run may be created this long before the log line
MATCH_AFTER = timedelta(minutes=10)
FINAL = {
    "main_green",
    "rerun_ok",
    "rerun_failed",
    "not_guard_only",
    "destroy_failed",
    "no_destroy_run",
    "expired",
}
GUARD_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+): plan deletes \d+ resource\(s\)\. Deletes are "
    r"applied only by terraform-destroy\.yml"
)
EXIT_RE = re.compile(r"^Process completed with exit code \d+\.$")
ERR_RE = re.compile(r"##\[error\](.*)$")
ROOTS_RE = re.compile(r"ROOTS: (\[.*\])\s*$")
APPLY_JOB_RE = re.compile(r"^apply \((" + TIERS + r")\)$")


class GhError(Exception):
    pass


def now():
    v = os.environ.get("OPRG_NOW")
    return parse_ts(v) if v else datetime.now(timezone.utc)


def parse_ts(s):
    return datetime.strptime(s.replace("Z", "+00:00")[:25], "%Y-%m-%dT%H:%M:%S%z")


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def gh(args, raw=False):
    p = subprocess.run([GH] + args, capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise GhError(f"gh {' '.join(args[:3])}: {(p.stderr or p.stdout).strip()[:300]}")
    return p.stdout if raw else json.loads(p.stdout or "null")


def job_log(job_id):
    return gh(
        ["api", f"repos/{REPO}/actions/jobs/{job_id}/logs", "--allow-escape-sequences"], raw=True
    )


def jobs(run_id):
    return run_jobs(gh, REPO, run_id)


def log_decision(rec):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(DECISIONS, "a") as f:
        f.write(json.dumps(dict({"ts": iso(now()), "lane": "destroy-followup"}, **rec)) + "\n")


def load(p, default):
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return default


def save_state(st):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(st, indent=2) + "\n")
    os.replace(tmp, STATE)


def enabled():
    return load(POLICY, {}).get("destroy_followup", {}).get("enabled", True) is not False


def dispatches():
    """destroy_dispatched records for the production tier inside the window, oldest first."""
    out = []
    try:
        lines = DECISIONS.read_text().splitlines()
    except OSError:
        return out
    cutoff = now() - WINDOW
    for ln in lines:
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if (
            d.get("decision") != "destroy_dispatched"
            or d.get("tier") != PROD_TIER
            or not d.get("tool")
        ):
            continue
        try:
            ts = parse_ts(d["ts"])
        except (KeyError, ValueError):
            continue
        if ts >= cutoff:
            out.append(dict(d, _ts=ts, _key=f"{d.get('pr')}:{d['tool']}:{d['ts']}"))
    return out


def run_roots(run_id):
    """Root names a terraform-destroy run handles, read from its plan job's ROOTS env line."""
    plan = [j for j in jobs(run_id) if j.get("name", "").startswith("plan")]
    if not plan:
        return set()  # resolve failed or has not finished: decided by the run status below
    j = plan[0]
    if j.get("conclusion") in ("skipped", "cancelled"):
        return set()
    if j.get("status") not in ("in_progress", "completed"):
        return None
    try:
        text = job_log(j["id"])
    except GhError:
        return None  # log not available yet
    for ln in text.splitlines():
        m = ROOTS_RE.search(ln)
        if m:
            try:
                return {r.get("name") for r in json.loads(m.group(1))}
            except ValueError:
                return None
    return None


def find_destroy_run(rec, runs, claimed):
    """The terraform-destroy dispatch run for this record: created near the log line, on main,
    by the same actor, not claimed by another record, and planning this root."""
    lo, hi = rec["_ts"] - MATCH_BEFORE, rec["_ts"] + MATCH_AFTER
    for r in sorted(runs, key=lambda x: x["created_at"]):
        if (
            r["id"] in claimed
            or r.get("event") != "workflow_dispatch"
            or r.get("head_branch") != "main"
        ):
            continue
        if rec.get("by") and (r.get("actor") or {}).get("login") not in (None, rec["by"]):
            continue
        c = parse_ts(r["created_at"])
        if not (lo <= c <= hi):
            continue
        names = run_roots(r["id"])
        if names is None:
            return "pending"
        if rec["tool"] in names:
            return r
    return None


def guard_only(run_id, covered):
    """(ok, blocked_roots, why). ok when the only failed job is apply (<tier>) and every error
    line in it is the destroy guard for a covered root or the trailing exit-code line."""
    failed = [j for j in jobs(run_id) if j.get("conclusion") == "failure"]
    if not failed:
        return False, set(), "no failed job"
    bad = [j["name"] for j in failed if not APPLY_JOB_RE.match(j.get("name", ""))]
    if bad:
        return False, set(), f"failed job(s) besides the apply: {', '.join(bad)}"
    blocked = set()
    for j in failed:
        for ln in job_log(j["id"]).splitlines():
            m = ERR_RE.search(ln)
            if not m:
                continue
            msg = m.group(1).strip()
            if EXIT_RE.match(msg):
                continue
            g = GUARD_RE.match(msg)
            if not g:
                return False, blocked, f"error that is not the destroy guard: {msg[:160]}"
            blocked.add(g.group("name"))
    if not blocked:
        return False, blocked, "no destroy-guard error found"
    missing = blocked - covered
    if missing:
        return (
            False,
            blocked,
            f"guard blocked root(s) with no successful destroy: {', '.join(sorted(missing))}",
        )
    return True, blocked, ""


def newest_main_apply():
    runs = gh(
        [
            "api",
            f"repos/{REPO}/actions/workflows/terraform-apply.yml/runs?branch=main&event=push&per_page=5",
            "--jq",
            ".workflow_runs",
        ]
    )
    return max(runs, key=lambda r: r["created_at"]) if runs else None


def tick():
    if not enabled():
        return []
    st = load(STATE, {"items": {}, "fail": 0})
    items = st.setdefault("items", {})
    out = []
    recs = dispatches()
    live = [r for r in recs if items.get(r["_key"], {}).get("status") not in FINAL]
    # expire old non-final items
    keys = {r["_key"] for r in recs}
    for k, v in items.items():
        if k not in keys and v.get("status") not in FINAL:
            v.update(status="expired", at=iso(now()))
    if not live:
        prune(items)
        save_state(st)
        return out

    druns = gh(
        [
            "api",
            f"repos/{REPO}/actions/workflows/terraform-destroy.yml/runs?branch=main&per_page=20",
            "--jq",
            ".workflow_runs",
        ]
    )
    claimed = {v.get("destroy_run") for v in items.values() if v.get("destroy_run")}
    # Successful destroys we know about cover their roots.
    covered = {v.get("tool") for v in items.values() if v.get("destroy_ok")}
    for rec in live:
        it = items.setdefault(
            rec["_key"], {"pr": rec.get("pr"), "tool": rec["tool"], "status": "waiting_destroy"}
        )
        if not it.get("destroy_run"):
            r = find_destroy_run(rec, druns, claimed)
            if r == "pending":
                continue
            if r is None:
                if now() - rec["_ts"] > MATCH_AFTER + timedelta(minutes=5):
                    it.update(status="no_destroy_run", at=iso(now()))
                    log_decision(
                        {"pr": rec.get("pr"), "decision": "no_destroy_run", "tool": rec["tool"]}
                    )
                continue
            it["destroy_run"] = r["id"]
            claimed.add(r["id"])
        d = next((x for x in druns if x["id"] == it["destroy_run"]), None)
        if d is None:
            d = gh(["api", f"repos/{REPO}/actions/runs/{it['destroy_run']}"])
        if d.get("status") != "completed":
            it["status"] = "waiting_destroy"
            continue
        if d.get("conclusion") != "success":
            it.update(status="destroy_failed", at=iso(now()), conclusion=d.get("conclusion"))
            log_decision(
                {
                    "pr": rec.get("pr"),
                    "decision": "destroy_not_successful",
                    "tool": rec["tool"],
                    "run": d["id"],
                    "conclusion": d.get("conclusion"),
                }
            )
            continue
        it["destroy_ok"] = True
        covered.add(rec["tool"])
        if it.get("status") == "waiting_destroy":
            it["status"] = "waiting_apply"

    # One decision per tick about main's newest apply run, shared by every destroy that is done.
    ready = [
        items[r["_key"]]
        for r in live
        if items.get(r["_key"], {}).get("status") in ("waiting_apply", "rerun")
    ]
    if ready:
        a = newest_main_apply()
        rerun_of = {it.get("rerun_run") for it in ready if it.get("status") == "rerun"}
        if a is None:
            pass
        elif a["id"] in rerun_of:
            want = max(it.get("rerun_attempt", 0) for it in ready if it.get("rerun_run") == a["id"])
            if a.get("status") == "completed" and (a.get("run_attempt") or 1) >= want:
                ok = a.get("conclusion") == "success"
                for it in ready:
                    if it.get("rerun_run") == a["id"]:
                        it.update(status="rerun_ok" if ok else "rerun_failed", at=iso(now()))
                log_decision(
                    {
                        "decision": "apply_rerun_ok" if ok else "apply_rerun_failed",
                        "run": a["id"],
                        "attempt": a.get("run_attempt"),
                    }
                )
                if not ok:
                    out.append(
                        f"[primary DESTROY] main terraform-apply run {a['id']} failed again after I "
                        f"re-ran it behind the destroy: {a.get('html_url', '')}"
                    )
        elif a.get("status") != "completed":
            pass  # a newer apply is running, judge it when it finishes
        elif a.get("conclusion") == "success":
            for it in ready:
                it.update(status="main_green", at=iso(now()), apply_run=a["id"])
            log_decision(
                {
                    "decision": "main_green",
                    "run": a["id"],
                    "tools": sorted(it["tool"] for it in ready),
                }
            )
        else:
            ok, blocked, why = guard_only(a["id"], covered)
            waiting = {
                items[r["_key"]]["tool"]
                for r in live
                if items.get(r["_key"], {}).get("status") == "waiting_destroy"
            }
            if not ok and blocked and (blocked - covered) and (blocked - covered) <= waiting:
                pass  # another dispatched destroy covers the rest, wait for it
            elif not ok:
                for it in ready:
                    it.update(status="not_guard_only", at=iso(now()), apply_run=a["id"], why=why)
                log_decision({"decision": "apply_not_guard_only", "run": a["id"], "why": why})
                out.append(
                    f"[primary DESTROY] main terraform-apply run {a['id']} is red for a reason I do "
                    f"not re-run ({why}): {a.get('html_url', '')}"
                )
            elif DRY:
                log_decision({"decision": "would_rerun", "run": a["id"], "roots": sorted(blocked)})
            else:
                gh(["run", "rerun", str(a["id"]), "--failed", "-R", REPO], raw=True)
                for it in ready:
                    it.update(
                        status="rerun",
                        rerun_run=a["id"],
                        rerun_attempt=(a.get("run_attempt") or 1) + 1,
                        at=iso(now()),
                    )
                log_decision({"decision": "apply_rerun", "run": a["id"], "roots": sorted(blocked)})
    prune(items)
    save_state(st)
    return out


def prune(items):
    """Drop final items older than 14 days."""
    cutoff = now() - timedelta(days=14)
    for k in [
        k
        for k, v in items.items()
        if v.get("status") in FINAL and v.get("at") and parse_ts(v["at"]) < cutoff
    ]:
        del items[k]


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "tick"
    if cmd == "status":
        for k, v in load(STATE, {"items": {}}).get("items", {}).items():
            print(
                k,
                v.get("status"),
                v.get("destroy_run", ""),
                v.get("rerun_run", v.get("apply_run", "")),
            )
        return 0
    if cmd != "tick":
        print(__doc__)
        return 2
    try:
        lines = tick()
        st = load(STATE, {"items": {}})
        if st.get("fail"):
            st["fail"] = 0
            save_state(st)
    except (GhError, subprocess.TimeoutExpired, OSError, ValueError, KeyError) as e:
        st = load(STATE, {"items": {}})
        st["fail"] = st.get("fail", 0) + 1
        save_state(st)
        lines = (
            [f"[primary DESTROY] follow-up tick failed {st['fail']} times in a row: {str(e)[:200]}"]
            if st["fail"] == 3
            else []
        )
    for ln in lines:
        print(ln)
    return 0


if __name__ == "__main__":
    sys.exit(main())
