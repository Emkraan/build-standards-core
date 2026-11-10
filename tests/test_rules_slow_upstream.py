"""The slow-upstream section of web-api-runtime and the time-of-day rule of web-build are registered."""

import json
import unittest

from support import ROOT, load

API = [f"web-api-runtime.10.{n}" for n in range(1, 6)]


class SlowUpstream(unittest.TestCase):
    def setUp(self):
        self.rules = {
            r["id"]: r for r in json.loads((ROOT / "standards/rules.json").read_text())["rules"]
        }
        self.api = (ROOT / "standards/web-api-runtime.md").read_text(encoding="utf8")
        self.build = (ROOT / "standards/web-build.md").read_text(encoding="utf8")
        self.checker = load("check_rules", "checks/check-rules.py")

    def test_five_api_rules_registered_and_present_in_the_doc(self):
        for rid in API + ["web-build.9.1"]:
            r = self.rules[rid]
            self.assertEqual(r["level"], "must")
            self.assertEqual(r["applies_to"], ["web"])
            self.assertTrue(r["statement"] and r["acceptance"])
        for rid in API:
            self.assertTrue(self.checker.section_exists(self.api, rid.split(".", 1)[1]))
        self.assertTrue(self.checker.section_exists(self.build, "9.1"))

    def test_no_sixth_rule_and_no_unregistered_build_rule(self):
        self.assertNotIn("web-api-runtime.10.6", self.rules)
        self.assertNotIn("web-build.9.2", self.rules)
        self.assertFalse(self.checker.section_exists(self.build, "9.2"))

    def test_section_states_prevents_and_acceptance_per_rule(self):
        body = self.api.split("## 10. Slow upstream queries")[1]
        self.assertEqual(body.count("- Prevents:"), 5)
        self.assertEqual(body.count("- Acceptance (test):"), 5)

    def test_cross_references_the_existing_swr_reader(self):
        body = self.api.split("## 10. Slow upstream queries")[1]
        self.assertIn("createSwrReader", body)
        self.assertIn("web-shell-packages.md", body)
        self.assertIn("web-process-health", body)
        self.assertIn("createSwrReader", (ROOT / "standards/web-shell-packages.md").read_text())

    def test_time_rule_names_the_utc_day_and_its_evidence(self):
        text = self.build.split("### 9.1")[1].split("\n## ")[0]
        self.assertIn("UTC day", text)
        self.assertIn("every evening", text)


if __name__ == "__main__":
    unittest.main()
