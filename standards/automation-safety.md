# Automation Safety Standard

Version: 1.1 | Last reviewed: 2026-10-21 | Status: current | Scope: all

Rules for any automation that acts without a person at the keyboard: scheduled jobs, review and
merge lanes, fix sessions, agents and the buttons in an operator UI that start them. They decide
what automation may touch, how it proves a write before making it, and how it fails. This doc is
the source of truth. Where a reference implementation differs, the implementation is fixed, or the
consumer records an explicit exception (README, "Source of truth and explicit exceptions").

Related: [PR Review and Merge](pr-review-and-merge.md), [Live Actions](live-actions.md),
[Notifications](notifications.md) (how failures reach the owner),
[PowerShell Scripting](scripting-powershell.md), [Python Scripting](scripting-python.md).

---

## 1. Rules

1. **Automation acts only on its owner's own work.** A lane, job or session changes only items owned by the account it acts for. Work owned by other people is surfaced to the owner for direction and never fixed, merged, closed, approved or commented on by automation.
   - Prevents: automation overriding a colleague's judgement or committing the owner to something nobody agreed to.
   - Acceptance (test): the ownership check runs before any write, and a test with an item owned by someone else asserts no write.
2. **Every write path has a dry run.** Each command that writes supports a dry-run or what-if mode that prints the exact actions it would take and makes no write. New jobs ship in dry run first.
   - Prevents: learning what a job does from the damage of its first run.
   - Acceptance (test): a test runs each write command in dry-run mode against a fake backend and asserts zero write calls.
3. **Never smoke-test on real items.** Prove a write path with synthetic records, a scratch state directory, a scratch server port and fake binaries. Test refusal guards with an impossible value (an all-zero commit sha). Restore anything touched and label synthetic data as synthetic.
   - Prevents: a test merge, approval, post or close that cannot be taken back.
   - Acceptance (review): test notes name the synthetic fixtures and the guard values used.
4. **Re-verify live state immediately before acting.** A queued item, UI row or brief is a snapshot. Re-read the object right before the write, pin the version that was reviewed (head sha, run attempt, updated time), and refuse when it moved. Destructive and privileged acts also require a typed confirmation of the object's name.
   - Prevents: merging commits nobody reviewed, approving a run that changed, and deleting the wrong object from a stale screen.
   - Acceptance (test): tests change the live version between read and act and assert a refusal with a "refresh first" message.
5. **Fail closed on read errors.** An error, a timeout or a short read is never "nothing there". Nothing is approved, closed or deleted on a failed read, and destructive runs carry a change cap.
   - Prevents: a broken source that closes every open item or deletes every object it could not see.
   - Acceptance (test): tests feed a failing and a truncated source and assert no write and a non-zero result.
6. **One stable work item per problem set.** Raise one item per distinct set of problems, with an id derived from the sorted problem keys, never from volatile text such as counters or dates. The same set updates in place, a dismissed item stays dismissed until the set changes, and a clean run closes it. The generator reads the dismissed store.
   - Prevents: a dismissed item returning on the next run as "new", and a queue that floods with duplicates.
   - Acceptance (test): tests reword the title and reorder the problems and assert the same id, and change the set and assert a new one.
   - A handled decision holds against new keys. Once the owner resolved, ignored or snoozed an item, a later item that matches it (the same object, sender or problem set, matched deterministically, never by a model's judgement) is an alias of the handled one and stays handled, even when the generator gives it a new key. It shows again only when there is new source evidence dated after the decision: a message received, a commit pushed, a check run or a state change read from the system of record after the decision time. Model prose (a summary, a re-worded title, a model's claim that something changed) is never evidence. A snooze lasts until its window ends.
   - Acceptance (test): a handled item regenerated under a new key with no new source evidence stays handled; the same item with a source record dated after the decision shows again; the same item with only new model-written text stays handled; a snoozed item reappears after its window and not before.
7. **Retries are idempotent and bounded.** Every action is safe to repeat and treats "already done" as success. One session runs per (object, version, problem), with a daily cap per object and a run budget per session.
   - Prevents: double merges, duplicate comments and runaway sessions on one stuck item.
   - Acceptance (test): tests replay an action after success and assert one effect and a success result.
8. **No grace periods that hide failures.** Act on or surface a problem the first time it is seen. Debounce only transient infrastructure errors, by counting consecutive failures, never by delaying the first report of a real problem or by timers that hide an item.
   - Prevents: problems that wait unseen for a timer, and alert storms from a flapping dependency.
   - Acceptance (review): every delay in the job is a consecutive-failure count, a backoff after the first alert, or a budget.
9. **Kill only your own processes.** Track the process ids a job starts and stop them by id or process group after checking the command line still matches. Never kill by a name pattern.
   - Prevents: one job stopping a sibling run, a gateway or the operator's own session.
   - Acceptance (review): no `pkill`, `killall` or pattern kill in the job, and stops are by recorded id.
