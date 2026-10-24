"""Tests for v0.87.0: pushes retry a transient network failure and never retry a rejection."""

from unittest import mock

from support import Work, load

ops = load("ops_center_v087", "hermes/ops_center.py")
mp = load("merge_pr_v087", "templates/overlay/scripts/merge-pr.py")
DROP = "send-pack: unexpected disconnect while reading sideband packet\nfatal: the remote end hung up unexpectedly"


class OpsPush(Work):
    def seq(self, results, calls):
        it = iter(results)

        def sh(cmd, *a, **k):
            calls.append(cmd)
            return next(it)

        return sh

    def test_retries_a_dropped_connection(self):
        calls = []
        rc, _ = ops.push(self.seq([(1, DROP), (0, "")], calls), self.dir, "origin", "x", pause=0)
        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 2)
        self.assertIn("http.postBuffer=524288000", calls[0])

    def test_never_retries_a_rejection(self):
        calls = []
        rc, _ = ops.push(
            self.seq([(1, "! [rejected] (stale info)")], calls), self.dir, "origin", "x", pause=0
        )
        self.assertEqual((rc, len(calls)), (1, 1))

    def test_gives_up_after_three(self):
        calls = []
        rc, _ = ops.push(self.seq([(1, DROP)] * 3, calls), self.dir, "origin", "x", pause=0)
        self.assertEqual((rc, len(calls)), (1, 3))


class MergePrPush(Work):
    def test_retries_then_succeeds(self):
        results = iter([(1, "", DROP), (0, "", "")])
        calls = []
        with (
            mock.patch.object(mp, "git", lambda *a, **k: (calls.append(a), next(results))[1]),
            mock.patch("builtins.print"),
        ):
            self.assertEqual(mp.push("-q", "r", "a:b", pause=0)[0], 0)
        self.assertEqual(len(calls), 2)

    def test_lease_failure_is_not_retried(self):
        calls = []
        with mock.patch.object(
            mp, "git", lambda *a, **k: (calls.append(a), (1, "", "! [rejected] stale info"))[1]
        ):
            self.assertEqual(mp.push("-q", "r", "a:b", pause=0)[0], 1)
        self.assertEqual(len(calls), 1)
