#!/usr/bin/env python3
# Synthetic tests for own_pr_merge.py (no network, no real PRs).
import base64
import contextlib
import datetime as dt
import importlib.util
import io
import json
import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "testing"))
import policy_env  # noqa: E402

STATE_ROOT = (
    policy_env.install()
)  # a scratch state tree holding the policy fixtures, so no live state is read

# The lane under test is the sibling file of this repo, not the installed copy, so a checkout tests its own
# code. The sibling modules it imports (gh_run_jobs) must resolve when the file is run by unittest too.
HERE = Path(__file__).resolve().parent.parent  # the lanes folder; this file sits in lanes/tests
LANE_PY = HERE / "own_pr_merge.py"
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
TMP = Path(tempfile.mkdtemp(prefix="ownpr-"))
os.environ["OPRG_STATE_DIR"] = str(TMP)
os.environ["OPRG_CACHE_DIR"] = str(TMP)
# the sign-off store lives in the tf-review state dir, keep it in the scratch dir too.
os.environ["TFGATE_STATE_DIR"] = str(TMP / "tfstate")
os.environ["TFGATE_CACHE_DIR"] = str(TMP / "tfcache")
(TMP / "tfstate").mkdir()
(TMP / "tfcache").mkdir()
os.environ["OPRG_POLICY"] = str(STATE_ROOT / "review" / "policy.json")
FREEZE = TMP / "freeze.json"
os.environ["OWNPR_FREEZE_FILE"] = str(FREEZE)
FREEZE.write_text(json.dumps({"timezone": "America/New_York", "windows": []}))
# The fixer reads the session store for busy sessions and archives finished auto-fix sessions.
# Point it at an empty temp store so a live session that mentions the test PR never defers it
# and a test run never archives real sessions.
SESSIONS_DB = TMP / "state.db"
os.environ["OWNPR_STATE_DB"] = str(SESSIONS_DB)
os.environ["OWNPR_ARCHIVE"] = "record"
_c = sqlite3.connect(SESSIONS_DB)
_c.executescript(
    "CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT, ended_at REAL,"
    " last_activity_at REAL, archived INTEGER DEFAULT 0);"
    "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, content TEXT,"
    " tool_calls TEXT, timestamp REAL);"
    "CREATE TABLE session_turn_leases (conversation_id TEXT PRIMARY KEY, holder TEXT, acquired_at REAL,"
    " expires_at REAL);"
)
_c.commit()
_c.close()

spec = importlib.util.spec_from_file_location("own", str(LANE_PY))
own = importlib.util.module_from_spec(spec)
spec.loader.exec_module(own)
eng = own.eng

HEAD = "a" * 40
GREEN = [
    {
        "name": "lint / typecheck / test / build",
        "workflowName": "CI",
        "conclusion": "SUCCESS",
        "status": "COMPLETED",
        "startedAt": "2026-10-09T10:00:00Z",
    },
    {
        "name": "ai-review result",
        "workflowName": "platform PR Review",
        "conclusion": "SUCCESS",
        "status": "COMPLETED",
        "startedAt": "2026-10-09T10:00:00Z",
    },
]


def pr(**kw):
    base = {
        "number": 900,
        "title": "t",
        "url": "u",
        "headRefOid": HEAD,
        "headRefName": "ticket-id-x",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "statusCheckRollup": GREEN,
        "labels": [],
    }
    base.update(kw)
    return base


def comment(login, created, body=""):
    return {"user": {"login": login}, "created_at": created, "updated_at": created, "body": body}


def review_comment(verdict, counts, created="2026-10-09T10:05:00Z", head=HEAD):
    blob = base64.b64encode(
        json.dumps({"verdict": verdict, "counts": counts, "head_sha": head}).encode()
    ).decode()
    return comment(
        "github-actions[bot]",
        created,
        f"{eng.AI_REVIEW_MARKER}\nx\n{eng.AI_REVIEW_DATA_PREFIX}{blob}{eng.AI_REVIEW_DATA_SUFFIX}",
    )


def triage(created, sha=HEAD, text="H1 refuted, see the code.", ids="H1 H2 B1"):
    # the marker names the finding ids it answers. ids="" writes a bare marker.
    tail = f" {ids}" if ids else ""
    return comment("owner-account", created, f"{text}\n<!-- triage:{sha}{tail} -->")


STATE = {"comments": [], "check": {}, "calls": [], "merge_ok": True, "list": []}


def fake_gh(args, timeout=60, raw=False):
    STATE["calls"].append(args)
    if args[:2] == ["pr", "list"]:
        return STATE["list"]
    if args[0] == "api" and "/events" in " ".join(args):
        return "\n".join(json.dumps(e) for e in STATE.get("events", [])) + "\n"
    if args[0] == "api" and "/comments" in " ".join(args):
        return "\n".join(json.dumps(c) for c in STATE["comments"]) + "\n"
    if args[0] == "api" and "actions/runs?head_sha=" in " ".join(args):
        return {"workflow_runs": STATE.get("runs", [])}
    if args[0] == "api" and re.search(r"actions/runs/\d+/jobs", " ".join(args)):
        rid = int(re.search(r"actions/runs/(\d+)/jobs", " ".join(args)).group(1))
        return {"jobs": STATE.get("jobs", {}).get(rid, [])}
    if args[0] == "api" and re.search(r"actions/jobs/\d+/logs", " ".join(args)):
        jid = int(re.search(r"actions/jobs/(\d+)/logs", " ".join(args)).group(1))
        return STATE.get("logs", {}).get(jid, "")
    if args[:2] == ["run", "rerun"]:
        return ""
    if args[:2] == ["pr", "diff"]:
        return STATE.get("diffs", {}).get(int(args[2]), "")
    if args[:2] == ["pr", "merge"]:
        if not STATE["merge_ok"]:
            raise eng.GhError("pr merge: rc=1 boom")
        return ""
    if args[:2] == ["pr", "view"]:
        return {"state": "MERGED", "mergeCommit": {"oid": "b" * 40}}
    raise AssertionError(f"unexpected gh call {args}")


def fake_check(n):
    c = {
        "head_sha": HEAD,
        "escalate": False,
        "escalations": [],
        "unresolved_threads": 0,
        "checks": {"green": True, "red": [], "pending": []},
    }
    c.update(STATE["check"])
    return c


eng.gh = fake_gh
eng.check = fake_check
POL = eng.policy()
CFG = own.config(POL)
fails = 0


def expect(name, p, status, contains="", comments=None, check=None, freeze=None):
    global fails
    STATE["comments"] = (
        comments
        if comments is not None
        else [review_comment("findings", {"blocking": 0, "high": 0})]
    )
    STATE["check"] = check or {}
    FREEZE.write_text(json.dumps({"timezone": "America/New_York", "windows": freeze or []}))
    got, reason, _ = own.evaluate(p, CFG, POL, {}, force=True)
    ok = got == status and contains.lower() in reason.lower()
    fails += not ok
    print(f"{'OK  ' if ok else 'FAIL'} {name}: {got} ({reason})")


expect("model bump skipped", pr(headRefName="ticket-id-review-model-bump-20261009"), "skip")
expect("draft held", pr(isDraft=True), "held", "draft")
expect("do-not-merge label held", pr(labels=[{"name": "do-not-merge"}]), "held", "do-not-merge")
expect("hold label held", pr(labels=[{"name": "Hold"}]), "held", "hold")
expect("conflict held", pr(mergeable="CONFLICTING"), "held", "conflict")
red = GREEN + [
    {
        "name": "terraform plan (x)",
        "workflowName": "terraform-ci",
        "conclusion": "FAILURE",
        "status": "COMPLETED",
        "startedAt": "2026-10-09T10:01:00Z",
    }
]
expect(
    "red check held",
    pr(statusCheckRollup=red),
    "held",
    "checks red",
    check={
        "checks": {
            "green": False,
            "red": ["terraform-ci/terraform plan (x)"],
            "pending": [],
            "destroy_guard_only": False,
        }
    },
)
lint_red = GREEN + [
    {
        "name": "copy-standards (no em dashes)",
        "workflowName": "CI",
        "conclusion": "FAILURE",
        "status": "COMPLETED",
        "startedAt": "2026-10-09T10:01:00Z",
    }
]
expect(
    "non-terraform red held before the deep check",
    pr(statusCheckRollup=lint_red),
    "held",
    "checks red: CI/copy-standards",
)
mixed_red = red + lint_red[-1:]
expect("destroy guard plus another red held", pr(statusCheckRollup=mixed_red), "held", "checks red")
guard_red = GREEN + [
    {
        "name": "terraform plan (platform-core platform)",
        "workflowName": "terraform-ci",
        "conclusion": "FAILURE",
        "status": "COMPLETED",
        "startedAt": "2026-10-09T10:01:00Z",
    },
    {
        "name": "terraform-ci result",
        "workflowName": "terraform-ci",
        "conclusion": "FAILURE",
        "status": "COMPLETED",
        "startedAt": "2026-10-09T10:02:00Z",
    },
]
GUARD_CHECK = {
    "escalate": True,
    "escalations": [{"rule": "plan-destroy"}, {"rule": "rbac-user-or-group"}],
    "checks": {
        "green": False,
        "pending": [],
        "destroy_guard_only": True,
        "red": [
            "terraform-ci/terraform plan (platform-core platform)",
            "terraform-ci/terraform-ci result",
        ],
    },
}
expect(
    "destroy guard only goes to the owner's sign-off",
    pr(statusCheckRollup=guard_red),
    "held",
    "needs me: plan-destroy",
    check=GUARD_CHECK,
)
expect(
    "destroy guard red the engine does not confirm stays red",
    pr(statusCheckRollup=guard_red),
    "held",
    "checks red",
    check=dict(GUARD_CHECK, checks=dict(GUARD_CHECK["checks"], destroy_guard_only=False)),
)
expect(
    "destroy guard with untriaged highs fixes the highs first",
    pr(statusCheckRollup=guard_red),
    "held",
    "no triage",
    comments=[review_comment("findings", {"high": 2})],
    check=GUARD_CHECK,
)
ok = own.fixer.problem_of("held", "needs me: plan-destroy, rbac-user-or-group") is None
fails += not ok
print(f"{'OK  ' if ok else 'FAIL'} a destroy-guard sign-off never starts an auto-fix")

