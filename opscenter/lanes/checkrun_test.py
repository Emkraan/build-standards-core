"""Tests for checkrun.py: the same result inline and started, one run per job, real overlap, a frozen environment."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from subprocess import TimeoutExpired

import checkrun


def py(code):
    return [sys.executable, "-c", code]


class Inline(unittest.TestCase):
    def test_a_job_that_was_never_started_runs_inline(self):
        batch = checkrun.Batch()
        job = batch.register(py("print('hello')"))
        done = job.result()
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "hello"))

    def test_a_timeout_reaches_the_caller(self):
        batch = checkrun.Batch()
        job = batch.register(py("import time\ntime.sleep(5)"), timeout=1)
        with self.assertRaises(TimeoutExpired):
            job.result()

    def test_a_nonzero_exit_is_returned_not_raised(self):
        batch = checkrun.Batch()
        done = batch.register(py("import sys\nsys.exit(3)")).result()
        self.assertEqual(done.returncode, 3)


class Started(unittest.TestCase):
    def test_a_started_job_gives_the_same_answer(self):
        batch = checkrun.Batch()
        job = batch.register(py("import sys\nprint('out')\nsys.stderr.write('err')\nsys.exit(2)"))
        self.assertEqual(batch.start(), 1)
        done = job.result()
        self.assertEqual(
            (done.returncode, done.stdout.strip(), done.stderr.strip()), (2, "out", "err")
        )

    def test_a_started_job_runs_once_however_often_it_is_read(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / "runs.log"
            batch = checkrun.Batch()
            job = batch.register(py(f"open({str(log)!r}, 'a').write('x')"))
            batch.start()
            first = job.result()
            second = job.result()
            self.assertIs(first, second)
            self.assertEqual(log.read_text(), "x")

    def test_starting_twice_does_not_run_a_job_twice(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / "runs.log"
            batch = checkrun.Batch()
            job = batch.register(py(f"open({str(log)!r}, 'a').write('x')"))
            self.assertEqual(batch.start(), 1)
            self.assertEqual(batch.start(), 0)
            job.result()
            self.assertEqual(log.read_text(), "x")

    def test_a_started_timeout_reaches_the_caller(self):
        batch = checkrun.Batch()
        job = batch.register(py("import time\ntime.sleep(5)"), timeout=1)
        batch.start()
        with self.assertRaises(TimeoutExpired):
            job.result()

    def test_jobs_really_overlap(self):
        # Each job waits for a file the other one writes. Run one after the other, the first would sit out its
        # timeout and raise, so this passes only when both are running at the same time.
        with tempfile.TemporaryDirectory() as folder:
            a, b = Path(folder) / "a", Path(folder) / "b"
            wait = (
                "import os, sys, time\n"
                "mine, theirs = sys.argv[1], sys.argv[2]\n"
                "open(mine, 'w').write('1')\n"
                "end = time.time() + 12\n"
                "while not os.path.exists(theirs):\n"
                "    if time.time() > end:\n"
                "        sys.exit(9)\n"
                "    time.sleep(0.02)\n"
            )
            batch = checkrun.Batch()
            first = batch.register([sys.executable, "-c", wait, str(a), str(b)], timeout=30)
            second = batch.register([sys.executable, "-c", wait, str(b), str(a)], timeout=30)
            batch.start(workers=2)
            self.assertEqual(first.result().returncode, 0)
            self.assertEqual(second.result().returncode, 0)

    def test_the_environment_is_read_when_the_batch_starts(self):
        batch = checkrun.Batch()
        job = batch.register(py("import os\nprint(os.environ.get('CHECKRUN_PROBE'))"))
        os.environ["CHECKRUN_PROBE"] = "before"
        try:
            batch.start()
            os.environ["CHECKRUN_PROBE"] = "after"
            self.assertEqual(job.result().stdout.strip(), "before")
        finally:
            os.environ.pop("CHECKRUN_PROBE", None)

    def test_a_job_with_its_own_environment_keeps_it(self):
        batch = checkrun.Batch()
        own = {**os.environ, "CHECKRUN_PROBE": "own"}
        job = batch.register(py("import os\nprint(os.environ.get('CHECKRUN_PROBE'))"), env=own)
        os.environ["CHECKRUN_PROBE"] = "ambient"
        try:
            batch.start()
            self.assertEqual(job.result().stdout.strip(), "own")
        finally:
            os.environ.pop("CHECKRUN_PROBE", None)

    def test_the_longest_job_is_submitted_first(self):
        # One worker runs jobs in the order they were submitted, so the log shows the order the batch chose.
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / "order.log"

            def note(word):
                return py(f"open({str(log)!r}, 'a').write({word!r})")

            batch = checkrun.Batch()
            quick = batch.register(note("quick,"), expect=1)
            slow = batch.register(note("slow,"), expect=100)
            middle = batch.register(note("middle,"), expect=10)
            batch.start(workers=1)
            for job in (quick, slow, middle):
                job.result()
            self.assertEqual(log.read_text(), "slow,middle,quick,")


if __name__ == "__main__":
    unittest.main()
