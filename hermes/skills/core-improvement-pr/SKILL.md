---
name: core-improvement-pr
description: "Use when work on a consumer finds an improvement that belongs in the core: checks it passes the scope test, makes the change by role with no names on a branch of the core repository, runs the sanitising checks, and opens one pull request. No issue first, never a fork."
---

# Core improvement pull request

This is the upward path from a consumer to the core. The nightly files nothing by itself; when an
agent finds a shareable improvement, it opens one sanitised pull request on the core repository from
a branch on that repository. There is no issue to file and no approval to wait for: the pull request
is the proposal, and `ci`, `visual` and the review take the place of an approval step
(`CONTRIBUTING.md`, "Reporting from a consumer"). This skill is the procedure.

## Hard rules

- **A branch on the core, never a fork.** Every contributing account has write access. Push the branch
  to `origin` of your own worktree of the core. If `gh` says the push is denied, stop and ask the owner
  for write access; do not fall back to a fork, whose CI waits for a maintainer and which is not
  part of the flow.
- **No issue for an improvement.** Do not open an issue to propose a change.
- **The core is public.** The branch name, commits, pull request title and body, and every comment
  carry no repo, app, host, address, employer, person, account, tenant, plan, path, token or key.
  Describe each thing by its role (product app, local ops center, multi-module shell, hub, agent
  home). Numbers go in as ratios, deltas or before-and-after pairs.
- **Plain ASCII.** No em or en dashes, curly quotes, NBSP or arrows.
- **Never invent data.** Every claim comes from a command you ran or code you read. What you could
  not check is written as `not checked: <reason>`.
- **One improvement per pull request.** Search first and add your evidence to an open pull request
  that already covers it instead of opening a second one.
- **Sensitive paths are the owner's.** A change under `.github/workflows/`, `checks/` or
  `templates/overlay/scripts/` is opened as usual but is merged only by the owner.

## 1. Does it belong in the core?

Apply the test in `CONTRIBUTING.md` ("Does it belong in the core?"): it would help another
consumer's agent that knows nothing about this machine, and it carries no name, path or value of
this estate. Either answer no: keep it local and stop. A rule that names a tool, host, tenant or
app becomes core material only once that name is a parameter with this case as one value.

## 2. Prepare

1. Core clone: the one the nightly pulls (the `core` key in
   `~/.config/build-standards-core/consumer.json`, else `~/GitHub/build-standards-core`). Never edit
   it; make your own worktree from it on a new branch cut from the current `origin/main`:
   `git fetch origin main && git worktree add <path> origin/main -b <role-words-branch>`.
   The core repository is the `core_repo` key in the same file, or `$CORE_REPO`; call it `$CORE`.
   Enable the hook there: `git config core.hooksPath checks/hooks`, and commit with a GitHub noreply email.
2. Scratch directory outside every repo, for example `mktemp -d` under the user's cache. The pull
   request description (`pr.md`) goes there.
3. Look for an open pull request:
   `gh pr list -R "$CORE" --state open --search "<two or three role words>" --json number,title,url -L 20`.
   When one covers the improvement, add your evidence as a comment on it (checked the same way as the
   description, step 5) and stop.

## 3. Make the change

Follow `CONTRIBUTING.md` for the change itself: agnostic (a value that is only ever this machine's
becomes a parameter with a documented default), a dated `CHANGELOG.md` entry in the same pull request,
Conventional Commits. Merge `origin/main` in before you push; never rebase.

## 4. Describe it

Write `pr.md` with these parts, in order:

1. **What.** One paragraph: the improvement, in the core's terms (which doc, rule, script, skill or
   part it changes).
2. **Why.** What went wrong or was slower without it, as seen on the consumer, described by role.
3. **Evidence.** Commands run and their result, code read (by role and relative path inside the core
   or a generic file name), before-and-after ratios.
4. **Adoption risk.** What another consumer would notice when it takes the change: none, low
   (visual only), medium (behaviour changes, no data loss) or high (a feature stops working).
5. **Adopted, adapted, rejected.** When the change comes from a source repo, which parts were adopted,
   adapted or rejected, by role and never by name.
6. **Issue outcome.** Exactly one of `Closes #N`, `Refs #N` with a `Remaining:` line, or
   `No issue: <reason>`. An improvement with no existing issue uses `No issue:`.

The title is a Conventional Commit line, a short plain sentence of what changes, by role.

## 5. Check, then open

1. From your worktree of the core:
   - `python3 checks/check-sanitised.py --file <scratch>/pr.md`
   - `python3 checks/check-consumer-neutral.py --file <scratch>/pr.md`
   - plain ASCII: `python3 -c "import sys; d=open(sys.argv[1],'rb').read(); sys.exit(any(b>127 for b in d))" <scratch>/pr.md`
   - the pre-merge set in `CONSUMING.md` section 13.

   Fix every hit and run all again. Do not open the pull request until all pass. Check the title the
   same way (write it to a file first). Every comment you post later is checked the same way.
2. Push the branch to `origin` and open it: `gh pr create -R "$CORE" --title "<title>" --body-file <scratch>/pr.md`.
3. Verify: `gh pr view <n> -R "$CORE" --json title,body,headRepositoryOwner` matches the checked file and
   the head repository is the core itself, not a fork.
4. Answer with the pull request URL. Drive it until it merges: fix a red check, merge `origin/main` when
   behind, and answer review comments.
