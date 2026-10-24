---
name: core-token-economy
description: Use when shell output looks empty or cut, before turning a terse voice on, or before compressing a memory or context file. Keeps token savings from dropping what the answer depends on.
---

# Token economy

The full decision record is `hermes/configurations.md` section 11 in the core repo. This is the
short form an agent needs while working.

## Shell output (rtk)

- Output that is empty, or reads only "N lines", when text was expected was dropped by the filter,
  not empty. Recall it: `rtk recall <hash> --full` (hash from the recovery hint), or `--grep <regex>`
  for a part, `rtk recall --list` to see what is stored.
- Run these unfiltered with `rtk proxy <command>`, never through a filter: failing test names and
  the runner summary line, infrastructure plans (especially deletes and replacements), lint and
  type-check errors with file and line, a diff under review, secret and security scan findings,
  and exit codes.
- Never report "checks passed" from filtered output without the runner's task or test count.

## Terse voice (caveman)

- Interactive working sessions only, switched on per session. Off for cron results a person reads,
  every human-facing draft with a required voice (messages, release notes, documents, commit and
  pull request text), and anything a program parses.
- Code, commands, paths, numbers, errors and links stay exact in every voice.

## Compressing a file (caveman-compress)

- Only for files that load every session. Never a file under the synced core skills directory,
  a secret store, or a file another program parses. Keep the backup. Read the result once to confirm
  no rule lost its condition.

## Measuring

A saving counts only against the consumer's own ledger: `rtk gain` for shell output, and the usage
ledger plugin for tokens per turn with and without the voice. If total tokens per turn do not fall,
turn the tool off.