10. **Human gates stay human.** Automation never approves its own work, bypasses a red required check, applies a delete or grants access on the owner's behalf. It prepares the evidence and a button, and the owner's click is the sign-off. One standing exception, recorded as the owner's decision (2026-10-21): the bounded own-PR merge lane (section 8) may bypass the approval count on the owner's own pull requests, and nothing else.
    - Prevents: automation turning a review into a formality.
    - Acceptance (review): every bypass or privileged call is reachable only from an owner action, or is the bounded own-PR lane's approval-count bypass, logged per merge.

## 2. Ownership and direction

- Decide ownership from the system of record (PR author, ticket assignee, resource owner tag),
  not from a name in free text.
- Items owned by someone else are shown with what is wrong and who owns it. The owner decides
  whether to give direction, and any message to that person is a draft the owner sends.
- An automation identity that writes as the owner writes in the owner's voice, with no tool
  attribution, and never commits the owner to a date, scope or assignment.

## 3. Proving a write path

1. Dry run against a copy of real state. Read every planned action.
2. Run the write against synthetic records on a scratch server or a fake binary that logs its
   arguments and returns canned output. Assert the exact calls.
3. Exercise each refusal: moved version, wrong owner, missing confirmation, failed read.
4. Restore any file you touched and delete any scratch session, record or worktree.
5. Only then point it at real data, and watch the first real run.

Pass test overrides inline on each command. An override exported into a persistent shell leaks a
fake binary or a scratch state directory into the next live run.

## 4. Stable ids for work items

- Basis order: an explicit stable key set by the generator, else the primary reference (first
  ticket or object id only), else a normalised title with counters, dates and numbers removed.
- Keep the basis in one function used by the generator, the store and every reader. A second copy
  that drifts breaks dismissals.
- Put a generation number in the id when a new instance of the same problem should reappear, and
  bump it only when the evidence changes.

## 5. Sessions and processes

- One session per (object, version, problem). A new version (a new push) clears the previous
  give-up and may start one new session.
- A session ends with exactly one machine-readable result line (fixed, triaged, gave up, nothing to
  do) and removes its own worktree.
- A session that needs a decision, an outside dependency or access it lacks gives up and says why.
  It does not guess.
- Detached workers record their process group. Liveness checks compare the command line, so a
  reused process id never reads as alive.
- Never edit a shell script while a run of it is in progress. The shell reads scripts as it goes and
  the rest of the run executes shifted text. Copy it for a variant instead.

## 6. Checklist

- [ ] Ownership checked before every write, others' work surfaced for direction.
- [ ] Dry run on every write path.
- [ ] Tested on synthetic records, scratch servers and fake binaries, guards tested with impossible values.
- [ ] Live state re-read and version pinned right before acting, typed confirmation for destructive acts.
- [ ] Failed or short reads write nothing.
- [ ] One work item per problem set with a stable id, dismissals read by the generator.
- [ ] Actions idempotent, "already done" is success, sessions capped.
- [ ] No timers that hide problems.
- [ ] Processes stopped only by recorded id.
- [ ] Approvals, bypasses, deletes and grants only from an owner action.

## 7. Count floors and change caps

- **Count floor.** A bulk cleanup reads the whole set first and refuses to continue when any paged
  read returns fewer rows than its floor (set per job; 1,000 by default). A throttled or truncated read can then never make every item look stale.
- **All-or-nothing cap.** Build the full candidate list before changing anything. If it is over
  the change cap (25 by default), change nothing and print the would-change list. A cap never stops a run half done.

**Acceptance (test):** a read under the floor throws; a candidate list one over the cap changes
nothing and prints the list; a list at the cap proceeds.

## 8. The bounded own-PR merge lane

A repo whose merge gate requires an approval can let a standing lane merge the owner's own pull
requests without that approval, because the owner is the only reviewer and would approve their own
work anyway. The owner approved this bounded form (2026-10-21). Any lane that goes further is not
this lane and falls under rule 10 unchanged.

- **What it may bypass:** the required approval count only. Nothing else.
- **What it never bypasses:** a red, missing or pending required check; a freeze window (read live
  on each pass); a hold label; an escalation rule that fires (a policy hold, a sensitive path, a
  trust hold, pr-review-and-merge.md section 4); an untriaged high finding or an unresolved thread.
- **Whose pull requests:** only those the owner authored, decided from the system of record (the
  PR author), never from text.
- **Switch:** it runs only while its switch (a repository variable or a parameter the owner sets)
  is on. Off means it merges nothing and says so once.
- **Log:** every merge it makes with the bypass writes one log line or record: the pull request,
  the head commit merged, that the approval count was bypassed, and the checks it read.
- **Pinned:** each merge names the head it read (pr-review-and-merge.md rule 6).
- Acceptance (test): with the switch on, an owner pull request that is green with no hold merges and
  logs the bypass; a red or pending check, a freeze, a hold label, a firing escalation or another
  author each leaves it unmerged; with the switch off nothing merges.
