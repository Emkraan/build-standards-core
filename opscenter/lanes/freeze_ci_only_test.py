"""
freeze_ci_only_test.py
Purpose: A pull request that only changes how CI checks pull requests is not held by a change freeze, and anything the
         classifier cannot be sure of is held: a non-CI file, a workflow that can run on a push, a script a push workflow runs
         (directly or through another script), a script no workflow names, a file it cannot read, an empty file list.
Run:     python3 freeze_ci_only_test.py
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import freeze_ci_only as f

PR_WF = "name: ci\non:\n  pull_request:\n    branches: [main]\njobs:\n  a:\n    steps:\n      - run: scripts/check.sh\n"
PUSH_WF = "name: deploy\non:\n  push:\n    branches: [main]\n  pull_request:\njobs:\n  a:\n    steps:\n      - run: scripts/check.sh\n"


def world(head, base=None, workflows=None, scripts=None):
    base = head if base is None else base
    return dict(
        read_head=head.get,
        read_base=base.get,
        list_workflows=lambda: (
            workflows
            if workflows is not None
            else [p for p in {**head, **base} if p.startswith(".github/workflows/")]
        ),
        list_scripts=lambda: (
            scripts
            if scripts is not None
            else [
                p
                for p in {**head, **base}
                if p.startswith(".github/scripts/") or p.startswith("scripts/")
            ]
        ),
    )


class Triggers(unittest.TestCase):
    def test_every_form_of_the_on_block(self):
        self.assertEqual(f.triggers("on: push\n"), {"push"})
        self.assertEqual(f.triggers("on: [push, pull_request]\n"), {"push", "pull_request"})
        self.assertEqual(
            f.triggers("'on':\n  pull_request:\n  schedule:\n    - cron: '1 1 * * *'\n"),
            {"pull_request", "schedule"},
        )
        self.assertEqual(f.triggers("on:\n  - push\n  - merge_group\n"), {"push", "merge_group"})
        self.assertEqual(f.triggers("on: {push: {}, pull_request: {}}\n"), {"push", "pull_request"})
        self.assertIsNone(f.triggers("name: x\njobs: {}\n"))  # no on block: unknown


class Classify(unittest.TestCase):
    def ok(self, files, **kw):
        return f.classify(files, **world(**kw))

    def test_a_pull_request_only_workflow_is_ci_only(self):
        ok, why = self.ok([".github/workflows/ci.yml"], head={".github/workflows/ci.yml": PR_WF})
        self.assertTrue(ok, why)

    def test_a_new_workflow_has_no_base_side(self):
        ok, why = f.classify(
            [".github/workflows/ci.yml"],
            **{
                **world({".github/workflows/ci.yml": PR_WF}, base={}),
                "list_workflows": lambda: [".github/workflows/ci.yml"],
            },
        )
        self.assertTrue(ok, why)

    def test_a_workflow_that_runs_on_push_is_held_on_either_side(self):
        ok, why = self.ok([".github/workflows/d.yml"], head={".github/workflows/d.yml": PUSH_WF})
        self.assertFalse(ok)
        self.assertIn("push", why)
        # the head removes the push trigger, but the base had it: still held
        ok, why = self.ok(
            [".github/workflows/d.yml"],
            head={".github/workflows/d.yml": PR_WF},
            base={".github/workflows/d.yml": PUSH_WF},
        )
        self.assertFalse(ok)
        self.assertIn("(base)", why)

    def test_a_file_outside_the_ci_paths_is_held(self):
        ok, why = self.ok(
            [".github/workflows/ci.yml", "app/server/index.js"],
            head={".github/workflows/ci.yml": PR_WF},
        )
        self.assertFalse(ok)
        self.assertIn("app/server/index.js", why)

    def test_no_changed_files_is_held(self):
        self.assertFalse(f.classify([], **world({}))[0])

    def test_a_script_used_by_a_pull_request_only_workflow_is_ci_only(self):
        head = {".github/workflows/ci.yml": PR_WF, ".github/scripts/check.sh": "echo hi\n"}
        ok, why = f.classify([".github/scripts/check.sh"], **world(head))
        self.assertTrue(ok, why)

    def test_a_script_used_by_a_push_workflow_is_held(self):
        head = {
            ".github/workflows/d.yml": PUSH_WF.replace(
                "scripts/check.sh", ".github/scripts/check.sh"
            ),
            ".github/scripts/check.sh": "x\n",
        }
        ok, why = f.classify([".github/scripts/check.sh"], **world(head))
        self.assertFalse(ok)
        self.assertIn("used by", why)

    def test_a_script_used_through_another_script_is_held(self):
        head = {
            ".github/workflows/d.yml": PUSH_WF.replace(
                "scripts/check.sh", ".github/scripts/outer.sh"
            ),
            ".github/scripts/outer.sh": "bash .github/scripts/inner.sh\n",
            ".github/scripts/inner.sh": "echo\n",
        }
        ok, why = f.classify([".github/scripts/inner.sh"], **world(head))
        self.assertFalse(ok, why)

    def test_a_script_no_workflow_names_is_held(self):
        head = {
            ".github/workflows/ci.yml": PR_WF.replace("scripts/check.sh", "other"),
            ".github/scripts/lonely.sh": "x\n",
        }
        ok, why = f.classify([".github/scripts/lonely.sh"], **world(head))
        self.assertFalse(ok)
        self.assertIn("unknown", why)

    def test_a_workflow_that_the_base_names_is_found_even_if_the_head_stopped_naming_it(self):
        head = {
            ".github/workflows/d.yml": PUSH_WF.replace("scripts/check.sh", "other"),
            ".github/scripts/check.sh": "x\n",
        }
        base = {
            ".github/workflows/d.yml": PUSH_WF.replace(
                "scripts/check.sh", ".github/scripts/check.sh"
            )
        }
        ok, why = f.classify([".github/scripts/check.sh"], **world(head, base))
        self.assertFalse(ok, why)

    def test_unreadable_is_held(self):
        ok, why = f.classify(
            [".github/workflows/ci.yml"],
            read_head=lambda p: None,
            read_base=lambda p: None,
            list_workflows=lambda: [".github/workflows/ci.yml"],
            list_scripts=lambda: [],
        )
        self.assertFalse(ok)
        self.assertIn("could not be read", why)
        self.assertFalse(
            self.ok(
                [".github/workflows/x.yml"], head={".github/workflows/x.yml": "name: no triggers\n"}
            )[0]
        )


class Fetch(unittest.TestCase):
    def test_a_failed_listing_is_held(self):
        def gh(args, raw=False):
            raise RuntimeError("boom")

        ok, why = f.fetch_and_classify(gh, "o/r", 5, "h", "b")
        self.assertFalse(ok)
        self.assertIn("could not be listed", why)

    def test_reads_both_sides_through_the_code_host(self):
        import base64

        def enc(t):
            return base64.b64encode(t.encode()).decode()

        def gh(args, raw=False):
            a = " ".join(args)
            if "/files" in a:
                return ".github/workflows/ci.yml\n"
            if "git/trees" in a:
                return ".github/workflows/ci.yml\napp/x.js\n"
            if "contents/.github/workflows/ci.yml" in a:
                return enc(PR_WF)
            raise RuntimeError(a)

        ok, why = f.fetch_and_classify(gh, "o/r", 5, "h", "b")
        self.assertTrue(ok, why)


if __name__ == "__main__":
    unittest.main()
