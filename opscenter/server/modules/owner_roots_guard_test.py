"""
owner_roots_guard_test.py
Purpose: The owner apply guard fails closed (a corrupt, unreadable or missing status file refuses, a missing one passes
         only with --allow-missing-status), --allow-pr skips a PR meant to lose its objects, an address matches with or
         without an index suffix on either side, the provider's open_pr_addresses makes the guard refuse a delete of an
         address an open PR declares (and refuse when that read fails), detect_ahead turns an unrecorded branch or hand
         apply into a detected hold, the terminal logging mode writes the decisions log record shape, a lock lag is
         retried on the provider's own error class, a protection the plan deletes is never handed to the lift, and a
         partial lift a failing before_apply reports is still restored.
Run:     python3 owner_roots_guard_test.py
"""

from __future__ import annotations

import json
import os
import tempfile
import types
import unittest
from pathlib import Path

import owner_roots as o

PATCHED = ("CACHE", "STATUS", "STATUS_LOCK", "DECISIONS", "provider", "_run")
KEY = "ident:dev"


class Provider:
    def __init__(self):
        self.open_prs = None
        self.detected = None
        self.fail = None

    def pr_state(self, pr):
        return ("open", None)

    def open_pr_addresses(self, root):
        if self.fail:
            raise RuntimeError(self.fail)
        return self.open_prs

    def detect_ahead(self, root):
        if self.fail:
            raise RuntimeError(self.fail)
        return self.detected


class Base(unittest.TestCase):
    def setUp(self):
        self._saved = {k: getattr(o, k) for k in PATCHED}
        self.dir = Path(tempfile.mkdtemp(prefix="owner-roots-guard-test-"))
        o.CACHE = self.dir / "cache"
        o.CACHE.mkdir()
        o.STATUS = o.CACHE / "status.json"
        o.STATUS_LOCK = o.CACHE / "status.lock"
        o.DECISIONS = self.dir / "decisions.jsonl"
        self.prov = Provider()
        o.provider = lambda: self.prov

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(o, k, v)

    def status(self, resources, hold=None):
        st = {"items": {KEY: {"state": "pending", "resources": resources}}, "pr_applied": {}}
        if hold:
            st["pr_applied"][KEY] = hold
        o.STATUS.write_text(json.dumps(st))

    def records(self):
        return [json.loads(x) for x in o.DECISIONS.read_text().splitlines()]


def hold(addresses, pr=513):
    return {"pr": pr, "head": "a" * 40, "addresses": addresses, "pr_state": "open"}


DESTROY = [{"address": 'x.a["k"]', "action": "destroy"}, {"address": "y.b", "action": "add"}]


class FailClosed(Base):
    def test_a_missing_status_file_refuses_and_names_the_cause(self):
        self.assertFalse(o.STATUS.exists())
        self.assertEqual(o.main(["guard", "ident", "dev"]), 3)

    def test_a_missing_status_file_passes_only_with_the_opt_out(self):
        self.assertEqual(o.main(["guard", "ident", "dev", "--allow-missing-status"]), 0)

    def test_a_corrupt_status_file_refuses_even_with_the_opt_out(self):
        o.STATUS.write_text("{not json")
        self.assertEqual(o.main(["guard", "ident", "dev"]), 3)
        self.assertEqual(o.main(["guard", "ident", "dev", "--allow-missing-status"]), 3)
        _, cause = o._read_status_strict()
        self.assertIn("corrupt", cause)

    def test_a_status_of_the_wrong_shape_refuses(self):
        o.STATUS.write_text(json.dumps({"items": [], "pr_applied": {}}))
        self.assertEqual(o.main(["guard", "ident", "dev"]), 3)
        self.status(DESTROY, {"pr": "not a number", "addresses": ["x.a"]})
        self.assertEqual(o.main(["guard", "ident", "dev"]), 3)

    def test_an_unreadable_status_file_refuses(self):
        o.STATUS.mkdir()  # a directory where the file should be: reading it fails
        self.assertEqual(o.main(["guard", "ident", "dev", "--allow-missing-status"]), 3)

    def test_a_readable_status_with_no_conflict_is_ok(self):
        self.status(DESTROY)
        self.assertEqual(o.main(["guard", "ident", "dev"]), 0)

    def test_bad_arguments_are_exit_2(self):
        self.assertEqual(o.main(["guard", "ident"]), 2)
        self.assertEqual(o.main(["guard", "ident", "dev", "--allow-pr", "x"]), 2)


