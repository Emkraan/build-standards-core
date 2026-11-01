"""
problems_test.py
Purpose: The single problem list: every item has a tone (needs_me, worth_a_look, healthy), at most four detail lines and a place
         (hub, section, item) that the problem map can rename; the counts by section and item count only items that are not
         healthy; a run in flight is a running flag, never a problem; a source that is missing contributes nothing and one that
         raises shows as a needs_me item; /api/badges carries the same list.
Run:     python3 problems_test.py
"""

import importlib
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ENV = ("OPSCENTER_PROBLEM_MAP", "OPSCENTER_STATE_DIR", "OPSCENTER_ROOT")
_saved = {}
TMP = None
pb = None


def setUpModule():
    global TMP, pb
    TMP = tempfile.TemporaryDirectory()
    for k in ENV:
        _saved[k] = os.environ.get(k)
    os.environ["OPSCENTER_ROOT"] = TMP.name
    os.environ["OPSCENTER_STATE_DIR"] = str(Path(TMP.name) / "state")
    os.environ.pop("OPSCENTER_PROBLEM_MAP", None)
    import paths
    import problems

    importlib.reload(paths)
    pb = importlib.reload(problems)


def tearDownModule():
    for k, v in _saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    TMP.cleanup()
    import paths
    import problems

    importlib.reload(paths)
    importlib.reload(problems)


def fake_builds(pipelines, failed):
    m = types.SimpleNamespace(
        PIPELINES=[1],
        swr=types.SimpleNamespace(peek=lambda k: {"pipelines": pipelines}),
        main_failure_items=lambda feed: failed,
    )
    return m


