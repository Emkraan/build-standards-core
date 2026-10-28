import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import contract as c  # noqa: E402

SCHEMA = json.loads((Path(__file__).resolve().parent / "board.schema.json").read_text())


def item(**kw):
    base = {
        "key": "disk-full",
        "priority": "high",
        "title": "Disk full on a server",
        "why": "It stops backups.",
        "action": "Free space.",
        "owner": "",
        "refs": [],
        "sources": [],
        "cids": ["c1"],
    }
    base.update(kw)
    return base


def doc(items=None, dropped=None):
    return {
        "generated_utc": "2026-10-28T10:00:00Z",
        "headline": "h",
        "items": items if items is not None else [item()],
        "dropped": dropped or [],
    }


class Validate(unittest.TestCase):
    def test_a_good_file_has_no_errors(self):
        self.assertEqual(c.validate(doc()), [])

    def test_not_an_object_and_missing_fields(self):
        self.assertEqual(c.validate([]), ["the file is not a JSON object"])
        errs = c.validate({})
        self.assertEqual(len([e for e in errs if e.startswith("missing top-level")]), 4)

    def test_item_fields_and_types(self):
        errs = c.validate(doc([item(title=" ", priority="urgent", refs="x", owner=None)]))
        text = " | ".join(errs)
        self.assertIn("missing or empty title", text)
        self.assertIn("priority 'urgent' is not one of", text)
        self.assertIn("refs must be a list of strings", text)
        self.assertIn("owner must be present as a string", text)

    def test_duplicate_and_reserved_keys(self):
        errs = c.validate(doc([item(key="A"), item(key="a", cids=["c2"])]))
        self.assertTrue(any("duplicate key" in e for e in errs))
        for prefix in c.RESERVED_PREFIXES:
            errs = c.validate(doc([item(key=prefix + "x")]))
            self.assertTrue(
                any("prefix the ops center owns" in e or "owns" in e for e in errs), prefix
            )

    def test_coverage_every_must_cid_is_an_item_or_a_drop(self):
        d = doc([item(cids=["c1"])], dropped=[{"cid": "c2", "reason": "noise"}])
        self.assertEqual(c.validate(d, must=["c1", "c2"]), [])
        errs = c.validate(d, must=["c1", "c2", "c3"])
        self.assertTrue(any("c3" in e for e in errs))
        self.assertEqual(c.validate(d, must=None), [])  # coverage unknown: structure only

    def test_a_drop_needs_a_reason(self):
        errs = c.validate(doc(dropped=[{"cid": "c9"}]))
        self.assertTrue(errs)

    def test_must_cids(self):
        self.assertEqual(
            c.must_cids({"candidates_must": [{"cid": "a"}, {"cid": ""}, "x", {"cid": "b"}]}),
            ["a", "b"],
        )
        self.assertEqual(c.must_cids(None), [])

    def test_the_schema_file_agrees_on_the_required_fields(self):
        self.assertEqual(sorted(SCHEMA["required"]), sorted(c.REQUIRED_TOP))
        self.assertEqual(
            sorted(SCHEMA["properties"]["items"]["items"]["required"]),
            sorted(c.REQUIRED_ITEM_STR + c.REQUIRED_ITEM_PRESENT_STR + c.REQUIRED_ITEM_LIST),
        )


class Settle(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.dash = Path(self._d.name)
        self.now = time.time() + 100  # the files below are older than QUIET_S

    def tearDown(self):
        self._d.cleanup()

    def put(self, data):
        p = self.dash / c.FILE
        p.write_text(data if isinstance(data, str) else json.dumps(data))
        return p

    def test_missing_and_pending(self):
        self.assertEqual(c.settle(self.dash, self.now)["status"], "missing")
        self.put(doc())
        self.assertEqual(c.settle(self.dash)["status"], "pending")  # touched a moment ago

    def test_a_good_file_is_accepted_then_unchanged(self):
        self.put(doc())
        self.assertEqual(c.settle(self.dash, self.now)["status"], "accepted")
        self.assertTrue((self.dash / c.LAST_GOOD).is_file())
        self.assertEqual(c.settle(self.dash, self.now)["status"], "unchanged")

    def test_a_bad_file_is_rejected_the_last_good_is_restored_and_the_streak_grows(self):
        self.put(doc())
        c.settle(self.dash, self.now)
        self.put({"headline": "x"})
        r = c.settle(self.dash, self.now)
        self.assertEqual((r["status"], r["streak"]), ("rejected", 1))
        self.assertEqual(
            json.loads((self.dash / c.FILE).read_text())["items"][0]["key"], "disk-full"
        )
        self.assertTrue((self.dash / c.REJECTED).is_file())
        self.put("{not json")
        self.assertEqual(c.settle(self.dash, self.now)["streak"], 2)
        newer = doc()
        newer["headline"] = "a different good file"
        self.put(newer)
        self.assertEqual(c.settle(self.dash, self.now + 1)["streak"], 0)

    def test_a_rejected_file_with_no_last_good_leaves_an_empty_board_with_an_old_time(self):
        self.put("[]")
        r = c.settle(self.dash, self.now)
        self.assertEqual(r["status"], "rejected")
        self.assertEqual(json.loads((self.dash / c.FILE).read_text())["items"], [])
        self.assertEqual((self.dash / c.FILE).stat().st_mtime, 0)

    def test_coverage_uses_the_wake_file_only_for_the_run_that_wrote_the_file(self):
        wake = self.dash / "wake.json"
        p = self.put(doc())
        mtime = p.stat().st_mtime
        wake.write_text(json.dumps({"must_cids": ["c1", "zz"], "woke_at": mtime - 5}))
        self.assertEqual(c.wake_cids_for(mtime, wake), ["c1", "zz"])
        wake.write_text(json.dumps({"must_cids": ["c1"], "woke_at": mtime + 5}))
        self.assertIsNone(c.wake_cids_for(mtime, wake))  # a later wake belongs to the next run
        wake.write_text("{nope")
        self.assertIsNone(c.wake_cids_for(mtime, wake))
        wake.write_text(json.dumps({"must_cids": ["c1", "zz"], "woke_at": mtime - 5}))
        r = c.settle(self.dash, self.now, wake)
        self.assertEqual(r["status"], "rejected")
        self.assertTrue(r["coverage_checked"])

    def test_main_prints_a_verdict_and_returns_the_exit_code(self):
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()) as out:
            good = self.put(doc())
            self.assertEqual(c.main(["contract.py", str(good)]), 0)
            bad = self.put({"headline": 3})
            self.assertEqual(c.main(["contract.py", str(bad)]), 1)
            self.assertEqual(c.main(["contract.py", str(self.dash / "none.json")]), 1)
        self.assertIn("rejected", out.getvalue())


if __name__ == "__main__":
    unittest.main()
