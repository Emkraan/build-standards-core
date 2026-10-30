"""
infra_tasks_test.py
Purpose: Maintenance tasks the Infrastructure page may start (a backup, a restore drill): none configured means none can start;
         the run contract holds (unknown task 404, unknown or invalid input 400, a task already running 409 with the reason,
         a repeat inside the gap answers already); the inputs reach the consumer's command as TASK_INPUT_<NAME> variables.
Run:     python3 infra_tasks_test.py
"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import infra  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="infra-tasks-"))
BUSY = TMP / "busy"
TASKS = {
    "backup": {
        "label": "State backup",
        "argv": ["/bin/true"],
        "busy_argv": [
            sys.executable,
            "-c",
            f"import sys,os; sys.exit(0 if os.path.exists({str(BUSY)!r}) else 1)",
        ],
    },
    "drill": {
        "argv": ["/bin/true"],
        "inputs": [
            {"name": "dry_run", "type": "boolean", "default": True},
            {"name": "target", "type": "choice", "options": ["a", "b"], "default": "a"},
        ],
    },
}
_saved = {}


def setUpModule():
    (TMP / "tasks.json").write_text(json.dumps(TASKS))
    _saved["INFRA_TASKS"] = os.environ.get("INFRA_TASKS")
    os.environ["INFRA_TASKS"] = str(TMP / "tasks.json")


def tearDownModule():
    if _saved["INFRA_TASKS"] is None:
        os.environ.pop("INFRA_TASKS", None)
    else:
        os.environ["INFRA_TASKS"] = _saved["INFRA_TASKS"]


class Tasks(unittest.TestCase):
    def setUp(self):
        infra._task_started.clear()
        BUSY.unlink(missing_ok=True)
        self.spawned = []

    def spawn(self, argv, env):
        self.spawned.append((argv, env))

    def go(self, **payload):
        return infra.task_run(payload, spawn=self.spawn)

    def test_the_configured_tasks_are_listed_with_their_inputs(self):
        got = {t["name"]: t for t in infra.tasks()}
        self.assertEqual((got["backup"]["label"], got["drill"]["label"]), ("State backup", "drill"))
        self.assertEqual([i["name"] for i in got["drill"]["inputs"]], ["dry_run", "target"])

    def test_none_configured_means_none_can_start(self):
        os.environ["INFRA_TASKS"] = str(TMP / "absent.json")
        try:
            self.assertEqual(infra.tasks(), [])
            with self.assertRaises(infra.TaskRefused) as e:
                self.go(what="backup")
            self.assertEqual(e.exception.status, 404)
        finally:
            os.environ["INFRA_TASKS"] = str(TMP / "tasks.json")

    def test_a_start_passes_the_inputs_as_environment_and_defaults_are_safe(self):
        r = self.go(what="drill")
        self.assertEqual((r["started"], r["inputs"]), (True, {"dry_run": "true", "target": "a"}))
        argv, env = self.spawned[0]
        self.assertEqual((env["TASK_INPUT_DRY_RUN"], env["TASK_INPUT_TARGET"]), ("true", "a"))

    def test_refusals_never_start_anything(self):
        for payload, status in (
            (dict(what="nope"), 404),
            (dict(what="drill", inputs={"zzz": 1}), 400),
            (dict(what="drill", inputs={"target": "c"}), 400),
            (dict(what="drill", inputs={"dry_run": "yes"}), 400),
        ):
            with self.assertRaises(Exception) as e:
                self.go(**payload)
            self.assertEqual(e.exception.status, status, payload)
        self.assertEqual(self.spawned, [])

    def test_a_running_task_is_refused_with_the_reason(self):
        BUSY.write_text("x")
        with self.assertRaises(infra.TaskRefused) as e:
            self.go(what="backup")
        self.assertEqual(e.exception.status, 409)
        self.assertIn("State backup is already running", str(e.exception))

    def test_a_double_click_starts_once(self):
        self.go(what="backup")
        self.assertTrue(self.go(what="backup")["already"])
        self.assertEqual(len(self.spawned), 1)
        for k in list(infra._task_started):
            infra._task_started[k] = time.time() - infra.TASK_GAP_S - 1
        self.assertTrue(self.go(what="backup")["started"])


if __name__ == "__main__":
    unittest.main()
