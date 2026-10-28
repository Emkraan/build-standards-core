"""The Builds page module against a fake gh binary: the feed (runs, jobs, failure reasons, waiting environments, summaries, landed
facts), the refusal for a branch behind main, and the guarded update from main (merge, rerun, conflict, every refusal)."""

import importlib
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

TMP = Path(tempfile.mkdtemp(prefix="builds-test-"))
STATE = TMP / "fake.json"
FAKE_GH = r"""#!/usr/bin/env python3
import json, os, sys
st = json.load(open(os.environ["FAKE_GH_STATE"]))
a = sys.argv[1:]
open(os.environ["FAKE_GH_STATE"] + ".calls", "a").write(json.dumps(a) + "\n")
if a[:2] == ["run", "rerun"]:
    sys.exit(1 if st.get("rerun_fail") else 0)
if "-i" in a:
    status = st.get("merge_status", 201)
    body = json.dumps({"message": st.get("merge_message", "")})
    print("HTTP/2 %d OK\r\n\r\n%s" % (status, body))
    sys.exit(0)
path = next((x for x in a if x.startswith("repos/")), "")
for prefix in sorted(st["routes"], key=len, reverse=True):
    resp = st["routes"][prefix]
    if path.startswith(prefix) or prefix in path:
        if isinstance(resp, dict) and resp.get("_fail"):
            sys.stderr.write("HTTP 502")
            sys.exit(1)
        if "--allow-escape-sequences" in a:
            print(resp if isinstance(resp, str) else "")
        else:
            print(json.dumps(resp))
        sys.exit(0)
sys.stderr.write("no route " + path)
sys.exit(1)
"""
gh = TMP / "gh"
gh.write_text(FAKE_GH)
gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
(TMP / "landed.py").write_text(
    "import json\nprint(json.dumps({'recorded': {'version': '1.2'}, 'live': {'version': '1.3'}, 'drift': ['version differs']}))\n"
)
(TMP / "config.json").write_text(
    json.dumps(
        {
            "repo": "acme/repo",
            "owner": "owner-account",
            "branch_regex": r"^tkt-\d+-",
            "summary_regex": r"(version \S+: .*)$",
            "pipelines": [
                {
                    "key": "rel",
                    "product": "app",
                    "label": "Release app",
                    "workflow": "release.yml",
                    "summary": True,
                },
                {
                    "key": "dep",
                    "product": "dev",
                    "label": "Deploy dev",
                    "workflow": "deploy.yml",
                    "refusal": True,
                },
            ],
            "landed": {"app": [sys.executable, str(TMP / "landed.py")]},
            "privileged_queue": str(TMP / "priv.json"),
        }
    )
)
os.environ.update(
    BUILDS_CONFIG=str(TMP / "config.json"),
    GH_BIN=str(gh),
    FAKE_GH_STATE=str(STATE),
    OPSCENTER_STATE_DIR=str(TMP / "state"),
)
import ghview  # noqa: E402
import swr  # noqa: E402

importlib.reload(ghview)
import builds  # noqa: E402

importlib.reload(builds)
CONFIG_FILE = str(TMP / "config.json")


def run(
    rid,
    status="completed",
    conclusion="success",
    branch="main",
    sha="a" * 40,
    path="release.yml",
    updated="2026-10-28T10:00:00Z",
):
    return {
        "id": rid,
        "run_attempt": 1,
        "status": status,
        "conclusion": conclusion,
        "event": "push",
        "head_branch": branch,
        "head_sha": sha,
        "triggering_actor": {"login": "someone"},
        "created_at": updated,
        "run_started_at": updated,
        "updated_at": updated,
        "html_url": f"https://example.com/run/{rid}",
        "path": f".github/workflows/{path}",
    }


JOBS = {
    "jobs": [
        {
            "id": 900,
            "name": "build",
            "status": "completed",
            "conclusion": "failure",
            "steps": [{"number": 1, "name": "compile", "conclusion": "failure"}],
        }
    ]
}
OK_JOBS = {
    "jobs": [
        {"id": 901, "name": "publish", "status": "completed", "conclusion": "success", "steps": []}
    ]
}