# Engine: destroy_guard_only reads the plan jobs
PLAN = {
    "ran": True,
    "roots": [
        {"job": "terraform plan (platform-core platform)", "guard_only": True},
        {"job": "terraform plan (vendor-b platform)", "guard_only": False},
    ],
}
cases = [
    (
        "guard job + result",
        {
            "red": [
                "terraform-ci/terraform plan (platform-core platform)",
                "terraform-ci/terraform-ci result",
            ],
            "pending": [],
        },
        PLAN,
        True,
    ),
    (
        "a real plan failure",
        {
            "red": [
                "terraform-ci/terraform plan (vendor-b platform)",
                "terraform-ci/terraform-ci result",
            ],
            "pending": [],
        },
        PLAN,
        False,
    ),
    (
        "still running",
        {"red": ["terraform-ci/terraform plan (platform-core platform)"], "pending": ["x"]},
        PLAN,
        False,
    ),
    (
        "no plan read",
        {"red": ["terraform-ci/terraform plan (platform-core platform)"], "pending": []},
        {"ran": False},
        False,
    ),
    ("nothing red", {"red": [], "pending": []}, PLAN, False),
]
for label, summ, plan, want in cases:
    got = eng.destroy_guard_only(summ, plan)
    fails += got != want
    print(f"{'OK  ' if got == want else 'FAIL'} engine destroy_guard_only {label}: {got}")
pend = GREEN + [
    {
        "name": "coverage (platform)",
        "workflowName": "terraform-drift",
        "conclusion": None,
        "status": "WAITING",
        "startedAt": "2026-10-09T10:01:00Z",
    }
]
expect("pending waits", pr(statusCheckRollup=pend), "waiting", "running")
expect("no ai result waits", pr(statusCheckRollup=GREEN[:1]), "waiting", "ai-review")
expect(
    "no verdict for head held",
    pr(),
    "held",
    "no PR review verdict",
    comments=[review_comment("clean", {}, head="c" * 40)],
)
expect(
    "blocked verdict held",
    pr(),
    "held",
    "verdict blocked",
    comments=[review_comment("blocked", {"blocking": 1})],
)
expect(
    "unavailable held", pr(), "held", "unavailable", comments=[review_comment("unavailable", {})]
)

# an override the owner applied plus a triage reply on this head turns a blocked
# verdict into a policy hold (Approve and merge), never a lane merge.
OVR = [{"name": "ai-review-override"}]
BLOCKED_TRIAGED = [
    review_comment("blocked", {"blocking": 1, "high": 2}),
    triage("2026-10-09T10:06:00Z"),
]


def ovr_events(actor):
    return [
        {
            "event": "labeled",
            "label": {"name": "ai-review-override"},
            "actor": {"login": "account"},
        },
        {"event": "labeled", "label": {"name": "ai-review-override"}, "actor": {"login": actor}},
    ]


STATE["events"] = ovr_events("owner-account")
expect(
    "override by me + triage = policy hold",
    pr(labels=OVR),
    "held",
    "needs me: ai-review-override",
    comments=BLOCKED_TRIAGED,
)
expect(
    "override keeps other policy rules",
    pr(labels=OVR),
    "held",
    "needs me: ai-review-override, rbac-scope-outside-app",
    comments=BLOCKED_TRIAGED,
    check={"escalate": True, "escalations": [{"rule": "rbac-scope-outside-app"}]},
)
expect(
    "override never skips red checks",
    pr(labels=OVR),
    "held",
    "checks red",
    comments=BLOCKED_TRIAGED,
    check={"checks": {"green": False, "red": ["terraform-ci/x"], "pending": []}},
)
expect(
    "override without triage held",
    pr(labels=OVR),
    "held",
    "verdict blocked",
    comments=[review_comment("blocked", {"blocking": 1})],
)
expect(
    "blocked triaged without label held", pr(), "held", "verdict blocked", comments=BLOCKED_TRIAGED
)
expect(
    "override on unavailable held",
    pr(labels=OVR),
    "held",
    "verdict unavailable",
    comments=[review_comment("unavailable", {}), triage("2026-10-09T10:06:00Z")],
)
STATE["events"] = ovr_events("account")
expect(
    "override by someone else held",
    pr(labels=OVR),
    "held",
    "verdict blocked",
    comments=BLOCKED_TRIAGED,
)
STATE["events"] = []
expect(
    "high untriaged held",
    pr(),
    "held",
    "no triage",
    comments=[review_comment("findings", {"high": 2})],
)
expect(
    "high with triage before the review held",
    pr(),
    "held",
    "no triage",
    comments=[triage("2026-10-09T10:00:00Z"), review_comment("findings", {"high": 2})],
)
expect(
    "high triaged with marker ready",
    pr(),
    "ready",
    "2 high triaged",
    comments=[review_comment("findings", {"high": 2}), triage("2026-10-09T10:06:00Z")],
)
expect(
    "short-sha marker counts",
    pr(),
    "ready",
    "1 high triaged",
    comments=[
        review_comment("findings", {"high": 1}),
        triage("2026-10-09T10:06:00Z", sha=HEAD[:7]),
    ],
)
expect(
    "plain fix request is not triage",
    pr(),
    "held",
    "no triage",
    comments=[
        review_comment("findings", {"high": 1}),
        comment("owner-account", "2026-10-09T10:06:00Z", "H1 needs a fix before this goes in."),
    ],
)
expect(
    "marker for another head is not triage",
    pr(),
    "held",
    "no triage",
    comments=[
        review_comment("findings", {"high": 1}),
        triage("2026-10-09T10:06:00Z", sha="e" * 40),
    ],
)
expect(
    "other user marker is not triage",
    pr(),
    "held",
    "no triage",
    comments=[
        review_comment("findings", {"high": 1}),
        comment("account", "2026-10-09T10:06:00Z", f"<!-- triage:{HEAD} -->"),
    ],
)
# a triage reply clears only the finding ids its marker names.
T1, T2 = "2026-10-09T10:06:00Z", "2026-10-09T10:07:00Z"
H2REV = review_comment("findings", {"high": 2})
# core-rule: pr-review-and-merge.1.8
expect(
    "bare marker no longer clears",
    pr(),
    "held",
    "no triage reply from me on this head (missing H1, H2)",
    comments=[H2REV, triage(T1, ids="")],
)
expect(
    "partial ids held with missing ids",
    pr(),
    "held",
    "2 high finding(s), triage reply covers H2 only (missing H1)",
    comments=[H2REV, triage(T1, ids="H2")],
)
expect("full ids ready", pr(), "ready", "2 high triaged", comments=[H2REV, triage(T1, ids="H1 H2")])
expect(
    "ids spread over two comments ready",
    pr(),
    "ready",
    "2 high triaged",
    comments=[H2REV, triage(T1, ids="H2"), triage(T2, ids="H1")],
)
# core-rule: pr-review-and-merge.1.8
expect(
    "ids on an older head ignored",
    pr(),
    "held",
    "covers H2 only (missing H1)",
    comments=[H2REV, triage(T1, sha="e" * 40, ids="H1"), triage(T2, ids="H2")],
)
# core-rule: pr-review-and-merge.1.8
expect(
    "ids in a comment before the review ignored",
    pr(),
    "held",
    "covers H2 only (missing H1)",
    comments=[triage("2026-10-09T10:00:00Z", ids="H1"), H2REV, triage(T1, ids="H2")],
)
expect(
    "lower case and comma ids ready",
    pr(),
    "ready",
    "2 high triaged",
    comments=[
        H2REV,
        comment("owner-account", T1, f"Both refuted.\n<!-- triage:{HEAD[:7]} h1,H2 -->"),
    ],
)
expect(
    "comma right after the sha ready",
    pr(),
    "ready",
    "2 high triaged",
    comments=[H2REV, comment("owner-account", T1, f"x <!--triage:{HEAD},h2, h1-->")],
)
expect(
    "other user ids are not triage",
    pr(),
    "held",
    "covers H2 only (missing H1)",
    comments=[H2REV, triage(T1, ids="H2"), comment("account", T2, f"<!-- triage:{HEAD} H1 -->")],
)
expect(
    "ten highs need H10",
    pr(),
    "held",
    "(missing H10)",
    comments=[
        review_comment("findings", {"high": 10}),
        triage(T1, ids=" ".join(f"H{i}" for i in range(1, 10))),
    ],
)
expect(
    "B ids alone do not clear highs",
    pr(),
    "held",
    "no triage reply from me on this head (missing H1, H2)",
    comments=[H2REV, triage(T1, ids="B1 B2")],
)
STATE["events"] = ovr_events("owner-account")
BLK2 = review_comment("blocked", {"blocking": 2, "high": 1})
expect(
    "override needs every B id",
    pr(labels=OVR),
    "held",
    "verdict blocked, override triage covers B1 only (missing B2)",
    comments=[BLK2, triage(T1, ids="B1 H1")],
)
expect(
    "override with H ids only held",
    pr(labels=OVR),
    "held",
    "verdict blocked",
    comments=[BLK2, triage(T1, ids="H1")],
)
expect(
    "override bare marker held",
    pr(labels=OVR),
    "held",
    "verdict blocked",
    comments=[BLK2, triage(T1, ids="")],
)
expect(
    "override with every B and H id = policy hold",
    pr(labels=OVR),
    "held",
    "needs me: ai-review-override",
    comments=[BLK2, triage(T1, ids="B1, B2"), triage(T2, ids="h1")],
)
expect(
    "override with B ids but a high missing held",
    pr(labels=OVR),
    "held",
    "1 high finding(s), no triage reply from me on this head (missing H1)",
    comments=[BLK2, triage(T1, ids="B1 B2")],
)
expect(
    "findings verdict with blocking partial held",
    pr(labels=OVR),
    "held",
    "2 blocking finding(s), override triage covers B2 only (missing B1)",
    comments=[review_comment("findings", {"blocking": 2, "high": 0}), triage(T1, ids="B2 B3")],
)
STATE["events"] = []

