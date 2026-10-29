"""Tests for plans.py. Synthetic files in a scratch folder, Jira refresh stubbed, no real plans."""

from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

TRACKER = """---
title: Synthetic build
type: tracker
status: active
summary: A synthetic project.
updated: 2026-10-16
tickets: PRJ-101, PRJ-102
next: Do the next thing (me)
---

## Where it stands
Fine.

## Next steps
- [x] First
- [ ] Second
- [ ] Third

## Log
- [x] not a step
"""

SBAR_PLAN = """---
title: Synthetic plan
type: plan
status: proposed
summary: A synthetic SBAR plan.
updated: 2026-10-10
---

## Situation
s
## Background
b
## Assessment
a
## Recommendation
r
"""


class PlansTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "plans"
        self.root.mkdir()
        os.environ["PLANS_DIR"] = str(self.root)
        self.cfg = Path(self.tmp.name) / "plans-config.json"
        self.cfg.write_text(
            json.dumps(
                {
                    "project": "PRJ",
                    "default_repo": "acme/infra",
                    "untracked_repos": ["acme/infra", "acme/app"],
                    "browse_url": "https://tracker.example/browse/",
                }
            )
        )
        os.environ["PLANS_CONFIG"] = str(self.cfg)
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import plans

        self.m = importlib.reload(plans)
        self.m._refresh_jira = lambda keys: None
        self._kick = self.m.swr.kick
        self.m.swr.kick = lambda name, fn: None
        self.m._gh = lambda query: (_ for _ in ()).throw(
            AssertionError("real gh must not run in tests")
        )
        self.write("projects/synthetic/tracker.md", TRACKER)
        self.write(
            "projects/synthetic/build-plan.md",
            "---\ntitle: Build plan\ntype: plan\nstatus: approved\n---\nbody\n",
        )
        self.write("projects/synthetic/host-record.md", "# Heading only record\n")
        self.write("library/synthetic-plan.md", SBAR_PLAN)
        self.write(
            "library/old-plan.md",
            "---\ntitle: Old\ntype: plan\nstatus: done\n---\n## Situation\nx\n",
        )
        self.write("library/notes.txt", "not markdown")
        self.write(".format.md", "# hidden spec")

    def tearDown(self):
        self.m.swr.kick = self._kick
        self.tmp.cleanup()
        os.environ.pop("PLANS_DIR", None)
        os.environ.pop("PLANS_CONFIG", None)

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def test_done_with_open_steps_shows_active(self):
        self.write(
            "projects/half/tracker.md",
            "---\ntitle: Half\ntype: tracker\nstatus: done\nupdated: 2026-10-20\n---\n## Next steps\n- [x] a\n- [ ] b\n",
        )
        self.write(
            "projects/whole/tracker.md",
            "---\ntitle: Whole\ntype: tracker\nstatus: done\nupdated: 2026-10-20\n---\n## Next steps\n- [x] a\n",
        )
        st = {p["slug"]: p["status"] for p in self.m.items()["projects"]}
        self.assertEqual(st["half"], "active")
        self.assertEqual(st["whole"], "done")

    def test_index_shapes(self):
        d = self.m.items()
        self.assertEqual([p["slug"] for p in d["projects"]], ["synthetic"])
        pr = d["projects"][0]
        self.assertEqual(pr["title"], "Synthetic build")
        self.assertEqual(pr["tracker"]["progress"], {"done": 1, "total": 3})
        self.assertEqual(pr["tracker"]["tickets"], ["PRJ-101", "PRJ-102"])
        self.assertEqual(pr["tracker"]["next"], "Do the next thing (me)")
        self.assertEqual([x["name"] for x in pr["docs"]], ["build-plan.md", "host-record.md"])
        self.assertEqual(pr["docs"][1]["title"], "Heading only record")
        self.assertFalse(pr["docs"][1]["front_matter"])
        names = [r["name"] for r in d["library"]]
        self.assertEqual(names, ["synthetic-plan.md", "old-plan.md"])
        self.assertTrue(d["library"][0]["sbar"])
        self.assertFalse(d["library"][1]["sbar"])
        self.assertEqual(d["counts"], {"projects": 1, "library": 1, "archived": 0})
        ids = [r["id"] for r in d["library"]] + [x["id"] for x in pr["docs"]]
        self.assertNotIn(".format.md", ids)

    def test_read_and_jail(self):
        r = self.m.read("library/synthetic-plan.md")
        self.assertIn("## Situation", r["text"])
        for bad in (
            "../x.md",
            "/etc/passwd",
            "library/../../x.md",
            ".format.md",
            "library/notes.txt",
            "projects",
        ):
            with self.assertRaises(PermissionError, msg=bad):
                self.m.read(bad)
        with self.assertRaises(KeyError):
            self.m.read("library/missing.md")
        with self.assertRaises(PermissionError):
            self.m.read("projects/synthetic")

    def test_archive_restore_file(self):
        v = str((self.root / "library/synthetic-plan.md").stat().st_mtime_ns)
        wi = self.m.archive("library/synthetic-plan.md", v, what_if=True)
        self.assertTrue(wi["what_if"])
        self.assertTrue((self.root / "library/synthetic-plan.md").exists())
        r = self.m.archive("library/synthetic-plan.md", v)
        self.assertEqual(r["to"], "archive/library/synthetic-plan.md")
        self.assertEqual(self.m.items()["counts"]["archived"], 1)
        # Already archived is an idempotent success.
        self.assertTrue(self.m.archive("archive/library/synthetic-plan.md")["already"])
        back = self.m.restore("archive/library/synthetic-plan.md")
        self.assertEqual(back["to"], "library/synthetic-plan.md")
        self.assertTrue((self.root / "library/synthetic-plan.md").exists())

    def test_archive_project_and_conflict(self):
        with self.assertRaises(self.m.Conflict):
            self.m.archive("projects/synthetic", "1")
        v = self.m.items()["projects"][0]["version"]
        r = self.m.archive("projects/synthetic", v)
        self.assertEqual(r["to"], "archive/projects/synthetic")
        d = self.m.items()
        self.assertEqual(d["projects"], [])
        self.assertEqual(d["archived"]["projects"][0]["slug"], "synthetic")
        self.assertTrue((self.root / "projects").is_dir())  # section folder stays
        self.m.restore("archive/projects/synthetic")
        self.assertEqual(self.m.items()["projects"][0]["slug"], "synthetic")
        self.assertFalse((self.root / "archive/projects").exists())

    def test_restore_refuses_overwrite(self):
        self.m.archive("library/old-plan.md")
        self.write("library/old-plan.md", "# new one\n")
        time.sleep(0.01)
        with self.assertRaises(self.m.Conflict):
            self.m.restore("archive/library/old-plan.md")

    # ---- freshness: synthetic gh and ticket data only ----

    def _cut(self):
        # The fixture tracker says updated 2026-10-16 and is written now, so its cutoff is that day's end.
        return self.m._written_cutoff("2026-10-16", time.time())

    def _fake_gh(self, nodes_by_key, recent=None):
        def fake(query):
            out = {}
            for i, part in enumerate(query.split("search(")[1:]):
                key = next((k for k in nodes_by_key if k in part.split("{")[0]), None)
                out[f"s{i}"] = {"nodes": nodes_by_key.get(key, [])}
            if "repository(" in query:
                out["r0"] = {"pullRequests": {"nodes": recent or []}}
            return out

        return fake

    def test_behind_when_pr_merged_after_tracker_day(self):
        node = {
            "number": 9,
            "title": "PRJ-101: synthetic change",
            "state": "MERGED",
            "url": "https://github.com/x/y/pull/9",
            "createdAt": "2026-10-16T13:00:00Z",
            "mergedAt": "2026-10-18T15:00:00Z",
            "repository": {"name": "prod"},
        }
        self.m._gh = self._fake_gh({"PRJ-101": [node]})
        spec = [("synthetic", self._cut(), ("PRJ-101", "PRJ-102"), ("acme/infra",))]
        self.m._refresh_fresh(spec, tuple(spec))
        f = self.m.items()["projects"][0]["freshness"]
        self.assertTrue(f["behind"])
        self.assertEqual(f["state"], "ok")
        self.assertEqual(f["events"][0]["kind"], "merged")
        self.assertEqual(f["events"][0]["ref"], "PR prod #9")

    def test_same_day_and_wrong_key_are_not_behind(self):
        same_day = {
            "number": 10,
            "title": "PRJ-101: landed the same day",
            "createdAt": "2026-10-16T13:00:00Z",
            "mergedAt": "2026-10-16T18:00:00Z",
        }
        # The search matched loosely, but the title names another ticket (PRJ-199).
        other = {
            "number": 11,
            "title": "PRJ-199 other",
            "createdAt": "2026-10-19T13:00:00Z",
            "mergedAt": None,
        }
        self.m._gh = self._fake_gh({"PRJ-101": [same_day, other]})
        spec = [("synthetic", self._cut(), ("PRJ-101", "PRJ-102"), ("acme/infra",))]
        self.m._refresh_fresh(spec, tuple(spec))
        f = self.m.items()["projects"][0]["freshness"]
        self.assertFalse(f["behind"])
        self.assertEqual(f["state"], "ok")

    def test_same_day_work_after_the_tracker_was_written_is_behind(self):
        # tracker written 16:30 local, PR merged 17:07 local the same day.
        later = {
            "number": 404,
            "title": "fix(app): later the same day",
            "headRefName": "PRJ-101-app-later",
            "createdAt": "2026-10-16T20:50:00Z",
            "mergedAt": "2026-10-16T21:07:00Z",
            "repository": {"name": "prod"},
        }
        earlier = dict(
            later,
            number=403,
            headRefName="PRJ-101-before",
            mergedAt="2026-10-16T20:00:00Z",
            createdAt="2026-10-16T19:00:00Z",
        )
        within_grace = dict(
            later,
            number=405,
            headRefName="PRJ-101-grace",
            mergedAt="2026-10-16T20:35:00Z",
            createdAt="2026-10-16T20:00:00Z",
        )
        self.m._gh = self._fake_gh({}, recent=[later, earlier, within_grace])
        spec = [("synthetic", "2026-10-16T20:30:00Z", ("PRJ-101",), ("acme/infra",))]
        self.m._refresh_fresh(spec, tuple(spec))
        ev = self.m._fresh["results"]["synthetic"]
        self.assertEqual([e["ref"] for e in ev], ["PR prod #404"])

    def test_cutoff_is_mtime_capped_at_the_claimed_day(self):
        import datetime as dt

        noon = dt.datetime(2026, 10, 16, 12, 0).astimezone().timestamp()
        self.assertEqual(
            self.m._written_cutoff("2026-10-16", noon),
            dt.datetime.fromtimestamp(noon, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        later = dt.datetime(2026, 10, 19, 9, 0).astimezone().timestamp()
        end = dt.datetime(2026, 10, 16, 23, 59, 59).astimezone().astimezone(dt.timezone.utc)
        self.assertEqual(
            self.m._written_cutoff("2026-10-16", later), end.strftime("%Y-%m-%dT%H:%M:%SZ")
        )

    def test_ticket_status_change_counts(self):
        self.m._gh = self._fake_gh({})
        with self.m._jira_lock:
            self.m._jira["refs"] = {
                "PRJ-102": {
                    "state": "Done",
                    "done": True,
                    "status_changed": "2026-10-17T10:00:00.000-0400",
                }
            }
        spec = [("synthetic", self._cut(), ("PRJ-101", "PRJ-102"), ("acme/infra",))]
        self.m._refresh_fresh(spec, tuple(spec))
        f = self.m.items()["projects"][0]["freshness"]
        self.assertTrue(f["behind"])
        self.assertEqual(f["events"][0]["ref"], "PRJ-102")
        self.assertIn("Done", f["events"][0]["title"])

    # core-rule: scripting-python.1.9
    def test_failed_read_is_error_never_fresh(self):
        def boom(query):
            raise RuntimeError("gh rc=1 synthetic outage")

        self.m._gh = boom
        spec = [("synthetic", self._cut(), ("PRJ-101", "PRJ-102"), ("acme/infra",))]
        self.m._refresh_fresh(spec, tuple(spec))
        f = self.m.items()["projects"][0]["freshness"]
        self.assertEqual(f["state"], "error")
        self.assertFalse(f["behind"])
        self.assertTrue(f["errors"])

    def test_editing_the_tracker_date_clears_until_rechecked(self):
        node = {
            "number": 9,
            "title": "PRJ-101: x",
            "createdAt": "2026-10-16T13:00:00Z",
            "mergedAt": "2026-10-18T15:00:00Z",
        }
        self.m._gh = self._fake_gh({"PRJ-101": [node]})
        spec = [("synthetic", self._cut(), ("PRJ-101", "PRJ-102"), ("acme/infra",))]
        self.m._refresh_fresh(spec, tuple(spec))
        self.write(
            "projects/synthetic/tracker.md",
            TRACKER.replace("updated: 2026-10-16", "updated: 2026-10-19"),
        )
        f = self.m.items()["projects"][0]["freshness"]
        self.assertEqual(f["state"], "loading")
        self.assertFalse(f["behind"])

    def test_branch_name_counts_when_title_has_no_key(self):
        branch_only = {
            "number": 401,
            "title": "fix(app): no ticket key in this title",
            "headRefName": "PRJ-101-app-validate-strictmode",
            "createdAt": "2026-10-17T13:00:00Z",
            "mergedAt": "2026-10-19T17:00:00Z",
            "repository": {"name": "prod"},
        }
        # PRJ-1019-... must not count for PRJ-101, and a key mid-branch must not count either.
        decoys = [
            dict(branch_only, number=402, headRefName="PRJ-1019-other"),
            dict(branch_only, number=403, headRefName="fix-PRJ-101-later"),
        ]
        self.m._gh = self._fake_gh({}, recent=[branch_only, *decoys])
        spec = [("synthetic", self._cut(), ("PRJ-101",), ("acme/infra",))]
        self.m._refresh_fresh(spec, tuple(spec))
        ev = self.m._fresh["results"]["synthetic"]
        self.assertEqual([e["ref"] for e in ev], ["PR prod #401"])
        self.assertEqual(ev[0]["kind"], "merged")

    def test_pr_found_by_title_and_branch_is_listed_once(self):
        node = {
            "number": 9,
            "title": "PRJ-101: both",
            "headRefName": "PRJ-101-both",
            "createdAt": "2026-10-17T13:00:00Z",
            "mergedAt": None,
            "repository": {"name": "prod"},
        }
        self.m._gh = self._fake_gh({"PRJ-101": [node]}, recent=[node])
        spec = [("synthetic", self._cut(), ("PRJ-101",), ("acme/infra",))]
        self.m._refresh_fresh(spec, tuple(spec))
        ev = self.m._fresh["results"]["synthetic"]
        self.assertEqual([(e["ref"], e["kind"]) for e in ev], [("PR prod #9", "opened")])

    def test_local_day_parses_both_stamp_shapes(self):
        self.assertEqual(len(self.m._local_day("2026-10-18T15:00:00Z")), 10)
        self.assertEqual(len(self.m._local_day("2026-10-17T10:00:00.000-0400")), 10)
        self.assertEqual(self.m._local_day("garbage"), "")
        self.assertEqual(self.m._local_day(""), "")

    def _pr(self, num, branch, title, days_ago=1):
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - days_ago * 86400))
        return {
            "number": num,
            "title": title,
            "headRefName": branch,
            "state": "MERGED",
            "url": f"https://github.com/x/y/pull/{num}",
            "createdAt": stamp,
            "mergedAt": stamp,
            "repository": {"name": "prod"},
        }

    def test_untracked_key_with_three_recent_prs_is_listed(self):
        # PRJ-103 has 3 recent PRs and no tracker, PRJ-101 is named by the tracker,
        # PRJ-104 has only 2, PRJ-105 is old. Only PRJ-103 lists, once per PR.
        nodes = [
            self._pr(1, "PRJ-103-a", "feat: one"),
            self._pr(2, "PRJ-103-b", "PRJ-103: two"),
            self._pr(3, "main-fix", "PRJ-103 three"),
            self._pr(4, "PRJ-101-x", "x"),
            self._pr(5, "PRJ-101-y", "y"),
            self._pr(6, "PRJ-101-z", "z"),
            self._pr(7, "PRJ-104-a", "a"),
            self._pr(8, "PRJ-104-b", "b"),
            self._pr(9, "PRJ-105-a", "a", days_ago=20),
            self._pr(10, "PRJ-105-b", "b", days_ago=20),
            self._pr(11, "PRJ-105-c", "c", days_ago=20),
        ]
        self.m._gh = lambda q: {
            "r0": {"pullRequests": {"nodes": nodes}},
            "r1": {"pullRequests": {"nodes": []}},
        }
        self.m._refresh_untracked()
        u = self.m.items()["untracked"]
        self.assertEqual(u["state"], "ok")
        self.assertEqual([r["key"] for r in u["rows"]], ["PRJ-103"])
        self.assertEqual(len(u["rows"][0]["prs"]), 3)

    def test_create_tracker_then_key_stops_listing(self):
        nodes = [self._pr(n, f"PRJ-103-{n}", "t") for n in (1, 2, 3)]
        self.m._gh = lambda q: {
            "r0": {"pullRequests": {"nodes": nodes}},
            "r1": {"pullRequests": {"nodes": []}},
        }
        self.m._refresh_untracked()
        dry = self.m.create_tracker("PRJ-103", "new-build", "New build", what_if=True)
        self.assertFalse((self.root / "projects/new-build").exists())
        self.assertIn("tickets: PRJ-103", dry["text"])
        res = self.m.create_tracker("PRJ-103", "new-build", "New build")
        self.assertTrue(res["created"])
        self.assertEqual(self.m.items()["untracked"]["rows"], [])
        with self.assertRaises(self.m.Conflict):
            self.m.create_tracker("PRJ-103", "new-build", "Again")
        with self.assertRaises(ValueError):
            self.m.create_tracker("PRJ-103", "../escape", "x")

    def test_closed_ticket_with_only_merged_prs_is_not_listed(self):
        nodes = [self._pr(n, f"PRJ-103-{n}", "t") for n in (1, 2, 3)]
        self.m._gh = lambda q: {
            "r0": {"pullRequests": {"nodes": nodes}},
            "r1": {"pullRequests": {"nodes": []}},
        }
        self.m._refresh_untracked()
        self.m._jira.update(refs={"PRJ-103": {"state": "Closed", "done": True}})
        self.assertEqual(self.m.items()["untracked"]["rows"], [])
        nodes[0]["state"] = "OPEN"
        self.m._refresh_untracked()
        self.assertEqual([r["key"] for r in self.m.items()["untracked"]["rows"]], ["PRJ-103"])

    def test_dismissed_key_stops_listing(self):
        nodes = [self._pr(n, f"PRJ-103-{n}", "t") for n in (1, 2, 3)]
        self.m._gh = lambda q: {
            "r0": {"pullRequests": {"nodes": nodes}},
            "r1": {"pullRequests": {"nodes": []}},
        }
        self.m._refresh_untracked()
        self.assertEqual(len(self.m.items()["untracked"]["rows"]), 1)
        self.m.dismiss_untracked("PRJ-103")
        self.assertEqual(self.m.items()["untracked"]["rows"], [])

    def test_nothing_configured_is_the_null_default(self):
        os.environ["PLANS_CONFIG"] = str(Path(self.tmp.name) / "absent.json")
        os.environ["OPSCENTER_TRACKER_PARAMS"] = str(Path(self.tmp.name) / "absent-params.json")
        try:
            self.assertEqual(
                (self.m._browse(), self.m._default_repo(), self.m._untracked_repos()), ("", "", ())
            )
            self.assertEqual(self.m._tickets("ABC-12 and xy-5 and QRS-777"), ["ABC-12", "QRS-777"])
            self.assertEqual(self.m.items()["projects"][0]["tracker"]["repos"], [])
            self.m._refresh_untracked()
        finally:
            os.environ.pop("OPSCENTER_TRACKER_PARAMS", None)

    def test_a_configured_project_limits_the_keys_and_a_bad_key_is_refused(self):
        self.assertEqual(self.m._tickets("PRJ-12 and ABC-34"), ["PRJ-12"])
        with self.assertRaises(ValueError):
            self.m.create_tracker("ABC-34", "x", "x")
        with self.assertRaises(ValueError):
            self.m.dismiss_untracked("nonsense")


if __name__ == "__main__":
    unittest.main()
