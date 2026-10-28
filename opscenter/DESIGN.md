# Core ops center: design

Status: draft for owner review. Design only; no code exists yet.

Inputs: `standards/local-ops-app.md` (the ops center rules today), `standards/web-ui.md`,
`standards/web-shell.md`, `standards/web-api-runtime.md`, `standards/rules.json`, `kit/README.md`,
`CONSUMING.md`, the core nightly tooling (`hermes/nightly.py`, `hermes/ops_center.py`,
`hermes/consumption.py`, `hermes/setup.py`, `hermes/report.py`), the approved Table A (105 rows)
and Table B (31 rows, all approved as recommended), the 20 approved assessment decisions, and the
two consumer assessments of 2026-10-23.

Names used here: the "shell consumer" owns the multi-module shell and is the UI and UX reference.
The "hub consumer" owns the hub; its ops center supplies the guard, the writer, the schemas, the
cost-gated analyzer and the automerge. Table A rows are cited as `A-n`, Table B rows as `B-nn`,
owner decisions as `D7-n` (section 7 of the assessment summary).

## 0. Owner rules this design obeys

1. The ops center is identical on every consumer. It changes only through slots and parameters.
   No consumer edits a core file; a consumer that needs a change files it upward.
2. Downstream apps may differ in function but share the UI and infrastructure standards.
3. Where the two consumer designs conflict, the shell consumer wins on UI and UX. The approved
   mechanisms from the hub consumer are the guard, the writer, the schemas, the cost-gated analyzer
   and the automerge.
4. The core names no tool, app, host, employer or person. Everything estate-specific is a slot or
   a parameter. A core check (section 9, R3) fails the build on a literal that belongs in one.

## 1. Scope and layout

### 1.1 Where it lives in the core

```text
opscenter/
  DESIGN.md            this file
  CONTRACT.md          the neutral contract (routes, state files, slots, parameters); replaces the
                       per-app contract/ops-center-contract.md
  server/              stdlib Python HTTP server and API modules
    app.py             entry: bind, gate, registry, static files
    gate.py            Host and Origin guard, body cap, security headers, preflight
    registry.py        route registry (method, path, auth class, schema, handler)
    envelope.py        {success, data|error} helpers and the error taxonomy
    swr.py             stale-while-revalidate cache, single flight per key
    run.py             the one subprocess helper (timeout, missing binary, nonzero exit)
    writer.py          the single default-deny outward writer (applier)
    approvals.py       the approvals inbox at /api/approvals
    state.py           atomic state read and write helper and command line entry, the only
                       writer of state files
    heartbeats.py      job liveness against the job manifest
    modules/           one file per core screen's API (action, awareness, drafts, work, reviews,
                       knowledge, plans, debt, activity, search, core, infra, overview, badges)
  engine/
    collect.py         runs collector slots, writes the inbound spool
    analyze.py         the cost-gated analyzer engine
    refresh.py         scheduler entry: collect then analyze, silent unless attention
    routing.py         routing rules as data (local-ops-app section 16)
    conformance.py     the conformance checker
    migrate.py         one-time state converter (section 3.4)
  schemas/
    envelopes/         the six envelope kinds (section 3.1)
    state/             one schema per state file
    api/               one schema per API section
    slots/             one schema per slot's payloads
    params.schema.json the parameters file schema
  slots/
    interfaces/        one interface module per slot (section 5)
    reference/         reference adapters: code host, work tracker, docs home
    null/              the null adapter for every other slot
  app/                 React, TypeScript, Vite front end on the kit AppShell
    src/shell/         rail, header, strip, palette, banners host, module registry
    src/screens/       core screens (section 4)
    src/slots/         slot UI mount points (tab, card, chip, banner, page)
  deploy/
    deploy.py          the deploy contract (section 7)
    automerge.yml      the automerge workflow template (section 7.2)
  adopt/
    adopt.py           the adopt command (section 8)
  testing/
    fixtures.py        approval fixture helper, fixture state dir, fake slot adapters
  applicability.json   which rules.json rules apply to an ops center (prerequisite P3)
  tests/               stdlib unit tests, app unit tests, e2e smoke
```

### 1.2 How it is consumed and synced

The ops center is consumed the way the kit is: a synced copy, never hand edited.

```text
<consumer ops center repo>/
  opscenter-core/      synced copy of the core opscenter/ (except DESIGN.md, tests/, adopt/)
  kit-core/            synced copy of kit/ (existing)
  tokens-core/         synced copy of tokens/ (existing)
  standards-overlay/   existing overlay, lock and checks
  local/
    params.json        the parameters file (section 6), schema checked, no secrets
    slots/             the consumer's own slot adapters, each with its schema
    modules.json       which optional slot modules are on (people, lanes, builds, documents)
```

- The consumer's ops center is registered in mode `ops-center` (class apply-at-once, as today in
  `CONSUMING.md` and `hermes/ops_center.py`). The nightly applies each core release at once behind
  the local gate; a repo with its own CI gate lands it by pull request (`apply_via: pr`). Nothing in
  this flow changes; the sync step gains `opscenter-core/` as a target path.
- The build compiles `opscenter-core/app` against `kit-core/` and `local/slots/*/ui` (slot UI is
  loaded through the slot registry, section 5.1), so the runtime copy never reads the checkout.
- `standards-overlay` gains one check, `check-opscenter-sync`: `opscenter-core/` equals the pinned
  release byte for byte, so a local edit fails CI and the pre-push guard.
- Mode name note: the current core uses mode `ops-center` with class `apply-at-once`; the two
  assessments disagreed on the name. This design keeps `ops-center` (mode) and `apply-at-once`
  (class) and does not rename either.

### 1.3 Slot versus parameter

- A **parameter** is a value: a string, number, list, path, flag or small object in
  `local/params.json`. It changes behaviour inside core code. Example: the home route, the port,
  quiet hours, the required checks list.
- A **slot** is code: an adapter that implements a core interface (section 5) and ships its own
  payload schemas. It supplies data or performs an outward act for an integration the core does not
  know. Example: the work tracker, the mail collector, the agent runtime.
- A slot that is absent resolves to the null adapter. Every screen, tab, chip and banner that
  depends on it hides. No core screen depends on a slot to render.
- A slot never writes outward on its own. Every outward act goes through the writer (section 2.5),
  which calls the slot's `act` with an approved operation.
- A slot never writes state files directly. It returns data; the core `state.py` writes it.

## 2. Backend

### 2.1 Runtime

- Python 3 standard library only (`http.server`, `urllib`, `json`, `hashlib`, `sqlite3` read only,
  `unittest`). No third-party packages, in core or in reference adapters.
- `ThreadingHTTPServer(("127.0.0.1", port), ...)` only. The bind address is not a parameter.
  `port` is (default 8766).
- State directory from parameter `host.state_dir`; runtime directory from `host.runtime_dir`. Both
  live outside the repo, so a deploy never touches data or identity.
- No auth layer. The loopback bind plus the gate is the boundary.
- `state.py` is callable outside the server (section 3.2). The server imports it, and any other
  process that writes the state tree runs it as a command, so the lock and the header have one
  implementation and no second write path exists.

