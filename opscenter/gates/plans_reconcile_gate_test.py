import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gatehelp  # noqa: E402
import gatelib  # noqa: E402
import plans_reconcile_gate as g  # noqa: E402

NOW = 1_800_000_000.0


def project(
    slug,
    status="active",
    skeleton=False,
    behind=False,
    state="ok",
    events=(),
    tickets=("T-1",),
    **kw,
):
    summary = g.SKELETON_PREFIX + " strip" if skeleton else "A real summary"
    p = {
        "slug": slug,
        "title": slug.title(),
        "status": status,
        "tracker": {"summary": summary, "tickets": list(tickets)},
        "freshness": {"state": state, "behind": behind, "events": list(events)},
    }
    p.update(kw)
    return p


class Pure(unittest.TestCase):
    def test_candidates_are_skeletons_and_behind_trackers_only(self):
        data = {
            "projects": [
                project("skel", skeleton=True),
                project(
                    "late",
                    behind=True,
                    events=[{"ref": "#2", "day": "d", "url": "u", "title": "t"}],
                ),
                project("fine"),
                project("old", skeleton=True, archived=True),
                project("done", status="done", skeleton=True),
                {"slug": "bare", "status": "active"},
            ]
        }
        cands, loading, errors = g.candidates(data)
        self.assertEqual([c["slug"] for c in cands], ["skel", "late"])
        self.assertEqual((loading, errors), (False, []))
        self.assertTrue(cands[0]["skeleton"])
        self.assertTrue(cands[1]["path"].endswith(os.path.join("projects", "late", "tracker.md")))

    def test_loading_and_errors_are_reported(self):
        cands, loading, errors = g.candidates(
            {"projects": [project("a", state="loading"), project("b", state="error")]}
        )
        self.assertTrue(loading)
        self.assertEqual(errors, ["freshness check failed"])

    def test_the_fingerprint_follows_the_events(self):
        a = g.candidates({"projects": [project("x", behind=True, events=[{"ref": "#1"}])]})[0][0][
            "fp"
        ]
        b = g.candidates({"projects": [project("x", behind=True, events=[{"ref": "#1"}])]})[0][0][
            "fp"
        ]
        c = g.candidates(
            {"projects": [project("x", behind=True, events=[{"ref": "#1"}, {"ref": "#2"}])]}
        )[0][0]["fp"]
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_due_rules(self):
        cand = {"slug": "s", "fp": "f1"}
        self.assertEqual(g.due([cand], {}, NOW), [cand])
        handed = lambda **k: {"handed": {"s": dict({"fp": "f1", "at": NOW, "count": 1}, **k)}}  # noqa: E731
        self.assertEqual(g.due([cand], handed(), NOW + 60), [])  # handed over a minute ago
        self.assertEqual(g.due([cand], handed(), NOW + g.RETRY_AFTER_S + 1), [cand])  # one retry
        self.assertEqual(
            g.due([cand], handed(count=2), NOW + g.RETRY_AFTER_S + 1), []
        )  # then leave it
        self.assertEqual(
            g.due([dict(cand, fp="f2")], handed(count=2), NOW + 5), [dict(cand, fp="f2")]
        )  # new evidence

    def test_archivable_needs_every_step_ticked_and_every_work_ticket_closed(self):
        def done(slug, progress, ts):
            return project(
                slug,
                status="done",
                tracker={"progress": progress, "ticket_status": ts, "tickets": list(ts)},
            )

        types = {"W-1": "Task", "W-2": "Task", "D-1": g.INTAKE_TYPE}
        ok = done("ok", {"done": 3, "total": 3}, {"W-1": {"done": True}, "D-1": {"done": False}})
        steps = done("steps", {"done": 2, "total": 3}, {"W-1": {"done": True}})
        open_t = done(
            "open", {"done": 1, "total": 1}, {"W-1": {"done": True}, "W-2": {"done": False}}
        )
        intake_only = done("intake", {"done": 1, "total": 1}, {"D-1": {"done": True}})
        got = g.archivable({"projects": [ok, steps, open_t, intake_only]}, types)
        self.assertEqual([p["slug"] for p in got], ["ok"])
        self.assertEqual(
            g.archivable({"projects": [ok]}, {}), []
        )  # a failed type read does nothing


