"""The runtime slot: the null default (a clear "no runtime configured"), a fake command that starts and reports sessions, the live
session reuse, failure handling, status refresh, resolve, and the routes."""

import json
import os
import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

FAKE = textwrap.dedent(
    """
    import json, os, sys
    log = os.environ["FAKE_LOG"]
    verb, arg = sys.argv[1], json.loads(sys.argv[2])
    open(log, "a").write(json.dumps([verb, arg]) + "\\n")
    if verb == "start":
        if os.environ.get("FAKE_FAIL"):
            print("boom", file=sys.stderr); sys.exit(3)
        print(json.dumps({"session_id": "s-" + arg["fp"], "pid": 42, "log": "/x.log"}))
    elif verb == "prompt":
        if os.environ.get("FAKE_NOPROMPT"):
            sys.exit(2)
        print("{}")
    elif verb == "status":
        if os.environ.get("FAKE_NOSTATUS"):
            sys.exit(1)
        print(json.dumps({i: {"state": "finished", "last_active": "2099-01-01T00:00:00Z"} for i in arg["session_ids"]}))
    """
)


class Slot(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="runtime-slot-"))
        self._env = dict(os.environ)
        for k in ("OPSCENTER_RUNTIME_CMD", "FAKE_FAIL", "FAKE_NOSTATUS", "OPSCENTER_PUBLIC_URL"):
            os.environ.pop(k, None)
        os.environ.update(
            OPSCENTER_STATE_DIR=str(self.d / "state"),
            OPSCENTER_SERVED_BOARD=str(self.d / "board.json"),
            FAKE_LOG=str(self.d / "calls.log"),
        )
        (self.d / "board.json").write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "fp": "ac_1",
                            "title": "Fix the thing",
                            "summary": "details",
                            "refs": ["T-1"],
                        }
                    ]
                }
            )
        )
        (self.d / "fake.py").write_text(FAKE)
        for m in ("stores", "runtime_slot"):
            sys.modules.pop(m, None)
        import runtime_slot

        self.rt = runtime_slot

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self.d, ignore_errors=True)

    def configure(self):
        os.environ["OPSCENTER_RUNTIME_CMD"] = json.dumps([sys.executable, str(self.d / "fake.py")])

    def calls(self):
        p = self.d / "calls.log"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def test_null_default_says_no_runtime_configured_and_never_starts_anything(self):
        self.assertEqual(
            self.rt.get(),
            {"sessions": {}, "runtime": {"configured": False, "state": "no runtime configured"}},
        )
        with self.assertRaises(self.rt.NoRuntime) as cm:
            self.rt.post_tackle({"fp": "ac_1"})
        self.assertEqual((cm.exception.status, str(cm.exception)), (501, "no runtime configured"))
        self.assertEqual(self.calls(), [])

    def test_a_start_runs_the_command_with_a_prompt_built_from_the_board_item(self):
        self.configure()
        os.environ["OPSCENTER_PUBLIC_URL"] = "http://ops.local"
        out = self.rt.post_tackle({"fp": "ac_1", "context": "be quick"})
        self.assertEqual(
            (out["state"], out["session_id"], out["pid"], out["live"], out["ticket"]),
            ("running", "s-ac_1", 42, True, "T-1"),
        )
        verb, arg = self.calls()[0]
        self.assertEqual(
            (verb, arg["fp"], arg["kind"], arg["title"]), ("start", "ac_1", "item", "Fix the thing")
        )
        self.assertIn("details", arg["prompt"])
        self.assertIn("be quick", arg["prompt"])
        self.assertIn("POST http://ops.local/api/tackle/resolve", arg["prompt"])
        self.assertTrue(out["has_context"])

    def test_the_prompt_comes_from_the_board_never_from_the_client_and_an_unknown_item_is_404(self):
        self.configure()
        with self.assertRaises(KeyError):
            self.rt.post_tackle({"fp": "nope"})
        self.assertEqual(self.calls(), [])

    def test_a_live_session_is_returned_instead_of_a_second_start(self):
        self.configure()
        self.rt.post_tackle({"fp": "ac_1"})
        again = self.rt.post_tackle({"fp": "ac_1"})
        self.assertEqual(again["session_id"], "s-ac_1")
        self.assertEqual(len([c for c in self.calls() if c[0] == "start"]), 1)

    def test_a_failed_start_is_recorded_as_failed_with_the_error_and_can_be_retried(self):
        self.configure()
        os.environ["FAKE_FAIL"] = "1"
        out = self.rt.post_tackle({"fp": "ac_1"})
        self.assertEqual((out["state"], out["live"]), ("failed", False))
        self.assertIn("boom", out["error"])
        os.environ.pop("FAKE_FAIL")
        self.assertEqual(self.rt.post_tackle({"fp": "ac_1"})["state"], "running")

    def test_a_missing_or_broken_command_fails_the_session_without_raising(self):
        os.environ["OPSCENTER_RUNTIME_CMD"] = str(self.d / "does-not-exist")
        self.assertEqual(self.rt.post_tackle({"fp": "ac_1"})["state"], "failed")

    def test_status_refreshes_running_sessions_and_a_command_that_cannot_answer_keeps_them(self):
        self.configure()
        self.rt.post_tackle({"fp": "ac_1"})
        os.environ["FAKE_NOSTATUS"] = "1"
        self.assertEqual(self.rt.get()["sessions"]["ac_1"]["state"], "running")
        os.environ.pop("FAKE_NOSTATUS")
        got = self.rt.get()
        self.assertEqual(
            (got["sessions"]["ac_1"]["state"], got["sessions"]["ac_1"]["live"], got["runtime"]),
            ("finished", False, {"configured": True}),
        )

    def test_resolve_records_the_summary_and_an_unknown_fp_is_404(self):
        self.configure()
        self.rt.post_tackle({"fp": "ac_1"})
        out = self.rt.post_resolve({"fp": "ac_1", "summary": "done it", "owner": True})
        self.assertEqual(
            (out["state"], out["resolved"], out["live"]), ("resolved", "done it", False)
        )
        with self.assertRaises(KeyError):
            self.rt.post_resolve({"fp": "zzz"})

    def test_discuss_requires_a_repo_and_a_number_and_keys_the_session_by_them(self):
        self.configure()
        with self.assertRaises(ValueError):
            self.rt.post_discuss({"repo": "o/r", "pr": "x"})
        out = self.rt.post_discuss({"repo": "o/r", "pr": 7, "context": "why"})
        self.assertEqual((out["fp"], out["title"]), ("pr-o-r-7", "o/r#7"))

    def test_the_command_may_be_a_shell_split_string(self):
        os.environ["OPSCENTER_RUNTIME_CMD"] = f"{sys.executable} {self.d / 'fake.py'}"
        self.assertEqual(self.rt.post_tackle({"fp": "ac_1"})["state"], "running")


