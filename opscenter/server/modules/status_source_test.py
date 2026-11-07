"""
status_source_test.py
Purpose: A missing, stale, unreadable or malformed status file is unknown and never in sync; a fresh reading is ok; a collector that
         loses its sign-in keeps serving its last reading marked stale and exits non-zero only after the lapse limit; a sign-in that
         comes back clears the lapse; a failure that is not the sign-in exits non-zero and never writes a fresh looking reading.
Run:     python3 status_source_test.py
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import status_source as s

NOW = 1_800_000_000.0


class Read(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.f = Path(self.tmp.name) / "status.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_is_unknown(self):
        r = s.read(self.f, now=NOW)
        self.assertEqual((r["state"], r["reason"]), ("unknown", "no status file yet"))

    def test_unreadable_and_malformed_are_unknown(self):
        for text in ("{nope", "[]", '{"at": "x", "data": 1}', '{"data": 1}'):
            self.f.write_text(text)
            self.assertEqual(s.read(self.f, now=NOW)["state"], "unknown", text)

    def test_fresh_is_ok_and_old_is_unknown(self):
        self.f.write_text(json.dumps({"at": NOW - 60, "data": {"n": 1}}))
        r = s.read(self.f, max_age_s=300, now=NOW)
        self.assertEqual((r["state"], r["data"]), ("ok", {"n": 1}))
        r = s.read(self.f, max_age_s=30, now=NOW)
        self.assertEqual(r["state"], "unknown")
        self.assertIn("minutes old", r["reason"])

    def test_a_stale_flag_is_unknown_even_when_young(self):
        self.f.write_text(json.dumps({"at": NOW - 5, "data": 1, "stale": True}))
        r = s.read(self.f, max_age_s=300, now=NOW)
        self.assertEqual((r["state"], r["stale"]), ("unknown", True))
        self.assertEqual(r["data"], 1)  # the last reading is still shown, marked

    def test_a_shape_check_can_reject_a_reading(self):
        self.f.write_text(json.dumps({"at": NOW, "data": {"hosts": None}}))
        r = s.read(
            self.f, now=NOW, check=lambda d: None if d.get("hosts") else "no hosts in the reading"
        )
        self.assertEqual((r["state"], r["reason"]), ("unknown", "no hosts in the reading"))


class Collect(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.f = Path(self.tmp.name) / "status.json"

    def tearDown(self):
        self.tmp.cleanup()

    def lapse(self):
        raise s.AuthLapse("expired")

    def test_a_good_run_writes_a_fresh_reading(self):
        self.assertEqual(s.collect(lambda: {"n": 2}, self.f, now=NOW)[0], 0)
        self.assertEqual(s.read(self.f, max_age_s=60, now=NOW + 1)["data"], {"n": 2})

    def test_a_lapse_keeps_the_last_reading_stale_and_stays_quiet_until_the_limit(self):
        s.collect(lambda: {"n": 2}, self.f, now=NOW)
        rc, line = s.collect(self.lapse, self.f, lapse_s=14400, now=NOW + 600)
        self.assertEqual(rc, 0)
        self.assertIn("serving the last reading as stale", line)
        r = s.read(self.f, now=NOW + 700)
        self.assertEqual((r["state"], r["stale"], r["data"]), ("unknown", True, {"n": 2}))

    def test_the_lapse_exits_non_zero_after_the_limit_and_keeps_counting_from_the_first_lapse(self):
        s.collect(lambda: {"n": 2}, self.f, now=NOW)
        s.collect(self.lapse, self.f, lapse_s=14400, now=NOW + 600)
        rc, line = s.collect(self.lapse, self.f, lapse_s=14400, now=NOW + 600 + 14400)
        self.assertEqual(rc, 1)
        self.assertIn("renew it", line)
        self.assertEqual(json.loads(self.f.read_text())["data"], {"n": 2})  # never thrown away

    def test_a_returning_sign_in_clears_the_lapse(self):
        s.collect(lambda: {"n": 2}, self.f, now=NOW)
        s.collect(self.lapse, self.f, now=NOW + 600)
        rc, _ = s.collect(lambda: {"n": 3}, self.f, now=NOW + 1200)
        self.assertEqual(rc, 0)
        d = json.loads(self.f.read_text())
        self.assertEqual((d["stale"], d["lapsed_since"], d["data"]), (False, None, {"n": 3}))

    def test_a_lapse_with_no_earlier_reading_is_unknown_not_a_pass(self):
        rc, _ = s.collect(self.lapse, self.f, now=NOW)
        self.assertEqual(rc, 0)
        self.assertEqual(s.read(self.f, now=NOW + 1)["state"], "unknown")

    def test_another_failure_exits_non_zero_and_never_writes_a_fresh_reading(self):
        s.collect(lambda: {"n": 2}, self.f, now=NOW)

        def boom():
            raise RuntimeError("HTTP 500")

        rc, line = s.collect(boom, self.f, now=NOW + 60)
        self.assertEqual(rc, 1)
        self.assertIn("HTTP 500", line)
        self.assertEqual(s.read(self.f, now=NOW + 61)["state"], "unknown")

    def test_the_sign_in_test_is_the_consumers(self):
        def boom():
            raise RuntimeError("az: please run az login")

        rc, line = s.collect(boom, self.f, now=NOW, is_auth_error=lambda e: "az login" in str(e))
        self.assertEqual(rc, 0)
        self.assertIn("lapsed", line)


if __name__ == "__main__":
    unittest.main()
