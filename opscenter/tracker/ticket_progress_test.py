#!/usr/bin/env python3
"""Tests for ticket_progress.py . Synthetic trackers and tickets in a scratch root, a fake tracker reader and
writer, a fake model. No real ticket, comment or board is touched."""

from __future__ import annotations

import datetime as dt
import importlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="ticket-progress-test-")
os.environ["OPSCENTER_ROOT"] = TMP
os.environ["OPSCENTER_STATE_DIR"] = str(Path(TMP) / "state")
os.environ["PLANS_DIR"] = str(Path(TMP) / "plans")
Path(TMP, "tracker-params.json").write_text(
    json.dumps(
        {
            "owner_name": "Owen Owner",
            "tz": "America/New_York",
            "site_id": "site-1",
            "browse_url": "https://tracker.example/browse/",
            "intake_parent": "TKT-1801",
            "banned_words": ["ops-center", "hermes", "ops center"],
        }
    )
)
os.environ["OPSCENTER_TRACKER_PARAMS"] = str(Path(TMP) / "tracker-params.json")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "server" / "modules"))
import automation_actions as aa  # noqa: E402
import params  # noqa: E402
import ticket_progress as tp  # noqa: E402

PARAMS_FILE = str(Path(TMP) / "tracker-params.json")


def reload_all():
    """Another test module may have pointed the shared params module at its own file: point it back, then reload."""
    os.environ["OPSCENTER_TRACKER_PARAMS"] = PARAMS_FILE
    importlib.reload(params)
    importlib.reload(tp)


importlib.reload(params)
importlib.reload(aa)
importlib.reload(tp)

UTC = dt.timezone.utc
ET = tp.ET


def at(y, mo, d, h=12, mi=0):
    """An ET wall time as an aware datetime."""
    return dt.datetime(y, mo, d, h, mi, tzinfo=ET)


TRACKER = """---
title: Synthetic build
type: tracker
status: active
tickets: TKT-9001, TKT-9002, TKT-9003
owner: Owen Owner
next: Land the second pool and confirm the destroy, then ask Alpha about CA (Owen).
---

## Next steps
- [x] Review and merge the base (merged 10/16, 117 resources)
- [x] Add the second pool (#432 merged 10/21)

## Log
- 2026-10-23: Reconciled against live. #478 merged and applied, apply 40341196615 succeeded. Both hosts are Available.
- 2026-10-22 18:01Z: I opened #444 to reorder the RDP properties. Sam filed TKT-9003 as intake for the filter.
- 2026-10-19: Older work before the comment, #401 merged.
"""


def issue(key="TKT-9001", type_="Ops Task", comments=None, **kw):
    base = {
        "key": key,
        "summary": "Build the thing",
        "type": type_,
        "labels": [],
        "parent": "",
        "done": False,
        "assignee": "Owen Owner",
        "comments": comments
        if comments is not None
        else [
            {
                "id": "100",
                "created": at(2026, 10, 19, 15),
                "body": "Progress since my last update:\n\n* I did it.",
                "author": "Owen Owner",
            }
        ],
    }
    base.update(kw)
    return base


class Env(unittest.TestCase):
    def setUp(self):
        self.root = Path(TMP)
        for p in (tp.STORE_PATH, tp.HANDLED_PATH, aa.STORE_PATH):
            if p.exists():
                p.unlink()
        pd = tp.PLANS / "projects"
        for old in pd.glob("*/tracker.md") if pd.exists() else []:
            old.unlink()
        self.tracker("synthetic", TRACKER)
        os.environ["TICKET_PROGRESS_NOW"] = "2026-10-26T14:00:00-04:00"
        self.model_calls = 0
        self.model_reply = {
            "comment": "Progress since my last update:\n\n* I opened #444 to reorder the RDP properties.\n* I confirmed both hosts are Available.\n\nNext: I will land the second pool and confirm the destroy."
        }
        tp._call_model = self.fake_model

    def tearDown(self):
        os.environ.pop("TICKET_PROGRESS_NOW", None)

    def tracker(self, slug, text):
        d = tp.PLANS / "projects" / slug
        d.mkdir(parents=True, exist_ok=True)
        (d / "tracker.md").write_text(text)

    def fake_model(self, prompt):
        self.model_calls += 1
        if isinstance(self.model_reply, Exception):
            raise self.model_reply
        return self.model_reply

    def reader(self, iss):
        return lambda key: dict(iss, key=key)

    def cards(self):
        return [
            e
            for e in aa._load()["items"].values()
            if e["id"].startswith(tp.CARD_PREFIX) and not e.get("closed")
        ]


