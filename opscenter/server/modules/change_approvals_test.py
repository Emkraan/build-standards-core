import importlib
import json
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

FAKE = textwrap.dedent(
    """
    import json, os, sys
    open(os.environ["FAKE_LOG"], "a").write(sys.argv[2] + "\\n")
    if os.environ.get("FAKE_FAIL"):
        sys.exit(3)
    print(json.dumps({"ok": True, "detail": "done"}))
    """
)


class Approvals(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="approvals-"))
        self._env = dict(os.environ)
        for k in ("OPSCENTER_APPROVALS_CMD", "OPSCENTER_TRACKER", "FAKE_FAIL"):
            os.environ.pop(k, None)
        os.environ.update(
            OPSCENTER_STATE_DIR=str(self.d / "state"), FAKE_LOG=str(self.d / "calls.log")
        )
        (self.d / "fake.py").write_text(FAKE)
        for m in ("stores", "change_approvals"):
            sys.modules.pop(m, None)
        import change_approvals

        self.ca = importlib.reload(change_approvals)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)

    def cmd(self):
        os.environ["OPSCENTER_APPROVALS_CMD"] = f"{sys.executable} {self.d / 'fake.py'}"

    def calls(self):
        p = self.d / "calls.log"
        return p.read_text().splitlines() if p.exists() else []

    def test_it_starts_off_and_a_decision_is_a_logged_dry_run_that_calls_nothing(self):
        self.cmd()
        self.assertEqual(self.ca.queue()["live"], False)
        out = self.ca.decide(
            {"key": "CHG-12", "decision": "approve", "note": "  fine  by me ", "confirm": True}
        )
        self.assertEqual((out["mode"], out["ok"], out["note"]), ("dry_run", True, "fine by me"))
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.ca.queue()["decisions"][0]["key"], "CHG-12")

    def test_bad_input_and_a_missing_confirmation_change_nothing(self):
        for body in (
            {"key": "CHG-12", "decision": "approve"},
            {"key": "chg-12", "decision": "approve", "confirm": True},
            {"key": "CHG-12", "decision": "delete", "confirm": True},
            {"key": "CHG-12", "decision": "approve", "confirm": "yes"},
        ):
            with self.assertRaises(ValueError):
                self.ca.decide(body)
        self.assertEqual(self.ca.queue()["decisions"], [])

    def test_the_switch_needs_a_confirmation_and_a_command_to_go_live(self):
        with self.assertRaises(ValueError):
            self.ca.switch({"live": True})
        with self.assertRaises(self.ca.Refused) as e:
            self.ca.switch({"live": True, "confirm": True})
        self.assertEqual(e.exception.status, 409)
        self.assertFalse(self.ca.queue()["can_go_live"])
        self.cmd()
        self.assertTrue(self.ca.queue()["can_go_live"])
        self.assertEqual(self.ca.switch({"live": True, "confirm": True}), {"live": True})
        self.assertEqual(self.ca.switch({"live": False, "confirm": True}), {"live": False})

    def test_live_calls_the_command_once_with_the_decision(self):
        self.cmd()
        self.ca.switch({"live": True, "confirm": True})
        out = self.ca.decide(
            {"key": "CHG-9", "decision": "decline", "note": "no window", "confirm": True}
        )
        self.assertEqual((out["mode"], out["ok"], out["detail"]), ("live", True, "done"))
        self.assertEqual(
            [json.loads(c) for c in self.calls()],
            [{"key": "CHG-9", "decision": "decline", "note": "no window"}],
        )

    def test_a_failing_command_is_logged_as_not_ok_and_never_as_done(self):
        self.cmd()
        os.environ["FAKE_FAIL"] = "1"
        self.ca.switch({"live": True, "confirm": True})
        out = self.ca.decide({"key": "CHG-9", "decision": "approve", "confirm": True})
        self.assertEqual((out["mode"], out["ok"]), ("live", False))
        self.assertIn("failed", out["detail"])

    def test_live_with_the_command_gone_is_refused(self):
        self.cmd()
        self.ca.switch({"live": True, "confirm": True})
        os.environ.pop("OPSCENTER_APPROVALS_CMD")
        with self.assertRaises(self.ca.Refused):
            self.ca.decide({"key": "CHG-9", "decision": "approve", "confirm": True})
        self.assertEqual(self.ca.queue()["decisions"], [])

    def test_the_log_keeps_the_newest_200_and_shows_50(self):
        for i in range(210):
            self.ca.decide({"key": f"CHG-{i + 1}", "decision": "approve", "confirm": True})
        d = json.loads((self.d / "state" / "dashboard" / "change-approvals.json").read_text())
        self.assertEqual(len(d["decisions"]), 200)
        q = self.ca.queue()["decisions"]
        self.assertEqual((len(q), q[0]["key"]), (50, "CHG-210"))


if __name__ == "__main__":
    unittest.main()
