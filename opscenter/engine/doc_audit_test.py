"""The documentation audit: rules R1 to R12 against a real git origin and a fake docs home driver, the gap store merge, the surface slice,
discovery, duplicate pages, the close-out carry, the fail-closed run and the lock."""

import datetime as dt
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

DRIVER = textwrap.dedent(
    """
    import json, os, re, sys
    tool, args = sys.argv[1], json.loads(sys.argv[2])
    db = json.load(open(os.environ["FAKE_HOME"]))
    def out(obj, err=False):
        print(json.dumps({"result": {"isError": err, "content": [{"text": json.dumps(obj)}]}}))
    if tool == "getConfluencePage":
        p = db["pages"].get(args["pageId"])
        out(p if p else {"error": "missing"}, err=p is None)
    elif tool == "searchConfluenceUsingCql":
        m = re.search(r"ancestor = (\\d+)", args["cql"])
        root = m.group(1)
        if "created" in args["cql"]:
            rows = db.get("tree", {}).get(root, [])
            out({"results": rows, "totalSize": len(rows)})
        else:
            out({"results": db.get("children", {}).get(root, [])})
    """
)


def sh(*a, cwd=None):
    subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True)


def iso(days_ago):
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def page(title, parent="1", days_ago=1, body="Owner: a. Current version 1."):
    return {
        "title": title,
        "parentId": parent,
        "version": {"createdAt": iso(days_ago)},
        "body": body,
    }


class Base(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="doc-audit-"))
        self._env = dict(os.environ)
        self.dash = self.d / "state" / "dashboard"
        self.dash.mkdir(parents=True)
        os.environ.update(
            OPSCENTER_STATE_DIR=str(self.d / "state"),
            DOC_AUDIT_CONFIG=str(self.d / "cfg.json"),
            FAKE_HOME=str(self.d / "home.json"),
            DOCS_HOME_CMD=json.dumps([sys.executable, str(self.d / "driver.py")]),
        )
        (self.d / "driver.py").write_text(DRIVER)
        self.origin = self.d / "origin.git"
        self.clone = self.d / "clone"
        sh("git", "init", "-q", "--bare", str(self.origin))
        sh("git", "clone", "-q", str(self.origin), str(self.clone))
        for k, v in (
            ("user.email", "t@example.com"),
            ("user.name", "t"),
            ("commit.gpgsign", "false"),
        ):
            sh("git", "config", k, v, cwd=self.clone)
        (self.clone / "svc").mkdir()
        (self.clone / "svc" / "CHANGELOG.md").write_text("## 1.0.0\n")
        (self.clone / "other").mkdir()
        (self.clone / "other" / "x.txt").write_text("x")
        (self.clone / "tree").mkdir()
        for n in ("a.ps1", "b.ps1", "c.txt"):
            (self.clone / "tree" / n).write_text("x")
        sh("git", "add", "-A", cwd=self.clone)
        sh("git", "commit", "-q", "-m", "init", cwd=self.clone)
        sh("git", "branch", "-M", "main", cwd=self.clone)
        sh("git", "push", "-q", "-u", "origin", "main", cwd=self.clone)
        self.cfg = {
            "repos": {"r": str(self.clone)},
            "wiki_url": "https://docs.example.com/p/",
            "raci_page_id": "900",
        }
        self.home = {"pages": {}, "children": {}, "tree": {}}
        self.save()
        import doc_audit

        self.da = importlib.reload(doc_audit)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self.d, ignore_errors=True)

    def save(self):
        (self.d / "cfg.json").write_text(json.dumps(self.cfg))
        (self.d / "home.json").write_text(json.dumps(self.home))

    def registry(self, things, **extra):
        (self.dash / "doc-inventory.json").write_text(json.dumps(dict({"things": things}, **extra)))

    def child(self, root, pid, title, days_ago=1):
        self.home["pages"][pid] = page(title, root, days_ago)
        self.home["children"].setdefault(root, []).append(
            {"content": {"id": pid, "title": title}, "lastModified": iso(days_ago)}
        )

    def gaps(self, thing):
        gaps, links, home = self.da.audit_thing(thing, self.da.DocsHome(), {})
        return {g["id"]: g for g in gaps}, links, home