class QuietMath(unittest.TestCase):
    def test_weekend_is_not_counted(self):
        # Thu comment: Fri, Mon, Tue are 3 full working days, so Wed is the first quiet day.
        thu = at(2026, 10, 22, 16)
        self.assertFalse(tp.is_quiet(thu, at(2026, 10, 27, 9)))  # Tue, only Fri and Mon complete
        self.assertTrue(tp.is_quiet(thu, at(2026, 10, 28, 9)))  # Wed
        self.assertEqual(tp.working_days_between(dt.date(2026, 10, 22), dt.date(2026, 10, 28)), 3)

    def test_friday_comment_spans_the_weekend(self):
        fri = at(2026, 10, 23, 16)
        self.assertFalse(tp.is_quiet(fri, at(2026, 10, 27, 9)))  # Mon only
        self.assertTrue(tp.is_quiet(fri, at(2026, 10, 29, 9)))  # Mon Tue Wed complete

    def test_same_day_and_next_day_are_never_quiet(self):
        d = at(2026, 10, 20, 9)
        self.assertFalse(tp.is_quiet(d, at(2026, 10, 20, 23)))
        self.assertFalse(tp.is_quiet(d, at(2026, 10, 21, 9)))

    def test_ticket_ages_by_et_date_not_utc(self):
        late = dt.datetime(2026, 10, 21, 2, 30, tzinfo=UTC)  # Tue 22:30 ET on 10/20
        self.assertEqual(
            tp.working_days_between(late.astimezone(ET).date(), dt.date(2026, 10, 26)), 3
        )

    def test_run_window(self):
        self.assertTrue(tp.in_run_window(at(2026, 10, 26, 9)))
        self.assertFalse(tp.in_run_window(at(2026, 10, 26, 19)))
        self.assertFalse(tp.in_run_window(at(2026, 10, 24, 10)))  # Saturday


class Entries(Env):
    def test_parse_front_matter_and_entries(self):
        tr = tp.parse_tracker(TRACKER, tp.now_utc())
        self.assertEqual(tr["tickets"][0], "TKT-9001")
        kinds = sorted({e["kind"] for e in tr["entries"]})
        self.assertEqual(kinds, ["done", "log"])
        self.assertEqual(len(tr["entries"]), 5)
        self.assertEqual([e["day"] for e in tr["entries"]][0], dt.date(2026, 10, 16))

    def test_entries_after_the_last_comment(self):
        tr = tp.parse_tracker(TRACKER, tp.now_utc())
        got = tp.entries_after(tr["entries"], at(2026, 10, 19, 15))
        texts = " ".join(e["text"] for e in got)
        self.assertIn("#478 merged", texts)
        self.assertIn("#444", texts)
        self.assertIn("second pool", texts)  # a checked item dated 10/21 in its text
        self.assertNotIn("#401", texts)  # dated before the comment
        self.assertNotIn("base", texts)  # 10/16 item

    def test_timed_entry_compares_by_instant_and_date_only_by_day(self):
        tr = tp.parse_tracker(
            "---\nstatus: active\ntickets: TKT-1\n---\n- 2026-10-22 18:01Z: timed.\n- 2026-10-22: dateonly.\n",
            tp.now_utc(),
        )
        before = dt.datetime(2026, 10, 22, 17, 0, tzinfo=UTC)
        after = dt.datetime(2026, 10, 22, 19, 0, tzinfo=UTC)
        self.assertEqual([e["text"] for e in tp.entries_after(tr["entries"], before)], ["timed."])
        self.assertEqual(tp.entries_after(tr["entries"], after), [])

    def test_tracker_intake_forms(self):
        text = "Sam filed TKT-9003 as intake for it. Also intake TKT-9005 and TKT-9006 is the intake (Sam). Work TKT-9001 ships."
        keys = tp.tracker_intake_keys(text, ["TKT-9001", "TKT-9003", "TKT-9005", "TKT-9006"])
        self.assertEqual(keys, {"TKT-9005", "TKT-9006"})

    def test_only_active_trackers_with_tickets(self):
        self.tracker("done-one", TRACKER.replace("status: active", "status: done"))
        self.tracker("no-tickets", TRACKER.replace("tickets: TKT-9001, TKT-9002, TKT-9003\n", ""))
        self.assertEqual([s for s, _p, _t in tp.list_trackers()], ["synthetic"])


