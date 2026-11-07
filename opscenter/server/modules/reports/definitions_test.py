"""
definitions_test.py
Purpose: Definitions are data: shipped defaults are seeded by version; an unedited copy is replaced when the version rises; an edited
         copy is never overwritten; an edit can be reset to the shipped copy; an export round trips through an import; a bad
         definition (a bad key, no title, a panel with no stream, or with neither a measure nor a spec, too many panels, not JSON) is refused whole and stores
         nothing; a missing or broken store reads as empty.
Run:     python3 definitions_test.py
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import definitions as d


def dash(key="overview", title="Overview", panels=None):
    return {
        "key": key,
        "title": title,
        "panels": panels
        if panels is not None
        else [{"title": "Posts", "stream": "events", "measure": "count"}],
    }


class Store(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "dashboards.json"
        self.s = d.Store(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_seed_adds_missing_keys(self):
        r = self.s.seed([dash(), dash("health", "Health")], 1)
        self.assertEqual((r["added"], r["updated"], r["kept"]), (["overview", "health"], [], []))
        self.assertEqual(self.s.get("overview")["title"], "Overview")
        self.assertEqual([x["key"] for x in self.s.list()], ["health", "overview"])

    def test_a_higher_version_replaces_an_unedited_copy(self):
        self.s.seed([dash()], 1)
        r = self.s.seed([dash(title="Overview v2")], 2)
        self.assertEqual(r["updated"], ["overview"])
        self.assertEqual(self.s.get("overview")["title"], "Overview v2")

    def test_the_same_or_a_lower_version_changes_nothing(self):
        self.s.seed([dash()], 2)
        r = self.s.seed([dash(title="Changed")], 2)
        self.assertEqual(r["kept"], ["overview"])
        r = self.s.seed([dash(title="Older")], 1)
        self.assertEqual(r["kept"], ["overview"])
        self.assertEqual(self.s.get("overview")["title"], "Overview")

    def test_an_edited_copy_is_never_overwritten(self):
        self.s.seed([dash()], 1)
        self.s.save(dash(title="My overview"))
        r = self.s.seed([dash(title="Overview v9")], 9)
        self.assertEqual((r["updated"], r["kept"]), ([], ["overview"]))
        self.assertEqual(self.s.get("overview")["title"], "My overview")
        self.assertTrue(next(x for x in self.s.list() if x["key"] == "overview")["edited"])

    def test_a_reset_puts_the_shipped_copy_back_and_the_next_seed_may_update_it(self):
        shipped = [dash()]
        self.s.seed(shipped, 1)
        self.s.save(dash(title="Mine"))
        self.s.reset("overview", shipped)
        self.assertEqual(self.s.get("overview")["title"], "Overview")
        self.assertFalse(next(x for x in self.s.list() if x["key"] == "overview")["edited"])
        self.assertEqual(self.s.seed([dash(title="v2")], 2)["updated"], ["overview"])
        with self.assertRaises(KeyError):
            self.s.reset("nope", shipped)

    def test_an_export_round_trips_through_an_import(self):
        self.s.seed([dash()], 1)
        text = self.s.export("overview")
        other = d.Store(Path(self.tmp.name) / "other.json")
        self.assertEqual(other.import_(text), "overview")
        self.assertEqual(other.get("overview"), self.s.get("overview"))
        with self.assertRaises(KeyError):
            self.s.export("missing")

    def test_bad_definitions_are_refused_whole(self):
        bad = [
            "not json",
            json.dumps([1]),
            json.dumps(dash(key="Bad Key")),
            json.dumps(dash(title=" ")),
            json.dumps({"key": "x", "title": "t", "panels": "no"}),
            json.dumps(dash(panels=[{"title": "p", "stream": "", "measure": "m"}])),
            json.dumps(dash(panels=[{"title": "p", "stream": "s"}])),
            json.dumps(dash(panels=[{"title": "p", "stream": "s", "measure": "m", "type": "pie"}])),
            json.dumps(dash(panels=[{"title": "p", "stream": "s", "spec": "not an object"}])),
            json.dumps(
                dash(panels=[{"title": "p", "stream": "s", "measure": "m"}] * (d.MAX_PANELS + 1))
            ),
            json.dumps(dash(panels=["not an object"])),
        ]
        for text in bad:
            with self.subTest(text=text[:40]), self.assertRaises(ValueError):
                self.s.import_(text)
        self.assertFalse(self.path.exists())  # nothing was stored

    def test_a_bad_shipped_definition_fails_the_whole_seed(self):
        with self.assertRaises(ValueError):
            self.s.seed([dash(), dash("bad", "")], 1)
        self.assertEqual(self.s.list(), [])

    def test_delete(self):
        self.s.seed([dash()], 1)
        self.s.delete("overview")
        self.assertIsNone(self.s.get("overview"))
        with self.assertRaises(KeyError):
            self.s.delete("overview")

    def test_a_missing_or_broken_store_reads_as_empty(self):
        self.assertEqual(self.s.list(), [])
        self.path.write_text("{broken")
        self.assertEqual(self.s.list(), [])
        self.assertEqual(self.s.seed([dash()], 1)["added"], ["overview"])  # a write recovers

    def test_extra_fields_are_kept(self):
        self.s.save(dict(dash(), layout={"cols": 3}))
        self.assertEqual(self.s.get("overview")["layout"], {"cols": 3})


if __name__ == "__main__":
    unittest.main()
