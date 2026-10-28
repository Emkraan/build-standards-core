# Build Standards Core

Business-agnostic build standards, design tokens and CI checks shared across the accounts that
contribute to it. It holds no business names, hostnames, tenants or people. Each business keeps
its own overlay repo that pins a version of this one and adds only what is specific to it.

This repo is the one place every contributing account may update. Everything downstream is owned
by its own account and only ever reads from here.

> **Agent reading this repo for the first time:** not cloned yet? Run
> `gh repo clone OWNER/build-standards-core ~/GitHub/build-standards-core` (a permanent path), then
> follow [CONSUMING.md](CONSUMING.md) now. It sets up
> the nightly job (`python3 hermes/setup.py --ui OWNER/REPO`) that applies this standard to the
> Hermes desktop app (skills, plugins such as rtk and caveman, settings) and to every UI consumer
> repo, then verifies it. A repo with no Hermes agent reads CONSUMING.md sections 3 and 8 to 14.

`OWNER` in commands below is the GitHub account or organisation this repository lives in.

## Contents

- [Direction](#direction)
- [What lives here and what does not](#what-lives-here-and-what-does-not)
- [Layout](#layout)
- [The standards](#the-standards)
- [How the pieces fit](#how-the-pieces-fit)
- [Day one for a new account](#day-one-for-a-new-account)
- [Consuming the core](#consuming-the-core)
- [Keeping vendored copies intact (consumer side)](#keeping-vendored-copies-intact-consumer-side)
- [What an overlay may and may not do](#what-an-overlay-may-and-may-not-do)
- [Source of truth and explicit exceptions](#source-of-truth-and-explicit-exceptions)
- [Hermes: shared configuration and core skills](#hermes-shared-configuration-and-core-skills)
- [What may and may not be shared](#what-may-and-may-not-be-shared)
- [Contributing core skills](#contributing-core-skills)
- [Contributing back](#contributing-back)
- [Versioning and releases](#versioning-and-releases)
- [Checks](#checks)
- [Visual gate](#visual-gate)
- [Adding a new source repo](#adding-a-new-source-repo)
- [FAQ](#faq)

## Direction

This repo is the mandatory baseline for four things: UI design (tokens, the shell, the kit),
web frontend and backend practice, the CI workflows that proved themselves across builds, and
agent runtime practice. A repo either conforms or records its deviations; the core is not a
menu.

Five ways to take the core. Every consumer picks one per repo, recorded in the machine-local
`consumer.json`, and [CONSUMING.md](CONSUMING.md) walks an agent through each:

| Way | For | What lands |
|---|---|---|
| `workflow` | a product repo with its own CI: one pull request per release, merged only on the owner's approval and only when the overlay's checks pass | synced copies pinned to a release; a pull request per release |
| `ops-center` | a machine's ops center app and other local tools without CI: the sync applies at once, gated on the core's checks, with a rollback | synced copies applied directly; one log line per apply |
| `vendored` | a repo that must carry no record of the core: a scrubbed copy with the identity files removed | files only; release and source hash recorded on the machine, never in the repo |
| `pin-file` | a repo that records the core as one `KEY=<tag>` line (a deploy repo whose host syncs the pinned release) | a pull request that bumps the line; approval-gated |
| `agent-home` | the agent runtime on a machine: skills, settings, hooks, cron jobs, plugins | applied at once by the nightly job; one log line per apply |

Separately from the way, there are three channels a consumer can draw from: the overlay sync (synced
copies, pinned by `standards.lock`), the opt-in reusable workflow `core-ci-reusable.yml` (the CI checks
without a copy of the workflow), and the agent skills the nightly installs. The channels table is in
[CONSUMING.md](CONSUMING.md#the-three-channels).

`local` was the older name of `ops-center`; a config that still says it behaves the same, and
the nightly notes the rename once.

Two consumption classes. This is the owner's rule, and every way above falls in one class:

1. **Apply at once: the ops center.** A local, single-operator app takes every core release at
   once, nightly, behind its own gate and with rollback (the `ops-center` way). The agent home
   is applied the same way.
2. **Approval-gated: every other app.** Product repos, hubs, multi-module shells, pin-file repos and vendored
   copies never change without the owner's approval. Each new release arrives as a pull request
   (the `workflow` way's sync pull request, the vendoring tool's pull request for `vendored`, or the
   bump for `pin-file`),
   and adopting new kit parts in such an app happens through planned pull requests the owner
   approves. Nothing is applied to such an app directly: no direct push, no merge the owner did
   not approve. The repository variable `CORE_UPDATE_MERGE` defaults to `approve`; `wait` or
   `gate` is the owner's standing approval for one repo and only the owner sets it.

The ops center is the owner's approval desk. Its Core consumption panel
([standards/local-ops-app.md](standards/local-ops-app.md) section 19) shows, for every consumer
registered on the machine, the pinned release against the latest, the open sync pull request
and its CI, the core-status counts and adoption suggestions, plus this account's report items
waiting for a decision and the improvements other accounts contributed. Every approval is one
action and goes through the normal pull request path. The data comes from one file the nightly
writes on the machine, `~/.config/build-standards-core/consumption.json`, so every ops center
renders the same thing and an improvement one account contributes shows up as a suggestion in
every other ops center. [CONSUMING.md](CONSUMING.md) section 3 has the table of who does what
per class; the rules are `ci-cd-release.11` and `local-ops-app.19`.

Baseline first. A repo that predates the core adopts the baseline before it swaps anything
out: sync the overlay, keep every existing feature working, put thin adapters over the kit
parts so call sites do not move, and retire the hand-rolled parts last
([kit/MIGRATION.md](kit/MIGRATION.md) step 0; `standards/web-ui.md` 0.11 says what counts as
adoption).

Core-owned and consumer-owned paths. Inside an overlay every synced directory is core-owned:
the nightly pull request writes it and the consumer never edits it. `standards-local/` is the
one consumer-owned directory inside the overlay: parameters, exceptions and the repo's own
standards live there. Anything else a consumer writes for itself lives in the repo's own
tree, outside the synced directories, so no sync ever overwrites it.

The upward path. A build's agent does not open a pull request here. Each account keeps one
open issue labeled `consumer-report`, in the owner's private intake repository and never in this
public one, carrying its report and the nightly's candidate
findings; the owner approves items there, and the account that owns the change opens the core
pull request for the approved items
([CONTRIBUTING.md](CONTRIBUTING.md#reporting-from-a-consumer)).

The core names no build. Nothing shipped names a product, business, host or tenant; a build
contributes by role, not by name: a monorepo through the shared-package rule, an ops center
through the local ops app standard, an API service through the backend rules, a proven
practice through a workflow. What belongs to one build stays in that build.

## What lives here and what does not

| In the core | In an overlay |
|---|---|
| Rules that hold in any business: tokens, component behaviour, RBAC shape, CI gates, data safety, logging format | Brand accent value, identity provider and tenant, hosting platform, runner topology, notification channel |
| Parameters with a documented default and a place to set them | The values of those parameters |
| Checks that keep the core agnostic | Business-specific standards and the checks that enforce them |
| Worked examples written with neutral names | Real names, hostnames, ids, people |

If a rule only makes sense inside one business, it belongs in that business's overlay, not here.

## Layout

| Path | Holds |
|---|---|
| `standards/` | One topic per doc. This is what overlays consume |
| `templates/overlay/` | Starter for a business overlay: pin file, sync and update scripts, `core-status.py`, `core-ci.py`, `repo_checks.py`, `merge-pr.py`, the template workflows and the local parameters sheet |
| `tokens/` | `tokens.json` (the one token source), `build.py` and everything it generates (CSS, TS, Tailwind preset, WPF dictionaries, contrast report), plus the behavioural layer `hub-layer.css`. Synced into overlays as `tokens-core/` |
| `checks/` | Scripts that keep this repo agnostic and clean: sanitisation and consumer neutrality (full tree or `--diff`), ASCII, placeholders, links and anchors, authors, changelog, closing references, CSS variables, token names in the docs, kit comments, the rules registry, and `auto-release.py` |
| `lint/` | `ui_lint.py`, the static UI rules every consumer runs; synced into overlays as `lint-core/` |
| `kit/` | The shared React kit (shell, primitives, overlays, required chrome, chart theme), its gallery and tests; `kit/src/` syncs into overlays as `kit-core/` |
| `opscenter/` | `DESIGN.md`: the design of the locally hosted ops center app that applies the core at once (see `standards/local-ops-app.md`) |
| `claude/` | The opt-in coding-agent CLI layer the nightly can apply (`claude/README.md`, `tools.json`, `apply_claude.py`) |
| `skills/` | `core-example.md`, the worked example of a shareable skill |
| `tests/` | The unit tests for the checks, the overlay scripts, the nightly and the lints (`python3 -m unittest discover -s tests -p "test_*.py"`) |
| `.github/workflows/` | The core's own CI: `checks.yml` (job `ci`), `kit.yml`, `visual.yml`, `sweep.yml` (weekly full-tree checks), `release.yml` and `gallery-release.yml` (automatic releases), `automerge.yml`, and `core-ci-reusable.yml` (the opt-in reusable `core-ci` workflow consumers call) |
| `hermes/` | Shared practice for consumers that run the Hermes agent: `configurations.md` (settings and plugins that proved themselves), `token-efficiency.md` (where model spend goes and the setting that controls each part), `skills/core-*` (shared skills, the generated `core-practices` first), `tools.json` (adopt, adapt or reject per plugin or skill), `setup.py` (one-time consumer setup), `nightly.py` (the nightly job), `apply_setup.py`, `build_skills.py` and `sync_skills.py`. See [hermes/README.md](hermes/README.md) |
| `CHANGELOG.md` | One dated entry per change to any standard. Read it before bumping a pin |
| `CONTRIBUTING.md` | Rules for changing this repo |

## The standards

The docs are grouped the way they build on each other: foundations (tokens, type, motion), the
components built from them, the patterns that combine components, the app types that assemble
patterns, and the engineering practice that ships any of it. The scope column is the `applies_to`
value of the doc's registered rules (see the rules registry below).

| Group | Doc | Topic | Scope |
|---|---|---|---|
| Foundations | `standards/web-ui.md` sections 0 to 5, 14, 16, 17 | The rules, colour tokens, Tailwind preset, type, geometry, motion, the accent tokens, categorical hues, tone and selection | web |
| Foundations | `standards/wpf-design-system.md` sections 1 to 3, 5, 6 | The same DNA for WPF: colour, type, geometry, spacing and the hard rules | wpf |
| Components | `standards/web-ui.md` sections 7, 8, 18, and `kit/README.md` | Primitives, dialogs, toasts, tables, charts, the stat tile, all shipped in the kit | web |
| Components | `standards/wpf-design-system.md` section 4 | The XAML control kit | wpf |
| Patterns | `standards/web-ui.md` sections 6, 11, 13, 19 to 25 | Shell, mobile drawer, search palette, rail, announcements and feed, build card, undo and confirm, required chrome | web |
| Patterns | `standards/rbac.md` | Additive-union RBAC shape and the lockstep check | web |
| Patterns | `standards/live-actions.md` | Actions in operator UIs against eventually consistent backends | all |
| Patterns | `standards/identity-and-people-data.md` | Directory as source of truth and the single roster | all (no rules yet) |
| Patterns | `standards/notifications.md` | Message format and channel rules | all (no rules yet) |
| App types | `standards/web-build.md` | Stack, layout, API envelope, auth, RBAC wiring and the verification gate for first-party web apps | web (no rules yet) |
| App types | `standards/web-shell.md` | Several tools on one origin: registry generated from manifests, per-module CSS scope, storage and accent, safe return target, home as the hub | web |
| App types | `standards/web-api-runtime.md` | Node and Express APIs behind a gateway: group caching, directory token, CORS max age and origin guard, Server-Timing, request log, telemetry, the shared runtime package | web |
| App types | `standards/web-client-runtime.md` | Single page apps with an OIDC library: one auth boot, renewal without iframes, the API client, lazy bundles, the shared client package, the live feed strip | web |
| App types | `standards/local-ops-app.md` | Locally hosted operations apps: contract, cost-gated analyzer, loopback server | local-ops |
| App types | `standards/web-ui.md` sections 10, 12, 21 | WPF translation, per-app accent and the plain-CSS port, system health | web |
| App types | `standards/wpf-powershell-gui.md` | Desktop GUI tools: encoding, runspaces, logging, modules, launching | wpf |
| Engineering | `standards/ci-cd-release.md` | Required checks, auto-merge, dependency updates, deploy, rollback, releases, secrets | all |
| Engineering | `standards/data-safety-sqlite.md` | Database safety rules and the recovery runbook | web |
| Engineering | `standards/scripting-powershell.md` | Auth order, trial modes, errors, exit codes, naming, 5.1 and 7, idempotency, endpoint scripts, runbook runtimes | powershell |
| Engineering | `standards/scripting-python.md` | Interpreter floor, stdlib first, secrets out of argv, atomic writes, run locks, test isolation, ruff | python |
| Engineering | `standards/secrets-and-credentials.md` | Identity before secret, least privilege, federation, deploy keys, moving and rotating secrets, secret scanning, broad grants | all |
| Engineering | `standards/automation-safety.md` | Own work only, dry runs, synthetic tests, re-verify before acting, stable work items, idempotent retries, human gates | all |
| Engineering | `standards/pr-review-and-merge.md` | Staging by name, changelog per change, head-pinned merges, answering review, triage markers, policy holds versus problems | all |
| Engineering | `standards/docs-and-changelog.md` | Done means documented, one docs home and changelog per thing, coverage audits | all |
| Engineering | `standards/iac-governance.md` | Plan gates, destroy guards, owner-applied roots, state backends, drift, change freezes | iac |
| Engineering | `standards/cmtrace-logging.md` | Log line format for device-management tooling | powershell (no rules yet) |
| Engineering | `standards/hermes.md` | What an agent runtime may and may not share (see [Hermes](#hermes-shared-configuration-and-core-skills)) | all (no rules yet) |

Each doc has numbered sections so links stay stable, and each rule carries an acceptance line
saying how it is checked. The engineering practice docs open with a section 1 of numbered rules,
each with the failure it prevents and its acceptance line, and end with a checklist.

**Rules registry.** `standards/rules.json` lists every enforceable rule once: a stable id, the doc
and section an exception names, the statement, the acceptance line and how a consumer proves it
(`lint`, `core-ci`, `overlay-ci`, `test` or `review`), and `applies_to`, the stacks it covers (`web`,
`wpf`, `local-ops`, `powershell`, `python`, `iac`, or `all`). The check kind is one of `lint`, `core-ci`,
`overlay-ci`, `repo-check` (a static check in `repo_checks.py`, RC001 to RC022), `test` or `review`.
`checks/check-rules.py` keeps it in step with the docs and the UI lint, and consumers diff it between
releases to raise new and changed rules. What each status means (pass, proved, attested, waived,
not_applicable, excepted, unverified, fail) and how a consumer records a proof is in
[CONSUMING.md](CONSUMING.md#8-rule-status-proofs-and-the-repo-checks).
Docs without registered rules are listed by the check until they have them. `opscenter/applicability.json`
is the published list of rule ids that apply to an ops center; `check-rules.py` fails when an id in it is not
in the registry. A consumer lists its
stacks in the `Stacks` row of `standards-local/parameters.md`, and `core-status.py` then leaves out the
rules for stacks it does not have. With the row empty every rule is reported.

## How the pieces fit

```text
  contributing account A ----\
  contributing account B -----+--> PR --> build-standards-core (this repo, main)
  contributing account C ----/                       |
                                                     | tagged release
                                                     v
                         +---------------------------+---------------------------+
                         |                           |                           |
                  overlay repo (A)            overlay repo (B)            overlay repo (C)
                  pins a core tag             pins a core tag             pins a core tag
                  + local parameters          + local parameters          + local parameters
                         |                           |                           |
                         v                           v                           v
                  A's apps and docs           B's apps and docs           C's apps and docs
```

Changes flow down by pinned, reviewed pull requests. Improvements flow up through the report path
(Direction, "The upward path") and land here by pull request. Nothing flows sideways, and no overlay can
change another overlay.

## Day one for a new account

For an account that owns its own repos (a different GitHub owner than the core). Do these in order.

1. **No access to request.** The core is public: anyone can read it, with no invitation, token or key.
   Check it: `git ls-remote --tags https://github.com/OWNER/build-standards-core.git` lists the releases.
2. **Optional: sign in to `gh`.** The scripts use `gh` when it is installed and signed in, and plain
   `git` over HTTPS otherwise, so a machine or CI job without an account works the same.
3. **Name the core.** The lock file never names it. Export `CORE_REPO=OWNER/build-standards-core` on a
   machine, and set the repository variable `CORE_REPO` in CI.
4. **Create your overlay.** In your own repo, copy `templates/overlay/` as described in step 1 of
   "Consuming the core", set `standards-local/parameters.md`, and run `python3 scripts/sync-core.py latest`.
5. **Keep the offline check.** The template `core-drift.yml` needs no secret and no access to the core,
   so it works for any owner. Nothing to configure.
6. **Mount the required chrome.** Work through section 25 of `standards/web-ui.md` for every app with a
   sidebar. The build card's changelog must be generated in CI, not at upload time.
7. **Open a pull request** for the overlay and let its checks pass before merging. Require `core-checks`
   in the merge gate, then follow [CONSUMING.md](CONSUMING.md#12-the-update-flow-for-an-account-that-only-has-the-public-docs)
   to keep the pin current.

| Symptom | Cause | Fix |
|---|---|---|
| `Could not read OWNER/build-standards-core at <ref>` | the ref does not exist, `CORE_REPO` is unset or wrong, or no route to github.com | check the tag and `CORE_REPO`, steps 1 and 3 |
| drift check says `DRIFT` | someone edited `standards-core/` by hand | rerun `sync-core.py` |
| `DRIFT: content hash ... does not match the lock` | the synced copies were edited, or the lock is stale | rerun `sync-core.py` and commit both |

## Consuming the core

Which way a repo consumes the core (`workflow`, `ops-center`, `vendored`, `pin-file`, `agent-home`) is in
[Direction](#direction), and [CONSUMING.md](CONSUMING.md) is the agent-side procedure for
each way. What follows is the `workflow` way in full: the overlay, its pinned pull requests
and the CI that keeps a repo current.

Do this once per business, in that business's own repo.

### 1. Copy the template

```bash
git clone https://github.com/OWNER/build-standards-core.git ~/scratch/core    # public, no account needed
cp -R ~/scratch/core/templates/overlay/. <your-overlay-repo>/
```

Any scratch directory works. The result in your repo is:

| Path | Purpose |
|---|---|
| `standards.lock` | The pinned ref, commit and content hash. It never names the core's repo or owner; scripts read the source from `CORE_REPO` or the machine-local `consumer.json` (`core_repo`, written by `hermes/setup.py`) |
| `standards-core/` | Generated copy of the core `standards/`. Never edit by hand |
| `standards-local/` | Your business-specific standards and parameter values |
| `scripts/sync-core.py` | Refreshes `standards-core/` and rewrites the pin |
| `scripts/check-core-sync.py` | Fails if the synced copies differ from the lock; `--latest` reports newer releases |
| `scripts/update-core.py` | Moves the overlay to the newest release |
| `scripts/check-exceptions.py` | Validates `standards-local/exceptions.md` and the `core-exception` markers |
| `targets.map` (optional) | Extra files that must equal a synced copy |
| `.github/workflows/core-update.yml` | Opens a pull request on a new release and leaves it for the owner's approval (`CORE_UPDATE_MERGE=approve`, the default); `wait` or `gate` is the owner's standing approval for one repo |
| `.github/workflows/core-drift.yml` | Runs the offline drift check on pull requests and weekly |
| `.github/workflows/lint-sweep.yml` | Weekly full-tree lint; keeps one issue open while it fails (ci-cd-release.md 2.1) |
| `.github/workflows/core-ci.yml` | The CI half of the standard: secret scan, workflow lint, ASCII, PR title, commitlint, attribution, identity, changelog, Python floor and ruff, PowerShell parse and edition syntax, Node pin (templates/overlay/README.md "CI workflow") |
| `scripts/repo_checks.py` | Static checks RC001 to RC022 that `core-status.py` runs for every `repo-check` rule |
| `scripts/core-status.py`, `scripts/core-ci.py`, `scripts/merge-pr.py` | The status report, the checks behind `core-ci.yml` and the noreply-author merge wrapper |
| `standards-local/proofs.json` | How the repo proves the rules `core-status.py` cannot see (see "Source of truth and explicit exceptions") |
| `standards-local/ui-lint.json` | Which paths the UI lint reads, its token files and `data_palettes` |

The scripts resolve paths from their own location, so the overlay can sit at a repo root or in a
subfolder (for example `standards-overlay/`). If you use a subfolder, move `.github/workflows/core-drift.yml`
to the repo's root `.github/workflows/` and add `working-directory` or adjust the script path.

### 2. Fill in the parameters

Edit `standards-local/parameters.md`. At minimum set the brand accent, identity provider, hosting
platform, runner topology and notification channel. Keep secrets, hostnames and tenant ids out of
any repo that is shared.

### 3. Pin and sync

```bash
git checkout -b chore/sync-core
python3 scripts/sync-core.py            # tracks the ref in standards.lock
python3 scripts/sync-core.py vX.Y.Z     # or pin an explicit release tag
python3 scripts/sync-core.py latest     # or the newest release
git add standards.lock standards-core tokens-core lint-core kit-core scripts
python3 scripts/check-core-sync.py       # confirm the copy matches the pin
```

The script needs `git` and Python 3.9 or newer (the floor is the macOS system python, and core CI runs
every script on 3.9). It reads the core through `gh` when that is signed in and over anonymous HTTPS
otherwise, from the repository named by `CORE_REPO`. It copies `standards/`,
`tokens/`, `lint/` and `kit/src/` into `standards-core/`, `tokens-core/`, `lint-core/` and
`kit-core/`, writes the kit's release notes generator to `scripts/gen-changelog.mjs`, refreshes the
overlay scripts, resolves the ref to a commit, and rewrites `standards.lock` with that commit, so a
pin is always an exact commit and never a moving branch. When a release changes the sync tooling
itself, the sync hands over to the new copy in the same run. Overlays on v0.11.0 or older lack the
handover, so run the first sync past it twice.

### 4. Review as a pull request

Open a pull request containing the `standards-core/` diff and the new `standards.lock`. Read the
core `CHANGELOG.md` entries since your old pin and list any rule your apps now violate. Land the
standards first and the code fixes after, so the gap is visible and tracked.

### 5. Let CI check the pin

The template `core-drift.yml` is an offline check and needs no secret, no `gh` and no access to the
core. `sync-core.py` writes a hash of `standards-core/` and `tokens-core/` into `standards.lock`
(`content_sha256`), and `check-core-sync.py` recomputes it. CI fails when someone edits the synced copies
by hand or they no longer match the lock. It does not prove the lock names a real release; `sync-core.py`
does that when you run it, because it must read the core. Syncing is a developer action that reads the
core over HTTPS or through `gh`. A CI job that only checks drift never needs access to the core.

Put the workflow in the repo's root `.github/workflows/`. If the overlay is in a subfolder, change the
script path in the workflow. `python3 scripts/check-core-sync.py --remote` additionally compares the copies
with the core itself and is meant for a developer machine.

An older `standards.lock` without `content_sha256` still passes with a notice; run `sync-core.py` once.

#### CI that builds the app

The drift check above needs nothing. A CI job that also **builds** the app needs the synced copies,
and a consumer that keeps them out of its own repo (a mirror, a backup, a monorepo that ignores them)
restores them in CI. The core is public, so the job checks it out with no key, token or secret. The
pinned ref comes from `standards.lock`, and `fetch-depth: 0` keeps the tags the pin names:

```yaml
- uses: actions/checkout@v5
- name: Pinned core ref
  id: core
  run: echo "ref=$(sed -n 's/^ref=//p' standards.lock)" >> "$GITHUB_OUTPUT"
- uses: actions/checkout@v5
  with:
    repository: OWNER/build-standards-core
    ref: ${{ steps.core.outputs.ref }}
    fetch-depth: 0
    path: .core
- name: Restore the core copies from the pin
  run: |
    mkdir -p scripts
    cp "$GITHUB_WORKSPACE"/.core/templates/overlay/scripts/*.py scripts/
    CORE_CHECKOUT="$GITHUB_WORKSPACE/.core" python3 scripts/sync-core.py "${{ steps.core.outputs.ref }}"
    python3 scripts/check-core-sync.py
```

Run it from the overlay folder (`working-directory`) when the app is not at the repo root, and ignore
`.core/` in `.gitignore`. `core sync: clean` means the copies match the pin's content hash.

### 6. Keep it current

Run `python3 scripts/check-core-sync.py --latest` on a developer machine. It prints
`pinned vX, latest vY, run sync-core.py vY` (exit 3) when you are behind, and needs no account or secret.

**Upgrading.** `python3 scripts/sync-core.py latest` (or an explicit tag) on a branch, then commit
`standards.lock`, the synced copies (`standards-core/`, `tokens-core/`, `lint-core/`, `kit-core/`) and
the refreshed core template workflows together and open a pull request. The sync refreshes only the
template workflows the repo has (`core-ci.yml`, `core-drift.yml`, `core-update.yml`, `lint-sweep.yml`),
keeps the `OVERLAY` value, `core-drift.yml`'s overlay path prefix and every line marked
`# core-sync: keep`, and prints the old -> new required-check names when `core-ci.yml`'s jobs change. Read the core
`CHANGELOG.md` entries since the old pin. A pin that is many releases behind is a finding, not a state to
leave alone. To automate this, see "Staying in lockstep" below.

#### Staying in lockstep

The core is the single source of truth and changes flow one way: core to consumers. To change a rule,
token or hub stylesheet, open a pull request against the core, tag a release, and let consumers pick it up.
Never edit `standards-core/`, `tokens-core/` or any file listed in `targets.map` in a consumer.

1. **Generated copies inside your code.** If a UI package must carry a core file (for example the token
   stylesheet), list it in `targets.map` in the overlay root, one `copy path = destination` per line, both
   relative to the overlay root. `sync-core.py` writes the destination and `check-core-sync.py` fails CI if
   it differs from the synced copy.
2. **Updater.** `scripts/update-core.py` moves the overlay to the newest release and prints the tag only
   when something changed. The template `.github/workflows/core-update.yml`, dispatched by the repo's scheduler, opens a pull
   request that waits for the owner's approval (Direction, "Two consumption classes"). Only where the
   owner set a standing approval for the repo does it merge on its own: `CORE_UPDATE_MERGE=wait` waits
   for every check on the head commit to pass and then merges that commit, so a red one never lands, and
   `CORE_UPDATE_MERGE=gate` leaves the merge to the repo's own merge gate. It never turns on GitHub's auto-merge, which merges at once on a
   repo with no required checks. It runs on `workflow_dispatch` (the consumer's own scheduler dispatches it; a cron is optional) and
   needs the repository variable `CORE_REPO` (`OWNER/build-standards-core`) and one token with contents,
   pull-requests and workflows write on the consumer: a GitHub App
   (repository variable `CORE_APP_ID`, secret `CORE_APP_PRIVATE_KEY`) or, without an App, the secret
   `CORE_TOKEN`. The core is public, so reading it needs no credential. Require the `core-ci.yml` jobs
   in the merge gate (`scripts/core-ci.py required-checks`, templates/overlay/README.md "Required
   checks").
3. **Local alternative.** Where a repo secret is not wanted, run the update from a scheduled job on a
   machine where `gh` is signed in as an account that can open pull requests on the repo, and open the
   pull request from there. A repo
   with no remote CI has no pull request gate, so the job must be the gate. The pattern that holds up:
   - Test the new release against the **committed** code in a throwaway copy (`git archive HEAD`), never
     the working tree, so uncommitted work never decides the verdict.
   - Run the copy's gate on the **current** pin first. If it already fails, the update is held and the
     failure is reported as the consumer's, never blamed on the release.
   - Then sync the copy and run everything the build runs: drift, exceptions, UI lint, typecheck and a
     build into a scratch folder. Typecheck with `tsc -p <project> --noEmit`, not `tsc -b`, when the
     copy links the real `node_modules`: build mode writes its build info there and can make the real
     build skip its typecheck.
   - Apply to the real tree only when its gate passes before and after the sync, roll back by syncing
     the old pin otherwise, and commit the pin, the copies and the overlay scripts by name.
   - CI without `gh`: check the core out over HTTPS and pass it as `CORE_CHECKOUT`, step by step in
     "CI that builds the app" under step 5.
   - Raise one work item per distinct set of problems, keyed on that set, so a dismissed item stays
     dismissed until something changes, and close it on the first clean run. Treat an unreachable
     GitHub as a problem only after several runs in a row.
4. **CI is a check, not the updater.** The offline drift check only proves the copies match the lock. Keep
   the updater running so the pin never ages.
5. **Status for tooling.** `python3 scripts/core-status.py --latest --json` reports the pin, each
   registered rule as pass, proved, attested, waived, not_applicable, excepted, fail or unverified, exceptions expiring within 30 days, and the
   rules that are new or changed in the newest release. Rules for stacks the overlay does not declare
   in the `Stacks` parameter are left out and listed under `out_of_scope`; a sheet with no `Stacks` row is a
   problem, and `--require-lint-config` fails on it. An `overlay-ci` rule passes or fails from its
   `core-ci.yml` job (`--ci` reads the latest default-branch run, `--ci-results FILE` a saved result) and
   fails when that workflow or job is not installed. A nightly job turns the report into work items
   before the pin moves. It never changes files.
6. **Mirrors and backups.** The synced copies are reproducible from `standards.lock`. A backup or mirror
   of a consumer should leave them out and restore with `sync-core.py <pinned ref>`, so it carries only
   the consumer's own code. Its CI restores them as in "CI that builds the app" under step 5, and its
   recovery runbook restores them with `gh` before the first build. Secret scanners (gitleaks `generic-api-key`) read every `x:Key` in the WPF
   token dictionaries as a key, so a repo that does carry `tokens-core/wpf/` needs a path allowlist for it.

#### What is and is not shared

Shared: standards text, the token and hub stylesheets, the check scripts, the overlay scripts and the
React kit (`kit/`). A React app imports the shell, primitives, overlays and required chrome from
`kit-core/` instead of rebuilding them, so every app gets the same behaviour and the same fixes (see
`kit/README.md`). Apps on another stack build against the required-chrome table in
`standards/web-ui.md` section 25 and use the kit gallery as the reference. Business code, data and
routing stay in each app.

#### Vendoring into a consumer that carries no record of the core

Some consumers must not reference the core at all: no lock file, no drift workflow, no repo name,
no core package name and no core docs or lint in their tree. For those, vendor instead of overlaying:

1. **Commit the kit and token sheets as plain package source.** The kit source, `tokens.css` and
   `hub-layer.css` (and `layers.css`) live in a normal workspace package of the consumer's monorepo
   (for example `packages/ui/src`), under the consumer's own package name, and every app imports
   that package. The optional entries whose peers the consumer does not install (`graph/`,
   `api-reference/` and the chart entry `charts/`) may be left out: the kit root never imports them.
   Leave them out as whole folders and record which in the tool, so the package still typechecks
   and the content hash (web-ui.md 0.11) is taken over the release as published, not the subset.
2. **Keep the pin and the tooling outside the consumer.** A local tool on a machine with access to
   the core owns the pin, the drift check and the upgrade. It archives a release tag, writes the
   package source into a branch of the consumer, and opens an ordinary pull request ("UI kit
   update") that the consumer's own CI gates. The pin is recorded by the tool, never in the
   consumer repo.
3. **Scrub, then deny.** The tool rewrites doc references and source names in comments, then fails
   with file and line on any remaining reference to the source (repo, package or doc names). A new
   kit comment that names a doc makes the sync fail: fix the wording in the core or add a scrub rule,
   never hand-edit the vendored source. Deny terms match on word boundaries, so a short term never
   matches inside an unrelated word, and a plain English word (such as "core" in a comment about a
   pure function) is never a deny term on its own: deny the full names instead.
4. **Mark the CSS as a side effect.** The package manifest lists its stylesheets in `sideEffects` so
   the bundler never tree-shakes the token and kit sheets away.
5. **Check against the consumer's React types.** Before releasing a kit change, sync it into a
   scratch branch of the consumer (without recording the pin) and run the package typecheck there.
   A consumer pinned to older React types catches a ref or element type the core's own types accept.

#### Rolling a kit change out across apps

- **Package pull request first, then one pull request per app.** The first pull request adds or
  upgrades the shared package with no app changes. Each app then moves in its own pull request, so a
  regression points at one app and can be reverted alone.
- **Screenshots of every route in both themes.** Each app pull request carries before and after
  screenshots of every route in light and dark, diffed, not a sample of pages.
- **Scope per-app storage on a shared origin.** Apps mounted at different paths of one origin share
  `localStorage`. Pass each app's `appId` to the shell (`AppShell appId`, `StorageScope`) so seen and
  dismissed state stays per app, while theme and rail pin stay shared on purpose.

### 7. Enforce what you consume

Consuming a doc is not compliance. `core-drift.yml` runs `lint-core/ui_lint.py` on the paths in
`standards-local/ui-lint.json`. A UI consumer clears its findings during adoption and keeps no
baseline (`kit/MIGRATION.md`, "Close the baseline"). Only an app that runs the lint without taking
the kit records a ratchet baseline under one explicit exception and burns it down (see
`lint/README.md`). Wire every other acceptance line into the
overlay's CI too. A rule with no check is a suggestion.

### Keeping vendored copies intact (consumer side)

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
  consumer scan; the content is reviewed in this repo before release, which is where scanning it
  belongs.

The typed mirror in a UI package (a `T` object alongside `tokens.css`) is consumer-owned: when a
sync moves a CSS custom property, the mirror's parity test fails by design. Update the mirrored
values, and any contrast annotations, in the same PR as the sync.

## What an overlay may and may not do

- **May tighten** a core rule: a smaller limit, an extra required check, a stricter palette.
- **May set** every parameter the core exposes.
- **May add** standards the core does not have.
- **May not loosen** a core rule. If a rule is wrong for your business, raise it here through
  the upward path ("Contributing back") and make the case. A deliberate, time-boxed exception
  is recorded in the overlay (next section).
- **May not edit** `standards-core/` by hand. The next sync would erase it and the pin would lie.

Adopt baseline-first: an existing repo syncs the overlay and keeps its features working,
behind thin adapters, before it swaps any hand-rolled part ([kit/MIGRATION.md](kit/MIGRATION.md)
step 0). Inside the overlay only `standards-local/` belongs to the consumer; scripts and
helpers a consumer writes for itself live in the repo's own tree, outside the synced
directories, so no sync ever overwrites them.

## Source of truth and explicit exceptions

The standards in this repo are the source of truth. No app, including the one a rule was first
learned from, outranks the text here. When an app and a standard disagree, the app is wrong until
one of three things happens:

1. **The app is fixed** to meet the standard. This is the default.
2. **The standard is changed** by pull request here, when the app proved the rule wrong. The fix
   lands in the core first and reaches every consumer through a release.
3. **The consumer records an explicit exception** when the app cannot meet the rule yet.

An explicit exception lives in the overlay's `standards-local/exceptions.md`, one row per exception:

| Field | Meaning |
|---|---|
| `ID` | `EXC-NNN`, never reused |
| `Rule` | Core doc and section, for example `web-ui.md 0.1` (section 0, rule 1) |
| `Scope` | The app or path it covers. Never all apps: that is a core change |
| `Deviation`, `Reason`, `Owner` | What differs, why, and who answers for it |
| `Approved`, `Review by` | Dates. Review by is at most 180 days after approval |

Code that deviates on purpose carries `core-exception: EXC-NNN` in a comment on that line, so a
check that would flag it can be traced to the record. `scripts/check-exceptions.py` (in the overlay
template, run by `core-drift.yml`) fails when a row is malformed, a review date has passed, or a
marker names an ID that is not in the table. An expired exception is renewed with a fresh reason
or closed by fixing the app. `--json` prints the table for tooling.

An exception never loosens the core for anyone else, and it is not a way to keep a business name,
host or id in the core.

**Proof records.** A rule `core-status.py` cannot see (a `test` or `review` rule, or an `overlay-ci` rule
whose result was not read) is `unverified` until the consumer records how it is proved in the overlay's
`standards-local/proofs.json` (consumer-owned). There are four kinds: `ci` and `test` turn the rule
`proved`, a dated `review` turns it `attested`, and a dated `waiver` with a reason turns it `waived`
(never counted as proof). A rule may carry a list of records, so a test and a dated review sit together and the rule stays `proved`. A test proof names its rule with a `core-rule: <id>` comment. The record
format, expiry, the other statuses (`pass`, `not_applicable`, `excepted`, `fail`) and the `repo-check`
rules RC001 to RC022 are in [CONSUMING.md](CONSUMING.md#8-rule-status-proofs-and-the-repo-checks).

## Hermes: shared configuration and core skills

Consumers that work through the Hermes agent share two things from `hermes/`, and nothing else
about their agent:

- **Configuration and plugins.** [hermes/configurations.md](hermes/configurations.md) lists the
  settings and plugin practice that proved themselves, each with why and the failure it prevents,
  including token economy (rtk, caveman) in sections 11 and 12. [hermes/tools.json](hermes/tools.json)
  holds the decision per tool and how it is installed.
- **Skills named `core-`.** A skill whose name starts with `core-` lives in
  `hermes/skills/core-<name>/`, holds no business data and is installed into every consumer by
  `hermes/sync_skills.py`. Every other skill is the consumer's own and never comes here, and no
  consumer skill may use the prefix. `core-practices` is generated from the rules registry by
  `hermes/build_skills.py`, so every consumer's agent works to the current rules.

Consume it with the nightly job: run `python3 hermes/setup.py` once ([CONSUMING.md](CONSUMING.md)).
Every night `hermes/nightly.py` pulls this repo, installs the core skills, installs and enables the
required plugins and skills from `tools.json`, and moves each registered UI consumer to the newest
release. A hand edit to an installed core skill is reported and kept, never
overwritten silently: change the skill here by pull request instead. Details and the contribution
rules are in [hermes/README.md](hermes/README.md).

### What may and may not be shared

Hermes agent overlays are **strictly split** between shareable and instance-local content:

**Allowed to share:**

- Skills starting with the `core-` prefix ONLY (`hermes/skills/core-*/`).
- Source code for plugins, with NO configuration or secrets.

**NEVER share:**

- MCP config, gateway tokens, kanban or cron config, the vault, `config.yaml`, local profiles
- Plugin keys, secrets, or any identifying information
- A skill that describes real policies or names identifying elements

See [`standards/hermes.md`](standards/hermes.md) for all sharing rules, failure modes, and
best-practice patterns.

### Contributing core skills

1. Prefix your skill `core-` and document its acceptance criteria.
2. Submit a pull request to this repo.
3. Validate zero leaks of instance context, secrets, or board references.
4. Run the checks; a nonconformant submission is fixed or rejected. Any consumer account may merge
   its own pull request once `ci` and `visual` pass, since every consumer is the same owner.
5. On acceptance, every consumer picks the skill up on its next `python3 hermes/sync_skills.py --dest <profile home>/skills/core` run (the nightly passes it).

## Contributing back

Improvements reach this repo through the upward path, not through drive-by pull requests: a
build's agent reports, the owner approves, and the account that owns the change opens the
pull request. Nobody pushes to `main`.

1. The consumer files what it found on its account's open `consumer-report` issue, created
   from the `consumer-report` issue template in the owner's private intake repository (reports are never filed in this public repository);
   the nightly appends what it finds on its own into that issue's candidate section. A
   proposal that is not ready to adopt carries `settling` until its open questions close.
2. The owner approves items in the issue.
3. The account that owns an approved item branches from `main` and opens the pull request
   linking the issue. Use Conventional Commits for the commit and the PR title. Make the
   change agnostic: name no employer, product, hostname, tenant or person; where a rule
   needs a value, expose it as a parameter and document the default. Add a dated entry to
   `CHANGELOG.md` in the same pull request.
4. Run the [checks](#checks) below (CONSUMING.md section 13 lists the pre-merge set). All must pass.
5. If the change comes from a source repo, state in the pull request which parts were adopted, adapted
   or rejected, by role and never by name. The provenance record that would name the source stays with the
   contributing account, not in this public repo. A source repo feeds later changes the same way any
   other consumer does: report, approval, pull request.

A rule is adopted when it is generic, adapted when it becomes generic once a name or platform is
turned into a parameter, and rejected when it only makes sense inside one business. Record the
decision either way.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full rules.

## Versioning and releases

- `main` is always releasable. Every change lands by pull request after the `ci` and `visual` checks
  pass, and carries a dated `CHANGELOG.md` entry.
- Releases are tags of the form `vMAJOR.MINOR.PATCH`, made automatically: when a pull request that adds a
  new top changelog entry merges, `release.yml` tags the merge commit, publishes the GitHub Release with
  that entry as its notes and attaches the kit gallery (`gallery-release.yml`). Nobody tags by hand.
  Consumers move only to published releases.
- The version is assigned at merge: take the next free number right before opening the pull request and
  again before it merges, and when another change took it, merge `origin/main` and renumber
  ([CONSUMING.md](CONSUMING.md#10-releases-and-versions)).
- A rule that becomes stricter, or a parameter that becomes required, is a **major** release.
- A new rule, doc or optional parameter is a **minor** release.
- A wording fix or clarification is a **patch** release.
- Overlays pin a tag (or, for the reusable workflow, a release commit) and may track `main` only on a
  scratch branch. An external monitor watches releases and pins; the core itself runs no monitor.

## Checks

```bash
python3 checks/check-sanitised.py --diff origin/main  # no business-specific terms or real emails on added lines
python3 checks/check-sanitised.py   # the same over the whole tree (what sweep.yml runs weekly)
python3 checks/check-consumer-neutral.py --diff origin/main  # nothing names a consumer (also: no argument)
python3 checks/check-ascii.py       # plain ASCII only, no em or en dashes or curly quotes
python3 checks/check-placeholders.py  # no placeholder prose standing in for removed content
python3 checks/check-links.py       # every relative markdown link and heading anchor resolves
python3 checks/check-authors.py origin/main  # every commit uses a GitHub noreply email
python3 checks/check-changelog.py origin/main  # shipped content changed, so the changelog changed
python3 checks/check-closing-refs.py origin/main  # no closing keyword before a consumer-report reference
python3 tokens/build.py --check     # token outputs are current and every contrast rule passes
python3 lint/ui_lint.py --self-test # the UI lint still catches every fixture violation
python3 lint/ui_lint.py tokens/hub-layer.css  # the core's own recipes pass the rules it sets
python3 lint/script_lint.py --self-test  # the script lint still catches every fixture violation
python3 checks/check-css-vars.py    # every var() in the core CSS resolves
python3 checks/check-token-names.py # every --token a standards doc names exists
python3 checks/check-rules.py       # the rules registry matches the docs, the UI lint and the repo checks
python3 checks/check-hermes-skills.py  # shared skills are core- named and core-practices is current
python3 checks/check-hermes-tools.py   # every Hermes tool has a decision and required tools are in the doc
python3 checks/check-kit-comments.py   # kit source comments name no doc
python3 templates/overlay/scripts/repo_checks.py  # the repo checks pass on the core itself
python3 -m unittest discover -s tests -p "test_*.py"  # run under the oldest supported Python (3.9) too
ruff check . && ruff format --check .  # pinned ruff, configured in pyproject.toml
(cd kit && npm ci && npm run check) # kit typecheck, unit and axe tests, gallery build
```

CI runs them on every pull request through one required job named `ci` (`checks.yml`; a push to `main`
runs only the secret scan). The `kit` workflow runs when `kit/` or `tokens/` change, and the `visual` job
(see [Visual gate](#visual-gate)) is required next to `ci`. CONSUMING.md section 13 says what READY means
and what to do when a check is cancelled.

**Denylists.** The shared list, `checks/denylist.sha256`, holds only the sha256 of each term, so
the file never names what it protects; `check-sanitised.py` hashes every span of one to four words
and reports a hit by place, never by term. Add a shared term with
`python3 checks/check-sanitised.py --hash "<term>" >> checks/denylist.sha256`. Keep terms only you
need outside the repo, in `~/.config/build-standards-core/denylist.txt` or a file named by
`CORE_PRIVATE_DENYLIST`. `check-sanitised.py` reads both and never prints a term. Turn on the pre-commit hook once per clone so they run before every commit:

```bash
git config core.hooksPath checks/hooks
git config user.email <id>+<login>@users.noreply.github.com
```

The hook checks only the lines a commit adds (`check-sanitised.py --staged`, `check-consumer-neutral.py
--staged`). CI runs the same checks as `--diff <base commit>` over a pull request's added lines, so
`--no-verify` does not get a hit in; with no argument each check reads the whole tree, which the weekly
`sweep.yml` does.

## Visual gate

The `visual` workflow screenshots every kit gallery specimen (each `section` with a stable
`specimen-<name>` id) in the dark and light themes and compares them to the committed baselines in
`kit/visual/baselines/linux`, then runs axe in a real browser with color-contrast on, in both
themes and with the dialog and the sheet open. Zero violations are allowed. It runs on every pull
request and is a required check next to `ci`. It runs in the pinned
Playwright image (`mcr.microsoft.com/playwright`, the same version as `@playwright/test`), which
fixes the browser build and the system fonts. Live content is held still: the clock is installed
and paused before load, reduced motion is forced, the theme is set through the `gallery.theme`
storage key, and `?gate` swaps the git-generated release notes for fixed sample notes.

```bash
cd kit
npm run visual          # build the gallery, then compare and run axe (local runs use their own OS baselines)
npm run visual:update   # dispatch the workflow with update-baselines on, then download the linux set
npm run visual:update -- --docker   # or make the linux set locally in the same image
```

CI baselines are the source of truth. After a deliberate visual change, push the branch, run
`npm run visual:update`, look at every changed image, and commit them by name. A specimen without
a baseline fails the run, and the failed run uploads the `visual-baselines` artifact with the new
image in it, so a first baseline can come from the pull request itself. Diffs and the HTML report
are in the `visual-report` artifact.

After an update-baselines run, copy the full linux baseline set from the artifact, never a single
specimen: copying only the changed one leaves unrelated specimens one pixel off.

Every pull request also uploads the built gallery as the `kit-gallery`
artifact. Every release attaches `kit-gallery-<tag>.zip` to the release, so any account can see the
reference without building it. Unzip it and serve the folder (`python3 -m http.server`), because the
page loads ES modules and browsers block them from `file://`.

## Adding a new source repo

1. Add the source's business-specific terms to your private denylist first (and, hashed, to the
   shared `checks/denylist.sha256` when every contributor must be stopped from naming them).
   Ingest by role: a source's names never reach this repo.
2. Copy the source docs into a scratch branch and replace identifiers with generic nouns.
3. Run `check-sanitised.py` until it reports zero hits, then read each doc for voice and for
   rules that only fit the source business.
4. Keep the per-doc decision table and the replacement map with the contributing account, and put the
   adopt, adapt or reject decision for each part in the pull request description, by role.
5. Open a pull request. Merge only when all checks pass.

## FAQ

**Why a copy and not a git submodule or a package?** A copy in the overlay is a plain reviewed
diff in the consumer's own history, works with no extra access at build time, and cannot change
under a consumer without a pull request.

**Where do the design tokens live?** In `tokens/tokens.json`. `tokens/build.py` generates the CSS,
TypeScript, Tailwind and WPF outputs and certifies contrast. Each app picks one named accent, or
generates a certified custom one in its overlay.

**A rule here conflicts with one of ours.** Tighten only. If yours is stricter, keep it. If yours
is looser, either meet the core or open a pull request here to change it.

**Can I put something here that only my business needs?** No. Keep it in your overlay.

**CI cannot check out the core.** The core is public, so a checkout needs no key or token. Check the
`repository:` name and that the pinned ref exists as a tag (`git ls-remote --tags`).

## Licence and provenance

MIT, see [LICENSE](LICENSE). The standards were assembled from build standards and operating
practice written by the repository owner's own accounts, restated as business-agnostic rules;
the owner confirmed the right to publish all of it on 2026-10-24. Item references such as
`(#117 G-031)` in the changelog and comments point at the owner's private intake for consumer
reports, not at this repository's issues.

