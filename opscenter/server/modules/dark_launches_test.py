"""
dark_launches_test.py
Purpose: Tests for dark_launches.py. A stateful fake gh keeps variables and workflow runs in a temp json
         file and logs every call, the registry and log live in a temp dir, so nothing reaches the code
         host, no workflow is dispatched and no real variable is read or set. The registry entries are
         synthetic (example/repo).
Run:     python3 dark_launches_test.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="darkl-"))
STORE = TMP / "gh-state.json"
CALLS = TMP / "calls.log"
FAKE = TMP / "gh"
FAKE.write_text(
    f"""#!{sys.executable}
import json, sys
a = sys.argv[1:]
open({str(CALLS)!r}, "a").write(" ".join(a) + "\\n")
st = json.load(open({str(STORE)!r}))
def save():
    json.dump(st, open({str(STORE)!r}, "w"))
if st.get("fail_all"):
    sys.stderr.write("HTTP 500 boom")
    sys.exit(1)
if a[:2] == ["variable", "get"]:
    key = a[2] + "@" + (a[a.index("--env") + 1] if "--env" in a else "")
    if st.get("var_error"):
        sys.stderr.write("HTTP 502 bad gateway")
        sys.exit(1)
    if key not in st["vars"]:
        sys.stderr.write("HTTP 404: Not Found")
        sys.exit(1)
    sys.stdout.write(st["vars"][key])
elif a[:2] == ["variable", "set"]:
    key = a[2] + "@" + (a[a.index("--env") + 1] if "--env" in a else "")
    if not st.get("set_ignored"):
        st["vars"][key] = a[a.index("--body") + 1]
        save()
elif a[:2] == ["workflow", "run"]:
    st.setdefault("dispatched", []).append(a)
    save()
elif a[:2] == ["run", "list"]:
    sys.stdout.write(json.dumps(st.get("runs", [])))
else:
    sys.stderr.write("no route " + " ".join(a))
    sys.exit(1)