expect(
    "policy escalation held",
    pr(),
    "held",
    "tf-exclusions",
    check={"escalate": True, "escalations": [{"rule": "tf-exclusions"}]},
)
expect("unresolved thread held", pr(), "held", "unresolved", check={"unresolved_threads": 1})
expect("head moved held", pr(), "held", "head moved", check={"head_sha": "d" * 40})
# The freeze file is read in its own zone, so the windows are built from the wall clock of that zone, not the host's.
FREEZE_NOW = dt.datetime.now(ZoneInfo("America/New_York")).replace(tzinfo=None)
now_local = FREEZE_NOW
win = [
    {
        "id": "test-freeze",
        "start": (now_local - dt.timedelta(hours=1)).isoformat(timespec="seconds"),
        "end": (now_local + dt.timedelta(hours=1)).isoformat(timespec="seconds"),
    }
]
expect("freeze held", pr(), "held", "change freeze test-freeze", freeze=win)
past = [{"id": "old", "start": "2026-01-01T00:00:00", "end": "2026-01-02T00:00:00"}]
expect("past freeze ignored, clean ready", pr(), "ready", "0 high", freeze=past)

# tick: merges a clean PR with --admin --match-head-commit and records it
FREEZE.write_text(json.dumps({"timezone": "America/New_York", "windows": []}))
STATE.update(
    list=[pr()],
    comments=[review_comment("clean", {"blocking": 0, "high": 0})],
    check={},
    calls=[],
    merge_ok=True,
)
own.tick()
merges = [c for c in STATE["calls"] if c[:2] == ["pr", "merge"]]
ok = merges == [
    [
        "pr",
        "merge",
        "900",
        "-R",
        "owner/primary-repo",
        "--rebase",
        "--admin",
        "--match-head-commit",
        HEAD,
    ]
]
st = json.loads((TMP / "own-pr-merge.json").read_text())
ok = ok and st["prs"]["900"]["status"] == "merged"
fails += not ok
print(f"{'OK  ' if ok else 'FAIL'} tick merges clean PR with pinned head: {merges}")

# tick: merge failure is reported once per head
(TMP / "own-pr-merge.json").unlink()
STATE.update(calls=[], merge_ok=False)
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    own.tick()
    own.tick()
lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
ok = len(lines) == 1 and "merge failed" in lines[0]
fails += not ok
print(f"{'OK  ' if ok else 'FAIL'} merge failure reported once: {lines}")

# DRY_RUN never calls pr merge
(TMP / "own-pr-merge.json").unlink()
eng.DRY_RUN = True
STATE.update(calls=[], merge_ok=True)
own.tick()
ok = not [c for c in STATE["calls"] if c[:2] == ["pr", "merge"]]
st = json.loads((TMP / "own-pr-merge.json").read_text())
ok = ok and st["prs"]["900"]["status"] == "would_merge"
fails += not ok
print(f"{'OK  ' if ok else 'FAIL'} dry run never merges")

# Cache: an unchanged held PR stays cached, a bumped updatedAt re-checks at once
eng.DRY_RUN = False
cached = {
    "head": HEAD,
    "deep": "held",
    "policy_sha": POL["_sha"],
    "pr_updated": "2026-10-09T10:05:00Z",
    "deep_epoch": own.NOW.timestamp(),
    "reason": "1 high finding(s), no triage reply from me on this head",
}
STATE.update(
    comments=[review_comment("findings", {"high": 1}), triage("2026-10-09T10:06:00Z")], check={}
)
got, why, _ = own.evaluate(pr(updatedAt="2026-10-09T10:05:00Z"), CFG, POL, dict(cached))
ok = got == "held" and "no triage" in why
fails += not ok
print(f"{'OK  ' if ok else 'FAIL'} unchanged held PR uses the cache: {got} ({why})")
got, why, _ = own.evaluate(pr(updatedAt="2026-10-09T10:06:00Z"), CFG, POL, dict(cached))
ok = got == "ready" and "1 high triaged" in why
fails += not ok
print(f"{'OK  ' if ok else 'FAIL'} new comment (updatedAt bump) re-checks at once: {got} ({why})")

# One PR raising an unexpected error is held, the other still merges, no crash
(TMP / "own-pr-merge.json").unlink(missing_ok=True)
real_check = eng.check


def flaky_check(n):
    if n == 901:
        raise TypeError("boom")
    return real_check(n)


eng.check = flaky_check
STATE.update(
    list=[pr(number=901), pr(number=902)],
    comments=[review_comment("clean", {"blocking": 0, "high": 0})],
    check={},
    calls=[],
    merge_ok=True,
)
own.tick()
st = json.loads((TMP / "own-pr-merge.json").read_text())
merges = [c[2] for c in STATE["calls"] if c[:2] == ["pr", "merge"]]
ok = (
    st["prs"]["901"]["status"] == "held"
    and "lane error: TypeError" in st["prs"]["901"]["reason"]
    and st["prs"]["902"]["status"] == "merged"
    and merges == ["902"]
    and st.get("error_count") == 0
)
fails += not ok
print(
    f"{'OK  ' if ok else 'FAIL'} bad PR isolated, good PR merged: 901={st['prs']['901'].get('reason')} merges={merges}"
)
eng.check = real_check

# A failure outside the per-PR loop is counted, never crashes, never merges
(TMP / "own-pr-merge.json").unlink(missing_ok=True)
real_list = own.list_mine
own.list_mine = lambda pol: (_ for _ in ()).throw(AttributeError("bad list"))
STATE.update(calls=[])
own.tick()
st = json.loads((TMP / "own-pr-merge.json").read_text())
ok = (
    st.get("error_count") == 1
    and "AttributeError" in st.get("last_error", "")
    and not STATE["calls"]
)
fails += not ok
print(
    f"{'OK  ' if ok else 'FAIL'} list failure counted: {st.get('error_count')} {st.get('last_error')}"
)
own.list_mine = real_list

# a held PR of mine with a fixable problem starts one fix session on the SAME pass
os.environ["OWNPR_FIX_SPAWN"] = "record"
(TMP / "own-pr-merge.json").unlink(missing_ok=True)
STATE.update(
    list=[pr(number=910, statusCheckRollup=lint_red), pr(number=911)],
    check={},
    calls=[],
    merge_ok=True,
    comments=[review_comment("clean", {"blocking": 0, "high": 0})],
)
own.tick()
st = json.loads((TMP / "own-pr-merge.json").read_text())
run = st.get("fix", {}).get("910", {}).get("running") or {}
dec = [
    json.loads(ln)
    for ln in (own.eng.STATE_DIR / "decisions.jsonl").read_text().splitlines()
    if ln.strip()
]
ok = (
    run.get("problem") == "red-checks"
    and st["prs"]["911"]["status"] == "merged"
    and not st.get("fix", {}).get("911", {}).get("running")
    and any(d.get("decision") == "autofix-started" and d.get("pr") == 910 for d in dec)
    and [c[2] for c in STATE["calls"] if c[:2] == ["pr", "merge"]] == ["911"]
)
fails += not ok
print(
    f"{'OK  ' if ok else 'FAIL'} red PR starts a fix session on the first pass, clean PR still merges: {run.get('problem')}"
)

# A policy hold never starts a fix session
(TMP / "own-pr-merge.json").unlink(missing_ok=True)
STATE.update(
    list=[pr(number=912)],
    check={"escalate": True, "escalations": [{"rule": "rbac-user-or-group"}]},
    calls=[],
)
own.tick()
st = json.loads((TMP / "own-pr-merge.json").read_text())
ok = st["prs"]["912"]["reason"].startswith("needs me") and not st.get("fix", {}).get("912", {}).get(
    "running"
)
fails += not ok
print(f"{'OK  ' if ok else 'FAIL'} policy hold: no fix session ({st['prs']['912']['reason']})")

# Defensive: a PR by someone else that slips into the list is never fixed or merged
(TMP / "own-pr-merge.json").unlink(missing_ok=True)
STATE.update(
    list=[
        pr(number=913, author={"login": "account"}, statusCheckRollup=red),
        pr(number=914, author={"login": "account"}),
    ],
    check={},
    calls=[],
    comments=[review_comment("clean", {"blocking": 0, "high": 0})],
)
own.tick()
st = json.loads((TMP / "own-pr-merge.json").read_text())
ok = not st.get("fix", {}).get("913", {}).get("running") and not [
    c for c in STATE["calls"] if c[:2] == ["pr", "merge"]
]
fails += not ok
print(f"{'OK  ' if ok else 'FAIL'} other author (red and clean): never fixed, never merged")

