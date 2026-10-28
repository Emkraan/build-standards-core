"""The four people slots with a null default: roster pull, calendar, meetings and message feeds. Fake commands and
files stand in for the consumer's adapters; with none configured the board renders and says what is unavailable."""

import datetime as dt
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

OWNER = "Owen Owner"
REPORT = {"name": "Report One", "first": "One"}
PARTNER = {
    "name": "Partner One",
    "first": "Partner",
    "email": "partner.one@example.com",
    "title": "Role C",
    "group": "partner",
}


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


class Slots(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.state = self.root / "state"
        (self.state / "dashboard").mkdir(parents=True)
        (self.state / "team-performance").mkdir(parents=True)
        self._env = {
            k: os.environ.get(k)
            for k in (
                "OPSCENTER_ROOT",
                "OPSCENTER_STATE_DIR",
                "OPSCENTER_PEOPLE_PARAMS",
                "OPSCENTER_AGENT_HOME",
            )
        }
        os.environ.update(
            OPSCENTER_ROOT=str(self.root),
            OPSCENTER_STATE_DIR=str(self.state),
            OPSCENTER_AGENT_HOME=str(self.root / "agent"),
            OPSCENTER_PEOPLE_PARAMS=str(self.root / "params.json"),
        )

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def load(self, **params):
        base = {
            "owner_name": OWNER,
            "owner_email": "owen.owner@example.com",
            "roster": [REPORT, PARTNER],
        }
        base.update(params)
        (self.root / "params.json").write_text(json.dumps(base))
        import one_on_ones

        self.oo = importlib.reload(one_on_ones)
        return self.oo

    def script(self, name, body):
        p = self.root / name
        p.write_text(body)
        return [sys.executable, str(p)]

    def person(self, board, name):
        return next(p for p in board["people"] if p["name"] == name)

    # the null default
    def test_with_no_adapter_the_board_renders_and_says_what_is_unavailable(self):
        oo = self.load()
        b = oo.board()
        self.assertEqual([p["name"] for p in b["people"]], ["Report One", "Partner One"])
        self.assertFalse(b["sources"]["calendar_ok"])
        self.assertFalse(b["sources"]["upcoming_ok"])
        with self.assertRaises(oo.ScheduleError) as cm:
            oo._gm(["upcoming"])
        self.assertEqual(cm.exception.code, 4)
        with self.assertRaises(oo.ScheduleError):
            oo.availability("Partner One")

    def test_no_roster_means_an_empty_board_not_a_crash(self):
        (self.root / "params.json").write_text("{}")
        import one_on_ones

        oo = importlib.reload(one_on_ones)
        self.assertEqual(oo.ROSTER, [])
        self.assertEqual(oo.board()["people"], [])

    # roster slot
    def test_the_roster_pull_fills_titles_and_addresses_and_a_dead_pull_falls_back_to_the_copy(
        self,
    ):
        pull = self.root / "pull.json"
        pull.write_text(
            json.dumps(
                {
                    "value": [
                        {
                            "displayName": "Report One",
                            "jobTitle": "Role A",
                            "mail": "Report.One@example.com",
                        }
                    ]
                }
            )
        )
        oo = self.load(roster_pull_file=str(pull))
        people, meta = oo.roster_state()
        one = next(p for p in people if p["name"] == "Report One")
        self.assertEqual(
            (one["title"], one["email"], meta["pull_ok"], meta["stale"]),
            ("Role A", "report.one@example.com", True, False),
        )
        pull.unlink()
        people, meta = oo.roster_state()
        one = next(p for p in people if p["name"] == "Report One")
        self.assertEqual(one["email"], "report.one@example.com")  # the last good copy
        self.assertTrue(meta["stale"] and not meta["pull_ok"])

    # meetings slot (and the calendar it shares)
    def test_meetings_command_upcoming_availability_create_and_the_booking_guard(self):
        soon = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=2)
        cmd = self.script(
            "meet.py",
            "import json, sys\n"  # noqa: UP031
            "cmd = sys.argv[1]\n"
            "if cmd == 'upcoming':\n"
            "    print(json.dumps({'events': [{'id': 'e1', 'subject': 'one on one', 'start': %r, 'end': %r, 'attendees': ['partner.one@example.com'], 'organizer': 'owen.owner@example.com', 'cancelled': False}]}))\n"
            "elif cmd == 'availability':\n"
            "    print(json.dumps({'minutes': int(sys.argv[sys.argv.index('--minutes') + 1]), 'suggestions': [{'start': 'a', 'end': 'b'}]}))\n"
            "elif cmd == 'create':\n"
            "    req = json.load(sys.stdin)\n"
            "    print(json.dumps({'id': 'new1', 'subject': 'S', 'start': req['start'], 'end': req['start'], 'join_url': 'u', 'transcription': {'applied': {'allowTranscription': True}}}))\n"
            % (iso(soon), iso(soon + dt.timedelta(minutes=30))),
        )
        oo = self.load(meetings_cmd=cmd)
        b = oo.board()
        partner = self.person(b, "Partner One")
        self.assertIsNotNone(partner["next_1on1"])
        self.assertFalse(partner["schedule_needed"])
        self.assertTrue(b["sources"]["upcoming_ok"])
        av = oo.availability("Partner One", 30)
        self.assertEqual((av["minutes"], av["subject"]), (30, "Owen Owner and Partner: 1:1"))
        res = oo.schedule(
            {
                "person": "Partner One",
                "start": "2099-01-05T10:00",
                "minutes": 30,
                "agenda": ["- one", "two"],
            }
        )
        self.assertEqual(res["id"], "new1")
        with self.assertRaises(ValueError):
            oo.schedule(
                {"person": "Partner One", "start": "2099-01-05T11:00"}
            )  # a second booking inside the guard
        with self.assertRaises(ValueError):
            oo.schedule({"person": "Partner One", "start": "tomorrow"})
        self.assertEqual(
            json.loads((self.state / "dashboard" / "one-on-ones.json").read_text())["scheduled"][0][
                "event_id"
            ],
            "new1",
        )

    def test_a_meetings_command_that_needs_a_new_sign_in_reports_code_two(self):
        cmd = self.script(
            "reauth.py",
            "import json, sys\nprint(json.dumps({'error': 'sign in again', 'reauth': True}))\nsys.exit(2)\n",
        )
        oo = self.load(meetings_cmd=cmd)
        with self.assertRaises(oo.ScheduleError) as cm:
            oo._gm(["upcoming"])
        self.assertEqual((cm.exception.code, str(cm.exception)), (2, "sign in again"))

    def test_a_calendar_command_feeds_the_meeting_chip_and_a_failure_keeps_the_last_good_pull(self):
        now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(hours=3)
        ev = {
            "subject": "Partner catch up",
            "start": {"dateTime": now.isoformat()},
            "end": {"dateTime": (now + dt.timedelta(minutes=30)).isoformat()},
            "attendees": [{"emailAddress": {"address": "Partner.One@example.com"}}],
        }
        cmd = self.script("cal.py", "import json\nprint(json.dumps([%s]))\n" % json.dumps(ev))  # noqa: UP031
        oo = self.load(calendar_cmd=cmd)
        cal = oo._calendar()
        self.assertEqual(cal[0]["attendees"], ["partner.one@example.com"])
        self.assertIsNotNone(
            oo._meeting_for({"first": "Partner", "email": "partner.one@example.com"}, cal)
        )
        oo._state["cal_at"] = 0
        oo.CAL_CMD = [sys.executable, "-c", "import sys; sys.exit(1)"]
        again = oo._calendar()
        self.assertEqual(again, cal)  # kept
        self.assertIsNotNone(oo._state["cal_error"])

    # message feeds slot
    def test_chat_and_mail_feeds_become_topics_and_noise_is_dropped(self):
        feeds = self.root / "agent" / "feeds"
        feeds.mkdir(parents=True)
        now = dt.datetime.now(dt.timezone.utc)
        (feeds / "chat.json").write_text(
            json.dumps(
                {
                    "updated": iso(now),
                    "items": [
                        {
                            "id": "c1",
                            "created": iso(now - dt.timedelta(hours=1)),
                            "chat_id": "chat1",
                            "chat_type": "oneOnOne",
                            "from_name": "Report One",
                            "text": "Can you approve the access request for the build server? It is blocking the release.",
                        },
                        {
                            "id": "c2",
                            "created": iso(now - dt.timedelta(hours=1)),
                            "chat_id": "chat2",
                            "chat_type": "oneOnOne",
                            "from_name": "Stranger",
                            "text": "hello?",
                        },
                    ],
                }
            )
        )
        (feeds / "mail.json").write_text(
            json.dumps(
                {
                    "updated": iso(now),
                    "items": [
                        {
                            "id": "m1",
                            "received": iso(now - dt.timedelta(hours=2)),
                            "from_name": "Report One",
                            "from_addr": "report.one@example.com",
                            "subject": "Accepted: planning",
                            "preview": "x",
                        },
                        {
                            "id": "m2",
                            "received": iso(now - dt.timedelta(hours=2)),
                            "from_name": "Report One",
                            "from_addr": "report.one@example.com",
                            "subject": "Licence renewal for the team",
                            "preview": "Can you decide on the renewal by Friday?",
                            "conversation_id": "conv2",
                        },
                    ],
                }
            )
        )
        oo = self.load()
        oo.harvest(force=True)
        # Raw threads are evidence only: they sit in the ledger and reach the board when an agenda or assessment
        # item matches them.
        ledger = json.loads((self.state / "dashboard" / "one-on-one-topics.json").read_text())[
            "topics"
        ]
        mine = [t for t in ledger.values() if t["person"] == "Report One"]
        self.assertEqual(
            {t["source"] for t in mine}, {"teams", "mail"}
        )  # the topic source keeps the app's name
        self.assertFalse(any("Accepted" in t["title"] for t in mine))
        self.assertEqual(
            {t["person"] for t in ledger.values()}, {"Report One"}
        )  # the stranger is ignored
        b = oo.board()
        self.assertEqual(b["sources"]["teams_updated"], iso(now))
        self.assertEqual(len(b["people"]), 2)

    def test_the_board_module_is_the_people_plugin_of_the_collector_and_the_board_composer(self):
        oo = self.load()
        sys.path.insert(0, str(HERE.parent / "engine"))
        os.environ["OPSCENTER_PEOPLE"] = str(HERE / "one_on_ones.py")
        os.environ["OPSCENTER_COLLECT_CONFIG"] = str(self.root / "none.json")
        try:
            sys.modules.pop("collect", None)
            import collect

            roles, errors = collect.people_roles({})
            self.assertEqual(
                (roles["report one"], roles["partner one"], roles["owen owner"], errors),
                ("report", "partner", "me", []),
            )
        finally:
            os.environ.pop("OPSCENTER_PEOPLE", None)
            os.environ.pop("OPSCENTER_COLLECT_CONFIG", None)
            sys.modules.pop("collect", None)
            sys.path.remove(str(HERE.parent / "engine"))
        self.assertTrue(callable(oo.agenda_action_items) and callable(oo.harvest))

    def test_the_excluded_title_regex_drops_analyzed_topics_but_not_manual_ones(self):
        oo = self.load(excluded_title_regex="retired-system")
        oo.add_topic("Report One", "retired-system sync", "by hand")
        b = oo.board()
        self.assertIn(
            "retired-system sync", [t["title"] for t in self.person(b, "Report One")["topics"]]
        )


if __name__ == "__main__":
    unittest.main()
