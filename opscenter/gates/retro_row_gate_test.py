"""The retro row wake gate, run as a process: a failing scan backs off (silent twice, an alert on the third), and a scan
that says nothing to do stays silent."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GATE = Path(__file__).resolve().parent / "retro_row_gate.py"


class RetroGate(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="retro-gate-test-"))
        clean = {k: v for k, v in os.environ.items() if not k.startswith(("OPSCENTER_", "GATE_"))}
        self.env = dict(
            clean,
            GATE_STATE_DIR=str(self.d / "gates"),
            OPSCENTER_ROOT=str(self.d),
            OPSCENTER_STATE_DIR=str(self.d / "state"),
            OPSCENTER_AGENT_HOME=str(self.d / "agent"),
            OPSCENTER_TRACKER_PARAMS=str(self.d / "params.json"),
        )

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def params(self, d):
        (self.d / "params.json").write_text(json.dumps(d))

    def tick(self):
        p = subprocess.run(
            [sys.executable, str(GATE)], capture_output=True, text=True, env=self.env, timeout=120
        )
        self.assertEqual(p.returncode, 0, p.stderr[-400:])
        return p.stdout

    def silent(self, out):
        return out.strip().splitlines()[-1:] == ['{"wakeAgent": false}']

    def test_a_failing_scan_alerts_on_the_third_tick(self):
        self.params(
            {
                "driver_cmd": [sys.executable, "-c", "import sys; sys.exit(1)"],
                "retro": {"parent_page": "1"},
            }
        )
        outs = [self.tick() for _ in range(3)]
        self.assertTrue(self.silent(outs[0]) and self.silent(outs[1]))
        self.assertIn("[RETRO-ROW GATE ALERT]", outs[2])

    def test_a_scan_with_nothing_to_do_is_silent(self):
        empty = self.d / "empty.py"
        empty.write_text(
            "import json\nprint(json.dumps({'result': {'content': [{'text': json.dumps({'results': []})}]}}))\n"
        )
        self.params({"driver_cmd": [sys.executable, str(empty)], "retro": {"parent_page": "1"}})
        self.assertTrue(self.silent(self.tick()))


if __name__ == "__main__":
    unittest.main()
