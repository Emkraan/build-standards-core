# Contributing

- Conventional Commits for every commit and PR title (`docs:`, `feat:`, `fix:`, `ci:`, `chore:`).
- No attribution to any tool or assistant in commits, PR text or files.
- Plain ASCII in every file: no em or en dashes, curly quotes, NBSP or arrows. Use `-`, `->`, `'`, `"`.
- The standards here are the source of truth. Never write that an app's code outranks a doc.
- One topic per doc. Link between docs with relative links; `check-links.py` verifies them.
- Agnostic only. `checks/denylist.sha256` (hashed, so it names nothing) and each contributor's
  private denylist hold terms that must never appear. Add a new source's names to your private denylist before contributing from it. No real email
  addresses in files.
- Only noreply author emails land in history (pr-review-and-merge.md 1.18). No account setting is
  required: `merge-pr.py` builds the squash commit with the noreply author and merges it with `--rebase`.
- Merge with `python3 templates/overlay/scripts/merge-pr.py <n>`: it builds the squash commit with the
  noreply author, pushes it to the branch, waits for the checks and merges it with `--rebase`, then reads
  the merge commit back and, on a leak, prints the exact recovery (an owner-approved history rewrite)
  and exits non-zero.
- Commit with a GitHub noreply email (`check-authors.py` fails anything else) and enable the hook:
  `git config core.hooksPath checks/hooks`. The hook refuses a `user.email` that is not a noreply address,
  runs `check-sanitised.py` and `check-consumer-neutral.py` in diff mode (`--staged`: only the lines the
  commit adds), and runs `check-ascii.py` and `check-links.py`. CI runs the first two
  as `--diff <base commit>` over the pull request's added lines, so a commit made with
  `--no-verify` is caught there; a hit already in a historical file (a changelog entry) is not the
  change's to fix. Run with no argument they check the whole tree, which is what the weekly sweep
  (`sweep.yml`) does.
- Every change to a standard needs a `CHANGELOG.md` entry dated that day; `check-changelog.py`
  fails a pull request that touches shipped content without one. Issue references in the
  changelog are bare numbers (`#101`), never owner-qualified URLs: consumers mirror the
  changelog, and a URL carries this repo's owner into theirs. Never tag by hand:
  when a pull request that adds a new top entry merges, `release.yml` creates the annotated tag
  `vX.Y.Z` on the merge commit and a GitHub Release whose notes are that entry, then calls
  `gallery-release.yml` for the same tag (a tag or release made with the workflow token starts no
  other workflow, so the call is explicit) to attach the kit gallery. The version must be greater
  than the latest tag; an existing tag is never moved, and a mismatch fails the run.
- Rewrite documents in full. Never leave placeholder prose that stands in for removed content
  (a parenthesised claim that the other sections are unchanged, wrapped in ellipses); that is how
  a fuzzy edit silently clobbers a document. `check-placeholders.py` fails the build on it.
- Shared Hermes skills are named `core-<name>` and live in `hermes/skills/`. Any shareable improvement
  found in a consumer comes back here in the same piece of work (`hermes/README.md` section 4).
- Do not force-push `main`. Changes land by pull request.
- Repository secrets: `DEPLOY_APP_PRIVATE_KEY` (with the variable `DEPLOY_APP_ID`) is the private key of the
  GitHub App the merge workflow `automerge.yml` signs in as. It is the only secret the workflows read; the
  built-in `GITHUB_TOKEN` is the rest. `repo_checks.py` (RC010) fails a workflow secret named nowhere in the docs.
- Declare the issue outcome in every pull request body: `Closes #N` when the change finishes the issue,
  `Refs #N` when it only moves it, or `No issue: <reason>` when there is none.
- Authority: the repo owner is the final say on every standard, and every consumer account is that
  same person. Pull requests here come from the upward path below: a consumer's agent opens a plain
  issue, the owner approves the item, and the account that owns an approved item opens the pull
  request and merges it once `ci` and `visual` pass; no second reviewer is required. The checks and
  the merge rule below take the place of review. Do not wait for another account to act, and do not
  leave a shareable improvement in a consumer: open an issue for it.