class Loop(Slot):
    """The item bound loop (DESIGN.md 12.95): a claim token, progress reports, bind, prompt and the one at a time launch."""

    def start_one(self):
        os.environ["OPSCENTER_RUNTIME_CMD"] = f"{sys.executable} {self.d / 'fake.py'}"
        return self.rt.post_tackle({"fp": "ac_1"})

    def claim_from_prompt(self):
        calls = [json.loads(line) for line in (self.d / "calls.log").read_text().splitlines()]
        prompt = next(a["prompt"] for v, a in calls if v == "start")
        return prompt.split('"claim": "')[1].split('"')[0]

    def test_the_session_is_told_its_claim_and_the_store_keeps_only_a_hash(self):
        out = self.start_one()
        self.assertNotIn("claim_hash", out)
        claim = self.claim_from_prompt()
        raw = (self.d / "state" / "dashboard" / "action-tackle.json").read_text()
        self.assertNotIn(claim, raw)
        self.assertIn("claim_hash", raw)

    def test_resolve_and_report_need_the_claim_or_the_owner(self):
        self.start_one()
        claim = self.claim_from_prompt()
        for body in (
            {"fp": "ac_1", "summary": "x"},
            {"fp": "ac_1", "summary": "x", "claim": "wrong"},
        ):
            with self.assertRaises(self.rt.Refused):
                self.rt.post_resolve(body)
        with self.assertRaises(self.rt.Refused):
            self.rt.post_report({"fp": "ac_1", "text": "halfway"})
        out = self.rt.post_report(
            {"fp": "ac_1", "text": "  half   way ", "claim": claim, "pct": 50}
        )
        self.assertEqual(out["reports"][0]["text"], "half way")
        self.assertEqual(out["reports"][0]["pct"], 50)
        self.assertEqual(
            self.rt.post_resolve({"fp": "ac_1", "summary": "ok", "claim": claim})["state"],
            "resolved",
        )

    def test_reports_keep_the_last_five_and_a_bad_percent_is_dropped(self):
        self.start_one()
        for i in range(7):
            self.rt.post_report({"fp": "ac_1", "text": f"step {i}", "owner": True, "pct": 150})
        out = self.rt.post_report({"fp": "ac_1", "text": "last", "owner": True})
        self.assertEqual(len(out["reports"]), 5)
        self.assertEqual(out["reports"][0]["text"], "last")
        self.assertNotIn("pct", out["reports"][1])

    def test_bind_attaches_a_session_to_an_item_and_an_unknown_item_is_404(self):
        self.start_one()
        out = self.rt.post_bind({"fp": "ac_1", "session_id": "desk-9", "surface": "desktop"})
        self.assertEqual((out["session_id"], out["state"]), ("desk-9", "running"))
        with self.assertRaises(KeyError):
            self.rt.post_bind({"fp": "zzz", "session_id": "x"})
        with self.assertRaises(ValueError):
            self.rt.post_bind({"fp": "ac_1"})

    def test_prompt_goes_to_the_runtime_for_a_live_session_only(self):
        with self.assertRaises(self.rt.NoRuntime):
            self.rt.post_prompt({"fp": "ac_1", "text": "hi"})
        self.start_one()
        self.assertEqual(
            self.rt.post_prompt({"fp": "ac_1", "text": "keep going"}), {"fp": "ac_1", "sent": True}
        )
        sent = [
            json.loads(line)
            for line in (self.d / "calls.log").read_text().splitlines()
            if '"prompt"' in line[:12]
        ]
        self.assertEqual(sent[0][1]["text"], "keep going")
        with self.assertRaises(KeyError):
            self.rt.post_prompt({"fp": "nope", "text": "hi"})
        os.environ["FAKE_NOPROMPT"] = "1"
        with self.assertRaises(self.rt.NoRuntime):
            self.rt.post_prompt({"fp": "ac_1", "text": "again"})

    def test_a_second_launch_waits_for_the_hold_time_then_is_busy_and_starts_nothing(self):
        os.environ["OPSCENTER_RUNTIME_CMD"] = f"{sys.executable} {self.d / 'fake.py'}"
        os.environ["OPSCENTER_LAUNCH_HOLD_S"] = "1"
        self.assertTrue(self.rt._lock.acquire(timeout=1))  # a launch in flight
        try:
            with self.assertRaises(self.rt.Busy) as e:
                self.rt.start("ac_2", title="Second")
            self.assertEqual(e.exception.status, 429)
        finally:
            self.rt._lock.release()
        self.assertFalse((self.d / "calls.log").exists())


if __name__ == "__main__":
    unittest.main()