class Problems(unittest.TestCase):
    def setUp(self):
        self.mods = {}
        self._mod = pb._mod
        pb._mod = lambda name: self.mods.get(name)

    def tearDown(self):
        pb._mod = self._mod
        os.environ.pop("OPSCENTER_PROBLEM_MAP", None)

    def test_nothing_in_the_tree_is_an_empty_list(self):
        self.assertEqual(pb.collect()["items"], [])
        self.assertEqual(pb.collect()["counts"]["total"], 0)

    def test_tones_counts_and_detail_limit(self):
        self.mods["builds"] = fake_builds(
            [
                {
                    "key": "a",
                    "label": "Release app",
                    "product": "app",
                    "url": "u",
                    "state": {"current": 9},
                },
                {
                    "key": "b",
                    "label": "Deploy web",
                    "product": "web",
                    "url": "w",
                    "state": {"current": None},
                },
            ],
            [{"key": "a", "label": "Release app", "run": 4, "conclusion": "failure", "url": "r"}],
        )
        self.mods["infra"] = types.SimpleNamespace(
            badge_problems=lambda: {
                "areas": {"jobs": [f"job {i}: failing" for i in range(7)], "spend": [], "ci": []},
                "looks": {"ci": ["Runners offline: r1"]},
            }
        )
        self.mods["core_consumption"] = types.SimpleNamespace(
            badge=lambda: 2, get=lambda: {"state": "ok", "consumers": [1]}
        )
        out = pb.collect()
        by = {i["id"]: i for i in out["items"]}
        self.assertEqual(by["builds:app"]["tone"], "needs_me")
        self.assertTrue(by["builds:app"]["running"])
        self.assertEqual(
            (by["builds:web"]["tone"], by["builds:web"]["running"]), ("healthy", False)
        )
        self.assertEqual(
            (by["jobs"]["tone"], len(by["jobs"]["details"]), by["jobs"]["headline"]),
            ("needs_me", 4, "7 scheduled job problems need me"),
        )
        self.assertEqual(
            (by["ci"]["tone"], by["spend"]["tone"], by["core"]["tone"]),
            ("worth_a_look", "healthy", "needs_me"),
        )
        self.assertEqual(by["core"]["headline"], "2 approvals waiting on me")
        c = out["counts"]
        self.assertEqual(
            (c["needs_me"], c["worth_a_look"], c["healthy"], c["running"], c["total"]),
            (3, 1, 2, 1, 6),
        )
        # the unit is one per problem line: 7 failing jobs read 7, not 1, and the tabs add up to the badge
        self.assertEqual(c["by_section"], {"builds": 1, "automation": 8, "cost": 2})
        self.assertEqual(c["by_item"]["automation/jobs"], 7)
        self.assertEqual(c["lines"], 11)
        self.assertEqual(c["lines"], sum(c["by_section"].values()))
        self.assertEqual((by["jobs"]["count"], len(by["jobs"]["details"])), (7, 4))
        self.assertNotIn("builds/web", c["by_item"])
        self.assertEqual(
            [i["tone"] for i in out["items"]],
            sorted(
                (i["tone"] for i in out["items"]),
                key=lambda t: ["needs_me", "worth_a_look", "healthy"].index(t),
            ),
        )

    def test_an_unconfigured_infrastructure_page_has_no_cards(self):
        self.mods["infra"] = types.SimpleNamespace(
            badge_problems=lambda: {
                "count": 0,
                "areas": {"jobs": [], "spend": [], "ci": []},
                "looks": {"ci": []},
            },
            configured=lambda: False,
        )
        self.assertEqual(pb.collect()["items"], [])
        self.mods["infra"].configured = lambda: True
        self.assertEqual({i["id"] for i in pb.collect()["items"]}, {"jobs", "ci", "spend"})

    def test_a_product_with_two_pipelines_is_one_item_that_needs_me_while_any_failed(self):
        self.mods["builds"] = fake_builds(
            [
                {"key": "a", "label": "Build", "product": "app", "state": {}},
                {"key": "b", "label": "Release", "product": "app", "state": {}},
            ],
            [{"key": "b", "label": "Release", "run": 7, "conclusion": "timed_out", "url": "r"}],
        )
        items = pb.collect()["items"]
        self.assertEqual([(i["id"], i["tone"]) for i in items], [("builds:app", "needs_me")])

    def test_the_problem_map_renames_the_hub_section_and_item(self):
        p = Path(TMP.name) / "map.json"
        p.write_text(
            json.dumps(
                {"hub": "platform", "jobs": {"section": "ops", "item": "crons", "label": "Crons"}}
            )
        )
        os.environ["OPSCENTER_PROBLEM_MAP"] = str(p)
        self.mods["infra"] = types.SimpleNamespace(
            badge_problems=lambda: {"areas": {"jobs": ["x"]}, "looks": {}}
        )
        by = {i["id"]: i for i in pb.collect()["items"]}
        self.assertEqual(
            (by["jobs"]["hub"], by["jobs"]["section"], by["jobs"]["item"], by["jobs"]["label"]),
            ("platform", "ops", "crons", "Crons"),
        )
        self.assertEqual(by["ci"]["hub"], "platform")

    def test_a_source_that_raises_is_a_needs_me_item_never_clear(self):
        def boom():
            raise RuntimeError("down")

        self.mods["infra"] = types.SimpleNamespace(badge_problems=boom)
        by = {i["id"]: i for i in pb.collect()["items"]}
        self.assertEqual((by["ci"]["tone"], by["ci"]["details"]), ("needs_me", ["down"]))


