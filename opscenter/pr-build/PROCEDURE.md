# Building a pull request that merges without the owner

The generic build procedure behind the own pull request lane (opscenter/DESIGN.md section 12.3, items 3 to 5) and the auto-fix
starter (`lanes/autofix.py`, section 12.9). It is written for any agent or person who builds a change for an owner whose own pull
requests are reviewed and merged by a lane, with the pre-push gate (section 12.11) as the mandatory step before a push. The
finding catalog (`finding-catalog.md`) is its learning loop.

Why it exists: most high or blocking review findings on a team's pull requests were knowable before the push, and each one found
after the push costs a CI round, a review round, a fix session or the owner's time. Build so the first review is clean.

On the code host everything is written in the owner's first person voice, under the owner's account, with no tool or AI wording.
The procedure, the gate and the catalog are private tooling: never name them in a repository, a pull request, a commit or a ticket.

## 1. Build order

1. One pull request per ticket. Every own pull request costs the owner a sign off, so batch all of a ticket's changes into one pull
   request and keep pushing fixes to it. Split only when ordering forces it (a delete time guard before the removal, a root that
   must apply first), and say why in the body. Never open a follow up pull request for a fix that fits the open one.
2. Work from the ticket's own branch, named by the repository's branch rule, in a fresh worktree off origin/main, never the owner's
   checkout.
3. Before writing code, read the catalog sections for what you touch. Each rule is a requirement.
4. Change, tests next to the change, the version bump, ASCII only, no em or en dashes.
5. Run the pre-push gate (section 2) until it passes. Fix, do not bypass. Acting automation gets its design check written first.
6. Commit as the owner under the repository's identity rule (a noreply address where the repository rejects real emails), by
   explicit path. Open the pull request with the gate summary in the body: the expected sign off rules (so the owner sees them at
   open), pre-triaged items with evidence, and any stack it waits on (`Waits on #N`, plus the hold label only when it truly must
   wait).
7. Leave it. The own pull request lane merges it and the auto-fix starter handles anything the review finds. Never hand merge.
8. After the merge, the documentation is part of done.

## 2. The pre-push gate

A command the consumer plugs into the auto-fix starter (`AUTOFIX_PREFLIGHT_CMD`, `AUTOFIX_REVIEW_CMD`) and runs before opening a
pull request and before every push to an own pull request. Exit 0 pass (warnings allowed), 1 failures (each printed with the fix),
2 environment problem (a failure: fail closed). It never writes outside the worktree's git dir and never calls a code host write.
For the files changed against origin/main it runs:

- the repository gates for what changed (lint, typecheck, tests, formatting and validation of infrastructure code, script
  analysis). A fast mode skips the slow gates for a quick loop, never before a push;
- hygiene: ASCII and dash scan (including escaped forms), the version bump, the branch name rule, a conflict with origin/main, no
  tool attribution in commits, secret patterns in the diff;
- the lane dry run: the same policy rules and plan matcher the lane uses, printed as the expected sign off rules for the body;
- overlap: other open pull requests of the owner touching the same roots;
- the catalog checks a script can test;
- the self review gate: the building session reviews its own full diff against the repository's review prompts and the catalog,
  then writes a review file in the worktree's git dir (never committed) that starts with the line `diff: <hash>` the gate prints.
  Every would be high or blocking item is a `FIXED: ...` line or a `PRE-TRIAGE: <claim> | <evidence path:line or live read>` line.
  The gate fails until the file names the current diff hash.

Local independent review (before the first push and before every later push): the review command runs the repository's CI reviewer
prompts, read from origin/main, on the branch diff as separate reviewers, writes the result in the git dir and prints each high
with a key (`LR-xxxxxx`). The gate fails until the current diff hash has a review with no unrefuted highs. Fix every real high and
rerun (a new diff is a new round, at most 3 rounds); refute a wrong one with `REFUTED: LR-xxxxxx | <evidence path:line or live
read>` in the self review file. After 3 rounds the gate passes with the remaining highs listed as `OPEN-HIGH:` lines in the file
and in the body notes, so say in the pull request that they are open. Batch every fix before the next round.

Design check for acting automation: when the diff adds code that deletes, applies, lifts a lock or changes role assignments
unattended, the gate fails until the git dir holds `design-check.md`. The template asks eight questions with one answer line each,
every answer a file reference or `N/A: <reason>`: fail closed on every upstream failure, behaviour when main moves mid run,
concurrency with merge driven applies, the lock window, an audit record on every path, the kill switch, dark launch (action off by
default until enabled after a soak), and, where the platform checks conditions only at grant creation, that every action a grant's
condition names exists in that grant's role, pinned by a test. Design the code to those answers before writing it.

## 3. One push per review round

When working an own pull request, address every open review finding in ONE commit round and push held files once per round, never
one push per finding. Each push to a file the plan job runs costs the owner an approval. Before editing, collect every open item for
the current head (the newest review comment, review threads, failing checks, the lane reason), fix them together, run the gate on the
combined change, then push. If held files were pushed in the last 20 minutes, fold the rest into one more push. The auto-fix starter
enforces the window in code and puts the same rule in its brief.

