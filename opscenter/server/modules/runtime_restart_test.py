"""
runtime_restart_test.py
Purpose: The restart card against a scratch script: no script is an empty card and a 501 on a write; a configured script's
         status is shaped into an alert (pending, failed, stale), a request and a cancel reach it, a bad action is
         refused, and an unloadable script degrades to an error on the card instead of raising.
Run:     python3 runtime_restart_test.py
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import runtime_restart as rr  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="runtime-restart-"))
SCRIPT = TMP / "restart.py"
SCRIPT.write_text(
    "STATE = {'pending': None, 'last': None, 'stale': False, 'busy': [], 'safe': True}\n"
    "CALLS = []\n"
    "def status():\n    return dict(STATE)\n"
    "def request(mode, note, who):\n    CALLS.append((mode, note, who)); STATE['pending'] = mode\n"
    "def cancel():\n    CALLS.append('cancel'); STATE['pending'] = None\n"
)


class Card(unittest.TestCase):
    def setUp(self):
        os.environ.pop("OPSCENTER_RUNTIME_RESTART_SCRIPT", None)
        rr._mod.update(path=None, obj=None)

    def test_no_script_is_an_empty_card_and_a_501(self):
        self.assertEqual(rr.get(), {"alert": None, "busy": [], "safe": False, "configured": False})
        with self.assertRaises(rr.NotConfigured) as e:
            rr.post({"action": "now"})
        self.assertEqual(e.exception.status, 501)

    def test_a_bad_action_is_refused_before_anything_loads(self):
        with self.assertRaises(ValueError):
            rr.post({"action": "reboot"})

    def test_request_cancel_and_the_alert_shapes(self):
        os.environ["OPSCENTER_RUNTIME_RESTART_SCRIPT"] = str(SCRIPT)
        self.assertIsNone(rr.get()["alert"])
        self.assertEqual(rr.post({"action": "idle"})["alert"], "pending")
        self.assertIsNone(rr.post({"action": "cancel"})["alert"])
        mod = rr._mod["obj"]
        self.assertEqual(
            mod.CALLS, [("idle", "Requested from the Ops Center", "ops-center"), "cancel"]
        )
        mod.STATE["last"] = {"ok": False}
        self.assertEqual(rr.get()["alert"], "failed")
        mod.STATE["last"] = {"ok": False, "refused": True}
        mod.STATE["stale"] = True
        self.assertEqual(rr.get()["alert"], "stale")

    def test_an_unloadable_script_is_an_error_on_the_card(self):
        os.environ["OPSCENTER_RUNTIME_RESTART_SCRIPT"] = str(TMP / "missing.py")
        got = rr.get()
        self.assertEqual((got["alert"], got["configured"]), (None, True))
        self.assertIn("cannot load", got["error"])


if __name__ == "__main__":
    unittest.main()
