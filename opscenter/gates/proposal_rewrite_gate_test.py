import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gatehelp  # noqa: E402
import proposal_rewrite_gate as g  # noqa: E402


def iso(delta_min):
    t = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=delta_min)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


class ProposalRewriteGate(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self._old = (g.DASH, g.FEEDBACK, g.PROPOSALS)
        g.DASH = self._d.name
        g.FEEDBACK = os.path.join(self._d.name, "proposal-feedback.json")
        g.PROPOSALS = os.path.join(self._d.name, "docs-proposals.json")

    def tearDown(self):
        g.DASH, g.FEEDBACK, g.PROPOSALS = self._old
        self._d.cleanup()

    def stage(self, feedback, proposals):
        Path(g.FEEDBACK).write_text(json.dumps({"feedback": feedback}))
        Path(g.PROPOSALS).write_text(json.dumps({"proposals": proposals}))

    def prop(self, fp="p1", sha="s1"):
        return {
            "fp": fp,
            "body_sha": sha,
            "target_title": "Page",
            "kind": "update",
            "target_id": "9",
        }

    def test_nothing_open_is_silent(self):
        self.stage({}, [self.prop()])
        self.assertTrue(gatehelp.is_silent(gatehelp.run_gate(g.main)[0]))

    def test_an_open_send_back_is_claimed_and_handed_over(self):
        self.stage({"p1": {"status": "open", "body_sha": "s1", "reason": "shorter"}}, [self.prop()])
        out, code = gatehelp.run_gate(g.main)
        self.assertEqual(code, 0)
        self.assertIn("SEND-BACKS TO REWRITE NOW", out)
        entry = json.loads(out.splitlines()[1])
        self.assertEqual(
            (entry["fp"], entry["note_from_owner"], entry["origin"]), ("p1", "shorter", "nightly")
        )
        self.assertTrue(entry["body_file"].endswith(os.path.join("proposals", "p1.body")))
        claimed = json.loads(Path(g.FEEDBACK).read_text())["feedback"]["p1"]
        self.assertEqual(claimed["status"], "rewriting")
        self.assertIn("claimed_at", claimed)

    def test_a_second_tick_does_not_rewrite_the_same_proposal(self):
        self.stage({"p1": {"status": "open", "body_sha": "s1"}}, [self.prop()])
        gatehelp.run_gate(g.main)
        self.assertTrue(gatehelp.is_silent(gatehelp.run_gate(g.main)[0]))

    def test_a_stale_claim_is_re_offered_and_a_fresh_one_is_not(self):
        self.stage(
            {"p1": {"status": "rewriting", "body_sha": "s1", "claimed_at": iso(30)}}, [self.prop()]
        )
        self.assertIn("SEND-BACKS", gatehelp.run_gate(g.main)[0])
        self.stage(
            {"p1": {"status": "rewriting", "body_sha": "s1", "claimed_at": iso(5)}}, [self.prop()]
        )
        self.assertTrue(gatehelp.is_silent(gatehelp.run_gate(g.main)[0]))

    def test_a_claim_with_no_readable_time_counts_as_stale(self):
        self.stage(
            {"p1": {"status": "rewriting", "body_sha": "s1", "claimed_at": "junk"}}, [self.prop()]
        )
        self.assertIn("SEND-BACKS", gatehelp.run_gate(g.main)[0])

    def test_a_gone_or_restaged_proposal_is_skipped(self):
        self.stage(
            {
                "p1": {"status": "open", "body_sha": "old"},
                "p2": {"status": "open", "body_sha": "s"},
            },
            [self.prop()],
        )
        self.assertTrue(gatehelp.is_silent(gatehelp.run_gate(g.main)[0]))

    def test_other_statuses_are_ignored(self):
        self.stage({"p1": {"status": "done", "body_sha": "s1"}}, [self.prop()])
        self.assertTrue(gatehelp.is_silent(gatehelp.run_gate(g.main)[0]))

    def test_missing_files_are_silent(self):
        self.assertTrue(gatehelp.is_silent(gatehelp.run_gate(g.main)[0]))


if __name__ == "__main__":
    unittest.main()
