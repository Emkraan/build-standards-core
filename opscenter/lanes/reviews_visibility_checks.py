#!/usr/bin/env python3
# Synthetic tests for reviews_visibility.py. Fake ops center bundles, fake GitHub, fake lane
# check, temp lane state and a temp Action Center store. Never touches real items, GitHub or the
# ops center.
import copy
import fcntl
import json
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="rvtest-"))
os.environ["OPSCENTER_ROOT"] = str(TMP)
os.environ["RV_STATE"] = str(TMP / "rv/state.json")
os.environ["RV_LOCK"] = str(TMP / "rv/check.lock")
os.environ["RV_LANES"] = json.dumps(
    {
        "primary": {"repo": "owner/primary", "own_state": str(TMP / "oly/own-pr-merge.json")},
        "secondary": {"repo": "owner/secondary", "own_state": str(TMP / "team/own-pr-merge.json")},
    }
)
os.environ["RV_OWNER_STATUS"] = str(TMP / "owner/status.json")
os.environ["RV_NO_REFRESH"] = "1"
os.environ["RV_BASE"] = "http://127.0.0.1:1"  # never reached, fetch is faked
sys.path.insert(0, str(Path(__file__).parent))
import reviews_visibility as cv  # noqa: E402

T0 = 1792100000.0  # synthetic clock
H336 = "763f4506c9f7b1696beb279d99df8b15e097b9b2"
HA = "a" * 40


def iso(e):
    import datetime as dt

    return dt.datetime.fromtimestamp(e, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write(p, data):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data))


def empty_oly():
    return {
        "my_prs": [],
        "my_prs_error": None,
        "my_prs_refreshed": T0 - 30,
        "needs_me": [],
        "needs_in_flight": [],
        "in_progress": [],
        "shipped": [],
        "privileged": [],
        "owner_roots": {"items": []},
        "runbook_releases": [],
        "runbook_releases_error": None,
        "acted": [],
    }


def empty_ares():
    return {"needs_me": [], "in_progress": [], "shipped": [], "acted": [], "lane_error": None}


W = {
    "oly": empty_oly(),
    "team": empty_ares(),
    "fail_fetch": False,
    "fail_gh": False,
    "oly_prs": [],
    "ares_prs": [],
    "runs": [],
    "live": {},
}


def fake_fetch(path, timeout=120):
    if W["fail_fetch"]:
        raise cv.ReadError("synthetic outage")
    return copy.deepcopy(W["oly"] if "platform" in path else W["team"])


def fake_gh_json(args, timeout=120):
    if W["fail_gh"]:
        raise cv.ReadError("synthetic gh outage")
    if args[:2] == ["pr", "list"]:
        return copy.deepcopy(W["oly_prs"] if args[3] == cv.REPOS["primary"] else W["ares_prs"])
    if args[0] == "api" and "status=waiting" in args[1]:
        return {"workflow_runs": [r for r, _ in W["runs"]]}
    if args[0] == "api" and args[1].endswith("/pending_deployments"):
        rid = args[1].split("/runs/")[1].split("/")[0]
        return next(p for r, p in W["runs"] if str(r["id"]) == rid)
    raise AssertionError(args)


cv.fetch = fake_fetch
cv.gh_json = fake_gh_json
cv.live_lane = lambda repo, n: W["live"].get((repo, n))


def items():
    p = TMP / "state/dashboard/automation-actions.json"
    return json.loads(p.read_text())["items"] if p.exists() else {}


def open_items():
    return {k: v for k, v in items().items() if not v.get("closed")}


def by_title(sub):
    return [v for v in open_items().values() if sub in v["title"]]


fails = 0


def check(name, cond):
    global fails
    print(("OK   " if cond else "FAIL ") + name)
    fails += 0 if cond else 1


def go(dt_s=0, dry=False):
    os.environ["RV_NOW"] = str(T0 + dt_s)
    return cv.run(dry=dry)


def reset():
    W.update(
        oly=empty_oly(),
        secondary=empty_ares(),
        fail_fetch=False,
        fail_gh=False,
        oly_prs=[],
        ares_prs=[],
        runs=[],
        live={},
    )
    for p in (TMP / "state", TMP / "rv", TMP / "oly", TMP / "team", TMP / "owner"):
        if p.exists():
            for f in sorted(p.rglob("*"), reverse=True):
                f.unlink() if f.is_file() else f.rmdir()


