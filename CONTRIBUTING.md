# Contributing

- Conventional Commits for every commit and PR title (`docs:`, `feat:`, `fix:`, `ci:`, `chore:`).
- No attribution to any tool or assistant in commits, PR text or files.
- Plain ASCII in every file: no em or en dashes, curly quotes, NBSP or arrows. Use `-`, `->`, `'`, `"`.
- The standards here are the source of truth. Never write that an app's code outranks a doc.
- One topic per doc. Link between docs with relative links; `check-links.py` verifies them.
- Agnostic only. `checks/denylist.sha256` (hashed, so it names nothing) and each contributor's
  private denylist hold terms that must never appear. Add a new source's names to your private denylist before ingesting it. No real email
  addresses in files.
- Only noreply author emails land in history (pr-review-and-merge.md 1.18). No account setting is
  required: `merge-pr.py` builds the squash commit with the noreply author and merges it with `--rebase`.
- Merge with `python3 templates/overlay/scripts/merge-pr.py <n>`: it builds the squash commit with the
  noreply author, pushes it to the branch, waits for the checks and merges it with `--rebase`, then reads
  the merge commit back and, on a leak, prints the exact recovery (an owner-approved history rewrite)
  and exits non-zero.
- Commit with a GitHub noreply email (`check-authors.py` fails anything else) and enable the hook:
  `git config core.hooksPath checks/hooks`.
- Every change to a standard needs a `CHANGELOG.md` entry dated that day; `check-changelog.py`
  fails a pull request that touches shipped content without one. Issue references in the
  changelog are bare numbers (`#101`), never owner-qualified URLs: consumers mirror the
  changelog, and a URL carries this repo's owner into theirs. After merge, tag the merge
  commit (`git tag vX.Y.Z <merge-sha> && git push origin vX.Y.Z`) so consumers can pin a release.
- Rewrite documents in full. Never leave placeholder prose that stands in for removed content
  (a parenthesised claim that the other sections are unchanged, wrapped in ellipses); that is how
  a fuzzy edit silently clobbers a document. `check-placeholders.py` fails the build on it.
- Shared Hermes skills are named `core-<name>` and live in `hermes/skills/`. Any shareable improvement
  found in a consumer comes back here in the same piece of work (`hermes/README.md` section 4).
- Do not force-push `main`. Changes land by pull request.
- Never put a GitHub closing keyword (`close`, `closes`, `closed`, `fix`, `fixes`, `fixed`,
  `resolve`, `resolves`, `resolved`) in front of a reference to a `consumer-report` issue in a pull
  request title, body or commit message: merging would close that account's report. Link it with
  `Refs #N` or `for #N`. `check-closing-refs.py` fails the pull request otherwise, and fails in CI
  when it cannot read a referenced issue's labels.
- Authority: the repo owner is the final say on every standard, and every consumer account is that
  same person. Pull requests here come from the upward path below: a build reports, the owner
  approves items, and the account that owns an approved item opens the pull request and merges it
  once `ci` and `visual` pass; no second reviewer is required. The checks and the rebase rule
  below take the place of review. Do not wait for another account to act, and do not leave a
  shareable improvement in a consumer: bring it up through its report.
- Rebase before you push and again before you merge: `git fetch origin && git rebase origin/main`,
  then re-run the checks. Work from a branch cut from the current `origin/main`, in your own
  worktree. Never resolve a conflict by taking your whole side of a file, and never overwrite a
  file from a stale copy; read what landed on `main` since you branched and keep it. Use
  `--force-with-lease` on your own branch only. Squash merge so one change is one commit.
- Category survey: ingest is not only per source. When the Hermes docs, its plugin catalog, a
  consumer's setup or an audit shows a class of tooling or setting that no doc covers, it gets a
  decision here (`hermes/tools.json` and `hermes/configurations.md` for Hermes) even if no source
  wrote it up. `ingest/hermes-token-economy-gap.md` is the worked example.
- Ingest rule: a source rule is adopted if it is generic, adapted if it is generic once a business
  name or platform is parameterised, and rejected if it only makes sense inside one business.
  Record each decision in `ingest/<source>.md`.

## Reporting from a consumer

A build's agent never opens a pull request on this repo, and this repo never reaches into a
build. Work moves between them through one channel in each direction: down, the nightly's
overlay pull request or direct apply; up, the account's single open `consumer-report` issue,
created from
the `consumer-report` issue template in the owner's private intake repository (reports are never filed in this public repository). The
nightly keeps two sections current on its own, sanitised, each between its own pair of markers:
`nightly:candidates` (kit-role candidates) and `nightly:changes` (what changed since the previous
nightly). It creates the issue the first time it finds something. Everything else in the body
belongs to the consumer's agent: update it in place, keep both marker sections intact, and never
edit between the markers.

**Producing the report.** The shared Hermes skill `core-consumer-report`
([hermes/skills/core-consumer-report/SKILL.md](hermes/skills/core-consumer-report/SKILL.md)) is the
procedure; the one-line command is in [CONSUMING.md](CONSUMING.md) section 7. An agent without
Hermes follows the same file by hand. No tool is a required contributor: any agent that follows
the skill produces the same report.

