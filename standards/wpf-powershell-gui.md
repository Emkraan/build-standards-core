# WPF PowerShell GUI Standards

Version: 1.3 | Last reviewed: 2026-10-13 | Status: current for engineering rules, legacy for visuals | Scope: WPF / PowerShell 5.1

Standards for all the owning team PowerShell WPF GUI tools.
These rules are derived from production experience and must be followed exactly.

> **Visual standard moved.** The color palette and control templates in this
> document are the **legacy indigo theme**. The current org-wide visual standard
> is the [Hub Design System](wpf-design-system.md) (near-black + orange,
> derived from the reference app). Use it for all new and rebuilt tools.
> The sections below remain authoritative for the **engineering** rules:
> encoding, string-interpolation pitfalls, logging, background runspace
> patterns, and the device-management system cmdlet notes.

---

## 1. Color Palette (legacy indigo - superseded by the Hub Design System)

The original dark indigo theme. Retained for tools not yet migrated.

| Token | Hex | Usage |
|---|---|---|
| `bg-base` | `#12121C` | Window background |
| `bg-panel` | `#1A1A2E` | Cards, panels, ComboBox background |
| `bg-elevated` | `#1E1E2E` | Inset panels, textbox containers that need contrast against a panel |
| `bg-input` | `#1A1A2E` | TextBox / ComboBox fill |
| `border` | `#3A3A5C` | Control borders |
| `border-hover` | `#5A5A8A` | Border on mouse-over |
| `border-focus` | `#6366F1` | Border on focus (accent) |
| `accent` | `#6366F1` | Primary accent, AccentButton background |
| `accent-hover` | `#4F46E5` | AccentButton hover |
| `accent-pressed` | `#4338CA` | AccentButton pressed |
| `accent-border` | `#818CF8` | AccentButton border |
| `danger` | `#7F1D1D` | DangerButton background |
| `danger-hover` | `#991B1B` | DangerButton hover |
| `danger-border` | `#EF4444` | DangerButton border |
| `text-primary` | `#E0E0F0` | Primary text, button labels |
| `text-secondary` | `#C8C8E8` | TextBox input text |
| `text-muted` | `#A0A0C0` | Labels, column headers |
| `text-dim` | `#6B6B9E` | Section header labels, hints |
| `text-log` | `#7878AA` | Log pane placeholder/dim text |
| `btn-default-bg` | `#2A2A42` | Default button background |
| `btn-default-hover` | `#3A3A5C` | Default button hover |
| `btn-default-border` | `#4A4A6A` | Default button border |
| `success` | `#4ADE80` | Status dot (green), success indicators |

---

## 2. Window Declaration

```xml
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Tool Name"
        Height="780" Width="860"
        MinHeight="640" MinWidth="700"
        WindowStartupLocation="CenterScreen"
        Background="#12121C"
        Foreground="#E0E0F0"
        FontFamily="Segoe UI"
        FontSize="13">
```

- Always set `FontFamily="Segoe UI"` and `FontSize="13"` on the Window. Child elements inherit.
- Do not set font overrides on individual controls unless strictly necessary.
- When overriding font on a TextBox (e.g. monospace ring count), the font must fit within the available height - see TextBox rules below.

---

## 3. TextBox Template

### The correct template

Put `Padding` on the **Border**, not as `Margin` on the ScrollViewer.
The ScrollViewer (`PART_ContentHost`) must have no explicit `Margin`, `HorizontalScrollBarVisibility`, or `VerticalScrollBarVisibility` - the TextBox class manages its own scroll behavior internally.

```xml
<Style TargetType="TextBox">
    <Setter Property="Background"       Value="#1A1A2E"/>
    <Setter Property="Foreground"       Value="#C8C8E8"/>
    <Setter Property="BorderBrush"      Value="#3A3A5C"/>
    <Setter Property="BorderThickness"  Value="1"/>
    <Setter Property="CaretBrush"       Value="#E0E0F0"/>
    <Setter Property="Padding"          Value="10,4"/>
    <Setter Property="SelectionBrush"   Value="#6366F1"/>
    <Setter Property="Template">
        <Setter.Value>
            <ControlTemplate TargetType="TextBox">
                <Border Name="TxBorder"
                        Background="{TemplateBinding Background}"
                        BorderBrush="{TemplateBinding BorderBrush}"
                        BorderThickness="{TemplateBinding BorderThickness}"
                        CornerRadius="5"
                        Padding="{TemplateBinding Padding}">
                    <ScrollViewer Name="PART_ContentHost"
                                  Background="Transparent"
                                  Focusable="False"/>
                </Border>
                <ControlTemplate.Triggers>
                    <Trigger Property="IsMouseOver" Value="True">
                        <Setter TargetName="TxBorder" Property="BorderBrush" Value="#5A5A8A"/>
                    </Trigger>
                    <Trigger Property="IsFocused" Value="True">
                        <Setter TargetName="TxBorder" Property="BorderBrush" Value="#6366F1"/>
                    </Trigger>
                    <Trigger Property="IsEnabled" Value="False">
                        <Setter TargetName="TxBorder" Property="Opacity" Value="0.4"/>
                    </Trigger>
                </ControlTemplate.Triggers>
            </ControlTemplate>
        </Setter.Value>
    </Setter>
</Style>
```

### Rules

| Rule | Reason |
|---|---|
| `Padding` goes on the `Border`, not as `Margin` on `PART_ContentHost` | When expressed as ScrollViewer Margin, WPF's `VerticalContentAlignment` centering calculates against the full control height rather than the usable content area, pushing text outside the clip rect |
| Never set `HorizontalScrollBarVisibility` or `VerticalScrollBarVisibility` on `PART_ContentHost` | `Hidden` allocates a ~17px layout slot even though the scrollbar is invisible, consuming most of the usable height |
| `Padding` vertical value must satisfy: `Height - 2 - (2 * PaddingV) >= FontLineHeight` | Insufficient clearance clips glyph ascenders/descenders. Use `Padding="10,4"` as the default |
| Do not set `VerticalContentAlignment` in the TextBox **style**. Only set it on individual elements if needed | Style-level `VerticalContentAlignment` interacts with the custom template in ways that push text outside the visible clip rect |
| Do not override `FontFamily` on input TextBoxes unless required | Consolas/monospace fonts have ~20px line height at 13pt vs ~16px for Segoe UI. With standard padding this clips |
| When a `FontFamily` override IS used, verify: `Height - 2 - (2 * PaddingV) >= monospaceFontLineHeight (~20px)` | Consolas at 13pt needs at least 22px usable height. `Padding="10,4"` on a `Height="36"` box gives 26px |

### Height reference

