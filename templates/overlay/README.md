# Overlay template

Copy this directory into a business's own repo. The overlay pins a version of the core and holds
only what is specific to that business.

| Path | Holds |
|---|---|
| `standards.lock` | The pinned ref, commit and content hash. It never names the core's repo or owner: scripts read the source from `CORE_REPO` or from the machine-local `consumer.json` |
| `standards-core/`, `tokens-core/`, `lint-core/`, `kit-core/` | Generated copies of the core `standards/`, `tokens/`, `lint/` and `kit/src/`. Never edit by hand |
| `standards-local/ui-lint.json` | Which app paths the UI lint checks, and an optional ratchet baseline |
| `standards-local/script-lint.json` | Which script paths the script lint checks (PowerShell and Python), the Python floor and an optional baseline. Required once `parameters.md` declares the `powershell`, `python` or `iac` stack: without it the script lint skips, and `core-status.py --require-lint-config` (run by `core-drift.yml`) fails the drift check |
| `standards-local/` | Business-specific standards and parameter values |
| `scripts/sync-core.py` | Refreshes `standards-core/`, the pin and the core template workflows the repo has (per-repo settings kept) |
| `standards-local/exceptions.md` | Explicit, time-boxed exceptions to core rules |
| `scripts/check-exceptions.py` | Fails on a malformed or expired exception or an unknown marker, warns on a rule that is not registered |
| `scripts/triage_marker.py` | The one reference parser for triage markers (`<!-- triage:<sha> <ids> -->`), imported by the merge lane and any CI re-review planner |
| `scripts/core-status.py` | One report for tooling: the pin, each registered rule's status, expiring exceptions, and (`--latest`) rules new or changed upstream |
| `scripts/core-ci.py` | The checks behind `core-ci.yml`, one subcommand per job, standard library only, with the scanner, analyzer and ruff pins |
| `scripts/repo_checks.py` | Static proofs of rules a repo's own files can show (kill by name, unpinned merges, destructive migrations, undocumented secrets and more); `core-status.py` runs them for every rule whose check kind is `repo-check` and reports pass or fail, never a guess |
| `scripts/merge-pr.py` | Squash merge with a noreply author email; refuses a pull request whose commits carry a non-noreply email, prints the recovery when the merge commit leaks one; remote only, then a local branch cleanup that is safe from any worktree or a detached HEAD |
| `.github/workflows/core-drift.yml` | The offline drift check |
| `.github/workflows/core-ci.yml` | The CI half of the standard (section "CI workflow") |
| `.github/workflows/lint-sweep.yml` | Weekly full-tree lint that keeps one issue open while it fails (ci-cd-release.md 2.1, section "Lint sweep") |
| `standards-local/proofs.json` | Consumer-owned: how the repo proves rules `core-status.py` cannot see (one record per rule, or a list such as a test plus a dated review), and (under `$not_applicable`) which rules or groups have no surface in it, each with a reason; see CONSUMING.md section 8 |

**Who owns what.** Every path above except `standards-local/` is core-owned: the sync writes it,
`check-core-sync.py` fails on a hand edit, and a consumer never adds files to it. That includes
`scripts/`: a consumer's own script (a changelog generator, a release helper) lives in the repo's
own tree outside the overlay (for example `tools/` or the app's `scripts/`), never beside the synced
scripts. `standards-local/` is the one consumer-owned folder in the overlay.

## Lint sweep

`.github/workflows/lint-sweep.yml` is copied like `core-ci.yml` (a sync refreshes it and keeps
its `OVERLAY` value at the top). Every Monday, and on demand, it runs the overlay's UI lint and script lint over the configured
paths and the repo's own full-tree lint from the parameters row `Lint sweep command` (empty: only the
overlay lints). While it fails it keeps one issue labelled `lint-sweep` open: it creates the issue
the first time, then edits that issue's body and comments on it, and never opens a second one; the
first green sweep closes it. It needs `issues: write` on its one job and nothing else. With
`core-status.py --ci` its latest run proves ci-cd-release.md 2.1.

