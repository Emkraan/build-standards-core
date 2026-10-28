import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import swr  # noqa: E402


class Swr(unittest.TestCase):
    def setUp(self):
        swr._mem.clear()
        swr._flight.clear()
        swr._kicks.clear()

    def test_a_cold_key_computes_inline_and_a_warm_one_is_served_as_is(self):
        calls = []
        fn = lambda: calls.append(1) or len(calls)  # noqa: E731
        self.assertEqual(swr.cached("k", 60, fn), 1)
        self.assertEqual(swr.cached("k", 60, fn), 1)
        self.assertEqual(len(calls), 1)

    def test_fresh_forces_a_computation(self):
        n = [0]

        def fn():
            n[0] += 1
            return n[0]

        swr.cached("k", 60, fn)
        self.assertEqual(swr.cached("k", 60, fn, fresh=True), 2)

    def test_an_expired_entry_is_served_at_once_and_refreshed_in_the_background(self):
        n = [0]
        done = threading.Event()

        def fn():
            n[0] += 1
            if n[0] > 1:
                done.set()
            return n[0]

        swr.cached("k", 0.01, fn)
        time.sleep(0.05)
        self.assertEqual(swr.cached("k", 0.01, fn), 1)  # the stale value, no wait
        self.assertTrue(done.wait(2))
        deadline = time.time() + 2
        while swr.peek("k") != 2 and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(swr.peek("k"), 2)

    def test_an_entry_older_than_max_stale_computes_inline(self):
        n = [0]

        def fn():
            n[0] += 1
            return n[0]

        swr.cached("k", 0.01, fn)
        time.sleep(0.05)
        self.assertEqual(swr.cached("k", 0.01, fn, max_stale=0.02), 2)

    def test_concurrent_cold_callers_share_one_computation(self):
        n = [0]
        gate = threading.Event()

        def slow():
            n[0] += 1
            gate.wait(2)
            return "v"

        out = []
        threads = [
            threading.Thread(target=lambda: out.append(swr.cached("k", 60, slow))) for _ in range(5)
        ]
        for t in threads:
            t.start()
        time.sleep(0.1)
        gate.set()
        for t in threads:
            t.join(3)
        self.assertEqual(out, ["v"] * 5)
        self.assertEqual(n[0], 1)

    def test_a_failing_background_refresh_keeps_the_last_good_value(self):
        swr.cached("k", 0.01, lambda: "good")
        time.sleep(0.05)

        def bad():
            raise RuntimeError("boom")

        self.assertEqual(swr.cached("k", 0.01, bad), "good")
        time.sleep(0.1)
        self.assertEqual(swr.peek("k"), "good")

    def test_a_failing_cold_compute_raises_and_leaves_nothing(self):
        def bad():
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            swr.cached("k", 60, bad)
        self.assertIsNone(swr.peek("k"))
        self.assertEqual(swr.cached("k", 60, lambda: 7), 7)  # the flight was released

    def test_invalidate_and_prefix(self):
        for k in ("a:1", "a:2", "b:1"):
            swr.cached(k, 60, lambda: 1)
        swr.invalidate("a:1")
        self.assertIsNone(swr.peek("a:1"))
        swr.invalidate_prefix("a:")
        self.assertIsNone(swr.peek("a:2"))
        self.assertEqual(swr.peek("b:1"), 1)

    def test_kick_runs_once_at_a_time(self):
        n = [0]
        gate = threading.Event()

        def slow():
            n[0] += 1
            gate.wait(2)

        swr.kick("x", slow)
        swr.kick("x", slow)
        time.sleep(0.1)
        gate.set()
        time.sleep(0.1)
        self.assertEqual(n[0], 1)
        swr.kick("x", lambda: n.append("again"))  # free again after the first finished
        time.sleep(0.1)
        self.assertIn("again", n)


if __name__ == "__main__":
    unittest.main()
