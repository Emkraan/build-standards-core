"""The board composer: fingerprints, freeze status, monitors, the contract check, plug-in items, the team away
strip and the data files it writes."""

import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def item(**kw):
    base = {
        "key": "k1",
        "priority": "high",
        "title": "Do the thing",
        "why": "because",
        "action": "act",
        "owner": "",
        "refs": [],
        "sources": [],
        "cids": [],
    }
    base.update(kw)
    return base


class Board(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="board-build-test-"))
        self.state = self.d / "state"
        (self.state / "dashboard").mkdir(parents=True)
        self._env = dict(os.environ)
        self._mods = {m: sys.modules.get(m) for m in ("collect", "board_build", "contract")}
        os.environ.update(
            OPSCENTER_ROOT=str(self.d),
            OPSCENTER_STATE_DIR=str(self.state),
            OPSCENTER_AGENT_HOME=str(self.d / "agent"),
            OPSCENTER_COLLECT_CONFIG=str(self.d / "none.json"),
            OPSCENTER_BUNDLE_OUT=str(self.d / "out"),
            AC_GATE_STATE_DIR=str(self.d / "gates"),
            AC_WAKE_PATH=str(self.d / "gates" / "wake.json"),
        )
        for k in (
            "OPSCENTER_PEOPLE",
            "OPSCENTER_BOARD_SOURCES",
            "OPSCENTER_REF_STATUS",
            "OPSCENTER_TEAM_AWAY",
            "OPSCENTER_MONITORS",
            "OPSCENTER_BUNDLE_DATASETS",
        ):
            os.environ.pop(k, None)
        import routing

        self.R = routing
        self._rules = (routing.RULES_PATH, routing.LOCK_PATH)
        routing.RULES_PATH = self.state / "dashboard" / "ac-routing.json"
        routing.LOCK_PATH = routing.RULES_PATH.parent / ".ac-routing.lock"
        shutil.copy(HERE / "fixtures" / "routing-seed.json", routing.RULES_PATH)
        for m in self._mods:
            sys.modules.pop(m, None)
        import board_build

        self.B = board_build

    def tearDown(self):
        self.R.RULES_PATH, self.R.LOCK_PATH = self._rules
        for m, v in self._mods.items():
            if v is None:
                sys.modules.pop(m, None)
            else:
                sys.modules[m] = v
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self.d, ignore_errors=True)

    def write_analysis(self, items):
        p = self.state / "dashboard" / "action-center.json"
        p.write_text(
            json.dumps(
                {
                    "generated_utc": "2099-01-01T00:00:00Z",
                    "headline": "h",
                    "items": items,
                    "dropped": [],
                }
            )
        )
        return p

    def test_fingerprint_is_stable_across_rewording_and_counters(self):
        fp = self.B.ac_fingerprint
        self.assertEqual(fp({"key": "Abc"}), fp({"key": " abc ", "title": "other"}))
        self.assertEqual(fp({"refs": ["x-1", "y-2"]}), fp({"refs": ["X-1"], "title": "changed"}))
        self.assertEqual(fp({"title": "Day 14 unshipped"}), fp({"title": "day 15 unshipped"}))
        self.assertTrue(fp({"title": "t"}).startswith("ac_"))

    def test_freeze_status_reads_the_file_zone(self):
        zone = ZoneInfo("Pacific/Auckland")
        now = dt.datetime.now(zone).replace(tzinfo=None)
        f = self.d / "freeze.json"
        f.write_text(
            json.dumps(
                {
                    "timezone": "Pacific/Auckland",
                    "synced": "s",
                    "windows": [
                        {
                            "name": "now",
                            "start": (now - dt.timedelta(hours=1)).isoformat(),
                            "end": (now + dt.timedelta(hours=1)).isoformat(),
                        },
                        {
                            "name": "later",
                            "start": (now + dt.timedelta(days=3)).isoformat(),
                            "end": (now + dt.timedelta(days=4)).isoformat(),
                        },
                        {"name": "bad"},
                    ],
                }
            )
        )
        got = self.B.freeze_status(f)
        self.assertEqual(
            (
                got["in_freeze"],
                got["current"]["name"],
                got["next"]["name"],
                got["next"]["days_out"],
            ),
            (True, "now", "later", 3),
        )
        self.assertEqual(got["synced"], "s")
        self.assertFalse(self.B.freeze_status(self.d / "missing.json")["in_freeze"])

    def test_monitor_health_reads_the_listed_files(self):
        m = self.d / "mon.json"
        m.write_text(json.dumps({"updated": "2099-01-01T00:00:00Z"}))
        os.environ["OPSCENTER_MONITORS"] = json.dumps(
            [{"name": "Mail", "path": str(m)}, {"name": "Gone", "path": str(self.d / "x.json")}]
        )
        got = self.B.monitor_health()
        self.assertEqual(got[0], {"name": "Mail", "updated": "2099-01-01T00:00:00Z"})
        self.assertIsNone(got[1]["updated"])

    def test_a_good_analysis_gets_fingerprints_the_contract_and_first_seen(self):
        p = self.write_analysis([item(key="freeze-gate", title="Freeze gate")])
        os.utime(p, (1, 1))  # old enough that the contract check does not wait on a mid-write file
        ac = self.B.load_action_center(p)
        self.assertEqual([i["key"] for i in ac["items"]], ["freeze-gate"])
        self.assertTrue(ac["items"][0]["fp"].startswith("ac_"))
        self.assertIn("contract", ac)
        self.assertEqual(ac["team_away"], {"people": []})
        seen = json.loads((self.state / "dashboard" / "ac-first-seen.json").read_text())[
            "first_seen"
        ]
        self.assertIn(ac["items"][0]["fp"], seen)

    def test_a_bad_analysis_is_rejected_and_the_last_good_file_stays(self):
        p = self.write_analysis([item(key="good")])
        os.utime(p, (1, 1))
        self.B.load_action_center(p)
        p.write_text(
            json.dumps(
                {"generated_utc": "x", "headline": "h", "items": [{"key": "oo-bad"}], "dropped": []}
            )
        )
        os.utime(p, (2, 2))
        ac = self.B.load_action_center(p)
        self.assertEqual(ac["contract"]["status"], "rejected")
        self.assertEqual(
            sorted(i["key"] for i in ac["items"]), ["auto-ac-analysis-rejected", "good"]
        )  # the alert is a board item
        items = json.loads((self.state / "dashboard" / "automation-actions.json").read_text())[
            "items"
        ]
        self.assertIn("ac-analysis-rejected", items)

    def test_plugin_items_merge_once_by_key_and_a_broken_one_is_skipped(self):
        good = self.d / "src.py"
        good.write_text(
            "def action_items():\n    return [{'key': 'file-1', 'title': 'F', 'refs': []}, {'key': 'k1', 'title': 'dup'}]\n"
        )
        bad = self.d / "bad.py"
        bad.write_text("def action_items():\n    raise ValueError('boom')\n")
        os.environ["OPSCENTER_BOARD_SOURCES"] = json.dumps([str(good), str(bad)])
        p = self.write_analysis([item(key="k1")])
        os.utime(p, (1, 1))
        ac = self.B.load_action_center(p)
        self.assertEqual(sorted(i["key"] for i in ac["items"]), ["file-1", "k1"])

    def test_team_away_and_ref_status_plugins(self):
        away = self.d / "away.py"
        away.write_text("def snapshot():\n    return {'people': [{'name': 'x'}]}\n")
        os.environ["OPSCENTER_TEAM_AWAY"] = str(away)
        p = self.write_analysis([item(key="k1")])
        os.utime(p, (1, 1))
        self.assertEqual(self.B.load_action_center(p)["team_away"], {"people": [{"name": "x"}]})
        broken = self.d / "away_bad.py"
        broken.write_text("def snapshot():\n    raise RuntimeError('no')\n")
        os.environ["OPSCENTER_TEAM_AWAY"] = str(broken)
        got = self.B.load_action_center(p)["team_away"]
        self.assertEqual(got["people"], [])
        self.assertIn("not loaded", got["error"])

    def test_main_writes_the_datasets_and_the_extra_ones(self):
        extra = self.d / "extra.json"
        extra.write_text(json.dumps({"hello": 1}))
        os.environ["OPSCENTER_BUNDLE_DATASETS"] = json.dumps({"extra.json": str(extra)})
        p = self.write_analysis([item(key="k1")])
        os.utime(p, (1, 1))
        self.assertEqual(self.B.main(), 0)
        out = self.d / "out"
        self.assertEqual(
            sorted(f.name for f in out.iterdir()),
            ["action-center.json", "extra.json", "freeze.json", "manifest.json", "monitors.json"],
        )
        self.assertEqual(json.loads((out / "extra.json").read_text()), {"hello": 1})
        self.assertIn("generated_et", json.loads((out / "manifest.json").read_text()))


if __name__ == "__main__":
    unittest.main()
