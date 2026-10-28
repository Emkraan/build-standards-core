import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parent / "livepath.py"


class LivePath(unittest.TestCase):
    def run_tool(self, mapping, *args):
        env = {k: v for k, v in os.environ.items() if k != "LIVEPATH_MAP"}
        if mapping is not None:
            f = Path(tempfile.mkdtemp()) / "map.json"
            f.write_text(json.dumps(mapping))
            env["LIVEPATH_MAP"] = str(f)
        p = subprocess.run(
            [sys.executable, str(TOOL), *args], capture_output=True, text=True, env=env, timeout=30
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout.splitlines()

    def test_mapped_paths_print_their_live_path_and_unmapped_are_skipped(self):
        got = self.run_tool(
            [["scripts/", "/live/scripts/"], ["~x/", "~/x-live/"]],
            "scripts/a.py",
            "other/b.py",
            "~x/c",
        )
        self.assertEqual(got[0], "/live/scripts/a.py")
        self.assertEqual(len(got), 2)
        self.assertTrue(got[1].endswith("x-live/c") and "~" not in got[1])

    def test_no_map_means_nothing_is_mapped(self):
        self.assertEqual(self.run_tool(None, "scripts/a.py"), [])
        self.assertEqual(self.run_tool("not a list", "scripts/a.py"), [])


if __name__ == "__main__":
    unittest.main()
