import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import active_builds as ab  # noqa: E402
import registry as reg  # noqa: E402

NOW = 1_800_000_000.0


class Source:
    def __init__(self, rows=None, boom=None, slow=0):
        self.rows, self.boom, self.slow = rows, boom, slow

    def active_builds(self, now):
        if self.slow:
            time.sleep(self.slow)
        if self.boom:
            raise self.boom
        return self.rows


class Headers(dict):
    pass


def call(r, headers=None):
    route = r.match("GET", "/api/active-builds")[0] if hasattr(r, "match") else None
    return route


def build(i, **over):
    return {"id": f"b{i}", "title": f"Build {i}", "state": "running", "started": NOW - i, **over}


class Summarize(unittest.TestCase):
    def test_counts_every_known_state_and_total(self):
        rows = [
            build(1),
            build(2, state="stuck"),
            build(3, state="failed"),
            build(4, state="finished"),
            build(5),
        ]
        out = ab.summarize(rows, NOW)
        self.assertEqual(
            out["counts"], {"running": 2, "stuck": 1, "failed": 1, "finished": 1, "total": 5}
        )
        self.assertIsNone(out["error"])

    def test_an_unknown_state_is_kept_and_not_counted_as_a_known_one(self):
        out = ab.summarize([build(1, state="Paused")], NOW)
        self.assertEqual(out["builds"][0]["state"], "paused")
        self.assertEqual(out["counts"]["running"], 0)
        self.assertEqual(out["counts"]["total"], 1)

    def test_rows_with_no_id_or_that_are_not_objects_are_dropped(self):
        out = ab.summarize([build(1), {"title": "no id"}, "text", None, {"id": ""}], NOW)
        self.assertEqual([b["id"] for b in out["builds"]], ["b1"])

    def test_newest_activity_first_falling_back_to_start(self):
        rows = [
            build(1, started=NOW - 500),
            build(2, started=NOW - 900, activity_at=NOW - 10),
            build(3, started=NOW - 100),
        ]
        self.assertEqual([b["id"] for b in ab.summarize(rows, NOW)["builds"]], ["b2", "b3", "b1"])

    def test_capped_with_the_count_before_the_cap_and_the_remainder_reported(self):
        out = ab.summarize([build(i) for i in range(ab.MAX_BUILDS + 7)], NOW)
        self.assertEqual(len(out["builds"]), ab.MAX_BUILDS)
        self.assertEqual(out["counts"]["total"], ab.MAX_BUILDS + 7)
        self.assertEqual(out["truncated"], 7)

    def test_times_accept_epoch_and_iso_with_an_offset_and_refuse_anything_else(self):
        out = ab.summarize(
            [
                build(
                    1,
                    started="2026-11-19T14:00:00Z",
                    finished="not a date",
                    activity_at="2026-11-19T14:00:00",
                    outcome=True,
                )
            ],
            NOW,
        )
        b = out["builds"][0]
        self.assertEqual(b["started"], 1_795_096_800.0)
        self.assertIsNone(b["finished"])
        self.assertIsNone(b["activity_at"], "an ISO time with no offset is not guessed at")

    def test_a_boolean_or_non_positive_time_is_not_a_time(self):
        b = ab.summarize([build(1, started=True, finished=0, activity_at=-5)], NOW)["builds"][0]
        self.assertEqual((b["started"], b["finished"], b["activity_at"]), (None, None, None))

    def test_only_http_and_https_links_survive(self):
        urls = {
            "https://x.test/a": "https://x.test/a",
            "http://x.test/a": "http://x.test/a",
            "javascript:alert(1)": None,
            "file:///etc/passwd": None,
            "//x.test": None,
        }
        for given, want in urls.items():
            self.assertEqual(
                ab.summarize([build(1, url=given)], NOW)["builds"][0]["url"], want, given
            )

    def test_text_is_clipped_and_whitespace_collapsed(self):
        b = ab.summarize([build(1, title="  one\n\ttwo  " + "x" * 500)], NOW)["builds"][0]
        self.assertTrue(b["title"].startswith("one two xxx"))
        self.assertEqual(len(b["title"]), ab.MAX_TEXT)

    def test_a_list_that_is_not_a_list_is_nothing_seen_not_a_crash(self):
        self.assertEqual(ab.summarize("oops", NOW)["counts"]["total"], 0)
        self.assertEqual(ab.summarize({"id": "x"}, NOW)["counts"]["total"], 0)


