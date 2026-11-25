"""settings_inventory_test.py - the settings table matches the code.

Every case uses synthetic source or reads the source tree, never a real state tree.
"""

from __future__ import annotations

import unittest

import settings_inventory as si


class ReadsInSource(unittest.TestCase):
    def reads(self, source):
        return dict(si.reads_in_source(source))

    def test_get_with_default_and_or_default(self):
        got = self.reads(
            "import os\\n"
            "A = os.environ.get('OPSCENTER_AAAA', '/x')\\n"
            "B = os.environ.get('OPSCENTER_BBBB') or paths.state_dir() / 'b.json'\\n"
            "C = os.environ['OPSCENTER_CCCC']\\n"
            "D = os.getenv('OPSCENTER_DDDD')\\n".replace("\\n", "\n")
        )
        self.assertEqual(got["OPSCENTER_AAAA"], "'/x'")
        self.assertEqual(got["OPSCENTER_BBBB"], "paths.state_dir() / 'b.json'")
        self.assertEqual(got["OPSCENTER_CCCC"], "(none)")
        self.assertEqual(got["OPSCENTER_DDDD"], "(none)")

    def test_helpers_that_take_a_name(self):
        got = self.reads(
            "x = op.load('OPSCENTER_PROV_PROVIDER')\n"
            "y = enabled('OPSCENTER_SWITCH')\n"
            "z = which('gh', 'OPSCENTER_GH_BINX')\n"
            "w = which('git', override_env='OPSCENTER_GIT_BINX')\n"
        )
        self.assertEqual(
            sorted(got),
            [
                "OPSCENTER_GH_BINX",
                "OPSCENTER_GIT_BINX",
                "OPSCENTER_PROV_PROVIDER",
                "OPSCENTER_SWITCH",
            ],
        )

    def test_lowercase_and_short_names_are_not_settings(self):
        self.assertEqual(
            self.reads("import os\nx = os.environ.get('home')\ny = os.environ.get('AB')\n"), {}
        )

    def test_state_column(self):
        self.assertEqual(si.under_state(["paths.dashboard_dir() / 'a.json'"]), "yes")
        self.assertEqual(si.under_state(["Path.home() / '.opscenter'"]), "no, a path")
        self.assertEqual(si.under_state(["'90'"]), "-")
        self.assertEqual(si.under_state(["(none)"]), "-")
        self.assertEqual(si.under_state(["x"], "OPSCENTER_STATE_DIR"), "is the state dir")


class TableMatchesCode(unittest.TestCase):
    def test_settings_file_is_current(self):
        """A new setting must be listed: the committed table is what the code says (rewrite it with --write)."""
        have = si.OUT_FILE.read_text(encoding="utf-8") if si.OUT_FILE.exists() else ""
        self.assertEqual(
            have,
            si.render(),
            "opscenter/SETTINGS.md is stale: python3 opscenter/tools/settings_inventory.py --write",
        )

    def test_the_scan_found_the_settings_and_could_not_pass_by_finding_none(self):
        table = si.collect()
        self.assertGreaterEqual(len(table), 100, "the scan found too few settings to trust")
        for name in (
            "OPSCENTER_STATE_DIR",
            "OPSCENTER_ROOT",
            "OPSCENTER_AGENT_HOME",
            "OPSCENTER_LANE_STATE_DIR",
        ):
            self.assertIn(name, table)

    def test_design_points_at_the_table(self):
        design = (si.OPSCENTER / "DESIGN.md").read_text(encoding="utf-8")
        self.assertTrue("SETTINGS.md" in design, "DESIGN.md must point at SETTINGS.md")


if __name__ == "__main__":
    unittest.main()
