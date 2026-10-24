# Claude Code: shared setup

Version: 1.0 | Last reviewed: 2026-10-18 | Status: current | Scope: every consumer that runs Claude Code

Registry: [tools.json](tools.json). Applier: `apply_claude.py`, run by the nightly sync
([hermes/nightly.py](../hermes/nightly.py)) after the Hermes step. No consumer runs a command per
session: the nightly job installs what is missing and reports `RESTART` once when a new session is
needed. The step is off by default: turn it on per consumer with `"apply": {"claude": true}` in the consumer
config. It is skipped quietly when the `claude` CLI is not installed.

## 1. One standard, every repo

- Everything installs at **user scope**. No repo carries a per-tool file, and no repo gets a tool
  another repo lacks. Prevents: one repo on a code graph and another on a different server.
- Each tool has one decision in the registry. A rejected tool is not installed anywhere.

## 2. The decisions

| Tool | Decision | What the nightly job does |
|---|---|---|
| rtk | adapt, required | installs the Claude Code PreToolUse hook (`rtk init -g --auto-patch`) |
| context-mode | adapt, required | adds the marketplace, installs and enables the plugin |
| codebase-memory-mcp | adopt, required | npm install, vendor installer (registers the server and its steering hooks), `auto_index true`, `~/.local/bin` link |
| token-savior | reject | nothing; it overlaps the code graph and its evidence is one unverified repo |
| caveman-compress | adapt, required | compresses the user-level `CLAUDE.md` when new or changed (state in `~/.local/state/build-standards-core/compressed.json`) |

"Required" here means required once a consumer turns this opt-in step on, never on a machine that
did not. `caveman-compress` is a separate case on the Hermes side: there the skills scan blocks it,
so the Hermes nightly never installs it and it stays optional and manual (CONSUMING.md section 4,
[hermes/configurations.md](../hermes/configurations.md) section 11.3). Here it is the compression
of the coding agent's own memory file, which this step runs with the agent CLI it already needs; a
machine without that CLI skips the whole step quietly.

Why one code graph and not two: every MCP server puts its tool schemas into every session, which is
the cost being cut. A second navigation server doubles that for the same job.

Two rules sit beside the tools:

- **mcp-secrets (required).** No literal token in the user config. Store it in the OS keychain and give
  the server a `headersHelper` script that prints `{"Authorization": "Bearer ..."}`, or reference an
  environment variable. The nightly job flags a literal one as MISSING; it never rewrites the file.
- **claude-ai-connectors (advisory).** Every connected claude.ai connector puts its tool schemas into every
  session. Remove the unused ones in the account settings (web UI only). The keepers are listed in the
  consumer's own notes, not in this repo.

## 3. Licence note

context-mode is Elastic License 2.0, not an OSI open source licence. Using it on a personal or
company machine is allowed; a consumer that bundles or redistributes it must review the terms first.

## 4. caveman-compress

- Mandatory for the user-level memory file named in the registry. It loads every session, so the saving repeats.
- Backups are kept out of tree. A failed validation leaves the file untouched and the nightly report says MISSING.
- It needs Python 3.10 or newer (the macOS system Python is too old), the `claude` CLI and the skill
  from the Hermes skills directory. Hermes' skills guard rates the skill DANGEROUS, so the nightly
  Hermes step still does not install it (configurations.md section 11.3); install it once by hand
  after reading its scripts. Until then this step reports MISSING whenever a registered file is due
  (new or changed and at least `min_bytes`). A file that is not due needs none of the tools, so a
  consumer whose memory file is small or unchanged passes without the skill installed.
- Repo-level `CLAUDE.md` and `AGENTS.md` are not touched: they are committed, reviewed text.
- The file goes to the model provider; only files that provider may see belong in the registry.
