#!/usr/bin/env python3
"""Tests for eng_backlog.py status reading and eng_curate.py. Synthetic files only, no gh calls."""

from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

TD = """# Technical debt

## TD-010: Grafana viewer grant drift on dashboards-app

- **Severity**: Medium
- **Description**: The viewer grant in grafana-rbac.tf drifts after every Owner apply.
- **Owner**: Owner
- **Status**: OPEN 2026-10-20

---

## TD-011: Old resolved row (RESOLVED 2026-10-01)

- **Status**: OPEN (2026-09-01)

---

## TD-012: Folded debt row

- **Status**: folded into TD-010 (Grafana viewer grant drift) 2026-10-30. Same apply.

---
"""

IMP = """# Improvement backlog

### IMP-200: Action Center collector groups duplicate cards
- **Status**: suggested 2026-10-20
- **Goal**: G3
- **Observed**: ac_collect.py emits two cards for the same PR when the review and the lane both see it.

### IMP-201: Faster plan gate dispatch
- **Status**: DONE 2026-10-24. infra #500 merged.
- **Goal**: G1

### IMP-202: Half built thing
- **Status**: approved 2026-10-10. Part 1 shipped, part 2 still open.

### IMP-203: Superseded idea
- **Status**: Superseded by IMP-200 (same collector change)

### IMP-204: Unknown word status
- **Status**: Investigating 2026-10-29

### IMP-205: In review item
- **Status**: In review, infra #510

### IMP-206: Dated status
- **Status**: 2026-10-12 shipped in infra #490
"""


sys.path.insert(0, str(Path(__file__).resolve().parent))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        (d / "td.md").write_text(TD, encoding="utf-8")
        (d / "imp.md").write_text(IMP, encoding="utf-8")
        os.environ.update(
            OPSCENTER_ROOT=str(d),
            ENGBL_TD=str(d / "td.md"),
            ENGBL_IMP=str(d / "imp.md"),
            ENGBL_HANDLED=str(d / "handled.json"),
            ENGBL_CURATION=str(d / "cur.json"),
            ENGBL_PR_ALIASES='{"infra": "acme/infra"}',
            ENGBL_RETIRED_TERMS='{"OldTracker": "OldTracker retired, the new tracker replaced it"}',
            ENGBL_OWNER="Owner",
        )
        import eng_backlog
        import eng_curate

        self.eb = importlib.reload(eng_backlog)
        self.ec = importlib.reload(eng_curate)
        self.dir = d

    def tearDown(self):
        self.tmp.cleanup()

    def row(self, rid):
        rows = [r for r in self.eb.all_rows() if r["id"] == rid]
        self.assertEqual(len(rows), 1, rid)
        return rows[0]


class StatusVocabulary(Base):
    def test_buckets(self):
        want = {
            "TD-010": ("todo", "open"),
            "TD-011": ("done", "open"),  # heading RESOLVED wins over a stale Status line
            "TD-012": ("done", "folded"),
            "IMP-200": ("decide", "suggested"),
            "IMP-201": ("done", "shipped"),
            "IMP-202": ("todo", "approved"),
            "IMP-203": ("done", "withdrawn"),
            "IMP-204": ("decide", "suggested"),
            "IMP-205": ("todo", "in-progress"),
            "IMP-206": ("done", "shipped"),
        }
        for rid, (bucket, _outcome) in want.items():
            self.assertEqual(self.row(rid)["bucket"], bucket, rid)

    def test_canonical_unknown_is_empty(self):
        self.assertEqual(self.eb.canonical("IMP", "Investigating 2026-10-29"), "")
        self.assertEqual(self.eb.canonical("TD", "DONE"), "resolved")
        self.assertEqual(self.eb.canonical("IMP", "Resolved by #444"), "shipped")

    def test_parent_links(self):
        parent = self.row("TD-010")
        child = self.row("TD-012")
        self.assertEqual(child["parent"], "TD-010")
        self.assertEqual(child["parent_uid"], parent["uid"])
        self.assertIn(child["uid"], parent["children"])
        self.assertIn(self.row("IMP-203")["uid"], self.row("IMP-200")["children"])


class Configuration(Base):
    def test_pr_aliases_and_urls_read_as_pull_requests(self):
        refs = self.ec._pr_refs(
            "fixed in infra #500 and infra PR #501, see https://github.com/o/r/pull/7 and other #9"
        )
        self.assertEqual(refs, {("acme/infra", 500), ("acme/infra", 501), ("o/r", 7)})

    def test_the_retired_terms_and_the_owner_come_from_configuration(self):
        self.assertEqual(
            self.ec.RETIRED_TERMS, {"OldTracker": "OldTracker retired, the new tracker replaced it"}
        )
        eid = self.ec.new_entry("TD", "A new debt", "text", "", severity="Low")
        self.assertIn("- **Owner**: Owner", (self.dir / "td.md").read_text())
        self.assertTrue(eid.startswith("TD-"))

    def test_with_nothing_configured_nothing_is_assumed(self):
        for k in ("ENGBL_PR_ALIASES", "ENGBL_RETIRED_TERMS", "ENGBL_OWNER", "ENGBL_REF_PATTERNS"):
            os.environ.pop(k, None)
        import eng_curate

        ec = importlib.reload(eng_curate)
        self.assertEqual((ec.RETIRED_TERMS, ec.PR_ALIASES, ec.OWNER), ({}, {}, ""))
        self.assertEqual(ec._pr_refs("infra #500"), set())


