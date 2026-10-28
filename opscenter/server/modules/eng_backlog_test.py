"""Debt and improvements: parsing TD and IMP entries from the markdown files, the buckets, the in-place Status rewrite under a lock, the
page-only snooze, and the item handed to the runtime slot."""

import datetime as dt
import importlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import eng_backlog

TD = """# Technical debt

## TD-001 Old cache layer (RESOLVED 2026-01-02)
- **Status**: RESOLVED 2026-01-02. Replaced.
- **Severity**: low

## TD-002 Flaky nightly job
- **Status**: open
- **Owner**: platform team
- Severity: high. Fails about weekly.

---

## TD-003: Vendored parser
- **Status**: ACCEPTED 2026-02-01 (workaround stays)
"""

IMP = """# Improvements

## IMP-001: Faster board build
- **Status**: suggested 2026-03-01
- **Goal**: G1 and G3
- **Effort**: two days

## IMP-002: Dark mode for the page
- **Status**: declined 2026-03-02

## IMP-003: Parked idea
- **Status**: parked 2026-03-03
"""


class Backlog(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="engbl-"))
        self._env = dict(os.environ)
        (self.d / "td.md").write_text(TD)
        (self.d / "imp.md").write_text(IMP)
        os.environ.update(
            ENGBL_TD=str(self.d / "td.md"),
            ENGBL_IMP=str(self.d / "imp.md"),
            ENGBL_HANDLED=str(self.d / "handled.json"),
        )
        self.m = importlib.reload(eng_backlog)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self.d, ignore_errors=True)
        importlib.reload(eng_backlog)

    def row(self, id_):
        return next(r for r in self.m.items()["items"] if r["id"] == id_)

    def test_entries_are_parsed_with_buckets_outcomes_and_fields(self):
        doc = self.m.items()
        self.assertEqual(len(doc["items"]), 6)
        self.assertEqual(self.row("TD-001")["bucket"], "done")
        td2 = self.row("TD-002")
        self.assertEqual(
            (td2["bucket"], td2["severity"], td2["owner"]), ("todo", "high", "platform team")
        )
        self.assertEqual(self.row("TD-003")["bucket"], "parked")
        imp1 = self.row("IMP-001")
        self.assertEqual(
            (imp1["bucket"], imp1["goals"], imp1["effort"]), ("decide", ["G1", "G3"], "two days")
        )
        self.assertEqual(self.row("IMP-002")["bucket"], "done")
        self.assertEqual(self.row("IMP-003")["bucket"], "parked")
        self.assertEqual(doc["counts"]["decide_imp"], 1)

    def test_the_uid_is_stable_and_the_entry_stops_at_a_rule(self):
        a = self.row("TD-002")
        self.assertEqual(a["uid"], self.row("TD-002")["uid"])
        self.assertNotIn("Vendored parser", a["body"])

    def test_approve_rewrites_only_that_status_line_and_keeps_the_earlier_text(self):
        uid = self.row("IMP-001")["uid"]
        out = self.m.set_status(uid, "approve", "go ahead")
        self.assertEqual(out["bucket"], "todo" if out["outcome"] == "open" else out["bucket"])
        text = (self.d / "imp.md").read_text()
        self.assertIn("approved ", text)
        self.assertIn("(decided in the Ops Center). go ahead.", text)
        self.assertIn("Earlier: suggested 2026-03-01", text)
        self.assertIn("## IMP-002: Dark mode for the page\n- **Status**: declined 2026-03-02", text)
        self.assertEqual((self.d / "td.md").read_text(), TD)

    def test_a_decision_that_does_not_apply_is_refused(self):
        with self.assertRaises(ValueError):
            self.m.set_status(self.row("TD-002")["uid"], "approve")
        with self.assertRaises(ValueError):
            self.m.set_status(self.row("IMP-002")["uid"], "approve")
        with self.assertRaises(ValueError):
            self.m.set_status(self.row("IMP-001")["uid"], "nonsense")

    def test_accepting_a_risk_or_closing_debt_needs_a_reason(self):
        uid = self.row("TD-002")["uid"]
        with self.assertRaises(ValueError):
            self.m.set_status(uid, "resolve", "")
        out = self.m.set_status(uid, "resolve", "fixed in the scheduler")
        self.assertEqual(out["bucket"], "done")
        self.assertIn("RESOLVED", (self.d / "td.md").read_text())

    def test_a_missing_status_line_is_added_to_the_entry(self):
        (self.d / "imp.md").write_text(IMP + "\n## IMP-004: No status yet\n- **Goal**: G2\n")
        uid = self.row("IMP-004")["uid"]
        self.m.set_status(uid, "park", "later")
        self.assertIn("- **Status**: parked ", (self.d / "imp.md").read_text().split("IMP-004")[1])

    def test_snooze_is_page_only_and_expires_and_restores(self):
        uid = self.row("IMP-001")["uid"]
        before = (self.d / "imp.md").read_text()
        self.m.handle(uid, "snooze")
        self.assertEqual((self.d / "imp.md").read_text(), before)
        self.assertIsNotNone(self.row("IMP-001")["snoozed"])
        self.assertEqual(self.m.items()["counts"]["decide_imp"], 0)
        self.m.handle(uid, "restore")
        self.assertIsNone(self.row("IMP-001")["snoozed"])
        self.m.handle(uid, "snooze")
        past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        h = self.m._load_handled()
        h[uid]["until"] = past
        self.m._save_handled(h)
        self.assertIsNone(self.row("IMP-001")["snoozed"])
        with self.assertRaises(ValueError):
            self.m.handle(uid, "bogus")
        with self.assertRaises(KeyError):
            self.m.handle("td-zzzzzz", "snooze")

    def test_a_decision_clears_a_snooze(self):
        uid = self.row("IMP-001")["uid"]
        self.m.handle(uid, "snooze")
        self.m.set_status(uid, "park")
        self.assertNotIn(uid, self.m._load_handled())

    def test_missing_files_give_an_empty_page(self):
        os.environ["ENGBL_TD"] = str(self.d / "none.md")
        os.environ["ENGBL_IMP"] = str(self.d / "none2.md")
        m = importlib.reload(eng_backlog)
        self.assertEqual(m.items()["items"], [])

    def test_the_tackle_item_carries_the_entry_and_its_source(self):
        item = self.m.tackle_item(self.row("TD-002"))
        self.assertEqual(
            (item["key"], item["priority"], item["refs"]), ("TD-002", "high", ["TD-002"])
        )
        self.assertIn("Entry as written", item["summary"])
        self.assertIn("td.md", item["summary"])


if __name__ == "__main__":
    unittest.main()
