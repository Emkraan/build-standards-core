"""
docs_drift_test.py
Purpose: The documentation drift feed. The summary counts statuses and bases, lists the pages most behind first (at most 40) and the pages with no
         verdict, keeps the preview filtered and trimmed, and never raises on empty input. A refresh keeps the last good data and names the error
         when the source fails or has no run, skips the source when the run id is unchanged, and a GET returns the cache at once and starts one
         refresh. Run now is the consumer's dispatch (refused when none, reasons passed through) and marks the run pending for ten minutes. The
         routes exist only with a provider and are closed until it authorises.
Run:     python3 docs_drift_test.py
"""

import datetime as dt
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import docs_drift as dd  # noqa: E402
import registry as reg  # noqa: E402


def row(page, status, commits=0, basis="footer-commit", **kw):
    return {
        "thing": "t",
        "page": page,
        "title": f"P{page}",
        "link": f"L{page}",
        "status": status,
        "basis": basis,
        "since": "x",
        "commits": commits,
        "files": [],
        "files_total": 0,
        "edited": "2026-01-01",
        **kw,
    }


DRIFT = {
    "head": "abc",
    "errors": [{"thing": "t", "page": "9", "error": "x"}],
    "things": [
        {
            "thing": "t",
            "pages": [
                row("1", "behind", 68),
                row("2", "behind", 21, basis="edit-date"),
                row("3", "current", basis="edit-date"),
                row("4", "no-footer", basis="none", detail="no footer"),
                row("5", "sha-missing", detail="gone"),
                row("6", "current-unverified", basis="edit-date"),
            ],
        }
    ],
}
FACTS = [
    {
        "facts": {
            "thing": "t",
            "name": "App",
            "version": "1.2.3",
            "latest_release": "1.2.3",
            "home": "H",
            "extra": "dropped",
        },
        "readme": {"status": "current"},
        "changelog": {"status": "gaps", "missing": ["1.2.2"]},
    }
]
RUN = {
    "id": 7,
    "created": "2026-01-01T00:00:00Z",
    "head": "abcd1234",
    "url": "https://host.example.com/run/7",
}
NOW = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)


class Provider:
    def __init__(self, run=RUN, error=None, dispatch=None, latest=True):
        self.calls = 0
        self.run, self.error, self._dispatch = run, error, dispatch
        if dispatch is not None:
            self.docs_drift_dispatch = lambda: self._dispatch
        if latest:
            self.docs_drift_latest_run = lambda: self.run

    def docs_drift_source(self, now):
        self.calls += 1
        if self.error:
            return {"error": self.error}
        if self.run is None:
            return None
        return {"run": self.run, "drift": DRIFT, "facts": FACTS, "preview": None}

    def authorize(self, headers, action, key=None):
        return "ok" if headers.get("X-User") == "me" else None


class Summary(unittest.TestCase):
    def test_counts_bases_sort_and_lists(self):
        s = dd.summarize(DRIFT, FACTS, RUN, now=NOW)
        self.assertEqual(
            s["counts"],
            {"behind": 2, "current": 1, "no-footer": 1, "sha-missing": 1, "current-unverified": 1},
        )
        self.assertEqual(s["bases"], {"footer-commit": 2, "edit-date": 3, "none": 1})
        self.assertEqual((s["total"], s["errors"], s["behind_total"]), (6, 1, 2))
        self.assertEqual([r["page"] for r in s["behind"]], ["1", "2"])
        self.assertEqual([r["page"] for r in s["no_verdict"]], ["4", "5"])
        self.assertEqual(s["facts"][0]["version"], "1.2.3")
        self.assertNotIn("extra", s["facts"][0])
        self.assertEqual((s["run"]["id"], s["fetched_utc"]), (7, "2026-01-01T00:00:00+00:00"))

    def test_empty_and_odd_inputs_do_not_raise(self):
        for drift, facts in (
            ({}, []),
            (None, None),
            ({"things": [None, {"pages": [None, 3]}]}, [None, 1]),
        ):
            s = dd.summarize(drift, facts, None)
            self.assertEqual((s["total"], s["behind"], s["facts"]), (0, [], []))

    def test_the_behind_list_is_capped_but_the_total_is_not(self):
        many = {"things": [{"pages": [row(str(i), "behind", i) for i in range(55)]}]}
        s = dd.summarize(many, [], RUN)
        self.assertEqual((len(s["behind"]), s["behind_total"]), (40, 55))
        self.assertEqual(s["behind"][0]["commits"], 54)

    def test_an_unknown_status_is_kept_and_counted(self):
        s = dd.summarize({"things": [{"pages": [row("1", "brand-new-status")]}]}, [], RUN)
        self.assertEqual(s["counts"], {"brand-new-status": 1})

    def test_the_preview_is_filtered_and_trimmed_and_an_older_run_reads_none(self):
        prev = {
            "model": "m",
            "head": "h",
            "pages": [
                {"page": "1", "title": "t", "secret": "x", "diff": ["a" * 900] * 200},
                "junk",
            ],
        }
        p = dd.summarize(DRIFT, [], RUN, prev)["preview"]
        self.assertEqual(len(p["pages"]), 1)
        self.assertNotIn("secret", p["pages"][0])
        self.assertEqual((len(p["pages"][0]["diff"]), len(p["pages"][0]["diff"][0])), (80, 400))
        self.assertIsNone(dd.summarize(DRIFT, [], RUN, None)["preview"])
        self.assertIsNone(dd.summarize(DRIFT, [], RUN, {"pages": "x"})["preview"])


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "cache.json"
        dd._running = False