class Lint(unittest.TestCase):
    GOOD = "Progress since my last update:\n\n* I built the pool (#432).\n* I fixed the roll.\n\nNext: I will confirm the destroy."

    def test_good_draft_passes(self):
        self.assertEqual(tp.lint(self.GOOD), [])

    def test_rejects_each_banned_form(self):
        cases = {
            "semicolon": self.GOOD.replace("pool", "pool" + tp.SEMI),
            "dash": self.GOOD.replace("built", "built \u2014 and"),
            "non-ASCII": self.GOOD.replace("roll", "r\u00f6ll"),
            "internal": self.GOOD.replace("the roll", "the ops-center roll"),
            "ai word": self.GOOD.replace("the roll", "the AI roll"),
            "run id": self.GOOD.replace("the roll", "run 40343380673"),
            "sha": self.GOOD.replace("the roll", "commit 3fa9c21d"),
            "path": self.GOOD.replace("the roll", "state/x"),
            "opening": self.GOOD.replace("Progress since my last update:", "Update:"),
            "no next": self.GOOD.rsplit("\n", 1)[0],
            "greeting": "Hi team,\n\n" + self.GOOD,
            "sign-off": self.GOOD + "\n\nThanks",
            "empty": "",
        }
        for name, text in cases.items():
            self.assertTrue(tp.lint(text), name)

    def test_clean_text_strips_run_ids_shas_paths_and_tools(self):
        raw = (
            "Merged [#478](https://x/y) with apply 40341196615 (sha 3fa9c21d7) via ops-home/state/x, improvement-id done"
            + tp.SEMI
            + " ok"
        )
        out = tp.clean_text(raw)
        self.assertEqual(
            tp.lint("Progress since my last update:\n\n* %s\n\nNext: go on now." % out),  # noqa: UP031
            [],  # noqa: UP031
        )  # noqa: UP031
        self.assertIn("#478", out)
        self.assertNotIn("40341196615", out)

    def test_deterministic_draft_passes_lint_and_drops_internal_sentences(self):
        tr = tp.parse_tracker(TRACKER, tp.now_utc())
        got = tp.entries_after(tr["entries"], at(2026, 10, 19, 15))
        text = tp.deterministic_draft(got, tr["meta"]["next"])
        self.assertEqual(tp.lint(text), [], text)
        self.assertNotIn("Reconciled", text)
        self.assertNotIn("(Owen)", text)


