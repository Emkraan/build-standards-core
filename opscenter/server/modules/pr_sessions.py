"""
pr_sessions.py
Purpose: Find a live session that is working one of my PRs right now, so the PR card says
         "session on it" and locks its buttons instead of looking idle (10/21: #448 sat red
         with a delegated fix session working it and nothing on the card said so).
         Signals, strongest first:
           1. a running delegated task (subagent) whose goal names the PR or its branch
           2. a non-cron session dedicated to the PR (Discuss / Auto-fix title) that is live
           3. a non-cron session whose recent tool calls work in the PR branch's worktree or
              push to the branch
         Reading or mentioning a PR number is never "working it" (a triage or status session
         must not lock the card). Read-only. Any read error counts as nobody.
Date:    2026-11-06

Configuration (all optional; nothing running changes until a consumer calls `working`):
  PRSESS_STATE_DB      the agent runtime's session database (tables sessions, messages, session_turn_leases);
                       default <agent home>/state.db
  PRSESS_DELEG_DIR     where delegated tasks keep their manifests (<dir>/*/manifest.json); default <agent home>/cache/delegation/live
  PRSESS_REPO_DIRS     JSON {"repo name": "local clone path"}; the worktrees of a clone tie a branch to a session
  PRSESS_TITLE_PATTERNS  JSON list of regexes with {repo} and {pr}; a live session whose title matches is dedicated to the PR
                       (default: a "Discuss ... PR #N" title and an "Auto-fix <repo> PR #N" title)
"""

import json
import os
import re
import sqlite3
import subprocess
import time
from pathlib import Path

import paths

HOME = Path.home()
STATE_DB = Path(os.environ.get("PRSESS_STATE_DB") or paths.agent_home() / "state.db")
DELEG_DIR = Path(
    os.environ.get("PRSESS_DELEG_DIR") or paths.agent_home() / "cache" / "delegation" / "live"
)
DEFAULT_TITLE_PATTERNS = [r"^Discuss\b.*\bPR #{pr}\b", r"^Auto-fix {repo} PR #{pr}\b"]


def _repo_dirs():
    try:
        d = json.loads(os.environ.get("PRSESS_REPO_DIRS") or "{}")
    except ValueError:
        return {}
    return {str(k): Path(v) for k, v in d.items()} if isinstance(d, dict) else {}


def _title_patterns():
    try:
        d = json.loads(os.environ.get("PRSESS_TITLE_PATTERNS") or "null")
    except ValueError:
        d = None
    return d if isinstance(d, list) and d else DEFAULT_TITLE_PATTERNS


ACTIVE_S = 300  # a session with no message for this long is not working anything
WORK_S = 900  # how far back a session's tool calls count as work on the branch
DELEG_MAX_AGE_S = 6 * 3600  # a "running" manifest older than this is a crashed run
CACHE_S = 20

_cache = {}