# Closing the PR drops its fix state once no session runs
STATE.update(list=[], calls=[])
own.tick()
st = json.loads((TMP / "own-pr-merge.json").read_text())
ok = "913" not in st.get("fix", {})
fails += not ok
print(f"{'OK  ' if ok else 'FAIL'} closed PR fix state dropped")

# a coverage red that only lists objects the head's own plan imports is resolved.
SUB = "/subscriptions/***/resourceGroups/platform/providers/Microsoft.Automation/automationAccounts/prod-prefix-automation-aa"
HOOK_A, HOOK_B = "team-prefix-a-hook", "team-prefix-b-hook"
COV = {}


def cov_log(ids, extra=()):
    lines = ["2026-10-13T16:27:35.8211451Z ##[warning]51 tracked object(s) not yet in Terraform"]
    lines += [f"2026-10-13T16:27:35.8227660Z ##[error]platform {SUB}/webhooks/{h}" for h in ids]
    lines += ["2026-10-13T16:27:35.8227660Z ##[error]%s" % e for e in extra]  # noqa: UP031
    lines.append("2026-10-13T16:27:35.8249307Z ##[error]Process completed with exit code 1.")
    # The echoed script lines carry ::error text too and must never count.
    lines.append(
        '2026-10-13T16:24:54.6396875Z   || { echo "::error::Azure CLI is not signed in"; exit 1; }'
    )
    return "\n".join(lines)


def plan_log(ids, suffix=""):
    return "\n".join(
        '2026-10-13T16:25:26.1Z \x1b[0mazurerm_automation_webhook.hook["%s"]: Preparing import... [id=%s/webHooks/%s%s]'  # noqa: UP031
        % (h, SUB, h, suffix)
        for h in ids
    ) + "\n2026-10-13T16:25:26.6Z Plan: %d to import, 0 to add, 0 to change, 0 to destroy." % len(  # noqa: UP031
        ids
    )


def cov_gh(args, timeout=60, raw=False):
    a = " ".join(args)
    if args[0] == "api" and "/actions/" in a:
        STATE["calls"].append(args)
        if COV.get("boom"):
            raise eng.GhError("api: rc=1 boom")
        if "actions/runs?head_sha=" in a:
            return {
                "workflow_runs": [
                    {
                        "id": 1,
                        "path": ".github/workflows/terraform-ci.yml",
                        "event": "pull_request",
                        "status": "completed",
                        "created_at": "2026-10-13T16:24:00Z",
                    },
                    {
                        "id": 2,
                        "path": ".github/workflows/terraform-drift.yml",
                        "event": "pull_request",
                        "status": COV.get("drift_status", "completed"),
                        "created_at": "2026-10-13T16:24:00Z",
                    },
                ]
            }
        if "actions/runs/1/jobs" in a:
            return {
                "jobs": [
                    {
                        "id": 11,
                        "name": COV.get("plan_job", "terraform plan (runbooks platform)"),
                        "conclusion": COV.get("plan_conclusion", "success"),
                    }
                ]
            }
        if "actions/runs/2/jobs" in a:
            return {"jobs": [{"id": 21, "name": "coverage (platform)", "conclusion": "failure"}]}
        if "actions/jobs/11/logs" in a:
            return plan_log(COV.get("imported", [HOOK_A, HOOK_B]), COV.get("suffix", ""))
        if "actions/jobs/21/logs" in a:
            return cov_log(COV.get("unmanaged", [HOOK_A, HOOK_B]), COV.get("extra", ()))
    return fake_gh(args, timeout, raw)


COV_RED = GREEN + [
    {
        "name": "coverage (platform)",
        "workflowName": "terraform-drift",
        "conclusion": "FAILURE",
        "status": "COMPLETED",
        "startedAt": "2026-10-13T16:24:00Z",
    }
]
COV_CHECK = {
    "checks": {
        "green": False,
        "red": ["terraform-drift/coverage (platform)"],
        "pending": [],
        "destroy_guard_only": False,
    }
}


def expect_cov(name, status, contains="", check=None, **cov):
    COV.clear()
    COV.update(cov)
    eng.gh = cov_gh
    try:
        expect(name, pr(statusCheckRollup=COV_RED), status, contains, check=check or COV_CHECK)
    finally:
        eng.gh = fake_gh


expect_cov(
    "coverage red only on imported ids merges",
    "ready",
    "coverage red only on 2 object(s) this PR imports",
)
expect_cov(
    "coverage id the plan does not import holds",
    "held",
    "checks red: terraform-drift/coverage",
    imported=[HOOK_A],
)
expect_cov(
    "coverage failing for another reason holds",
    "held",
    "checks red: terraform-drift/coverage",
    extra=["platform state container allows public access"],
)
expect_cov(
    "azapi import id with ?api-version= matches the coverage id",
    "ready",
    "coverage red only on 2 object(s) this PR imports",
    suffix="?api-version=2022-10-01",
)
expect_cov("coverage read error (no ids listed) holds", "held", "checks red", unmanaged=[])
expect_cov(
    "failed plan job never counts as an import", "held", "checks red", plan_conclusion="failure"
)
expect_cov(
    "import in the other tier does not count",
    "held",
    "checks red",
    plan_job="terraform plan (runbooks dev-tier)",
)
expect_cov(
    "coverage run still running does not count", "held", "checks red", drift_status="in_progress"
)
expect_cov("gh error reading logs holds", "held", "checks red", boom=True)
expect_cov(
    "another red check still holds and is the only one named",
    "held",
    "checks red: ci/lint",
    check={
        "checks": {
            "green": False,
            "red": ["ci/lint", "terraform-drift/coverage (platform)"],
            "pending": [],
            "destroy_guard_only": False,
        }
    },
)
expect_cov(
    "covered coverage plus a policy rule is a policy hold",
    "held",
    "needs me: plan-destroy",
    check=dict(COV_CHECK, escalate=True, escalations=[{"rule": "plan-destroy"}]),
)
ok = own.cheap_gate(pr(statusCheckRollup=COV_RED), CFG)[0] is None
fails += not ok
print(f"{'OK  ' if ok else 'FAIL'} cheap gate passes a coverage red on to the deep check")
COV.clear()
STATE["comments"] = [review_comment("findings", {"blocking": 0, "high": 0})]
STATE["check"] = COV_CHECK
eng.gh = cov_gh
rec = {}
own.evaluate(pr(statusCheckRollup=COV_RED), CFG, POL, rec, force=True)
eng.gh = fake_gh
STATE["check"] = {}
ok = rec.get("import_covered") == ["terraform-drift/coverage (platform)"]
fails += not ok
print(
    f"{'OK  ' if ok else 'FAIL'} lane state records the covered coverage check for the Ops Center"
)


# ---------------------------------------------------------------- pipeline v2
STATE.update(runs=[], jobs={}, logs={}, diffs={})
DESTROY_PLAN = {
    "ran": True,
    "destroy": 2,
    "destroyed": ['azurerm_role_assignment.app-e["a"]', "azurerm_storage_management_policy.state"],
    "roots": [{"job": "terraform plan (pipeline-identities platform)", "guard_only": True}],
}
DESTROY_CHECK = {
    "escalate": True,
    "escalations": [{"rule": "plan-destroy"}],
    "plan": DESTROY_PLAN,
    "checks": {
        "green": False,
        "red": ["terraform-ci/terraform plan (pipeline-identities platform)"],
        "pending": [],
        "destroy_guard_only": True,
    },
}
OTHER_265 = pr(number=265, headRefOid="c" * 40)
OTHER_267 = pr(number=267, headRefOid="d" * 40)
DIFF_265 = '+resource "azurerm_role_assignment" "app-e" {\n+  for_each = local.g\n'
DIFF_267 = '+resource "azurerm_storage_management_policy" "state" {\n'


def expect_v2(name, p, status, contains="", check=None, mine=None, diffs=None):
    global fails
    STATE["comments"] = [review_comment("clean", {"blocking": 0, "high": 0})]
    STATE["check"] = check or {}
    STATE["diffs"] = diffs or {}
    own.DIFFS.clear()
    FREEZE.write_text(json.dumps({"timezone": "America/New_York", "windows": []}))
    got, reason, _ = own.evaluate(p, CFG, POL, {}, force=True, mine=mine)
    good = got == status and contains.lower() in reason.lower()
    fails += not good
    print(f"{'OK  ' if good else 'FAIL'} v2 {name}: {got} ({reason})")


me = pr(number=901)
# a PR that changes a root the guard failed on (or a module it sources) waits on the PRs that
# declare the destroys. A PR that leaves that root alone is let past the guard (no "waits on" for it).
ROOT_DIFF = "diff --git a/infrastructure/terraform/pipeline-identities/main.tf b/infrastructure/terraform/pipeline-identities/main.tf\n+x\n"
# core-rule: pr-review-and-merge.1.16
expect_v2(
    "destroys only other open PRs declare wait on them (this PR changes the root)",
    me,
    "held",
    "waits on #265, #267",
    check=DESTROY_CHECK,
    mine=[me, OTHER_265, OTHER_267],
    diffs={901: ROOT_DIFF, 265: DIFF_265, 267: DIFF_267},
)
expect_v2(
    "destroys only other open PRs declare, root not in this PR: past the guard (improvement-id)",
    me,
    "ready",
    "belong to #265, #267, root not in this PR",
    check=dict(DESTROY_CHECK, escalate=False, escalations=[]),
    mine=[me, OTHER_265, OTHER_267],
    diffs={901: "+x\n", 265: DIFF_265, 267: DIFF_267},
)
expect_v2(
    "a destroy this PR removes stays the owner's sign-off",
    me,
    "held",
    "needs me: plan-destroy",
    check=DESTROY_CHECK,
    mine=[me, OTHER_265, OTHER_267],
    diffs={
        901: '-resource "azurerm_storage_management_policy" "state" {\n',
        265: DIFF_265,
        267: DIFF_267,
    },
)
# core-rule: pr-review-and-merge.1.16
expect_v2(
    "an unattributed destroy stays the owner's sign-off",
    me,
    "held",
    "needs me: plan-destroy",
    check=DESTROY_CHECK,
    mine=[me, OTHER_265],
    diffs={901: "", 265: DIFF_265},
)
expect_v2(
    "no other open PRs: sign-off",
    me,
    "held",
    "needs me: plan-destroy",
    check=DESTROY_CHECK,
    mine=[me],
)
real_gh = eng.gh


