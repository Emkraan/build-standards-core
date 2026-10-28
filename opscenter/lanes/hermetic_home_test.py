import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "testing"))

import hermetic_home  # noqa: E402


class HermeticHome(unittest.TestCase):
    def test_install_builds_an_isolated_home(self):
        old = os.environ["HOME"]
        try:
            with tempfile.TemporaryDirectory() as d:
                fx = Path(d) / "policy.json"
                fx.write_text(json.dumps({"ok": True}))
                scripts = Path(d) / "scripts"
                scripts.mkdir()
                home = hermetic_home.install(
                    scripts=scripts, state_fixtures={"review/policy.json": fx}
                )
                self.assertEqual(os.environ["HOME"], str(home))
                self.assertNotEqual(str(home), old)
                self.assertTrue((home / ".agent" / "scripts").is_symlink())
                self.assertEqual(
                    json.loads((home / "ops" / "state" / "review" / "policy.json").read_text()),
                    {"ok": True},
                )
        finally:
            os.environ["HOME"] = old


if __name__ == "__main__":
    unittest.main()
