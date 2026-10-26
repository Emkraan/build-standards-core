# CI/CD and Release Standard

Version: 1.19 | Last reviewed: 2026-10-21 | Status: current | Scope: web (first-party), PowerShell

How first-party repos are checked, merged, deployed, released and rolled back. The reference
implementation is the reference app repo (`.github/workflows/`, `scripts/`,
`docs/DEPLOYMENT.md`). All of it runs on the free GitHub personal plan: no GitHub Advanced
Security, no branch protection, no paid scanners. Because there is no branch protection, the
auto-merge workflow is what enforces "all checks green before merge".

Related: [First-Party Build Standard](web-build.md) (stack and commands),
[Data Safety - SQLite](data-safety-sqlite.md) (why the deploy is shaped this way).

---

## 1. Principles

- Every check is free. This rule assumes the free personal plan described above (no branch protection, no paid minutes). A repo on a paid plan or an organisation may use hosted runners and required-check rulesets instead, and records that choice as an explicit exception. Jobs run on the **self-hosted runner**: `runs-on: [self-hosted, linux, arm64]`,
  never `ubuntu-latest` (GitHub-hosted minutes are not paid for on this account). The runner is a
  native linux/arm64 container (GitHub's `actions-runner` image, plus `gh`, PowerShell 7 and Playwright deps)
  under the container runtime on the owner's Mac. The hub has a pool of three (`runner-pool-1`, `-2`, `-3`) because its checks run in parallel; every other repo has one runner (`runner-core`, `runner-tool`, `runner-ops-app`, `runner-a sibling app-store repo`), the second runners were removed 2026-10-09 to save memory; build files and the registration script
  are kept in the runner scripts directory of the ops workspace. The container runtime VM is
  8 CPU / 8 GiB (raised from 6 on 2026-10-09 after OOM kills, and kept modest on purpose: guest page cache is
  not returned to macOS on a 16 GB host that already swaps). CI and deploys run only while that Mac and the container runtime are up; the Mac has system sleep
  disabled.
- Runner health: a runner watchdog script (cron, every 2 min) restarts a runner
  container only when it has no `Runner.Worker`, no job activity for 30 min, and its repo has
  queued runs; it also starts the container runtime and stopped containers. `ERR BrokerServer ... Operation
  canceled` log lines are normal (the listener cancels its own long-poll at every job start and
  finish) and are not a health signal. GitHub's runner `busy` flag and run `in_progress` counts
  lag; check for a `Runner.Worker` process instead. Live status is on the CCC Runners tab.
- Do not emulate amd64 on that runner: under Rosetta the runner (.NET), Go tools (`gh`) and pnpm 12
  (Rust) crash. Anything that must be x64 is produced explicitly and verified on amd64. The hub
  deploy package fetches the official linux-x64 `better-sqlite3` prebuilt, checks the ELF machine
  and load-tests it (and the extracted package's server smoke test) in a linux/amd64 `node:22`
  container.
- A persistent runner does not start each job on a clean VM: its job-started hook clears
  leftovers actions write to fixed `/tmp` paths, and gitleaks runs with
  `GITLEAKS_ENABLE_UPLOAD_ARTIFACT: 'false'` (its SARIF upload assumes the workspace is under
  `$HOME`).
- **Every action is pinned by full commit SHA** with the version in a trailing comment
  (`uses: actions/checkout@<sha> # v5.1.0`). Docker images are pinned by digest. Dependabot keeps
  the pins current.
- Workflows declare least-privilege `permissions:` at the top (default `contents: read`).
- The Node version in every workflow matches the App Service runtime (Node 22); a script checks it.
- `pnpm install --frozen-lockfile` everywhere. CI never rewrites the lockfile.
- CI workflows are also `workflow_call`-able, so the deploy re-runs the exact same checks on the
  commit it ships.

## 2. Required CI checks

The merge gate (a ruleset, branch protection, or the auto-merge workflow's `REQUIRED_CHECKS` list)
treats each required check-run name as required: a missing check counts as not passed. Which checks
a repo requires depends on its shape; the table below says which. The core's template
`core-ci.yml` supplies the shared checks as ONE job, `core-checks`, whose named steps each prove a
rule (`core-secret-scan`, `core-python` and the rest). The merge gate requires the one check name
`core-checks`; `core-status.py --ci` reads each step's result. Every name there starts with `core-`,
so no core-ci check shares a name with a job of the repo's own workflows: a gate keyed on check
names would read two jobs called `python` as one. A repo lists `core-checks` next to its own checks.

Why one job: each core check is a short script, so a job's cost is mostly runner start and checkout.
One job per pull request run, a push to the default branch that runs only the secret scan, and a
title or body edit that runs only the two text checks keep the shared runner pool free (twelve jobs
per run used to be most of a busy consumer's queue).

**Reusable workflow (opt in, v1.12.0).** A repo can call the core's reusable workflow
(`.github/workflows/core-ci-reusable.yml`, pinned to a release sha) from a caller `core-ci.yml` instead of
carrying a copy of the template. It is the same one job with the same steps, gating and job budget, the
caller keeps the triggers, and the pinned scripts read the repo's `standards-local` through
`CORE_CI_OVERLAY`. Because GitHub reports a job that calls a reusable workflow as
`<caller job> / <called job>`, a caller job named `core-checks` reports `core-checks / core-checks`, and that
is the one name the merge gate then requires instead of the bare `core-checks`; change the required check in
the same sitting as the caller (CONSUMING.md, "Alternative: call the reusable `core-ci` workflow"). The
copied template remains the default and is unchanged.

**Migrating to one job (v1.0.0).** Copy `core-ci.yml` from the template again (keep `OVERLAY`), then
in the merge gate require `core-checks` and remove the per-check names (`core-ascii`, `core-python`
and the others): `python3 scripts/core-ci.py required-checks --fix` prints both changes. Do it in the
same change as the copy, or the gate waits for checks that no longer report.

**Migrating to the `core-` names (v0.77.0).** Older gates used bare names (`python`); a repo still on
them goes straight to `core-checks` with the step above.

### Required checks by repo shape

`req` means required in the merge gate (for the `core-ci.yml` rows: the step must run and pass inside
the required `core-checks` check), `stack` means required when the repo declares that stack in its
Stacks parameter (the step is skipped otherwise, and a skipped step never passes a rule), and `-`
means not applicable. A local ops center has no hosted merge gate: the
nightly's local gate (`hermes/ops_center.py`) runs its column before and after every sync and is the
gate.

| Check | Single hub app | Monorepo with IaC | Docs-only repo | Local ops center |
|---|---|---|---|---|
| `core-ci.yml` step `core-secret-scan` | req | req | req | - (no hosted CI) |
| `core-ci.yml` step `core-workflow-lint` | req | req | req | - |
| `core-ci.yml` step `core-ascii` | req | req | req | - |
| `core-ci.yml` step `core-pr-title`, `core-commitlint` | req | req | req | - |
| `core-ci.yml` step `core-attribution`, `core-identity` | req | req | req | - |
| `core-ci.yml` step `core-changelog` | req | req | req | - |
| `core-ci.yml` step `core-python`, `core-powershell` | stack | stack | - | - |
| `core-ci.yml` step `core-node-pin` | req | stack | - | - |
| `core-ci.yml` step `core-kit-peers` | req (with `kit-core`) | req (with `kit-core`) | - | - |
| Build, typecheck, lint and tests (`lint-and-build` or the repo's own name) | req | req, per changed app | - | local gate: typecheck, build, verify |
| Dependency audit and OSV scan (`audit`, `osv`) | req | req | - | - |
| Static analysis (`semgrep`) | req | req | - | - |
| Data checks (`migration-safety`) | req (with a database) | req, per app with a database | - | - |
| Quality suite (`coverage`, `quality-build`, `bundle-size`, `e2e`) | req | req, per web app | - | - |
| IaC plan result (`iac-governance.md`) | - | req | - | - |
| Review bot result (`pr-review-and-merge.md` section 3) | req | req | req | - |
| Overlay checks (core sync, exceptions, UI and script lint) | `core-drift.yml` | `core-drift.yml` | `core-drift.yml` | local gate |

Every repo of every shape requires the `core-checks` check of `core-ci.yml`, whose steps cover the rows
above that apply to it: `python3 scripts/core-ci.py required-checks` reports a gate that does not
require it or still requires the old per-check names. A
repo whose shape is not in the table takes the nearest column and records the difference as an
explicit exception.

### The single hub app's full set

The reference hub app runs its own workflows under these names (its `checks.yml` jobs predate
`core-ci.yml` and carry the same rules):

| Check (job name) | Workflow | What it enforces |
|---|---|---|
| `lint-and-build` | `ci.yml` | Node pin check, frozen install, typecheck (turbo), Biome lint (errors fail), Biome format on files changed vs the base branch, vitest, turbo build, RBAC lockstep, OpenAPI check, SQLite migration smoke (fresh and fixture DB), deploy-package smoke |
| `audit` | `ci.yml` | `pnpm audit --prod`, fail on high/critical, allowlist with expiry (`scripts/audit-prod.mjs`, `.audit-allowlist.json`) |
| `osv` | `ci.yml` | OSV-Scanner on `pnpm-lock.yaml` (dev deps too), fail on HIGH/CRITICAL not in `.osv-allowlist.json` (`scripts/osv-gate.mjs`) |
| `semgrep` | `ci.yml` | Semgrep CE (`p/javascript`, `p/typescript`, `p/nodejsscan`, `p/expressjs`), metrics off, `--error` |
| `migration-safety` | `ci.yml` | base-ref migrations then PR migrations on a realistic seeded DB; fail on a lost table, column or rows |
| `actionlint` | `ci.yml` | workflow lint (digest-pinned `rhysd/actionlint` image, bundles shellcheck) |
| `gitleaks` | `ci.yml` | secret scan of the full history of the PR |
| `dash-check` | `checks.yml` | banned Unicode scan (`scripts/check-unicode.mjs`) the browser-native dialog scan (`scripts/check-native-dialogs.mjs`) and the edge-bar accent scan (`scripts/check-edge-accents.mjs`) |
| `check-lockstep` | `checks.yml` | RBAC / SysArch permission lockstep |
| `coverage` | `quality.yml` | vitest v8 coverage thresholds (ratchet) |
| `quality-build` | `quality.yml` | one client + server build per PR, uploaded as the `build-output` artifact for `bundle-size` and `e2e` |
| `bundle-size` | `quality.yml` | client gzip JS/CSS budget, +10% over the committed baseline |
| `e2e` | `quality.yml` | Playwright smoke (Chromium) + axe: no console errors, no critical or serious violations |
| `pr-title` | `checks.yml` | conventional-commit PR title |
| `commitlint` | `checks.yml` | conventional-commit messages for every PR commit |
| `attribution` | `checks.yml` | no assistant or tool attribution in PR commit messages, title or body (`scripts/check-attribution.mjs`, see below) |
| `identity` | `checks.yml` | every PR branch commit has the organisation author and committer email, or a GitHub noreply or bot address (the merge commit itself carries a noreply author email, see [PR Review and Merge](pr-review-and-merge.md) rule 18) (`scripts/check-identity.mjs`, see below) |

**Skipped on Dependabot PRs.** `gitleaks`, `semgrep`, `dash-check` and `check-lockstep` carry
`if: github.actor != 'dependabot[bot]'`: a Dependabot PR only touches manifests and
`pnpm-lock.yaml`, so they cannot find anything new, and each skip frees a runner slot. Auto-merge
counts a skipped check as passed. A human push to the branch makes them run again. Everything that
exercises the new dependencies (`lint-and-build`, `audit`, `osv`, `actionlint`, `migration-safety`,
the Quality suite, PR hygiene) always runs; `migration-safety` in particular stays on because
driver bumps such as better-sqlite3 change what the migrations run on.

**Superseded runs are cancelled.** Every PR workflow has a concurrency group keyed on the PR
number with `cancel-in-progress: ${{ github.event_name == 'pull_request' }}`, so a new push to a PR
cancels its older runs while pushes to `main` always finish.

**Light checks share one workflow.** `dash-check`, `check-lockstep`, `pr-title`, `commitlint`,
`attribution` and `identity` are jobs of one `checks.yml` (workflow `Checks`), so each push queues one run and fires one
Auto-merge `workflow_run` instead of three. Add new cheap checks there as jobs, not as new
workflow files.

When a job is added, renamed or removed, update `REQUIRED_CHECKS` in `automerge.yml`, the
`workflow_run.workflows` list there, and this table in the same PR.

### Check details

- **Attribution guard.** Every first-party repo carries a required `attribution` check (job in
  `checks.yml`, or in `pr-hygiene.yml` for repos without one) that runs
  `scripts/check-attribution.mjs`. It fails a PR when any commit message in the PR, the PR title
  or the PR body contains: a `Co-authored-by:` trailer naming anyone other than `dependabot[bot]`;
  a `Generated with` line; the vendor no-reply address; or the words Claude, Anthropic, ChatGPT,
  Copilot, GPT-4 or LLM-generated (case-insensitive). File references such as `CLAUDE.md` and
  `.claude/` are allowed because they name a file, not an author. Dependabot PRs are skipped. The
  job runs on `opened`, `edited`, `synchronize` and `reopened`, so fixing the title or body
  re-runs it. An edit runs every check, never a lighter subset: the merge gate reads the newest
  result for the check name, and an edit made seconds after a push cancels that push's run, so a
  lighter edit run would turn the gate green for a commit whose full checks never completed. Commit and PR text is written by the owner in the first person and carries no tool
  attribution. If it ever lands in history, the fix is a message-only rewrite of every branch and
  tag with a tree-hash comparison before and after; never edit trees.
- **Private term guard that does not contain its terms.** A repo that must never carry private
  names (internal hosts, tenants, people, products of the estate) runs a guard in the `attribution`
  job (no new required check name) over tracked files, commit messages and the PR title and body.
  The guard assembles each banned term from fragments at run time, so its own file never holds the
  names it bans, and it reports the kind of term and the place (file and line, or "PR body"), never
  the term itself, so a CI log does not leak it either. A plain list of the names is kept only on
  the operator's machine (a private denylist outside the repo), never in a shared repo.
  **Acceptance (test):** a fixture holding a banned term fails with its kind and location and the
  log does not contain the term; a search of the guard's own file for any banned term finds none.
- **Identity guard.** Every first-party repo carries a required `identity` check (a sibling job of
  `attribution`) that runs `scripts/check-identity.mjs` over the commits of the PR. It fails when a
  commit's author or committer email is not `*@example.com`, `noreply@github.com` (GitHub web
  merges) or `*@users.noreply.github.com` (GitHub accounts and bots, including Dependabot). Set
  `git config user.email` to the organisation address in every checkout and globally. If a personal
  address ever lands in history, the fix is the same message-and-identity-only rewrite as the
  attribution guard (a `git filter-repo` mailmap, tree hashes compared before and after).
- **Runner image and PowerShell.** The image bakes in PowerShell 7 so the sibling tool and a sibling app-store repo
  PowerShell CI set (parse, XAML well-formedness, PSScriptAnalyzer, standards lint, Pester) runs on
  linux/arm64. Those checks are static, so nothing needs Windows. A check that loads WPF would; none does.
- **Deploy-package smoke.** `scripts/build-deploy-package.sh` builds `app.zip` exactly as the
  deploy does (`pnpm deploy --prod`, hoisted linker, better-sqlite3 compiled for linux-x64 Node 22).
  `scripts/oryx-extract-smoke.sh` extracts it the way App Service Oryx does and starts the server
  from the extracted wwwroot on Node 22, proving the native module ABI before anything ships.
- **SQLite migration smoke.** `scripts/smoke-server.mjs` starts the built server on a fresh DB
  and on a fixture DB (`server/test/fixtures/schema-v<version>.sql`).
- **Migration safety.** `scripts/migration-safety.mjs` builds the base code (PR base, or the last
  release tag when called from the deploy), loads the fixture schema plus
  `seed-realistic.sql` (synthetic people on `example.test`), runs the base migrations, then the PR
  migrations on the same file, and fails if a table or column disappears or any table loses rows.
  It also calls `/api/ops/smoke` on the migrated DB.
- **Allowlists expire.** Every entry in `.audit-allowlist.json` and `.osv-allowlist.json` is
  `{ "reason": "...", "expires": "YYYY-MM-DD" }`. An expired entry stops suppressing its advisory,
  so the build fails again and the decision is revisited.
- **Semgrep suppressions are justified inline:** `// nosemgrep: <rule-id> -- <reason>`. A bare
  `nosemgrep` is not accepted in review. Exclusions live in `.semgrepignore`.
- **Coverage ratchet.** Thresholds live in `server/vitest.config.ts` and are only ever raised.
- **Build once.** A client build peaks near 1.7 GB, and the shared container runtime VM is 6 GiB, so concurrent builds
  were OOM-killed (exit 137, `Killed`). In `quality.yml` the `quality-build` job builds once and `bundle-size`
  and `e2e` download the artifact (`server/public`, `server/dist`) instead of rebuilding. Do not add a job that
  runs its own client build; depend on `quality-build`. Size runner pools by memory (about 1.7 GB per concurrent
  build plus about 3 GB VM baseline), not by job count.
- **Bundle budget.** Intended growth: run `pnpm run bundle-size:update` and commit the new
  `.bundle-size-baseline.json` with a reason in the PR body.
- **axe baseline.** Known violations are listed per page in `e2e/a11y-baseline.json` with a
  reason; anything new and critical or serious fails.
- **Unicode scan.** Every tracked text file: no em dash or en dash. Code and config files
  additionally: no curly quotes, NBSP, zero-width characters, BOM, figure dash or minus sign.
  Intentional occurrences are allowlisted per file in the script.

### 2.1 Weekly full-tree lint sweep

A pull request lints only what it changes, so a linter upgrade or a new rule can leave older files
failing unnoticed until someone touches them. A repo with a lint step **should** also run the
template `lint-sweep.yml` (templates/overlay): once a week it lints the whole tree (the overlay's UI
and script lint over the configured paths, plus the repo's own full-tree command from the
parameters row "Lint sweep command"), and while the sweep fails it keeps exactly one open issue
labelled `lint-sweep`: it opens it on the first failure, updates the same issue on every later
failure, never opens a second, and closes it on the first green sweep. Its action is SHA-pinned and
it runs on `CORE_CI_RUNNER` like the other templates.

- Prevents: rot that only shows up when an unrelated pull request touches an old file and fails for
  a reason its author did not cause.
- Acceptance (overlay-ci): `lint-sweep.yml` is installed and its `sweep` job's latest default-branch
  run succeeded.

## 3. Conventional commits and semver

- PR titles and commits follow Conventional Commits with the types `feat fix chore ci docs refactor
  perf test style build revert` (same list in `checks.yml` and `commitlint.config.mjs`).
- Squash merges use the PR title as the commit subject, so `pr-title` is the check that matters for
  versioning.
- The deploy computes the version from the commit subjects since the last `vX.Y.Z` tag:
  `type!:` or a `BREAKING CHANGE` footer is major, `feat` is minor, anything else is patch.
  Commits that did not deploy are still counted by the next deploy. Do not hand-bump versions.
- **Monorepo exception.** A repo that ships several apps with their own release cadence may keep one version per app, bumped forward in the PR and matching the top heading of that app's changelog, with a CI check for both. It records this as an exception, and the in-app What's new is then built from those changelogs, not from commit subjects, because most commits are neither `feat`, `fix` nor `perf`.

### In-app changelog

The hub's What's new popover and `/changelog` page are generated at build time from git history
(`scripts/changelog.mjs`, called from the client Vite config), one group per released `vX.Y.Z` tag
plus the build being made. Only `feat`, `fix` and `perf` commits appear. PR numbers, hashes, links,
scopes and dashes are stripped so developer information never reaches users. A PR sets plain-language
wording with `Changelog:` lines in its body (one per change); without one, the PR title is used.
The page is open to everyone who can open the hub and has no API or permission.

## 4. Dependabot policy

- `.github/dependabot.yml` covers `npm` (every workspace directory) and `github-actions`, weekly
  (Monday 06:00 America/New_York), at most 2 open npm PRs and 5 open
  `github-actions` PRs. The npm cap makes a Monday batch of majors trickle in instead of landing
  about 20 CI jobs per PR on the self-hosted runner pool at once.
- Minor and patch updates are grouped into one PR per ecosystem; majors open one PR per dependency
  across all directories (an `npm-major` group with `group-by: dependency-name`), never one per
  directory.
- `rebase-strategy: disabled`. Majors wait for the weekly review, and auto-rebasing them on every
  push to `main` reran the full CI each time and flooded the self-hosted runner queue. Comment
  `@dependabot rebase` to refresh a PR on demand (the weekly review does this before merging).
- Commit prefixes keep the PR title lint and semver meaningful: `fix(deps)` for production
  dependencies, `chore(deps-dev)` for dev dependencies, `ci(deps)` for actions.
- Pins that must not move (for example `@types/node` above the runtime major) are `ignore`d.
- Minor and patch PRs auto-merge once green. **Major bumps (and 0.x minor bumps, which semver
  treats as breaking) never auto-merge**; they wait for the weekly major-update review (Friday
  22:00 ET), which evaluates them for breakage and merges the clean ones.
- Dependabot security updates and alerts are a repo setting (Settings > Code security); they are
  free and should be on for every repo.

## 5. Auto-merge

`automerge.yml` is the merge gate. Policy: full auto-merge. Every non-draft PR into `main`,
Dependabot included, is merged by the repo's declared merge method
([PR Review and Merge](pr-review-and-merge.md) rule 1.5; squash unless the repo declares rebase or
a merge queue) once all checks pass. The `--squash` flags below stand for the declared method.

- **Triggers:** `workflow_run` (completed) of every CI workflow, plus `pull_request_target`
  (opened, synchronize, reopened, ready_for_review, labeled, unlabeled). Each run re-evaluates all
  open PRs, so a run dropped by the concurrency group loses nothing. "Every CI workflow" includes
  the core's: `workflows:` lists `core-ci` (and `lint-sweep` when the gate requires its check)
  next to the repo's own workflow names. A gate that lists only its own workflows never runs when
  a core-ci job is the last check to finish, so a green PR waits until something reruns it.
  `core-ci.py workflow-lint` warns on a `workflow_run` trigger that lists workflows but not
  `core-ci`. **Acceptance (test):** the warning fires on `workflows: [CI]` and is quiet on
  `workflows: [CI, core-ci]`. Example:

  ```yaml
  on:
    workflow_run:
      workflows: [CI, core-ci]
      types: [completed]
    pull_request_target:
      types: [opened, synchronize, reopened, ready_for_review, labeled, unlabeled]
  env:
    REQUIRED_CHECKS: >-
      lint-and-build core-secret-scan core-workflow-lint core-ascii core-pr-title core-commitlint
      core-attribution core-identity core-changelog core-python core-node-pin core-kit-peers
  ```
- **Gate:** every check run on the head SHA concluded `success`, `skipped` or `neutral`, nothing is
  still running, and every name in `REQUIRED_CHECKS` is present. The PR must be mergeable and its
  head must not have moved since the checks were read (the merge call passes `sha`).
- **Quiet period, one merge per pass:** a lane that merges on a schedule merges only a head it saw
  unchanged on its previous pass, and merges at most one PR per pass. A head that moved restarts its
  wait. Prevents: merging a head someone is still pushing to, and a burst of merges that each
  rebuilds on a main the next one has not seen. **Acceptance (test):** a PR first seen this pass is
  not merged; two ready PRs merge on two passes.
- **Opt out:** the `no-automerge` label. Remove it to let the PR merge.
- **Security:** the workflow never checks out or runs PR code; it only reads PR metadata and check
  results through the API, so the privileged token of `workflow_run` / `pull_request_target` is
  never exposed to PR content.
- **Workflow-file PRs and the merge token:** `GITHUB_TOKEN` cannot merge a PR that changes
  `.github/workflows/` (this includes Dependabot github-actions PRs). The merge step therefore
  uses `GH_TOKEN="${MERGE_TOKEN}"` on the merge call only, where `MERGE_TOKEN` is
  `${{ secrets.AUTOMERGE_TOKEN || github.token }}`. Reads, branch deletes and dispatches keep
  `github.token`. With no secret set, behavior is unchanged and those PRs still need `gh pr merge
  --squash --admin --delete-branch`. See the AUTOMERGE_TOKEN section below.
- **Deploy dispatch:** a merge made with `GITHUB_TOKEN` does not fire push workflows. After a merge
  whose diff touches the deploy paths, the auto-merge workflow dispatches `deploy.yml` on `main`
  itself (`workflow_dispatch` is allowed). A merge made with `AUTOMERGE_TOKEN` is attributed to a
  user, so it does fire the push trigger; the hub's workflow then skips its own dispatch when the
  secret is set. A human merge fires the normal push trigger instead and
  the auto-merge workflow does nothing for it, so there is never a double deploy.
- **Production approval:** the merge policy is full auto-merge. Production deploy actions taken by
  hand (manual dispatch, rollback, app stop/start, restores) may need the owner's explicit approval.
  The hub's `deploy.yml` has no GitHub environment approval gate today; if one is added, it is
  never bypassed.

Repos with no deploy (docs-only, such as this one) use a simpler auto-merge: same gate and label,
no Dependabot major logic beyond skipping majors, no deploy dispatch.

### Bundled model assets and native runtimes

A feature that needs a model file (the hub's meaning search uses an int8 embedding model, 105 MB) follows these rules:

- The file is **not committed**. A fetch script (`scripts/fetch-embedding-model.mjs`) downloads it from a **pinned
  revision** and verifies a **SHA-256** per file, so a changed or tampered download fails the build. CI runs it before
  the tests (`ci.yml`, `quality.yml` coverage), and `build-deploy-package.sh` runs it and ships the files in `models/`.
- A native runtime (`onnxruntime-node`) ships every platform's binary inside its npm package. The deploy package keeps
  only the one the App Service runs (linux-x64) and the package script **runs the packaged model once in a
  linux/amd64 container**, as it does for `better-sqlite3`. pnpm 12 needs the runtime's install script listed in
  `pnpm-workspace.yaml` `allowBuilds` (set to `false` when it only fetches optional GPU libraries).
- The feature is **off by default** behind an App Service setting (`DOCS_SEMANTIC=1`) so merging changes nothing until it
  is switched on, and it loads the model at startup and keeps it resident. **Always On must be enabled** on the App
  Service, or the cloud host unloads the app when idle and the next request is cold.
- Check memory before enabling: admin System Health shows the container usage, peak and headroom. The hub runs on
  Linux **Basic B3** (4 vCPU, 7 GB); the model adds roughly 100 to 250 MB and about 475 MB peak while embedding.

## 6. Deploy

`deploy.yml` (the app platform, publish-profile credential):

1. **Triggers:** push to `main` on app paths only (`client/**`, `server/**`, `shared/**`,
   `package.json`, `pnpm-lock.yaml`, `pnpm-workspace.yaml`, `scripts/build-deploy-package.sh`,
   `.github/workflows/deploy.yml`), or `workflow_dispatch`. Docs- and CI-only merges do not deploy.
   The same path list lives in `automerge.yml` as `DEPLOY_PATHS_RE`; keep them in lockstep.
2. **Serialized:** concurrency group `deploy-production`, `cancel-in-progress: false`, shared with
   `rollback.yml`. A static-host deploy follows the same rule: serialised, never cancelled in flight. Overlapping deploys are what corrupted the DB (see
   [Data Safety](data-safety-sqlite.md)).
3. **Re-runs CI** (`uses: ./.github/workflows/ci.yml`) on the exact commit. No deploy without green.
4. **Computes the version** (section 3), builds, stamps `version` and `buildSha` into the deployed
   `package.json`, and builds `app.zip` with the same script the CI smoke used.
5. **Pre-deploy backup** (best effort): `POST /api/ops/predeploy-backup` with
   `Authorization: Bearer $DEPLOY_HOOK_SECRET`. The running app (the lock holder) backs itself up.
   The DB is never opened via Kudu.
6. **Deploys** with `azure/webapps-deploy`.
7. **Health gate:** polls `/health` (up to `HEALTH_TIMEOUT_SEC`, 600) until it returns 200 with
   status `ok`, the new version and the deployed commit SHA, on three polls in a row and from a process newer than the one the deploy replaced (so a stale instance that still answers cannot pass). A static host with no health route publishes a version file with the SHA and runs a smoke test against it. 503 means starting, waiting for the DB
   lock, or a failed integrity check.
8. **Smoke:** `GET /api/ops/smoke` (DB `quick_check`, core row counts, RBAC catalog, scheduler).
   A failure fails the run before tagging.
9. **Tags and releases:** pushes `vX.Y.Z` and creates a GitHub Release with notes grouped Features /
   Fixes / Other from the commit subjects since the previous tag. Only after steps 7 and 8 pass.

**Branch deploys never hold the deploy token.** A deploy of branch code (a preview or dev tier)
runs in two stages. The build stage runs the branch's own workflow with no environment and no
secrets and uploads the artifact. A `workflow_run` stage, which always runs `main`'s copy of the
workflow, checks the branch name against the deploy pattern (one consumer parameter,
[PR Review and Merge](pr-review-and-merge.md) section 2), then takes the environment and deploys the
artifact. Prevents: a branch that edits its own workflow reading the deploy token.
**Acceptance (review):** the build job declares no `environment` and reads no secret; the deploy job
is triggered only by `workflow_run`.

**Ringed releases for software that runs on devices.** An agent or app shipped to managed devices
releases once per version bump from `main`, never from a branch. Signing uses a federated identity,
never a stored key, and a dry run only signs. The release moves through rings (canary, early, broad)
with a hold between rings; a revoke ring withdraws a version, and the device refuses to install a
version older than the one it runs (anti-rollback). Registration of a device fails closed when its
identity cannot be verified. **Acceptance (test):** a version cannot reach the broad ring without
passing canary and early; a device offered an older version refuses it.

`/health` and `/api/ops/*` are excluded from platform-level auth. Every `/api/ops/*` route requires the Bearer
secret (timing-safe compare) and answers 403 when it is wrong or unset.

## 7. Rollback

`rollback.yml` (manual, input `vX.Y.Z`): checks out the tag, rebuilds it with that tag's own
packaging script, takes the pre-deploy backup, deploys, health-gates on the tag's version and SHA,
and runs the smoke check (skipped with a warning for tags older than the smoke endpoint). It shares
the `deploy-production` group and creates no tag and no release.

Rollback is safe only because **migrations are forward-only and additive**: older code ignores
unknown tables and columns. A newer `NOT NULL` column without a default would break older code's
inserts, which is why that pattern is banned. If the older code misbehaves, restore the pre-deploy
backup taken by the rollback run.

## 8. Off-site backup

`backup-offsite.yml` runs nightly (07:45 UTC, after the 02:15 ET app backup) and on demand. It
downloads a fresh verified backup from `GET /api/ops/backup-download`, re-checks it with
`sqlite3 PRAGMA quick_check`, encrypts it (`openssl enc -aes-256-cbc -pbkdf2 -iter 200000`) with
`BACKUP_ENCRYPTION_KEY`, verifies the round trip, deletes the plaintext and uploads only the
encrypted file and its `.sha256` as an artifact kept 14 days. The DB holds staff names and emails:
never upload or attach it unencrypted. Restore steps are in
[Data Safety](data-safety-sqlite.md#6-recovery-runbook).

## 9. Required secrets

| Secret | Where | Used by |
|---|---|---|
| `AZURE_WEBAPP_PUBLISH_PROFILE` | repo secret | `deploy.yml`, `rollback.yml` (the deploy credential; treat it like a password) |
| `DEPLOY_HOOK_SECRET` | repo secret and App Service app setting (same value) | pre-deploy backup, smoke, off-site backup download |
| `BACKUP_ENCRYPTION_KEY` | repo secret, plus a copy in the team password vault | `backup-offsite.yml` (without the vault copy the artifacts cannot be decrypted) |
| `AUTOMERGE_TOKEN` | repo secret (optional) | the merge call of `automerge.yml` only; see below |
| `GITHUB_TOKEN` | built in | auto-merge, tags, releases, gitleaks |

### AUTOMERGE_TOKEN

- **Why:** GitHub refuses a `GITHUB_TOKEN` merge of any PR that changes `.github/workflows/`.
  A personal access token with the workflow scope can merge them, so
  workflow PRs and Dependabot actions bumps stop needing an admin merge.
- **Scope:** one classic personal access token owned by the repo owner, with the `repo` and
  `workflow` scopes only. It is broader than a fine-grained token (it reaches every repo the owner
  can write to, not just the five that use it). Classic is chosen because the workflow permission
  then covers all five repos (the reference app, sibling tool, an app-store repo, this standards repo, the ops app) with one
  token and the annual review is a single step. No admin, org or user scopes.
- **Install:** run `<agent-home>/scripts/set-automerge-token.sh`. It asks for the token in a hidden
  dialog, stores it in the macOS login Keychain (service `the automerge-token keychain service`), validates
  it, sets the `AUTOMERGE_TOKEN` secret on every repo and writes the annual review date. The token is
  never typed in a terminal, printed, put in a file or pasted into chat.
- **Expiry and review:** the PAT is a never-expiring classic token. The owner accepted that risk.
  It is reviewed once a year, not rotated. It is stored only in the login Keychain item
  `the automerge-token keychain service` (account `the owner`) and never in files or chat. The review date is
  in `<agent-home>/recovery/automerge-token-rotate-after` (12 months out). At the review, confirm the
  scopes are still `repo` and `workflow`, that the token is still needed, and that no repo
  outside the five has been added. Revoking the PAT is the whole recovery.
- **Blast radius:** a leaked token can push and merge in those repos and edit their workflows, so
  treat it like a deploy credential. Revoking the PAT is the whole recovery: the workflows fall
  back to `GITHUB_TOKEN` automatically.
- **Never exposed to PR code:** only the merge step reads the secret, and `automerge.yml` never
  checks out or runs PR content. Do not pass it to any job that runs PR-controlled code, never
  echo it, and never use it in `pull_request` workflows. `pull_request_target` does not see
  Actions secrets on Dependabot PRs; the `workflow_run` trigger does, so it covers them.

No other long-lived credentials live in GitHub. Automation uses certificate-based or
managed-identity auth, never interactive credentials. The rules for choosing an identity, moving,
rotating and scanning secrets are in [Secrets and Credentials](secrets-and-credentials.md), and the
PR flow (staging, review answers, head-pinned merges) is in [PR Review and Merge](pr-review-and-merge.md).

## 10. Applying this to a new repo

Minimum for any repo, including docs-only: SHA-pinned actions, Dependabot for `github-actions`,
actionlint, gitleaks, the Unicode scan, the PR title lint, the attribution guard, and an auto-merge workflow that honors
`no-automerge`. Add the language checks (typecheck, lint, tests, audit, OSV, Semgrep) for code repos
and the deploy, health gate, rollback and backup pieces for anything that runs in production.

### 10.1 PowerShell repos

PowerShell repos (WPF tools, the device-management system packages, automation) add the PowerShell CI set on top of the
minimum. Reference copies: the sibling sibling tool repo and the sibling app-store repo. Copy
these files unchanged except `ci/Policy.psd1` and the `EXCLUDE` list in `scripts/check-ascii.mjs`:

- `.github/workflows/powershell-ci.yml` with jobs `parse`, `xaml`, `psscriptanalyzer`,
  `standards`, `pester`, `ascii`, `actionlint`, `gitleaks`, with pwsh (GitHub-hosted until the
  repo gets a self-hosted runner).
  PSScriptAnalyzer and Pester are pinned by exact version (1.24.0, 5.7.1).
- `ci/Invoke-CI.ps1` (one entry point, locally and in CI: `pwsh ./ci/Invoke-CI.ps1 -Task All`) and
  `ci/Hub.CI.psm1` (static AST rules; nothing executes repo scripts).
- `PSScriptAnalyzerSettings.psd1`: all default rules at Error and Warning, plus
  `PSUseCompatibleSyntax` (5.1 and 7.4) and the credential rules. Errors fail anywhere; Warnings
  fail in files the PR changes. Pre-existing findings get a script-level
  `SuppressMessageAttribute` with a justification; never exclude a rule in the settings.
- Parse check: `[System.Management.Automation.Language.Parser]::ParseFile` on every tracked
  `.ps1`/`.psm1`/`.psd1`, vendor code included.
- XAML check: `.xaml` files and embedded XAML here-strings must be well-formed XML; documents
  assembled by concatenation (`$Head + $Resources + $Body`) are resolved and checked whole.
- Standards lint: no `Get-Credential` or `Read-Host -AsSecureString` outside GUI tools, no
  hardcoded secret literals, CMTrace logging (see the [CMTrace Logging Standard](cmtrace-logging.md); `Write-CMTraceLog`, or the deployment toolkit's `Open-ADTSession` /
  `Write-ADTLogEntry`) in automation.
- Pester 5 smoke tests (`tests/Standards.Tests.ps1`): every file parses, every script is classified,
  logging present, automation supports `-WhatIf` and sets exit codes, the device-management system CI discovery scripts
  (`*Discovery*.ps1`) output only booleans; `tests/fixtures/` proves each rule fires.
- `ci/Policy.psd1` classifies scripts (`Gui`, `Automation`, `PsadtDeployment`, `AppDetection`,
  `CIDiscovery`, `Data`, `Fixture`), lists vendor paths, and holds the `KnownGaps` tech-debt
  baseline. A test fails when a known gap is fixed, so the baseline only shrinks.
- `automerge.yml` `REQUIRED_CHECKS`: `parse xaml psscriptanalyzer standards pester ascii
  actionlint gitleaks pr-title attribution identity`.

## 11. Core consumption classes

The owner's rule for how a release of the shared core reaches an app. Every consumer is in one of
two classes, and the way it is registered with (`consumer.json` `mode`) decides which.

| Class | Who | How a release lands | How new kit parts are adopted |
|---|---|---|---|
| apply-at-once | the ops center (a local, single-operator app) and the agent home | the nightly applies every release at once, behind the ops center's own gate, with rollback; an ops center whose source is a repo with its own CI gate gets it as a pull request that merges as soon as that CI passes, never waiting for the owner | the ops center's own pull requests or commits |
| approval-gated | every other app: product repos, hubs, multi-module shells, vendored copies | a pull request per release (the `workflow` way's sync pull request, or the vendoring tool's pull request for `vendored`) that merges only after the owner approves it | planned pull requests the owner approves |

1. **Nothing is applied to an approval-gated app directly.** No direct push to its default branch,
   no merge of a sync or adoption pull request the owner did not approve, no tool that writes the
   app's files outside a pull request. The template `core-update.yml` (triggered by `workflow_dispatch`, with an App token from `CORE_APP_ID` or the `CORE_TOKEN` fallback) opens the sync pull request
   as a draft by default (`CORE_UPDATE_MERGE=approve`), so the repo's merge gate (section 5) does
   not merge it; the owner's approval is marking it ready. `CORE_UPDATE_MERGE=wait` or `gate` is
   the owner's standing approval for one repo, set by the owner only.
2. **The approval is one action and goes through the pull request.** The ops center's Core
   consumption panel ([Local Ops App](local-ops-app.md) section 19) is where the owner gives it;
   the action marks the pull request ready or merges it with the repo's declared method once its
   checks pass. It never writes to the app any other way.
3. **A gated ops center stays apply-at-once.** When the ops center's source is a repo with its own
   CI gate, the release is applied as a pull request to that repo: synced in an isolated worktree,
   the local gate run before and after, a branch pushed, the pull request opened, the repo's own
   checks on that head waited for, and the pull request merged at once pinned to that head. The
   owner is not waited for and the deploy checkout is never written directly. A failure or timeout
   closes the pull request, deletes the branch and leaves the pin unchanged (`CONSUMING.md`,
   `direct`).
4. **The nightly reports, it does not wait.** An open sync pull request on an approval-gated app
   is its normal state and is reported as awaiting approval; only failing checks on it are a
   problem.

**Acceptance (review):** every consumer in `consumer.json` maps to one class; the sync workflow of
an approval-gated repo opens a draft and merges nothing unless the owner set a standing approval;
no job pushes to an approval-gated app's default branch.
