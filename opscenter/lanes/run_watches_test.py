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
    if args[0] == "api" and "/jobs?" in args[-1]:
        rid = int(args[-1].split("/runs/")[1].split("/")[0])
        return {"jobs": JOBS.get(rid, [])}
    if args[0] == "api" and "/logs" in args[-1]:
        return LOGS[int(args[-1].split("/jobs/")[1].split("/")[0])]
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


class Fake:
    """A recording code host: jobs per run id and logs per job id, with reads that can be made to fail."""

    def __init__(self, jobs, logs, jobs_fail=False, log_fail=()):
        self.jobs, self.logs, self.jobs_fail, self.log_fail = jobs, logs, jobs_fail, set(log_fail)
        self.calls = []

    def __call__(self, args, raw=False):
        self.calls.append(" ".join(str(a) for a in args))
        path = args[-1]
        if "/logs" in path:
            jid = int(path.split("/jobs/")[1].split("/")[0])
            if jid in self.log_fail:
                raise RuntimeError("HTTP 404")
            return self.logs.get(jid, "")
        if "/jobs?" in path:
            if self.jobs_fail:
                raise RuntimeError("HTTP 404")
            rid = int(path.split("/runs/")[1].split("/")[0])
            return {"jobs": self.jobs.get(rid, [])}
        raise AssertionError(args)

    def reads(self):
        return [c for c in self.calls if "/jobs" in c or "/logs" in c]


# The scenarios of the reference main watch tests: a terraform log with colour codes and a box drawing prefix, a second
# Error line, an annotation and the runner's exit code line; and a run whose first annotation is the exit code line.
MJOBS = {
    10: [
        {"id": 101, "name": "discover", "conclusion": "success"},
        {"id": 102, "name": "apply", "conclusion": "failure"},
        {"id": 103, "name": "deploy", "conclusion": "skipped"},
    ],
    20: [
        {"id": 201, "name": "apply", "conclusion": "failure"},
        {"id": 202, "name": "x", "conclusion": "failure"},
    ],
}
MLOGS = {
    102: "2026-10-31T19:38:29.1Z group start\n"
    "2026-10-31T19:38:29.6Z \x1b[31m\u2502 Error:\x1b[0m unexpected status 403 (403 Forbidden), AuthorizationFailed\n"
    "2026-10-31T19:38:29.7Z Error: second one\n"
    "2026-10-31T19:38:30.6Z ##[error]apply failed for root a\n"
    "2026-10-31T19:38:30.7Z ##[error]Process completed with exit code 1.\n",
    201: "2026-10-31T19:00:00.1Z ##[error]Process completed with exit code 1.\n"
    "2026-10-31T19:00:00.2Z ##[error]timeout waiting for the plan\n",
}
DEPLOY = dict(MAIN, workflow="deploy.yml", label="Deploy apps")