class AllowPr(Base):
    def test_allow_pr_skips_the_hold_of_a_pr_meant_to_lose_its_objects(self):
        self.status(DESTROY, hold(['x.a["k"]']))
        self.assertEqual(o.main(["guard", "ident", "dev"]), 3)
        self.assertEqual(o.main(["guard", "ident", "dev", "--allow-pr", "513"]), 0)
        self.assertEqual(o.main(["guard", "ident", "dev", "--allow-pr", "7"]), 3)

    def test_allow_pr_skips_only_that_open_pr(self):
        self.status(DESTROY)
        self.prov.open_prs = [
            {"number": 265, "addresses": ["x.a"]},
            {"number": 300, "addresses": []},
        ]
        self.assertEqual(o.main(["guard", "ident", "dev"]), 3)
        self.assertEqual(o.main(["guard", "ident", "dev", "--allow-pr", "265"]), 0)


class IndexSuffix(unittest.TestCase):
    def test_base_address(self):
        self.assertEqual(o.base_address('x.a["k"]'), "x.a")
        self.assertEqual(o.base_address('module.m["a"].x.y[0]'), "module.m.x.y")
        self.assertEqual(o.base_address('x.a["a]b"]'), "x.a")

    def test_both_directions_and_never_two_different_instances(self):
        self.assertEqual(o._addr_hits(['x.a["k"]'], ["x.a"]), ['x.a["k"]'])
        self.assertEqual(o._addr_hits(["x.a"], ['x.a["k"]']), ["x.a"])
        self.assertEqual(o._addr_hits(['x.a["k"]'], ['x.a["k"]']), ['x.a["k"]'])
        self.assertEqual(o._addr_hits(['x.a["j"]'], ['x.a["k"]']), [])
        self.assertEqual(o._addr_hits(["x.ab"], ["x.a"]), [])


class IndexSuffixGuard(Base):
    def test_a_hold_of_the_base_address_refuses_a_delete_of_an_instance(self):
        self.status(DESTROY, hold(["x.a"]))
        self.assertIn("waiting on #513", o.guard_refusal("ident", "dev", {"resources": DESTROY}))

    def test_a_hold_of_an_instance_refuses_a_delete_of_the_base(self):
        res = [{"address": "x.a", "action": "replace"}]
        self.status(res, hold(['x.a["k"]']))
        self.assertIn("waiting on #513", o.guard_refusal("ident", "dev", {"resources": res}))
        self.assertEqual(o._hold_check("ident", "dev", res, "m" * 40)["addresses"], ["x.a"])


class OpenPrCoverage(Base):
    def test_no_hook_and_a_null_answer_change_nothing(self):
        self.status(DESTROY)
        o.provider = lambda: None
        self.assertIsNone(o.guard_refusal("ident", "dev", {"resources": DESTROY}))
        o.provider = lambda: self.prov
        self.assertIsNone(o.guard_refusal("ident", "dev", {"resources": DESTROY}))

    def test_a_delete_of_an_address_an_open_pr_declares_is_refused(self):
        self.status(DESTROY)
        self.prov.open_prs = [{"number": 265, "addresses": ["x.a"]}]
        why = o.guard_refusal("ident", "dev", {"resources": DESTROY})
        self.assertIn("open PR #265", why)
        self.assertIn('x.a["k"]', why)
        self.assertEqual(o.main(["guard", "ident", "dev"]), 3)

    def test_an_open_pr_that_declares_something_else_passes(self):
        self.status(DESTROY)
        self.prov.open_prs = [{"number": 265, "addresses": ["z.c"]}]
        self.assertIsNone(o.guard_refusal("ident", "dev", {"resources": DESTROY}))

    def test_a_failed_read_refuses(self):
        self.status(DESTROY)
        self.prov.fail = "gh down"
        self.assertIn("could not be read", o.guard_refusal("ident", "dev", {"resources": DESTROY}))
        self.assertEqual(o.main(["guard", "ident", "dev"]), 3)

    def test_a_plan_with_no_delete_never_asks(self):
        self.prov.fail = "never asked"
        add = [{"address": "y.b", "action": "add"}]
        self.assertIsNone(o.guard_refusal("ident", "dev", {"resources": add}))