def boom_diff(args, timeout=60, raw=False):
    if args[:2] == ["pr", "diff"]:
        raise eng.GhError("pr diff: rc=1 boom")
    return real_gh(args, timeout, raw)


eng.gh = boom_diff
# core-rule: pr-review-and-merge.1.16
expect_v2(
    "diff read failure keeps the sign-off (fail closed)",
    me,
    "held",
    "needs me: plan-destroy",
    check=DESTROY_CHECK,
    mine=[me, OTHER_265, OTHER_267],
)
eng.gh = real_gh
ok = (
    own._addr_key('module.a.module.b.azurerm_x.y["k"]') == ("azurerm_x", "y")
    and own._addr_key("data.azurerm_client_config.c") is None
)
fails += not ok
print(f"{'OK  ' if ok else 'FAIL'} v2 address key strips modules and keys, skips data")

# Composite for_each keys (app|verb) count as declared by the PR that declares the app token
AVD_OPS = [
    f'azurerm_api_management_api_operation.all["avd|{v}"]'
    for v in ("DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT")
]
AVD_DESTROYS = AVD_OPS + [
    'azurerm_api_management_api.app["avd"]',
    'azurerm_api_management_api_policy.gateway["avd"]',
    'random_password.app_secret["avd-github-token-key"]',
    'app_secret_vendor["avd-github-app-client-secret"]',
]
AVD_DIFF = '+  "avd-github-token-key" = {}\n+  "avd-github-app-client-secret" = {}\n+  "avd": { "path": "avd" }\n'
FD_ME = pr(number=498, headRefOid="e" * 40)
FD_485 = pr(number=485, headRefOid="f" * 40)
real_pr_diff = own._pr_diff


def fd_case(name, destroyed, diffs, want, others=None):
    global fails
    own._pr_diff = lambda repo, n, sha: diffs.get(n, "")
    try:
        got = own.foreign_destroys(POL, FD_ME, destroyed, others or [FD_ME, FD_485])
    finally:
        own._pr_diff = real_pr_diff
    good = got == want
    fails += not good
    print(f"{'OK  ' if good else 'FAIL'} foreign destroys {name}: {got}")


fd_case(
    "composite keys follow the app token (#498 and #485)",
    AVD_DESTROYS,
    {498: "+x\n", 485: AVD_DIFF},
    [485],
)
fd_case(
    "a composite key whose app is not declared stays unattributed",
    AVD_OPS,
    {498: "+x\n", 485: '+  "other": {}\n'},
    [],
)
fd_case(
    "one undeclared address in the mix keeps the hold",
    AVD_DESTROYS + ['azurerm_api_management_api.app["zzz"]'],
    {498: "+x\n", 485: AVD_DIFF},
    [],
)
fd_case(
    "a longer name does not match the first segment",
    ['x.y["avd|GET"]'],
    {498: "+x\n", 485: '+  "avd-other": {}\n'},
    [],
)
fd_case("an empty first segment never matches", ['x.y["|GET"]'], {498: "+x\n", 485: "+  GET\n"}, [])
fd_case(
    "this PR declaring the app keeps the hold", AVD_DESTROYS, {498: AVD_DIFF, 485: AVD_DIFF}, []
)

# Sign-off from a decision card merges that exact head, never another head, never a delete
SIGN = own.SIGNOFF_FILE
SIGN.write_text(
    json.dumps({"prs": {"901": {"head": HEAD, "rules": ["ai-review-override", "github-dir"]}}})
)
pol_check = {"escalate": True, "escalations": [{"rule": "github-dir"}]}
expect_v2(
    "signed-off policy hold merges", me, "ready", "signed off by me", check=pol_check, mine=[me]
)
SIGN.write_text(json.dumps({"prs": {"901": {"head": "f" * 40, "rules": ["github-dir"]}}}))
expect_v2(
    "sign-off for another head does not count",
    me,
    "held",
    "needs me: github-dir",
    check=pol_check,
    mine=[me],
)
SIGN.write_text(json.dumps({"prs": {"901": {"head": HEAD, "rules": ["plan-destroy"]}}}))
expect_v2(
    "a plan-destroy sign-off never merges from the card",
    me,
    "held",
    "needs me: plan-destroy",
    check=DESTROY_CHECK,
    mine=[me],
)
SIGN.write_text(json.dumps({"prs": {"901": {"head": HEAD, "rules": ["github-dir"]}}}))
expect_v2(
    "partial sign-off does not merge",
    me,
    "held",
    "needs me",
    check={"escalate": True, "escalations": [{"rule": "github-dir"}, {"rule": "rbac-custom-role"}]},
    mine=[me],
)
SIGN.unlink()

# the delta check reads file contents through the gate module. A fresh gate module is built on every
# _tfgate() call, so patch the loader once here (no read ever reaches GitHub).
DFILES = {}
_orig_tfgate = eng._tfgate


def _dgh(args, timeout=60, raw=False):
    p = args[1] if len(args) > 1 else ""
    if "/contents/" in p and "?ref=" in p:
        path, sha = p.split("/contents/", 1)[1].split("?ref=")
        v = DFILES.get((path, sha), GhErrorT("api x: rc=1 gh: Not Found (HTTP 404)"))
        if isinstance(v, Exception):
            raise v
        return v
    if "/commits/" in p:
        return p.rsplit("/", 1)[1]
    raise GhErrorT("synthetic gh refusal: " + " ".join(args[:3]))


GhErrorT = eng.GhError


def _patched_tfgate():
    m = _orig_tfgate()
    m.gh = _dgh
    return m


eng._tfgate = _patched_tfgate

# one sign-off per PR carries to a later head that raises nothing new
so = eng._tfgate().load_signoff()
H2 = "b" * 40
GH_FP = {
    "rule": "github-dir",
    "where": ".github/x.yml",
    "fp": "e1",
    "cfp": "c1",
    "path": ".github/x.yml",
}
RB_FP = {"rule": "rbac-user-or-group", "where": "a.tf:3", "fp": "e2", "cfp": "c2", "path": "a.tf"}
GOOD_PLAN = {
    "ran": True,
    "status": "completed",
    "conclusion": "success",
    "add": 1,
    "change": 0,
    "destroy": 0,
    "replace": 0,
    "resources": [{"address": "azurerm_resource_group.a", "action": "create"}],
    "roots": [{"job": "terraform plan (a platform)", "conclusion": "success", "parsed": True}],
    "errors": [],
    "destroyed": [],
    "replaced": [],
}


def carry_case(
    name, status, contains, hits, plan=None, rec_hits=None, lane=None, rec_plan=None, sign=True
):
    global fails
    (TMP / "tfstate" / "pr-signoffs.json").unlink(missing_ok=True)
    if sign:
        so.record(
            901,
            HEAD if False else H2,
            lane or so.OWN,
            "approve_merge",
            rec_hits if rec_hits is not None else [GH_FP, RB_FP],
            rec_plan,
        )
    chk = {"escalate": True, "escalations": hits}
    if plan is not None:
        chk["plan"] = plan
    expect_v2(name, me, status, contains, check=chk, mine=[me])


