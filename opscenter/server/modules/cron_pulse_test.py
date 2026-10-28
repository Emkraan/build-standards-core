#!/usr/bin/env python3
"""Tests for cron_pulse.py. Synthetic jobs.json, executions.db and output dirs in a scratch
folder, the Hermes CLI mocked. Nothing here touches the real cron store or starts a real run."""

from __future__ import annotations

import datetime as dt
import importlib
import json
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

NOW = dt.datetime.now(dt.timezone.utc)


def iso(minutes=0):
    return (NOW + dt.timedelta(minutes=minutes)).isoformat()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.scripts = t / "scripts"
        self.scripts.mkdir()
        (t / "output").mkdir()
        for k, v in {
            "CRONPULSE_JOBS": t / "jobs.json",
            "CRONPULSE_EXEC_DB": t / "executions.db",
            "CRONPULSE_OUTPUT": t / "output",
            "CRONPULSE_SCRIPTS": self.scripts,
            "CRONPULSE_CARD_MAP": t / "map.json",
            "CRONPULSE_RUN_LOGS": t / "logs",
        }.items():
            os.environ[k] = str(v)
        import cron_pulse

        self.cp = importlib.reload(cron_pulse)
        self.t = t
        self.jobs = []

    def tearDown(self):
        self.tmp.cleanup()

    def write_jobs(self):
        (self.t / "jobs.json").write_text(json.dumps({"jobs": self.jobs}))
        self.cp.invalidate()

    def job(self, jid, **kw):
        j = {
            "id": jid,
            "name": f"Job {jid}",
            "enabled": True,
            "state": "scheduled",
            "prompt": "",
            "schedule": {"display": "every 15m"},
            "next_run_at": iso(10),
            "last_run_at": iso(-5),
        }
        j.update(kw)
        self.jobs.append(j)
        return j

    def db(self, rows):
        con = sqlite3.connect(self.t / "executions.db")
        con.execute(
            "CREATE TABLE IF NOT EXISTS executions (id INTEGER PRIMARY KEY, job_id TEXT, source TEXT, pid INT, status TEXT, claimed_at TEXT, started_at TEXT, finished_at TEXT)"
        )
        for r in rows:
            con.execute(
                "INSERT INTO executions (job_id,source,pid,status,claimed_at,started_at,finished_at) VALUES (?,?,?,?,?,?,?)",
                r,
            )
        con.commit()
        con.close()

    def card_map(self, d):
        (self.t / "map.json").write_text(json.dumps(d))
        self.cp.invalidate()


class ParseTests(Base):
    def test_pr_loop_and_prompt_refs_and_branch_patterns(self):
        (self.scripts / "w.sh").write_text(
            'for pr in 347 348 361 362; do gh pr view "$pr" --repo owner/primary; done\n'
        )
        self.job(
            "aaaaaaaaaaaa",
            monitor_script="w.sh",
            prompt="Watch TKT-5284-desktop-pool and PR #351, also pull/352.",
        )
        self.write_jobs()
        r = self.cp.snapshot(fresh=True)["jobs"][0]
        self.assertEqual(r["prs"], [347, 348, 351, 352, 361, 362])
        self.assertEqual(r["branches"], ["TKT-5284-*"])
        self.assertEqual(r["repo"], "primary")
        self.assertTrue(r["monitor_gated"])

    def test_prompt_only_job_without_repo_is_not_a_watcher(self):
        self.job("bbbbbbbbbbbb", prompt="Morning briefing. Mention item #20 and #215.")
        self.write_jobs()
        self.assertEqual(self.cp.snapshot(fresh=True)["jobs"], [])

    def test_override_adds_lanes_and_can_turn_parsing_off(self):
        self.job("cccccccccccc", prompt="Review owner/primary PRs such as #12.")
        self.card_map(
            {
                "jobs": {
                    "cccccccccccc": {
                        "repo": "primary",
                        "lanes": ["engineer_pr", "bogus"],
                        "all_mine": True,
                        "auto": False,
                    }
                }
            }
        )
        self.write_jobs()
        r = self.cp.snapshot(fresh=True)["jobs"][0]
        self.assertEqual(r["prs"], [])
        self.assertEqual(r["lanes"], ["engineer_pr"])
        self.assertTrue(r["all_mine"])
        self.assertEqual(r["mapping"], "override")

    def test_disabled_job_never_watches(self):
        (self.scripts / "w.sh").write_text("for pr in 361; do :; done # owner/primary\n")
        self.job("dddddddddddd", monitor_script="w.sh", enabled=False, state="paused")
        self.write_jobs()
        snap = self.cp.snapshot(fresh=True)
        r = snap["jobs"][0]
        self.assertFalse(r["enabled"])
        self.assertIsNone(r["next_run_at"])
        out = self.cp.watcher_for(snap, "primary", "my_pr", pr=361)
        self.assertTrue(out["unwatched"])
        self.assertEqual(out["paused_job"], "Job dddddddddddd")

    def test_missing_files_do_not_raise(self):
        self.assertEqual(self.cp.snapshot(fresh=True)["jobs"], [])