class Sync(Env):
    def run_sync(self, iss=None, **kw):
        return tp.sync(force=True, reader=self.reader(iss or issue()), **kw)

    def test_quiet_ticket_raises_one_card_with_post_edit_dismiss_shape(self):
        out = self.run_sync()
        self.assertEqual(out["raised"], 1, out)
        (c,) = self.cards()
        self.assertEqual(c["id"], "ticket-progress-tkt-9001-g1")
        self.assertEqual(c["approve"]["label"], "Post comment")
        self.assertEqual(c["draft"]["fields"][0]["key"], "comment")
        self.assertEqual([a["kind"] for a in c["actions"]], ["ticket-dismiss"])
        self.assertEqual(c["refs"], ["TKT-9001"])
        self.assertIn("Progress since my last update:", c["draft"]["fields"][0]["text"])
        self.assertEqual(tp.lint(c["draft"]["fields"][0]["text"]), [])

    def test_not_quiet_raises_nothing(self):
        recent = issue(
            comments=[
                {"id": "9", "created": at(2026, 10, 23, 15), "body": "x", "author": "Owen Owner"}
            ]
        )
        self.assertEqual(self.run_sync(recent)["raised"], 0)
        self.assertEqual(self.cards(), [])

    def test_quiet_without_new_entries_raises_nothing(self):
        late = issue(
            comments=[
                {"id": "9", "created": at(2026, 10, 23, 15), "body": "x", "author": "Owen Owner"}
            ]
        )
        self.tracker("synthetic", TRACKER)
        os.environ["TICKET_PROGRESS_NOW"] = "2026-10-29T14:00:00-04:00"
        out = self.run_sync(late)
        self.assertEqual(out["raised"], 0)

    def test_intake_tickets_are_skipped(self):
        for kw in (
            {"type_": "Discovery"},
            {"parent": "TKT-1801"},
            {"labels": ["intake"]},
            {"summary": "Intake for the filter"},
        ):
            out = self.run_sync(issue(**kw))
            self.assertEqual(out["raised"], 0, kw)
            self.assertTrue(any("intake" in s for s in out["skipped"]), (kw, out))
        self.assertEqual(self.cards(), [])

    def test_tracker_marked_intake_work_key_is_skipped(self):
        self.tracker(
            "synthetic",
            TRACKER.replace("tickets: TKT-9001,", "tickets: TKT-9003,").replace(
                "Sam filed TKT-9003 as intake", "Sam filed intake TKT-9003"
            ),
        )
        out = self.run_sync()
        self.assertEqual(out["raised"], 0)
        self.assertIn("intake", " ".join(out["skipped"]))

    def test_done_or_not_mine_is_skipped(self):
        self.assertEqual(self.run_sync(issue(done=True))["raised"], 0)
        self.assertEqual(self.run_sync(issue(assignee="Someone Else"))["raised"], 0)

    def test_only_the_work_ticket_is_checked(self):
        seen = []

        def rd(key):
            seen.append(key)
            return issue(key=key)

        tp.sync(force=True, reader=rd)
        self.assertEqual(seen, ["TKT-9001"])

    def test_one_card_per_ticket_and_in_place_redraft(self):
        self.run_sync()
        self.assertEqual(self.run_sync()["raised"], 0)
        self.assertEqual(len(self.cards()), 1)
        first_calls = self.model_calls
        # a new entry arrives: same card id, new draft, no second card
        self.tracker(
            "synthetic",
            TRACKER.replace(
                "## Log\n", "## Log\n- 2026-10-26: I finished the new host and it is Available.\n"
            ),
        )
        self.model_reply = {
            "comment": "Progress since my last update:\n\n* I finished the new host.\n\nNext: I will confirm the destroy."
        }
        out = self.run_sync()
        self.assertEqual((out["raised"], out["updated"]), (0, 1))
        (c,) = self.cards()
        self.assertEqual(c["id"], "ticket-progress-tkt-9001-g1")
        self.assertIn("I finished the new host", c["draft"]["fields"][0]["text"])
        self.assertEqual(self.model_calls, first_calls + 1)

    def test_unchanged_entries_do_not_call_the_model_again(self):
        self.run_sync()
        n = self.model_calls
        self.run_sync()
        self.assertEqual(self.model_calls, n)

    def test_stray_second_open_card_is_closed(self):
        self.run_sync()
        aa.raise_item("ticket-progress-tkt-9001-g7", "dup", "dup", "dup")
        out = self.run_sync()
        self.assertEqual(len(self.cards()), 1)
        self.assertGreaterEqual(out["closed"], 1)

    def test_card_clears_when_someone_comments(self):
        self.run_sync()
        out = self.run_sync(
            issue(
                comments=[
                    {
                        "id": "200",
                        "created": at(2026, 10, 26, 9),
                        "body": "x",
                        "author": "Owen Owner",
                    }
                ]
            )
        )
        self.assertEqual(self.cards(), [])
        self.assertEqual(out["closed"], 1)

    def test_failed_read_changes_nothing(self):
        self.run_sync()

        def boom(key):
            raise tp.TicketError("down", 502)

        out = tp.sync(force=True, reader=boom)
        self.assertEqual(len(out["errors"]), 1)
        self.assertEqual(len(self.cards()), 1)

    def test_truncated_comment_list_is_unreadable(self):
        many = [
            {"id": str(i), "created": at(2026, 10, 1, 9), "body": "x", "author": "a"}
            for i in range(60)
        ]
        raised = []
        tp.tracker_call = lambda tool, args: {
            "fields": {
                "summary": "s",
                "status": {"statusCategory": {"key": "indeterminate"}},
                "issuetype": {"name": "Task"},
                "comment": {
                    "comments": [
                        {
                            "id": c["id"],
                            "created": c["created"].strftime("%Y-%m-%dT%H:%M:%S.000%z"),
                            "body": "x",
                            "author": {"displayName": "a"},
                        }
                        for c in many
                    ]
                },
            }
        }
        try:
            with self.assertRaises(tp.TicketError):
                tp.read_ticket("TKT-9001")
        finally:
            reload_all()
            tp._call_model = self.fake_model
        self.assertEqual(raised, [])

    def test_dry_run_writes_nothing(self):
        out = self.run_sync(dry_run=True)
        self.assertEqual(out["raised"], 1)
        self.assertEqual(self.cards(), [])
        self.assertFalse(tp.STORE_PATH.exists())

    def test_throttle_and_window(self):
        os.environ["TICKET_PROGRESS_NOW"] = "2026-10-24T10:00:00-04:00"  # Saturday
        self.assertIn("idle", tp.sync(reader=self.reader(issue())))
        os.environ["TICKET_PROGRESS_NOW"] = "2026-10-26T10:00:00-04:00"
        self.assertNotIn("idle", tp.sync(reader=self.reader(issue())))
        os.environ["TICKET_PROGRESS_NOW"] = "2026-10-26T11:00:00-04:00"
        self.assertIn("idle", tp.sync(reader=self.reader(issue())))  # ran an hour ago
        os.environ["TICKET_PROGRESS_NOW"] = "2026-10-26T13:30:00-04:00"
        self.assertNotIn("idle", tp.sync(reader=self.reader(issue())))

    def test_model_failure_falls_back_to_the_deterministic_draft(self):
        self.model_reply = RuntimeError("model down")
        self.run_sync()
        (c,) = self.cards()
        text = c["draft"]["fields"][0]["text"]
        self.assertEqual(tp.lint(text), [])
        self.assertIn("Progress since my last update:", text)
        self.assertEqual(
            json.loads(tp.STORE_PATH.read_text())["tickets"]["TKT-9001"]["draft_source"],
            "deterministic",
        )

    def test_bad_model_text_is_rejected_by_lint(self):
        self.model_reply = {
            "comment": "Progress since my last update:\n\n* I did ops-center work"
            + tp.SEMI
            + " fine.\n\nNext: more."
        }
        self.run_sync()
        (c,) = self.cards()
        text = c["draft"]["fields"][0]["text"]
        self.assertNotIn("ops-center", text)
        self.assertEqual(tp.lint(text), [])

    def test_when_nothing_passes_the_card_says_needs_edit_and_shows_no_draft(self):
        self.model_reply = {"comment": "bad" + tp.SEMI}
        self.tracker(
            "synthetic",
            TRACKER.replace(
                "next: Land the second pool and confirm the destroy, then ask Alpha about CA (Owen).",
                "next:",
            ),
        )
        self.run_sync()
        (c,) = self.cards()
        self.assertEqual(c["draft"]["fields"][0]["text"], "")
        self.assertIn("needs an edit", c["why"])
        self.assertEqual(tp.lint(c["why"] + c["title"] + c["action"]).count("has a semicolon"), 0)
        self.assertNotIn(tp.SEMI, c["why"])