- Never rebase. Work from a branch cut from the current `origin/main`, in your own worktree, and
  bring in what landed since with a merge: `git fetch origin main` then `git merge FETCH_HEAD`, before
  you push and again before you merge, then re-run the checks. Never resolve a conflict by taking your
  whole side of a file, and never overwrite a file from a stale copy; read what landed on `main` since
  you branched and keep it. The version is assigned at merge: when another change took your
  `CHANGELOG.md` top entry's number, renumber that entry above the latest tag (`git ls-remote --tags
  origin 'v*'`) and run the checks again. Never force-push. Squash merge so one change is one commit.
- Category survey: contributions are not only per source. When the Hermes docs, its plugin catalog, a
  consumer's setup or an audit shows a class of tooling or setting that no doc covers, it gets a
  decision here (`hermes/tools.json` and `hermes/configurations.md` for Hermes) even if no source
  wrote it up.
- Adoption rule: a source rule is adopted if it is generic, adapted if it is generic once a business
  name or platform is parameterised, and rejected if it only makes sense inside one business. The
  pull request description states the decision (adopt, adapt or reject) for each rule; provenance is
  kept with the contributing account, never in this repo.

## Reporting from a consumer

A build's agent never opens a pull request on this repo before approval, and this repo never
reaches into a build. Work moves between them through one channel in each direction: down, the
nightly's overlay pull request or direct apply; up, a plain issue on this repository. The nightly
files nothing upward by itself (its optional `report_repo` sections are off by default, CONSUMING.md
section 7). When a consumer's agent finds a shareable improvement, it opens one
sanitised issue here describing it by role, the owner approves the item in the issue, and the
account that owns the approved item opens the pull request linking it with `Refs #N` or
`Closes #N`. A pull request that arrives with no approved item behind it is closed unmerged.

**Opening the issue.** The shared Hermes skill `core-improvement-issue`
([hermes/skills/core-improvement-issue/SKILL.md](hermes/skills/core-improvement-issue/SKILL.md)) is
the procedure; the one-line command is in [CONSUMING.md](CONSUMING.md) section 7. An agent without
Hermes follows the same file by hand. One improvement per issue: search the open issues first and
add evidence to one that already covers it.

**What the issue holds.** What changes in the core, why (what went wrong or was slower without it
on the consumer), the evidence (commands run, code read, before-and-after ratios), the proposed
change with any machine-only value as a parameter, and the adoption risk for other consumers. A
claim that could not be checked is written as "not checked" with the reason; an issue never
estimates.

**Does it belong in the core?** "Contribute back every shareable improvement" and
"machine-specific things stay local" collide the moment a real improvement is half one and
half the other. The test:

> Would this help another consumer's agent that knows nothing about your machine, carrying
> no name, path or value that belongs to your estate? Both yes: propose it. Either no: keep
> it local, and if it is the core's rule that is wrong, open an issue for the difference
> instead.

Parameterise before proposing. A rule that names your tool, host, tenant or app is local by
default; it becomes core material once the name is a parameter with your case as one value
(the way `CORE_REPO` and `standards-local/parameters.md` turned one machine's setup and one
business's values into generic rules). A value that is only ever yours belongs in
`standards-local/parameters.md` or the machine-local `consumer.json`, never in a shipped
file.

**Sanitising.** This repository is public, so an issue carries no repo, app, host, address,
employer, person, account, tenant, plan, path, token or key. Repos and apps are named by role only
(product app, local ops center, multi-module shell, hub, agent home). Measured numbers go in as
ratios, deltas or before-and-after pairs, not absolutes: a count that only your estate has is a
name (the core-status rule counts are the core's own rules and go in as they are). A screenshot is
rarely needed; when one is, it carries layout only, scrubbed with `checks/redact_page.js` and
checked by eye. Check the draft file before posting, from the core clone: `python3
checks/check-sanitised.py --file <draft>`, `python3 checks/check-consumer-neutral.py --file
<draft>`, and confirm it is plain ASCII; post only what passes. The checks see only the file given
to them, so the title and every comment are checked the same way before they are posted.

**When the core took something from your repo.** The provenance stays with your account, and the pull
request description records what was adopted, adapted or rejected. It is not a subscription. The core
does not pull your repo's later changes, and your repo is not exempt from the core. Both directions run
through this repo like any other consumer's: your repo's later changes arrive as issues the owner
approves, then one pull request per change with its evidence; a wrong core copy of a contributed design
is fixed through an issue, not a direct write.
