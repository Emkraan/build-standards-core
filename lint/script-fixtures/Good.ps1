#Requires -Version 5.1
<#
.SYNOPSIS
    Nothing in this script may be flagged.
.DESCRIPTION
    Reads a fixture and writes nothing.
    Runs on: any host. Schedule: none. Identity: none.
.NOTES
    Author : Owner
    Created: 2026-01-01
    Version: 1.0.0
    Exit codes: 0 success, 1 unhandled failure
#>
[CmdletBinding()]
param([string]$Path = '.')

function Get-FixtureItem {
    param([string]$Name)
    try {
        Get-Item -Path $Name
    } catch [System.IO.IOException], [System.UnauthorizedAccessException] {
        Write-Output "read failed: $($_.Exception.Message)"
        throw
    } catch {
        Write-Output 'unexpected failure'
        exit 1
    }
}

function script:ConvertTo-FixtureLine { param($Item) "$Item" }

# function bad_name { } is only a comment, and so is catch { }
$text = 'catch { } function no_verb { }'
$here = @'
function also_not_code { }
try { } catch { }
'@
try { Remove-Item -Path $Path -WhatIf } catch { } # core-exception: EXC-001
Write-Output "done $text $here"
