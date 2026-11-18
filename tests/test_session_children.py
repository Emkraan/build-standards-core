"""The session-children pane tracks every kind of background agent work, from synthetic data only."""

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import types
import unittest
from pathlib import Path

from support import ROOT, Work, load

PLUGIN = "hermes/plugins/session-children"
collect = load("session_children_collect_t", PLUGIN + "/collect.py")
store = load("session_children_store_t", PLUGIN + "/children_store.py")
hooks = load("session_children_init_t", PLUGIN + "/__init__.py")

# Where the agent's own source lives, read once before any test changes the agent home. Set
# HERMES_AGENT_SRC to point elsewhere. Tests that need it skip when it is absent.
AGENT_SRC = Path(
    os.environ.get("HERMES_AGENT_SRC")
    or (Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes")) / "hermes-agent")
)

NOW = 1795050000.0  # a fixed instant, so no test depends on the clock
SESSION_DDL = (
    "CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, parent_session_id TEXT, "
    "started_at REAL, ended_at REAL, end_reason TEXT, title TEXT, message_count INTEGER, "
    "tool_call_count INTEGER, last_activity_at REAL, last_activity_description TEXT)"
)
ASYNC_DDL = (
    "CREATE TABLE async_delegations (delegation_id TEXT PRIMARY KEY, origin_session TEXT, "
    "parent_session_id TEXT, state TEXT, dispatched_at REAL, completed_at REAL, updated_at REAL, "
    "event_json TEXT, result_json TEXT, task_json TEXT)"
)
WORK_DDL = (
    "CREATE TABLE work (ref TEXT, title TEXT, brief TEXT, session TEXT, chat TEXT, status TEXT, "
    "last TEXT, asked TEXT, created REAL, updated REAL, ended REAL, stopping INTEGER DEFAULT 0, "
    "engine TEXT, run TEXT)"
)


class Base(Work):
    def setUp(self):
        super().setUp()
        self.home = self.dir / "home"
        self.home.mkdir()
        old = os.environ.get("HERMES_HOME")
        os.environ["HERMES_HOME"] = str(self.home)
        for name in ("SESSION_CHILDREN_WORKSTREAM_DB", "SESSION_CHILDREN_STUCK_SECONDS"):
            os.environ.pop(name, None)
        self.addCleanup(self.restore_home, old)
        self.db = sqlite3.connect(str(self.home / "state.db"))
        self.db.row_factory = sqlite3.Row
        self.db.execute(SESSION_DDL)
        self.db.execute(ASYNC_DDL)
        self.addCleanup(self.db.close)

    @staticmethod
    def restore_home(old):
        if old is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = old

    def session(self, sid, **kw):
        row = {
            "source": "desktop",
            "parent_session_id": None,
            "started_at": NOW - 600,
            "ended_at": None,
            "end_reason": None,
            "title": None,
            "message_count": 4,
            "tool_call_count": 2,
            "last_activity_at": NOW - 30,
            "last_activity_description": "tool completed: terminal",
        }
        row.update(kw)
        cols = ["id"] + list(row)
        self.db.execute(
            "INSERT INTO sessions({}) VALUES ({})".format(
                ", ".join(cols), ", ".join("?" * len(cols))
            ),
            [sid] + list(row.values()),
        )
        self.db.commit()

    def registry(self, rows, sub="vendor"):
        path = self.home / sub
        path.mkdir(exist_ok=True)
        conn = sqlite3.connect(str(path / "work.db"))
        conn.execute(WORK_DDL)
        for r in rows:
            base = {
                "brief": "PLANTED-BRIEF",
                "last": "",
                "asked": None,
                "ended": None,
                "stopping": 0,
            }
            base.update(r)
            cols = list(base)
            conn.execute(
                "INSERT INTO work({}) VALUES ({})".format(
                    ", ".join(cols), ", ".join("?" * len(cols))
                ),
                list(base.values()),
            )
        conn.commit()
        conn.close()
        return path / "work.db"

    def by_ref(self, result):
        return {i["title"].split()[0]: i for i in result["items"]}


class Workstreams(Base):
    def test_every_status_maps_to_one_state_and_a_running_one_is_never_failed(self):
        self.session("chat1")
        self.session("s1")
        self.session("s2", last_activity_at=NOW - 3600)
        self.session("s3", ended_at=NOW - 100, end_reason="startup_orphan_reap")
        base = {"chat": "chat1", "created": NOW - 900, "updated": NOW - 30}
        self.registry(
            [
                dict(base, ref="W1", title="live one", session="s1", status="working"),
                dict(base, ref="W2", title="quiet one", session="s2", status="working"),
                dict(base, ref="W3", title="reaped one", session="s3", status="working"),
                dict(
                    base,
                    ref="W4",
                    title="asks",
                    session="s1",
                    status="needs_you",
                    asked="Pick a plan\nsecond line",
                ),
                dict(base, ref="W5", title="done one", session="s1", status="done", ended=NOW - 60),
                dict(
                    base, ref="W6", title="bad one", session="s1", status="failed", ended=NOW - 60
                ),
                dict(
                    base, ref="W7", title="stopped", session="s1", status="stopped", ended=NOW - 60
                ),
                dict(base, ref="W8", title="no session yet", session=None, status="starting"),
            ]
        )
        got = self.by_ref(collect.collect_workstreams(self.db, self.home, NOW))
        self.assertEqual(
            {k: v["state"] for k, v in got.items()},
            {
                "W1": "running",
                "W2": "stuck",
                "W3": "failed",
                "W4": "stuck",
                "W5": "finished",
                "W6": "failed",
                "W7": "finished",
                "W8": "running",
            },
        )
        self.assertEqual(got["W1"]["activity"], "tool completed: terminal")
        self.assertIsNone(got["W1"]["outcome"])
        self.assertIn("No activity for 60 min", got["W2"]["outcome"])
        self.assertEqual(got["W3"]["outcome"], "Session ended: startup_orphan_reap")
        self.assertEqual(got["W4"]["outcome"], "Waiting on you: Pick a plan")
        self.assertEqual(got["W7"]["outcome"], "Stopped")

    def test_the_brief_is_never_read_into_an_item(self):
        self.session("s1")
        self.registry(
            [
                {
                    "ref": "W1",
                    "title": "t",
                    "session": "s1",
                    "chat": "s1",
                    "status": "working",
                    "created": NOW - 10,
                    "updated": NOW - 5,
                }
            ]
        )
        text = json.dumps(collect.collect_workstreams(self.db, self.home, NOW))
        self.assertNotIn("PLANTED-BRIEF", text)

    def test_the_owning_chat_matches_any_segment_of_its_compression_lineage(self):
        self.session("c-old", end_reason="compression", ended_at=NOW - 500)
        self.session("c-new", parent_session_id="c-old")
        self.session("s1")
        self.registry(
            [
                {
                    "ref": "W1",
                    "title": "t",
                    "session": "s1",
                    "chat": "c-old",
                    "status": "working",
                    "created": NOW - 10,
                    "updated": NOW - 5,
                }
            ]
        )
        item = collect.collect_workstreams(self.db, self.home, NOW)["items"][0]
        self.assertTrue({"c-old", "c-new"} <= set(item["parents"]))

    def test_a_session_that_continues_through_compression_reports_the_newest_segment(self):
        self.session(
            "s-old", end_reason="compression", ended_at=NOW - 500, last_activity_at=NOW - 500
        )
        self.session("s-new", parent_session_id="s-old", last_activity_description="writing a file")
        self.registry(
            [
                {
                    "ref": "W1",
                    "title": "t",
                    "session": "s-old",
                    "chat": "x",
                    "status": "working",
                    "created": NOW - 900,
                    "updated": NOW - 5,
                }
            ]
        )
        item = collect.collect_workstreams(self.db, self.home, NOW)["items"][0]
        self.assertEqual(
            (item["state"], item["open_id"], item["activity"]),
            ("running", "s-new", "writing a file"),
        )

    def test_no_registry_says_so_and_returns_nothing(self):
        got = collect.collect_workstreams(self.db, self.home, NOW)
        self.assertEqual(got["items"], [])
        self.assertIn("No workstream registry", got["note"])

    def test_a_registry_with_an_unknown_layout_is_unavailable_never_wrong(self):
        path = self.home / "vendor"
        path.mkdir()
        conn = sqlite3.connect(str(path / "work.db"))
        conn.execute("CREATE TABLE work (ref TEXT, title TEXT)")
        conn.commit()
        conn.close()
        os.environ["SESSION_CHILDREN_WORKSTREAM_DB"] = str(path / "work.db")
        with self.assertRaises(collect.Unavailable):
            collect.collect_workstreams(self.db, self.home, NOW)

    def test_a_wal_file_without_its_index_opens_and_is_not_changed(self):
        path = self.registry(
            [
                {
                    "ref": "W1",
                    "title": "t",
                    "session": None,
                    "chat": None,
                    "status": "working",
                    "created": NOW - 5,
                    "updated": NOW - 5,
                }
            ]
        )
        conn = sqlite3.connect(str(path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
        for extra in ("-wal", "-shm"):
            if Path(str(path) + extra).exists():
                Path(str(path) + extra).unlink()
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        got = collect.collect_workstreams(self.db, self.home, NOW)
        self.assertEqual(len(got["items"]), 1)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)


class Runners(Base):
    def link(self, **kw):
        row = {
            "id": 1,
            "pid": 4242,
            "child_id": "r1",
            "tip_id": "r1",
            "parent_id": "chat1",
            "started_at": NOW - 300,
            "updated_at": NOW - 20,
            "finished_at": None,
            "outcome": None,
            "archived": 0,
            "vis": 1,
        }
        row.update(kw)
        return row

    def run_one(self, link, alive=True):
        calls = {"running": 0, "lost": 0}
        got = collect.collect_runners(
            self.db,
            [link],
            NOW,
            is_alive=lambda pid: alive,
            on_running=lambda link: calls.__setitem__("running", calls["running"] + 1),
            on_lost=lambda link: calls.__setitem__("lost", calls["lost"] + 1),
        )
        return got["items"][0], calls

    def test_states(self):
        self.session("chat1")
        self.session("r1", title="build a thing")
        it, calls = self.run_one(self.link())
        self.assertEqual(
            (it["state"], it["title"], calls["running"]), ("running", "build a thing", 1)
        )
        it, calls = self.run_one(self.link(), alive=False)
        self.assertEqual(
            (it["state"], it["outcome"], calls["lost"]),
            ("failed", "Process ended without finishing", 1),
        )
        it, _ = self.run_one(self.link(finished_at=NOW - 10, outcome="ok", archived=1))
        self.assertEqual((it["state"], it["outcome"]), ("finished", "Finished cleanly, archived"))
        it, _ = self.run_one(self.link(finished_at=NOW - 10, outcome="interrupted"))
        self.assertEqual((it["state"], it["outcome"]), ("failed", "Interrupted"))
        it, _ = self.run_one(self.link(finished_at=NOW - 10, outcome="failed"))
        self.assertEqual(it["state"], "failed")

    def test_alive_but_quiet_is_stuck_and_never_failed(self):
        self.session("r1", last_activity_at=NOW - 2400)
        it, _ = self.run_one(self.link())
        self.assertEqual(it["state"], "stuck")
        self.assertIn("40 min", it["outcome"])

    def test_the_stuck_window_can_be_set_by_environment(self):
        os.environ["SESSION_CHILDREN_STUCK_SECONDS"] = "60"
        self.addCleanup(os.environ.pop, "SESSION_CHILDREN_STUCK_SECONDS", None)
        mod = load("session_children_collect_env", PLUGIN + "/collect.py")
        self.assertEqual(mod.STUCK_SECONDS, 60)


class Subagents(Base):
    def delegation(self, key, state, **kw):
        row = {
            "origin_session": "chat1",
            "parent_session_id": "chat1",
            "dispatched_at": NOW - 300,
            "completed_at": None,
            "updated_at": NOW - 10,
            "task_json": json.dumps({"goal": "look up the thing\nmore", "role": "leaf"}),
            "event_json": None,
            "result_json": None,
        }
        row.update(kw)
        cols = ["delegation_id", "state"] + list(row)
        self.db.execute(
            "INSERT INTO async_delegations({}) VALUES ({})".format(
                ", ".join(cols), ", ".join("?" * len(cols))
            ),
            [key, state] + list(row.values()),
        )
        self.db.commit()

    def test_delegation_states_and_the_result_text_is_never_read(self):
        self.delegation("a", "running")
        self.delegation("b", "stalling")
        big = json.dumps({"results": [{"status": "completed", "summary": "PLANTED-SUMMARY" * 50}]})
        self.delegation("c", "completed", completed_at=NOW - 20, result_json=big)
        self.delegation(
            "d",
            "completed",
            completed_at=NOW - 20,
            result_json=json.dumps({"results": [{"status": "failed", "summary": "x"}]}),
        )
        self.delegation(
            "e", "error", completed_at=NOW - 20, event_json=json.dumps({"error": "boom\ntrace"})
        )
        self.delegation("f", "unknown", completed_at=None)
        got = {i["id"].split(":")[1]: i for i in collect.collect_async_subagents(self.db, NOW)}
        self.assertEqual(
            {k: v["state"] for k, v in got.items()},
            {
                "a": "running",
                "b": "stuck",
                "c": "finished",
                "d": "failed",
                "e": "failed",
                "f": "failed",
            },
        )
        self.assertEqual(got["a"]["title"], "look up the thing")
        self.assertEqual(got["e"]["outcome"], "boom")
        self.assertIn("Owner process ended", got["f"]["outcome"])
        self.assertNotIn("PLANTED-SUMMARY", json.dumps(list(got.values())))

    def test_an_old_finished_delegation_is_not_selected(self):
        self.delegation("old", "completed", completed_at=NOW - 8 * 3600, updated_at=NOW - 8 * 3600)
        self.assertEqual(collect.collect_async_subagents(self.db, NOW), [])

    def test_a_store_without_json_functions_still_lists_delegations(self):
        self.delegation("a", "running")
        original = collect._ASYNC_JSON
        collect._ASYNC_JSON = original.replace("json_extract(", "json_extractx(")
        self.addCleanup(setattr, collect, "_ASYNC_JSON", original)
        got = collect.collect_async_subagents(self.db, NOW)
        self.assertEqual([(i["state"], i["title"]) for i in got], [("running", "Subagent task")])


class Journal(Base):
    def test_the_hooks_journal_a_subagent_start_and_stop(self):
        hooks._on_subagent_start(
            parent_session_id="chat1",
            child_session_id="k1",
            child_role="leaf",
            child_goal="check the logs\nwith detail " + "x" * 300,
            child_subagent_id="sa-1",
        )
        rows = store.connect().execute("SELECT * FROM subagents").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["goal"][:15], "check the logs")
        self.assertNotIn("detail", rows[0]["goal"])
        self.assertLessEqual(len(rows[0]["goal"]), 120)
        self.assertIsNone(rows[0]["finished_at"])
        hooks._on_subagent_stop(
            parent_session_id="chat1",
            child_session_id="k1",
            child_status="completed",
            duration_ms=5,
        )
        row = store.connect().execute("SELECT * FROM subagents").fetchone()
        self.assertEqual((row["status"], row["finished_at"] is not None), ("completed", True))

    def test_a_stop_without_a_child_id_closes_the_newest_open_row_of_that_parent(self):
        hooks._on_subagent_start(parent_session_id="chat1", child_session_id=None, child_goal="one")
        hooks._on_subagent_start(parent_session_id="chat1", child_session_id=None, child_goal="two")
        hooks._on_subagent_stop(
            parent_session_id="chat1", child_session_id=None, child_status="failed"
        )
        rows = {r["goal"]: r for r in store.connect().execute("SELECT * FROM subagents")}
        self.assertIsNone(rows["one"]["finished_at"])
        self.assertEqual(rows["two"]["status"], "failed")

    def test_a_hook_without_a_parent_records_nothing_and_never_raises(self):
        hooks._on_subagent_start(child_goal="x")
        hooks._on_subagent_stop(child_status="completed")
        self.assertEqual(store.connect().execute("SELECT count(*) FROM subagents").fetchone()[0], 0)

    def journal(self):
        return collect.journal_rows(store.connect(), time.time() + 1)

    def test_a_journal_row_shows_running_failed_or_finished(self):
        self.session("chat1")
        hooks._on_subagent_start(
            parent_session_id="chat1", child_session_id="k1", child_goal="alive one"
        )
        hooks._on_subagent_start(
            parent_session_id="chat1", child_session_id="k2", child_goal="done one"
        )
        hooks._on_subagent_stop(
            parent_session_id="chat1", child_session_id="k2", child_status="completed"
        )
        hooks._on_subagent_start(
            parent_session_id="chat1", child_session_id="k3", child_goal="bad one"
        )
        hooks._on_subagent_stop(
            parent_session_id="chat1", child_session_id="k3", child_status="interrupted"
        )
        now = time.time() + 1
        got = {
            i["title"]: i
            for i in collect.collect_journal_subagents(
                self.db, self.journal(), [], [], now, is_alive=lambda pid: True
            )
        }
        self.assertEqual(
            {k: v["state"] for k, v in got.items()},
            {"alive one": "running", "done one": "finished", "bad one": "failed"},
        )
        self.assertEqual(got["bad one"]["outcome"], "Subagent reported: interrupted")
        dead = {
            i["title"]: i
            for i in collect.collect_journal_subagents(
                self.db, self.journal(), [], [], now, is_alive=lambda pid: False
            )
        }
        self.assertEqual(dead["alive one"]["state"], "failed")
        self.assertEqual(dead["alive one"]["outcome"], "Process ended without finishing")

    def test_a_row_that_overlaps_a_background_delegation_of_the_same_parent_is_skipped(self):
        hooks._on_subagent_start(
            parent_session_id="chat1", child_session_id="k1", child_goal="same work"
        )
        hooks._on_subagent_start(
            parent_session_id="child-of-chat1", child_session_id="k2", child_goal="nested"
        )
        now = time.time()
        span = {
            "origin_session": "chat1",
            "parent_session_id": "chat1",
            "dispatched_at": now - 30,
            "completed_at": None,
        }
        got = collect.collect_journal_subagents(
            self.db, self.journal(), [], [span], now + 1, is_alive=lambda pid: True
        )
        self.assertEqual([i["title"] for i in got], ["nested"])

    def test_the_hooks_the_plugin_registers_are_real_agent_hooks(self):
        names = []
        hooks.register(types.SimpleNamespace(register_hook=lambda name, fn: names.append(name)))
        self.assertEqual(
            sorted(names),
            [
                "on_session_end",
                "on_session_finalize",
                "on_session_start",
                "subagent_start",
                "subagent_stop",
            ],
        )
        agent_plugins = AGENT_SRC
        probe = (
            "import sys\n"
            f"sys.path.insert(0, {str(agent_plugins)!r})\n"
            "from hermes_cli.plugins import VALID_HOOKS\n"
            f"print(sorted(set({names!r}) - VALID_HOOKS))"
        )
        py = agent_plugins / "venv" / "bin" / "python"
        if not py.exists():
            self.skipTest("not checked: the agent is not installed here")
        r = subprocess.run([str(py), "-c", probe], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            self.skipTest("not checked: the agent's plugin module did not import")
        self.assertEqual(r.stdout.strip(), "[]")


class Processes(Base):
    def write(self, rel, data):
        path = self.home / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf8")
        return path

    def test_running_finished_and_failed_with_no_output_or_arguments_leaked(self):
        self.session("chat1")
        self.write(
            "processes.json",
            [
                {
                    "session_id": "proc_run",
                    "command": "cd /w && npm test --token PLANTED-ARG",
                    "pid": 11,
                    "started_at": NOW - 100,
                    "parent_session_id": "chat1",
                },
                {
                    "session_id": "proc_dead",
                    "command": "python3 job.py",
                    "pid": 12,
                    "started_at": NOW - 100,
                    "parent_session_id": "chat1",
                },
            ],
        )
        done = {
            "started_at": NOW - 500,
            "parent_session_id": "chat1",
            "output": "PLANTED-OUTPUT",
            "completion_reason": "exited",
        }
        self.write(
            "logs/process-results/proc_ok.json",
            dict(done, id="proc_ok", command="make build", exit_code=0),
        )
        self.write(
            "logs/process-results/proc_bad.json",
            dict(done, id="proc_bad", command="pytest -x", exit_code=1),
        )
        self.write(
            "logs/process-results/proc_kill.json",
            dict(
                done, id="proc_kill", command="sleep 99", exit_code=-15, completion_reason="killed"
            ),
        )
        got = collect.collect_processes(self.db, self.home, NOW + 5, is_alive=lambda pid: pid == 11)
        items = {i["id"].split(":")[1]: i for i in got["items"]}
        self.assertEqual(
            {k: v["state"] for k, v in items.items()},
            {
                "proc_run": "running",
                "proc_dead": "failed",
                "proc_ok": "finished",
                "proc_bad": "failed",
                "proc_kill": "failed",
            },
        )
        self.assertEqual(items["proc_run"]["title"], "npm test")
        self.assertEqual(items["proc_bad"]["outcome"], "Exit 1")
        self.assertEqual(items["proc_kill"]["outcome"], "Exit -15 (killed)")
        self.assertIn("exit status not recorded", items["proc_dead"]["outcome"])
        text = json.dumps(got)
        self.assertNotIn("PLANTED-OUTPUT", text)
        self.assertNotIn("PLANTED-ARG", text)

    def test_a_process_with_a_retained_result_is_not_listed_twice(self):
        self.write(
            "processes.json",
            [{"session_id": "proc_x", "command": "a", "pid": 1, "started_at": NOW - 9}],
        )
        self.write(
            "logs/process-results/proc_x.json",
            {"id": "proc_x", "command": "a", "exit_code": 0, "started_at": NOW - 9},
        )
        got = collect.collect_processes(self.db, self.home, NOW, is_alive=lambda pid: True)
        self.assertEqual([i["state"] for i in got["items"]], ["finished"])

    def test_a_process_is_never_stuck_because_its_activity_is_not_recorded(self):
        self.write(
            "processes.json",
            [{"session_id": "proc_old", "command": "a", "pid": 1, "started_at": NOW - 99999}],
        )
        got = collect.collect_processes(self.db, self.home, NOW, is_alive=lambda pid: True)
        item = got["items"][0]
        self.assertEqual((item["state"], item["activity_at"]), ("running", None))

    def test_no_registry_files_say_so(self):
        self.assertIn(
            "No process registry", collect.collect_processes(self.db, self.home, NOW)["note"]
        )

    def test_a_checkpoint_with_an_unexpected_layout_is_unavailable(self):
        self.write("processes.json", {"not": "a list"})
        with self.assertRaises(collect.Unavailable):
            collect.collect_processes(self.db, self.home, NOW)

    def test_command_title_skips_wrapper_steps_and_shows_no_arguments(self):
        t = collect.command_title
        self.assertEqual(
            t("cd /x/y && python3 ~/a/b.py --flag value" + chr(59) + " echo DONE_EXIT=$?"),
            "python3 b.py",
        )
        self.assertEqual(t("bash -lc 'run' | tee out"), "bash run")
        self.assertEqual(t(""), "Background process")
        self.assertEqual(t(None), "Background process")
        self.assertLessEqual(len(t("x" * 500)), 60)


class Retention(unittest.TestCase):
    def entry(self, state, started, finished=None):
        return collect.item("process", "k", "t", state, started, [], finished_at=finished)

    def test_windows(self):
        k = collect.keep
        self.assertTrue(k(self.entry("running", NOW - 99999), NOW))
        self.assertTrue(k(self.entry("stuck", NOW - 99999), NOW))
        self.assertTrue(k(self.entry("finished", NOW - 900, NOW - 600), NOW))
        self.assertFalse(k(self.entry("finished", NOW - 4000, NOW - 1900), NOW))
        self.assertTrue(k(self.entry("failed", NOW - 9000, NOW - 7200), NOW))
        self.assertFalse(k(self.entry("failed", NOW - 30000, NOW - 25000), NOW))


class Summary(Base):
    """The whole route, with the web framework stubbed (it comes with the agent, not with this repo)."""

    def api(self):
        saved = sys.modules.get("fastapi")
        router = types.SimpleNamespace(get=lambda path: lambda fn: fn)
        sys.modules["fastapi"] = types.SimpleNamespace(APIRouter=lambda: router)
        self.addCleanup(
            lambda: (
                sys.modules.__setitem__("fastapi", saved)
                if saved
                else sys.modules.pop("fastapi", None)
            )
        )
        return load("session_children_api_t", PLUGIN + "/dashboard/plugin_api.py")

    def seed(self):
        self.session("c-old", end_reason="compression", ended_at=NOW - 500)
        self.session("c-new", parent_session_id="c-old")
        self.session("w1")
        self.session("r1", title="runner job")
        base = {"chat": "c-new", "created": NOW - 900, "updated": NOW - 30}
        self.registry([dict(base, ref="W1", title="long job", session="w1", status="working")])
        conn = store.connect()
        conn.execute(
            "INSERT INTO links(pid, child_id, tip_id, parent_id, started_at, updated_at) VALUES (?,?,?,?,?,?)",
            (os.getpid(), "r1", "r1", "c-new", NOW - 300, NOW - 20),
        )
        conn.commit()
        conn.close()
        self.db.execute(
            "INSERT INTO async_delegations(delegation_id, origin_session, parent_session_id, state, "
            "dispatched_at, updated_at, task_json) VALUES ('d1','c-old','c-old','running',?,?,?)",
            (NOW - 200, NOW - 10, json.dumps({"goal": "quick lookup"})),
        )
        self.db.commit()
        path = self.home / "processes.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "session_id": "proc_a",
                        "command": "make test",
                        "pid": os.getpid(),
                        "started_at": NOW - 50,
                        "parent_session_id": "c-old",
                    }
                ]
            ),
            encoding="utf8",
        )

    def test_one_payload_with_all_four_sections_keyed_by_the_whole_lineage(self):
        self.seed()
        api = self.api()
        out = api.build_summary(self.db, NOW)
        self.assertEqual(
            {k: v["ok"] for k, v in out["sections"].items()},
            {"workstream": True, "runner": True, "subagent": True, "process": True},
        )
        self.assertEqual(
            sorted(i["kind"] for i in out["all"]), ["process", "runner", "subagent", "workstream"]
        )
        self.assertEqual(out["running"], 4)
        self.assertEqual(out["attention"], 0)
        for sid in ("c-old", "c-new"):
            self.assertEqual(len(out["by_parent"][sid]), 4, sid)
        self.assertNotIn("parents", out["all"][0])
        self.assertEqual(out["by_child"]["r1"]["parent_id"], "c-new")

    def test_failed_and_stuck_sort_first(self):
        self.seed()
        self.db.execute("UPDATE sessions SET last_activity_at=? WHERE id='w1'", (NOW - 9000,))
        self.db.commit()
        out = self.api().build_summary(self.db, NOW)
        self.assertEqual(out["all"][0]["state"], "stuck")
        self.assertEqual(out["attention"], 1)
        self.assertEqual(out["running"], 3)

    def test_one_broken_source_is_reported_and_the_others_still_show(self):
        self.seed()
        (self.home / "processes.json").write_text("{not json", encoding="utf8")
        out = self.api().build_summary(self.db, NOW)
        self.assertFalse(out["sections"]["process"]["ok"])
        self.assertTrue(out["sections"]["process"]["note"].startswith("Unavailable:"))
        self.assertTrue(out["sections"]["workstream"]["ok"])
        self.assertEqual(
            sorted(i["kind"] for i in out["all"]), ["runner", "subagent", "workstream"]
        )

    def test_the_route_answers_when_the_session_store_is_missing(self):
        self.db.close()
        os.remove(str(self.home / "state.db"))
        api = self.api()
        out = api.summary()
        self.assertEqual(out["all"], [])
        self.assertTrue(all(not s["ok"] for s in out["sections"].values()))

    def test_the_summary_never_writes_to_the_session_store(self):
        self.seed()
        self.db.close()
        path = self.home / "state.db"
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        api = self.api()
        conn = api._state_db()
        try:
            api.build_summary(conn, NOW)
        finally:
            conn.close()
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
        self.db = sqlite3.connect(str(path))


