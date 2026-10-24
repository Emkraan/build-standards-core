# Token efficiency for an agent home

Version: 1.0 | Last reviewed: 2026-10-20 | Status: current | Scope: every consumer that runs the
Hermes agent against a paid model provider

This standard says where an agent home's model spend goes and which setting controls each part. It
is the policy layer over the operating detail in [configurations.md](configurations.md) sections 11
and 12, which stay the reference for how each tool is installed and used. Each rule gives its value
where the source measured one, and the measurement a consumer runs where it did not.

## 1. Source and what it measured

The source is one agent home's token audit of 2026-10-13, which read 30 days of per-call usage from
the agent's session store (provider, model, input, output, cache read and cache write tokens, and
cost, per session and per session source). Its findings, as shares so they carry no estate's
absolute numbers:

- Cache reads and cache writes made up nearly all of the billed spend. Output tokens were a small
  share.
- Two long interactive sessions made up about two-thirds of the billed spend. One of them made
  about 2.5 times the calls of the other and wrote more cache.
- Sub-agent workers (one issue per worker) made up about a quarter of the billed spend, spread over
  a dozen sessions.
- Scheduled and kanban agent calls cost nothing because they ran on a local model.
- At the time of the audit the prompt cache lifetime was 5 minutes, stale tool output was never
  pruned (`proactive_prune_tokens: 0`), compression triggered at half the window, and sub-agents ran
  on a pinned cloud model with the default turn ceiling of 250.

What the audit did not measure, and what this standard therefore does not invent: the saving of
shell output filtering on this machine, the saving of compressing context files, a prune threshold,
a sub-agent turn ceiling, and a per-job budget. Sections 3, 5 and 6 give the measurement that sets
each one.

**Re-measure** with the same query after any change below, over at least a week of comparable work,
and compare cost per session by source (interactive, sub-agent, scheduled, kanban, one-shot).

## 2. Prompt cache lifetime

1. **Match the cache lifetime to how turns arrive.** Interactive and messaging sessions use the long
   lifetime (1 hour). Scheduled jobs, kanban workers and sub-agents use the short one (5 minutes).
   In Hermes, `prompt_caching.cache_ttl: auto` applies exactly that split.
   - Why: a pause longer than the lifetime makes the next turn rewrite the whole context at the cache
     write rate, and cache traffic is most of the spend (section 1). A person pauses for longer than
     5 minutes all the time. An unattended run does not pause, so the long lifetime only raises its
     write price.
   - Cost to weigh: at the provider's pricing on the audit date a 5-minute write costs 1.25 times
     the base input price and a 1-hour write 2 times. The long lifetime pays off only when a session
     would otherwise rewrite after a pause.
   - Acceptance (review): the agent config sets the split (or `auto`), never one long lifetime for
     every source.
2. **Keep the stable prefix stable.** Skills, memory and tool schemas load before the conversation.
   Change them between sessions, not during one, since any change to the prefix invalidates every
   cached turn after it.

## 3. Context size: compression and pruning

1. **Compression stays on and triggers by window share with a token ceiling.** Use the settings in
   [configurations.md](configurations.md) section 12: `compression.threshold` as a share of the
   window, paired with `compression.threshold_tokens` on large-window models so the lower of the two
   wins.
2. **Prune old oversized tool results before compressing.** `proactive_prune_tokens: 0` (the audit
   value) never prunes, so every later turn re-reads stale tool output from the cache. Set a non-zero
   threshold.
   - The audit measured no threshold. Set it from the consumer's own sessions: take the median
     context size at which sessions first compress, start the prune threshold well below it, and keep
     it only if cost per interactive session falls with no rise in re-run tool calls.

## 4. Shell output and the model's own words

1. **Filter shell output before the model reads it.** rtk is required, scoped and recovered as
   [configurations.md](configurations.md) section 11.1 says.
   - The audit did not measure its saving here; the project's published range is not a measurement.
     Record `rtk gain` before and after enabling, per consumer.
2. **A terse voice is a small lever.** Output tokens were a small share of spend (section 1), and
   the terse-voice skill adds roughly 1,000 input tokens to every call. Expect a single-digit
   saving at most, so it stays interactive-only and off by default
   ([configurations.md](configurations.md) section 11.2).
3. **Compress the files that load every session, by hand and measured.** Context-file compression
   cuts input on every call, which is where the spend is, but its published saving was not measured
   here. Measure each file before and after and reread it once
   ([configurations.md](configurations.md) section 11.3).

## 5. Delegation

1. **Pin the sub-agent model explicitly.** `delegation.model` and `delegation.provider` are set, never
   inherited, so a change to the main model never silently moves every worker. Unattended workers
   that write code use a cloud model of the quality the work needs; a local model is used for a
   worker only where its own guidance says it fits ([configurations.md](configurations.md)
   section 13).
2. **Escalate per call, not per profile.** A worker that needs a stronger model gets it on that one
   delegation call. The profile default stays the cheapest model that does the routine work.
3. **Set a turn ceiling from measurement.** The default ceiling (`delegation.max_iterations: 250`)
   let sub-agent workers reach about a quarter of the spend (section 1).
   - The audit measured no better value. Read the turn count of the consumer's completed workers,
     set the ceiling a margin above the turn count that covers nearly all of them, and treat a worker
     that hits the ceiling as a failure to report, never as success.

## 6. Scheduled jobs and sub-agents: budgets

1. **Script first, gate second, model last.** A job that can be a script runs with no agent. An
   agent job sits behind the pre-run gate ([configurations.md](configurations.md) sections 2
   and 16), so the model wakes only on changed input.
2. **Unattended agent work runs on the cheapest model that does it.** In the audit, scheduled and
   kanban agent calls cost nothing because they ran on a local model.
3. **Every recurring agent job and every delegated batch has a budget.** The budget is a cost or
   token ceiling per run and per day, read from the usage ledger
   ([configurations.md](configurations.md) section 4), and a run over it is reported once per job.
   - The audit set no budget values. Set each from the job's own median over a week, with headroom,
     and review them with the re-measurement in section 1.

## Change log

| Date | Change |
|---|---|
| 2026-10-20 | First version, from the agent-home token audit of 2026-10-13. |
