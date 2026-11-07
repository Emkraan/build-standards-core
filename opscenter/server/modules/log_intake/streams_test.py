"""
streams_test.py
Purpose: The pure stream rules: only tables in the configured namespace are owned; field names are validated (reserved, bad and duplicate names are
         refused); a schema edit adds, removes and retypes without ever reusing a column (a retired column stays, a retype allocates a new one);
         destructive edits are flagged; clean_records maps declared fields to columns, types them, keeps unknown keys in a capped Extra, cleans
         dashes and control characters and drops rows missing a required field.
Run:     python3 streams_test.py
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from log_intake import streams as s


def f(name, kind="string", required=False):
    return {"name": name, "kind": kind, "required": required}


class Namespace(unittest.TestCase):
    def setUp(self):
        self._saved = {
            k: os.environ.pop(k, None)
            for k in ("LOG_INTAKE_TABLE_PREFIX", "LOG_INTAKE_TABLE_SUFFIX")
        }

    def tearDown(self):
        for k, v in self._saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    def test_only_tables_in_the_namespace_are_owned(self):
        self.assertTrue(s.is_owned_table("Stream_Browser"))
        for bad in (
            "Browser",
            "Stream_",
            "Stream_a_b",
            "Stream_" + "x" * 37,
            "Other_Browser",
            "Heartbeat",
            "",
            None,
            5,
        ):
            self.assertFalse(s.is_owned_table(bad), bad)
        with self.assertRaises(ValueError):
            s.assert_stream_table("Heartbeat")
        s.assert_stream_table("Stream_Ok")

    def test_the_prefix_and_suffix_are_configuration(self):
        os.environ["LOG_INTAKE_TABLE_PREFIX"] = "Acme_"
        os.environ["LOG_INTAKE_TABLE_SUFFIX"] = "_CL"
        self.assertEqual(s.table_for("Ext"), "Acme_Ext_CL")
        self.assertTrue(s.is_owned_table("Acme_Ext_CL"))
        self.assertFalse(s.is_owned_table("Acme_Ext"))
        self.assertFalse(s.is_owned_table("Stream_Ext"))
        self.assertFalse(s.is_owned_table("Acme__CL"))

    def test_table_names_are_letters_and_digits_only(self):
        for bad in ("", "a b", "a-b", "x" * 37, None):
            with self.assertRaises(ValueError):
                s.table_for(bad)
        self.assertEqual(s.table_for("A1"), "Stream_A1")


class Schema(unittest.TestCase):
    def test_adds_removes_and_retypes_without_ever_reusing_a_column(self):
        p1 = s.plan_schema([], [f("AA"), f("BB", "int")])
        self.assertEqual([x["column"] for x in p1["fields"]], ["AA", "BB"])
        self.assertFalse(p1["destructive"])
        cur = p1["fields"]
        p2 = s.plan_schema(cur, [f("AA"), f("BB", "string"), f("CC")])
        self.assertEqual(p2["added"], ["CC"])
        self.assertEqual(
            p2["retyped"], [{"name": "BB", "from": "int", "to": "string", "newColumn": "BB_2"}]
        )
        self.assertTrue(p2["destructive"])
        self.assertTrue(next(x for x in p2["fields"] if x["column"] == "BB")["retired"])
        p3 = s.plan_schema(p2["fields"], [f("AA")])
        self.assertEqual(sorted(p3["removed"]), ["BB", "CC"])
        p4 = s.plan_schema(p3["fields"], [f("AA"), f("BB", "int")])
        self.assertEqual([x["column"] for x in p4["fields"] if not x["retired"]], ["AA", "BB_3"])

    def test_reserved_bad_and_duplicate_names_are_refused(self):
        p = s.plan_schema([], [f("TimeGenerated"), f("a"), f("Dup"), f("dup"), f("ok", "weird")])
        self.assertGreaterEqual(len(p["errors"]), 4)
        self.assertIn("reserved", " ".join(p["errors"]))
        self.assertIn("listed twice", " ".join(p["errors"]))
        self.assertIn("unknown type", " ".join(p["errors"]))

    def test_the_sinks_own_reserved_names_are_added_by_the_caller(self):
        self.assertIsNone(s.validate_field_name("Title"))
        self.assertIn("reserved", s.validate_field_name("Title", extra_reserved=("title",)))

    def test_at_most_forty_fields(self):
        p = s.plan_schema([], [f(f"Field{i}") for i in range(41)])
        self.assertTrue(any("At most 40" in e for e in p["errors"]))

    def test_a_rename_or_a_required_change_is_a_change_but_not_destructive(self):
        cur = s.plan_schema([], [f("Name")])["fields"]
        p = s.plan_schema(cur, [f("Name", required=True)])
        self.assertTrue(p["changed"])
        self.assertFalse(p["destructive"])
        self.assertFalse(s.plan_schema(cur, [f("Name")])["changed"])


class Clean(unittest.TestCase):
    STREAM = {
        "fields": [
            {
                "name": "UserName",
                "column": "UserName",
                "kind": "string",
                "required": True,
                "retired": False,
            },
            {
                "name": "Count",
                "column": "Count",
                "kind": "int",
                "required": False,
                "retired": False,
            },
            {
                "name": "Seen",
                "column": "Seen",
                "kind": "datetime",
                "required": False,
                "retired": False,
            },
            {"name": "Old", "column": "Old", "kind": "string", "required": False, "retired": True},
        ]
    }

    def test_maps_types_and_keeps_unknown_keys_in_extra(self):
        r = s.clean_records(
            self.STREAM,
            [
                {
                    "UserName": "  a\u2014b  ",
                    "Count": 3,
                    "Seen": "2026-11-07T10:00:00Z",
                    "Misc": "kept",
                    "Old": "ignored",
                    "DeviceName": "x",
                },
                "not an object",
                {"Count": 1},
            ],
        )
        self.assertEqual(r["rejected"], 2)  # one non-object, one missing the required field
        row = r["rows"][0]
        self.assertEqual(
            (row["UserName"], row["Count"], row["Seen"]), ("a-b", 3, "2026-11-07T10:00:00.000Z")
        )
        self.assertEqual(row["Extra"], {"Misc": "kept", "DeviceName": "x", "Old": "ignored"})
        self.assertNotIn("Old", row)  # a retired column no longer receives data

    def test_values_of_the_wrong_type_become_null(self):
        row = s.clean_records(self.STREAM, [{"UserName": "u", "Count": "3", "Seen": "garbage"}])[
            "rows"
        ][0]
        self.assertEqual((row["Count"], row["Seen"]), (None, None))
        self.assertEqual(
            s.clean_records(self.STREAM, [{"UserName": "u", "Count": 3.0}])["rows"][0]["Count"], 3
        )
        self.assertIsNone(
            s.clean_records(self.STREAM, [{"UserName": "u", "Count": True}])["rows"][0]["Count"]
        )
        self.assertIsNone(
            s.clean_records(self.STREAM, [{"UserName": "u", "Count": 3.5}])["rows"][0]["Count"]
        )

    def test_control_characters_and_length_are_cleaned(self):
        row = s.clean_records(self.STREAM, [{"UserName": "a\x00b\tc" + "z" * 400}])["rows"][0]
        self.assertTrue(row["UserName"].startswith("a b c"))
        self.assertEqual(len(row["UserName"]), s.MAX_FIELD_LENGTH)

    def test_extra_is_capped_by_keys_and_bytes(self):
        rec = {"UserName": "u"}
        rec.update({f"Key{i:02d}": "v" for i in range(30)})
        self.assertEqual(
            len(s.clean_records(self.STREAM, [rec])["rows"][0]["Extra"]), s.MAX_EXTRA_KEYS
        )
        big = {"UserName": "u", **{f"K{i:02d}": "x" * 299 for i in range(20)}}
        self.assertIsNone(
            s.clean_records(self.STREAM, [big])["rows"][0]["Extra"]
        )  # over the byte cap: dropped whole
        self.assertIsNone(s.clean_records(self.STREAM, [{"UserName": "u"}])["rows"][0]["Extra"])

    def test_an_extra_key_that_is_not_a_valid_field_name_is_skipped(self):
        row = s.clean_records(
            self.STREAM, [{"UserName": "u", "TimeGenerated": "x", "bad key": "y", "Fine": 1}]
        )["rows"][0]
        self.assertEqual(row["Extra"], {"Fine": 1})


if __name__ == "__main__":
    unittest.main()