def pr(n, login, created, draft=False, bot=False, head=HA):
    return {
        "number": n,
        "title": f"synthetic {n}",
        "author": {"login": login, "is_bot": bot},
        "isDraft": draft,
        "headRefOid": head,
        "createdAt": iso(created),
    }


# 1. Incident #336: lane holds for github-dir and tfplan-matcher, card says waiting after an override choice.
reset()
W["oly_prs"] = [pr(336, "owner-login", T0 - 7200, head=H336)]
W["oly"]["my_prs"] = [
    {
        "pr": 336,
        "head_sha": H336,
        "pending": [],
        "waiting": [],
        "hold": {
            "kind": "waiting",
            "summary": 'You chose "Merge and split the identity next" for this head. The lane merges it '
            "once the review check turns green on the override.",
        },
    }
]
write(
    str(cv.OWN["primary"]),
    {
        "prs": {
            "336": {
                "head": H336,
                "status": "held",
                "reason": "needs me: github-dir, tfplan-matcher",
            }
        }
    },
)
write(
    TMP / "oly/own-pr-signoffs.json",
    {"prs": {"336": {"head": H336, "at": iso(T0 - 3600), "rules": ["ai-review-override"]}}},
)
rc = go()
hits = by_title("PR #336 waits on me")
check(
    "#336 contradiction raised high", rc == 0 and len(hits) == 1 and hits[0]["priority"] == "high"
)
check("#336 item names the lane reason", hits and "github-dir, tfplan-matcher" in hits[0]["why"])
check(
    "#336 owner and source set",
    hits and hits[0]["owner"] == "owner" and "visibility" in hits[0]["source"],
)
before = json.dumps(items())
go(60)
check("rerun with the same finding changes nothing", json.dumps(items()) == before)

# 2. Every rule signed off for this head: the lane merges it next pass, no contradiction.
write(
    TMP / "oly/own-pr-signoffs.json",
    {
        "prs": {
            "336": {
                "head": H336,
                "at": iso(T0),
                "rules": ["ai-review-override", "github-dir", "tfplan-matcher"],
            }
        }
    },
)
go(120)
check("signed-off hold is legit waiting and the item closes", not by_title("PR #336 waits on me"))
check("closed item records a reason", any(v.get("closed") for v in items().values()))

# 3. Live lane check says the head is no longer held: no contradiction.
write(TMP / "oly/own-pr-signoffs.json", {"prs": {}})
W["live"][("primary", 336)] = {"pr": 336, "head": H336, "status": "ready", "reason": "all green"}
go(180)
check("live check overrides a stale lane record", not by_title("PR #336 waits on me"))
W["live"] = {}
# Lane held needs me and card is policy: consistent.
W["oly"]["my_prs"][0]["hold"] = {"kind": "policy", "summary": "Everything passes."}
go(240)
check("policy card for a needs-me hold is fine", not open_items())
# Card says waiting while the lane holds it on a problem.
write(
    str(cv.OWN["primary"]),
    {"prs": {"336": {"head": H336, "status": "held", "reason": "checks red: deploy"}}},
)
W["oly"]["my_prs"][0]["hold"] = {"kind": "waiting", "summary": "Re-run pending."}
go(300)
check(
    "waiting card over a problem hold is a contradiction", len(by_title("PR #336 waits on me")) == 1
)
# Auto-fix gave up (direction) but card says problem.
write(
    str(cv.OWN["primary"]),
    {
        "prs": {"336": {"head": H336, "status": "held", "reason": "checks red: deploy"}},
        "fix": {"336": {"gave_up": {"head": H336, "why": "cannot fix", "at": iso(T0)}}},
    },
)
W["oly"]["my_prs"][0]["hold"] = {"kind": "problem", "summary": "Checks red."}
go(310)
hits = by_title("PR #336 waits on me")
check(
    "gave_up with a problem card is a contradiction",
    len(hits) == 1 and "auto-fix gave up" in hits[0]["why"],
)

