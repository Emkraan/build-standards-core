"""Tests for link_health.py. Hermetic: no network, temp files only.

Date: 2026-10-26
"""

import json
import shutil
import socket
import subprocess
import tempfile
import unittest
import urllib.parse
from pathlib import Path

import link_health as lh

LINKS = [
    {"name": "Alive", "url": "https://alive.example.com/", "group": "A", "note": None},
    {"name": "Gone", "url": "https://gone.example.com/x", "group": "A", "note": None},
    {"name": "Flaky", "url": "https://flaky.example.com/", "group": "B", "note": None},
    {"name": "Lan", "url": "http://lan.example.local/", "group": "B", "note": "On network"},
]


def fake_probe(url):
    host = urllib.parse.urlsplit(url).hostname
    return {
        "alive.example.com": ("ok", "HTTP 302", 302),
        "gone.example.com": ("hard", "HTTP 404", 404),
        "flaky.example.com": ("soft", "Timed out", None),
    }[host]


class ProbeTest(unittest.TestCase):
    def test_dns_failure_is_hard(self):
        self.assertEqual(lh.probe("https://x.invalid/", resolves=lambda h: False)[0], "hard")

    def test_redirect_and_auth_are_alive(self):
        for code in (200, 302, 401, 403, 500):
            self.assertEqual(
                lh.probe("https://a.b/", resolves=lambda h: True, request=lambda m, p, c=code: c)[
                    0
                ],
                "ok",
            )

    def test_404_and_410_are_hard(self):
        for code in (404, 410):
            self.assertEqual(
                lh.probe("https://a.b/", resolves=lambda h: True, request=lambda m, p, c=code: c)[
                    0
                ],
                "hard",
            )

    def test_head_refused_falls_back_to_get(self):
        calls = []

        def req(method, parts):
            calls.append(method)
            return 405 if method == "HEAD" else 200

        self.assertEqual(lh.probe("https://a.b/", resolves=lambda h: True, request=req)[0], "ok")
        self.assertEqual(calls, ["HEAD", "GET"])

    def test_timeout_is_soft(self):
        def req(method, parts):
            raise socket.timeout("slow")

        self.assertEqual(lh.probe("https://a.b/", resolves=lambda h: True, request=req)[0], "soft")


class ClassifyTest(unittest.TestCase):
    def test_first_run(self):
        doc = lh.classify(LINKS, None, probe_fn=fake_probe, now="2026-10-26T10:00:00Z")
        states = {r["name"]: r["state"] for r in doc["links"].values()}
        self.assertEqual(states, {"Alive": "ok", "Gone": "dead", "Flaky": "warn", "Lan": "skipped"})
        self.assertEqual([d["name"] for d in doc["dead"]], ["Gone"])
        self.assertEqual(doc["checked"], 3)

    def test_soft_failure_twice_is_dead_and_keeps_since(self):
        first = lh.classify(LINKS, None, probe_fn=fake_probe, now="2026-10-19T10:00:00Z")
        second = lh.classify(LINKS, first, probe_fn=fake_probe, now="2026-10-26T10:00:00Z")
        flaky = second["links"]["https://flaky.example.com/"]
        self.assertEqual(flaky["state"], "dead")
        self.assertEqual(flaky["since"], "2026-10-19T10:00:00Z")
        self.assertEqual(sorted(d["name"] for d in second["dead"]), ["Flaky", "Gone"])

    def test_recovery_clears(self):
        first = lh.classify(LINKS, None, probe_fn=fake_probe)
        doc = lh.classify(LINKS, first, probe_fn=lambda u: ("ok", "HTTP 200", 200))
        self.assertEqual(doc["dead"], [])


def _catalog(d, links=None):
    cat = Path(d) / "catalog.json"
    links = links or [
        {"name": "Alive", "url": "https://alive.example.com/"},
        {"name": "Gone", "url": "https://gone.example.com/x"},
    ]
    cat.write_text(
        json.dumps({"groups": [{"id": "a", "title": "A", "hue": "teal", "links": links}]}, indent=2)
        + "\n"
    )
    return cat


def _no_runner(args, **kw):
    raise AssertionError(f"unexpected command {args}")