class Buttons(Env):
    def setUp(self):
        super().setUp()
        tp.sync(force=True, reader=self.reader(issue()))
        self.posted = []

    def writer(self, tool, args):
        self.posted.append((tool, args))
        self.live.append(
            {
                "id": "555",
                "created": at(2026, 10, 26, 14),
                "body": args["commentBody"],
                "author": "Owen Owner",
            }
        )
        return {"id": "555"}

    live: list = []

    def rd(self, key):
        return issue(key=key, comments=list(self.live))

    def go(self, **kw):
        self.live = list(issue()["comments"])
        return tp.post("TKT-9001", reader=self.rd, writer=self.writer, **kw)

    def test_post_writes_verifies_records_and_clears_the_card(self):
        code, res = self.go()
        self.assertEqual(code, 200)
        self.assertEqual(res["comment_id"], "555")
        self.assertFalse(res["already"])
        self.assertEqual(len(self.posted), 1)
        tool, args = self.posted[0]
        self.assertEqual(
            (tool, args["issueIdOrKey"], args["contentFormat"]),
            ("addCommentToJiraIssue", "TKT-9001", "markdown"),
        )
        self.assertEqual(self.cards(), [])
        st = json.loads(tp.STORE_PATH.read_text())["tickets"]["TKT-9001"]
        self.assertEqual(st["posts"][0]["comment_id"], "555")
        self.assertEqual(st["gen"], 2)

    def test_post_uses_my_edit_and_lints_it(self):
        good = "Progress since my last update:\n\n* I edited this.\n\nNext: I will go on."
        self.go(text=good)
        self.assertIn("I edited this.", self.posted[0][1]["commentBody"])

    def test_post_refuses_a_bad_edit_with_no_write(self):
        with self.assertRaises(tp.TicketError) as cm:
            self.go(
                text="Progress since my last update:\n\n* I did it"
                + tp.SEMI
                + " ok.\n\nNext: more work."
            )
        self.assertEqual(cm.exception.code, 422)
        self.assertEqual(self.posted, [])

    def test_post_refuses_an_empty_draft(self):
        with self.assertRaises(tp.TicketError) as cm:
            self.go(text="  ")
        self.assertEqual(cm.exception.code, 400)

    def test_post_refuses_when_a_newer_comment_landed(self):
        self.live = list(issue()["comments"]) + [
            {"id": "300", "created": at(2026, 10, 26, 13), "body": "other", "author": "person"}
        ]
        with self.assertRaises(tp.TicketError) as cm:
            tp.post("TKT-9001", reader=self.rd, writer=self.writer)
        self.assertEqual(cm.exception.code, 409)
        self.assertEqual(self.posted, [])

    def test_post_is_idempotent_when_the_text_is_already_the_newest_comment(self):
        text = json.loads(tp.STORE_PATH.read_text())["tickets"]["TKT-9001"]["draft"]
        self.live = list(issue()["comments"]) + [
            {"id": "400", "created": at(2026, 10, 26, 13), "body": text, "author": "Owen Owner"}
        ]
        code, res = tp.post("TKT-9001", reader=self.rd, writer=self.writer)
        self.assertEqual((code, res["already"], res["comment_id"]), (200, True, "400"))
        self.assertEqual(self.posted, [])
        self.assertEqual(self.cards(), [])

    def test_post_that_cannot_be_confirmed_keeps_the_card(self):
        self.live = list(issue()["comments"])

        def lost(tool, args):
            return {"id": "777"}

        with self.assertRaises(tp.TicketError) as cm:
            tp.post("TKT-9001", reader=self.rd, writer=lost)
        self.assertEqual(cm.exception.code, 502)
        self.assertEqual(len(self.cards()), 1)

    def test_post_to_an_intake_is_refused(self):
        self.live = list(issue()["comments"])
        with self.assertRaises(tp.TicketError):
            tp.post(
                "TKT-9001", reader=lambda k: issue(key=k, type_="Discovery"), writer=self.writer
            )
        self.assertEqual(self.posted, [])

    def test_post_dry_run_writes_nothing(self):
        code, res = self.go(dry_run=True)
        self.assertTrue(res["dry_run"])
        self.assertEqual(self.posted, [])
        self.assertEqual(len(self.cards()), 1)

    def test_post_without_an_open_card_is_refused(self):
        self.go()
        with self.assertRaises(tp.TicketError):
            tp.post("TKT-9001", reader=self.rd, writer=self.writer)

    def test_dismiss_snoozes_until_a_new_entry(self):
        code, _ = tp.dismiss("TKT-9001")
        self.assertEqual(code, 200)
        self.assertEqual(self.cards(), [])
        out = tp.sync(force=True, reader=self.reader(issue()))
        self.assertEqual((out["raised"], self.cards()), (0, []))
        self.assertIn("dismissed", " ".join(out["skipped"]))
        self.tracker(
            "synthetic",
            TRACKER.replace("## Log\n", "## Log\n- 2026-10-26: I added the third host.\n"),
        )
        out = tp.sync(force=True, reader=self.reader(issue()))
        self.assertEqual(out["raised"], 1)
        (c,) = self.cards()
        self.assertEqual(
            c["id"], "ticket-progress-tkt-9001-g2"
        )  # a new id, the old handled record cannot hide it

    def test_card_handled_on_the_board_counts_as_dismissed(self):
        fp = tp._fp("ticket-progress-tkt-9001-g1")
        tp.HANDLED_PATH.write_text(
            json.dumps({"handled": {fp: {"act": "ignored", "at": "2026-10-26T14:00:00Z"}}})
        )
        out = tp.sync(force=True, reader=self.reader(issue()))
        self.assertEqual(self.cards(), [])
        self.assertEqual(out["raised"], 0)

    def test_fingerprint_matches_the_board(self):
        if not (HERE.parent / "engine" / "board_build.py").exists():
            self.skipTest("the board composer is not in this tree")
        spec = importlib.util.spec_from_file_location(
            "board_build_for_fp", str(HERE.parent / "engine" / "board_build.py")
        )
        bb = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bb)
        self.assertEqual(
            tp._fp("ticket-progress-tkt-9001-g1"),
            bb.ac_fingerprint({"key": "auto-ticket-progress-tkt-9001-g1"}),
        )


if __name__ == "__main__":
    unittest.main()