# 4. Incident governance run 38799492695: assessment not written and no plan source for 30 minutes.
reset()
W["oly"]["privileged"] = [
    {
        "key": "governance:38799492695",
        "environment": "governance",
        "env_label": "Governance",
        "run_id": 38799492695,
        "run_attempt": 1,
        "run_url": "https://example.invalid/run",
        "plan_source": None,
        "phase": "in_flight",
        "blocked": "the assessment is still being written",
        "since": iso(T0 - 31 * 60),
    }
]
go()
stuck = [v for v in open_items().values() if "38799492695" in v["title"]]
check(
    "privileged incident raises two medium stuck items",
    len(stuck) == 2 and all(v["priority"] == "medium" for v in stuck),
)
W["oly"]["privileged"][0].update(since=iso(T0 - 5 * 60))
go(10)
check("a fresh privileged item is not stuck yet", not open_items())

# 5. Invisible open PR of mine, and a brand new one the list has not picked up.
reset()
W["oly_prs"] = [pr(400, "owner-login", T0 - 3600), pr(401, "owner-login", T0 - 60)]
W["oly"]["my_prs_refreshed"] = T0 - 120
go()
check(
    "old PR of mine missing from The owner's PRs is invisible high",
    len(by_title("PR #400 of mine")) == 1 and by_title("PR #400 of mine")[0]["priority"] == "high",
)
check("PR created after the list was built is not flagged", not by_title("#401"))
W["oly"]["acted"] = [{"pr": 400, "outcome": "merged"}]
go(30)
check("a tombstoned PR counts as visible and the item closes", not by_title("PR #400 of mine"))

# 6. Engineer PRs: invisible medium, bots and drafts skipped, queued ones fine.
reset()
W["oly_prs"] = [
    pr(500, "alice", T0 - 3600),
    pr(501, "dependabot[bot]", T0 - 3600, bot=True),
    pr(502, "bob", T0 - 3600, draft=True),
    pr(503, "carol", T0 - 3600),
]
W["oly"]["in_progress"] = [{"pr": 503}]
go()
check(
    "engineer PR on no tab is invisible medium",
    len(by_title("#500")) == 1 and by_title("#500")[0]["priority"] == "medium",
)
check(
    "bots, drafts and queued PRs are not flagged",
    not by_title("#501") and not by_title("#502") and not by_title("#503"),
)

# 6b. engineer PRs held for the maintenance window are visible, and a hold that outlived a
# full window raises one medium stuck item.
reset()
W["oly_prs"] = [pr(520, "alice", T0 - 7200), pr(521, "bob", T0 - 7200)]
W["oly"]["held_for_window"] = [
    {
        "pr": 520,
        "head_sha": HA,
        "phase": "held",
        "title": "held fresh",
        "author": "alice",
        "held_at": iso(T0 - 3600),
        "window": {"class_label": "non-CCC", "stale": False},
    },
    {
        "pr": 521,
        "head_sha": HA,
        "phase": "held",
        "title": "held stale",
        "author": "bob",
        "held_at": iso(T0 - 90000),
        "last_check": "checks not green: red=['ci/test']" + chr(59) + " pending=[]",
        "window": {"class_label": "non-CCC", "stale": True},
    },
]
go()
check(
    "held PRs are on a tab (not invisible)",
    not [v for v in open_items().values() if v["title"].startswith("Engineer PR")],
)
check(
    "a hold past a full window is stuck medium",
    len(by_title("#521 is still held")) == 1
    and by_title("#521 is still held")[0]["priority"] == "medium"
    and not by_title("#520 is still held"),
)
check("stuck hold text has no semicolon", chr(59) not in by_title("#521 is still held")[0]["why"])
W["oly"]["held_for_window"] = W["oly"]["held_for_window"][:1]
W["oly"]["in_progress"] = [{"pr": 521}]
go(60)
check("the stuck hold closes once it merges or leaves the list", not by_title("#521 is still held"))

# 7. Waiting deployments.
reset()
run = {
    "id": 777,
    "name": "terraform-apply",
    "head_branch": "main",
    "run_attempt": 1,
    "html_url": "https://x.invalid",
    "updated_at": iso(T0 - 600),
    "created_at": iso(T0 - 900),
}
W["runs"] = [
    (run, [{"environment": {"name": "governance"}, "current_user_can_approve": True}]),
    (dict(run, id=778), [{"environment": {"name": "prod"}, "current_user_can_approve": False}]),
    (
        dict(run, id=779),
        [{"environment": {"name": "terraform-plan"}, "current_user_can_approve": True}],
    ),
]
W["oly"]["needs_me"] = [{"key": "tfplan-x", "tfplan": {"run_ids": [779]}}]
go()
check(
    "unplaced waiting deployment is invisible high",
    len(by_title("run 777")) == 1 and by_title("run 777")[0]["priority"] == "high",
)
check(
    "deployments the owner cannot approve or already placed are fine",
    not by_title("run 778") and not by_title("run 779"),
)
W["oly"]["privileged"] = [
    {
        "key": "governance:777",
        "run_id": 777,
        "plan_source": "log:x",
        "phase": "needs_me",
        "since": iso(T0),
    }
]
go(30)
check("placing the run closes the item", not by_title("run 777"))

