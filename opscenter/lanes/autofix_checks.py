#!/usr/bin/env python3
# Synthetic tests for own_pr_fixer.py (no network, never starts a real Hermes session).
import datetime as dt
import importlib.util
import json as _json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ["OWNPR_FIX_SPAWN"] = "record"
os.environ["AUTOFIX_PREFLIGHT_CMD"] = "preflight run --repo {target} --worktree {worktree}"
TMP = Path(tempfile.mkdtemp(prefix="ownfix-"))

DB = TMP / "state.db"
os.environ["OWNPR_STATE_DB"] = str(DB)
_c = sqlite3.connect(DB)
_c.executescript(
    "CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT, started_at REAL, ended_at REAL, last_activity_at REAL, archived INTEGER DEFAULT 0);"
    "CREATE TABLE session_turn_leases (conversation_id TEXT PRIMARY KEY, holder TEXT, acquired_at REAL, expires_at REAL);"
    "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, content TEXT, tool_calls TEXT, timestamp REAL);"
)
_c.commit()
_c.close()
TARGETS = {
    "skills": ["ops-center", "own-pr-autofix"],
    "targets": {
        "prod": {
            "repo": "owner/prod-repo",
            "build": True,
            "skill": "build-skill",
            "catalog": str(TMP / "finding-catalog.md"),
        },
        "team": {
            "repo": "owner/team-repo",
            "build": True,
            "skill": "build-skill",
            "catalog": str(TMP / "finding-catalog.md"),
        },
        "core": {
            "repo": "owner/core",
            "skill": "core-skill",
            "identity": "owner-login <1+owner-login@users.noreply.github.com>",
        },
        "ops-center": {"repo": "owner/ops", "sync_branch_prefix": "sync/", "notes": "SYNC NOTES"},
        "ops-center-feature": {"notes": "FEATURE NOTES"},
    },
}
(TMP / "autofix-targets.json").write_text(_json.dumps(TARGETS))
os.environ["AUTOFIX_TARGETS"] = str(TMP / "autofix-targets.json")
spec = importlib.util.spec_from_file_location(
    "fx", str(Path(__file__).resolve().parent / "autofix.py")
)
fx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fx)
fx.set_runtime(fx.HermesRuntime())

HEAD = "a" * 40
NOW = dt.datetime(2026, 10, 9, 21, 0, 0, tzinfo=dt.timezone.utc)
NOW_TS = NOW.timestamp()
CFG = {"autofix": {"enabled": True, "max_sessions_per_day": 3, "run_budget_s": 5400}}
fails = 0
ALIVE = set()  # brief paths whose session the test treats as running
_real_alive = fx._alive
fx._alive = lambda pid, marker=None: marker in ALIVE if marker else False
# no network. Default push is a plain source file, so the older cases keep pushing at once.
PUSHED = {"files": ["apps/x/src/a.ts"]}
fx.push_files = lambda repo, old, new: PUSHED["files"]


def pr(**kw):
    base = {
        "number": 900,
        "title": "t",
        "url": "u",
        "headRefOid": HEAD,
        "headRefName": "ticket-id-x",
        "author": {"login": "owner-login"},
    }
    base.update(kw)
    return base


def at(minutes):
    return NOW + dt.timedelta(minutes=minutes)


def call(frec, status="held", reason="checks red: lint", p=None, now=NOW, cfg=CFG):
    return fx.consider(
        "prod",
        "[prod the owner PR]",
        "owner/prod-repo",
        "owner-login",
        p or pr(),
        status,
        reason,
        frec,
        cfg,
        TMP,
        now,
    )


def ok(name, cond, extra=""):
    global fails
    fails += not cond
    print(f"{'OK  ' if cond else 'FAIL'} {name} {extra}")


def end(frec, outcome=None, text=""):
    """The running session exits, optionally writing its result line."""
    run = frec["running"]
    ALIVE.discard(run["brief"])
    if outcome:
        Path(run["result_path"]).write_text(f"some log\nFIX RESULT: {outcome} - {text}\n")


