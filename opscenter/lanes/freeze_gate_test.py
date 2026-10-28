import json
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import freeze_gate as fg  # noqa: E402

CFG = json.loads((Path(__file__).resolve().parent / "fixtures" / "freeze.json").read_text())
OUTSIDE = datetime(2026, 12, 1, 15, 0, tzinfo=timezone.utc)
INSIDE = datetime(2026, 12, 24, 15, 0, tzinfo=timezone.utc)
OPEN_ENDED = datetime(2027, 2, 10, 15, 0, tzinfo=timezone.utc)


class Classify(unittest.TestCase):
    def test_docs_and_markdown_are_quiet(self):
        self.assertEqual(
            fg.classify(
                ["docs/a.txt", "app/server/README.md", "infra/main.tf"], CFG["deploy_impact"]
            ),
            [],
        )

    def test_server_path_deploys(self):
        self.assertEqual(
            fg.classify(["app/server/index.js"], CFG["deploy_impact"]), ["app/server/index.js"]
        )

    def test_client_glob_deploys(self):
        self.assertEqual(
            fg.classify(["tool/client/src/App.tsx"], CFG["deploy_impact"]),
            ["tool/client/src/App.tsx"],
        )

    def test_unrecognised_path_in_an_app_folder_fails_closed(self):
        self.assertEqual(
            fg.classify(["other-app/lib/x.js"], CFG["deploy_impact"]), ["other-app/lib/x.js"]
        )

    def test_top_level_file_and_quiet_heads_do_not_deploy(self):
        self.assertEqual(
            fg.classify(["LICENSE", "scripts/x.sh", ".github/ci.yml"], CFG["deploy_impact"]), []
        )

    def test_quiet_heads_are_a_parameter(self):
        impact = dict(CFG["deploy_impact"], quiet_heads=["tools"])
        self.assertEqual(fg.classify(["scripts/x.sh", "tools/y.sh"], impact), ["scripts/x.sh"])


class Decide(unittest.TestCase):
    def test_outside_a_freeze_merges(self):
        p, code = fg.decide(CFG, ["app/server/index.js"], OUTSIDE)
        self.assertEqual((p["verdict"], code, p["in_freeze"]), ("MERGE_OK", 0, False))

    def test_in_freeze_with_a_deploying_path_holds(self):
        p, code = fg.decide(CFG, ["app/server/index.js", "README.md"], INSIDE)
        self.assertEqual((p["verdict"], code), ("HOLD", 10))
        self.assertEqual(p["window"], "w1")
        self.assertEqual(p["exception"], "emergency change approval")
        self.assertEqual(p["matched_paths"], ["app/server/index.js"])

    def test_in_freeze_with_only_quiet_paths_merges(self):
        p, code = fg.decide(CFG, ["docs/x.txt", "README.md"], INSIDE)
        self.assertEqual((p["verdict"], code, p["in_freeze"]), ("MERGE_OK", 0, True))

    def test_open_ended_window_holds_and_says_so(self):
        p, code = fg.decide(CFG, ["app/web/x.js"], OPEN_ENDED)
        self.assertEqual((p["verdict"], code, p["open_ended"]), ("HOLD", 10, True))
        self.assertIn("end date", p["reason"])

    def test_no_paths_fails_closed_even_outside_a_freeze(self):
        p, code = fg.decide(CFG, [], OUTSIDE)
        self.assertEqual((p["verdict"], code, p["deploy_impacting"]), ("HOLD", 10, None))

    def test_window_edges(self):
        edge = datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc)  # 18:59:59 local, inside
        self.assertEqual(fg.status(CFG, edge)[0]["in_freeze"], True)
        after = datetime(2027, 1, 1, 6, 0, 0, tzinfo=timezone.utc)  # 01:00 local, after
        self.assertEqual(fg.status(CFG, after)[0]["in_freeze"], False)

    def test_status_in_and_out(self):
        self.assertEqual(fg.status(CFG, OUTSIDE)[1], 0)
        p, code = fg.status(CFG, INSIDE)
        self.assertEqual((code, p["window_name"]), (10, "quarter close"))


class Failures(unittest.TestCase):
    def test_missing_config_holds(self):
        cfg, failed = fg.load_config("/nonexistent/freeze.json")
        self.assertIsNone(cfg)
        self.assertEqual((failed[0]["verdict"], failed[1]), ("HOLD", 10))

    def test_unreadable_config_holds(self):
        bad = Path(__file__).parent / "fixtures" / "freeze-bad.json"
        bad.write_text("{not json")
        try:
            cfg, failed = fg.load_config(str(bad))
        finally:
            bad.unlink()
        self.assertIsNone(cfg)
        self.assertIn("unreadable", failed[0]["reason"])

    def test_code_host_failure_holds(self):
        def run(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 1, "", "HTTP 502")

        paths, failed = fg.changed_paths_for_pr("o/r", 5, run)
        self.assertIsNone(paths)
        self.assertEqual(failed[1], 10)
        self.assertIn("502", failed[0]["reason"])

    def test_code_host_timeout_holds(self):
        def run(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, 90)

        self.assertEqual(fg.changed_paths_for_pr("o/r", 5, run)[1][1], 10)

    def test_paths_are_read_from_the_code_host(self):
        def run(cmd, **kw):
            self.assertIn("repos/o/r/pulls/7/files", cmd[2])
            return subprocess.CompletedProcess(cmd, 0, "a.js\n\nb.js\n", "")

        self.assertEqual(fg.changed_paths_for_pr("o/r", 7, run), (["a.js", "b.js"], None))


if __name__ == "__main__":
    unittest.main()