class MainReference(unittest.TestCase):
    """The reference main watch scenarios against collect(). Left out as board specific: the run id in the item key (a
    resolved failure stays resolved there; here the key is stable and the item exists only while main is red), the run
    title in the text, the semicolon rewrite of the board's text, and the dry run (collect() never writes a board)."""

    def items(self, gh, apply_runs=(), deploy_runs=(), cache=None):
        runs = {"apply.yml": list(apply_runs), "deploy.yml": list(deploy_runs)}
        cfg = {"watches": [MAIN, DEPLOY]}
        got = w.collect(
            cfg, gh, runs_for=lambda x: runs[x["workflow"]], cache=cache or w.JobsCache()
        )
        return {i["key"]: i for i in got}

    def test_failed_apply_raises_one_item_with_the_first_error_line_only(self):
        it = self.items(Fake(MJOBS, MLOGS), [run(10, "failure", day=2), run(9, "success")])[
            "main-watch-apply.yml"
        ]
        self.assertIn(
            "apply: Error: unexpected status 403 (403 Forbidden), AuthorizationFailed", it["why"]
        )
        self.assertNotIn("second one", it["why"])
        self.assertNotIn("exit code", it["why"])
        self.assertNotIn("\x1b", it["why"])
        self.assertNotIn("2026-10-31T", it["why"])
        self.assertNotIn("discover", it["why"])
        self.assertEqual(it["links"][0]["url"], "https://example.invalid/runs/10")

    def test_newest_success_raises_nothing(self):
        self.assertEqual(
            self.items(Fake(MJOBS, MLOGS), [run(11, "success", day=2), run(10, "failure")]), {}
        )

    def test_branch_and_in_progress_runs_do_not_count(self):
        runs = [
            run(12, "failure", branch="feature", day=3),
            run(11, None, status="in_progress", day=3),
            run(9, "success", day=1),
        ]
        self.assertEqual(self.items(Fake(MJOBS, MLOGS), runs), {})

    def test_cancelled_neither_raises_nor_clears(self):
        gh = Fake(MJOBS, MLOGS)
        self.assertIn(
            "main-watch-apply.yml",
            self.items(gh, [run(11, "cancelled", day=2), run(10, "failure", day=1)]),
        )
        self.assertEqual(self.items(gh, [run(11, "cancelled", day=2), run(9, "success")]), {})

    def test_a_newer_failure_names_its_own_run_jobs_and_falls_back_past_the_exit_line(self):
        it = self.items(Fake(MJOBS, MLOGS), [run(20, "failure", day=3), run(10, "failure")])[
            "main-watch-apply.yml"
        ]
        self.assertEqual(it["refs"], ["run 20"])
        self.assertIn("apply: timeout waiting for the plan", it["why"])
        self.assertIn("; x", it["why"])

    def test_each_workflow_has_its_own_item_and_a_green_clears_only_its_own(self):
        gh = Fake(MJOBS, MLOGS)
        got = self.items(gh, [run(10, "failure")], [run(20, "timed_out", day=2)])
        self.assertEqual(sorted(got), ["main-watch-apply.yml", "main-watch-deploy.yml"])
        self.assertIn("timed out", got["main-watch-deploy.yml"]["title"])
        got = self.items(
            gh, [run(10, "failure")], [run(21, "success", day=3), run(20, "timed_out", day=2)]
        )
        self.assertEqual(sorted(got), ["main-watch-apply.yml"])

    def test_an_unchanged_failure_does_not_reread_jobs_and_logs(self):
        gh, cache = Fake(MJOBS, MLOGS), w.JobsCache()
        first = self.items(gh, [run(10, "failure")], cache=cache)
        self.assertTrue(gh.reads())
        gh.calls.clear()
        self.assertEqual(self.items(gh, [run(10, "failure")], cache=cache), first)
        self.assertEqual(gh.reads(), [])

    def test_failed_reads_are_an_unknown_item_never_clear(self):
        # the reference leaves its board as it is; here a read that fails is an item, unknown and never clear
        def boom(x):
            raise RuntimeError("HTTP 502")

        got = w.collect({"watches": [MAIN]}, Fake(MJOBS, MLOGS), runs_for=boom, cache=w.JobsCache())
        self.assertEqual([i["key"] for i in got], ["run-watch-unread-apply.yml"])
        got = self.items(Fake(MJOBS, MLOGS, jobs_fail=True), [run(20, "failure")])
        self.assertEqual(sorted(got), ["run-watch-unread-apply.yml"])
        self.assertEqual(got["run-watch-unread-apply.yml"]["priority"], "medium")

    def test_a_log_read_failure_still_raises_and_is_read_again(self):
        cache = w.JobsCache()
        it = self.items(Fake(MJOBS, MLOGS, log_fail=[102]), [run(10, "failure")], cache=cache)
        self.assertIn("failed: apply. A later", it["main-watch-apply.yml"]["why"])
        self.assertNotIn("Error:", it["main-watch-apply.yml"]["why"])
        gh = Fake(MJOBS, MLOGS)
        it = self.items(gh, [run(10, "failure")], cache=cache)
        self.assertIn("apply: Error: unexpected status 403", it["main-watch-apply.yml"]["why"])
        self.assertTrue(any("/logs" in c for c in gh.calls))

    def test_first_error_shapes(self):
        fe = w.first_error
        self.assertEqual(fe("2026-10-31T19:38:29.6Z | Error: boom")[:1], ["Error: boom"])
        self.assertEqual(
            fe("##[error]only this\n##[error]Process completed with exit code 1."), ["only this"]
        )
        self.assertEqual(fe("##[error]Process completed with exit code 1."), [])
        self.assertEqual(fe(""), [])


