"""The standby-slot deploy, the polling post-swap smoke and the slot reaper are registered rules."""

import json
import unittest

from support import ROOT, load

IDS = [f"ci-cd-release.6.{n}" for n in (2, 3, 4)]


class DeploySlots(unittest.TestCase):
    def setUp(self):
        self.rules = {
            r["id"]: r for r in json.loads((ROOT / "standards/rules.json").read_text())["rules"]
        }
        self.text = (ROOT / "standards/ci-cd-release.md").read_text(encoding="utf8")
        self.checker = load("check_rules", "checks/check-rules.py")

    def test_rules_registered_and_the_doc_has_each_paragraph(self):
        for rid in IDS:
            r = self.rules[rid]
            self.assertEqual(r["level"], "must")
            self.assertTrue(r["statement"] and r["acceptance"])
            self.assertTrue(self.checker.section_exists(self.text, rid.split(".", 1)[1]))
            self.assertIn(f"**{rid.split('.', 1)[1]} ", self.text)
        self.assertNotIn("ci-cd-release.6.5", self.rules)

    def test_existing_smoke_rule_is_kept(self):
        self.assertIn("ci-cd-release.6.1", self.rules)
        self.assertIn("**6.1 The post-deploy smoke retries", self.text)

    def test_smoke_rule_keeps_no_list_and_names_the_500(self):
        para = self.text.split("**6.3 ")[1].split("**6.4 ")[0]
        self.assertIn("keeps no list", para)
        self.assertIn("a 500", para)
        self.assertIn("Evidence:", para)

    def test_reaper_does_not_trust_the_deploy_workflow(self):
        para = self.text.split("**6.4 ")[1].split("\n## ")[0]
        self.assertIn("not a step of the deploy workflow", para)
        self.assertIn("never from a record the deploy wrote", para)
        self.assertIn("Evidence:", para)


if __name__ == "__main__":
    unittest.main()
