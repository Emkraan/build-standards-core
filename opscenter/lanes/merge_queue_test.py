"""
merge_queue_test.py
Purpose: Synthetic tests for merge_queue.enqueue. gh is a fake that models one PR, so
         nothing touches GitHub: a stale SQUASH request is disabled then enqueued and verified,
         an already queued PR is a no-op, an enqueue that does not take raises, and a repo
         with no merge queue still works.
Run:     /usr/bin/python3 merge_queue_test.py
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import merge_queue as mq  # noqa: E402

HEAD = "a" * 40
REPO = "example/synthetic"


class FakeGh:
    """One PR. enqueue_takes False models GitHub ignoring the request. has_queue False models a repo
    with no merge queue. no_method_ok False models gh demanding a method flag."""

    def __init__(
        self,
        auto=None,
        queued=False,
        state="OPEN",
        head=HEAD,
        enqueue_takes=True,
        has_queue=True,
        no_method_ok=True,
        threads=None,
        direct_error=None,
    ):
        self.auto, self.queued, self.state, self.head = auto, queued, state, head
        self.enqueue_takes, self.has_queue, self.no_method_ok = (
            enqueue_takes,
            has_queue,
            no_method_ok,
        )
        # threads: list of (id, first comment author, resolved). Unresolved threads block like main's ruleset.
        self.threads = [list(t) for t in (threads or [])]
        self.direct_error = direct_error
        self.calls = []

    def _blocked(self):
        return any(not t[2] for t in self.threads)

    def __call__(self, args, timeout=60, raw=False):
        self.calls.append(list(args))
        if args[:2] == ["api", "graphql"]:
            q = next(a for a in args if a.startswith("query="))
            if "reviewThreads" in q:
                nodes = [
                    {
                        "id": t[0],
                        "isResolved": t[2],
                        "path": "README.md",
                        "line": 1,
                        "comments": {"nodes": [{"author": {"login": t[1]}}]},
                    }
                    for t in self.threads
                ]
                return json.dumps(
                    {
                        "data": {
                            "repository": {
                                "pullRequest": {"id": "PR1", "reviewThreads": {"nodes": nodes}}
                            }
                        }
                    }
                )
            if "resolveReviewThread" in q:
                tid = next(a for a in args if a.startswith("t="))[2:]
                for t in self.threads:
                    if t[0] == tid:
                        t[2] = True
                return json.dumps(
                    {"data": {"resolveReviewThread": {"thread": {"isResolved": True}}}}
                )
            if "enqueuePullRequest" in q:
                if self._blocked():
                    raise RuntimeError(
                        "gh: Pull request A conversation must be resolved before this pull request can be merged."
                    )
                if self.direct_error:
                    raise RuntimeError(f"gh: {self.direct_error}")
                self.queued, self.auto = True, None
                return json.dumps(
                    {
                        "data": {
                            "enqueuePullRequest": {
                                "mergeQueueEntry": {"position": 1, "state": "QUEUED"}
                            }
                        }
                    }
                )
            if "pullRequest(number:$n){id}" in q:
                return json.dumps({"data": {"repository": {"pullRequest": {"id": "PR1"}}}})
            if "mergeQueue(branch" in q:
                return json.dumps(
                    {
                        "data": {
                            "repository": {"mergeQueue": {"id": "x"} if self.has_queue else None}
                        }
                    }
                )
            pr = {
                "state": self.state,
                "headRefOid": self.head,
                "baseRefName": "main",
                "isInMergeQueue": self.queued,
                "autoMergeRequest": {"mergeMethod": self.auto} if self.auto else None,
                "mergeQueueEntry": {"position": 1, "state": "AWAITING_CHECKS"}
                if self.queued
                else None,
            }
            return json.dumps({"data": {"repository": {"pullRequest": pr}}})
        if "--disable-auto" in args:
            self.auto = None
            return ""
        if "--auto" in args:
            if "--rebase" not in args and not self.no_method_ok:
                raise RuntimeError("gh pr merge: a merge method is required")
            if self.enqueue_takes:
                if self.has_queue and self._blocked():
                    self.auto = "SQUASH"  # the PR 461 symptom: armed, never queued
                elif self.has_queue:
                    self.queued, self.auto = True, None
                else:
                    self.auto = "REBASE"
            return ""
        raise AssertionError(f"unexpected gh call {args}")

    def merges(self):
        return [c for c in self.calls if c[:2] == ["pr", "merge"]]


def run(g, **kw):
    return mq.enqueue(REPO, 434, HEAD, gh=g, sleep=lambda s: None, **kw)


class EnqueueTest(unittest.TestCase):
    def test_pr461_my_open_nits_block_until_my_approval_resolves_them(self):
        g = FakeGh(
            auto="SQUASH", threads=[("T1", "owner-login", False), ("T2", "owner-login", False)]
        )
        r = run(g, accept_own_threads="owner-login")
        self.assertEqual(r["status"], "queued")
        self.assertEqual(r["resolved_threads"], 2)
        self.assertIn("resolved 2 of review thread(s) of the owner", r["text"])
        self.assertTrue(all(t[2] for t in g.threads))

    def test_someone_elses_open_thread_refuses_and_names_it(self):
        g = FakeGh(threads=[("T1", "owner-login", False), ("T2", "other-user", False)])
        with self.assertRaises(mq.MergeQueueError) as cm:
            run(g, accept_own_threads="owner-login")
        self.assertIn("other-user on README.md:1", str(cm.exception))
        self.assertEqual(g.merges(), [])
        self.assertFalse(g.threads[0][2], "nothing resolved when the enqueue is refused")

    def test_resolved_threads_are_ignored(self):
        g = FakeGh(threads=[("T1", "other-user", True)])
        self.assertEqual(run(g, accept_own_threads="owner-login")["status"], "queued")

    def test_without_accept_my_threads_stay_and_github_reason_is_surfaced(self):
        g = FakeGh(auto="SQUASH", threads=[("T1", "owner-login", False)])
        with self.assertRaises(mq.MergeQueueError) as cm:
            run(g)
        self.assertIn("A conversation must be resolved", str(cm.exception))
        self.assertFalse(g.threads[0][2])

    def test_armed_not_queued_direct_enqueue_recovers(self):
        g = FakeGh(auto="SQUASH")
        orig = g.__call__

        def arms_only(args, timeout=60, raw=False):
            if "--auto" in args and "--disable-auto" not in args:
                g.calls.append(list(args))
                g.auto = "SQUASH"
                return ""
            return orig(args, timeout, raw)

        r = mq.enqueue(REPO, 434, HEAD, gh=arms_only, sleep=lambda s: None)
        self.assertEqual(r["status"], "queued")

    def test_stale_squash_request_is_disabled_then_enqueued(self):
        g = FakeGh(auto="SQUASH")
        r = run(g)
        m = g.merges()
        self.assertEqual(m[0][-1], "--disable-auto")
        self.assertIn("--auto", m[1])
        self.assertIn(HEAD, m[1])
        self.assertEqual(len(m), 2)
        self.assertEqual(
            (r["ok"], r["status"], r["text"]), (True, "queued", "in merge queue (position 1)")
        )

    def test_clean_pr_without_request_just_enqueues(self):
        g = FakeGh()
        r = run(g)
        self.assertEqual(len(g.merges()), 1)
        self.assertEqual(r["status"], "queued")

    def test_already_queued_is_a_no_op(self):
        g = FakeGh(queued=True)
        r = run(g)
        self.assertEqual(g.merges(), [])
        self.assertEqual(r["status"], "queued")

    def test_already_merged_is_ok(self):
        g = FakeGh(state="MERGED")
        self.assertEqual(run(g)["status"], "merged")
        self.assertEqual(g.merges(), [])

    def test_enqueue_that_does_not_take_raises(self):
        g = FakeGh(auto="SQUASH", enqueue_takes=False)
        with self.assertRaises(mq.MergeQueueError) as cm:
            run(g)
        self.assertIn("PR #434 did not enter the merge queue", str(cm.exception))

    def test_request_armed_but_never_enqueued_on_a_queue_repo_raises(self):
        # GitHub accepts the request and never enqueues it, the exact PR 434 symptom
        g = FakeGh(auto="SQUASH", direct_error="Pull request is in unstable state")
        orig = g.__call__

        def arms_only(args, timeout=60, raw=False):
            if "--auto" in args and "--disable-auto" not in args:
                g.calls.append(list(args))
                g.auto = "REBASE"
                return ""
            return orig(args, timeout, raw)

        with self.assertRaises(mq.MergeQueueError) as cm:
            mq.enqueue(REPO, 434, HEAD, gh=arms_only, sleep=lambda s: None)
        self.assertIn("auto-merge is armed but GitHub has not enqueued it", str(cm.exception))
        self.assertIn("GitHub says: gh: Pull request is in unstable state", str(cm.exception))

    def test_repo_without_a_queue_accepts_an_armed_auto_merge(self):
        g = FakeGh(has_queue=False)
        r = run(g)
        self.assertEqual(r["status"], "auto")
        self.assertIn("no merge queue", r["text"])

    def test_gh_demanding_a_method_falls_back_to_rebase(self):
        g = FakeGh(has_queue=False, no_method_ok=False)
        r = run(g)
        self.assertEqual(r["status"], "auto")
        self.assertIn("--rebase", g.merges()[-1])

    def test_gh_error_on_both_attempts_is_surfaced(self):
        g = FakeGh(no_method_ok=False)
        orig = g.__call__

        def boom(args, timeout=60, raw=False):
            if "--auto" in args:
                g.calls.append(list(args))
                raise RuntimeError("GraphQL: Pull request is not mergeable")
            return orig(args, timeout, raw)

        with self.assertRaises(mq.MergeQueueError) as cm:
            mq.enqueue(REPO, 434, HEAD, gh=boom, sleep=lambda s: None)
        self.assertIn("not mergeable", str(cm.exception))

    def test_moved_head_refuses_without_writing(self):
        g = FakeGh(head="b" * 40)
        with self.assertRaises(mq.MergeQueueError) as cm:
            run(g)
        self.assertIn("head moved", str(cm.exception))
        self.assertEqual(g.merges(), [])

    def test_closed_pr_refuses(self):
        g = FakeGh(state="CLOSED")
        with self.assertRaises(mq.MergeQueueError):
            run(g)
        self.assertEqual(g.merges(), [])

    def test_failed_read_fails_closed(self):
        def bad(args, timeout=60, raw=False):
            raise RuntimeError("network down")

        with self.assertRaises(mq.MergeQueueError) as cm:
            mq.enqueue(REPO, 434, HEAD, gh=bad, sleep=lambda s: None)
        self.assertIn("could not read", str(cm.exception))

    def test_failed_disable_stops_before_enqueue(self):
        g = FakeGh(auto="SQUASH")
        orig = g.__call__

        def bad(args, timeout=60, raw=False):
            if "--disable-auto" in args:
                raise RuntimeError("forbidden")
            return orig(args, timeout, raw)

        with self.assertRaises(mq.MergeQueueError) as cm:
            mq.enqueue(REPO, 434, HEAD, gh=bad, sleep=lambda s: None)
        self.assertIn("could not cancel", str(cm.exception))
        self.assertEqual(g.merges(), [])

    def test_queue_entry_appearing_late_is_found(self):
        g = FakeGh(auto="SQUASH")
        reads = {"n": 0}
        orig = g.__call__

        def slow(args, timeout=60, raw=False):
            if "--auto" in args and "--disable-auto" not in args:
                g.calls.append(list(args))
                return ""
            if args[:2] == ["api", "graphql"]:
                reads["n"] += 1
                if reads["n"] == 4:
                    g.queued = True
            return orig(args, timeout, raw)

        r = mq.enqueue(REPO, 434, HEAD, gh=slow, sleep=lambda s: None)
        self.assertEqual(r["status"], "queued")


if __name__ == "__main__":
    unittest.main()
