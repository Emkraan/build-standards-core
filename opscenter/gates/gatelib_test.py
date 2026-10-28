import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gatehelp  # noqa: E402
import gatelib  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self._old = gatelib.STATE_DIR
        gatelib.STATE_DIR = self._d.name

    def tearDown(self):
        gatelib.STATE_DIR = self._old
        self._d.cleanup()


class Contract(Base):
    def test_silent_prints_the_wake_false_line_and_exits_zero(self):
        out, code = gatehelp.run_gate(gatelib.gate_silent)
        self.assertEqual((json.loads(out), code), ({"wakeAgent": False}, 0))

    def test_wake_prints_context_lines_and_exits_zero(self):
        out, code = gatehelp.run_gate(gatelib.wake, "line one", None, "line two")
        self.assertEqual((out, code), ("line one\nline two\n", 0))


class Failures(Base):
    def test_a_failure_streak_wakes_on_the_third_then_once_per_cooldown(self):
        f = lambda: gatelib.failure_should_wake("g", "boom", backoff_first=3, cooldown=100)  # noqa: E731
        self.assertEqual([f(), f(), f()], [False, False, True])
        self.assertFalse(f())  # inside the cooldown
        h = gatelib.load_health("g")
        h["last_alert_epoch"] -= 101
        gatelib.save_health("g", h)
        self.assertTrue(f())
        self.assertEqual(gatelib.load_health("g")["last_error"], "boom")

    def test_clear_failures_returns_the_streak_and_resets(self):
        gatelib.failure_should_wake("g", "x")
        gatelib.failure_should_wake("g", "x")
        self.assertEqual(gatelib.clear_failures("g"), 2)
        self.assertEqual(gatelib.load_health("g")["failures"], 0)
        self.assertEqual(gatelib.clear_failures("g"), 0)

    def test_health_defaults_when_the_file_is_missing_or_bad(self):
        self.assertEqual(gatelib.load_health("nope")["failures"], 0)
        Path(gatelib._health_path("bad")).write_text("{")
        self.assertEqual(gatelib.load_health("bad")["failures"], 0)

    def test_audit_is_due_once_per_day(self):
        self.assertTrue(gatelib.audit_due("g", "2026-10-28"))
        gatelib.mark_audit("g", "2026-10-28")
        self.assertFalse(gatelib.audit_due("g", "2026-10-28"))
        self.assertTrue(gatelib.audit_due("g", "2026-10-29"))


class Run(unittest.TestCase):
    def test_run_returns_code_and_output_and_never_raises(self):
        rc, out, _ = gatelib.run([sys.executable, "-c", "print('hi')"])
        self.assertEqual((rc, out.strip()), (0, "hi"))
        self.assertEqual(gatelib.run(["/nonexistent/binary"])[0], 1)
        rc, _, err = gatelib.run([sys.executable, "-c", "import time; time.sleep(5)"], timeout=1)
        self.assertEqual(rc, 124)
        self.assertIn("timeout", err)

    def test_env_overlay(self):
        rc, out, _ = gatelib.run(
            [sys.executable, "-c", "import os; print(os.environ['GATE_X'])"], env={"GATE_X": "7"}
        )
        self.assertEqual(out.strip(), "7")


class Accumulation(Base):
    def test_urgent_reasons(self):
        self.assertTrue(gatelib.is_urgent_why("Urgent-Signal: outage"))
        self.assertTrue(gatelib.is_urgent_why("count-spike 9"))
        self.assertFalse(gatelib.is_urgent_why("plain human"))
        self.assertFalse(gatelib.is_urgent_why(None))

    def test_accumulate_appends_keeps_the_first_since_and_clears(self):
        self.assertEqual(gatelib.accumulate("m", []), 0)
        self.assertEqual(gatelib.accumulate("m", [{"id": 1}]), 1)
        _, since = gatelib.load_accumulated("m")
        self.assertEqual(gatelib.accumulate("m", [{"id": 2}, {"id": 3}]), 3)
        items, since2 = gatelib.load_accumulated("m")
        self.assertEqual((len(items), since2), (3, since))
        self.assertEqual(oct(os.stat(gatelib._accum_path("m")).st_mode & 0o777), "0o600")
        gatelib.clear_accumulated("m")
        self.assertEqual(gatelib.load_accumulated("m"), ([], None))
        gatelib.clear_accumulated("m")  # clearing nothing is fine

    def test_should_drain_only_in_the_first_ten_minutes_of_a_drain_hour(self):
        def at(h, m):
            return time.struct_time((2026, 10, 28, h, m, 0, 2, 301, -1))

        self.assertTrue(gatelib.should_drain(at(12, 0), {12, 17}))
        self.assertTrue(gatelib.should_drain(at(17, 9), {12, 17}))
        self.assertFalse(gatelib.should_drain(at(12, 10), {12, 17}))
        self.assertFalse(gatelib.should_drain(at(13, 0), {12, 17}))
        self.assertFalse(gatelib.should_drain(at(12, 0), set()))


class InboundStore(unittest.TestCase):
    def tearDown(self):
        gatelib.set_inbound_store(None)

    def test_without_a_store_harvest_does_nothing(self):
        self.assertEqual(gatelib.harvest_inbound_files([{"id": 1}], "mail"), 0)

    def test_a_store_gets_the_messages_and_its_failure_never_propagates(self):
        class Ok:
            def harvest_messages(self, m, surface):
                return len(m)

        class Bad:
            def harvest_messages(self, m, surface):
                raise RuntimeError("x")

        gatelib.set_inbound_store(Ok())
        self.assertEqual(gatelib.harvest_inbound_files([1, 2], "chat"), 2)
        gatelib.set_inbound_store(Bad())
        self.assertEqual(gatelib.harvest_inbound_files([1], "chat"), 0)
        self.assertEqual(gatelib.harvest_inbound_files([], "chat"), 0)


class EnvFile(unittest.TestCase):
    def test_reads_a_key_and_returns_empty_when_absent(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("A=1\nCURL_CA_BUNDLE=/etc/ca.pem \nB=2\n")
            self.assertEqual(gatelib.curl_ca_bundle(str(p)), "/etc/ca.pem")
            self.assertEqual(gatelib.env_file_value("MISSING", str(p)), "")
            self.assertEqual(gatelib.env_file_value("A", str(Path(d) / "nope")), "")


if __name__ == "__main__":
    unittest.main()
