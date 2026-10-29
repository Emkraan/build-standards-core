"""
repo_reviews_test.py
Purpose: Tests for how the Other repos tab shows the core merge lane (repo_reviews._core_lane and
         the lane rows in _repo). A fake gh answers pr list and a temp file replaces the lane state,
         so nothing touches GitHub or a real file.
Date:    2026-10-14
Run:     python3 repo_reviews_test.py
"""

import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="repo-reviews-lane-"))
STATE = TMP / "lane-state.json"
PRS = TMP / "prs.json"
GH = TMP / "gh"
GH.write_text(
    "#!/usr/bin/env python3\nimport sys\nif sys.argv[1:3] == ['pr', 'list']:\n"
    f"    print(open({str(PRS)!r}).read())\nelse:\n    print('[]')\n"
)
GH.chmod(0o755)
CFG = TMP / "reviews-config.json"
CFG.write_text(
    json.dumps(
        {
            "owner": "owner1",
            "repo_reviews": ["acme/core"],
            "core_lane_repo": "acme/core",
            "repo_labels": {"acme/core": "Core"},
            "autofix_lanes": {"acme/core": "core"},
            "autofix_after": {"core": "It goes back to the core owner's queue."},
        }
    )
)
os.environ["OPSCENTER_REVIEWS_CONFIG"] = str(CFG)
os.environ["CORE_LANE_STATE"] = str(STATE)
os.environ["REPO_REVIEWS_GH_BIN"] = str(GH)
os.environ["REVIEW_ACTED_STORE"] = str(TMP / "acted.json")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import own_lane  # noqa: E402
import repo_reviews as rr  # noqa: E402

own_lane.register(
    "core", STATE
)  # the core lane writes its own-PR fix records into the same state file

REPO = "acme/core"
HEAD = "a" * 40


def now_iso():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pr(conclusion="SUCCESS", head=HEAD):
    return {
        "number": 71,
        "title": "docs: a change",
        "url": "https://github.com/x/y/pull/71",
        "author": {"login": "owner1"},
        "headRefOid": head,
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
        "reviewRequests": [],
        "statusCheckRollup": [
            {"name": "ci", "conclusion": conclusion, "completedAt": "2026-10-14T10:00:00Z"}
        ],
        "createdAt": "2026-10-14T09:00:00Z",
        "updatedAt": "2026-10-14T09:00:00Z",
        "autoMergeRequest": None,
    }


def lane(status, reason, head=HEAD, **top):
    st = {
        "updated": now_iso(),
        "error_count": 0,
        "prs": {"71": {"head": head, "status": status, "reason": reason}},
    }
    st.update(top)
    STATE.write_text(json.dumps(st))