class Provider(unittest.TestCase):
    """OPSCENTER_PROBLEMS_PROVIDER: live headlines, running on any item and a consumer's own problem sources."""

    PROVIDER = """
class P:
    def headlines(self):
        return {"ci": "2 online, 1 queued, last backup 3 h ago", "builds:app": "v1.2.3 shipped"}
    def running(self):
        return ["ci"]
    def needs_me(self):
        return [
            {"key": "builds:app", "details": ["Deploy to dev refused, waiting on a click"]},
            {"key": "runs", "section": "automation", "item": "runs", "label": "Runs",
             "details": ["Run 9 waits on an approval"]},
        ]
    def worth_a_look(self):
        return [{"key": "spend", "details": ["Spend at 78 percent of the limit", "Account b could not be read"]}]
"""

    def setUp(self):
        self.mods = {}
        self._mod = pb._mod
        pb._mod = lambda name: self.mods.get(name)
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        pb._mod = self._mod
        os.environ.pop("OPSCENTER_PROBLEMS_PROVIDER", None)
        pb._provider.update(spec=None, obj=None)
        self.tmp.cleanup()

    def use(self, src):
        f = Path(self.tmp.name) / "prov.py"
        f.write_text(src, encoding="utf-8")
        os.environ["OPSCENTER_PROBLEMS_PROVIDER"] = f"{f}:P"
        pb._provider.update(spec=None, obj=None)

    def world(self):
        self.mods["builds"] = fake_builds(
            [
                {
                    "key": "a",
                    "label": "Release app",
                    "product": "app",
                    "url": "u",
                    "state": {"current": None},
                }
            ],
            [],
        )
        self.mods["infra"] = types.SimpleNamespace(
            badge_problems=lambda: {
                "areas": {"jobs": [], "spend": [], "ci": []},
                "looks": {"ci": []},
            }
        )

    def test_null_default_changes_nothing(self):
        self.world()
        out = pb.collect()
        self.assertEqual({i["id"]: i["headline"] for i in out["items"]}["ci"], "Healthy")
        self.assertEqual(out["counts"]["lines"], 0)

    def test_headlines_running_and_sources(self):
        self.world()
        self.use(self.PROVIDER)
        out = pb.collect()
        by = {i["id"]: i for i in out["items"]}
        self.assertEqual(by["ci"]["headline"], "2 online, 1 queued, last backup 3 h ago")
        self.assertEqual((by["ci"]["running"], by["ci"]["tone"]), (True, "healthy"))
        # a source on an existing item raises its tone and adds its lines
        self.assertEqual((by["builds:app"]["tone"], by["builds:app"]["count"]), ("needs_me", 1))
        self.assertEqual(by["builds:app"]["headline"], "v1.2.3 shipped")
        # a new key is a new item; worth a look counts one per line and stays amber
        self.assertEqual((by["runs"]["tone"], by["runs"]["section"]), ("needs_me", "automation"))
        self.assertEqual((by["spend"]["tone"], by["spend"]["count"]), ("worth_a_look", 2))
        c = out["counts"]
        self.assertEqual(c["lines"], 1 + 1 + 2)
        self.assertEqual(c["by_item"]["automation/runs"], 1)
        self.assertEqual(c["running"], 1)

    def test_a_source_never_lowers_a_tone(self):
        self.world()
        self.mods["infra"] = types.SimpleNamespace(
            badge_problems=lambda: {
                "areas": {"jobs": [], "spend": ["Model fallback active"], "ci": []},
                "looks": {"ci": []},
            }
        )
        self.use(self.PROVIDER)
        by = {i["id"]: i for i in pb.collect()["items"]}
        self.assertEqual((by["spend"]["tone"], by["spend"]["count"]), ("needs_me", 3))

    def test_a_broken_provider_is_one_needs_me_item(self):
        self.world()
        for src in (
            "class P:\n    def needs_me(self):\n        raise RuntimeError('boom')\n",
            "this is not python",
        ):
            self.use(src)
            by = {i["id"]: i for i in pb.collect()["items"]}
            self.assertEqual(by["provider"]["tone"], "needs_me")
        os.environ["OPSCENTER_PROBLEMS_PROVIDER"] = "nope"
        pb._provider.update(spec=None, obj=None)
        self.assertEqual(
            {i["id"]: i for i in pb.collect()["items"]}["provider"]["tone"], "needs_me"
        )


if __name__ == "__main__":
    unittest.main()
