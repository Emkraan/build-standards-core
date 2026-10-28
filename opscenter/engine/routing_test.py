#!/usr/bin/env python3
"""Tests for the Action Center routing engine and collector. Synthetic data only.

Run: python3 state/dashboard/routing_test.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TMP = Path(tempfile.mkdtemp(prefix="ac-routing-test-", dir=os.environ.get("TMPDIR")))
shutil.copy(HERE / "fixtures/routing-seed.json", TMP / "ac-routing.json")
os.environ["AC_ROUTING_PATH"] = str(TMP / "ac-routing.json")
sys.path.insert(0, str(HERE))
import routing as R  # noqa: E402

SCRATCH_RULES = TMP / "ac-routing.json"


def setUpModule():
    # Another test module may have pointed the shared routing module elsewhere: point it back at this file.
    R.RULES_PATH = SCRATCH_RULES
    R.LOCK_PATH = SCRATCH_RULES.parent / ".ac-routing.lock"
    os.environ["AC_ROUTING_PATH"] = str(SCRATCH_RULES)


def cand(**kw):
    base = {
        "cid": "x:1",
        "source": "mail.other",
        "actor": "Someone",
        "actor_role": "other",
        "addressed": "none",
        "title": "t",
        "text": "",
    }
    base.update(kw)
    return base


class SeedParity(unittest.TestCase):
    """The seed rules must reproduce the filters they replaced in board_build.py and the prompt."""

    def setUp(self):
        self.data = R.load()

    def test_retired_system_item_routed_on_key_title_action(self):
        for f in ("key", "title", "action"):
            it = {"key": "k", "title": "x", "action": "y", f: "retired-system pagefile fix"}
            kept, away = R.filter_items([it], self.data)
            self.assertEqual(kept, [], f)
            self.assertEqual(away[0]["rule"], "seed-retired-system")

    def test_retired_system_in_passing_survives(self):
        it = {
            "key": "pagefile",
            "title": "Pagefile fix",
            "action": "Ship it",
            "why": "found while testing retired-system",
        }
        kept, _ = R.filter_items([it], self.data)
        self.assertEqual(len(kept), 1)

    def test_retired_system_rule_is_items_only(self):
        r = R.route(cand(title="retired-system weekly report"), self.data)
        self.assertNotEqual(r["rule"], "seed-retired-system")

    def test_doc_items_routed(self):
        kept, away = R.filter_items(
            [
                {"key": "doc-app-b", "title": "x"},
                {"key": "k", "title": "y", "sources": ["Documentation gap"]},
            ],
            self.data,
        )
        self.assertEqual(kept, [])
        self.assertEqual({a["route"] for a in away}, {"elsewhere"})

    def test_doc_gap_candidates_routed(self):
        self.assertEqual(
            R.route(cand(source="doc.gap", actor_role="automation"), self.data)["route"],
            "elsewhere",
        )

    def test_direct_sources_must_be_considered(self):
        for src in ("mail.direct", "chat.1on1", "chat.mention"):
            self.assertEqual(R.route(cand(source=src), self.data)["route"], "action_center", src)

    def test_ordinary_item_kept(self):
        kept, away = R.filter_items(
            [{"key": "freeze-gate", "title": "Freeze gate", "action": "Decide"}], self.data
        )
        self.assertEqual((len(kept), away), (1, []))


class Defaults(unittest.TestCase):
    def setUp(self):
        self.data = R.load()

    def test_fail_open_for_any_person_who_addresses_me(self):
        # A new source nobody wrote a rule for (a colleague's duplicate-docs report would be one).
        r = R.route(
            cand(source="brand.new", actor="Pat Example", actor_role="partner", addressed="direct"),
            self.data,
        )
        self.assertEqual((r["route"], r["rule"]), ("action_center", "default:person"))

    def test_team_channel_post_needs_no_rule(self):
        r = R.route(cand(source="chat.channel", actor_role="report", addressed="team"), self.data)
        self.assertEqual(r["route"], "action_center")

    def test_automation_and_me_are_context(self):
        self.assertEqual(
            R.route(cand(actor_role="automation", addressed="direct"), self.data)["route"],
            "analysis",
        )
        self.assertEqual(
            R.route(cand(actor_role="me", addressed="direct"), self.data)["route"], "analysis"
        )


class ClickRules(unittest.TestCase):
    def setUp(self):
        shutil.copy(HERE / "fixtures/routing-seed.json", TMP / "ac-routing.json")

    def test_click_rule_wins_and_is_idempotent(self):
        m = {"actor": "Pat Example"}
        r1 = R.add_rule(m, "elsewhere", where="Service Desk", reason="not mine", from_item="ac_1")
        r2 = R.add_rule(m, "elsewhere", where="Service Desk")
        self.assertFalse(r1["already"])
        self.assertTrue(r2["already"])
        data = R.load()
        self.assertEqual(data["rules"][0]["id"], r1["id"])
        self.assertEqual(sum(1 for r in data["rules"] if r["id"] == r1["id"]), 1)
        got = R.route(cand(source="chat.mention", actor="Pat Example", addressed="mention"), data)
        self.assertEqual((got["route"], got["rule"]), ("elsewhere", r1["id"]))

    def test_disable_restores_previous_route(self):
        r = R.add_rule({"actor": "Pat Example"}, "nowhere")
        R.set_disabled(r["id"], True)
        got = R.route(
            cand(source="chat.mention", actor="Pat Example", addressed="mention"), R.load()
        )
        self.assertEqual(got["route"], "action_center")

    def test_seed_rules_cannot_be_deleted(self):
        with self.assertRaises(R.RoutingError):
            R.delete_rule("seed-retired-system")

    def test_click_rule_delete(self):
        r = R.add_rule({"text": "quarantine"}, "nowhere")
        self.assertTrue(R.delete_rule(r["id"]))
        self.assertFalse(any(x["id"] == r["id"] for x in R.load()["rules"]))

    def test_validation(self):
        for bad in ({}, {"fields": ["key"]}, {"nope": 1}, {"text": "("}):
            with self.assertRaises(R.RoutingError):
                R.add_rule(bad, "nowhere")
        with self.assertRaises(R.RoutingError):
            R.add_rule({"actor": "x"}, "elsewhere")  # elsewhere needs a where
        with self.assertRaises(R.RoutingError):
            R.add_rule({"actor": "x"}, "sideways")

    def test_preview(self):
        out = R.preview(
            {"actor": "Kim"},
            "nowhere",
            [cand(actor="Kim"), cand(actor="Bob")],
            [{"key": "a", "title": "b"}],
        )
        self.assertEqual((out["candidate_count"], out["item_count"]), (1, 0))


class ExtChatAdapter(unittest.TestCase):
    """Rows of a second chat feed share the slim shape and route through the same adapter."""

    def setUp(self):
        import collect as C

        self.C = C
        self.feed = TMP / "ext-feed.json"
        rows = [
            {
                "id": "ext:D1:100.1",
                "created": "2099-01-01T10:00:00Z",
                "platform": "ext",
                "surface": "chat",
                "chat_id": "ext:D1",
                "chat_type": "oneOnOne",
                "from_name": "Synthetic Person A",
                "text": "can you check this",
                "files": [],
                "web_url": "u",
                "reply_to": None,
                "mentions": [],
                "mentions_me": False,
            },
            {
                "id": "ext:C1:200.1",
                "created": "2099-01-01T11:00:00Z",
                "platform": "ext",
                "surface": "channel",
                "team": "Ext",
                "channel": "pilot",
                "from_name": "Synthetic Person B",
                "text": "status update",
                "files": [],
                "web_url": "u",
                "reply_to": None,
                "mentions": [],
                "mentions_me": False,
            },
            {
                "id": "ext:C1:200.2",
                "created": "2099-01-01T11:05:00Z",
                "platform": "ext",
                "surface": "channel",
                "team": "Ext",
                "channel": "pilot",
                "from_name": "Synthetic Person C",
                "text": "@owner-name approve?",
                "files": [],
                "web_url": "u",
                "reply_to": "ext:C1:200.1",
                "mentions": ["owner-name"],
                "mentions_me": True,
            },
        ]
        self.feed.write_text(json.dumps({"items": rows}))

    def test_sources_and_routes(self):
        roles = {"Synthetic Person B": "report"}
        out = self.C.from_chat(roles, "2098-01-01", self.feed, "ext", "Ext")
        by = {c["source"]: c for c in out}
        self.assertEqual(set(by), {"ext.1on1", "ext.channel", "ext.mention"})
        self.assertEqual(by["ext.1on1"]["addressed"], "direct")
        self.assertEqual(by["ext.mention"]["cid"], "ext:C1:200.2")
        self.assertIn(
            "status update",
            by["ext.mention"]["text"],
            "thread context groups the reply with its parent",
        )
        # An ext channel post from the owner's own report is context, not addressed to me.
        self.assertEqual(by["ext.channel"]["addressed"], "none")
        routing = R.load()
        self.assertEqual(R.route(by["ext.1on1"], routing)["route"], "action_center")
        self.assertEqual(R.route(by["ext.mention"], routing)["route"], "action_center")
        self.assertEqual(R.route(by["ext.channel"], routing)["route"], "analysis")
        for c in out:
            self.assertIn(c["source"], routing["sources"])


class Broken(unittest.TestCase):
    """A broken routing file never hides an item or a candidate (unknown never hides)."""

    def test_broken_file_raises(self):
        p = TMP / "broken.json"
        p.write_text("{not json")
        with self.assertRaises(R.RoutingError):
            R.load(p)
        p.write_text(json.dumps({"rules": [{"id": "x", "match": {}, "route": "nowhere"}]}))
        with self.assertRaises(R.RoutingError):
            R.load(p)

    def setUp(self):
        self.live = TMP / "ac-routing.json"
        shutil.copy(HERE / "fixtures/routing-seed.json", self.live)
        self.root = TMP / "root"
        (self.root / "state" / "dashboard").mkdir(parents=True, exist_ok=True)
        self.items = [
            {"key": "app-e-pagefile", "title": "retired-system pagefile fix", "action": "Ship it"},
            {"key": "doc-app-b", "title": "Document the app-b", "action": "Write it"},
            {"key": "freeze-gate", "title": "Freeze gate", "action": "Decide"},
        ]
        self.ac_file = self.root / "state" / "dashboard" / "action-center.json"
        self.ac_file.write_text(json.dumps({"items": self.items}))

    def load_board(self):
        """Run the real board loader (board_build.load_action_center) on a scratch state tree. The reader modules
        are imported fresh so they pick up the scratch paths."""
        os.environ["OPSCENTER_ROOT"] = str(self.root)
        os.environ["OPSCENTER_STATE_DIR"] = str(self.root / "state")
        os.environ["OPSCENTER_AGENT_HOME"] = str(self.root / "agent")
        for k in (
            "OPSCENTER_PEOPLE",
            "OPSCENTER_BOARD_SOURCES",
            "OPSCENTER_REF_STATUS",
            "OPSCENTER_TEAM_AWAY",
        ):
            os.environ.pop(k, None)
        for m in ("collect", "board_build"):
            sys.modules.pop(m, None)
        import board_build

        return board_build.load_action_center(self.ac_file)

    # core-rule: local-ops-app.16
    def test_healthy_file_routes_items_away(self):
        out = self.load_board()
        self.assertEqual([i["key"] for i in out["items"]], ["freeze-gate"])
        self.assertEqual(len(out["routing"]["items_routed_away"]), 2)

    # core-rule: local-ops-app.16
    def test_broken_file_keeps_every_item_visible(self):
        for bad in (
            "{not json",
            json.dumps({"rules": [{"id": "x", "match": {}, "route": "nowhere"}]}),
            "",
        ):
            self.live.write_text(bad)
            out = self.load_board()
            self.assertEqual(
                sorted(i["key"] for i in out["items"]),
                sorted(i["key"] for i in self.items),
                "every item stays when the routing file is %r" % bad[:20],  # noqa: UP031
            )
            self.assertIn("routing not applied", out["routing"].get("error", ""))

    # core-rule: local-ops-app.16
    def test_missing_file_keeps_every_item_visible(self):
        self.live.unlink()
        out = self.load_board()
        self.assertEqual(len(out["items"]), len(self.items))
        self.assertIn("routing not applied", out["routing"].get("error", ""))

    # core-rule: local-ops-app.16
    def test_collector_stops_on_a_broken_file_instead_of_dropping_candidates(self):
        import collect as C

        self.live.write_text("{not json")
        with self.assertRaises(R.RoutingError):
            C.collect()


if __name__ == "__main__":
    try:
        unittest.main(verbosity=1)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