class Acts(Base):
    def test_fold_and_undo(self):
        r = self.row("IMP-204")
        self.eb.set_status(r["uid"], "fold", "same work", target="IMP-200")
        r2 = self.row("IMP-204")
        self.assertEqual(r2["bucket"], "done")
        self.assertEqual(r2["parent"], "IMP-200")
        self.eb.set_status(r2["uid"], "undo")
        self.assertEqual(self.row("IMP-204")["status"], "Investigating 2026-10-29")

    def test_fold_into_itself_refused(self):
        r = self.row("IMP-200")
        with self.assertRaises(ValueError):
            self.eb.set_status(r["uid"], "fold", target="IMP-200")

    def test_undo_without_history_refused(self):
        with self.assertRaises(ValueError):
            self.eb.set_status(self.row("IMP-200")["uid"], "undo")


class Curation(Base):
    def test_add_folds_into_clear_match(self):
        out = self.ec.add(
            "IMP", "Collector emits duplicate Action Center cards", "ac_collect.py doubles PR cards"
        )
        self.assertEqual(out["action"], "update")
        self.assertEqual(out["into"], "IMP-200")
        self.assertIn("Update", self.row("IMP-200")["body"])

    def test_add_new_gets_next_free_id(self):
        out = self.ec.add(
            "IMP", "Teach the Builds page to show Vercel previews", "unrelated topic entirely"
        )
        self.assertEqual(out["action"], "new")
        self.assertEqual(out["id"], "IMP-207")
        self.assertEqual(self.row("IMP-207")["bucket"], "decide")
        # reservations never hand out the same id twice, even before the entry is written
        self.assertEqual(self.ec.reserve_id("IMP"), "IMP-208")
        self.assertEqual(self.ec.reserve_id("IMP"), "IMP-209")

    def test_add_into_and_force_new(self):
        out = self.ec.add("TD", "Another drift", "x", into="TD-010")
        self.assertEqual(out["into"], "TD-010")
        out = self.ec.add(
            "IMP", "Collector emits duplicate Action Center cards", "ac_collect.py", force_new=True
        )
        self.assertEqual(out["action"], "new")

    def test_run_closes_status_that_says_done_but_not_partial(self):
        p = self.dir / "imp.md"
        p.write_text(
            p.read_text().replace(
                "- **Status**: Investigating 2026-10-29",
                "- **Status**: approved 2026-10-01. DONE 10/29, infra #520 merged.",
            ),
            encoding="utf-8",
        )
        out = self.ec.run(gh=False)
        ids = [a[1] for a in out["actions"]]
        self.assertIn("IMP-204", ids)
        self.assertNotIn("IMP-202", ids)  # part 2 still open
        self.assertEqual(self.row("IMP-204")["bucket"], "done")
        log = json.loads((self.dir / "cur.json").read_text())["log"]
        self.assertEqual(log[0]["id"], "IMP-204")
        # one click undo puts it back
        self.eb.set_status(self.row("IMP-204")["uid"], "undo")
        self.assertEqual(self.row("IMP-204")["bucket"], "todo")

    def test_run_folds_parked_twins_without_shared_reference(self):
        extra = """
## TD-020: deploy-hooks holds tenant-wide Console app write

- **Description**: The deploy-hooks managed identity holds tenant-wide Console app write for app assignment.
- **Status**: accepted 2026-10-20, revisit if Console adds scoped app permissions

---

## TD-021: automation account identity gains tenant-wide Console configuration write

- **Description**: The automation account managed identity gains tenant-wide Console configuration write for driver approval.
- **Status**: accepted 2026-10-25, revisit if Graph adds a narrower role

---
"""
        p = self.dir / "td.md"
        p.write_text(p.read_text() + extra, encoding="utf-8")
        out = self.ec.run(gh=False)
        folds = [(a[1], a[2]) for a in out["actions"] if a[0] == "fold"]
        self.assertEqual([f[0] for f in folds], ["TD-021"])
        self.assertIn("folded into TD-020", folds[0][1])
        self.assertEqual(self.row("TD-021")["parent"], "TD-020")
        self.assertEqual(
            self.row("TD-020")["bucket"], "parked"
        )  # the parent keeps its accepted status
        # parked never folds into open work
        self.assertNotEqual(self.row("TD-010")["children"], [self.row("TD-021")["uid"]])

    def test_dismissed_fold_is_never_automatic(self):
        extra = """
## TD-020: deploy-hooks holds tenant-wide Console app write

- **Description**: The deploy-hooks managed identity holds tenant-wide Console app write.
- **Status**: accepted 2026-10-20

---

## TD-021: deploy-hooks also holds tenant-wide Console configuration write

- **Description**: The deploy-hooks managed identity holds tenant-wide Console configuration write.
- **Status**: accepted 2026-10-25

---
"""
        p = self.dir / "td.md"
        p.write_text(p.read_text() + extra, encoding="utf-8")
        self.ec.dismiss(self.row("TD-021")["uid"], "fold:TD-020")
        out = self.ec.run(gh=False)
        self.assertNotIn("TD-021", [a[1] for a in out["actions"]])

    def test_dismissed_hint_stays_dismissed(self):
        r = self.row("IMP-204")
        self.ec.dismiss(r["uid"], "stale:")
        self.assertIn(
            "stale:", json.loads((self.dir / "cur.json").read_text())["dismissed"][r["uid"]]
        )


if __name__ == "__main__":
    unittest.main()