| TextBox Height | Padding | Usable height | Fits Segoe UI 13pt | Fits Consolas 13pt |
|---|---|---|---|---|
| 34 | 10,6 | 20px | marginal | NO |
| 36 | 10,6 | 22px | yes | marginal |
| 36 | 10,4 | 26px | yes | YES |
| 38 | 10,4 | 28px | yes | yes |

**Default:** `Height="36"`, `Padding="10,4"`.

---

## 4. Button Styles

Three styles: default, AccentButton, DangerButton. All use `CornerRadius="5"`.

```xml
<!-- Default button -->
<Style TargetType="Button">
    <Setter Property="Background"      Value="#2A2A42"/>
    <Setter Property="Foreground"      Value="#E0E0F0"/>
    <Setter Property="BorderBrush"     Value="#4A4A6A"/>
    <Setter Property="BorderThickness" Value="1"/>
    <Setter Property="Padding"         Value="12,7"/>
    <Setter Property="Cursor"          Value="Hand"/>
    <Setter Property="FontSize"        Value="12"/>
    <Setter Property="FontWeight"      Value="SemiBold"/>
    <Setter Property="Template">
        <Setter.Value>
            <ControlTemplate TargetType="Button">
                <Border Background="{TemplateBinding Background}"
                        BorderBrush="{TemplateBinding BorderBrush}"
                        BorderThickness="{TemplateBinding BorderThickness}"
                        CornerRadius="5"
                        Padding="{TemplateBinding Padding}">
                    <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
                </Border>
                <ControlTemplate.Triggers>
                    <Trigger Property="IsMouseOver" Value="True">
                        <Setter Property="Background" Value="#3A3A5C"/>
                    </Trigger>
                    <Trigger Property="IsPressed" Value="True">
                        <Setter Property="Background" Value="#4A4A7A"/>
                    </Trigger>
                    <Trigger Property="IsEnabled" Value="False">
                        <Setter Property="Opacity" Value="0.35"/>
                    </Trigger>
                </ControlTemplate.Triggers>
            </ControlTemplate>
        </Setter.Value>
    </Setter>
</Style>

<!-- Accent (primary action) -->
<Style x:Key="AccentButton" TargetType="Button" BasedOn="{StaticResource {x:Type Button}}">
    <Setter Property="Background"  Value="#6366F1"/>
    <Setter Property="BorderBrush" Value="#818CF8"/>
    <Setter Property="Foreground"  Value="#FFFFFF"/>
    <Style.Triggers>
        <Trigger Property="IsMouseOver" Value="True">
            <Setter Property="Background" Value="#4F46E5"/>
        </Trigger>
        <Trigger Property="IsPressed" Value="True">
            <Setter Property="Background" Value="#4338CA"/>
        </Trigger>
        <Trigger Property="IsEnabled" Value="False">
            <Setter Property="Opacity" Value="0.35"/>
        </Trigger>
    </Style.Triggers>
</Style>

<!-- Danger (abort / destructive) -->
<Style x:Key="DangerButton" TargetType="Button" BasedOn="{StaticResource {x:Type Button}}">
    <Setter Property="Background"  Value="#7F1D1D"/>
    <Setter Property="BorderBrush" Value="#EF4444"/>
    <Setter Property="Foreground"  Value="#FFFFFF"/>
    <Style.Triggers>
        <Trigger Property="IsMouseOver" Value="True">
            <Setter Property="Background" Value="#991B1B"/>
        </Trigger>
        <Trigger Property="IsPressed" Value="True">
            <Setter Property="Background" Value="#B91C1C"/>
        </Trigger>
        <Trigger Property="IsEnabled" Value="False">
            <Setter Property="Opacity" Value="0.35"/>
        </Trigger>
    </Style.Triggers>
</Style>
```

- Button content must be ASCII-only - see encoding rules below.
- Use `&gt;` instead of `>` or the right angle quote (U+203A) in XAML button content strings.

---

## 5. ComboBox Template

```xml
<ControlTemplate x:Key="DarkComboToggle" TargetType="ToggleButton">
    <Border x:Name="Border" Background="#1E1E2E" BorderBrush="#3A3A5C"
            BorderThickness="1" CornerRadius="5">
        <Grid>
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="24"/>
            </Grid.ColumnDefinitions>
            <ContentPresenter Grid.Column="0" Margin="10,0,0,0"
                              VerticalAlignment="Center" HorizontalAlignment="Left"/>
            <Path Grid.Column="1" x:Name="Arrow" Fill="#8888AA"
                  HorizontalAlignment="Center" VerticalAlignment="Center"
                  Data="M 0 0 L 5 5 L 10 0 Z"/>
        </Grid>
    </Border>
    <ControlTemplate.Triggers>
        <Trigger Property="IsMouseOver" Value="True">
            <Setter TargetName="Border" Property="BorderBrush" Value="#6366F1"/>
        </Trigger>
    </ControlTemplate.Triggers>
</ControlTemplate>
```

---

## 6. Script Encoding - HARD RULE

PowerShell 5.1 on Windows reads `.ps1` files in system ANSI encoding unless a UTF-8 BOM is present. Scripts in this toolbox are deployed without a BOM.

**Any non-ASCII character in a string literal or XAML attribute will silently break parsing when the script is launched with `-WindowStyle Hidden`. The script will not run and no error will be visible.**

| Character | Replacement |
|---|---|
| Em dash (U+2014) | `-` |
| Right angle quote (U+203A) | `&gt;` in XAML, `>` in PS strings |
| Any curly quote `"` `"` `'` `'` | Straight quotes only |
| Any non-ASCII in general | ASCII equivalent or remove |

**Verification before every commit:**

```bash
python3 -c "
data = open('YourScript.ps1','rb').read()
high = [i for i,b in enumerate(data) if b > 127]
print('Non-ASCII bytes:', len(high))
"
```

Zero non-ASCII bytes is the required result.

Non-ASCII in **comments** is lower risk (comments are stripped by the parser before execution) but must still be removed to keep the verification clean and avoid future confusion.

---

## 7. PowerShell String Interpolation Pitfalls

These are silent or parser-fatal errors that produce no useful error message.
Run a syntax check before every commit (see below).

### Variable immediately followed by a colon - scope modifier ambiguity

When a variable name is immediately followed by `:` inside a double-quoted string,
PowerShell parses `$varname:` as the start of a scope-qualified reference
(like `$script:`, `$env:`, `$global:`). The parser then expects a valid variable name
after the colon, fails, and throws a parse error that prevents the script from loading.

```powershell
# BROKEN - $ringNum: looks like $script: to the parser
Write-Host "Ring $ringNum: done"
$log.Enqueue("Step $stepName: complete")

# CORRECT - brace the variable name to terminate the token
Write-Host "Ring ${ringNum}: done"
$log.Enqueue("Step ${stepName}: complete")
```