class CardTests(Base):
    def setUp(self):
        super().setUp()
        (self.scripts / "w.sh").write_text(
            "for pr in 361 362; do gh pr view $pr --repo owner/primary; done\n"
        )
        self.job(
            "111111111111",
            name="Desktop watcher",
            monitor_script="w.sh",
            prompt="TKT-5284-desktop chain",
        )
        self.job("222222222222", name="platform PR gate", prompt="x")
        self.card_map(
            {
                "jobs": {
                    "222222222222": {
                        "repo": "primary",
                        "lanes": ["engineer_pr"],
                        "all_mine": True,
                        "auto": False,
                    }
                },
                "server_owned": {"owner_root": {"name": "Server", "cadence": "2h"}},
            }
        )
        self.write_jobs()

    def test_specific_pr_beats_lane_and_lists_others(self):
        w = self.cp.watcher_for(self.cp.snapshot(fresh=True), "primary", "my_pr", pr=361)
        self.assertEqual(w["watcher"]["id"], "111111111111")
        self.assertEqual([a["id"] for a in w["watcher"]["also"]], ["222222222222"])

    def test_branch_pattern_matches(self):
        w = self.cp.watcher_for(
            self.cp.snapshot(fresh=True), "primary", "engineer_pr", pr=999, branch="TKT-5284-pool-x"
        )
        self.assertEqual(w["watcher"]["id"], "111111111111")

    def test_lane_only_and_unwatched_and_server_owned(self):
        snap = self.cp.snapshot(fresh=True)
        self.assertEqual(
            self.cp.watcher_for(snap, "primary", "my_pr", pr=5)["watcher"]["id"], "222222222222"
        )
        self.assertTrue(self.cp.watcher_for(snap, "secondary", "my_pr", pr=5)["unwatched"])
        self.assertTrue(self.cp.watcher_for(snap, "primary", "privileged")["unwatched"])
        so = self.cp.watcher_for(snap, "primary", "owner_root")
        self.assertTrue(so["watcher"]["server"])
        self.assertFalse(so["unwatched"])

    def test_decorate_primary_tags_every_list(self):
        data = {
            "my_prs": [{"pr": 361, "branch": "x"}],
            "needs_me": [{"pr": 77, "sources": ["review", "tfplan"]}],
            "privileged": [{"key": "k"}],
            "owner_roots": {"items": [{"id": "r"}]},
            "runbook_releases": [],
        }
        out = self.cp.decorate_primary(data)
        self.assertEqual(out["my_prs"][0]["watcher"]["name"], "Desktop watcher")
        self.assertEqual(out["needs_me"][0]["watcher"]["id"], "222222222222")
        self.assertTrue(out["privileged"][0]["unwatched"])
        self.assertTrue(out["owner_roots"]["items"][0]["watcher"]["server"])
        self.assertEqual(len(out["cron_pulse"]["jobs"]), 2)
        self.assertNotIn("watcher", data["my_prs"][0])  # input untouched


class RunningTests(Base):
    def test_in_flight_row_means_running_and_finished_row_does_not(self):
        self.job("111111111111", prompt="owner/primary #55")
        self.write_jobs()
        self.db(
            [
                ("111111111111", "direct", 1, "running", iso(-2), iso(-2), None),
                ("111111111111", "scheduled", 1, "completed", iso(-30), iso(-30), iso(-29)),
            ]
        )
        self.assertTrue(self.cp.snapshot(fresh=True)["jobs"][0]["running"])
        self.assertEqual(self.cp.snapshot(fresh=True)["jobs"][0]["run_source"], "direct")

    def test_orphaned_rows_are_ignored(self):
        self.job("111111111111", prompt="owner/primary #55")
        self.write_jobs()
        self.db(
            [
                ("111111111111", "direct", 1, "running", iso(-60 * 24), iso(-60 * 24), None),
                ("111111111111", "scheduled", 1, "claimed", iso(-60), None, None),
            ]
        )
        self.assertFalse(self.cp.snapshot(fresh=True)["jobs"][0]["running"])

    def test_manual_run_at_is_queued(self):
        self.job("111111111111", prompt="owner/primary #55", manual_run_at=iso(0))
        self.write_jobs()
        r = self.cp.snapshot(fresh=True)["jobs"][0]
        self.assertTrue(r["queued"])
        self.assertFalse(r["running"])

    def test_no_db_is_not_running(self):
        self.job("111111111111", prompt="owner/primary #55")
        self.write_jobs()
        self.assertFalse(self.cp.snapshot(fresh=True)["jobs"][0]["running"])

    def test_silent_no_change_tick(self):
        (self.scripts / "w.sh").write_text("for pr in 361; do :; done # owner/primary\n")
        self.job("111111111111", monitor_script="w.sh")
        d = self.t / "output" / "111111111111"
        d.mkdir()
        stamp = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        (d / f"{stamp}.md").write_text("# Cron\n**Status:** no_change (agent run suppressed)\n")
        self.write_jobs()
        r = self.cp.snapshot(fresh=True)["jobs"][0]
        self.assertTrue(r["silent_no_change"])
        self.assertEqual(r["last_tick"]["kind"], "no_change")
        (d / "2099-01-01_00-00-00.md").write_text("# Cron\n**Status:** ok\nbody\n")
        self.assertFalse(self.cp.snapshot(fresh=True)["jobs"][0]["silent_no_change"])