class AgentSchema(Base):
    """Prove the queries against the agent's own schema when the agent is installed here."""

    def test_every_column_and_query_exists_in_the_real_session_store(self):
        py = AGENT_SRC / "venv" / "bin" / "python"
        src = AGENT_SRC
        if not py.exists():
            self.skipTest("not checked: the agent is not installed here")
        scratch = self.dir / "agent-home"
        scratch.mkdir()
        probe = (
            "import json, sys, sqlite3\n"
            f"sys.path.insert(0, {str(src)!r})\n"
            "import hermes_state\n"
            "db = hermes_state.SessionDB()\n"
            "path = str(db.db_path) if hasattr(db, 'db_path') else None\n"
            "db.close()\n"
            "print(json.dumps(path))\n"
        )
        env = dict(os.environ, HERMES_HOME=str(scratch))
        r = subprocess.run(
            [str(py), "-c", probe], capture_output=True, text=True, timeout=120, env=env
        )
        if r.returncode != 0:
            self.skipTest("not checked: the agent's session store did not open in a scratch home")
        found = list(scratch.glob("*.db"))
        self.assertTrue(found, r.stdout + r.stderr)
        conn = sqlite3.connect(str(scratch / "state.db"))
        conn.row_factory = sqlite3.Row
        cols = {x[1] for x in conn.execute("PRAGMA table_info(sessions)")}
        wanted = {c.strip() for c in collect.SESSION_COLS.split(",")}
        self.assertEqual(wanted - cols, set())
        acols = {x[1] for x in conn.execute("PRAGMA table_info(async_delegations)")}
        self.assertTrue(
            {
                "delegation_id",
                "origin_session",
                "parent_session_id",
                "state",
                "dispatched_at",
                "completed_at",
                "updated_at",
                "task_json",
                "event_json",
                "result_json",
            }
            <= acols
        )
        self.assertEqual(collect.collect_async_subagents(conn, NOW), [])
        self.assertEqual(collect.async_spans(conn, NOW), [])
        self.assertEqual(collect.collect_processes(conn, scratch, NOW)["items"], [])
        conn.close()


