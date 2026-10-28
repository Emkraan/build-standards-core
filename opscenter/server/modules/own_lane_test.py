import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import own_lane as ol  # noqa: E402

HEAD = "a" * 40
OLD = "b" * 40


class Fresh(unittest.TestCase):
    def test_fresh_needs_a_recent_pass_and_no_errors(self):
        now = 1_800_000_000
        recent = "2027-01-15T07:59:00Z"  # epoch 1_800_000_000 is 2027-01-15T08:00:00Z
        self.assertTrue(ol.fresh({"updated": recent}, now))
        self.assertFalse(ol.fresh({"updated": recent, "error_count": 2}, now))
        self.assertFalse(ol.fresh({"updated": "2027-01-15T07:00:00Z"}, now))
        self.assertFalse(ol.fresh({}, now))
        self.assertFalse(ol.fresh({"updated": "nonsense"}, now))


class Load(unittest.TestCase):
    def test_load_reads_the_lane_folder_and_register_overrides_it(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "alpha").mkdir()
            (Path(d) / "alpha" / "own-pr-merge.json").write_text(
                json.dumps({"prs": {"1": {"head": HEAD, "status": "merged"}}})
            )
            os.environ["OPSCENTER_LANE_STATE_DIR"] = d
            try:
                self.assertEqual(
                    ol.lane(ol.load("alpha"), 1, HEAD), {"status": "merged", "reason": ""}
                )
                self.assertEqual(ol.load("missing"), {})
                other = Path(d) / "elsewhere.json"
                other.write_text(json.dumps({"updated": "x"}))
                ol.register("beta", other)
                self.assertEqual(ol.load("beta"), {"updated": "x"})
            finally:
                os.environ.pop("OPSCENTER_LANE_STATE_DIR")
                ol.STATE.clear()

    def test_lane_is_per_head(self):
        st = {"prs": {"1": {"head": HEAD, "status": "held", "reason": "needs me: a"}}}
        self.assertEqual(ol.lane(st, 1, HEAD)["status"], "held")
        self.assertIsNone(ol.lane(st, 1, OLD))
        self.assertIsNone(ol.lane(st, 2, HEAD))


class Rules(unittest.TestCase):
    def test_held_rules(self):
        self.assertEqual(ol.held_rules("needs me: a, b ,c"), ["a", "b", "c"])
        self.assertEqual(ol.held_rules("waiting"), [])
        self.assertEqual(ol.held_rules(""), [])

    def test_uncovered_rules_never_cover_the_delete_rules(self):
        reason = "needs me: ai-review-override, plan-destroy, rbac-grant"
        ch = {"rules": ["ai-review-override", "plan-destroy"]}
        self.assertEqual(ol.uncovered_rules(reason, ch), ["plan-destroy", "rbac-grant"])
        self.assertEqual(
            ol.uncovered_rules(reason, None), ["ai-review-override", "plan-destroy", "rbac-grant"]
        )


class Autofix(unittest.TestCase):
    def test_running_wins(self):
        st = {
            "fix": {"1": {"running": {"problem": "red-checks", "started": "2026-10-28T15:00:00Z"}}}
        }
        r = ol.autofix(st, 1, HEAD)
        self.assertEqual(r["state"], "running")
        self.assertIn("red checks", r["text"])

    def test_deferred_only_for_the_same_head(self):
        st = {"fix": {"1": {"deferred": {"head": HEAD, "session": "s1", "since": "t"}}}}
        self.assertEqual(ol.autofix(st, 1, HEAD)["state"], "deferred")
        self.assertIsNone(ol.autofix(st, 1, OLD))

    def test_waiting_on_names_the_prs(self):
        st = {"fix": {"1": {"gave_up": {"head": HEAD, "waits_on": [4, 5, 6], "at": "t"}}}}
        r = ol.autofix(st, 1, HEAD)
        self.assertEqual(r["state"], "waiting_on")
        self.assertIn("#4, #5 and #6", r["text"])

    def test_gave_up_carries_the_decision(self):
        st = {
            "fix": {
                "1": {
                    "gave_up": {
                        "head": HEAD,
                        "why": "conflict",
                        "at": "t",
                        "decision": {"question": "q"},
                    }
                }
            }
        }
        r = ol.autofix(st, 1, HEAD)
        self.assertEqual((r["state"], r["decision"]), ("gave_up", {"question": "q"}))

    def test_a_directed_fix_choice_reads_as_running(self):
        with tempfile.TemporaryDirectory() as d:
            lane = Path(d) / "alpha"
            lane.mkdir()
            (lane / "own-pr-directions.json").write_text(
                json.dumps(
                    {"prs": {"1": {"head": HEAD, "at": "2026-10-28T16:00:00Z", "label": "Rebase"}}}
                )
            )
            os.environ["OPSCENTER_LANE_STATE_DIR"] = d
            try:
                st = {
                    "fix": {
                        "1": {"gave_up": {"head": HEAD, "why": "x", "at": "2026-10-28T15:00:00Z"}}
                    }
                }
                r = ol.autofix(st, 1, HEAD, "alpha")
                self.assertEqual(r["state"], "running")
                self.assertIn("Rebase", r["text"])
                # a choice older than the give up does not count
                st["fix"]["1"]["gave_up"]["at"] = "2026-10-28T17:00:00Z"
                self.assertEqual(ol.autofix(st, 1, HEAD, "alpha")["state"], "gave_up")
            finally:
                os.environ.pop("OPSCENTER_LANE_STATE_DIR")

    def test_rearm(self):
        st = {"fix": {"1": {"rearm": {"head": HEAD, "at": "t"}}}}
        self.assertEqual(ol.autofix(st, 1, HEAD)["state"], "running")

    def test_nothing_recorded(self):
        self.assertIsNone(ol.autofix({}, 1, HEAD))


class Sessions(unittest.TestCase):
    class Live:
        def working(self, lane, n, branch):
            return {"label": "fix-1", "text": "a session is on it"}

    class Idle:
        def working(self, lane, n, branch):
            return None

    class Broken:
        def working(self, lane, n, branch):
            raise RuntimeError("boom")

    gave_up = {"fix": {"1": {"gave_up": {"head": HEAD, "why": "x", "at": "t"}}}}

    def test_a_live_session_beats_a_gave_up_record(self):
        r = ol.autofix_or_session(self.gave_up, 1, HEAD, sessions=self.Live())
        self.assertEqual((r["state"], r["session"]), ("deferred", "fix-1"))

    def test_no_reader_idle_or_broken_keep_the_lane_record(self):
        for s in (None, self.Idle(), self.Broken()):
            self.assertEqual(
                ol.autofix_or_session(self.gave_up, 1, HEAD, sessions=s)["state"], "gave_up"
            )

    def test_a_running_fix_is_not_replaced(self):
        st = {
            "fix": {
                "1": {"running": {"problem": "merge-conflict", "started": "2026-10-28T15:00:00Z"}}
            }
        }
        self.assertEqual(
            ol.autofix_or_session(st, 1, HEAD, sessions=self.Live())["state"], "running"
        )


if __name__ == "__main__":
    unittest.main()
