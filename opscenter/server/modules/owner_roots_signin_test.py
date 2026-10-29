"""
owner_roots_signin_test.py
Purpose: The Sign in button runs one prompt at a time (a new click ends the previous worker and its prompt), re-plans
         every root by itself once the sign-in lands as the expected account, and reports a wrong account, a failed or
         abandoned prompt, and a missing sign-in command. A provider file with a fake prompt and a scratch cache only,
         nothing reaches a cloud or Terraform.
Run:     python3 owner_roots_signin_test.py
"""

from __future__ import annotations

import os
import signal
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

SCRATCH = Path(tempfile.mkdtemp(prefix="owner-roots-signin-test-"))
FAKE_LOGIN = SCRATCH / "login"
USER_FILE = SCRATCH / "user"
PROVIDER = SCRATCH / "provider.py"
ADMIN = "admin-account"
PROVIDER.write_text(
    "class P:\n"
    f"    expected_identity = {ADMIN!r}\n"
    f"    def identity(self):\n        return __import__('pathlib').Path({str(USER_FILE)!r}).read_text().strip()\n"
    f"    def signin_cmd(self):\n        return [{str(FAKE_LOGIN)!r}]\n"
)

ENV = {
    "OWNER_ROOTS_CACHE": str(SCRATCH / "cache"),
    "OWNER_ROOTS_PROVIDER": f"{PROVIDER}:P",
    "OWNER_ROOTS_SIGNIN_POLL_S": "0.05",
}
import importlib  # noqa: E402

o = None
_saved = {}


def setUpModule():
    """The module reads its environment at import: set it, load the module fresh, undo all of it afterwards."""
    global o
    for k in list(ENV) + []:
        _saved[k] = os.environ.get(k)
    os.environ.update(ENV)
    for k in []:
        os.environ.pop(k, None)
    import owner_roots

    o = importlib.reload(owner_roots)


def tearDownModule():
    for k, v in _saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    import owner_roots

    importlib.reload(owner_roots)


def fake_az(login="exit 0", user=ADMIN):
    """A synthetic prompt: runs the given shell line; the identity is the user file."""
    FAKE_LOGIN.write_text(f"#!/bin/sh\n{login}\n")
    FAKE_LOGIN.chmod(FAKE_LOGIN.stat().st_mode | stat.S_IEXEC)
    USER_FILE.write_text(user)


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A killed child of this test stays a zombie until reaped, ps shows it as Z.
    st = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, timeout=10
    ).stdout.strip()
    return bool(st) and not st.startswith("Z")


def wait_dead(pid, s=5.0):
    end = time.time() + s
    while time.time() < end:
        if not alive(pid):
            return True
        time.sleep(0.05)
    return False


class Worker(unittest.TestCase):
    def setUp(self):
        o.SIGNIN.unlink(missing_ok=True)
        self.planned = []
        self._plan_all = o.plan_all
        o.plan_all = lambda: self.planned.append(time.time())

    def tearDown(self):
        o.plan_all = self._plan_all
        o.SIGNIN_TIMEOUT_S = 600

    def test_signed_in_as_admin_replans_every_root(self):
        fake_az()
        self.assertEqual(o.signin_worker(), 0)
        st = o._signin_load()
        self.assertEqual(st["state"], "done")
        self.assertEqual(st["user"], ADMIN)
        self.assertEqual(len(self.planned), 1)

    def test_wrong_account_fails_and_does_not_plan(self):
        fake_az(user="other-account")
        self.assertEqual(o.signin_worker(), 1)
        st = o._signin_load()
        self.assertEqual(st["state"], "failed")
        self.assertIn("not " + ADMIN, st["error"])
        self.assertEqual(self.planned, [])

    def test_failed_login_reports_exit_and_stderr(self):
        fake_az(login="echo 'login refused synthetic' >&2; exit 1")
        self.assertEqual(o.signin_worker(), 1)
        st = o._signin_load()
        self.assertEqual(st["state"], "failed")
        self.assertIn("exit 1", st["error"])
        self.assertIn("login refused synthetic", st["error"])
        self.assertEqual(self.planned, [])

    def test_no_sign_in_configured_fails_with_a_clear_error(self):
        saved = os.environ["OWNER_ROOTS_PROVIDER"]
        os.environ["OWNER_ROOTS_PROVIDER"] = ""
        try:
            self.assertEqual(o.signin_worker(), 1)
            self.assertIn("No sign-in is configured", o._signin_load()["error"])
        finally:
            os.environ["OWNER_ROOTS_PROVIDER"] = saved

    def test_abandoned_prompt_times_out(self):
        fake_az(login="sleep 30")
        o.SIGNIN_TIMEOUT_S = 1
        self.assertEqual(o.signin_worker(), 1)
        st = o._signin_load()
        self.assertEqual(st["state"], "failed")
        self.assertIn("not finished", st["error"])

    def test_waits_for_a_running_plan_before_replanning(self):
        fake_az()
        o.CACHE.mkdir(parents=True, exist_ok=True)
        import fcntl
        import threading

        with open(o.LOCK, "a") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            threading.Timer(0.3, lambda: fcntl.flock(held, fcntl.LOCK_UN)).start()
            t0 = time.time()
            self.assertEqual(o.signin_worker(), 0)
        self.assertGreaterEqual(self.planned[0] - t0, 0.25)


