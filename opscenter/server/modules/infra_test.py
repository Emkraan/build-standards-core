"""
infra_test.py
Purpose: The Infrastructure page against a fake code host script and a provider file: the null default answers the empty
         shapes, the code host view lists PRs with a check summary and workflows red on main, the runner fleet and the live
         jobs read the configured repo, a provider fills spend, cron, the VM and the log, and a bad provider is refused.
Run:     python3 infra_test.py
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="infra-test-"))
CALLS = TMP / "calls.log"
GH = TMP / "gh"
GH.write_text(
    "#!/usr/bin/env python3\nimport json, sys\n"
    f"open({str(CALLS)!r}, 'a').write(' '.join(sys.argv[1:]) + '\\n')\n"
    "a = sys.argv[1:]\n"
    "if a[:2] == ['pr', 'list']:\n"
    "    print(json.dumps([{'number': 3, 'title': 't', 'author': {'login': 'x'}, 'isDraft': False, 'reviewDecision': '',\n"
    "        'statusCheckRollup': [{'name': 'ci', 'conclusion': 'FAILURE', 'status': 'COMPLETED', 'workflowName': 'w'},\n"
    "                              {'name': 'lint', 'conclusion': 'SUCCESS', 'status': 'COMPLETED', 'workflowName': 'w'}],\n"
    "        'updatedAt': '2026-10-01T00:00:00Z', 'url': 'u', 'headRefName': 'b', 'mergeStateStatus': 'CLEAN'}]))\n"
    "elif a[:2] == ['run', 'list']:\n"
    "    print(json.dumps([{'databaseId': 9, 'workflowName': 'build', 'displayTitle': 'x', 'status': 'completed',\n"
    "        'conclusion': 'failure', 'event': 'push', 'headBranch': 'main', 'createdAt': '2026-10-01T00:00:00Z',\n"
    "        'updatedAt': '2026-10-01T00:00:00Z', 'url': 'u'}]))\n"
    "elif a[0] == 'api' and a[1].endswith('/actions/runners'):\n"
    "    print(json.dumps({'runners': [{'name': 'r1', 'status': 'online', 'busy': False, 'labels': [{'name': 'self-hosted'}]}]}))\n"
    "elif a[0] == 'api' and '/actions/runs?status=' in a[1]:\n"
    "    print(json.dumps({'workflow_runs': [{'id': 5, 'display_title': 'run', 'name': 'w', 'head_branch': 'b',\n"
    "        'created_at': 'c', 'html_url': 'u'}]}))\n"
    "elif a[0] == 'api' and a[1].endswith('/jobs?per_page=50'):\n"
    "    print(json.dumps({'jobs': [{'id': 1, 'name': 'j', 'status': 'in_progress', 'steps': [{'number': 1, 'name': 's'}]}]}))\n"
    "elif a[0] == 'api' and '/actions/runs?per_page=8' in a[1]:\n"
    "    print(json.dumps({'workflow_runs': [{'id': 5, 'status': 'in_progress', 'name': 'w', 'updated_at': 'u1'}]}))\n"
    "else:\n    print('{}')\n"
)
GH.chmod(0o755)
PROV = TMP / "provider.py"
PROV.write_text(
    "class P:\n"
    "    def spend(self):\n        return {'generated_utc': 'now', 'months': [], 'jobs': [{'id': 'a'}]}\n"
    "    def cron(self):\n        return {'generated_utc': 'now', 'scheduler_heartbeat_age_s': 900,\n"
    "                'jobs': [{'name': 'nightly', 'health': 'failing'}, {'name': 'ok', 'health': 'ok'}]}\n"
    "    def vm(self):\n        return {'name': 'vm1', 'status': 'Running'}\n"
    "    def job_log(self, runner, lines):\n        return ['\\x1b[32mstep ok\\x1b[0m', 'next']\n"
    "    def health(self):\n        return [('OK', 'fine'), ('WARN', 'backup is old')]\n"
    "    def fallback_active(self):\n        return True\n"
)
sys.path.insert(0, str(Path(__file__).resolve().parent))

import infra  # noqa: E402
import swr  # noqa: E402

_old_gh = infra.GH


def setUpModule():
    infra.GH = str(GH)


def tearDownModule():
    infra.GH = _old_gh
    for k in ("INFRA_REPOS", "INFRA_RUNNER_REPO", "OPSCENTER_INFRA_PROVIDER", "INFRA_BILLING_USER"):
        os.environ.pop(k, None)


class Infra(unittest.TestCase):
    def setUp(self):
        swr._mem.clear()
        infra._done_jobs.clear()
        infra._live_jobs_seen.clear()
        for k in ("INFRA_REPOS", "INFRA_RUNNER_REPO", "OPSCENTER_INFRA_PROVIDER"):
            os.environ.pop(k, None)
        CALLS.write_text("")

    def test_the_null_default_answers_the_empty_shapes(self):
        self.assertEqual(infra.github()["repos"], [])
        r = infra.runners()
        self.assertEqual((r["repo"], r["vm"], r["runners"], r["links"]), ("", None, [], {}))
        self.assertEqual(infra.live_jobs()["runs"], [])
        self.assertEqual(infra.cron()["jobs"], [])
        self.assertEqual((infra.spend()["jobs"], infra.spend()["totals"]["d7"]), ([], 0))
        self.assertEqual(infra.badge_problems(), {"count": 0, "items": []})
        with self.assertRaises(infra.NotConfigured) as e:
            infra.job_log("runner-1")
        self.assertEqual(e.exception.status, 501)
        self.assertEqual(CALLS.read_text(), "")

    def test_the_code_host_view_summarises_checks_and_finds_red_on_main(self):
        os.environ["INFRA_REPOS"] = "acme/app,acme/infra"
        g = infra.github()
        self.assertEqual(g["repos"], ["acme/app", "acme/infra"])
        pr = g["prs"][0]
        self.assertEqual(
            (pr["checks"]["pass"], pr["checks"]["fail"], pr["checks"]["failing"]), (1, 1, ["ci"])
        )
        self.assertEqual({x["workflow"] for x in g["red_on_main"]}, {"build"})

    def test_the_runner_fleet_and_live_jobs_read_the_configured_repo(self):
        os.environ["INFRA_RUNNER_REPO"] = "acme/infra"
        r = infra.runners()
        self.assertEqual([x["name"] for x in r["runners"]], ["r1"])
        self.assertEqual((len(r["queued"]), len(r["running"])), (1, 1))
        self.assertIn("actions", r["links"])
        live = infra.live_jobs()
        self.assertTrue(live["active"])
        self.assertEqual(live["runs"][0]["jobs"][0]["steps"][0]["name"], "s")

    def test_a_provider_fills_spend_cron_vm_log_and_the_badge(self):
        os.environ["OPSCENTER_INFRA_PROVIDER"] = f"{PROV}:P"
        self.assertEqual(infra.spend()["jobs"], [{"id": "a"}])
        self.assertEqual(len(infra.cron()["jobs"]), 2)
        os.environ["INFRA_RUNNER_REPO"] = "acme/infra"
        self.assertEqual(infra.runners()["vm"]["name"], "vm1")
        log = infra.job_log("runner-1", 5)
        self.assertEqual(log["lines"], ["step ok", "next"])
        items = infra.badge_problems()["items"]
        self.assertIn("nightly: failing", items)
        self.assertIn("Model fallback active", items)
        self.assertIn("backup is old", items)
        self.assertTrue(any(i.startswith("Scheduler heartbeat 15 min") for i in items))

    def test_a_bad_runner_name_and_a_bad_provider_are_refused(self):
        os.environ["OPSCENTER_INFRA_PROVIDER"] = f"{PROV}:P"
        with self.assertRaises(ValueError):
            infra.job_log("../etc")
        os.environ["OPSCENTER_INFRA_PROVIDER"] = str(TMP / "missing.py") + ":P"
        with self.assertRaises(infra.ProviderRefused) as e:
            infra.provider()
        self.assertEqual(e.exception.status, 403)
        os.environ["OPSCENTER_INFRA_PROVIDER"] = "no-colon"
        with self.assertRaises(infra.ProviderRefused):
            infra.provider()


if __name__ == "__main__":
    unittest.main()
