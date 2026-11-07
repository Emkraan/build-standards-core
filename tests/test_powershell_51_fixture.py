"""The ConvertFrom-Json array rule (scripting-powershell.md) names a Windows PowerShell 5.1 fixture. Core CI has no
5.1 host, so these tests prove the fixture is what the standard says and that it never passes in silence off 5.1."""

import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests/fixtures/powershell-51/ConvertFromJsonShape.ps1"
STANDARD = (ROOT / "standards/scripting-powershell.md").read_text(encoding="utf-8")


class PowerShell51FixtureTests(unittest.TestCase):
    def test_standard_gives_the_5_1_cause_and_names_the_fixture(self):
        self.assertIn(
            "Windows PowerShell 5.1 returns a JSON array from `ConvertFrom-Json` as a single object",
            STANDARD,
        )
        self.assertIn(
            "Do not wrap the\n  pipeline in `@(...)`; assign the result, then enumerate `@($rows)`",
            STANDARD,
        )
        self.assertIn("tests/fixtures/powershell-51/ConvertFromJsonShape.ps1", STANDARD)
        self.assertIn(
            "separate problem from the\n  PowerShell 7 `Invoke-RestMethod` note", STANDARD
        )

    def test_fixture_has_the_three_cases_and_only_runs_on_desktop(self):
        text = FIXTURE.read_text(encoding="utf-8")
        for case in ("'[]'", "'[{\"id\":1}]'", '[{"id":1},{"id":2},{"id":3}]'):
            self.assertIn(case, text)
        for want in ("Want = 0", "Want = 1", "Want = 3"):
            self.assertIn(want, text)
        self.assertIn("$PSVersionTable.PSEdition -ne 'Desktop'", text)
        self.assertIn("SKIP:", text)
        self.assertIn("$rows = $case.Json | ConvertFrom-Json", text)
        self.assertIn("@($rows).Count", text)
        # The rule itself: no wrapped pipeline in the fixture's own code.
        code = [ln for ln in text.splitlines() if not ln.lstrip().startswith(("#", "."))]
        self.assertFalse(any("@(" in ln and "ConvertFrom-Json" in ln for ln in code))

    @unittest.skipIf(shutil.which("pwsh") is None, "no PowerShell 7 host to prove the skip")
    def test_fixture_skips_plainly_off_windows_powershell(self):
        out = subprocess.run(
            ["pwsh", "-NoProfile", "-File", str(FIXTURE)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(out.returncode, 0)
        self.assertTrue(out.stdout.startswith("SKIP:"))
        self.assertNotIn("PASS", out.stdout)


if __name__ == "__main__":
    unittest.main()
