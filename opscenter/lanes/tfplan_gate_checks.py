"""
tfplan_gate_test.py
Purpose: Synthetic checks for the plan gate (tfplan_gate.py): superseded runs are cancelled (never silently
         skipped), a stacked PR sharing a commit is not mistaken for the run's PR, the session branch
         match is exact, a working session never hides a held plan (it only adds a note to the card),
         the parallel run reads keep their order, approval carry forward, the one sign-off per PR, and
         the narrow rules for backend, the admin token root, .github/scripts/tests and the exclusions file.
         gh, assess_pr and park_reason are monkeypatched. Nothing reaches the code host.
Usage:   python3 tfplan_gate_test.py (also run by unittest through tfplan_gate_unittest.py)
"""

import datetime as dt
import json
import os
import sqlite3
import sys
import tempfile
import threading
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="tfgate-sup-", dir=os.environ.get("TMPDIR")))
os.environ["TFGATE_STATE_DIR"] = str(TMP / "state")
os.environ["TFGATE_CACHE_DIR"] = str(TMP / "cache")
os.environ["TFGATE_STATE_DB"] = str(TMP / "state.db")
os.environ.pop("TFGATE_DRY_RUN", None)
os.environ.pop("TFGATE_GH_BIN", None)
(TMP / "state").mkdir()
(TMP / "cache").mkdir()
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tfplan_gate as g  # noqa: E402

FAIL = []
OLD, NEW, OTHER = "a" * 40, "b" * 40, "c" * 40
W = {}
CALLS = []
CALLS_LOCK = threading.Lock()


def check(name, cond):
    print(("OK   " if cond else "FAIL ") + name)
    if not cond:
        FAIL.append(name)


