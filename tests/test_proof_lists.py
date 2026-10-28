"""A rule's value in standards-local/proofs.json may be a list of records (a test plus a dated review)."""

import datetime
import json
import unittest

from support import Work, load

TODAY = datetime.date(2026, 10, 27)
REG = {
    "rules": [
        {"id": "a.1", "check": {"kind": "review"}},
        {"id": "a.2", "check": {"kind": "test"}},
        {"id": "a.3", "check": {"kind": "review"}, "requires_review": True},
    ]
}
RULES = {r["id"]: r for r in REG["rules"]}


def review(date="2026-10-01", **kw):
    return dict(
        {"kind": "review", "ref": "docs/review.md", "date": date, "reviewed_by": "owner"}, **kw
    )


def test_rec(rid):
    return {"kind": "test", "ref": f"tests/{rid}.py"}


class ProofLists(Work):
    def setUp(self):
        super().setUp()
        self.st = load("core_status_pl", "templates/overlay/scripts/core-status.py")
        (self.dir / "standards-local").mkdir()
        (self.dir / "docs").mkdir()
        (self.dir / "tests").mkdir()
        (self.dir / "docs" / "review.md").write_text("reviewed\n")
        for rid in RULES:
            (self.dir / "tests" / f"{rid}.py").write_text(f"# core-rule: {rid}\n")
        self.st.PROOFS = self.dir / "standards-local" / "proofs.json"
        self.st.repo_root = lambda: self.dir

    def load(self, data):
        self.st.PROOFS.write_text(json.dumps(data))
        return self.st.load_proofs(REG, TODAY)

    def status(self, rid, data):
        good, problems = self.load(data)
        proof = good.get(rid)
        return (self.st.proof_status(RULES[rid], proof) if proof else (None, "")), problems

    def test_single_object_form_is_unchanged(self):
        (st, _), problems = self.status("a.2", {"a.2": test_rec("a.2")})
        self.assertEqual((st, problems), ("proved", []))
        (st, _), problems = self.status("a.1", {"a.1": review()})
        self.assertEqual((st, problems), ("attested", []))

    def test_test_alone_stays_proved(self):
        (st, _), _ = self.status("a.2", {"a.2": [test_rec("a.2")]})
        self.assertEqual(st, "proved")

    def test_review_alone_stays_attested(self):
        (st, _), problems = self.status("a.1", {"a.1": [review()]})
        self.assertEqual((st, problems), ("attested", []))

    def test_test_and_review_together_are_proved_and_the_review_is_noted(self):
        data = {"a.2": [review(), test_rec("a.2")]}
        (st, note), problems = self.status("a.2", data)
        self.assertEqual((st, problems), ("proved", []))
        self.assertIn("review: docs/review.md", note)

    def test_review_companion_is_not_weaker_than_a_test_rule(self):
        _, problems = self.load({"a.2": [test_rec("a.2"), review()]})
        self.assertEqual(problems, [])
        _, problems = self.load({"a.2": review()})
        self.assertIn("weaker than", problems[0])

    def test_requires_review_needs_the_review_too(self):
        (st, note), _ = self.status("a.3", {"a.3": [test_rec("a.3")]})
        self.assertEqual(st, "unverified")
        self.assertIn("review", note)
        (st, _), _ = self.status("a.3", {"a.3": [test_rec("a.3"), review()]})
        self.assertEqual(st, "proved")

    def test_expired_review_is_a_problem_and_the_test_counts_unless_review_is_required(self):
        old = review(date="2025-01-01")
        (st, _), problems = self.status("a.2", {"a.2": [test_rec("a.2"), old]})
        self.assertEqual(st, "proved")
        self.assertIn("days old", problems[0])
        self.assertIn("a.2[1]", problems[0])
        (st, _), problems = self.status("a.3", {"a.3": [test_rec("a.3"), old]})
        self.assertEqual(st, "unverified")
        self.assertEqual(len(problems), 1)

    def test_malformed_entries_are_problem_lines(self):
        good, problems = self.load({"a.2": [test_rec("a.2"), "oops", {"kind": "test"}]})
        self.assertEqual(good["a.2"]["kind"], "test")
        self.assertEqual(len(problems), 2)
        self.assertTrue(all("needs kind" in p for p in problems))
        good, problems = self.load({"a.2": []})
        self.assertEqual((good, len(problems)), ({}, 1))
        good, problems = self.load({"a.2": ["oops"]})
        self.assertEqual((good, len(problems)), ({}, 1))

    def test_reserved_keys_are_not_read_as_proofs(self):
        data = {
            "$description": "x",
            "$max_review_age_days": 30,
            "$not_applicable": [
                {"rule": "a", "reason": "r", "date": "2026-10-01", "reviewed_by": "o"}
            ],
            "a.2": [test_rec("a.2")],
        }
        good, problems = self.load(data)
        self.assertEqual((sorted(good), problems), (["a.2"], []))


if __name__ == "__main__":
    unittest.main()