This applies anywhere a variable is followed by `:` in a double-quoted string,
including inside `Write-CMTraceLog` calls, `LogQueue.Enqueue` calls, and XAML
string literals embedded in here-strings.

**Rule:** Any variable in a double-quoted string that is followed by `:` must use
`${varname}` brace syntax.

### .NET format string - literal text containing format tokens

`[datetime].ToString()` format strings treat every letter as a potential format
token. The letter `M` means month, `d` means day, `h` means hour, etc.

```powershell
# BROKEN - the M in "PM" is parsed as month, outputs "P6" (June = 6)
$date.ToString('M/d/yy 10:00 PM')

# CORRECT - single quotes inside the format string escape literal text
$date.ToString("M/d/yy '10:00 PM'")
```

### Syntax verification before every commit

```bash
pwsh -NoProfile -Command "
\$errors = \$null
\$null = [System.Management.Automation.Language.Parser]::ParseFile(
    'YourScript.ps1', [ref]\$null, [ref]\$errors)
if (\$errors.Count -gt 0) {
    \$errors | ForEach-Object { Write-Host \"\$(\$_.Extent.StartLineNumber): \$(\$_.Message)\" }
} else { Write-Host 'No syntax errors' }
"
```

Run this **in addition to** the non-ASCII byte check. A script can be ASCII-clean and
still fail to parse due to string interpolation errors.

---

## 8. Logging - CMTrace Format

Every script uses `Write-CMTraceLog` for file logging. The canonical function, log paths, rotation and CI rules are in the [CMTrace Logging Standard](cmtrace-logging.md); this section covers the WPF specifics. Logs go to `$env:LOCALAPPDATA\Logs\Software\` for user-context tools.

### Function: one canonical logger

This doc carries no copy of `Write-CMTraceLog`. Copy the function from
[CMTrace Logging section 2](cmtrace-logging.md#2-the-canonical-write-cmtracelog) verbatim, after
declaring `$script:LogFile` and `$script:LogComponent`. A second copy drifts: an earlier one here
defaulted `Component` to `$MyInvocation.ScriptName` (a full file path inside a function), had no
null-path guard, no ASCII scrub and no rotation. Test: the `Write-CMTraceLog` definition in a
script is identical to the canonical text, and no GUI doc or snippet shows a different one.

The WPF-specific parts follow: the log path, the in-window pane and runspace registration (see the
runspace sections below).

### Log path declaration (top of every script)

```powershell
$script:LogComponent = 'ToolName'
$script:LogFile = "$env:LOCALAPPDATA\Logs\Software\ToolName_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
try { [void][System.IO.Directory]::CreateDirectory((Split-Path -Path $script:LogFile -Parent)) }
catch { Write-Warning "Could not create the log folder: $($_.Exception.Message)"; $script:LogFile = $null }
```

### Share-hosted tools: per-user log path only

Tools that run from a network share used by many technicians at once write their log to the
per-user local path above (`$env:LOCALAPPDATA\Logs\Software\`), or to a per-machine path such as
`%ProgramData%` for an unattended task. Never write one shared log file on the share or next to
the script: concurrent writers collide and the share is readable by everyone. A failed log write
must only warn (the canonical function retries, then calls `Write-Warning`); it never stops the UI.
A GUI has no stdout contract, so the warning is safe here. A script whose stdout is read by a
machine (discovery, detection) sets `$script:LogQuiet = $true` instead: see
[CMTrace Logging section 7](cmtrace-logging.md#7-the-device-management-system-ci-discovery-scripts-logging-must-never-write-to-the-pipeline).
Allow an optional `-LogFile` parameter to point the log at a dummy path for testing.

### Log every swallowed error around an external call

A `catch` that swallows an error from an AD, Graph (Mg*, `Invoke-MgGraphRequest`, REST, MSAL),
the device-management system/WMI/CIM (SMS Provider, CM cmdlets), Intune, Imprivata, file-share or registry call must log it,
even when control flow deliberately continues:

```powershell
try { $dc = (Get-ADDomainController -DomainName $Domain -Discover -ErrorAction Stop).HostName }
catch { Write-CMTraceLog -Message ("DC discovery failed for {0}: {1}" -f $Domain, $_.Exception.Message) -Severity 'Warning' }
```

Use Warning (type 2) when the tool carries on, Error (type 3) when the operation failed. Also send it
to the in-window log where the tool has one (for example the runspace LogQueue). Only pure
UI/cleanup catches (Dispose, Close, timer Stop, window and clipboard calls, best-effort cosmetic
calls) may stay empty. Their `PSAvoidUsingEmptyCatchBlock` suppression justification must list
what it covers and must not claim to cover external calls.

### Log header (immediately after log dir init)

```powershell
$ScriptName    = 'ToolName'
$ScriptVersion = '1.0.0'
Write-CMTraceLog "========================================" -Component $ScriptName
Write-CMTraceLog "Script  : $ScriptName v$ScriptVersion"   -Component $ScriptName
Write-CMTraceLog "User    : $($env:USERDOMAIN)\$($env:USERNAME)" -Component $ScriptName
Write-CMTraceLog "Machine : $($env:COMPUTERNAME)"          -Component $ScriptName
Write-CMTraceLog "Log     : $script:LogFile"               -Component $ScriptName
Write-CMTraceLog "========================================" -Component $ScriptName
```

---

## 9. Version Numbering

Every script declares a `$ScriptVersion` variable and displays it in:

- The window title: `$Window.Title = "Tool Name  v$ScriptVersion"`
- The log pane initial text: `$LogPane.Text = "  Tool Name v$ScriptVersion - ready`n"`
- The CMTrace log header

This makes it immediately verifiable after a pull that the correct version is running.

Version format: `MAJOR.MINOR.PATCH` - bump PATCH for every fix commit.

---

## 10. Background Runspace Pattern

### SyncHash

```powershell
$SyncHash = [hashtable]::Synchronized(@{
    Window       = $Window
    LogFile      = $script:LogFile
    SiteCode     = $script:SiteCode
    Status       = 'idle'   # idle | loading | ready | creating | done | error
    Abort        = $false
    LogQueue     = [System.Collections.Concurrent.ConcurrentQueue[string]]::new()
    ErrorMessage = ''
    # add domain-specific keys as needed
})
```

### Log drain timer (UI thread)

```powershell
$LogTimer = [System.Windows.Threading.DispatcherTimer]::new()
$LogTimer.Interval = [TimeSpan]::FromMilliseconds(200)
$LogTimer.Add_Tick({
    $Entry = $null
    while ($SyncHash.LogQueue.TryDequeue([ref]$Entry)) {
        $LogPane.Text += "$Entry`n"
        $LogScroller.ScrollToEnd()
    }
    # switch on $SyncHash.Status to update UI state
})
$LogTimer.Start()
```

### Runspace helper

```powershell
function Start-Runspace {
    param($Script, [hashtable]$Variables)
    $rs = [runspacefactory]::CreateRunspace()
    $rs.ApartmentState = 'STA'
    $rs.ThreadOptions  = 'ReuseThread'
    $rs.Open()
    foreach ($kv in $Variables.GetEnumerator()) {
        $rs.SessionStateProxy.SetVariable($kv.Key, $kv.Value)
    }
    $ps = [powershell]::Create()
    $ps.Runspace = $rs
    $ps.AddScript($Script) | Out-Null
    $h = $ps.BeginInvoke()
    return @{ PS = $ps; Handle = $h; Runspace = $rs }
}