## 4. Stacking

- A pull request kept as a draft "until X" states X as a fenced gate block in its description, never prose only. The lane skips
  drafts for merging but checks the gate on a schedule and marks the pull request ready with an evidence comment once every line
  passes. Lines are `applied #N`, `merged #N` and a query line with its label. Pair every "zero bad events" query with an "enough
  traffic" floor so a quiet window cannot pass, and give production refusal windows 24 hours.
- Never apply an owner applied root from an unmerged branch unless every other open pull request touching that root is rebased on
  top of it or explicitly waits on it: branch applied state makes every other plan show foreign destroys. Two pull requests that each
  applied a different root from their branch deadlock; check for other branch applies first.
- Write `Waits on #N` in dependent pull requests and land the applied one first. One shared root per open pull request where
  possible; split import only work from behaviour changes.
- A removal is a destroy: it needs the release path, never a plain merge.

## 5. Acting automation ships dark

Anything that acts unattended (deletes, applies, lock lifts, access changes, grant removals) merges with its action OFF and runs in
report mode. The owner turns it on with one Enable click after reading a dry run (`server/modules/dark_launches.py`).

- The switch is a variable the automation reads at run time (`<NAME>_ENABLED`): unset, empty or anything but the exact string `true`
  means dry run. The workflow also takes a `dry_run` input, default true, that forces report mode even when the switch is on.
- Report mode does everything except the write: read, plan, compute the exact list of objects it would change, and write it to the
  job summary and an artifact. It exits non zero on a failed read and never treats an error as "nothing to do".
- Read the switch once at the start of the job from the environment the job runs in, never from a file in the pull request, in a
  protected environment so a branch cannot flip it.
- The body says the action ships off and names the variable, the environment, the workflow and the dry run to review. Never set the
  variable in the pull request or the same session: enabling is the owner's click.
- Register it only once the pull request has merged and the workflow exists on main.
- Not every change is acting automation: a workflow that only reports, an app code change or a plain infrastructure change through
  the normal reviewed plan is a normal pull request. If unsure, ask whether anything would delete, apply or change access without a
  person reading a plan first.

## 6. When the review flags something anyway

The auto-fix starter owns it. When building interactively and you see the review: fix every real finding in ONE push, refute the
rest with evidence in ONE triage reply ending with the head marker, and add any new real finding class to the catalog.

A triage marker names the ids it answers: `<!-- triage:<head sha> H2 -->`. Only H and B ids: the lane's pattern accepts `[HhBb]\d+`
only, so a marker that also lists a medium or low id does not parse and the pull request stays held "missing H1". Answer mediums
and lows in the reply text and keep them out of the marker. The lane clears only the named ids and a bare marker clears nothing;
never name an id the reply does not refute or accept. Confirm with the lane's check command after posting.

A fixed high can stay open in the review tracker as "code did not change" when the fix moved its line range: answer it with a
triage that cites the new lines.

## 7. Pitfalls that recur

- Gate runs that validate a module directory can leave an untracked lock file there; delete it after every run, never commit it, or
  the next run counts it in the diff and the self review hash goes stale.
- A local plan with a hand written backend override must take the account per tier; pointing it at another tier's state creates a
  stray empty state and the plan looks like a fresh root.
- A "behind origin/main" warning is only a warning, but a guard on the branch pipeline may fail the whole run when the branch does not
  include the latest main: rebase the full stack before every push that must deploy.
- The code host runs no pull request workflows (review, scan, plan) on a pull request that conflicts with main; a stacked child that
  waits on its parent stays unreviewed after a push, so there is nothing to triage. Check the merge state and say so.
- A pull request plan runs on the merge ref of its push event: a change main merged minutes later can show as destroys in a root the
  pull request never touches. Prove it with the main commit time against the event time, rebase, and push for a fresh plan.
- A task runner without `--continue` stops starting tasks after the first failure, so a baseline log with no type errors can mean the
  type check never ran. Gate with `--continue` and prove which errors predate you against the base.
- Shells differ: an unquoted variable holding many paths is one pathspec in some shells. Use an array. Keep logs under the
  worktree scratch folder, never a shared temp folder.
- A new function identity must not call the directory API before its consent apply: the first token is cached for hours without the
  roles. Smoke tests before the grant use bodies that stop before the directory call.
- Several client branches that deploy to one shared web build overwrite each other: verify them together on one combined
  integration branch pushed last, and confirm the served bundle contains a new string before calling it live.
- A headless browser tab can be frozen by page lifecycle while evaluation still answers: bring it to front and set it active before
  every step, capture traffic with a wrapped fetch, and run long async probes fire and forget.

## 8. Keeping the catalog alive

When a review raises a real finding the catalog would not have caught, append a rule under "Appended by the learning loop":
`- [<section letter>] <rule>.` Dedup against existing rules first. Fix sessions emit `CATALOG ADD:` lines in their result file and the
auto-fix starter appends them. Never add a rule that weakens a check.
