"""The docs home adapter defaults to nothing: with no DOCS_HOME_CMD every read fails closed, so a queued approval is left in
the inbox untouched, nothing is written and the run still exits 0."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parent / "queued_approvals.py"


class NullAdapter(unittest.TestCase):
    def test_a_create_with_no_adapter_stays_queued_and_writes_nothing(self):
        d = Path(tempfile.mkdtemp(prefix="aqa-null-"))
        (d / "proposals").mkdir()
        body = "hello"
        import hashlib

        sha = hashlib.sha1(body.encode()).hexdigest()
        (d / "proposals" / "fp1.body").write_text(body)
        (d / "docs-proposals.json").write_text(
            json.dumps(
                {
                    "proposals": [
                        {
                            "fp": "fp1",
                            "kind": "create",
                            "target_title": "T",
                            "parent_id": "5",
                            "body_sha": sha,
                        }
                    ]
                }
            )
        )
        (d / "approve-inbox.jsonl").write_text(
            json.dumps({"fp": "fp1", "act": "approved", "body_sha": sha}) + "\n"
        )
        cfg = d / "guard.json"
        cfg.write_text(json.dumps({"allowed_roots": {"1": "tree"}}))
        env = {k: v for k, v in os.environ.items() if not k.startswith(("DOCS_", "AQA_"))}
        env.update(AQA_DASH=str(d), DOCS_GUARD_CONFIG=str(cfg))
        p = subprocess.run(
            [sys.executable, str(APP)], capture_output=True, text=True, env=env, timeout=60
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("RETRY", p.stdout)
        self.assertIn("no docs home adapter is configured", p.stdout)
        self.assertEqual(len((d / "approve-inbox.jsonl").read_text().splitlines()), 1)
        self.assertFalse((d / "approve-applied.jsonl").exists())

    def test_an_empty_inbox_is_silent(self):
        d = Path(tempfile.mkdtemp(prefix="aqa-null-"))
        env = {k: v for k, v in os.environ.items() if not k.startswith(("DOCS_", "AQA_"))}
        env["AQA_DASH"] = str(d)
        p = subprocess.run(
            [sys.executable, str(APP)], capture_output=True, text=True, env=env, timeout=60
        )
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))


if __name__ == "__main__":
    unittest.main()