class Refresh(Base):
    def test_fetches_and_caches(self):
        p = Provider()
        s = dd.refresh(p, self.path, now=NOW)
        self.assertEqual((s["run"]["id"], s["behind_total"], s["error"]), (7, 2, None))
        self.assertEqual(json.loads(self.path.read_text())["total"], 6)

    def test_the_same_run_is_not_fetched_again_but_a_forced_refresh_is(self):
        p = Provider()
        dd.refresh(p, self.path, now=NOW)
        dd.refresh(p, self.path, now=NOW + dt.timedelta(hours=1))
        self.assertEqual(p.calls, 1)
        s = json.loads(self.path.read_text())
        self.assertEqual(s["fetched_utc"], "2026-01-01T01:00:00+00:00")
        dd.refresh(p, self.path, force=True, now=NOW)
        self.assertEqual(p.calls, 2)

    def test_a_source_without_a_cheap_run_check_is_called_every_time(self):
        p = Provider(latest=False)
        dd.refresh(p, self.path, now=NOW)
        dd.refresh(p, self.path, now=NOW)
        self.assertEqual(p.calls, 2)

    def test_a_failure_keeps_the_last_good_data_and_names_the_error(self):
        dd.refresh(Provider(), self.path, now=NOW)
        s = dd.refresh(Provider(error="x" * 500, run={"id": 8}), self.path, now=NOW)
        self.assertEqual((s["total"], s["run"]["id"]), (6, 7))
        self.assertEqual(len(s["error"]), 300)

    def test_no_run_yet_and_no_source_are_errors_not_crashes(self):
        s = dd.refresh(Provider(run=None, latest=False), self.path, now=NOW)
        self.assertIn("no successful", s["error"])
        self.assertEqual(s["behind"], [])
        self.assertIn("no docs drift source", dd.refresh(object(), self.path)["error"])

    def test_a_source_that_raises_or_answers_wrongly_is_an_error(self):
        class Boom:
            def docs_drift_source(self, now):
                raise OSError("down")

        class Odd:
            def docs_drift_source(self, now):
                return [1]

        self.assertEqual(dd.refresh(Boom(), self.path)["error"], "down")
        self.assertIn("not an object", dd.refresh(Odd(), self.path)["error"])


