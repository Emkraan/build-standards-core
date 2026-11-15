"""Rule 2.4 of data-safety-sqlite is reworded and the conditional local-WAL section is registered."""

import json
import unittest

from support import ROOT, load

NEW = [f"data-safety-sqlite.8.{n}" for n in range(1, 5)]


class SqliteWal(unittest.TestCase):
    def setUp(self):
        self.rules = {
            r["id"]: r for r in json.loads((ROOT / "standards/rules.json").read_text())["rules"]
        }
        self.text = (ROOT / "standards/data-safety-sqlite.md").read_text(encoding="utf8")
        self.checker = load("check_rules", "checks/check-rules.py")

    def test_rule_2_4_keeps_the_share_ban_and_adds_the_condition(self):
        r = self.rules["data-safety-sqlite.2.4"]
        self.assertIn("never allowed", r["statement"])
        self.assertIn("network file share", r["statement"])
        self.assertIn("restore test", r["statement"])
        self.assertNotIn("allowed only on local disk.", r["statement"])
        item = self.text.split("4. **Journal mode follows where the file lives.**")[1].split(
            "5. **"
        )[0]
        self.assertIn("never allowed on a network file share", item)
        self.assertIn("restore test", item)

    def test_new_rules_registered_and_present(self):
        for rid in NEW:
            r = self.rules[rid]
            self.assertEqual((r["level"], r["applies_to"]), ("must", ["web"]))
            self.assertTrue(self.checker.section_exists(self.text, rid.split(".", 1)[1]))
        self.assertNotIn("data-safety-sqlite.8.5", self.rules)

    def test_restore_test_is_a_condition_not_a_done_thing(self):
        sec = self.text.split("## 8. Local-disk WAL")[1]
        self.assertIn("Status: settling", sec)
        self.assertIn("has not run", sec)
        self.assertIn("4.54 s against 0.08 s", sec)
        self.assertIn("passes before the DB moves to local WAL", sec)

    def test_what_not_to_do_no_longer_bans_all_cloud_wal(self):
        self.assertNotIn("Do not switch the cloud-hosted DB back to WAL.", self.text)
        self.assertIn("Do not put a DB in WAL on a network file share, ever.", self.text)


if __name__ == "__main__":
    unittest.main()
