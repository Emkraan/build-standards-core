"""
privileged_reviews_test.py
Purpose: The privileged lane against a fake code host and a temp state tree: the null default (no config) is an empty
         page and a 501 on a decision; an approve re-verifies the run and decides the pending deployment; the typed
         confirm, a moved commit, a finished run and a blocked failed apply each refuse; every decision is logged.
Run:     python3 privileged_reviews_test.py
"""

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import review_config  # noqa: E402

HEAD = "a" * 40
KEY = "destroy:77"


class Priv(unittest.TestCase):
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
        (d / "cache").mkdir()
        import live_truth
        import privileged_reviews

        self.live = live_truth
        self.mod = importlib.reload(privileged_reviews)
        self.calls = []
        self.run = {"status": "waiting", "head_sha": HEAD, "run_attempt": 1, "head_branch": "main"}
        self.mod._gh = self.fake_gh
        self._truth_run = live_truth.run
        live_truth.run = lambda repo, rid: {
            "status": "waiting",
            "envs": ["destroy"],
            "head_sha": HEAD,
            "run_attempt": 1,
        }

    def tearDown(self):
        self.live.run = self._truth_run
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.d.cleanup()

    def fake_gh(self, args, timeout=40):
        self.calls.append(args)
        if args[-1].endswith("/pending_deployments"):
            return [{"environment": {"id": 9, "name": "destroy"}}] if "-X" not in args else {}
        if "pending_deployments" in args[-1] or "-X" in args:
            return {}
        return self.run

    def configure(self):
        Path(os.environ["OPSCENTER_REVIEWS_CONFIG"]).write_text(
            json.dumps(
                {
                    "owner": "owner1",
                    "plan_repo": "acme/infra",
                    "privileged_envs": {"destroy": "Destroy", "governance": "Governance"},
                    "typed_confirm": ["destroy"],
                }
            )
        )

    def queue(self, **over):
        it = {
            "key": KEY,
            "environment": "destroy",
            "run_id": 77,
            "run_attempt": 1,
            "head_sha": HEAD,
            "head_branch": "main",
            "status": "pending",
            "confirm_name": "prod-db",
            "assessment": {
                "head_sha": HEAD,
                "risk": {"level": "high"},
                "recommendation": {"action": "review"},
            },
            "plan": {"add": 0, "change": 0, "destroy": 2},
            "first_seen": "2026-10-01T00:00:00Z",
        }
        it.update(over)
        self.mod.STATE.mkdir(parents=True, exist_ok=True)
        self.mod._save({"items": {KEY: it}, "updated": "t"})

    def test_null_default_is_an_empty_page(self):
        got = self.mod.get()
        self.assertEqual(
            (got["pending"], got["recent"], got["secrets"]["status"]), ([], [], "never_run")
        )

    def test_an_unconfigured_decision_is_refused_with_501(self):
        with self.assertRaises(review_config.NotConfigured) as e:
            self.mod.decide({"key": KEY, "head_sha": HEAD}, "approve")
        self.assertEqual(e.exception.status, 501)

    def test_bad_action_is_400(self):
        self.configure()
        with self.assertRaises(self.mod.ReviewError) as e:
            self.mod.decide({}, "nope")
        self.assertEqual(e.exception.code, 400)

    def test_get_labels_the_environment_and_flags_the_typed_confirm(self):
        self.configure()
        self.queue()
        got = self.mod.get()["pending"][0]
        self.assertEqual(
            (got["env_label"], got["typed_confirm"], got["phase"]), ("Destroy", True, "needs_me")
        )

    def test_approve_needs_the_typed_confirm_then_decides_and_logs(self):
        self.configure()
        self.queue()
        with self.assertRaises(self.mod.ReviewError) as e:
            self.mod.decide({"key": KEY, "head_sha": HEAD}, "approve")
        self.assertEqual(e.exception.code, 400)
        out = self.mod.decide({"key": KEY, "head_sha": HEAD, "confirm": "prod-db"}, "approve")
        self.assertEqual((out["status"], out["environment"]), ("approved", "destroy"))
        post = [c for c in self.calls if "-X" in c][0]
        self.assertIn("repos/acme/infra/actions/runs/77/pending_deployments", post)
        self.assertIn("environment_ids[]=9", post)
        q = json.loads(self.mod.QUEUE.read_text())["items"][KEY]
        self.assertEqual((q["status"], q["decided_by"]), ("approved", "owner1"))
        rec = json.loads(self.mod.DECISIONS.read_text().splitlines()[-1])
        self.assertEqual(
            (rec["decision"], rec["lane"], rec["plan"]["destroy"]),
            ("manual_approved", "privileged", 2),
        )

    def test_a_moved_commit_a_finished_run_and_an_unknown_key_refuse(self):
        self.configure()
        self.queue()
        with self.assertRaises(self.mod.ReviewError) as e:
            self.mod.decide({"key": KEY, "head_sha": "b" * 40, "confirm": "prod-db"}, "approve")
        self.assertEqual(e.exception.code, 409)
        self.run["status"] = "completed"
        with self.assertRaises(self.mod.ReviewError) as e:
            self.mod.decide({"key": KEY, "head_sha": HEAD, "confirm": "prod-db"}, "approve")
        self.assertEqual(e.exception.code, 409)
        with self.assertRaises(self.mod.ReviewError) as e:
            self.mod.decide({"key": "destroy:1", "head_sha": HEAD}, "reject")
        self.assertEqual(e.exception.code, 404)
        self.assertFalse([c for c in self.calls if "-X" in c])

    def test_a_blocked_failed_apply_offers_retry_only(self):
        self.configure()
        self.queue(
            status=self.mod.BLOCKED, fingerprint="f1", failed_apply={"run_id": 5, "error": "boom"}
        )
        with self.assertRaises(self.mod.ReviewError) as e:
            self.mod.decide({"key": KEY, "head_sha": HEAD, "confirm": "prod-db"}, "approve")
        self.assertEqual(e.exception.code, 409)
        q = json.loads(self.mod.QUEUE.read_text())
        q["apply_failures"] = {"f1": {"cleared_at": None}}
        self.mod._save(q)
        out = self.mod.decide({"key": KEY, "head_sha": HEAD, "confirm": "prod-db"}, "retry")
        self.assertEqual(out["status"], "approved")
        self.assertEqual(
            json.loads(self.mod.DECISIONS.read_text().splitlines()[-1])["via"], "retry_failed_apply"
        )

    def test_the_guard_can_refuse_an_approve(self):
        self.configure()
        self.queue(pr={"number": 3})

        def guard(num, payload):
            raise ValueError("waits on another PR")

        with self.assertRaises(self.mod.ReviewError) as e:
            self.mod.decide({"key": KEY, "head_sha": HEAD, "confirm": "prod-db"}, "approve", guard)
        self.assertIn("another PR", str(e.exception))


if __name__ == "__main__":
    unittest.main()
