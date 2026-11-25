"""Tests for documents.py and the places that link to a document. Synthetic folders in a scratch directory, no real documents."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import documents as docs  # noqa: E402
import extensions as ex  # noqa: E402
import registry as reg  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name).resolve()
        self.root = self.d / "docs"
        (self.root / "board").mkdir(parents=True)
        (self.root / "board" / "paper.pdf").write_bytes(b"%PDF-1.4 x")
        (self.root / "notes.md").write_text("# hello")
        (self.root / "plan.docx").write_bytes(b"PK word")
        (self.root / "page.html").write_text("<script>alert(1)</script>")
        (self.root / "logo.svg").write_text("<svg onload=alert(1)/>")
        (self.root / ".secret.pdf").write_bytes(b"%PDF hidden")
        (self.root / ".hidden").mkdir()
        (self.root / ".hidden" / "a.pdf").write_bytes(b"%PDF hidden")
        self.outside = self.d / "outside"
        self.outside.mkdir()
        (self.outside / "private.pdf").write_bytes(b"%PDF private")
        self.evil = self.d / "docs-evil"
        self.evil.mkdir()
        (self.evil / "x.pdf").write_bytes(b"%PDF sibling")
        self.saved = os.environ.get("OPSCENTER_DOCUMENT_ROOTS")
        os.environ["OPSCENTER_DOCUMENT_ROOTS"] = str(self.root)

    def tearDown(self):
        if self.saved is None:
            os.environ.pop("OPSCENTER_DOCUMENT_ROOTS", None)
        else:
            os.environ["OPSCENTER_DOCUMENT_ROOTS"] = self.saved
        self.tmp.cleanup()

    def serve(self, root, path):
        r = reg.Registry()
        docs.register(r)
        route, _ = r.match("GET", docs.ROUTE)
        return route.handler(
            reg.Request("GET", docs.ROUTE, query={"root": [str(root)], "path": [path]})
        )


class Resolve(Base):
    def test_a_relative_and_an_absolute_path_inside_a_root_resolve_to_one_address(self):
        a = docs.link_for("board/paper.pdf")
        b = docs.link_for(str(self.root / "board" / "paper.pdf"))
        self.assertEqual(a, "/api/documents/file?root=0&path=board/paper.pdf")
        self.assertEqual(a, b)
        self.assertTrue(docs.is_link(a))

    def test_nothing_is_a_link_when_no_root_is_set_or_the_root_is_missing(self):
        os.environ["OPSCENTER_DOCUMENT_ROOTS"] = ""
        self.assertEqual(docs.roots(), [])
        self.assertIsNone(docs.link_for("notes.md"))
        os.environ["OPSCENTER_DOCUMENT_ROOTS"] = str(self.d / "nope")
        self.assertIsNone(docs.link_for("notes.md"))

    def test_a_path_that_leaves_the_root_is_refused_every_way(self):
        link = self.root / "to-outside"
        link.symlink_to(self.outside)
        (self.root / "private-link.pdf").symlink_to(self.outside / "private.pdf")
        for bad in (
            "../outside/private.pdf",
            "board/../../outside/private.pdf",
            str(self.outside / "private.pdf"),
            str(self.evil / "x.pdf"),
            "../docs-evil/x.pdf",
            "to-outside/private.pdf",
            "private-link.pdf",
            "/etc/passwd",
            "~/notes.md",
        ):
            self.assertIsNone(docs.link_for(bad), bad)
            self.assertIsNone(docs.resolve(bad), bad)

    def test_a_symlink_that_stays_inside_the_root_is_allowed(self):
        (self.root / "alias.md").symlink_to(self.root / "notes.md")
        self.assertEqual(docs.link_for("alias.md"), "/api/documents/file?root=0&path=alias.md")

    def test_hidden_files_folders_and_types_that_could_run_are_refused(self):
        for bad in (
            ".secret.pdf",
            ".hidden/a.pdf",
            "page.html",
            "logo.svg",
            "board",
            "missing.pdf",
            "",
            "a\x00.pdf",
        ):
            self.assertIsNone(docs.link_for(bad), repr(bad))

    def test_a_file_over_the_size_cap_is_refused(self):
        old = docs.MAX_BYTES
        docs.MAX_BYTES = 5
        try:
            self.assertIsNone(docs.link_for("board/paper.pdf"))
        finally:
            docs.MAX_BYTES = old

    def test_two_roots_are_told_apart_by_number(self):
        (self.evil / "x.pdf").write_bytes(b"%PDF sibling")
        os.environ["OPSCENTER_DOCUMENT_ROOTS"] = os.pathsep.join([str(self.root), str(self.evil)])
        self.assertEqual(docs.link_for("x.pdf"), "/api/documents/file?root=1&path=x.pdf")
        self.assertEqual(docs.link_for("notes.md"), "/api/documents/file?root=0&path=notes.md")

    def test_only_an_address_this_module_makes_is_a_document_link(self):
        for bad in (
            "https://t.test",
            "/api/documents/file",
            "/api/documents/file?root=x&path=a.pdf",
            "javascript:alert(1)",
            None,
            5,
        ):
            self.assertFalse(docs.is_link(bad), bad)


class Serve(Base):
    def test_a_pdf_is_shown_and_a_word_document_is_a_download(self):
        status, data, ctype, extra = self.serve(0, "board/paper.pdf")
        self.assertEqual((status, data, ctype), (200, b"%PDF-1.4 x", "application/pdf"))
        self.assertTrue(extra["Content-Disposition"].startswith("inline"))
        status, data, ctype, extra = self.serve(0, "plan.docx")
        self.assertTrue(extra["Content-Disposition"].startswith("attachment"))
        self.assertIn("wordprocessingml", ctype)

    def test_text_is_sent_as_plain_text(self):
        _, _, ctype, _ = self.serve(0, "notes.md")
        self.assertTrue(ctype.startswith("text/plain"))

    def test_the_route_refuses_what_resolve_refuses_and_never_reads_outside(self):
        (self.root / "private-link.pdf").symlink_to(self.outside / "private.pdf")
        for root, path in (
            (0, "../outside/private.pdf"),
            (0, str(self.outside / "private.pdf")),
            (0, "private-link.pdf"),
            (0, "page.html"),
            (0, ".secret.pdf"),
            (5, "notes.md"),
            (-1, "notes.md"),
        ):
            with self.assertRaises(KeyError, msg=f"{root} {path}"):
                self.serve(root, path)

    def test_a_root_that_is_not_a_number_is_a_bad_request(self):
        with self.assertRaises(ValueError):
            self.serve("x", "notes.md")

    def test_a_filename_cannot_break_out_of_the_header(self):
        (self.root / 'a"b\r\nSet-Cookie.md').write_text("x")
        _, _, _, extra = self.serve(0, 'a"b\r\nSet-Cookie.md')
        self.assertNotIn("\r", extra["Content-Disposition"])
        self.assertNotIn("\n", extra["Content-Disposition"])
        self.assertEqual(extra["Content-Disposition"].count('"'), 2)


class Rows(Base):
    def test_a_row_with_a_document_links_to_it_and_a_missing_one_says_so(self):
        ok = ex._row({"id": "a", "title": "Paper", "doc": "board/paper.pdf"})
        self.assertEqual(ok["url"], "/api/documents/file?root=0&path=board/paper.pdf")
        self.assertEqual(ok["doc"], "ok")
        gone = ex._row({"id": "b", "title": "Gone", "doc": "board/none.pdf"})
        self.assertEqual((gone["url"], gone["doc"]), (None, "missing"))
        outside = ex._row({"id": "c", "title": "Out", "doc": "../outside/private.pdf"})
        self.assertEqual((outside["url"], outside["doc"]), (None, "missing"))

    def test_a_web_address_wins_and_a_row_with_neither_has_no_doc(self):
        both = ex._row({"id": "a", "title": "t", "url": "https://t.test/x", "doc": "notes.md"})
        self.assertEqual((both["url"], both.get("doc")), ("https://t.test/x", None))
        none = ex._row({"id": "a", "title": "t"})
        self.assertEqual((none["url"], "doc" in none), (None, False))

    def test_a_row_cannot_carry_a_document_address_of_its_own(self):
        row = ex._row({"id": "a", "title": "t", "url": "/api/documents/file?root=0&path=notes.md"})
        self.assertIsNone(row["url"])

    def test_with_the_setting_off_a_document_path_is_never_a_link(self):
        os.environ["OPSCENTER_DOCUMENT_ROOTS"] = ""
        row = ex._row({"id": "a", "title": "t", "doc": "notes.md"})
        self.assertEqual((row["url"], row["doc"]), (None, "missing"))


class Decisions(Base):
    def make(self):
        f = self.d / "m.json"
        f.write_text(
            json.dumps(
                {
                    "pages": [
                        {"id": "ideas", "title": "Ideas", "group": "Platform", "kind": "list"}
                    ],
                    "rows": {
                        "ideas": [
                            {
                                "id": "i1",
                                "title": "First",
                                "state": "new",
                                "doc": "notes.md",
                                "actions": [
                                    {"id": "accept", "label": "Accept", "state": "accepted"},
                                    {"id": "defer", "label": "Defer"},
                                ],
                            },
                            {
                                "id": "i2",
                                "title": "Second",
                                "actions": [{"id": "reject", "label": "Reject"}],
                            },
                        ]
                    },
                }
            )
        )
        return f, ex.FileProvider(str(f))

    def test_an_action_records_a_decision_and_the_row_shows_it(self):
        f, p = self.make()
        before = f.read_text()
        out = p.extension_action("ideas", "i1", "accept")
        self.assertEqual(out["ok"], True)
        rows = ex.read_rows(p, "ideas")[0]["rows"]
        first = next(r for r in rows if r["id"] == "i1")
        self.assertEqual(first["state"], "accepted")
        self.assertEqual(first["fields"][-1]["label"], "Decision")
        self.assertIn("Accept", first["fields"][-1]["value"])
        self.assertEqual(next(r for r in rows if r["id"] == "i2")["state"], None)
        self.assertEqual(f.read_text(), before)
        self.assertTrue(p.decisions_path.is_file())

    def test_a_later_decision_replaces_the_earlier_one_and_the_label_is_the_default_state(self):
        _, p = self.make()
        p.extension_action("ideas", "i1", "accept")
        p.extension_action("ideas", "i1", "defer")
        first = next(r for r in ex.read_rows(p, "ideas")[0]["rows"] if r["id"] == "i1")
        self.assertEqual(first["state"], "Defer")
        self.assertEqual(len(json.loads(p.decisions_path.read_text())["ideas"]), 1)

    def test_an_undeclared_action_or_row_records_nothing(self):
        _, p = self.make()
        self.assertFalse(p.extension_action("ideas", "i1", "reject")["ok"])
        self.assertFalse(p.extension_action("ideas", "nope", "accept")["ok"])
        self.assertFalse(p.extension_action("other", "i1", "accept")["ok"])
        self.assertFalse(p.decisions_path.exists())

    def test_the_action_route_works_on_a_data_only_page(self):
        _, p = self.make()
        r = reg.Registry()
        ex.register(r, p)
        route, groups = r.match("POST", "/api/extensions/ideas/action")
        out = route.handler(
            reg.Request(
                "POST",
                "/api/extensions/ideas/action",
                body={"row": "i1", "action": "accept", "confirm": True},
                groups=groups,
            )
        )
        self.assertEqual(out["ok"], True)
        with self.assertRaises(ValueError):
            route.handler(
                reg.Request(
                    "POST",
                    "/api/extensions/ideas/action",
                    body={"row": "i1", "action": "accept"},
                    groups=groups,
                )
            )

    def test_a_corrupt_decisions_file_is_ignored_and_replaced(self):
        _, p = self.make()
        p.decisions_path.write_text("{nope")
        self.assertEqual(ex.read_rows(p, "ideas")[0]["rows"][0]["state"], "new")
        p.extension_action("ideas", "i1", "accept")
        self.assertEqual(
            json.loads(p.decisions_path.read_text())["ideas"]["i1"]["action"], "accept"
        )


if __name__ == "__main__":
    unittest.main()