class Builds(unittest.TestCase):
    def setUp(self):
        os.environ["BUILDS_CONFIG"] = CONFIG_FILE
        os.environ["GH_BIN"] = str(gh)
        importlib.reload(ghview)
        importlib.reload(builds)
        swr_clear()
        for d in (
            builds._done_jobs,
            builds._seen_jobs,
            builds._done_reason,
            builds._rollout_line,
            builds._last_done,
            builds._behind,
            builds._own,
            builds._pending,
            builds._conflicts,
            builds._errors,
        ):
            d.clear()
        self.state = {"routes": {}}

    def save(self):
        STATE.write_text(json.dumps(self.state))
        Path(str(STATE) + ".calls").unlink(missing_ok=True)

    def calls(self):
        p = Path(str(STATE) + ".calls")
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def routes(self, **kw):
        self.state["routes"].update(kw)
        self.save()

    def basic(self):
        self.routes(
            **{
                "repos/acme/repo/actions/workflows/release.yml/runs": {
                    "workflow_runs": [
                        run(1, "completed", "success"),
                        run(2, "in_progress", None),
                        run(3, "waiting", None),
                    ]
                },
                "repos/acme/repo/actions/workflows/deploy.yml/runs": {"workflow_runs": []},
                "repos/acme/repo/actions/runs/1/jobs": OK_JOBS,
                "repos/acme/repo/actions/runs/2/jobs": OK_JOBS,
                "repos/acme/repo/actions/runs/3/jobs": OK_JOBS,
                "repos/acme/repo/actions/runs/3/pending_deployments": [
                    {"environment": {"name": "production"}}
                ],
                "repos/acme/repo/actions/jobs/901/logs": "2026-10-28T10:00:00.0000000Z version 1.3: 4 rows\n",
            }
        )

    def test_the_feed_lists_pipelines_runs_waiting_environments_and_a_summary(self):
        self.basic()
        self.routes(**{})
        d = builds.get()
        self.assertEqual([p["key"] for p in d["pipelines"]], ["rel", "dep"])
        runs = {r["id"]: r for r in d["pipelines"][0]["runs"]}
        self.assertEqual(runs[3]["waiting_on"], ["production"])
        self.assertEqual(runs[1]["summary"], "version 1.3: 4 rows")
        self.assertEqual((d["running"], d["waiting"], d["active"]), (1, 1, True))
        self.assertEqual(builds.badge(), {"running": 1, "waiting": 1})

    def test_the_landed_command_output_is_the_landed_block_and_a_missing_command_is_no_block(self):
        self.basic()
        d = builds.get()
        self.assertEqual(d["landed"]["app"]["drift"], ["version differs"])
        self.assertNotIn("dev", d["landed"])

    def test_a_failed_run_shows_the_first_specific_annotation(self):
        self.routes(
            **{
                "repos/acme/repo/actions/workflows/release.yml/runs": {
                    "workflow_runs": [run(5, "completed", "failure")]
                },
                "repos/acme/repo/actions/workflows/deploy.yml/runs": {"workflow_runs": []},
                "repos/acme/repo/actions/runs/5/jobs": JOBS,
                "repos/acme/repo/check-runs/900/annotations": [
                    {
                        "annotation_level": "failure",
                        "message": "Process completed with exit code 1.",
                    },
                    {"annotation_level": "failure", "message": "the compile broke"},
                ],
            }
        )
        r = builds.get()["pipelines"][0]["runs"][0]
        self.assertEqual(
            r["reason"], {"where": 'build, step "compile"', "message": "the compile broke"}
        )

    def test_one_failing_pipeline_read_is_reported_and_the_rest_still_render(self):
        self.basic()
        self.routes(**{"repos/acme/repo/actions/workflows/deploy.yml/runs": {"_fail": True}})
        d = builds.get()
        self.assertTrue(any("Deploy dev" in e for e in d["errors"]))
        self.assertEqual(len(d["pipelines"][0]["runs"]), 3)

    def refused(self, branch="tkt-1-x", own=True):
        self.routes(
            **{
                "repos/acme/repo/actions/workflows/release.yml/runs": {"workflow_runs": []},
                "repos/acme/repo/actions/workflows/deploy.yml/runs": {
                    "workflow_runs": [
                        run(7, "completed", "failure", branch=branch, path="deploy.yml")
                    ]
                },
                "repos/acme/repo/actions/runs/7/jobs": JOBS,
                "repos/acme/repo/actions/runs/7": run(
                    7, "completed", "failure", branch=branch, path="deploy.yml"
                ),
                "repos/acme/repo/check-runs/900/annotations": [
                    {
                        "annotation_level": "failure",
                        "message": f"{branch} is 3 commit(s) behind main, merge main first",
                    }
                ],
                "repos/acme/repo/compare/main...": 3,
                "repos/acme/repo/commits/": {"login": "owner-account" if own else "someone"},
                "repos/acme/repo/branches/": {"sha": "a" * 40},
                "repos/acme/repo/actions/workflows/deploy.yml/runs?branch": [{"id": 7}],
                "repos/acme/repo/pulls?head": [],
            }
        )

    def test_a_refused_run_on_the_owners_branch_needs_action_and_another_persons_does_not(self):
        self.refused(own=True)
        ref = builds.get()["pipelines"][1]["runs"][0]["refusal"]
        self.assertEqual(
            (ref["branch"], ref["behind"], ref["own"], ref["phase"]),
            ("tkt-1-x", 3, True, "needs_action"),
        )
        builds._own.clear()
        swr_clear()
        self.refused(own=False)
        ref = builds.get()["pipelines"][1]["runs"][0]["refusal"]
        self.assertEqual((ref["own"], ref["phase"]), (False, "info"))

    def test_update_from_main_is_refused_for_a_bad_branch_a_changed_run_or_someone_elses_branch(
        self,
    ):
        self.refused(own=True)
        for payload, code in (
            ({"run": 7, "branch": "main", "sha": "a" * 7}, 400),
            ({"run": 7, "branch": "feature/x", "sha": "a" * 7}, 400),
            ({"run": "7", "branch": "tkt-1-x", "sha": "a" * 7}, 400),
            ({"run": 7, "branch": "tkt-1-x", "sha": "b" * 7}, 409),
        ):
            with self.assertRaises(builds.BuildsError) as cm:
                builds.update_from_main(payload)
            self.assertEqual(cm.exception.status, code, payload)
        builds._own.clear()
        self.refused(own=False)
        with self.assertRaises(builds.BuildsError) as cm:
            builds.update_from_main({"run": 7, "branch": "tkt-1-x", "sha": "a" * 7})
        self.assertEqual(cm.exception.status, 403)

    def test_update_from_main_merges_reruns_or_reports_the_conflict(self):
        self.refused(own=True)
        self.state["merge_status"] = 201
        self.save()
        self.assertEqual(
            builds.update_from_main({"run": 7, "branch": "tkt-1-x", "sha": "a" * 7}),
            {"result": "merged"},
        )
        self.assertEqual(
            builds.update_from_main({"run": 7, "branch": "tkt-1-x", "sha": "a" * 7}),
            {"result": "working", "already": True},
        )
        builds._pending.clear()
        self.state["merge_status"] = 204
        self.save()
        self.assertEqual(
            builds.update_from_main({"run": 7, "branch": "tkt-1-x", "sha": "a" * 7})["result"],
            "rerun",
        )
        self.assertIn(["run", "rerun", "7", "-R", "acme/repo"], self.calls())
        builds._pending.clear()
        self.state["merge_status"] = 409
        self.state["routes"]["repos/acme/repo/compare/main...tkt-1-x"] = ["a.txt", "b.txt"]
        self.state["routes"]["repos/acme/repo/compare/tkt-1-x...main"] = ["b.txt", "c.txt"]
        self.save()
        out = builds.update_from_main({"run": 7, "branch": "tkt-1-x", "sha": "a" * 7})
        self.assertEqual(out, {"result": "conflict", "files": ["b.txt"]})

    def test_no_config_means_an_empty_page(self):
        os.environ["BUILDS_CONFIG"] = str(TMP / "none.json")
        importlib.reload(builds)
        swr_clear()
        self.routes()
        d = builds.get()
        self.assertEqual((d["pipelines"], d["running"], d["waiting"]), ([], 0, 0))

    def test_parse_refusal(self):
        self.assertEqual(
            builds.parse_refusal({"message": "##[error]tkt-9-a is 5 commit(s) behind main"}),
            ("tkt-9-a", 5),
        )
        self.assertIsNone(builds.parse_refusal({"message": "boom"}))
        self.assertIsNone(builds.parse_refusal(None))


def swr_clear():
    swr.invalidate("builds:feed", "builds:landed:app")


if __name__ == "__main__":
    unittest.main()