# 7b. plan waits on the owner's parked draft show on its The owner's PRs row, not Needs me.
reset()
DH = "d" * 40
drun = dict(run, id=880, name="terraform-ci", head_branch="ticket-id-x", head_sha=DH)
W["runs"] = [
    (drun, [{"environment": {"name": "terraform-plan"}, "current_user_can_approve": True}]),
    (
        dict(drun, id=881),
        [{"environment": {"name": "governance"}, "current_user_can_approve": True}],
    ),
    (
        dict(drun, id=882, head_sha="e" * 40),
        [{"environment": {"name": "terraform-plan"}, "current_user_can_approve": True}],
    ),
]
W["oly"]["my_prs"] = [
    {
        "pr": 900,
        "draft": True,
        "head_sha": DH,
        "pending": [],
        "waiting": ["terraform plan (a dev-tier)"],
        "hold": {
            "kind": "problem",
            "parked": "nogate",
            "plan_line": "1 terraform check(s) wait on the plan gate.",
        },
    },
]
go()
check("parked draft plan wait is not flagged", not by_title("run 880"))
check("privileged env on a draft head still flagged", len(by_title("run 881")) == 1)
check("plan wait on another head still flagged", len(by_title("run 882")) == 1)
W["oly"]["my_prs"][0]["hold"].pop("plan_line")
go(30)
check("draft row without the plan line is flagged", len(by_title("run 880")) == 1)
W["oly"]["my_prs"][0]["hold"]["plan_line"] = "x"
W["oly"]["my_prs"][0]["draft"] = False
go(60)
check("plan wait on a ready PR off Needs me is flagged", len(by_title("run 880")) == 1)


# 8. Owner roots.
reset()
write(
    os.environ["RV_OWNER_STATUS"],
    {
        "items": {
            "state-backend:platform": {"state": "pending", "pending_since": iso(T0)},
            "pipeline-identities:platform": {"state": "clean"},
        }
    },
)
W["oly"]["owner_roots"] = {
    "items": [
        {"key": "state-backend:platform", "state": "pending", "phase": "idle"},
        {"key": "pipeline-identities:platform", "state": "clean", "phase": "idle"},
    ]
}
go()
check(
    "pending Owner root not on Needs me is invisible high",
    len(by_title("Owner root state-backend:platform")) == 1,
)
W["oly"]["owner_roots"]["items"][0].update(phase="needs_me")
go(30)
check("Owner root on Needs me clears", not open_items())
write(
    os.environ["RV_OWNER_STATUS"],
    {"items": {"state-backend:platform": {"state": "planning", "started": iso(T0 - 45 * 60)}}},
)
W["oly"]["owner_roots"]["items"][0].update(phase="in_flight", state="planning")
go(60)
check("Owner root planning for 45 minutes is stuck", len(by_title("has been planning")) == 1)

# 9. The owner's PR waiting with nothing running: stuck only after 30 minutes, then clears.
reset()
W["oly_prs"] = [pr(600, "owner-login", T0 - 7200)]
W["oly"]["my_prs"] = [
    {
        "pr": 600,
        "head_sha": HA,
        "pending": [],
        "waiting": [],
        "hold": {
            "kind": "waiting",
            "summary": "Everything passes. The lane merges it on its next pass.",
        },
    }
]
write(str(cv.OWN["primary"]), {"prs": {"600": {"head": HA, "status": "ready", "reason": "green"}}})
go()
check("first sighting of a waiting PR raises nothing", not open_items())
go(31 * 60)
check(
    "waiting with nothing running for 31 minutes is stuck medium",
    len(by_title("#600 has been")) == 1,
)
W["oly"]["my_prs"] = []
W["oly_prs"] = []
go(32 * 60)
check("the PR merging closes the stuck item", not open_items())
st = json.loads(Path(os.environ["RV_STATE"]).read_text())
check("first-seen times of cleared conditions are dropped", not st["seen"])

