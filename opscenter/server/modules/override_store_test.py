"""
override_store_test.py
Purpose: A gate override is scoped, time-boxed and fails closed (layout standard rule 10): a missing, unreadable, malformed,
         foreign-scope or expired store each mean no override; the expiry is compared on every read with nothing running to
         turn it off; an entry lifts only its own key; one writer logs every change; a key that does not qualify is refused.
Run:     python3 override_store_test.py
"""

import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import override_store as o

T0 = dt.datetime(2026, 11, 1, 12, 0, tzinfo=dt.timezone.utc)


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


class Store(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.clock = Clock()
        self.mine = {"repo#1"}

        def qualify(key):
            if key not in self.mine:
                raise o.OverrideRefused(f"{key} is not mine", 403)

        self.s = o.OverrideStore(self.dir / "ov.json", clock=self.clock, qualify=qualify)

    def tearDown(self):
        self.tmp.cleanup()

    def hours(self, h):
        return T0 + dt.timedelta(hours=h)

    def test_missing_unreadable_and_malformed_stores_mean_no_override(self):
        self.assertFalse(self.s.allowed("repo#1", "w1"))
        for text in (
            "{not json",
            "[]",
            '"x"',
            '{"keys": 5}',
            '{"all": {"scope": "w1", "until": "garbage"}}',
        ):
            (self.dir / "ov.json").write_text(text)
            self.assertFalse(self.s.allowed("repo#1", "w1"), text)
            self.assertEqual(self.s.status("w1"), {"all": False, "until": None, "keys": []}, text)

    def test_scope_and_expiry_are_checked_on_every_read(self):
        self.s.set("repo#1", "w1", self.hours(5))
        self.assertTrue(self.s.allowed("repo#1", "w1"))
        self.assertFalse(self.s.allowed("repo#1", "w2"))  # foreign scope
        self.assertFalse(self.s.allowed("repo#1", ""))
        self.clock.now = self.hours(5)  # nothing ran, the next read sees the expiry
        self.assertFalse(self.s.allowed("repo#1", "w1"))

    def test_it_lifts_only_its_own_key(self):
        self.s.set("repo#1", "w1", self.hours(5))
        self.assertFalse(self.s.allowed("repo#2", "w1"))

    def test_all_covers_every_key_in_its_scope_until_it_expires(self):
        self.s.set("*", "w1", self.hours(2))
        self.assertTrue(self.s.allowed("anything", "w1"))
        self.assertFalse(self.s.allowed("anything", "w2"))
        self.assertEqual(self.s.status("w1")["all"], True)
        self.clock.now = self.hours(3)
        self.assertFalse(self.s.allowed("anything", "w1"))

    def test_a_key_that_does_not_qualify_is_refused_and_nothing_is_written(self):
        with self.assertRaises(o.OverrideRefused) as e:
            self.s.set("repo#9", "w1", self.hours(1))
        self.assertEqual(e.exception.code, 403)
        self.assertFalse((self.dir / "ov.json").exists())

    def test_no_scope_or_past_expiry_is_refused(self):
        with self.assertRaises(o.OverrideRefused) as e:
            self.s.set("repo#1", "", self.hours(1))
        self.assertEqual(e.exception.code, 409)
        with self.assertRaises(o.OverrideRefused):
            self.s.set("repo#1", "w1", self.hours(-1))

    def test_clear_takes_it_back_and_every_change_is_logged(self):
        self.s.set("repo#1", "w1", self.hours(5), who="owner")
        self.s.clear("repo#1", who="owner")
        self.assertFalse(self.s.allowed("repo#1", "w1"))
        log = [json.loads(x) for x in (self.dir / "ov.log.jsonl").read_text().splitlines()]
        self.assertEqual([x["action"] for x in log], ["on", "off"])
        self.assertEqual(log[0]["scope"], "w1")

    def test_a_write_over_an_unreadable_store_starts_clean(self):
        (self.dir / "ov.json").write_text("{broken")
        self.s.set("repo#1", "w1", self.hours(1))
        self.assertTrue(self.s.allowed("repo#1", "w1"))

    def test_pending_line_says_what_happens_next(self):
        self.assertEqual(
            o.pending_line("Freeze bypassed", 180), "Freeze bypassed, re-checked within 3 minutes"
        )
        self.assertEqual(o.pending_line("Done", 30), "Done, re-checked within 1 minute")


if __name__ == "__main__":
    unittest.main()
