import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import extensions as ex  # noqa: E402
import registry as reg  # noqa: E402

NOW = 1_800_000_000.0


class Source:
    def __init__(self, pages=None, rows=None, boom=None, rows_boom=None, slow=0):
        self.pages, self.rows, self.boom, self.rows_boom, self.slow = (
            pages,
            rows,
            boom,
            rows_boom,
            slow,
        )
        self.asked = []

    def extensions(self, now):
        if self.slow:
            time.sleep(self.slow)
        if self.boom:
            raise self.boom
        return self.pages

    def extension_rows(self, page_id, now):
        self.asked.append(page_id)
        if self.rows_boom:
            raise self.rows_boom
        return self.rows


def page(i="reports", **over):
    return {"id": i, "title": str(i).title(), "group": "Operate", "kind": "list", **over}


def link(i="docs", **over):
    return {
        "id": i,
        "title": i.title(),
        "group": "Knowledge",
        "kind": "link",
        "url": "https://tool.test/x",
        **over,
    }


class Summarize(unittest.TestCase):
    def test_a_list_page_and_a_link_page_are_kept_in_the_shape_a_client_draws(self):
        out = ex.summarize([page(lede="Reports waiting for a look"), link()], NOW)
        self.assertIsNone(out["error"])
        self.assertEqual([p["id"] for p in out["pages"]], ["reports", "docs"])
        self.assertEqual(out["pages"][0]["lede"], "Reports waiting for a look")
        self.assertIsNone(out["pages"][0]["url"], "a list page carries no link")
        self.assertEqual(out["pages"][1]["url"], "https://tool.test/x")
        self.assertEqual(out["fetched_utc"], "2027-01-15T08:00:00Z")

    def test_an_id_that_is_not_a_safe_slug_drops_the_page(self):
        for bad in (
            "A",
            "a",
            "Has Space",
            "../etc",
            "x" * 41,
            "-lead",
            "trail-",
            "under_score",
            "dot.dot",
            "",
            None,
            7,
        ):
            self.assertEqual(ex.summarize([page(bad)], NOW)["pages"], [], repr(bad))

    def test_an_id_is_lower_cased_so_the_route_and_the_manifest_agree(self):
        self.assertEqual(ex.summarize([page("Reports")], NOW)["pages"][0]["id"], "reports")

    def test_a_page_cannot_take_a_name_the_core_already_serves(self):
        for name in (
            "action",
            "reviews",
            "debt",
            "operations",
            "api",
            "extensions",
            "platform",
            "jira",
        ):
            self.assertEqual(ex.summarize([page(name)], NOW)["pages"], [], name)

    def test_every_first_segment_the_core_app_serves_is_reserved(self):
        app = Path(__file__).resolve().parents[2] / "app" / "src" / "App.tsx"
        if not app.is_file():
            self.skipTest("the app source is not beside the server")
        import re

        served = {m.group(1) for m in re.finditer(r'<Route path="/([a-z0-9-]+)', app.read_text())}
        self.assertTrue(served, "the route table was read")
        self.assertEqual(
            sorted(served - ex.RESERVED_IDS), [], "a core route a consumer page could shadow"
        )

    def test_a_kind_the_core_cannot_draw_drops_the_page(self):
        for kind in ("iframe", "html", "script", "", None, 3):
            self.assertEqual(ex.summarize([page(kind=kind)], NOW)["pages"], [], repr(kind))

    def test_a_link_page_needs_an_http_or_https_address(self):
        good = ex.summarize([link("a1"), link("a2", url="http://t.test/x")], NOW)
        self.assertEqual(len(good["pages"]), 2)
        for url in (
            "javascript:alert(1)",
            "file:///etc/passwd",
            "data:text/html,x",
            "//t.test",
            "",
            None,
        ):
            self.assertEqual(ex.summarize([link("a1", url=url)], NOW)["pages"], [], repr(url))

    def test_a_list_page_never_carries_a_link_even_when_one_is_given(self):
        self.assertIsNone(ex.summarize([page(url="https://t.test/x")], NOW)["pages"][0]["url"])

    def test_an_unknown_group_becomes_platform_and_a_known_one_matches_any_case(self):
        out = ex.summarize(
            [
                page("a1", group="Invented"),
                page("a2", group="people"),
                page("a3", group=None),
                page("a4", group="KNOWLEDGE"),
            ],
            NOW,
        )
        self.assertEqual(
            [p["group"] for p in out["pages"]], ["Platform", "People", "Platform", "Knowledge"]
        )

    def test_text_is_plain_text_clipped_and_collapsed(self):
        out = ex.summarize([page(title="  a\n  b\t<b>c</b> " + "x" * 200, lede="y" * 500)], NOW)[
            "pages"
        ][0]
        self.assertTrue(
            out["title"].startswith("a b <b>c</b>"),
            "markup is kept as text for the client to draw as text",
        )
        self.assertLessEqual(len(out["title"]), 60)
        self.assertEqual(len(out["lede"]), ex.MAX_TEXT)

    def test_a_missing_title_falls_back_to_the_id(self):
        self.assertEqual(
            ex.summarize([{"id": "reports", "kind": "list"}], NOW)["pages"][0]["title"], "reports"
        )

    def test_a_repeated_id_is_kept_once_and_the_first_wins(self):
        out = ex.summarize([page("reports", title="First"), page("reports", title="Second")], NOW)
        self.assertEqual([p["title"] for p in out["pages"]], ["First"])

    def test_pages_are_capped_and_the_cut_is_counted(self):
        out = ex.summarize([page(f"page-{i:02d}") for i in range(ex.MAX_PAGES + 5)], NOW)
        self.assertEqual(len(out["pages"]), ex.MAX_PAGES)
        self.assertEqual(out["truncated"], 5)

    def test_junk_in_the_list_is_dropped_and_a_non_list_is_empty(self):
        self.assertEqual(len(ex.summarize([None, 4, "x", [], page()], NOW)["pages"]), 1)
        for junk in (None, "x", {}, 3):
            self.assertEqual(ex.summarize(junk, NOW)["pages"], [])