class StateTest(unittest.TestCase):
    def test_missing_state_reads_empty(self):
        with tempfile.TemporaryDirectory() as d:
            st = lh.read_state(Path(d) / "none.json", Path(d) / "e.json", Path(d) / "c.json")
            self.assertEqual(st["dead"], [])

    def test_pending_edit_and_deployed_edit(self):
        with tempfile.TemporaryDirectory() as d:
            out, edits, cat = Path(d) / "h.json", Path(d) / "e.json", _catalog(d)
            out.write_text(json.dumps(lh.classify(LINKS, None, probe_fn=fake_probe)))
            self.assertEqual(lh.dead_count(out, edits, cat), 1)
            edits.write_text(json.dumps({"https://gone.example.com/x": {"pr": 7, "at": lh._now()}}))
            st = lh.read_state(out, edits, cat)
            self.assertEqual(st["dead"][0]["edit"]["pr"], 7)
            self.assertEqual(lh.dead_count(out, edits, cat), 0)
            # after the merge deploys, the old address is gone from the catalog and drops out
            _catalog(d, [{"name": "Alive", "url": "https://alive.example.com/"}])
            self.assertEqual(lh.read_state(out, edits, cat)["dead"], [])
            self.assertEqual(lh.read_state(out, edits, cat)["edits"], {})

    def test_stale_edit_expires(self):
        with tempfile.TemporaryDirectory() as d:
            out, edits, cat = Path(d) / "h.json", Path(d) / "e.json", _catalog(d)
            out.write_text(json.dumps(lh.classify(LINKS, None, probe_fn=fake_probe)))
            edits.write_text(
                json.dumps({"https://gone.example.com/x": {"pr": 7, "at": "2026-01-01T00:00:00Z"}})
            )
            self.assertEqual(lh.dead_count(out, edits, cat), 1)

    def test_cli_writes_state(self):
        with tempfile.TemporaryDirectory() as d:
            cat = Path(d) / "c.json"
            cat.write_text(
                json.dumps(
                    {
                        "groups": [
                            {
                                "title": "B",
                                "links": [
                                    {"name": "Lan", "url": "http://x.local/", "note": "On network"}
                                ],
                            }
                        ]
                    }
                )
            )
            out = Path(d) / "h.json"
            self.assertEqual(lh.main(["check", "--catalog", str(cat), "--out", str(out)]), 0)
            self.assertEqual(json.loads(out.read_text())["counts"]["skipped"], 1)

    def test_catalog_is_valid(self):
        links = lh.load_catalog(
            Path(__file__).resolve().parent / "fixtures" / "links-catalog.example.json"
        )
        self.assertGreater(len(links), 5)
        self.assertEqual(len({x["url"] for x in links}), len(links), "duplicate url in catalog")


class EditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.cat, self.out, self.edits = _catalog(d), Path(d) / "h.json", Path(d) / "e.json"
        self.out.write_text(json.dumps(lh.classify(LINKS, None, probe_fn=fake_probe)))
        self.opened = []

    def tearDown(self):
        self.tmp.cleanup()

    def fake_open(self, mutate, title, summary, branch):
        data = json.loads(self.cat.read_text())
        mutate(data)
        self.opened.append((data, title, branch))
        return 120, "https://github.com/owner/ops-center/pull/120"

    def edit(self, *a, probe_fn=fake_probe, **kw):
        return lh.edit_link(
            *a,
            probe_fn=probe_fn,
            open_pr=self.fake_open,
            runner=_no_runner,
            out=self.out,
            edits=self.edits,
            catalog=self.cat,
            **kw,
        )

    def test_swap_opens_pr_and_records_edit(self):
        r = self.edit("swap", "https://gone.example.com/x", "https://alive.example.com/new")
        self.assertEqual((r["status"], r["pr"]), ("pr", 120))
        data, title, branch = self.opened[0]
        self.assertEqual(data["groups"][0]["links"][1]["url"], "https://alive.example.com/new")
        self.assertEqual(title, "fix(links): correct the Gone address")
        self.assertTrue(branch.startswith("links/swap-gone-"))
        self.assertEqual(lh.dead_count(self.out, self.edits, self.cat), 0)

    def test_swap_refuses_a_dead_or_bad_or_duplicate_address(self):
        with self.assertRaises(lh.EditError) as e:
            self.edit("swap", "https://gone.example.com/x", "https://gone.example.com/y")
        self.assertEqual(e.exception.status, 422)
        for bad in (
            "ftp://x",
            "not a url",
            "https://gone.example.com/x",
            "https://alive.example.com/",
        ):
            with self.assertRaises(lh.EditError):
                self.edit("swap", "https://gone.example.com/x", bad)
        self.assertEqual(self.opened, [])

    def test_remove_drops_link(self):
        r = self.edit("remove", "https://gone.example.com/x")
        self.assertEqual(r["status"], "pr")
        self.assertEqual([x["name"] for x in self.opened[0][0]["groups"][0]["links"]], ["Alive"])

    def test_remove_of_a_link_that_answers_again_clears_the_flag(self):
        r = self.edit(
            "remove", "https://gone.example.com/x", probe_fn=lambda u: ("ok", "HTTP 200", 200)
        )
        self.assertEqual(r["status"], "alive")
        self.assertEqual(self.opened, [])
        self.assertEqual(json.loads(self.out.read_text())["dead"], [])

    def test_unknown_link_and_open_pr_refused(self):
        with self.assertRaises(lh.EditError) as e:
            self.edit("remove", "https://nope.example.com/")
        self.assertEqual(e.exception.status, 404)
        self.edits.write_text(
            json.dumps({"https://gone.example.com/x": {"pr": 9, "at": lh._now()}})
        )
        with self.assertRaises(lh.EditError) as e:
            lh.edit_link(
                "remove",
                "https://gone.example.com/x",
                probe_fn=fake_probe,
                open_pr=self.fake_open,
                runner=lambda a, **k: "OPEN\n",
                out=self.out,
                edits=self.edits,
                catalog=self.cat,
            )
        self.assertEqual(e.exception.status, 409)


