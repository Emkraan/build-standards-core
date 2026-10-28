#!/usr/bin/env python3
"""Tests for identity-and-people-data 1.1 and 1.2 on the 1:1 roster.

Date:    2026-10-27
Purpose: 1.1 The directory owns identity, so no write path may edit an identity field (name, first,
         email, title). Code holds no title or address for a report. The directory pull wins whenever
         it succeeds and writes the fallback copy. The copy is read only when the pull fails, is
         reported stale with its age, and a copy edited by hand is ignored. Every write path takes
         an existing roster member and nothing else.
         1.2 The roster is held once (one_on_ones.ROSTER). No other source file carries a copy of its
         names or emails, and no other module builds its own list of addresses.
Fixtures use role placeholders and example.com addresses only. The static checks read the real
roster at run time, so no real name or address is written in this file.
"""

from __future__ import annotations

import ast
import copy
import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parent
IDENTITY_FIELDS = ("name", "first", "email", "title")
MUTATORS = {
    "append",
    "extend",
    "insert",
    "remove",
    "pop",
    "clear",
    "update",
    "setdefault",
    "sort",
    "reverse",
}
SKIP_DIRS = {
    "node_modules",
    "dist",
    "tests",
    "standards-core",
    "kit-core",
    "tokens-core",
    "lint-core",
    "scripts",
}
TEXT_SUFFIXES = {".py", ".ts", ".tsx", ".json", ".mjs", ".css", ".html", ".md"}

PLACEHOLDER_ROSTER = [
    {"name": "Report One", "first": "One"},
    {"name": "Report Two", "first": "Two"},
    {
        "name": "Partner One",
        "first": "Partner",
        "email": "partner.one@example.com",
        "title": "Role C",
        "group": "partner",
    },
]


def source_files():
    """Non-test source under the app folder that this repo owns (core copies and fixtures excluded)."""
    for path in sorted(APP.rglob("*")):
        rel = path.relative_to(APP)
        if (
            not path.is_file()
            or path.suffix not in TEXT_SUFFIXES
            or set(rel.parts[:-1]) & SKIP_DIRS
        ):
            continue
        if (
            path.name.endswith("_test.py")
            or ".test." in path.name
            or path.name == "package-lock.json"
        ):
            continue
        yield path


def real_roster():
    """The roster the module builds from its parameters file (a scratch one holding the placeholder roster, so the
    scan below looks for names that exist; in core the code itself holds no roster at all)."""
    d = Path(tempfile.mkdtemp(prefix="idroster-"))
    pf = d / "people-params.json"
    pf.write_text(json.dumps({"roster": PLACEHOLDER_ROSTER}))
    old = {
        k: os.environ.get(k)
        for k in ("OPSCENTER_ROOT", "OPSCENTER_STATE_DIR", "OPSCENTER_PEOPLE_PARAMS")
    }
    os.environ.update(
        OPSCENTER_ROOT=str(d), OPSCENTER_STATE_DIR=str(d / "state"), OPSCENTER_PEOPLE_PARAMS=str(pf)
    )
    try:
        import one_on_ones

        return copy.deepcopy(importlib.reload(one_on_ones).ROSTER)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def chain_names(node):
    """Every Name id and Attribute attr along an expression such as a.b[0].c."""
    out = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            out.append(sub.id)
        elif isinstance(sub, ast.Attribute):
            out.append(sub.attr)
    return out


def roster_mutations(path):
    """(line, what) for every statement that edits ROSTER or one of its entries. The one allowed
    statement is the module level assignment that defines ROSTER in one_on_ones.py."""
    tree = ast.parse(path.read_text(encoding="utf8"))
    top_defs = (
        {id(n) for n in tree.body if isinstance(n, ast.Assign)}
        if path.name == "one_on_ones.py"
        else set()
    )
    found = []
    loop_vars = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            src = chain_names(node.iter)
            if "ROSTER" in src or "roster" in src or "team" in src:
                loop_vars.add(node.target.id)
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets = (
                []
                if id(node) in top_defs and "ROSTER" in chain_names(node.targets[0])
                else node.targets
            )
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        elif isinstance(node, ast.Delete):
            targets = node.targets
        for t in targets:
            names = chain_names(t)
            if "ROSTER" in names or (
                isinstance(t, ast.Subscript)
                and chain_names(t.value)[:1]
                and chain_names(t.value)[0] in loop_vars
            ):
                found.append((node.lineno, "assignment"))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in MUTATORS
        ):
            names = chain_names(node.func.value)
            if "ROSTER" in names or (names and names[0] in loop_vars):
                found.append((node.lineno, node.func.attr))
    return found


class RosterIdentityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.dash = self.root / "state" / "dashboard"
        self.dash.mkdir(parents=True)
        os.environ["OPSCENTER_ROOT"] = str(self.root)
        import one_on_ones

        self.oo = importlib.reload(one_on_ones)
        self.oo.ROSTER = copy.deepcopy(PLACEHOLDER_ROSTER)
        self.oo.DR_RAW.parent.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("OPSCENTER_ROOT", None)

    def pull(self, rows):
        self.oo.DR_RAW.write_text(json.dumps({"value": rows}))

    def test_core_rule_1_1_directory_pull_wins_over_the_code_copy(self):
        # core-rule: identity-and-people-data.1.1 (the directory owns title and email, the code holds neither for a report)
        self.pull(
            [
                {
                    "displayName": "Report One",
                    "jobTitle": "Role Z",
                    "mail": "Report.One@Example.Com",
                },
                {
                    "displayName": "Report Two",
                    "jobTitle": "Role B",
                    "mail": "report.two@example.com",
                },
            ]
        )
        rows = {p["name"]: p for p in self.oo.roster()}
        self.assertEqual(rows["Report One"]["title"], "Role Z")
        self.assertEqual(rows["Report One"]["email"], "report.one@example.com")
        self.assertEqual(
            self.oo.ROSTER,
            PLACEHOLDER_ROSTER,
            "reading the directory never rewrites the code roster",
        )
        for p in real_roster():
            if p.get("group", "report") == "report":
                self.assertNotIn("email", p, "a report's address is never kept in code")
                self.assertNotIn("title", p, "a report's title is never kept in code")

    def test_core_rule_1_1_the_copy_is_written_from_a_successful_pull(self):
        # core-rule: identity-and-people-data.1.1 (the fallback copy is a copy of the last pull and nothing else)
        self.assertFalse(self.oo.ROSTER_COPY.exists(), "no copy before a pull")
        self.pull(
            [{"displayName": "Report One", "jobTitle": "Role Z", "mail": "report.one@example.com"}]
        )
        self.oo.roster()
        doc = json.loads(self.oo.ROSTER_COPY.read_text())
        self.assertEqual(doc["people"]["Report One"]["title"], "Role Z")
        self.assertEqual(doc["people"]["Report One"]["email"], "report.one@example.com")
        self.assertEqual(set(doc["people"]), {"Report One"}, "only people the pull listed")
        # a failed pull never writes the copy
        before = self.oo.ROSTER_COPY.read_bytes()
        self.oo.DR_RAW.write_text("{not json")
        self.oo.roster()
        self.assertEqual(self.oo.ROSTER_COPY.read_bytes(), before)

    def test_core_rule_1_1_the_copy_is_read_only_when_the_pull_fails_and_is_marked_stale(self):
        # core-rule: identity-and-people-data.1.1 (read only if the pull fails, marked stale with its age, pull wins on success)
        self.pull(
            [{"displayName": "Report One", "jobTitle": "Role Z", "mail": "report.one@example.com"}]
        )
        people, meta = self.oo.roster_state()
        self.assertFalse(meta["stale"], "a good pull is never marked stale")
        self.assertTrue(meta["pull_ok"])
        pulled_at = json.loads(self.oo.ROSTER_COPY.read_text())["people"]["Report One"]["pulled"]
        # the directory changes: the pull wins over the copy
        self.pull(
            [
                {
                    "displayName": "Report One",
                    "jobTitle": "Role New",
                    "mail": "report.one@example.com",
                }
            ]
        )
        people, meta = self.oo.roster_state()
        self.assertEqual({p["name"]: p for p in people}["Report One"]["title"], "Role New")
        self.assertFalse(meta["stale"])
        # the pull fails: the copy is read and the board is told it is stale, with its age
        self.oo.DR_RAW.unlink()
        people, meta = self.oo.roster_state()
        row = {p["name"]: p for p in people}["Report One"]
        self.assertEqual((row["title"], row["email"]), ("Role New", "report.one@example.com"))
        self.assertTrue(meta["stale"])
        self.assertFalse(meta["pull_ok"])
        self.assertEqual(meta["names"], ["Report One"])
        self.assertEqual(
            meta["as_of"],
            json.loads(self.oo.ROSTER_COPY.read_text())["people"]["Report One"]["pulled"],
        )
        self.assertTrue(meta["as_of"] and pulled_at)
        self.assertEqual(
            meta["missing"], ["Report Two"], "someone never pulled has no value, and says so"
        )
        # the board payload carries the same marker for the screen
        self.assertTrue(self.oo.board()["roster"]["stale"])

    def test_core_rule_1_1_a_hand_edited_copy_is_never_read(self):
        # core-rule: identity-and-people-data.1.1 (no copy is edited by hand, so an edited copy is ignored)
        self.pull(
            [{"displayName": "Report One", "jobTitle": "Role Z", "mail": "report.one@example.com"}]
        )
        self.oo.roster()
        doc = json.loads(self.oo.ROSTER_COPY.read_text())
        doc["people"]["Report One"]["title"] = "Edited By Hand"
        self.oo.ROSTER_COPY.write_text(json.dumps(doc))
        self.oo.DR_RAW.unlink()
        people, meta = self.oo.roster_state()
        self.assertEqual({p["name"]: p for p in people}["Report One"]["title"], "")
        self.assertIn("Report One", meta["missing"])

    def test_core_rule_1_1_only_the_pull_writes_the_copy(self):
        # core-rule: identity-and-people-data.1.1 (static: ROSTER_COPY is written in one function, called from one place)
        tree = ast.parse((APP / "one_on_ones.py").read_text(encoding="utf8"))
        writers = []
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            for node in ast.walk(fn):
                if (
                    isinstance(node, ast.Name)
                    and node.id == "ROSTER_COPY"
                    and fn.name not in ("_read_roster_copy",)
                ):
                    writers.append(fn.name)
        self.assertEqual(sorted(set(writers)), ["_write_roster_copy"])
        callers = [
            fn.name
            for fn in ast.walk(tree)
            if isinstance(fn, ast.FunctionDef)
            for node in ast.walk(fn)
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_write_roster_copy"
        ]
        self.assertEqual(callers, ["roster_state"])
        for path in APP.glob("*.py"):
            if path.name not in ("one_on_ones.py",) and not path.name.endswith("_test.py"):
                self.assertNotIn("roster-last-pull", path.read_text(encoding="utf8"), path.name)

    def test_core_rule_1_1_no_write_path_edits_an_identity_field(self):
        # core-rule: identity-and-people-data.1.1 (add, status, remove and schedule leave every identity field alone)
        before = copy.deepcopy(self.oo.ROSTER)
        self.pull(
            [
                {
                    "displayName": "Report One",
                    "jobTitle": "Role Z",
                    "mail": "report.one@example.com",
                },
                {
                    "displayName": "Report Two",
                    "jobTitle": "Role B",
                    "mail": "report.two@example.com",
                },
            ]
        )
        pull = self.oo.DR_RAW.read_bytes()
        sent = []
        self.oo._gm = lambda args, payload=None, timeout=90: (
            sent.append(payload) or {"id": "evt", "subject": "s"}
        )
        fp = self.oo.add_topic("Report One", "A topic", "detail")
        with self.assertRaises(ValueError):
            self.oo.add_topic("Not On The Roster", "A topic")
        self.oo.set_status(fp, "discussed")
        self.oo.schedule(
            {
                "person": "Report Two",
                "start": "2026-10-28T10:00",
                "minutes": 30,
                "name": "Spoofed Name",
                "email": "spoofed@example.com",
                "title": "Spoofed Role",
                "what_if": True,
            }
        )
        self.assertEqual(
            sent[0]["email"],
            "report.two@example.com",
            "the invite address comes from the roster, not the request",
        )
        self.assertEqual(sent[0]["name"], "Report Two")
        with self.assertRaises(ValueError):
            self.oo.schedule({"person": "Not On The Roster", "start": "2026-10-28T10:00"})
        self.oo.remove_topic(fp)
        self.assertEqual(self.oo.ROSTER, before)
        self.assertEqual(
            self.oo.DR_RAW.read_bytes(), pull, "no write path touches the directory pull"
        )
        saved = (self.dash / "one-on-ones.json").read_text()
        for row in ("report.one@example.com", "report.two@example.com", "Role Z", "Role B"):
            self.assertNotIn(row, saved)

    def test_core_rule_1_1_nothing_in_the_source_edits_the_roster(self):
        # core-rule: identity-and-people-data.1.1 (static: no statement edits ROSTER or an entry of it)
        offenders = []
        for path in APP.glob("*.py"):
            if path.name.endswith("_test.py"):
                continue
            for line, what in roster_mutations(path):
                offenders.append(f"{path.name}:{line} {what}")
        self.assertEqual(offenders, [])

    def test_core_rule_1_1_the_mutation_scan_sees_a_planted_edit(self):
        # core-rule: identity-and-people-data.1.1 (the scan itself fails on an edit, so a pass means something)
        planted = Path(self.tmp.name) / "planted.py"
        planted.write_text(
            "import one_on_ones\n"
            "one_on_ones.ROSTER.append({})\n"
            "for p in one_on_ones.roster():\n"
            "    p['email'] = 'x'\n"
            "one_on_ones.ROSTER[0]['title'] = 'y'\n"
        )
        self.assertEqual(len(roster_mutations(planted)), 3)

    def test_core_rule_1_2_the_roster_is_held_once(self):
        # core-rule: identity-and-people-data.1.2 (no other source file holds a name or email of the roster)
        roster = real_roster()
        needles = [p["name"] for p in roster] + [p["email"] for p in roster if p.get("email")]
        self.assertGreaterEqual(len(needles), 2)
        offenders = []
        for path in source_files():
            if path.name == "one_on_ones.py":
                continue
            text = path.read_text(encoding="utf8", errors="replace").lower()
            offenders += [f"{path.relative_to(APP)}" for n in needles if n.lower() in text]
        self.assertEqual(sorted(set(offenders)), [])

    def test_core_rule_1_2_no_other_module_builds_its_own_list_of_addresses(self):
        # core-rule: identity-and-people-data.1.2 (no list literal of two or more addresses outside the roster)
        offenders = []
        for path in APP.glob("*.py"):
            if path.name.endswith("_test.py") or path.name == "one_on_ones.py":
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf8"))):
                if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
                    mails = [
                        e
                        for e in node.elts
                        if isinstance(e, ast.Constant)
                        and isinstance(e.value, str)
                        and "@" in e.value
                        and "." in e.value
                    ]
                    if len(mails) >= 2:
                        offenders.append(f"{path.name}:{node.lineno}")
        self.assertEqual(offenders, [])

    def test_core_rule_1_2_features_read_the_one_roster(self):
        # core-rule: identity-and-people-data.1.2 (the away feature reads its people from the one roster)
        import team_away

        team_away = importlib.reload(team_away)
        self.assertEqual(
            team_away.team(), [p for p in self.oo.ROSTER if p.get("group", "report") == "report"]
        )
        self.assertEqual(
            {p["name"] for p in self.oo.roster()}, {p["name"] for p in PLACEHOLDER_ROSTER}
        )


if __name__ == "__main__":
    unittest.main(verbosity=1)