class Rules(Base):
    def test_a_live_tier_a_thing_with_no_home_is_a_high_gap_and_a_wip_thing_stops_after_it(self):
        g, links, home = self.gaps(
            {"id": "t", "name": "Svc", "tier": "A", "status": "live", "repo": "r"}
        )
        self.assertEqual((g["R1:home"]["severity"], links, home), ("high", [], None))
        g, _, _ = self.gaps({"id": "t", "name": "Svc", "tier": "B", "status": "live", "repo": "r"})
        self.assertEqual(g["R1:home"]["severity"], "medium")
        g, _, _ = self.gaps({"id": "t", "name": "Svc", "tier": "A", "status": "wip", "repo": "r"})
        self.assertEqual(list(g), ["R1:home"])
        self.assertEqual(g["R1:home"]["severity"], "low")

    def test_a_tier_a_home_needs_its_required_page_types(self):
        self.home["pages"]["10"] = page("Svc home")
        self.child("10", "11", "Svc Design Document")
        self.child("10", "12", "Svc runbook")
        self.save()
        t = {
            "id": "t",
            "name": "Svc",
            "tier": "A",
            "status": "live",
            "repo": "r",
            "confluence_home": "10",
            "service_desk": True,
        }
        g, links, home = self.gaps(t)
        self.assertEqual(
            sorted(k for k in g if k.startswith("R2")),
            ["R2:changelog", "R2:quickcard", "R2:release", "R2:troubleshooting"],
        )
        self.assertEqual(links[0]["url"], "https://docs.example.com/p/10")
        self.assertEqual(home["title"], "Svc home")

    def test_a_tier_b_thing_needs_a_runbook_and_a_changelog_somewhere(self):
        self.home["pages"]["10"] = page("Job home", body="Owner: a\n## Changelog\n| v | d |")
        self.save()
        g, _, _ = self.gaps(
            {
                "id": "t",
                "name": "Job",
                "tier": "B",
                "status": "live",
                "repo": "r",
                "confluence_home": "10",
            }
        )
        self.assertEqual(sorted(g), ["R2:runbook"])

    def test_the_repo_changelog_is_held_to_each_release_once_it_is_a_week_old(self):
        sh("git", "tag", "-a", "svc-v2.0.0", "-m", "r", cwd=self.clone)
        sh("git", "push", "-q", "origin", "svc-v2.0.0", cwd=self.clone)
        self.home["pages"]["10"] = page("Svc home")
        self.child("10", "11", "Changelog")
        self.save()
        t = {
            "id": "t",
            "name": "Svc",
            "tier": "A",
            "status": "live",
            "repo": "r",
            "confluence_home": "10",
            "release": "tag:svc-v*",
            "changelog_file": "svc/CHANGELOG.md",
            "path": "svc",
        }
        g, _, _ = self.gaps(t)
        self.assertNotIn("R3:repo:2.0.0", g)  # the release is minutes old
        self.assertNotIn("R8:marker", g)
        g, _, _ = self.gaps(dict(t, release="none"))
        self.assertIn("R8:marker", g)
        g, _, _ = self.gaps(dict(t, changelog_file="svc/MISSING.md"))
        self.assertIn("R3:repo-changelog", g)

    def test_a_docs_home_only_changelog_is_required_when_the_thing_says_so(self):
        self.home["pages"]["10"] = page("Svc home")
        self.save()
        t = {
            "id": "t",
            "name": "Svc",
            "tier": "A",
            "status": "live",
            "repo": "r",
            "confluence_home": "10",
            "changelog": "confluence",
            "release": "none",
        }
        g, _, _ = self.gaps(t)
        self.assertIn("R3:conf-changelog", g)

    def test_metadata_and_placement(self):
        self.home["pages"]["10"] = page("Svc home", parent="5", body="nothing useful")
        self.child("10", "11", "Svc runbook")
        self.save()
        t = {
            "id": "t",
            "name": "Svc",
            "tier": "B",
            "status": "live",
            "repo": "r",
            "confluence_home": "10",
            "expected_parent": "6",
            "changelog_page": True,
        }
        g, _, _ = self.gaps(t)
        self.assertEqual(sorted(g), ["R6:metadata", "R7:placement"])
        self.assertEqual(g["R6:metadata"]["text"], "Home page is missing metadata: Owner.")

    def test_a_stale_home_while_the_code_kept_changing_is_a_low_gap(self):
        self.home["pages"]["10"] = page("Svc home", days_ago=400)
        self.child("10", "11", "Svc runbook", days_ago=400)
        self.save()
        t = {
            "id": "t",
            "name": "Svc",
            "tier": "B",
            "status": "live",
            "repo": "r",
            "confluence_home": "10",
            "path": "svc",
            "changelog_page": True,
        }
        g, _, _ = self.gaps(t)
        self.assertEqual(g["R5:age"]["severity"], "low")