NODE = shutil.which("node")
JS = (ROOT / "hermes" / "desktop-plugins" / "session-children" / "plugin.js").read_text(
    encoding="utf8"
)


def helpers():
    start = JS.index("// BEGIN pure helpers")
    end = JS.index("// END pure helpers")
    return JS[start:end]


def run_js(expr):
    prog = helpers() + "\nconsole.log(JSON.stringify(" + expr + "))\n"
    r = subprocess.run(
        [NODE, "--input-type=module", "-e", prog], capture_output=True, text=True, timeout=60
    )
    if r.returncode != 0:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


@unittest.skipUnless(NODE, "not checked: node is not installed here")
class Pane(unittest.TestCase):
    def test_times_are_eastern_with_the_abbreviation_never_utc(self):
        winter = 1795050000  # 8:00 PM EST on 2026-11-18
        summer = 1783170000  # 9:00 AM EDT on 2026-07-04
        later = winter + 86400 * 2
        out = run_js(
            f"[formatEt({winter}, {winter}*1000), formatEt({summer}, {summer}*1000), formatEt({winter}, {later}*1000)]"
        )
        self.assertEqual(out[0], "8:00 PM EST")
        self.assertEqual(out[1], "9:00 AM EDT")
        self.assertEqual(out[2], "Nov 18, 8:00 PM EST")
        for text in out:
            self.assertNotIn("UTC", text)
            self.assertNotIn("GMT", text)

    def test_the_four_sections_come_in_the_agreed_order(self):
        self.assertEqual(run_js("KIND_ORDER"), ["workstream", "runner", "subagent", "process"])
        self.assertEqual(
            run_js("KIND_ORDER.map(k => KIND_TITLES[k])"),
            ["Workstreams", "Headless runners", "Subagents", "Background processes"],
        )

    def test_running_is_never_red_and_failed_is(self):
        self.assertEqual(run_js("COLORS.running"), "var(--ui-accent)")
        self.assertNotEqual(run_js("COLORS.running"), run_js("COLORS.failed"))
        self.assertEqual(run_js("COLORS.failed"), "var(--ui-danger)")
        self.assertNotEqual(run_js("COLORS.stuck"), run_js("COLORS.failed"))

    def test_rows_group_by_kind_and_attention_items_lead(self):
        items = (
            "[{kind:'process',state:'finished',started_at:1,id:'a'},{kind:'process',state:'running',started_at:2,id:'b'},"
            "{kind:'process',state:'stuck',started_at:0,id:'c'},{kind:'process',state:'failed',started_at:3,id:'d'},"
            "{kind:'subagent',state:'running',started_at:1,id:'e'}]"
        )
        out = run_js(
            f"(() => {{\n const g = groupByKind({items})\n return [g.process.map(i => i.id), g.subagent.length, g.workstream.length]\n}})()"
        )
        self.assertEqual(out, [["c", "d", "b", "a"], 1, 0])

    def test_only_old_finished_rows_fade(self):
        now = 2000000
        old, recent = now - 1000, now - 10
        out = run_js(
            f"[isFaded({{state:'finished',finished_at:{old}}},{now}*1000),"
            f" isFaded({{state:'finished',finished_at:{recent}}},{now}*1000),"
            f" isFaded({{state:'failed',finished_at:1}},{now}*1000), isFaded({{state:'stuck'}},{now}*1000)]"
        )
        self.assertEqual(out, [True, False, False, False])

    def test_the_detail_line_says_when_it_started_when_it_was_last_active_and_what_happened(self):
        t = 1795050000
        out = run_js(
            f"[detailText({{state:'stuck',started_at:{t - 3000},activity_at:{t - 2400},"
            f"outcome:'No activity for 40 min'}},{t}*1000),"
            f" detailText({{state:'running',started_at:{t - 100},activity_at:null}},{t}*1000),"
            f" detailText({{state:'failed',started_at:{t - 100},finished_at:{t - 10},"
            f"outcome:'Exit 1'}},{t}*1000)]"
        )
        self.assertIn("EST", out[0])
        self.assertIn("Active", out[0])
        self.assertIn("40m ago", out[0])
        self.assertTrue(out[0].endswith("No activity for 40 min"))
        self.assertIn("Last activity not recorded", out[1])
        self.assertIn("Ended", out[2])
        self.assertTrue(out[2].endswith("Exit 1"))

    def test_the_source_is_valid_module_syntax(self):
        scratch = ROOT / ".test-work"
        scratch.mkdir(exist_ok=True)
        path = scratch / "plugin-check.mjs"
        self.addCleanup(lambda: path.unlink() if path.exists() else None)
        path.write_text(JS, encoding="utf8")
        r = subprocess.run([NODE, "--check", str(path)], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)