# 1. which holds are fixable
cases = [
    ("held", "checks red: lint", "red-checks"),
    ("held", "2 high finding(s), no triage reply from me on this head", "untriaged-highs"),
    ("held", "2 high finding(s), triage reply covers H2 only (missing H1)", "untriaged-highs"),
    (
        "held",
        "PR review verdict blocked, override triage covers B1 only (missing B2)",
        "blocking-findings",
    ),
    (
        "held",
        "2 blocking finding(s), override triage covers B1 only (missing B2)",
        "blocking-findings",
    ),
    ("held", "1 blocking finding(s)", "blocking-findings"),
    ("held", "PR review verdict blocked", "blocking-findings"),
    ("held", "merge conflict with main", "merge-conflict"),
    ("held", "1 unresolved review thread(s)", "review-threads"),
    ("held", "needs me: rbac-user-or-group", None),
    ("held", "draft", None),
    ("held", "labelled do-not-merge", None),
    ("held", "change freeze cf-2026-10 until 2026-11-02", None),
    ("held", "PR review unavailable for this head", None),
    ("held", "lane error: TypeError: boom", None),
    ("waiting", "2 check(s) running", None),
    ("ready", "x", None),
]
for st, why, want in cases:
    got = fx.problem_of(st, why)
    ok(f"problem_of({st}, {why[:40]})", got == want, f"-> {got}")

# 2. engineer PR is never fixed, whatever the hold
frec = {}
ok("engineer PR refused", call(frec, p=pr(author={"login": "account"})) is None and not frec)

# 3. red checks start one session at once with the right argv and brief
frec = {}
line = call(frec)
run = frec.get("running") or {}
argv = run.get("argv") or []
brief = Path(run.get("brief", "/nonexistent")).read_text() if run else ""
ok(
    "first pass starts a session",
    line is None and run.get("problem") == "red-checks" and run.get("head") == HEAD,
)
ok(
    "launch record: titled, brief, common skills plus the build skill",
    argv[:1] == ["launch"]
    and argv[1] == "Auto-fix prod-repo PR #900 aaaaaaaa"
    and argv[3] == "ops-center,own-pr-autofix,build-skill",
)
ok(
    "brief names the PR, head, problem and result file",
    "#900" in brief
    and HEAD in brief
    and "red-checks" in brief
    and run["result_path"] in brief
    and "Never merge" in brief,
)
ok("brief is ASCII with no semicolons", all(ord(c) < 128 for c in brief) and ";" not in brief)

# 4. while it runs, no second session
ALIVE.add(run["brief"])
first = dict(run)
call(frec, now=at(3))
ok("no second session while running", frec["running"] == first)

# 5. it reports fixed, the lane gets 10 minutes to see the push
end(frec, "fixed", "the owner fixed the lint error and pushed.")
ok("fixed: quiet inside the grace window", call(frec, now=at(6)) is None and "running" not in frec)
ok("history recorded", frec["history"][-1]["outcome"] == "fixed")
line = call(frec, now=at(20))
ok(
    "same head still red after 10 min: gave up, reported",
    line and "checks are still red after a fix session" in line and "#900" in line,
    f"-> {line}",
)
ok("reported once", call(frec, now=at(23)) is None)

# 6. a new head clears the give-up and a new session starts
NEW = "b" * 40
call(frec, p=pr(headRefOid=NEW), now=at(30))
ok(
    "new head starts a new session",
    frec.get("running", {}).get("head") == NEW and "gave_up" not in frec,
)

# 7. a session that gives up is reported with its reason
end(frec, "gave-up", "It needs a Key Vault access decision.")
line = call(frec, p=pr(headRefOid=NEW), now=at(40))
ok("gave-up reported with the reason", line and "Key Vault access decision" in line, f"-> {line}")

# 8. the problem clears: no report, give-up for an old head is dropped
line = call(frec, status="ready", reason="all green", p=pr(headRefOid="c" * 40), now=at(50))
ok("cleared: quiet and give-up dropped", line is None and "gave_up" not in frec)

# 9. policy hold never starts a session
frec = {}
ok(
    "policy hold: nothing",
    call(frec, reason="needs me: rbac-user-or-group") is None and "running" not in frec,
)

# 10. a crash with no result gets one retry, then gives up
frec = {}
call(frec)
end(frec)
call(frec, now=at(5))
ok(
    "crash: one retry",
    frec.get("running")
    and len(frec["history"]) == 1
    and frec["history"][0]["outcome"] == "no-result",
)
end(frec)
line = call(frec, now=at(10))
ok(
    "second crash: gave up",
    line and "two fix sessions ended without a result" in line and "running" not in frec,
    f"-> {line}",
)

