"""
runbook_releases_test.py
Purpose: Tests for runbook_releases.py. A fake gh answers from a per-test route table and
         logs every call, OPRG_STATE_DIR / OPRG_CACHE_DIR point at a temp dir, so nothing reaches
         GitHub and no workflow is ever dispatched. Log fixtures are modelled on the
         plan and deploy logs of a guarded release.
Run:     python3 runbook_releases_test.py
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="rbrel-"))
ROUTES = TMP / "routes.json"
CALLS = TMP / "calls.log"
FAKE = TMP / "gh"
FAKE.write_text(
    f"""#!{sys.executable}
import json, re, sys
args = " ".join(sys.argv[1:])
open({str(CALLS)!r}, "a").write(args + "\\n")
for pat, out, rc in json.load(open({str(ROUTES)!r})):
    if re.search(pat, args):
        sys.stdout.write(out)
        sys.exit(rc)
sys.stderr.write("no route for " + args)
sys.exit(1)
"""
)
FAKE.chmod(0o755)
_ENV = {
    "OPRG_STATE_DIR": str(TMP / "state"),
    "OPRG_CACHE_DIR": str(TMP / "cache"),
    "OPRG_GH_BIN": str(FAKE),
}
sys.path.insert(0, str(Path(__file__).resolve().parent))

import contextlib  # noqa: E402
import importlib  # noqa: E402

import runbook_releases as rr  # noqa: E402

_saved = {}


def setUpModule():
    """The module reads its paths and gh binary at import: set them, reload it, undo all of it afterwards."""
    for k in _ENV:
        _saved[k] = os.environ.get(k)
    os.environ.update(_ENV)
    importlib.reload(rr)


def tearDownModule():
    for k, v in _saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    importlib.reload(rr)


A = [
    'azurerm_automation_runbook.rb["team-prefix-cmdb-emptyproduct_removal"]',
    'azurerm_automation_runbook.rb["team-prefix-cmdb-software_sync"]',
    'azurerm_automation_runbook.rb["team-prefix-device-udaranking_validate"]',
]
TS = "2026-10-13T16:15:00.0000000Z "


def plan_lines(addrs, add=0, change=0):
    out = [TS + "SUMMARY=$(grep -E '^(Plan:|No changes)|Error:' plan.txt | head -3 | tr '\\n' ' ')"]
    out += [TS + f"  # {a} will be destroyed" for a in addrs]
    out.append(TS + f"Plan: {add} to add, {change} to change, {len(addrs)} to destroy.")
    return out


CI_GUARD_LOG = "\n".join(
    plan_lines(A)
    + [
        TS + "##[error]Plan destroys resources. Destroys need a reviewed change, not a routine PR.",
        TS + "##[error]Process completed with exit code 1.",
    ]
)


def rb_guard_log(addrs, add=0):
    return "\n".join(
        plan_lines(addrs, add)
        + [
            TS
            + "##[error]Plan destroys runbook objects. Re-run via workflow_dispatch with allow_destroy=true after review.",
            TS + "##[error]Process completed with exit code 1.",
        ]
    )


def applied_log(addrs):
    return "\n".join(
        plan_lines(A)
        + [TS + f"{a}: Destruction complete after 0s" for a in addrs]
        + [TS + f"Apply complete! Resources: 0 added, 0 changed, {len(addrs)} destroyed."]
    )


def run(
    i,
    event="push",
    status="completed",
    conclusion="failure",
    created="2026-10-13T16:14:55Z",
    head="c" * 40,
):
    return {
        "id": i,
        "event": event,
        "status": status,
        "conclusion": conclusion,
        "created_at": created,
        "head_sha": head,
        "html_url": f"https://example/run/{i}",
    }


def routes(
    runs=(), logs=None, main="c" * 40, compare=(), pr_log=CI_GUARD_LOG, pr_conclusion="failure"
):
    logs = logs or {}
    r = [
        [
            r"runs/900/jobs",
            json.dumps(
                {
                    "jobs": [
                        {
                            "id": 9001,
                            "name": "terraform plan (runbooks prod)",
                            "conclusion": pr_conclusion,
                        }
                    ]
                }
            ),
            0,
        ],
        [r"jobs/9001/logs", pr_log, 0],
        [r"workflows/deploy-runbooks.yml/runs", json.dumps({"workflow_runs": list(runs)}), 0],
        [r"commits/main", main + "\n", 0],
        [r"compare/", json.dumps(list(compare)), 0],
        [r"^workflow run", "", 0],
        [
            r"^pr view \d+ .*--json files",
            json.dumps({"files": [{"path": "runbooks/prod-prefix-automation-aa/manifest.json"}]}),
            0,
        ],
    ]
    for rid, text in logs.items():
        r.append(
            [
                rf"runs/{rid}/jobs",
                json.dumps({"jobs": [{"id": rid * 10, "name": "deploy / deploy"}]}),
                0,
            ]
        )
        r.append([rf"jobs/{rid * 10}/logs", text, 0])
    ROUTES.write_text(json.dumps(r))


def calls():
    return CALLS.read_text().splitlines() if CALLS.exists() else []


class Releases(unittest.TestCase):
    def setUp(self):
        for p in (rr.STORE, rr.RUN_CACHE, CALLS, rr.DECISIONS):
            with contextlib.suppress(OSError):
                Path(p).unlink()
        rr._mem["items"] = None
        rr.TTL_S = 0
        rr.DONE_SHOW_S = (
            10**9
        )  # the fixtures carry fixed dates, so finished items must never age out

    def recorded(self, **kw):
        routes(**kw)
        msg = rr.record(251, "TKT-1: retire", "https://example/pr/251", "prod", 900, "a" * 40)
        rr.STORE.write_text(
            rr.STORE.read_text().replace(
                rr._load(rr.STORE, {})["251"]["approved_at"], "2026-10-13T16:14:52Z"
            )
        )
        return msg

    def state(self):
        return rr.items(force=True)[0]

    def test_parse_guard_and_apply_logs(self):
        p = rr.parse_log(rb_guard_log(A))
        self.assertEqual(p["planned"], sorted(A))
        self.assertEqual((p["add"], p["change"], p["destroy"]), (0, 0, 3))
        self.assertTrue(rr._guard_only(p, rr.RB_GUARD))
        q = rr.parse_log(applied_log(A))
        self.assertEqual(q["destroyed"], sorted(A))
        self.assertEqual(q["errors"], [])

    def test_record_reads_approved_set(self):
        msg = self.recorded()
        self.assertIn("3 runbook delete(s)", msg)
        self.assertEqual(rr._load(rr.STORE, {})["251"]["approved"], sorted(A))
        self.assertIn("runbook_deletes_recorded", rr.DECISIONS.read_text())

    def test_record_refuses_when_pr_plan_not_guard_only(self):
        msg = self.recorded(pr_conclusion="success")
        self.assertIn("could not read", msg)
        self.assertEqual(self.state()["state"], "error")
        self.assertEqual(len(rr.needs_me(rr.items(force=True))), 1)

    def test_dev_tier_is_not_recorded(self):
        self.assertIn("from the branch", rr.record(1, "t", "u", "dev", 900, "a" * 40))
        self.assertFalse(rr.STORE.exists())

    def test_waiting_until_main_run_finishes(self):
        self.recorded()
        self.assertEqual(self.state()["state"], "waiting")
        routes(runs=[run(1, status="in_progress", conclusion=None)])
        self.assertEqual(self.state()["state"], "waiting")
        self.assertEqual(rr.needs_me(rr.items(force=True)), [])

    def test_ready_when_guard_and_same_set(self):
        self.recorded()
        routes(runs=[run(1)], logs={1: rb_guard_log(A)})
        s = self.state()
        self.assertEqual(s["state"], "ready")
        self.assertEqual(s["run"]["id"], 1)
        self.assertEqual(len(rr.needs_me([s])), 1)

    def test_runs_before_the_merge_are_ignored(self):
        self.recorded()
        routes(runs=[run(1, created="2026-10-13T14:00:00Z")], logs={1: rb_guard_log(A)})
        self.assertEqual(self.state()["state"], "waiting")

    def test_mismatch_on_extra_delete(self):
        self.recorded()
        extra = A + ['azurerm_automation_runbook.rb["ops-other"]']
        routes(runs=[run(1)], logs={1: rb_guard_log(extra)})
        s = self.state()
        self.assertEqual(s["state"], "mismatch")
        self.assertEqual(s["extra"], ['azurerm_automation_runbook.rb["ops-other"]'])

    def test_mismatch_when_plan_also_adds(self):
        self.recorded()
        routes(runs=[run(1)], logs={1: rb_guard_log(A, add=1)})
        self.assertEqual(self.state()["state"], "mismatch")

    def test_mismatch_on_other_error(self):
        self.recorded()
        log = "\n".join(
            plan_lines(A)
            + [
                TS + "##[error]Error: AuthorizationFailed",
                TS + "##[error]Process completed with exit code 1.",
            ]
        )
        routes(runs=[run(1)], logs={1: log})
        self.assertEqual(self.state()["state"], "mismatch")

    def test_done_when_later_run_succeeded(self):
        self.recorded()
        routes(
            runs=[
                run(
                    2,
                    event="workflow_dispatch",
                    conclusion="success",
                    created="2026-10-13T16:19:47Z",
                ),
                run(1),
            ],
            logs={1: rb_guard_log(A)},
        )
        s = self.state()
        self.assertEqual(s["state"], "done")
        self.assertEqual(rr.needs_me([s]), [])

    # core-rule: scripting-python.1.7
    def test_release_refuses_stale_run_id(self):
        self.recorded()
        routes(runs=[run(1)], logs={1: rb_guard_log(A)})
        with self.assertRaises(rr.ReleaseError) as e:
            rr.release({"pr": 251, "run_id": 99})
        self.assertEqual(e.exception.code, 409)
        self.assertFalse(any(c.startswith("workflow run") for c in calls()))

    def test_release_refuses_when_not_ready(self):
        self.recorded()
        routes(runs=[run(1, status="in_progress", conclusion=None)])
        with self.assertRaises(rr.ReleaseError) as e:
            rr.release({"pr": 251, "run_id": 1})
        self.assertEqual(e.exception.code, 409)

    def test_release_refuses_when_main_changed_runbook_files(self):
        self.recorded()
        routes(
            runs=[run(1)],
            logs={1: rb_guard_log(A)},
            main="d" * 40,
            compare=["runbooks/prod-prefix-automation-aa/manifest.json"],
        )
        with self.assertRaises(rr.ReleaseError) as e:
            rr.release({"pr": 251, "run_id": 1})
        self.assertIn("main changed runbook files", str(e.exception))
        self.assertFalse(any(c.startswith("workflow run") for c in calls()))

    def test_release_dispatches_when_main_moved_elsewhere_then_tracks(self):
        self.recorded()
        routes(
            runs=[run(1)],
            logs={1: rb_guard_log(A)},
            main="d" * 40,
            compare=["apps/vendor-b/server/index.js"],
        )
        out = rr.release({"pr": 251, "run_id": 1})
        self.assertIn("allow_destroy", out["done"][0])
        disp = [c for c in calls() if c.startswith("workflow run")]
        self.assertEqual(
            disp,
            ["workflow run deploy-runbooks.yml -R owner/repo --ref main -f allow_destroy=true"],
        )
        self.assertIn("runbook_deletes_released", rr.DECISIONS.read_text())
        with self.assertRaises(rr.ReleaseError):
            rr.release({"pr": 251, "run_id": 1})
        at = rr._load(rr.STORE, {})["251"]["dispatched_at"]
        routes(runs=[run(1)], logs={1: rb_guard_log(A)})
        self.assertEqual(self.state()["state"], "releasing")
        routes(
            runs=[
                run(
                    3, event="workflow_dispatch", status="in_progress", conclusion=None, created=at
                ),
                run(1),
            ],
            logs={1: rb_guard_log(A)},
        )
        self.assertEqual(self.state()["state"], "releasing")
        routes(
            runs=[run(3, event="workflow_dispatch", conclusion="success", created=at), run(1)],
            logs={1: rb_guard_log(A), 3: applied_log(A)},
        )
        s = self.state()
        self.assertEqual(s["state"], "released")
        self.assertEqual((s["extra"], s["missing"]), ([], []))
        self.assertEqual(rr.needs_me([s]), [])

    def test_released_with_extra_delete_needs_me(self):
        self.recorded()
        routes(runs=[run(1)], logs={1: rb_guard_log(A)})
        rr.release({"pr": 251, "run_id": 1})
        at = rr._load(rr.STORE, {})["251"]["dispatched_at"]
        more = A + ['azurerm_automation_runbook.rb["ops-other"]']
        routes(
            runs=[run(3, event="workflow_dispatch", conclusion="success", created=at), run(1)],
            logs={1: rb_guard_log(A), 3: applied_log(more)},
        )
        s = self.state()
        self.assertEqual(s["state"], "released")
        self.assertEqual(len(rr.needs_me([s])), 1)

    def test_release_failed_run(self):
        self.recorded()
        routes(runs=[run(1)], logs={1: rb_guard_log(A)})
        rr.release({"pr": 251, "run_id": 1})
        at = rr._load(rr.STORE, {})["251"]["dispatched_at"]
        routes(
            runs=[run(3, event="workflow_dispatch", conclusion="failure", created=at), run(1)],
            logs={1: rb_guard_log(A), 3: "x"},
        )
        self.assertEqual(self.state()["state"], "failed")

    def test_prose_is_clean(self):
        src = Path(rr.__file__).read_text()
        self.assertNotIn("\u2014", src)
        for line in src.splitlines():
            s = line.strip()
            if s.startswith("#") or s.startswith('"') or "why=" in s:
                self.assertNotIn(";", s, line)


if __name__ == "__main__":
    unittest.main(verbosity=1)
