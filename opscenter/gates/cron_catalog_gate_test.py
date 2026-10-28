import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cron_catalog_gate as g  # noqa: E402
import gatehelp  # noqa: E402
import gatelib  # noqa: E402


def tool(d, body):
    p = Path(d) / "catalog_fix.py"
    p.write_text(textwrap.dedent(body))
    return str(p)


class CronCatalogGate(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self._old = (gatelib.STATE_DIR, g.TOOL)
        gatelib.STATE_DIR = self._d.name

    def tearDown(self):
        gatelib.STATE_DIR, g.TOOL = self._old
        self._d.cleanup()

    def scan(self, payload, rc=0):
        g.TOOL = tool(
            self._d.name, f"import sys, json\nprint(json.dumps({payload!r}))\nsys.exit({rc})\n"
        )
        return gatehelp.run_gate(g.main)

    def test_no_findings_is_silent(self):
        out, code = self.scan({"ok": True, "findings": [], "areas": ["Ops"]})
        self.assertTrue(gatehelp.is_silent(out))
        self.assertEqual(code, 0)

    def test_findings_wake_with_the_list_and_write_the_file(self):
        found = [{"id": "j1", "name": "misc", "reasons": ["name", "description"]}]
        out, code = self.scan({"ok": True, "findings": found, "areas": ["Ops", "Docs"]})
        self.assertEqual(code, 0)
        self.assertIn("1 enabled job(s) need a name or description fix", out)
        self.assertIn("Areas already in use: Ops, Docs", out)
        self.assertIn("j1 'misc' (name+description)", out)
        written = json.loads(Path(g.out_path()).read_text())
        self.assertEqual(written["findings"], found)

    def test_a_failing_scan_is_silent_until_the_third_failure(self):
        results = []
        for _ in range(3):
            out, _ = self.scan({"ok": False, "error": "no jobs file"}, rc=1)
            results.append(gatehelp.is_silent(out))
        self.assertEqual(results, [True, True, False])
        self.assertIn("no jobs file", out)
        self.assertIn("Do not rename", out)

    def test_unparseable_output_counts_as_a_failure(self):
        g.TOOL = tool(self._d.name, "print('not json')\n")
        for _ in range(2):
            gatehelp.run_gate(g.main)
        out, _ = gatehelp.run_gate(g.main)
        self.assertIn("unparseable scan output", out)

    def test_a_good_scan_resets_the_failure_streak(self):
        self.scan({"ok": False, "error": "x"}, rc=1)
        self.scan({"ok": True, "findings": [], "areas": []})
        self.assertEqual(gatelib.load_health("cron-catalog")["failures"], 0)


if __name__ == "__main__":
    unittest.main()
