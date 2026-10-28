import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import browser_status as bs  # noqa: E402
import swr  # noqa: E402


class BrowserStatus(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.launcher = Path(self._d.name) / "launcher"
        self._old = (bs.LAUNCHER, bs.VISIBLE_ALERT_S, bs.DOWN_ALERT_S, bs._main_started)
        bs.LAUNCHER = str(self.launcher)
        bs._down_since = None
        swr._mem.clear()

    def tearDown(self):
        bs.LAUNCHER, bs.VISIBLE_ALERT_S, bs.DOWN_ALERT_S, bs._main_started = self._old
        bs._down_since = None
        swr._mem.clear()
        self._d.cleanup()

    def script(self, status="mode=headless pages=2 agent_loaded=yes", hide_rc=0, hide_err=""):
        self.launcher.write_text(
            "#!/bin/sh\n"
            f'if [ "$1" = status ]; then echo "{status}"; exit 0; fi\n'
            f'if [ "$1" = hide ]; then echo "{hide_err}" >&2; exit {hide_rc}; fi\n'
        )
        self.launcher.chmod(self.launcher.stat().st_mode | stat.S_IXUSR)

    def test_headless_has_no_alert(self):
        self.script()
        bs._main_started = lambda: time.time() - 99999
        r = bs._get()
        self.assertEqual(
            (r["mode"], r["pages"], r["agent_loaded"], r["alert"]), ("headless", 2, True, None)
        )

    def test_a_window_visible_too_long_alerts_and_a_short_one_does_not(self):
        self.script("mode=visible pages=1 agent_loaded=no")
        bs._main_started = lambda: time.time() - 2000
        self.assertEqual(bs._get()["alert"], "visible")
        bs._main_started = lambda: time.time() - 10
        self.assertIsNone(bs._get()["alert"])

    def test_down_alerts_only_after_the_down_alert_age(self):
        self.script("mode=down")
        bs.DOWN_ALERT_S = 0.05
        self.assertIsNone(bs._get()["alert"])
        time.sleep(0.1)
        self.assertEqual(bs._get()["alert"], "down")
        self.script("mode=headless")
        bs._main_started = lambda: None
        bs._get()
        self.assertIsNone(bs._down_since)

    def test_an_unreadable_launcher_reports_unknown_not_an_error(self):
        bs.LAUNCHER = "/nonexistent/launcher"
        r = bs._get()
        self.assertEqual((r["mode"], r["alert"]), ("unknown", None))
        self.assertIn("error", r)

    def test_hide_returns_the_new_status_and_raises_with_the_launcher_message(self):
        self.script("mode=headless pages=0 agent_loaded=yes")
        bs._main_started = lambda: None
        self.assertEqual(bs.hide()["mode"], "headless")
        self.script(hide_rc=3, hide_err="no window")
        with self.assertRaises(RuntimeError) as cm:
            bs.hide()
        self.assertIn("no window", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
