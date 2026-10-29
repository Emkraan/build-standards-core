"""
tf_reviews_test.py
Purpose: The plan review queue against a fake code host and a temp state tree: the null default is an empty page and a
         501; a code host 5xx on one run is retried and a run that still fails keeps the card pending; an approve
         of the owner's own PR records the one sign-off, a reject revokes it; approve_for_signoff touches only a
         pending card for the exact head.
Run:     python3 tf_reviews_test.py
"""

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lanes"))

import review_config  # noqa: E402
import signoff_store  # noqa: E402

HEAD = "abc"


class Plan(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        d = Path(self.d.name)
        self.saved = {
            k: os.environ.get(k)
            for k in ("TFGATE_STATE_DIR", "TFGATE_CACHE_DIR", "OPSCENTER_REVIEWS_CONFIG")
        }
        os.environ["TFGATE_STATE_DIR"] = str(d / "state")
        os.environ["TFGATE_CACHE_DIR"] = str(d / "cache")
        os.environ["OPSCENTER_REVIEWS_CONFIG"] = str(d / "cfg.json")
        (d / "state").mkdir()
        import tf_reviews

        self.t = importlib.reload(tf_reviews)
        self.t.time.sleep = lambda s: None
        self.posts = {1: 0, 2: 0}

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.d.cleanup()

    def configure(self):
        Path(os.environ["OPSCENTER_REVIEWS_CONFIG"]).write_text(
            json.dumps({"owner": "owner1", "plan_repo": "acme/infra", "plan_env": "plan"})
        )

    def queue(self, **over):
        it = {
            "pr": 349,
            "status": "pending",
            "head_sha": HEAD,
            "run_ids": [1, 2],
            "author": "owner1",
            "hits": [{"fp": "f1"}],
        }
        it.update(over)
        self.t.QUEUE.write_text(json.dumps({"items": {"k": it}}))

    def fake(self, fail_run=None, fail_times=0):
        def gh(args, timeout=40):
            path = args[-1] if args[1] != "-X" else args[3]
            if args[:2] == ["api", "-X"]:
                rid = int(path.split("/runs/")[1].split("/")[0])
                self.posts[rid] += 1
                if rid == fail_run and self.posts[rid] <= fail_times:
                    raise self.t.ReviewError("gh api -X POST: gh: Server Error (HTTP 502)")
                return {}
            if path.endswith("pending_deployments"):
                return [{"environment": {"id": 7, "name": "plan"}}]
            if "/pulls/" in path:
                return {"state": "open", "head": {"sha": HEAD}}
            return {"status": "waiting", "head_sha": HEAD, "path": "x.yml"}

        return gh

    def test_null_default_is_an_empty_page_and_a_501(self):
        got = self.t.get()
        self.assertEqual((got["pending"], got["parked"], got["decisions"]), ([], [], []))
        with self.assertRaises(review_config.NotConfigured) as e:
            self.t.decide(349, "approved")
        self.assertEqual(e.exception.status, 501)

    def test_bad_state_is_400_and_unknown_pr_404(self):
        self.configure()
        self.queue()
        with self.assertRaises(self.t.ReviewError) as e:
            self.t.decide(349, "maybe")
        self.assertEqual(e.exception.code, 400)
        with self.assertRaises(self.t.ReviewError) as e:
            self.t.decide(1, "approved")
        self.assertEqual(e.exception.code, 404)

    def test_retry_recovers_from_a_5xx(self):
        self.configure()
        self.queue(author="someone")
        self.t._gh = self.fake(2, 1)
        self.assertEqual(self.t.decide(349, "approved")["runs"], [1, 2])

    def test_hard_failure_keeps_the_card_pending(self):
        self.configure()
        self.queue()
        self.t._gh = self.fake(2, 99)
        with self.assertRaises(self.t.ReviewError) as c:
            self.t.decide(349, "approved")
        self.assertIn("run 2", str(c.exception))
        self.assertEqual(json.loads(self.t.QUEUE.read_text())["items"]["k"]["status"], "pending")

    def test_a_moved_head_refuses(self):
        self.configure()
        self.queue(head_sha="old")
        self.t._gh = self.fake()
        with self.assertRaises(self.t.ReviewError) as c:
            self.t.decide(349, "approved")
        self.assertEqual(c.exception.code, 409)

    def test_approve_records_the_owner_signoff_and_reject_revokes_it(self):
        self.configure()
        self.queue()
        self.t._gh = self.fake()
        self.t.decide(349, "approved")
        self.assertIsNotNone(signoff_store.active(349, signoff_store.OWN, HEAD))
        item = json.loads(self.t.QUEUE.read_text())["items"]["k"]
        self.assertEqual(
            (item["status"], item["approval_source"], item["approved_fps"]),
            ("approved", "manual", ["f1"]),
        )
        self.queue()
        self.t.decide(349, "rejected")
        self.assertIsNone(signoff_store.active(349, signoff_store.OWN, HEAD))

    def test_someone_elses_pr_records_no_signoff(self):
        self.configure()
        self.queue(author="someone")
        self.t._gh = self.fake()
        self.t.decide(349, "approved")
        self.assertIsNone(signoff_store.active(349, signoff_store.OWN, HEAD))

    def test_approve_for_signoff_touches_only_a_pending_card_for_that_head(self):
        self.configure()
        self.queue()
        self.t._gh = self.fake()
        self.assertIsNone(self.t.approve_for_signoff(349, "other"))
        self.assertIn("approved 2", self.t.approve_for_signoff(349, HEAD))


if __name__ == "__main__":
    unittest.main()
