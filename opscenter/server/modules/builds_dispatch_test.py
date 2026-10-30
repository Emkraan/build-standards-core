"""
builds_dispatch_test.py
Purpose: The run contract of builds.dispatch: inputs are checked against the pipeline's fixed spec before the code host runs;
         unknown pipelines, inputs, values and refs are refused; defaults are the safe ones; a double click starts once; a
         paused pipeline and a run already live on the ref are refused with a reason; the answer says whether the run publishes.
Run:     python3 builds_dispatch_test.py
"""

import importlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

TMP = Path(tempfile.mkdtemp(prefix="builds-dispatch-"))
CONFIG = {
    "repo": "acme/repo",
    "branch_regex": r"^tkt-\d+-",
    "pipelines": [
        {
            "key": "rel",
            "label": "Release",
            "workflow": "release.yml",
            "ref": "main",
            "inputs": [
                {
                    "name": "mode",
                    "type": "choice",
                    "options": ["dry-run", "release"],
                    "default": "dry-run",
                    "publishes_when": "release",
                },
                {"name": "note", "type": "string", "default": ""},
            ],
        },
        {
            "key": "roll",
            "label": "Rollout",
            "workflow": "rollout.yml",
            "inputs": [
                {
                    "name": "version",
                    "type": "string",
                    "required": True,
                    "pattern": r"^\d+\.\d+\.\d+$",
                    "default": "",
                },
                {"name": "dry_run", "type": "boolean", "default": True, "publishes_when": False},
            ],
        },
        {"key": "build", "label": "Build", "workflow": "build.yml", "ref": "branch"},
        {"key": "held", "label": "Held", "workflow": "held.yml", "paused": True},
    ],
}
_saved = {}
b = None


def setUpModule():
    global b
    (TMP / "config.json").write_text(json.dumps(CONFIG))
    for k in ("BUILDS_CONFIG", "OPSCENTER_STATE_DIR"):
        _saved[k] = os.environ.get(k)
    os.environ["BUILDS_CONFIG"] = str(TMP / "config.json")
    os.environ["OPSCENTER_STATE_DIR"] = str(TMP / "state")
    import builds

    b = importlib.reload(builds)


def tearDownModule():
    for k, v in _saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    import builds

    importlib.reload(builds)


class Dispatch(unittest.TestCase):
    def setUp(self):
        b._dispatched.clear()
        b.swr._mem.pop("builds:feed", None)
        self.calls = []
        self._kick = b.swr.kick
        b.swr.kick = lambda *a, **k: None

    def tearDown(self):
        b.swr.kick = self._kick

    def run_gh(self, argv, **kw):
        self.calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def go(self, **payload):
        return b.dispatch(payload, run=self.run_gh)

    def test_defaults_are_the_safe_ones_and_the_answer_says_it_does_not_publish(self):
        r = self.go(pipeline="rel")
        self.assertEqual((r["started"], r["publishes"]), (True, False))
        argv = self.calls[0]
        self.assertIn("release.yml", argv)
        self.assertEqual(argv[argv.index("--ref") + 1], "main")
        self.assertIn("mode=dry-run", argv)

    def test_a_publishing_value_is_reported(self):
        self.assertTrue(self.go(pipeline="rel", inputs={"mode": "release"})["publishes"])
        self.assertTrue(
            self.go(pipeline="roll", inputs={"version": "1.2.3", "dry_run": False})["publishes"]
        )
        self.assertFalse(self.go(pipeline="roll", inputs={"version": "1.2.4"})["publishes"])

    def test_booleans_and_strings_pass_through(self):
        self.go(pipeline="roll", inputs={"version": "1.30.1", "dry_run": False})
        self.assertIn("version=1.30.1", self.calls[0])
        self.assertIn("dry_run=false", self.calls[0])

    def test_refusals_never_reach_the_code_host(self):
        bad = [
            (dict(pipeline="nope"), 404),
            (dict(pipeline="rel", inputs={"mode": "yolo"}), 400),
            (dict(pipeline="rel", inputs={"extra": "x"}), 400),
            (dict(pipeline="rel", ref="tkt-1-x"), 400),
            (dict(pipeline="roll", inputs={"version": ""}), 400),
            (dict(pipeline="roll", inputs={"version": "1.2; rm -rf"}), 400),
            (dict(pipeline="roll", inputs={"version": "1.2.3", "dry_run": "yes"}), 400),
            (dict(pipeline="build", ref="feature/x"), 400),
            (dict(pipeline="rel", inputs={"note": "two\nlines"}), 400),
            (dict(pipeline="held"), 409),
        ]
        for payload, status in bad:
            with self.assertRaises(b.BuildsError, msg=payload) as e:
                self.go(**payload)
            self.assertEqual(e.exception.status, status, payload)
        self.assertEqual(self.calls, [])

    def test_the_unknown_input_error_names_it(self):
        with self.assertRaises(b.BuildsError) as e:
            self.go(pipeline="rel", inputs={"zzz": "1", "yyy": "2"})
        self.assertIn("yyy, zzz", str(e.exception))

    def test_a_branch_ref_is_allowed_only_where_the_spec_says(self):
        self.go(pipeline="build", ref="tkt-6111-environments")
        self.assertEqual(self.calls[0][self.calls[0].index("--ref") + 1], "tkt-6111-environments")

    def test_a_double_click_starts_once_and_different_inputs_are_not_a_double_click(self):
        self.go(pipeline="build")
        self.assertTrue(self.go(pipeline="build")["already"])
        self.assertEqual(len(self.calls), 1)
        self.go(pipeline="rel", inputs={"note": "a"})
        self.go(pipeline="rel", inputs={"note": "b"})
        self.assertEqual(len(self.calls), 3)
        for k in list(b._dispatched):
            b._dispatched[k] = time.time() - b.DISPATCH_GAP_S - 1
        self.assertTrue(self.go(pipeline="build")["started"])

    def test_a_run_already_live_on_that_ref_is_refused_with_the_reason(self):
        b.swr._mem["builds:feed"] = {
            "val": {
                "pipelines": [
                    {"key": "build", "runs": [{"id": 7, "status": "in_progress", "branch": "main"}]}
                ]
            },
            "at": time.time(),
            "has": True,
        }
        with self.assertRaises(b.BuildsError) as e:
            self.go(pipeline="build")
        self.assertEqual(e.exception.status, 409)
        self.assertIn("run 7 in_progress", str(e.exception))
        self.assertEqual(self.calls, [])

    def test_a_failing_code_host_is_a_502_with_its_last_line(self):
        def bad(argv, **kw):
            return SimpleNamespace(returncode=1, stdout="", stderr="first\nHTTP 422 nope")

        with self.assertRaises(b.BuildsError) as e:
            b.dispatch({"pipeline": "build"}, run=bad)
        self.assertEqual((e.exception.status, str(e.exception)), (502, "HTTP 422 nope"))

    def test_the_spec_is_in_the_feed_and_covers_every_pipeline(self):
        self.assertEqual({p["key"] for p in b.PIPELINES}, set(b.DISPATCH))
        self.assertEqual(b.DISPATCH["roll"]["inputs"][1]["default"], True)
        self.assertTrue(b.DISPATCH["held"]["paused"])


if __name__ == "__main__":
    unittest.main()