class CoreLaneRows(unittest.TestCase):
    def setUp(self):
        PRS.write_text(json.dumps([pr()]))
        if STATE.exists():
            STATE.unlink()

    def view(self):
        r = rr._repo(REPO)
        return r["needs_me"], r["in_progress"]

    def test_waiting_is_merging_soon(self):
        lane("waiting", "quiet period, head is too new (9 min left)")
        needs, prog = self.view()
        self.assertEqual(needs, [])
        self.assertTrue(prog[0]["state"].startswith("merging soon (lane)"))

    def test_held_needs_me_with_reason(self):
        lane("held", "version v0.31.0 taken by #70, rebase and bump")
        needs, prog = self.view()
        self.assertEqual(prog, [])
        self.assertIn("version v0.31.0 taken by #70", needs[0]["why"])
        self.assertEqual(needs[0]["kind"], "stale")

    def test_absent_state_keeps_old_behaviour(self):
        needs, prog = self.view()
        self.assertEqual(needs[0]["kind"], "stale")  # green 30 minutes and nothing merged it
        self.assertNotIn("lane", needs[0]["why"])

    def test_other_head_ignored(self):
        lane("waiting", "quiet period", head="b" * 40)
        needs, _ = self.view()
        self.assertEqual(needs[0]["kind"], "stale")

    def test_failing_or_dry_run_lane_ignored(self):
        lane("waiting", "quiet period", error_count=3)
        self.assertEqual(rr._core_lane(), {})
        lane("waiting", "quiet period", dry_run=True)
        self.assertEqual(rr._core_lane(), {})

    def test_owner_queue_is_in_progress(self):
        lane("owner", "ready for the core owner (v0.65.0)")
        st = json.loads(STATE.read_text())
        st["prs"]["71"].update(
            version="0.65.0", queue=1, queue_of=3, blocked_by=[], queue_text="next in version order"
        )
        STATE.write_text(json.dumps(st))
        needs, prog = self.view()
        self.assertEqual(needs, [])
        self.assertEqual(prog[0]["state"], "with the core owner: v0.65.0, next in version order")
        self.assertEqual(prog[0]["owner_queue"]["place"], 1)

    def test_core_autofix_running_is_in_progress(self):
        st = {
            "updated": now_iso(),
            "error_count": 0,
            "prs": {"71": {"head": HEAD, "status": "held", "reason": "merge conflict"}},
            "fix": {"71": {"running": {"problem": "merge-conflict", "started": now_iso()}}},
        }
        STATE.write_text(json.dumps(st))
        PRS.write_text(json.dumps([dict(pr(), mergeable="CONFLICTING")]))
        needs, prog = self.view()
        self.assertEqual(needs, [])
        self.assertEqual(prog[0]["state"], "auto-fixing")
        self.assertIn("core owner's queue", prog[0]["autofix"]["text"])

    def test_owner_mode_wait_never_says_merging(self):
        lane("waiting", "required check not reported yet: ci", merge_mode="owner")
        _, prog = self.view()
        self.assertTrue(prog[0]["state"].startswith("lane checking"), prog[0]["state"])

    def test_issue_rows_say_who_moves_next(self):
        def iso(s):
            return dt.datetime.fromtimestamp(s, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        now = 2_000_000_000
        base = {
            "number": 1,
            "title": "t",
            "url": "u",
            "author": {"login": "owner1"},
            "createdAt": iso(now - 86400),
        }
        other = dict(
            base,
            comments=[
                {"author": {"login": "other1"}, "createdAt": iso(now - 3600), "body": "Merge it."}
            ],
        )
        b, row = rr._issue_row("acme/core", other, now)
        self.assertEqual((b, row["kind"]), ("need", "replied"))
        self.assertEqual(row["excerpt"], "Merge it.")
        bot = dict(
            other,
            comments=other["comments"]
            + [{"author": {"login": "github-actions[bot]"}, "createdAt": iso(now)}],
        )
        self.assertEqual(rr._issue_row("acme/core", bot, now)[0], "need")
        mine = dict(base, comments=[])
        b, row = rr._issue_row("acme/core", mine, now)
        self.assertEqual((b, row["state"]), ("waiting", "waiting on acme"))
        old = dict(base, createdAt=iso(now - 9 * 86400), comments=[])
        self.assertEqual(rr._issue_row("acme/core", old, now)[1]["kind"], "quiet")

    def test_red_beats_a_lane_wait(self):
        PRS.write_text(json.dumps([pr(conclusion="FAILURE")]))
        lane("waiting", "checks running: ci")
        needs, _ = self.view()
        self.assertEqual(needs[0]["kind"], "checks")


class NullDefault(unittest.TestCase):
    def setUp(self):
        self.old = os.environ["OPSCENTER_REVIEWS_CONFIG"]
        os.environ["OPSCENTER_REVIEWS_CONFIG"] = str(TMP / "absent.json")
        rr._cache.update(at=0.0, data=None)

    def tearDown(self):
        os.environ["OPSCENTER_REVIEWS_CONFIG"] = self.old
        rr._cache.update(at=0.0, data=None)

    def test_no_config_is_an_empty_page(self):
        got = rr.get(force=True)
        self.assertEqual((got["repos"], got["counts"]["needs_me"]), ([], 0))

    def test_rerun_of_an_unlisted_repo_is_refused(self):
        with self.assertRaises(ValueError):
            rr.rerun({"repo": "core", "pr": 1, "head_sha": HEAD})

    def test_no_owner_means_no_issue_rows(self):
        self.assertEqual(rr._issues("acme/core"), ([], []))


if __name__ == "__main__":
    unittest.main(verbosity=2)