$script:LogFnDef = (Get-Command Write-CMTraceLog).ScriptBlock
```

### Critical rules

#### Use `SessionStateProxy.SetVariable` - never `AddArgument`

`$ps.AddArgument($obj)` combined with `BeginInvoke()` **serializes** objects at the runspace boundary. The runspace receives a deserialized copy with no connection to the original. `SyncHash` updates from the runspace are invisible to the UI thread. `LogQueue` messages never appear. `Status` never transitions.

`SessionStateProxy.SetVariable` injects variables directly into the runspace session state as the same in-process .NET objects - no serialization, shared by reference.

```powershell
# WRONG - serializes everything, breaks shared state
$ps.AddArgument($SyncHash) | Out-Null
$ps.BeginInvoke()

# CORRECT - injects by reference, shared state works
$rs.SessionStateProxy.SetVariable('SyncHash', $SyncHash)
$ps.BeginInvoke()
```

#### Register `Write-CMTraceLog` with `New-Item Function:\` - never `Invoke-Expression`

`(Get-Command Write-CMTraceLog).Definition` returns only the function body (param block + body), not the `function Name { }` wrapper. `Invoke-Expression` of the raw body **executes** it as a script, immediately hitting the mandatory `$Message` parameter and throwing - before any log messages are enqueued, before any `SyncHash.Status` update. The entire runspace crashes silently.

```powershell
# WRONG - executes the function body, throws on mandatory param
$script:LogFnDef = (Get-Command Write-CMTraceLog).Definition
# in runspace:
Invoke-Expression $LogFn   # crashes

# CORRECT - stores as ScriptBlock, registers as named function
$script:LogFnDef = (Get-Command Write-CMTraceLog).ScriptBlock
# in runspace:
New-Item -Path "Function:\Write-CMTraceLog" -Value $LogFn -Force | Out-Null
```

#### Order of operations in catch blocks

Put UI-facing operations (`LogQueue.Enqueue`, `SyncHash.Status`) **before** CMTrace file writes. If `Write-CMTraceLog` fails (disk full, bad path), the user still sees the error in the log pane and the status transitions correctly.

```powershell
catch {
    # UI feedback first - these must always run
    $SyncHash.LogQueue.Enqueue("[$(Get-Date -Format 'HH:mm:ss')] ERROR: $($_.Exception.Message)")
    $SyncHash.ErrorMessage = $_.Exception.Message
    try { Pop-Location } catch { $SyncHash.LogQueue.Enqueue("[$(Get-Date -Format 'HH:mm:ss')] WARN: Pop-Location: $($_.Exception.Message)") }
    $SyncHash.Status = 'error'
    # File log last - failure here is acceptable
    Write-CMTraceLog "Error: $($_.Exception.Message)" -Severity 'Error' -Component $Component
}
```

#### Avoid `$Input` as a variable name in runspace scripts

`$Input` is a reserved PowerShell automatic variable (the pipeline enumerator). Assigning to it inside a scriptblock can cause unexpected behavior. Use a descriptive name instead (`$CollInput`, `$SearchTerm`, etc.).

---

## 11. Prerequisite Modules - check AND auto-install (STANDARD)

Every tool that depends on a PowerShell module (Graph, ActiveDirectory-adjacent helpers, ImportExcel, etc.) must **check for the module and offer to install it** - never just error out telling the operator to install it by hand. Service Desk machines will not all have the module, and a dead-end error is a support ticket. The tool installs to `CurrentUser` scope (no admin) with a progress splash, and only falls back to manual instructions if the install genuinely fails.

### Rules

1. **Declare requirements as data** at the top: a list of `@{ Name; MinimumVersion }`. One source of truth.
2. **Check with version awareness** - a present-but-too-old module counts as missing.
3. **Prompt once**, then install **non-interactively**. Because `PS1GUI` tools launch with no console, an interactive `Install-Module` confirmation prompt hangs invisibly. Always pass `-Force -Scope CurrentUser -AllowClobber`.
4. **Bootstrap the environment** before `Install-Module`, or it fails on a fresh box:
   - Enable **TLS 1.2** - PowerShell 5.1 defaults to TLS 1.0/1.1, which the PowerShell Gallery rejects.
   - Ensure the **NuGet package provider** is present (`Install-PackageProvider NuGet -Force -Scope CurrentUser`).
5. **Show progress** - run the install in a background runspace behind a small indeterminate-progress splash so a one-time, minute-long install is not a silent freeze. (Do the install before the main window loads.)
6. **Re-verify on disk** after installing; do not assume success.
7. **Graceful fallback** - if the install fails (locked-down machine, PSGallery blocked, no internal mirror), show the manual `Install-Module ... -Scope CurrentUser` command **and** "contact the owner." This install path may name the module and command (it is a setup action); the normal UI and HTML guides still must not expose backend internals.
8. **Do not require elevation** - `CurrentUser` scope only. A tool should never demand admin just to install its own module.

### Hardening (learned the hard way - required)

These three make the difference between "works on a fresh, locked-down healthcare box" and "spuriously fails or hangs." All are in the reference implementation (`identity provider - Manage Group Memberships`):

9. **Refresh `PSModulePath` after install, before re-verify.** On a fresh profile the CurrentUser module folder (`...\Documents\WindowsPowerShell\Modules`) often did not exist at process start, so it is **absent from the running session's `$env:PSModulePath`** - the module you just installed then looks "missing" and the tool wrongly reports failure and exits. This is the *mainline* first-run path, not an edge case. Prepend it (OneDrive/redirected-Documents aware) so the same process sees it without a relaunch:

   ```powershell
   $userModPath = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'WindowsPowerShell\Modules'
   if ($env:PSModulePath -notlike "*$userModPath*") { $env:PSModulePath = $userModPath + ';' + $env:PSModulePath }
   ```

10. **Never let the splash hang the UI.** The splash is a borderless, top-most, un-closable window; if it is closed *only* from the worker's `finally`, a runspace that cannot start (Constrained Language Mode / WDAC / AppLocker - common on clinical endpoints) leaves it open and `ShowDialog()` blocks the main thread forever. Wrap runspace `Open()`/`BeginInvoke()` in try/catch that closes the splash on failure, **and** add a 1-second `DispatcherTimer` watchdog that force-closes the splash when `$handle.IsCompleted` (belt and suspenders).
11. **Trust PSGallery for the session and surface the NuGet error.** With no console, a residual untrusted-repository confirmation prompt hangs invisibly - set `Set-PSRepository -Name PSGallery -InstallationPolicy Trusted` (try/catch, non-fatal) before installing, and pin `-Repository PSGallery`. Do **not** empty-`catch {}` the NuGet-provider bootstrap (the example below captures the error into `$fails`); fold it into the module's failure detail so a firewalled Gallery (the common failure on a locked-down network) produces an actionable message, not a downstream symptom. The same rule as the swallowed-error section above: a `catch` around an external call is never empty.

### Reusable function (drop in near the top, after the `Add-Type` WPF assemblies)

```powershell
$RequiredModules  = @( @{ Name = 'Microsoft.Graph.Authentication'; MinimumVersion = '2.0.0' } )
$ManualInstallHint = "Install-Module Microsoft.Graph -Scope CurrentUser"

