#!/usr/bin/env python3
"""Tests for alerts.py. Synthetic run files in a scratch folder, no real cron output or board."""

from __future__ import annotations

import datetime as dt
import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path

JOB_A = "aaaaaaaaaaaa"
JOB_B = "bbbbbbbbbbbb"


def script_run(name, jid, body=None, status=None):
    head = (
        f"# Cron Job: {name}\n\n**Job ID:** {jid}\n**Run Time:** x\n**Mode:** no_agent (script)\n"
    )
    if status:
        return head + "**Status:** {}\n\n{}\n".format(status, body or "")
    return head + "\n---\n\n%s\n" % (body or "")


def agent_run(jid, response="", error=None, prompt="Do the thing.\n## Response\n\nquoted heading"):
    head = f"# Cron Job: Agent\n\n**Job ID:** {jid}\n**Run Time:** x\n**Schedule:** 0 * * * *\n\n"
    doc = head + "**Prompt Characters:** %d\n## Prompt\n\n%s\n\n" % (len(prompt), prompt)  # noqa: UP031
    if error is not None:
        return doc + f"## Error\n\n```\n{error}\n```\n"
    return doc + "**Response Characters:** %d\n## Response\n\n%s\n" % (len(response), response)  # noqa: UP031


class AlertsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.cron = root / "cron"
        self.dash = root / "dash"
        (self.cron / "output").mkdir(parents=True)
        self.dash.mkdir()
        os.environ["ALERTS_CRON_HOME"] = str(self.cron)
        os.environ["ALERTS_DASH"] = str(self.dash)
        os.environ["OPSCENTER_ROOT"] = str(root / "ops-center")
        (self.cron / "jobs.json").write_text(
            json.dumps(
                {
                    "jobs": [
                        {"id": JOB_A, "name": "Drift report"},
                        {"id": JOB_B, "name": "Self-heal"},
                    ]
                }
            )
        )
        (self.dash / "alert-sources.json").write_text(json.dumps({"jobs": [JOB_A, JOB_B]}))
        import alerts
        import automation_actions

        self.al = importlib.reload(alerts)
        self.aa = importlib.reload(automation_actions)
        self.now = dt.datetime.now().astimezone()

    def tearDown(self):
        self.tmp.cleanup()
        for k in ("ALERTS_CRON_HOME", "ALERTS_DASH", "OPSCENTER_ROOT"):
            os.environ.pop(k, None)

    def put(self, jid, hours_ago, text):
        t = self.now - dt.timedelta(hours=hours_ago)
        d = self.cron / "output" / jid
        d.mkdir(exist_ok=True)
        (d / t.strftime("%Y-%m-%d_%H-%M-%S.md")).write_text(text)

    # parse_run shapes
    def test_parse_shapes(self):
        p = self.al.parse_run
        self.assertEqual(p(script_run("x", JOB_A, status="silent (empty output)"))[0], "silent")
        self.assertEqual(
            p(script_run("x", JOB_A, status="no_change (agent run suppressed)"))[0], "silent"
        )
        self.assertEqual(
            p(script_run("x", JOB_A, "Script exited with code 2", status="script failed")),
            ("failure", "Script exited with code 2"),
        )
        self.assertEqual(
            p(script_run("x", JOB_A, "3 scripts drifted")), ("report", "3 scripts drifted")
        )
        self.assertEqual(
            p(agent_run(JOB_A, response="Two tickets moved.")), ("report", "Two tickets moved.")
        )
        self.assertEqual(p(agent_run(JOB_A, response="[SILENT]"))[0], "silent")
        self.assertEqual(p(agent_run(JOB_A, response="Nothing new.\n\n[SILENT]"))[0], "silent")
        self.assertEqual(
            p(agent_run(JOB_A, response="[CRON_FAILURE]\nJira down")), ("failure", "Jira down")
        )
        kind, body = p(agent_run(JOB_A, error="RuntimeError: offline"))
        self.assertEqual(kind, "failure")
        self.assertIn("RuntimeError: offline", body)

    def test_parse_legacy_unframed_uses_last_heading(self):
        text = "# Cron Job: x\n\n## Prompt\n\nquote:\n## Error\n\nold\n\n## Response\n\nAll good, one change."
        self.assertEqual(self.al.parse_run(text), ("report", "All good, one change."))

    # collect
    def test_reports_clear_after_window_and_silent_is_skipped(self):
        self.put(JOB_A, 1, script_run("Drift", JOB_A, "new drift"))
        self.put(JOB_A, 2, script_run("Drift", JOB_A, status="silent (empty output)"))
        self.put(JOB_A, 50, script_run("Drift", JOB_A, "old drift"))
        alerts = self.al.collect()["alerts"]
        self.assertEqual([a["body"] for a in alerts], ["new drift"])
        self.assertEqual(alerts[0]["name"], "Drift report")
        self.assertFalse(alerts[0]["open"])

    def test_open_failure_streak_collapses_and_survives_window(self):
        for h in (1, 2, 60):
            self.put(
                JOB_B,
                h,
                script_run("Self-heal", JOB_B, "PROBLEM %d" % h, status="script failed"),  # noqa: UP031
            )
        self.put(JOB_B, 70, script_run("Self-heal", JOB_B, status="silent (empty output)"))
        data = self.al.collect()
        self.assertEqual(len(data["alerts"]), 1)
        a = data["alerts"][0]
        self.assertTrue(a["open"])
        self.assertEqual(a["count"], 3)
        self.assertIsNone(a["expires"])
        self.assertIn(JOB_B, data["streaks"])

    def test_recovered_failure_is_a_normal_alert(self):
        self.put(JOB_B, 1, script_run("Self-heal", JOB_B, status="silent (empty output)"))
        self.put(JOB_B, 3, script_run("Self-heal", JOB_B, "PROBLEM", status="script failed"))
        data = self.al.collect()
        self.assertEqual(data["streaks"], {})
        self.assertEqual(data["alerts"][0]["kind"], "failure")
        self.assertFalse(data["alerts"][0]["open"])
        self.assertIsNotNone(data["alerts"][0]["expires"])

    # ack
    def test_ack_and_unack(self):
        self.put(JOB_B, 1, script_run("Self-heal", JOB_B, "PROBLEM", status="script failed"))
        aid = self.al.collect()["alerts"][0]["id"]
        self.al.ack([aid])
        self.assertEqual(
            self.al.get()["counts"], {"unacked": 0, "failing": 1, "acked": 1, "reports": 0}
        )
        self.al.ack([aid], "unack")
        self.assertEqual(self.al.get()["counts"]["unacked"], 1)
        with self.assertRaises(ValueError):
            self.al.ack(["../../etc"])

    # informational reports need no ack and never count in the badge
    def test_report_needs_no_ack_and_is_not_in_the_badge(self):
        self.put(JOB_A, 1, script_run("Drift", JOB_A, "new drift"))
        self.put(JOB_A, 3, agent_run(JOB_A, response="Two tickets moved."))
        data = self.al.get()
        self.assertEqual([a["kind"] for a in data["alerts"]], ["report", "report"])
        self.assertTrue(all(a["needs_ack"] is False for a in data["alerts"]))
        self.assertEqual(data["counts"], {"unacked": 0, "failing": 0, "acked": 0, "reports": 2})
        self.assertEqual(self.al.badge(), 0)
        # Acknowledging a report anyway does not move it into the acked count.
        self.al.ack([data["alerts"][0]["id"]])
        self.assertEqual(
            self.al.get()["counts"], {"unacked": 0, "failing": 0, "acked": 0, "reports": 2}
        )

    def test_only_failures_count_in_the_badge_and_raise_items(self):
        self.put(JOB_A, 1, script_run("Drift", JOB_A, "new drift"))
        self.put(JOB_B, 1, script_run("Self-heal", JOB_B, "PROBLEM", status="script failed"))
        self.put(JOB_B, 5, script_run("Self-heal", JOB_B, "old", status="silent (empty output)"))
        data = self.al.get()
        self.assertEqual(data["counts"]["unacked"], 1)
        self.assertEqual(data["counts"]["reports"], 1)
        self.assertEqual(self.al.badge(), 1)
        r = self.al.sync()
        self.assertEqual(r["failing"], 1)
        self.assertEqual(len(self.aa.action_items()), 1)
        # A recovered failure still needs an ack until the owner read it, a report never does.
        self.put(JOB_B, 0, script_run("Self-heal", JOB_B, status="silent (empty output)"))
        data = self.al.get()
        failed = [a for a in data["alerts"] if a["kind"] == "failure"]
        self.assertTrue(failed[0]["needs_ack"])
        self.assertEqual(data["counts"]["unacked"], 1)

    # sync to the Action Center store
    def test_sync_raises_once_then_closes_on_recovery(self):
        self.put(JOB_B, 1, script_run("Self-heal", JOB_B, "PROBLEM", status="script failed"))
        r = self.al.sync()
        self.assertEqual((r["failing"], r["raised_or_updated"], r["closed"]), (1, 1, 0))
        items = self.aa.action_items()
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["key"].startswith("auto-alert-" + JOB_B))
        self.assertEqual(items[0]["title"], "Self-heal is failing")
        # unchanged on the next tick: no rewrite
        self.assertEqual(self.al.sync()["raised_or_updated"], 0)
        # job recovers: item closes
        self.put(JOB_B, 0, script_run("Self-heal", JOB_B, status="silent (empty output)"))
        r = self.al.sync()
        self.assertEqual((r["failing"], r["closed"]), (0, 1))
        self.assertEqual(self.aa.action_items(), [])

    # failures are watched for every enabled job, reports only for listed jobs
    def test_unlisted_job_failure_is_watched_but_its_reports_are_not(self):
        job_c, job_d = "cccccccccccc", "dddddddddddd"
        (self.cron / "jobs.json").write_text(
            json.dumps(
                {
                    "jobs": [
                        {"id": JOB_A, "name": "Drift report"},
                        {"id": job_c, "name": "Core sync", "enabled": True},
                        {"id": job_d, "name": "Old one-shot", "enabled": False},
                    ]
                }
            )
        )
        self.put(job_c, 1, script_run("Core sync", job_c, "updated 0 files"))
        self.put(job_c, 2, script_run("Core sync", job_c, "boom", status="script failed"))
        self.put(job_d, 1, script_run("Old", job_d, "boom", status="script failed"))
        data = self.al.collect()
        # job_c recovered: its failure shows (not open), its normal report does not, job_d is disabled
        self.assertEqual(
            [(a["job"], a["kind"], a["open"]) for a in data["alerts"]], [(job_c, "failure", False)]
        )
        self.put(job_c, 0, script_run("Core sync", job_c, "boom again", status="script failed"))
        self.assertIn(job_c, self.al.collect()["streaks"])

    def test_ignore_failures_opts_a_job_out(self):
        (self.dash / "alert-sources.json").write_text(
            json.dumps({"jobs": [JOB_A], "ignore_failures": [JOB_B]})
        )
        self.put(JOB_B, 1, script_run("Self-heal", JOB_B, "PROBLEM", status="script failed"))
        self.assertEqual(self.al.collect()["alerts"], [])
        self.assertEqual(self.al.watched(), [JOB_A])


if __name__ == "__main__":
    unittest.main()
