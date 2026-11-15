import os
import unittest
from unittest import mock

from support import Work, load

ex = load("safe_hermes_restart_exec", "hermes/safe-restart/safe_hermes_restart_exec.py")


class Fence(Work):
    def setUp(self):
        super().setUp()
        self.freeze = str(self.dir / "freeze")
        self.calls = []
        self.events = []
        self.pids = {}
        for name, val in (
            ("FREEZE_FILE", self.freeze),
            ("BACKEND_FILE", str(self.dir / "backend")),
            ("FENCE_FILE", str(self.dir / "fence")),
        ):
            p = mock.patch.object(ex, name, val)
            p.start()
            self.addCleanup(p.stop)
        for target, fn in (
            ("time.sleep", lambda s: None),
            ("subprocess.run", self.fake_run),
            ("builtins.print", lambda *a, **k: None),
        ):
            p = mock.patch(target, fn)
            p.start()
            self.addCleanup(p.stop)
        self.busy = []
        p = mock.patch.object(ex, "idle_reasons", lambda: self.busy)
        p.start()
        self.addCleanup(p.stop)
        os.environ.pop("SAFE_RESTART_FENCE", None)
        os.environ.pop("SAFE_RESTART_FREEZE_S", None)

    def fake_run(self, args, **kw):
        out = mock.Mock(returncode=0, stderr="", stdout="")
        if args[:2] == ["launchctl", "kickstart"]:
            label = args[-1]
            self.events.append(("kickstart", label))
            self.pids[label] = self.pids.get(label, 100) + 1
        elif args[:2] == ["launchctl", "list"]:
            label = args[-1]
            full = next((k for k in self.pids if k.endswith("/" + label)), None)
            out.stdout = f'"PID" = {self.pids.get(full, 100)};'
        return out

    def test_flag_default_off(self):
        self.assertFalse(ex.fence_enabled(str(self.dir / "fence")))
        self.assertEqual(ex.freeze_seconds(str(self.dir / "fence")), 30)

    def test_flag_sources_and_parameter(self):
        flag = self.dir / "fence"
        flag.write_text("45\n")
        self.assertTrue(ex.fence_enabled(str(flag)))
        self.assertEqual(ex.freeze_seconds(str(flag)), 45)
        os.environ["SAFE_RESTART_FREEZE_S"] = "7"
        self.addCleanup(os.environ.pop, "SAFE_RESTART_FREEZE_S", None)
        self.assertEqual(ex.freeze_seconds(str(flag)), 7)

    def test_order_backend_then_gateway_verified(self):
        (self.dir / "backend").write_text("ai.hermes.backend\n")
        ok, detail, old, new = ex.run_fenced(30)
        self.assertTrue(ok, detail)
        labels = [lbl for _, lbl in self.events]
        self.assertEqual(labels, [f"gui/{os.getuid()}/ai.hermes.backend", ex.LABEL])
        self.assertNotEqual(old, new)
        self.assertFalse(os.path.exists(self.freeze))

    def test_backend_failure_skips_gateway_and_releases_freeze(self):
        (self.dir / "backend").write_text("ai.hermes.backend\n")
        with mock.patch.object(ex, "restart_unit", return_value=(False, 1, 1)):
            ok, detail, _, _ = ex.run_fenced(30)
        self.assertFalse(ok)
        self.assertIn("gateway left alone", detail)
        self.assertEqual(self.events, [])
        self.assertFalse(os.path.exists(self.freeze))

    def test_freeze_released_when_restart_raises(self):
        with mock.patch.object(ex, "restart_unit", side_effect=RuntimeError("boom")):
            ok, detail, _, _ = ex.run_fenced(30)
        self.assertFalse(ok)
        self.assertIn("boom", detail)
        self.assertFalse(os.path.exists(self.freeze))

    def test_freeze_held_during_recheck_and_released_on_busy(self):
        seen = []
        self.busy = ["chat turn in flight: a"]
        orig = ex.idle_reasons
        with mock.patch.object(
            ex, "idle_reasons", lambda: (seen.append(os.path.exists(self.freeze)), orig())[1]
        ):
            ok, detail, _, _ = ex.run_fenced(30)
        self.assertEqual(seen, [True])
        self.assertFalse(ok)
        self.assertEqual(self.events, [])
        self.assertFalse(os.path.exists(self.freeze))

    def test_flag_off_is_the_old_single_gateway_kickstart(self):
        trig = self.dir / "trigger"
        import time

        trig.write_text(str(int(time.time())))
        self.pids[ex.LABEL] = 100
        with (
            mock.patch.object(ex, "TRIGGER", str(trig)),
            mock.patch.object(ex, "card"),
            mock.patch.object(ex, "run_fenced") as fenced,
            mock.patch.object(ex, "freeze_on") as fon,
            mock.patch("urllib.request.urlopen"),
        ):
            ex.main()
        fenced.assert_not_called()
        fon.assert_not_called()
        self.assertEqual(self.events, [("kickstart", ex.LABEL)])
        self.assertFalse(os.path.exists(self.freeze))


if __name__ == "__main__":
    unittest.main()
