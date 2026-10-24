# Consuming the core: instructions for an agent

You are an agent (normally the Hermes desktop app) that has opened this repo. This repo is
the shared standard for every consumer account: the mandatory baseline for UI design, web
frontend and backend practice, the CI workflows that proved themselves across builds, and
agent runtime practice (README "Direction"). All consumer accounts belong to one owner, who
has the final say.

The operator's whole instruction is one sentence: "Read `OWNER/build-standards-core` and set this
machine up as a consumer." Everything else is below. Do not wait to be told more.

Your first job is to make this machine a consumer, so the standard applies itself every night. Do
these steps in order, then report the result to the operator. Each step is idempotent: if it was
done before, running it again only updates it.

## 1. Get the clone and check the basics

- If you are not already in a clone of this repo, run
  `gh repo clone OWNER/build-standards-core ~/GitHub/build-standards-core` and work from there. Use a
  permanent path: the nightly job runs from this clone for good, and macOS clears `/tmp` and the Hermes
  scratch folder. `hermes/setup.py` refuses a temporary path.
- `gh auth status` shows a signed-in account that can read this repo
  (`gh repo view OWNER/build-standards-core` prints it).
- This clone is on `main` with no local edits (`git status` clean). The nightly job fast-forwards it,
  so never work in this clone: make changes in a separate git worktree.
- `python3 --version` is 3.9 or later, and `hermes --version` works.
- Only noreply author emails land in history (rule `pr-review-and-merge.md 1.18`), and no account
  setting is required for it. Merge with `scripts/merge-pr.py`: where the repo allows rebase merging it
  builds the squash commit itself, authored by the signed-in account's noreply address, and merges it
  with `--rebase`, which keeps that author. Turn on "Allow rebase merging" on a repo that uses it;
  without it, merge-pr falls back to a squash merge and refuses a pull request whose commits carry an
  email that is not a noreply address.

## 2. Register this machine

A UI consumer is a repo of this account that holds a standards overlay (a `standards-overlay/` or
similar folder with `standards.lock`). Ask the operator which repos those are if it is not obvious.
A repo without an overlay first adopts one: README section "Consuming the core". If you cannot tell,
do not stop: run the registration without `--ui` (the agent-home part still applies), then tell the
operator to rerun it with `--ui OWNER/REPO` for each UI repo.

Run from this clone:

```
python3 hermes/setup.py --ui OWNER/REPO[:MODE[:PATH]] [--ui OWNER/REPO ...]
```

`MODE` is `workflow` (default), `ops-center` or `vendored`, and `PATH` is the repo's local clone
(required for the last two: section 3 says what each mode does). `local` is the deprecated name of
`ops-center` and keeps working as an alias. Setup writes
`~/.config/build-standards-core/consumer.json`, the machine's consumer record (section 5), the cron
wrapper `~/.hermes/scripts/core-nightly.sh`, and the Hermes cron job `core-nightly` (no-agent, daily
at 03:15, output to the origin chat, failures notified). It removes the older `core-skills-sync` job
it replaces. Pass `--deliver local` where results belong on a local board rather than the chat, and
rename the job to the consumer's own naming rule with `--name` (or `hermes cron edit`): setup finds
the job again by its wrapper script, so a rerun keeps the name and delivery target unless you pass
them. Then it runs the job once and prints what it did. Add `--check` first to preview.

## 3. Set up each way

A repo takes the core one of four ways; the registration records which, and the nightly treats it
accordingly (README "Direction").

### `workflow`: a product repo

- The repo carries the overlay itself: README section "Consuming the core" walks a repo without one
  through adopting it, baseline-first.
- Approval-gated (the table below). The nightly moves the repo toward the newest release through
  the repo's own `core-update.yml` workflow, which opens a draft pull request pinned to the release
  and leaves it for the owner (`CORE_UPDATE_MERGE` unset or `approve`). The owner approves it in one
  action from the ops center's Core consumption panel or on GitHub (mark it ready), and it merges
  through the repo's merge gate once every check passed. `CORE_UPDATE_MERGE=wait` (merge once
  green) or `gate` (the merge gate merges it) is the owner's standing approval for that repo, set
  by the owner only. It never uses GitHub's auto-merge: on a repo with no required checks that
  merges at once, before CI runs. An open sync pull request is reported as awaiting approval; one
  with failing checks is a problem.
