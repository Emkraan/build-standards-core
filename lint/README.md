# Script lint

`script_lint.py` is the mechanical half of the PowerShell and Python scripting rules. Findings are
suppressed only with `core-exception: EXC-NNN` on the line or the line above, naming the rule: the
ID must be an active row in `standards-local/exceptions.md` whose rule is the finding's rule, and an
expired exception stops suppressing. There is no switch that turns a rule off. A baseline ratchet
(`--write-baseline`, `--json`) lets an app that starts with findings record them and burn them down,
one exception row per rule with findings. It runs in core CI against its own fixtures
(`--self-test`). Standard library Python, no install.

The UI lint that used to sit beside it is retired: the web and WPF standards and their lint now live in
the owner's standards repo. The lint runs only when the overlay has `standards-local/script-lint.json`; otherwise it
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