class Read(unittest.TestCase):
    def test_a_good_source_gives_its_pages(self):
        out = ex.read(Source([page()]), NOW)
        self.assertEqual([p["id"] for p in out["pages"]], ["reports"])
        self.assertIsNone(out["error"])

    def test_a_failing_source_is_an_error_and_never_an_empty_manifest(self):
        out = ex.read(Source(boom=OSError("secret path /x")), NOW)
        self.assertEqual(out["pages"], [])
        self.assertEqual(out["error"], "the source failed (OSError)")
        self.assertNotIn("secret", str(out), "the reason names the exception type only")

    def test_a_source_that_does_not_return_a_list_is_an_error(self):
        self.assertEqual(
            ex.read(Source({"a": 1}), NOW)["error"], "the source did not return a list"
        )

    def test_a_provider_with_no_extensions_method_is_an_error(self):
        self.assertEqual(ex.read(object(), NOW)["error"], "the provider has no extensions method")
        self.assertEqual(ex.read(None, NOW)["error"], "the provider has no extensions method")

    def test_a_slow_source_is_cut_off(self):
        old = ex.TIMEOUT_SECONDS
        ex.TIMEOUT_SECONDS = 0.2
        try:
            t = time.time()
            out = ex.read(Source([page()], slow=2), NOW)
            self.assertLess(time.time() - t, 1.5)
            self.assertIn("did not answer", out["error"])
            self.assertEqual(out["pages"], [])
        finally:
            ex.TIMEOUT_SECONDS = old


def row(i, **over):
    return {"id": f"r{i}", "title": f"Row {i}", **over}


class Rows(unittest.TestCase):
    def test_a_list_page_gives_its_rows(self):
        src = Source(
            [page()],
            rows=[row(1, detail="d", state="Open", url="https://t.test/1", at="2026-11-19")],
        )
        out, status = ex.read_rows(src, "reports", NOW)
        self.assertEqual(status, 200)
        self.assertEqual(out["page"]["id"], "reports")
        self.assertEqual(
            out["rows"][0],
            {
                "id": "r1",
                "title": "Row 1",
                "detail": "d",
                "state": "Open",
                "url": "https://t.test/1",
                "at": "2026-11-19",
            },
        )
        self.assertEqual(src.asked, ["reports"])

    def test_a_page_the_manifest_does_not_name_asks_the_provider_nothing(self):
        src = Source([page()], rows=[row(1)])
        out, status = ex.read_rows(src, "other", NOW)
        self.assertEqual((status, out["error"], out["rows"]), (404, "no such page", []))
        self.assertEqual(
            src.asked, [], "an id typed into the address bar never reaches the consumer"
        )

    def test_a_page_the_core_dropped_is_not_askable(self):
        src = Source([page("action")], rows=[row(1)])
        self.assertEqual(ex.read_rows(src, "action", NOW)[1], 404)
        self.assertEqual(src.asked, [])

    def test_a_link_page_has_no_rows_and_asks_the_provider_nothing(self):
        src = Source([link()], rows=[row(1)])
        out, status = ex.read_rows(src, "docs", NOW)
        self.assertEqual((status, out["rows"]), (200, []))
        self.assertEqual(src.asked, [])

    def test_a_failed_manifest_is_a_bad_gateway_never_a_missing_page(self):
        out, status = ex.read_rows(Source(boom=ValueError("x")), "reports", NOW)
        self.assertEqual(status, 502)
        self.assertIn("failed", out["error"])

    def test_a_failed_row_read_is_an_error_and_never_an_empty_list(self):
        out, status = ex.read_rows(Source([page()], rows_boom=KeyError("k")), "reports", NOW)
        self.assertEqual((status, out["rows"]), (502, []))
        self.assertEqual(out["error"], "the source failed (KeyError)")
        self.assertEqual(
            out["page"]["id"],
            "reports",
            "the page still names itself so the client can say which one failed",
        )

    def test_a_provider_with_no_rows_method_is_an_error(self):
        class Bare:
            def extensions(self, now):
                return [page()]

        out, status = ex.read_rows(Bare(), "reports", NOW)
        self.assertEqual((status, out["error"]), (502, "the provider has no extension_rows method"))

    def test_rows_that_are_not_a_list_are_an_error(self):
        out, status = ex.read_rows(Source([page()], rows={"a": 1}), "reports", NOW)
        self.assertEqual((status, out["error"]), (502, "the source did not return a list"))

    def test_junk_rows_are_dropped_unsafe_links_are_removed_and_text_is_clipped(self):
        src = Source(
            [page()],
            rows=[
                None,
                3,
                {"title": "no id"},
                row(1, url="javascript:x", detail="z" * 900, state="s" * 90),
                row(2),
            ],
        )
        out, _ = ex.read_rows(src, "reports", NOW)
        self.assertEqual([r["id"] for r in out["rows"]], ["r1", "r2"])
        self.assertIsNone(out["rows"][0]["url"])
        self.assertEqual(len(out["rows"][0]["detail"]), 400)
        self.assertEqual(len(out["rows"][0]["state"]), 30)

    def test_rows_are_capped_and_the_cut_is_counted(self):
        out, _ = ex.read_rows(
            Source([page()], rows=[row(i) for i in range(ex.MAX_ROWS + 7)]), "reports", NOW
        )
        self.assertEqual((len(out["rows"]), out["truncated"]), (ex.MAX_ROWS, 7))