- The repo carries the template `core-ci.yml` beside `core-drift.yml` (templates/overlay/README.md
  "CI workflow"): it proves the `overlay-ci` rules, and its jobs belong in the merge gate.
  `python3 scripts/core-ci.py required-checks` lists the jobs the gate does not require yet, and
  `--fix` prints the command that adds them (it never runs it).
- The repo's default branch must require status checks: branch protection, an active ruleset, or a
  `REQUIRED_CHECKS` list in its merge gate workflow. `hermes/setup.py --ui OWNER/REPO` reads them
  through gh and refuses a `workflow` repo that has none, because nothing would stop a red sync
  pull request from merging. Add the required checks, or register the repo as `ops-center` (the
  local gate). `--allow-no-required-checks` registers it anyway and prints a warning; choose it only
  knowingly, since `core-update.yml` then is the only thing that waits for CI.
- This needs the `CORE_TOKEN` secret in the repo. A `workflow` repo without it: register it with
  its `PATH`, and the job syncs from the local clone and opens the pull request itself.

### `ops-center`: the machine's ops center and other local tools without CI

- Register with the repo's local `PATH`; the repo needs no CI and no token.
- The nightly applies a release at once. In an isolated git worktree of the committed default
  branch it runs the gate on the current pin, syncs the new release, and runs the gate again:
  core sync, exceptions, UI lint, script lint, typecheck, test build, plus the repo's own verify
  command from `standards-local/parameters`. Only then does it commit to the default branch and
  push where a remote exists; where the remote requires a pull request, the job opens it and
  merges it at once, because the local gate is the gate.
- Any failure rolls back: the worktree is discarded, the pin stays where it was, and the failure
  is reported once per kind until a clean run.
- One line in the log per apply. There is no pull request to review after the fact: the gate is
  what makes applying at once safe.
