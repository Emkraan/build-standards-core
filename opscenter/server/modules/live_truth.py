"""
live_truth.py
Purpose: Live GitHub facts every Needs me lane checks before it shows a card as actionable
         (a card that cannot be actioned is not shown as actionable). Two facts, both refreshed in the background so a page GET never waits:
           pr_heads(repo)  -> {pr number: head sha} of the repo's open PRs, or None when unknown
           run(run_id)     -> {status, head_sha, run_attempt, head_branch, envs} or None when unknown
         The first call for a key blocks once (cold cache), later calls serve the cached value and
         kick one refresh when it is older than TTL_S. Unknown never hides a card: the action
         endpoint still re-verifies everything at click time.
Date:    2026-10-13
"""

import json
import os
import subprocess
import threading
import time

import paths

GH = os.environ.get("LIVE_TRUTH_GH", paths.which("gh"))
TTL_S = 20
_lock = threading.Lock()
_mem = {}  # key -> {"at": epoch, "val": value, "busy": bool}


def _gh(args, timeout=30):
    p = subprocess.run([GH] + args, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip()[:200])
    return json.loads(p.stdout) if p.stdout.strip() else None


def _fetch_heads(repo):
    rows = (
        _gh(
            [
                "pr",
                "list",
                "-R",
                repo,
                "--state",
                "open",
                "--limit",
                "200",
                "--json",
                "number,headRefOid",
            ]
        )
        or []
    )
    return {int(r["number"]): r["headRefOid"] for r in rows}


def _fetch_run(repo_run):
    repo, rid = repo_run
    r = _gh(["api", f"repos/{repo}/actions/runs/{rid}"]) or {}
    envs = []
    if r.get("status") == "waiting":
        pend = _gh(["api", f"repos/{repo}/actions/runs/{rid}/pending_deployments"]) or []
        envs = sorted(
            {str(n) for n in ((p.get("environment") or {}).get("name") for p in pend) if n}
        )
    return {
        "status": r.get("status"),
        "head_sha": r.get("head_sha"),
        "run_attempt": r.get("run_attempt"),
        "head_branch": r.get("head_branch"),
        "envs": envs,
    }


def _refresh(key, fn, arg):
    try:
        val = fn(arg)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
        val = None
    with _lock:
        ent = _mem.setdefault(key, {})
        # Keep the last good value on a failed read for one more TTL, then report unknown.
        if val is not None or time.time() - ent.get("at", 0) > 3 * TTL_S:
            ent["val"] = val
            ent["at"] = time.time()
        ent["busy"] = False


def _get(key, fn, arg):
    with _lock:
        ent = _mem.get(key)
        cold = ent is None
        if cold:
            ent = _mem[key] = {"at": 0.0, "val": None, "busy": True}
        elif time.time() - ent["at"] > TTL_S and not ent["busy"]:
            ent["busy"] = True
            threading.Thread(target=_refresh, args=(key, fn, arg), daemon=True).start()
    if cold:
        _refresh(key, fn, arg)
    return _mem[key]["val"]


def pr_heads(repo):
    return _get(("heads", repo), _fetch_heads, repo)


def _fetch_pr_state(repo_pr):
    """One PR read straight from GitHub: state, head, whether it sits in the merge queue and whether
    auto-merge is armed. Reuses merge_queue.read so the queue facts mean what enqueue() proved."""
    import merge_queue

    repo, pr = repo_pr

    def gh(args, raw=False):
        p = subprocess.run([GH] + args, capture_output=True, text=True, timeout=30)
        if p.returncode != 0:
            raise RuntimeError(p.stderr.strip()[:200])
        return p.stdout

    try:
        node = merge_queue.read(gh, repo, pr)
    except merge_queue.MergeQueueError as e:
        raise RuntimeError(str(e)) from e
    return {
        "state": node.get("state"),
        "head_sha": node.get("headRefOid"),
        "in_queue": bool(node.get("isInMergeQueue")),
        "auto_merge": bool(node.get("autoMergeRequest")),
        "position": (node.get("mergeQueueEntry") or {}).get("position"),
    }


def pr_state(repo, pr):
    """{state, head_sha, in_queue, auto_merge, position} for one PR, or None when unknown. Cached and
    refreshed in the background like the other facts here (live-actions 1.9 and 1.14)."""
    return _get(("pr", repo, int(pr)), _fetch_pr_state, (repo, int(pr)))


def run(repo, run_id):
    return _get(("run", repo, int(run_id)), _fetch_run, (repo, int(run_id)))


def invalidate():
    """Drop every cached fact (after a write, so the next read is fresh)."""
    with _lock:
        _mem.clear()