# 11. daily cap across heads
frec = {
    "history": [
        {
            "head": h * 40,
            "problem": "red-checks",
            "outcome": "fixed",
            "started": at(-60 * k).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ended": at(-60 * k + 10).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        for k, h in ((3, "d"), (2, "e"), (1, "f"))
    ]
}
line = call(frec)
ok(
    "3 sessions in 24 h: gave up, no 4th",
    line and "3 auto-fix sessions in 24 h" in line and "running" not in frec,
    f"-> {line}",
)
frec["history"][0]["started"] = at(-60 * 25).strftime("%Y-%m-%dT%H:%M:%SZ")
frec.pop("gave_up")
frec.pop("reported", None)
call(frec)
ok("older than 24 h does not count", frec.get("running") is not None)

# 12. over budget: stopped and treated as given up
killed = []
real_killpg, real_getpgid = os.killpg, os.getpgid
os.killpg = lambda g, s: killed.append((g, s))
os.getpgid = lambda p: 4242
frec = {}
call(frec)
frec["running"]["pid"] = 999999
ALIVE.add(frec["running"]["brief"])
line = call(frec, now=at(90 + 16))
ok("over budget: process group stopped", killed == [(4242, 15)], f"-> {killed}")
ok("over budget: reported as given up", line and "time budget" in line, f"-> {line}")
os.killpg, os.getpgid = real_killpg, real_getpgid
ALIVE.clear()


# 13b. a live session already on the PR defers the fix, then the fix starts once it goes quiet
def add_session(
    sid,
    source="cli",
    title="Tackle: x",
    ended=None,
    active=NOW_TS,
    content="",
    tool_calls="",
    said=None,
):
    c = sqlite3.connect(DB)
    c.execute(
        "INSERT INTO sessions (id, source, title, ended_at, last_activity_at) VALUES (?,?,?,?,?)",
        (sid, source, title, ended, active),
    )
    c.execute(
        "INSERT INTO messages (session_id, content, tool_calls, timestamp) VALUES (?,?,?,?)",
        (sid, content, tool_calls, active if said is None else said),
    )
    c.commit()
    c.close()


def clear_sessions():
    c = sqlite3.connect(DB)
    c.executescript("DELETE FROM sessions; DELETE FROM messages;")
    c.commit()
    c.close()


add_session(
    "cron_x_1",
    source="cron",
    title="platform PRs",
    content="https://github.com/owner/prod-repo/pull/900",
)
add_session("fix1", title="Auto-fix platform PR #900 aaaaaaaa", content="prod-repo/pull/900")
add_session("old", content="prod-repo/pull/900", active=NOW.timestamp() - 1200)
add_session("done", content="prod-repo/pull/900", ended=NOW.timestamp() - 60)
add_session("other", content="prod-repo/pull/901 and team-repo/pull/900")
add_session(
    "longlived", title="Ops work", content="prod-repo/pull/900", said=NOW.timestamp() - 3600
)
frec = {}
call(frec)
ok(
    "cron, own fix, stale, ended, other-PR and old-mention sessions do not block",
    frec.get("running") is not None,
)
clear_sessions()
add_session(
    "discuss-other",
    title="Discuss: prod-repo PR #258 Import stragglers",
    content="it waits on https://github.com/owner/prod-repo/pull/900 to merge",
)
frec = {}
call(frec)
ok(
    "a session about another PR of this repo that names this PR does not block",
    frec.get("running") is not None,
)
clear_sessions()
add_session(
    "discuss-this",
    title="Discuss: platform PR #900 Something",
    content="https://github.com/owner/prod-repo/pull/900",
)
frec = {}
call(frec)
ok("a session about this PR still defers", "running" not in frec and frec.get("deferred"))
clear_sessions()
add_session(
    "tackle",
    title="Tackle: File the PS 7.2 intake",
    tool_calls='{"command": "gh pr view 900 -R x; git push origin ticket-id-x"}',
)
frec = {}
call(frec)
ok(
    "live session on the branch: deferred, no session",
    "running" not in frec
    and frec.get("deferred", {}).get("session") == "Tackle: File the PS 7.2 intake",
    f"-> {frec.get('deferred')}",
)
clear_sessions()
add_session(
    "tackle",
    title="Tackle: File the PS 7.2 intake",
    content="see https://github.com/owner/prod-repo/pull/900",
)
frec = {}
call(frec)
ok("live session naming the PR URL: deferred", "running" not in frec and frec.get("deferred"))
call(frec, now=at(11))
ok(
    "same session quiet 11 min later: fix starts, deferral cleared",
    frec.get("running") is not None and "deferred" not in frec,
)
clear_sessions()

# 13c. a session compression just continued mid-turn has no last_activity_at yet
add_session(
    "child", content="branch ticket-id-x pushed, https://github.com/owner/prod-repo/pull/900"
)
_c = sqlite3.connect(DB)
_c.execute(
    "UPDATE sessions SET last_activity_at = NULL, started_at = ? WHERE id = 'child'", (NOW_TS - 54,)
)
_c.commit()
_c.close()
frec = {}
call(frec)
ok(
    "fresh compression child with no activity mark yet: deferred",
    "running" not in frec and frec.get("deferred"),
)
clear_sessions()
add_session("child", content="prod-repo/pull/900", said=NOW_TS - 120)
_c = sqlite3.connect(DB)
_c.execute(
    "UPDATE sessions SET last_activity_at = NULL, started_at = ? WHERE id = 'child'",
    (NOW_TS - 7200,),
)
_c.commit()
_c.close()
frec = {}
call(frec)
ok(
    "no activity mark but a message 2 min ago: deferred",
    "running" not in frec and frec.get("deferred"),
)
clear_sessions()
add_session("child", content="prod-repo/pull/900", active=None, said=NOW_TS - 1200)
_c = sqlite3.connect(DB)
_c.execute("UPDATE sessions SET started_at = ? WHERE id = 'child'", (NOW_TS - 7200,))
_c.commit()
_c.close()
frec = {}
call(frec)
ok("no activity mark, old start, quiet 20 min: fix starts", frec.get("running") is not None)
clear_sessions()

# 13. disabled in policy: nothing
frec = {}
ok(
    "autofix disabled: nothing",
    call(frec, cfg={"autofix": {"enabled": False}}) is None and not frec,
)

# 14. result parsing takes the last FIX RESULT line
rp = TMP / "r.txt"
rp.write_text(
    "FIX RESULT: gave-up - first\nnoise\nFIX RESULT: triaged - the owner posted the triage reply.\n"
)
ok("read_result last line", fx.read_result(rp) == ("triaged", "the owner posted the triage reply."))
ok("read_result missing file", fx.read_result(TMP / "none") == (None, ""))

# 14b. finished auto-fix sessions are picked for archiving, live or other ones never
clear_sessions()
os.environ["OWNPR_ARCHIVE"] = "record"
add_session(
    "af-done", title="Auto-fix platform PR #1 aaaaaaaa", ended=NOW_TS - 600, active=NOW_TS - 600
)
add_session(
    "af-fresh", title="Auto-fix platform PR #2 bbbbbbbb", ended=NOW_TS - 30, active=NOW_TS - 30
)
add_session("af-running", title="Auto-fix platform PR #3 cccccccc", ended=None, active=NOW_TS - 900)
add_session(
    "af-leased", title="Auto-fix platform PR #4 dddddddd", ended=NOW_TS - 600, active=NOW_TS - 600
)
add_session(
    "af-archived", title="Auto-fix platform PR #5 eeeeeeee", ended=NOW_TS - 600, active=NOW_TS - 600
)
add_session("tackle-done", title="Tackle: x", ended=NOW_TS - 600, active=NOW_TS - 600)
_c = sqlite3.connect(DB)
_c.execute("UPDATE sessions SET archived = 1 WHERE id = 'af-archived'")
_c.execute(
    "INSERT INTO session_turn_leases VALUES ('af-leased', 'h', ?, ?)", (NOW_TS - 10, NOW_TS + 300)
)
_c.commit()
_c.close()
ok(
    "archive: only ended, quiet, unleased, unarchived auto-fix sessions",
    fx.archive_finished(NOW) == ["af-done"],
    f"-> {fx.archive_finished(NOW)}",
)
os.environ.pop("OWNPR_ARCHIVE")
_c = sqlite3.connect(DB)
_c.executescript("DELETE FROM session_turn_leases;")
_c.close()
clear_sessions()

# 14c. a give-up caused by other open PRs waits for them, then re-arms as a rebase on main
STATES = {}
fx.pr_state = lambda repo, n: STATES.get(n, "OPEN")
ok(
    "waits_on: phrase in give-up text",
    fx.waits_on("applied from open PRs #265 and #267 but not on main", 900) == [265, 267],
)
ok("waits_on: three, never itself", fx.waits_on("open PRs #3, #900, and #1", 900) == [1, 3])
ok(
    "waits_on: merged PRs named elsewhere do not count",
    fx.waits_on("rebased after #261 merged", 900) == [],
)
wp = TMP / "w.result"
wp.write_text("FIX WAITS ON: #12, #14\nFIX RESULT: gave-up - plans red from other PRs\n")
ok("waits_on: explicit line wins", fx.waits_on("open PR #99", 900, wp) == [12, 14])
frec = {}
call(frec)
end(frec, "gave-up", "The red plans come from open PRs #265 and #267, not this PR.")
line = call(frec, now=at(5))
ok(
    "waiting give-up: reported once, waits recorded",
    line
    and "#265 and #267" in line
    and frec["gave_up"].get("waits_on") == [265, 267]
    and "running" not in frec,
    f"-> {line}",
)
ok("still waiting: quiet, no session", call(frec, now=at(8)) is None and "running" not in frec)
STATES[265] = "MERGED"
ok("one of two merged: still waiting", call(frec, now=at(11)) is None and "running" not in frec)
STATES[267] = "MERGED"
line = call(frec, now=at(14))
run = frec.get("running") or {}
brief = Path(run["brief"]).read_text() if run else ""
ok(
    "both merged: re-armed as rebase-on-main on the same head",
    line is None
    and run.get("problem") == "rebase-on-main"
    and run.get("head") == HEAD
    and "gave_up" not in frec,
    f"-> {line} {run.get('problem')}",
)
ok(
    "rebase brief names the merged PRs, stays ASCII without semicolons",
    "#265 and #267" in brief
    and "--force-with-lease" in brief
    and all(ord(c) < 128 for c in brief)
    and ";" not in brief,
)
end(frec, "fixed", "the owner rebased on main and pushed.")
ok("rebase fixed: grace window", call(frec, now=at(18)) is None)
line = call(frec, now=at(30))
ok(
    "same head still held after the rebase session: gave up",
    line and "after the rebase on main" in line,
    f"-> {line}",
)
NEWH = "9" * 40
call(
    frec,
    p=pr(headRefOid=NEWH),
    reason="2 high finding(s), no triage reply from me on this head",
    now=at(40),
)
ok(
    "new head after the rebase: rearm dropped, normal fix starts",
    frec.get("running", {}).get("problem") == "untriaged-highs" and "rearm" not in frec,
)
ALIVE.clear()
# a waited-on PR closed unmerged: plain give-up, never re-armed
STATES.clear()
frec = {}
call(frec)
end(frec, "gave-up", "Blocked by open PR #50.")
call(frec, now=at(5))
STATES[50] = "CLOSED"
line = call(frec, now=at(8))
ok(
    "waited-on PR closed: plain give-up with the reason",
    line and "#50 closed without merging" in line and "running" not in frec,
    f"-> {line}",
)
STATES[50] = "MERGED"
ok(
    "closed then merged later: still no re-arm",
    call(frec, now=at(12)) is None and "running" not in frec,
)
# a give-up recorded before (no waits_on key) is read from its text
STATES.clear()
frec = {
    "gave_up": {
        "head": HEAD,
        "why": "applied from open PRs #265 and #267",
        "at": "2026-10-09T20:00:00Z",
    }
}
STATES[265] = STATES[267] = "MERGED"
call(frec, now=at(1))
ok(
    "legacy give-up re-arms from its text",
    frec.get("running", {}).get("problem") == "rebase-on-main",
)
ALIVE.clear()
# the destroy guard shows as a plan-destroy sign-off meanwhile: waits quietly, re-arms on merge
STATES.clear()
frec = {
    "gave_up": {
        "head": HEAD,
        "why": "applied from open PRs #265 and #267",
        "at": "2026-10-09T20:00:00Z",
    }
}
ok(
    "policy hold while waiting: quiet",
    call(frec, reason="needs me: plan-destroy", now=at(1)) is None and "running" not in frec,
)
ok("waits derived even on a policy hold", frec["gave_up"].get("waits_on") == [265, 267])
STATES[265] = STATES[267] = "MERGED"
ok(
    "do-not-merge label: never re-armed",
    call(frec, reason="labelled do-not-merge", now=at(2)) is None and "running" not in frec,
)
ok(
    "checks running: never re-armed",
    call(frec, status="waiting", reason="2 check(s) running", now=at(3)) is None
    and "running" not in frec,
)
call(frec, reason="needs me: plan-destroy", now=at(4))
ok(
    "policy hold, both merged: rebase starts",
    frec.get("running", {}).get("problem") == "rebase-on-main",
)
ALIVE.clear()


# 14v2. pipeline v2
fx.busy_session = lambda *a, **k: None
CAT = TMP / "catalog.md"
CAT.write_text(
    "# catalog\n- [A] Every import id is checked against the live object. Why: #258 H1.\n"
)
TARGETS["targets"]["prod"]["catalog"] = str(CAT)
TARGETS["targets"]["team"]["catalog"] = str(CAT)
(TMP / "autofix-targets.json").write_text(_json.dumps(TARGETS))
os.environ["OWNPR_FIX_SPAWN"] = "record"

# lane "waits on": recorded as a waiting give-up, quiet, no session, re-arms when they merge
frec = {}
states = {265: "OPEN", 267: "OPEN"}
fx.pr_state = lambda repo, n: states.get(int(n))
line = call(
    frec,
    reason="waits on #265, #267: the plan destroys 9 object(s) only their branches declare (x)",
)
ok(
    "v2 lane waits: no session, quiet, waits_on recorded",
    line is None
    and "running" not in frec
    and frec.get("gave_up", {}).get("waits_on") == [265, 267],
)
states.update({265: "MERGED", 267: "MERGED"})
call(frec, reason="needs me: plan-destroy", now=at(5))
ok(
    "v2 lane waits: both merged -> rebase-on-main session",
    frec.get("running", {}).get("problem") == "rebase-on-main",
)
ALIVE.clear()

# structured decision is parsed and kept on the give-up
frec = {}
call(frec, reason="1 blocking finding(s)")
run = frec["running"]
dec = {
    "question": "Accept the tenant-wide grant or narrow it?",
    "recommend": "A",
    "options": [
        {
            "id": "A",
            "label": "Narrow to scope tags",
            "action": "fix",
            "effect": "Use Device management scope tags for the release identity",
        },
        {
            "id": "B",
            "label": "Accept the risk",
            "action": "override",
            "effect": "Merge with the grant as is",
            "reply": "the owner accept B1. The grant is limited by the alert in improvement-id and the owner review it monthly.",
        },
        {"id": "C", "label": "Hold it", "action": "hold", "effect": "adds do-not-merge"},
    ],
}
Path(run["result_path"]).write_text(
    "x\nCATALOG ADD: [B] Device management write grants for one app use scope tags, never tenant-wide. Why: #249 B1 tenant-wide grant\n"
    "CATALOG ADD: [A] Every import id is checked against the live object. Why: #258 H1.\n"
    "FIX DECISION: " + _json.dumps(dec) + "\nFIX RESULT: gave-up - needs owner\n"
)
call(frec, reason="1 blocking finding(s)", now=at(1))
g = frec.get("gave_up") or {}
ok(
    "v2 decision kept on the give-up",
    (g.get("decision") or {}).get("recommend") == "A" and len(g["decision"]["options"]) == 3,
)
cat = CAT.read_text()
ok(
    "v2 catalog: new rule appended once, duplicate skipped",
    cat.count("scope tags, never tenant-wide") == 1
    and cat.count("checked against the live object") == 1
    and frec["history"][-1].get("catalog_added") == 1,
)

# malformed decisions are dropped
for name, bad in [
    ("one option", {"question": "q", "options": [{"id": "A", "label": "x", "action": "fix"}]}),
    (
        "unknown action",
        {
            "question": "q",
            "options": [
                {"id": "A", "label": "x", "action": "merge"},
                {"id": "B", "label": "y", "action": "hold"},
            ],
        },
    ),
    (
        "override reply with AI wording",
        {
            "question": "q",
            "options": [
                {"id": "A", "label": "x", "action": "fix"},
                {
                    "id": "B",
                    "label": "y",
                    "action": "override",
                    "reply": "The AI assistant says fine.",
                },
            ],
        },
    ),
    (
        "override reply with a semicolon",
        {
            "question": "q",
            "options": [
                {"id": "A", "label": "x", "action": "fix"},
                {"id": "B", "label": "y", "action": "override", "reply": "Fine; ship it."},
            ],
        },
    ),
    (
        "override reply carrying a marker",
        {
            "question": "q",
            "options": [
                {"id": "A", "label": "x", "action": "fix"},
                {
                    "id": "B",
                    "label": "y",
                    "action": "override",
                    "reply": "ok <!-- triage:abc1234 -->",
                },
            ],
        },
    ),
]:
    f = TMP / "bad.result"
    f.write_text("FIX DECISION: " + _json.dumps(bad) + "\n")
    ok(f"v2 decision dropped: {name}", fx.read_decision(f) is None)

# the owner's "fix it this way" choice starts a directed fix for that head, once, even past the daily cap
DIR = TMP.parent / "own-pr-directions.json" if False else fx.directions_file(TMP)
DIR.write_text(
    _json.dumps(
        {
            "prs": {
                "900": {
                    "head": HEAD,
                    "option_id": "A",
                    "action": "fix",
                    "label": "Narrow to scope tags",
                    "effect": "Use Device management scope tags",
                    "at": "2026-10-09T21:05:00Z",
                }
            }
        }
    )
)
frec["history"] = (
    frec.get("history", [])
    + [{"head": HEAD, "problem": "x", "started": NOW.strftime("%Y-%m-%dT%H:%M:%SZ")}] * 3
)
call(frec, reason="1 blocking finding(s)", now=at(6))
run = frec.get("running") or {}
brief = Path(run.get("brief", "/nonexistent")).read_text() if run else ""
ok(
    "v2 direction: directed-fix starts past the cap, brief carries the choice",
    run.get("problem") == "directed-fix"
    and "Narrow to scope tags" in brief
    and "gave_up" not in frec,
)
end(frec, "fixed", "narrowed")
call(frec, reason="1 blocking finding(s)", now=at(30))
ok(
    "v2 direction: used once (no second directed session for the same click)",
    (frec.get("running") or {}).get("problem") != "directed-fix",
)
DIR.write_text(
    _json.dumps(
        {
            "prs": {
                "900": {
                    "head": "f" * 40,
                    "action": "fix",
                    "label": "x",
                    "at": "2026-10-09T22:00:00Z",
                }
            }
        }
    )
)
frec2 = {}
call(frec2, status="held", reason="needs me: github-dir")
ok("v2 direction for another head is ignored", "running" not in frec2)
DIR.unlink()
ALIVE.clear()
ok(
    "v2 brief names preflight and the decision format",
    "preflight run --repo prod" in brief and "FIX DECISION:" in brief and "CATALOG ADD:" in brief,
)


# v2 regression (#280): a session that pushed a new head and then gave up with a decision files
# the decision under the PR's current head, so the card shows instead of a cap give-up.
frec = {}
call(frec, reason="2 high finding(s), no triage reply from me on this head")
run = frec["running"]
Path(run["result_path"]).write_text(
    "FIX DECISION: " + _json.dumps(dec) + "\nFIX RESULT: gave-up - needs owner\n"
)
ALIVE.discard(run["brief"])
NEWHEAD = "c" * 40
call(
    frec,
    reason="1 high finding(s), no triage reply from me on this head",
    p=pr(headRefOid=NEWHEAD),
    now=at(2),
)
g = frec.get("gave_up") or {}
ok(
    "v2 decision after a push is filed under the new head",
    g.get("head") == NEWHEAD and bool(g.get("decision")) and "running" not in frec,
)


# 14d. held-path pushes are batched, one push per round
def new_fix(frec, head, now, reason="checks red: lint", **kw):
    return fx.consider(
        "prod",
        "[prod the owner PR]",
        "owner/prod-repo",
        "owner-login",
        pr(headRefOid=head),
        "held",
        reason,
        frec,
        CFG,
        TMP,
        now,
        **kw,
    )


BASE = "1" * 40
H1 = "2" * 40
H2 = "3" * 40
clear_sessions()
# a held file in the push is recognised by the gate's own matcher
ok("held_files: .github script is held", bool(fx.held_files([".github/scripts/x.py"])))
ok("held_files: app source is not", fx.held_files(["apps/x/src/a.ts"]) == [])
ok("held_files: unknown files count as held", bool(fx.held_files(None)))
# (a) a push of held files opens the window, the next fix waits and records it
PUSHED["files"] = [".github/scripts/deploy_secrets.py", "apps/x/src/a.ts"]
f = {}
new_fix(f, BASE, NOW)
ok("14d first sight starts a session (no earlier push known)", bool(f.get("running")))
f.pop("running")
f["history"] = []
new_fix(f, H1, at(1))
ok("14d held push recorded", f.get("held_push", {}).get("head") == H1, str(f.get("held_push")))
ok(
    "14d second fix inside the window is batched, no session",
    not f.get("running") and f.get("batched", {}).get("problem") == "red-checks",
)
ok(
    "14d batched wait is about the rest of the window",
    0 < f["batched"]["wait_s"] <= fx.HELD_PUSH_WINDOW_S,
)
# (b) many findings, still no session until the window ends, then ONE session with the round rule
new_fix(f, H1, at(5), reason="1 high finding(s), no triage reply from me on this head")
new_fix(f, H1, at(10), reason="2 blocking finding(s)")
ok("14d several findings inside the window start nothing", not f.get("running"))
new_fix(f, H1, at(22))
ok("14d window over: exactly one session starts", bool(f.get("running")) and "batched" not in f)
brief = Path(f["running"]["brief"]).read_text()
ok(
    "14d brief carries the one-push-per-round rule",
    "ONE PUSH PER ROUND" in brief and "EVERY open finding" in brief,
)
# (c) the only blocker does not wait
f2 = {"seen_head": BASE}
PUSHED["files"] = [".github/workflows/a.yml"]
new_fix(f2, H1, at(1), others=[])
ok("14d sole blocker goes at once even inside the window", bool(f2.get("running")))
# (d) a directed-fix click never waits
f3 = {"seen_head": BASE}
fx_dir = fx.read_direction
fx.read_direction = lambda w, n, h: {"action": "fix", "label": "do it", "effect": "x", "at": "t1"}
new_fix(f3, H1, at(1))
fx.read_direction = fx_dir
ok(
    "14d directed fix ignores the window",
    bool(f3.get("running")) and f3["running"]["problem"] == "directed-fix",
)
# (e) non-held pushes still go immediately
PUSHED["files"] = ["apps/x/src/a.ts", "README.md"]
f4 = {"seen_head": BASE}
new_fix(f4, H1, at(1))
ok(
    "14d non-held push opens no window and the fix starts at once",
    "held_push" not in f4 and bool(f4.get("running")),
)
# (f) unreadable compare fails toward batching, never toward an extra push
PUSHED["files"] = None
f5 = {"seen_head": BASE}
new_fix(f5, H1, at(1))
ok("14d unknown files batch", bool(f5.get("held_push")) and not f5.get("running"))
# (g) not a build target (<ops-center>, core): the window never applies
PUSHED["files"] = [".github/scripts/x.py"]
f6 = {"seen_head": BASE}
fx.consider(
    "ops-center",
    "[ops-center the owner's PR]",
    "owner-login/ops-center-repo",
    "owner-login",
    pr(headRefOid=H1),
    "held",
    "checks red: lint",
    f6,
    CFG,
    TMP,
    at(1),
)
ok("14d other targets are untouched", "held_push" not in f6 and bool(f6.get("running")))
PUSHED["files"] = ["apps/x/src/a.ts"]
clear_sessions()

# 15. liveness: a pid is alive only when the marker is on its command line, and pid <= 0 never is
marker = str(TMP / "spawn-marker.brief.txt")
proc = subprocess.Popen(["/bin/sh", "-c", "sleep 30; true", marker], stdin=subprocess.DEVNULL)
time.sleep(0.5)
ok("alive: running", _real_alive(proc.pid))
ok(
    "alive: marker matches this session only",
    _real_alive(proc.pid, marker) and not _real_alive(proc.pid, "/other/brief.txt"),
)
ok("pid <= 0 is never alive", not _real_alive(-1) and not _real_alive(0))
proc.kill()
proc.wait()
ok("alive: gone after stop", not _real_alive(proc.pid, marker))

# 16. part 3: the standing residual-risk rule rides in the brief, from policy config only
RULE = {
    "id": "RR-1",
    "enabled": True,
    "text": "A finding is accepted ONLY when BOTH hold: (i) a race window of about a second or less, AND (ii) a named recovery exists.",
    "td_file": "technical-debt.md",
}
BASE_CTX = {
    "target": "prod",
    "repo": "o/r",
    "pr": 7,
    "title": "t",
    "url": "u",
    "branch": "b",
    "head": HEAD,
    "problem": "untriaged-highs",
    "reason": "r",
    "attempt": 1,
    "max": 3,
    "result_path": "/tmp/x.result",
    "gates": "g",
    "round": "",
    "waits_on": [],
    "direction": None,
}
with_rule = fx.brief_text(
    dict(BASE_CTX, residual=fx.residual_rule_text({"residual_risk_rule": RULE}))
)
ok(
    "16a brief names the rule id, both conditions and the debt append",
    all(
        x in with_rule
        for x in ("RR-1", "BOTH hold", "technical-debt.md", "- **Status**: accepted", "file:line")
    ),
    "",
)
ok(
    "16b brief demands the three citations",
    "the rule id (RR-1), the race window in seconds, and the named recovery" in with_rule,
)
ok(
    "16c brief keeps the lane marker rule (only named ids clear)",
    "The lane clears only the ids named" in with_rule and "clears only those ids" in with_rule,
)
ok(
    "16d brief says grep the highest TD id first",
    'grep -o "DEBT-[0-9]*"' in with_rule and "next id" in with_rule,
)
ok(
    "16e brief stays ASCII with no em dash or semicolon in the rule block",
    with_rule.isascii()
    and "\u2014" not in with_rule
    and ";" not in fx.residual_rule_text({"residual_risk_rule": RULE}),
)
ok("16f only a high qualifies", "never qualifies, only a high" in with_rule)
none_brief = fx.brief_text(dict(BASE_CTX, residual=""))
for label, cfgx in (
    ("absent", {}),
    ("disabled", {"residual_risk_rule": dict(RULE, enabled=False)}),
    ("no id", {"residual_risk_rule": dict(RULE, id="")}),
    ("not a dict", {"residual_risk_rule": "x"}),
    ("none cfg", None),
):
    ok("16g rule " + label + " adds nothing", fx.residual_rule_text(cfgx) == "")
ok("16h no rule means no rule text in the brief", "residual-risk" not in none_brief)

print("FAILURES:", fails)
sys.exit(1 if fails else 0)