class Main(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        d = Path(self._d.name)
        self._old = (
            gatelib.STATE_DIR,
            g.STATE,
            os.environ.get("GATE_PLANS_JSON"),
            os.environ.get("GATE_NOW"),
        )
        gatelib.STATE_DIR = str(d / "gate")
        g.STATE = str(d / "gate" / "plans-state.json")
        self.plans = d / "plans.json"
        os.environ["GATE_PLANS_JSON"] = str(self.plans)
        os.environ["GATE_NOW"] = str(NOW)

    def tearDown(self):
        gatelib.STATE_DIR, g.STATE = self._old[:2]
        for k, v in zip(("GATE_PLANS_JSON", "GATE_NOW"), self._old[2:]):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._d.cleanup()

    def write(self, projects):
        self.plans.write_text(json.dumps({"projects": projects}))

    def test_nothing_to_reconcile_is_silent(self):
        self.write([project("fine")])
        self.assertTrue(gatehelp.is_silent(gatehelp.run_gate(g.main)[0]))

    def test_a_skeleton_wakes_once_then_waits_the_minimum_gap(self):
        self.write([project("skel", skeleton=True, tickets=("T-1", "T-2"))])
        out, code = gatehelp.run_gate(g.main)
        self.assertEqual(code, 0)
        self.assertIn("1 tracker(s) need a reconcile", out)
        self.assertIn("TRACKER skel (skeleton from the Untracked work strip)", out)
        self.assertIn("tickets: T-1, T-2", out)
        os.environ["GATE_NOW"] = str(NOW + 60)
        self.assertTrue(gatehelp.is_silent(gatehelp.run_gate(g.main)[0]))

    def test_behind_lists_the_events(self):
        self.write(
            [
                project(
                    "late",
                    behind=True,
                    events=[{"day": "10-27", "ref": "#2", "url": "u", "title": "merged"}],
                )
            ]
        )
        out, _ = gatehelp.run_gate(g.main)
        self.assertIn("(Behind)", out)
        self.assertIn("since: 10-27 #2 u | merged", out)

    def test_a_loading_check_is_silent_and_does_not_hand_anything_over(self):
        self.write([project("a", skeleton=True), project("b", state="loading")])
        self.assertTrue(gatehelp.is_silent(gatehelp.run_gate(g.main)[0]))
        self.assertFalse(Path(g.STATE).exists())

    def test_read_failures_back_off_and_the_third_wakes(self):
        outs = [gatehelp.run_gate(g.main)[0] for _ in range(3)]  # the plans file does not exist
        self.assertEqual([gatehelp.is_silent(o) for o in outs], [True, True, False])
        self.assertIn("plans API read failed", outs[2])

    def test_freshness_errors_with_no_candidate_back_off_the_same_way(self):
        self.write([project("a", state="error")])
        outs = [gatehelp.run_gate(g.main)[0] for _ in range(3)]
        self.assertEqual([gatehelp.is_silent(o) for o in outs], [True, True, False])
        self.assertIn("freshness check failed", outs[2])

    def test_a_tracker_that_stops_being_a_candidate_is_forgotten(self):
        self.write([project("skel", skeleton=True)])
        gatehelp.run_gate(g.main)
        self.write([project("skel")])
        os.environ["GATE_NOW"] = str(NOW + 7200)
        gatehelp.run_gate(g.main)
        self.assertEqual(json.loads(Path(g.STATE).read_text())["handed"], {})


class Adopt(unittest.TestCase):
    def test_a_linked_work_ticket_is_added_to_the_tracker_and_logged(self):
        with tempfile.TemporaryDirectory() as d:
            old = (g.PLANS_DIR, os.environ.pop("GATE_PLANS_JSON", None))
            g.PLANS_DIR = d
            tracker = Path(d) / "projects" / "p" / "tracker.md"
            tracker.parent.mkdir(parents=True)
            tracker.write_text("title: p\ntickets: D-1\n\n## Log\n- earlier\n")
            calls = []

            def fake_jql(q):
                calls.append(q)
                if q.startswith("key in"):
                    return [
                        {
                            "key": "D-1",
                            "fields": {
                                "issuetype": {"name": g.INTAKE_TYPE},
                                "created": "2026-10-01T09:00:00",
                            },
                        }
                    ]
                return [{"key": "W-7"}, {"key": "D-1"}]

            try:
                with mock.patch.object(g, "_jql", fake_jql):
                    added = g.adopt_work_tickets(
                        {"projects": [{"slug": "p", "tracker": {"tickets": ["D-1"]}}]}, NOW
                    )
            finally:
                g.PLANS_DIR = old[0]
            self.assertEqual(added, [("p", ["W-7"])])
            text = tracker.read_text()
            self.assertIn("tickets: D-1, W-7", text)
            self.assertIn("W-7 found linked to the intake", text)
            self.assertIn('created >= "2026-10-01"', calls[1])

    def test_a_fixture_run_never_writes(self):
        os.environ["GATE_PLANS_JSON"] = "x"
        try:
            self.assertEqual(
                g.adopt_work_tickets(
                    {"projects": [{"slug": "p", "tracker": {"tickets": ["D-1"]}}]}, NOW
                ),
                [],
            )
            self.assertEqual(g.auto_archive({"projects": []}, {}, NOW), [])
        finally:
            os.environ.pop("GATE_PLANS_JSON")

    def test_no_driver_means_no_tracker_calls(self):
        old = g.DRIVER
        g.DRIVER = ""
        try:
            self.assertIsNone(g._jql("key in (A-1)"))
        finally:
            g.DRIVER = old


if __name__ == "__main__":
    unittest.main()
