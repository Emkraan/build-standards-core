# PowerShell Scripting Standard

Version: 1.0 | Last reviewed: 2026-10-13 | Status: current | Scope: PowerShell (automation, runbooks, endpoint scripts)

How PowerShell automation is written so it can run unattended, be trialled safely and fail in a
way someone notices. It covers scheduled scripts, cloud runbooks and scripts that run on managed
endpoints. This doc is the source of truth. Where a reference implementation differs, the
implementation is fixed, or the consumer records an explicit exception (README, "Source of truth
and explicit exceptions").

Related: [CMTrace Logging Standard](cmtrace-logging.md) (log format, what not to log, the WhatIf
and exit code logging rules), [CI/CD and Release Standard](ci-cd-release.md#101-powershell-repos)
(the PowerShell CI set), [Secrets and Credentials](secrets-and-credentials.md) (identity and
secret handling), [Automation Safety](automation-safety.md) (what automation may act on),
[WPF PowerShell GUI Standards](wpf-powershell-gui.md) (interactive tools).

---

## 1. Rules

1. **Workload identity, never a stored secret.** Authenticate as a managed identity where the host has one, otherwise with a certificate held non-exportable in the machine store. Automation never holds a password, client secret, account key or credential prompt.
   - Prevents: secrets copied into scripts, runbook variables and shares that leak, never rotate and outlive the person who created them.
   - Acceptance (review): the PowerShell standards lint finds no credential prompt and no secret literal, and the header names the identity the script runs as.
2. **Every write path has a trial mode that defaults safe.** Mutating scripts support `-WhatIf` (through `SupportsShouldProcess`) or a `TrialRun` switch. `TrialRun` is the canonical name for the explicit switch; `Trial`, `TrialMode` and `TestMode` are accepted aliases in existing scripts and the CI check (see [CMTrace Logging section 10](cmtrace-logging.md#10-reading-the-logs-and-how-the-sibling-tool-ci-enforces-this)) passes any of them. New scripts use `TrialRun`; do not rename a working alias only to match. Scheduled and runbook entry points default to trial, and the switch gates every write, including state, ingestion and self-relaunch.
   - Prevents: a first run, or a schedule that lost its parameters, changing real data before anyone saw the plan.
   - Acceptance (test): a Pester test runs each entry point in trial mode with every write cmdlet mocked and asserts none was called.
3. **Destructive runs cap and fail closed.** A script that deletes or disables carries a maximum change count and stops when a source read fails, returns nothing or returns far fewer rows than the last run.
   - Prevents: an empty or failed read being treated as "everything is gone", which deletes the whole estate.
   - Acceptance (test): tests cover a failed read, an empty read and a read over the cap, and each exits non-zero with no write.
4. **Errors are caught specifically and never swallowed.** Wrap each external call in `try`/`catch`, catch the specific exception types first, and end with a catch that logs and rethrows or sets a failing exit code. No empty `catch` and no `-ErrorAction SilentlyContinue` on a call whose result is used.
   - Prevents: a run that failed half way reporting success, so the gap is found weeks later in the data.
   - Acceptance (lint): `script_lint` PS003 finds no empty catch block, and review finds no silenced call whose output is read.
5. **Exit codes and output carry the result.** Exit codes follow [CMTrace Logging section 8](cmtrace-logging.md#8-whatif-trial-mode-and-exit-codes). Runbooks write results with `Write-Output` as structured lines or objects, never `Write-Host`, and end with one summary line of counts.
   - Prevents: a scheduler showing green on a failed or partial run, and runbook streams nobody can parse.
   - Acceptance (review): every exit path sets an explicit code and the last output line is the summary.
6. **Names and header are standard.** Functions use approved Verb-Noun names, parameters are PascalCase, variables are descriptive, no local variable reuses a parameter name, and no helper shadows a built-in. Every script starts with the header block in section 5.
   - Prevents: a local that silently overwrites a parameter (names are case-insensitive), and scripts nobody can trace to an owner, host or schedule.
   - Acceptance (lint): `script_lint` PS002 finds the header fields and approved Verb-Noun function names.
7. **ASCII only, both editions.** Scripts are plain ASCII and run on Windows PowerShell 5.1 and PowerShell 7 unless the header names one edition.
   - Prevents: a curly quote or dash that 5.1 reads as a different character and breaks parsing, and code that passes on a developer's 7.x and fails on the 5.1 host.
   - Acceptance (overlay-ci): the `core-ci.yml` jobs `core-ascii` and `core-powershell` pass (the ASCII check, and PSScriptAnalyzer `PSUseCompatibleSyntax` for 5.1 and 7).
8. **Idempotent by design.** Read current state, change only what differs, read back and verify. A second run of a completed run changes nothing, and keys or folders are created only when missing.
   - Prevents: duplicate objects and repeated side effects when a scheduler retries or two runs overlap.
   - Acceptance (test): a test runs the change twice against mocks and asserts the second run makes no write.
9. **Scheduler parameters are parsed defensively.** Treat switch values from schedulers and webhooks as strings, normalise with a strict match that keeps trial mode on unless the value is an explicit false, accept parameters the platform may pre-parse from JSON, and anchor validation patterns with `\z`.
   - Prevents: a boolean parameter that fails binding on "True", an empty string that turns trial mode off, and a validated value that carries a trailing newline.
   - Acceptance (test): tests pass "true", "false", "", "garbage" and a JSON string for each switch and parameter.
10. **Endpoint scripts respect their execution context.** Detection only reads and reports, and matches exactly what remediation writes. Scripts assume SYSTEM context, a possibly 32-bit host and repeated retries, and record durable outcomes instead of clock-based limits (section 6).
    - Prevents: remediation loops that never converge, actions that silently skip half the fleet, and side effects multiplied by every retry.
    - Acceptance (review): a reviewer checks section 6 against the detection and remediation pair.
11. **Runtimes are tracked to retirement.** Every runbook records the runtime it runs on, and a retirement notice is answered from job evidence with one move to the newest supported runtime.
    - Prevents: discovering a retired runtime from failing jobs, and migrating twice because the next version down also retires soon.
    - Acceptance (review): the runbook inventory lists runtime per runbook and the next retirement date.

## 2. Authentication order

| Caller | Identity |
|---|---|
| Cloud runbook, app service, function | System or user-assigned managed identity |
| Server joined to the cloud control plane | The agent's system-assigned managed identity |
| Server with no cloud identity | Certificate on an app registration, private key non-exportable in `LocalMachine\My` |
| Managed endpoint with no cloud identity | A narrowly scoped, revocable, time-bound token (for example a policy-bound signed URL), never an account key |
| Interactive admin task | The admin's own browser sign-in. Never device-code sign-in where policy requires MFA |

- Grant the new identity the same narrow scope the old credential held, never a broader one.
- Request tokens by resource and reuse one connection per run. Pass tokens between processes through
  environment variables or pipes, never on the command line.
- When a cutover replaces a stored credential, remove the old role assignment, delete the old
  credential and purge any soft-deleted copy in the same change.

## 3. Trial mode and write gates

```powershell
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $false)][object]$TrialRun = $true,
    [Parameter(Mandatory = $false)][int]$MaxChanges = 50
)
# Only an explicit false turns trial mode off. Empty, null or garbage keeps it on.
$TrialRun = -not (([string]$TrialRun).Trim().ToLowerInvariant() -in @('false', '$false', '0'))
```

- Gate only the real mutation with `$PSCmdlet.ShouldProcess` or the `TrialRun` check. Preparation
  steps (temp copies, cleanup, log writes) pass `-WhatIf:$false`, because `-WhatIf` propagates to
  `Copy-Item`, `New-Item` and `Remove-Item` and the trial run otherwise fails for a reason production
  never hits.
- Log each skipped change with a fixed prefix (`WhatIf: would ...`), as in
  [CMTrace Logging section 8](cmtrace-logging.md#8-whatif-trial-mode-and-exit-codes).
- Count planned changes before the first write and stop when the count is over `MaxChanges`.
- Snapshot a source file to temp before hashing or uploading it if another process may write it
  mid-run, and refuse to publish an empty file.

## 4. Errors, output and language pitfalls

- Catch edition-specific exceptions separately (`System.Net.WebException` on 5.1, the HTTP response
  exception on 7). `InvalidDataException` is not an `IOException` and needs its own catch.
- A cleanup between two critical steps goes in its own `try` whose catch only logs, so it cannot
  fail the main action. The exit path retries it.
- A `trap` binds to the block it is written in. A cleanup trap for the whole script goes at script
  top level and is a no-op when nothing was opened.
- Pick one array convention. `return , $list` with an `@(...)` wrapper at the call site yields one
  element, and `.Count` reads 1 even for an empty result. Return plainly and wrap at the call site.
- `Invoke-RestMethod` on PowerShell 7 can return a top-level JSON array as one object. Assign the
  result first, then enumerate `@($rows)`. Mocks must reproduce the same shape.
- An `if` used as an expression unrolls a one-element array to a scalar. Write `@(if ($c) { $list })`.
- `ConvertFrom-Json` turns ISO 8601 strings into dates and `ConvertTo-Csv` writes them in the host
  culture. Emit dates as `ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')`.
- In double-quoted strings write `${Name}:` when a colon follows a variable.
- Sanity-check the first real run's distribution against an independent count. One decision taking
  nearly every row is a binding bug, not a finding.

## 5. Header block

```powershell
<#
.SYNOPSIS
    One line: what the script does.
.DESCRIPTION
    What it reads, what it changes, and what it never touches.
    Runs on: <host or platform>. Schedule: <cadence>. Identity: <managed identity or certificate subject>.
    Pair: <the other half of the pipeline, if any (detection, server task, relay)>.
.NOTES
    Author : <owner>
    Created: YYYY-MM-DD
    Version: 1.0.0
    Exit codes: 0 success, 1 unhandled failure, <n> <documented meaning>
#>
```

Inline comments explain only logic that is not obvious from the code.

## 6. Endpoint management scripts

- **Detection and remediation are a pair.** Detection only reads, exits with the platform's
  compliant code, and checks exactly the value remediation writes. A detection whose compliant value
  differs from what remediation writes loops forever, which shows as a recurrence count close to
  the detection count.
- **Detection output rules.** Some platforms count a custom detection as installed only when it
  exits 0 and writes to standard output. Know the rule for yours, and keep a test that fails when
  the ids a standalone detection script hardcodes drift from the package manifest.
- **SYSTEM context.** No user profile, no mapped drives, no user network credentials. A script
  that stages per-user files does it from a package installed as SYSTEM that writes into profile
  paths, never from a user-context download that needs a credential.
- **32-bit hosts.** An agent may launch a 32-bit PowerShell. Use the 64-bit path (`sysnative`) or
  the explicit registry view when the script reads or writes 64-bit locations.
- **Retries multiply side effects.** Installers are retried and remediations run on a cadence, so
  any per-run side effect repeats. Record a durable outcome (what was measured, a counted attempt
  budget, an unresolved verdict) and honour it before any lever runs. Do not use clock-based
  cooldowns or expiries: they silently exclude a device for their duration or repeat a harmful
  action when they lapse.
- **No quiet give-ups.** Every give-up emits a structured event with a reason code mapped to an
  owning team, so it is countable fleet-wide.
- **Shared resources.** A process removes only what it created. Record ownership as `<value>|<pid>`
  and reclaim a leaked value only when that process is gone. Save every value a lever can change
  before it runs and restore only what changed. Never rely on undocumented OS behaviour to undo one.
- **Write a stamp only after the action it records succeeded.**

## 7. Runbooks and runtime lifecycle

- Name runbooks by a controlled grammar (owner, domain, action) held in one file that CI and policy
  both read.
- Secrets come from the secret store through the runbook's managed identity, never from automation
  account variables.
- Job and schedule parameters arrive as strings and JSON-looking values may arrive parsed (rule 9).
  A no-parameter test run proves nothing about the real parameter shape, so trial-run the real one.
- **Retirement notices.** List runtime per runbook, then read the job objects after the deadline to
  see which runtime actually ran and whether jobs failed. Retired runtimes usually keep running with
  reduced support, so report exposure from evidence, not from the notice. Move once, to the newest
  generally available runtime.
- A webhook or schedule update API may reset every property it is not sent. Read first, then send
  the full set.

## 8. Testing

- Parse every changed file with the language parser, run PSScriptAnalyzer with the repo settings and
  report only findings new against the base branch.
- Pull branching decisions into pure functions that Pester tests directly. Test the installer
  wiring with AST structural tests when the script itself cannot run off its target OS.
- Prove a new suite catches the bug: run it against the old code (the new cases must fail) and
  mutate each guard once.
- Mock every platform cmdlet so the suite runs on a Linux CI runner, and never let a test start a
  real long-running process.
- The PR body says what was not exercised (for example, no run on a real device).

## 9. Checklist

- [ ] Managed identity or certificate auth, no stored secret, identity named in the header.
- [ ] Trial mode on every write path, default on for scheduled entry points, preparation not gated.
- [ ] Destructive runs have a change cap and stop on a failed, empty or short read.
- [ ] Specific catches, no empty catch, no silenced call whose result is used.
- [ ] Explicit exit codes, structured `Write-Output`, final summary line.
- [ ] Verb-Noun, PascalCase, no local named after a parameter, header block present.
- [ ] ASCII only, parses and lints for 5.1 and 7.
- [ ] Second run changes nothing.
- [ ] Switch and JSON parameters tested with string inputs, patterns anchored with `\z`.
- [ ] Endpoint pair: detection matches remediation, SYSTEM and 32-bit handled, no clock limits.
- [ ] Runtime recorded in the inventory.
- [ ] Logging follows [CMTrace Logging](cmtrace-logging.md#12-checklist).
