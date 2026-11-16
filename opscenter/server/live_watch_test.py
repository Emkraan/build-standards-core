"""Tests for the push channel loops (live_watch.py): data scan (change, same, unchanged stat), state watch (debounce, rate gap, run
window cap, catch-up when a source is newer than the served bundle, never overlaps), warm loop gating (nothing without a visible tab,
interval, nudge after a write, single flight, no call when hidden), the bundler lock and the loop's idle behaviour. Hermetic: scratch
folders, an injected clock and fetch, no threads."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import live_bus
import live_watch


class DataWatchTest(unittest.TestCase):
    def test_new_same_changed(self):
        with tempfile.TemporaryDirectory() as d:
            bus = live_bus.Bus()
            c = bus.connect()
            w = live_watch.DataWatch(bus, Path(d))
            f = Path(d) / "a.json"
            f.write_text('{"a":1}')
            self.assertEqual(w.scan(), 0)  # first sight is quiet
            self.assertEqual(w.scan(), 0)
            f.write_text('{"a":22}')
            self.assertEqual(w.scan(), 1)
            self.assertEqual(w.scan(), 0)
            self.assertTrue(c.q.qsize() >= 2)  # hello plus one topic frame
            (Path(d) / "skip.txt").write_text("x")
            self.assertEqual(w.scan(), 0)
            self.assertNotIn("data:skip.txt", bus.topics)

    def test_same_content_rewritten_does_not_publish(self):
        with tempfile.TemporaryDirectory() as d:
            bus = live_bus.Bus()
            w = live_watch.DataWatch(bus, Path(d))
            f = Path(d) / "a.json"
            f.write_text('{"a":1}')
            w.scan()
            f.write_text('{"a":1}')
            os.utime(f, ns=(1, 1))
            self.assertEqual(w.scan(), 0)

    def test_missing_folder_is_not_an_error(self):
        w = live_watch.DataWatch(live_bus.Bus(), Path("/nonexistent/dir/x"))
        self.assertEqual(w.scan(), 0)


class StateWatchTest(unittest.TestCase):
    def make(self, d, marker=None):
        self.src = Path(d) / "src.json"
        self.src.write_text("1")
        self.ran = 0

        def run():
            self.ran += 1

        return live_watch.StateWatch(lambda: [self.src], run, marker, threaded=False)

    def bump(self, n):
        self.src.write_text("x" * n)

    def test_debounce_then_run_once(self):
        with tempfile.TemporaryDirectory() as d:
            w = self.make(d)
            self.assertFalse(w.tick(100))  # first look, nothing to do
            self.bump(2)
            self.assertFalse(w.tick(101))  # change seen, quiet period starts
            self.bump(3)
            self.assertFalse(w.tick(102))  # still moving, restarts
            self.assertFalse(w.tick(103))  # 1 s of quiet is not enough
            self.assertTrue(w.tick(104))
            self.assertEqual(self.ran, 1)
            self.assertFalse(w.tick(105))
            self.assertEqual(self.ran, 1)

    def test_at_most_once_per_gap(self):
        with tempfile.TemporaryDirectory() as d:
            w = self.make(d)
            w.tick(100)
            self.bump(2)
            w.tick(101)
            self.assertTrue(w.tick(103))
            self.bump(3)
            w.tick(104)
            self.assertFalse(w.tick(106))  # quiet, but inside the 20 s gap
            self.assertFalse(w.tick(120))
            self.assertTrue(w.tick(124))  # the gap passed, the pending change runs
            self.assertEqual(self.ran, 2)

    def test_run_window_cap_stops_a_self_triggering_loop(self):
        with tempfile.TemporaryDirectory() as d:
            w = self.make(d)
            w.tick(0)
            t = 0
            for i in range(20):
                self.bump(i + 2)
                t += 25
                w.tick(t)
                w.tick(t + 2)
            self.assertEqual(self.ran, live_watch.STATE_MAX_RUNS)
            self.assertGreater(w.skipped, 0)

    def test_catch_up_when_a_source_is_newer_than_the_bundle(self):
        with tempfile.TemporaryDirectory() as d:
            marker = Path(d) / "manifest.json"
            marker.write_text("{}")
            w = self.make(d, marker)
            os.utime(marker, ns=(1_000_000_000_000, 1_000_000_000_000))  # the bundle is old
            self.assertTrue(w.tick(100))
            self.assertEqual(self.ran, 1)

    def test_no_catch_up_when_the_bundle_is_current(self):
        with tempfile.TemporaryDirectory() as d:
            marker = Path(d) / "manifest.json"
            self.src_ns = None
            w = self.make(d, marker)
            marker.write_text("{}")  # written after the source
            self.assertFalse(w.tick(100))
            self.assertEqual(self.ran, 0)

    def test_a_failing_run_is_contained_and_never_overlaps(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "s.json"
            src.write_text("1")

            def boom():
                raise RuntimeError("bundle failed")

            w = live_watch.StateWatch(lambda: [src], boom, None, threaded=False)
            w.tick(100)
            src.write_text("22")
            w.tick(101)
            self.assertTrue(w.tick(103))
            self.assertFalse(w.running)

    def test_a_missing_source_is_a_stable_signature(self):
        w = live_watch.StateWatch(
            lambda: [Path("/nonexistent/x.json")], lambda: None, None, threaded=False
        )
        self.assertEqual(w.signature(), w.signature())


class WarmerTest(unittest.TestCase):
    def setUp(self):
        self.bus = live_bus.Bus()
        live_bus.ALIASES["/api/badges"] = "badges"
        self.addCleanup(live_bus.ALIASES.clear)
        self.calls = []
        self.bodies = {"/api/badges": b'{"n":1}'}

        def fetch(path):
            self.calls.append(path)
            return self.bodies.get(path)

        self.warm = live_watch.Warmer(self.bus, fetch)
        self.c = self.bus.connect()

    def want(self, visible=True, ms=30000):
        self.bus.presence(
            self.c.id, visible, [{"topic": "badges", "path": "/api/badges", "ms": ms}]
        )

    def test_no_visible_tab_means_no_reads(self):
        self.assertEqual(self.warm.tick(100), 0)
        self.want(visible=False)
        self.assertEqual(self.warm.tick(200), 0)
        self.assertEqual(self.calls, [])

    def test_reads_on_the_interval_only(self):
        self.want(ms=30000)
        self.assertEqual(self.warm.tick(100), 0)  # first sight waits a full interval
        self.assertEqual(self.warm.tick(120), 0)
        self.assertEqual(self.warm.tick(131), 1)
        self.assertEqual(self.calls, ["/api/badges"])
        self.assertEqual(self.warm.tick(140), 0)

    def test_a_changed_body_publishes_through_note_response(self):
        self.want(ms=2000)
        self.warm.tick(0)
        self.warm.tick(3)
        self.assertEqual(self.bus.topics["badges"]["v"], live_bus.body_version(b'{"n":1}'))
        self.bodies["/api/badges"] = b'{"n":2}'
        self.warm.tick(6)
        self.assertEqual(self.bus.topics["badges"]["v"], live_bus.body_version(b'{"n":2}'))

    def test_a_failed_read_changes_nothing(self):
        self.want(ms=2000)
        self.bodies.clear()
        self.warm.tick(0)
        self.warm.tick(3)
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn("badges", self.bus.topics)

    def test_nudge_after_a_write_reads_again_within_a_second_gap(self):
        self.want(ms=60000)
        self.warm.tick(0)
        self.assertEqual(self.warm.tick(61), 1)  # the normal interval read
        self.warm.nudge(61.5)
        self.assertEqual(self.warm.tick(61.6), 0)  # under the one second gap since the last read
        self.assertEqual(self.warm.tick(62.6), 1)
        self.assertEqual(self.warm.tick(64), 0)  # one nudge, one read

    def test_single_flight(self):
        self.want(ms=2000)
        self.warm.tick(0)
        self.warm.inflight.add("badges")
        self.assertEqual(self.warm.tick(10), 0)
        self.warm.inflight.clear()
        self.assertEqual(self.warm.tick(10), 1)

    def test_hidden_tab_forgets_the_schedule(self):
        self.want(ms=2000)
        self.warm.tick(0)
        self.want(visible=False)
        self.warm.tick(5)
        self.assertEqual(self.warm.last, {})


class LoopTest(unittest.TestCase):
    def test_idle_with_no_client_and_state_reset(self):
        with tempfile.TemporaryDirectory() as d:
            bus = live_bus.Bus()
            hits = []
            data = live_watch.DataWatch(bus, Path(d))
            state = live_watch.StateWatch(
                lambda: [], lambda: hits.append("run"), None, threaded=False
            )
            warm = live_watch.Warmer(bus, lambda p: hits.append(p))
            loop = live_watch.Loop(bus, data, state, warm)
            state.seen = ("x",)
            (Path(d) / "a.json").write_text("{}")
            loop.tick(1.0)
            self.assertEqual(hits, [])
            self.assertIsNone(state.seen)
            self.assertEqual(bus.topics, {})  # not even the data scan runs

    def test_hidden_clients_scan_data_but_never_bundle_or_warm(self):
        with tempfile.TemporaryDirectory() as d:
            bus = live_bus.Bus()
            c = bus.connect()
            bus.presence(c.id, False, [{"topic": "x", "path": "/api/x", "ms": 2000}])
            hits = []
            data = live_watch.DataWatch(bus, Path(d))
            state = live_watch.StateWatch(
                lambda: [], lambda: hits.append("run"), None, threaded=False
            )
            warm = live_watch.Warmer(bus, lambda p: hits.append(p))
            loop = live_watch.Loop(bus, data, state, warm)
            (Path(d) / "a.json").write_text("{}")
            loop.tick(1.0)
            loop.tick(60.0)
            self.assertEqual(hits, [])
            self.assertIn("data:a.json", bus.topics)


class RunCmdTest(unittest.TestCase):
    def test_missing_binary_and_timeout_are_codes_not_exceptions(self):
        self.assertEqual(live_watch.run_cmd(["/nonexistent/bin"], ".", 2)[0], 127)
        self.assertEqual(live_watch.run_cmd(["sleep", "5"], ".", 0.2)[0], 124)
        rc, out = live_watch.run_cmd(["echo", "hi"], ".", 5)
        self.assertEqual((rc, out.strip()), (0, "hi"))


if __name__ == "__main__":
    unittest.main()
