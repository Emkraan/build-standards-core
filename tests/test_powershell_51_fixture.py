"""The ConvertFrom-Json array rule (scripting-powershell.md) names a Windows PowerShell 5.1 fixture. Core CI has no
5.1 host, so these tests prove the fixture is what the standard says and that it never passes in silence off 5.1."""

import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests/fixtures/powershell-51/ConvertFromJsonShape.ps1"
STANDARD = (ROOT / "standards/scripting-powershell.md").read_text(encoding="utf-8")


def test_standard_gives_the_5_1_cause_and_names_the_fixture():
    assert (
        "Windows PowerShell 5.1 returns a JSON array from `ConvertFrom-Json` as a single object"
        in STANDARD
    )
    assert (
        "Do not wrap the\n  pipeline in `@(...)`; assign the result, then enumerate `@($rows)`"
        in STANDARD
    )
    assert "tests/fixtures/powershell-51/ConvertFromJsonShape.ps1" in STANDARD
    assert "separate problem from the\n  PowerShell 7 `Invoke-RestMethod` note" in STANDARD


def test_fixture_has_the_three_cases_and_only_runs_on_desktop():
    text = FIXTURE.read_text(encoding="utf-8")
    for case in ("'[]'", "'[{\"id\":1}]'", '[{"id":1},{"id":2},{"id":3}]'):
        assert case in text
    assert "Want = 0" in text and "Want = 1" in text and "Want = 3" in text
    assert "$PSVersionTable.PSEdition -ne 'Desktop'" in text
    assert "SKIP:" in text
    assert "$rows = $case.Json | ConvertFrom-Json" in text
    assert "@($rows).Count" in text
    # The rule itself: no wrapped pipeline in the fixture's own code.
    code = [ln for ln in text.splitlines() if not ln.lstrip().startswith(("#", "."))]
    assert not any("@(" in ln and "ConvertFrom-Json" in ln for ln in code)


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="no PowerShell 7 host to prove the skip")
def test_fixture_skips_plainly_off_windows_powershell():
    out = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(FIXTURE)], capture_output=True, text=True, timeout=60
    )
    assert out.returncode == 0
    assert out.stdout.startswith("SKIP:")
    assert "PASS" not in out.stdout
