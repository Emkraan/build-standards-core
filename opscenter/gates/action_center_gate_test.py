"""The Action Center wake gate, run as a process against scratch state: the wake rules, the chatter split, the
retry and backoff after a missing or rejected analysis, the wake snapshot and the build failure path."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
GATE = HERE / "action_center_gate.py"


def bundle(must=("a",), context=(), generated="t1"):
    return {
        "generated_utc": generated,
        "now_et": "x",
        "candidates_must": [{"cid": c, "title": c} for c in must],
        "candidates_context": [{"cid": c, "source": s, "title": c} for c, s in context],
        "previous_items": [{"key": "p"}],
        "collector_errors": [],
        "ref_status": {"finished": {}, "errors": ["flaky"]},
    }


class Gate(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="ac-gate-test-"))
        self.root = self.d / "root"
        (self.root / "state" / "dashboard").mkdir(parents=True)
        self.bundle = self.d / "bundle.json"
        self.ac = self.d / "action-center.json"
        clean = {k: v for k, v in os.environ.items() if not k.startswith(("OPSCENTER_", "AC_", "GATE_"))}
        self.env = dict(
            clean,
            GATE_STATE_DIR=str(self.d / "gates"),
            GATE_BUNDLE_JSON=str(self.bundle),
            GATE_AC_JSON=str(self.ac),
            GATE_STATE=str(self.d / "state.json"),
            GATE_CONTRACT_STATE=str(self.d / "contract.json"),
            GATE_WAKE_PATH=str(self.d / "wake.json"),
            OPSCENTER_ROOT=str(self.root),
            OPSCENTER_STATE_DIR=str(self.root / "state"),
            GATE_MIN_GAP_S="1800",
        )

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def tick(self, data=None, **env):
        if data is not None:
            self.bundle.write_text(data if isinstance(data, str) else json.dumps(data))
        p = subprocess.run(
            [sys.executable, str(GATE)],
            capture_output=True,
            text=True,
            env=dict(self.env, **env),
            timeout=60,
        )
        self.assertEqual(p.returncode, 0, p.stderr[-500:])
        return p.stdout

    def silent(self, out):
        return out.strip().splitlines()[-1:] == ['{"wakeAgent": false}']

    def state(self):
        return json.loads((self.d / "state.json").read_text())

    def test_first_tick_wakes_and_writes_the_snapshot(self):
        out = self.tick(bundle(must=("a", "b")))
        self.assertIn("ACTION-CENTER GATE: waking because", out)
        self.assertEqual(json.loads((self.d / "wake.json").read_text())["must_cids"], ["a", "b"])
        self.assertIn("woke_hash", self.state())

    def test_an_unchanged_bundle_is_silent_and_noise_does_not_count(self):
        self.tick(bundle())
        again = bundle(
            generated="t2"
        )  # a new stamp, new previous items, flaky ref errors: not signal
        again["previous_items"] = [{"key": "q"}]
        again["ref_status"]["errors"] = ["other"]
        self.assertTrue(self.silent(self.tick(again)))

    def test_a_changed_bundle_waits_for_the_min_gap_then_wakes(self):
        self.tick(bundle())
        self.assertTrue(
            self.silent(self.tick(bundle(must=("a", "new"))))
        )  # changed, but 0 s after the last wake
        st = self.state()
        st["woke_at"] -= 3600
        (self.d / "state.json").write_text(json.dumps(st))
        self.ac.write_text("{}")  # the last analysis wrote its file after it was woken
        os.utime(self.ac, (time.time(), time.time()))
        self.assertIn("bundle changed since last analysis", self.tick(bundle(must=("a", "new"))))

    def test_chatter_only_changes_wait_for_the_chatter_age(self):
        self.tick(bundle(context=[("g1", "chat.group")]))
        st = self.state()
        st["woke_at"] -= 3600
        (self.d / "state.json").write_text(json.dumps(st))
        self.ac.write_text("{}")
        os.utime(self.ac, (time.time(), time.time()))
        # a new group message is chatter: one hour is not the two hour age
        self.assertTrue(
            self.silent(self.tick(bundle(context=[("g1", "chat.group"), ("g2", "chat2.group")])))
        )
        st = self.state()
        st["woke_at"] -= 7200
        (self.d / "state.json").write_text(json.dumps(st))
        os.utime(self.ac, (time.time(), time.time()))
        self.assertIn(
            "only background chatter changed",
            self.tick(bundle(context=[("g1", "chat.group"), ("g2", "chat2.group")])),
        )

    def test_a_run_that_wrote_nothing_is_retried_after_twenty_minutes(self):
        self.tick(bundle())
        st = self.state()
        st["woke_at"] -= 1300  # 21 minutes ago, and the analysis file is older than that wake
        (self.d / "state.json").write_text(json.dumps(st))
        self.ac.write_text("{}")
        os.utime(self.ac, (st["woke_at"] - 100, st["woke_at"] - 100))
        self.assertIn("did not write action-center.json; retrying", self.tick(bundle()))

    def test_a_rejected_analysis_names_the_errors_and_backs_off_after_three(self):
        self.tick(bundle())
        st = self.state()
        st["woke_at"] -= 1300
        (self.d / "state.json").write_text(json.dumps(st))
        self.ac.write_text("{}")
        os.utime(self.ac, (st["woke_at"] - 100, st["woke_at"] - 100))
        (self.d / "contract.json").write_text(
            json.dumps({"status": "rejected", "streak": 1, "errors": ["bad priority"]})
        )
        self.assertIn("rejected by the engine (1 in a row: bad priority)", self.tick(bundle()))
        # three in a row: the retry waits four hours
        st = self.state()
        st["woke_at"] -= 1300
        (self.d / "state.json").write_text(json.dumps(st))
        os.utime(self.ac, (st["woke_at"] - 100, st["woke_at"] - 100))
        (self.d / "contract.json").write_text(
            json.dumps({"status": "rejected", "streak": 3, "errors": ["bad priority"]})
        )
        self.assertTrue(self.silent(self.tick(bundle())))

    def test_a_build_failure_wakes_on_the_third_and_reports_once(self):
        env = {"GATE_BUNDLE_JSON": ""}
        # no override: the gate runs the real builder against a root with a broken routing file
        (self.root / "state" / "dashboard" / "ac-routing.json").write_text("{not json")
        outs = [self.tick(None, **env) for _ in range(3)]
        self.assertTrue(self.silent(outs[0]) and self.silent(outs[1]))
        self.assertIn("bundle build failing", outs[2])
        items = json.loads(
            (self.root / "state" / "dashboard" / "automation-actions.json").read_text()
        )["items"]
        self.assertIn("ac-gate-bundle", items)

    def test_bundle_that_is_not_json_is_a_failure_not_a_crash(self):
        outs = [self.tick("{nope") for _ in range(3)]
        self.assertTrue(self.silent(outs[0]))
        self.assertIn("not valid JSON", outs[2])


if __name__ == "__main__":
    unittest.main()
