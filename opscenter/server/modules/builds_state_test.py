"""
builds_state_test.py
Purpose: Current state vs history: a pipeline counts as failed only while its newest finished run on main failed; a later green run
         clears it, a branch run never counts, cancelled is not a failure, a run in flight is current and never failed; the
         older finished runs are history; main_failures and the items agree.
Run:     python3 builds_state_test.py
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import builds  # noqa: E402


def run(rid, branch="main", status="completed", conclusion="success", url=None):
    return {
        "id": rid,
        "branch": branch,
        "status": status,
        "conclusion": conclusion,
        "url": url or f"u/{rid}",
    }


class State(unittest.TestCase):
    def test_a_superseded_failure_is_history_not_current(self):
        st = builds.pipeline_state([run(3), run(2, conclusion="failure")])
        self.assertEqual((st["failed"], st["history"], st["current"]), (False, [2], None))

    def test_a_branch_failure_never_counts(self):
        st = builds.pipeline_state([run(3, branch="tkt-1-x", conclusion="failure"), run(2)])
        self.assertFalse(st["failed"])

    def test_the_newest_finished_main_run_failing_counts_even_while_a_new_run_is_live(self):
        st = builds.pipeline_state(
            [run(5, status="in_progress", conclusion=None), run(4, conclusion="timed_out"), run(3)]
        )
        self.assertEqual(
            (st["failed"], st["current"], st["last_main"]),
            (True, 5, {"id": 4, "conclusion": "timed_out"}),
        )

    def test_cancelled_is_not_a_failure(self):
        self.assertFalse(builds.pipeline_state([run(2, conclusion="cancelled")])["failed"])

    def test_a_run_in_flight_is_current_never_failed(self):
        st = builds.pipeline_state([run(2, status="queued", conclusion=None)])
        self.assertEqual((st["failed"], st["current"]), (False, 2))

    def test_the_lines_and_the_items_agree(self):
        feed = {
            "pipelines": [
                {
                    "key": "a",
                    "label": "Release",
                    "product": "app",
                    "runs": [run(2, conclusion="failure")],
                },
                {"key": "b", "label": "Deploy", "product": "web", "runs": [run(3)]},
            ]
        }
        self.assertEqual(builds.main_failures(feed), ["Release: last main run failure"])
        self.assertEqual(
            [(i["key"], i["run"], i["url"]) for i in builds.main_failure_items(feed)],
            [("a", 2, "u/2")],
        )
        self.assertEqual(builds.main_failures({}), [])


if __name__ == "__main__":
    unittest.main()
