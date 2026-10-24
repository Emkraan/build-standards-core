# PR Review and Merge Standard

Version: 1.4 | Last reviewed: 2026-10-21 | Status: current | Scope: all

How a change travels from a working tree to `main`: what gets staged, how it is described, how
review findings are answered, which holds a person signs off and which automation fixes, and how
the merge is pinned to what was reviewed. The CI checks themselves, commit types and the
auto-merge workflow are defined in the [CI/CD and Release Standard](ci-cd-release.md). This doc is
the source of truth for the flow. Where a reference implementation differs, the implementation is
fixed, or the consumer records an explicit exception (README, "Source of truth and explicit
exceptions").

Related: [Automation Safety](automation-safety.md), [Docs and Changelog](docs-and-changelog.md),
[Live Actions](live-actions.md) (the merge button in an operator UI),
[Local Ops App section 11](local-ops-app.md#11-worktree-workflow-for-parallel-changes) (worktrees).

---

## 1. Rules

1. **Commit only the files you changed, by name.** Stage and commit with explicit paths (`git add -- <files>`, `git commit -- <files>`), from a worktree per change. Never `git add -A`, `git add .` or `git commit -a`.
   - Prevents: another session's half-done work, a secret or a generated file riding into a commit.
   - Acceptance (review): the PR's file list matches the change and `git diff --stat` was read before the commit.
2. **Conventional Commits for every commit and PR title.** Types and the semver mapping follow [CI/CD section 3](ci-cd-release.md#3-conventional-commits-and-semver).
   - Prevents: versions and release notes that cannot be computed from history.
   - Acceptance (overlay-ci): the `core-ci.yml` jobs `core-pr-title` and `core-commitlint` pass.
3. **Every change carries its changelog entry.** When the docs home is the repo, the same PR adds a dated, versioned entry in the changelog of the thing it changes. When the docs home is elsewhere, the entry is added there the day the change ships, and the PR links the pending entry or says where it will land ([Docs and Changelog](docs-and-changelog.md) rule 1 and rule 3). One exemption: a PR opened by the core sync (it only refreshes core-owned overlay files and the lock) needs no entry of its own, because the core's changelog records the change. The exemption is by the sync's author and by changed paths only (core-owned paths), never by title or label.
   - Prevents: releases nobody can explain later, and changelogs rebuilt from memory.
   - Acceptance (review): the PR links or contains the entry for its version.
4. **No tool attribution, owner identity only.** Commits, PR text and comments carry no assistant or tool attribution and no generated-by lines, and commits use the owner's approved address.
   - Prevents: history that misstates who is accountable, and personal addresses leaking into a shared repo.
   - Acceptance (overlay-ci): the `core-ci.yml` jobs `core-attribution` and `core-identity` pass ([CI/CD section 2](ci-cd-release.md#check-details)).
5. **The main branch is protected.** Nobody pushes to `main`. Changes land by PR after the required checks pass, by the merge method the repo declares (squash, rebase or a merge queue), through a ruleset or the auto-merge gate. The repo records its merge method and whether it uses a queue in its parameters; a rule that says "squash" below means "the declared method". With a merge queue, every required check also triggers on `merge_group` and one result job aggregates them, so the queue and the PR see the same gate.
   - Prevents: unreviewed commits on the branch every release is cut from.
   - Acceptance (review): the ruleset or auto-merge gate lists the required checks and no direct push is possible.
6. **Merges are pinned to the reviewed head.** Every merge names the head commit that was reviewed (`--match-head-commit <sha>` or the API `sha` field), and every push and merge re-reads the PR state immediately before it runs.
   - Prevents: a commit pushed after review slipping into `main`, and a fix pushed to a branch whose PR already merged.
   - Acceptance (review): merge commands and endpoints pass the head sha, and tooling refuses a moved head.
7. **Review findings are verified, not obeyed.** Check each finding against the code, fix every real one, refute the rest with evidence (path and line, a run log, live state), and post one disposition reply per round. Stop pushing when the only findings left are re-raises already answered.
   - Prevents: speculative fixes that buy another review round and new defects, and real defects dismissed as noise.
   - Acceptance (review): each high finding has a fix commit or an evidence-backed refutation in the disposition reply.
8. **A triage marker attests to one head.** A triage reply ends with a hidden marker naming the head sha and the finding ids it answers (`<!-- triage:<sha> H1 H3 -->`). The merge lane clears only the ids named, so a reply that answers one finding never clears another, and a marker with no ids clears nothing. The lane and any CI re-review planner parse the marker with one reference pattern (`<!-- triage:<sha> <ids> -->`, ids optional and space-separated), kept in one shared module with a test over every form. The core ships that module as the overlay's `scripts/triage_marker.py` (`parse`, `cleared`, `--self-test`); a consumer imports it rather than writing a second pattern. Post it only after that head's review is in, and never on a reply that promises a fix.
   - Prevents: a merge lane merging before the promised fix lands, or on a head whose new findings nobody read.
   - Acceptance (test): the merge lane ignores a marker for another sha and a marker older than the review of the head, and the lane and the planner give the same result for a marker with ids, one without ids and a malformed one.
9. **Policy holds go to the owner, problems go to the fixer.** A hold that needs a person's sign-off (a policy rule, a delete, an access grant, a gate that fails only because a change is intended) shows an approve button. A real problem (red check, conflict, untriaged finding) goes to the fixer and never shows a merge button.
   - Prevents: a "merge anyway" button that is really an ignore option, and sign-offs sent to auto-fix, which gives up into a dead end.
   - Acceptance (test): the hold classifier tests cover policy-only, problem-only and mixed holds.
10. **Working PRs get no action buttons.** While checks run, a review is pending or a fix session is on the PR, the UI shows a working indicator and only a link to the PR.
    - Prevents: a merge, approval or discussion that disrupts running work or acts on a head about to change.
    - Acceptance (test): the PR row renders no action button when its working flag is set.
11. **Delegated work is verified before merge.** The reviewer of work from a sub-agent, a bot or another account re-runs the checks locally (including private ones CI cannot run), reads the full diff and lists the PR's commits.
    - Prevents: merging a commit nobody wrote on purpose, or a check that passes in CI only because CI lacks the private input.
    - Acceptance (review): the merge record names the local checks run and the commits listed.
12. **Never weaken a gate to get green.** A fix never lowers a threshold, adds a skip marker or ignore glob, or edits a review policy, workflow or ruleset to pass. A check that is red for an unrelated infrastructure reason is rerun (failed jobs only) and stays red until it passes or the owner bypasses it.
    - Prevents: gates that quietly stop guarding anything.
    - Acceptance (review): the diff of a fix PR touches no gate configuration, or a separate reviewed PR does.
13. **Preflight runs every gate before the push.** Before a change is pushed or its PR opened, one local command runs what the PR will face: the repo's own tests, linters and builds for the changed files, hygiene checks (ASCII, version bump, branch name against the repo's one branch pattern parameter, commit identity, no secret-shaped values), a conflict check against the base, the merge lane's policy rules as a dry run, and an overlap check against other open changes that touch the same infrastructure roots. The dry run prints the sign-offs the owner will be asked for, so they go in the PR description. The preflight fails closed on any read error with its own exit code, and never writes outside the working copy's git directory.
    - Prevents: review rounds and fix sessions spent on failures the author could have seen locally, and sign-offs the owner first learns about at merge time.
    - Acceptance (test): the preflight tests cover a passing change, each failing gate, a policy dry run that lists sign-offs, an overlapping open change and a read error that exits with the distinct code.
14. **Self-review uses the reviewers' own prompts and is bound to the diff.** The author reviews the full diff against the same prompts the automated reviewers use plus the team's finding catalog, and records each would-be high or blocking item as fixed or pre-triaged with evidence (path and line, or a live read). The record is a file whose first line names a hash of the current diff, and the preflight (rule 13) fails until that hash matches, so a changed diff needs a fresh self-review.
    - Prevents: automated review finding what the author could have found, and a self-review that silently covers an older diff.
    - Acceptance (test): the preflight fails with a missing record, fails when the diff changes after the record, and passes when the hash matches.
15. **Infrastructure noise is re-run, bounded and named.** This refines rule 12. The merge lane re-runs failed jobs (failed jobs only) without starting a fix only when the log tail of every failed job matches a known infrastructure-noise pattern (rate limits, connection resets, runner loss, expired workload-identity assertions). It does so at most a fixed number of times per head (a parameter, default 2) and logs which pattern matched. Any failure it cannot name goes to the fixer.
    - Prevents: fix sessions spent on flaky infrastructure, endless re-runs that hide a real failure, and re-runs nobody can explain later.
    - Acceptance (test): the classifier tests cover all-noise, mixed and unknown failures, the per-head cap and the logged pattern name.
16. **Deletes owned by another open change wait on it.** A plan can delete objects that this change's diff does not touch, because another open change by the same owner applied them from its branch into shared state and declares them. Then this change waits on the other one and re-arms itself (rebase on the base) once that one merges. It is never offered as a delete sign-off, since approving it would delete live objects. A read failure or a delete no open change declares keeps the normal sign-off hold. See [IaC Governance rule 11](iac-governance.md#1-rules).
    - Prevents: the owner approving a merge that deletes objects another open change just created.
    - Acceptance (test): the hold tests cover an attributed delete (waits, then re-arms after the other merge), an unattributed delete and a read failure (both keep the sign-off hold).
17. **A fixer that needs the owner returns a decision, and real findings feed the catalog.** When an automated fix stops on a choice only the owner can make, it returns a structured decision, not prose: a question, two to four options each with an action kind (fix a specific way, accept the risk, hold) and its exact effect, and a recommendation. The operator UI shows one button per option, pinned to the reviewed head, and the click is the owner's sign-off for that head only ([Automation Safety rule 10](automation-safety.md#1-rules)). Text that a decision will post as the owner is checked against the identity and copy rules before it is offered. Every real finding a fix session fixed that the finding catalog would not have caught is appended to the catalog (deduplicated), so the next build checks for it.
    - Prevents: owner questions buried in free text, a click that approves a head nobody reviewed, posts that break the copy rules, and the same defect found again by review on the next change.
    - Acceptance (test): the decision schema rejects fewer than two or more than four options and an option without an action kind, a click on a moved head is refused, and a fixed finding the catalog missed is appended once.
18. **A merge commit carries only a noreply author email, with no account setting required.** Only GitHub noreply author emails land in shared history. No contributor turns on any account setting for it, so an account that also works in repositories expecting another address keeps working there. A GitHub squash merge takes the pull request author's primary email unless that account keeps its email private, and the merge API's author hint is then ignored; so the merge never lets GitHub pick the author. Merges go through `scripts/merge-pr.py`. Where the repo allows rebase merging (turn on "Allow rebase merging"), it builds the squash commit itself: one commit on the base branch tip holding the pull request's merged tree, titled `<title> (#<n>)` with the pull request body, authored and committed by `<id>+<login>@users.noreply.github.com` of the signed-in account. It pushes that commit to the pull request branch with `--force-with-lease`, waits for the repo's checks on it, and merges it with `--rebase`, which keeps the author. Where the repo does not allow rebase merging, it squash merges with the noreply author hint and first refuses a pull request whose commits carry an email that is not a noreply address. Either way it reads the merge commit back and, on a leak, prints the exact recovery (an owner-approved history rewrite) and exits non-zero. Every clone sets `git config user.email <id>+<login>@users.noreply.github.com` for its commits to the repo. (Branch commits may use the organisation address, which the `identity` check allows; the merge commit may not.) CI fails any commit on a branch or on main whose author or committer email is not a noreply address, merge commits GitHub builds for a pull request excepted.
    - Prevents: an employer or personal address written into a shared repository's permanent history by a merge button, which cannot be undone without rewriting a protected branch.
    - Acceptance (core-ci): `checks/check-authors.py` exits 0 on the core; `merge-pr.py` builds a noreply squash commit and merges it with --rebase where rebase merging is allowed, refuses a pull request with a non-noreply commit email on the squash fallback, and prints the recovery when the merge commit leaks one.
19. **Every file is plain ASCII.** No tracked text file holds a byte above 127: no em or en dash, curly quote, NBSP, arrow, ellipsis or zero-width character, in code, docs, config and data alike. Binaries, lockfiles and the synced core copies are out of scope (the core checks its own content before release). A repo that already holds non-ASCII files does not narrow the check to pass: it records a time-boxed exception per path (rule `pr-review-and-merge.md 1.19`, a `Scope` that names the path or glob, a `Review by` date) in `standards-local/exceptions.md` and clears the files before that date. A script or XAML file is never covered by such an exception; its own rules (scripting-powershell.md 1.7, wpf-design-system.md 6.1) hold.
    - Prevents: characters that break a parser or a hidden-window launch, render as mojibake in a log, or hide in a diff, and a check quietly narrowed until it proves nothing.
    - Acceptance (overlay-ci): the `core-ci.yml` job `core-ascii` passes; with no ASCII patterns parameter it reads every tracked text file, and each line it excepts names the exception.

## 2. Preparing the PR

1. `git fetch`, then `git worktree add ../<repo>-<topic> -b <type>/<topic> origin/main`. The branch pattern is one consumer parameter (default `<type>/<topic>`), read by both the preflight and CI; where a branch name selects a deploy tier, the same parameter is the only place the test is written.
2. Make the change, run the repo's checks locally, and scan only the added lines for banned
   characters when older lines carry them.
3. `git diff --stat`, then commit the files by name with the owner's identity.
4. Write the PR body to a file and pass it with `--body-file`. Sections: what and why, how it was
   verified (and what was not exercised), how it ships (merging may not deploy).
5. Before adding a file outside the change's own tree (a workflow, code owners, repo config), read
   who owns that path. A path only the author owns makes the whole PR bypass-only.

## 3. Answering review

- Settle a finding that predicts a CI failure with that head's CI log, not with a code change.
- Web-check any claim about vendor or OS behaviour before posting it, and correct a reply that
  turns out wrong.
- When several findings trace to one design gap, fix the model once with tests for every path.
- Before the last round, re-read the PR body and runbook claims against the final code.
- An unavailable review (malformed output, reviewer error) is not a verdict. Rerun it once.
- **A review bot is a required check that fails closed.** It reads its config from the base branch,
  never from the PR, and an override covers exactly one commit (it names the head sha). The check
  fails only on a confirmed block or when no review exists for the head; findings without a block
  pass it, since failing on every high finding would stall most work. **Acceptance (test):** a PR
  that edits the bot config is reviewed under the base config; an override on an older sha does
  not pass a newer head; a missing review fails the check.
- After a new push, cancel runs of superseded heads that wait on an environment approval, so the
  owner is not asked to approve a commit nobody will merge.

## 4. Holds and the merge button

| Hold | Example | UI | Who acts |
|---|---|---|---|
| Policy | Every gate passes and a rule needs sign-off (access grant, delete, sensitive path) | Approve and merge | The owner |
| Guard-only red | The only red is a guard that blocks an intended delete | Approve and merge, which also starts the reviewed release path | The owner |
| Problem | Red check, conflict, untriaged high finding, unresolved thread | What is wrong and the next step, no merge button | The fixer, then the owner if it gives up |
| Waiting | Checks or review running, a fix session on it | Working indicator, link only | Nobody |

The approve endpoint re-derives the hold live and refuses anything that is no longer a policy hold.
A guard-only red is classified from the job log: every error line is the guard message or its exit.

**Trust holds.** Besides holds by path and policy, a review lane that merges other people's pull
requests holds these for the owner's sign-off, as policy holds (approve and merge, the owner acts),
even when every gate passes:

| Trust hold | When it fires |
|---|---|
| First PR of a new app | The pull request adds a new app or module root (a new deployable, a new package, a new IaC root) that no merged pull request has touched before |
| New contributor | The author has fewer than N merged pull requests in the repo (N is a parameter, default 3) |
| Device-shipped paths | The diff touches a path whose content is shipped to managed devices or end-user machines (scripts, packages, configuration profiles: a path list the repo keeps in its parameters) |

**A failed lookup holds.** When the lane cannot read what a trust hold needs (the author's merge
count, the list of known app roots, the device path list), it holds the pull request with the
reason "trust lookup failed" and never treats the failure as "no hold" (automation-safety.md rule
5).

Acceptance (test): a fixture pull request for each kind is held with its rule id, a contributor at
N merged pull requests is not held by the new-contributor rule, and a lookup that errors holds with
the lookup reason.

## 5. Merging

```bash
gh pr view <n> --json state,headRefOid,mergeable,statusCheckRollup
gh pr merge <n> --squash --delete-branch --match-head-commit <reviewed sha> \
  --author-email <id>+<login>@users.noreply.github.com   # or: python3 scripts/merge-pr.py <n> --match-head-commit <sha>
```

- Confirm the PR is still open and the head is the reviewed sha before the merge. If it already
  merged, record that and stop. A fix for a merged PR is a new PR off `main`.
- After a merge that changes a workflow or a deployed app, prove the live path: the push runs'
  conclusions and the deployed version.
- An admin bypass is the owner's per-PR decision. A broad "keep going" does not cover it. The one
  standing exception is the bounded own-PR merge lane (automation-safety.md section 8): on the
  owner's own pull requests, only while its switch is on, it may bypass the approval count and
  nothing else (never a red check, a freeze, a hold label or an escalation), and it logs each
  bypass. The owner recorded that decision on 2026-10-21.

## 6. Checklist

- [ ] Worktree off `origin/main`, files committed by name, `git diff --stat` read.
- [ ] Conventional Commit title and messages.
- [ ] Changelog entry for the version in the docs home.
- [ ] No tool attribution, owner identity on every commit.
- [ ] Merge goes through the protected path, pinned to the reviewed head, with a noreply author email.
- [ ] Each finding fixed or refuted with evidence, one disposition reply per round.
- [ ] Triage marker only after the head's review, never on a promise.
- [ ] Policy holds have a button, problems do not, working PRs have none.
- [ ] Delegated work re-checked locally and its commits listed.
- [ ] No gate weakened.
- [ ] Preflight passed locally, its sign-offs listed in the PR description.
- [ ] Self-review record matches the current diff hash.
- [ ] Re-runs only for named infrastructure noise, within the per-head cap.
- [ ] Deletes owned by another open change wait on it, never offered as a sign-off.
- [ ] Owner decisions are structured and pinned to the head, missed findings added to the catalog.
