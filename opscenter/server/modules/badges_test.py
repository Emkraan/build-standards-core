"""
badges_test.py
Purpose: The combined badges payload: nothing configured is the all-zero shape, the action board count drops handled and
         live-snoozed items, each section reads its module and degrades to its zero value when that module raises, and a
         failing infrastructure check shows as one problem.
Run:     python3 badges_test.py
"""

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ENV = ("OPSCENTER_STATE_DIR", "OPSCENTER_SERVED_BOARD", "OPSCENTER_ROOT")
_saved = {}
TMP = None
b = None


def setUpModule():
    global TMP, b
    TMP = tempfile.TemporaryDirectory()
    for k in ENV:
        _saved[k] = os.environ.get(k)
    os.environ["OPSCENTER_ROOT"] = TMP.name
    os.environ["OPSCENTER_STATE_DIR"] = str(Path(TMP.name) / "state")
    os.environ.pop("OPSCENTER_SERVED_BOARD", None)
    import importlib

    import badges
    import paths
    import stores

    for m in (paths, stores, badges):
        importlib.reload(m)
    b = badges


def tearDownModule():
    for k, v in _saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    TMP.cleanup()
    import importlib

    import badges
    import paths
    import stores

    for m in (paths, stores, badges):
        importlib.reload(m)


def stub(name, **fns):
    m = types.ModuleType(name)
    for k, v in fns.items():
        setattr(m, k, v)
    return m


class Badges(unittest.TestCase):
    def setUp(self):
        self.state = Path(os.environ["OPSCENTER_STATE_DIR"])
        self.saved_mods = {}
        (self.state / "public-data" / "action-center.json").unlink(missing_ok=True)
        (self.state / "dashboard" / "action-handled.json").unlink(missing_ok=True)

    def tearDown(self):
        for name, old in self.saved_mods.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old

    def put(self, name, **fns):
        self.saved_mods[name] = sys.modules.get(name)
        sys.modules[name] = stub(name, **fns)

    def board(self, items):
        d = self.state / "public-data"
        d.mkdir(parents=True, exist_ok=True)
        (d / "action-center.json").write_text(json.dumps({"items": items}))

    def test_nothing_configured_is_the_zero_shape_with_stable_keys(self):
        got = b.get()
        self.assertEqual(
            set(got),
            {
                "builds",
                "core",
                "action_open",
                "debt",
                "knowledge",
                "knowledge_pending",
                "knowledge_docs",
                "links",
                "infra",
                "alerts",
            },
        )
        self.assertEqual((got["action_open"], got["knowledge"], got["infra"]["count"]), ([], 0, 0))

    def test_handled_and_snoozed_items_are_not_open(self):
        self.board([{"fp": "a"}, {"fp": "b"}, {"fp": "c"}, {"fp": "d"}])
        d = self.state / "dashboard"
        d.mkdir(parents=True, exist_ok=True)
        (d / "action-handled.json").write_text(
            json.dumps(
                {
                    "handled": {
                        "a": {"act": "done"},
                        "b": {"act": "snoozed", "until": "2999-01-01T00:00:00Z"},
                        "c": {"act": "snoozed", "until": "2000-01-01T00:00:00Z"},
                    }
                }
            )
        )
        self.assertEqual(b.get()["action_open"], ["c", "d"])

    def test_each_section_reads_its_module(self):
        self.put("builds", badge=lambda: {"running": 2, "waiting": 1})
        self.put("core_consumption", badge=lambda: 3)
        self.put("alerts", badge=lambda: 4)
        self.put("doc_coverage", badge=lambda: 5)
        self.put("curation", public=lambda: {"proposals": [{"fp": "p1"}, {"fp": "p2"}, {}]})
        self.put("eng_backlog", items=lambda: {"counts": {"decide_imp": 6}})
        self.put("link_health", dead_count=lambda *a: 7)
        self.put("infra", badge_problems=lambda: {"count": 1, "items": ["x"]})
        got = b.get()
        self.assertEqual(
            (got["builds"], got["core"], got["alerts"], got["debt"], got["links"]),
            ({"running": 2, "waiting": 1}, 3, 4, 6, 7),
        )
        self.assertEqual(
            (got["knowledge"], got["knowledge_docs"], got["knowledge_pending"]),
            (7, 5, ["p1", "p2"]),
        )
        self.assertEqual(got["infra"], {"count": 1, "items": ["x"]})

    def test_a_failing_module_is_its_zero_value_and_a_failing_infra_check_is_a_problem(self):
        def boom(*a):
            raise RuntimeError("down")

        self.put("builds", badge=boom)
        self.put("alerts", badge=boom)
        self.put("eng_backlog", items=boom)
        self.put("infra", badge_problems=boom)
        got = b.get()
        self.assertEqual(
            (got["builds"], got["alerts"], got["debt"]), ({"running": 0, "waiting": 0}, 0, 0)
        )
        self.assertEqual(got["infra"]["count"], 1)
        self.assertIn("down", got["infra"]["items"][0])

    def test_an_unreadable_board_is_empty(self):
        d = self.state / "public-data"
        d.mkdir(parents=True, exist_ok=True)
        (d / "action-center.json").write_text("{nope")
        self.assertEqual(b.get()["action_open"], [])


if __name__ == "__main__":
    unittest.main()
