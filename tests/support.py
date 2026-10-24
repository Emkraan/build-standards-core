"""Shared helpers for the nightly tests. Fixtures live under the worktree, never under /tmp."""

import importlib.util
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORK = ROOT / ".test-work"
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "hermes"))


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sh(cmd, cwd=None, timeout=60):
    r = subprocess.run(
        [str(c) for c in cmd], cwd=cwd, capture_output=True, text=True, timeout=timeout
    )
    return r.returncode, (r.stdout + r.stderr).strip()


class Work(unittest.TestCase):
    def setUp(self):
        WORK.mkdir(exist_ok=True)
        self.dir = pathlib.Path(tempfile.mkdtemp(dir=WORK))
        self.addCleanup(shutil.rmtree, self.dir, True)