carry_case(
    "signoff: same hits carry to a new head",
    "ready",
    "carried the owner's sign-off from bbbbbbbb",
    [GH_FP, RB_FP],
    GOOD_PLAN,
)
carry_case(
    "signoff: a subset of the signed hits carries",
    "ready",
    "carried the owner's sign-off",
    [GH_FP],
    GOOD_PLAN,
)
carry_case("signoff: no plan at all carries", "ready", "carried the owner's sign-off", [GH_FP])
carry_case(
    "signoff: a new rule re-asks",
    "held",
    "needs me: github-dir, rbac-custom-role",
    [GH_FP, {"rule": "rbac-custom-role", "where": "b.tf:1", "fp": "e9", "cfp": "c9"}],
    GOOD_PLAN,
)
carry_case(
    "signoff: same rule on changed content re-asks",
    "held",
    "needs me",
    [dict(GH_FP, fp="e1x", cfp="c1x")],
    GOOD_PLAN,
)
carry_case(
    "signoff: a hit with no fingerprint re-asks",
    "held",
    "needs me",
    [{"rule": "github-dir", "where": ".github/x.yml"}],
    GOOD_PLAN,
)
carry_case(
    "signoff: plan destroy re-asks",
    "held",
    "needs me",
    [GH_FP, {"rule": "plan-destroy", "where": "u"}],
    dict(
        GOOD_PLAN,
        destroy=1,
        destroyed=["azurerm_x.y"],
        resources=[{"address": "azurerm_x.y", "action": "destroy"}],
    ),
)
carry_case(
    "signoff: plan replace re-asks",
    "held",
    "needs me",
    [GH_FP],
    dict(
        GOOD_PLAN,
        replace=1,
        destroy=1,
        replaced=["azurerm_x.y"],
        destroyed=["azurerm_x.y"],
        resources=[{"address": "azurerm_x.y", "action": "replace"}],
    ),
)
carry_case(
    "signoff: a plan destroy with no named object re-asks",
    "held",
    "needs me",
    [GH_FP],
    dict(GOOD_PLAN, destroy=2),
)
GRANT = {"address": "azurerm_role_assignment.new", "action": "create"}
carry_case(
    "signoff: a new role assignment in the plan re-asks",
    "held",
    "needs me",
    [GH_FP],
    dict(GOOD_PLAN, resources=GOOD_PLAN["resources"] + [GRANT]),
)
carry_case(
    "signoff: a new Entra grant in the plan re-asks",
    "held",
    "needs me",
    [GH_FP],
    dict(
        GOOD_PLAN,
        resources=[{"address": 'module.m.azuread_app_role_assignment.g["x"]', "action": "create"}],
    ),
)
carry_case(
    "signoff: a grant the owner saw in the plan does not re-ask",
    "ready",
    "carried the owner's sign-off",
    [GH_FP],
    dict(GOOD_PLAN, resources=[GRANT]),
    rec_plan=so.plan_facts(dict(GOOD_PLAN, resources=[GRANT])),
)
carry_case(
    "signoff: a plan that is not final re-asks",
    "held",
    "needs me",
    [GH_FP],
    dict(GOOD_PLAN, status="in_progress"),
)
carry_case(
    "signoff: a plan with errors re-asks",
    "held",
    "needs me",
    [GH_FP],
    dict(GOOD_PLAN, errors=["boom"]),
)
carry_case(
    "signoff: no sign-off holds", "held", "needs me: github-dir", [GH_FP], GOOD_PLAN, sign=False
)
carry_case(
    "signoff: an engineer-lane sign-off never carries an own PR",
    "held",
    "needs me",
    [GH_FP],
    GOOD_PLAN,
    lane=so.ENGINEER,
)
(TMP / "tfstate" / "pr-signoffs.json").unlink(missing_ok=True)
so.record(
    901,
    H2,
    so.OWN,
    "plan_card",
    [
        {
            "reason": "changes .github/ (x): .github/x.yml",
            "fp": "g1",
            "cfp": "c1",
            "path": ".github/x.yml",
        }
    ],
    None,
)
expect_v2(
    "signoff: the plan card click covers the same .github file in the policy card",
    me,
    "ready",
    "carried the owner's sign-off",
    check={"escalate": True, "escalations": [GH_FP], "plan": GOOD_PLAN},
    mine=[me],
)
expect_v2(
    "signoff: the plan card click does not cover another rule",
    me,
    "held",
    "rbac-x",
    check={"escalate": True, "escalations": [GH_FP, dict(RB_FP, rule="rbac-x")]},
    mine=[me],
)
so.revoke(901, "test reject")
expect_v2(
    "signoff: a rejection revokes it",
    me,
    "held",
    "needs me",
    check={"escalate": True, "escalations": [GH_FP]},
    mine=[me],
)
# a new sign-off beats the held-head cache
(TMP / "tfstate" / "pr-signoffs.json").unlink(missing_ok=True)
rc = {
    "head": HEAD,
    "deep": "held",
    "policy_sha": POL["_sha"],
    "pr_updated": me.get("updatedAt"),
    "deep_epoch": 1.0,
    "reason": "needs me: github-dir",
}
so.record(901, H2, so.OWN, "approve_merge", [GH_FP], None)
STATE["comments"] = [review_comment("clean", {"blocking": 0, "high": 0})]
STATE["check"] = {"escalate": True, "escalations": [GH_FP]}
got, reason, _ = own.evaluate(me, CFG, POL, rc, force=False, mine=[me])
ok = got == "ready" and "carried" in reason
fails += not ok
print(f"{'OK  ' if ok else 'FAIL'} signoff newer than the cached hold re-checks: {got} ({reason})")
# tick merges a carried head and logs the distinct decision
(TMP / "own-pr-merge.json").unlink(missing_ok=True)
STATE.update(
    list=[pr(number=901)],
    calls=[],
    merge_ok=True,
    comments=[review_comment("clean", {"blocking": 0, "high": 0})],
    check={"escalate": True, "escalations": [GH_FP]},
)
own.tick()
dec = [
    json.loads(ln)
    for ln in (own.eng.STATE_DIR / "decisions.jsonl").read_text().splitlines()
    if ln.strip()
]
cd = [d for d in dec if d.get("decision") == "merged_carried_signoff" and d.get("pr") == 901]
ok = (
    len(cd) == 1
    and cd[0].get("carried_from") == H2
    and [c[2] for c in STATE["calls"] if c[:2] == ["pr", "merge"]] == ["901"]
)
fails += not ok
print(
    f"{'OK  ' if ok else 'FAIL'} tick merges a carried head with the distinct decision name: {cd}"
)
(TMP / "tfstate" / "pr-signoffs.json").unlink(missing_ok=True)

# a .github file the sign-off does not cover by content is covered when its delta is plain
SPATH = ".github/scripts/s.py"
S_OLD = "import os\n\ndef f():\n    return 1\n"
S_NEW = "import os\nimport sys\n\ndef f():\n    return len(sys.argv)\n"
S_SIGNED = {"rule": "github-dir", "where": SPATH, "fp": "s1", "cfp": "sc1", "path": SPATH}
S_HIT = {"rule": "github-dir", "where": SPATH, "fp": "s2", "cfp": "sc2", "path": SPATH}


def dcase(
    name, status, contains, hits, old, new, plan=GOOD_PLAN, lane=None, sign=True, rec_plan=None
):
    DFILES.clear()
    DFILES[(SPATH, H2)] = old
    DFILES[(SPATH, HEAD)] = new
    carry_case(
        name,
        status,
        contains,
        hits,
        plan,
        rec_hits=[S_SIGNED],
        lane=lane,
        sign=sign,
        rec_plan=rec_plan,
    )


dcase(
    "delta: plain script change carries the sign-off",
    "ready",
    "no sensitive change in .github/scripts/s.py",
    [S_HIT],
    S_OLD,
    S_NEW,
)
dcase(
    "delta: the covered hits and a plain delta together carry",
    "ready",
    "carried the owner's sign-off",
    [S_SIGNED, S_HIT],
    S_OLD,
    S_NEW,
)
for what, line in (
    ("permissions", "permissions: write-all"),
    ("id-token", "id-token: write"),
    ("a secrets reference", "TOKEN: ${{ secrets.X }}"),
    ("an environment key", "environment: terraform-plan"),
):
    dcase(
        "delta: adding %s re-asks" % what,  # noqa: UP031
        "held",
        "needs me: github-dir",
        [S_HIT],
        S_OLD,
        S_NEW + line + "\n",
    )
dcase(
    "delta: removing a sensitive line re-asks",
    "held",
    "needs me",
    [S_HIT],
    S_OLD + "permissions: read\n",
    S_NEW,
)
dcase(
    "delta: a CODEOWNERS hit never carries on a delta",
    "held",
    "needs me",
    [dict(S_HIT, where=".github/CODEOWNERS", path=".github/CODEOWNERS")],
    S_OLD,
    S_NEW,
)
dcase(
    "delta: a plain .github hit next to an uncovered rbac hit re-asks",
    "held",
    "needs me",
    [S_HIT, dict(RB_FP, fp="e7", cfp="c7")],
    S_OLD,
    S_NEW,
)
dcase(
    "delta: a hit with no fingerprint re-asks",
    "held",
    "needs me",
    [dict(S_HIT, fp=None, cfp=None)],
    S_OLD,
    S_NEW,
)
dcase(
    "delta: the plan guard stays (a destroy re-asks)",
    "held",
    "needs me",
    [S_HIT],
    S_OLD,
    S_NEW,
    plan=dict(
        GOOD_PLAN,
        destroy=1,
        destroyed=["azurerm_x.y"],
        resources=[{"address": "azurerm_x.y", "action": "destroy"}],
    ),
)
dcase(
    "delta: a read error re-asks",
    "held",
    "needs me",
    [S_HIT],
    S_OLD,
    GhErrorT("api x: rc=1 HTTP 502"),
)
dcase("delta: no sign-off holds", "held", "needs me", [S_HIT], S_OLD, S_NEW, sign=False)
dcase(
    "delta: an engineer-lane sign-off never carries",
    "held",
    "needs me",
    [S_HIT],
    S_OLD,
    S_NEW,
    lane=so.ENGINEER,
)
dcase(
    "delta: a new workflow file re-asks",
    "held",
    "needs me",
    [dict(S_HIT, where=".github/workflows/n.yml", path=".github/workflows/n.yml")],
    S_OLD,
    S_NEW,
)
# tick merges it and logs the distinct decision
DFILES.clear()
DFILES[(SPATH, H2)] = S_OLD
DFILES[(SPATH, HEAD)] = S_NEW
(TMP / "tfstate" / "pr-signoffs.json").unlink(missing_ok=True)
so.record(901, H2, so.OWN, "approve_merge", [S_SIGNED], None)
(TMP / "own-pr-merge.json").unlink(missing_ok=True)
STATE.update(
    list=[pr(number=901)],
    calls=[],
    merge_ok=True,
    comments=[review_comment("clean", {"blocking": 0, "high": 0})],
    check={"escalate": True, "escalations": [S_HIT], "plan": GOOD_PLAN},
)
own.tick()
dec = [
    json.loads(ln)
    for ln in (own.eng.STATE_DIR / "decisions.jsonl").read_text().splitlines()
    if ln.strip()
]
cd = [d for d in dec if d.get("decision") == "merged_carried_delta" and d.get("pr") == 901]
ok = (
    len(cd) == 1
    and cd[0].get("carried_from") == H2
    and cd[0].get("delta_paths") == [SPATH]
    and [c[2] for c in STATE["calls"] if c[:2] == ["pr", "merge"]] == ["901"]
)
fails += not ok
print(
    f"{'OK  ' if ok else 'FAIL'} tick merges a delta-carried head with merged_carried_delta: {cd}"
)
(TMP / "tfstate" / "pr-signoffs.json").unlink(missing_ok=True)

