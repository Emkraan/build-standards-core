"""
other_reviews_test.py
Purpose: The other repo's review page against a fake code host script and an escalations command: the null default is
         an empty page and a 501; an escalated engineer PR needs the owner and a stale escalation head is in
         progress; the owner's PR is ready to merge when the own-PR lane is not running; merge refuses an engineer's
         PR and a red PR; approve is pinned to the head, refuses the owner's own PR and re-verifies an unverified row.
Run:     python3 other_reviews_test.py
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="other-reviews-"))
PRS = TMP / "prs.json"
LIVE = TMP / "live.json"
CALLS = TMP / "calls.log"
GH = TMP / "gh"
GH.write_text(
    "#!/usr/bin/env python3\nimport sys\n"
    f"open({str(CALLS)!r}, 'a').write(' '.join(sys.argv[1:]) + '\\n')\n"
    "a = sys.argv[1:]\n"
    "if a[:2] == ['pr', 'list']:\n"
    f"    print(open({str(PRS)!r}).read() if '--state' in a and a[a.index('--state') + 1] == 'open' else '[]')\n"
    "elif a[:2] == ['pr', 'view']:\n"
    f"    print(open({str(LIVE)!r}).read())\n"
    "else:\n    print('{}')\n"
)
GH.chmod(0o755)
ESC = TMP / "esc.py"
ESCJ = TMP / "esc.json"
ESC.write_text(f"#!/usr/bin/env python3\nprint(open({str(ESCJ)!r}).read())\n")
ESC.chmod(0o755)
CFG = TMP / "reviews-config.json"
CFG.write_text(json.dumps({"owner": "owner1", "other_repo": "acme/other", "other_lane": "other"}))
ENV = dict(
    OPSCENTER_REVIEWS_CONFIG=str(CFG),
    OTHER_REVIEWS_GH_BIN=str(GH),
    REVIEW_ACTED_STORE=str(TMP / "acted.json"),
    OPSCENTER_STATE_DIR=str(TMP / "state"),
)
sys.path.insert(0, str(Path(__file__).resolve().parent))

import importlib  # noqa: E402

o = None
_saved = {}


def setUpModule():
    """The module reads its environment at import: set it, load the module fresh, undo all of it afterwards."""
    global o
    for k in list(ENV) + ["OPSCENTER_ESCALATIONS_CMD"]:
        _saved[k] = os.environ.get(k)
    os.environ.update(ENV)
    os.environ.pop("OPSCENTER_ESCALATIONS_CMD", None)
    import other_reviews
    import review_acted

    _saved["_store"] = review_acted.STORE
    review_acted.STORE = TMP / "acted.json"  # its store path is read at import
    o = importlib.reload(other_reviews)


def tearDownModule():
    import review_acted

    review_acted.STORE = _saved.pop("_store")
    for k, v in _saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


HEAD = "a" * 40
OK = [{"name": "ci", "conclusion": "SUCCESS", "completedAt": "2026-10-14T10:00:00Z"}]


def pr(n, author, head=HEAD, checks=OK, draft=False):
    return {
        "number": n,
        "title": f"change {n}",
        "url": f"https://example.test/pull/{n}",
        "author": {"login": author},
        "headRefOid": head,
        "headRefName": f"b{n}",
        "isDraft": draft,
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
        "reviewDecision": "",
        "statusCheckRollup": checks,
        "createdAt": "2026-10-14T09:00:00Z",
        "updatedAt": "2026-10-14T09:00:00Z",
    }


def live(author, head=HEAD, state="OPEN", checks=OK, draft=False):
    LIVE.write_text(
        json.dumps(
            {
                "state": state,
                "isDraft": draft,
                "headRefOid": head,
                "author": {"login": author},
                "mergeable": "MERGEABLE",
                "statusCheckRollup": checks,
                "title": "t",
            }
        )
    )


class Other(unittest.TestCase):
    def setUp(self):
        PRS.write_text("[]")
        CALLS.write_text("")
        ESCJ.write_text("[]")
        os.environ.pop("OPSCENTER_ESCALATIONS_CMD", None)
        os.environ["OPSCENTER_REVIEWS_CONFIG"] = str(CFG)
        (TMP / "acted.json").unlink(missing_ok=True)
        o._cache.update(at=0.0, data=None)

    def esc(self, rows):
        ESCJ.write_text(json.dumps(rows))
        os.environ["OPSCENTER_ESCALATIONS_CMD"] = str(ESC)

    def test_null_default_is_an_empty_page_and_a_501(self):
        os.environ["OPSCENTER_REVIEWS_CONFIG"] = str(TMP / "none.json")
        got = o.get(force=True)
        self.assertEqual((got["needs_me"], got["in_progress"], got["configured"]), ([], [], False))
        for fn in (o.merge, o.approve, o.decide_fix):
            with self.assertRaises(Exception) as e:
                fn({"pr": 1, "head_sha": HEAD})
            self.assertEqual(e.exception.status, 501)

    def test_an_escalated_engineer_pr_needs_the_owner(self):
        PRS.write_text(json.dumps([pr(5, "eng1"), pr(6, "eng1")]))
        self.esc([{"pr": 5, "reason": "risky", "recommendation": "approve", "head": HEAD[:7]}])
        got = o.get(force=True)
        self.assertEqual([r["pr"] for r in got["needs_me"]], [5])
        self.assertEqual(
            (got["needs_me"][0]["kind"], got["needs_me"][0]["why"]), ("escalated", "risky")
        )
        self.assertEqual([r["pr"] for r in got["in_progress"]], [6])

    def test_an_escalation_on_an_older_head_is_in_progress(self):
        PRS.write_text(json.dumps([pr(5, "eng1", head="b" * 40)]))
        self.esc([{"pr": 5, "reason": "risky", "head": HEAD[:7]}])
        got = o.get(force=True)
        self.assertEqual(got["needs_me"], [])
        self.assertIn("new commits since the escalation", got["in_progress"][0]["state"])

    def test_the_owners_green_pr_is_ready_to_merge_when_the_lane_is_not_running(self):
        PRS.write_text(json.dumps([pr(7, "owner1")]))
        got = o.get(force=True)
        self.assertEqual(
            (got["needs_me"][0]["kind"], got["own_lane_error"] is not None),
            ("ready_to_merge", True),
        )

    def test_an_unreadable_escalation_source_marks_the_row_unknown(self):
        PRS.write_text(json.dumps([pr(5, "eng1")]))
        os.environ["OPSCENTER_ESCALATIONS_CMD"] = str(TMP / "does-not-exist")
        got = o.get(force=True)
        self.assertEqual(got["lane_error"], "escalations unreadable")

    def test_merge_refuses_an_engineers_pr_and_a_red_one(self):
        live("eng1")
        with self.assertRaises(o.ReviewError) as e:
            o.merge({"pr": 5, "head_sha": HEAD})
        self.assertEqual(e.exception.code, 403)
        live(
            "owner1",
            checks=[{"name": "ci", "conclusion": "FAILURE", "completedAt": "2026-10-14T10:00:00Z"}],
        )
        with self.assertRaises(o.ReviewError) as e:
            o.merge({"pr": 5, "head_sha": HEAD})
        self.assertEqual(e.exception.code, 409)
        self.assertNotIn("pr merge", CALLS.read_text())

    def test_merge_of_a_green_owner_pr_is_pinned_to_the_head(self):
        live("owner1")
        out = o.merge({"pr": 7, "head_sha": HEAD})
        self.assertEqual(out["pr"], 7)
        self.assertIn(f"--match-head-commit {HEAD}", CALLS.read_text())

    def test_a_moved_head_a_bad_head_and_a_closed_pr(self):
        live("owner1", head="c" * 40)
        with self.assertRaises(o.ReviewError) as e:
            o.merge({"pr": 7, "head_sha": HEAD})
        self.assertEqual(e.exception.code, 409)
        with self.assertRaises(o.ReviewError) as e:
            o.merge({"pr": 7, "head_sha": "short"})
        self.assertEqual(e.exception.code, 400)
        live("owner1", state="MERGED")
        self.assertTrue(o.merge({"pr": 7, "head_sha": HEAD})["already"])

    def test_approve_refuses_the_owners_own_pr_and_posts_a_pinned_review(self):
        live("owner1")
        with self.assertRaises(o.ReviewError) as e:
            o.approve({"pr": 7, "head_sha": HEAD})
        self.assertEqual(e.exception.code, 403)
        live("eng1")
        out = o.approve({"pr": 5, "head_sha": HEAD})
        self.assertIn("approved #5", out["done"][0])
        self.assertIn(f"commit_id={HEAD}", CALLS.read_text())

    def test_an_unverified_approve_needs_the_escalation_to_be_confirmed(self):
        live("eng1")
        self.esc([])
        with self.assertRaises(o.ReviewError) as e:
            o.approve({"pr": 5, "head_sha": HEAD, "unverified": True})
        self.assertEqual(e.exception.code, 409)
        self.esc([{"pr": 5, "reason": "x", "head": HEAD[:7]}])
        self.assertIn(
            "approved #5", o.approve({"pr": 5, "head_sha": HEAD, "unverified": True})["done"][0]
        )


if __name__ == "__main__":
    unittest.main()
