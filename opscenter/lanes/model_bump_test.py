"""Model bump target settings: the primary and secondary targets come from OPSCENTER_REVIEW_TARGETS."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class ModelBumpTargets(unittest.TestCase):
    def run_status(self, targets, *args):
        with tempfile.TemporaryDirectory() as d:
            tf = Path(d) / "targets.json"
            tf.write_text(json.dumps(targets))
            env = dict(os.environ, OPSCENTER_REVIEW_TARGETS=str(tf), OPSCENTER_ROOT=d, HOME=d)
            env["OPRG_GH_BIN"] = "/usr/bin/false"
            snippet = (  # noqa: UP031
                "import sys, json; sys.argv = ['model_bump.py'] + %r; sys.path.insert(0, %r); "
                "import model_bump as m; print(json.dumps({'repo': m.REPO, 'tag': m.TAG, 'target': m.TARGET}))"
            ) % (list(args), str(HERE))
            p = subprocess.run(
                [sys.executable, "-c", snippet], capture_output=True, text=True, env=env, timeout=60
            )
            self.assertEqual(p.returncode, 0, p.stderr[-1500:])
            return json.loads(p.stdout.strip().splitlines()[-1])

    def test_defaults_name_no_estate(self):
        got = self.run_status({})
        self.assertEqual(got["repo"], "owner/primary-repo")
        self.assertEqual(got["target"], "primary")
        self.assertEqual(got["tag"], "[primary MODEL BUMP]")

    def test_the_targets_file_sets_repo_and_tag(self):
        got = self.run_status(
            {"secondary": {"repo": "acme/other", "tag": "[other MODEL BUMP]"}},
            "tick",
            "--target",
            "secondary",
        )
        self.assertEqual(
            got, {"repo": "acme/other", "tag": "[other MODEL BUMP]", "target": "secondary"}
        )

    def test_an_unknown_target_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, OPSCENTER_ROOT=d, HOME=d)
            p = subprocess.run(
                [sys.executable, str(HERE / "model_bump.py"), "status", "--target", "nope"],
                capture_output=True,
                text=True,
                env=env,
                timeout=60,
            )
            self.assertNotEqual(p.returncode, 0)
            self.assertIn("--target must be one of", p.stderr)


if __name__ == "__main__":
    unittest.main()