# Infrastructure noise: failed jobs re-run (failed only), no fix session, bounded per head
os.environ["OWNPR_FIX_SPAWN"] = "record"
(TMP / "own-pr-merge.json").unlink(missing_ok=True)
NOISE_LOG = "2026-10-13T10:00:00Z Error response from daemon: toomanyrequests: You have reached your pull rate limit\n"
REAL_LOG = "2026-10-13T10:00:00Z FAIL src/a.test.js\n2026-10-13T10:00:01Z AssertionError: expected 1 to be 2\n"
STATE.update(
    list=[pr(number=920, statusCheckRollup=lint_red)],
    check={},
    calls=[],
    comments=[review_comment("clean", {"blocking": 0, "high": 0})],
    runs=[
        {
            "id": 5,
            "path": ".github/workflows/ci.yml",
            "status": "completed",
            "conclusion": "failure",
            "created_at": "2026-10-13T10:00:00Z",
        }
    ],
    jobs={5: [{"id": 51, "name": "lint / typecheck / test / build", "conclusion": "failure"}]},
    logs={51: NOISE_LOG},
)
own.tick()
st = json.loads((TMP / "own-pr-merge.json").read_text())
reruns = [c for c in STATE["calls"] if c[:2] == ["run", "rerun"]]
ok = (
    st["prs"]["920"]["status"] == "waiting"
    and "infrastructure noise" in st["prs"]["920"]["reason"]
    and reruns == [["run", "rerun", "5", "--failed", "-R", POL["repo"]]]
    and not st.get("fix", {}).get("920", {}).get("running")
)
fails += not ok
print(
    f"{'OK  ' if ok else 'FAIL'} v2 noise: failed jobs re-run, no fix session ({st['prs']['920'].get('reason')})"
)
own.tick()
own.tick()
st = json.loads((TMP / "own-pr-merge.json").read_text())
reruns = [c for c in STATE["calls"] if c[:2] == ["run", "rerun"]]
run = st.get("fix", {}).get("920", {}).get("running") or {}
ok = len(reruns) == 2 and run.get("problem") == "red-checks"
fails += not ok
print(
    f"{'OK  ' if ok else 'FAIL'} v2 noise: retry budget 2 per head, then the fixer takes it ({len(reruns)} reruns, {run.get('problem')})"
)
(TMP / "own-pr-merge.json").unlink(missing_ok=True)
STATE.update(calls=[], logs={51: REAL_LOG})
own.tick()
st = json.loads((TMP / "own-pr-merge.json").read_text())
ok = (
    not [c for c in STATE["calls"] if c[:2] == ["run", "rerun"]]
    and (st.get("fix", {}).get("920", {}).get("running") or {}).get("problem") == "red-checks"
)
fails += not ok
print(f"{'OK  ' if ok else 'FAIL'} v2 real failure: no re-run, the fixer takes it")
STATE.update(runs=[], jobs={}, logs={}, diffs={})

# ---------------------------------------------------------------- merge-lane core rules (proofs)
eng.gh = fake_gh
eng.check = fake_check
eng.DRY_RUN = False
os.environ["OWNPR_FIX_SPAWN"] = "record"
CLEAN = review_comment("clean", {"blocking": 0, "high": 0})


def decisions():
    path = own.eng.STATE_DIR / "decisions.jsonl"
    return (
        [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]
        if path.exists()
        else []
    )


# core-rule: pr-review-and-merge.1.15
# The noise classifier: all-noise re-runs failed jobs only and logs the matched pattern name, a mix of noise and
# a real failure goes to the fixer, an unknown failure goes to the fixer, and the per-head cap bounds it.
NOISE_PR = pr(number=921, statusCheckRollup=lint_red)
FAILED_RUN = {
    "id": 5,
    "path": ".github/workflows/ci.yml",
    "status": "completed",
    "conclusion": "failure",
    "created_at": "2026-10-13T10:00:00Z",
}
RESET_LOG = "2026-10-13T10:00:00Z npm ERR! network ECONNRESET while fetching\n"
UNKNOWN_LOG = "2026-10-13T10:00:00Z something exploded and nobody has seen it before\n"


def noise_case(name, jobs, logs, want_rerun, rec=None, cfg=None, boom=False):
    global fails
    STATE.update(calls=[], runs=[FAILED_RUN], jobs={5: jobs}, logs=logs)
    rec = {} if rec is None else rec
    before = len(decisions())
    saved_gh = eng.gh
    if boom:

        def eng_boom(args, timeout=60, raw=False):
            if "/logs" in " ".join(args):
                raise eng.GhError("api logs: rc=1 HTTP 502")
            return saved_gh(args, timeout, raw)

        eng.gh = eng_boom
    try:
        got = own.noise_retry(POL, NOISE_PR, rec, cfg or CFG)
    finally:
        eng.gh = saved_gh
    reruns = [c for c in STATE["calls"] if c[:2] == ["run", "rerun"]]
    new = decisions()[before:]
    good = bool(got) == want_rerun and bool(reruns) == want_rerun and bool(new) == want_rerun
    if want_rerun:
        good = (
            good
            and reruns == [["run", "rerun", "5", "--failed", "-R", POL["repo"]]]
            and rec.get("noise_retries") == 1
        )
    fails += not good
    print(f"{'OK  ' if good else 'FAIL'} noise {name}: {got}")
    return new


J_NOISE = {"id": 51, "name": "lint / typecheck / test / build", "conclusion": "failure"}
J_REAL = {"id": 52, "name": "unit tests", "conclusion": "failure"}
new = noise_case("all noise re-runs the failed jobs only", [J_NOISE], {51: NOISE_LOG}, True)
logged = new[0] if new else {}
good = (
    logged.get("decision") == "noise-retry"
    and logged.get("sha") == HEAD
    and logged.get("attempt") == 1
    and "toomanyrequests" in logged.get("detail", "")
    and "lint / typecheck / test / build" in logged.get("detail", "")
)
fails += not good
print(
    f"{'OK  ' if good else 'FAIL'} noise: the matched pattern name is logged: {logged.get('detail')}"
)
new = noise_case(
    "a second named pattern is logged by its own name", [J_NOISE], {51: RESET_LOG}, True
)
good = bool(new) and "ECONNRESET" in new[0].get("detail", "")
fails += not good
print(f"{'OK  ' if good else 'FAIL'} noise: another pattern is logged by name")
noise_case(
    "mixed noise and a real failure goes to the fixer",
    [J_NOISE, J_REAL],
    {51: NOISE_LOG, 52: REAL_LOG},
    False,
)
noise_case(
    "mixed with the real one first goes to the fixer",
    [J_REAL, J_NOISE],
    {51: NOISE_LOG, 52: REAL_LOG},
    False,
)
noise_case("a failure with no known pattern goes to the fixer", [J_NOISE], {51: UNKNOWN_LOG}, False)
noise_case(
    "a log that cannot be read goes to the fixer", [J_NOISE], {51: NOISE_LOG}, False, boom=True
)
noise_case(
    "the per-head cap (default 2) is spent",
    [J_NOISE],
    {51: NOISE_LOG},
    False,
    rec={"noise_retries": 2},
)
noise_case(
    "a lower cap from the policy parameter is honoured",
    [J_NOISE],
    {51: NOISE_LOG},
    False,
    rec={"noise_retries": 1},
    cfg=dict(CFG, max_noise_retries=1),
)
noise_case(
    "the first retry under a cap of 2 runs",
    [J_NOISE],
    {51: NOISE_LOG},
    True,
    rec={"noise_retries": 0},
    cfg=dict(CFG, max_noise_retries=2),
)
ok = own.DEFAULTS["max_noise_retries"] == 2
fails += not ok
print(f"{'OK  ' if ok else 'FAIL'} noise: the default cap is 2 per head")
STATE.update(runs=[], jobs={}, logs={}, calls=[])

# core-rule: pr-review-and-merge.1.16
# Re-arm: the lane holds an attributed delete as "waits on #n" (never "needs me", so never a delete sign-off),
# the fixer records the wait quietly and rebases the same head once every PR it waits on has merged.
fx = own.fixer
saved_fx = (fx.pr_state, fx.push_files)
fx_states = {265: "OPEN", 267: "OPEN"}
fx.pr_state = lambda repo, n: fx_states.get(int(n))
fx.push_files = lambda repo, old, new: ["apps/x/src/a.ts"]
me = pr(number=901)
STATE["list"] = []  # list_open_all falls back to the PRs passed in as mine
STATE["comments"] = [CLEAN]
STATE["check"] = DESTROY_CHECK
STATE["diffs"] = {901: ROOT_DIFF, 265: DIFF_265, 267: DIFF_267}
own.DIFFS.clear()
w_status, w_reason, _ = own.evaluate(me, CFG, POL, {}, force=True, mine=[me, OTHER_265, OTHER_267])
ok = (
    w_status == "held"
    and w_reason.startswith("waits on #265, #267")
    and not w_reason.startswith("needs me")
)
fails += not ok
print(
    f"{'OK  ' if ok else 'FAIL'} 1.16 an attributed delete waits and is never a sign-off: {w_reason[:60]}"
)
(TMP / "rearm").mkdir(exist_ok=True)
frec = {}
rearm_now = dt.datetime(2026, 10, 27, 12, 0, 0, tzinfo=dt.timezone.utc)