## Parameters a business sets in `standards-local/parameters.md`

Brand accent triplet, identity provider and tenant, hosting platform, runner topology, notification
channel, and any rule it tightens. A local doc may tighten a core rule. It may not loosen one: raise
a pull request against the core instead. Where one app cannot meet a rule yet, record an explicit
exception in `standards-local/exceptions.md` (see the core README, "Source of truth and explicit
exceptions").

## CI workflow

`.github/workflows/core-ci.yml` is copied with the overlay, like `core-drift.yml`: put it in the
repo's root `.github/workflows/` and set `OVERLAY` at its top when the overlay is a subfolder. The
workflow file is refreshed by every sync (`scripts/sync-core.py`, the nightly, `core-update.yml`) like
`core-drift.yml`, `core-update.yml` and `lint-sweep.yml`, so a fix to a check or to the workflow reaches the
repo with the next release. The sync keeps what is the repo's own: the `OVERLAY` value, the overlay path
prefix in front of relative paths, every line marked `core-sync: keep` and a `schedule:` block the repo
added; nothing else in the file is customised by editing it. The runner is set without editing the file:
the repository variable `CORE_CI_RUNNER`, a JSON `runs-on` value, overrides the default `ubuntu-24.04`. A
workflow the repo does not have is not added, and a `core-ci.yml` that calls the reusable workflow is left
as it is (see below). When a release changes the job names, the sync prints the old -> new required
checks so the merge gate can be updated.

Every `uses:` is pinned to a full commit sha with its version in a comment, and the scanner
(gitleaks), PSScriptAnalyzer and ruff are pinned by version and sha256 in `core-ci.py`. The workflow
is ONE job, `core-checks` (the one check name the merge gate requires); each check is a named step
of it, and a failed step does not stop the others. A pull request runs every step, a title or body
edit is a pull request event and runs every step too, a merge queue entry runs every step that does
not read the pull request, and a push to the default branch runs only `core-secret-scan`. Steps:

| Step | Proves | Runs |
|---|---|---|
| `core-secret-scan` | secrets-and-credentials.md 1.8 | PRs and the default branch; the base commit's scanner config (or the default rules plus a path allowlist for `tokens-core/wpf/`), ignore files and `gitleaks:allow` comments off |
| `core-workflow-lint` | ci-cd-release.md 1 | every workflow: sha pins with a version comment, image digests, a top-level `permissions:` block, frozen installs |
| `core-ascii` | pr-review-and-merge.md 1.19, wpf-design-system.md 6.1, with `core-powershell` wpf-powershell-gui.md 6 and scripting-powershell.md 1.7 | every tracked text file (section "ASCII in every file") |
| `core-pr-title`, `core-commitlint` | ci-cd-release.md 3, pr-review-and-merge.md 1.2 | PRs |
| `core-attribution`, `core-identity` | pr-review-and-merge.md 1.4 | PRs; `standards-local/denylist.sha256` (optional, sha256 per lowercased term) adds the private term guard over tracked files, commits, title and body, reported by kind and place only |
| `core-changelog` | docs-and-changelog.md 1.3 and 1.9 | PRs: a moved version needs its `## YYYY-MM-DD (vX.Y.Z` heading; with the parameters row `Changelog entries` set to `per-pr`, also exactly one new entry per PR in the fixed heading, newest first, every older entry byte for byte (step `changelog-entries`; a PR that touches only the sync's overlay paths is exempt; an unknown base fails in CI) |
| `core-python` | scripting-python.md 1.1 and 1.10 | `python` stack: the floor interpreter, the committed ruff config's target, `ruff check`, `ruff format --check`, the test command |
| `core-powershell` | with `core-ascii`, the two PowerShell rules above | `powershell` or `wpf` stack: parser errors and `PSUseCompatibleSyntax` for 5.1 and 7 |
| `core-node-pin` | (ci-cd-release.md 1 principles) | `web` stack: one Node major across `.nvmrc`, `.node-version`, `engines.node` and every workflow |
| `core-kit-peers` | (kit/MIGRATION.md step 0) | an overlay with `kit-core/`: nothing the kit root reaches imports an optional peer (`recharts`, `@xyflow/react`, `@scalar/api-reference-react`), every tsconfig that includes the whole copy excludes each optional entry (`charts`, `graph`, `api-reference`) whose peer the app does not declare, and where the repo has installed `tsc` the copy typechecks with those entries excluded and their peers blocked |

Values come from `standards-local/parameters.md`: Stacks, Python floor and test command, commit
emails, changelog file, version files, ASCII patterns, Node major. The repository variable
`CORE_CI_RUNNER` sets `runs-on` as JSON; unset, the job runs on `ubuntu-24.04` (the Python floor, 3.9, has no build on newer images). Require `core-checks`
in the merge gate (section "Required checks"). Exclude the vendored copies (`standards-core/`, `lint-core/`,
`tokens-core/`, `kit-core/`) in the ruff config, as for any formatter.

`core-status.py --ci` reads the latest default-branch run of `core-ci.yml` and turns each
`overlay-ci` rule into pass or fail; without it an installed workflow leaves the rule unverified,
and a missing workflow or step fails it. A skipped step (a stack the repo does not declare) never
passes a rule. A push run skips the pull request steps, so their results are read from the run on
the head of the last merged pull request with the same tree.

**Reusable alternative (v1.12.0).** A repo may call the core's reusable `core-ci` workflow from a pinned
caller instead of copying this file; the check is then `core-checks / core-checks`. A sync leaves such a
caller alone. See CONSUMING.md, "Alternative: call the reusable `core-ci` workflow".

The workflow file gained the `kit-peers` job and the setup output `kit` in v0.57.0; a sync refreshes it.

**Job names (v0.77.0).** Every job id and check name starts with `core-` (`core-python`,
`core-identity`; `core-setup` is the helper no gate requires). Before, the template's `python` job and
a repo's own `python` job had the same check name, so a merge gate keyed on check names read the two
as one. Migration, once per repo: run a sync (it refreshes `core-ci.yml` and keeps your `OVERLAY`
value), then run `python3 scripts/core-ci.py required-checks --fix`: it lists the new names the gate
does not require yet and, under "Replace each", every old core-ci name still listed (`python ->
core-python`). Update the gate's required checks (ruleset, branch protection or `REQUIRED_CHECKS`)
and remove an old name only when no repo job of the same name needs it. Until the workflow is copied
again, `required-checks` notes that the copy predates the `core-` names and `core-status.py` reports
the overlay-ci rules as failing (`core-ci.yml has no job core-python`).

**A merge gate triggered by `workflow_run`** must list `core-ci` in `workflows:` next to the repo's
own CI workflows (and `lint-sweep` when it requires that check), or a pull request whose last
finishing check is a core-ci job is never merged until something reruns the gate (ci-cd-release.md
section 5 has the example). `core-ci.py workflow-lint` warns on a `workflow_run` trigger that lists
workflows but not `core-ci`.

### Required checks

A core-ci job proves its rule only if a red run stops the merge, so every job except `core-setup` belongs
in the merge gate's required checks. A skipped job (a stack the repo does not declare) reports
success, so requiring it costs nothing.

```
python3 scripts/core-ci.py required-checks         # is core-checks required, any old names left (needs gh)
python3 scripts/core-ci.py required-checks --fix   # also print the command that adds them
```

It reads the default branch's branch protection and active rulesets through gh, and a
`REQUIRED_CHECKS` list in any workflow (the merge gate a repo runs as a workflow on a plan without
branch protection), and exits 1 while a job is missing. `--fix` prints, and never runs, the commands:
`gh api` adding the contexts to branch protection when the branch has it, the line to add to a
`REQUIRED_CHECKS` list, and a `gh api` call that creates a ruleset requiring every core-ci job. Run
the one that fits the repo. `core-status.py --ci` lists the missing jobs as a problem whenever
`core-ci.yml` is installed (`--required-json FILE` reads the API answers from a file instead).

### ASCII in every file

The rule (pr-review-and-merge.md 1.19) is plain ASCII in every file. With the ASCII patterns
parameter empty, the `core-ascii` job reads every tracked text file; it skips binaries (a NUL byte in the
first 8 KiB), lockfiles (`package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `poetry.lock`, `uv.lock`
and the like) and the synced copies and `targets.map` destinations. The parameter still narrows the
check to the globs it lists, and every run prints that it was narrowed, but narrowing is not how a
repo with existing non-ASCII files gets green. It records a time-boxed exception per path instead:

```
| ID | Rule | Scope | Deviation | Reason | Owner | Approved | Review by |
|---|---|---|---|---|---|---|---|
| EXC-007 | pr-review-and-merge.md 1.19 | docs/legacy/** | curly quotes in imported docs | imported before the rule | owner | 2026-10-20 | 2027-01-31 |
```

`Scope` is a path, a folder or a glob (comma-separated for several). While the row is current, the
job reports each hit inside its scope as a warning naming the exception and passes; once `Review by`
passes, the hits fail again and `check-exceptions.py` fails the row. An exception for this rule never
covers a `.ps1`, `.psm1`, `.psd1` or `.xaml` file: those stay under scripting-powershell.md 1.7 and
wpf-design-system.md 6.1. The core runs the same selection over its own files
(`checks/check-ascii.py`), with no narrowing and no exception.

### Secret scanners and token files

WPF and XAML token files hold many `#RRGGBB` literals, which generic high-entropy rules report as secrets.
Allow those files in your scanner config, not by switching the scanner off:

```toml
# .gitleaks.toml (gitleaks 8.25 or newer: [[allowlists]] with paths, regexes and targetRules)
[extend]
useDefault = true          # keep every default rule; this file only adds allowances

[[allowlists]]
description = "design token files hold colour hex values, not secrets"
paths = [
  '''(^|/)tokens-core/''',
  '''(^|/)[^/]*[Tt]okens?[^/]*\.(xaml|css|json)$''',
  '''(^|/)Themes?/[^/]*\.xaml$''',
]

[[allowlists]]
description = "a bare colour literal is never a credential"
targetRules = ["generic-api-key"]
regexes = ['''#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?\b''']
```

Keep the paths to the token and theme files only. Do not allowlist `**/*.xaml`, a whole folder of code,
or the `[extend]` default rules: a secret pasted next to a colour must still be found. For other scanners
the same two allowances apply: exclude the token file paths (trufflehog `--exclude-paths FILE`, detect-secrets
`--exclude-files REGEX`, a generic `paths-ignore` list) and, where the scanner supports it, one regex for a
`#RRGGBB` or `#AARRGGBB` literal scoped to its generic high-entropy rule. The core does not weaken its own
secret scan: this snippet is for a consumer repo's scanner config only.

### Existing non-ASCII content

Fix the source with escapes first, then a time-boxed exception for generated or vendor files, then the
`ascii_ignore` table below the parameters in `standards-local/parameters.md` (columns `Path` and `Reason`,
every row needs a reason, script and XAML files cannot be listed). CONSUMING.md has the order and an example.
The `UI adoption stage` parameter (`none`, `partial`, `adopted`; empty keeps the gate on) makes the drift
workflow report the UI adoption step as N/A until the UI series lands.

## Staying current

`scripts/check-core-sync.py --latest` reports a newer release. `.github/workflows/core-update.yml` automates
the pull request (needs a GitHub App token, `CORE_APP_ID` plus `CORE_APP_PRIVATE_KEY`, or a `CORE_TOKEN` secret, and a dispatch from the repo's scheduler). An app other than an ops center never changes without
the owner's approval (core README, "Direction"), so with the repository variable `CORE_UPDATE_MERGE`
unset (or `approve`) the job only opens the pull request, as a draft so no merge gate that merges green
pull requests picks it up, and leaves it for the owner. The owner approves it in one action from the
ops center's Core consumption panel (core `standards/local-ops-app.md` section 19) or on GitHub: mark
it ready (`gh pr ready`), and the merge gate or `merge-pr.py` merges it once its checks pass. It never uses GitHub's auto-merge: on a repo with no required status checks,
`gh pr merge --auto` merges at once, before CI has run. Two values are the owner's standing approval
for one repo, set by the owner only: `wait` waits for every check on the pull request's head commit
(`core-ci.py wait-checks`: every core-ci job present, all complete and green on two reads in a row, a
timeout of `CORE_UPDATE_WAIT_MINUTES`, default 60, with a progress line of checks done, pending and
failed at most every 5 minutes, `--progress MIN` to change it) and then squash merges that commit with
`merge-pr.py --match-head-commit`, and `gate` leaves the merge to the repo's own merge gate. The
workflow file changed in v0.59.0 (the `approve` default); a sync refreshes it. `targets.map` keeps generated files in your code equal to
the synced copies. See the core README, "Staying in lockstep".

## Updating

1. `python3 scripts/sync-core.py` on a branch. When the core's template parameters sheet has rows
   your `standards-local/parameters.md` lacks, the sync appends them to its table with the template's
   value cell and the marker `<!-- sync-core: row added from the template vX.Y.Z; set a value -->`,
   never changes an existing row, and prints one line naming them. Fill each one in (an empty value
   means the row's documented default).
   The sync also refreshes the core template workflows the repo already has
   (`.github/workflows/core-ci.yml`, `core-drift.yml`, `core-update.yml`, `lint-sweep.yml`) and keeps
   the repo's own settings: the `OVERLAY` env value, the overlay path prefix in front of
   `core-drift.yml`'s relative paths, and every template line marked `# core-sync: keep` (the cron
   lines). It never touches another workflow and never adds one the repo does not have. When
   `core-ci.yml`'s job names change it prints the old -> new required-check names; update the merge
   gate (`python3 scripts/core-ci.py required-checks --fix` prints the commands). The ops center's sync
   pull request and the `core-update.yml` pull request body carry those lines, and the token
   (App or CORE_TOKEN) needs workflows write to push the refreshed files.
2. Read the core `CHANGELOG.md` entries since the old pin.
3. Open a pull request with the diff of `standards-core/`, the refreshed workflows and the new
   `standards.lock`.

## Contributing back

A rule that proves useful in one business goes to the core by pull request, stripped of business
names. `checks/check-sanitised.py` in the core must pass.

## Keeping vendored copies intact

The synced copies (`standards-core/`, `tokens-core/`, and every `targets.map` destination) are
content-hashed. Two classes of consumer tooling will break the hash or fail on them unless they
are excluded:

- Formatters and pre-commit fixers (biome, prettier, ruff-format) reflow vendored JSON and TS,
  silently rewriting the bytes; the drift check then fails with a content hash mismatch. Add
  ignore globs for the vendored directories and every `targets.map` destination, in the
  formatter config, not just the hook (CI formatters count too). For biome:
  `"!standards-overlay/standards-core/**"`, `"!standards-overlay/tokens-core/**"`, plus each
  mapped destination.
- Secret scanners (gitleaks) hit the vendored WPF resource dictionaries in `tokens-core/wpf/`,
  where `generic-api-key` matches `Key="..."` attributes. Allowlist the vendored paths in the
  consumer scan; the content is reviewed in the core before release, which is where scanning it
  belongs.

The typed mirror in a UI package (a `T` object alongside `tokens.css`) is consumer-owned: when a
sync moves a CSS custom property, the mirror's parity test fails by design. Update the mirrored
values, and any contrast annotations, in the same pull request as the sync.

## Hermes content in the overlay

The overlay may carry `core-` skills only as installed copies, placed by the core's
`python3 hermes/sync_skills.py --dest <profile home>/skills/core` run. Never hand-edit an installed core skill and never give a business
skill the `core-` prefix; shareable improvements come back to the core by pull request. Plugin
source may be shared, but no plugin configuration, keys, MCP config, gateway tokens, cron or
board config, vault contents, or `config.yaml` ever leaves the instance. The full split, failure
modes and patterns are in the core repo, `standards/hermes.md`.
