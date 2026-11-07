"""
inbound_files_test.py
Purpose: Files a direct report sends become Action Center items: a chat message with an attachment from a report is harvested (1:1 and
         group chats, never channel posts, never someone who is not a report), a mail with attachments or a document share naming a
         report is harvested, a message with no file is not, a replay of the same message is one entry (first seen kept), an item is
         medium when fresh and high after 48 hours, a dismissed entry is not an item, the board's resolve hides it by fingerprint and
         an old handled entry is pruned while an unhandled one never is.
Run:     python3 inbound_files_test.py
"""

import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "server" / "modules"))

TMP = tempfile.TemporaryDirectory()
os.environ["OPSCENTER_ROOT"] = TMP.name
os.environ["OPSCENTER_STATE_DIR"] = str(Path(TMP.name) / "state")
os.environ["INBOUND_FILES_SHARE_SENDERS"] = json.dumps(["docs.example.com"])
os.environ["INBOUND_FILES_TZ"] = "UTC"

import inbound_files as f  # noqa: E402

REPORT = {"name": "Alex Doe", "first": "Alex", "email": "alex@example.com", "group": "report"}
OTHER = {"name": "Sam Peer", "first": "Sam", "email": "sam@example.com", "group": "peer"}
NOW = dt.datetime(2026, 11, 6, 12, 0, tzinfo=dt.timezone.utc)


def chat(
    i="m1",
    name="Alex Doe",
    files=None,
    surface="chat",
    ctype="oneOnOne",
    at="2026-11-06T10:00:00Z",
    text="see the log",
):
    return {
        "id": i,
        "from_name": name,
        "surface": surface,
        "chat_type": ctype,
        "created": at,
        "files": [{"name": "log.txt", "url": "https://files.example/log.txt"}]
        if files is None
        else files,
        "text": text,
        "web_url": "https://chat.example/m1",
    }


class Harvest(unittest.TestCase):
    def setUp(self):
        f.STORE_PATH.unlink(missing_ok=True)
        f.one_on_ones.roster = lambda: [REPORT, OTHER]

    def store(self):
        return json.loads(f.STORE_PATH.read_text())["files"]

    def test_a_chat_file_from_a_report_is_harvested(self):
        self.assertEqual(f.harvest_messages([chat()], "chat"), 1)
        e = self.store()["chat:m1"]
        self.assertEqual(
            (e["person"], e["where"], e["surface"]), ("Alex Doe", "in your 1:1 chat", "chat")
        )

    def test_the_old_surface_name_still_works_and_group_chats_say_so(self):
        self.assertEqual(f.harvest_messages([chat(ctype="group")], "teams"), 1)
        self.assertEqual(self.store()["chat:m1"]["where"], "in a group chat")

    def test_channel_posts_non_reports_and_messages_without_files_are_not_harvested(self):
        msgs = [
            chat("c1", surface="channel"),
            chat("c2", name="Sam Peer"),
            chat("c3", files=[]),
            chat("c4", name="Nobody"),
        ]
        self.assertEqual(f.harvest_messages(msgs, "chat"), 0)
        self.assertFalse(f.STORE_PATH.exists())

    def test_a_replay_is_one_entry_and_keeps_first_seen(self):
        f.harvest_messages([chat()], "chat")
        first = self.store()["chat:m1"]["first_seen"]
        self.assertEqual(f.harvest_messages([chat(text="edited")], "chat"), 0)
        e = self.store()["chat:m1"]
        self.assertEqual((e["first_seen"], e["text"]), (first, "edited"))

    def test_mail_with_attachments_and_a_document_share_naming_a_report(self):
        mail = {
            "id": "x1",
            "from_addr": "alex@example.com",
            "from_name": "Alex Doe",
            "subject": "Install transcript",
            "has_attachments": True,
            "received": "2026-11-06T09:00:00Z",
            "web_link": "https://mail.example/x1",
            "preview": "attached",
        }
        share = {
            "id": "x2",
            "from_addr": "noreply@example.com",
            "from_name": "Alex Doe via Docs",
            "subject": "Alex shared 'Plan.docx' with you",
            "received": "2026-11-06T09:30:00Z",
            "web_link": "https://docs.example/plan",
        }
        plain = {
            "id": "x3",
            "from_addr": "alex@example.com",
            "from_name": "Alex Doe",
            "subject": "no file",
            "received": "2026-11-06T09:40:00Z",
        }
        self.assertEqual(f.harvest_messages([mail, share, plain], "mail"), 2)
        s = self.store()
        self.assertEqual(s["mail:x1"]["files"][0]["name"], "Install transcript")
        self.assertEqual(
            (s["mail:x2"]["files"][0]["name"], s["mail:x2"]["where"]),
            ("Plan.docx", "by a document share"),
        )
        self.assertNotIn("mail:x3", s)

    def test_a_share_from_an_unlisted_sender_is_not_a_share(self):
        share = {
            "id": "x2",
            "from_addr": "noreply@other.example.com",
            "from_name": "Alex Doe",
            "subject": "Alex shared 'Plan.docx' with you",
        }
        self.assertEqual(f.harvest_messages([share], "mail"), 0)

    def test_with_no_roster_nothing_is_harvested(self):
        f.one_on_ones.roster = lambda: []
        self.assertEqual(f.harvest_messages([chat()], "chat"), 0)

    def test_the_rolling_feeds_are_a_second_path(self):
        feed = Path(TMP.name) / "chat-feed.json"
        feed.write_text(json.dumps({"items": [chat()]}))
        os.environ["INBOUND_FILES_FEEDS"] = json.dumps(
            {"chat": str(feed), "mail": str(Path(TMP.name) / "missing.json")}
        )
        try:
            self.assertEqual(f.harvest_feeds(), 1)
            self.assertEqual(f.harvest_feeds(), 0)
        finally:
            os.environ.pop("INBOUND_FILES_FEEDS")
        self.assertEqual(f.harvest_feeds(), 0)  # no feeds configured


