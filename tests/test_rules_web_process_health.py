"""The web-process-health standard is registered rule by rule, listed in the README and cross-linked."""

import json
import unittest

from support import ROOT, load

DOC = "web-process-health"
IDS = [f"{DOC}.1.{n}" for n in range(1, 5)]


class WebProcessHealth(unittest.TestCase):
    def setUp(self):
        self.rules = {
            r["id"]: r for r in json.loads((ROOT / "standards/rules.json").read_text())["rules"]
        }
        self.text = (ROOT / "standards" / f"{DOC}.md").read_text(encoding="utf8")
        self.checker = load("check_rules", "checks/check-rules.py")

    def test_four_rules_registered_with_every_field(self):
        for rid in IDS:
            r = self.rules[rid]
            self.assertEqual(r["ref"], rid.replace(".1.", ".md 1.", 1))
            self.assertEqual(r["level"], "must")
            self.assertEqual(r["applies_to"], ["web"])
            self.assertTrue(r["statement"] and r["acceptance"] and r["title"])
            self.assertTrue(self.checker.section_exists(self.text, rid.split(".", 1)[1]))

    def test_no_unregistered_fifth_rule(self):
        self.assertNotIn(f"{DOC}.1.5", self.rules)
        self.assertFalse(self.checker.section_exists(self.text, "1.5"))

    def test_each_rule_states_prevents_evidence_and_acceptance(self):
        body = self.text.split("## 1. Rules")[1].split("## 2.")[0]
        for line in ("Prevents:", "Evidence:", "Acceptance ("):
            self.assertEqual(body.count(f"- {line}"), 4, line)

    def test_measured_evidence_and_cross_references(self):
        self.assertIn("729,682 ms", self.text)
        self.assertIn("633 ms", self.text)
        self.assertIn("10 minutes", self.text)
        for link in ("web-shell-server.md", "web-shell-packages.md", "data-safety-sqlite.md"):
            self.assertIn(f"]({link}", self.text)

    def test_listed_in_the_readme_table(self):
        readme = (ROOT / "README.md").read_text(encoding="utf8")
        self.assertIn(f"| `standards/{DOC}.md` |", readme)


if __name__ == "__main__":
    unittest.main()