FAKE_GH = """#!/bin/sh
case "$1" in
  api) echo 100 ;;
  pr) echo "https://github.com/owner/ops-center/pull/102" ;;
esac
"""


STUB_CHANGELOG = """import sys
a = sys.argv[1:]
if a[0] == "new":
    pr, title = a[a.index("--pr") + 1], a[a.index("--title") + 1]
    p = "CHANGELOG.md"
    s = open(p).read().replace("<!-- changelog:entries -->", "<!-- changelog:entries -->\\n## [#%s] %s" % (pr, title))
    open(p, "w").write(s)
"""


class OpenPrTest(unittest.TestCase):
    """The real git flow against a local origin. Only gh is faked (it returns PR 102 against a
    predicted 101, so the renumber path runs too)."""

    def test_branch_commit_changelog_and_renumber(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)

            def run(*a, cwd=None):
                return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True).stdout

            run("git", "init", "-q", "--bare", "-b", "main", str(d / "origin.git"))
            seed = d / "seed"
            run("git", "clone", "-q", str(d / "origin.git"), str(seed))
            (seed / "tools").mkdir()
            (seed / "tools" / "changelog.py").write_text(STUB_CHANGELOG)
            (seed / "CHANGELOG.md").write_text("# Changelog\n\n<!-- changelog:entries -->\n")
            cat = seed / lh.CATALOG_REL
            cat.parent.mkdir(parents=True)
            _catalog(cat.parent)
            shutil.move(str(cat.parent / "catalog.json"), str(cat))
            run("git", "add", "-A", cwd=seed)
            run("git", *lh.IDENT, "commit", "-q", "-m", "seed", cwd=seed)
            run("git", "push", "-q", "-u", "origin", "HEAD:main", cwd=seed)
            gh = d / "gh"
            gh.write_text(FAKE_GH)
            gh.chmod(0o755)
            old = (lh.GH, lh.CHANGELOG_TOOL)
            lh.GH = str(gh)
            lh.CHANGELOG_TOOL = "tools/changelog.py"
            try:

                def mutate(data):
                    data["groups"][0]["links"][1]["url"] = "https://new.example.com/"

                num, url = lh.open_catalog_pr(
                    mutate,
                    "fix(links): correct the Gone address",
                    "the owner corrected it.",
                    "links/swap-gone-1",
                    repo=seed,
                )
            finally:
                lh.GH, lh.CHANGELOG_TOOL = old
            self.assertEqual(num, 102)
            show = run(
                "git", "--git-dir", str(d / "origin.git"), "show", "links/swap-gone-1:CHANGELOG.md"
            )
            self.assertIn("## [#102] ", show)
            body = run(
                "git",
                "--git-dir",
                str(d / "origin.git"),
                "show",
                f"links/swap-gone-1:{lh.CATALOG_REL}",
            )
            self.assertIn("https://new.example.com/", body)
            self.assertNotIn("links/swap-gone-1", run("git", "branch", cwd=seed))
            self.assertEqual(len(run("git", "worktree", "list", cwd=seed).splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