class DetectAhead(Base):
    def test_no_hook_leaves_an_unrecorded_root_alone(self):
        self.status(DESTROY)
        o.provider = lambda: None
        self.assertIsNone(o._hold_check("ident", "dev", DESTROY, "m" * 40))

    def test_a_detected_pr_becomes_a_detected_hold(self):
        self.status(DESTROY)
        self.prov.detected = {"pr": 77, "head": "h" * 40, "addresses": ["x.a", "q.r"]}
        ahead = o._hold_check("ident", "dev", DESTROY, "m" * 40)
        self.assertEqual((ahead["pr"], ahead["addresses"]), (77, ['x.a["k"]']))
        rec = o._holds()[KEY]
        self.assertEqual((rec["source"], rec["pr_state"]), ("detected", "open"))
        self.assertTrue(rec["detected_at"])
        self.assertIsNone(rec["applied_at"])
        self.assertIn("waiting on #77", o.guard_refusal("ident", "dev", {"resources": DESTROY}))

    def test_a_failed_read_changes_nothing_and_is_logged(self):
        self.status(DESTROY)
        self.prov.fail = "unreadable"
        self.assertIsNone(o._hold_check("ident", "dev", DESTROY, "m" * 40))
        self.assertNotIn(KEY, o._holds())
        self.assertEqual(self.records()[-1]["decision"], "owner_apply_pr_ahead_unread")

    def test_not_asked_when_main_destroys_nothing(self):
        self.prov.fail = "never asked"
        self.assertIsNone(o._hold_check("ident", "dev", [{"address": "y.b", "action": "add"}], "m"))


class TerminalLog(Base):
    def test_log_start_and_done_write_the_record_shape(self):
        args = ["--root", "ident:dev", "--sha", "abc123"]
        self.assertEqual(o.main(["--log-start", *args, "--by", "Admin@Example.com"]), 0)
        self.assertEqual(o.main(["--log-done", *args]), 0)
        start, done = self.records()
        self.assertEqual(
            {k: start[k] for k in ("decision", "root", "sha", "by", "lane")},
            {
                "decision": "owner_apply_started",
                "root": "ident:dev",
                "sha": "abc123",
                "by": "admin@example.com",
                "lane": "owner",
            },
        )
        self.assertTrue(start["ts"].endswith("Z"))
        self.assertEqual(
            (done["decision"], done["result"], done["locks_restored"]),
            ("owner_apply_done", "terminal apply", 0),
        )
        self.assertNotIn("by", done)

    def test_by_defaults_to_the_expected_identity(self):
        self.prov.expected_identity = "Owner-Account"
        self.assertEqual(o.main(["--log-start", "--root", "a:b", "--sha", "s"]), 0)
        self.assertEqual(self.records()[-1]["by"], "owner-account")

    def test_bad_arguments_and_write_errors_are_exit_2(self):
        self.assertEqual(o.main(["--log-start", "--root", "nocolon", "--sha", "x", "--by", "a"]), 2)
        self.assertEqual(o.main(["--log-start", "--root", "a:b", "--by", "a"]), 2)
        self.assertEqual(o.main(["--log-start", "--log-done", "--root", "a:b", "--sha", "x"]), 2)
        self.assertEqual(
            o.main(["--log-start", "--root", "a:b", "--sha", "x"]), 2
        )  # no --by, no identity
        o.DECISIONS = self.dir / "no" / "such" / "dir" / "decisions.jsonl"
        self.assertEqual(o.main(["--log-done", "--root", "a:b", "--sha", "x"]), 2)


