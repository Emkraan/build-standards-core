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

## The three channels

The core reaches a consumer through three channels. A consumer uses one, two or all three, and
none of them needs an invitation, a token or an account to read the core: it is public.

| Channel | What it delivers | How it stays current | Section |
|---|---|---|---|
| Overlay sync | `standards-core/`, `tokens-core/`, `lint-core/`, `kit-core/`, the overlay scripts and the template workflows (`core-ci.yml`, `core-drift.yml`, `core-update.yml`, `lint-sweep.yml`), pinned by `standards.lock` | the repo's own `core-update.yml` opens a pull request on every release; or run `python3 scripts/update-core.py` by hand | 3, 12 |
| Reusable workflow (opt in) | the same one-job `core-ci` checks, run from the core at a pinned release, with no copy of `core-ci.yml` in the repo | move the pinned commit (by hand or with Renovate) | 3 ("Alternative") |
| Agent skills | the `core-` skills and settings for the agent on a machine | the nightly job (`hermes/nightly.py`) | 2, 4 |

The overlay is still what holds `standards-local/` (parameters, exceptions, proofs, lint config),
even when CI runs through the reusable workflow. A repo with no Hermes agent skips sections 1, 2
and 4 to 7 and reads sections 3 and 8 to 14. The sections after 7 are written for any consumer.

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
python3 hermes/setup.py --ui OWNER/REPO[=MODE:PATH] [--ui OWNER/REPO ...]
```

`MODE` is `workflow` (the default, written as just `OWNER/REPO`), `ops-center`, `vendored` or
`pin-file`, and `PATH` is the repo's local clone (required for the last three: `OWNER/REPO=ops-center:PATH`;
section 3 says what each mode does). `local` is the deprecated name of `ops-center` and keeps working as
an alias. Setup writes
`~/.config/build-standards-core/consumer.json`, the machine's consumer record (section 5), the cron
wrapper `~/.hermes/scripts/core-nightly.sh`, and the Hermes cron job `core-nightly` (no-agent, daily
at 03:15, output to the origin chat, failures notified). It removes the older `core-skills-sync` job
it replaces. Pass `--deliver local` where results belong on a local board rather than the chat, and
rename the job to the consumer's own naming rule with `--name` (or `hermes cron edit`): setup finds
the job again by its wrapper script, so a rerun keeps the name and delivery target unless you pass
them. Then it runs the job once and prints what it did. Add `--check` first to preview.

## 3. Set up each way

A repo takes the core one of five ways; the registration records which, and the nightly treats it
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
  "CI workflow"): it proves the `overlay-ci` rules, and its one check, `core-checks`, belongs in the merge gate.
  `python3 scripts/core-ci.py required-checks` reports when the gate does not require it, and
  `--fix` prints the command that adds them (it never runs it). A repo can instead call the reusable
  workflow from a pinned caller (see "Alternative: call the reusable `core-ci` workflow"); its check is
  then `core-checks / core-checks`.
- The repo's default branch must require status checks: branch protection, an active ruleset, or a
  `REQUIRED_CHECKS` list in its merge gate workflow. `hermes/setup.py --ui OWNER/REPO` reads them
  through gh and refuses a `workflow` repo that has none, because nothing would stop a red sync
  pull request from merging. Add the required checks, or register the repo as `ops-center` (the
  local gate). `--allow-no-required-checks` registers it anyway and prints a warning; choose it only
  knowingly, since `core-update.yml` then is the only thing that waits for CI.
- Set the repository variable `CORE_REPO` to `OWNER/build-standards-core`: it is where `core-update.yml`
  finds the core (a variable, so no file in the repo names it). Reading the core needs no credential.
- This needs one token that can open pull requests that start CI on THIS repo. Prefer a GitHub App: set the repository variable `CORE_APP_ID` (the App's client ID) and
  the secret `CORE_APP_PRIVATE_KEY` (or name an existing App secret in the variable `CORE_APP_KEY_SECRET`);
  the job mints a short-lived installation token with contents, pull-requests and workflows write on this
  repo, so no personal token exists. The App needs those three repository permissions. An account with no
  App sets the `CORE_TOKEN` secret instead, used only while `CORE_APP_ID` is unset.
- The job runs on `workflow_dispatch`; the template carries no cron. GitHub drops scheduled runs of
  private repositories, so dispatch it from the scheduler you already run (for example `gh workflow run
  core-update.yml --repo OWNER/REPO` from a job runner), or add a `schedule:` block under `on:` yourself
  (a sync keeps it) on a public repository or when a missed run is acceptable. A `workflow` repo without it: register it with its `PATH`,
  and the job syncs from the local clone and opens the pull request itself.

#### Alternative: call the reusable `core-ci` workflow (opt in)

Instead of a synced copy of `core-ci.yml`, a `workflow` repo, internal or on another account, on
GitHub-hosted or self-hosted runners, can run the same checks from a tiny caller pinned to a core release.
The copy path above is unchanged and stays the default; nothing moves a repo from one to the other.

```yaml
# .github/workflows/core-ci.yml  (keep this file name and name: core-ci)
name: core-ci
on:
  pull_request:
    types: [opened, edited, synchronize, reopened]
  merge_group:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  core-checks:
    uses: OWNER/build-standards-core/.github/workflows/core-ci-reusable.yml@<40 hex release sha> # vX.Y.Z
    with:
      runs-on: '["self-hosted", "linux", "arm64"]'   # optional
      overlay: "."                                    # optional
