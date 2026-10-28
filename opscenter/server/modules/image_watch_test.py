#!/usr/bin/env python3
"""Tests for image_watch.py. Synthetic runs behind fake gh and az binaries in a
scratch folder, a scratch state dir and a scratch automation store. No real run, VM or board."""

from __future__ import annotations

import importlib
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

FAKE_GH = r"""#!/usr/bin/env python3
import json, os, sys
sc = json.load(open(os.environ["IMAGE_FAKE"]))
a = sys.argv[1:]
def log(): open(os.environ["IMAGE_FAKE_CALLS"], "a").write(" ".join(a) + "\n")
if a[0] == "api" and "/workflows/" in a[1]:
    if sc.get("runs_fail"):
        sys.exit(1)
    print(json.dumps({"workflow_runs": sc["runs"]}))
elif a[0] == "api" and "/jobs" in a[1]:
    rid = a[1].split("/runs/")[1].split("/")[0]
    print(json.dumps({"jobs": sc.get("jobs_by_run", {}).get(rid, sc["jobs"])}))
elif a[0] == "api" and "/compare/" in a[1]:
    if sc.get("compare_fail"):
        sys.exit(1)
    print(json.dumps({"files": [{"filename": f} for f in sc["changed"]]}))
elif a[:2] == ["run", "view"]:
    sys.stdout.write(sc["log"])
elif a[:2] == ["run", "rerun"] or a[:2] == ["workflow", "run"]:
    log()
    if sc.get("write_fail"):
        sys.stderr.write(sc["write_fail"]); sys.exit(1)
else:
    sys.exit(2)
"""
FAKE_AZ = r"""#!/usr/bin/env python3
import json, os, sys
sc = json.load(open(os.environ["IMAGE_FAKE"]))
if sc.get("vm_fail"):
    sys.stderr.write("ERROR: az not logged in"); sys.exit(1)
print(sc.get("vm", "PowerState/deallocated"))
"""

LOG = (
    "job 3 - snapshot\tbuild the capture VM from the snapshot\t2026-10-17T17:58:55.2609230Z "
    "ERROR: (BadRequest) Security Type 'TrustedLaunch' is not supported for CreateOption 'Copy'.\n"
    "job 3 - snapshot\tbuild the capture VM from the snapshot\t2026-10-17T17:58:55.4126093Z "
    "##[error]Process completed with exit code 1.\n"
)


def run(
    rid=39035341812,
    attempt=2,
    conclusion="failure",
    status="completed",
    created="2026-10-17T13:08:33Z",
    event="workflow_dispatch",
    branch="main",
    sha="d9f751e0c56efa46bfca7d2b4b8017b4d0621716",
):
    return {
        "id": rid,
        "run_attempt": attempt,
        "conclusion": conclusion if status == "completed" else None,
        "status": status,
        "created_at": created,
        "updated_at": created,
        "event": event,
        "head_branch": branch,
        "head_sha": sha,
        "html_url": f"https://github.com/owner/repo/actions/runs/{rid}",
    }


JOBS = [
    {"name": "job 2 - manual installs done", "conclusion": "success", "steps": []},
    {
        "name": "job 3 - snapshot, capture VM, validate, sysprep, publish",
        "conclusion": "failure",
        "steps": [
            {"name": "Set up job", "conclusion": "success"},
            {"name": "build the capture VM from the snapshot", "conclusion": "failure"},
        ],
    },
]


class WatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        for name, body in (("gh", FAKE_GH), ("az", FAKE_AZ)):
            p = root / name
            p.write_text(body)
            p.chmod(p.stat().st_mode | stat.S_IEXEC)
        (root / "state" / "dashboard").mkdir(parents=True)
        self.calls = root / "calls.txt"
        self.scenario = root / "scenario.json"
        os.environ.update(
            {
                "IMAGE_WATCH_GH": str(root / "gh"),
                "IMAGE_WATCH_AZ": str(root / "az"),
                "IMAGE_WATCH_DASH": str(root / "state" / "dashboard"),
                "OPSCENTER_ROOT": str(root),
                "IMAGE_FAKE": str(self.scenario),
                "IMAGE_FAKE_CALLS": str(self.calls),
            }
        )
        sys.path.insert(0, str(Path(__file__).parent))
        import automation_actions
        import image_watch

        self.aa = importlib.reload(automation_actions)
        self.w = importlib.reload(image_watch)

    def tearDown(self):
        self.tmp.cleanup()

    def set(self, **kw):
        sc = {
            "runs": [run()],
            "jobs": JOBS,
            "changed": [],
            "log": LOG,
            "vm": "PowerState/deallocated",
        }
        sc.update(kw)
        self.scenario.write_text(json.dumps(sc))

    def open_items(self):
        return {k: v for k, v in self.aa._load()["items"].items() if not v.get("closed")}

    def calls_made(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    # ---- detection
    def test_live_case_raises_item_with_step_error_and_master_state(self):
        self.set()
        res = self.w.sync()
        self.assertEqual(res["raised_or_updated"], 1)
        item = self.open_items()["image-failed-39035341812-a2"]
        why = item["why"]
        self.assertIn("run 39035341812 attempt 2", why)
        self.assertIn("job 3 - snapshot, capture VM, validate, sysprep, publish", why)
        self.assertIn("step 'build the capture VM from the snapshot'", why)
        self.assertIn("Security Type 'TrustedLaunch' is not supported for CreateOption 'Copy'", why)
        self.assertNotIn("Process completed with exit code", why)
        self.assertIn("deallocated", why)
        self.assertEqual(item["links"][0]["label"], "Open run")
        self.assertIn("/actions/runs/39035341812", item["links"][0]["url"])
        self.assertEqual([a["kind"] for a in item.get("actions", [])], ["image-rerun"])
        self.assertEqual(item["priority"], "high")

    def test_result_line_comes_first(self):
        self.set(
            log='x\ty\t2026-10-17T17:58:55.1Z IMAGE-RESULT {"ok":false,"why":"sysprep"}\n' + LOG
        )
        self.w.sync()
        why = self.open_items()["image-failed-39035341812-a2"]["why"]
        self.assertLess(why.index("IMAGE-RESULT"), why.index("ERROR: (BadRequest)"))

    def test_ignores_pr_branch_other_event_and_success_cancelled(self):
        self.set(
            runs=[
                run(branch="feat"),
                run(rid=2, event="push"),
                run(rid=3, conclusion="cancelled"),
                run(rid=4, conclusion="success"),
            ]
        )
        self.assertEqual(self.w.sync()["failing"], False)
        self.assertEqual(self.open_items(), {})

    def test_in_progress_latest_attempt_is_not_a_failure(self):
        self.set(runs=[run(status="in_progress")])
        self.assertEqual(self.w.sync()["failing"], False)

    # ---- clearing
    def test_clears_when_newer_run_succeeds(self):
        self.set()
        self.w.sync()
        self.assertEqual(len(self.open_items()), 1)
        self.set(
            runs=[
                run(rid=50, attempt=1, conclusion="success", created="2026-10-18T09:00:00Z"),
                run(),
            ],
            jobs_by_run={
                "50": [
                    {
                        "name": "job 3 - snapshot, capture VM, validate, sysprep, publish",
                        "conclusion": "success",
                        "steps": [],
                    }
                ]
            },
        )
        res = self.w.sync()
        self.assertEqual(res["closed"], 1)
        self.assertEqual(self.open_items(), {})

    def test_clears_when_newer_attempt_succeeds(self):
        self.set()
        self.w.sync()
        self.set(runs=[run(attempt=3, conclusion="success")])
        self.assertEqual(self.w.sync()["closed"], 1)
        self.assertEqual(self.open_items(), {})

    def test_clears_when_a_new_attempt_is_running(self):
        self.set()
        self.w.sync()
        self.set(runs=[run(attempt=3, status="in_progress")])
        self.w.sync()
        self.assertEqual(self.open_items(), {})

    def test_scheduled_success_that_built_nothing_does_not_clear(self):
        self.set()
        self.w.sync()
        skipped = [
            {
                "name": "job 3 - snapshot, capture VM, validate, sysprep, publish",
                "conclusion": "skipped",
                "steps": [],
            }
        ]
        self.set(
            runs=[
                run(
                    rid=51,
                    attempt=1,
                    conclusion="success",
                    event="schedule",
                    created="2026-10-24T11:00:00Z",
                ),
                run(),
            ],
            jobs_by_run={"51": skipped},
        )
        self.w.sync()
        self.assertEqual(len(self.open_items()), 1)

    def test_older_success_does_not_clear(self):
        self.set(runs=[run(), run(rid=9, conclusion="success", created="2026-10-10T11:00:00Z")])
        self.w.sync()
        self.assertEqual(len(self.open_items()), 1)

    # core-rule: automation-safety.1.5
    def test_run_read_failure_changes_nothing(self):
        self.set()
        self.w.sync()
        self.set(runs_fail=True)
        res = self.w.sync()
        self.assertIn("error", res)
        self.assertEqual(len(self.open_items()), 1)

    def test_same_failure_is_idempotent(self):
        self.set()
        self.w.sync()
        self.assertEqual(self.w.sync()["raised_or_updated"], 0)

    # ---- fix merged after the run started
    def test_fix_merged_after_run_says_new_build_and_drops_rerun(self):
        self.set(changed=[".github/scripts/image-run.sh", "apps/x/package.json"])
        self.w.sync()
        item = self.open_items()["image-failed-39035341812-a2"]
        self.assertIn("A new build is needed, not a rerun", item["why"])
        self.assertIn("image-run.sh", item["why"])
        self.assertNotIn("apps/x/package.json", item["why"])
        self.assertNotIn("image-rerun", [a["kind"] for a in item.get("actions", [])])

    def test_docs_tests_and_window_log_are_not_a_fix(self):
        self.set(
            changed=[
                "infrastructure/terraform/image/README.md",
                "infrastructure/terraform/image/manual-installs.json",
                "infrastructure/terraform/image/tests/X.Tests.ps1",
                ".github/scripts/tests/test_image_run.py",
            ]
        )
        self.w.sync()
        item = self.open_items()["image-failed-39035341812-a2"]
        self.assertNotIn("new build is needed", item["why"])
        self.assertIn("image-rerun", [a["kind"] for a in item.get("actions", [])])

    def test_unrelated_main_changes_keep_rerun(self):
        self.set(changed=[])
        self.w.sync()
        item = self.open_items()["image-failed-39035341812-a2"]
        self.assertIn("image-rerun", [a["kind"] for a in item.get("actions", [])])

    def test_compare_failure_keeps_rerun_with_a_caution(self):
        self.set(compare_fail=True)
        self.w.sync()
        item = self.open_items()["image-failed-39035341812-a2"]
        self.assertIn("confirm before rerunning", item["why"])
        self.assertIn("image-rerun", [a["kind"] for a in item.get("actions", [])])

    # ---- master state
    def test_running_master_is_flagged_critical_with_close_button(self):
        self.set(vm="PowerState/running")
        self.w.sync()
        item = self.open_items()["image-failed-39035341812-a2"]
        self.assertIn("RUNNING", item["why"])
        self.assertIn("password", item["why"])
        self.assertEqual(item["priority"], "critical")
        self.assertEqual(
            [a["kind"] for a in item.get("actions", [])], ["image-rerun", "image-close"]
        )
        self.assertIn("master still running", item["title"])

    def test_deallocated_master_has_no_close_button(self):
        self.set(vm="PowerState/deallocated")
        self.w.sync()
        kinds = [a["kind"] for a in self.open_items()["image-failed-39035341812-a2"]["actions"]]
        self.assertNotIn("image-close", kinds)

    def test_unreadable_master_is_unknown_never_stopped(self):
        self.set(vm_fail=True)
        self.w.sync()
        item = self.open_items()["image-failed-39035341812-a2"]
        self.assertIn("unknown", item["why"])
        self.assertNotIn("is stopped", item["why"])
        self.assertIn("image-close", [a["kind"] for a in item.get("actions", [])])

    def test_master_read_is_cached(self):
        self.set(vm="PowerState/running")
        cache = {}
        self.assertEqual(self.w.master_state(cache), "running")
        self.set(vm="PowerState/deallocated")
        self.assertEqual(self.w.master_state(cache), "running")  # inside the TTL
        self.assertEqual(self.w.master_state(cache, fresh=True), "deallocated")

    def test_stopped_without_dealloc_is_named_billed(self):
        self.set(vm="PowerState/stopped")
        self.w.sync()
        self.assertIn("still billed", self.open_items()["image-failed-39035341812-a2"]["why"])

    def test_active_run_holds_both_buttons(self):
        self.set(
            vm="PowerState/running",
            runs=[
                run(rid=60, attempt=1, status="in_progress", created="2026-10-18T09:00:00Z"),
                run(),
            ],
        )
        self.w.sync()
        item = self.open_items()["image-failed-39035341812-a2"]
        self.assertEqual(item.get("actions", []), [])
        self.assertIn("in progress", item["why"])

    # ---- the buttons (fresh live re-read, never automatic)
    def test_sync_never_reruns_or_closes(self):
        self.set(vm="PowerState/running")
        self.w.sync()
        self.assertEqual(self.calls_made(), [])

    def test_rerun_runs_failed_jobs_only_and_closes_card_after(self):
        self.set()
        self.w.sync()
        code, body = self.w.act("image-rerun", 39035341812, 2)
        self.assertEqual(code, 200, body)
        self.assertEqual(self.calls_made(), ["run rerun 39035341812 --failed -R owner/repo"])

    def test_rerun_refused_when_run_moved(self):
        self.set(runs=[run(attempt=3)])
        code, body = self.w.act("image-rerun", 39035341812, 2)
        self.assertEqual(code, 409)
        self.assertIn("Refresh first", body["error"])
        self.assertEqual(self.calls_made(), [])

    def test_rerun_refused_when_fix_merged(self):
        self.set(changed=[".github/workflows/image-build.yml"])
        code, _ = self.w.act("image-rerun", 39035341812, 2)
        self.assertEqual(code, 409)
        self.assertEqual(self.calls_made(), [])

    def test_rerun_refused_when_a_run_is_active(self):
        self.set(
            runs=[run(rid=60, attempt=1, status="queued", created="2026-10-18T09:00:00Z"), run()]
        )
        code, _ = self.w.act("image-rerun", 39035341812, 2)
        self.assertEqual(code, 409)

    def test_rerun_already_running_is_idempotent_success(self):
        self.set(write_fail="run 39035341812 is already in progress")
        code, body = self.w.act("image-rerun", 39035341812, 2)
        self.assertEqual(code, 200)
        self.assertTrue(body.get("already"))

    def test_close_dispatches_close_mode_on_main(self):
        self.set(vm="PowerState/running")
        code, body = self.w.act("image-close", 39035341812, 2)
        self.assertEqual(code, 200, body)
        self.assertEqual(
            self.calls_made(),
            ["workflow run image-build.yml --ref main -f mode=close -R owner/repo"],
        )

    def test_close_refused_when_master_already_deallocated(self):
        self.set(vm="PowerState/deallocated")
        code, _ = self.w.act("image-close", 39035341812, 2)
        self.assertEqual(code, 409)
        self.assertEqual(self.calls_made(), [])

    def test_close_allowed_when_master_unknown(self):
        self.set(vm_fail=True)
        code, _ = self.w.act("image-close", 39035341812, 2)
        self.assertEqual(code, 200)

    def test_dry_run_writes_nothing(self):
        self.set(vm="PowerState/running")
        code, body = self.w.act("image-close", 39035341812, 2, dry_run=True)
        self.assertEqual((code, body["dry_run"]), (200, True))
        self.assertEqual(self.calls_made(), [])
        self.w.sync(dry_run=True)
        self.assertEqual(self.open_items(), {})

    def test_unknown_kind_is_rejected(self):
        self.set()
        self.assertEqual(self.w.act("rm-rf", 1, 1)[0], 400)

    def test_write_failure_is_an_error_not_success(self):
        self.set(write_fail="HTTP 403: forbidden")
        code, body = self.w.act("image-rerun", 39035341812, 2)
        self.assertEqual(code, 422)
        self.assertIn("403", body["error"])


if __name__ == "__main__":
    unittest.main()