function Test-ModulePresent {
    param([string]$Name, [string]$MinimumVersion)
    $have = Get-Module -ListAvailable -Name $Name | Sort-Object Version -Descending | Select-Object -First 1
    if (-not $have) { return $false }
    if ($MinimumVersion -and $have.Version -lt [version]$MinimumVersion) { return $false }
    return $true
}

function Invoke-PrerequisiteBootstrap {
    param([Parameter(Mandatory)][array]$Modules, [string]$ManualHint)

    $missing = @($Modules | Where-Object { -not (Test-ModulePresent -Name $_.Name -MinimumVersion $_.MinimumVersion) })
    if ($missing.Count -eq 0) { return $true }

    $names = ($missing | ForEach-Object { $_.Name }) -join ', '
    $ans = [System.Windows.MessageBox]::Show(
        "This tool needs a one-time component installed for your account:`n`n    $names`n`n" +
        "It installs to your user profile (no administrator rights needed) and may take a minute. Install it now?",
        "Install Prerequisite", [System.Windows.MessageBoxButton]::YesNo, [System.Windows.MessageBoxImage]::Question)
    if ($ans -ne 'Yes') {
        [System.Windows.MessageBox]::Show("The tool cannot run without it.`n`nInstall it yourself with:`n    $ManualHint`n`nor contact the owner.",
            "Prerequisite Required", "OK", "Warning") | Out-Null
        return $false
    }

    [xml]$splashXaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        WindowStyle="None" ResizeMode="NoResize" WindowStartupLocation="CenterScreen"
        Width="420" Height="150" Topmost="True" AllowsTransparency="True"
        Background="Transparent" ShowInTaskbar="False">
  <Border Background="#FF0C0C0C" BorderBrush="#FF2A2A2A" BorderThickness="1" CornerRadius="12" Padding="22,20">
    <StackPanel VerticalAlignment="Center">
      <TextBlock Text="Installing required components" Foreground="#FFF2EDE8" FontFamily="Segoe UI" FontSize="15" FontWeight="SemiBold"/>
      <TextBlock Text="One-time setup for your account. Please wait..." Foreground="#FF6E6E6E" FontFamily="Segoe UI" FontSize="11" Margin="0,4,0,14"/>
      <ProgressBar IsIndeterminate="True" Height="8" Background="#FF1C1C1C" BorderBrush="#FF2A2A2A" Foreground="#FFE06420"/>
    </StackPanel>
  </Border>
</Window>
'@
    $splash    = [Windows.Markup.XamlReader]::Load((New-Object System.Xml.XmlNodeReader $splashXaml))
    $bootstrap = [hashtable]::Synchronized(@{ Dispatcher = $splash.Dispatcher; Splash = $splash; Failures = @() })

    $installScript = {
        $fails = @()
        try {
            try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch { $fails += "TLS 1.2: $($_.Exception.Message)" }
            if (-not (Get-PackageProvider -Name NuGet -ErrorAction SilentlyContinue)) {
                try { Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Scope CurrentUser -Force -ErrorAction Stop | Out-Null } catch { $fails += "NuGet provider: $($_.Exception.Message)" }
            }
            foreach ($m in $Mods) {
                try {
                    $p = @{ Name = $m.Name; Scope = 'CurrentUser'; Force = $true; AllowClobber = $true; ErrorAction = 'Stop' }
                    if ($m.MinimumVersion) { $p.MinimumVersion = $m.MinimumVersion }
                    Install-Module @p
                    if (-not (Get-Module -ListAvailable -Name $m.Name)) { $fails += "$($m.Name): not found after install" }
                } catch { $fails += "$($m.Name): $($_.Exception.Message)" }
            }
        } catch { $fails += "Bootstrap error: $($_.Exception.Message)" }
        finally {
            $B.Failures = $fails
            $B.Dispatcher.Invoke([action] { $B.Splash.Close() }, [System.Windows.Threading.DispatcherPriority]::Background)
        }
    }

    $rs = [runspacefactory]::CreateRunspace(); $rs.ApartmentState = 'STA'; $rs.ThreadOptions = 'ReuseThread'; $rs.Open()
    $rs.SessionStateProxy.SetVariable('B', $bootstrap)
    $rs.SessionStateProxy.SetVariable('Mods', $missing)
    $ps = [powershell]::Create(); $ps.Runspace = $rs
    [void]$ps.AddScript($installScript)
    $handle = $ps.BeginInvoke()
    $splash.ShowDialog() | Out-Null          # runspace closes it when done
    try { $ps.EndInvoke($handle) } catch { $bootstrap.Failures = @($bootstrap.Failures) + "Bootstrap runspace: $($_.Exception.Message)" }
    $ps.Dispose(); $rs.Dispose()

    if (@($bootstrap.Failures).Count -gt 0 -or @($Modules | Where-Object { -not (Test-ModulePresent -Name $_.Name -MinimumVersion $_.MinimumVersion) }).Count -gt 0) {
        [System.Windows.MessageBox]::Show("Could not install the required component. Install it manually with:`n    $ManualHint`n`nor contact the owner.",
            "Install Failed", "OK", "Error") | Out-Null
        return $false
    }
    return $true
}