class Route(unittest.TestCase):
    def registry(self, provider):
        r = reg.Registry()
        ex.register(r, provider)
        return r

    def call(self, r, path, headers=None):
        route, groups = r.match("GET", path)
        self.assertIsNotNone(route, f"{path} is registered")
        return route.handler(reg.Request("GET", path, {}, None, headers or {}, groups))

    def test_the_routes_are_two_reads(self):
        paths = [p for _, p in self.registry(Source([])).paths()]
        self.assertEqual(len(paths), 2)
        self.assertIn("/api/extensions", paths)

    def test_it_cannot_be_written_to(self):
        r = self.registry(Source([page()]))
        for path in ("/api/extensions", "/api/extensions/reports"):
            for method in ("POST", "PUT", "PATCH", "DELETE"):
                route, known = r.match(method, path)
                self.assertIsNone(route, f"{method} {path}")
                self.assertTrue(known, "the path exists, so a write is a 405 and not a 404")

    def test_an_address_that_is_not_a_safe_id_is_not_a_route(self):
        r = self.registry(Source([page()]))
        for path in (
            "/api/extensions/Reports",
            "/api/extensions/../x",
            "/api/extensions/a",
            "/api/extensions/a/b",
            "/api/extensions/" + "x" * 41,
        ):
            route, known = r.match("GET", path)
            self.assertIsNone(route, path)
            self.assertFalse(known, path)

    def test_it_refuses_when_the_provider_has_no_authorizer(self):
        r = self.registry(Source([page()], rows=[row(1)]))
        for path in ("/api/extensions", "/api/extensions/reports"):
            with self.assertRaises(PermissionError):
                self.call(r, path)

    def test_it_refuses_when_the_authorizer_says_no_and_allows_when_it_says_who(self):
        seen = []

        class Gate(Source):
            def authorize(self, headers, action, key=None):
                seen.append(action)
                return {"name": "operator"} if headers.get("X-Who") == "ok" else None

        r = self.registry(Gate([page()], rows=[row(1)]))
        for path in ("/api/extensions", "/api/extensions/reports"):
            with self.assertRaises(PermissionError):
                self.call(r, path, {"X-Who": "no"})
        self.assertEqual(len(self.call(r, "/api/extensions", {"X-Who": "ok"})["pages"]), 1)
        self.assertEqual(len(self.call(r, "/api/extensions/reports", {"X-Who": "ok"})["rows"]), 1)
        self.assertEqual(set(seen), {"extensions.read"})

    def test_a_missing_page_is_a_404_and_a_failed_source_a_502(self):
        class Gate(Source):
            def authorize(self, headers, action, key=None):
                return "operator"

        r = self.registry(Gate([page()], rows=[row(1)]))
        self.assertEqual(self.call(r, "/api/extensions/other")[0], 404)
        r = self.registry(Gate(boom=OSError("x")))
        self.assertEqual(self.call(r, "/api/extensions/reports")[0], 502)

    def test_the_module_has_no_way_to_run_anything(self):
        src = Path(ex.__file__).read_text()
        body = "\n".join(line.split("#")[0] for line in src.splitlines())
        for word in (
            "subprocess",
            "os.kill",
            "signal",
            "Popen",
            "os.system",
            "eval(",
            "exec(",
            "open(",
        ):
            self.assertNotIn(word, body, word)


if __name__ == "__main__":
    unittest.main()