class FakeProc:
    pid = 4242

    def __init__(self, rc=0):
        self.rc = rc

    def wait(self):
        return self.rc


class RunTests(Base):
    def setUp(self):
        super().setUp()
        self.job(
            "111111111111", prompt="owner/primary #55", deliver="origin", name="Desktop watcher"
        )
        self.job("222222222222", prompt="owner/primary #66", enabled=False, state="paused")
        self.write_jobs()
        self.calls = []

    def spawn(self, argv, cwd, log):
        self.calls.append((argv, cwd))
        return FakeProc()

    def test_run_without_note_uses_the_cli_and_never_touches_jobs_json(self):
        before = (self.t / "jobs.json").read_text()
        r = self.cp.run("111111111111", spawn=self.spawn)
        self.assertTrue(r["started"])
        self.assertTrue(r["job"]["queued"])
        argv, _ = self.calls[0]
        self.assertEqual(argv[1:], ["cron", "run", "111111111111"])
        self.assertEqual((self.t / "jobs.json").read_text(), before)

    def test_run_with_note_goes_through_the_event_entry_with_the_note(self):
        r = self.cp.run("111111111111", note="Focus on PR 361", spawn=self.spawn)
        self.assertTrue(r["with_note"])
        argv, cwd = self.calls[0]
        self.assertIn("execute_job_for_event", argv[2])
        self.assertNotIn(
            "111111111111", argv[2]
        )  # ids and notes travel as argv, never spliced into code
        self.assertEqual(argv[3:], ["111111111111", "Focus on PR 361"])
        self.assertEqual(cwd, os.environ.get("CRONPULSE_HERMES_SRC", self.cp.HERMES_SRC))

    def test_second_click_while_pending_does_not_spawn_again(self):
        self.cp.run("111111111111", spawn=self.spawn)
        r = self.cp.run("111111111111", spawn=self.spawn)
        self.assertTrue(r["already"])
        self.assertEqual(len(self.calls), 1)

    def test_running_job_is_not_started_again(self):
        self.db([("111111111111", "scheduled", 1, "running", iso(-1), iso(-1), None)])
        r = self.cp.run("111111111111", spawn=self.spawn)
        self.assertFalse(r["started"])
        self.assertEqual(self.calls, [])

    def test_refusals(self):
        for jid, note, code in [
            ("zzz", None, 400),
            ("333333333333", None, 404),
            ("222222222222", None, 409),
            ("111111111111", "x" * 601, 400),
            ("111111111111", "caf\u00e9", 400),
        ]:
            with self.assertRaises(self.cp.PulseError) as cm:
                self.cp.run(jid, note=note, spawn=self.spawn)
            self.assertEqual(cm.exception.code, code, (jid, note))
        self.assertEqual(self.calls, [])

    def test_cli_failure_surfaces_as_request_error(self):
        def spawn(argv, cwd, log):
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text("boom: no such job")
            return FakeProc(rc=2)

        self.cp.run("111111111111", spawn=spawn)
        r = {}
        for _ in range(50):
            time.sleep(0.05)
            r = self.cp.snapshot(fresh=True)["jobs"][0]
            if r["request_error"]:
                break
        self.assertIn("boom", r["request_error"])
        self.assertFalse(r["queued"])

    def test_pending_clears_once_last_run_moves_past_the_request(self):
        self.cp.run("111111111111", spawn=self.spawn)
        self.assertTrue(self.cp.snapshot(fresh=True)["jobs"][0]["queued"])
        self.jobs[0]["last_run_at"] = (
            dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=5)
        ).isoformat()
        self.write_jobs()
        self.assertFalse(self.cp.snapshot(fresh=True)["jobs"][0]["queued"])


if __name__ == "__main__":
    unittest.main()