**Why the report is data, not prose.** The goal is one premium design from the core on every
consumer (product repos, local ops centers, multi-module shells, hubs, future apps), with each
account improving it over time. Where a consumer's design is ahead of the core, the report must
describe it precisely enough for the core to be raised to it; and it must describe the consumer's
functionality precisely enough that adopting a core part never breaks a feature.

**The report outline** (the template's sections, in order):

- **a. Machine and ways in.** `consumer.json` with names replaced by role labels; the nightly
  jobs; per repo the way it takes the core, by neutral label (`workflow`, `apply-at-once` for the
  Direct mode, `vendored`, `agent-home`),
  the pinned release and how far behind it is; `core-status --json` counts (pass, proved, fail,
  unverified) and the UI verdict.
- **b. Design inventory per app.** Tokens used and any local token or accent work; the shell
  (layout, rail, header, strip, home or hub, module switching); every UI part with its source
  (kit, adapter over kit, local); interaction patterns (palette, shortcuts, toasts, dialogs,
  motion); typography and density; light and dark; layout-only screenshots of every main screen
  in both themes.
- **c. Design diff against the core kit**, at the pinned release, part by part: one row per kit
  part and per local part, verdict same, local is better, core is better, missing in core or
  missing locally. Each "local is better" or "missing in core" row is a proposal item `D-nnn`.
- **d. Functionality inventory per app,** the parts each feature depends on, and the adoption
  risk table: what breaks or changes if a local part is replaced by the current kit part.
- **e. Practice and CI:** workflows, gates, scripts and conventions that beat the core (`P-nnn`),
  and each difference from a core rule with a verdict on which side should change.
- **f. Gaps in the core's instructions** (`G-nnn`): what it says in one place and does in
  another, and what it asks for that a consumer cannot do.
- **g. Changes since the last report:** the nightly's `nightly:changes` section.

**Proposal items.** Every item has an id, a title, ready or settling (settling names the open
question), its evidence, and what changes in the core if it is approved. Ids are scoped to the
account (`D-001`, `P-001`, `G-001`), never reused and never renumbered, so the owner can approve or
reject each one in a comment ("approve D-003"; "reject P-002: reason"). Anything the agent could
not collect is written as "not collected" with the reason; a report never estimates a row.
A report in the older v1 shape that numbered its gaps `D1`, `D2` carries them over as the `G` item with the same number (`D1` is `G-001`) and continues after the highest; the skill says how.

**Labels and approval.** The issue carries `consumer-report`; a proposal not ready to adopt
carries `settling` until its open questions close. The owner approves items in the issue. An
approved item is moved by the account that owns the change: that account opens the core pull
request linking the issue. Nothing lands from a report without that approval, and a pull
request that arrives with no approved item behind it is closed unmerged.

**Does it belong in the core?** "Contribute back every shareable improvement" and
"machine-specific things stay local" collide the moment a real improvement is half one and
half the other. The test:

> Would this help another consumer's agent that knows nothing about your machine, carrying
> no name, path or value that belongs to your estate? Both yes: propose it. Either no: keep
> it local, and if it is the core's rule that is wrong, file the difference as a report item
> instead.

Parameterise before proposing. A rule that names your tool, host, tenant or app is local by
default; it becomes core material once the name is a parameter with your case as one value
(the way `CORE_REPO` and `standards-local/parameters.md` turned one machine's setup and one
business's values into generic rules). A value that is only ever yours belongs in
`standards-local/parameters.md` or the machine-local `consumer.json`, never in a shipped
file.

**Sanitising evidence.** Screenshots carry layout only: replace every letter and digit, remove
text a stylesheet draws, freeze the page as a static clone so it cannot re-render, blur what
cannot be replaced (the skill's step 2.7 is the recipe), and keep out account names, plan tiers, fleet sizes and hostnames.
Measured numbers go in as ratios, deltas or before-and-after pairs, not absolutes: a count
that only your estate has is a name (the core-status rule counts are the core's own rules and
go in as they are). Repos and apps are named by role only (product app, local ops center,
multi-module shell, hub, agent home). Check the draft file before posting, from the core clone:
`python3 checks/check-sanitised.py --file <draft>`, `python3 checks/check-consumer-neutral.py
--file <draft>`, and confirm it is plain ASCII; post only what passes. The checks see only the
file given to them, so a comment is checked the same way before it is posted. Screenshots are
hosted in a secret gist and linked by raw URL: the login in that URL is the one account name both
checks accept in file mode, because it is the posting account, already public as the issue's
author. The body has a hard limit of 65,536 characters; whole tables move to a markdown file in the
gist when it does not fit, linked by the same raw URL form (`.../raw/<file>.md`, the login allowed
there too), and the items and nightly markers stay in the body.

**When the core took something from your repo.** The record in `ingest/` is provenance, not
a subscription. The core does not pull your repo's later changes, and your repo is not
exempt from the core. Both directions run through this repo like any other consumer's: your
repo's later changes arrive as report items the owner approves, then one pull request per
change with its evidence; a wrong core copy of an ingested design is fixed by a report item,
not a direct write.