if (-not (Invoke-PrerequisiteBootstrap -Modules $RequiredModules -ManualHint $ManualInstallHint)) { exit 1 }
Import-Module Microsoft.Graph.Authentication -ErrorAction SilentlyContinue
```

> `$B` and `$Mods` are injected into the install runspace with `SessionStateProxy.SetVariable` (same rule as the main runspace - never `AddArgument`). The splash uses a synchronized hashtable and closes itself from the runspace via `Dispatcher.Invoke`. Reference implementation: `identity provider - Manage Group Memberships/Manage-GroupMemberships.ps1`.

---

## 12. Endpoint-Manager Cmdlet Notes

| Operation | Use | Notes |
|---|---|---|
| Find collection by ID | `Get-CMDeviceCollection -CollectionId $id` | 8-char alphanumeric IDs only |
| Find collection by name | `Get-CMDeviceCollection -Name "$term*"` | Prefix search; avoid `"*$term*"` (full table scan) |
| Get deployments | `Get-CMDeployment -CollectionName $coll.Name` | `-CollectionId` is NOT a valid parameter |
| Enumerate members (fast) | WMI query on `SMS_FullCollectionMembership` | MS-recommended indexed class; much faster than `Get-CMDevice` or `Get-CMCollectionMember` for large collections - see below |
| Add members (bulk) | `Add-CMDeviceCollectionQueryMembershipRule` with `WHERE ResourceId IN (id1,id2,...)` | One call for N devices; avoid `Add-CMDeviceDirectMembershipRule` per device |
| Member count (load phase) | `$coll.MemberCount` | Use the cached property; don't enumerate members during load |
| Refresh collection | `Invoke-CMCollectionUpdate -CollectionId $id` | |

Always `Push-Location "$($SiteCode):\"` before CM cmdlets and `Pop-Location` (in both success and catch paths) after.

### Fast member enumeration via WMI

`SMS_FullCollectionMembership` is an indexed, flat WMI class that returns only resource IDs.
Much faster than `Get-CMDevice` or `Get-CMCollectionMember` for 1000+ device collections.

```powershell
$siteServer = (Get-PSDrive -Name $SiteCode -PSProvider CMSite).Root
$namespace  = "root\SMS\site_$SiteCode"
$members = @(Get-WmiObject -Namespace $namespace -ComputerName $siteServer `
    -Query "SELECT ResourceID FROM SMS_FullCollectionMembership WHERE CollectionID = '$CollectionId'" `
    -ErrorAction SilentlyContinue)
$resourceIds = @($members | Select-Object -ExpandProperty ResourceID)
```

### Scheduling datetimes - Client local time vs UTC

the device-management system stores schedule times as UTC internally. The `New-CM*Deployment` cmdlets accept
`[datetime]` parameters for available and deadline times. How the value is stored and
which "Time based on" setting is created depends on `DateTimeKind`:

| DateTimeKind | What the device-management system does |
|---|---|
| `Local` | Converts to UTC before storing. Deployment created with "Time based on: UTC". The stored UTC value will display correctly in the console but all devices enforce at the same UTC instant - NOT each device's local 10:00 PM. |
| `Unspecified` | Stores the value as-is. "Time based on" depends on how the cmdlet or WMI object is configured. |

**Rule:** Use `DateTimeKind.Unspecified` (the default from `[datetime]::new()`) for all schedule
datetimes. Do NOT use `[datetime]::SpecifyKind(..., [DateTimeKind]::Local)` - this causes timezone
conversion that shifts the stored time and creates UTC-based schedules.

### Forcing "Client local time" - parameter names differ by cmdlet

Each deployment cmdlet uses a **different parameter** to control local vs UTC scheduling.

| Cmdlet | Parameter | Value |
|---|---|---|
| `New-CMApplicationDeployment` | `-TimeBaseOn` | `LocalTime` or `Utc` |
| `New-CMTaskSequenceDeployment` | `-UseUtcForAvailableSchedule` + `-UseUtcForExpireSchedule` | `$false` |
| `New-CMPackageDeployment` | `-UseUtcForAvailableSchedule` + `-UseUtcForExpireSchedule` | `$false` |

**`-UseUtcForAvailableSchedule` and `-UseUtcForExpireSchedule` do NOT exist on `New-CMApplicationDeployment`.**
Using them there causes "A parameter cannot be found" errors. The correct param is `-TimeBaseOn LocalTime`.

```powershell
# Application - uses -TimeBaseOn
New-CMApplicationDeployment -Name $appName -CollectionId $collId `
    -AvailableDateTime $availDt -DeadlineDateTime $deadlineDt `
    -DeployPurpose Required -DeployAction Install `
    -UserNotification DisplaySoftwareCenterOnly `
    -TimeBaseOn LocalTime | Out-Null

# Task Sequence - uses -UseUtcFor* params
New-CMTaskSequenceDeployment -TaskSequencePackageId $ts.PackageID -CollectionId $collId `
    -AvailableDateTime $availDt -DeadlineDateTime $deadlineDt `
    -DeployPurpose Required `
    -UseUtcForAvailableSchedule $false `
    -UseUtcForExpireSchedule    $false | Out-Null

# Package - uses -UseUtcFor* params
New-CMPackageDeployment -PackageId $pkg.PackageID -ProgramName '*' -CollectionId $collId `
    -AvailableDateTime $availDt -DeadlineDateTime $deadlineDt `
    -DeployPurpose Required `
    -UseUtcForAvailableSchedule $false `
    -UseUtcForExpireSchedule    $false | Out-Null
```

Combined with `DateTimeKind.Unspecified` datetimes (stored as-is, no conversion), this sets
"Time based on: Client local time" so each device enforces at the stored time in its own timezone.

### Console folder placement

To place a new collection in the same folder as its parent:

```powershell
# 1. Find the container node the parent is in
$containerItem = Get-WmiObject -Namespace $namespace -ComputerName $siteServer `
    -Class SMS_ObjectContainerItem `
    -Filter "InstanceKey='$($parentColl.CollectionID)' AND ObjectType=5000"

# 2. Walk up the node tree to build the folder path
if ($containerItem) {
    $pathParts = [System.Collections.Generic.List[string]]::new()
    $currentId = $containerItem.ContainerNodeID
    while ($currentId -and $currentId -ne 0) {
        $node = Get-WmiObject -Namespace $namespace -ComputerName $siteServer `
            -Class SMS_ObjectContainerNode -Filter "ContainerNodeID=$currentId"
        if (-not $node) { break }
        $pathParts.Insert(0, $node.Name)
        $currentId = $node.ParentContainerNodeID
    }
    if ($pathParts.Count -gt 0) {
        $folderPath = "$SiteCode`:\DeviceCollection\" + ($pathParts -join '\')
        Move-CMObject -FolderPath $folderPath -InputObject $newColl
    }
}
```

---

## 13. tool.ini Format

Every tool folder must include a `tool.ini` for automatic discovery by the toolbox folder scan.

```ini
[Data]
FileName=YourScript.ps1      ; script/exe to launch (or the URL when FileType=URL)
FileType=PS1GUI              ; PS1GUI | PS1 | EXE | BAT | URL | Path
Image=preview.png            ; optional preview image, relative to the tool folder

