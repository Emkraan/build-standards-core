#Requires -Version 5.1
<#
.SYNOPSIS
    Proves the ConvertFrom-Json array rule on Windows PowerShell 5.1.
.DESCRIPTION
    Windows PowerShell 5.1 returns a JSON array from ConvertFrom-Json as a single object, so a pipeline wrapped in
    @(...) yields an array inside an array. Assigning the result first and enumerating @($rows) gives the same shape
    for an empty array, one object and several objects: .Count of 0, 1 and N. This fixture runs those three cases and
    fails on any other count. It is separate from the PowerShell 7 Invoke-RestMethod note, which is a different problem.
    Runs on: Windows PowerShell 5.1 only (PSEdition Desktop). Schedule: none. Identity: none.
.NOTES
    Author : Owner
    Created: 2026-11-07
    Version: 1.0.0
    Exit codes: 0 pass (or skipped off 5.1, said plainly), 1 a case gave the wrong count
.EXAMPLE
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\ConvertFromJsonShape.ps1
#>
[CmdletBinding()]
param()

if ($PSVersionTable.PSEdition -ne 'Desktop') {
    Write-Output "SKIP: this fixture proves the rule on Windows PowerShell 5.1 (PSEdition Desktop); this host is $($PSVersionTable.PSEdition) $($PSVersionTable.PSVersion)"
    exit 0
}

$cases = @(
    @{ Name = 'empty array'; Json = '[]'; Want = 0 },
    @{ Name = 'one object'; Json = '[{"id":1}]'; Want = 1 },
    @{ Name = 'several objects'; Json = '[{"id":1},{"id":2},{"id":3}]'; Want = 3 }
)

$failed = 0
foreach ($case in $cases) {
    # The rule: assign the result first, then enumerate @($rows).
    $rows = $case.Json | ConvertFrom-Json
    $count = @($rows).Count
    if ($count -ne $case.Want) {
        Write-Output "FAIL: $($case.Name) gave Count $count, wanted $($case.Want)"
        $failed++
    } else {
        Write-Output "ok: $($case.Name) gives Count $count"
    }
}

if ($failed -gt 0) { exit 1 }
Write-Output "PASS on Windows PowerShell $($PSVersionTable.PSVersion)"
exit 0