```

An `edited` run (a title or body change) runs every check, the same as a push to the branch: the merge
gate reads the newest result for `core-checks`, and an edit made seconds after a push cancels that run, so
a lighter edit run would report green for a commit whose full checks never completed. Keep `edited` in the
trigger list so a fixed title or body is re-validated.

- Inputs, all optional: `runs-on` (a JSON `runs-on` value; empty means the repository variable
  `CORE_CI_RUNNER`, else `ubuntu-24.04`), `overlay` (the overlay folder, `.` by default), `core-ref` and
  `core-repository` (override where the scripts come from; by default the exact commit the workflow was
  called at, read from `job.workflow_sha`, so the scripts always match the pinned workflow). No `secrets:`
  line is needed: no step reads a secret and the core is fetched anonymously.
- It runs the same ONE job with the same named steps, gating and `FULL` and `COMMITS` values as the
  template (a test keeps the two byte for byte equal): every check on a pull request event (an edit
  included, as above), every step that does not read the pull request on a merge queue entry, and only
  `core-secret-scan` on a push to the default branch. The triggers stay in the caller, so the job budget is the same:
  one job per pull request event.
- The caller's repo is checked out at the pull request head with full history; the core is fetched at the
  pinned commit into the runner's temp folder, outside the workspace, so no repo-wide tool sees it. The
  caller's own `scripts/core-ci.py` is not used; the pinned copy runs with `CORE_CI_OVERLAY` pointing at the
  caller's overlay, so `standards-local/parameters.md`, `exceptions.md` and `kit-core` are still the repo's.
- A sync (`sync-core.py`, the nightly) leaves a `core-ci.yml` that calls the reusable workflow as it is and
  prints a note; move the pinned sha to a new release yourself, or let Renovate do it (it updates a
  sha-pinned `uses:` and its version comment).
- The runner needs `git`, `python3` (3.9 or newer) and network access to github.com. A repo that cannot reach
  the public core must use the copy path.
- Access: the core is public, so any repo, private, internal or on another account, can call it with no
  setting on the core (the repository "Actions access" setting applies only to private and internal
  repos, and the API answers 422 for a public one). The calling repo's own Actions policy must allow it: when
  an organisation limits Actions to a list, add `OWNER/build-standards-core/.github/workflows/*` to the
  allowed actions and reusable workflows, pinned to a full sha.

**The required check name changes.** GitHub reports a job that calls a reusable workflow as
`<caller job name, else id> / <called job name>`. The called job is `core-checks`, so a caller job `core-checks`
reports **`core-checks / core-checks`** (verified on a real run, in the same repo and from a private repo, and
in the check-runs API). The bare `core-checks` of the synced template cannot be produced by a reusable call
whatever the caller job is named, so the merge gate must require `core-checks / core-checks` instead. Name the
caller job `core-checks` as above; any other id or `name:` gives `<that> / core-checks`. The steps are still
steps of that one job, so `core-status.py --ci` reads them as before and `required-checks` reports the
qualified name.

**Migration recipe (once per repo, one sitting).**

1. Pick the release commit: `gh api repos/OWNER/build-standards-core/commits/vX.Y.Z --jq .sha`.
2. Open a pull request that replaces `.github/workflows/core-ci.yml` with the caller above, that sha and its
   `# vX.Y.Z` comment. Its run reports `core-checks / core-checks`; the old `core-checks` stays pending
   because the new workflow no longer reports it, so the pull request cannot merge yet.
3. Once that check is green, change the required check, then merge straight away. Ruleset:

   ```sh
   gh api repos/OWNER/REPO/rulesets --jq '.[] | [.id, .name]'
   gh api repos/OWNER/REPO/rulesets/ID | jq '{name, target, enforcement, conditions, bypass_actors,
     rules: (.rules | map(if .type == "required_status_checks" then .parameters.required_status_checks |=
     map(if .context == "core-checks" then .context = "core-checks / core-checks" else . end) else . end))}' > body.json
   gh api -X PUT repos/OWNER/REPO/rulesets/ID --input body.json
   ```

   Branch protection: `gh api -X DELETE repos/OWNER/REPO/branches/main/protection/required_status_checks/contexts
   -f 'contexts[]=core-checks'`, then the same path with `-X POST -f 'contexts[]=core-checks / core-checks'`.
   A `REQUIRED_CHECKS` list in a merge gate workflow takes the new name in the same pull request.
4. Open pull requests that still run the old copy report the bare name and wait on the new one until they
   are updated from the default branch; do the swap when few are open.
5. Verify: `python3 scripts/core-ci.py required-checks` reports all jobs required, and
   `python3 scripts/core-status.py --ci` still reads each step.

Rollback is the reverse: restore the template copy of `core-ci.yml` (`sync-core.py` writes nothing for a
repo that has none, so copy it from `templates/overlay/.github/workflows/`) and require `core-checks` again.
`required-checks` prints the old and new names it finds in either direction. This recipe is for the owner or
the repo's agent to run; the core never changes a ruleset or a required check itself.

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

### `pin-file`: a repo that records the core as one line

- For a repo that holds the core only as a `KEY=<tag>` line in a plain file (for example a deploy repo
  whose host syncs the pinned release at deploy time). Register it with `--ui OWNER/REPO=pin-file:PATH`,
  then set `file` (and optionally `key`, `after`, `add`, `message`, `metrics`) in its entry in
  `consumer.json`; `hermes/pin_file.py` documents each key.
- Approval-gated. The nightly reads the pin from the default branch and, when it is behind, rewrites the
  line in a throwaway worktree, commits as the clone's noreply identity, pushes `chore/core-pin-<release>`
  and opens the pull request. The repo's own merge path takes it after the owner approves.

### Who does what, per class

The owner's rule (README "Direction", "Two consumption classes"; `ci-cd-release.md` section 11):

| | Apply-at-once (`ops-center`, `agent-home`) | Approval-gated (`workflow`, `vendored`, `pin-file`) |
|---|---|---|
| A new release | the nightly applies it at once behind the ops center's gate, rolls back on failure; a gated repo's release lands as a pull request that merges as soon as its own checks pass | arrives as a pull request: `core-update.yml`'s draft, the vendoring tool's, or the pin-file bump |
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
    "report": true,
    "consumption": true
  },
  "report_repo": "OWNER/PRIVATE-INTAKE",
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
| `ui_consumers[].mode` | `workflow`, `ops-center`, `vendored` or `pin-file`; `local` is a deprecated alias of `ops-center` | v0.36.0 (`ops-center` and `vendored` from v0.49.0, `pin-file` from v0.88.0) |
| `ui_consumers[].overlay` | the overlay folder inside the repo (default `standards-overlay`) | v0.36.0 |
| `ui_consumers[].path` | the repo's local clone; required for `ops-center` and `vendored` | v0.36.0 |
| `ui_consumers[].apply` | `false`: report only, a local job of this machine applies the core (`setup.py --report-only`); missing means on | v0.58.0 |
| `ui_consumers[].sync_head` | the head-branch prefix of the repo's sync pull request, for the consumption feed (default `chore/core-`; a vendoring tool names its own) | v0.59.0 |
| `ui_consumers[].apply_via` | `ops-center` only: `pr` lands each release as a pull request through the repo's own CI gate and merges it at once; `direct` commits to the default branch; missing: detected (a remote whose default branch requires status checks, or the repo's own pre-push guard, means `pr`) | v0.64.0 |
| `ui_consumers[].pr_timeout_min` | `ops-center` with `apply_via` `pr`: minutes to wait for the repo's own checks before the pull request is closed (default 60) | v0.64.0 |
| `report_issue` | number of the open `consumer-report` issue in the intake that the nightly updates (also `CORE_REPORT_ISSUE`); when set and open it is used before any search, so a search lag or a changed label never opens a second issue; unset: the open `consumer-report` issues of this account are searched, by the search index and then by the REST listing | v1.27.6 |
| `report_repo` | `OWNER/REPO` of the private intake that receives this account's consumer report (section 7); set it with `hermes/setup.py --report-repo OWNER/REPO` | v0.102.0 |
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
`consumer-report` issue in the private intake (`report_repo`). Every ops center renders its Core consumption panel from it
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
  `ci` job, a `test` file that carries the rule id, a dated `review` record that reports as `attested`, or a
  dated `waiver` with a reason that reports as `waived`; section 8) or stays on the operator's list. A
  stale or broken record is reported as a problem.
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
What a build learns goes into one place: this account's single open `consumer-report` issue in the
owner's PRIVATE intake repository, named on this machine as `report_repo` in `consumer.json` (set it
with `hermes/setup.py --report-repo OWNER/REPO`), created from the intake's `consumer-report`
template on the first report run. The core is public, so a report is never filed on it: with no
`report_repo`, a `report_repo` equal to the core, or one that is not private, the nightly files nothing
and says why.

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

## 8. Rule status, proofs and the repo checks

`python3 scripts/core-status.py` is the one report on an overlay: the pin, one status per registered rule,
exceptions expiring within 30 days and problems. `--json` prints the machine form, `--latest` adds the rules
that are new or changed in the newest release, `--ci` reads the `overlay-ci` results from the repo's latest
default-branch run (needs `gh`), `--require-ui-adopted` and `--require-lint-config` exit 1 for the drift
workflow, and `--vendored OWNER/REPO` reads a vendored repo's record. It never changes a file.

### The eight statuses

| Status | Means | How a consumer gets it |
|---|---|---|
| `pass` | no finding: a lint rule with zero findings, a `repo-check` rule with no finding, an `overlay-ci` job that succeeded, or a rule the core proved before release (`core-ci`) | nothing to record; fix the finding |
| `proved` | a `ci` or `test` proof record is valid; counted apart from `pass`, because the script did not watch it pass | a `ci` or `test` record in `standards-local/proofs.json` (a `review` alongside it is allowed and noted) |
| `attested` | a person looked: a dated `review` record that expires | a `review` record |
| `waived` | the rule is set aside for this repo with a reason; never counted as proof and it expires | a `waiver` record |
| `not_applicable` | a rule the core proves on the kit, in an app that does not adopt the kit whole (below); or a rule or group the repo declares has no surface here, with a reason ("Declaring rules that do not apply") | nothing for the kit case; a `$not_applicable` entry for the declared case |
| `excepted` | findings sit inside a ratchet baseline or an active exception | a row in `standards-local/exceptions.md` that names the rule (README "Source of truth and explicit exceptions") |
| `unverified` | nothing proves it yet: a `test` or `review` rule with no record, or an `overlay-ci` result that was not read | record a proof, or leave it on the operator's list |
| `fail` | a finding above the baseline, a `core-ci.yml` or `lint-sweep.yml` job the rule needs is not installed, or a declared stack has no lint config | fix it; no record can turn a `fail` into anything else |

A proof record only ever replaces `unverified`. The rule kinds in `standards/rules.json` are `lint`,
`core-ci`, `overlay-ci`, `repo-check`, `test` and `review`.

### Recording a proof: `standards-local/proofs.json`

The file is consumer-owned. Every record is `"<rule id>": {"kind": ..., "ref": ...}`; paths are from the
repo root, dates are `YYYY-MM-DD`.

```json
{
  "$max_review_age_days": 180,
  "rbac.1.3": {"kind": "ci", "ref": "ci.yml#route-guard"},
  "web-ui.20": {"kind": "test", "ref": "app/test/rail.test.ts"},
  "ci-cd-release.7": {"kind": "review", "ref": "docs/reviews/deploy.md", "date": "2026-10-20", "reviewed_by": "owner"},
  "web-ui.0.3": {"kind": "waiver", "ref": "docs/waivers/glow.md", "date": "2026-10-20", "reason": "the app draws no glow surfaces", "reviewed_by": "owner"}
}
```

| Kind | `ref` | Also needed | Reports as |
|---|---|---|---|
| `ci` | `<workflow file>#<job>` of a workflow installed in `.github/workflows/` (a job id, or a `core-` step of `core-ci.yml`) | nothing | `proved` |
| `test` | a test file that exists | the file carries the rule id, as a comment such as `core-rule: web-ui.20` | `proved` |
| `review` | the review record | `date` within `$max_review_age_days` (default 180); `reviewed_by` (a missing one is a warning) | `attested` |
| `waiver` | the waiver record | `date` (same expiry), `reason` and `reviewed_by`, all required | `waived` |

A rule whose proof tests only check that a risk owner and decision record are named (for example
`secrets-and-credentials.1.9` and `scripting-powershell.1.10`) must also carry a dated `review` record from
the accountable owner.

**More than one record for a rule.** The value may be a list, so a rule carries its test and its review
together and the review does not replace the test. A single object works exactly as before.

```json
{
  "example-rule.1.2": [
    {"kind": "test", "ref": "app/test/owner.test.ts"},
    {"kind": "review", "ref": "docs/reviews/owner.md", "date": "2026-10-20", "reviewed_by": "owner"}
  ]
}
```

| Records on the rule | Reports as |
|---|---|
| one object, or a list of one | as the table above (`ci` or `test` is `proved`, `review` is `attested`) |
| `ci` or `test`, plus a current `review` | `proved`; the note names both records |
| `ci` or `test` alone | `proved`, unless the registry marks the rule `requires_review: true`; then `unverified` with a note that a dated review is also needed |
| `review` alone | `attested` |
| `ci` or `test`, plus an expired or broken `review` | the review is a problem line and proves nothing; the rule reads as the `ci` or `test` alone row |
| a malformed or broken entry in the list | a problem line naming its place (`rule[1]`); the other entries still count |

The strongest valid `ci` or `test` record is the one reported; a `review` beside it is a companion and is
not held to the "weaker than the rule's check" limit. `--ci` exit behaviour is unchanged. Today no rule in
the registry carries `requires_review`, so a test alone still reads `proved` everywhere; the marker exists
for a later release that names the rules whose tests only check that an owner is recorded. The reserved
keys (`$max_review_age_days`, `$description`, `$not_applicable`) are never read as proofs.

A proof's kind must be the rule's own check kind or stronger (`ci`, then `test`, then `review`), so a
`review` record cannot prove a `test` rule; a `waiver` can set aside any rule that would read `unverified`.
A missing file, an unknown rule id, a weaker kind, a stale date or a waiver without a reason is listed
under problems and proves nothing. `unverified` rules are the work list; the verified ones need no file.

**The `core-rule: <id>` tag and `PROOF_TAG_ENFORCED`.** A test proof must name its rule, so the proof
fails when the test file is replaced or the tag removed. Today a missing tag keeps the proof and adds a
`WARNING` line (a `warnings` entry in `--json`). `PROOF_TAG_ENFORCED` is a constant at the top of the
synced `scripts/core-status.py`: a core release sets it to `True`, and from then a missing tag is a
problem and the proof stops counting. A consumer never edits it (the file is core-owned); tag every test
proof now so the release that flips it changes nothing. The release notes say when it flips.

### Kit-test proofs: `not_applicable` without UI adoption

Nine rules are proved by a test the kit already ships, run in the core before release, and carry
`requires: ui-adoption` in the registry: `web-ui.0.8` (toast Undo), `web-ui.12` (theme init), `web-ui.18`
(count-up), `web-ui.19` (rail state and pin), `web-ui.22` (changelog parser), `web-ui.24` (axe on the shell
and overlays in both themes), `web-ui.26.1` (per-app dismissal keys), `web-shell.3` (generated registry) and
`web-shell.5` (module CSS scope). An app that adopts the kit whole (the UI verdict `adopted`) reads `pass`
for them; any other app reads `not_applicable`, counted apart in the summary. A proof record does not
change a `not_applicable` rule: the way to a `pass` is to adopt the UI (`kit/MIGRATION.md`).

### Declaring rules that do not apply: `$not_applicable`

Scope by stack (the `Stacks` row of `parameters.md`) is coarse: a single-operator local app is `web` and
still has no role model, no directory surface and no shell. Such a repo lists the rules or groups that have
no real surface in it, in the same `standards-local/proofs.json`, under one reserved key:

```json
{
  "$not_applicable": [
    {"rule": "rbac", "reason": "one operator, no roles or permissions in the app", "date": "2026-10-27", "reviewed_by": "owner"},
    {"rule": "web-shell", "reason": "single page, no shell or module registry", "date": "2026-10-27", "reviewed_by": "owner", "until": "2027-04-27"},
    {"rule": "web-api-runtime.5.3", "reason": "no directory lookups", "date": "2026-10-27", "reviewed_by": "owner"}
  ]
}
```

- `rule` is a rule id or a group prefix. A prefix matches whole dotted segments: `rbac` covers `rbac` and
  every `rbac.*`; `web-api-runtime.1` covers `web-api-runtime.1` and `web-api-runtime.1.4`, never
  `web-api-runtime.10`.
- `reason`, `date` (`YYYY-MM-DD`) and `reviewed_by` are required. `until` is optional; from the day after it
  the entry is expired.
- A covered rule that would read `unverified` reads `not_applicable` with the reason beside it, counted apart
  from `waived`. A rule that has a result (`pass`, `fail`, `excepted`) or a proof (`proved`, `attested`,
  `waived`) keeps that status: the declaration never hides a finding or replaces a proof.
- Every entry is listed under `N/A` in the report and as `not_applicable_declared` in `--json`, with how
  many rules it covers. `core-status.py --ci` exits 1 if an entry lacks a reason, `reviewed_by` or `date`,
  is expired, matches no rule, or covers a protected rule; an entry with a problem applies to nothing, so
  its rules go back to `unverified`. Without `--ci` the same lines are `PROBLEM`s and the exit code is
  unchanged.
- Guard: no entry may cover a rule of `secrets-and-credentials` or `automation-safety`, whatever the
  prefix, unless the registry marks that rule `"applicable_optional": true`. Use it only for a rule with no
  surface at all; a rule the app breaks is an exception, not a declaration.

How it differs: a **waiver** sets aside a rule that applies but the repo will not meet, needs a record file
and expires like a review. An **exception** (`exceptions.md`) accepts a known finding for a rule that
applies, with an expiry. A **declaration** says the rule has nothing to apply to; no record file, and it
is the only one of the three that covers a whole group. A kit rule's `not_applicable` (above) comes from
the UI verdict, not from a declaration.

### The `repo-check` kind: RC001 to RC022

A `repo-check` rule is proved by a static check of the repo's own tracked files, `scripts/repo_checks.py`.
`core-status.py` runs the check of every such rule: no finding is `pass`, a finding is `fail`, an active
exception that names the rule is `excepted`, and `unverified` only when the check cannot run. A check
passes when the repo holds nothing the rule governs (no migrations, no deploy workflow) and fails on a
violation or, where the rule demands a thing, on its absence. A line carrying `core-exception: EXC-NNN` is
skipped. The synced copies (`standards-core/`, `kit-core/`, `lint-core/`, `tokens-core/`), build output
and dependency folders are not scanned.

| Check | Rule | Reports a finding when |
|---|---|---|
| RC001 | `automation-safety.1.9` | a script or workflow kills a process by name or pattern |
| RC002 | `pr-review-and-merge.1.6` | a merge command or merge endpoint call carries no head sha |
| RC003 | `ci-cd-release.4` | a renovate config auto-merges major updates |
| RC004 | `ci-cd-release.5` | a workflow with a trusted trigger checks out or runs pull request code |
| RC005 | `web-api-runtime.3.3` | hosting or infrastructure config holds a platform CORS origin list |
| RC006 | `data-safety-sqlite.2.10` | a SQLite repo's deploy workflow has no queueing concurrency group or no health step that names the sha (a static-site or Vercel-only deploy is carved out) |
| RC007 | `data-safety-sqlite.2.12` | a migration is destructive, or adds a NOT NULL column without a default |
| RC008 | `identity-and-people-data.1.7` | a fixture email address is outside the reserved test domains |
| RC009 | `web-client-runtime.1.2` | the auth redirect is handled in more than one non-test source file |
| RC010 | `ci-cd-release.9` | a secret a workflow reads is named in no documentation page |
| RC011 | `secrets-and-credentials.1.4` | a checkout of another repository has no ssh-key |
| RC012 | `scripting-python.1.2` | an import outside the standard library is not in a pinned requirements file with a reason comment, or in a declared dependency list with a lock file (a `pip-compile --generate-hashes` file counts as a lock only when every line carries a hash) |
| RC013 | `ci-cd-release.6` | a stateful deploy workflow neither re-runs CI nor waits on a CI job, or has no health check |
| RC014 | `web-ui.9` | a web app's test suites never run axe or never cover both themes |
| RC015 | `web-ui.25` | an app mounts an app shell and renders no build card |
| RC016 | `web-build.8.1` | a package has no verify script, or one that skips a `check:*`, typecheck, lint, build or test script the package defines |
| RC017 | `scripting-python.1.3` | a subprocess call passes a secret-named value or flag as an argument |
| RC018 | `web-client-runtime.4.2` | a vite config has no `manualChunks` |
| RC019 | `web-client-runtime.4.1` | a bundled app has no bundle size budget check (a size-limit or bundlewatch config, or a budget script) |
| RC020 | `web-client-runtime.4.3` | a vite config has no `assetsInlineLimit` |
| RC021 | `web-client-runtime.5.1` | an app's client code builds the bearer header in more than one file |
| RC022 | `rbac.3` | an app compares permissions or roles by hand in more than one non-test file |

RC021 and RC022 group files per app (`apps/<name>`, `packages/<name>`, `services/<name>`). Each rule's
acceptance line says exactly what its check proves and what stays with review.

Run them locally from the repo (the overlay's `scripts/` folder):

```sh
python3 scripts/repo_checks.py              # every check: one line each, exit 1 on any finding
python3 scripts/repo_checks.py --list       # each check id and the rule it proves
python3 scripts/repo_checks.py --json       # findings as JSON
python3 scripts/repo_checks.py --root DIR   # another repository (the git top level of DIR is used)
```

In a clone of the core the script is `templates/overlay/scripts/repo_checks.py`.

## 9. UI lint config and scrolling

**Lint config.** `standards-local/ui-lint.json` tells `python3 lint-core/ui_lint.py` what to read:

```json
{ "paths": ["src"], "exclude": [], "token_files": [], "data_palettes": [], "baseline": null }
```

`paths` and `exclude` pick the files; `token_files` adds files allowed to hold colour literals (the synced
`tokens-core/` always is); `baseline` is only for an app that runs the lint without taking the kit (a UI
consumer may not keep one: `core-status.py --require-ui-adopted` and the lint refuse it). `data_palettes`
lists globs of files that hold data colours (a chart theme, a table of category colours): the colour
literal rule UI003 is skipped in them and every other rule still applies. A colour literal in any other
file still fails. A one-sided border under 2px in a neutral grey (equal channels, or saturation of 10% or
less) is a hairline divider and UI001 does not flag it; a coloured hairline, a border of 2px or more and
every accent edge bar still fail. Suppress a finding only with `core-exception: EXC-NNN` (or `edge-ok` for
a data mark that looks like an edge bar, UI001 only); there is no switch that turns a rule off. The full
rule table is `lint/README.md`.

**Scrolling.** The standard is `web-ui.md` rule 0.12 (`web-ui.0.12`, a review rule): the page body is one
vertical scroll container, a board is sized to the window with a floor and scrolls on its own edge, a wide
table has a capped scroll area with a floor, a page header is never capped with a viewport fraction, and
`overflow: hidden` is never put on a flex parent to fit a board. The kit carries the sizing, so use it
instead of local CSS:

| Kit part | What it does |
|---|---|
| `page-scroll` class | makes the page body the one vertical scroll container (full height) |
| `Table` `capped` prop | limits the table to the window height less 15rem, with no floor so a short table stays short, as a named focusable region so the keyboard can scroll it |
| `LaneBoard` `fit` prop | sizes the board to the window height less 6rem, never under 360px, scrolls sideways on the board edge and each lane on its own |

`capped` and `fit` default to off, so an existing use is unchanged. The proof is loading every route that has a
board or a wide table at a window about 700px tall; record it as an `attested` review in `proofs.json`.
Details are in `kit/README.md`.

## 10. Releases and versions

- A release is a tag `vMAJOR.MINOR.PATCH` plus a GitHub Release. Nobody tags by hand. When a pull request
  that adds a new top `CHANGELOG.md` entry merges, `release.yml` (`checks/auto-release.py`) creates the
  annotated tag on the merge commit, creates the Release with that entry as its notes, and calls
  `gallery-release.yml` to attach `kit-gallery-<tag>.zip`. A push with no new top entry does nothing. The
  top version must be greater than the latest tag and an existing tag is never moved: a mismatch fails the
  run. `python3 checks/auto-release.py --dry-run` prints the decision for the current commit and changes
  nothing.
- The entry heading is `## YYYY-MM-DD (vX.Y.Z, short title)`, newest first. A rule that becomes stricter, or
  a parameter that becomes required, is a major release; a new rule, doc or optional parameter is a minor
  release; a wording fix or clarification is a patch release.
- The version is assigned at merge, not when you start. Just before you open the pull request, and again
  before it merges, read the latest tag and the top entry on `main` (`git fetch origin` then
  `git ls-remote --tags --sort=-v:refname origin 'v*'` and the first heading of `origin/main:CHANGELOG.md`).
  If another change took your number, merge `origin/main` into your branch, renumber your entry to the next
  free version, and run the checks again. Never leave two entries with one version.
- Consumers move only to published releases. Read the `CHANGELOG.md` entries between your pin and the
  newest release before moving the pin.
- Monitoring. An external monitor, outside this repository, watches the releases and the pins of the
  consumers. The core runs none of it and a consumer needs nothing from it; the in-repo signal is the
  consumer's own `check-core-sync.py --latest` (exit 3 when behind).

## 11. Reporting and contributing

- The core is public. Reading it, syncing it and calling its reusable workflow need no account, invitation
  or token.
- A build's agent never opens a pull request on this repo and never files a report on it. Findings go to the
  account's one open `consumer-report` issue in the owner's private intake repository (section 7). The owner
  approves items there; the account that owns an approved item opens the core pull request, links the issue
  with `Refs #N` or `for #N` (never a closing keyword in front of a report issue: `check-closing-refs.py`
  fails it), and merges it once `ci` and `visual` pass.
- A pull request from a fork of the public core runs the same checks. `merge-pr.py` refuses a branch on a
  fork (it cannot rewrite it), so such a pull request is merged by an owner account, and one with no
  approved item behind it is closed unmerged (CONTRIBUTING.md).
- A vulnerability is reported privately through the repository's Security tab (`SECURITY.md`), never as an
  issue.
- Every change needs a dated `CHANGELOG.md` entry, plain ASCII, no business names and no real email
  addresses (CONTRIBUTING.md). Commit with a GitHub noreply address and enable the hook once per clone:
  `git config core.hooksPath checks/hooks`.

## 12. The update flow for an account that only has the public docs

This is the flow for a repo on its own GitHub account, with no access to anything of the owner's. It needs
`git` and Python 3.9 or newer; `gh` is optional (the scripts fall back to plain `git` over HTTPS).

1. Check the core is reachable: `git ls-remote --tags https://github.com/OWNER/build-standards-core.git`.
2. Tell the scripts where the core is. In CI set the repository variable `CORE_REPO` to
   `OWNER/build-standards-core`; on a machine export `CORE_REPO` (or run `hermes/setup.py`, which writes
   `core_repo` into `consumer.json`). The lock file never names it. `CORE_CHECKOUT` is optional (see
   "Adopting into a repo that has history").
3. Adopt once: copy `templates/overlay/` into the repo, fill `standards-local/parameters.md`, run
   `python3 scripts/sync-core.py latest`, and commit the lock, the synced copies and the scripts (README
   "Consuming the core"). Put `core-ci.yml` in the root `.github/workflows/` and require `core-checks` in the
   merge gate (`python3 scripts/core-ci.py required-checks`).
4. See where you stand: `python3 scripts/check-core-sync.py --latest` prints `pinned vX, latest vY` and exits
   3 when behind. `python3 scripts/core-status.py` is the rule report.
5. Update. By hand: `git switch -c chore/core-sync`, `python3 scripts/update-core.py` (prints the new tag
   when it changed files, nothing when current), run `python3 scripts/check-core-sync.py`, commit, open the
   pull request and let CI run. Automatically: dispatch `core-update.yml` from your scheduler
   (`gh workflow run core-update.yml --repo OWNER/REPO`); it needs the token lane in section 3 (the App
   variable `CORE_APP_ID` and secret `CORE_APP_PRIVATE_KEY`, or the secret `CORE_TOKEN`).
6. Hold-free means no one has to remember to release a held pull request. `core-update.yml` opens the sync
   as a draft until someone marks it ready (`gh pr ready N`); that is the default (`CORE_UPDATE_MERGE`
   unset or `approve`). An account that is its own approver sets the variable `CORE_UPDATE_MERGE` to `wait`
   (the job waits for every check on the head commit to be green on two reads, then merges that exact commit
   with `merge-pr.py --match-head-commit`) or `gate` (the repo's own merge gate merges it once the required
   checks pass). A red check or the `CORE_UPDATE_WAIT_MINUTES` timeout (default 60) leaves the pull request
   open. GitHub's auto-merge is never used.
7. Read the `CHANGELOG.md` entries since the old pin, list any rule your apps now violate, land the
   standards first and the code fixes after.

### Adopting into a repo that has history (new repo traps)

- Latest release. `python3 scripts/sync-core.py latest` (and `update-core.py`) pick the highest strict
  `vX.Y.Z` tag by semantic version. A tag that is not exactly that shape, and the tag GitHub flags as the
  "latest release", are ignored, so an old release published last cannot win. An explicit tag
  (`sync-core.py v1.28.0`) needs only `CORE_REPO` (or `consumer.json`). `CORE_CHECKOUT` is optional: set it
  only to sync from an existing local clone with no network (it must hold the tag: `git fetch --tags`);
  with it set and no `CORE_REPO`, the name is read from that clone's `origin` remote.
- Workflows of the same name. A sync refreshes `core-ci.yml`, `core-drift.yml`, `core-update.yml` and
  `lint-sweep.yml` only when the repo's file is core-managed: it carries the `# core-managed` marker line, or
  it is an older synced copy (first line `name: <template name>` that refers to the overlay scripts). Any
  other file with that name is left untouched and the template is written next to it as `<name>.core-new`
  (GitHub ignores it); the sync prints `diff -u <file> <file>.core-new`. Merge the parts you want, add the
  `# core-managed` line, and delete the `.core-new` file. `sync-core.py --strict` (or `CORE_SYNC_STRICT=1`)
  exits 1 after the sync when it skipped a file, for CI. Copy `templates/overlay/` by hand with the same
  care: never overwrite a workflow that lacks the marker.
- Merge gate list. The sync rewrites a `REQUIRED_CHECKS` list only when it cannot make the gate wait on a
  missing check: the default branch already defines the `core-checks` job, or the default branch has no
  workflow with a `REQUIRED_CHECKS` list (this pull request adds the job and the gate together). In any other
  case the list is left unchanged and the sync prints `REQUIRED_CHECKS: <exact replacement>` and the order:
  merge the pull request that adds `core-checks` first, then change the list in a second pull request.
- UI not adopted yet. Set the parameter `UI adoption stage` in `standards-local/parameters.md` to `none` or
  `partial`: the drift workflow's `core-status.py --require-ui-adopted` step then prints `ui: N/A` and passes
  instead of failing, so `core-drift.yml` can land before the UI series. Set it to `adopted` (or empty) when
  the UI is whole; empty is the default and keeps the original behavior (a partial UI fails).

### Existing non-ASCII content (the ASCII check)

The rule is plain ASCII in every tracked text file (pr-review-and-merge.md 1.19). Get green in this order:

1. Fix the source. Replace the character with an escape that renders the same glyph (`\u00e9` in strings, JSON and
   JavaScript, `&#233;` in HTML or XAML, `` `u{00e9} `` in PowerShell 7 strings or `[char]0x00e9`). This is the
   answer for anything you own.
2. Generated or vendor files you cannot edit: a time-boxed `excepted` row in `standards-local/exceptions.md`
   for rule `pr-review-and-merge.md 1.19`, with a path or glob in `Scope`, a reason, an owner and a `Review
   by` date. Hits inside the scope are warnings until that date, then fail again.
3. A path the check should never read (a vendored folder that is tracked, an imported data dump): list it
   in the `## ascii_ignore` table of `standards-local/parameters.md` with a reason, one row per path, folder or
   glob. Every run prints each ignored file and its reason; a row with no reason fails the check. Script and
   XAML files cannot be listed.

   | Path | Reason |
   |---|---|
   | vendor/legacy-docs/ | imported archive, owned upstream |

   Narrowing the check with the `ASCII check patterns` parameter is the blunt tool and is not the way out.
   A repo that declares nothing sees no change.

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

## 13. What READY means, and troubleshooting

**A pull request to the core is READY** when it is opened as a normal (not draft) pull request after every
check in `.github/workflows/checks.yml` has passed locally, the changelog top entry carries the next free
version, and `ci` and `visual` are the checks that remain. Locally, from the clone:

```sh
python3 checks/check-sanitised.py --diff origin/main      # also run with no argument for the full tree
python3 checks/check-consumer-neutral.py --diff origin/main
python3 checks/check-ascii.py
python3 checks/check-placeholders.py
python3 checks/check-links.py
python3 checks/check-rules.py
python3 checks/check-hermes-skills.py        # regenerate with python3 hermes/build_skills.py when a source doc changed
python3 checks/check-changelog.py origin/main
python3 checks/check-authors.py origin/main
python3 checks/check-closing-refs.py origin/main
python3 -m unittest discover -s tests -p "test_*.py"
ruff check . && ruff format --check .
```

README "Checks" lists the rest (tokens, lints, kit). Run the unit tests under the oldest interpreter too
(`/usr/bin/python3` on macOS is 3.9), not only the newest.

**A consumer repo is READY** when `python3 scripts/check-core-sync.py` prints `core sync: clean`,
`python3 scripts/check-exceptions.py` and `python3 lint-core/ui_lint.py` pass, `python3
scripts/core-status.py --require-ui-adopted --require-lint-config` exits 0 (a UI repo), `core-checks`
(or `core-checks / core-checks`) is required in the merge gate and green, and no rule is `fail`. The
`unverified` list is the open work, not a blocker.

| Symptom | Cause | Fix |
|---|---|---|
| The pull request is `UNSTABLE` and nothing is running; one check shows cancelled | a non-required check was cancelled (an edit seconds after a push cancels the earlier run) and the merge workflow did not run again | `gh run rerun <run id>`, then `gh workflow run automerge.yml --repo OWNER/build-standards-core`. Check `gh pr view N --json state,mergeStateStatus` no more often than every 3 minutes |
| The merge gate waits forever on `core-checks` after the move to the reusable workflow | the called job reports `core-checks / core-checks` | require the qualified name (section 3, migration recipe) |
| `core-ci.yml has no job core-python` and the `overlay-ci` rules fail | the repo's `core-ci.yml` predates the `core-` job names | `python3 scripts/sync-core.py latest`, then `python3 scripts/core-ci.py required-checks --fix` |
| A sync pull request fails `core-required-checks`, or the merge gate waits on a name that no longer exists | a core-ci job was renamed and the gate (a `REQUIRED_CHECKS` list in the auto-merge workflow, or a ruleset) still lists the old name | `python3 scripts/core-ci.py required-checks --fix` rewrites the list in the workflow (or prints the exact line, file and line number when it is not a plain list) and prints the ruleset commands; `sync-core.py` already applies the list rewrite in the sync pull request. See "Gate and workflow disagree" below |
| `Could not read OWNER/build-standards-core at <ref>` | the ref does not exist, `CORE_REPO` is unset or wrong, or no route to github.com | check the tag and `CORE_REPO` (step 2 of section 12) |
| `DRIFT` or `content hash ... does not match the lock` | someone edited a synced copy, or a formatter reflowed it | rerun `sync-core.py` and commit both; exclude the synced folders from formatters (README) |
| `version 3.9 was not found` on a runner | a job set up Python 3.9 on an image that has none (`ubuntu-latest`) | run on `ubuntu-24.04`, which the template and reusable workflows default to; `CORE_RUNNER` and `CORE_CI_RUNNER` override |
| A script fails with a syntax or import error on the system Python | a construct newer than 3.9 | Python 3.9 is the floor for every shipped script and for core CI: no `match`, no `X | Y` types at runtime without `from __future__ import annotations`, no `tomllib` without a fallback |
| `check-closing-refs` fails | a closing keyword sits in front of a `consumer-report` reference | write `Refs #N` or `for #N` |
| A proof reads `WARNING ... does not name the rule` | the test file lacks the rule id | add the comment `core-rule: <rule id>` |

### Gate and workflow disagree (bootstrap)

A merge gate kept as a list in the auto-merge workflow has a chicken and egg case: the workflow that runs
is the copy on the default branch, so a pull request that renames a core-ci job and fixes the list is
judged by the old list and can never merge itself. Break it once, by hand: review the fix pull request,
confirm its `core-checks` and `core-required-checks` are green, then merge it with squash and pin the merge
to the reviewed head, for example `gh pr merge N --squash --match-head-commit <reviewed head sha>`
(or `python3 scripts/merge-pr.py N --match-head-commit <sha>`). Never merge with `--admin` without the sha.
Afterwards the default branch holds both, and the gate agrees again.

To avoid it for good, copy `templates/overlay/.github/workflows/automerge.yml`: it reads the required core
job names from the synced `core-ci.yml` (`core-ci.py required-names`), so a rename reaches the gate in the
same sync pull request, and `REQUIRED_CHECKS` lists only the repo's own checks.

Ordering: a job the gate newly requires must already exist (run) on the default branch before the gate
lists it, or every pull request waits on a check that never reports. Merge the pull request that adds the
job first, then the gate change. `sync-core.py` and `required-checks --fix` print this order when core-ci
job names change.

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
- Never tag by hand. A merged pull request that adds a new top `CHANGELOG.md` entry is released
  automatically (section 10), and consumers move only to published releases.
- Scope: the Hermes part of the standard covers only what is listed in `hermes/tools.json`.
  Whether something found on this machine belongs in the core is decided by one test
  (CONTRIBUTING.md "Does it belong in the core?"): would it help another consumer's agent that
  knows nothing about this machine, carrying no name, path or value of this estate? Both yes: report
  it (section 7). Either no, as with smart-home or personal tools: it stays local and is not a gap
  in the core.

## Where things are

| Need | File |
|---|---|
| What the core is for, the five ways, the three channels and the two consumption classes | README "Direction" |
| The consumption feed and the ops center's approval desk | `standards/local-ops-app.md` section 19, `hermes/consumption.py` |
| Rules for code, UI, CI and scripts | `standards/` and `standards/rules.json` |
| Hermes settings and plugins, with reasons | `hermes/configurations.md` |
| Token efficiency policy for an agent home | `hermes/token-efficiency.md` |
| Per-tool decisions the nightly job installs | `hermes/tools.json` |
| How a UI repo consumes the core | README "Consuming the core", `templates/overlay/` |
| How a build reports to the core | the private intake's `consumer-report` template (`report_repo`), `CONTRIBUTING.md` |
| How to contribute | `CONTRIBUTING.md`, `hermes/README.md` section 4, sections 10, 11 and 13 above |
| Rule statuses, proof records, the `RC001` to `RC022` checks | section 8, `standards/rules.json` |
| UI lint config, scrolling, kit scroll parts | section 9, `lint/README.md`, `kit/README.md` |
| The overlay's own files and CI steps | `templates/overlay/README.md` |
| Updating from a repo with only the public docs | section 12 |