[Description]
Author=the owner
Version=1.0.0
Name=Your Tool               ; optional display name (else derived from the folder)
Category=Active Directory    ; optional (else derived from a "Cat - Name" folder prefix)
!Description=One-sentence description of what the tool does.
```

- `FileType=PS1GUI` launches the script hidden (see **Launching Tools** below); use `PS1` for a non-GUI console script.
- `Image=` (convention: `preview.png`) is shown in the tool's detail/preview pane; leave blank for a generated placeholder.
- `Name` / `Category` are optional. If omitted, a folder named `Cat - Tool Name` yields category `Cat` and name `Tool Name`.
- `!Description` is the key for the description field (the `!` prefix is required by the parser).

---

## 14. Launching Tools (child processes)

How a launcher starts a tool, by `FileType`:

| FileType | Launch |
|---|---|
| `URL` | `Start-Process $target` |
| `Path` | `Invoke-Item -LiteralPath $target` |
| `EXE` / `BAT` | `Start-Process -FilePath $target` |
| `PS1` | `powershell.exe` with a **visible** console |
| `PS1GUI` | `powershell.exe` with **no console window at all** |

Two hard rules, both learned from production breakage:

### 1. Quote paths that contain spaces - never use an array argument list

Tool paths routinely contain spaces (`...\the device-management system - Ring Deployment Builder\...`). Windows PowerShell's `Start-Process -ArgumentList @('-File', $path)` joins array elements with spaces **without quoting them**, so `-File \\share\the device-management system - Ring Deployment Builder\Tool.ps1` is split at every space, `powershell.exe` cannot find the script, errors, and exits. The dying process shows up as a **brief console flash** and the tool never launches.

Pass a **single string** with the path quoted instead:

```powershell
Start-Process -FilePath 'powershell.exe' `
    -ArgumentList "-ExecutionPolicy Bypass -NoProfile -File `"$target`""
```

### 2. PS1GUI must launch with no console window (no flash)

`powershell.exe -WindowStyle Hidden` still briefly allocates a console. To launch a WPF GUI script with **zero** flash, bypass `Start-Process` and start the process directly with `CreateNoWindow`:

```powershell
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName        = 'powershell.exe'
$psi.Arguments       = "-ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File `"$target`""
$psi.UseShellExecute = $false      # required for CreateNoWindow to take effect
$psi.CreateNoWindow  = $true       # no console is allocated...
$psi.WindowStyle     = [System.Diagnostics.ProcessWindowStyle]::Hidden
[System.Diagnostics.Process]::Start($psi) | Out-Null   # ...but the script's WPF window still appears
```

`CreateNoWindow` suppresses only the console; the script's `ShowDialog()` window is a separate top-level window and renders normally. The child inherits the launcher's token, so an elevated launcher starts the tool elevated with no UAC prompt. Use this for `PS1GUI`; use the visible-console form (rule 1) for `PS1`.

---

## 15. Script Structure Template

```powershell
#Requires -Version 5.1
<#
.SYNOPSIS
    Tool Name - Brief description.
.NOTES
    Author : the owner
#>

# ---------------------------------------------------------------------------
# LOG CONFIGURATION
# ---------------------------------------------------------------------------
$script:LogComponent = 'ToolName'
$script:LogFile = "$env:LOCALAPPDATA\Logs\Software\ToolName_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
try { [void][System.IO.Directory]::CreateDirectory((Split-Path -Path $script:LogFile -Parent)) }
catch { Write-Warning "Could not create the log folder: $($_.Exception.Message)"; $script:LogFile = $null }

# ---------------------------------------------------------------------------
# WRITE-CMTRACELOG  (copy verbatim - see Logging section)
# ---------------------------------------------------------------------------
# Paste the canonical Write-CMTraceLog here, unchanged:
# cmtrace-logging.md section 2. Do not write a second version.

# ---------------------------------------------------------------------------
# LOG HEADER
# ---------------------------------------------------------------------------
$ScriptName    = 'ToolName'
$ScriptVersion = '1.0.0'
Write-CMTraceLog "Script : $ScriptName v$ScriptVersion" -Component $ScriptName
Write-CMTraceLog "User   : $($env:USERDOMAIN)\$($env:USERNAME)" -Component $ScriptName

# ---------------------------------------------------------------------------
# WPF ASSEMBLIES  (needed before any MessageBox / splash / prereq bootstrap)
# ---------------------------------------------------------------------------
Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName PresentationCore
Add-Type -AssemblyName WindowsBase

# ---------------------------------------------------------------------------
# PREREQUISITES  (check AND auto-install required modules - see the
#   "Prerequisite Modules" standard above; never dead-end with "install it yourself")
# ---------------------------------------------------------------------------
# $RequiredModules = @( @{ Name = '...'; MinimumVersion = '...' } )
# if (-not (Invoke-PrerequisiteBootstrap -Modules $RequiredModules -ManualHint $ManualInstallHint)) { exit 1 }
Add-Type -AssemblyName System.Drawing

# ---------------------------------------------------------------------------
# XAML
# ---------------------------------------------------------------------------
[xml]$MainXaml = @' ... '@
$Reader = New-Object System.Xml.XmlNodeReader $MainXaml
$Window = [Windows.Markup.XamlReader]::Load($Reader)

# FindName all named elements
$txtFoo = $Window.FindName('txtFoo')
# ...

# ---------------------------------------------------------------------------
# SYNCHASH + TIMER
# ---------------------------------------------------------------------------
$SyncHash = [hashtable]::Synchronized(@{ ... })
$LogTimer = ...
$LogTimer.Start()

# Set initial state
$Window.Title = "Tool Name  v$ScriptVersion"
$LogPane.Text = "  Tool Name v$ScriptVersion - ready`n"

# ---------------------------------------------------------------------------
# RUNSPACE SCRIPTS
# ---------------------------------------------------------------------------
$script:LogFnDef = (Get-Command Write-CMTraceLog).ScriptBlock

$WorkScript = {
    $script:LogFile = $LogFile
    New-Item -Path "Function:\Write-CMTraceLog" -Value $LogFn -Force | Out-Null
    # ...
}

# ---------------------------------------------------------------------------
# RUNSPACE HELPER
# ---------------------------------------------------------------------------
function Start-Runspace { ... }

