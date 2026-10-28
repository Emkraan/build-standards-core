"""check-rules reads opscenter/applicability.json (ops center prerequisite P3)."""

import json
import unittest

from support import ROOT, Work, load, sh

FORMAT = "build-standards-opscenter-applicability/1"


class Applicability(Work):
    def setUp(self):
        super().setUp()
        self.mod = load("check_rules", "checks/check-rules.py")
        self.ids = {
            r["id"] for r in json.loads((ROOT / "standards/rules.json").read_text())["rules"]
        }

    def problems(self, data):
        f = self.dir / "applicability.json"
        f.write_text(data if isinstance(data, str) else json.dumps(data))
        return self.mod.applicability_problems(f, self.ids)

    def test_passing_fixture(self):
        some = sorted(self.ids)[:3]
        self.assertEqual(self.problems({"format": FORMAT, "rules": some}), [])
        self.assertEqual(self.problems({"format": FORMAT, "rules": []}), [])

    def test_failing_fixture_unknown_id(self):
        bad = self.problems({"format": FORMAT, "rules": [sorted(self.ids)[0], "no-such-doc.9.9"]})
        self.assertEqual(len(bad), 1)
        self.assertIn("no-such-doc.9.9", bad[0])

    def test_other_failures(self):
        rid = sorted(self.ids)[0]
        self.assertTrue(self.problems({"format": FORMAT, "rules": [rid, rid]}))
        self.assertTrue(self.problems({"format": "x/1", "rules": []}))
        self.assertTrue(self.problems({"format": FORMAT, "rules": "all"}))
        self.assertTrue(self.problems({"format": FORMAT, "rules": [3]}))
        self.assertTrue(self.problems("not json"))
        self.assertTrue(self.mod.applicability_problems(self.dir / "missing.json", self.ids))

    def test_published_file_passes_the_check(self):
        self.assertEqual(sh(["python3", ROOT / "checks/check-rules.py"], cwd=ROOT)[0], 0)
        self.assertEqual(self.mod.applicability_problems(self.mod.APPLICABILITY, self.ids), [])

    def test_check_rules_fails_on_a_bad_id(self):
        # end to end: point the module at a failing file and run main
        f = self.dir / "applicability.json"
        f.write_text(json.dumps({"format": FORMAT, "rules": ["no-such-doc.9.9"]}))
        self.mod.APPLICABILITY = f
        self.assertEqual(self.mod.main(), 1)
        f.write_text(json.dumps({"format": FORMAT, "rules": []}))
        self.assertEqual(self.mod.main(), 0)


if __name__ == "__main__":
    unittest.main()
