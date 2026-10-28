import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gatehelp  # noqa: E402
import gatelib  # noqa: E402
import sprint_close_gate as g  # noqa: E402


class SprintCloseGate(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        d = Path(self._d.name)
        self._old = (gatelib.STATE_DIR, g.SCANNER, g.PAYLOAD, g.STATE, g.DECISIONS)
        gatelib.STATE_DIR = str(d / "gate")
        g.SCANNER = str(d / "scan.py")
        g.PAYLOAD = str(d / "payload.json")
        g.STATE = str(d / "state.json")
        g.DECISIONS = str(d / "needs-me.json")

    def tearDown(self):
        gatelib.STATE_DIR, g.SCANNER, g.PAYLOAD, g.STATE, g.DECISIONS = self._old
        self._d.cleanup()

    def scanner(self, payload, rc=0, raw=None):
        text = raw if raw is not None else json.dumps(payload)
        Path(g.SCANNER).write_text(f"import sys\nsys.stdout.write({text!r})\nsys.exit({rc})\n")

    def ticket(self, key, **kw):
        t = {
            "key": key,
            "status": "In Progress",
            "summary": "s",
            "commits": [],
            "prs": [],
            "open_prs": [],
            "decision_lines": [],
        }
        t.update(kw)
        return t

    def test_no_change_and_no_decision_is_silent(self):
        self.scanner({"tickets": [self.ticket("T-1")], "fingerprint_changed": []})
        self.assertTrue(gatehelp.is_silent(gatehelp.run_gate(g.main)[0]))

    def test_new_evidence_wakes_with_the_payload_file_and_the_commit_step(self):
        self.scanner(
            {
                "sprint": "S9",
                "tickets": [self.ticket("T-1", commits=[1, 2])],
                "fingerprint_changed": ["T-1"],
            }
        )
        out, code = gatehelp.run_gate(g.main)
        self.assertEqual(code, 0)
        self.assertIn("sprint S9, 1 ticket(s) with new evidence: T-1", out)
        self.assertIn("--commit", out)
        self.assertIn("commits 2", out)
        self.assertEqual(json.loads(Path(g.PAYLOAD).read_text())["needs_me_decisions"], [])

    def test_a_skipped_ticket_never_wakes(self):
        self.scanner(
            {"tickets": [self.ticket("T-1", skip_reason="closed")], "fingerprint_changed": ["T-1"]}
        )
        self.assertTrue(gatehelp.is_silent(gatehelp.run_gate(g.main)[0]))

    def test_possible_evidence_under_other_keys_is_listed(self):
        t = self.ticket("T-1", candidate_evidence=[{"key": "T-9", "commits": 3}])
        self.scanner({"tickets": [t], "fingerprint_changed": ["T-1"]})
        self.assertIn("POSSIBLE EVIDENCE under other keys", gatehelp.run_gate(g.main)[0])
        self.assertIn("T-9 (3 commits)", gatehelp.run_gate(g.main)[0])

    def decide(self, key="T-1", question="q", at="2026-10-28T10:00:00Z", **kw):
        Path(g.DECISIONS).write_text(
            json.dumps({key: dict({"question": question, "at": at, "decision": "close"}, **kw)})
        )
        Path(g.STATE).write_text(json.dumps({"tickets": {key: {"needs_me": {"question": "q"}}}}))

    def test_an_unapplied_owner_decision_wakes_even_with_no_new_evidence(self):
        self.scanner({"tickets": [self.ticket("T-1")], "fingerprint_changed": []})
        self.decide(note="done")
        out, _ = gatehelp.run_gate(g.main)
        self.assertIn("OWNER DECISION T-1: close", out)
        self.assertIn("owner note: done", out)

    def test_an_applied_or_stale_question_decision_is_not_pending(self):
        self.scanner({"tickets": [self.ticket("T-1")], "fingerprint_changed": []})
        self.decide(question="an older question")
        self.assertTrue(gatehelp.is_silent(gatehelp.run_gate(g.main)[0]))
        self.decide()
        Path(g.STATE).write_text(
            json.dumps(
                {
                    "tickets": {
                        "T-1": {
                            "needs_me": {"question": "q"},
                            "decision_applied": {"at": "2026-10-28T10:00:00Z"},
                        }
                    }
                }
            )
        )
        self.assertTrue(gatehelp.is_silent(gatehelp.run_gate(g.main)[0]))

    def test_a_decision_for_a_closed_ticket_is_ignored(self):
        self.scanner(
            {"tickets": [self.ticket("T-1", skip_reason="closed")], "fingerprint_changed": []}
        )
        self.decide()
        self.assertTrue(gatehelp.is_silent(gatehelp.run_gate(g.main)[0]))

    def test_scanner_failures_back_off_and_the_second_one_wakes(self):
        self.scanner({}, rc=3)
        first = gatehelp.run_gate(g.main)[0]
        second = gatehelp.run_gate(g.main)[0]
        self.assertTrue(gatehelp.is_silent(first))
        self.assertIn("scanner is failing", second)

    def test_non_json_and_tracker_errors_are_failures_not_wakes_on_the_first_tick(self):
        self.scanner(None, raw="not json")
        self.assertTrue(gatehelp.is_silent(gatehelp.run_gate(g.main)[0]))
        self.assertIn("not JSON", gatehelp.run_gate(g.main)[0])
        self.scanner({"error": "tracker 502"})
        gatelib.save_health("sprint-close", {"failures": 0, "last_alert_epoch": 0})
        gatehelp.run_gate(g.main)
        self.assertIn("tracker 502", gatehelp.run_gate(g.main)[0])


if __name__ == "__main__":
    unittest.main()
