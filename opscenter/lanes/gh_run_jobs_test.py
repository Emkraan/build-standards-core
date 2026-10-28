"""
gh_run_jobs_test.py
Purpose: tests for the shared run jobs reader: pages of 50, one retry on a GitHub 5xx, other
         errors raised, list-shaped answers accepted. Fake gh, no GitHub.
Run:     /usr/bin/python3 gh_run_jobs_test.py
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gh_run_jobs as g  # noqa: E402

g.RETRY_WAIT_S = 0


class GhError(Exception):
    pass


class Fake:
    def __init__(self, total, fail=None):
        self.jobs = [{"id": i} for i in range(total)]
        self.fail = list(fail or [])
        self.paths = []

    def __call__(self, args):
        path = args[1]
        self.paths.append(path)
        if self.fail:
            raise GhError(self.fail.pop(0))
        q = dict(kv.split("=") for kv in path.split("?")[1].split("&"))
        per, page = int(q["per_page"]), int(q["page"])
        return {"jobs": self.jobs[(page - 1) * per : page * per]}


class RunJobs(unittest.TestCase):
    def test_65_jobs_read_in_two_pages_of_50(self):
        f = Fake(65)
        self.assertEqual(len(g.run_jobs(f, "o/r", 40347326535)), 65)
        self.assertEqual(len(f.paths), 2)
        self.assertTrue(all("per_page=50" in p for p in f.paths))

    def test_exact_page_reads_one_empty_page(self):
        f = Fake(50)
        self.assertEqual(len(g.run_jobs(f, "o/r", 1)), 50)
        self.assertEqual(len(f.paths), 2)

    def test_502_is_retried_once(self):
        f = Fake(3, fail=["rc=1 gh: Server Error (HTTP 502)"])
        self.assertEqual(len(g.run_jobs(f, "o/r", 1)), 3)

    def test_two_502s_raise(self):
        f = Fake(3, fail=["HTTP 502", "HTTP 502"])
        with self.assertRaises(GhError):
            g.run_jobs(f, "o/r", 1)

    def test_404_is_not_retried(self):
        f = Fake(3, fail=["HTTP 404"])
        with self.assertRaises(GhError):
            g.run_jobs(f, "o/r", 1)
        self.assertEqual(len(f.paths), 1)

    def test_list_answer_is_accepted(self):
        self.assertEqual(g.run_jobs(lambda a: [{"id": 1}], "o/r", 1), [{"id": 1}])


if __name__ == "__main__":
    unittest.main(verbosity=1)
