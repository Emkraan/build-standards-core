# CMTrace Logging Standard

Version: 1.1 | Last reviewed: 2026-10-07 | Status: current | Scope: PowerShell

How every the owning team PowerShell script writes its log: one CMTrace-format line per event,
through one function, to a path that matches how the script runs. This is the canonical home of
`Write-CMTraceLog`. The WPF-specific parts (runspaces, the in-window log pane, UI-thread rules)
stay in [WPF PowerShell GUI Standards](wpf-powershell-gui.md#8-logging---cmtrace-format);
the CI gates are summarised in section 10 of this doc and defined in
[CI/CD and Release Standard](ci-cd-release.md).

This doc is the source of truth. Where a reference implementation differs, the implementation
is fixed, or the consumer records an explicit exception (README, "Source of truth and explicit
exceptions").
Section 11 records how the original sources differed when this standard was written.

## 1. The CMTrace line format

One log entry is one line (a message may contain line breaks; CMTrace shows them as one entry):

```text
<![LOG[Message text]LOG]!><time="HH:mm:ss.fff-240" date="MM-dd-yyyy" component="Name" context="DOMAIN\user" type="1" thread="12" file="">
```

| Field | Meaning | Rule |
|---|---|---|
| `LOG[...]` | The message | Plain ASCII. Never contains the sequence `]LOG]!>`. |
| `time` | Local time, `HH:mm:ss.fff`, then the UTC offset in minutes with a sign | Written from the local clock. The sibling tool writes the real offset (for Eastern daylight time `-240`); older copies write a fixed `+000`. Both open in CMTrace. |
| `date` | `MM-dd-yyyy` | Local date, US order. CMTrace parses this exact shape. |
| `component` | Short noun for the part of the script | Filterable in CMTrace and OneTrace. See section 5. |
| `context` | Who ran it | `DOMAIN\user` from the current Windows identity. May be empty. |
| `type` | Severity code | `1` Information, `2` Warning, `3` Error. |
| `thread` | Managed thread id | `[System.Threading.Thread]::CurrentThread.ManagedThreadId`. Separates runspaces. |
| `file` | Source file | Always `""`. Do not populate it. |

Type codes are the only severity channel. CMTrace colours type 2 yellow and type 3 red, and its
filters key off them. Do not invent other codes; CMTrace also knows type 0, which the function
below does not emit.

## 2. The canonical Write-CMTraceLog

Copy this function verbatim into every script, near the top, after declaring `$script:LogFile`
(section 3). It is plain ASCII, runs unchanged in Windows PowerShell 5.1 and PowerShell 7, and
has these properties:

- Appends with `FileShare.ReadWrite`, so background runspaces can write at once and CMTrace can
  read the file while the script runs. It does not use `Add-Content` (an exclusive lock that
  collides under concurrency).
- Uses .NET calls only for file work, so it is not suppressed by `-WhatIf` (section 8) and never
  emits to the success pipeline (section 7).
- Retries a write 3 times, then calls `Write-Warning` once, unless `$script:LogQuiet` is `$true`
  (section 7: a failed log write must not reach stdout). A failed log write never stops the
  script. A `$null` `LogFile` means logging is off and the function returns quietly.
- Rolls the file to `<name>.lo_` when it passes `$script:MaxLogSizeBytes` (section 4).
- Replaces any non-ASCII character in the message with `?`.

```powershell
function Write-CMTraceLog {
    param(
        [Parameter(Mandatory)][AllowEmptyString()][string]$Message,
        [ValidateSet('Information','Warning','Error')][string]$Severity = 'Information',
        [string]$Component = $script:LogComponent,
        [string]$LogFile   = $script:LogFile
    )
    if (-not $LogFile) { return }
    if (-not $Component) { $Component = 'Script' }
    $SevMap = @{ Information = 1; Warning = 2; Error = 3 }
    $Now    = Get-Date
    $Bias   = [int][System.TimeZoneInfo]::Local.GetUtcOffset($Now).TotalMinutes
    $Offset = '{0:+0;-0;+0}' -f $Bias
    try { $Context = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name } catch { $Context = '' }
    $Text   = [regex]::Replace($Message, '[^\x20-\x7E\r\n\t]', '?')
    $Entry  = '<![LOG[{0}]LOG]!><time="{1}{2}" date="{3}" component="{4}" context="{5}" type="{6}" thread="{7}" file="">' -f `
        $Text, $Now.ToString('HH:mm:ss.fff'), $Offset, $Now.ToString('MM-dd-yyyy'), $Component, $Context, `
        $SevMap[$Severity], [System.Threading.Thread]::CurrentThread.ManagedThreadId
    $Max = 3; $Att = 0; $Done = $false
    while (-not $Done -and $Att -lt $Max) {
        try {
            $Limit = if ($script:MaxLogSizeBytes) { [int64]$script:MaxLogSizeBytes } else { 0 }
            if ($Limit -gt 0 -and [System.IO.File]::Exists($LogFile) -and ([System.IO.FileInfo]$LogFile).Length -gt $Limit) {
                $Old = [System.IO.Path]::ChangeExtension($LogFile, 'lo_')
                try { if ([System.IO.File]::Exists($Old)) { [System.IO.File]::Delete($Old) }; [System.IO.File]::Move($LogFile, $Old) } catch { $null = $_ }
            }
            $Fs = [System.IO.File]::Open($LogFile, [System.IO.FileMode]::Append, [System.IO.FileAccess]::Write, [System.IO.FileShare]::ReadWrite)
            try { $Sw = [System.IO.StreamWriter]::new($Fs); $Sw.WriteLine($Entry); $Sw.Flush() }
            finally { $Fs.Dispose() }
            $Done = $true
        } catch {
            $Att++
            if ($Att -lt $Max) { Start-Sleep -Milliseconds 100 }
            elseif (-not $script:LogQuiet) { Write-Warning "Write-CMTraceLog failed: $($_.Exception.Message)" }
        }
    }
}
```

CI recognises the logger by the line `function Write-CMTraceLog` (section 10), so keep that exact
name. Parameters are `-Message`, `-Severity`, `-Component`, `-LogFile`. Do not rename them: tools
and shared snippets call them by name.

The `Information` / `Warning` / `Error` severity names are the standard. Two sibling tool scripts
(`Pull-JobCode.ps1` and `the device-management system Collection Manager.ps1`) use `Info`; that is tolerated, not copied.

## 3. Log paths by execution context

Declare the path once, at the top of the script, with a timestamped name, and create the folder
with .NET so `-WhatIf` cannot skip it:

```powershell
$script:LogComponent    = 'ToolName'
$script:MaxLogSizeBytes = 5MB
$script:LogFile = Join-Path $env:LOCALAPPDATA ('Logs\Software\ToolName_{0}.log' -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
try { [void][System.IO.Directory]::CreateDirectory((Split-Path -Path $script:LogFile -Parent)) }
catch { Write-Warning "Could not create the log folder: $($_.Exception.Message)"; $script:LogFile = $null }
```

| Context | Path | Notes |
|---|---|---|
| Technician GUI or interactive script (user context) | `$env:LOCALAPPDATA\Logs\Software\ToolName_<yyyyMMdd_HHmmss>.log` | What every sibling tool GUI does today. |
| Unattended task on a server (scheduled task, service account) | `C:\ProgramData\<ToolName>\<ToolName>.log` | What `Pull-JobCode.ps1` does. Fixed name, so rotation (section 4) applies. |
| SYSTEM: the device-management system or ExampleMDM deployment, CI discovery, remediation | `C:\Windows\Logs\Software\ToolName_<yyyyMMdd_HHmmss>.log` | Writable by SYSTEM. From the original logging skill; no sibling tool script uses it yet. |
| Tool launched from a network share | Per-user local path above | Never log to the share or next to the script. See the share rule in the [WPF standard](wpf-powershell-gui.md#share-hosted-tools-per-user-log-path-only). |

Rules:

- Match the path to the account. `$env:LOCALAPPDATA` under SYSTEM resolves to the system profile
  and is not where anyone will look.
- Expose an optional `-LogFile` parameter on scripts that run unattended, so a test can point at a
  scratch path. If the value is empty, logging is off; it is never an error.
- Write at start-up, then continuously. Do not buffer log lines and flush at the end.
- Write a header block right after the folder is created, so every file starts the same way:

```powershell
$ScriptName    = 'ToolName'
$ScriptVersion = '1.0.0'
Write-CMTraceLog -Message '========================================' -Component $ScriptName
Write-CMTraceLog -Message "Script  : $ScriptName v$ScriptVersion"    -Component $ScriptName
Write-CMTraceLog -Message "Machine : $($env:COMPUTERNAME)"           -Component $ScriptName
Write-CMTraceLog -Message "Log     : $script:LogFile"                -Component $ScriptName
Write-CMTraceLog -Message '========================================' -Component $ScriptName
```

The user is already in the `context` field of every line, so the header does not repeat it.

## 4. Rotation and size

- **Timestamped per-run logs** (GUI tools, deployment scripts) do not rotate within a run. Prune
  old files at start-up instead, and keep failures to a warning:

  ```powershell
  Get-ChildItem -Path (Split-Path $script:LogFile -Parent) -Filter 'ToolName_*.log' -ErrorAction SilentlyContinue |
      Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
      Remove-Item -Force -ErrorAction SilentlyContinue
  ```

- **Fixed-name logs** (unattended tasks that run daily or hourly) set `$script:MaxLogSizeBytes`
  (5 MB is the sibling tool value). The function moves the full file to `<name>.lo_` (one generation,
  the old `.lo_` is replaced) and starts a new one, the same convention the device-management system uses, so CMTrace
  opens both.
- A script that does not set `$script:MaxLogSizeBytes` never rotates. Per-run files only.
- Never let log housekeeping fail the script.

## 5. Severity and component usage

| Severity (type) | Use it for | Example |
|---|---|---|
| Information (1) | Start, finish, each step, counts, decisions, WhatIf previews | `Found 214 devices in scope.` |
| Warning (2) | Something unexpected that the script survived: skipped item, retry, fallback, a swallowed error around an external call | `Device 'PC123' has no primary user. Skipping.` |
| Error (3) | An operation failed and its result is missing or wrong, or the script is about to exit non-zero | `Failed to remove 'PC123' from the collection: <message>` |

- Log the exception message (`$_.Exception.Message`), not the whole error record or a stack dump,
  unless debugging. Include the identifier of the thing that failed.
- Every swallowed `catch` around an AD, Graph, the device-management system/WMI/CIM, ExampleMDM, ExampleSSO, file-share or
  registry call logs a Warning or Error. The full rule and the allowed empty catches are in the
  [WPF standard](wpf-powershell-gui.md#log-every-swallowed-error-around-an-external-call).
- Do not log an Error for something the script handled and recovered from; that is a Warning.
- Components are short nouns for the section of the script: `Inventory`, `Auth`, `Network`,
  `Export`, `UI`, `Worker`, `Cleanup`. Keep the set small and stable so filters stay useful. Set
  the default once with `$script:LogComponent`, and pass `-Component` only when a section differs.
  Do not leave the default to `$MyInvocation.ScriptName` (it resolves to a full file path inside a
  function).
- No emoji or box characters in messages (they would turn into `?`). A row of `=` marks the
  header and footer.

## 6. Background runspaces and the in-window log

The runspace rules (passing `$script:LogFile` and the function across, the `New-Item Function:\`
registration, writing to the UI pane before the file) are in the
[WPF standard](wpf-powershell-gui.md#8-logging---cmtrace-format) and are not repeated here.
Two points matter for logging in particular:

- Register the function in the runspace from its `ScriptBlock`, never by `Invoke-Expression` on
  `.Definition` (that executes the function body and crashes the runspace). The original skill
  recommended the `Invoke-Expression` form; the WPF standard is the correct one.
- The runspace writes to the file directly. Do not route file I/O through the dispatcher; queue
  only the display line for the UI.

## 7. the device-management system CI discovery scripts: logging must never write to the pipeline

A the device-management system Configuration Item discovery script returns a boolean and nothing else. Any extra
output object turns the result into an array and the CI evaluates wrongly. So for these scripts:

- Return only `$true` or `$false`. No strings, no counts, no objects.
- Log to the file with `Write-CMTraceLog` and nowhere else. The canonical function above emits
  nothing to the success pipeline (all .NET calls), and its one `Write-Warning` is off when
  `$script:LogQuiet = $true`. Set that at the top of every script whose stdout is parsed.
- **`Write-Warning` and stdout under `powershell.exe -File`.** Under `powershell.exe -File` (how
  the device-management client and most schedulers launch a script) a warning is written to the
  console host and reaches the captured stdout, so a failed log write or a stray `Write-Warning`
  turns `True` into `WARNING: ...` plus `True` and the CI evaluates wrongly. Under `pwsh` the
  stream is separate, so a test run there hides the defect. Rule: a script whose stdout is read by
  a machine sets `$script:LogQuiet = $true` and never calls `Write-Warning`, `Write-Host` or
  `Write-Verbose` on that path; warnings go to the log file as Severity `Warning`. Test: run the
  script with `powershell.exe -NoProfile -File x.ps1 -LogFile <unwritable path>` and assert the
  captured stdout is exactly `True` or `False`, with the log path both valid and invalid.
- No `Write-Host`, `Write-Output` of a non-boolean, `Write-Information`, `echo`, or a bare
  expression. Do not copy the console mirror that `Pull-JobCode.ps1` adds to its own function
  (`Write-Host` per message); it is fine for an unattended task and forbidden here.
- Silence every call that can return a value: `$null = ...`, `[void]`, or `| Out-Null`.
- Log the decision before returning, and keep the log path SYSTEM-safe (section 3):

```powershell
Write-CMTraceLog -Message "Compliant: $Compliant (installed $Version, required $Required)." -Component 'Discovery'
return $Compliant
```

The sibling tool CI enforces the boolean rule (section 10). It cannot see a function from another
module that writes to the pipeline, so test a discovery script by running it and checking that the
output is exactly one boolean.

## 8. WhatIf, trial mode and exit codes

- **Logging is not gated by `-WhatIf`.** The log is the record of what the script would have done.
  Write every line normally; do not wrap `Write-CMTraceLog` in `ShouldProcess`. This is why the
  function and the folder creation use .NET calls: `New-Item` and `Add-Content` honour
  `$WhatIfPreference` and would silently drop the log under `-WhatIf`.
- **Log the preview.** In `-WhatIf` or trial mode, log each skipped change as Information with a
  fixed prefix, for example `WhatIf: would remove 'PC123' from 'Ring 1'.` Log the mode in the
  header (`Mode : WhatIf`) so a reader knows no change was made.
- How trial modes gate writes, and the rest of the scripting rules, are in the
  [PowerShell Scripting Standard](scripting-powershell.md). This section covers what the log records.
- Automation scripts must support `-WhatIf` (`[CmdletBinding(SupportsShouldProcess)]` or an
  explicit `-TrialRun` switch, or the accepted aliases `-WhatIf`, `-Trial`, `-TrialMode` and
  `-TestMode`) and set explicit exit codes. `TrialRun` is the canonical name used in the
  [scripting standard](scripting-powershell.md#3-trial-mode-and-write-gates); the aliases exist
  because older scripts use them and the CI check accepts them.
- **Exit codes:** `0` success, `1` unhandled failure, any other non-zero value a documented,
  script-specific failure; `3010` for "success, reboot required" in the device-management system deployments. A
  partial result (some items failed, run completed) is a non-zero exit, with one Error line per
  failed item.
- **Always log the outcome before exiting**, so the file ends with the result:

```powershell
Write-CMTraceLog -Message ('================ END (exit {0}) ================' -f $ExitCode) -Component $ScriptName
exit $ExitCode
```

## 9. What not to log

- Secrets of any kind: passwords, client secrets, tokens, bearer or `Authorization` headers,
  certificate private material, connection strings with credentials, `SecureString` contents,
  API keys. Log that authentication succeeded and which identity or thumbprint was used, not the
  secret.
- PHI, and anything that identifies a patient: names, MRNs, encounter or account numbers, dates
  of birth. Device names, group names, UPNs and counts are fine and are the useful content.
- Whole request or response bodies from Graph, REST or ExampleSSO calls. Log the status, the
  identifier and the exception message; a body can carry personal data, and a URL can carry a
  token in its query string.
- Anything the log is not allowed to hold because the folder is broader than the data: a log under
  `C:\ProgramData` or on a share can be read by more people than the script's operator.
- Do not log full file contents or whole directory listings; log counts and the path.

If a message might contain user-supplied text, log a bounded excerpt, and never rely on the
ASCII filter in the function to remove sensitive data (it only replaces non-ASCII characters).

## 10. Reading the logs, and how the sibling tool CI enforces this

### Reading

- **CMTrace** (`CMTrace.exe`, on managed devices under `%WinDir%\CCM\` when the device-management system client
  is installed) and **OneTrace** (shipped with the device-management system console in current releases) both
  open the files. Open the file while the script runs; it updates live because the writer shares
  the file. Type 2 rows show yellow and type 3 rows red, and both viewers filter on component and
  text. Availability and exact menu names depend on the device-management system version.
- To open a rolled log, open `<name>.lo_` the same way. Both viewers can merge several files by
  time when a run spans a rolled log or several runspaces.
- From PowerShell, without CMTrace: `Get-Content -Path <log> -Tail 50 -Wait` shows raw lines.

### Enforcement (example-org-tool)

`pwsh ./ci/Invoke-CI.ps1 -Task All` runs the same checks locally and in CI. Which rules touch
logging:

| Rule | Where | What it checks |
|---|---|---|
| Script is classified | `ci/Policy.psd1` `Classes` | Every `.ps1` is `Gui`, `Automation`, `PsadtDeployment`, `AppDetection`, `CIDiscovery`, `Data` or `Fixture`. An unclassified script fails. |
| Logger present | `Test-CIHasLogging` with `LoggingPatterns` | The file contains a line matching `^\s*function\s+Write-CMTraceLog\b`, or a non-comment line that calls `Open-ADTSession` or `Write-ADTLogEntry`. Required for `Automation` and `PsadtDeployment` in the Standards task, and for `Gui`, `Automation` and `PsadtDeployment` in the Pester smoke tests. |
| WhatIf support | `Test-CISupportsWhatIf` | `SupportsShouldProcess`, or a `TrialRun` (canonical), `WhatIf`, `Trial`, `TrialMode` or `TestMode` parameter, in the script's own param block. |
| Exit code | `Test-CIHasExitCode` | At least one `exit` statement. |
| Boolean-only discovery | `Get-CINonBooleanOutput` (`CIDiscovery` scripts) | Flags `Write-Host`, `Write-Information`, `echo`, `Write-Output` or `return` of a non-boolean, and bare non-boolean expressions. |
| Known gaps | `KnownGaps` in `ci/Policy.psd1` | Pre-existing misses are skipped with a reason and a test fails when one is fixed. Never add an entry for new code. |

What CI does not check: the line format, the severity names, the log path, rotation, secrets in
messages, or that a discovery script's called functions stay off the pipeline. Those are review
items against this standard.

## 11. Where the original skill and the sibling tool code differ

The logging guidance began as an internal how-to. Where it and the sibling tool code differed, this
standard chose as follows:

| Topic | Original how-to | Sibling tool code | This standard |
|---|---|---|---|
| Time field | Fixed `+000` | `Pull-JobCode.ps1` writes the real UTC offset in minutes; the WPF tools and the [WPF standard](wpf-powershell-gui.md) write `+000` | Real offset; `+000` copies stay valid |
| `context` field | Empty | `Pull-JobCode.ps1` fills it with the Windows identity; the rest leave it empty | Windows identity |
| Severity names | `Information` | Most function definitions use `Information`; `Pull-JobCode.ps1` and `the device-management system Collection Manager.ps1` use `Info` | `Information` |
| Write method | `File.Open` with `FileShare.ReadWrite` | Same in the GUI tools; `Pull-JobCode.ps1` and `the device-management system Collection Manager.ps1` use `Add-Content` | `File.Open` (also immune to `-WhatIf`) |
| `thread` | Managed thread id | `the device-management system Collection Manager.ps1` writes `$PID` | Managed thread id |
| Rotation | None | `Pull-JobCode.ps1` rolls to `.lo_` at 5 MB | Roll to `.lo_`, opt-in by size |
| Console echo | None | `Pull-JobCode.ps1` mirrors each message with `Write-Host` | None; forbidden in discovery scripts |
| Default component | `$MyInvocation.ScriptName` | Each script sets its own component | `$script:LogComponent` |
| Machine log path | `C:\Windows\Logs\Software\` | `C:\ProgramData\<Tool>\` for the server task; no script uses the Windows path | Both, by context (section 3) |
| Runspace registration | `Invoke-Expression` of `.Definition` | The WPF standard documents that this crashes the runspace; use `New-Item Function:\` | WPF standard |
| Header | Includes user and OS | The WPF standard omits OS | Without user (it is in `context`) |

The CI/CD standard and the code agree on the deployment toolkit: `LoggingPatterns` in the sibling tool `ci/Policy.psd1`
also accepts a call to `Open-ADTSession` or `Write-ADTLogEntry` (on a non-comment line), so a
script that logs only through the deployment toolkit passes the logger check.

## 12. Checklist

- [ ] `function Write-CMTraceLog` is present, copied from section 2 (CI looks for this name).
- [ ] `$script:LogFile` is set at the top, timestamped, in the path for the execution context.
- [ ] The log folder is created with .NET, and a failure sets `$script:LogFile = $null` and warns.
- [ ] A header block, then continuous logging; no end-of-run flush.
- [ ] Info, Warning and Error used as in section 5; every swallowed external-call catch logged.
- [ ] No secrets, tokens, PHI or whole response bodies in any message.
- [ ] Automation: `-WhatIf` or trial mode logs the preview; explicit exit codes; the final line
      logs the exit code.
- [ ] CI discovery scripts: only `$true` or `$false` on the pipeline; nothing else writes output.
- [ ] Fixed-name logs set `$script:MaxLogSizeBytes`; per-run logs are pruned.
- [ ] ASCII only in the script and in every message.
