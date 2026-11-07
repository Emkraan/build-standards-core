"""
dashboards_test.py
Purpose: Dashboard checks and runs. Bad definitions are refused with a reason (ids, types, widths, streams, fields, drill filters, stat and chart
         rules); a run gives every panel its own result and a broken panel its own error, a dropdown narrows a panel only when its stream has the
         field, a longer range widens, a stat compares with the period before and can be a share, future-dated events stay off time panels and
         are reported with the rows behind them, a caller that has gone stops the page, and two different sources give the same dashboard result
         (the source contract).
Run:     python3 dashboards_test.py
"""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reports import dashboards as d  # noqa: E402
from reports import query, sources  # noqa: E402
from reports.query_test import FIELDS, ago, post, setup_env  # noqa: E402


def tile(**kw):
    return {
        "id": "t",
        "title": "T",
        "stream": "ext",
        "type": "stat",
        "w": 3,
        "spec": {"metrics": ["rows"]},
        **kw,
    }


def chart(**kw):
    return {
        "id": "c",
        "title": "C",
        "stream": "ext",
        "type": "bar",
        "w": 6,
        "spec": {"groupBy": ["Ext"], "metrics": ["rows"]},
        **kw,
    }


DASH = {
    "filters": [{"id": "ext", "label": "Extension", "stream": "ext", "field": "Ext"}],
    "panels": [tile(timeField="At"), chart(drill="ext", timeField="At")],
}


class Base(unittest.TestCase):
    def setUp(self):
        self.stream = setup_env(self)
        post(
            self.stream,
            "PC1",
            "a",
            ago(1),
            [
                {"UserName": "u1", "Ext": "Dash", "Count": 1, "At": ago(2)},
                {"UserName": "u2", "Ext": "Dash", "Count": 1, "At": ago(20)},
            ],
        )
        post(
            self.stream,
            "PC2",
            "b",
            ago(1),
            [
                {"UserName": "u1", "Ext": "Notes", "Count": 1, "At": ago(3)},
                {"UserName": "u3", "Ext": "Notes", "Count": 1, "At": ago(40)},
            ],
        )
        post(
            self.stream,
            "PC3",
            "c",
            ago(0),
            [{"UserName": "u4", "Ext": "Clock", "Count": 1, "At": "2999-01-01T00:00:00Z"}],
        )
        self.src = sources.LocalSource()

    def run_(self, spec=DASH, **inp):
        return d.run_dashboard(spec, inp, self.src)


class Check(Base):
    def problem(self, **kw):
        s = copy.deepcopy(DASH)
        s.update(kw)
        return d.check_dashboard(s, self.src)

    def test_the_shipped_shape_is_fine(self):
        self.assertIsNone(self.problem())

    def test_refusals(self):
        self.assertIn("panels must be a list", self.problem(panels="x"))
        self.assertIn("at most 40", self.problem(panels=[tile(id=f"p{i}") for i in range(41)]))
        self.assertIn("defaultRange", self.problem(defaultRange="14"))
        self.assertIn("refreshSeconds", self.problem(refreshSeconds=-1))
        self.assertIn("Duplicate panel id", self.problem(panels=[tile(), tile()]))
        self.assertIn("Panel id must be", self.problem(panels=[tile(id="Bad Id")]))
        self.assertIn("needs a title", self.problem(panels=[tile(title=" ")]))
        self.assertIn("unknown type", self.problem(panels=[tile(type="pie")]))
        self.assertIn("width must be 1 to 12", self.problem(panels=[tile(w=13)]))
        self.assertIn("height must be 1 to 12", self.problem(panels=[tile(h=0)]))
        self.assertIn("stream not found", self.problem(panels=[tile(stream="nope")]))
        self.assertIn("Unknown field in filter", self.problem(panels=[tile(timeField="Nope")]))

    def test_filters_and_drill(self):
        self.assertIn(
            "Filter id",
            self.problem(filters=[{"id": "A b", "label": "x", "stream": "ext", "field": "Ext"}]),
        )
        self.assertIn("Duplicate filter id", self.problem(filters=DASH["filters"] * 2))
        self.assertIn(
            "needs a label",
            self.problem(filters=[{"id": "x", "label": "", "stream": "ext", "field": "Ext"}]),
        )
        self.assertIn(
            "stream not found",
            self.problem(filters=[{"id": "x", "label": "x", "stream": "no", "field": "Ext"}]),
        )
        self.assertIn(
            "Unknown group field",
            self.problem(filters=[{"id": "x", "label": "x", "stream": "ext", "field": "Nope"}]),
        )
        self.assertIn("drill filter", self.problem(panels=[chart(drill="missing")]))

    def test_stat_and_chart_rules(self):
        self.assertIn(
            "cannot group",
            self.problem(panels=[tile(spec={"groupBy": ["Ext"], "metrics": ["rows"]})]),
        )
        self.assertIn("needs a measure", self.problem(panels=[tile(spec={})]))
        self.assertIn(
            "needs a group and a measure", self.problem(panels=[chart(spec={"metrics": ["rows"]})])
        )
        self.assertIsNone(
            self.problem(
                panels=[
                    {
                        "id": "tb",
                        "title": "Rows",
                        "stream": "ext",
                        "type": "table",
                        "w": 12,
                        "spec": {},
                    }
                ]
            )
        )
        self.assertIn(
            "Unknown field",
            self.problem(
                panels=[tile(stat={"shareOf": [{"field": "Nope", "op": "eq", "value": "x"}]})]
            ),
        )

    def test_a_panel_with_only_a_measure_runs_it(self):
        s = {
            "panels": [
                {"title": "T", "stream": "ext", "type": "stat", "w": 3, "measure": "devices"}
            ]
        }
        self.assertIsNone(d.check_dashboard(s, self.src))
        self.assertEqual(d.run_dashboard(s, {}, self.src)["panels"]["0"]["rows"], [[3]])