- **An ops center whose source is a gated repo** (its own CI on pull requests, a merge gate, a
  deploy job that takes `main` and refuses local edits) stays apply-at-once. Set `"apply_via":
  "pr"` in its entry (the nightly also picks it when the remote's default branch requires status
  checks or the repo has its own pre-push guard). The nightly then syncs in an isolated worktree of
  the remote's default branch, runs the local gate before and after, pushes `chore/core-<release>`,
  opens the pull request, waits for the repo's own checks on that head (`scripts/core-ci.py
  wait-checks`, the same wait `core-update.yml` uses, bounded by `pr_timeout_min`) and merges it at
  once with `scripts/merge-pr.py --match-head-commit`. It never waits for the owner and never writes
  the deploy checkout: the repo's own deploy job takes the merge. A failed or timed-out check, or a
  refused merge, closes the pull request, deletes the branch and leaves the pin unchanged, reported
  once per kind. While it waits, the nightly prints a progress line (checks done, pending, failed) at
  most every 5 minutes.
- Every push runs from the clone, never from the gate worktree, so the repo's pre-push hook runs as
  it does for a push by hand. Git hands a hook `GIT_DIR`, and from a worktree that is
  `<clone>/.git/worktrees/<name>`: a hook, or a test it runs, that calls `git init` with it set writes
  `core.bare = true` into the clone and `git pull` there stops working. A repo's tests that make
  fixture repos should still drop `GIT_DIR`, `GIT_WORK_TREE` and `GIT_INDEX_FILE` from the
  environment they give git. The nightly checks every clone before and after its run, sets a
  `core.bare = true` on a clone with a work tree back to false, and reports it once.
- A sync adds the template parameters rows the repo's `standards-local/parameters.md` lacks, with a
  marker comment, and names them on one line (templates/overlay/README.md "Updating"). Fill them in;
  a missing `Commit emails` row is what failed a sync's `core-identity` check before.
- A guard on the default branch that refuses the nightly's push (the repo's own pre-push hook,
  branch protection or a ruleset) rolls back every direct apply. `hermes/setup.py --ui OWNER/REPO=ops-center:PATH`
  looks for one and prints which mode fits, and the nightly's failure line names the hook. Two
  fixes: let the hook allow a push to the default branch whose diff touches only the overlay
  folder (with a test of the hook), or register the repo as `workflow` (the pull request mode). A
  branch that requires reviews or checks also refuses the merge-at-once pull request, so it needs
  `workflow`.

### `vendored`: a repo that must carry no record of the core

- The core's shipped content is copied into the repo's own shared UI package with names scrubbed,
  per README "Vendoring into a consumer that carries no record of the core". The repo carries no
  overlay, no lock file and no marker.
- The machine keeps the record the repo cannot:
  `~/.config/build-standards-core/vendored/<owner>__<repo>.json` holds the release the copy
  actually carries, its source hash, how the release was found, the newest release and whether
  the copy is behind. It is read by `core-status.py --vendored OWNER/REPO`, which prints `behind`
  (exit 3) when a newer release exists, so a silent repo's adoption is still provable on the
  machine that made the copy, and a copy held back on purpose never reads as current.
- The release the copy carries comes from the vendoring tool, never from the newest release:
  either the tool writes the release it copied to a pin file on this machine, named as `pin` in
  the repo's `consumer.json` entry, or it records `{release, source_hash}` in the record file when
  it copies, and the nightly matches that source hash against each release in the core clone. A
  record with neither is reported, not guessed.
- The nightly never writes into the repo. Approval-gated: a new release reaches the repo only as
  the vendoring tool's pull request, which the owner approves. Name that tool's branch prefix as
  `sync_head` in the entry so the Core consumption panel finds the pull request.
- Registered report only (`--report-only`), the nightly still writes the machine record each run
  (it reads the clone and the core clone and writes nothing into the repo), and the report sections
  scan the clone at its root against the core's kit, so section g and the candidates list the repo
  too.

### Who does what, per class

The owner's rule (README "Direction", "Two consumption classes"; `ci-cd-release.md` section 11):

| | Apply-at-once (`ops-center`, `agent-home`) | Approval-gated (`workflow`, `vendored`) |
|---|---|---|
| A new release | the nightly applies it at once behind the ops center's gate, rolls back on failure; a gated repo's release lands as a pull request that merges as soon as its own checks pass | arrives as a pull request: `core-update.yml`'s draft, or the vendoring tool's |
| Who approves it | nobody: the gate is the approval | the owner, one action in the Core consumption panel or on GitHub |
| Who merges it | the nightly, after the gate passes (and the repo's own checks, for a gated repo) | the repo's merge gate or `merge-pr.py`, after the owner's approval and green checks |
| Adopting new kit parts | the ops center's own changes | planned pull requests the owner approves, one per swap |
| What the nightly may do to the repo | commit and push the sync to its default branch, or for a gated repo open the sync pull request and merge it once its checks pass | dispatch `core-update.yml`, read state; never push, never merge |
| What the panel shows | release and gate result, no approval control | pin, behind, sync pull request and CI, status, adoption suggestions with risk |
| `setup.py` says | "applies at once" | "approval-gated" |

### `agent-home`: this machine's agent runtime

- The registration in section 2 covers it: skills, settings, crons and plugins from
  `hermes/tools.json` and `hermes/configurations.md`, applied at once every night, one line per
  apply.

## 4. What the nightly applies, and how to opt out

Every night the job (`hermes/nightly.py`, always run from this clone so every consumer runs the same
code) works through these steps in order. Each step's key lives in the `apply` object of
`consumer.json`; a missing key means the default shown.

| Step | What it changes on this machine | Opt-out key (default) |
|---|---|---|
| pull | fast-forwards this clone, with retries; a new release takes effect the same night | none: it is how the job gets its own code |
| hermes | refreshes the `core-` skills in `~/.hermes/skills/core` and applies the Hermes settings from `hermes/tools.json`; never hand-edits `config.yaml`, never removes anything | `apply.hermes` (on) |
| binaries | installs what `hermes/tools.json` adopts: the `rtk` binary and its `rtk-rewrite` plugin, the `caveman` skill; each skipped when already present | `apply.binaries` (on) |
| ui | every registered repo, per its mode (section 3) | `apply.ui` (on) |
| claude | the coding-agent CLI layer: hooks, plugins, MCP servers, context compression | `apply.claude` (off; also skipped quietly when the CLI is not installed) |
| safe-restart | the safe-restart agent and the paused restart jobs | `apply.safe_restart` (off) |
| report | the upward scan into this account's `consumer-report` issue (section 7) | `apply.report` (on) |
| consumption | writes `~/.config/build-standards-core/consumption.json`, the feed every ops center's Core consumption panel renders (section 5); read-only on every remote | `apply.consumption` (on) |

Turn the off-by-default steps on (or any step back off) without editing the file:
`python3 hermes/setup.py --claude` or `--safe-restart`, and `--no-claude` or `--no-safe-restart`.
A rerun keeps every other setting.

The job is silent when nothing changed. A line starting `RESTART` means restart the Hermes desktop
app and gateway to load a new plugin. A failure exits non-zero, so Hermes notifies the operator.

One truth about optional tooling: the Hermes steps never install `caveman-compress`. The Hermes
skills security scan blocks it (verdict dangerous), so for the agent home it stays optional and
manual: `hermes/configurations.md` section 11.3. The opt-in `claude` step compresses the coding
agent's own memory file with it, and only on a machine that turned that step on and has its CLI
(`claude/README.md` section 2).

## 5. The machine's record: `consumer.json`

Version 2 is the current shape:

```json
{
  "version": 2,
  "core": "~/GitHub/build-standards-core",
  "core_repo": "https://github.com/OWNER/build-standards-core",
  "hermes_home": "~/.hermes",
  "apply": {
    "hermes": true,
    "binaries": true,
    "ui": true,
    "claude": false,
    "safe_restart": false,
    "report": true
  },
  "ui_consumers": [
    {
      "repo": "OWNER/REPO",
      "mode": "workflow",
      "overlay": "standards-overlay",
      "path": "<local clone, required for ops-center and vendored>"
    }
  ]
}
```

| Key | What it is | Since |
|---|---|---|
| `version` | the schema this file follows; a version newer than the job knows is an error, never a guess | v0.49.0 (a file without it is version 1) |
| `core` | this permanent clone | v0.36.0 |
| `core_repo` | where the sync scripts resolve the core when `CORE_REPO` is not set in the environment | v0.38.0 (rerun `hermes/setup.py`; v0.47.3 also carries a legacy lock value over) |
| `hermes_home` | the Hermes home directory | v0.36.0 |
| `apply.hermes`, `apply.binaries`, `apply.ui` | the nightly's opt-outs (section 4), on when missing | v0.36.0 |
| `apply.safe_restart` | the safe-restart step, off when missing | v0.44.0 (off by default from v0.49.0) |
| `apply.claude` | the coding-agent CLI step, off when missing | v0.45.0 (off by default from v0.49.0) |
| `apply.report` | the upward report step, on when missing | v0.49.0 |
| `apply.consumption` | the consumption feed `consumption.json` (standards/local-ops-app.md section 19), on when missing | v0.59.0 |
| `ui_consumers[].repo` | the repo as `OWNER/REPO` on GitHub | v0.36.0 |
| `ui_consumers[].mode` | `workflow`, `ops-center` or `vendored`; `local` is a deprecated alias of `ops-center` | v0.36.0 (`ops-center` and `vendored` from v0.49.0) |
| `ui_consumers[].overlay` | the overlay folder inside the repo (default `standards-overlay`) | v0.36.0 |
| `ui_consumers[].path` | the repo's local clone; required for `ops-center` and `vendored` | v0.36.0 |
| `ui_consumers[].apply` | `false`: report only, a local job of this machine applies the core (`setup.py --report-only`); missing means on | v0.58.0 |
| `ui_consumers[].sync_head` | the head-branch prefix of the repo's sync pull request, for the consumption feed (default `chore/core-`; a vendoring tool names its own) | v0.59.0 |
| `ui_consumers[].apply_via` | `ops-center` only: `pr` lands each release as a pull request through the repo's own CI gate and merges it at once; `direct` commits to the default branch; missing: detected (a remote whose default branch requires status checks, or the repo's own pre-push guard, means `pr`) | v0.64.0 |
| `ui_consumers[].pr_timeout_min` | `ops-center` with `apply_via` `pr`: minutes to wait for the repo's own checks before the pull request is closed (default 60) | v0.64.0 |
| `ui_consumers[].pin` | `vendored` only: a file on this machine where the vendoring tool writes the release it copied (the first `vX.Y.Z` in it is read); optional when the tool records the source hash instead | v0.58.0 |

A release that adds a key adds its row here with the release, and the nightly fills the default in
when it migrates the file, so a machine set up earlier never fails on a key it lacks.

The nightly migrates a version 1 file in place, leaves its backup beside it, and prints one line
saying so.

**A machine whose UI repos take the core outside `consumer.json`.** A machine may have set up its
own local job for a UI repo before a mode existed for it (a gated local nightly for an ops center,
or a vendoring tool with its own scrub and skip rules). With no entry in `ui_consumers` the
nightly never fills the report's two marker sections for that repo. Migrate it one of two ways:

- **Switch the job to the mode.** Register the repo with the mode that matches what the local job
  does (`ops-center:PATH` for a gated local apply, `vendored:PATH` for a scrubbed copy), check that
  the nightly's run is green for a night, then retire the local job.
- **Keep the local job, register for the report only.** Register the repo with its mode and
  `--report-only` (`python3 hermes/setup.py --ui OWNER/REPO=ops-center:PATH --report-only`), which
  writes `"apply": false` on that entry: the nightly then skips the apply for it but still reads
  its local clone for the report sections (`nightly:candidates`, `nightly:changes`), so section g
  tracks it.

Either way the repo appears in `ui_consumers`, which is what the report step reads. A `vendored`
repo carries no overlay: the report scan reads its clone at the root against the core clone's kit,
read-only, and its release comes from the machine record, which the nightly writes for a report-only
entry too (#117 G-031). Its counts reach the report through `core-status.py --vendored` in section a.

**The consumption feed.** Each run the nightly also writes
`~/.config/build-standards-core/consumption.json` (schema versioned, written atomically): per
registered consumer its class, pin, latest, behind count, open sync pull request with CI state,
core-status counts, UI verdict and adoption suggestions, this account's report items waiting for a
decision or approved with no core pull request yet, and a `peers` block read from every open
`consumer-report` issue on the core. Every ops center renders its Core consumption panel from it
(standards/local-ops-app.md section 19, which holds the schema). The feed is read-only on every
remote and never writes to another account's issue.

## 6. Verify and report

- `hermes cron list` shows `core-nightly` active, with the next run time.
- `python3 hermes/apply_setup.py --check` prints "hermes setup matches the core decisions".
- After the restart, `hermes plugins list` shows `rtk-rewrite` enabled and `rtk gain` prints stats.
- In a registered consumer repo, `python3 scripts/core-status.py` prints the rules it carries and
  its UI adoption state; `--require-ui-adopted` turns that into a gate, and a vendored repo is
  judged from the record on the machine. `--ci` reads the repo's latest `core-ci.yml` run, so each
  `overlay-ci` rule reports pass or fail instead of unverified.
- `standards-local/parameters.md` has a `Stacks` row (a missing row is a problem, and
  `--require-lint-config` fails on it).
- Every rule still `unverified` either gets a proof record in `standards-local/proofs.json` (a
  `ci` job, a `test` file or a dated `review` record; README "Source of truth and explicit
  exceptions") or stays on the operator's list. A stale or broken record is reported as a problem.
- Tell the operator what changed, and that the app needs a restart if the run said RESTART.
- If the nightly pull is blocked by local changes you did not make (generated files), run `git status`,
  `git restore` those files and run the job again. Never commit in this clone.

**History rewritten.** If the core's history was rewritten (the clone shows "ahead N, behind M"
against `origin/main` and `git merge-base HEAD origin/main` finds no common commit), a
fast-forward can never succeed again and a plain `git fetch` may fail on moved tags. The nightly
detects this itself: on a clean clone it runs `git fetch --tags --force origin` and
`git reset --hard origin/main`, keeps the old tip as a local branch `core-before-rewrite-<sha>`, and
logs one line. On a clone with local edits it changes nothing and fails with the exact recovery
command:

```bash
git -C ~/GitHub/build-standards-core fetch --tags --force origin && git -C ~/GitHub/build-standards-core reset --hard origin/main
```

The reset is safe because nobody commits in this clone (section 1). The overlay pins survive a
rewrite: `standards.lock` records the release tag and a content hash, the offline drift check
compares the hash, and `check-core-sync.py --remote` checks out the tag when the recorded commit no
longer exists.

## 7. The upward path

You do not open a pull request on this repo from a build, and the nightly never opens one either.
What a build learns goes into one place: this account's single open `consumer-report` issue on the
core, created from the template at
`.github/ISSUE_TEMPLATE/consumer-report.md` on the first report run.

The nightly (`hermes/report.py`) keeps its own section current between the issue's two markers
`<!-- nightly:candidates:start -->` and `<!-- nightly:candidates:end -->`: local parts that
duplicate or extend a kit role, local tokens or classes the lint flags, and new local additions
since the last run. It updates the issue only when that section changed, runs the sanitiser on the
text first and holds locally on a hit, and never touches anything outside the markers.

It keeps a second section the same way, between `<!-- nightly:changes:start -->` and
`<!-- nightly:changes:end -->`: per registered UI repo (named by a hashed label, never the repo),
local parts added, removed or with a changed signature, the counts of local tokens and kit-class
restyles the lint flags, the core-status count deltas, and new local parts that match a kit role.
Its state is kept in `~/.config/build-standards-core/changes__*.json`; a quiet night keeps the last
change set and edits nothing.

The full report is produced on demand. On a consumer machine with Hermes, run:

```bash
hermes chat -Q -s core-consumer-report -q "Produce and file this account's consumer report now, following the core-consumer-report skill."
```

`-s` preloads the shared skill the nightly installs, `-q` with `-Q` answers and exits. Run it where
`gh` is signed in as the account and `CORE_REPO` is set as for the nightly. An agent without Hermes
gets the same result by reading `hermes/skills/core-consumer-report/SKILL.md` in the core clone and
following it step by step.

Everything else you add goes outside the markers, following the report outline, the scope test and
the sanitising rules in [CONTRIBUTING.md](CONTRIBUTING.md#reporting-from-a-consumer). The owner
approves items in the issue; the account that owns an approved item opens the core pull request and
links the issue.

## What the job will not do

- Install anything the Hermes skills security scan blocks (`caveman-compress` stays optional and
  manual: section 4 and `hermes/configurations.md` section 11.3).
- Edit a repo's code beyond the overlay sync, merge a pull request whose checks fail, or touch
  secrets.
- Open a pull request on this repo: consumers report (section 7).

## Contributing

- Changes to the standard arrive through the upward path: report items on the account's issue, the
  owner's approval, then the owning account branches from the current `origin/main` in its own
  worktree, runs the checks (README "Checks"), opens a pull request, and merges it once `ci` and
  `visual` pass. Rules: [CONTRIBUTING.md](CONTRIBUTING.md).
- Every account that commits or opens pull requests keeps its email private (section 1 and
  `pr-review-and-merge.md 1.18`); merge with `merge-pr.py`, which refuses a pull request whose commits
  carry an email that is not noreply and prints the recovery if the merge commit still leaks one.
- After the merge, tag the merge commit (`vX.Y.Z`) and push the tag. The tag push publishes the
  GitHub release, and consumers move only to published releases.
- Scope: the Hermes part of the standard covers only what is listed in `hermes/tools.json`.
  Whether something found on this machine belongs in the core is decided by one test
  (CONTRIBUTING.md "Does it belong in the core?"): would it help another consumer's agent that
  knows nothing about this machine, carrying no name, path or value of this estate? Both yes: report
  it (section 7). Either no, as with smart-home or personal tools: it stays local and is not a gap
  in the core.

## Where things are

| Need | File |
|---|---|
| What the core is for, the four ways and the two consumption classes | README "Direction" |
| The consumption feed and the ops center's approval desk | `standards/local-ops-app.md` section 19, `hermes/consumption.py` |
| Rules for code, UI, CI and scripts | `standards/` and `standards/rules.json` |
| Hermes settings and plugins, with reasons | `hermes/configurations.md` |
| Token efficiency policy for an agent home | `hermes/token-efficiency.md` |
| Per-tool decisions the nightly job installs | `hermes/tools.json` |
| How a UI repo consumes the core | README "Consuming the core", `templates/overlay/` |
| How a build reports to the core | `.github/ISSUE_TEMPLATE/consumer-report.md`, `CONTRIBUTING.md` |
| How to contribute | `CONTRIBUTING.md`, `hermes/README.md` section 4 |
