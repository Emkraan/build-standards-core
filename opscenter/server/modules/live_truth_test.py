"""
live_truth_test.py
Purpose: live_truth against a fake gh: the cold read blocks once and is cached, an unknown read is None
         (never an exception), a failed refresh keeps the last good value, invalidate drops everything.
Run:     python3 live_truth_test.py
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import live_truth as lt  # noqa: E402


class LiveTruth(unittest.TestCase):
    def setUp(self):
        lt.invalidate()
        self._gh = lt._gh
        self.calls = []

    def tearDown(self):
        lt._gh = self._gh
        lt.invalidate()

    def test_pr_heads_maps_numbers_to_heads_and_is_cached(self):
        def fake(args, timeout=30):
            self.calls.append(args)
            return [{"number": 7, "headRefOid": "a" * 40}, {"number": "9", "headRefOid": "b" * 40}]

        lt._gh = fake
        self.assertEqual(lt.pr_heads("acme/repo"), {7: "a" * 40, 9: "b" * 40})
        self.assertEqual(lt.pr_heads("acme/repo"), {7: "a" * 40, 9: "b" * 40})
        self.assertEqual(len(self.calls), 1)

    def test_an_unreadable_fact_is_unknown_not_an_error(self):
        def boom(args, timeout=30):
            raise RuntimeError("no network")

        lt._gh = boom
        self.assertIsNone(lt.pr_heads("acme/repo"))
        self.assertIsNone(lt.run("acme/repo", 5))

    def test_run_reads_the_pending_environments_only_when_waiting(self):
        def fake(args, timeout=30):
            if args[-1].endswith("/pending_deployments"):
                return [{"environment": {"name": "dev"}}, {"environment": {"name": "dev"}}]
            return {"status": "waiting", "head_sha": "c" * 40, "run_attempt": 2, "head_branch": "x"}

        lt._gh = fake
        got = lt.run("acme/repo", 5)
        self.assertEqual((got["status"], got["envs"], got["run_attempt"]), ("waiting", ["dev"], 2))
        lt.invalidate()

        def done(args, timeout=30):
            return {"status": "completed", "head_sha": "c" * 40}

        lt._gh = done
        self.assertEqual(lt.run("acme/repo", 5)["envs"], [])

    def test_a_failed_refresh_keeps_the_last_good_value_for_a_while(self):
        lt._gh = lambda args, timeout=30: [{"number": 1, "headRefOid": "d" * 40}]
        self.assertEqual(lt.pr_heads("acme/repo"), {1: "d" * 40})

        def boom(args, timeout=30):
            raise RuntimeError("down")

        lt._gh = boom
        lt._refresh(("heads", "acme/repo"), lt._fetch_heads, "acme/repo")
        self.assertEqual(lt._mem[("heads", "acme/repo")]["val"], {1: "d" * 40})

    def test_the_gh_binary_is_not_a_hardcoded_path(self):
        self.assertNotIn("/opt/homebrew", Path(lt.__file__).read_text())


if __name__ == "__main__":
    unittest.main()
