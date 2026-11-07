"""
run_watches_test.py
Purpose: The main watch and the drift watch: the newest completed run on main decides; a failure or timeout raises one item with
         the workflow, the failed job, its first error line and the run link; a later success closes it; cancelled and skipped
         runs do not count; two red scheduled nights raise one item that names each failing job and error; a manual run and a
         branch run never count; a streak below the minimum raises nothing; a watch that cannot be read is an item, never clear.
Run:     python3 run_watches_test.py
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_watches as w


def run(i, conclusion, event="push", branch="main", status="completed", day=1):
    return {
        "databaseId": i,
        "status": status,
        "conclusion": conclusion,
        "event": event,
        "headBranch": branch,
        "createdAt": f"2026-11-{day:02d}T03:00:00Z",
        "url": f"https://example.invalid/runs/{i}",
    }


JOBS = {
    11: [
        {
            "id": 111,
            "name": "apply",
            "conclusion": "failure",
            "steps": [
                {"name": "terraform apply", "conclusion": "failure"},
                {"name": "setup", "conclusion": "success"},
            ],
        }
    ],
    22: [
        {
            "id": 222,
            "name": "plan-a",
            "conclusion": "failure",
            "steps": [{"name": "plan", "conclusion": "failure"}],
        },
        {"id": 223, "name": "plan-b", "conclusion": "success", "steps": []},
    ],
}
LOGS = {
    111: "2026-11-01T03:00:01Z ok\n2026-11-01T03:00:09Z ##[error]Error: AuthorizationFailed on resource x\nmore",
    222: "Error: state drift detected in module m",
}


def gh(args, raw=False):
    if args[0] == "api" and "/jobs?" in args[1]:
        rid = int(args[1].split("/runs/")[1].split("/")[0])
        return {"jobs": JOBS.get(rid, [])}
    if args[0] == "api" and "/logs" in args[1]:
        return LOGS[int(args[1].split("/jobs/")[1].split("/")[0])]
    raise AssertionError(args)


MAIN = {
    "kind": "main",
    "repo": "o/r",
    "workflow": "apply.yml",
    "label": "Platform apply",
    "owner": "Owner",
}
DRIFT = {"kind": "drift", "repo": "o/r", "workflow": "drift.yml", "label": "Nightly drift"}


class Main(unittest.TestCase):
    def test_a_failed_apply_raises_one_item_with_job_error_and_link(self):
        it = w.main_item(MAIN, [run(11, "failure")], gh)
        self.assertEqual(it["key"], "main-watch-apply.yml")
        self.assertIn("failed on main", it["title"])
        self.assertIn(
            "apply (step terraform apply): Error: AuthorizationFailed on resource x", it["why"]
        )
        self.assertEqual(it["links"][0]["url"], "https://example.invalid/runs/11")

    def test_a_timeout_is_a_failure(self):
        self.assertIn("timed out", w.main_item(MAIN, [run(11, "timed_out")], gh)["title"])

    def test_a_later_success_closes_the_item(self):
        self.assertIsNone(
            w.main_item(MAIN, [run(12, "success", day=2), run(11, "failure", day=1)], gh)
        )

    def test_cancelled_and_skipped_runs_do_not_count_either_way(self):
        # a cancelled newer run does not close a red main, and does not raise one on a green main
        it = w.main_item(MAIN, [run(13, "cancelled", day=3), run(11, "failure", day=1)], gh)
        self.assertIsNotNone(it)
        self.assertIsNone(
            w.main_item(MAIN, [run(14, "skipped", day=3), run(12, "success", day=2)], gh)
        )
        self.assertIsNone(w.main_item(MAIN, [run(15, "cancelled")], gh))

    def test_a_run_in_flight_and_a_branch_run_do_not_decide(self):
        self.assertIsNone(
            w.main_item(
                MAIN, [run(16, None, status="in_progress", day=3), run(12, "success", day=2)], gh
            )
        )
        self.assertIsNone(
            w.main_item(
                MAIN, [run(17, "failure", branch="feature", day=3), run(12, "success", day=2)], gh
            )
        )


class Drift(unittest.TestCase):
    def test_two_red_nights_raise_one_item_with_jobs_and_errors(self):
        runs = [run(22, "failure", "schedule", day=2), run(21, "failure", "schedule", day=1)]
        it = w.drift_item(DRIFT, runs, gh)
        self.assertEqual(it["key"], "drift-watch-drift.yml")
        self.assertIn("red for 2 nights", it["title"])
        self.assertIn("plan-a (step plan): Error: state drift detected in module m", it["why"])
        self.assertNotIn("plan-b", it["why"])
        self.assertEqual(len(it["links"]), 2)

    def test_it_updates_while_the_streak_grows(self):
        runs = [
            run(23, "failure", "schedule", day=3),
            run(22, "failure", "schedule", day=2),
            run(21, "failure", "schedule", day=1),
        ]
        self.assertIn("red for 3 nights", w.drift_item(DRIFT, runs, gh)["title"])

    def test_a_scheduled_success_closes_it(self):
        runs = [
            run(24, "success", "schedule", day=4),
            run(23, "failure", "schedule", day=3),
            run(22, "failure", "schedule", day=2),
        ]
        self.assertIsNone(w.drift_item(DRIFT, runs, gh))

    def test_dispatch_and_branch_runs_do_not_count(self):
        # a manual run that succeeded does not hide two red nights
        runs = [
            run(25, "success", "workflow_dispatch", day=3),
            run(22, "failure", "schedule", day=2),
            run(21, "failure", "schedule", day=1),
        ]
        self.assertIsNotNone(w.drift_item(DRIFT, runs, gh))
        # a red branch run never raises one
        runs = [
            run(26, "failure", "schedule", "feature", day=3),
            run(27, "failure", "schedule", "feature", day=2),
        ]
        self.assertIsNone(w.drift_item(DRIFT, runs, gh))

    def test_one_red_night_is_below_the_minimum(self):
        self.assertIsNone(
            w.drift_item(
                DRIFT,
                [run(22, "failure", "schedule", day=2), run(20, "success", "schedule", day=1)],
                gh,
            )
        )
        self.assertIsNotNone(
            w.drift_item(dict(DRIFT, min_streak=1), [run(22, "failure", "schedule", day=2)], gh)
        )


class Collect(unittest.TestCase):
    def test_collects_each_watch_and_never_reads_a_broken_one_as_clear(self):
        cfg = {"watches": [MAIN, DRIFT, {"kind": "nope", "workflow": "x"}]}
        runs = {"apply.yml": [run(11, "failure")], "drift.yml": [run(30, "success", "schedule")]}
        items = w.collect(cfg, gh, runs_for=lambda x: runs[x["workflow"]])
        keys = sorted(i["key"] for i in items)
        self.assertEqual(keys, ["main-watch-apply.yml", "run-watch-unread-x"])

    def test_a_read_that_fails_is_an_item(self):
        def boom(x):
            raise RuntimeError("HTTP 502")

        items = w.collect({"watches": [MAIN]}, gh, runs_for=boom)
        self.assertEqual(items[0]["key"], "run-watch-unread-apply.yml")
        self.assertIn("unknown", items[0]["why"])

    def test_no_config_no_items(self):
        self.assertEqual(w.collect({}, gh), [])

    def test_first_error_strips_timestamps_and_annotations(self):
        self.assertEqual(
            w.first_error("2026-11-01T03:00:09Z ##[error]Error: boom\nfine"), ["Error: boom"]
        )


if __name__ == "__main__":
    unittest.main()
