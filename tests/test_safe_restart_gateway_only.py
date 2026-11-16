import json
import os
import time
import unittest
import urllib.error
from unittest import mock

from support import Work, load

sr = load("safe_hermes_restart", "hermes/safe-restart/safe_hermes_restart.py")
ex = load("safe_hermes_restart_exec", "hermes/safe-restart/safe_hermes_restart_exec.py")


def health(**over):
    """A synthetic gateway health read in the shape of the detailed health route."""
    h = {
        "gateway_busy": False,
        "gateway_drainable": True,
        "active_agents": 0,
        "readiness": {
            "checks": {
                "background_queues": {
                    "active_api_runs": 0,
                    "process_completions": 0,
                    "active_delegations": 0,
                }
            }
        },
    }
    h.update(over)
    return h


class GatewayReasons(unittest.TestCase):
    def reasons(self, h, **kw):
        return sr.gateway_reasons(lambda: h, **kw)

    def test_quiet_gateway_is_idle(self):
        self.assertEqual(self.reasons(health()), [])

    def test_agents_runs_and_queues_are_busy(self):
        h = health(active_agents=2)
        h["readiness"]["checks"]["background_queues"].update(
            active_api_runs=1, process_completions=3, active_delegations=1
        )
        out = self.reasons(h)
        self.assertEqual(len(out), 4)
        self.assertIn("gateway has 2 agent runs in flight", out)
        self.assertIn("gateway has 1 API run in flight", out)

    def test_busy_flag_alone_is_busy(self):
        self.assertEqual(self.reasons(health(gateway_busy=True)), ["gateway reports it is busy"])

    def test_not_drainable_is_busy(self):
        self.assertEqual(
            self.reasons(health(gateway_drainable=False)), ["gateway cannot drain right now"]
        )

    def test_unreadable_is_busy_never_idle(self):
        for exc in (
            urllib.error.URLError("refused"),
            RuntimeError("no key"),
            ValueError("bad json"),
        ):
            with self.subTest(exc=type(exc).__name__):

                def read(exc=exc):
                    raise exc

                out = sr.gateway_reasons(read)
                self.assertEqual(len(out), 1)
                self.assertTrue(out[0].startswith("cannot read the gateway health"))

    def test_a_short_or_odd_read_is_busy(self):
        self.assertEqual(self.reasons({}), ["gateway health carries no busy flag"])
        self.assertEqual(self.reasons([]), ["gateway health carries no busy flag"])

    def test_tick_read_skips_the_counts_a_cron_run_may_cause(self):
        busy = health(gateway_busy=True, active_agents=1)
        self.assertEqual(self.reasons(busy, agents=False), [])
        self.assertEqual(
            self.reasons(health(gateway_drainable=False), agents=False),
            ["gateway cannot drain right now"],
        )


class Mode(Work):
    def test_gateway_only_follows_the_backend_label(self):
        path = self.dir / "backend"
        self.assertTrue(sr.gateway_only(str(path)))
        path.write_text("\n")
        self.assertTrue(sr.gateway_only(str(path)))
        path.write_text("ai.hermes.backend\n")
        self.assertFalse(sr.gateway_only(str(path)))

    def test_key_is_read_from_the_env_file_and_absent_means_none(self):
        env = self.dir / "env"
        env.write_text("OTHER=1\nAPI_SERVER_KEY='synthetic-key-value'\n")
        self.assertEqual(sr.api_key(str(env)), "synthetic-key-value")
        self.assertIsNone(sr.api_key(str(self.dir / "absent")))
        env.write_text("OTHER=1\n")
        self.assertIsNone(sr.api_key(str(env)))