def iso(age_s):
    return dt.datetime.fromtimestamp(g.NOW - age_s, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fake_gh(args, timeout=60, raw=False):
    with CALLS_LOCK:
        CALLS.append(args)
    if args[:3] == ["api", "-X", "POST"]:
        if W.get("cancel_fails") and args[3].endswith("/cancel"):
            raise g.GhError("HTTP 409 synthetic")
        return "" if raw else {}
    path = args[1]
    if "/compare/" in path:
        if W.get("compare_fails"):
            raise g.GhError("HTTP 502 synthetic")
        return W.get("compare", {"files": []})
    if "status=waiting" in path:
        return {"workflow_runs": W["runs"]}
    if path.endswith("/pending_deployments"):
        rid = int(path.split("/runs/")[1].split("/")[0])
        return (
            []
            if rid in W.get("not_plan", ())
            else [{"environment": {"name": "terraform-plan", "id": 5}}]
        )
    if "/commits/" in path and path.endswith("/pulls"):
        return W["commit_prs"].get(path.split("/commits/")[1].split("/")[0], [])
    if "/pulls?head=" in path:
        return []
    if "/pulls/" in path:
        return W["prs"][int(path.rsplit("/", 1)[1])]
    if "/actions/runs/" in path:
        return W["by_id"][int(path.rsplit("/", 1)[1])]
    raise AssertionError(args)


def pr(n, head, state="open", login="owner-login"):
    return {
        "number": n,
        "state": state,
        "head": {"sha": head, "ref": f"ticket-id-b{n}"},
        "user": {"login": login},
        "title": f"PR {n}",
        "html_url": f"https://x.invalid/{n}",
        "labels": [],
    }


def run(rid, sha, age_s=900, branch="ticket-id-b1", prs=None):
    return {
        "id": rid,
        "head_sha": sha,
        "head_branch": branch,
        "event": "pull_request",
        "path": ".github/workflows/terraform-drift.yml",
        "created_at": iso(age_s),
        "pull_requests": prs or [],
        "name": "terraform-drift",
        "status": "waiting",
    }


def decisions():
    p = TMP / "state/decisions.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def queue():
    return json.loads((TMP / "state/queue.json").read_text())


def posts():
    return [c[3] for c in CALLS if c[1] == "-X"]


def reset():
    CALLS.clear()
    W.clear()
    for f in (TMP / "state").glob("*"):
        f.unlink()


real_recent = g.recent_queue_runs
g.gh = fake_gh
real_detail = g.assess_pr_detail
g.assess_pr_detail = lambda n, sha=None, own=False: (
    ["x.tf"],
    W.get("hits") or [{"reason": "changes .github/: synthetic", "fp": None}],
)
g.recent_queue_runs = lambda known: []
g.park_reason = lambda p, s: W.get("park")

# 1. Run on the old head of a merged PR whose commit also sits in an open stacked PR (38911998598).
reset()
W.update(
    runs=[run(1, OLD, branch="ticket-id-b1-access")],
    commit_prs={OLD: [{"number": 348, "state": "closed"}, {"number": 350, "state": "open"}]},
    prs={348: pr(348, NEW, "closed"), 350: pr(350, OTHER)},
)
g.run_pass()
check(
    "superseded run on a stacked commit is cancelled",
    sum(p.endswith("/runs/1/cancel") for p in posts()) == 1,
)
check(
    "superseded cancel is logged",
    any(d.get("decision") == "cancelled_superseded" and d["run"] == 1 for d in decisions()),
)
check(
    "superseded run never lands on PR 350's card",
    not any(k.startswith("350@") for k in queue()["items"]),
)

# 2. Open PR whose head moved: the old-head run is cancelled, the new head's run is held.
reset()
W.update(
    runs=[run(2, OLD, prs=[{"number": 7}]), run(3, NEW, prs=[{"number": 7}])],
    commit_prs={},
    prs={7: pr(7, NEW)},
)
g.run_pass()
check("old-head run cancelled", any(p.endswith("/runs/2/cancel") for p in posts()))
check("current-head run not cancelled", not any(p.endswith("/runs/3/cancel") for p in posts()))
check(
    "current-head run held on Needs me",
    queue()["items"].get("7@" + NEW, {}).get("status") == "pending",
)

# 3. A young superseded run gets one more pass (a head read may lag a fresh push).
reset()
W.update(runs=[run(4, OLD, age_s=30, prs=[{"number": 7}])], commit_prs={}, prs={7: pr(7, NEW)})
g.run_pass()
check("young superseded run is left alone", not any(p.endswith("/cancel") for p in posts()))

# 4. A cancel failure keeps the run visible as its own card.
reset()
W.update(
    runs=[run(5, OLD, prs=[{"number": 7}])], commit_prs={}, prs={7: pr(7, NEW)}, cancel_fails=True
)
g.run_pass()
check(
    "failed cancel shows run-5 pending",
    queue()["items"].get("run-5", {}).get("status") == "pending",
)
check(
    "failed cancel logged",
    any(d.get("decision") == "cancel_superseded_failed" for d in decisions()),
)

# 5. A working session never hides the plan: the card shows on the first pass with a note.
reset()
W.update(
    runs=[run(6, NEW, prs=[{"number": 7}])],
    commit_prs={},
    prs={7: pr(7, NEW)},
    park="session s is working the PR",
)
wake = g.run_pass()
it = queue()["items"]["7@" + NEW]
check("working session: item pending on the first pass", it.get("status") == "pending")
check("working session: never parked", "parked" not in it)
check("working session: note on the card", it.get("working") == "session s is working the PR")
check("working session: assessment still requested", any(w["key"] == "7@" + NEW for w in wake))
check("working transition logged", any(d.get("decision") == "working" for d in decisions()))
q = queue()
q["items"]["7@" + NEW]["parked"] = "legacy park"
(TMP / "state/queue.json").write_text(json.dumps(q))
W["park"] = None
g.run_pass()
it = queue()["items"]["7@" + NEW]
check("session ends: note removed, legacy park cleared", "working" not in it and "parked" not in it)

# 6. Parallel reads: pending_deployments results stay paired with their run, and the recent
#    queue re-read keeps only waiting runs.
reset()
W.update(
    runs=[run(10 + i, NEW, prs=[{"number": 7}]) for i in range(12)],
    commit_prs={},
    prs={7: pr(7, NEW)},
    not_plan={11, 13, 17},
)
g.run_pass()
held = set(queue()["items"]["7@" + NEW]["run_ids"])
check(
    "parallel pending reads pair with their runs",
    held == {10 + i for i in range(12)} - {11, 13, 17},
)
q = {
    "items": {"7@" + NEW: {"status": "pending", "first_seen": iso(60), "run_ids": [101, 102, 103]}}
}
(TMP / "state/queue.json").write_text(json.dumps(q))
W["by_id"] = {
    101: {"id": 101, "status": "waiting"},
    102: {"id": 102, "status": "completed"},
    103: {"id": 103, "status": "waiting"},
}
got = real_recent(set())
check("recent queue re-read keeps only waiting runs", sorted(r["id"] for r in got) == [101, 103])

# 6b. Fast pass: holds and queues like the cron pass, but never stamps an assessment wake.
reset()
W.update(runs=[run(30, NEW, prs=[{"number": 7}])], commit_prs={}, prs={7: pr(7, NEW)})
g.PASS_ONLY = True
wake = g.run_pass()
g.PASS_ONLY = False
it = queue()["items"]["7@" + NEW]
check("fast pass queues the hold", it.get("status") == "pending")
check("fast pass stamps no wake", not wake and "last_wake_epoch" not in it)
wake = g.run_pass()
check(
    "the cron pass after it still wakes for the assessment",
    any(w["key"] == "7@" + NEW for w in wake),
)

# 7. working_session branch match is exact (a push to <branch>-access must not match <branch>).
con = sqlite3.connect(str(TMP / "state.db"))
con.executescript(
    "CREATE TABLE session_turn_leases(conversation_id TEXT, expires_at REAL);"
    "CREATE TABLE sessions(id TEXT, title TEXT, parent_session_id TEXT, end_reason TEXT);"
    "CREATE TABLE messages(session_id TEXT, timestamp REAL, tool_calls TEXT);"
)
con.execute("INSERT INTO session_turn_leases VALUES('s1', ?)", (g.NOW + 600,))
con.execute("INSERT INTO sessions VALUES('s1', 'Build things', NULL, NULL)")
con.execute(
    "INSERT INTO messages VALUES('s1', ?, ?)",
    (g.NOW - 60, json.dumps({"cmd": "git push origin HEAD:ticket-id-fake-x-access 2>&1"})),
)
con.commit()
check("push to a longer branch does not match", g.working_session(350, "ticket-id-fake-x") is None)
check(
    "push to the longer branch matches its own PR",
    g.working_session(348, "ticket-id-fake-x-access") is not None,
)
con.execute(
    "INSERT INTO messages VALUES('s1', ?, ?)",
    (g.NOW - 30, json.dumps({"cmd": "git push origin HEAD:ticket-id-fake-x"})),
)
con.commit()
check("push to the exact branch matches", g.working_session(350, "ticket-id-fake-x") is not None)
con.close()


# ======================================================================================
# narrow rules (assess_hits on synthetic diffs, gh and the main standard patched)
# ======================================================================================
def diff_for(path, added=(), removed=(), ctx=("  # ctx",), start=10, new=False):
    body = [" " + c.strip() if not c.startswith(" ") else c for c in ctx]
    lines = [f"diff --git a/{path} b/{path}"]
    if new:
        lines += ["new file mode 100644", "index 0000000..abc1234", "--- /dev/null"]
    else:
        lines += ["index 1111111..2222222 100644", f"--- a/{path}"]
    lines += [
        f"+++ b/{path}",
        "@@ -%d,%d +%d,%d @@ resource x {" % (start, len(removed) + 1, start, len(added) + 1),  # noqa: UP031
    ]
    lines += body + ["-" + x for x in removed] + ["+" + x for x in added]
    return "\n".join(lines) + "\n"


def reasons_of(files, diff, sha=None):
    return [h["reason"] for h in g.assess_hits(files, diff, sha)]


STD_EMPTY = {"type": "azurerm", "attrs": {}, "key": False}
real_backend_standard = g.backend_standard
g.backend_standard = lambda: W.get("std", STD_EMPTY)
P = "infrastructure/terraform/newroot/providers.tf"
BK = ['  backend "azurerm" {}']

W.clear()
check(
    "backend: standard empty block in a new root is allowed",
    reasons_of([P], diff_for(P, BK, new=True)) == [],
)
check(
    "backend: standard block in a function app root still allowed",
    reasons_of(
        ["functions/s/infra/providers.tf"], diff_for("functions/s/infra/providers.tf", BK, new=True)
    )
    == [],
)
check(
    "backend: block with an attribute holds",
    len(
        reasons_of(
            [P], diff_for(P, ['  backend "azurerm" {', '    container_name = "x"', "  }"], new=True)
        )
    )
    == 1,
)
check(
    "backend: another backend type holds",
    len(reasons_of([P], diff_for(P, ['  backend "local" {}'], new=True))) == 1,
)
check(
    "backend: block sharing its line with other code holds",
    len(reasons_of([P], diff_for(P, ['terraform { backend "azurerm" {} }'], new=True))) == 1,
)
check(
    "backend: unterminated block holds",
    len(reasons_of([P], diff_for(P, ['  backend "azurerm" {', "    # open"], new=True))) == 1,
)
W["std"] = None
check(
    "backend: no consistent standard on main holds",
    len(reasons_of([P], diff_for(P, BK, new=True))) == 1,
)
W["std"] = {"type": "azurerm", "attrs": {}, "key": True}
check(
    "backend: key named for the root is allowed when main roots set one",
    reasons_of(
        [P],
        diff_for(
            P, ['  backend "azurerm" {', '    key = "newroot/platform.tfstate"', "  }"], new=True
        ),
    )
    == [],
)
check(
    "backend: key for another root holds",
    len(
        reasons_of(
            [P],
            diff_for(P, ['  backend "azurerm" {', '    key = "other.tfstate"', "  }"], new=True),
        )
    )
    == 1,
)
check(
    "backend: empty block holds when main roots carry a key",
    len(reasons_of([P], diff_for(P, BK, new=True))) == 1,
)
W.clear()
check(
    "backend: a key is refused when no root on main sets one",
    len(
        reasons_of(
            [P],
            diff_for(P, ['  backend "azurerm" {', '    key = "newroot.tfstate"', "  }"], new=True),
        )
    )
    == 1,
)
check(
    "backend: .tf.json is never judged by the standard",
    len(reasons_of(["a/b.tf.json"], diff_for("a/b.tf.json", BK, new=True))) >= 1,
)

# backend_standard() itself, from a fake main
g.backend_standard = real_backend_standard
BE = {
    "a/infra/providers.tf": 'terraform {\n  backend "azurerm" {}\n}\n',
    "b/infra/main.tf": 'terraform {\n  # backend "x" {}\n  backend "azurerm" {}\n}\n',
    "c/other.tf": "x",
}


def std_gh(args, timeout=60, raw=False):
    p = args[1]
    if p.endswith("/commits/main"):
        return "mainsha\n"
    if "/git/trees/" in p:
        return {
            "tree": [
                {"path": k, "type": "blob", "sha": "s" + str(i)} for i, k in enumerate(sorted(BE))
            ]
        }
    if "/contents/" in p:
        return BE[p.split("/contents/")[1].split("?")[0]]
    raise AssertionError(args)


g.gh = std_gh
std = g.backend_standard()
check(
    "backend_standard reads the one standard from main (comments ignored)",
    std == {"type": "azurerm", "attrs": {}, "key": False},
)
BE["d/infra/providers.tf"] = 'terraform {\n  backend "azurerm" {\n    key = "d.tfstate"\n  }\n}\n'
check(
    "backend_standard: roots disagreeing on key use gives no standard", g.backend_standard() is None
)
BE["d/infra/providers.tf"] = (
    'terraform {\n  backend "azurerm" {\n    container_name = "t"\n  }\n}\n'
)
check(
    "backend_standard: roots disagreeing on attributes gives no standard",
    g.backend_standard() is None,
)
g.gh = fake_gh
g.backend_standard = lambda: W.get("std", STD_EMPTY)

# grafana
GD = "infrastructure/terraform/grafana/dashboards.tf"
GP = "infrastructure/terraform/grafana/providers.tf"
GV = "infrastructure/terraform/grafana/terraform.tfvars"
LINE = ['    "new-board" = "folder_a"']
check("grafana: dashboards.tf alone is allowed", reasons_of([GD], diff_for(GD, LINE)) == [])
check(
    "grafana: dashboards.tf with folders.tf and permissions.tf is allowed",
    reasons_of(
        [GD, GD.replace("dashboards", "folders")],
        diff_for(GD, LINE) + diff_for(GD.replace("dashboards", "folders"), LINE),
    )
    == [],
)
check(
    "grafana: providers.tf holds every grafana file",
    len(reasons_of([GD, GP], diff_for(GD, LINE) + diff_for(GP, ["x = 1"]))) == 2,
)
check(
    "grafana: tfvars holds",
    len(reasons_of([GV], diff_for(GV, ['grafana_url = "https://x.invalid"']))) == 1,
)
check(
    "grafana: lockfile holds",
    len(
        reasons_of(
            ["infrastructure/terraform/grafana/.terraform.lock.hcl"],
            diff_for("infrastructure/terraform/grafana/.terraform.lock.hcl", ["# x"]),
        )
    )
    >= 1,
)
for label, ln in (
    ("url", '  url = "https://evil.invalid"'),
    ("token", "  token = var.t"),
    ("provider block", 'provider "grafana" {'),
    ("backend", '  backend "azurerm" {}'),
    ("data http", 'data "http" "x" {}'),
    ("auth", '  auth = "x"'),
):
    check(f"grafana: added {label} line holds", len(reasons_of([GD], diff_for(GD, [ln]))) >= 1)
check(
    "grafana: removed provider line holds",
    len(reasons_of([GD], diff_for(GD, LINE, removed=['provider "grafana" {']))) >= 1,
)
check(
    "grafana: a comment mentioning a url does not hold",
    reasons_of([GD], diff_for(GD, ["    # see https://x.invalid and the token docs"])) == [],
)
check(
    "grafana: file in a subfolder holds",
    len(
        reasons_of(
            [GD.replace("grafana/", "grafana/sub/")],
            diff_for(GD.replace("grafana/", "grafana/sub/"), LINE),
        )
    )
    == 1,
)

# .github/scripts/tests
T1 = ".github/scripts/tests/test_a.py"
HEAD = "d" * 40


def wf_gh(files):
    def f(args, timeout=60, raw=False):
        W.setdefault("wf_calls", []).append(args[1])
        p = args[1]
        if W.get("wf_error"):
            raise g.GhError("synthetic")
        if p.startswith(f"repos/{g.REPO}/contents/.github?ref="):
            return [{"name": "workflows", "sha": "w1"}, {"name": "scripts", "sha": "s1"}]
        if "/contents/.github/workflows?ref=" in p:
            return [
                {"name": k.split("/")[-1], "path": k, "type": "file"}
                for k in files
                if k.startswith(".github/workflows/")
            ]
        if "/contents/" in p:
            path = p.split("/contents/")[1].split("?")[0]
            if path in files:
                return files[path]
            raise g.GhError("404")
        raise AssertionError(args)

    return f


PLAN = (
    "jobs:\n  plan:\n    environment: ${{ github.event_name == 'pull_request' && 'terraform-plan' || '' }}\n"
    "    runs-on: x\n    steps:\n      - run: .github/scripts/tf-backend.sh a b\n"
)
UNIT = "jobs:\n  unit:\n    runs-on: x\n    steps:\n      - run: python -m pytest .github/scripts/tests -q\n"
SAFE = {
    ".github/workflows/terraform-ci.yml": PLAN,
    ".github/workflows/unit.yml": UNIT,
    ".github/scripts/tf-backend.sh": "echo hi\n",
}
D1 = diff_for(T1, ["def test_x(): pass"], new=True)


def tests_case(files, sha=HEAD, changed=(T1,), diff=None):
    W["wf_calls"] = []
    for fcache in (TMP / "cache").glob("head-workflow-verdicts.json"):
        fcache.unlink()
    g.gh = wf_gh(files)
    try:
        return reasons_of(list(changed), diff or D1, sha)
    finally:
        g.gh = fake_gh


check("tests: allowed when only a job without the environment runs pytest", tests_case(SAFE) == [])
check(
    "tests: verdict is cached per head tree (second read makes one call)",
    (tests_case(SAFE) == []) and (g.gh == fake_gh),
)
W["wf_calls"] = []
g.gh = wf_gh(SAFE)
n1 = len(W["wf_calls"])
reasons_of([T1], D1, HEAD)
check(
    "tests: second assess of the same head reads only the directory listing",
    len(W["wf_calls"]) - n1 == 1,
)
g.gh = fake_gh
check("tests: held with no head sha", len(tests_case(SAFE, sha=None)) == 1)
bad = dict(
    SAFE,
    **{".github/workflows/terraform-ci.yml": PLAN + "      - run: pytest .github/scripts/tests\n"},
)
check("tests: held when the terraform-plan job runs pytest", len(tests_case(bad)) == 1)
bad = dict(
    SAFE, **{".github/workflows/terraform-ci.yml": PLAN + "      - run: python -m unittest\n"}
)
check("tests: held when the terraform-plan job runs unittest", len(tests_case(bad)) == 1)
bad = dict(SAFE, **{".github/scripts/tf-backend.sh": "pytest -q .github/scripts/tests\n"})
check(
    "tests: held when a script the terraform-plan job calls runs the tests",
    len(tests_case(bad)) == 1,
)
bad = dict(SAFE, **{".github/scripts/tf-backend.sh": None})
bad.pop(".github/scripts/tf-backend.sh")
check("tests: held when a script the job calls cannot be read", len(tests_case(bad)) == 1)
ACT = PLAN + "      - uses: ./.github/actions/x\n"
check(
    "tests: held when a composite action the job uses runs pytest",
    len(
        tests_case(
            dict(
                SAFE,
                **{
                    ".github/workflows/terraform-ci.yml": ACT,
                    ".github/actions/x/action.yml": "runs:\n  steps:\n    - run: pytest\n",
                },
            )
        )
    )
    == 1,
)
check(
    "tests: composite action without tests is fine",
    tests_case(
        dict(
            SAFE,
            **{
                ".github/workflows/terraform-ci.yml": ACT,
                ".github/actions/x/action.yml": "runs:\n  steps:\n    - run: echo\n",
            },
        )
    )
    == [],
)
EXT = "jobs:\n  call:\n    uses: other/repo/.github/workflows/x.yml@main\n"
check(
    "tests: held on an external reusable workflow",
    len(tests_case(dict(SAFE, **{".github/workflows/e.yml": EXT}))) == 1,
)
check(
    "tests: held on a workflow it cannot parse",
    len(
        tests_case(
            dict(SAFE, **{".github/workflows/odd.yml": "name: x\nenvironment: terraform-plan\n"})
        )
    )
    == 1,
)
check(
    "tests: held when the head workflows cannot be read",
    (W.update(wf_error=True) or True) and len(tests_case(SAFE)) == 1,
)
W.pop("wf_error", None)
check(
    "tests: held when the PR changes a workflow too",
    len(
        tests_case(
            SAFE,
            changed=(T1, ".github/workflows/unit.yml"),
            diff=D1 + diff_for(".github/workflows/unit.yml", ["x"]),
        )
    )
    >= 2,
)
check(
    "tests: non-test .github script stays held even when tests are allowed",
    len(
        tests_case(
            SAFE,
            changed=(T1, ".github/scripts/tf-x.py"),
            diff=D1 + diff_for(".github/scripts/tf-x.py", ["x"]),
        )
    )
    == 1,
)
check(
    "tests: CODEOWNERS and workflow edits stay held without any head read",
    len(reasons_of([".github/CODEOWNERS"], diff_for(".github/CODEOWNERS", ["* @x"]))) >= 2,
)
g.gh = fake_gh

# fingerprints are content based and ignore line numbers, hunk headers and context
FA = diff_for(".github/CODEOWNERS", ["* @a"], start=10, ctx=("  ctx one",))
FB = diff_for(".github/CODEOWNERS", ["* @a"], start=400, ctx=("  something else entirely",))
FC = diff_for(".github/CODEOWNERS", ["* @b"], start=10)
fa, fb, fc = ([h["fp"] for h in g.assess_hits([".github/CODEOWNERS"], d)] for d in (FA, FB, FC))
check(
    "fingerprint ignores hunk headers, line numbers and context (rebase safe)",
    fa == fb and None not in fa,
)
check("fingerprint changes when the added content changes", fa != fc)
la = g.assess_hits(["a/x.tf"], diff_for("a/x.tf", ['  provisioner "local-exec" {'], start=5))
lb = g.assess_hits(
    ["a/x.tf"], diff_for("a/x.tf", ['  provisioner "local-exec" {'], start=99, ctx=("  other",))
)
lc = g.assess_hits(
    ["a/x.tf"], diff_for("a/x.tf", ['  provisioner "local-exec" {', '    command = "x"'])
)
check(
    "line-rule fingerprint is the matched line, stable across rebases",
    la[0]["fp"] == lb[0]["fp"] and la[0]["fp"],
)
check(
    "line-rule fingerprint differs by path",
    la[0]["fp"]
    != g.assess_hits(["b/x.tf"], diff_for("b/x.tf", ['  provisioner "local-exec" {']))[0]["fp"],
)
check(
    "assess_diff keeps returning plain reason strings",
    g.assess_diff([".github/CODEOWNERS"], FA)
    == [h["reason"] for h in g.assess_hits([".github/CODEOWNERS"], FA)],
)
binary = "diff --git a/.github/CODEOWNERS b/.github/CODEOWNERS\nindex 1..2 100644\nBinary files a/.github/CODEOWNERS and b/.github/CODEOWNERS differ\n"
check(
    "a file with no text lines fingerprints its diff header",
    all(h["fp"] for h in g.assess_hits([".github/CODEOWNERS"], binary)),
)
check(
    "a hit for a file missing from the diff cannot carry",
    any(h["fp"] is None for h in g.assess_hits([".github/CODEOWNERS", ".github/x.yml"], FA)),
)
check(
    "a lockfile hit needs main's providers and fingerprints the lockfile hunk",
    (setattr(g, "main_providers", lambda: {"hashicorp/azurerm"}) or True)
    and [
        h["reason"].startswith("lockfile adds provider") and bool(h["fp"])
        for h in g.assess_hits(
            ["r/.terraform.lock.hcl"],
            diff_for(
                "r/.terraform.lock.hcl",
                ['provider "registry.terraform.io/x/y" {', '  version = "1"'],
            ),
        )
    ]
    == [True],
)


# ======================================================================================
# approval carries forward (run_pass with a seeded queue)
# ======================================================================================
H1, H2, H3 = (
    {"reason": "changes .github/ x: a", "fp": "fp1"},
    {"reason": "changes CODEOWNERS: b", "fp": "fp2"},
    {"reason": "backend block added in n.tf", "fp": "fp3"},
)
V1, V2, V3 = "1" * 40, "2" * 40, "3" * 40


def seed(items):
    (TMP / "state/queue.json").write_text(json.dumps({"items": items}))


def approved_item(
    sha, fps, src="manual", pr_n=7, status="approved", at="2026-10-16T10:00:00Z", **kw
):
    return dict(
        {
            "pr": pr_n,
            "head_sha": sha,
            "status": status,
            "decided_at": at,
            "approval_source": src,
            "approved_fps": fps,
            "run_ids": [1],
            "decided_runs": [1],
            "held_reasons": [],
            "files": [],
            "first_seen": iso(5000),
        },
        **kw,
    )


def go(hits, items, login="owner-login", dry=False):
    reset()
    seed(items)
    W.update(
        runs=[run(50, V3, prs=[{"number": 7}])],
        commit_prs={},
        prs={7: pr(7, V3, login=login)},
        hits=hits,
    )
    g.DRY_RUN = dry
    try:
        g.run_pass()
    finally:
        g.DRY_RUN = False


def comments():
    return [
        a for c in CALLS if c[:3] == ["api", "-X", "POST"] for a in c if a.startswith("comment=")
    ]


go([H1], {"7@" + V1: approved_item(V1, ["fp1"])})
check(
    "carry: same fingerprint approved earlier is approved with the exact carry comment",
    comments() == ["comment=Approved: no new held changes since the owner's review"],
)
d = [x for x in decisions() if x["decision"] == "approved_carried"]
check(
    "carry: logs approved_carried with the approved sha it carried from",
    len(d) == 1 and d[0]["carried_from"] == V1 and d[0]["pr"] == 7,
)
check("carry: no card is queued for the carried head", "7@" + V3 not in queue()["items"])
go([H1, H2], {"7@" + V1: approved_item(V1, ["fp1", "fp2"])})
check(
    "carry: several hits all approved carries",
    comments() == ["comment=Approved: no new held changes since the owner's review"],
)
go([H1, H3], {"7@" + V1: approved_item(V1, ["fp1"])})
it = queue()["items"].get("7@" + V3, {})
check("carry: a new fingerprint holds normally", not posts() and it.get("status") == "pending")
check("carry: new_held lists only the new hit", it.get("new_held") == [H3["reason"]])
check(
    "carry: held item stores the hit fingerprints",
    [h["fp"] for h in it.get("hits", [])] == ["fp1", "fp3"],
)
go([H1], {})
check(
    "carry: a first look never carries and has no new_held",
    not posts() and "new_held" not in queue()["items"]["7@" + V3],
)
go(
    [H1],
    {
        "7@" + V1: approved_item(
            V1, ["fp1"], status="rejected", src="manual", approved_fps=[], rejected_fps=["fp1"]
        )
    },
)
check(
    "carry: a rejected head never carries",
    not posts() and queue()["items"]["7@" + V3]["status"] == "pending",
)
go(
    [H1],
    {
        "7@" + V1: approved_item(V1, ["fp1"]),
        "7@" + V2: approved_item(
            V2, [], status="rejected", at="2026-10-16T11:00:00Z", rejected_fps=["fp1"]
        ),
    },
)
check("carry: a later rejection of the same content revokes the earlier approval", not posts())
go(
    [H1],
    {
        "7@" + V1: approved_item(V1, [], status="rejected", rejected_fps=["fp1"]),
        "7@" + V2: approved_item(V2, ["fp1"], at="2026-10-16T12:00:00Z"),
    },
)
check(
    "carry: a later approval of the same content wins over an earlier rejection",
    comments() == ["comment=Approved: no new held changes since the owner's review"],
)
go([H1], {"7@" + V1: approved_item(V1, ["fp1"], src="carried")})
check("carry: a carried approval is never a source", not posts())
go([H1], {"7@" + V1: approved_item(V1, ["fp1"], src=None)})
check("carry: an approval with no manual source (auto) is never a source", not posts())
go([H1], {"9@" + V1: approved_item(V1, ["fp1"], pr_n=9)})
check("carry: another PR's approval never carries", not posts())
go(
    [H1, {"reason": "diff too large to verify", "fp": None}],
    {"7@" + V1: approved_item(V1, ["fp1"])},
)
check("carry: a hit with no fingerprint holds", not posts())
go([H1], {"7@" + V1: approved_item(V1, ["fp1"])}, login="someone-else")
check(
    "carry: a PR by another author carries from the owner's approval too",
    comments() == ["comment=Approved: no new held changes since the owner's review"],
)
# a re-ask card carries the newly held files' diff since the owner's approved head
import hashlib as _hl  # noqa: E402

H3P = dict(H3, path="n.tf")
H1P = dict(H1, path="x")


def go_delta(hits, items, compare=None, fails=False):
    reset()
    seed(items)
    W.update(
        runs=[run(50, V3, prs=[{"number": 7}])],
        commit_prs={},
        prs={7: pr(7, V3)},
        hits=hits,
        compare=compare or {"files": []},
        compare_fails=fails,
    )
    g.run_pass()
    return queue()["items"].get("7@" + V3, {})


cmp_ = {
    "files": [
        {"filename": "n.tf", "status": "modified", "additions": 3, "deletions": 1},
        {"filename": "x", "status": "modified", "additions": 9, "deletions": 9},
    ]
}
it = go_delta([H1P, H3P], {"7@" + V1: approved_item(V1, ["fp1"])}, cmp_)
hd = it.get("held_delta") or {}
check(
    "delta: base is the owner's approved head, head is the new head",
    hd.get("base_sha") == V1 and hd.get("head_sha") == V3,
)
check(
    "delta: lists only the newly held file with its line counts",
    [(f["path"], f["additions"], f["deletions"]) for f in hd.get("files", [])] == [("n.tf", 3, 1)],
)
check(
    "delta: file link is the compare view anchored on that file",
    hd.get("files", [{}])[0].get("url")
    == f"https://github.com/{g.REPO}/compare/{V1}...{V3}#diff-" + _hl.sha256(b"n.tf").hexdigest(),
)
check(
    "delta: the hold itself is unchanged (pending, nothing posted)",
    it.get("status") == "pending" and not posts(),
)
n_cmp = sum(1 for c in CALLS if "/compare/" in c[1])
g.run_pass()
check(
    "delta: an unchanged head pair is not fetched again",
    sum(1 for c in CALLS if "/compare/" in c[1]) == n_cmp == 1,
)
it = go_delta([H1P, H3P], {"7@" + V1: approved_item(V1, ["fp1"])}, {"files": []})
check(
    "delta: a held file absent from the compare is listed as unchanged between heads",
    (it.get("held_delta") or {}).get("unchanged") == ["n.tf"],
)
it = go_delta([H1P, H3P], {"7@" + V1: approved_item(V1, ["fp1"])}, fails=True)
hd = it.get("held_delta") or {}
check(
    "delta: a failed compare read keeps the hold and the compare link, with the error",
    it.get("status") == "pending"
    and not posts()
    and hd.get("error")
    and hd.get("compare_url", "").endswith(f"{V1}...{V3}"),
)
it = go_delta([H1P], {})
check("delta: a first look has no delta", "held_delta" not in it)
it = go_delta(
    [H1P],
    {
        "7@" + V1: approved_item(V1, ["fp1"]),
        "7@" + V3: dict(
            approved_item(V3, [], status="pending", src=None), held_delta={"base_sha": V1}
        ),
    },
)
check(
    "delta: a carried head drops the delta", "held_delta" not in queue()["items"].get("7@" + V3, {})
)
real_cd = g.carry_decision
g.carry_decision = lambda *a: (_ for _ in ()).throw(RuntimeError("synthetic"))
go([H1], {"7@" + V1: approved_item(V1, ["fp1"])})
g.carry_decision = real_cd
check(
    "carry: any error in the carry check holds",
    not posts() and queue()["items"]["7@" + V3]["status"] == "pending",
)
go([H1], {"7@" + V1: approved_item(V1, ["fp1"])}, dry=True)
check(
    "carry: dry run logs would_approve_carried and posts nothing",
    not posts() and any(x["decision"] == "would_approve_carried" for x in decisions()),
)
# unexpected workflow on the carried head never carries
reset()
seed({"7@" + V1: approved_item(V1, ["fp1"])})
r_bad = run(50, V3, prs=[{"number": 7}])
r_bad["path"] = ".github/workflows/other.yml"
W.update(runs=[r_bad], commit_prs={}, prs={7: pr(7, V3)}, hits=[H1])
g.run_pass()
check("carry: an unexpected workflow is never carried", not posts())
# an already queued card for the carried head is closed and keeps no fingerprints
go(
    [H1],
    {
        "7@" + V1: approved_item(V1, ["fp1"]),
        "7@" + V3: {
            "pr": 7,
            "head_sha": V3,
            "status": "pending",
            "run_ids": [49],
            "held_reasons": ["x"],
            "files": [],
            "first_seen": iso(300),
        },
    },
)
q3 = queue()["items"]["7@" + V3]
check(
    "carry: a queued card for that head is closed as carried",
    q3["status"] == "approved"
    and q3["approval_source"] == "carried"
    and "approved_fps" not in q3
    and q3["carried_from"] == V1,
)

# the second wave of a carried run uses the carry comment, never 'Approved after review'
reset()
seed({"7@" + V3: dict(approved_item(V3, [], src="carried"), run_ids=[50], decided_runs=[50])})
W.update(runs=[run(50, V3, prs=[{"number": 7}])], commit_prs={}, prs={7: pr(7, V3)}, hits=[H1])
g.run_pass()
check(
    "carry: follow-up wave of a carried run uses the carry comment",
    comments() == ["comment=Approved: no new held changes since the owner's review"],
)

g.assess_pr_detail = real_detail

# ======================================================================================
# terraform-exclusions.json allowed only when the change appends new entries
# ======================================================================================
EX = "infrastructure/terraform-exclusions.json"
BASE_SHA, HEAD159 = "d" * 40, "e" * 40
SUB = "/subscriptions/object-id"


def ent(name, rg="dev"):
    return {
        "pattern": f"{SUB}/resourcegroups/{rg}/providers/microsoft.alertsmanagement/smartdetectoralertrules/failure anomalies - {name}",
        "reason": f"Failure Anomalies rule that Azure creates with {name}. Exact id. Added 2026-10-16",
    }


def exfile(entries, **extra):
    d = {"description": "ADR 0008 exclusion list"}
    d.update(extra)
    d["exclusions"] = entries
    return json.dumps(d, indent=2)


E_BASE = [
    {
        "pattern": SUB
        + "/resourcegroups/platform/providers/microsoft.storage/storageaccounts/prod_prefixprodstore/blobservices/default/containers/cost-exports",
        "reason": "x",
    },
    {
        "pattern": "/subscriptions/*/resourcegroups/*/providers/microsoft.eventgrid/systemtopics/*",
        "reason": "y",
    },
    ent("dev-prefix-a-appi"),
]


def ex_gh(base_text, head_text, merge_base=BASE_SHA, fail=None):
    def f(args, timeout=60, raw=False):
        p = args[1]
        if fail == "compare" and "/compare/" in p:
            raise g.GhError("HTTP 500 synthetic")
        if "/compare/main..." in p:
            return {"merge_base_commit": {"sha": merge_base}}
        if "/contents/" in p:
            if fail == "contents":
                raise g.GhError("HTTP 404 synthetic")
            return base_text if p.endswith("ref=" + BASE_SHA) else head_text
        raise AssertionError(args)

    return f


def ex_verdict(base_text, head_text, **kw):
    g.gh = ex_gh(base_text, head_text, **kw)
    try:
        return g.exclusions_allowed(HEAD159)
    finally:
        g.gh = fake_gh


def ex_hits(base_text, head_text, lines=("+ x",), sha=HEAD159, **kw):
    g.gh = ex_gh(base_text, head_text, **kw)
    try:
        return g.assess_hits([EX], diff_for(EX, list(lines)), sha)
    finally:
        g.gh = fake_gh


B = exfile(E_BASE)
n = ent("dev-prefix-b-appi")
ok, why = ex_verdict(B, exfile(E_BASE + [n, ent("prod-prefix-b-appi", "prod")]))
check(f"exclusions: appending new entries is allowed ({why})", ok)
check("exclusions: allowed change yields no hit", ex_hits(B, exfile(E_BASE + [n])) == [])
check(
    "exclusions: a new entry inserted in the middle is allowed",
    ex_verdict(B, exfile(E_BASE[:1] + [ent("dev-prefix-new-appi")] + E_BASE[1:]))[0],
)
check("exclusions: removing an entry holds", not ex_verdict(B, exfile(E_BASE[:2]))[0])
check(
    "exclusions: removing one and adding one holds", not ex_verdict(B, exfile(E_BASE[:2] + [n]))[0]
)
check(
    "exclusions: editing a reason holds",
    not ex_verdict(B, exfile([dict(E_BASE[0], reason="changed")] + E_BASE[1:] + [n]))[0],
)
check(
    "exclusions: editing a pattern holds",
    not ex_verdict(
        B, exfile([dict(E_BASE[0], pattern=E_BASE[0]["pattern"] + "x")] + E_BASE[1:] + [n])
    )[0],
)
check(
    "exclusions: reordering existing entries holds",
    not ex_verdict(B, exfile([E_BASE[1], E_BASE[0], E_BASE[2], n]))[0],
)
check("exclusions: an unchanged file holds (nothing added)", not ex_verdict(B, B)[0])
check(
    "exclusions: new entry with an extra key holds",
    not ex_verdict(B, exfile(E_BASE + [dict(n, extra="x")]))[0],
)
check(
    "exclusions: new entry missing reason holds",
    not ex_verdict(B, exfile(E_BASE + [{"pattern": n["pattern"]}]))[0],
)
check(
    "exclusions: new entry with empty reason holds",
    not ex_verdict(B, exfile(E_BASE + [dict(n, reason=" ")]))[0],
)
check(
    "exclusions: new entry with a non-string value holds",
    not ex_verdict(B, exfile(E_BASE + [dict(n, reason=5)]))[0],
)
check(
    "exclusions: new entry that is not an object holds",
    not ex_verdict(B, exfile(E_BASE + ["x"]))[0],
)
check(
    "exclusions: new entry repeating an existing pattern holds",
    not ex_verdict(B, exfile(E_BASE + [dict(E_BASE[0])]))[0],
)
check("exclusions: new top-level key holds", not ex_verdict(B, exfile(E_BASE + [n], version=2))[0])
check(
    "exclusions: changed description holds",
    not ex_verdict(B, json.dumps({"description": "other", "exclusions": E_BASE + [n]}))[0],
)
check(
    "exclusions: removed top-level key holds",
    not ex_verdict(B, json.dumps({"exclusions": E_BASE + [n]}))[0],
)
check(
    "exclusions: exclusions turned into a dict holds",
    not ex_verdict(
        B, json.dumps({"description": "ADR 0008 exclusion list", "exclusions": {"a": 1}})
    )[0],
)
check("exclusions: top level turned into a list holds", not ex_verdict(B, json.dumps([n]))[0])
MIXED = E_BASE + [{"pattern": "p", "reason": "r", "x": 1}]
check(
    "exclusions: base entries of mixed schema hold",
    not ex_verdict(exfile(MIXED), exfile(MIXED + [n]))[0],
)
for label, pat in [
    ("star", "*"),
    ("double star", "**"),
    ("empty", ""),
    ("blank", "  "),
    ("slash star", "/*"),
    ("subscriptions star", "/subscriptions/*"),
    ("all in a resource group", SUB + "/resourcegroups/platform/providers/*"),
    ("any type in a provider", SUB + "/resourcegroups/platform/providers/microsoft.storage/*"),
    ("wildcard type", SUB + "/resourcegroups/platform/providers/microsoft.storage/*/*"),
    (
        "wildcard namespace",
        "/subscriptions/*/resourcegroups/*/providers/*/storageaccounts/prod_prefixprodstore",
    ),
    (
        "wildcard final segment",
        SUB + "/resourcegroups/platform/providers/microsoft.storage/storageaccounts/*",
    ),
    (
        "short final segment",
        SUB + "/resourcegroups/platform/providers/microsoft.storage/storageaccounts/a*",
    ),
    (
        "double star in name",
        SUB + "/resourcegroups/platform/providers/microsoft.storage/storageaccounts/olym**pus",
    ),
    (
        "character class",
        SUB + "/resourcegroups/platform/providers/microsoft.storage/storageaccounts/[a-z]platform",
    ),
    ("no provider", SUB + "/resourcegroups/platform/prod_prefixprodstore"),
    (
        "uppercase",
        SUB.upper()
        + "/resourcegroups/platform/providers/microsoft.storage/storageaccounts/prod_prefixprodstore",
    ),
    (
        "leading space",
        " "
        + SUB
        + "/resourcegroups/platform/providers/microsoft.storage/storageaccounts/prod_prefixprodstore",
    ),
    ("not an ARM id", "prod_prefixprodstore"),
]:
    check(
        f"exclusions: broad pattern holds ({label})",
        not ex_verdict(B, exfile(E_BASE + [{"pattern": pat, "reason": "r"}]))[0],
    )
SAMPLES = [
    {"pattern": "/subscriptions/a/resourcegroups/b/providers/microsoft.c/d/xx1"},
    {"pattern": "/subscriptions/e/resourcegroups/f/providers/microsoft.g/h/xx2"},
]
check(
    "exclusions: a pattern matching every existing entry holds",
    g._excl_pattern_problem(
        "/subscriptions/*/resourcegroups/*/providers/microsoft.*/*/*xx*", SAMPLES
    )
    is not None,
)
check(
    "exclusions: exact name under a wildcard subscription is allowed",
    g._excl_pattern_problem(
        "/subscriptions/*/resourcegroups/platform/providers/microsoft.automation/automationaccounts/prod-prefix-automation-aa/runtimeenvironments/powershell-5.1",
        E_BASE,
    )
    is None,
)
check(
    "exclusions: prefix glob like the saved search entry is allowed",
    g._excl_pattern_problem(
        "/subscriptions/*/resourcegroups/platform/providers/microsoft.operationalinsights/workspaces/prod-prefix-logging/savedsearches/logmanagement(prod-prefix-logging)_*",
        E_BASE,
    )
    is None,
)
check(
    "exclusions: ? in a name (existing snapshot entry) is allowed",
    g._excl_pattern_problem(
        SUB + "/resourcegroups/image-rg/providers/microsoft.compute/snapshots/master-??-snap-*",
        E_BASE,
    )
    is None,
)
check("exclusions: malformed head JSON holds", not ex_verdict(B, "{not json")[0])
check("exclusions: malformed base JSON holds", not ex_verdict("{not json", exfile(E_BASE + [n]))[0])
check("exclusions: empty head file holds", not ex_verdict(B, "")[0])
check(
    "exclusions: fetch error on the contents holds",
    not ex_verdict(B, exfile(E_BASE + [n]), fail="contents")[0],
)
check(
    "exclusions: fetch error on the compare holds",
    not ex_verdict(B, exfile(E_BASE + [n]), fail="compare")[0],
)
check(
    "exclusions: fetch error holds through assess_hits too",
    len(ex_hits(B, exfile(E_BASE + [n]), fail="contents")) == 1,
)
check("exclusions: no merge base holds", not ex_verdict(B, exfile(E_BASE + [n]), merge_base="")[0])
check(
    "exclusions: malformed merge base sha holds",
    not ex_verdict(B, exfile(E_BASE + [n]), merge_base="zz")[0],
)
check("exclusions: no head sha holds", g.exclusions_allowed(None)[0] is False)
check(
    "exclusions: assess_diff without a head sha holds",
    len(ex_hits(B, exfile(E_BASE + [n]), sha=None)) == 1,
)
# the held case keeps fingerprints
held = ex_hits(B, exfile(E_BASE[:2]))
check(
    "exclusions: removal gives the hold with a fingerprint",
    len(held) == 1 and "terraform-exclusions.json" in held[0]["reason"] and bool(held[0]["fp"]),
)
check(
    "exclusions: held fingerprint is stable for the same lines",
    ex_hits(B, exfile(E_BASE[:2]))[0]["fp"] == held[0]["fp"],
)
check(
    "exclusions: held fingerprint changes when the changed lines change",
    ex_hits(B, exfile(E_BASE[:2]), lines=("+ other",))[0]["fp"] != held[0]["fp"],
)
# other holds in the same PR stay
g.gh = ex_gh(B, exfile(E_BASE + [n]))
mixed = g.assess_hits(
    [EX, ".github/CODEOWNERS"],
    diff_for(EX, ["+ x"]) + diff_for(".github/CODEOWNERS", ["* @a"]),
    HEAD159,
)
g.gh = fake_gh
check(
    "exclusions: other holds in the same PR remain",
    any("CODEOWNERS" in h["reason"] for h in mixed)
    and not any("exclusions" in h["reason"] for h in mixed),
)


def apr159(args, timeout=60, raw=False):
    if args[0] == "pr":
        return diff_for(EX, ["+ x"])
    if args[0] == "api" and args[1] == "--paginate":
        return json.dumps({"filename": EX}) + "\n"
    if args[0] == "api" and args[1].endswith("/pulls/359"):
        return {"head": {"sha": HEAD159}}
    return ex_gh(B, exfile(E_BASE + [n]))(args, timeout, raw)


g.gh = apr159
fl, rs = g.assess_pr(359)
g.gh = fake_gh
check(
    "exclusions: assess_pr reads the head sha and releases an append-only PR",
    fl == [EX] and rs == [],
)

# ======================================================================================
# one sign-off per PR (store, gate carry, plan card, Approve and merge helper)
# ======================================================================================
g.gh = fake_gh
g.assess_pr_detail = lambda n, sha=None, own=False: (
    ["x.tf"],
    W.get("hits") or [{"reason": "changes .github/: synthetic", "fp": None}],
)
so = g.load_signoff()
SO_H1 = {"reason": "changes .github/ x: a", "fp": "fp1", "cfp": "cf1", "path": ".github/a.yml"}
SO_H2 = {"reason": "changes CODEOWNERS: b", "fp": "fp2", "cfp": "cf2", "path": ".github/CODEOWNERS"}


def sign(sha, hits, lane=None, source="approve_merge", pr_n=7):
    so.record(pr_n, sha, lane or so.OWN, source, hits, None)


def go_so(hits, pre, login="owner-login", dry=False):
    reset()
    pre()
    W.update(
        runs=[run(50, V3, prs=[{"number": 7}])],
        commit_prs={},
        prs={7: pr(7, V3, login=login)},
        hits=hits,
    )
    g.DRY_RUN = dry
    try:
        g.run_pass()
    finally:
        g.DRY_RUN = False


go_so([SO_H1, SO_H2], lambda: sign(V1, [SO_H1, SO_H2]))
check(
    "signoff: own PR with every hit covered is approved with the carry comment",
    comments() == ["comment=Approved: no new held changes since the owner's review"],
)
d = [x for x in decisions() if x["decision"] == "approved_carried_signoff"]
check(
    "signoff: logs the distinct decision with the signed head",
    len(d) == 1 and d[0]["carried_from"] == V1 and d[0]["pr"] == 7,
)
check(
    "signoff: the old decision name is not used",
    not [x for x in decisions() if x["decision"] == "approved_carried"],
)
go_so([SO_H1], lambda: sign(V1, [SO_H1, SO_H2]))
check("signoff: a subset of the signed hits carries", len(comments()) == 1)
go_so([SO_H1, dict(SO_H2, fp="fp9", cfp="cf9")], lambda: sign(V1, [SO_H1, SO_H2]))
it = queue()["items"]["7@" + V3]
check("signoff: a new fingerprint holds", not posts() and it["status"] == "pending")
check("signoff: the card names only what is new", it.get("new_held") == [SO_H2["reason"]])
check(
    "signoff: the card links the delta from the signed head",
    (it.get("held_delta") or {}).get("base_sha") == V1,
)
go_so([dict(SO_H1, fp=None, cfp=None)], lambda: sign(V1, [SO_H1]))
check("signoff: a hit with no fingerprint holds", not posts())
go_so([SO_H1], lambda: (sign(V1, [SO_H1]), so.revoke(7, "t")))
check("signoff: a revoked sign-off never carries", not posts())
go_so([SO_H1], lambda: sign(V1, [SO_H1], lane=so.ENGINEER))
check("signoff: an engineer-lane sign-off for another head never carries", not posts())
go_so([SO_H1], lambda: sign(V3, [SO_H1], lane=so.ENGINEER), login="alice")
check("signoff: an engineer-lane sign-off for this exact head carries", len(comments()) == 1)
go_so([SO_H1], lambda: sign(V1, [SO_H1]), login="alice")
check("signoff: an own-lane sign-off never carries an engineer PR", not posts())
go_so([SO_H1], lambda: sign(V1, [SO_H1], pr_n=8))
check("signoff: another PR's sign-off never carries", not posts())
go_so([SO_H1], lambda: sign(V1, [SO_H1]), dry=True)
check(
    "signoff: dry run logs would_approve_carried_signoff and posts nothing",
    not posts() and any(x["decision"] == "would_approve_carried_signoff" for x in decisions()),
)
# the engine's .github hit and the gate's .github hit are one thing: same file content, either card
sign_hits = [
    {
        "rule": "github-dir",
        "reason": "changes .github/ (workflows, actions, CI scripts)",
        "fp": "engfp",
        "cfp": "cf1",
        "path": ".github/a.yml",
    }
]
go_so([SO_H1], lambda: sign(V1, sign_hits))
check(
    "signoff: a policy-card sign-off covers the plan card's .github hit with the same content",
    len(comments()) == 1,
)
go_so([dict(SO_H1, cfp="other")], lambda: sign(V1, sign_hits))
check("signoff: changed .github content is not covered", not posts())
go_so([SO_H2], lambda: sign(V1, [dict(SO_H1, reason="changes CODEOWNERS: z")]))
check("signoff: the .github cross-cover does not stretch to other rules", not posts())
reset()
seed({})
W.update(runs=[run(50, V3, prs=[{"number": 7}])], commit_prs={}, prs={7: pr(7, V3)}, hits=[SO_H1])
so.record(7, V1, so.OWN, "approve_merge", [SO_H1], None)
real_sc = g.signoff_carry
g.signoff_carry = lambda *a: (_ for _ in ()).throw(RuntimeError("synthetic"))
g.run_pass()
g.signoff_carry = real_sc
check(
    "signoff: any error in the sign-off carry holds",
    not posts() and queue()["items"]["7@" + V3]["status"] == "pending",
)
# fingerprints: the gate's hits carry a rule-agnostic content fingerprint
real_wf = g.tests_rule_ok
hh = g.assess_hits([".github/CODEOWNERS"], diff_for(".github/CODEOWNERS", ["* @a"]))
hh2 = g.assess_hits(
    [".github/CODEOWNERS"], diff_for(".github/CODEOWNERS", ["* @a"], start=99, ctx=("  moved",))
)
hh3 = g.assess_hits([".github/CODEOWNERS"], diff_for(".github/CODEOWNERS", ["* @b"]))
check(
    "signoff: hits carry a content fingerprint that ignores line numbers",
    hh[0]["cfp"] and hh[0]["cfp"] == hh2[0]["cfp"],
)
check("signoff: the content fingerprint changes with the content", hh[0]["cfp"] != hh3[0]["cfp"])
check(
    "signoff: content_fps keys every file of a diff",
    set(g.content_fps(diff_for("a.tf", ["x"]) + diff_for("b.tf", ["y"]))) == {"a.tf", "b.tf"},
)
# store hygiene
reset()
for _ in range(9):
    sign(V1, [SO_H1])
check(
    "signoff: the store keeps a bounded history per PR",
    len(json.loads((TMP / "state/pr-signoffs.json").read_text())["prs"]["7"]) == so.KEEP_PER_PR,
)

# ======================================================================================
# own PRs only, a .github/ edit that is not security relevant is released
# ======================================================================================
SHA40 = "1" * 40
MAIN_WF = "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@" + SHA40 + "\n"


def gh199(files, main_files=None, fail=False):
    base = wf_gh(files)

    def f(args, timeout=60, raw=False):
        p = args[1]
        if p.endswith("/commits/main"):
            return "m" * 40
        if "?ref=" + "m" * 40 in p:
            mf = main_files or {".github/workflows/ci.yml": MAIN_WF}
            if "/contents/.github/workflows?ref=" in p:
                return [{"name": k.split("/")[-1], "path": k, "type": "file"} for k in mf]
            path = p.split("/contents/")[1].split("?")[0]
            if path in mf:
                return mf[path]
            raise g.GhError("404")
        if fail:
            raise g.GhError("synthetic")
        return base(args, timeout, raw)

    return f


def own_case(changed, diff, files=SAFE, own=True, sha=HEAD, **kw):
    for fcache in (TMP / "cache").glob("head-workflow-verdicts.json"):
        fcache.unlink()
    g._SURFACE.clear()
    g._MAIN_USES.clear()
    g.gh = gh199(files, **kw)
    try:
        return [h["reason"] for h in g.assess_hits(list(changed), diff, sha, own)]
    finally:
        g.gh = fake_gh


def released(path, added=(), removed=(), new=False, **kw):
    return own_case([path], diff_for(path, added, removed, new=new), **kw) == []


PROMPT = ".github/prompts/review.md"
check("github own: a prompt edit is released for the owner's PR", released(PROMPT, ["Be terse."]))
check(
    "github own: the same edit still holds for an engineer PR",
    len(own_case([PROMPT], diff_for(PROMPT, ["Be terse."]), own=False)) == 1,
)
check("github own: a test edit is released", released(T1, ["def test_y(): pass"]))
SCR = ".github/scripts/ai-review.py"
check(
    "github own: a script beside a shell script that loads nothing is released",
    released(SCR, ["print(1)"]),
)
check(
    "github own: a script a terraform-plan job runs holds",
    not released(".github/scripts/tf-backend.sh", ["echo bye"]),
)
loader = dict(SAFE, **{".github/scripts/tf-backend.sh": "source ./lib.sh\n"})
check(
    "github own: a sibling of a script that sources files holds",
    not released(SCR, ["print(1)"], files=loader),
)
mention = dict(SAFE, **{".github/scripts/tf-backend.sh": "echo hi\npython3 ai-review-helper.py\n"})
check(
    "github own: a file the terraform-plan script mentions holds",
    not released(".github/prompts/ai-review-helper.md", ["x"], files=mention),
)
nested = dict(
    SAFE,
    **{
        ".github/scripts/tf-backend.sh": "bash .github/scripts/lib/deep.sh\n",
        ".github/scripts/lib/deep.sh": "bash .github/scripts/lib/deeper.sh\n",
        ".github/scripts/lib/deeper.sh": "echo\n",
    },
)
check(
    "github own: a file two levels below a terraform-plan script holds",
    not released(".github/scripts/lib/deeper.sh", ["echo y"], files=nested),
)
check(
    "github own: an unreadable referenced script holds",
    not released(PROMPT, ["x"], files={k: v for k, v in SAFE.items() if "tf-backend" not in k}),
)
check(
    "github own: a workflow without an environment job is released (step edit)",
    released(".github/workflows/unit.yml", ["      - run: echo more"]),
)
check(
    "github own: the terraform-plan workflow holds",
    not released(".github/workflows/terraform-ci.yml", ["      - run: echo more"]),
)
for what, line in (
    ("permissions", "permissions:"),
    ("id-token", "      id-token: write"),
    ("environment key", "    environment: prod"),
    ("secrets reference", "        TOKEN: ${{ secrets.X }}"),
    ("pull_request_target", "  pull_request_target:"),
    ("workflow_run", "  workflow_run:"),
):
    check(
        f"github own: workflow adding {what} holds",
        not released(".github/workflows/unit.yml", [line]),
    )
check(
    "github own: removing permissions holds too",
    not released(".github/workflows/unit.yml", [], ["permissions:"]),
)
check(
    "github own: a new third-party uses that is unpinned holds",
    not released(".github/workflows/unit.yml", ["      - uses: actions/setup-python@v5"]),
)
check(
    "github own: a pinned uses from a new owner holds",
    not released(".github/workflows/unit.yml", ["      - uses: evil/act@" + SHA40]),
)
check(
    "github own: a pinned uses from an owner main already uses is released",
    released(".github/workflows/unit.yml", ["      - uses: actions/setup-python@" + "2" * 40]),
)
check(
    "github own: a uses identical to main is released",
    released(".github/workflows/unit.yml", ["      - uses: actions/checkout@" + SHA40]),
)
check(
    "github own: a local uses is released",
    released(".github/workflows/unit.yml", ["      - uses: ./.github/actions/x"]),
)
check(
    "github own: a docker uses holds",
    not released(".github/workflows/unit.yml", ["      - uses: docker://alpine:3"]),
)
check(
    "github own: a pinned uses holds when main shows no known owner",
    not released(
        ".github/workflows/unit.yml",
        ["      - uses: actions/setup-python@" + "2" * 40],
        main_files={".github/workflows/x.yml": "jobs: {}\n"},
    ),
)
check(
    "github own: a new workflow file holds",
    not released(".github/workflows/new.yml", ["on: push"], new=True),
)
for path in (
    ".github/CODEOWNERS",
    ".github/terraform-roots.json",
    ".github/forbidden-patterns.json",
    ".github/dependabot.yml",
    ".github/other.json",
    ".github/scripts/../x",
):
    check(f"github own: {path} holds", not released(path, ["x"]))
check(
    "github own: a sensitive word in a script holds",
    not released(SCR, ["token = os.environ['x']  # secrets.FOO"]),
)
check(
    "github own: a binary change holds",
    own_case(
        [PROMPT],
        f"diff --git a/{PROMPT} b/{PROMPT}\nindex 1..2 100644\nBinary files a/x and b/x differ\n",
    )
    != [],
)
check("github own: no head sha holds", own_case([PROMPT], diff_for(PROMPT, ["x"]), sha=None) != [])
check(
    "github own: a gh read error holds",
    own_case([PROMPT], diff_for(PROMPT, ["x"]), fail=True) != [],
)
mixed = diff_for(PROMPT, ["x"]) + diff_for(".github/CODEOWNERS", ["* @z"])
check(
    "github own: a mixed PR still holds the security file only",
    len(own_case([PROMPT, ".github/CODEOWNERS"], mixed)) == 2
    and all("CODEOWNERS" in r for r in own_case([PROMPT, ".github/CODEOWNERS"], mixed)),
)
check(
    "github own: mixed hit names are the unchanged reasons",
    any(
        r.startswith("changes CODEOWNERS") for r in own_case([PROMPT, ".github/CODEOWNERS"], mixed)
    ),
)
check(
    "github own: the exclusions list keeps its improvement-id path",
    len(
        own_case(
            ["infrastructure/terraform-exclusions.json"],
            diff_for("infrastructure/terraform-exclusions.json", ["x"]),
            sha=None,
        )
    )
    >= 1,
)
check(
    "github own: grafana root still holds for the owner's PR",
    len(
        own_case(
            ["infrastructure/terraform/grafana/providers.tf"],
            diff_for("infrastructure/terraform/grafana/providers.tf", ["x"]),
        )
    )
    >= 1,
)
# ======================================================================================
# delta carry for the owner's own PRs (a .github file whose change since the owner's last manual look is plain)
# ======================================================================================
FILES = {}  # (path, sha) -> text, or an Exception to raise
COMMITS_BAD = set()


def dgh(args, timeout=60, raw=False):
    p = args[1] if len(args) > 1 else ""
    if "/contents/" in p and "?ref=" in p:
        path, sha = p.split("/contents/", 1)[1].split("?ref=")
        v = FILES.get((path, sha), g.GhError("api x: rc=1 gh: Not Found (HTTP 404)"))
        if isinstance(v, Exception):
            raise v
        return v
    if "/commits/" in p and args[2:3] == ["--jq"]:
        sha = p.rsplit("/", 1)[1]
        if sha in COMMITS_BAD:
            raise g.GhError("api x: rc=1 gh: Not Found (HTTP 404)")
        return sha
    return fake_gh(args, timeout, raw)


SCRP = ".github/scripts/tf_branch_drift.py"
WFP = ".github/workflows/terraform-ci.yml"
BASE_PY = "import os\n\ndef main():\n    return 1\n"
NEW_PY = "import os\nimport sys\n\ndef main():\n    x = sys.argv\n    return 1\n"
GHH = {
    "reason": "changes .github/ (workflows, actions, CI scripts): " + SCRP,
    "fp": "gfp1",
    "cfp": "gc1",
    "path": SCRP,
}
g.gh = dgh


def put(path, base_txt, head_txt, mid=None):
    FILES.clear()
    COMMITS_BAD.clear()
    FILES[(path, V1)] = base_txt
    if mid is not None:
        FILES[(path, V2)] = mid
    FILES[(path, V3)] = head_txt


def rel(path, base_txt, head_txt):
    put(path, base_txt, head_txt)
    return g.delta_release(path, V1, V3)


ok_, why_ = rel(SCRP, BASE_PY, NEW_PY)
check("delta: plain script logic is released", ok_)
check("delta: byte-identical is released", rel(SCRP, BASE_PY, BASE_PY)[0])
check(
    "delta: a trailing-whitespace-only change is released",
    rel(SCRP, BASE_PY, BASE_PY.replace("return 1", "return 1  "))[0],
)
put(SCRP, BASE_PY, NEW_PY)
del FILES[(SCRP, V1)]
check("delta: a script new since base releases when plain", g.delta_release(SCRP, V1, V3)[0])
for what, line in (
    ("permissions", "permissions: write-all"),
    ("id-token", "      id-token: write"),
    ("secrets", "      TOKEN: ${{ secrets.FOO }}"),
    ("environment", "    environment: terraform-plan"),
    ("trigger", "on: pull_request_target"),
):
    check(f"delta: adding {what} holds (script)", not rel(SCRP, BASE_PY, NEW_PY + line + "\n")[0])
    check(
        f"delta: adding {what} holds (workflow)",
        not rel(WFP, "name: x\njobs: {}\n", "name: x\njobs: {}\n" + line + "\n")[0],
    )
check(
    "delta: REMOVING a sensitive line holds",
    not rel(WFP, "name: x\npermissions:\n  contents: read\njobs: {}\n", "name: x\njobs: {}\n")[0],
)
check(
    "delta: prose naming secrets.tf in a script is released",
    rel(SCRP, BASE_PY, NEW_PY + "# keys secrets under secrets.tf\n")[0],
)
check(
    "delta: a secrets expression in a script holds",
    not rel(SCRP, BASE_PY, NEW_PY + "x = '${{ secrets.X }}'\n")[0],
)
check(
    "delta: a bare secrets reference in a workflow still holds",
    not rel(WFP, "name: x\n", "name: x\n# see secrets.tf\n")[0],
)
check(
    "delta: an unpinned uses added holds",
    not rel(WFP, "name: x\n", "name: x\n      - uses: evil/act@v1\n")[0],
)
check(
    "delta: a local uses added is fine",
    rel(WFP, "name: x\n", "name: x\n      - uses: ./.github/actions/a\n")[0],
)
put(WFP, "name: x\n", "name: x\n")
del FILES[(WFP, V1)]
check("delta: a new workflow file holds", not g.delta_release(WFP, V1, V3)[0])
put(".github/actions/a/action.yml", "a: 1\n", "a: 1\n")
del FILES[(".github/actions/a/action.yml", V1)]
check(
    "delta: a new action file holds", not g.delta_release(".github/actions/a/action.yml", V1, V3)[0]
)
put(SCRP, BASE_PY, NEW_PY)
del FILES[(SCRP, V3)]
check("delta: a file deleted at the head holds", not g.delta_release(SCRP, V1, V3)[0])
for pth in (
    ".github/CODEOWNERS",
    ".github/terraform-roots.json",
    ".github/forbidden-patterns.json",
    ".github/dependabot.yml",
    "infrastructure/terraform-exclusions.json",
    ".github/other.json",
):
    put(pth, "a\n", "a\nb\n")
    check(f"delta: {pth} holds", not g.delta_release(pth, V1, V3)[0])
put(SCRP, BASE_PY, NEW_PY)
FILES[(SCRP, V3)] = g.GhError("api x: rc=1 HTTP 502")
check("delta: a head read error holds", not g.delta_release(SCRP, V1, V3)[0])
put(SCRP, BASE_PY, NEW_PY)
FILES[(SCRP, V1)] = g.GhError("api x: rc=1 HTTP 502")
check(
    "delta: a base read error holds (not read as a new file)", not g.delta_release(SCRP, V1, V3)[0]
)
put(SCRP, BASE_PY, NEW_PY)
COMMITS_BAD.add(V1)
check("delta: an unreadable base commit holds", not g.delta_release(SCRP, V1, V3)[0])
put(SCRP, BASE_PY, "\x00\x01binary")
check("delta: a binary file holds", not g.delta_release(SCRP, V1, V3)[0])
put(SCRP, BASE_PY, NEW_PY)
check("delta: no base sha holds", not g.delta_release(SCRP, None, V3)[0])
check("delta: base equal to head holds", not g.delta_release(SCRP, V3, V3)[0])


def go_d(hits, items, login="owner-login", dry=False, pre=None):
    reset()
    seed(items)
    if pre:
        pre()
    W.update(
        runs=[run(50, V3, prs=[{"number": 7}])],
        commit_prs={},
        prs={7: pr(7, V3, login=login)},
        hits=hits,
    )
    g.DRY_RUN = dry
    try:
        g.run_pass()
    finally:
        g.DRY_RUN = False


OLD_APP = {"7@" + V1: approved_item(V1, ["oldfp"])}
put(SCRP, BASE_PY, NEW_PY)
go_d([GHH], OLD_APP)
d = [x for x in decisions() if x["decision"] == "approved_carried_delta"]
check(
    "delta gate: a plain script delta carries with the carry comment",
    comments() == ["comment=Approved: no new held changes since the owner's review"],
)
check(
    "delta gate: logs approved_carried_delta with carried_from and delta_paths",
    len(d) == 1 and d[0]["carried_from"] == V1 and d[0]["delta_paths"] == [SCRP],
)
check("delta gate: no card is queued", "7@" + V3 not in queue()["items"])
check(
    "delta gate: the old decision names are not used",
    not [
        x for x in decisions() if x["decision"] in ("approved_carried", "approved_carried_signoff")
    ],
)
go_d([GHH], OLD_APP, dry=True)
check(
    "delta gate: dry run logs would_approve_carried_delta and posts nothing",
    not posts() and any(x["decision"] == "would_approve_carried_delta" for x in decisions()),
)
go_d([GHH], OLD_APP, login="alice")
check(
    "delta gate: an engineer PR never carries",
    not [c for c in posts()] and queue()["items"]["7@" + V3]["status"] == "pending",
)
put(SCRP, BASE_PY, NEW_PY + "permissions: write-all\n")
go_d([GHH], OLD_APP)
check(
    "delta gate: a sensitive delta holds and queues the card",
    not posts() and queue()["items"]["7@" + V3]["status"] == "pending",
)
put(SCRP, BASE_PY, NEW_PY)
go_d([GHH, {"reason": "backend block added in n.tf", "fp": "fpb", "path": "n.tf"}], OLD_APP)
check("delta gate: mixed .github plain plus a DENY_LINE hit holds", not posts())
go_d([GHH, {"reason": "diff too large to verify", "fp": None}], OLD_APP)
check("delta gate: mixed with an unfingerprinted reason holds", not posts())
go_d(
    [
        GHH,
        dict(
            GHH,
            reason="changes CODEOWNERS: .github/CODEOWNERS",
            path=".github/CODEOWNERS",
            fp="gfp2",
        ),
    ],
    OLD_APP,
)
check("delta gate: a CODEOWNERS hit next to a plain one holds", not posts())
go_d(
    [
        dict(
            GHH,
            path=".github/terraform-roots.json",
            reason="changes .github/ (x): .github/terraform-roots.json",
        )
    ],
    OLD_APP,
)
check("delta gate: terraform-roots.json holds", not posts())
go_d([GHH], {})
check("delta gate: no earlier manual approval never carries", not posts())
go_d([GHH], {"7@" + V1: approved_item(V1, ["oldfp"], src="carried")})
check("delta gate: a carried approval is never the base", not posts())
go_d(
    [GHH],
    {
        "7@" + V1: approved_item(V1, ["oldfp"]),
        "7@" + V2: approved_item(
            V2, [], status="rejected", at="2026-10-16T11:00:00Z", rejected_fps=["x"]
        ),
    },
)
check("delta gate: a later rejection voids the base", not posts())
# base is the last MANUAL head, not a later carried head
put(SCRP, BASE_PY, NEW_PY, mid=BASE_PY + "permissions: write-all\n")
FILES[(SCRP, V3)] = BASE_PY + "permissions: write-all\n"
items_c = {
    "7@" + V1: approved_item(V1, ["oldfp"]),
    "7@" + V2: approved_item(V2, [], src="carried", at="2026-10-16T11:00:00Z"),
}
check(
    "delta base: manual_base picks the manual head, not the carried one",
    g.manual_base(items_c, 7, V3) == V1,
)
go_d([GHH], items_c)
check(
    "delta base: a sensitive line slipped in on a carried head still holds at the next head",
    not posts(),
)
# sign-off as the base
put(SCRP, BASE_PY, NEW_PY)
go_d([GHH], {}, pre=lambda: sign(V1, [SO_H1]))
check(
    "delta gate: the owner's own sign-off head is a valid base",
    comments() == ["comment=Approved: no new held changes since the owner's review"]
    and any(
        x["decision"] == "approved_carried_delta" and x["carried_from"] == V1 for x in decisions()
    ),
)
go_d([GHH], {}, pre=lambda: (sign(V1, [SO_H1]), so.revoke(7, "t")))
check("delta gate: a revoked sign-off is not a base", not posts())
real_dc = g.delta_carry
g.delta_carry = lambda *a: (_ for _ in ()).throw(RuntimeError("synthetic"))
go_d([GHH], OLD_APP)
g.delta_carry = real_dc
check(
    "delta gate: any exception holds",
    not posts() and queue()["items"]["7@" + V3]["status"] == "pending",
)
go_d([GHH], OLD_APP, pre=lambda: FILES.__setitem__((SCRP, V3), g.GhError("api x: rc=1 HTTP 502")))
check("delta gate: a read error holds", not posts())

g.gh = fake_gh

# ---- comment and docstring only edits under .github/scripts/*.py (synthetic files) ----
CO_PATH = ".github/scripts/example-tool.py"
CO_BASE = '#!/usr/bin/env python3\n"""Lists things.\n\nUsage: example\n"""\nimport os\n\n\ndef run():\n    """Run it."""\n    return os.getcwd()  # where we are\n'
CO_DOC = CO_BASE.replace("Lists things.", "Lists things, docs reworded.").replace(
    "# where we are", "# cwd"
)
CO_CODE = CO_BASE.replace("os.getcwd()", "os.getcwd() + 'x'")
CO_BANG = CO_DOC.replace("python3", "python3 -the owner")
CO_SELF = CO_BASE + "print(__doc__)\n"
CO_ARGP = CO_BASE + "import argparse\nP = argparse.ArgumentParser(description=__doc__)\n"


def co_verdict(base_txt, head_txt, path=CO_PATH, fail=None, merge_base=BASE_SHA):
    def f(args, timeout=60, raw=False):
        p = args[1]
        if "/compare/main..." in p:
            if fail == "compare":
                raise g.GhError("HTTP 502 synthetic")
            return {"merge_base_commit": {"sha": merge_base}}
        if "/contents/" in p:
            txt = base_txt if p.endswith("ref=" + BASE_SHA) else head_txt
            if txt is None:
                raise g.GhError("gh: Not Found (HTTP 404)")
            if isinstance(txt, Exception):
                raise txt
            return txt
        raise AssertionError(args)

    g.gh = f
    try:
        return g.comment_only_release(path, HEAD159)
    finally:
        g.gh = fake_gh


check("improvement-id: docstring and comment edits release", co_verdict(CO_BASE, CO_DOC)[0])
check("improvement-id: a code change holds", not co_verdict(CO_BASE, CO_CODE)[0])
check("improvement-id: a shebang change holds", not co_verdict(CO_BASE, CO_BANG)[0])
check(
    "improvement-id: a script that reads __doc__ holds",
    not co_verdict(CO_SELF, CO_SELF.replace("Lists", "Shows"))[0],
)
check(
    "improvement-id: argparse description=__doc__ still releases",
    co_verdict(CO_ARGP, CO_ARGP.replace("Lists", "Shows"))[0],
)
check("improvement-id: a new file holds", not co_verdict(None, CO_DOC)[0])
check("improvement-id: a deleted file holds", not co_verdict(CO_BASE, None)[0])
check(
    "improvement-id: a compare read error holds", not co_verdict(CO_BASE, CO_DOC, fail="compare")[0]
)
check(
    "improvement-id: a contents read error holds",
    not co_verdict(CO_BASE, g.GhError("HTTP 500 synthetic"))[0],
)
check(
    "improvement-id: unparseable code holds",
    not co_verdict(CO_BASE + "def (:\n", CO_DOC + "def (:\n")[0],
)
check(
    "improvement-id: a workflow path never qualifies",
    not co_verdict(CO_BASE, CO_DOC, path=".github/workflows/x.py")[0],
)
check(
    "improvement-id: a shell script never qualifies",
    not co_verdict(CO_BASE, CO_DOC, path=".github/scripts/x.sh")[0],
)
check("improvement-id: no head sha holds", not g.comment_only_release(CO_PATH, None)[0])
check("improvement-id: identical text holds", not co_verdict(CO_BASE, CO_BASE)[0])
check(
    "improvement-id: removing a function docstring releases",
    co_verdict(CO_BASE, CO_BASE.replace('"""Run it."""\n    return', "return"))[0],
)


def co_hits(base_txt, head_txt, own=False):
    def f(args, timeout=60, raw=False):
        p = args[1]
        if "/compare/main..." in p:
            return {"merge_base_commit": {"sha": BASE_SHA}}
        if "/contents/" in p:
            return base_txt if p.endswith("ref=" + BASE_SHA) else head_txt
        raise AssertionError(args)

    g.gh = f
    try:
        d = diff_for(CO_PATH, added=["# new comment"], removed=["# old comment"])
        return [h["reason"] for h in g.assess_hits([CO_PATH], d, HEAD159, own)]
    finally:
        g.gh = fake_gh


check(
    "improvement-id: assess_hits releases a comment-only engineer edit",
    co_hits(CO_BASE, CO_DOC) == [],
)
check("improvement-id: assess_hits holds a code edit", len(co_hits(CO_BASE, CO_CODE)) == 1)

print("\n%d failure(s)" % len(FAIL))  # noqa: UP031
sys.exit(1 if FAIL else 0)
