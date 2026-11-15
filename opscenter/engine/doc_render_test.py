"""
doc_render_test.py
Purpose: Repo markdown renders into docs home HTML: the shallowest heading becomes the top heading and the document title is dropped;
         inline code and fenced code stay byte-exact apart from ASCII normalization; non-ASCII punctuation is normalized; tables, bullet
         lists, links and quotes render; section() cuts a document between two headings; stamp() names the repo, files and commit and
         never calls the repo the source; sanitize_check() reports back-to-back rules, non-ASCII, semicolons in prose (never in code)
         and any configured internal term.
Run:     python3 doc_render_test.py
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import doc_render as d

MD = '# Title\n\n## Intro\n\nSome *text*, with `a; b` and a [link](https://x.example).\n\n- one\n- two\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n```bash\necho "x; y"\n```\n\n> quote\n'


class Render(unittest.TestCase):
    def test_the_title_is_dropped_and_the_shallowest_heading_is_the_top(self):
        out = d.render(MD)
        self.assertNotIn("<h1>", out)
        self.assertIn("<h2>Intro</h2>", out)
        nested = d.render("# T\n\n## A\n\n### Sub\n")
        self.assertIn("<h2>A</h2>", nested)
        self.assertIn("<h3>Sub</h3>", nested)

    def test_inline_markup_links_lists_tables_and_quotes(self):
        out = d.render(MD)
        self.assertIn("<em>text</em>", out)
        self.assertIn('<a href="https://x.example">link</a>', out)
        self.assertIn("<ul>", out)
        self.assertIn(
            "<table><thead><tr><th>A</th><th>B</th></tr></thead><tbody><tr><td>1</td><td>2</td></tr></tbody></table>",
            out,
        )
        self.assertIn("quote", out)

    def test_code_is_byte_exact_and_never_flagged_for_semicolons(self):
        out = d.render(MD)
        self.assertIn('<pre><code class="language-bash">echo "x; y"</code></pre>', out)
        self.assertIn("<code>a; b</code>", out)
        self.assertEqual(d.sanitize_check(out), [])

    def test_non_ascii_punctuation_is_normalized(self):
        out = d.render(
            "## T\n\nIt\u2019s a \u201cquote\u201d \u2014 and an arrow \u2192 here\u2026\n"
        )
        self.assertTrue(out.isascii())
        self.assertIn("It's", out)
        self.assertIn("-&gt;", out)
        self.assertEqual(d.to_ascii("a\u00a0b"), "a b")

    def test_render_turns_a_prose_semicolon_into_a_comma_and_the_check_reports_one_that_is_left(
        self,
    ):
        self.assertIn("One, two.", d.render("## T\n\nOne; two.\n"))
        self.assertIn("semicolon in prose", d.sanitize_check("<p>One; two.</p>"))
        self.assertEqual(d.sanitize_check("<p>a &amp; b</p><pre>x; y</pre>"), [])

    def test_back_to_back_rules_and_non_ascii_are_reported(self):
        self.assertIn(
            "back-to-back <hr> (renders as a double line)", d.sanitize_check("<p>x</p><hr>\n<hr>")
        )
        self.assertTrue(any(p.startswith("non-ASCII") for p in d.sanitize_check("<p>\u2603</p>")))

    def test_internal_terms_come_from_configuration(self):
        self.assertEqual(d.sanitize_check("<p>see the Runbook Tool</p>"), [])
        os.environ["DOC_RENDER_INTERNAL_TERMS"] = '["runbook tool"]'
        try:
            self.assertEqual(
                d.sanitize_check("<p>see the Runbook Tool</p>"),
                ["internal reference: runbook tool"],
            )
        finally:
            os.environ.pop("DOC_RENDER_INTERNAL_TERMS")


class Section(unittest.TestCase):
    DOC = "# T\n\n## One\n\na\n\n## Two\n\nb\n\n## Three\n\nc\n"

    def test_from_a_heading_to_the_next(self):
        s = d.section(self.DOC, "Two", "Three")
        self.assertIn("## Two", s)
        self.assertIn("b", s)
        self.assertNotIn("Three", s)
        self.assertNotIn("One", s)

    def test_from_a_heading_to_the_end(self):
        self.assertIn("c", d.section(self.DOC, "Three"))


class Stamp(unittest.TestCase):
    def test_names_the_repo_files_and_commit_and_never_calls_the_repo_the_source(self):
        s = d.stamp("acme/infra", ["docs/a.md", "docs/b.md"], "abc123")
        self.assertIn("acme/infra", s)
        self.assertIn("<code>docs/a.md</code>, <code>docs/b.md</code>", s)
        self.assertIn("<code>abc123</code>", s)
        self.assertIn("documentation record", s)
        self.assertNotIn("source of truth", s)
        self.assertIn("in the docs home", s)
        self.assertIn("in the wiki", d.stamp("r", ["p"], "c", home="the wiki"))
        self.assertTrue(s.startswith("<hr>"))


if __name__ == "__main__":
    unittest.main()