# ---------------------------------------------------------------------------
# BUTTON HANDLERS
# ---------------------------------------------------------------------------
$btnGo.Add_Click({
    Start-Runspace -Script $WorkScript -Variables @{
        SyncHash = $SyncHash
        LogFn    = $script:LogFnDef
        LogFile  = $script:LogFile
    } | Out-Null
})

# ---------------------------------------------------------------------------
# SHOW WINDOW
# ---------------------------------------------------------------------------
$Window.ShowDialog() | Out-Null
$LogTimer.Stop()
```

---

## 16. Toolbox Standardization (applies to every tool + the launcher)

These conventions are mandatory for all the owning team Toolbox tools. They keep the catalog consistent and were established 2026-06-26.

### Results tables: horizontal scroll + sorting + click-row detail panel

1. **Horizontal scroll - never let the LAST column be `Width="*"` if rows can overflow.** A `*` column absorbs all slack, so the grid never exceeds the viewport and the horizontal scrollbar never appears (data gets clipped). Give every column a real px width or `Width="Auto"`, and set `HorizontalScrollBarVisibility="Auto"`. Use a single trailing `*` column **only** when the table is intentionally fit-to-width with no overflow.
2. **Sorting on by default.** Do not set `CanUserSortColumns="False"`. For `DataGridTemplateColumn`s (and any computed column) set `SortMemberPath` so the header sort works.
3. **Every results grid has a click-row detail panel** (master-detail), so long free-text columns the grid truncates are always fully readable. Use the `Hub.DetailPanel` style (wpf-design-system.md 4k). Place an empty/`Collapsed` detail panel beside or below the grid and populate it on selection:

```powershell
# Master-detail wiring (UI thread). $DetailPane is an Hub.DetailPanel Border
# holding named TextBlocks; $ResultsGrid is the DataGrid.
$ResultsGrid.Add_SelectionChanged({
    $row = $ResultsGrid.SelectedItem
    if (-not $row) { $DetailEmpty.Visibility = 'Visible'; $DetailBody.Visibility = 'Collapsed'; return }
    $DetailEmpty.Visibility = 'Collapsed'; $DetailBody.Visibility = 'Visible'
    # set each detail TextBlock from the row object (show the FULL value, no trimming)
    $dvName.Text = [string]$row.Username
    $dvDetail.Text = [string]$row.Detail   # the long field the grid clips
})
```

The detail panel shows the full value of every column for the selected row (it is the trade-off that lets the grid columns be fixed-width for scrolling).

### Footer (two lines) - tools AND the launcher

Author line with **full names** (no initials), then **the owning team** directly beneath. `Author:` for one author, `Authors:` for two.

```xml
<StackPanel VerticalAlignment="Center">
  <TextBlock Text="Author: the owner" FontStyle="Italic" Foreground="{StaticResource Hub.Muted}" FontSize="10"/>
  <TextBlock Text="the owning team" FontStyle="Italic" Foreground="{StaticResource Hub.Muted}" FontSize="10" Margin="0,1,0,0"/>
</StackPanel>
```

### Versioning - `MAJOR.MINOR.PATCH`, bumped on every change

- **MAJOR**: breaking change to inputs/outputs, config/credential model, or a full rewrite.
- **MINOR**: new backward-compatible user-visible capability (e.g. the table/detail/help wave).
- **PATCH**: bug fix, wording/description, footer text, style-only change.

The authoritative version is the in-script `$ScriptVersion` constant (every tool must define one, even ini-only tools), **mirrored to `tool.ini` `Version=`**. Show it in the window title and the launcher card. Keep script and ini in lockstep - never let them drift.

### Descriptions - `tool.ini` `!Description=`

One short, **action-first** sentence (<= ~22 words): what it does + key input/output, consistent voice across the catalog. Example: *"Add or remove devices from the device-management system device collections via direct membership rules, with live per-device status."*

### Category-driven icons (launcher) - not the tool-name first letter

The card and sidebar icons derive from the tool's **Category**, so a family is visually recognizable. Hand-drawn WPF `Path` line-art (Stretch=Uniform, StrokeThickness 1.5, stroke `Hub.Accent`, no fill, ~16x16 viewbox) plus a category-colored dot:

| Category | Glyph (Path Data) | Dot |
|---|---|---|
| Active Directory | `M 8 1 L 8 5 M 3 9 L 3 12 M 13 9 L 13 12 M 3 5 L 13 5 L 13 9 M 3 5 L 3 9 M 8 5 L 8 9` (hierarchy) | blue `#3B82F6` |
| the device-management system | `M 8 8 m -6 0 a 6 6 0 1 0 12 0 a 6 6 0 1 0 -12 0 M 8 8 m -3 0 a 3 3 0 1 0 6 0 a 3 3 0 1 0 -6 0 M 8 2 L 8 5` (rings) | orange `#E06420` |
| Imprivata | `M 8 1 L 14 3 V 8 C 14 11 11 13 8 14 C 5 13 2 11 2 8 V 3 Z M 5 8 L 7 10 L 11 6` (shield + check) | cyan `#22D3EE` |
| General (fallback) | `M 1 4 H 6 L 7 6 H 14 V 13 H 1 Z` (folder) | gray `#6E6E6E` |

Match the category case-insensitively on family keywords (`Active Directory`/`AD`, `the device-management system`/`MECM`/`Endpoint`/`Device`, `Imprivata`, else General).

### How-to button + HTML guide + Steps Recorder capture

- **Top-right of every tool: a `How to use` button** (it replaces the redundant in-tool version badge - the version still shows in the window title, footer, and launcher card). On click it opens the tool's guide in the **default browser**: `Start-Process (Join-Path $PSScriptRoot 'guide.html')`.
- **Guides are self-contained, Hub-themed HTML** (`guide.html` in the tool folder) with section navigation - rich and printable, no Office dependency.
- **Guides are USER-facing only - never expose backend internals.** Do not name credential/secret files (`svc_key.bin`, `svc_pass.enc`) or where they live, file paths, service accounts, module/RSAT names, or log formats. For any systemy failure (won't open, missing module/credentials, access errors), tell the user to *contact the owner* rather than naming components. Same rule as the UI: Service Desk users do not need to know how the toolbox works under the hood.
- **Capturing usage for a tool that has no guide yet:** gate strictly to the owner account. On launch, if `guide.html` is absent **and** `$env:USERNAME -ieq $OwnerAccount` (a constant set to the owner's account name at the top of the script), prompt *"Capture usage to build the how-to guide?"*; on yes, `Start-Process psr.exe` (Windows Steps Recorder, native). The maintainer walks the workflow, saves the recording, and hands it off to author the HTML. The plain `How to use` button (open guide) is available to everyone; only the capture prompt is gated.

---

*Author: the owner | the owning team*
