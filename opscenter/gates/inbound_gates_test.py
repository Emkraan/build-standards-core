"""The inbound scorer and the two inbound wake gates: a noise filter that keeps everything it cannot prove mechanical, the mail and
chat gates as processes with fake pullers (spool, accumulation, urgent wake, drain, sentinels, failure backoff)."""

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


def load_score(cfg=None):
    d = Path(tempfile.mkdtemp(prefix="score-"))
    f = d / "cfg.json"
    f.write_text(json.dumps(cfg or {}))
    old = os.environ.get("INBOUND_SCORE_CONFIG")
    os.environ["INBOUND_SCORE_CONFIG"] = str(f)
    try:
        import importlib

        import inbound_score

        return importlib.reload(inbound_score)
    finally:
        if old is None:
            os.environ.pop("INBOUND_SCORE_CONFIG", None)
        else:
            os.environ["INBOUND_SCORE_CONFIG"] = old


class Score(unittest.TestCase):
    def test_with_no_config_everything_from_a_person_is_kept(self):
        s = load_score()
        self.assertEqual(
            s.score_mail({"from_addr": "a@example.com", "subject": "hello"}),
            (True, "human-or-unknown-sender"),
        )
        keep, drop, _ = s.triage(
            [{"from_addr": "noreply@example.com", "subject": "weekly digest"}], "mail"
        )
        self.assertEqual((len(keep), len(drop)), (1, 0))

    def test_urgency_words_always_keep_and_high_importance_is_urgent(self):
        s = load_score(
            {"mechanical_senders": ["bot@example.com"], "routine_subjects": ["weekly digest"]}
        )
        self.assertTrue(
            s.score_mail({"from_addr": "bot@example.com", "subject": "weekly digest: outage"})[
                1
            ].startswith("urgent-signal")
        )
        self.assertEqual(
            s.score_mail({"from_addr": "x@example.com", "subject": "hi", "importance": "High"}),
            (True, "flagged-high-importance"),
        )

    def test_a_known_sender_with_a_routine_subject_is_dropped_and_an_unknown_subject_kept(self):
        s = load_score(
            {
                "mechanical_senders": ["bot@example.com"],
                "routine_subjects": ["weekly (digest|report)"],
            }
        )
        self.assertEqual(
            s.score_mail({"from_addr": "BOT@example.com", "subject": "Weekly digest"}),
            (False, "mechanical-routine"),
        )
        self.assertEqual(
            s.score_mail({"from_addr": "bot@example.com", "subject": "something new"}),
            (True, "known-sender-but-unrecognized-subject"),
        )

    def test_a_downgrade_batches_an_echo_but_never_a_hard_failure(self):
        s = load_score(
            {
                "downgrades": [
                    {"sender": "ci@example.com", "subject": "^Re: ", "reason": "echo-batched"}
                ]
            }
        )
        self.assertEqual(
            s.score_mail({"from_addr": "ci@example.com", "subject": "Re: incident review"}),
            (True, "echo-batched"),
        )
        self.assertTrue(
            s.score_mail({"from_addr": "ci@example.com", "subject": "Re: build failed"})[
                1
            ].startswith("urgent-signal")
        )

    def test_ticket_regex_and_extra_urgent_patterns(self):
        s = load_score({"ticket_regex": r"\bABC-\d+\b", "urgent_patterns": ["pager"]})
        self.assertTrue(
            s.score_mail({"from_addr": "x@example.com", "subject": "see ABC-123"})[1].startswith(
                "urgent-signal"
            )
        )
        self.assertTrue(
            s.score_mail({"from_addr": "x@example.com", "subject": "the pager"})[1].startswith(
                "urgent-signal"
            )
        )

    def test_chat_self_bots_recorders_and_monitoring_channels(self):
        s = load_score(
            {
                "self_names": ["Owen Owner"],
                "bot_senders": ["workflow"],
                "noise_channels": ["alerts"],
            }
        )
        self.assertEqual(
            s.score_chat({"from_name": "Owen Owner", "text": "freeze it"}), (False, "self-authored")
        )
        self.assertEqual(
            s.score_chat({"from_name": "Otter.ai notetaker", "text": "x"}), (False, "bot-sender")
        )
        self.assertEqual(
            s.score_chat({"from_name": "workflow", "text": "x"}), (False, "bot-sender")
        )
        self.assertEqual(
            s.score_chat({"from_name": "Pat", "text": "urgent please"}), (True, "urgent-signal")
        )
        self.assertEqual(
            s.score_chat({"from_name": "Pat", "text": "lunch"}), (True, "human-message")
        )

    def test_alert_triage_drops_flap_and_keeps_novel_spikes_and_unresolved(self):
        s = load_score({"noise_channels": ["alerts"]})
        fire = lambda n, st, c="": {"channel": "alerts", "text": f"{n} | Status: {st} {c}"}  # noqa: E731
        keep, drop, base = s.triage(
            [fire("Disk", "Firing"), fire("Disk", "Resolved")], "chat", {"Disk": 2}
        )
        self.assertEqual(
            [r for _, r in drop],
            ["self-healing-flap", "self-healing-flap"],
        )
        keep, drop, _ = s.triage([fire("Brand New", "Firing")], "chat", {})
        self.assertTrue(keep[0][1].startswith("novel-alert"))
        keep, drop, _ = s.triage(
            [fire("Disk", "Firing", "71 errors"), fire("Disk", "Resolved")], "chat", {"Disk": 2}
        )
        self.assertTrue(any(r.startswith("count-spike") for _, r in keep))
        keep, drop, _ = s.triage([fire("Disk", "Firing", "1 error")], "chat", {"Disk": 2})
        self.assertTrue(keep[0][1].startswith("firing-unresolved"))
        keep, drop, _ = s.triage([{"channel": "alerts", "text": "free text"}], "chat", {})
        self.assertEqual(keep[0][1], "unparseable-alert")