class OnePrompt(unittest.TestCase):
    def setUp(self):
        o.SIGNIN.unlink(missing_ok=True)

    def test_second_click_ends_the_first_prompt(self):
        fake_az(login="sleep 30")
        ok, note1 = o.start_signin()
        self.assertTrue(ok)
        first = o._signin_load()["pid"]
        self.assertNotIn("earlier prompt was closed", note1)
        time.sleep(0.5)  # let the worker reach the prompt
        self.assertTrue(o._is_signin_worker(first))
        ok, note2 = o.start_signin()
        second = o._signin_load()["pid"]
        try:
            self.assertTrue(ok)
            self.assertNotEqual(first, second)
            self.assertIn("earlier prompt was closed", note2)
            self.assertTrue(wait_dead(first), "first worker still running")
            self.assertTrue(o._is_signin_worker(second))
            self.assertEqual(o.signin_view()["state"], "waiting")
        finally:
            os.killpg(second, signal.SIGTERM)
            wait_dead(second)

    def test_replanning_worker_is_left_alone(self):
        fake_az(login="sleep 30")
        ok, _ = o.start_signin()
        pid = o._signin_load()["pid"]
        try:
            time.sleep(0.3)
            o._signin_set(state="replanning")
            ok, note = o.start_signin()
            self.assertFalse(ok)
            self.assertIn("already signed in", note)
            self.assertEqual(o._signin_load()["pid"], pid)
        finally:
            os.killpg(pid, signal.SIGTERM)
            wait_dead(pid)

    def test_dead_worker_shows_failed(self):
        o._signin_set(state="waiting", pid=999999, started=o._now())
        v = o.signin_view()
        self.assertEqual(v["state"], "failed")
        self.assertIn("stopped before it finished", v["error"])

    def test_unrelated_pid_is_never_treated_as_ours(self):
        self.assertFalse(o._is_signin_worker(os.getpid()))
        self.assertFalse(o._is_signin_worker(None))
        self.assertFalse(o._is_signin_worker("x"))

    def test_get_carries_the_signin(self):
        o._signin_set(
            state="done", pid=1, started=o._now(), finished=o._now(), user=ADMIN, error=None
        )
        self.assertEqual(o.get()["signin"]["state"], "done")

    def test_request_signin_returns_202(self):
        fake_az(login="sleep 30")
        code, body = o.request({}, "signin")
        pid = o._signin_load()["pid"]
        try:
            self.assertEqual(code, 202)
            self.assertIn("Every Owner root is re-planned by itself", body["done"][0])
        finally:
            time.sleep(0.3)
            os.killpg(pid, signal.SIGTERM)
            wait_dead(pid)


if __name__ == "__main__":
    unittest.main()