def fake_runs(*outputs):
    calls = []
    seq = list(outputs)

    def run(args, cwd=None, timeout=1200, log=None):
        calls.append(args)
        rc, text = seq.pop(0)
        return types.SimpleNamespace(
            returncode=rc, stdout=text if not rc else "", stderr=text if rc else ""
        )

    return run, calls


class LockHooks(Base):
    def setUp(self):
        super().setUp()
        self._retry = os.environ.get("OWNER_ROOTS_RETRY_S")
        os.environ["OWNER_ROOTS_RETRY_S"] = "0"
        self.addCleanup(
            lambda: (
                os.environ.pop("OWNER_ROOTS_RETRY_S", None)
                if self._retry is None
                else os.environ.__setitem__("OWNER_ROOTS_RETRY_S", self._retry)
            )
        )
        self.plan = self.dir / "p.tfplan"
        self.plan.write_bytes(b"x")
        self.seen = []
        prov = self.prov
        prov.before_apply = lambda deletes, log: {"lifted": deletes}
        prov.after_apply = lambda state, log: self.seen.append(state) or (1, [])
        prov.error_kinds = lambda: [("scope_locked", r"ScopeLocked", "A lock blocked a delete.")]

    def apply(self):
        return o._apply_with_hooks(KEY, self.dir, self.plan, ["/r/1"], self.dir / "locks", None)

    def test_a_lock_lag_is_retried_on_the_providers_class(self):
        self.prov.retry_kinds = lambda: ["scope_locked"]
        o._run, calls = fake_runs(
            (1, "Error: ScopeLocked: the scope is locked"), (0, "Apply complete! x")
        )
        self.assertEqual(self.apply(), ("Apply complete! x", 1))
        self.assertEqual(len(calls), 2)

    def test_without_retry_kinds_the_same_failure_is_not_retried(self):
        o._run, calls = fake_runs(
            (1, "Error: ScopeLocked: the scope is locked"), (0, "Apply complete!")
        )
        with self.assertRaises(RuntimeError):
            self.apply()
        self.assertEqual(len(calls), 1)

    def test_nothing_lifted_means_no_retry(self):
        self.prov.retry_kinds = lambda: ["scope_locked"]
        self.prov.before_apply = lambda deletes, log: None
        o._run, calls = fake_runs((1, "Error: ScopeLocked"), (0, "Apply complete!"))
        with self.assertRaises(RuntimeError):
            self.apply()
        self.assertEqual(len(calls), 1)

    def test_a_partial_lift_from_a_failing_before_apply_is_restored(self):
        class Blocked(RuntimeError):
            state = {"lifted": ["/r/1"]}

        def before(deletes, log, state_dir):
            self.state_dir = state_dir
            raise Blocked("a wider lock covers a delete")

        self.prov.before_apply = before
        o._run, calls = fake_runs()
        with self.assertRaises(Blocked):
            self.apply()
        self.assertEqual(calls, [])  # nothing applied
        self.assertEqual(self.seen, [{"lifted": ["/r/1"]}])
        self.assertTrue(self.state_dir.is_dir())

    def test_a_protection_the_plan_deletes_is_left_out_of_deletes(self):
        self.prov.is_protection = lambda rid: "/locks/" in rid
        show = {
            "resource_changes": [
                {"change": {"actions": ["delete"], "before": {"id": "/r/1/locks/keep"}}},
                {"change": {"actions": ["delete", "create"], "before": {"id": "/r/2|x"}}},
            ]
        }
        self.assertEqual(o._plan_deletes(show), ["/r/2"])
        o.provider = lambda: None
        self.assertEqual(o._plan_deletes(show), ["/r/1/locks/keep", "/r/2"])


if __name__ == "__main__":
    unittest.main()