def consider16(reason, minutes):
    return fx.consider(
        "prod",
        own.TAG,
        POL["repo"],
        POL["self_login"],
        me,
        "held",
        reason,
        frec,
        CFG,
        TMP / "rearm",
        rearm_now + dt.timedelta(minutes=minutes),
    )


consider16(w_reason, 0)
ok = frec.get("gave_up", {}).get("waits_on") == [265, 267] and "running" not in frec
fails += not ok
print(f"{'OK  ' if ok else 'FAIL'} 1.16 while they are open: recorded as a wait, no fix session")
fx_states[265] = "MERGED"
consider16(w_reason, 3)
ok = "running" not in frec
fails += not ok
print(f"{'OK  ' if ok else 'FAIL'} 1.16 one of two merged: still waiting")
fx_states[267] = "MERGED"
consider16("needs me: plan-destroy", 6)
ok = (frec.get("running") or {}).get("problem") == "rebase-on-main" and (
    frec.get("running") or {}
).get("head") == HEAD
fails += not ok
print(f"{'OK  ' if ok else 'FAIL'} 1.16 both merged: the same head re-arms as a rebase on main")
fx.pr_state, fx.push_files = saved_fx
STATE["diffs"] = {}

# core-rule: automation-safety.8
# The own-PR lane bypasses the approval count and nothing else. tick() is the whole lane: it merges with the
# maintainer bypass (--admin) pinned to the head, logs it, and leaves every other state unmerged.
LANE_FREEZE = [
    {
        "id": "lane-freeze",
        "start": (FREEZE_NOW - dt.timedelta(hours=1)).isoformat(timespec="seconds"),
        "end": (FREEZE_NOW + dt.timedelta(hours=1)).isoformat(timespec="seconds"),
    }
]
PENDING = GREEN + [
    {
        "name": "unit tests",
        "workflowName": "CI",
        "conclusion": "",
        "status": "IN_PROGRESS",
        "startedAt": "2026-10-09T10:02:00Z",
    }
]


def lane_tick(prs, check=None, freeze=None, switch=True):
    (TMP / "own-pr-merge.json").unlink(missing_ok=True)
    FREEZE.write_text(json.dumps({"timezone": "America/New_York", "windows": freeze or []}))
    real_policy = eng.policy
    if not switch:

        def policy_off():
            pol = real_policy()
            return dict(pol, own_pr_merge=dict(pol.get("own_pr_merge") or {}, enabled=False))

        eng.policy = policy_off
    STATE.update(
        list=prs,
        comments=[CLEAN],
        check=check or {},
        calls=[],
        merge_ok=True,
        runs=[],
        jobs={},
        logs={},
    )
    own.DIFFS.clear()
    try:
        own.tick()
    finally:
        eng.policy = real_policy
    return [c for c in STATE["calls"] if c[:2] == ["pr", "merge"]]


before = len(decisions())
merges = lane_tick([pr(number=930)])
logged = [d for d in decisions()[before:] if d.get("pr") == 930 and d.get("decision") == "merged"]
ok = (
    len(merges) == 1
    and merges[0][2] == "930"
    and "--admin" in merges[0]
    and merges[0][merges[0].index("--match-head-commit") + 1] == HEAD
    and len(logged) == 1
    and logged[0].get("lane") == "own-pr"
    and logged[0].get("sha") == HEAD
    and "all checks green" in logged[0].get("detail", "")
)
fails += not ok
print(
    f"{'OK  ' if ok else 'FAIL'} 8 switch on, green PR, no hold: merges and logs it: {merges} {logged}"
)
refusals = [
    ("a red check", [pr(number=931, statusCheckRollup=lint_red)], None, None),
    ("a pending check", [pr(number=932, statusCheckRollup=PENDING)], None, None),
    ("a hold label", [pr(number=933, labels=[{"name": "hold"}])], None, None),
    ("a do-not-merge label", [pr(number=934, labels=[{"name": "do-not-merge"}])], None, None),
    (
        "a firing escalation",
        [pr(number=935)],
        {"escalate": True, "escalations": [{"rule": "rbac-user-or-group"}]},
        None,
    ),
    ("a change freeze", [pr(number=936)], None, LANE_FREEZE),
    ("another author", [pr(number=937, author={"login": "account"})], None, None),
]
for what, prs_, chk, frz in refusals:
    before = len(decisions())
    merges = lane_tick(prs_, check=chk, freeze=frz)
    logged = [
        d for d in decisions()[before:] if d.get("decision") in ("merged", "merged_carried_signoff")
    ]
    ok = merges == [] and logged == []
    fails += not ok
    print(f"{'OK  ' if ok else 'FAIL'} 8 {what} leaves it unmerged: {merges}")
before = len(decisions())
merges = lane_tick([pr(number=938)], switch=False)
logged = [
    d for d in decisions()[before:] if d.get("decision") in ("merged", "merged_carried_signoff")
]
ok = merges == [] and logged == []
fails += not ok
print(f"{'OK  ' if ok else 'FAIL'} 8 switch off: a green PR does not merge: {merges}")
merges = lane_tick([pr(number=939)], switch=True)
ok = [m[2] for m in merges] == ["939"]
fails += not ok
print(f"{'OK  ' if ok else 'FAIL'} 8 switch back on: the same PR merges again: {merges}")
(TMP / "own-pr-merge.json").unlink(missing_ok=True)
STATE.update(list=[], calls=[], check={})


# the <team> target (own policy, inherited IaC rules, Vercel ignored, docs-only review skip)
ATMP = Path(tempfile.mkdtemp(prefix="ownpr-team-prefix-"))
saved = {k: os.environ.get(k) for k in ("OPRG_POLICY", "OPRG_STATE_DIR", "OPRG_CACHE_DIR")}
os.environ.update(
    OPRG_POLICY=str(STATE_ROOT / "secondary-review" / "own-pr-policy.json"),
    OPRG_STATE_DIR=str(ATMP),
    OPRG_CACHE_DIR=str(ATMP),
)
saved_argv = sys.argv
sys.argv = ["own_pr_merge.py", "tick", "--target", "secondary"]
spec_a = importlib.util.spec_from_file_location("own_ares", str(LANE_PY))
own_a = importlib.util.module_from_spec(spec_a)
spec_a.loader.exec_module(own_a)
sys.argv = saved_argv
own_a.eng.gh = fake_gh
own_a.eng.check = fake_check
POL_A = own_a.eng.policy()
CFG_A = own_a.config(POL_A)
rules = {r["id"] for r in POL_A["line_rules"]}
ok = (
    own_a.TAG == "[secondary the owner's PR]"
    and POL_A["repo"] == "owner/secondary-repo"
    and "rbac-user-or-group" in rules
    and len(POL_A["line_rules"]) == len(POL["line_rules"])
    and POL_A["_sha"] != own_a._engine_policy()["_sha"]
    and CFG_A["autofix"]["enabled"] is True
)
fails += not ok
print(
    f"{'OK  ' if ok else 'FAIL'} team target: tag, repo, {len(POL_A['line_rules'])} inherited line rules, own sha"
)
ARES_GREEN = [
    {
        "name": "python",
        "workflowName": "ci",
        "conclusion": "SUCCESS",
        "status": "COMPLETED",
        "startedAt": "2026-10-09T10:00:00Z",
    },
    {
        "name": "ai-review result",
        "workflowName": "team PR Review",
        "conclusion": "SUCCESS",
        "status": "COMPLETED",
        "startedAt": "2026-10-09T10:00:00Z",
    },
]
SKIPPED = ARES_GREEN + [
    {
        "name": "review",
        "workflowName": "team PR Review",
        "conclusion": "SKIPPED",
        "status": "COMPLETED",
        "startedAt": "2026-10-09T10:00:00Z",
    }
]
VERCEL_RED = ARES_GREEN + [
    {
        "name": "Vercel",
        "workflowName": "",
        "context": "Vercel",
        "conclusion": "FAILURE",
        "status": "COMPLETED",
        "startedAt": "2026-10-09T10:00:00Z",
    }
]


def expect_a(name, p, status, contains="", comments=None):
    global fails
    STATE["comments"] = (
        comments if comments is not None else [review_comment("clean", {"blocking": 0, "high": 0})]
    )
    STATE["check"] = {}
    got, reason, _ = own_a.evaluate(p, CFG_A, POL_A, {}, force=True)
    good = got == status and contains.lower() in reason.lower()
    fails += not good
    print(f"{'OK  ' if good else 'FAIL'} team {name}: {got} ({reason})")


expect_a("clean merges", pr(statusCheckRollup=ARES_GREEN), "ready")
expect_a(
    "docs-only review skipped counts as clean", pr(statusCheckRollup=SKIPPED), "ready", comments=[]
)
expect_a(
    "no review and not skipped waits for the verdict",
    pr(statusCheckRollup=ARES_GREEN),
    "held",
    "no PR review verdict",
    comments=[],
)
expect_a("Vercel red is ignored", pr(statusCheckRollup=VERCEL_RED), "ready")
ci_red = ARES_GREEN + [
    {
        "name": "powershell",
        "workflowName": "ci",
        "conclusion": "FAILURE",
        "status": "COMPLETED",
        "startedAt": "2026-10-09T10:01:00Z",
    }
]
expect_a("ci red held", pr(statusCheckRollup=ci_red), "held", "checks red")
for k, v in saved.items():
    if v is None:
        os.environ.pop(k, None)
    else:
        os.environ[k] = v

print("FAILURES:", fails)
sys.exit(1 if fails else 0)
