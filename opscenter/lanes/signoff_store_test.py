import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import signoff_store as so  # noqa: E402

H1 = {"reason": "changes .github/ x: a", "fp": "fp1", "cfp": "cf1", "path": ".github/a.yml"}
H2 = {"reason": "changes CODEOWNERS: b", "fp": "fp2", "cfp": "cf2", "path": ".github/CODEOWNERS"}


class SignoffStore(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self._old = os.environ.get("TFGATE_STATE_DIR")
        os.environ["TFGATE_STATE_DIR"] = self._d.name

    def tearDown(self):
        if self._old is None:
            os.environ.pop("TFGATE_STATE_DIR", None)
        else:
            os.environ["TFGATE_STATE_DIR"] = self._old
        self._d.cleanup()

    def test_record_keeps_the_plan_facts_and_the_extra_keys_at_the_top(self):
        plan = {
            "status": "completed",
            "resources": [{"address": "a.role_assignment_x", "action": "create"}],
        }
        facts = so.plan_facts(plan)
        self.assertEqual(
            (facts["final"], facts["unverifiable"], facts["grants"]),
            (True, False, ["a.role_assignment_x"]),
        )
        self.assertEqual(facts["resources"], [["a.role_assignment_x", "create"]])
        so.record(
            7,
            "a" * 40,
            so.OWN,
            "approve_merge",
            [H1],
            facts,
            extra={"apply_ok": True, "confirm_name": None},
        )
        rec = so.active(7)
        self.assertEqual(
            (rec["apply_ok"], rec["plan"]["grants"], rec["extra"]["apply_ok"]),
            (True, ["a.role_assignment_x"], True),
        )

    def test_a_missing_or_errored_plan_is_unverifiable(self):
        self.assertEqual(
            (so.plan_facts(None)["final"], so.plan_facts(None)["unverifiable"]), (False, True)
        )
        self.assertTrue(so.plan_facts({"status": "completed", "errors": ["x"]})["unverifiable"])

    def test_confirm_needed_names_the_root_of_a_delete_or_replace(self):
        plan = {
            "resources": [
                {"address": "a.b", "action": "create"},
                {"address": "c.d", "action": "delete", "root": "apps/foo"},
            ]
        }
        self.assertEqual(so.confirm_needed(plan, 7), "apps/foo")
        self.assertIsNone(
            so.confirm_needed({"resources": [{"address": "a.b", "action": "create"}]}, 7)
        )
        self.assertIsNone(so.confirm_needed(None, 7))

    def test_record_and_active(self):
        so.record(7, "a" * 40, so.OWN, "approve_merge", [H1])
        rec = so.active(7)
        self.assertEqual(
            (rec["head_sha"], rec["source"], rec["lane"]), ("a" * 40, "approve_merge", so.OWN)
        )
        self.assertIsNone(so.active(8))
        self.assertIsNone(so.active(7, lane=so.ENGINEER))

    def test_an_exact_head_is_required_when_asked(self):
        so.record(7, "a" * 40, so.ENGINEER, "plan_card", [H1])
        self.assertIsNotNone(so.active(7, so.ENGINEER, head_sha="a" * 40))
        self.assertIsNone(so.active(7, so.ENGINEER, head_sha="b" * 40))

    def test_revoke_hides_but_keeps_the_history(self):
        so.record(7, "a" * 40, so.OWN, "approve_merge", [H1])
        self.assertTrue(so.revoke(7, "owner"))
        self.assertIsNone(so.active(7))
        self.assertFalse(so.revoke(7, "owner"))
        data = json.loads((Path(self._d.name) / "pr-signoffs.json").read_text())
        self.assertTrue(data["prs"]["7"][0]["revoked"])

    def test_history_is_bounded_and_the_newest_wins(self):
        for i in range(so.KEEP_PER_PR + 4):
            so.record(7, f"{i:040d}", so.OWN, "approve_merge", [H1])
        data = json.loads((Path(self._d.name) / "pr-signoffs.json").read_text())
        self.assertEqual(len(data["prs"]["7"]), so.KEEP_PER_PR)
        self.assertEqual(so.active(7)["head_sha"], f"{so.KEEP_PER_PR + 3:040d}")

    def test_the_file_is_private(self):
        so.record(7, "a" * 40, so.OWN, "x", [])
        self.assertEqual(
            oct((Path(self._d.name) / "pr-signoffs.json").stat().st_mode & 0o777), "0o600"
        )

    def test_unknown_lane_is_refused(self):
        with self.assertRaises(ValueError):
            so.record(7, "a" * 40, "other", "x", [])

    def test_a_damaged_file_reads_as_empty(self):
        (Path(self._d.name) / "pr-signoffs.json").write_text("{nope")
        self.assertIsNone(so.active(7))
        so.record(7, "a" * 40, so.OWN, "x", [H1])
        self.assertIsNotNone(so.active(7))

    def test_covers_by_fingerprint(self):
        rec = so.record(7, "a" * 40, so.OWN, "x", [H1, H2])
        self.assertTrue(so.covers(rec, H1))
        self.assertTrue(so.covers(rec, dict(H2)))
        self.assertFalse(so.covers(rec, dict(H1, fp="other", cfp="other")))
        self.assertFalse(so.covers(rec, dict(H1, fp=None)))
        self.assertFalse(so.covers(None, H1))

    def test_a_github_file_is_covered_across_rules_by_content(self):
        policy_hit = {
            "rule": "github-dir",
            "reason": "changes .github/ (workflows)",
            "fp": "engfp",
            "cfp": "cf1",
            "path": ".github/a.yml",
        }
        rec = so.record(7, "a" * 40, so.OWN, "x", [policy_hit])
        self.assertTrue(so.covers(rec, H1))  # same file content, different fingerprint
        self.assertFalse(so.covers(rec, dict(H1, cfp="changed")))
        self.assertFalse(so.covers(rec, H2))  # the cross cover does not stretch to other rules


if __name__ == "__main__":
    unittest.main()
