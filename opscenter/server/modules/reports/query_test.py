"""
query_test.py
Purpose: The report engine. A spec is checked against the stream (unknown fields, operators, metrics and bad dates are refused with a reason), values
         are bound parameters (an injection attempt is only ever a value), filters, grouping, metrics, sorting, limits and truncation work on real
         intake tables, looked-up fields join from the attached cache (a person falls back to the raw name), time buckets label local days, weeks
         (Monday) and months, a between filter counts the last day in full, and future-dated events are found and left off.
Run:     python3 query_test.py
"""

import datetime as dt
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from log_intake import current_store, stream_store  # noqa: E402
from log_intake import streams as ls  # noqa: E402

from reports import directory, query  # noqa: E402

NOW = dt.datetime.now(dt.timezone.utc)


def ago(days, hour=12):
    d = (NOW - dt.timedelta(days=days)).date()
    return dt.datetime(d.year, d.month, d.day, hour, tzinfo=dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


FIELDS = [
    {"name": "UserName", "kind": "string"},
    {"name": "Ext", "kind": "string"},
    {"name": "Count", "kind": "int"},
    {"name": "Enabled", "kind": "boolean"},
    {"name": "At", "kind": "datetime"},
]


def setup_env(test):
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    os.environ["LOG_INTAKE_DB"] = str(Path(tmp.name) / "i.db")
    os.environ["OPSCENTER_REPORTS_DB"] = str(Path(tmp.name) / "r.db")
    test.addCleanup(
        lambda: [
            os.environ.pop(k, None)
            for k in ("LOG_INTAKE_DB", "OPSCENTER_REPORTS_DB", "OPSCENTER_REPORTS_TZ")
        ]
    )
    stream_store.create_stream(
        {"key": "ext", "name": "Ext", "tableName": "Ext", "fields": FIELDS}, "t"
    )
    return stream_store.get_stream("ext")


def post(stream, device, snap, collected, records):
    rows = ls.clean_records(stream, records)["rows"]
    current_store.save_current(stream["key"], device, snap, collected, rows, stream["mode"])


class Base(unittest.TestCase):
    def setUp(self):
        self.stream = setup_env(self)
        post(
            self.stream,
            "PC1",
            "a",
            ago(1),
            [
                {
                    "UserName": "CORP\\Alice",
                    "Ext": "Dash",
                    "Count": 3,
                    "Enabled": True,
                    "At": ago(2),
                },
                {
                    "UserName": "CORP\\Bob",
                    "Ext": "Dash",
                    "Count": 5,
                    "Enabled": False,
                    "At": ago(40),
                },
            ],
        )
        post(
            self.stream,
            "PC2",
            "b",
            ago(10),
            [
                {
                    "UserName": "CORP\\Alice",
                    "Ext": "Notes",
                    "Count": 7,
                    "Enabled": True,
                    "At": ago(3),
                }
            ],
        )
        post(
            self.stream,
            "PC3",
            "c",
            ago(0),
            [{"UserName": "x", "Ext": "Clock", "Count": 1, "At": "2999-01-01T00:00:00Z"}],
        )
        self.con = query.connect()
        self.addCleanup(self.con.close)

    def run_(self, **kw):
        return query.run_local(self.stream, {**query.empty_spec(), **kw}, self.con)

    def cell(self, **kw):
        return self.run_(**kw)["rows"]


class Checks(Base):
    def problem(self, **kw):
        return query.check_spec(self.stream, {**query.empty_spec(), **kw})

    def test_a_good_spec_has_no_problem(self):
        self.assertIsNone(self.problem(groupBy=["Ext"], metrics=["rows"]))

    def test_unknown_things_are_refused_with_a_reason(self):
        self.assertIn(
            "Unknown field in filter",
            self.problem(filters=[{"field": "Nope", "op": "eq", "value": "x"}]),
        )
        self.assertIn(
            "Unknown filter operator",
            self.problem(filters=[{"field": "Ext", "op": "drop", "value": "x"}]),
        )
        self.assertIn("Unknown group field", self.problem(groupBy=["Nope"], metrics=["rows"]))
        self.assertIn("Unknown metric", self.problem(metrics=["median:Count"]))
        self.assertIn("needs a number field", self.problem(metrics=["sum:Ext"]))
        self.assertIn("at least one metric", self.problem(groupBy=["Ext"]))
        self.assertIn("match must be", self.problem(match="some"))

    def test_value_and_date_rules(self):
        self.assertIn("needs a value", self.problem(filters=[{"field": "Ext", "op": "eq"}]))
        self.assertIn(
            "whole number of days",
            self.problem(filters=[{"field": "At", "op": "withinDays", "value": "1.5"}]),
        )
        self.assertIn(
            "two dates",
            self.problem(
                filters=[{"field": "At", "op": "between", "value": "2026-01-02,2026-01-01"}]
            ),
        )
        self.assertIsNone(self.problem(filters=[{"field": "At", "op": "inFuture"}]))

    def test_a_bucket_needs_a_time_field(self):
        self.assertIsNone(self.problem(groupBy=["day:At"], metrics=["rows"]))
        self.assertIn("Unknown group field", self.problem(groupBy=["day:Ext"], metrics=["rows"]))
        self.assertIn("Unknown group field", self.problem(groupBy=["year:At"], metrics=["rows"]))

    def test_a_retired_field_is_not_a_field(self):
        s = {
            **self.stream,
            "fields": [{**f, "retired": f["name"] == "Ext"} for f in self.stream["fields"]],
        }
        self.assertIn(
            "Unknown group field",
            query.check_spec(s, {**query.empty_spec(), "groupBy": ["Ext"], "metrics": ["rows"]}),
        )

    def test_a_refused_spec_never_reaches_the_database(self):
        with self.assertRaises(ValueError):
            self.run_(groupBy=["Nope"], metrics=["rows"])


class Safety(Base):
    def test_an_injection_attempt_is_only_a_value(self):
        evil = "x'); DROP TABLE log_stream_current; --"
        self.assertEqual(
            self.cell(filters=[{"field": "Ext", "op": "eq", "value": evil}], metrics=["rows"]),
            [[0]],
        )
        self.assertEqual(
            self.cell(filters=[{"field": "Ext", "op": "in", "value": evil}], metrics=["rows"]),
            [[0]],
        )
        self.assertEqual(self.cell(metrics=["rows"]), [[4]])

    def test_a_sort_name_that_is_not_a_column_is_refused(self):
        with self.assertRaises(ValueError):
            self.run_(metrics=["rows"], sort={"by": "1; DROP TABLE x", "dir": "asc"})

    def test_the_spec_cannot_reach_another_stream(self):
        stream_store.create_stream(
            {
                "key": "other",
                "name": "O",
                "tableName": "Other",
                "fields": [{"name": "Secret", "kind": "string"}],
            },
            "t",
        )
        other = stream_store.get_stream("other")
        post(other, "PC9", "z", ago(0), [{"Secret": "hunter2"}])
        self.assertEqual(
            self.cell(
                filters=[{"field": "Ext", "op": "contains", "value": "hunter2"}], metrics=["rows"]
            ),
            [[0]],
        )


class Operators(Base):
    def rows(self, field, op, value=None):
        f = {"field": field, "op": op}
        if value is not None:
            f["value"] = value
        return self.cell(filters=[f], metrics=["rows"])[0][0]

    def test_text_operators_ignore_case(self):
        self.assertEqual(self.rows("Ext", "eq", "dash"), 2)
        self.assertEqual(self.rows("Ext", "ne", "DASH"), 2)
        self.assertEqual(self.rows("Ext", "contains", "OTE"), 1)
        self.assertEqual(self.rows("Ext", "startsWith", "da"), 2)
        self.assertEqual(self.rows("Ext", "in", "dash, notes"), 3)
        self.assertEqual(self.rows("Ext", "notIn", "dash"), 2)

    def test_empty_and_not_empty(self):
        self.assertEqual(self.rows("Enabled", "empty"), 1)
        self.assertEqual(self.rows("Enabled", "notEmpty"), 3)

    def test_numbers_compare_as_numbers(self):
        self.assertEqual(self.rows("Count", "gt", "3"), 2)
        self.assertEqual(self.rows("Count", "gte", "3"), 3)
        self.assertEqual(self.rows("Count", "lt", "3"), 1)
        self.assertEqual(self.rows("Count", "lte", "10"), 4)

    def test_time_operators(self):
        # a future date is "within" any window; dashboards add notFuture, which is why they never count it
        self.assertEqual(self.rows("At", "withinDays", "5"), 3)
        self.assertEqual(self.rows("At", "olderThanDays", "30"), 1)
        self.assertEqual(self.rows("At", "inFuture"), 1)
        self.assertEqual(self.rows("At", "notFuture"), 3)

    def test_between_counts_the_last_day_in_full(self):
        day = (NOW - dt.timedelta(days=3)).date().isoformat()
        self.assertEqual(self.rows("At", "between", f"{day},{day}"), 0 + 1)
        us = (NOW - dt.timedelta(days=3)).date().strftime("%m/%d/%Y").lstrip("0")
        self.assertEqual(self.rows("At", "between", f"{us},{us}"), 1)

    def test_match_any_needs_one(self):
        f = [
            {"field": "Ext", "op": "eq", "value": "Notes"},
            {"field": "Ext", "op": "eq", "value": "Clock"},
        ]
        self.assertEqual(self.cell(match="any", filters=f, metrics=["rows"]), [[2]])
        self.assertEqual(self.cell(match="all", filters=f, metrics=["rows"]), [[0]])


class Shape(Base):
    def test_group_and_metrics(self):
        r = self.run_(
            groupBy=["Ext"],
            metrics=["rows", "devices", "sum:Count", "avg:Count", "max:Count", "distinct:UserName"],
            sort={"by": "Ext", "dir": "asc"},
        )
        self.assertEqual(
            [c["name"] for c in r["columns"]],
            ["Ext", "Rows", "Devices", "Sum Count", "Avg Count", "Max Count", "Distinct UserName"],
        )
        self.assertEqual(r["rows"][0][:5], ["Clock", 1, 1, 1.0, 1.0])
        self.assertEqual(r["rows"][1], ["Dash", 2, 1, 8.0, 4.0, 5, 2])

    def test_default_order_is_the_first_measure_descending(self):
        self.assertEqual([r[0] for r in self.cell(groupBy=["Ext"], metrics=["rows"])][0], "Dash")

    def test_list_mode_puts_the_device_first_and_booleans_are_booleans(self):
        r = self.run_(columns=["Enabled"], sort={"by": "Device", "dir": "asc"})
        self.assertEqual(r["columns"][0]["name"], "Device")
        self.assertEqual(
            sorted({tuple(x) for x in r["rows"]}, key=str),
            sorted({("PC1", True), ("PC1", False), ("PC2", True), ("PC3", None)}, key=str),
        )

    def test_last_report_and_limit_truncation(self):
        self.assertEqual(
            self.run_(
                groupBy=["@device"], metrics=["lastReport"], sort={"by": "Device", "dir": "asc"}
            )["columns"][1]["type"],
            "datetime",
        )
        r = self.run_(groupBy=["Ext"], metrics=["rows"], limit=2)
        self.assertEqual((len(r["rows"]), r["truncated"]), (2, True))

    def test_events_streams_read_the_event_table(self):
        stream_store.create_stream(
            {
                "key": "ev",
                "name": "E",
                "tableName": "Ev",
                "mode": "events",
                "fields": [{"name": "Num", "kind": "int"}],
            },
            "t",
        )
        ev = stream_store.get_stream("ev")
        post(ev, "PC1", "e1", ago(1), [{"Num": 1}])
        post(ev, "PC1", "e2", ago(1), [{"Num": 2}])
        self.assertEqual(
            query.run_local(ev, {**query.empty_spec(), "metrics": ["rows", "sum:Num"]}, self.con)[
                "rows"
            ],
            [[2, 3.0]],
        )


class Buckets(Base):
    def test_labels_are_local_day_week_monday_and_month(self):
        self.assertEqual(
            query.bucket_time("2026-11-04T03:00:00Z", "day", "America/New_York"), "2026-11-03"
        )
        self.assertEqual(query.bucket_time("2026-11-04 12:00:00", "day", "UTC"), "2026-11-04")
        self.assertEqual(query.bucket_time("2026-11-04T12:00:00Z", "week", "UTC"), "2026-11-02")
        self.assertEqual(query.bucket_time("2026-11-04T12:00:00Z", "month", "UTC"), "2026-11")
        self.assertIsNone(query.bucket_time("", "day"))
        self.assertIsNone(query.bucket_time("not a time", "day"))
        self.assertIsNone(query.bucket_time(5, "day"))

    def test_group_by_day_blanks_what_is_not_a_time(self):
        r = self.cell(groupBy=["day:At"], metrics=["rows"], sort={"by": "Day", "dir": "asc"})
        self.assertTrue(all(isinstance(x[0], str) or x[0] is None for x in r))
        self.assertEqual(sum(x[1] for x in r), 4)

    def test_the_zone_is_configuration(self):
        os.environ["OPSCENTER_REPORTS_TZ"] = "Pacific/Kiritimati"
        self.assertEqual(query.bucket_time("2026-11-04T12:00:00Z", "day"), "2026-11-05")


class Days(unittest.TestCase):
    def test_the_three_formats(self):
        for text in ("2026-03-09", "3/9/2026", "03092026"):
            self.assertEqual(query.parse_day(text), dt.date(2026, 3, 9))
        for bad in ("", "2026-13-01", "13/40/2026", "1999-01-01", "x", None):
            self.assertIsNone(query.parse_day(bad))

    def test_a_range_across_a_clock_change_is_whole_days(self):
        lo, hi = query.day_range("2026-03-08,2026-03-08", "America/New_York")
        self.assertEqual((lo, hi), ("2026-03-08 05:00:00", "2026-03-09 04:00:00"))

    def test_a_bad_range_is_none(self):
        for bad in ("2026-03-09", "2026-03-09,2026-03-01", "a,b", ""):
            self.assertIsNone(query.day_range(bad))


class Lookups(Base):
    def setUp(self):
        super().setUp()
        d = [
            {
                "displayName": "Alice A",
                "userPrincipalName": "a@example.com",
                "mail": "a@example.com",
                "department": "Ops",
                "jobTitle": "Lead",
                "accountEnabled": True,
            }
        ]
        directory.reset_pause()
        directory.enrich_accounts(
            ["corp\\alice"], None, lambda k, v: d if k == "account" and v == "alice" else []
        )
        self.con.close()
        self.con = query.connect()

    def test_a_looked_up_field_joins_and_a_person_falls_back_to_the_raw_name(self):
        r = self.cell(groupBy=["@user"], metrics=["rows"], sort={"by": "User", "dir": "asc"})
        self.assertEqual(r, [["Alice A", 2], ["CORP\\Bob", 1], ["x", 1]])

    def test_other_looked_up_fields_are_blank_when_unresolved(self):
        r = self.cell(
            groupBy=["@department"], metrics=["rows"], sort={"by": "Department", "dir": "asc"}
        )
        self.assertEqual(r, [[None, 2], ["Ops", 2]])

    def test_a_filter_on_a_looked_up_field(self):
        self.assertEqual(
            self.cell(
                filters=[{"field": "@department", "op": "eq", "value": "ops"}], metrics=["rows"]
            ),
            [[2]],
        )

    def test_a_stream_without_the_key_field_cannot_use_a_lookup(self):
        s = {**self.stream, "fields": [f for f in self.stream["fields"] if f["name"] != "UserName"]}
        self.assertIn(
            "Unknown group field",
            query.check_spec(s, {**query.empty_spec(), "groupBy": ["@user"], "metrics": ["rows"]}),
        )

    def test_row_columns_include_every_resolvable_lookup(self):
        cols = query.row_columns_for(self.stream, {"filters": [], "groupBy": []})
        self.assertIn("@user", cols)
        self.assertNotIn("@publisher", cols)
        self.assertEqual(cols[: len(FIELDS)], [f["name"] for f in FIELDS])


class Off(unittest.TestCase):
    def test_importing_creates_no_file(self):
        with tempfile.TemporaryDirectory() as t:
            os.environ["LOG_INTAKE_DB"] = str(Path(t) / "i.db")
            os.environ["OPSCENTER_REPORTS_DB"] = str(Path(t) / "r.db")
            try:
                import importlib

                importlib.reload(query)
                self.assertEqual(list(Path(t).iterdir()), [])
            finally:
                os.environ.pop("LOG_INTAKE_DB", None)
                os.environ.pop("OPSCENTER_REPORTS_DB", None)


if __name__ == "__main__":
    unittest.main()
