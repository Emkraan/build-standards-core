"""
pool_view_test.py
Purpose: The optional host pool evidence: off by default, the plan's retiring hosts are read with the configured regex, the
         consumer's command is called as `hosts <pool>` with the configured values in its environment, a failed read never
         turns into a pass, and the verdict (retiring hosts drained with 0 sessions, a new host Available) drives the
         recommendation. Synthetic hosts and a fake command only.
Run:     python3 pool_view_test.py
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pool_view as pv  # noqa: E402
import swr  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="pool-view-"))
CMD = TMP / "hosts-cmd"
ANSWER = TMP / "answer.json"
CALLS = TMP / "calls.log"
CMD.write_text(
    "#!/usr/bin/env python3\nimport os, sys\n"
    f"open({str(CALLS)!r}, 'a').write(' '.join(sys.argv[1:]) + ' ' + os.environ.get('POOL_VIEW_SUBSCRIPTION', '') + '\\n')\n"
    f"sys.stdout.write(open({str(ANSWER)!r}).read())\n"
    f"sys.exit(int(open({str(TMP / 'rc')!r}).read() or 0))\n"
)
CMD.chmod(0o755)
(TMP / "rc").write_text("0")
CFG = {
    "roll_workflow": "wf/roll.yml",
    "pool_prefix": "pool-",
    "subscription": "sub-1",
    "cmd": str(CMD),
}
KEYS = ["POOL_VIEW_CONFIG", "POOL_VIEW_CMD", "POOL_VIEW_ROLL_WORKFLOW", "POOL_VIEW_HOST_REGEX"]
_saved = {}


def setUpModule():
    for k in KEYS:
        _saved[k] = os.environ.pop(k, None)


def tearDownModule():
    for k, v in _saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def host(n, status="Available", allow=True, sessions=0):
    return {
        "name": f"host-eu-{n}",
        "status": status,
        "allow_new_session": allow,
        "sessions": sessions,
    }


def vm(n, action="delete"):
    return {"address": f'module.p.vm["host-eu-{n}"]', "type": "x_virtual_machine", "action": action}


class PoolView(unittest.TestCase):
    def setUp(self):
        swr._mem.clear()
        CALLS.write_text("")
        (TMP / "rc").write_text("0")
        self.cfg = TMP / "pool-view.json"
        self.cfg.write_text(json.dumps(CFG))
        os.environ["POOL_VIEW_CONFIG"] = str(self.cfg)

    def tearDown(self):
        os.environ.pop("POOL_VIEW_CONFIG", None)

    def test_off_by_default(self):
        os.environ["POOL_VIEW_CONFIG"] = str(TMP / "absent.json")
        self.assertEqual((pv.enabled(), pv.is_roll("wf/roll.yml")), (False, False))
        self.assertEqual(CALLS.read_text(), "")

    def test_a_configured_roll_workflow_is_a_roll_and_env_overrides_the_file(self):
        self.assertTrue(pv.is_roll("wf/roll.yml"))
        self.assertFalse(pv.is_roll("wf/other.yml"))
        os.environ["POOL_VIEW_ROLL_WORKFLOW"] = "wf/x.yml"
        try:
            self.assertTrue(pv.is_roll("wf/x.yml"))
        finally:
            os.environ.pop("POOL_VIEW_ROLL_WORKFLOW")

    def test_retiring_reads_hosts_from_vm_deletes_only(self):
        res = [
            vm("01"),
            vm("02", "replace"),
            vm("03", "create"),
            {"type": "x_nic", "action": "delete", "address": "a.host-eu-04"},
        ]
        self.assertEqual(pv.retiring(res), {"eu": ["host-eu-01", "host-eu-02"]})

    def test_the_command_is_called_with_the_pool_name_and_config_in_its_environment(self):
        ANSWER.write_text(json.dumps({"hosts": [host("01", allow=False), host("51")]}))
        pv.evidence([vm("01")], blocking=True)
        self.assertEqual(CALLS.read_text().strip(), "hosts pool-eu sub-1")

    def test_drained_idle_hosts_and_a_ready_new_host_recommend_approving(self):
        ANSWER.write_text(
            json.dumps({"hosts": [host("01", allow=False), host("02", allow=False), host("51")]})
        )
        ev = pv.evidence([vm("01"), vm("02")], blocking=True)
        self.assertEqual(ev["status"], "ok")
        self.assertIn("I recommend approving", ev["text"])

    def test_a_busy_or_undrained_host_or_no_ready_new_host_needs_attention(self):
        ANSWER.write_text(
            json.dumps(
                {"hosts": [host("01", allow=True, sessions=2), host("51", status="Unavailable")]}
            )
        )
        ev = pv.evidence([vm("01")], blocking=True)
        self.assertEqual(ev["status"], "attention")
        t = ev["text"]
        self.assertIn("still accepting new sessions", t)
        self.assertIn("still has 2 sessions", t)
        self.assertIn("no new host is Available", t)

    def test_a_failed_read_is_unknown_never_a_pass(self):
        (TMP / "rc").write_text("3")
        ANSWER.write_text("{}")
        ev = pv.evidence([vm("01")], blocking=True)
        self.assertEqual(ev["status"], "unknown")
        self.assertIn("could not read the host pool", ev["text"])

    def test_no_command_configured_is_a_failed_read(self):
        self.cfg.write_text(json.dumps({k: v for k, v in CFG.items() if k != "cmd"}))
        self.assertEqual(pv.evidence([vm("01")], blocking=True)["status"], "unknown")

    def test_a_plan_that_names_no_pool_has_no_host_evidence(self):
        ev = pv.evidence([], blocking=True)
        self.assertEqual((ev["status"], ev["pools"]), ("unknown", []))

    def test_a_cold_nonblocking_read_is_checking(self):
        ANSWER.write_text(json.dumps({"hosts": []}))
        self.assertEqual(pv.evidence([vm("01")])["status"], "checking")


if __name__ == "__main__":
    unittest.main()
