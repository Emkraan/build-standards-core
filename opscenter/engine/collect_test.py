"""The collector and the analysis bundle: every adapter, the config, the plug-ins, the report and the bundle."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

NOW = "2099-01-02T12:00:00Z"
CUT = "2098-12-30T12:00:00Z"


class Scratch(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="collect-test-"))
        self.state = self.d / "state"
        (self.state / "dashboard").mkdir(parents=True)
        (self.d / "agent" / "feeds").mkdir(parents=True)
        self._env = dict(os.environ)
        self._mods = {m: sys.modules.get(m) for m in ("collect", "analysis_bundle", "board_build")}
        os.environ.update(
            OPSCENTER_ROOT=str(self.d),
            OPSCENTER_STATE_DIR=str(self.state),
            OPSCENTER_AGENT_HOME=str(self.d / "agent"),
            OPSCENTER_COLLECT_CONFIG=str(self.d / "collector.json"),
        )
        for k in (
            "OPSCENTER_PEOPLE",
            "OPSCENTER_BOARD_SOURCES",
            "OPSCENTER_REF_STATUS",
            "OPSCENTER_TEAM_AWAY",
        ):
            os.environ.pop(k, None)
        # The routing module is shared by every test in the process: point its file at this scratch tree and put
        # it back afterwards (a child process reads the path from the environment).
        import routing

        self.R = routing
        self._rules = (routing.RULES_PATH, routing.LOCK_PATH)
        routing.RULES_PATH = self.state / "dashboard" / "ac-routing.json"
        routing.LOCK_PATH = routing.RULES_PATH.parent / ".ac-routing.lock"
        os.environ["AC_ROUTING_PATH"] = str(routing.RULES_PATH)
        shutil.copy(HERE / "fixtures" / "routing-seed.json", routing.RULES_PATH)
        for m in self._mods:
            sys.modules.pop(m, None)
        import collect

        self.C = collect

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

    def cfg(self, **kw):
        base = {"owner_name": "Owen Owner", "tracker_base_url": "https://tracker.example/browse/"}
        base.update(kw)
        (self.d / "collector.json").write_text(json.dumps(base))
        return self.C.reload_config()

    def write(self, rel, data):
        p = self.d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data if isinstance(data, str) else json.dumps(data))
        return p


class Config(Scratch):
    def test_defaults_name_no_estate(self):
        c = self.C.reload_config()
        self.assertEqual(c["owner_name"], "the owner")
        self.assertEqual(c["chat_feeds"], [])
        self.assertTrue(str(c["mail_feed"]).endswith("agent/feeds/mail.json"))

    def test_the_file_sets_owner_feeds_and_refs(self):
        c = self.cfg(
            chat_feeds=[
                {"prefix": "chat", "label": "Chat", "path": "/x/c.json", "team_posts": True},
                {"prefix": ""},
            ],
            ref_regex=r"\bTKT-\d+\b",
            ask_days=7,
        )
        self.assertEqual([f["prefix"] for f in c["chat_feeds"]], ["chat"])
        self.assertEqual(c["ask_days"], 7)
        self.assertEqual(self.C._refs("see TKT-12 and ABC-9"), ["TKT-12"])

    def test_a_broken_config_file_falls_back_to_defaults(self):
        self.write("collector.json", "{not json")
        self.assertEqual(self.C.reload_config()["owner_name"], "the owner")


class Adapters(Scratch):
    def test_mail_direct_and_other(self):
        self.cfg()
        self.write(
            "agent/feeds/mail.json",
            {
                "items": [
                    {
                        "id": "m1",
                        "received": NOW,
                        "direct_ask": True,
                        "from_name": "Pat",
                        "subject": "Need ABC-123",
                        "body_text": "please",
                    },
                    {
                        "id": "m2",
                        "received": NOW,
                        "direct_to_me": False,
                        "from_name": "List",
                        "subject": "fyi",
                        "preview": "x",
                    },
                    {
                        "id": "m3",
                        "received": "2000-01-01T00:00:00Z",
                        "from_name": "Old",
                        "subject": "old",
                    },
                ]
            },
        )
        out = self.C.from_mail({"pat": "report"}, CUT)
        by = {c["cid"]: c for c in out}
        self.assertEqual(set(by), {"mail:m1", "mail:m2"})
        self.assertEqual(by["mail:m1"]["source"], "mail.direct")
        self.assertEqual(by["mail:m1"]["actor_role"], "report")
        self.assertEqual(by["mail:m1"]["refs"], ["ABC-123"])
        self.assertEqual(by["mail:m2"]["addressed"], "cc")

    def test_chat_feeds_use_the_configured_prefix_and_the_owner_name(self):
        feed = self.write(
            "feeds/chat.json",
            {
                "items": [
                    {
                        "id": "c:1",
                        "created": NOW,
                        "surface": "chat",
                        "chat_type": "oneOnOne",
                        "chat_id": "c:D",
                        "from_name": "Pat",
                        "text": "hi",
                    },
                    {
                        "id": "c:2",
                        "created": NOW,
                        "surface": "chat",
                        "chat_type": "oneOnOne",
                        "chat_id": "c:D",
                        "from_name": "Owen Owner",
                        "text": "ok",
                    },
                    {
                        "id": "c:3",
                        "created": NOW,
                        "surface": "channel",
                        "team": "T",
                        "channel": "ops",
                        "from_name": "Pat",
                        "text": "post",
                        "reply_to": None,
                    },
                ]
            },
        )
        self.cfg(
            chat_feeds=[{"prefix": "chat", "label": "Chat", "path": str(feed), "team_posts": True}]
        )
        out = self.C.from_chats({"pat": "report"}, CUT)
        by = {c["source"]: c for c in out}
        self.assertEqual(set(by), {"chat.1on1", "chat.channel"})
        self.assertTrue(
            by["chat.1on1"]["extra"]["replied_after_last"] is False
        )  # the owner's reply is older than Pat's last
        self.assertEqual(by["chat.channel"]["addressed"], "team")  # team_posts on, Pat is a report

    def test_tracker_state_and_doc_gap_adapters(self):
        self.write(
            "state/tracker-snapshot.json",
            {"last_check_utc": NOW, "tickets": {"ABC-5": {"status": "Open", "priority": "High"}}},
        )
        self.write("state/current-state.md", "# Escalations\n- something escalated\n")
        self.write(
            "state/dashboard/doc-gaps.json",
            {
                "generated_utc": NOW,
                "things": {
                    "t1": {
                        "name": "Thing",
                        "gaps": [
                            {"id": "g1", "severity": "high", "text": "no runbook"},
                            {"id": "g2", "severity": "low", "text": "x"},
                        ],
                    }
                },
            },
        )
        self.cfg()
        t = self.C.from_tracker()
        self.assertEqual(
            (t[0]["cid"], t[0]["source"], t[0]["owner"]),
            ("tracker:ABC-5", "tracker.assigned", "Owen Owner"),
        )
        self.assertEqual(t[0]["link"], "https://tracker.example/browse/ABC-5")
        d = self.C.from_doc_gaps()
        self.assertEqual([c["cid"] for c in d], ["doc:t1:g1"])
        self.assertIsInstance(self.C.from_state(), list)

    def test_a_missing_source_yields_nothing_and_a_failing_adapter_is_reported(self):
        self.cfg()
        res = self.C.collect()
        self.assertEqual(res["errors"], [])
        orig = self.C.ADAPTERS
        self.C.ADAPTERS = (("boom", lambda roles, cut: 1 / 0),) + orig
        try:
            res = self.C.collect()
        finally:
            self.C.ADAPTERS = orig
        self.assertTrue(any("boom adapter failed" in e for e in res["errors"]))


class Plugins(Scratch):
    def test_roster_plugin_classifies_people_and_a_missing_one_is_reported(self):
        self.cfg()
        plug = self.write(
            "roster_plugin.py",
            "def roster():\n    return [{'name': 'Pat Report', 'group': 'report'}]\n",
        )
        os.environ["OPSCENTER_PEOPLE"] = str(plug)
        roles, errors = self.C.people_roles({"people": {"leader": ["Lee Lead"]}})
        self.assertEqual(
            (roles["pat report"], roles["lee lead"], roles["owen owner"], errors),
            ("report", "leader", "me", []),
        )
        os.environ["OPSCENTER_PEOPLE"] = str(self.d / "nope.py")
        roles, errors = self.C.people_roles({})
        self.assertTrue(errors and errors[0].startswith("roster unavailable"))

    def test_board_sources_feed_the_on_board_list(self):
        self.cfg()
        plug = self.write(
            "src.py",
            "def action_items():\n    return [{'key': 'file-1', 'title': 't', 'refs': []}]\n",
        )
        os.environ["OPSCENTER_BOARD_SOURCES"] = json.dumps([str(plug), str(self.d / "missing.py")])
        keys = [i["key"] for i in self.C.on_board_items()]
        self.assertIn("file-1", keys)

    def test_ratchet_raises_and_closes_one_item(self):
        self.cfg()
        self.C.ratchet(["new.source"])
        am = self.C.automation()
        items = am._load()["items"]
        self.assertIn("ac-unrouted-sources", items)
        self.C.ratchet([])
        self.assertTrue(am._load()["items"]["ac-unrouted-sources"].get("closed"))


class Bundle(Scratch):
    def test_report_and_the_bundle_shape(self):
        self.cfg()
        self.write(
            "agent/feeds/mail.json",
            {
                "items": [
                    {
                        "id": "m1",
                        "received": "2099-01-01T00:00:00Z",
                        "direct_ask": True,
                        "from_name": "Pat",
                        "subject": "ask",
                    }
                ]
            },
        )
        p = subprocess.run(
            [sys.executable, str(HERE / "analysis_bundle.py")],
            capture_output=True,
            text=True,
            env=dict(os.environ),
            timeout=120,
        )
        self.assertEqual(p.returncode, 0, p.stderr[-800:])
        b = json.loads(p.stdout)
        self.assertEqual([c["cid"] for c in b["candidates_must"]], ["mail:m1"])
        for k in (
            "candidates_context",
            "routed_away",
            "on_board",
            "people",
            "handled",
            "previous_items",
            "ref_status",
            "now_et",
        ):
            self.assertIn(k, b)
        self.assertEqual(b["ref_status"], {"finished": {}, "errors": []})
        rep = json.loads((self.state / "dashboard" / "ac-routing-report.json").read_text())
        self.assertEqual(rep["considered"], 1)

    def test_a_broken_routing_file_fails_the_build(self):
        self.cfg()
        (self.state / "dashboard" / "ac-routing.json").write_text("{not json")
        p = subprocess.run(
            [sys.executable, str(HERE / "analysis_bundle.py")],
            capture_output=True,
            text=True,
            env=dict(os.environ),
            timeout=120,
        )
        self.assertNotEqual(p.returncode, 0)


if __name__ == "__main__":
    unittest.main()