class Run(Base):
    def test_ranges_and_future_dates(self):
        r = self.run_(range="7")
        self.assertEqual(r["panels"]["t"]["rows"], [[2]])
        self.assertEqual(self.run_(range="30")["panels"]["t"]["rows"], [[3]])
        self.assertEqual(self.run_(range="all")["panels"]["t"]["rows"], [[4]])
        self.assertEqual(r["range"], "7")

    def test_the_default_range_is_30_unless_the_dashboard_says(self):
        self.assertEqual(self.run_()["range"], "30")
        self.assertEqual(self.run_({**DASH, "defaultRange": "7"})["range"], "7")
        self.assertEqual(d.parse_range("junk"), 30)
        self.assertEqual(d.parse_range("9999"), 30)
        self.assertEqual(d.parse_range("all"), "all")

    def test_a_dropdown_narrows_every_panel_and_lists_its_options(self):
        r = self.run_(range="all", selections={"ext": "dash"})
        self.assertEqual(r["panels"]["t"]["rows"], [[2]])
        self.assertEqual(r["panels"]["c"]["rows"], [["Dash", 2]])
        self.assertEqual(r["options"]["ext"], ["Clock", "Dash", "Notes"])

    def test_a_dropdown_skips_a_panel_whose_stream_lacks_the_field(self):
        from log_intake import stream_store

        stream_store.create_stream(
            {
                "key": "oth",
                "name": "O",
                "tableName": "Other",
                "fields": [{"name": "Thing", "kind": "string"}],
            },
            "t",
        )
        post(stream_store.get_stream("oth"), "PC1", "x", ago(0), [{"Thing": "a"}, {"Thing": "b"}])
        spec = {**DASH, "panels": [tile(stream="oth", id="o", spec={"metrics": ["rows"]}), tile()]}
        r = self.run_(spec, range="all", selections={"ext": "dash"})
        self.assertEqual((r["panels"]["o"]["rows"], r["panels"]["t"]["rows"]), ([[2]], [[2]]))

    def test_a_broken_panel_reports_its_own_error(self):
        spec = {**DASH, "panels": [tile(stream="gone"), tile(id="ok")]}
        r = self.run_(spec)
        self.assertIn("Stream not found", r["panels"]["t"]["error"])
        self.assertEqual(r["panels"]["ok"]["rows"], [[5]])

    def test_the_rows_behind_a_panel_carry_the_filters_and_every_field(self):
        rs = self.run_(range="7", selections={"ext": "Dash"})["panels"]["c"]["rowsSpec"]
        ops = [(f["field"], f["op"]) for f in rs["filters"]]
        self.assertIn(("Ext", "eq"), ops)
        self.assertIn(("At", "notFuture"), ops)
        self.assertIn(("At", "withinDays"), ops)
        self.assertEqual(rs["columns"][: len(FIELDS)], [f["name"] for f in FIELDS])
        rows = query.run_local(self.stream, rs, query.connect())
        self.assertEqual(len(rows["rows"]), 1)

    def test_a_match_any_panel_has_no_rows_behind_it(self):
        spec = {
            **DASH,
            "panels": [chart(spec={"match": "any", "groupBy": ["Ext"], "metrics": ["rows"]})],
        }
        self.assertIsNone(self.run_(spec)["panels"]["c"]["rowsSpec"])

    def test_future_dated_events_are_reported_with_the_rows(self):
        f = self.run_()["futureDated"]
        self.assertEqual(
            [(x["stream"], x["field"], x["rows"], x["devices"]) for x in f], [("ext", "At", 1, 1)]
        )
        self.assertEqual(f[0]["rowsSpec"]["filters"], [{"field": "At", "op": "inFuture"}])
        self.assertEqual(self.run_({**DASH, "panels": [tile()]})["futureDated"], [])

    def test_a_caller_that_has_gone_stops_the_page(self):
        calls = []
        with self.assertRaises(RuntimeError):
            d.run_dashboard(
                DASH, {}, self.src, should_stop=lambda: calls.append(1) or len(calls) > 2
            )