DJOBS = {
    3: [
        {"id": 11, "name": "drift (a)", "conclusion": "failure"},
        {"id": 12, "name": "coverage", "conclusion": "failure"},
        {"id": 13, "name": "drift (b)", "conclusion": "success"},
    ],
}
DJOBS[4] = DJOBS[3]
DLOGS = {
    11: "2026-10-31T07:01:00.1Z ##[error]root a has drift: 1 to change\n"
    "2026-10-31T07:01:00.2Z ##[error]Process completed with exit code 1.\n",
    12: "2026-10-31T07:02:00.1Z \x1b[31m##[error]unmanaged resource-1\x1b[0m\n",
}


class DriftReference(unittest.TestCase):
    """The reference drift watch scenarios against collect(). Left out as board specific: the first red run's id in the
    item key, the semicolon rewrite of the board's text, and the dry run. Different by design (core is the better side):
    a timed out night counts as red, and a read that fails is an unknown item instead of leaving a board as it is."""

    def items(self, gh, runs, cache=None):
        got = w.collect(
            {"watches": [DRIFT]}, gh, runs_for=lambda x: list(runs), cache=cache or w.JobsCache()
        )
        return {i["key"]: i for i in got}

    def s(self, i, conclusion, day, event="schedule", branch="main"):
        return run(i, conclusion, event, branch, day=day)

    def test_one_red_night_raises_nothing(self):
        self.assertEqual(
            self.items(Fake(DJOBS, DLOGS), [self.s(3, "failure", 31), self.s(2, "success", 30)]),
            {},
        )

    def test_two_red_nights_raise_one_item_with_jobs_and_errors(self):
        runs = [self.s(3, "failure", 31), self.s(2, "failure", 30), self.s(1, "success", 29)]
        it = self.items(Fake(DJOBS, DLOGS), runs)["drift-watch-drift.yml"]
        self.assertIn("red for 2 nights", it["title"])
        self.assertIn("drift (a): root a has drift: 1 to change", it["why"])
        self.assertIn("coverage: unmanaged resource-1", it["why"])
        self.assertNotIn("exit code", it["why"])
        self.assertNotIn("drift (b)", it["why"])
        self.assertNotIn("\x1b", it["why"])
        self.assertEqual(it["links"][0]["url"], "https://example.invalid/runs/3")

    def test_dispatch_and_branch_runs_do_not_count(self):
        runs = [
            self.s(4, "failure", 31, event="workflow_dispatch"),
            self.s(3, "failure", 31, branch="feature"),
            self.s(2, "failure", 30),
            self.s(1, "success", 29),
        ]
        self.assertEqual(self.items(Fake(DJOBS, DLOGS), runs), {})

    def test_a_cancelled_night_does_not_break_the_streak(self):
        runs = [self.s(3, "failure", 31), self.s(5, "cancelled", 30), self.s(2, "failure", 29)]
        self.assertIn("drift-watch-drift.yml", self.items(Fake(DJOBS, DLOGS), runs))

    def test_a_growing_streak_keeps_one_item_and_a_green_night_closes_it(self):
        gh = Fake(DJOBS, DLOGS)
        got = self.items(gh, [self.s(3, "failure", 30), self.s(2, "failure", 29)])
        self.assertEqual(list(got), ["drift-watch-drift.yml"])
        runs = [self.s(4, "failure", 31), self.s(3, "failure", 30), self.s(2, "failure", 29)]
        got = self.items(gh, runs)
        self.assertEqual(list(got), ["drift-watch-drift.yml"])
        self.assertIn("red for 3 nights", got["drift-watch-drift.yml"]["title"])
        runs = [self.s(5, "success", 31), self.s(4, "failure", 30), self.s(3, "failure", 29)]
        self.assertEqual(self.items(gh, runs), {})

    def test_an_unchanged_streak_does_not_reread_jobs(self):
        gh, cache = Fake(DJOBS, DLOGS), w.JobsCache()
        runs = [self.s(3, "failure", 31), self.s(2, "failure", 30)]
        self.items(gh, runs, cache)
        gh.calls.clear()
        self.assertIn("drift-watch-drift.yml", self.items(gh, runs, cache))
        self.assertEqual(gh.reads(), [])

    def test_failed_reads_are_an_unknown_item_never_clear(self):
        runs = [self.s(4, "failure", 31), self.s(3, "failure", 30)]
        got = self.items(Fake(DJOBS, DLOGS, jobs_fail=True), runs)
        self.assertEqual(list(got), ["run-watch-unread-drift.yml"])

    def test_a_log_read_failure_still_lists_the_job(self):
        runs = [self.s(3, "failure", 31), self.s(2, "failure", 30)]
        why = self.items(Fake(DJOBS, DLOGS, log_fail=[11]), runs)["drift-watch-drift.yml"]["why"]
        self.assertIn("drift (a); coverage: unmanaged resource-1", why)