### 2.2 Route registry and the gate

Every route is declared once:

```python
route("GET", "/api/action-center", auth="read", schema="api/action-center", handler=...)
route("POST", "/api/handled", auth="write", body="api/handled-request", handler=...)
route("GET", "/api/tackle/prompt", auth="plugin", token="one-time", handler=...)
```

- Fields: method, path pattern, auth class, response schema, request body schema, handler, cache
  class (`no-store` for people data, `no-cache` plus ETag otherwise).
- Auth classes: `read` (Host check), `write` (Host and Origin check), `plugin` (Host check, Origin
  `null` allowed, one-time token required, preflight answered for that path only).
- An unknown path under `/api/` is 404 in the envelope. Any other path is a static file inside the
  built `app/dist`; traversal is 403.
- The gate runs before the registry dispatches, deny by default:
  1. `Host` must be `127.0.0.1:<port>`, `localhost:<port>` or the same without the port, else 403
     `bad_host`. This covers every verb, GET included (closes the shell consumer's L-12 defect).
  2. On POST, PUT, PATCH, DELETE: an `Origin` that is present must be a loopback origin, else 403
     `bad_origin`. No `Origin` passes (scripts, tests).
  3. Body cap (parameter `server.max_body`, default 1 MiB): 413 above it.
  4. Headers on every response: `X-Content-Type-Options: nosniff`, the route's cache class, and
     never `Access-Control-Allow-Origin: *`. A preflight answers only loopback origins on `plugin`
     routes.
- Handler exceptions return 500 in the envelope; the server stays up.
- Slots register routes through the same registry under `/api/slot/<slot>/...`; a slot cannot
  bypass the gate because it never sees the socket.

Acceptance (test): a test walks the whole registry and shows each route refused with a bad Host
(403), each write route refused with a foreign Origin (403), an oversized body refused (413), no
response carrying a wildcard CORS header, and an unregistered POST answered 404.

### 2.3 The envelope

- Success: `{"success": true, "data": <payload>}`. Failure: `{"success": false, "error":
  {"code": "<snake_case>", "message": "<one line>", "detail": <optional object>}}`.
- Codes are a closed list in `envelope.py`: `bad_host`, `bad_origin`, `too_large`, `not_found`,
  `bad_request`, `conflict`, `denied`, `stale`, `upstream`, `internal`. HTTP status follows the code.
- Per-section degradation (local-ops-app section 7): a section whose source fails returns
  `{"generated_utc": ..., "error": "..."}` inside a successful envelope. The UI shows one quiet
  "could not be read" state for that section only.
- The client uses one reader (`api.ts`, from S-1 when it lands) that accepts only the envelope. A
  tolerant reader that also accepts bare JSON exists for one release (R2) so outside scripts can
  move first, then is removed.
- Payloads are validated against their schema in tests and, when `server.validate_responses` is on
  (default on in tests, off at runtime), at the response edge.

### 2.4 Live reads behind a stale-while-revalidate cache

- No bundle of state into static files (B-02). Every screen reads the server, which reads state
  files and slot sources live.
- `swr.get(key, ttl, loader)`: a fresh entry is served; an expired one is served at once while one
  background refresh runs (single flight per key); a failed refresh keeps the last good value and
  records the error on the section; one source never poisons another key.
- TTLs are parameters per section (defaults: state files 2 s, infra jobs and runners 15 s, code
  host 30 s, spend 60 s, plan limits 300 s, consumption feed 60 s).
- Read paths never write. Any step that today stamps or harvests during a read moves to an engine
  job first (shell consumer risk: the bundle step writes).
- Build-time datasets (a changelog for the build card) stay a build step, not a live read.
- ETag on every `no-cache` response; an unchanged poll is a 304 with no body.

### 2.5 The single outward writer

There is one path to change anything outside the state directory: `writer.py`. No module, slot or
engine job calls an outward write any other way. A core check (`check-opscenter-writer`) fails on
an outward call site outside `writer.py` and the slot `act` methods it invokes.

**Operation.** Every outward change is an operation:

```json
{
  "id": "op-<sha256 prefix>",
  "scope": "code_host | work_tracker | docs_home | core | <slot name>",
  "action": "pr.ready | pr.merge | issue.comment | page.publish | ticket.transition | ...",
  "target": {"kind": "...", "ref": "..."},
  "direction": "publish | update | delete | comment",
  "content": "...",
  "content_hash": "sha256 of content",
  "base_hash": "sha256 of the target as read when the operation was built, or null",
  "pin": {"head_sha": "40 hex, for pull request actions"},
  "requested_by": "owner | engine:<job> | session:<id>",
  "created_utc": "..."
}
```

**Applier steps,** in order, each a hard stop:

1. Already recorded in the applied ledger (same id): return the recorded outcome (idempotent).
2. A rule in parameter `writer.rules` allows this scope, action and direction. With no rule the
   operation is denied (default deny) and recorded as `denied`.
3. The operation carries an approval record (from the inbox, or the owner click that built it) and
   the approval's hash equals `content_hash`.
4. Re-read the target live through the slot's `read`. `base_hash` still matches, and for pull
   request actions the head equals `pin.head_sha` and the required checks are green. A mismatch is
   `stale`: nothing is written and the UI says what moved.
5. Write, unless dry run. A rule is live when its effective flag is on. The effective flag is the
   rule's switch in `writer-rules.json` when one has been set from the screen, else the rule's
   own `live`, else `writer.live` (a parameter, default `false`). The three core approvals
   (section 4.4) ship with explicit rules that are live by default, so they never silently dry
   run (hub consumer risk).
6. Read back and verify the effect.
7. Record the outcome in the applied ledger and write a tombstone (section 2.5.1).

**Tombstones.** An applied or refused-as-already-done operation leaves a tombstone keyed by target.
The UI shows the item as done until the next source read confirms it, so a double click or a stale
poll never offers the same act twice.

**Live switch.** Parameters are read once at start, so a rule's live flag needs its own way to
change at runtime. The Core page carries a "Writer rules" card (section 4.2) that lists every
rule with its scope, action, direction, effective flag, where the flag comes from (parameter or
switch), and the result of its last dry run. Each rule offers three actions:

- **Dry run.** The writer replays the rule's pending approved operations through every applier
  step with the write forced off, and the card shows each step's result and the outcome the
  operation would have recorded. Nothing outward is written and no operation changes state. One
  activity record notes the dry run.
- **Enable.** Allowed only when a dry run of that rule finished after the rule last changed (its
  rule hash), replayed at least one operation, and had no refused step. A dry run that replayed
  no operation never qualifies, because it passes with nothing tested. It needs a typed confirm (section 4.4) of the text
  `<scope>.<action> live`, and the server re-checks the text and the dry run before it flips
  the flag.
- **Disable.** Always allowed, one click, no dry run needed.

The switch is itself a writer operation (scope `core`, action `rule.live`, requested by the owner
click only, never by an engine job or session). Its state is a `kv` file, `writer-rules.json`
(schema `writer-rules/1`, writer `server.writer`), holding the flag and the rule hash it was set
for. A rule that changes in `local/params.json` drops its switch, so a changed rule starts from
its parameter value and needs a new dry run. Every switch is one activity ledger record. The
three core approval rules appear in the card and can be switched off, never silently.

Acceptance (test): enable is refused with no dry run, with a dry run older than the rule, with a
dry run that replayed no operation, and with a dry run that had a refused step. Enable with a matching dry run and the typed text flips the
flag. Disable needs neither. A dry run writes nothing through the fake slot. A rule edited in
parameters loses its switch. A session or engine caller is refused. Each switch leaves one
activity record.

**Approvals inbox, `/api/approvals`.** `GET` lists pending, approved, rejected and applied entries.
`POST` queues one entry `{operation, decision: approve|reject}`; it refuses missing fields, a
`content_hash` that does not match `content`, and a duplicate id. The writer drains approved
entries. Machine callers (engine jobs, sessions) queue proposals here; only an owner decision
approves. The shell consumer renames its local `/api/approvals` (change records) before it adopts
(D7-4).

**Test fixture helper** (`opscenter/testing/fixtures.py`, D7-5):

```python
with approved(op_or_matcher, live=True) as rec:  # writes a rule and an approval record
    call_the_flow()
assert rec.applied == [...]  # what the writer did, read back from a fake
```

It also ships `fake_slot(scope)` (records `act` calls, scripted `read` results) so a consumer's
tests of flows that write outward pass without hand-written approval files. The shell consumer
measured that this drops its 78 writer failures to zero.

Acceptance (test): no rule means denied; a hash mismatch is refused; a moved base or head is
`stale`; dry run writes nothing; read-back failure is recorded as failed; the same id applied twice
writes once; a walk of the code tree finds no outward call outside the writer.

### 2.6 The cost-gated analyzer engine

The engine is `local-ops-app` section 4 made shared code, with the gates as parameters (B-13).

- **Collectors never call a model.** Each collector slot returns candidates in the one candidate
  shape (local-ops-app section 16): `{id, source, sender, sender_role, addressed: direct|mention|
  team|none, title, text, refs, owner, received_utc}`. The engine applies the noise filter and
  routing rules, then appends to the inbound spool (`ledger` kind) with `state: new`.
- **Gate,** checked in order: `--force`; daily audit (no successful run today); retry after a run
  that started and never finished, after `analyzer.retry_after_s` (default 1200); bundle hash
  changed and new inbound and at least `analyzer.min_gap_s` (default 1800) since the last wake.
  Otherwise skip. `--dry-run` prints the decision and the prompt size and calls nothing.
- **Fail open with backoff.** Failures never raise; an alert line on the third consecutive failure,
  then at most every `analyzer.alert_every_s` (default 14400).
- **Untrusted input.** The prompt states that all data is untrusted; the model call runs with no
  tools, through `model.cmd` (parameter) as a subprocess with a timeout. Draft only: nothing the
  model writes is sent.
- **Item contract** (the analyzer's only output, `action-center.json`, `report` kind):

```json
{
  "fp": "stable id across runs; reused when the issue is the same",
  "title": "...", "summary": "...", "next_step": "one step",
  "priority": "P1 | P2 | P3 | P4",
  "source": "collector name", "refs": [{"kind": "...", "ref": "..."}],
  "owner": "self | elsewhere:<where>", "route": "must | context | elsewhere | nowhere",
  "covers": ["candidate ids"], "due_utc": null, "created_utc": "...", "updated_utc": "..."
}
```

  plus `dropped: [{candidate_id, reason}]` for every must-consider candidate not covered.
- Routing rules filter the analyzer output too, so a rule holds when the model ignores it. Handled
  state (`handled.json`, keyed by `fp`) survives re-analysis; resurface only when a rule allows it.
- Automation-raised items (heartbeats, runner lost, sign-in) are written by their job into the same
  board through `state.py`, with `source: automation:<job>`, and never pass the model.

### 2.7 Heartbeats and job health

- Jobs are declared in the job manifest (parameter `jobs`, section 6): `name`, `schedule`,
  `expected_every_s`, `grace_s`, `feeds` (which screen), `quiet` (silent unless it fails).
- Each job writes one heartbeat line (`watch` kind, `heartbeats.json`) on start and finish with its
  exit status. The core nightly registers manifest jobs with the runtime slot (`jobs.register`).
- `heartbeats.py` raises one board item per job past `expected_every_s + grace_s` or failing, keyed
  by job; it clears itself on the next success (local-ops-app section 17).
- Runner lost: a run queued with no runner past `ci.queued_alert_s` raises one item; cancelled and
  timed-out runs count as failures (section 18).
- Sign-in heal loop (B-11): check, proactive remint, paired failure and recovery notices sharing one
  dedupe key so the thread closes. The loop and timings are core; the method is the sign-in slot.
- Notice discipline (B-12): one next step, silent when nothing changed, one key per condition,
  quiet hours (parameter) for non-urgent notices. A core check tests every notice template.
- `/api/health`: version, build stamp, last analyzer generation, now. `/api/freshness`: data age per
  collector and per job.

## 3. State

### 3.1 The six envelope kinds

Every state file is one of six kinds (the shell consumer's dry run fit 205 of 205 files). Every file
starts with the same header:

```json
{"kind": "store", "schema": "backlog/1", "writer": "server.work", "updated_utc": "..."}
```

| Kind | Shape | Use |
|---|---|---|
| `ledger` | append-only records `{id, at_utc, ...}`, JSON array or JSON lines (`.jsonl`, header as line 1), one writer or a declared producer and drainer (below) | spool, activity, applied, alerts, approvals inbox |
| `store` | `records: {<id>: {...}}` | backlog, projects, ideas, handled, tackle sessions |
| `kv` | `values: {<key>: <scalar or small object>}` | publish modes, acks, small decisions |
| `watch` | `targets: {<name>: {status, last_seen_utc, last_ok_utc, detail}}` | heartbeats, sign-in health, collector health |
| `report` | `generated_utc` plus `sections: {...}` with per-section `error` | action center, awareness, docs queue, freshness |
| `config` | a parameters-like object, read only at runtime | routing rules, alert sources, job card map |

**Producer and drainer.** A ledger is not always written by one process. An inbox is appended by
the process that receives the work (the server, under the lock) and later drained by a separate
job that marks each record as handled (the approvals inbox and the inbound spool are both this
shape). A ledger schema therefore declares either one `writer` or a pair:

```json
{"kind": "ledger", "schema": "approvals/1", "producer": "server.approvals", "drainer": "engine.writer", "updated_utc": "..."}
```

- The producer appends. It never changes a record once written. It is also the only role that
  prunes: the drainer never removes a record, so something has to expire them, and that is the
  producer's retention pass. The pass removes whole records only, under the same lock, through
  `state.py`, and it stamps the producer's name. For the inbound spool the producer is the
  collector step of the engine (`collect.py`), and it runs the pass at the start of every
  collection. A record expires when its marker shows it was drained (a final `state`) and its
  `at_utc` is older than `analyzer.spool_days` days. A record still marked `new` never expires,
  so unprocessed work is never dropped by age. A ledger that is pruned names its retention
  parameter in its schema (`spool_days` here), and a ledger that names none is never pruned.
- The drainer never appends and never removes. It changes only the marker fields a record
  declares in the schema (`state`, `applied_utc`, `outcome` and the like), through a read modify
  write under the same lock. The `id`, `at_utc` and every content field stay as the producer
  wrote them, so the content hash of a record is the same before and after a mark.
- Both go through `state.py` and stamp their own name in the header's `writer` field of the write
  they make. A write by any other name is refused.
- Only a `ledger` may declare a pair. Every other kind keeps exactly one writer.

Acceptance (test): the producer cannot change a marked field of an existing record. The drainer
cannot append, remove, or change a content field. A third name is refused. The retention pass
removes a drained record older than `analyzer.spool_days` and leaves a younger one and any record
still `new`, and a prune by the drainer is refused. An append and a mark
at the same moment lose neither. A schema that declares a pair on a kind other than `ledger` is
refused by the conformance checker.

Markdown logs (plans tree, debt files, decision logs) stay outside the schemas, their front matter
is read by a parser that has its own fixture tests.

### 3.2 Per-file schemas

- Each state file has one schema in `schemas/state/` that extends its envelope kind
  (`"extends": "envelopes/store"`), names its one writer (or, for a `ledger`, its producer and
  drainer, section 3.1), and versions itself (`backlog/1`).
- The core ships schemas for every core state file. The starting set is the hub consumer's 26
  schemas (12 state, 13 API sections, plus approvals), with the gaps it found filled: activity,
  collector health, sign-in health, analyzer state, plan limits history, docs state, suppressions,
  and the `identity` field typed as an object.
- A slot ships a schema for every file and payload it produces, in its own `schemas/` folder; the
  slot loader refuses a slot without them.
- Every state file has exactly one writer, except a `ledger` that declares one producer and one
  drainer (section 3.1). All writers go through `state.py` (atomic temp file plus `os.replace`, a
  file lock for read-modify-write, the header stamped on write).
- `state.py` is callable outside the server. The server imports it. Every other process that writes
  the state tree (a scheduled script, a gate script, a skill, a job that keeps state of its own)
  runs it as a command, so it takes the same lock and stamps the same header and nothing needs a
  second write path:

  ```text
  python3 state.py [--state-dir DIR] [--writer NAME] [--lock-timeout-s N] <command> <file> [args]
    append  <file> <record>        ledger kinds: add one record (id and at_utc stamped when absent)
    replace <file> <document>      store, kv, watch, report and config kinds: write the whole file
    update  <file> <key> <patch>   read modify write of one record or value, under the lock
    read    <file> [key]           read the file or one key, no write
  ```

  - The state directory is `--state-dir`, else parameter `host.state_dir`. A record, document or
    patch is JSON text, `@<path>` or `-` for standard input.
  - A write command needs `--writer`. The value must equal the writer the file's schema declares.
    For a ledger that declares a producer and a drainer, the declared writer means
    either of the two, so the producer's name and the drainer's name are both accepted and any
    other value is not. A script that owns a file is declared as its writer in that schema, for
    example `script.<name>`. Any other value is refused with `denied` and the file is untouched.
  - The document is validated against the file's schema before the write. A violation is refused
    with `bad_request` and the file is untouched. The header (`kind`, `schema`, `writer`,
    `updated_utc`) is stamped by the command and never taken from the caller.
  - The lock wait is bounded by `--lock-timeout-s` (default 10). A held lock past it is refused
    with `conflict`.
  - Output is one JSON line, `{"ok": true, "file": ..., "written": <n>}` or `{"ok": false,
    "code": ..., "message": ...}`, with a code from the envelope list (section 2.3). The exit
    status is 0 for success, 1 for a refused write and 2 for bad usage.
  - Reads take the same lock in shared mode and never write.

Acceptance (test): two processes appending to one ledger at the same moment lose no record. A
replace keeps the header and stamps `updated_utc`. A `--writer` that is not the declared writer (for a
ledger, its producer or its drainer) is refused and the file is byte for byte unchanged. A schema violation is refused and the file is
unchanged. A held lock past the timeout exits 1 with `conflict`. A read never changes the file.

### 3.3 The conformance checker

- `engine/conformance.py <state dir> [--server URL] [--slots DIR]`. Stdlib only. Supports the
  subset the schemas use (`type`, `required`, `properties`, `items`, `values`, `enum`) plus
  `extends` and a JSON lines mode (one record schema per line, header on line 1).
- Offline it checks every state file; with `--server` every API section. A section `error` is a
  warning, not a failure.
- CI runs it on the fixture state dir and on every slot's fixtures. The ops center's own gate runs
  it with `--server` against the freshly deployed runtime (section 7).
- Contract change rule: the contract markdown, the schema, the fixtures and the conformance tests
  change in the same pull request. A schema version bump without a migration step fails a check.

### 3.4 Migration contract for existing state

- `engine/migrate.py <state dir> --plan` reads every file, maps it to a target schema through a
  per-consumer map file (`local/migrate-map.json`: source file, target schema, field renames) and
  prints what it would convert. Nothing is written.
- `--apply` first copies the whole state dir to `<state dir>.pre-<release>`, then converts in the
  order config, watch and report, kv, store, ledgers last (a live ledger means writer and reader
  change in the same release).
- A record it cannot convert is reported with its file and index and left out of the converted
  file; it is never fixed silently. The run exits 1 when any record failed, and the owner decides.
- Idempotent: a file already at the target schema version is skipped.
- Readers accept the previous version for one release (one-time reader), then drop it.
- Writers move to `state.py` before their files convert, so a converted file is never rewritten in
  the old shape.

## 4. App

### 4.1 Shell

- Built on the kit `AppShell` with `Rail`, `NavGroup`, `NavItem`, `Header`, `FeedStrip`,
  `BuildCard`, `CommandPalette`, `ShortcutLayer`, `Toaster`, `useConfirm`, `TooltipLayer` and
  `ErrorBoundary`, exactly as the shell consumer composes it (owner rule 3): four rail groups with a
  hue per item, letter jumps, pin with `[`, the build card and refresh line in the rail footer.
- Rail badges come from one endpoint, `/api/badges` (A-2), polled every 30 s and on focus. A badge
  is a count only and never raises a notice (A-61).
- Header: title, date subtitle, sync chip ("Live, data refreshed <time>" or "API unreachable,
  retrying"), theme toggle, search trigger. Home link points at the home route parameter.
- Feed strip: up to 12 status items, each supplied by a module or slot provider (A-6).
- Command palette with server search (`/api/search`, debounced, minimum 2 characters, top 8 per
  provider), and a full search page (A-8, A-9). Search providers register per module and slot.
- Banners host: page-top banners supplied by slots (A-12); none ship in core content.
- Markdown reader from the kit (A-16).
- Accent and brand mark are parameters; one accent for the app.

### 4.2 Rail destinations and screens that ship in the core

Only Table A rows marked core. Slot-supplied tabs mount into these screens when their slot is on.

| Group | Destination | Route | Tabs and content | Table A |
|---|---|---|---|---|
| Operate | Overview | `/overview` | stat tiles, link cards, freshness tiles per collector | 13, 15 |
| Operate | Action Center | `/action` | Now (board with resolve, snooze, ignore, ignore forever, undo, route elsewhere, freeze strip), Awareness, Drafts (copy only), Completed (reopen), Routing (rules as data with preview), Alerts (job runs with ack) | 17 to 23, 25, 28 to 30, 34, 94 |
| Operate | Work | `/work` | Backlog (list and drag board), Projects (progress and notes), Ideas (decide, send to a build session) | 40, 41, 43 |
| Operate | Reviews | `/reviews` | Needs me (generic PR decision card: head pin, live re-read, tombstone, approval brief, hold label, maintenance hold, dependency wait, merge queue proof), Other repos (rerun) | 44, 46, 50, 53, 55 |
| Knowledge | Knowledge | `/knowledge` | Proposals (diff, approve, reject, rewrite of sent back), Coverage (gap detection), History, publish mode per class | 70 to 74 |
| Knowledge | Plans | `/plans` | trackers and library, reader, archive and restore | 77 |
| Knowledge | Debt | `/debt` | Needs decision, To do, Parked, Snoozed, Done | 78 |
| Platform | Infrastructure | `/infra` | Overview roll up, Scheduled jobs, Live jobs, Code host, Runners, Spend, Heartbeats | 79 to 83, 85, 87 |
| Platform | Core | `/core` | consumption panel (section 4.4), writer rules card (section 2.5) | 57 to 61, 64, 65 |
| Platform | Activity | `/activity` | every change, newest first | 14 |
| (palette) | Search | `/search` | full search across providers | 9 |

- The People group (1:1 board, team, yearly) appears only when the people slot is on; it is off by
  default (B-30).
- Slot destinations: Work tracker (`/tracker`, A-35 to A-39), Reviews lanes (`/reviews/<lane>`,
  A-45), Builds (`/builds`, A-88), Documents (`/documents`, A-75, A-76), and the Resilience and
  Plan limits tabs in Infrastructure (A-84, A-86).
- Reviews visibility check (A-54) and the daily sitrep (A-93) are core engine jobs; the sitrep
  channel is a parameter and the job exits 1 when its data is unreadable.

### 4.3 The home route

- Parameter `app.home`, default `/action` (B-01). Overview ships as a core page either way.
- `/` and unknown routes redirect to `app.home`. Header Home and the palette's home entry use it.
- When the ops center is mounted inside a multi-module shell, the shell's hub is home and the tool
  switcher is the way back (web-shell section 9, D7-10); the ops center then claims no `/`.

### 4.4 The consumption panel

The core ships the panel, the server module and their tests (`local-ops-app` section 19 becomes the
contract text; the feed writer stays `hermes/consumption.py`).

- Reads only `consumption.json`, format `build-standards-consumption/1`; any other format, a missing
  or invalid file is an error state with no rows. The read makes no code host call. 60 s cache.
- Cards: Consumers (label, mode, class, report only, pinned and latest, sync PR, status and UI,
  approval), Adoption suggestions with risk, My report (awaiting my decision, approved with no core
  PR), Peers (open reports, shipped by other accounts, count of new).
- The three approvals, each one click, each a writer operation with an explicit live rule:
  1. **Ready:** mark a draft sync PR ready for review.
  2. **Merge:** merge the sync PR by the repo's declared method, pinned to the head seen.
  3. **Approve item:** post `approve <id>` on this account's own report issue.
- **Typed confirm** (B-10): the confirm dialog requires the exact text, `<repo>#<number>` for a PR
  action, `<id> on issue #<n>` for an item, and `<scope>.<action> live` to enable a writer rule
  (section 2.5). The server re-checks the text.
- The server re-reads live before acting: a PR that is not open records a tombstone and says
  already done; a moved head or failing checks refuses; an item not in the awaiting list or an
  issue that is not this account's report refuses.
- Approval control is absent on apply-at-once and report-only rows, disabled while checks fail.
- Never: push a branch, write an approval-gated app's files, merge on failing checks, comment
  anywhere but the own report issue.

### 4.5 Approval section for downstream apps

The Core page groups the account's downstream apps (registered by `adopt`, section 8.2) in their own
card, "Downstream apps":

- One row per app: repo label, mode, report-only flag, pinned and latest, sync PR with CI state,
  core-status counts, UI verdict, last report-back time.
- A report-only app shows its status and no approval control. "Promote to applied" appears after one
  clean report and is itself a writer operation (it changes the consumer file through the core
  setup path, never the app repo).
- An applied, approval-gated app offers Ready and Merge on its sync PR with typed confirm, exactly as
  in 4.4. The nightly never merges for it.

## 5. Slots

### 5.1 The slot contract

Every slot is a folder with:

```text
<slot>/
  slot.json        name, interface, version, capabilities, routes, ui mounts, params it reads
  adapter.py       implements the interface (stdlib only)
  schemas/         one schema per payload
  fixtures/        fixture payloads for conformance and tests
  ui/              optional: tab, card, chip, banner or page components on the kit
```

- Interface methods are a fixed set per slot kind: `status()`, `list(query)`, `read(ref)`,
  `act(operation)` (called only by the writer), `collect(since)` (collectors only).
- `status()` returns `{available: bool, reason}`; unavailable hides the slot's UI.
- Capabilities declare which actions `act` supports; the writer refuses an action outside them.
- Timeouts and subprocess calls go through `run.py`; every read is wrapped by `swr`.
- The null adapter returns `available: false` and empty lists, and refuses every `act`.

### 5.2 Reference adapters (D7-3)

| Slot | Reference adapter | Verbs |
|---|---|---|
| `code_host` | over the code host CLI, read paths through `swr` | list repos, PRs, runs, checks; read PR with head and checks; act: comment, ready, merge pinned to head, rerun, review approve or request changes, label |
| `work_tracker` | over the tracker's REST API with a token from the sign-in slot | list (sprint, backlog, needs me, change approvals), read, act: transition, comment, move |
| `docs_home` (variant `git`, default) | over a git-backed docs repo through `code_host` | list pages, read page with hash, act: publish by pull request, update |
| `docs_home` (variant `api`) | over the docs home's own API, for a consumer whose docs home is not a git repo | list pages under the allowed roots, read page with hash and ancestor chain, act: publish, update (never delete), each with a scope proof and a read back (below) |

**The `api` docs home variant.** A docs home that is not a git repo has no pull request to review,
so the adapter itself must prove what a review would. Parameter `docs.adapter` picks the variant
(`git` by default) and parameter `docs.allowed_roots[]` lists the page roots a write may touch.
The adapter refuses any write it cannot prove, in this order, each a hard stop with the code in
section 2.3:

1. **Scope proof.** The target is resolved live to its ancestor chain, and one ancestor must be an
   allowed root. A target that cannot be resolved, whose chain cannot be read, or that sits
   outside every root is `denied`. A new page needs a parent that passes the same proof. A move
   out of a root is a write on the destination and the source, and both must pass.
2. **No delete.** Direction `delete` is not in the variant's capabilities, so the writer refuses it
   before the adapter is called, and the adapter refuses it again if called.
3. **Body hash.** The hash of the body the adapter is about to send equals the operation's
   `content_hash`, and for an update the live page's hash equals `base_hash`. A mismatch is
   `stale`, nothing is written.
4. **Write,** unless dry run (section 2.5).
5. **Read back.** The page is read again and its body hash must equal `content_hash`. A mismatch
   is recorded as `failed` with both hashes, never as applied.

The `api` variant uses the same operation shape, approval and applied ledger as every other slot.
Credentials come from the sign-in slot and never appear in a parameter or an operation.

Acceptance (test, against a fake docs API): a target outside every root is denied. A target whose
ancestor chain cannot be read is denied. A delete is refused. A body whose hash differs from
`content_hash` is refused. A moved base is `stale`. A read back that differs is `failed`. A
target inside a root with matching hashes is applied and read back. The `git` variant behaves
as before.

Every other slot ships an interface and the null adapter.

### 5.3 Every slot from Table A

| Slot | Table A | Interface summary | Shipped |
|---|---|---|---|
| `people` | 7, 27, 67, 68, 69 | roster from parameter; list 1:1 topics, team read, member profiles, yearly records; act: schedule, save; chip "next 1:1", strip "team away" | null, off by default |
| `runtime` | 12, 24, 51, 52, 80, 89, 90 | jobs list and run now, register manifest jobs, sessions (tackle launch with claim token protocol, B-09), discuss session, restart, spend ledgers, account pool, fallback watch, banners | null |
| `freeze_source` | 26 | list windows `{name, start_utc, end_utc, exception}` | null (strip is core) |
| `collector` (one per source: mail, chat, tickets) | 31, 32 | `collect(since)` returns candidates; rules from parameters | null |
| `meetings` | 33 | list meetings, read transcript, produce digest items; privacy scrub and private file modes are core rules | null |
| `work_tracker` | 35 to 39 | see 5.2 | reference |
| `classification` | 42 | the work type and project default sets | null (empty set) |
| `digest_source` | 43 | ideas digest input | null |
| `review_lanes` | 45, 56 | lane manifest `{lane, repo, tabs, engine_check, gates, canary}`; mounts `/reviews/<lane>` on the core PR card | null |
| `gated_deploys` | 47 | list pending gated deployments and plan runs; act: approve, reject, retry | null |
| `docs_home` | 70 to 74 (source) | see 5.2 (variants `git` and `api`), naming scheme from parameter (B-14) | reference |
| `doc_builder` | 75 | build a draft from a template path and header label | null |
| `doc_archive` | 76 | list and read documents from a folder of one doc kind | null |
| `resilience` | 84 | watchdog, self heal, backup and restore drill status | null |
| `spend` | 85 | spend rows per account and model; the page is core | null (page shows tokens only) |
| `plan_limits` | 86 | session and weekly windows per account | null |
| `pipelines` | 88 | pipeline list from parameter; read progress and what landed | null |
| `ci_host` | 80 to 83 | runners, live jobs, runner log with redaction, watchdog path | null |
| `sign_in` | 96 | method (interactive or app credential), token check, remint, notify | null |
| `notify` | 93, 95 | send one notice to the channel parameter with a dedupe key | null (prints to stdout) |
| `desktop_embed` | 105 | deep link and embed for a desktop host plugin | null |
| `code_host` | 44, 46, 82 | see 5.2 | reference |

Claim token protocol (core, B-09): `POST /api/tackle` stages a prompt file (mode 0600, TTL
`tackle.prompt_ttl_s`, default 300) and a one-time launch token; the runtime slot launches the
session; the session fetches the prompt once (`plugin` auth), binds with a claim secret, and reports
with it; the server verifies the reporting session is the bound one. States: launching, claimed,
running, resolved, failed; unclaimed after `tackle.claim_timeout_s` (default 360) is failed. One
launch at a time. The prompt says draft only.

## 6. Parameters

`local/params.json`, checked against `schemas/params.schema.json`, read once at start. No secrets:
secret references name a store and a key, never a value.

| Group | Parameter | Default | Notes |
|---|---|---|---|
| identity | `owner`, `display_name`, `author_label`, `team_name` | required | no literal in code (L-02, L-04) |
| identity | `roster_file` | null | people slot only |
| identity | `commit_domains` | `[]` | declared exception: commit author domains allowed besides the noreply identity (D7-14); the identity check reads it |
| repos | `core_repo`, `self_repo`, `watched_repos[]`, `account` | required | every `owner/name` lives here |
| repos | `report_issue` | discovered | the account's consumer report |
| app | `home` | `/action` | B-01 |
| app | `name`, `accent`, `brand_mark` | required | branding |
| app | `modules` | `{people: false, lanes: false, builds: false, documents: false}` | optional slot modules |
| app | `poll` | badges 30 s, board 30 s, core 60 s | per screen |
| host | `state_dir`, `runtime_dir`, `port` (8766), `service_label`, `service_manager` (`launchd` or `systemd`), `agent_home`, `workspace_root` | required except port | host layout |
| server | `max_body` (1 MiB), `validate_responses` (false), `ttl.*` | as section 2.4 | |
| writer | `live` (false), `rules[]` (each with its own `live`) | three core approval rules, live | default deny, the screen switch (section 2.5) overrides both at runtime |
| analyzer | `min_gap_s` (1800), `retry_after_s` (1200), `daily_audit` (true), `alert_every_s` (14400), `spool_days` (14, the age after which a drained spool record is pruned) | | B-13 |
| model | `cmd`, `timeout_s`, `price_table`, `outlier_threshold`, `plan_usage_cmd` | `cmd` null disables the analyzer and briefs | |
| routing | `rules_file`, `ignore_senders[]`, `ignore_subject_regex[]`, `priority_senders[]` | | collectors |
| notify | `channel`, `cmd`, `quiet_hours` (`22:00-07:00`), `dedupe_prefix` | | B-12, A-97 |
| sign_in | `check_every_s`, `remint_timeout_s` (330), `alert_after` | | loop timings |
| ci | `runner_labels[]`, `container_prefix`, `watchdog_path`, `required_checks[]`, `queued_alert_s` | | no hard-coded labels |
| ci | `runners` | `self-hosted` | declared exception: `hosted` allowed with a `reason` (D7-13); the CI rule reads it |
| git | `branch_prefix_pattern` | null | declared exception: a ticket prefix before the conventional type, for example `^[A-Z]+-[0-9]+/`; PR title lint still requires a conventional title (D7-15) |
| git | `pre_push_overlay_only` | true | B-25 |
| docs | `naming_scheme`, `topic_folders`, `template_path`, `header_label`, `export_folders`, `publish_mode` per class | | B-14, B-15 |
| docs | `adapter` (`git` or `api`), `allowed_roots[]` | `git`, `[]` | section 5.2, the `api` variant refuses every write while `allowed_roots` is empty |
| work | `classification_sets`, `project_defaults`, `debt_files[]`, `plans_root`, `plans_format` | | A-42, A-77, A-78 |
| jobs | manifest `[{name, schedule, expected_every_s, grace_s, feeds, quiet}]` | the core jobs | A-98 |
| heartbeats | `names[]`, `sync_from_tags` (false) | from the job manifest | A-87 |
| freeze | `source` | null | slot name |
| deploy | `strategy` (`copy` or `checkout`), `keep_releases` (3), `health_timeout_s` (30) | `copy` | B-07 |
| automerge | `enabled` (true), `hold_label`, `method` | repo's declared method | B-08 |
| autofix | `own_sync_pr` (true) | | A-65, kill switch |
| discovery | `roots[]`, `ignore[]` | `[workspace_root]` | section 8.2 |
| report | `daily_at` | after the nightly | section 8.4 |

A parameter missing from the file takes its default; a required one missing fails start with the
name of the parameter. `adopt` prompts for every required row (section 8.1).

## 7. Deploy and merge

### 7.1 The deploy contract

`opscenter-core/deploy/deploy.py [--strategy copy|checkout] [--check]`

Strategy `copy` (default):

1. Build: `pnpm install --frozen-lockfile`, `pnpm run build` against `kit-core/` and `local/slots`.
2. Stage: copy `server/`, `engine/`, `schemas/`, `slots/`, `local/slots/` and `app/dist/` to
   `<runtime_dir>/releases/<commit>`; strip caches; write `release.json` (commit, core release,
   content hash).
3. Switch: point `<runtime_dir>/current` at the new release (atomic rename of a symlink).
4. Restart through `host.service_manager` with `host.service_label`.
5. Health: `/api/health` reports the new commit within `deploy.health_timeout_s`, and
   `conformance --server` passes.
6. On failure: point `current` back at the previous release, restart, report once. Keep the last
   `deploy.keep_releases` releases.

Strategy `checkout`: fast-forward a live checkout to the target commit, build in place, restart,
health check; on failure reset to the previous commit, rebuild, restart. Same health gate.

- Drift check (B-28): `--check` compares `current/release.json` to the committed head and the
  content hash of the runtime tree; drift is one board item.
- State dir and `params.json` are never inside a release.
- The nightly calls deploy after an apply that changed `opscenter-core/` or `local/`; the scheduler
  job runs `engine/refresh.py` from `current`.
- No nightly mirror of live code into the repo; the runtime is built from the repo (A-105).

### 7.2 Automerge: newest run per check

`deploy/automerge.yml` is a workflow template the overlay installs into consumer repos that opt in.

- Trigger: check suite and workflow run completed, pull request labelled or synchronised.
- For each name in the repo's required checks (input: `required_checks`, read from the branch rule
  when present, else the parameter), take the newest run of that check on the PR head SHA. All
  newest runs `success`: merge with the repo's declared method and `--match-head-commit <sha>`.
- A failed newest run blocks; a manual rerun that succeeds unblocks (the newest run wins).
- Skips drafts and the hold label; never checks out PR code; never uses an admin override.
- A gate job that waits on core checks (the shell consumer's shape) is accepted as one more
  required check, so its wait is an input, not a second mechanism.
- Kill switch: `automerge.enabled` and a repo variable.
- Rolled out on one repo first, then the rest (hub consumer risk).

## 8. `adopt`

`python3 hermes/adopt.py [--dry-run] [--root DIR]` from the core clone. Idempotent; a rerun changes
only what differs.

### 8.1 What it installs

1. Checks: core clone present and current; `consumer.json` version; the code host CLI signed in.
2. The ops center repo: creates it from the core template when absent, or takes an existing one
   (`--ops-center PATH`). Syncs `opscenter-core/`, `kit-core/`, `tokens-core/` and the overlay with
   its lock.
3. `local/params.json`: prompts for every required parameter row, fills discovered values
   (account, repos, report issue), writes and validates it. Includes the `Commit emails` row the hub
   consumer found missing.
4. Registers the ops center in `consumer.json` as mode `ops-center` with `apply_via` detected.
5. Template workflows only for repos in mode `workflow` (with the core token).
6. Scheduled jobs: the core nightly, deploy after apply, refresh, heartbeats, state autosave, from
   the job manifest through the runtime slot (or the host scheduler when the runtime slot is null).
7. The server unit: writes the service definition for `host.service_manager`, checks that it loads,
   records the port, and fails with the fix when it does not (the shell consumer's gap).
8. Skill sync and binaries (existing `setup.py` steps).
9. Runs deploy once and `conformance --server`.

### 8.2 Registering downstream repos (report only first)

- Scans `discovery.roots` for repos with a `standards.lock`, a local standards folder, a core CI
  workflow or a pin line.
- Classifies each with the existing modes (`workflow`, `ops-center`, `vendored`, `pin-file`) and
  proposes the mode; the owner confirms each in the prompt (or in `--dry-run` output).
- Registers every repo `report_only: true`. Discovery never changes a repo.
- A repo that needs an overlay first is listed with that next step and stays report only.
- The owner promotes a repo to applied from the Core page after one clean report (section 4.5).

### 8.3 How state is migrated

- Detects an existing ops center state dir. Without one, writes empty state from fixtures.
- With one: runs `migrate.py --plan`, shows the plan, and on confirm runs `--apply` with the full
  backup first (section 3.4). Any unconverted record stops adopt with the list; nothing is guessed.
- Then `conformance <state dir>` must pass before the deploy step.

### 8.4 Daily report-back

- The nightly (step 5, `hermes/report.py`) adds one machine-owned section per downstream app to the
  account's consumer report: pinned and latest, sync PR state, core-status counts, UI verdict,
  local additions since the last run, report-only flag.
- Sanitised before posting (`check-sanitised.py`); unchanged sections are not rewritten.
- The consumption feed (`consumption.json`) carries the same rows to the Core page, so the panel and
  the report agree.
- Ops centers apply at once; downstream apps get sync PRs the owner approves. Improvements a
  consumer proposes go up through the report and come back to every consumer as a release.

## 9. Build plan

One core release per step. Each step ships its code, tests and an acceptance check that runs in core
CI, plus a fixture consumer (`opscenter/tests/consumer`) that the release must deploy and pass.
Release numbers are assigned at merge in a fixed merge order (D7-19).

### 9.1 Prerequisites

| Step | Content | Acceptance |
|---|---|---|
| P1 | `check-sanitised` and `check-consumer-neutral` scope to added lines in a diff mode; the pre-commit and CI paths forbid `--no-verify` bypass (D7-20) | a pre-existing hit in CHANGELOG no longer fails; a new hit in an added line fails; a commit made with `--no-verify` is caught by CI |
| P2 | S-1 and S-2 reference runtime packages with a neutral identity interface (D7-6); S-3 and S-4 core CI checks (D7-7); S-5 deploy section rewrite (D7-8); S-6 and S-8, S-8 for the shared dev tier only (D7-9); S-7 after a measured saving | each package has its own tests and a consumer fixture; each check has a failing and a passing fixture; S-7 ships only with the measurement attached |
| P3 | `opscenter/applicability.json`: the published list of rules that apply to an ops center (D7-18); `check-rules` reads it | both consumers' ops center reports compute against the same applicable set; a rule id not in rules.json fails |

### 9.2 Ops center releases

| Release | Content | Tests | Acceptance |
|---|---|---|---|
| R1 Guard and route registry | `gate.py`, `registry.py`, `app.py` skeleton, `/api/health`, static files | registry walk (bad Host, foreign Origin, body cap, no wildcard CORS, unknown POST 404), traversal 403 | fixture consumer serves the SPA and health; every probe in the walk is refused as specified |
| R2 Envelope | `envelope.py`, error codes, tolerant client reader for one release, response validation in tests | shape test on every route; error code to status map | fixture consumer and both tolerant and strict readers pass; R3 removes the tolerant reader |
| R3 Schemas and checker | six envelope kinds, all core state and API schemas, `state.py` with its command line entry, `conformance.py` with `extends` and JSON lines, `migrate.py`, params schema, the estate-literal check | conformance on fixture state, producer and drainer ledger (roles enforced, marks leave content unchanged, retention pass by the producer only), migrate plan and apply on a copy (idempotent, backup, failure report), state.py command line (concurrent appends, header kept, undeclared writer refused, schema violation refused) | fixture state passes; a seeded bad record is reported and not converted |
| R4 Writer and inbox | `writer.py`, `approvals.py`, tombstones, applied ledger, `testing/fixtures.py`, `check-opscenter-writer`, the three core approvals and the consumption panel server module | the writer acceptance in 2.5, the live switch acceptance in 2.5, panel tests from local-ops-app 19 | fixture flows write only through the writer; the consumption panel's three approvals pass against a fake code host |
| R5 Live reads and engine | `swr.py`, `run.py`, core server modules, collector and analyzer engine with the gate, routing, heartbeats, sign-in loop, notice discipline; the app shell and every core screen in 4.2 | swr single flight and last-good; gate order; heartbeat raise and clear; app unit and e2e smoke on fixture state in both themes | fixture consumer runs every core screen live with no bundle step |
| R6 Slots | slot loader, interfaces, null adapters, reference adapters (code host, work tracker, docs home), slot UI mounts, claim token protocol, optional modules | per-slot conformance on fixtures, `api` docs home scope proof, delete refusal and read back; null adapter hides UI; claim token states | fixture consumer runs with all null, then with the three reference adapters against fakes |
| R7 Automerge | `automerge.yml` template, overlay install step | newest run per check, rerun unblocks, hold label, draft skip, head pin | merges a test PR on one repo; a failing then rerun check behaves as specified |
| R8 Deploy | `deploy.py` with both strategies, rollback, drift check, service definitions | failed health rolls back; drift raises one item; keep_releases prunes | fixture consumer deploys, fails a seeded health check and rolls back |
| R9 Adopt | `hermes/adopt.py`, discovery, report-only registration, migration step, downstream app card, daily report-back rows | dry run on a fixture workspace; rerun is a no-op; unconverted record stops adopt | a clean machine fixture goes from nothing to a running, conformant ops center |

## 10. Migration path per consumer

Each consumer first moves its pin to the release before R1 (shell consumer: v0.80.0, hub consumer:
overlay v0.88.0; both proven or emulated green), then follows these steps. Each step is one PR on
the consumer that leaves its ops center working.

### 10.1 Shell consumer (13 PRs)

| Consumer PR | Core release it needs | Note |
|---|---|---|
| 1 pin bump | none | proven green |
| 2 tests first (Host, Origin, shape; missing test folders into CI) | R1 tests as the model | |
| 3 guard on every verb | R1 | closes the wildcard CORS defect |
| 4 tolerant readers (client and 7 outside scripts) | R2 | |
| 5 envelope everywhere | R2 | after PR 4 is deployed |
| 6 rename local `/api/approvals` | none | must land before PR 7 (D7-4) |
| 7 single writer and inbox (28 code host write sites, 3 tracker writes, docs approve) | R4 | uses the fixture helper |
| 8 live read routes beside the bundle; move read-path writes to jobs | R5 | |
| 9 client on live reads, bundle job removed | R5 | after PR 8 runs a week |
| 10 schemas and conformance in CI; state migration | R3 | the core ships these earlier than this PR needs; the PR only adopts them |
| 11 slots: people, review lanes, tracker and runtime adapters, banners | R6 | 32 duplicate code host wrappers collapse into the reference adapter |
| 12 automerge | R7 | |
| 13 deploy contract, mirror dropped, drift check kept | R8 | `strategy: checkout` available if copy cannot be used yet |

After PR 13 the consumer replaces its local server and app with `opscenter-core/` plus `local/`
(the swap PR), runs `adopt` in place for registration and the report-back (R9), and deletes the
local copies one release later.

### 10.2 Hub consumer (27 steps in 6 groups)

| Group | Steps | Core release | Note |
|---|---|---|---|
| 0 | narrow CORS, pause polling, kit theme init, overlay bump, verify script, frozen clock | none | verified |
| 1 | typed confirm, home from config, nine schemas, JSON lines mode | R3 (schemas, JSON lines), R4 (typed confirm) | its 26 schemas are the R3 seed; the nine are added in core, not locally |
| 2 | document envelope and guard, `--server` conformance in CI, route registry, swr helper, core approvals through the applier | R1, R2, R3, R4, R5 | its guard and envelope are lifted as the R1 and R2 reference |
| 3 | kit charts, one badges endpoint, tab and module registry | R5 | |
| 4 | parameterize runner labels, freeze source, doc template, classification; extract sign-in and runtime launcher; cost gate params; notice discipline; pre-push parameter | R5, R6 | the launcher becomes the runtime slot with the claim token protocol |
| 5 | deploy contract, docs flow merge (version field and one-time reader, switch writers, remove old flow), automerge, new modules, `adopt` dry run | R7, R8, R9 | docs flow merge in three PRs; automerge on one repo first |

Then the same swap PR as 10.1. The hub consumer's standards repo retires in favour of the core
(D7-16).

## 11. Owner decisions on the open questions (2026-10-23)

1. **Cost gate sizing.** Ship the defaults in section 2.6. Measure model spend for two weeks after R2
   and retune the defaults from the measurement.
2. **Runtime slot shape.** One runtime interface. The claim token protocol is core; each consumer's
   launch path (a runtime database binding or a deep link with claim tokens) is an adapter.
3. **Review of schemas and slot interfaces.** Both consumers get a 48 hour review window on a release
   candidate before R3 and R6 ship. The owner decides any disagreement.
4. **Swap timing.** Each consumer swaps to `opscenter-core/` after its last mechanism PR, as this
   design says.
5. **People data retention.** When the people slot is on, its data stays local only and never passes
   the writer, is deleted after 90 days by default, and the period is a parameter
   (`people.retention_days`).
