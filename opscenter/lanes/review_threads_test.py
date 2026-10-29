"""
review_threads_test.py
Purpose: review_threads against a fake gh runner: read keeps only unresolved threads, others() drops mine,
         notify tags each author once (a second call posts nothing), automated threads are listed and never
         tagged, resolve refuses a thread that is not open, and every read failure raises ThreadError.
Run:     python3 review_threads_test.py
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import review_threads as rt  # noqa: E402

REPO = "acme/repo"
HEAD = "a" * 40


def node(tid, login, resolved=False, typename="User", path="a.py", line=3):
    c = {
        "author": {"login": login, "__typename": typename},
        "body": "please  fix\nthis",
        "url": f"https://x/{tid}",
    }
    return {
        "id": tid,
        "isResolved": resolved,
        "isOutdated": False,
        "path": path,
        "line": line,
        "originalLine": line,
        "comments": {"nodes": [c]},
    }


class FakeGh:
    def __init__(self, nodes):
        self.nodes = nodes
        self.comments = []
        self.mutations = []
        self.fail = False

    def __call__(self, args, timeout=60, raw=False):
        if self.fail:
            raise RuntimeError("boom")
        if args[:2] == ["api", "graphql"]:
            q = next(a for a in args if a.startswith("query="))
            if "resolveReviewThread" in q:
                self.mutations.append(args[-1])
                return "{}"
            return json.dumps(
                {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": self.nodes}}}}}
            )
        if args[0] == "api" and "/comments" in args[1]:
            return json.dumps(self.comments)
        if args[:2] == ["pr", "comment"]:
            body = args[args.index("--body") + 1]
            self.comments.append({"user": {"login": "owner"}, "body": body})
            return ""
        raise AssertionError(args)


class Threads(unittest.TestCase):
    def test_read_keeps_unresolved_and_flattens_the_text(self):
        gh = FakeGh(
            [
                node("T_1", "alice"),
                node("T_2", "bob", resolved=True),
                node("T_3", "ci[bot]", typename="Bot"),
            ]
        )
        got = rt.read(gh, REPO, 5)
        self.assertEqual([t["id"] for t in got], ["T_1", "T_3"])
        self.assertEqual(got[0]["last_text"], "please fix this")
        self.assertTrue(got[1]["automated"])

    def test_others_drops_my_own_threads(self):
        got = rt.read(FakeGh([node("T_1", "Owner"), node("T_2", "alice")]), REPO, 5)
        self.assertEqual([t["id"] for t in rt.others(got, "owner")], ["T_2"])

    def test_notify_tags_once_and_never_tags_a_bot(self):
        gh = FakeGh([node("T_1", "alice"), node("T_3", "ci[bot]", typename="Bot")])
        threads = rt.read(gh, REPO, 5)
        self.assertEqual(rt.notify(gh, REPO, 5, HEAD, threads, "owner"), ["alice"])
        self.assertIn("@alice", gh.comments[0]["body"])
        self.assertIn("Automated review", gh.comments[0]["body"])
        self.assertNotIn("@ci[bot]", gh.comments[0]["body"])
        self.assertEqual(rt.notify(gh, REPO, 5, HEAD, threads, "owner"), [])
        self.assertEqual(len(gh.comments), 1)
        gh.nodes.append(node("T_4", "carol"))
        self.assertEqual(rt.notify(gh, REPO, 5, HEAD, rt.read(gh, REPO, 5), "owner"), ["carol"])

    def test_nothing_is_posted_without_threads(self):
        gh = FakeGh([])
        self.assertEqual(rt.notify(gh, REPO, 5, HEAD, [], "owner"), [])
        self.assertEqual(gh.comments, [])

    def test_resolve_needs_an_open_thread_on_this_pr(self):
        gh = FakeGh([node("T_open1", "alice")])
        with self.assertRaises(rt.ThreadError):
            rt.resolve(gh, REPO, 5, "T_gone1")
        with self.assertRaises(rt.ThreadError):
            rt.resolve(gh, REPO, 5, "bad id!")
        self.assertEqual(rt.resolve(gh, REPO, 5, "T_open1")["starter"], "alice")
        self.assertEqual(gh.mutations, ["t=T_open1"])

    def test_every_read_failure_raises_thread_error(self):
        gh = FakeGh([])
        gh.fail = True
        with self.assertRaises(rt.ThreadError):
            rt.read(gh, REPO, 5)
        with self.assertRaises(rt.ThreadError):
            rt.announced(gh, REPO, 5, "owner")

    def test_the_marker_names_the_head_and_every_thread(self):
        body, _ = rt.comment_body(
            [
                {
                    "id": "T_1",
                    "starter": "a",
                    "automated": False,
                    "path": None,
                    "line": None,
                    "url": None,
                }
            ],
            HEAD,
            {"T_1"},
        )
        self.assertIn(f"<!-- open-threads:{HEAD} T_1 -->", body)
        self.assertIn("on the PR", body)


if __name__ == "__main__":
    unittest.main()