class ErrorLines(unittest.TestCase):
    def test_the_word_failed_in_ordinary_output_is_not_an_error(self):
        self.assertEqual(w.first_error("Run failed-checks-script ok\nall checks failed: 0"), [])

    def test_the_error_line_is_preferred_over_an_earlier_annotation(self):
        log = "##[error]step broke\nterraform says\n\u2502 Error: quota exceeded\n"
        self.assertEqual(w.first_error(log), ["Error: quota exceeded", "step broke"])

    def test_the_exit_code_line_never_comes_with_a_real_error(self):
        log = "Error: boom\n##[error]Process completed with exit code 1.\n"
        self.assertEqual(w.first_error(log), ["Error: boom"])

    def test_an_annotated_error_line_is_not_repeated(self):
        log = "##[error]Error: boom\nError: boom\n"
        self.assertEqual(w.first_error(log), ["Error: boom"])


class Cache(unittest.TestCase):
    def test_a_different_run_or_attempt_is_never_answered_from_the_cache(self):
        gh, cache = Fake(MJOBS, MLOGS), w.JobsCache()
        self.assertEqual(cache.jobs(gh, "o/r", run(10, "failure"))[0]["name"], "apply")
        self.assertEqual(len(cache.jobs(gh, "o/r", run(20, "failure"))), 2)
        gh.calls.clear()
        cache.jobs(gh, "o/r", dict(run(10, "failure"), attempt=2))
        self.assertTrue(gh.reads())
        gh.calls.clear()
        cache.jobs(gh, "other/r", run(10, "failure"))
        self.assertTrue(gh.reads())

    def test_the_cache_is_bounded_to_the_newest_entries(self):
        gh, cache = Fake(MJOBS, MLOGS), w.JobsCache(keep=2)
        for i in (1, 2, 3):
            cache.jobs(gh, "o/r", run(i, "failure"))
        self.assertEqual(len(cache.entries), 2)
        self.assertNotIn(w.JobsCache.key("o/r", run(1, "failure")), cache.entries)

    def test_a_cache_file_survives_the_process_and_a_broken_one_starts_empty(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "c.json"
            cfg = {"watches": [MAIN], "cache_file": str(path)}
            gh = Fake(MJOBS, MLOGS)
            w.collect(cfg, gh, runs_for=lambda x: [run(10, "failure")])
            gh.calls.clear()
            got = w.collect(cfg, gh, runs_for=lambda x: [run(10, "failure")])
            self.assertEqual(gh.reads(), [])
            self.assertIn("Error: unexpected status 403", got[0]["why"])
            path.write_text("not json")
            w.collect(cfg, gh, runs_for=lambda x: [run(10, "failure")])
            self.assertTrue(gh.reads())

    def test_an_old_gh_without_the_escape_flag_still_reads_the_log(self):
        def old(args, raw=False):
            if "--allow-escape-sequences" in args:
                raise RuntimeError("unknown flag: --allow-escape-sequences")
            return MLOGS[102]

        self.assertEqual(w._job_log(old, "o/r", 102), MLOGS[102])


if __name__ == "__main__":
    unittest.main()
