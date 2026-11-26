"""Runs the review lane check files (pr_review_*_checks.py, own_pr_merge_checks.py, destroy_followup_checks.py)
under unittest, one subprocess each, so a failed check fails core CI. Each check file builds its own scratch
state tree from fixtures/ and fakes gh, so none touches a real repository. The unittest based files report
through their exit code; the script style files also print one OK or FAIL line per check."""

import sys
import unittest
from pathlib import Path

import checkrun

HERE = Path(__file__).resolve().parent
FILES = sorted(p.name for p in HERE.glob("pr_review_*_checks.py")) + [
    "queued_approvals_checks.py",
    "tests/own_pr_merge_checks.py",
    "tests/core_pr_lane_checks.py",
    "tests/own_sync_lane_checks.py",
    "destroy_followup_checks.py",
]


class ReviewLaneChecks(unittest.TestCase):
    pass


# Rough run times in seconds, only so the full run starts the slowest script first (checkrun.py).
EXPECT_SECONDS = {
    "tests/core_pr_lane_checks.py": 120,
    "destroy_followup_checks.py": 6,
    "tests/own_sync_lane_checks.py": 4,
}
JOBS = {
    _n: checkrun.register(
        [sys.executable, str(HERE / _n)], cwd=HERE, timeout=600, expect=EXPECT_SECONDS.get(_n, 1)
    )
    for _n in FILES
}


def _make(name):
    def run(self):
        p = JOBS[name].result()
        failed = [line for line in p.stdout.splitlines() if line.startswith("FAIL ")]
        self.assertEqual(failed, [], (p.stdout + p.stderr)[-3000:])
        self.assertEqual(p.returncode, 0, (p.stdout + p.stderr)[-3000:])

    return run


for _n in FILES:
    setattr(ReviewLaneChecks, "test_" + _n[: -len(".py")], _make(_n))


class ReviewLaneFiles(unittest.TestCase):
    def test_every_checks_file_is_listed(self):
        found = {p.name for p in HERE.glob("*_checks.py")}
        listed = set(FILES) | {
            "autofix_checks.py",
            "tfplan_gate_checks.py",
            "reviews_visibility_checks.py",
        }
        self.assertEqual(found - listed, set(), "a checks file no wrapper runs")


if __name__ == "__main__":
    unittest.main()