class Items(unittest.TestCase):
    def setUp(self):
        f.STORE_PATH.unlink(missing_ok=True)
        f.HANDLED_PATH.unlink(missing_ok=True)
        f.one_on_ones.roster = lambda: [REPORT]

    def test_fresh_is_medium_old_is_high_and_the_text_names_the_file(self):
        f.harvest_messages(
            [
                chat("a", at="2026-11-06T10:00:00Z", text="root cause in TICKET-123"),
                chat("b", at="2026-11-03T10:00:00Z"),
            ],
            "chat",
        )
        items = {i["key"]: i for i in f.action_items(NOW)}
        self.assertEqual(sorted(i["priority"] for i in items.values()), ["high", "medium"])
        fresh = next(i for i in items.values() if i["priority"] == "medium")
        self.assertIn("Unread file from Alex: log.txt", fresh["title"])
        self.assertEqual(fresh["refs"], ["TICKET-123"])
        self.assertEqual(fresh["owner"], "Alex Doe")
        self.assertTrue(fresh["key"].startswith("file-"))
        self.assertIn("11/6 10:00 AM UTC", fresh["why"])

    def test_a_dismissed_entry_is_not_an_item(self):
        f.harvest_messages([chat()], "chat")
        self.assertTrue(f.dismiss("chat:m1", "already read"))
        self.assertEqual(f.action_items(NOW), [])
        self.assertFalse(f.dismiss("chat:none", "x"))

    def test_items_are_ascii(self):
        f.harvest_messages([chat(text="it’s “broken” — see")], "chat")
        for v in f.action_items(NOW)[0].values():
            self.assertTrue(json.dumps(v).isascii())

    def test_prune_drops_old_handled_entries_and_never_an_unhandled_one(self):
        f.harvest_messages([chat("old"), chat("new"), chat("open")], "chat")
        fp = f.one_on_ones._board_fingerprint()
        if fp is None:
            self.skipTest("the board composer is not in the tree")
        old, new = f._key("chat:old"), f._key("chat:new")
        f.HANDLED_PATH.write_text(
            json.dumps(
                {
                    "handled": {
                        fp({"key": old}): {"act": "resolved", "at": "2026-09-01T00:00:00Z"},
                        fp({"key": new}): {"act": "ignored", "at": "2026-11-05T00:00:00Z"},
                    }
                }
            )
        )
        self.assertEqual(f.prune(NOW), 1)
        left = json.loads(f.STORE_PATH.read_text())["files"]
        self.assertEqual(sorted(left), ["chat:new", "chat:open"])


if __name__ == "__main__":
    unittest.main()