class Shipped(unittest.TestCase):
    def test_the_manifest_and_the_plugin_agree(self):
        yaml_text = (ROOT / PLUGIN / "plugin.yaml").read_text(encoding="utf8")
        manifest = json.loads(
            (ROOT / PLUGIN / "dashboard" / "manifest.json").read_text(encoding="utf8")
        )
        version = [
            line.split(":", 1)[1].strip()
            for line in yaml_text.splitlines()
            if line.startswith("version:")
        ][0]
        self.assertEqual(manifest["version"], version)
        for hook in (
            "on_session_start",
            "on_session_end",
            "on_session_finalize",
            "subagent_start",
            "subagent_stop",
        ):
            self.assertIn("  - " + hook, yaml_text)

    def test_the_shipped_text_has_no_dash_semicolon_or_non_ascii(self):
        for rel in (PLUGIN, "hermes/desktop-plugins/session-children"):
            for path in (ROOT / rel).rglob("*"):
                if path.is_file() and path.suffix in (".py", ".js", ".yaml", ".json"):
                    text = path.read_text(encoding="utf8")
                    self.assertTrue(text.isascii(), str(path))
                    if path.suffix == ".py":
                        import tokenize

                        with open(str(path), "rb") as fh:
                            for tok in tokenize.tokenize(fh.readline):
                                self.assertFalse(
                                    tok.type == tokenize.OP and tok.string == chr(59), str(path)
                                )


if __name__ == "__main__":
    unittest.main()
