"""
pr_gate_test.py
Purpose: The draft gate block grammar: no block is None; a block with a continuation line joins it; a line that is not
         `kind: argument` or a kind nobody registered is an error and is never met; an empty block is never met; every line met
         is a pass; a check that raises is unmet; the consumer adds kinds; the built-in kinds read live data through gh.
Run:     python3 pr_gate_test.py
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pr_gate as g

BLOCK = "Why\n\n```gate\n# first\npr-merged: 513\nlogs-quiet: no deletes\n  and the run is fresh\n```\n\nmore text\n"


def runner(answers):
    def run(args):
        class R:
            stdout = json.dumps(answers[args[0] + " " + args[1]])

        return R()

    return run


class Grammar(unittest.TestCase):
    def test_no_block(self):
        self.assertIsNone(g.parse("just a description"))
        self.assertIsNone(g.parse(""))
        self.assertIsNone(g.parse(None))

    def test_block_with_continuation_comments_and_blank_lines(self):
        gate = g.parse(BLOCK)
        self.assertEqual(
            [(x["kind"], x["arg"]) for x in gate["lines"]],
            [("pr-merged", "513"), ("logs-quiet", "no deletes and the run is fresh")],
        )

    def test_bad_lines_are_errors(self):
        gate = g.parse("```gate\nthis has no colon\n: no kind\nok: fine\n```")
        self.assertEqual([bool(x["error"]) for x in gate["lines"]], [True, True, False])
        res = g.evaluate(gate, "o/r", kinds={"ok": lambda a, r, run: (True, "fine")})
        self.assertEqual([x["met"] for x in res], [False, False, True])
        self.assertIn("error", res[0]["detail"])

    def test_an_unknown_kind_is_never_met(self):
        res = g.evaluate(g.parse("```gate\nnope: x\n```"), "o/r")
        self.assertFalse(res[0]["met"])
        self.assertIn("unknown kind", res[0]["detail"])

    def test_an_unclosed_block_still_reads_to_the_end(self):
        self.assertEqual(len(g.parse("```gate\na: 1\nb: 2")["lines"]), 2)


class Evaluate(unittest.TestCase):
    def test_all_met(self):
        gate = g.parse(BLOCK)
        run = runner({"pr view": {"state": "MERGED", "mergedAt": "2026-01-01T00:00:00Z"}})
        res = g.evaluate(
            gate, "o/r", kinds={"logs-quiet": lambda a, r, run: (True, "quiet")}, run=run
        )
        met, total, first = g.summary(res)
        self.assertEqual((met, total, first), (2, 2, None))

    def test_the_first_unmet_line_is_named(self):
        gate = g.parse(BLOCK)
        run = runner({"pr view": {"state": "OPEN", "mergedAt": None}})
        res = g.evaluate(
            gate, "o/r", kinds={"logs-quiet": lambda a, r, run: (True, "quiet")}, run=run
        )
        met, total, first = g.summary(res)
        self.assertEqual((met, total), (1, 2))
        self.assertEqual(first["label"], "pr-merged: 513")
        self.assertIn("open", first["detail"])

    def test_a_check_that_raises_is_unmet_not_a_pass(self):
        def boom(a, r, run):
            raise RuntimeError("the code host is down")

        res = g.evaluate(g.parse("```gate\nx: 1\n```"), "o/r", kinds={"x": boom})
        self.assertFalse(res[0]["met"])
        self.assertIn("could not check", res[0]["detail"])

    def test_an_empty_block_is_never_met(self):
        met, total, first = g.summary(g.evaluate(g.parse("```gate\n# nothing\n```"), "o/r"))
        self.assertEqual((met, total), (0, 0))
        self.assertIn("no lines", first["detail"])

    def test_run_success_reads_the_newest_completed_run(self):
        run = runner(
            {
                "run list": [
                    {"status": "in_progress", "conclusion": None},
                    {"status": "completed", "conclusion": "success"},
                ]
            }
        )
        res = g.evaluate(g.parse("```gate\nrun-success: terraform-ci main\n```"), "o/r", run=run)
        self.assertTrue(res[0]["met"])
        run = runner({"run list": [{"status": "completed", "conclusion": "failure"}]})
        self.assertFalse(
            g.evaluate(g.parse("```gate\nrun-success: terraform-ci main\n```"), "o/r", run=run)[0][
                "met"
            ]
        )
        self.assertFalse(
            g.evaluate(g.parse("```gate\nrun-success: onlyone\n```"), "o/r", run=run)[0]["met"]
        )

    def test_run_success_passes_on_any_newest_green_run_however_old(self):
        # documented: run-success has no reference point; `applied` is the kind that ties a run to a merge
        run = runner(
            {
                "run list": [
                    {
                        "status": "completed",
                        "conclusion": "success",
                        "startedAt": "2020-01-01T00:00:00Z",
                    }
                ]
            }
        )
        res = g.evaluate(g.parse("```gate\nrun-success: apply main\n```"), "o/r", run=run)
        self.assertTrue(res[0]["met"])


MERGED = {"state": "MERGED", "mergedAt": "2026-10-22T21:50:00Z"}
CONF = {"apply_workflow": "apply.yml", "apply_branch": "main"}
APPLIED = "```gate\napplied: #465\n```"


def apply_run(rid, conclusion, started, status="completed"):
    return {
        "databaseId": rid,
        "status": status,
        "conclusion": conclusion,
        "startedAt": started,
        "createdAt": started,
        "headBranch": "main",
    }


class Applied(unittest.TestCase):
    def check(self, pr, runs, config=CONF):
        calls = []

        def run(args):
            calls.append(args)

            class R:
                stdout = json.dumps(pr if args[:2] == ["pr", "view"] else runs)

            return R()

        res = g.evaluate(g.parse(APPLIED), "o/r", run=run, config=config)
        return res[0], calls

    def test_met_only_by_a_success_that_started_after_the_merge(self):
        r, calls = self.check(MERGED, [apply_run(7, "success", "2026-10-22T23:50:00Z")])
        self.assertTrue(r["met"], r)
        self.assertIn("run 7", r["detail"])
        run_list = next(c for c in calls if c[:2] == ["run", "list"])
        self.assertEqual(
            (run_list[run_list.index("--workflow") + 1], run_list[run_list.index("--branch") + 1]),
            ("apply.yml", "main"),
        )
        # a run that started exactly at the merge counts
        self.assertTrue(
            self.check(MERGED, [apply_run(8, "success", "2026-10-22T21:50:00Z")])[0]["met"]
        )

    def test_an_old_green_run_before_the_merge_is_not_applied(self):
        r, _ = self.check(MERGED, [apply_run(3, "success", "2026-10-22T20:00:00Z")])
        self.assertFalse(r["met"])
        self.assertIn("has not succeeded on main since the merge", r["detail"])
        r, _ = self.check(MERGED, [])
        self.assertFalse(r["met"])

    def test_a_failed_run_after_the_merge_is_named(self):
        r, _ = self.check(
            MERGED,
            [
                apply_run(9, "failure", "2026-10-22T23:00:00Z"),
                apply_run(3, "success", "2026-10-22T20:00:00Z"),
            ],
        )
        self.assertFalse(r["met"])
        self.assertIn("run 9", r["detail"])
        self.assertIn("failure", r["detail"])
        # an in-progress run after the merge is not a pass yet
        r, _ = self.check(
            MERGED, [apply_run(10, None, "2026-10-22T23:00:00Z", status="in_progress")]
        )
        self.assertFalse(r["met"])

    def test_an_unmerged_pr_is_not_applied(self):
        r, calls = self.check(
            {"state": "OPEN", "mergedAt": None}, [apply_run(7, "success", "2026-10-22T23:50:00Z")]
        )
        self.assertFalse(r["met"])
        self.assertIn("not merged", r["detail"])
        r, _ = self.check({"state": "MERGED", "mergedAt": None}, [])
        self.assertFalse(r["met"])
        self.assertIn("merge time", r["detail"])

    def test_not_configured_is_never_met_and_says_so(self):
        for k in ("OPSCENTER_GATE_APPLY_WORKFLOW", "OPSCENTER_GATE_APPLY_BRANCH"):
            os.environ.pop(k, None)
        r, calls = self.check(
            MERGED, [apply_run(7, "success", "2026-10-22T23:50:00Z")], config=None
        )
        self.assertFalse(r["met"])
        self.assertIn("no apply workflow", r["detail"])
        self.assertEqual(calls, [])
        r, _ = self.check(MERGED, [], config={"apply_workflow": "apply.yml", "apply_branch": None})
        self.assertFalse(r["met"])

    def test_the_settings_can_come_from_the_environment(self):
        os.environ["OPSCENTER_GATE_APPLY_WORKFLOW"] = "apply.yml"
        os.environ["OPSCENTER_GATE_APPLY_BRANCH"] = "main"
        try:
            r, _ = self.check(
                MERGED, [apply_run(7, "success", "2026-10-22T23:50:00Z")], config=None
            )
        finally:
            os.environ.pop("OPSCENTER_GATE_APPLY_WORKFLOW")
            os.environ.pop("OPSCENTER_GATE_APPLY_BRANCH")
        self.assertTrue(r["met"], r)

    def test_a_bad_argument_is_unmet(self):
        r = g.evaluate(g.parse("```gate\napplied: soon\n```"), "o/r", config=CONF)[0]
        self.assertFalse(r["met"])
        self.assertIn("not a pull request number", r["detail"])


class Consumer(unittest.TestCase):
    def test_the_consumer_adds_kinds_from_a_file(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "kinds.py"
            f.write_text("KINDS = {'always': lambda a, r, run: (True, 'yes ' + a)}\n")
            os.environ["OPSCENTER_GATE_KINDS"] = str(f)
            try:
                res = g.evaluate(g.parse("```gate\nalways: now\n```"), "o/r")
            finally:
                os.environ.pop("OPSCENTER_GATE_KINDS")
        self.assertEqual((res[0]["met"], res[0]["detail"]), (True, "yes now"))


if __name__ == "__main__":
    unittest.main()