# 10. secondary: contradiction, invisible, ok.
reset()
W["ares_prs"] = [
    pr(80, "owner-login", T0 - 3600),
    pr(81, "dave", T0 - 3600),
    pr(82, "owner-login", T0 - 3600),
]
W["team"]["in_progress"] = [
    {
        "pr": 80,
        "mine": True,
        "head_sha": HA,
        "checks": {"pending": []},
        "state": 'you chose "x", the lane merges it once the review check turns green',
    }
]
W["team"]["needs_me"] = [{"pr": 82, "mine": True, "head_sha": HA, "kind": "signoff"}]
write(
    str(cv.OWN["secondary"]),
    {"prs": {"80": {"head": HA, "status": "held", "reason": "needs me: github-dir"}}},
)
go()
check("team hold in In progress is a contradiction", len(by_title("team PR #80 waits on me")) == 1)
check(
    "team PR on no tab is invisible medium for an engineer",
    len(by_title("team PR #81")) == 1 and by_title("team PR #81")[0]["priority"] == "medium",
)
check("team PR on Needs me is fine", not by_title("#82"))

# 11. GitHub outage keeps GitHub-dependent items open and counts failures.
W["fail_gh"] = True
go(60)
check(
    "GitHub outage does not close GitHub-dependent items",
    len(by_title("team PR #81")) == 1 and len(by_title("team PR #80")) == 1,
)
go(120)
go(180)
check(
    "three GitHub failures raise the cannot-read-GitHub item",
    "reviews-vis-cannot-read-github" in open_items(),
)
W["fail_gh"] = False
go(240)
check("GitHub back closes that item", "reviews-vis-cannot-read-github" not in open_items())

# 12. Ops Center outage: exit 2, item after three, closed on recovery.
reset()
W["fail_fetch"] = True
r1, r2 = go(), go(60)
check(
    "bundle failure exits 2 with no item before the third", r1 == 2 and r2 == 2 and not open_items()
)
r3 = go(120)
check(
    "third failure raises the cannot-read item",
    r3 == 2 and "reviews-vis-cannot-read" in open_items(),
)
W["fail_fetch"] = False
check(
    "recovery exits 0 and closes it", go(180) == 0 and "reviews-vis-cannot-read" not in open_items()
)

# 13. Dry run writes nothing.
reset()
W["oly_prs"] = [pr(400, "owner-login", T0 - 3600)]
go(dry=True)
check(
    "dry run writes no item and no state", not items() and not Path(os.environ["RV_STATE"]).exists()
)

# 14. Lock held: skip with exit 0.
Path(os.environ["RV_LOCK"]).parent.mkdir(parents=True, exist_ok=True)
with open(os.environ["RV_LOCK"], "w") as lk:
    fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
    check("a held lock skips the run", cv.main([]) == 0 and not items())

# 15. Every text written is ASCII with no em dash and no semicolon.
reset()
W["oly_prs"] = [
    pr(336, "owner-login", T0 - 7200, head=H336),
    pr(400, "owner-login", T0 - 3600),
    pr(500, "alice", T0 - 3600),
]
W["oly"]["my_prs"] = [
    {
        "pr": 336,
        "head_sha": H336,
        "pending": [],
        "waiting": [],
        "hold": {"kind": "waiting", "summary": "x"},
    }
]
write(
    str(cv.OWN["primary"]),
    {"prs": {"336": {"head": H336, "status": "held", "reason": "needs me: github-dir"}}},
)
W["oly"]["privileged"] = [
    {
        "key": "g:1",
        "run_id": 1,
        "plan_source": None,
        "phase": "in_flight",
        "blocked": "b",
        "since": iso(T0 - 3600),
    }
]
W["oly"]["runbook_releases_error"] = "boom"
go()
txt = json.dumps(items())
check(
    "item text is ASCII with no em dash or semicolon",
    len(open_items()) >= 5
    and txt.isascii()
    and chr(59) not in "".join(v["title"] + v["why"] + v["action"] for v in items().values()),
)

print("\n%d failure(s)" % fails)  # noqa: UP031
sys.exit(1 if fails else 0)