class AppBackends(Work):
    def ledger(self, entries):
        path = self.dir / "ledger.json"
        path.write_text(json.dumps(entries))
        return str(path)

    def own(self, **over):
        e = {
            "pid": os.getpid(),
            "create_time": sr.started_at(os.getpid()),
            "purpose": "serve",
            "host": "127.0.0.1",
            "port": 58005,
            "isolated": False,
        }
        e.update(over)
        return e

    def test_missing_ledger_means_none(self):
        self.assertEqual(sr.app_backends(str(self.dir / "absent.json")), [])

    def test_unreadable_ledger_is_an_error_and_busy(self):
        path = self.dir / "ledger.json"
        path.write_text("not json")
        with self.assertRaises(ValueError):
            sr.app_backends(str(path))
        out = sr.backend_reasons(str(path))
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].startswith("spawn ledger unreadable"))

    def test_live_matching_entry_is_found(self):
        found = sr.app_backends(self.ledger([self.own()]))
        self.assertEqual(found, [{"pid": os.getpid(), "port": 58005}])

    def test_reused_pid_is_not_a_backend(self):
        skewed = self.own(create_time=sr.started_at(os.getpid()) - 600)
        self.assertEqual(sr.app_backends(self.ledger([skewed])), [])

    def test_dead_pid_other_purpose_remote_host_and_isolated_are_skipped(self):
        entries = [
            self.own(pid=999999),
            self.own(purpose="mcp-helper"),
            self.own(host="192.0.2.10"),
            self.own(isolated=True),
            self.own(port=None),
        ]
        self.assertEqual(sr.app_backends(self.ledger(entries)), [])

    def test_idle_backend_is_not_busy(self):
        out = sr.backend_reasons(
            self.ledger([self.own()]), read=lambda b: {"ok": True, "idle": True}
        )
        self.assertEqual(out, [])

    def test_busy_backend_blocks_and_names_the_reason(self):
        proof = {"idle": False, "reason": "turn_in_flight"}
        out = sr.backend_reasons(self.ledger([self.own()]), read=lambda b: proof)
        self.assertEqual(len(out), 1)
        self.assertIn("is busy (turn_in_flight)", out[0])

    def test_backend_that_cannot_prove_idle_is_busy(self):
        def read(b):
            raise RuntimeError("no session token on the backend page")

        out = sr.backend_reasons(self.ledger([self.own()]), read=read)
        self.assertEqual(len(out), 1)
        self.assertIn("cannot prove it is idle", out[0])

    def test_busy_reasons_adds_gateway_and_backend_only_in_gateway_only_mode(self):
        calls = []
        patches = [
            mock.patch.object(sr, "HH", str(self.dir)),
            mock.patch.object(sr, "turn_reasons", lambda: []),
            mock.patch.object(sr, "jobs", lambda: []),
            mock.patch.object(
                sr.subprocess, "run", lambda *a, **k: mock.Mock(returncode=0, stdout="")
            ),
            mock.patch.object(
                sr,
                "gateway_reasons",
                lambda **k: (calls.append("gw"), ["gateway has 1 agent run"])[1],
            ),
            mock.patch.object(
                sr, "backend_reasons", lambda: (calls.append("be"), ["desktop backend busy"])[1]
            ),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        with mock.patch.object(sr, "gateway_only", lambda: True):
            self.assertEqual(
                sr.busy_reasons(None), ["gateway has 1 agent run", "desktop backend busy"]
            )
        self.assertEqual(calls, ["gw", "be"])
        calls.clear()
        with mock.patch.object(sr, "gateway_only", lambda: False):
            self.assertEqual(sr.busy_reasons(None), [])
        self.assertEqual(calls, [])


class GatewayOnlyRestart(Work):
    def setUp(self):
        super().setUp()
        self.events = []
        self.pids = {ex.LABEL: 100}
        self.held = []
        self.cards = []
        self.drain_rc = 0
        for name, val in (
            ("FREEZE_FILE", str(self.dir / "freeze")),
            ("BACKEND_FILE", str(self.dir / "backend")),
            ("FENCE_FILE", str(self.dir / "fence")),
            ("TRIGGER", str(self.dir / "trigger")),
            ("HERMES", "/synthetic/hermes"),
        ):
            p = mock.patch.object(ex, name, val)
            p.start()
            self.addCleanup(p.stop)
        for target, fn in (
            ("time.sleep", lambda s: None),
            ("subprocess.run", self.fake_run),
            ("builtins.print", lambda *a, **k: None),
            ("urllib.request.urlopen", mock.Mock()),
        ):
            p = mock.patch(target, fn)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(ex, "preflight_reasons", lambda: list(self.held))
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(ex, "idle_reasons", lambda: [])
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(ex, "card", lambda *a, **k: self.cards.append((a, k)))
        p.start()
        self.addCleanup(p.stop)
        for flag in ("FORCE_TOKEN", "FENCE_TOKEN"):
            self.addCleanup(setattr, ex, flag, False)
        os.environ.pop("SAFE_RESTART_FENCE", None)

    def fake_run(self, args, **kw):
        out = mock.Mock(returncode=0, stderr="", stdout="")
        if args[:2] == ["launchctl", "kickstart"]:
            self.events.append(("kickstart", args[-1]))
            self.pids[ex.LABEL] += 1
        elif args[:2] == ["launchctl", "list"]:
            out.stdout = f'"PID" = {self.pids[ex.LABEL]};'
        elif args[1:] == ["gateway", "restart"]:
            self.events.append(("drain", args[0]))
            out.returncode = self.drain_rc
            if self.drain_rc == 0:
                self.pids[ex.LABEL] += 1
        else:
            self.events.append(("other", tuple(args)))
        return out

    def trigger(self, tokens=""):
        (self.dir / "trigger").write_text(f"{int(time.time())} {tokens}".strip())

    def test_quiet_gateway_restarts_through_the_draining_command(self):
        self.trigger()
        ex.main()
        self.assertEqual(self.events, [("drain", "/synthetic/hermes")])
        self.assertEqual(len(self.cards), 1)
        self.assertIn("restarted safely", self.cards[0][0][0])

    def test_busy_gateway_refuses_and_restarts_nothing(self):
        self.held = ["gateway has 1 agent run in flight"]
        self.trigger()
        ex.main()
        self.assertEqual(self.events, [])
        self.assertEqual(self.pids[ex.LABEL], 100)
        title, body = self.cards[0][0][0], self.cards[0][0][1]
        self.assertIn("refused", title)
        self.assertIn("gateway has 1 agent run in flight", body)
        self.assertTrue(self.cards[0][1]["blocked"])  # blocked, so it reaches the owner

    def test_unreadable_health_refuses(self):
        self.held = ["cannot read the gateway health: refused"]
        self.trigger()
        ex.main()
        self.assertEqual(self.events, [])
        self.assertIn("refused", self.cards[0][0][0])

    def test_force_kickstarts_without_a_drain_and_records_what_it_cut(self):
        self.held = ["gateway has 2 agent runs in flight"]
        self.trigger("force")
        ex.main()
        self.assertEqual(self.events, [("kickstart", ex.LABEL)])
        body = self.cards[0][0][1]
        self.assertIn("forced restart, no drain", body)
        self.assertIn("gateway has 2 agent runs in flight", body)

    def test_a_failed_drain_is_reported_as_failure_not_success(self):
        self.drain_rc = 1
        self.trigger()
        ex.main()
        self.assertEqual(self.events, [("drain", "/synthetic/hermes")])
        self.assertIn("FAILED", self.cards[0][0][0])

    def test_fenced_gateway_only_reads_again_and_drains(self):
        (self.dir / "fence").write_text("1\n")
        self.trigger()
        ex.main()
        self.assertEqual(self.events, [("drain", "/synthetic/hermes")])
        self.assertFalse(os.path.exists(self.dir / "freeze"))

    def test_fenced_gateway_only_refuses_when_the_second_read_is_busy(self):
        (self.dir / "fence").write_text("1\n")
        self.held = ["gateway cannot drain right now"]
        self.trigger()
        ex.main()
        self.assertEqual(self.events, [])
        self.assertIn("refused", self.cards[0][0][0])
        self.assertFalse(os.path.exists(self.dir / "freeze"))

    def test_the_helper_never_signals_a_process(self):
        self.trigger()
        ex.main()
        self.assertEqual([e for e in self.events if e[0] == "other"], [])


if __name__ == "__main__":
    unittest.main()