class Store(Base):
    def res(self, gaps, name="Thing"):
        return {"gaps": gaps, "links": [], "meta": {"id": "t", "name": name}}

    def test_a_new_gap_bumps_the_generation_and_a_closed_gap_is_recorded(self):
        g1 = self.da.gap("R1:home", "R1", "high", "no home")
        first = self.da.merge_store({}, {"t": self.res([g1])}, "2026-01-01T00:00:00Z")["t"]
        self.assertEqual(
            (first["generation"], first["key"], first["priority"], first["new_since_last"]),
            (1, "doc-t-g1", "high", []),
        )
        same = self.da.merge_store(
            {"things": {"t": first}}, {"t": self.res([dict(g1)])}, "2026-01-02T00:00:00Z"
        )["t"]
        self.assertEqual(
            (same["generation"], same["gaps"][0]["first_seen"]), (1, "2026-01-01T00:00:00Z")
        )
        g2 = self.da.gap("R6:metadata", "R6", "low", "meta")
        more = self.da.merge_store(
            {"things": {"t": same}}, {"t": self.res([dict(g1), g2])}, "2026-01-03T00:00:00Z"
        )["t"]
        self.assertEqual(
            (more["generation"], more["new_since_last"], more["key"]),
            (2, ["R6:metadata"], "doc-t-g2"),
        )
        closed = self.da.merge_store(
            {"things": {"t": more}}, {"t": self.res([])}, "2026-01-04T00:00:00Z"
        )["t"]
        self.assertEqual(
            (closed["priority"], [c["id"] for c in closed["closed"]]),
            ("none", ["R1:home", "R6:metadata"]),
        )

    def test_the_surface_takes_high_and_medium_things_worst_first_capped_and_skips_hidden(self):
        things = {}
        for i in range(8):
            things[f"t{i}"] = {
                "id": f"t{i}",
                "priority": "medium",
                "gaps": [{"severity": "medium"}] * (i + 1),
            }
        things["low"] = {"id": "low", "priority": "low", "gaps": [{"severity": "low"}]}
        things["hi"] = {"id": "hi", "priority": "high", "gaps": [{"severity": "high"}]}
        s = self.da.surface(things)
        self.assertEqual((s[0], len(s), "low" in s), ("hi", 5, False))
        self.assertNotIn("t7", self.da.surface(things, {"t7"}))


