# Hermes configurations and plugins that proved themselves

Version: 1.5 | Last reviewed: 2026-10-17 | Status: current | Scope: every consumer that runs the
Hermes agent

Each entry names the setting, the value, why, and the failure it prevents. Values that differ per
consumer (channels, accounts, paths) are described, never filled in. Check the
[Hermes docs](https://hermes-agent.nousresearch.com/docs) for the current option names before
copying an entry, since the agent moves faster than this page.

## 1. Chat display

| Setting | Value | Why |
|---|---|---|
| `display.interim_assistant_messages` | `false` | One bubble per turn. Narration between tool calls stops pushing the answer off screen, and the final answer is always last |
| `display.timestamps` | `true` | The chat reads chronologically, so it is clear which reply belongs to which background event |

Prevents: an operator scrolling through progress notes to find the answer, and replies triggered
by background jobs being read as replies to the last question.

## 2. Scheduled jobs

- **Deterministic work is a script job with no agent.** Refreshes, sweeps, syncs and watchers run
  as `no_agent` jobs with a script. They cost no tokens and cannot improvise.
- **Agent jobs sit behind a pre-run gate.** A small gate script decides whether the model wakes:
  only when the input it would read changed (hash the bundle) and never more often than a minimum
  gap. The gate returns "no wake" otherwise. This was the largest cost cut on any job that polls.
- **Hash only what the job must act on.** When a bundle carries ambient context (group chats,
  channels, FYI mail) next to items the job must act on, hash the two apart. Material changes wake
  the model on the normal gap, and context alone wakes it only when the last run is a few hours
  old. A rolling chat window in the hash wakes the model on every tick and quietly defeats the gate.
- **Watch every job for failure by default.** The failure watcher reads every enabled job, with a
  short opt-out list that carries a reason per entry. A hand-kept list of watched jobs drifts: new
  jobs go unwatched and deleted ids linger.
- **Clean up after one-shot jobs.** A nightly script job removes one-shot jobs that finished
  cleanly more than a day ago, prunes ids that no longer exist from every registry keyed on job ids
  (catalog, watch lists, card maps), and reports recurring jobs that sat disabled for a week. It
  never removes a recurring job or a one-shot whose last run failed, re-reads the job list before
  each removal, and stops without changes when the job list cannot be read.
- **Deliver locally unless a human must act.** Board-only jobs deliver `local`. Only final results,
  approvals and failures go to a chat channel, and progress stays silent.
- **A no-agent job prints only signal.** A script job's stdout is delivered, so it prints nothing
  when all is clear and one line per thing a person must know otherwise. Every script job exports
  `PATH` first, since cron runs with a thin one. Prevents: a channel that fills with "ok" lines until
  the one real failure is missed.
- **One weekly job reviews dependency majors.** Majors are code changes, so no nightly opens one on
  its own (ci-cd-release.md section 4). One weekly job lists every major available across the repos,
  links each to its changelog, and hands each to a human decision. Acceptance: every open major has a
  decision newer than it.
- **Keep memory small with a job, not by hand.** A nightly job distils the day's sessions into the
  memory and skill files (lessons, not logs, section 6) and a nightly job backs the private context
  (memory, skills, job catalog) up to a private store. Both are script jobs with an agent step only
  where a summary is needed, and both report only on failure.
- **Describe every job.** Job names follow `<Area> - <what it does>`. Keep a description catalog
  next to the jobs (the scheduler has no description field) and add the entry in the same change
  that adds the job.
- **Every job id is the key.** Scripts and suppression rules key on job ids, never names, so a
  rename breaks nothing.

## 3. Credentials and accounts

- **Credential pool, fill first by priority.** With a seat-plan account and a usage-billed account,
  put the seat plan first and let the pool fall back. Watch for fallback while the first account
  still has headroom (an unexpected billed call is an incident, raise it once).
- **A plan-limit 429 fails over within 30 seconds.** By default the agent retries the same
  credential once before it rotates, and it honours Retry-After up to 600 seconds. A seat plan
  that hits its usage window sends a Retry-After of hours, so every turn sits idle for 10 minutes
  before the pool moves on. Treat a 429 whose reset is more than 30 seconds away as a plan limit
  and rotate at once, and cap any rate-limit wait at 30 seconds so an exhausted pool fails over
  or fails fast. Short throttles (reset under 30 seconds) keep the retry-once behaviour. Where
  this needs a local source patch, keep it in a marker-tagged, idempotent patcher that a
  scheduled self-heal re-applies after every agent update, and restart every long-lived agent
  process after it lands, because a process keeps the code it started with.
- **Adding a pool account can re-seed removed sources.** Signing in a new account can clear the
  suppression list for that provider, so credentials that were removed on purpose (an
  environment token, a borrowed CLI login) come back as pool rows. After every add, list the pool
  and remove anything that should not be there.
- **Never refresh a pool token from outside the agent.** A status page that reads usage must not
  refresh tokens: refreshing rotates the refresh token out from under the running agent.
- **Secrets come from the password manager at use time.** Read the value straight into its
  destination in one command, never into the transcript, never echoed, unset after.

## 4. Plugins

- **Middleware sees the agent, hooks do not.** Observer hooks run on their own thread, so the agent
  object (and which credential served a call) is not reachable from a hook. Resolve anything
  per-call in an inline middleware and hand it to the hook by request id.
- **Restart every process after a plugin edit.** The gateway and the desktop backend load plugin
  code once. After an edit restart the gateway and relaunch the desktop app, or old code keeps
  running (diagnose by grouping the plugin's output by platform).
- **A usage ledger plugin** that writes one line per model call (ids and token counts only, never
  keys or text) gives per-account usage that the agent's own session table cannot split. Keep the
  ledger bounded: rotate it by size or age (for example 90 days or 50 MB, whichever comes first),
  keep it outside any synced or repo folder with mode 0600, and never log prompts, keys or response
  text.
- **When the agent's Python cannot see entry-point plugins, install a plugin directory.** A
  runtime on a managed or bundled Python does not see packages `pip` put elsewhere, so an
  entry-point plugin installs cleanly and never loads. Install the plugin as a plain plugin
  directory under the agent home instead, and prove it with the agent's own plugin list, never with
  `pip`. Prevents: a filter plugin reported as installed that never ran.
- **Unapproved plugins stay disabled.** `homeassistant` is rejected in `hermes/tools.json`: smart-home
  control is out of scope for a work agent. A consumer that has it enabled disables it with
  `hermes plugins disable homeassistant`; the nightly job never installs or enables it and never
  removes anything.

## 5. Running under a service manager

- **Never kill by process name pattern.** The gateway may run under a wrapper process whose name
  matches common patterns. Kill only the exact child process id you started.
- **A headless browser for automation.** Run the automation browser headless under the service
  manager with a remote-debugging port, show it only when the operator must act (a sign-in prompt),
  and say so. The order for any system is API first, a hidden browser only when the API hits a
  wall, a visible browser only for a manual step.

## 6. Skills

- **The first 57 characters of a description are the trigger.** Write `Use when <trigger>.
  <one-line behaviour>.` so the skill list shows when to load it.
- **Lessons, not logs.** A skill records an imperative rule and why. Dates, ticket numbers and
  incident stories belong in the history, not the skill. `checks/check-hermes-skills.py` fails a
  hand-written shared (`core-`) skill that carries a date or a ticket id; a consumer can run the same
  pattern over its own skills.
- **Shared skills carry the `core-` prefix** and come from this repo ([README](README.md)).

## 7. Interpreter floor

- Scripts the agent runs on a shared machine target the oldest system Python still shipped with
  the operating system (3.9 on current macOS). `X | None` annotations crash at definition time
  there: use `from __future__ import annotations`.

## 8. Parallel workers on one repo

- **Each worker gets its own worktree, ports and database port.** A worker branches into its own
  git worktree off the remote main, runs its dev servers on its own local ports and its own
  Postgres port, and never touches the shared clone. Prevents: one worker's staged files, server or
  migration landing in another worker's commit or test run.
- **Never push to a branch whose pull request merged.** Check the pull request state before every
  push. Once merged, follow-up fixes go in a new branch and a new pull request. Prevents: commits
  stranded on a deleted branch that never reach main.
- **Push every fix before the review can go clean.** Where an auto-merge lane merges on green, the
  pull request merges the moment checks pass. Push all known fixes in one go, not one by one while
  checks run. Prevents: a half-fixed head merging.
- **Lockfile conflicts take main's lockfile.** On a rebase, check out main's lockfile, reinstall
  with the package manager, and commit the result. Never hand-merge a lockfile. Prevents: a lockfile
  that matches neither side and fails a frozen install in CI.

## 9. Shell portability on macOS

- **There is no `timeout` command.** Never prefix commands with it in scripts that run on macOS.
  Use the tool's own timeout setting or a background process with a kill.
- **grep has no `-P`.** For an ASCII check use `LC_ALL=C grep -n '[^[:print:][:space:]]' <files>`.
- **Run monorepo task runners through the package manager.** Call the runner through the pinned
  package manager (for example `npx -y pnpm@<version> turbo run build`), not bare `npx turbo`,
  which can fetch a different version outside the workspace. Prevents: tasks that silently run
  against the wrong tool version or none at all.

## 10. Proving work before reporting it

- **"Checks passed" shows the task count.** A worker's report of passing checks includes the
  runner's summary line (tasks run, tests passed). Empty output means nothing ran, not that
  everything passed. Prevents: a filter that matched no package being reported as green.
- **Verify the merge before publishing a release.** Read the pull request state (merged, with the
  merge commit) before tagging or creating the release, and target the branch name rather than a
  commit that may not be resolvable yet. Prevents: a release of code that never merged.

## 11. Token economy

The policy over this section and section 12 (where the spend goes, cache lifetime, delegation and
job budgets, each with its source) is [token-efficiency.md](token-efficiency.md).

What a consumer spends tokens on is mostly shell output read by the model, text the model writes,
and files that load every session. Three tools address those, and each has a decision under the
ingest rule (adopted as is, adapted with limits, rejected). The machine-readable copy is
[tools.json](tools.json). The nightly job (`hermes/nightly.py`, set up once by `hermes/setup.py`)
installs and enables every required tool from it, so a consumer does nothing by hand except restart
Hermes when the job says RESTART.

| Tool | Cuts | Decision | Why |
|---|---|---|---|
| rtk (Rust Token Killer) | Shell output (git, gh, test runners, linters, package managers) before the model reads it | adapted | Large measured saving, but it filters lines, so it needs the never-rewrite list below |
| caveman (terse voice) | Words the model writes | adapted | Real saving on output, but the skill adds input tokens every turn and fits only some work, so it is interactive-only and off by default |
| caveman-compress | Memory and context files that load every session | adapted | Real input-side saving, but the packaged skill fails the Hermes skills security scan, so it is optional and installed by hand only |

Both are tools from third parties. The core pins no version: check each project's current release
notes before installing, and re-read this section when a major version changes.

### 11.1 rtk

- **Install and enable.** Done by the nightly job: it installs the `rtk` binary with brew (or
  cargo), runs `rtk init -g --agent hermes` (which honours `HERMES_HOME`), enables `rtk-rewrite`, and
  prints RESTART. Restart the desktop app and gateway then, because plugins load once. By hand the same
  three commands apply. Prevents: a binary installed but a hook that never runs.
- **Scope.** Interactive sessions: on. Cron agent jobs and sub-agents: on, because they run the
  same noisy commands and nobody reads that output. The plugin rewrites commands, so it applies
  wherever the agent shell tool runs.
- **Never let it rewrite or compress what the answer depends on:**
  - failing test names, counts and the runner's summary line (section 10 already treats empty output
    as nothing ran),
  - infrastructure plans, especially anything that deletes or replaces a resource,
  - linter and type-check errors with their file and line,
  - a diff under review, and any output pasted back to a person as evidence,
  - secret-scan and security-scan findings,
  - exit codes.
  For those run the command through `rtk proxy <command>`, which runs it unfiltered and still
  counts it.
- **Recovery when a filter dropped what was needed.** A filtered result carries a recovery hash.
  `rtk recall <hash> --full` returns the whole output, `--from N`, `--lines N` and `--grep <regex>`
  return a part, `rtk recall --list` shows what is stored. If output is empty or reads only "N lines"
  when text was expected, treat it as dropped, not empty, and recall it. Prevents: a green report
  built from output the filter removed.
- **Measure.** `rtk gain` prints total commands, input and output tokens and tokens saved, from the
  consumer's own history. Record the percent before and after enabling, per consumer.

### 11.2 caveman

- **Install and enable.** Done by the nightly job with
  `hermes skills install JuliusBrussee/caveman/skills/caveman --yes`, which runs the Hermes skills
  security scan first (verdict safe). Switch the voice on for one session with `/caveman`. Do not turn
  it on globally. Prefer `hermes skills install` over `npx skills add`, which skips the scan.
- **Scope.** Interactive working sessions only, where the reader is the operator. Off for cron agent
  jobs whose result a person reads as a report, for every human-facing draft with a required voice
  (messages, release notes, documents, commit and pull request text), and for anything a downstream
  program parses. A sub-agent summary may be terse, but keeps every identifier, path, number and
  link the parent needs, since one dropped character breaks them.
- **Cost to weigh.** The skill adds roughly 1,000 to 1,500 input tokens per turn, so on work that is
  already terse the net can be negative. Switch it off for such work.
- **Measure.** From the usage ledger (section 4) compare output tokens and total tokens per turn for
  comparable work, one week with the voice and one without. Keep it only if total tokens per turn
  fall. Do not rely on the project's published percentages.

### 11.3 caveman-compress

- **Not installed automatically.** `hermes skills install` blocks it: the skills guard rates it
  DANGEROUS (it shells out to an agent CLI, reads the environment and rewrites agent context files),
  and `--force` does not override that verdict. The nightly job therefore leaves it alone. Install it
  by hand only after reading its scripts, and record that decision on the consumer. Prevents: a
  standard that quietly routes around the platform's security scan.
- **Claude Code.** Mandatory there for the user-level memory file: `claude/apply_claude.py` runs it
  nightly when the file is new or changed ([claude/README.md](../claude/README.md) section 4).
- **Use.** Run it on a file that loads every session (memory, standing instructions, a long todo
  list) with `/caveman-compress <file>`. It keeps a backup of the original.
- **Never compress** a file in the synced core skills directory (`hermes/sync_skills.py` would report
  it as a local edit), a secret store, a file another program parses, or a file a person edits by hand
  and expects in plain prose without rereading it.
- **Privacy.** The file goes to the configured model provider. Only compress files that provider may see.
- **Measure.** Count tokens of the file before and after, and read the file once to confirm no rule
  lost its condition. Prevents: a smaller file that changed what it says.

## 12. Context, memory and output size

These settings sit next to the tools above, because they decide how much of every turn is spent on
carrying old text. Option names are from the Hermes docs on
[context compression and caching](https://hermes-agent.nousresearch.com/docs/developer-guide/context-compression-and-caching);
check them for the current defaults.

- **Keep compression on.** `compression.enabled: true`. Context past the limit fails or degrades
  quality, and compression is the supported way through. Prevents: a long session dying at the window.
- **Set the trigger by context window, with a ceiling.** `compression.threshold` is a fraction of
  the model window (default 0.50). On large-window models pair it with `compression.threshold_tokens`
  (an absolute cap, the lower of the two wins) so a huge window does not let a session grow far past
  what is useful. Per-model values go in `compression.model_thresholds`. Prevents: a million-token
  window sending a million tokens on every turn.
- **Protect the tail.** `compression.protect_last_n` (default 20) and `min_tail_user_messages`
  keep the recent exchange verbatim. Do not lower them to save tokens: the model loses the thread it
  is in the middle of.
- **Prune big tool results early.** The proactive prune settings (`proactive_prune_tokens`,
  `proactive_prune_min_result_chars`) drop old oversized tool results before a full compression.
  This is the native counterpart to section 11.1 for output that already reached the model.
- **Cap the memory files.** `memory.memory_char_limit` and `memory.user_char_limit` bound the files
  that load into every session. Keep them small and move task knowledge into skills, which load only
  when relevant. This is also where 11.3 pays off. Prevents: a memory file that grows until it costs
  more than the work.
- **Cache prompts.** `prompt_caching.cache_ttl` set to match how often turns arrive keeps the stable
  prefix cached. Lowering `reasoning` effort per model (`agent.reasoning_overrides`, the key Hermes reads) trims
  output on routine work.
- **No native output cap was found.** The Hermes config reference lists no setting that limits shell
  output length, so rtk (11.1) is the mechanism for it. If a native key appears, record it here.
- **Open: MCP tool description size.** Tool schemas load into context on every turn, so a server
  with hundreds of tools is a standing cost. The Hermes docs reviewed here describe no compression
  for it. The measure that works today is to enable only the servers a profile needs. Re-check when
  the Hermes docs change.

## 13. Local model guidance

Applies only to a consumer whose Hermes runs a model on its own hardware (a local inference server).
A hosted provider needs none of it. These rules come from a machine whose requests were refused or
timed out once several agents shared one small server.

- **Know the real per-slot window.** A server started with N parallel slots divides its context
  pool: each session gets `pool / N`, not the pool. Read the real value from the server
  (`/slots` or `/props` report `n_ctx` per slot) and set `model.context_length` to it. Hermes budgets
  to the value it is told, so a wrong one lets a session overrun its slot. Prevents: "context size
  exceeded" answers to requests that looked small.
- **Fewer, larger slots beat many small ones.** Weights usually fill most of the memory, so the
  window is bounded by free memory after the weights, not by the model. Size the slot count to the
  agents that really run together, then raise the window until memory pressure shows. Prevents: four
  sessions silently sharing a window sized for one.
- **Cap every background source of load to the slots.** All three queues are separate, so cap each:
  `cron.max_parallel_jobs`, `kanban.max_in_progress` and the gateway's concurrent sessions. Their
  sum must not exceed the slot count, and one slot should stay free for the interactive session.
  Kanban's own default is no cap on a desktop, so it must be set explicitly.
- **A waiting request looks like a slow one.** A request queued behind a busy slot shows up as a long
  timeout, not an error. Treat repeated timeouts of several minutes as a capacity signal, not a
  flaky network, and reduce concurrency before raising any timeout.
- **Never let a failure pass unseen.** A job that fails at night must reach a human through the
  notification route (section 2: deliver only failures and results). Check the gateway was running
  before blaming the model: a missed run with a stopped gateway is downtime, not a model fault.
- **Verify after changing.** `hermes config get` for each key, then watch the next run for
  compression near the new window and for no refusals in the server log.

The short form an agent loads is the `core-local-model` skill.

## 14. Safe Hermes restart

A restart that interrupts running work loses it, and a restart started from inside the gateway can
kill itself. Use the self-disabling job in `hermes/safe-restart/` instead of restarting by hand
while agents are busy: enable it, and it waits for idle, restarts once, verifies, reports on the
review board and disables itself. Setup and design are in `hermes/safe-restart/README.md`. Hermes
rejects cron scripts containing gateway lifecycle commands, so the restart runs from a launchd
agent outside the gateway. The idle proof must cover every runtime that can hold work: no live kanban
worker, no other cron run in progress, no busy model slot, and no chat turn in flight in the desktop
backend. A probe that cannot be read counts as busy, never as idle.

## 15. Fallback and kanban boards

- **Prove the fallback with a real run.** A configured `fallback_providers` entry is not proof. Point
  a throwaway Hermes home at a stub model that accepts a request and never streams, run one
  prompt, and confirm the log shows the stale abort, the fallback model taking over and a finished
  reply. Use a copy of the credential file made after the last login. Prevents: a fallback that
  looks set but never works when the local model stalls.
- **The built-in `default` board cannot be removed.** Hermes has no delete for boards, and `default`
  is built in. Keep one live board for operator work and leave `default` empty, with no cron,
  script or card map writing to it.
- **Retire a board in this order.** Stop its workers, move each unfinished card to the live board
  with its remaining scope and context, close the original as `NOT DONE, MOVED` with a pointer to the
  new card, repoint every script and job prompt that names the board, then archive the board. Never
  close a moved card as plain done.

## 16. Pre-run gate library

Keep the gates of every agent job in one library. A gate prints, as its last stdout line,
`{"wakeAgent": false}` to skip the model. It always exits 0, because a gate is honoured only on
exit 0. On an unexpected error it fails open. A failing input wakes the agent on the third failure
in a row, then at most every 4 hours. A gated job can run more often, because most runs cost no
tokens; cap the expensive step (for example one analysis per 30 minutes).
