#!/usr/bin/env python3
"""
own_sync_lane.py
Purpose: Synthetic tests for own_sync_lane.py. Fake gh, scratch cache and state db,
         the fixer in record mode (never starts a real session). No network.
Date:    2026-10-14
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent  # the lanes folder
LANE = HERE / "own_sync_lane.py"
TMP = Path(tempfile.mkdtemp(prefix="mxlane-"))
FAKE_GH = TMP / "gh"
PRS = TMP / "prs.json"
CALLS = TMP / "calls.log"
DB = TMP / "state.db"
fails = 0

FAKE_GH.write_text(
    "#!/usr/bin/env python3\n"
    "import os, sys\n"
    "open(os.environ['MXFAKE_CALLS'], 'a').write(' '.join(sys.argv[1:]) + '\\n')\n"
    "if os.environ.get('MXFAKE_FAIL'):\n"
    "    sys.stderr.write('HTTP 502')\n"
    "    sys.exit(1)\n"
    "if sys.argv[1:3] == ['pr', 'list']:\n"
    "    print(open(os.environ['MXFAKE_PRS']).read())\n"
    "    sys.exit(0)\n"
    "if sys.argv[1:3] == ['run', 'list']:\n"
    '    print(\'[{"databaseId": 9001, "status": "completed"}]\')\n'
    "    sys.exit(0)\n"
    "if sys.argv[1:3] == ['run', 'rerun']:\n"
    "    sys.exit(0)\n"
    "sys.stderr.write('unexpected gh call')\n"
    "sys.exit(9)\n"
)
os.chmod(FAKE_GH, 0o755)
con = sqlite3.connect(DB)
con.executescript(
    "CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT, ended_at REAL, "
    "last_activity_at REAL, archived INTEGER DEFAULT 0);"
    "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, content TEXT, "
    "tool_calls TEXT, timestamp REAL);"
)
con.commit()
con.close()


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + ("" if cond or not detail else f"  [{detail}]"))
    if not cond:
        fails += 1


def pr(n=27, **kw):
    base = {
        "number": n,
        "title": f"Nightly sync {n}",
        "url": f"https://github.com/owner-account/ops-center-repo/pull/{n}",
        "author": {"login": "owner-account"},
        "headRefOid": "a" * 40,
        "headRefName": "sync/2026-10-14-0230",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "labels": [],
        "updatedAt": "2026-10-14T06:31:00Z",
        "statusCheckRollup": [
            {
                "name": "ruff",
                "workflowName": "ci",
                "conclusion": "FAILURE",
                "completedAt": "2026-10-14T06:31:18Z",
            },
            {
                "name": "gate",
                "workflowName": "ci",
                "conclusion": "FAILURE",
                "completedAt": "2026-10-14T06:31:26Z",
            },
            {
                "name": "biome",
                "workflowName": "ci",
                "conclusion": "SUCCESS",
                "completedAt": "2026-10-14T06:31:10Z",
            },
        ],
    }
    base.update(kw)
    return base


TARGETS = TMP / "autofix-targets.json"
TARGETS.write_text(
    json.dumps(
        {
            "skills": ["own-pr-autofix"],
            "targets": {
                "sync": {
                    "repo": "owner-account/ops-center-repo",
                    "sync_branch_prefix": "sync/",
                    "notes": "Fix the LIVE file first, then the copy.",
                },
                "sync-feature": {"notes": "Work in a fresh worktree of the repo."},
            },
        }
    )
)
GREEN = [{"name": "ruff", "workflowName": "ci", "conclusion": "SUCCESS", "completedAt": "x"}]


def run(cmd="tick", prs=None, now="2026-10-14T12:00:00Z", case="default", policy=None, extra=None):
    cache = TMP / f"cache-{case}"
    pol = TMP / f"policy-{case}.json"
    if policy is not None:
        pol.write_text(policy if isinstance(policy, str) else json.dumps(policy))
    PRS.write_text(json.dumps(prs if prs is not None else [pr()]))
    env = dict(
        os.environ,
        MXLANE_GH_BIN=str(FAKE_GH),
        MXLANE_CACHE_DIR=str(cache),
        MXLANE_POLICY=str(pol),
        MXLANE_NOW=now,
        MXFAKE_PRS=str(PRS),
        MXFAKE_CALLS=str(CALLS),
        AUTOFIX_TARGETS=str(TARGETS),
        OWNPR_FIX_SPAWN="record",
        OWNPR_STATE_DB=str(DB),
    )
    env.pop("MXFAKE_FAIL", None)
    env.update(extra or {})
    args = [sys.executable, str(LANE)] + (cmd if isinstance(cmd, list) else [cmd])
    p = subprocess.run(args, capture_output=True, text=True, env=env, timeout=60)
    st = {}
    try:  # noqa: SIM105
        st = json.loads((cache / "own-pr-merge.json").read_text())
    except (OSError, ValueError):
        pass
    return p, st, cache


# 1. Red sync PR: held for checks red (aggregate gate not named), one fix session recorded.
p, st, cache = run(case="red")
rec = st.get("prs", {}).get("27", {})
check(
    "red PR held for checks red",
    rec.get("status") == "held" and rec.get("reason") == "checks red: ruff",
    rec,
)
fx = st.get("fix", {}).get("27", {}).get("running") or {}
check("fix session started for red-checks", fx.get("problem") == "red-checks", fx)
check("session runs the common skill", "own-pr-autofix" in (fx.get("argv") or []))
brief = Path(fx.get("brief", "/nonexistent")).read_text() if fx.get("brief") else ""
check("brief carries the live-files-first note", "Fix the LIVE file first" in brief)
check("brief names the PR and head", "#27" in brief and "a" * 40 in brief)
check("tick printed nothing", p.stdout.strip() == "", p.stdout)
check("exit 0", p.returncode == 0, p.stderr)
dec = [json.loads(x) for x in (cache / "decisions.jsonl").read_text().splitlines()]
check(
    "decisions log held + autofix-started",
    [d["decision"] for d in dec] == ["held", "autofix-started"],
    dec,
)

# 2. Same head, the recorded session ended with no result: one retry only, then a give-up line.
p, st, _ = run(case="red", now="2026-10-14T12:05:00Z")
hist = st["fix"]["27"].get("history") or []
check(
    "ended session moved to history as no-result",
    hist and hist[-1].get("outcome") == "no-result",
    hist,
)
check(
    "one retry after a crash", (st["fix"]["27"].get("running") or {}).get("problem") == "red-checks"
)
p, st, _ = run(case="red", now="2026-10-14T12:10:00Z")
check(
    "second crash gives up with one line",
    "[sync the owner's PR] PR #27" in p.stdout and "gave up" in p.stdout,
    p.stdout,
)
check(
    "give-up recorded for this head", (st["fix"]["27"].get("gave_up") or {}).get("head") == "a" * 40
)
p, st, _ = run(case="red", now="2026-10-14T12:15:00Z")
check("give-up is reported once", p.stdout.strip() == "", p.stdout)

# 3. A new head clears the give-up and may start again.
p, st, _ = run(case="red", prs=[pr(headRefOid="b" * 40)], now="2026-10-14T12:20:00Z")
check(
    "new head starts a fresh session",
    (st["fix"]["27"].get("running") or {}).get("head") == "b" * 40,
    st["fix"],
)

# 4. Scope: engineer PRs and non-sync branches are never touched.
p, st, _ = run(case="scope", prs=[pr(30, author={"login": "someone"}), pr(31, headRefName="fix/x")])
check("engineer PR skipped", "30" not in st.get("prs", {}) and "30" not in st.get("fix", {}))
check("non-sync branch skipped", "31" not in st.get("prs", {}) and "31" not in st.get("fix", {}))

# 5. Deliberate holds and running work start nothing.
cases = {
    "label": (pr(labels=[{"name": "do-not-merge"}]), "held", "label do-not-merge"),
    "draft": (pr(isDraft=True), "held", "draft"),
    "pending": (
        pr(statusCheckRollup=[{"name": "ruff", "workflowName": "ci", "status": "IN_PROGRESS"}]),
        "waiting",
        "1 check(s) running",
    ),
    "nochecks": (pr(statusCheckRollup=[]), "waiting", "no checks reported yet"),
    "green": (pr(statusCheckRollup=GREEN), "ready", "all checks green, GitHub auto-merge lands it"),
}
for name, (p_in, want_status, want_reason) in cases.items():
    p, st, _ = run(case=name, prs=[p_in])
    r = st.get("prs", {}).get("27", {})
    check(
        f"{name}: {want_status}",
        (r.get("status"), r.get("reason")) == (want_status, want_reason),
        r,
    )
    check(
        f"{name}: no session", not (st.get("fix", {}).get("27") or {}).get("running"), st.get("fix")
    )

# 6. Conflict is fixable, an aggregate-only red still counts.
p, st, _ = run(case="conflict", prs=[pr(mergeable="CONFLICTING")])
check(
    "conflict starts a merge-conflict session",
    (st["fix"]["27"].get("running") or {}).get("problem") == "merge-conflict",
)
only_gate = [{"name": "gate", "workflowName": "ci", "conclusion": "FAILURE", "completedAt": "x"}]
p, st, _ = run(case="gateonly", prs=[pr(statusCheckRollup=only_gate)])
check(
    "gate-only red is still held",
    st["prs"]["27"].get("reason") == "checks red: gate",
    st["prs"]["27"],
)

# 7. Kill switches.
p, st, _ = run(case="afoff", policy={"own_pr_merge": {"autofix": {"enabled": False}}})
check(
    "autofix disabled: held, no session",
    st["prs"]["27"]["status"] == "held" and not st["fix"]["27"].get("running"),
)
p, st, _ = run(case="laneoff", policy={"own_pr_merge": {"enabled": False}})
check("lane disabled: nothing listed", st.get("disabled") is True and not st.get("prs"), st)

# 8. Fail closed: gh failure and a broken policy start nothing and count errors, alert on the 3rd.
for i in range(3):
    p, st, _ = run(case="ghfail", extra={"MXFAKE_FAIL": "1"}, now=f"2026-10-14T12:0{i}:00Z")
check(
    "gh failure counted", st.get("error_count") == 3 and "HTTP 502" in st.get("last_error", ""), st
)
check(
    "third failure prints one alert line",
    "auto-fix lane failing (3 passes in a row)" in p.stdout,
    p.stdout,
)
check("gh failure started nothing", not st.get("fix"))
p, st, _ = run(case="badpol", policy="{not json")
check(
    "broken policy fails closed",
    st.get("error_count") == 1 and "policy" in st.get("last_error", ""),
    st,
)
check("broken policy started nothing", not st.get("fix"))

# 9. The lane never merges, approves, labels or comments: only gh pr list was ever called.
calls = [ln for ln in CALLS.read_text().splitlines() if ln.strip()]
check(
    "only pr list calls",
    calls and all(c.startswith("pr list") for c in calls),
    sorted(set(c[:20] for c in calls)),
)
check(
    "never merges, labels or comments",
    not [c for c in calls if c.startswith(("pr merge", "pr edit", "pr comment", "pr review"))],
)

# 10. check is read-only and prints the decision.
p, st, cache = run(cmd=["check", "27"], case="checkcmd")
out = json.loads(p.stdout or "{}")
check(
    "check prints the decision",
    out.get("status") == "held" and out.get("reason") == "checks red: ruff",
    p.stdout,
)
check("check writes no state", not (cache / "own-pr-merge.json").exists())

# 11. A closed PR drops out of the state.
p, st, _ = run(case="red", prs=[], now="2026-10-14T13:00:00Z")
check("closed PR dropped from prs", "27" not in st.get("prs", {}), st.get("prs"))

# 12. Stuck green: re-run the ci run once after stale_ready_min, report once a window later.
CALLS.write_text("")
g = [pr(statusCheckRollup=GREEN)]
p, st, _ = run(case="stuck", prs=g, now="2026-10-14T12:00:00Z")
check(
    "stuck: fresh green does nothing",
    not [c for c in CALLS.read_text().splitlines() if c.startswith("run")],
)
p, st, _ = run(case="stuck", prs=g, now="2026-10-14T12:25:00Z")
runs = [c for c in CALLS.read_text().splitlines() if c.startswith("run")]
check("stuck: one ci re-run after 20 min", any(c.startswith("run rerun 9001") for c in runs), runs)
check("stuck: kick is silent", p.stdout.strip() == "", p.stdout)
p, st, _ = run(case="stuck", prs=g, now="2026-10-14T12:30:00Z")
check(
    "stuck: no second re-run",
    sum(c.startswith("run rerun") for c in CALLS.read_text().splitlines()) == 1,
)
p, st, _ = run(case="stuck", prs=g, now="2026-10-14T12:50:00Z")
check(
    "stuck: reported once after the re-run window",
    "green but the gate has not merged" in p.stdout,
    p.stdout,
)
p, st, _ = run(case="stuck", prs=g, now="2026-10-14T13:20:00Z")
check("stuck: report not repeated", p.stdout.strip() == "", p.stdout)
p, st, _ = run(case="nochk", prs=[pr(statusCheckRollup=[])], now="2026-10-14T12:00:00Z")
p, st, _ = run(case="nochk", prs=[pr(statusCheckRollup=[])], now="2026-10-14T12:30:00Z")
check("no checks for 30 min: reported", "no checks ran" in p.stdout, p.stdout)

# 13. An empty prefix takes feature branches too, and they get the feature-PR brief.
p, st, _ = run(case="feat", prs=[pr(33, headRefName="feat/x")], policy={"branch_prefixes": [""]})
fx = st.get("fix", {}).get("33", {}).get("running") or {}
check("feature branch picked up with prefix ''", fx.get("problem") == "red-checks", st)
brief = Path(fx.get("brief", "/nonexistent")).read_text() if fx.get("brief") else ""
check(
    "feature brief uses the worktree notes",
    "fresh worktree" in brief and "Fix the LIVE file first" not in brief,
)

print(f"{fails} failed")
sys.exit(1 if fails else 0)
