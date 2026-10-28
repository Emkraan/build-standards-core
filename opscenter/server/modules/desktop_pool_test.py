import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import desktop_pool as dp  # noqa: E402
import swr  # noqa: E402


def vm(name, action="destroy"):
    return {
        "type": "azurerm_windows_virtual_machine",
        "action": action,
        "attrs": {"name": name},
        "address": f"module.x.vm[{name}]",
    }


def host(name, status="Available", allow=True, sessions=0):
    return {"name": name, "status": status, "allow_new_session": allow, "sessions": sessions}


class Pool(unittest.TestCase):
    def setUp(self):
        swr._mem.clear()
        swr._flight.clear()
        self._old = (dp._run, dp.SUBSCRIPTION, dp.RESOURCE_GROUP)
        dp.SUBSCRIPTION, dp.RESOURCE_GROUP = "sub-1", "rg-1"

    def tearDown(self):
        dp._run, dp.SUBSCRIPTION, dp.RESOURCE_GROUP = self._old
        swr._mem.clear()

    def serve(self, hosts):
        """Make the cloud read answer with these hosts for every pool."""
        rows = [
            {
                "name": f"hostpool-x/{h['name']}.example.invalid",
                "properties": {
                    "status": h["status"],
                    "allowNewSession": h["allow_new_session"],
                    "sessions": h["sessions"],
                },
            }
            for h in hosts
        ]
        dp._run = lambda argv, timeout=25: json.dumps({"value": rows})

    def test_retiring_takes_deleted_and_replaced_vms_by_host_name_only(self):
        res = [
            vm("host-blue-01"),
            vm("host-blue-02", "replace"),
            vm("host-green-01", "update"),
            vm("other-blue-03"),
            {"type": "azurerm_subnet", "action": "destroy", "attrs": {"name": "host-blue-09"}},
        ]
        self.assertEqual(dp.retiring(res), {"blue": ["host-blue-01", "host-blue-02"]})
        self.assertEqual(dp.retiring(None), {})

    def test_the_host_name_can_come_from_the_key_or_the_address(self):
        r = {"type": "x_virtual_machine", "action": "delete", "attrs": {}, "key": "host-red-07"}
        self.assertEqual(dp.retiring([r]), {"red": ["host-red-07"]})

    def test_a_drained_idle_pool_with_a_serving_new_host_is_ok(self):
        j = dp._judge_pool(
            "blue", [host("host-blue-01", allow=False), host("host-blue-02")], {"host-blue-01"}
        )
        self.assertTrue(j["ok"])
        self.assertEqual((j["new_ready"], j["not_registered"]), (1, []))

    def test_every_way_a_pool_is_not_ready_is_a_named_problem(self):
        hosts = [
            host("host-blue-01", allow=True, sessions=3),
            host("host-blue-02", allow=False, sessions=None),
            host("host-blue-03", status="Unavailable"),
        ]
        j = dp._judge_pool("blue", hosts, {"host-blue-01", "host-blue-02"})
        text = " | ".join(j["problems"])
        self.assertIn("host-blue-01 is still accepting new sessions", text)
        self.assertIn("host-blue-01 still has 3 sessions", text)
        self.assertIn("host-blue-02 did not report its session count", text)
        self.assertIn("host-blue-03 is Unavailable", text)
        self.assertFalse(j["ok"])

    def test_no_new_host_and_a_host_already_gone(self):
        j = dp._judge_pool(
            "blue", [host("host-blue-01", allow=False)], {"host-blue-01", "host-blue-05"}
        )
        self.assertIn("the pool has no new host", j["problems"])
        self.assertEqual(j["not_registered"], ["host-blue-05"])

    def test_evidence_ok_attention_unknown_and_checking(self):
        res = [vm("host-blue-01")]
        self.serve([host("host-blue-01", allow=False), host("host-blue-02")])
        ev = dp.evidence(res, blocking=True)
        self.assertEqual((ev["kind"], ev["status"]), ("pool-roll", "ok"))
        self.assertIn("approving is recommended", ev["text"])
        swr._mem.clear()
        self.serve([host("host-blue-01", allow=True), host("host-blue-02")])
        self.assertEqual(dp.evidence(res, blocking=True)["status"], "attention")
        swr._mem.clear()

        def boom(argv, timeout=25):
            raise dp.PoolReadError("az timed out after 25s")

        dp._run = boom
        ev = dp.evidence(res, blocking=True)
        self.assertEqual(ev["status"], "unknown")
        self.assertIn("timed out", ev["text"])
        self.assertEqual(dp.evidence([], roll=None)["status"], "unknown")  # no pool named

    def test_a_cold_nonblocking_read_reports_checking_and_never_waits(self):
        dp._run = lambda *a, **k: json.dumps({"value": []})
        ev = dp.evidence([vm("host-blue-01")], blocking=False)
        self.assertEqual(ev["status"], "checking")

    def test_paged_answers_are_followed_and_a_runaway_is_refused(self):
        pages = [
            {"value": [{"name": "p/host-a-01", "properties": {}}], "nextLink": "https://next"},
            {"value": [{"name": "p/host-a-02", "properties": {}}]},
        ]
        dp._run = lambda argv, timeout=25: json.dumps(pages.pop(0))
        self.assertEqual([h["name"] for h in dp.fetch_hosts("a")], ["host-a-01", "host-a-02"])
        dp._run = lambda argv, timeout=25: json.dumps({"value": [], "nextLink": "https://more"})
        with self.assertRaises(dp.PoolReadError):
            dp.fetch_hosts("a")

    def test_the_url_carries_the_parameters(self):
        u = dp.pool_url("blue")
        self.assertIn("/subscriptions/sub-1/resourceGroups/rg-1/", u)
        self.assertIn("hostPools/hostpool-blue/sessionHosts", u)

    def test_is_roll(self):
        self.assertTrue(dp.is_roll(dp.ROLL_WORKFLOW))
        self.assertFalse(dp.is_roll("other.yml"))
        self.assertFalse(dp.is_roll(None))


if __name__ == "__main__":
    unittest.main()