class GateBase(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="inbound-gate-"))
        self.gates = self.d / "gates"
        clean = {k: v for k, v in os.environ.items() if not k.startswith(("GATE_", "INBOUND_"))}
        self.env = dict(
            clean,
            GATE_STATE_DIR=str(self.gates),
            GATE_DRAIN_HOURS="99",
            INBOUND_SCORE_CONFIG=str(self.d / "score.json"),
        )
        (self.d / "score.json").write_text(json.dumps({"self_names": ["Owen Owner"]}))

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def puller(self, name, body):
        p = self.d / name
        p.write_text(body)
        return [sys.executable, str(p)]

    def run_gate(self, gate, **env):
        e = dict(self.env, **env)
        p = subprocess.run(
            [sys.executable, str(HERE / gate)], capture_output=True, text=True, env=e, timeout=120
        )
        self.assertEqual(p.returncode, 0, p.stderr[-400:])
        return p.stdout

    def silent(self, out):
        return out.strip().splitlines()[-1:] == ['{"wakeAgent": false}']


class MailGate(GateBase):
    def pull_json(self, msgs):
        return self.puller(
            "mail.py",
            f"import json\nprint(json.dumps({{'messages': {msgs!r}, 'checkpoint': 'a', 'new_checkpoint': 'b'}}))\n",
        )

    def test_no_puller_means_silent(self):
        self.assertTrue(self.silent(self.run_gate("inbound_mail_gate.py")))

    def test_routine_mail_is_spooled_and_accumulated_without_waking_and_urgent_wakes(self):
        spool = self.d / "spool.json"
        cmd = self.pull_json([{"from_addr": "a@example.com", "subject": "hello", "received": "t"}])
        out = self.run_gate(
            "inbound_mail_gate.py", GATE_MAIL_PULLER=json.dumps(cmd), GATE_MAIL_SPOOL=str(spool)
        )
        self.assertTrue(self.silent(out))
        self.assertEqual(json.loads(spool.read_text())["total"], 1)
        acc = json.loads((self.gates / "inbound-mail-accumulated.json").read_text())
        self.assertEqual(acc["items"][0]["_why"], "human-or-unknown-sender")
        cmd = self.pull_json(
            [{"from_addr": "b@example.com", "subject": "major outage now", "received": "t2"}]
        )
        out = self.run_gate(
            "inbound_mail_gate.py", GATE_MAIL_PULLER=json.dumps(cmd), GATE_MAIL_SPOOL=str(spool)
        )
        self.assertIn("URGENT item(s) in this batch", out)
        self.assertIn("major outage now", out)
        self.assertIn("2 item(s) accumulated", out)

    def test_a_scheduled_drain_hour_wakes_for_a_routine_backlog(self):
        cmd = self.pull_json([{"from_addr": "a@example.com", "subject": "hello"}])
        hour = __import__("time").localtime().tm_hour
        out = self.run_gate(
            "inbound_mail_gate.py", GATE_MAIL_PULLER=json.dumps(cmd), GATE_DRAIN_HOURS=str(hour)
        )
        mins = __import__("time").localtime().tm_min
        self.assertTrue("scheduled routine drain" in out or mins >= 10)

    def test_a_sentinel_wakes_and_a_failing_puller_backs_off(self):
        sentinel = self.puller("s.py", "print('[MAIL-REAUTH-NEEDED] sign in again')\n")
        self.assertIn(
            "[MAIL-REAUTH-NEEDED]",
            self.run_gate("inbound_mail_gate.py", GATE_MAIL_PULLER=json.dumps(sentinel)),
        )
        bad = self.puller("bad.py", "import sys\nsys.exit(1)\n")
        outs = [
            self.run_gate("inbound_mail_gate.py", GATE_MAIL_PULLER=json.dumps(bad))
            for _ in range(3)
        ]
        self.assertTrue(self.silent(outs[0]) and self.silent(outs[1]))
        self.assertIn("[MAIL GATE ALERT] The mail puller is failing.", outs[2])
        garbage = self.puller("g.py", "print('nope')\n")
        outs = [
            self.run_gate(
                "inbound_mail_gate.py",
                GATE_MAIL_PULLER=json.dumps(garbage),
                GATE_STATE_DIR=str(self.d / "gates2"),
            )
            for _ in range(3)
        ]
        self.assertIn("Puller output is not JSON", outs[2])


