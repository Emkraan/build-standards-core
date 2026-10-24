---
name: core-local-model
description: Use when Hermes runs a model on local hardware, or a local model run fails with refusals, size errors or long timeouts. Sets window, concurrency and failure visibility.
---

# Local model guidance

Full record: `hermes/configurations.md` section 13 in the core repo. Skip this skill for a hosted
provider.

## Before running work on a local model

1. Read the server's real per-slot window (`/slots` or `/props`, field `n_ctx`) and make
   `model.context_length` equal it. A shared pool is divided by the slot count.
2. Cap load to the slots: `cron.max_parallel_jobs`, `kanban.max_in_progress` and gateway sessions
   together stay below the slot count, leaving one slot for the interactive session. Kanban has no
   cap by default, so set it.
3. Prefer fewer, larger slots. The window is bounded by memory left after the weights.

## When a run fails

- "Too large" or "context exceeded" on a small request: the slots are full or the window is
  mis-set. Check the server log and the two settings above before anything else.
- Timeouts of several minutes: the request waited for a slot. Lower concurrency, do not raise the
  timeout.
- A missed scheduled run: check the gateway was up first.
- Route every failure to a human through the notification route. Never leave one in a log only.

## After a change

`hermes config get <key>` for each key, then confirm on the next run.
