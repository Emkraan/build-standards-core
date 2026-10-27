# UI lint

`ui_lint.py` is the static half of the web-ui rules. It runs in every overlay's `core-drift.yml`
against the paths in `standards-local/ui-lint.json`, and in core CI against its own fixtures
(`--self-test`). Standard library Python, no install.

| Rule | Catches | Standard |
|---|---|---|
| UI001 | Edge-bar accents: a coloured or 2px+ single-side border, an inset side stripe, a thin edge pseudo-element, a first or last grid track of 6px or less in a file where a painted cell stretches or takes full height, a non-pseudo element 6px or less wide with a painted background (dots, where the height is at most twice the width, are fine) | web-ui 0.1 |
| UI002 | `window.alert`, `confirm`, `prompt`, or a bare `alert(`, `confirm(`, `prompt(` the file never binds itself. `const { confirm, dialog } = useConfirm()` then `confirm(...)` is not flagged | web-ui 0.7 |
| UI003 | A colour literal outside the token files (hex, rgb, hsl, oklch, named colours) | web-ui 2 |
| UI004 | A raw z-index (0 and -1 are allowed for local stacking) | web-ui 5 |
| UI005 | A raw transition or animation time | web-ui 14 |
| UI006 | Em or en dash, curly quote, NBSP, zero-width or ellipsis character | web-ui 4 |
| UI007 | `data-app-accent` set more than once, or an accent token set in app CSS | web-ui 16 |
| UI008 | A `[data-theme]` or `prefers-color-scheme` selector in app CSS (a theme is a token swap) | web-ui 1 |
| UI009 | A kit control class (`btn`, `badge`, `tab`, `input`...) borrowed by an element that restyles its box inline | web-ui 0.10 |
| UI010 | An app stylesheet that declares a core token (`--surface-1`, `--text-primary`, `--radius-md`...) | web-ui 0.11 |

## Config (`standards-local/ui-lint.json`)

```json
{ "paths": ["src"], "exclude": [], "token_files": [], "data_palettes": [], "baseline": null }
```

`token_files` adds files allowed to hold colour literals (the synced `tokens-core/` is always
allowed). A custom accent block printed by `tokens-core/build.py --accent` is recognised by its
header and may set accent tokens.

`data_palettes` lists globs of files that hold data colours (a chart theme, a table of category colours)
rather than theme colours. Colour literals in those files are exempt from UI003. Every other rule still
applies to them, and a colour literal anywhere else still fails.

## Neutral dividers

A one-sided border under 2px in a neutral grey (equal channels, or saturation of 10% or less) is a hairline
divider, so UI001 does not flag it. A coloured hairline, a 2px or thicker one-sided border, an accent edge
bar and every other UI001 shape still fail. A literal grey in that border is still a colour literal (UI003)
unless the file is a data palette: the fix is a `--border-*` token.

## Suppression is traceable

- `edge-ok` on the line or the line above, UI001 only, for data marks that look like bars.
- `core-exception: EXC-NNN` on the line or the line above. The ID must be an active row in
  `standards-local/exceptions.md`, and that row must name the finding's rule (UI001 needs a row for
  `web-ui.md 0.1`). An expired exception stops suppressing.

There is no switch that turns a rule off.

## Adoption ratchet

**Not for a UI consumer.** An app that takes the kit (a `kit-core/` copy or a vendored kit) may not
keep a baseline: `ui_lint.py` refuses one ("a baseline is not allowed for a UI consumer",
[web-ui.md](../standards/web-ui.md) 0.11), and an empty baseline file left behind holds the nightly
update. A UI consumer clears its findings during adoption instead ([kit/MIGRATION.md](../kit/MIGRATION.md),
"Close the baseline"). The ratchet below is for the script lint and for an app that runs the UI lint
without taking the kit.

An app of that kind that starts with findings records a baseline, then burns it down. One rule, one exception,
one expiry: each rule with findings needs its own active exception row naming that rule.

```bash
# 1. add one exception row per rule with findings, for example
#    | EXC-001 | web-ui.md 0.1 | src | Edge bars kept during migration | ... | 2026-10-12 | 2027-01-10 |
# 2. set "baseline": "standards-local/ui-lint-baseline.json" in ui-lint.json
python3 lint-core/ui_lint.py --write-baseline
```

`--write-baseline` refuses when a rule with findings has no exception and names the rows to add.
CI then fails only when a file and rule count rises above the baseline. Each run prints how many
findings were fixed since the baseline, and `--write-baseline` locks the progress in. When a rule's
exception expires, that rule's baseline stops counting and its findings fail.

`--json` prints findings, counts over the baseline and fixes since the baseline for tooling.

## Script lint (`script_lint.py`)

The mechanical half of the PowerShell and Python scripting rules. Same suppression
(`core-exception: EXC-NNN` naming the rule) and the same ratchet (`--write-baseline`, `--json`) as
the UI lint. It runs only when the overlay has `standards-local/script-lint.json`, otherwise it
prints one skip line and exits 0, so adopting it is a deliberate step.

```json
{ "paths": ["scripts"], "exclude": [], "python_floor": "3.9", "baseline": null }
```

`python_floor` falls back to the "Python interpreter floor" row in `standards-local/parameters.md`,
then to 3.9.

| Rule | Catches | Standard | Registry |
|---|---|---|---|
| PS001 | A non-ASCII character in a `.ps1`, `.psm1` or `.psd1` (a UTF-8 byte order mark is allowed) | scripting-powershell 1.7 | supports the overlay-ci rule |
| PS002 | A `.ps1` that does not start with the section 5 header block (`.SYNOPSIS`, `.DESCRIPTION`, `Author`, `Created: YYYY-MM-DD`, `Version`, `Exit codes`), or a function or filter whose name is not Verb-Noun with an approved verb. `*.Tests.ps1` and modules need no header | scripting-powershell 1.6 | lint |
| PS003 | An empty `catch` block (a comment is not a statement) | scripting-powershell 1.4 | lint |
| PY001 | `shell=True` with a literal true value, `os.system`, `os.popen`, `subprocess.getoutput` or `getstatusoutput` | scripting-python 1.8 | lint |
| PY002 | A ruff config (`pyproject.toml` with `[tool.ruff]`, `ruff.toml`, `.ruff.toml`) whose `target-version` is missing or is not the floor | scripting-python 1.10 | supports the overlay-ci rule |

The approved verbs are embedded (PowerShell 7 `Get-Verb`), so the lint needs no `pwsh`. A Python
file that does not parse on the running interpreter falls back to a text match for `shell=True`.

A rule marked "supports" is only partly mechanical: its findings fail the rule in
`core-status.py`, and with no finding the rule stays unverified until the overlay proves the rest
(PSScriptAnalyzer `PSUseCompatibleSyntax`, CI running `ruff check` and `ruff format --check`).

These stay with review or tests because static text cannot prove them reliably: specific catch
types and silenced calls whose output is read, parameter and variable naming, the single
subprocess helper and its timeout, atomic state writes (scripting-python 1.4), locks, environment
overrides and `from __future__ import annotations`.
