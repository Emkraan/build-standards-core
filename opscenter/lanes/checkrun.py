"""Runs the check scripts that the lane test wrappers launch, optionally ahead of time and in parallel.

A wrapper test registers the command it will run when its module is imported and asks for the result in its test
method. Running one test by itself never starts anything early, so the result is produced inline exactly as a plain
subprocess call would. The full lanes run (tests/test_opscenter_lanes.py) calls start() once after every module is
loaded. That launches each registered script at the same moment, longest first, while the in-process tests run, and a
wrapper then collects the finished result of its own command. Each script still runs exactly once, with the
environment it would have had, and a timeout or a failure reaches the wrapper the same way in both modes.
"""

from __future__ import annotations

import os
import subprocess
import threading
from concurrent.futures import Future, ThreadPoolExecutor

DEFAULT_WORKERS = 4


class Job:
    """One check script command. result() returns the finished process, running it inline when it was never started."""

    def __init__(self, cmd, cwd, env, timeout, expect):
        self.cmd = [str(part) for part in cmd]
        self.cwd = None if cwd is None else str(cwd)
        self.env = env
        self.timeout = timeout
        self.expect = expect
        self._future: Future | None = None
        self._lock = threading.Lock()

    def _spawn(self, env):
        return subprocess.run(
            self.cmd,
            cwd=self.cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )

    def result(self):
        with self._lock:
            future = self._future
        if future is not None:
            return future.result()
        return self._spawn(self.env)


class Batch:
    """A set of jobs that start together. Tests make their own Batch so they never launch the real wrappers."""

    def __init__(self):
        self.jobs: list[Job] = []
        self._pool: ThreadPoolExecutor | None = None
        self._lock = threading.Lock()

    def register(self, cmd, *, cwd=None, env=None, timeout=300, expect=1):
        """Record a command. expect is a rough run time in seconds, used only to start the longest jobs first."""
        job = Job(cmd, cwd, env, timeout, expect)
        with self._lock:
            self.jobs.append(job)
        return job

    def start(self, workers=DEFAULT_WORKERS):
        """Launch every job not yet started. The environment is read here, in the calling thread, so a test that
        changes os.environ a moment later cannot leak into a script that has not spawned yet. Safe to call twice."""
        with self._lock:
            pending = [job for job in self.jobs if job._future is None]
            if not pending:
                return 0
            if self._pool is None:
                self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="checkrun")
            pool = self._pool
            snapshot = dict(os.environ)
            for job in sorted(pending, key=lambda item: -item.expect):
                env = snapshot if job.env is None else job.env
                with job._lock:
                    job._future = pool.submit(job._spawn, env)
            return len(pending)


DEFAULT = Batch()


def register(cmd, *, cwd=None, env=None, timeout=300, expect=1):
    return DEFAULT.register(cmd, cwd=cwd, env=env, timeout=timeout, expect=expect)


def start(workers=DEFAULT_WORKERS):
    return DEFAULT.start(workers)