class Sources(Base):
    def test_discovery_finds_unregistered_directories_and_loose_files(self):
        self.cfg["discovery"] = {
            "dirs": [{"repo": "r", "parent": "", "label": "r"}],
            "file_trees": [
                {
                    "repo": "r",
                    "dir": "tree",
                    "ext": ".ps1",
                    "label": "scripts",
                    "gap_id": "scripts",
                    "legacy_match": True,
                }
            ],
        }
        self.save()
        reg = {
            "things": [
                {"id": "s", "repo": "r", "path": "svc", "match": ""},
                {"id": "tr", "repo": "r", "path": "tree", "match": "a.*"},
            ]
        }
        found, loose = self.da.discover(reg)
        self.assertEqual(sorted(found), ["r/other"])
        self.assertEqual(loose, [("scripts", "scripts", ["b.ps1"])])
        reg["discovery_ignore"] = ["r:other"]
        self.assertEqual(self.da.discover(reg)[0], [])

    def test_duplicate_pages_are_found_by_title_without_the_copy_suffix(self):
        self.cfg["dup_roots"] = {"700": "the team tree"}
        self.save()
        self.home["tree"]["700"] = [
            {
                "content": {
                    "id": "71",
                    "title": "Guide",
                    "history": {"createdDate": "2026-01-01T00:00:00Z"},
                }
            },
            {
                "content": {
                    "id": "72",
                    "title": "Guide (1)",
                    "history": {"createdDate": "2026-02-01T00:00:00Z"},
                }
            },
            {
                "content": {
                    "id": "73",
                    "title": "Other",
                    "history": {"createdDate": "2026-02-01T00:00:00Z"},
                }
            },
        ]
        self.save()
        gaps, seen = self.da.duplicate_gaps(self.da.DocsHome())
        self.assertEqual((seen, len(gaps), gaps[0]["id"]), (3, 1, "R11:71-72"))
        self.assertIn("the team tree", gaps[0]["text"])

    def test_the_closeout_gap_clears_when_the_page_is_edited_after_the_check(self):
        state = self.d / "close.json"
        state.write_text(
            json.dumps(
                {
                    "tickets": {
                        "K-1": {
                            "doc_check": {
                                "result": "stale",
                                "page": "10",
                                "at": "2026-01-01T00:00:00Z",
                                "thing": "t",
                                "page_title": "P",
                            }
                        },
                        "K-2": {"doc_check": {"result": "missing", "at": "2026-01-01"}},
                        "K-3": {"doc_check": {"result": "stale", "resolved": True}},
                    }
                }
            )
        )
        self.cfg["closeout_state"] = str(state)
        self.home["pages"]["10"] = page("P", days_ago=1)
        self.save()
        out = self.da.closeout_gaps(self.da.DocsHome(), {"t"})
        self.assertEqual(
            list(out), ["_registry"]
        )  # K-1 cleared by the later edit; K-2 has no owner thing
        self.assertIn("No registry thing owns this change", out["_registry"][0]["text"])
        self.home["pages"]["10"] = page("P", days_ago=900)
        self.save()
        self.da = importlib.reload(self.da)
        out = self.da.closeout_gaps(self.da.DocsHome(), {"t"})
        self.assertEqual(sorted(out), ["_registry", "t"])
        self.assertIn("https://docs.example.com/p/10", out["t"][0]["text"])

    def test_jobs_without_a_catalog_entry_are_listed(self):
        (self.d / "jobs.json").write_text(
            json.dumps({"jobs": [{"id": "j1", "name": "one"}, {"id": "j2"}]})
        )
        (self.d / "cat.json").write_text(json.dumps({"jobs": {"j2": {}}}))
        self.cfg.update(cron_jobs=str(self.d / "jobs.json"), cron_catalog=str(self.d / "cat.json"))
        self.save()
        self.assertEqual(self.da.internal_gaps(), ["j1 one"])

    def test_the_ownership_table_gives_accountable_and_responsible_people(self):
        self.home["pages"]["900"] = page(
            "RACI",
            body="| Domain / Responsibility | Ann | Bo |\n|---|---|---|\n| **Billing** | A, R | R |\n| Other | I | A |\n",
        )
        self.save()
        raci = self.da.load_raci(self.da.DocsHome())
        self.assertEqual(raci["Billing"], {"A": ["Ann"], "R": ["Ann", "Bo"]})
        self.assertEqual(raci["Other"], {"A": ["Bo"], "R": []})
        self.home["pages"]["900"] = page("RACI", body="no table")
        self.save()
        self.da = importlib.reload(self.da)
        with self.assertRaises(self.da.AuditError):
            self.da.load_raci(self.da.DocsHome())


class Runs(Base):
    def run_main(self, *argv):
        sys.argv = ["doc_audit.py", *argv]
        return self.da.main()

    def test_a_full_run_writes_the_store_and_a_failed_run_keeps_it_with_the_error(self):
        self.home["pages"]["10"] = page("Svc home")
        self.child("10", "11", "Svc runbook")
        self.cfg["discovery"] = {"dirs": [{"repo": "r", "parent": "", "label": "r"}]}
        self.home["pages"]["900"] = page(
            "RACI", body="| Domain / Responsibility | Ann |\n|---|---|\n"
        )
        self.save()
        self.registry(
            [
                {
                    "id": "t",
                    "name": "Svc",
                    "tier": "B",
                    "status": "live",
                    "repo": "r",
                    "confluence_home": "10",
                    "changelog_page": True,
                }
            ]
        )
        self.assertEqual(self.run_main(), 0)
        store = json.loads((self.dash / "doc-gaps.json").read_text())
        self.assertEqual(store["things"]["t"]["priority"], "none")
        self.assertIn("R9:r/other", [g["id"] for g in store["things"]["_registry"]["gaps"]])
        self.assertIsNone(store["last_error"])
        os.environ["DOCS_HOME_CMD"] = "[]"
        self.assertEqual(self.run_main(), 2)
        kept = json.loads((self.dash / "doc-gaps.json").read_text())
        self.assertEqual(kept["things"], store["things"])
        self.assertIn("no docs home adapter", kept["last_error"])

    def test_dry_run_writes_nothing_and_an_empty_registry_fails_closed(self):
        self.registry([])
        self.assertEqual(self.run_main("--dry-run"), 2)
        self.assertFalse((self.dash / "doc-gaps.json").exists())

    def test_a_second_run_while_the_lock_is_held_skips(self):
        import fcntl

        with open(self.dash / ".doc-audit.lock", "w") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            self.assertEqual(self.run_main(), 0)
        self.assertFalse((self.dash / "doc-gaps.json").exists())


if __name__ == "__main__":
    unittest.main()