def _cached(key, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_S:
        return hit[1]
    val = fn()
    _cache[key] = (time.time(), val)
    return val


def _worktrees(repo):
    """{branch: worktree path} for the repo's local worktrees."""
    d = _repo_dirs().get(repo)
    if not d or not d.exists():
        return {}
    try:
        out = subprocess.run(
            ["git", "-C", str(d), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    res, path = {}, None
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = line[9:]
        elif line.startswith("branch refs/heads/") and path:
            res[line[18:]] = path
    return res


def _delegations():
    """Running delegated tasks: [{goal, since, last}]."""
    res, now = [], time.time()
    if not DELEG_DIR.exists():
        return res
    for m in DELEG_DIR.glob("*/manifest.json"):
        try:
            if now - m.stat().st_mtime > DELEG_MAX_AGE_S * 4:
                continue
            man = json.loads(m.read_text())
        except (OSError, ValueError):
            continue
        for t in man.get("tasks") or []:
            if t.get("status") != "running":
                continue
            log = Path(t.get("log") or "")
            try:
                last = log.stat().st_mtime if log.exists() else m.stat().st_mtime
                started = m.stat().st_ctime
            except OSError:
                continue
            if now - started > DELEG_MAX_AGE_S:
                continue
            res.append({"goal": t.get("goal") or "", "since": started, "last": last})
    return res


def _live_sessions():
    """Non-cron sessions with a message in the last ACTIVE_S or a live turn lease:
    [{id, title, last, steps, calls}] where calls is their tool-call text of the last WORK_S."""
    now = time.time()
    try:
        con = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return []
    try:
        leased = {
            r[0]
            for r in con.execute(
                "SELECT conversation_id FROM session_turn_leases WHERE expires_at > ? AND conversation_id NOT LIKE 'cron_%'",
                (now,),
            )
        }
        rows = con.execute(
            "SELECT s.id, COALESCE(s.title, ''), MAX(m.timestamp), COUNT(m.tool_calls) FROM sessions s "
            "JOIN messages m ON m.session_id = s.id WHERE s.ended_at IS NULL AND s.source != 'cron' "
            "AND s.id NOT LIKE 'cron_%' AND m.timestamp > ? GROUP BY s.id",
            (now - WORK_S,),
        ).fetchall()
        res = []
        for sid, title, last, steps in rows:
            if now - (last or 0) > ACTIVE_S and sid not in leased:
                continue
            calls = "\n".join(
                c or ""
                for (c,) in con.execute(
                    "SELECT tool_calls FROM messages WHERE session_id = ? AND timestamp > ? AND tool_calls IS NOT NULL",
                    (sid, now - WORK_S),
                )
            )
            res.append({"id": sid, "title": title, "last": last, "steps": steps, "calls": calls})
        return res
    except sqlite3.Error:
        return []
    finally:
        con.close()


def _ago(ts):
    s = max(0, int(time.time() - ts))
    return f"{s} s" if s < 90 else f"{s // 60} min"


def working(repo, pr, branch):
    """The session working this PR right now, else None:
    {kind: subagent|session, label, since, last, text}."""
    pr_rx = re.compile(rf"(?:PR\s*#|pull/){int(pr)}(?!\d)")
    br = branch if branch and len(branch) >= 8 else None
    br_rx = re.compile(re.escape(br) + r"(?![A-Za-z0-9._/-])") if br else None
    for t in _cached("deleg", _delegations):
        g = t["goal"]
        if (pr_rx.search(g) and repo.lower() in g.lower()) or (br_rx and br_rx.search(g)):
            label = "Subagent: " + (g[:70].rstrip() + ("..." if len(g) > 70 else ""))
            return {
                "kind": "subagent",
                "label": label,
                "since": t["since"],
                "last": t["last"],
                "text": f'A fix session is working on it ("{label}", started {_ago(t["since"])} ago, last step '
                f"{_ago(t['last'])} ago). The buttons come back when it finishes.",
            }
    title_rx = re.compile(
        "|".join(
            f"(?:{p.format(repo=re.escape(repo), pr=int(pr))})"
            for p in _title_patterns()
            if "{pr}" in p
        )
    )
    wt = _cached(f"wt:{repo}", lambda: _worktrees(repo)).get(br) if br else None
    for s in _cached("sess", _live_sessions):
        hit = bool(title_rx.search(s["title"]))
        if not hit and br:
            calls = s["calls"]
            short = wt.replace(str(HOME), "~", 1) if wt else None
            hit = bool(
                (wt and (wt in calls or short in calls))
                or re.search(r":" + re.escape(br) + r"(?![A-Za-z0-9._/-])", calls)
                or re.search(
                    r"checkout\s+(?:-b\s+)?" + re.escape(br) + r"(?![A-Za-z0-9._/-])", calls
                )
            )
        if hit:
            label = s["title"] or s["id"]
            return {
                "kind": "session",
                "label": label,
                "since": None,
                "last": s["last"],
                "text": f'The session "{label}" is working on it (last step {_ago(s["last"])} ago). '
                "The buttons come back when it goes quiet.",
            }
    return None
