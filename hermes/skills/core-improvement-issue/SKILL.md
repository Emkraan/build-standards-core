---
name: core-improvement-issue
description: "Use when work on a consumer finds an improvement that belongs in the core: checks it passes the scope test, writes it up by role with no names, runs the sanitising checks, and opens one plain issue on the core repository."
---

# Core improvement issue

This is the upward path from a consumer to the core. The nightly files nothing by itself; when an
agent finds a shareable improvement, it opens one plain, sanitised issue on the core repository.
The owner approves the item there, and the account that owns an approved item opens the pull
request and merges it once `ci` and `visual` pass (`CONTRIBUTING.md`, "Reporting from a consumer"). This
skill is the procedure for the issue.

## Hard rules

- **The core is public.** The issue carries no repo, app, host, address, employer, person, account,
  tenant, plan, path, token or key. Describe each thing by its role (product app, local ops center,
  multi-module shell, hub, agent home). Numbers go in as ratios, deltas or before-and-after pairs.
- **Plain ASCII.** No em or en dashes, curly quotes, NBSP or arrows.
- **Never invent data.** Every claim comes from a command you ran or code you read. What you could
  not check is written as `not checked: <reason>`.
- **One improvement per issue.** Search first and comment on an open issue that already covers it
  instead of opening a second one.
- **No pull request before approval.** Open the pull request only after the owner approves the
  item in the issue, and only from the account that owns the change.

## 1. Does it belong in the core?

Apply the test in `CONTRIBUTING.md` ("Does it belong in the core?"): it would help another
consumer's agent that knows nothing about this machine, and it carries no name, path or value of
this estate. Either answer no: keep it local and stop. A rule that names a tool, host, tenant or
app becomes core material only once that name is a parameter with this case as one value.

## 2. Prepare

1. Core clone: the one the nightly pulls (the `core` key in
   `~/.config/build-standards-core/consumer.json`, else `~/GitHub/build-standards-core`). Read it,
   never edit it. The core repository is the `core_repo` key in the same file, or `$CORE_REPO`;
   call it `$CORE`.
2. Scratch directory outside every repo, for example `mktemp -d` under the user's cache. The draft
   (`issue.md`) goes there.
3. Look for an existing issue:
   `gh issue list -R "$CORE" --state open --search "<two or three role words>" --json number,title,url -L 20`.
   When one covers the improvement, write your evidence as a comment on it (checked the same way as
   the body, step 4) and stop.

## 3. Draft

Write `issue.md` with these parts, in order:

1. **What.** One paragraph: the improvement, in the core's terms (which doc, rule, script, skill
   or part it changes).
2. **Why.** What went wrong or was slower without it, as seen on the consumer, described by role.
3. **Evidence.** Commands run and their result, code read (by role and relative path inside the
   core or a generic file name), before-and-after ratios.
4. **Proposed change.** What changes in the core if it is approved, and the parameter that holds
   any value that is only ever this machine's.
5. **Adoption risk.** What another consumer would notice when it takes the change: none, low
   (visual only), medium (behaviour changes, no data loss) or high (a feature stops working).

The title is a short plain sentence of what changes, by role.

## 4. Check, then file

1. From the core clone:
   - `python3 checks/check-sanitised.py --file <scratch>/issue.md`
   - `python3 checks/check-consumer-neutral.py --file <scratch>/issue.md`
   - plain ASCII: `python3 -c "import sys; d=open(sys.argv[1],'rb').read(); sys.exit(any(b>127 for b in d))" <scratch>/issue.md`

   Fix every hit and run all three again. Do not post until all three pass. Check the title the
   same way (write it to a file first). Every comment you post later is checked the same way.
2. File: `gh issue create -R "$CORE" --title "<title>" --body-file <scratch>/issue.md`.
3. Verify: `gh issue view <n> -R "$CORE" --json title,body` matches the checked file.
4. Answer with the issue URL. After the owner approves, the pull request declares the outcome with
   `Refs #N` or `Closes #N`.