class ChatGate(GateBase):
    def src(self, name, body, **kw):
        cmd = self.puller(f"{name}.py", body)
        return dict({"name": name, "cmds": [cmd], "kind": name}, **kw)

    def ok(self, msgs):
        return f"import json\nprint(json.dumps({{'messages': {msgs!r}}}))\n"

    def test_no_sources_means_silent(self):
        self.assertTrue(self.silent(self.run_gate("inbound_chat_gate.py")))

    def test_messages_from_two_sources_are_triaged_the_owner_dropped_urgent_wakes(self):
        a = self.src(
            "chat",
            self.ok(
                [
                    {"from_name": "Pat", "text": "can you check this", "created": "t"},
                    {"from_name": "Owen Owner", "text": "freeze it"},
                ]
            ),
        )
        b = self.src(
            "ext",
            self.ok(
                [
                    {
                        "from_name": "Lee",
                        "text": "urgent: prod is down",
                        "created": "t2",
                        "channel": "ops",
                    }
                ]
            ),
            optional=True,
        )
        out = self.run_gate("inbound_chat_gate.py", GATE_CHAT_SOURCES=json.dumps([a, b]))
        self.assertIn("URGENT item(s) in this batch", out)
        self.assertIn("ext ops", out)
        acc = json.loads((self.gates / "inbound-chat-accumulated.json").read_text())["items"]
        self.assertEqual(sorted(e["_kind"] for e in acc), ["chat", "ext"])
        spool = json.loads((self.gates / "chat-spool.json").read_text())
        self.assertEqual(spool["filtered"][0]["reason"], "self-authored")

    def test_an_optional_source_failing_does_not_block_the_others(self):
        good = self.src("chat", self.ok([{"from_name": "Pat", "text": "hello"}]))
        bad = self.src("ext", "import sys\nsys.exit(1)\n", optional=True)
        out = self.run_gate("inbound_chat_gate.py", GATE_CHAT_SOURCES=json.dumps([good, bad]))
        self.assertTrue(self.silent(out))
        self.assertEqual(
            len(json.loads((self.gates / "inbound-chat-accumulated.json").read_text())["items"]), 1
        )

    def test_every_source_failing_alerts_on_the_third_tick_and_a_sentinel_wakes_with_the_fix_text(
        self,
    ):
        bad = self.src("chat", "import sys\nsys.exit(1)\n")
        outs = [
            self.run_gate("inbound_chat_gate.py", GATE_CHAT_SOURCES=json.dumps([bad]))
            for _ in range(3)
        ]
        self.assertTrue(self.silent(outs[0]) and self.silent(outs[1]))
        self.assertIn("Every chat source is failing", outs[2])
        s = self.src(
            "chat",
            "print('[CHAT-REAUTH-NEEDED] x')\n",
            sentinels=["[CHAT-REAUTH-NEEDED]"],
            fix="Sign in again.",
        )
        out = self.run_gate("inbound_chat_gate.py", GATE_CHAT_SOURCES=json.dumps([s]))
        self.assertIn("returned [CHAT-REAUTH-NEEDED]", out)
        self.assertIn("Sign in again.", out)

    def test_a_pull_that_exits_three_is_an_empty_batch_not_a_failure(self):
        locked = self.src("chat", "import sys\nsys.exit(3)\n")
        self.assertTrue(
            self.silent(
                self.run_gate("inbound_chat_gate.py", GATE_CHAT_SOURCES=json.dumps([locked]))
            )
        )
        self.assertFalse(
            (self.gates / "inbound-chat-health.json").exists()
            and "failures" in (self.gates / "inbound-chat-health.json").read_text()
        )

    def test_monitoring_channel_flap_is_dropped_and_a_novel_alert_wakes(self):
        (self.d / "score.json").write_text(json.dumps({"noise_channels": ["alerts"]}))
        flap = self.src(
            "chat",
            self.ok(
                [
                    {"channel": "alerts", "text": "Disk | Status: Firing 1 error"},
                    {"channel": "alerts", "text": "Disk | Status: Resolved"},
                ]
            ),
        )
        (self.gates).mkdir(parents=True, exist_ok=True)
        (self.gates / "chat-alert-baseline.json").write_text(json.dumps({"Disk": 2}))
        self.assertTrue(
            self.silent(self.run_gate("inbound_chat_gate.py", GATE_CHAT_SOURCES=json.dumps([flap])))
        )
        novel = self.src(
            "chat", self.ok([{"channel": "alerts", "text": "Brand New | Status: Firing"}])
        )
        self.assertIn(
            "novel-alert",
            self.run_gate("inbound_chat_gate.py", GATE_CHAT_SOURCES=json.dumps([novel])),
        )


if __name__ == "__main__":
    unittest.main()
