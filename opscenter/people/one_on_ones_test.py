#!/usr/bin/env python3
"""Tests for the 1:1 agenda cards on the Action Center. Synthetic agenda, ledger and
status files in a scratch folder, no real board data."""

from __future__ import annotations

import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path

PERSON = "product-owner-name"


def agenda_item(iid, added="2026-10-10", **kw):
    base = {
        "id": iid,
        "person": PERSON,
        "priority": "P2",
        "added": added,
        "title": "Title " + iid,
        "refs": [],
        "match": [],
        "my_action": "Tell person the thing.",
        "detail": "Detail.",
    }
    base.update(kw)
    return base


def ledger_with(*messages):
    """One Teams thread with <person>. messages are (who, at, text)."""
    return {
        "topics": {
            "tm:1": {
                "fp": "tm:1",
                "person": PERSON,
                "source": "teams",
                "messages": [
                    {"id": str(i), "at": at, "who": who, "text": text}
                    for i, (who, at, text) in enumerate(messages)
                ],
            }
        }
    }


class AgendaCardsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.dash = self.root / "state" / "dashboard"
        self.dash.mkdir(parents=True)
        os.environ["OPSCENTER_ROOT"] = str(self.root)
        import one_on_ones

        self.oo = importlib.reload(one_on_ones)

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("OPSCENTER_ROOT", None)

    def write(self, items, ledger=None, status=None):
        (self.dash / "one-on-one-agenda.json").write_text(json.dumps({"items": items}))
        (self.dash / "one-on-one-topics.json").write_text(json.dumps(ledger or {"topics": {}}))
        if status is not None:
            (self.dash / "one-on-ones.json").write_text(json.dumps(status))

    def states(self):
        return {c["item"]["id"]: c["state"] for c in self.oo.agenda_cards()}

    def keys(self):
        return [i["key"] for i in self.oo.agenda_action_items()]

    # replied
    def test_a_reply_after_the_topic_date_marks_the_card_replied(self):
        self.write(
            [agenda_item("a", refs=["ticket-id"])],
            ledger_with(
                ("them", "2026-10-10T13:00:00Z", "Can you send ticket-id shots?"),
                ("me", "2026-10-11T09:00:00Z", "Sent ticket-id shots"),
            ),
        )
        self.assertEqual(self.states(), {"a": "replied"})
        self.assertEqual(self.keys(), [])
        replied = self.oo.agenda_replied_items()
        self.assertEqual([r["id"] for r in replied], ["a"])
        self.assertEqual(replied[0]["replied_at"], "2026-10-11T09:00:00Z")

    def test_a_reply_before_the_topic_date_does_not_count(self):
        self.write(
            [agenda_item("a", refs=["ticket-id"])],
            ledger_with(("me", "2026-10-09T09:00:00Z", "Looking at ticket-id")),
        )
        self.assertEqual(self.states(), {"a": "open"})
        self.assertEqual(self.keys(), ["oo-a"])

    def test_a_message_from_them_is_not_a_reply(self):
        self.write(
            [agenda_item("a", refs=["ticket-id"])],
            ledger_with(("them", "2026-10-11T09:00:00Z", "ping ticket-id")),
        )
        self.assertEqual(self.states(), {"a": "open"})

    def test_a_reply_to_someone_else_or_about_something_else_does_not_count(self):
        led = ledger_with(("me", "2026-10-11T09:00:00Z", "Unrelated lunch plans"))
        led["topics"]["tm:2"] = {
            "fp": "tm:2",
            "person": "person Wilkinson",
            "messages": [
                {"id": "9", "at": "2026-10-11T10:00:00Z", "who": "me", "text": "ticket-id done"}
            ],
        }
        self.write([agenda_item("a", refs=["ticket-id"])], led)
        self.assertEqual(self.states(), {"a": "open"})

    def test_match_phrase_counts_but_a_short_phrase_never_does(self):
        led = ledger_with(
            ("me", "2026-10-11T09:00:00Z", "The san group is fine, see the feedback form")
        )
        self.write(
            [
                agenda_item("long", match=["feedback form"]),
                agenda_item("short", match=["san"]),
            ],
            led,
        )
        self.assertEqual(self.states(), {"long": "replied", "short": "open"})

    # reopen
    def test_reopen_puts_the_card_back_until_a_newer_reply(self):
        led = ledger_with(("me", "2026-10-11T09:00:00Z", "Sent ticket-id shots"))
        self.write([agenda_item("a", refs=["ticket-id"])], led)
        self.assertEqual(self.states(), {"a": "replied"})
        self.oo.reopen_replied("a")
        self.assertEqual(self.states(), {"a": "open"})
        self.assertEqual(self.keys(), ["oo-a"])
        self.assertEqual(self.oo.agenda_replied_items(), [])
        # A later reply closes it again.
        led["topics"]["tm:1"]["messages"].append(
            {"id": "7", "at": "2999-01-01T00:00:00Z", "who": "me", "text": "Still ticket-id, done"}
        )
        (self.dash / "one-on-one-topics.json").write_text(json.dumps(led))
        self.assertEqual(self.states(), {"a": "replied"})

    def test_reopen_refuses_an_unknown_item(self):
        self.write([agenda_item("a")])
        with self.assertRaises(ValueError):
            self.oo.reopen_replied("nope")

    def test_reopen_keeps_the_other_status_entries(self):
        self.write(
            [agenda_item("a")],
            status={
                "status": {"ag:x": {"state": "discussed", "at": "2026-10-01T00:00:00Z"}},
                "manual": [],
            },
        )
        self.oo.reopen_replied("a")
        saved = json.loads((self.dash / "one-on-ones.json").read_text())
        self.assertIn("ag:x", saved["status"])
        self.assertIn("a", saved["ac_reopen"])

    # no decision owed
    def test_no_decision_wording_never_raises_a_card(self):
        self.write(
            [
                agenda_item(
                    "w1", my_action="Confirm it is settled, no decision owed, just acknowledge."
                ),
                agenda_item("w2", my_action="Say hi. Nothing owed."),
                agenda_item("flag", decision_owed=False),
                agenda_item("real"),
            ]
        )
        self.assertEqual(
            self.states(),
            {"w1": "no_decision", "w2": "no_decision", "flag": "no_decision", "real": "open"},
        )
        self.assertEqual(self.keys(), ["oo-real"])

    # unchanged behaviour
    def test_not_needed_still_drops_the_card_and_items_without_an_action_are_skipped(self):
        self.write(
            [agenda_item("a"), agenda_item("b", my_action=""), agenda_item("c")],
            status={
                "status": {"ag:a": {"state": "not_needed", "at": "2026-10-12T00:00:00Z"}},
                "manual": [],
            },
        )
        self.assertEqual(self.states(), {"a": "not_needed", "c": "open"})
        self.assertEqual(self.keys(), ["oo-c"])

    def test_card_shape_is_unchanged(self):
        self.write([agenda_item("a", refs=["ticket-id"])])
        card = self.oo.agenda_action_items()[0]
        self.assertEqual(card["key"], "oo-a")
        self.assertEqual(card["priority"], "medium")
        self.assertEqual(card["sources"], ["1:1 agenda"])
        self.assertEqual(card["one_on_one"]["person"], PERSON)


if __name__ == "__main__":
    unittest.main()