class Stat(Base):
    def test_change_against_the_period_before(self):
        spec = {"panels": [tile(timeField="At", stat={"compare": True})]}
        r = self.run_(spec, range="30")["panels"]["t"]["stat"]
        # within 30 days: 3 (At 2, 3, 20 days ago); the 30 days before: 1 (40 days ago)
        self.assertEqual(
            (r["value"], r["previous"], r["change"], r["percent"]), (3, 1, 200.0, False)
        )

    def test_no_comparison_over_all_time(self):
        spec = {"panels": [tile(timeField="At", stat={"compare": True})]}
        r = self.run_(spec, range="all")["panels"]["t"]["stat"]
        self.assertEqual((r["previous"], r["change"]), (None, None))

    def test_a_share_is_a_percent_of_the_base_rows(self):
        spec = {
            "panels": [
                tile(
                    timeField="At",
                    stat={"shareOf": [{"field": "Ext", "op": "eq", "value": "Dash"}]},
                )
            ]
        }
        r = self.run_(spec, range="30")["panels"]["t"]["stat"]
        self.assertEqual((r["value"], r["percent"]), (66.7, True))

    def test_a_share_of_nothing_is_zero_not_a_division(self):
        spec = {
            "panels": [
                tile(
                    timeField="At",
                    spec={
                        "metrics": ["rows"],
                        "filters": [{"field": "Ext", "op": "eq", "value": "zzz"}],
                    },
                    stat={"shareOf": [{"field": "Ext", "op": "eq", "value": "Dash"}]},
                )
            ]
        }
        self.assertEqual(self.run_(spec)["panels"]["t"]["stat"]["value"], 0)

    def test_the_named_column_is_picked(self):
        spec = {"panels": [tile(spec={"metrics": ["rows", "devices"]}, stat={"column": "Devices"})]}
        self.assertEqual(self.run_(spec, range="all")["panels"]["t"]["stat"]["value"], 3)


class FakeSource:
    """A second source over the same facts, answering from memory: the dashboard cannot tell it from the local one."""

    def __init__(self, local):
        self.local = local

    def get_stream(self, key):
        return self.local.get_stream(key)

    def run(self, stream, spec):
        return self.local.run(stream, copy.deepcopy(spec))


class Parity(Base):
    def test_two_sources_give_the_same_dashboard(self):
        a = d.run_dashboard(DASH, {"range": "30"}, self.src)
        b = d.run_dashboard(DASH, {"range": "30"}, FakeSource(self.src))
        for r in (a, b):
            r.pop("generatedAt")
        self.assertEqual(a, b)

    def test_a_source_with_its_own_options_is_used(self):
        class Own(FakeSource):
            def options(self, stream, field, limit):
                return ["only"]

        self.assertEqual(d.run_dashboard(DASH, {}, Own(self.src))["options"], {"ext": ["only"]})

    def test_a_failing_source_is_a_panel_error_not_a_crash(self):
        class Down(FakeSource):
            def run(self, stream, spec):
                raise OSError("source is down")

        r = d.run_dashboard(DASH, {}, Down(self.src))
        self.assertEqual(r["panels"]["t"]["error"], "source is down")
        self.assertEqual(r["futureDated"], [])


if __name__ == "__main__":
    unittest.main()