class RunNow(Base):
    def test_a_started_run_is_pending_and_polled_for_ten_minutes(self):
        p = Provider(dispatch={"started": True})
        dd.refresh(p, self.path, now=NOW)
        self.assertEqual(dd.run_now(p, self.path, now=NOW), {"started": True})
        cache = json.loads(self.path.read_text())
        self.assertEqual(cache["pending_run"]["after_run"], 7)
        self.assertTrue(dd._stale(cache, NOW + dt.timedelta(minutes=9)))
        cache["fetched_utc"] = (NOW + dt.timedelta(minutes=10)).isoformat()
        self.assertFalse(dd._stale(cache, NOW + dt.timedelta(minutes=11)))
        self.assertIsNone(dd._pending(cache, NOW + dt.timedelta(minutes=11)))

    def test_a_refusal_passes_its_reason_and_link_through(self):
        p = Provider(
            dispatch={
                "started": False,
                "reason": "A run is already queued",
                "url": "https://host.example.com/r",
            }
        )
        self.assertEqual(
            dd.run_now(p, self.path),
            {
                "started": False,
                "reason": "A run is already queued",
                "url": "https://host.example.com/r",
            },
        )
        self.assertFalse(self.path.exists())

    def test_no_dispatch_and_a_failing_dispatch_are_reported_not_raised(self):
        self.assertFalse(dd.run_now(Provider(), self.path)["started"])

        class Bad(Provider):
            def docs_drift_dispatch(self):
                raise OSError("gh failed")

        self.assertEqual(dd.run_now(Bad(), self.path), {"started": False, "reason": "gh failed"})


class ReadState(Base):
    def test_a_missing_cache_reads_empty_and_starts_one_refresh(self):
        done = threading.Event()

        class Slow(Provider):
            def docs_drift_source(inner, now):
                done.wait(5)
                return Provider.docs_drift_source(inner, now)

        p = Slow()
        a = dd.read_state(p, self.path)
        b = dd.read_state(p, self.path)
        self.assertEqual((a["total"], a["refreshing"], b["refreshing"]), (0, True, True))
        self.assertTrue(dd._running)
        done.set()
        for _ in range(100):
            if not dd._running:
                break
            threading.Event().wait(0.05)
        self.assertEqual(p.calls, 1, "one refresh, not two")
        self.assertEqual(dd.read_state(p, self.path)["run"]["id"], 7)

    def test_a_fresh_cache_does_not_refresh(self):
        p = Provider()
        dd.refresh(p, self.path)
        before = p.calls
        s = dd.read_state(p, self.path)
        self.assertFalse(s["refreshing"])
        self.assertEqual(p.calls, before)


class Routes(Base):
    def call(self, r, method, path, user=None):
        route, groups = r.match(method, path)
        self.assertIsNotNone(route, path)
        return route.handler(
            reg.Request(method, path, {}, {}, {"X-User": user} if user else {}, groups)
        )

    def test_no_provider_no_route(self):
        import os

        import optional

        os.environ.pop("OPSCENTER_DOCS_DRIFT_PROVIDER", None)
        r = reg.Registry()
        self.assertEqual(optional.register(r), [])
        self.assertEqual(r.paths(), [])

    def test_registered_with_a_provider_and_closed_until_it_authorises(self):
        r = reg.Registry()
        dd.register(r, Provider(dispatch={"started": True}))
        self.assertEqual(
            sorted(p for _, p in r.paths()),
            ["/api/docs-drift", "/api/docs-drift/refresh", "/api/docs-drift/run"],
        )
        with self.assertRaises(PermissionError):
            self.call(r, "GET", "/api/docs-drift")
        with self.assertRaises(PermissionError):
            self.call(r, "POST", "/api/docs-drift/run", "stranger")
        import os

        os.environ["OPSCENTER_DOCS_DRIFT_CACHE"] = str(self.path)
        self.addCleanup(os.environ.pop, "OPSCENTER_DOCS_DRIFT_CACHE", None)
        self.assertEqual(self.call(r, "POST", "/api/docs-drift/refresh", "me")["run"]["id"], 7)
        self.assertEqual(self.call(r, "POST", "/api/docs-drift/run", "me"), {"started": True})

    def test_run_without_a_dispatch_is_501_and_a_refusal_is_409(self):
        import os

        os.environ["OPSCENTER_DOCS_DRIFT_CACHE"] = str(self.path)
        self.addCleanup(os.environ.pop, "OPSCENTER_DOCS_DRIFT_CACHE", None)
        r = reg.Registry()
        dd.register(r, Provider())
        self.assertEqual(self.call(r, "POST", "/api/docs-drift/run", "me")[0], 501)
        r = reg.Registry()
        dd.register(r, Provider(dispatch={"started": False, "reason": "busy"}))
        self.assertEqual(self.call(r, "POST", "/api/docs-drift/run", "me")[0], 409)


if __name__ == "__main__":
    unittest.main()