class Read(unittest.TestCase):
    def test_a_good_source_gives_rows_and_no_error(self):
        out = ab.read(Source([build(1)]), NOW)
        self.assertIsNone(out["error"])
        self.assertEqual(out["counts"]["total"], 1)

    def test_a_source_that_raises_is_an_error_with_no_rows_and_does_not_name_the_message(self):
        out = ab.read(Source(boom=RuntimeError("secret token abc123")), NOW)
        self.assertEqual(out["builds"], [])
        self.assertIn("RuntimeError", out["error"])
        self.assertNotIn("abc123", out["error"])

    def test_an_empty_list_is_a_real_answer_and_is_not_an_error(self):
        out = ab.read(Source([]), NOW)
        self.assertIsNone(
            out["error"], "nothing running is an answer, an unreachable source is not"
        )
        self.assertEqual(out["counts"]["total"], 0)

    def test_a_source_that_does_not_return_a_list_is_an_error(self):
        self.assertIn("list", ab.read(Source({"not": "a list"}), NOW)["error"])
        self.assertIn("list", ab.read(Source(None), NOW)["error"])

    def test_a_slow_source_is_cut_off_and_reported(self):
        old = ab.TIMEOUT_SECONDS
        ab.TIMEOUT_SECONDS = 0.2
        try:
            started = time.monotonic()
            out = ab.read(Source([build(1)], slow=2), NOW)
            took = time.monotonic() - started
        finally:
            ab.TIMEOUT_SECONDS = old
        self.assertLess(took, 1.5)
        self.assertEqual(out["builds"], [])
        self.assertIn("did not answer", out["error"])

    def test_a_provider_without_the_method_is_an_error_and_not_an_empty_board(self):
        self.assertIn("no active_builds", ab.read(object(), NOW)["error"])
        self.assertIn("no active_builds", ab.read(None, NOW)["error"])


class Route(unittest.TestCase):
    def registry(self, provider):
        r = reg.Registry()
        ab.register(r, provider)
        return r

    def call(self, r, headers=None):
        route, groups = r.match("GET", "/api/active-builds")
        self.assertIsNotNone(route, "the route is registered")
        return route.handler(
            reg.Request("GET", "/api/active-builds", {}, None, headers or {}, groups)
        )

    def test_the_only_route_is_one_read(self):
        self.assertEqual(self.registry(Source([])).paths(), [("GET", "/api/active-builds")])

    def test_it_cannot_be_written_to(self):
        r = self.registry(Source([]))
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            route, known = r.match(method, "/api/active-builds")
            self.assertIsNone(route, method)
            self.assertTrue(known, "the path exists, so a write is a 405 and not a 404")

    def test_it_refuses_when_the_provider_has_no_authorizer(self):
        with self.assertRaises(PermissionError):
            self.call(self.registry(Source([build(1)])))

    def test_it_refuses_when_the_authorizer_says_no_and_allows_when_it_says_who(self):
        seen = []

        class Gate(Source):
            def authorize(self, headers, action, key=None):
                seen.append(action)
                return {"name": "operator"} if headers.get("X-Who") == "ok" else None

        r = self.registry(Gate([build(1)]))
        with self.assertRaises(PermissionError):
            self.call(r, {"X-Who": "no"})
        self.assertEqual(self.call(r, {"X-Who": "ok"})["counts"]["total"], 1)
        self.assertEqual(set(seen), {"active-builds.read"})

    def test_the_module_has_no_way_to_start_or_stop_anything(self):
        src = Path(ab.__file__).read_text()
        body = "\n".join(line.split("#")[0] for line in src.splitlines())
        for word in ("subprocess", "os.kill", "signal", "Popen", "os.system"):
            self.assertNotIn(word, body, word)


if __name__ == "__main__":
    unittest.main()
