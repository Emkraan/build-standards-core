"""Tests for the push channel bus (live_bus.py): version dedupe, the quiet first sight, the hello catch-up, the client cap, a full
queue closing a client, presence validation, the heartbeat, and the response hook that only watches declared paths. Hermetic: no
sockets, no threads, an injected clock."""

from __future__ import annotations

import json
import queue
import unittest

import live_bus


class FakeClock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def frames(client: live_bus.Client) -> list:
    out = []
    while True:
        try:
            raw = client.q.get_nowait().decode()
        except queue.Empty:
            return out
        event, _, rest = raw.partition("\n")
        out.append((event.removeprefix("event: "), json.loads(rest.removeprefix("data: ").strip())))


class BusTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.bus = live_bus.Bus(clock=self.clock, max_clients=2)
        live_bus.ALIASES["/api/badges"] = "badges"
        self.addCleanup(live_bus.ALIASES.clear)

    def test_first_sight_is_quiet_and_a_change_publishes_once(self):
        c = self.bus.connect()
        frames(c)  # hello
        self.assertEqual(self.bus.observe("data:a.json", "v1"), "new")
        self.assertEqual(frames(c), [])
        self.assertEqual(self.bus.observe("data:a.json", "v1"), "same")
        self.assertEqual(frames(c), [])
        self.clock.t += 1
        self.assertEqual(self.bus.observe("data:a.json", "v2"), "changed")
        self.assertEqual(frames(c), [("topic", {"t": "data:a.json", "v": "v2", "at": 1001000})])
        self.assertEqual(self.bus.observe("data:a.json", "v2"), "same")
        self.assertEqual(frames(c), [])

    def test_hello_carries_every_topic_so_a_reconnect_catches_up(self):
        self.bus.observe("badges", "b1")
        self.bus.observe("data:a.json", "a1")
        c = self.bus.connect()
        ((event, body),) = frames(c)
        self.assertEqual(event, "hello")
        self.assertEqual(body["id"], c.id)
        self.assertEqual(set(body["topics"]), {"badges", "data:a.json"})
        self.assertEqual(body["topics"]["badges"]["v"], "b1")

    def test_client_cap_and_disconnect_frees_a_slot(self):
        a, b = self.bus.connect(), self.bus.connect()
        self.assertIsNone(self.bus.connect())
        self.bus.disconnect(a)
        self.assertIsNotNone(self.bus.connect())
        self.assertTrue(a.closed)
        self.assertFalse(b.closed)

    def test_full_queue_closes_the_client_so_it_reconnects(self):
        c = self.bus.connect()
        for i in range(live_bus.QUEUE_MAX + 5):
            self.clock.t += (
                live_bus.FLAP_WINDOW_S + 1
            )  # spaced out so the flap guard does not hold them
            self.bus.observe("t", f"v{i}")
        self.assertTrue(c.closed)

    def test_presence_validation(self):
        c = self.bus.connect()
        self.assertFalse(self.bus.presence("nope", True, []))
        self.assertFalse(self.bus.presence(c.id, "yes", []))
        self.assertFalse(self.bus.presence(c.id, True, "x"))
        wants = [
            {"topic": "badges", "path": "/api/badges", "ms": 30000},
            {"topic": "bad", "path": "/etc/passwd", "ms": 30000},
            {"topic": "bad2", "path": "/api/../x", "ms": 30000},
            {"topic": "bad3", "path": "/api/x?y=1", "ms": 30000},
            {"topic": "bad4", "path": "/api/live", "ms": 30000},
            {"topic": "data:a.json", "ms": 5000},
            {"topic": "fast", "path": "/api/fast", "ms": 1},
            "junk",
        ]
        self.assertTrue(self.bus.presence(c.id, True, wants))
        got = self.bus.visible_wants()
        self.assertEqual(got["badges"], ("/api/badges", 30000))
        self.assertEqual(got["data:a.json"], (None, 5000))
        self.assertEqual(got["fast"], ("/api/fast", live_bus.MIN_WARM_MS))
        for bad in ("bad", "bad2", "bad3", "bad4"):
            self.assertNotIn(bad, got)

    def test_hidden_clients_want_nothing_and_the_smallest_interval_wins(self):
        a, b = self.bus.connect(), self.bus.connect()
        self.bus.presence(a.id, True, [{"topic": "x", "path": "/api/x", "ms": 60000}])
        self.bus.presence(b.id, True, [{"topic": "x", "path": "/api/x", "ms": 20000}])
        self.assertEqual(self.bus.visible_wants()["x"][1], 20000)
        self.bus.presence(b.id, False, [{"topic": "x", "path": "/api/x", "ms": 20000}])
        self.assertEqual(self.bus.visible_wants()["x"][1], 60000)
        self.bus.presence(a.id, False, [])
        self.assertEqual(self.bus.visible_wants(), {})
        self.assertEqual(self.bus.counts(), {"clients": 2, "visible": 0})

    def test_note_response_watches_only_declared_paths_without_params(self):
        c = self.bus.connect()
        self.bus.presence(c.id, True, [{"topic": "badges", "path": "/api/badges", "ms": 30000}])
        self.assertIsNone(self.bus.note_response("/api/other", "", b"{}"))
        self.assertEqual(self.bus.note_response("/api/badges", "", b'{"n":1}'), "new")
        self.assertEqual(self.bus.note_response("/api/badges", "", b'{"n":1}'), "same")
        self.assertIsNone(self.bus.note_response("/api/badges", "id=3", b'{"n":9}'))
        self.assertEqual(self.bus.note_response("/api/badges", "fresh=1", b'{"n":1}'), "same")
        frames(c)
        self.assertEqual(self.bus.note_response("/api/badges", "", b'{"n":2}'), "changed")
        self.assertEqual([f[1]["t"] for f in frames(c)], ["badges"])

    def test_a_stamped_answer_is_the_same_content(self):
        # Regression: an endpoint that stamps generated_utc on every read. Hashing the stamp made every warm read a
        # change, every change a reload and every reload a read (130 requests in 90 seconds).
        a = b'{"generated_utc":"2026-11-16T03:19:41Z","people":[{"n":1,"now":5}]}'
        b = b'{"generated_utc":"2026-11-16T03:19:48Z","people":[{"n":1,"now":9}]}'
        c = b'{"generated_utc":"2026-11-16T03:19:48Z","people":[{"n":2,"now":9}]}'
        self.assertEqual(live_bus.body_version(a), live_bus.body_version(b))
        self.assertNotEqual(live_bus.body_version(a), live_bus.body_version(c))
        self.assertEqual(live_bus.body_version(b"not json"), live_bus.body_version(b"not json"))
        self.assertNotEqual(live_bus.body_version(b"not json"), live_bus.body_version(b"not jsoN"))

    def test_flap_guard_holds_a_topic_that_keeps_changing(self):
        c = self.bus.connect()
        frames(c)
        for i in range(live_bus.FLAP_MAX + 4):
            self.clock.t += 1
            self.bus.observe("loop", f"v{i}")
        sent = [f for f in frames(c) if f[0] == "topic"]
        # the first sight is quiet, then FLAP_MAX events, the rest are held
        self.assertEqual(len(sent), live_bus.FLAP_MAX)
        self.assertGreater(self.bus.suppressed, 0)
        self.clock.t += live_bus.FLAP_WINDOW_S + 1
        self.assertEqual(self.bus.observe("loop", "later"), "changed")
        self.assertEqual(len([f for f in frames(c) if f[0] == "topic"]), 1)

    def test_aliases(self):
        self.assertEqual(live_bus.api_topic("/api/badges"), "badges")
        live_bus.ALIASES.clear()
        self.assertEqual(live_bus.api_topic("/api/badges"), "api:/api/badges")
        self.assertEqual(live_bus.api_topic("/api/infra/spend"), "api:/api/infra/spend")
        self.assertEqual(live_bus.data_topic("freeze.json"), "data:freeze.json")


class ServeTest(unittest.TestCase):
    def test_retry_then_frames_then_heartbeat_then_end(self):
        bus = live_bus.Bus()
        c = bus.connect()
        out = []

        def write(chunk):
            out.append(chunk)
            if chunk == b": hb\n\n":
                c.closed = True

        live_bus.serve(bus, c, write, heartbeat_s=0.01)
        self.assertEqual(out[0], b"retry: 3000\n\n")
        self.assertTrue(out[1].startswith(b"event: hello\n"))
        self.assertEqual(out[2], b": hb\n\n")

    def test_a_dead_peer_ends_the_loop(self):
        bus = live_bus.Bus()
        c = bus.connect()

        def write(_chunk):
            raise BrokenPipeError

        with self.assertRaises(OSError):
            live_bus.serve(bus, c, write, heartbeat_s=0.01)


if __name__ == "__main__":
    unittest.main()
