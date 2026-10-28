"""A consumer declares rules that do not apply to it in standards-local/proofs.json ($not_applicable)."""

import datetime
import json
import unittest

from support import Work, load

TODAY = datetime.date(2026, 10, 27)
REG = {
    "rules": [
        {"id": "rbac", "check": {"kind": "review"}},
        {"id": "rbac.1.1", "check": {"kind": "review"}},
        {"id": "rbac.1.10", "check": {"kind": "review"}},
        {"id": "rbac.2", "check": {"kind": "test"}},
        {"id": "shell.1", "check": {"kind": "review"}},
        {"id": "secrets-and-credentials.1.1", "check": {"kind": "review"}},
        {"id": "automation-safety.1.2", "check": {"kind": "review"}, "applicable_optional": True},
    ]
}


def entry(rule="rbac", **kw):
    e = {"rule": rule, "reason": "no such surface", "date": "2026-10-01", "reviewed_by": "owner"}
    e.update(kw)
    return e


class NotApplicable(Work):
    def setUp(self):
        super().setUp()
        self.st = load("core_status_na", "templates/overlay/scripts/core-status.py")
        (self.dir / "standards-local").mkdir()
        self.st.PROOFS = self.dir / "standards-local" / "proofs.json"
        self.st.repo_root = lambda: self.dir

    def load(self, entries, extra=None):
        self.st.PROOFS.write_text(json.dumps(dict(extra or {}, **{"$not_applicable": entries})))
        return self.st.load_not_applicable(REG, TODAY)

    def test_valid_entry_and_group_prefix_matching(self):
        good, problems = self.load([entry("rbac"), entry("shell", until="2026-12-01")])
        self.assertEqual(problems, [])
        self.assertEqual(good[0]["ids"], {"rbac", "rbac.1.1", "rbac.1.10", "rbac.2"})
        self.assertEqual(good[1]["ids"], {"shell.1"})
        self.assertEqual(good[1]["days_left"], 35)

    def test_prefix_matches_whole_segments_only(self):
        good, problems = self.load([entry("rbac.1.1")])
        self.assertEqual((problems, good[0]["ids"]), ([], {"rbac.1.1"}))

    def test_missing_reason_or_reviewer_or_date(self):
        for bad in ({"reason": " "}, {"reviewed_by": ""}, {"date": "soon"}):
            good, problems = self.load([entry(**bad)])
            self.assertEqual(good, [])
            self.assertEqual(len(problems), 1, bad)

    def test_expired_entry_is_a_problem_and_applies_to_nothing(self):
        good, problems = self.load([entry(until="2026-10-26")])
        self.assertEqual(good, [])
        self.assertIn("expired", problems[0])
        good, problems = self.load([entry(until="2026-10-27")])  # today is still valid
        self.assertEqual((len(good), problems), (1, []))

    def test_unknown_prefix_is_a_problem(self):
        good, problems = self.load([entry("rba"), entry("*")])
        self.assertEqual((good, len(problems)), ([], 2))

    def test_guard_blocks_protected_family_unless_registry_allows(self):
        good, problems = self.load([entry("secrets-and-credentials")])
        self.assertEqual(good, [])
        self.assertIn("protected", problems[0])
        good, problems = self.load([entry("automation-safety")])
        self.assertEqual((len(good), problems), (1, []))

    def test_no_declaration_changes_nothing(self):
        self.st.PROOFS.write_text(json.dumps({"$description": "x"}))
        self.assertEqual(self.st.load_not_applicable(REG, TODAY), ([], []))
        self.st.PROOFS.unlink()
        self.assertEqual(self.st.load_not_applicable(REG, TODAY), ([], []))

    def test_reserved_key_is_not_read_as_a_proof(self):
        (self.dir / "t.py").write_text("core-rule: rbac.2\n")
        self.st.PROOFS.write_text(
            json.dumps({"$not_applicable": [entry()], "rbac.2": {"kind": "test", "ref": "t.py"}})
        )
        good, problems = self.st.load_proofs(REG)
        self.assertEqual((sorted(good), problems), (["rbac.2"], []))

    def test_only_unverified_rules_are_set_aside(self):
        na = {"rbac.2": {"reason": "r"}}
        self.assertTrue(self.st.na_applies("unverified", "rbac.2", na))
        for kept in ("proved", "attested", "pass", "fail", "excepted", "waived"):
            self.assertFalse(self.st.na_applies(kept, "rbac.2", na), kept)
        self.assertFalse(self.st.na_applies("unverified", "shell.1", na))


if __name__ == "__main__":
    unittest.main()
