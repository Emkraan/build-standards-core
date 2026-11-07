# Plan: the optional log intake module (E1 to E7)

Source: the hub's feature inventory (intake issue 117, comment 6607335699, section 3). Decision: build into the core as an opt-in
module (README, "The opt-in contract"). Status of the evidence: the hub's text and named tests only; the source is not available, so each
entry says whether it is **specified** (the text and tests fix its behaviour) or **needs source** (the text names the feature but not its
shape).

## What the module is

Devices post a JSON envelope to one route per stream with one key per stream; a stream (mode, schema, retention, rate limit) is data
edited in a tool, not code; the latest snapshot per device is kept locally so reports work with no cloud workspace; an optional sink
forwards rows to a workspace table.

## Module layout (server side, `opscenter/server/modules/log_intake/`)

| File | Holds | Entries |
|---|---|---|
| `streams.py` | The stream record, its schema, the namespace rule for sink tables, validation | E1, E2, E3 |
| `stream_store.py` | Streams as data: create, update (audited), delete (typed confirmation), ingest key per stream (hashed) | E1, E2, E3 |
| `ingest.py` | The post route: key check, envelope validation, row cap, field mapping, per-device hourly limit with 429 and a one hour Retry-After | E1, E2 |
| `current_store.py` | The latest post per device (an older replay is ignored), retention sweep | E5 |
| `sink.py` | The workspace sink slot and the access test that names the missing role and scope | E6 |
| `routes.py` | Registers the routes above only when the module is enabled | all |

Setting: `OPSCENTER_LOG_INTAKE` (a JSON file or `1` with defaults). Absent: nothing above is imported.

## Entry by entry

| # | What is built | Specified or needs source | Tests (from the hub's named tests, written fresh) |
|---|---|---|---|
| E1 | One post route per stream with one ingest key per stream; a stream is created in the tool, never in code | Specified: rejects a missing, a wrong-stream and an unknown key; accepts a post and maps its fields; validates the envelope and caps rows. Needs source: the envelope shape and the field mapping grammar | rejects missing, wrong-stream and unknown keys; accepts and maps; envelope validation; row cap |
| E2 | Stream settings: mode (latest per device or events), editable schema, retention (default 90 days), per-stream per-device hourly limit (default 6 for latest, 50 for events, range 1 to 1000), a device over it gets 429 with a one hour Retry-After | Specified (defaults, range, 429, Retry-After, audited updates, schema changes never reuse a column). Needs source: the schema editing model | limits one device and leaves others alone; honours a raised limit; defaults and audit; mode switch; a schema change never reuses a column; a retention edit (the hub has none: written here) |
| E3 | Sink table names must match one configurable pattern or the call is refused before any request; deleting a stream needs the table name typed; table, retention and schema changes are audited | Specified: the namespace rule and the typed confirmation. The pattern is configuration (the hub's is its own prefix) | owns only tables in its namespace; refuses tables outside it; destructive edits need the confirmation and write an audit entry; the typed confirmation when dropping a sink table (the hub has none: written here) |
| E4 | Interim share drop (a relay posts files devices wrote to a share) | Not built: hub-specific transport. The 429 path in E2 is its only server side | none |
| E5 | The latest snapshot per device kept locally, so reports work with no workspace | Specified: keeps the latest post per device, ignores an older replay | keeps latest; ignores an older replay |
| E6 | Workspace tab data: editable settings, a read-only access test naming the missing role and scope, a marked test row, a forwarding switch; a stream with no table is skipped, not failed | Needs source: the hub's pull request is still open and red; the text gives the behaviour, not the contract of the access test | a missing right is reported with the role and scope that would grant it; a stream with no table is skipped; a marked row send (the hub has no test: written here) |
| E7 | Device log folder with a size cap roll | Not built: a device scripting convention (`cmtrace-logging.md` covers log format and rolling) | none |

## Client side (the kit session)

A Log intake page group behind the same setting: streams list and editor, the key reveal-once dialog, the typed-confirmation delete,
the workspace tab with the access test result. Opt-in entry point in the kit, not part of the default bundle.

## Open questions pending the source

1. The envelope and field mapping shapes (E1).
2. The schema editing model and column reuse rule (E2).
3. The access test contract and what "marked row" means (E6).
4. Whether the sink is one slot or one per cloud (E3, E6).