"""
)
FAKE.chmod(0o755)
os.environ["OPSCENTER_GH_BIN"] = str(FAKE)
os.environ["DARK_LAUNCH_REGISTRY"] = str(TMP / "dark-launches.json")
os.environ["DARK_LAUNCH_LOG"] = str(TMP / "log.jsonl")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import dark_launches as dl  # noqa: E402

REG = Path(os.environ["DARK_LAUNCH_REGISTRY"])
LAUNCH = {
    "id": "drift-remediation",
    "repo": "example/repo",
    "environment": "prod",
    "variable": "DRIFT_REMEDIATION_ENABLED",
    "workflow": "drift.yml",
    "title": "Synthetic drift remediation",
    "status": "dark",
}
VAR = "DRIFT_REMEDIATION_ENABLED@prod"


def iso(offset=0):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + offset))


def setup(vars_=None, runs=None, entries=None, **extra):
    st = {"vars": vars_ or {}, "runs": runs or []}
    st.update(extra)
    STORE.write_text(json.dumps(st))
    CALLS.write_text("")
    Path(os.environ["DARK_LAUNCH_LOG"]).write_text("")
    REG.write_text(json.dumps({"launches": entries if entries is not None else [dict(LAUNCH)]}))
    dl._drop_cache()


def state():
    return json.loads(STORE.read_text())


def calls():
    return [ln for ln in CALLS.read_text().splitlines() if ln]


def run(status="completed", conclusion="success", offset=5):
    return {
        "databaseId": 1,
        "status": status,
        "conclusion": conclusion,
        "createdAt": iso(offset),
        "url": "https://x/run/1",
    }


def dispatched_log():
    Path(os.environ["DARK_LAUNCH_LOG"]).write_text(
        json.dumps({"ts": iso(-10), "id": LAUNCH["id"], "event": "dry_run_dispatched"}) + "\n"
    )


class Registry(unittest.TestCase):
    def test_missing_file_is_empty(self):
        setup()
        REG.unlink()
        self.assertEqual(dl.get()["launches"], [])
        self.assertIsNone(dl.get()["error"])

    def test_malformed_registry_fails_closed(self):
        setup()
        REG.write_text("{nope")
        d = dl.get(force=True)
        self.assertEqual(d["launches"], [])
        self.assertIn("unreadable", d["error"])
        with self.assertRaises(dl.DarkError) as c:
            dl.dry_run({"id": "drift-remediation"})
        self.assertEqual(c.exception.code, 503)
        self.assertEqual(calls(), [])

    def test_bad_entries_rejected(self):
        for bad in (
            dict(LAUNCH, variable="lower_case"),
            dict(LAUNCH, workflow="../x.yml"),
            dict(LAUNCH, repo="no-slash"),
            dict(LAUNCH, environment="a b"),
            dict(LAUNCH, status="live"),
            dict(LAUNCH, title=""),
            dict(LAUNCH, dry_run_input="Dry Run"),
        ):
            setup(entries=[bad])
            self.assertIn("dark-launches.json", dl.get(force=True)["error"], bad)
        setup(entries=[dict(LAUNCH), dict(LAUNCH)])
        self.assertIn("duplicate", dl.get(force=True)["error"])

    def test_retired_is_hidden(self):
        setup(entries=[dict(LAUNCH, status="retired")])
        self.assertEqual(dl.get(force=True)["launches"], [])

    def test_empty_shipped_registry_has_no_cards(self):
        setup(entries=[])
        self.assertEqual(dl.get(force=True)["launches"], [])
        self.assertEqual(calls(), [])


class Cards(unittest.TestCase):
    def test_unset_variable_is_off_and_cannot_enable_before_a_dry_run(self):
        setup()
        c = dl.get(force=True)["launches"][0]
        self.assertEqual((c["live"], c["dry_run"]["state"]), ("off", "none"))
        self.assertTrue(c["can_dry_run"])
        self.assertFalse(c["can_enable"])
        self.assertFalse(c["can_disable"])

    def test_read_error_is_unknown_not_off(self):
        setup(var_error=True)
        c = dl.get(force=True)["launches"][0]
        self.assertEqual(c["live"], "unknown")
        self.assertFalse(c["can_enable"])
        self.assertTrue(c["can_disable"])

    def test_dry_run_states(self):
        for runs, want in (
            ([], "running"),
            ([run(status="in_progress", conclusion="")], "running"),
            ([run()], "passed"),
            ([run(conclusion="failure")], "failed"),
            ([run(offset=-3600)], "running"),  # an older run is not mine
        ):
            setup(runs=runs)
            dispatched_log()
            self.assertEqual(dl.get(force=True)["launches"][0]["dry_run"]["state"], want, runs)

    def test_dry_run_read_failure_is_unknown(self):
        setup(fail_all=True)
        dispatched_log()
        self.assertEqual(dl.dry_run_state(dl._clean(LAUNCH))["state"], "unknown")

    def test_old_dry_run_expires(self):
        setup(runs=[run()])
        Path(os.environ["DARK_LAUNCH_LOG"]).write_text(
            json.dumps({"ts": iso(-8 * 86400), "id": LAUNCH["id"], "event": "dry_run_dispatched"})
            + "\n"
        )
        self.assertEqual(dl.dry_run_state(dl._clean(LAUNCH))["state"], "none")

    def test_passed_dry_run_unlocks_enable(self):
        setup(runs=[run()])
        dispatched_log()
        c = dl.get(force=True)["launches"][0]
        self.assertTrue(c["can_enable"])


class Actions(unittest.TestCase):
    def test_dry_run_dispatches_with_dry_run_true_on_main_and_logs(self):
        setup()
        r = dl.dry_run({"id": "drift-remediation"})
        self.assertIn("dry run", r["done"][0])
        d = state()["dispatched"][0]
        self.assertEqual(d[:3], ["workflow", "run", "drift.yml"])
        self.assertIn("dry_run=true", d)
        self.assertEqual(d[d.index("--ref") + 1], "main")
        self.assertEqual(d[d.index("-R") + 1], "example/repo")
        self.assertEqual(state()["vars"], {})
        self.assertIn("dry_run_dispatched", Path(os.environ["DARK_LAUNCH_LOG"]).read_text())

    def test_dry_run_while_one_is_running_is_idempotent(self):
        setup(runs=[run(status="in_progress", conclusion="")])
        dispatched_log()
        r = dl.dry_run({"id": "drift-remediation"})
        self.assertTrue(r["already"])
        self.assertNotIn("dispatched", state())

    def test_dry_run_gh_failure_logs_nothing(self):
        setup(fail_all=True)
        with self.assertRaises(dl.DarkError) as c:
            dl.dry_run({"id": "drift-remediation"})
        self.assertEqual(c.exception.code, 502)
        self.assertEqual(Path(os.environ["DARK_LAUNCH_LOG"]).read_text(), "")

    def test_unknown_id_is_404_and_runs_nothing(self):
        setup()
        for fn in (dl.dry_run, dl.enable, dl.disable):
            with self.assertRaises(dl.DarkError) as c:
                fn({"id": "nope-nope", "confirm": "X"})
            self.assertEqual(c.exception.code, 404)
        self.assertEqual(calls(), [])

    def test_enable_needs_the_typed_variable_name(self):
        setup(runs=[run()])
        dispatched_log()
        for typed in ("", "yes", "drift_remediation_enabled"):
            with self.assertRaises(dl.DarkError) as c:
                dl.enable({"id": "drift-remediation", "confirm": typed})
            self.assertEqual(c.exception.code, 400)
        self.assertEqual(state()["vars"], {})

    def test_enable_refused_without_a_passed_dry_run(self):
        for runs, dispatched in (
            ([], False),
            ([run(conclusion="failure")], True),
            ([run(status="in_progress", conclusion="")], True),
        ):
            setup(runs=runs)
            if dispatched:
                dispatched_log()
            with self.assertRaises(dl.DarkError) as c:
                dl.enable({"id": "drift-remediation", "confirm": "DRIFT_REMEDIATION_ENABLED"})
            self.assertEqual(c.exception.code, 409)
            self.assertEqual(state()["vars"], {})

    def test_enable_refused_when_live_read_fails(self):
        setup(runs=[run()], var_error=True)
        dispatched_log()
        with self.assertRaises(dl.DarkError) as c:
            dl.enable({"id": "drift-remediation", "confirm": "DRIFT_REMEDIATION_ENABLED"})
        self.assertEqual(c.exception.code, 409)

    def test_enable_sets_true_on_the_environment_and_records_it(self):
        setup(runs=[run()])
        dispatched_log()
        r = dl.enable({"id": "drift-remediation", "confirm": "DRIFT_REMEDIATION_ENABLED"})
        self.assertIn("now true", r["done"][0])
        self.assertEqual(state()["vars"][VAR], "true")
        sets = [c for c in calls() if c.startswith("variable set")]
        self.assertEqual(len(sets), 1)
        self.assertIn("--env prod", sets[0])
        self.assertIn("--body true", sets[0])
        self.assertEqual(json.loads(REG.read_text())["launches"][0]["status"], "enabled")
        self.assertIn('"event": "enabled"', Path(os.environ["DARK_LAUNCH_LOG"]).read_text())

    def test_enable_twice_is_idempotent(self):
        setup(vars_={VAR: "true"}, runs=[run()])
        r = dl.enable({"id": "drift-remediation", "confirm": "DRIFT_REMEDIATION_ENABLED"})
        self.assertTrue(r["already"])
        self.assertEqual([c for c in calls() if c.startswith("variable set")], [])

    def test_enable_fails_when_the_read_back_disagrees(self):
        setup(runs=[run()], set_ignored=True)
        dispatched_log()
        with self.assertRaises(dl.DarkError) as c:
            dl.enable({"id": "drift-remediation", "confirm": "DRIFT_REMEDIATION_ENABLED"})
        self.assertEqual(c.exception.code, 502)
        self.assertEqual(json.loads(REG.read_text())["launches"][0]["status"], "dark")

    def test_repo_level_variable_has_no_env_flag(self):
        setup(runs=[run()], entries=[dict(LAUNCH, environment="")])
        dispatched_log()
        dl.enable({"id": "drift-remediation", "confirm": "DRIFT_REMEDIATION_ENABLED"})
        sets = [c for c in calls() if c.startswith("variable set")]
        self.assertNotIn("--env", sets[0])
        self.assertEqual(state()["vars"]["DRIFT_REMEDIATION_ENABLED@"], "true")

    def test_disable_needs_no_dry_run_and_sets_false(self):
        setup(vars_={VAR: "true"}, entries=[dict(LAUNCH, status="enabled")])
        r = dl.disable({"id": "drift-remediation"})
        self.assertIn("now false", r["done"][0])
        self.assertEqual(state()["vars"][VAR], "false")
        self.assertEqual(json.loads(REG.read_text())["launches"][0]["status"], "dark")

    def test_disable_on_unknown_read_still_sets_false(self):
        setup(var_error=True)
        # the set works, the read back fails, so it reports the unconfirmed state instead of claiming success
        with self.assertRaises(dl.DarkError):
            dl.disable({"id": "drift-remediation"})
        self.assertEqual(state()["vars"][VAR], "false")

    def test_disable_when_already_off_repairs_status(self):
        setup(vars_={VAR: "false"}, entries=[dict(LAUNCH, status="enabled")])
        r = dl.disable({"id": "drift-remediation"})
        self.assertTrue(r["already"])
        self.assertEqual(json.loads(REG.read_text())["launches"][0]["status"], "dark")

    def test_only_true_counts_as_on(self):
        for val, want in (
            ("true", "on"),
            ("TRUE", "on"),
            ("false", "off"),
            ("1", "off"),
            ("yes", "off"),
            ("", "off"),
        ):
            setup(vars_={VAR: val})
            self.assertEqual(dl.live_value(dl._clean(LAUNCH)), want, val)

    def test_other_entries_survive_a_status_write(self):
        other = dict(LAUNCH, id="second-launch", variable="SECOND_ENABLED")
        setup(vars_={VAR: "true"}, entries=[dict(LAUNCH, status="enabled"), other])
        dl.disable({"id": "drift-remediation"})
        rows = json.loads(REG.read_text())["launches"]
        self.assertEqual([r["id"] for r in rows], ["drift-remediation", "second-launch"])
        self.assertEqual(rows[1], other)


if __name__ == "__main__":
    unittest.main()
