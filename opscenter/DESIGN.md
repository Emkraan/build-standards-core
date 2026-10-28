# Core ops center: design

Status: draft for owner review. Design only; no code exists yet. Section 12 records what the shell
consumer's running ops center does today, row by row against sections 2 to 9, and the owner's
decision (section 11, item 7) that every module it runs belongs in the standard.

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
- **Gate,** checked in order: `--force`, daily audit (no successful run today), retry after a run
  that started and never finished (after `analyzer.retry_after_s`, default 1200), then the change
  test: the bundle hash changed, there is new inbound, and at least `analyzer.min_gap_s` (default
  1800) has passed since the last wake. Otherwise skip. `--dry-run` prints the decision, the
  branch that decided it, the prompt size, and which hash exclusions applied, and calls nothing.
- **Two optional cuts on the change test,** both off by default so a consumer that sets neither
  gets exactly the gate above:
  - `analyzer.hash_exclude` (`{fields: [...], senders: [...]}`) leaves content out of the bundle
    hash, so it can never be the reason for a wake. A listed field is dropped from every
    candidate before hashing. A candidate from a listed sender is dropped from the hash. The
    sender entry `owner` stands for the owner's own identity (parameter `identity.owner`). The
    excluded content stays in the spool, and it is still in the prompt when a run happens for
    another reason. The point is to stop a change that carries no new work (the owner's own
    replies, a field that changes on every read) from waking a paid model call.
  - `analyzer.ambient_max_age_s` (default `null`, off). A candidate is ambient when `addressed`
    is `none`. When the value is set and every candidate that changed the hash since the last
    run is ambient, the wake waits until the last run is at least that many seconds old. A
    change that includes any candidate addressed `direct`, `mention` or `team` is not held back.

  Acceptance (test): with both unset the gate decisions equal the gate above on a table of runs.
  A change only in an excluded field, or only from an excluded sender, leaves the hash equal and
  skips. The `owner` entry matches the owner's identity. An ambient only change skips while the
  last run is younger than the value and wakes once it is older. A mixed change wakes at once.
  `--dry-run` names the branch and the exclusions.
- **Fail open with backoff.** Failures never raise; an alert line on the third consecutive failure,
  then at most every `analyzer.alert_every_s` (default 14400).
- **Untrusted input.** The prompt states that all data is untrusted. Draft only: nothing the
  model writes is sent. The rule is that the model call is a no-tools subprocess through
  `model.cmd` (parameter) with a timeout. The engine owns the gate, the spool, the routing filter,
  the item contract and the handled state, and the model is a pure function from prompt to items.
  The conformance checks assume this rule (decided, section 11 item 6).
  - **Declared exception, an agent job.** A consumer whose analyzer is an agent job declares it
    with parameter `model.mode` set to `agent_job` plus a `reason`, the same pattern as
    `commit_domains`, `ci.runners` and `git.branch_prefix_pattern`. The declaration is visible in
    the parameters file and the conformance checker. The default stays `subprocess`, so every new
    consumer gets the safe default and one that already runs as an agent job keeps its tools.
  - **Conditions of the exception.** `agent_job` is allowed only under four conditions, and the
    conformance checker reads them from the declaration:
    1. A post-validation step, such as a board refresh, may run at the end of the job only through
       the engine's validation entry point, so the item file is validated before anything
       publishes it, whoever runs the step. The step never reads or publishes the item file by
       any other path.
    2. A rebuild fallback inside the job, for a bundle that is missing or invalid, is allowed only
       when it calls the same builder the gate uses (one build path with two callers). The job
       never carries a second implementation of the builder.
    3. The engine validates the item file against the item contract below (required fields,
       priority values, every must-consider candidate covered or dropped) before the routing filter
       runs.
    4. The declared `reason` states that the tool policy is the prompt and not a technical limit.
    The result is that the job reads the bundle the gate wrote (or rebuilds it through the gate's
    own builder) and writes the item file, and nothing it runs afterwards reaches the board except
    through the engine's validation.
  - **How the gate wakes the job.** The gate runs as the pre-run step of the scheduled job. It
    builds the input bundle, applies the gate rules above, and writes the bundle to a file. When
    the rules say skip, it prints nothing and the job does not start. When they say run, it prints
    one wake line that names the reason and the bundle path, and the scheduler starts the agent.
    `--dry-run` still prints the decision and calls nothing.
  - **What the engine still owns.** The job's prompt and tool list belong to the consumer and are
    never read by the engine. The job writes its items to the item file, and the engine then reads
    that file and validates it against the item contract below (condition 3). A malformed file is
    rejected, the previous file stays in place, and the rejection counts as a failure for the
    backoff above. The routing filter then runs over the job's items exactly as it does over a
    subprocess's items, and handled state still applies, so a rule holds when the job ignores it.
    The draft only rule is unchanged. The engine therefore keeps the item contract and the routing
    guarantees in both modes, and the untrusted input guarantee in `agent_job` mode is stated by
    the job's tool policy (condition 4). The job must reach any outward effect only by queuing a
    proposal in the approvals inbox (section 2.5).
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
- A job reports liveness in one of two ways, and a manifest job may use either. The first is a
  heartbeat line the job writes itself (`watch` kind, `heartbeats.json`) on start and finish with
  its exit status. The second is the runtime slot's own record of each run: the slot method
  `jobs.last_runs()` returns, per job, `{name, last_start_utc, last_end_utc, exit_status,
  output_tail}`, where `output_tail` is a bounded tail of the run's output with the redaction the
  `ci_host` runner log uses (section 5.3). It is read only, goes through `swr`, and needs no change
  to the job. The core nightly registers manifest jobs with the runtime slot (`jobs.register`).
- `heartbeats.py` raises one board item per job past `expected_every_s + grace_s` or failing, keyed
  by job, and it clears itself on the next success (local-ops-app section 17). Its sources are
  parameter `heartbeats.sources` (default `["lines"]`, so nothing changes until a consumer adds
  `"runtime"`). With both sources on, the entry with the newer end time wins for each job, and
  the failing output tail goes into the board item's detail. A runtime slot that is null or
  unavailable leaves the heartbeat lines as the only source, with no error.

  Acceptance (test, against a fake runtime slot): a failed last run raises one item keyed by the
  job, and the next successful run clears it. A run older than `expected_every_s + grace_s`
  raises one item. With both sources the newer entry wins. A null runtime slot falls back to the
  lines. With `sources` left at its default the slot is never called.
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
| `runtime` | 12, 24, 51, 52, 80, 89, 90 | jobs list, last runs (`jobs.last_runs()`, section 2.7) and run now, register manifest jobs, sessions (tackle launch with claim token protocol, B-09), discuss session, restart, spend ledgers, account pool, fallback watch, banners | null |
| `freeze_source` | 26 | list windows `{name, start_utc, end_utc, exception}` | null (strip is core) |
| `collector` (one per source: mail, chat, tickets) | 31, 32 | `collect(since)` returns candidates; rules from parameters | null |
| `meetings` | 33 | list meetings, read transcript, produce digest items; privacy scrub and private file modes are core rules | null |
| `work_tracker` | 35 to 39 | see 5.2 | reference |
| `classification` | 42 | the work type and project default sets | null (empty set) |
| `digest_source` | 43 | ideas digest input | null |
| `review_lanes` | 45, 56 | lane manifest `{lane, repo, tabs, engine_check, own_pr_lane, gates, canary}`; mounts `/reviews/<lane>` on the core PR card | null |
| `gated_deploys` | 47 | list pending gated deployments and plan runs, act: approve, reject, retry, override window, delete release, accept risk, decide fix (verbs below) | null |
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

Gated deploy verbs. A consumer's gated deploy lane carries more than approve, reject and retry, and
each extra verb below is an outward change, so each one is a writer operation (section 2.5) and a capability
the slot declares. A verb the slot does not declare is refused by the writer.

| Verb | Direction | What it does | Extra rule |
|---|---|---|---|
| `approve`, `reject`, `retry` | update | decide or rerun one pending gated run | pinned to the run seen |
| `override_window` | update | let a run proceed inside a closed change window | a reason is required and is recorded with the exception the window source reports |
| `delete_release` | delete | remove a release or a pending run | default deny, needs its own explicit rule, never covered by a wildcard rule |
| `accept_risk` | update | record the accountable owner's acceptance of a finding | owner decision only, a machine caller can queue a proposal and never approve it |
| `decide_fix` | update | choose one of the fixes the slot offered for a finding | the chosen option id must be one the last read offered |

Setting the triage state of a finding is not a verb of this slot. It changes only the ops center's own
state and has no outward effect, so it is not a writer operation and needs no capability. It is written
as ordinary state, through the state API, and never calls the slot.

The same rules as every operation hold: an approval record whose hash equals the content hash, a live
re-read before the write, a tombstone after it, and the applied ledger.

Claim token protocol (core, B-09): `POST /api/tackle` stages a prompt file (mode 0600, TTL
`tackle.prompt_ttl_s`, default 300) and a one-time launch token; the runtime slot launches the
session; the session fetches the prompt once (`plugin` auth), binds with a claim secret, and reports
with it; the server verifies the reporting session is the bound one. States: launching, claimed,
running, resolved, failed; unclaimed after `tackle.claim_timeout_s` (default 360) is failed. One
launch at a time. The prompt says draft only.

Review lane manifest fields. `engine_check` names the check the lane's engine reports. `own_pr_lane`
is optional and names the lane that merges the owner's own pull requests under a policy file:

```json
{"lane": "...", "repo": "owner/name", "own_pr_lane": {"policy_ref": "path of the policy file in the repo"}}
```

- The core reads the lane and shows it on `/reviews/<lane>`: the policy as read, the open own pull
  requests and what the policy decides for each, and the last decisions.
- The read never writes. The merge itself is a writer operation (scope `code_host`, action
  `pr.merge`) under a rule in parameter `writer.rules`, pinned to the head seen and gated on the
  required checks, so a lane never merges outside the writer.
- A lane without `own_pr_lane` shows no own pull request section. The field is a data declaration,
  and the policy file stays the consumer's own.

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
| analyzer | `min_gap_s` (1800), `retry_after_s` (1200), `daily_audit` (true), `alert_every_s` (14400), `spool_days` (14, the age after which a drained spool record is pruned), `ambient_max_age_s` (null), `hash_exclude` (`{fields: [], senders: []}`) | the last two are off until set | B-13, section 2.6 |
| model | `cmd`, `timeout_s`, `price_table`, `outlier_threshold`, `plan_usage_cmd` | `cmd` null disables the analyzer and briefs | |
| model | `mode` (`subprocess` or `agent_job`) | `subprocess` | decided in section 11 item 6, `agent_job` is the declared exception and needs a `reason` plus the four conditions in section 2.6 (a post-validation step only through the engine's validation entry point, a rebuild fallback only through the gate's builder) |
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
| heartbeats | `names[]`, `sync_from_tags` (false), `sources` (`["lines"]`, or add `"runtime"`) | from the job manifest | A-87, section 2.7 |
| freeze | `source` | null | slot name |
| deploy | `strategy` (`copy` or `checkout`), `keep_releases` (3), `health_timeout_s` (30), `health_path` (`/api/health`), `companions[]` (`{from, to}`, default none), the last two for both strategies | `copy` | B-07, section 7.1 |
| automerge | `enabled` (true), `hold_label`, `method`, `merge_attempts` (3), `merge_pause_s` (10) | repo's declared method | B-08, section 7.2 |
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
5. Health: the health probe below passes (`deploy.health_path` reports the new commit within
   `deploy.health_timeout_s`, and `conformance --server` passes).
6. Companions install after the probe passes (see below). On failure: point `current` back at the
   previous release, restart, report once. Keep the last `deploy.keep_releases` releases.

Strategy `checkout`: fast-forward a live checkout to the target commit, build in place, restart,
then run the health probe. A failure of the build, the restart or the probe each triggers the
rollback: reset to the previous commit, rebuild, restart and probe again, and report once. A build
that succeeds does not skip the probe, and a passing probe is required whatever the build did.

Both strategies share the health probe and the companion paths below. `deploy.health_path` and
`deploy.companions[]` apply to `copy` as well as `checkout`, so a consumer that changes strategy keeps
the same probe and the same agent home files. For `copy` the previous commit is the one in the
previous release's `release.json` and the target commit is the one being staged.

- **Health probe.** A `GET` of `deploy.health_path` (default `/api/health`) repeated until it reports
  the target commit within `deploy.health_timeout_s`, then `conformance --server` passes. A probe
  that never answers, answers with another commit or fails conformance is a failed deploy.
- **Companion paths.** `deploy.companions[]` lists files the ops center ships for the agent home as
  `{from: <path in the repo>, to: <path under host.agent_home>}`. They install only after the health
  probe passes, so a failed deploy leaves the agent home as it was. For each companion that changed
  between the previous and the target commit:
  1. A destination that is absent, or whose content hash equals the previous commit's file, is
     replaced with the target commit's file.
  2. A destination whose content hash is neither is local drift. It is left in place, nothing is
     overwritten, and one board item names the file and says the drift needs the owner's decision.
  3. A companion that did not change between the two commits is not touched.
  4. A destination outside `host.agent_home` is refused when the parameters file is read.

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
- **Retrying merge.** A merge call can fail while the code host is briefly unreachable from a
  self hosted runner, and a single failed call then fails a gate whose checks are green. The merge
  step (`merge-pr.py`) retries only a transient failure (a dropped connection, a timeout, a 5xx
  answer), up to `automerge.merge_attempts` calls in all (default 3) with `automerge.merge_pause_s`
  seconds before each retry (default 10). The workflow passes the two parameters as the script's
  `--attempts` and `--pause` flags. Each retry runs in this order: sleep, then read the pull request
  state and head, then merge. It stops, without retrying, when the pull request is already merged
  (the outcome is success), is closed, or has a head other than the one that was checked. Every retry
  passes `--match-head-commit` with the head just read, even when the caller passed none, so a retry
  can never merge a different head. The retry claims only an open state and an unchanged head. It
  does not read the required runs again: the code host refuses a merge while a required check is not
  green, and that refusal (like a conflict, a failed head match or a branch rule) is not transient
  and is never retried. The pause is the only wait, and a retry never adds an admin override.
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
   its lock. `PATH` may be the repo root, the app folder inside it, or a symbolic link to either, for
   example a deployed checkout that the state tree reaches through a link to its app folder:
   - `adopt` resolves the link (real path), walks up to the git top level and takes that repo. A
     path that resolves outside any git repository, or to a repo with no ops center app, is refused
     with the resolved path in the message.
   - The consumer entry's `path` records the resolved top level, so a later change of the link does
     not move the registration. The dry run prints both the path given and the resolved one.
   - `adopt` never replaces, removes or retargets the link, and never writes through it into any
     repo other than the resolved one.
   - A checkout that is also the live deployed copy (`deploy.strategy` `checkout`) is taken without
     switching its branch or editing its working tree. The sync lands in a separate worktree by
     pull request (`apply_via: pr`), and the deploy step then fast-forwards the live checkout.
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
| R5 Live reads and engine | `swr.py`, `run.py`, core server modules, collector and analyzer engine with the gate, routing, heartbeats, sign-in loop, notice discipline; the app shell and every core screen in 4.2 | swr single flight and last-good; gate order including the two optional cuts; heartbeat raise and clear (from lines and from the runtime slot's last runs); app unit and e2e smoke on fixture state in both themes | fixture consumer runs every core screen live with no bundle step |
| R6 Slots | slot loader, interfaces, null adapters, reference adapters (code host, work tracker, docs home), slot UI mounts, claim token protocol, optional modules | per-slot conformance on fixtures, `api` docs home scope proof, delete refusal and read back; null adapter hides UI; claim token states | fixture consumer runs with all null, then with the three reference adapters against fakes |
| R7 Automerge | `automerge.yml` template, overlay install step | newest run per check, rerun unblocks, hold label, draft skip, head pin | merges a test PR on one repo; a failing then rerun check behaves as specified |
| R8 Deploy | `deploy.py` with both strategies, rollback, drift check, service definitions | failed health rolls back; drift raises one item; keep_releases prunes; a custom `health_path` is the one probed; companions install only after the probe, a drifted destination is left alone with one board item, an unchanged one is untouched, and a destination outside the agent home is refused; both strategies | fixture consumer deploys, fails a seeded health check and rolls back, then deploys with `checkout` and `copy`, a custom `health_path` and a changed companion, and the agent home file is replaced only after the probe passes and left alone when seeded with drift |
| R9 Adopt | `hermes/adopt.py`, discovery, report-only registration, migration step, downstream app card, daily report-back rows | dry run on a fixture workspace; rerun is a no-op; unconverted record stops adopt; `--ops-center` given as a repo root, an app folder and a symbolic link to each resolves to one top level; a path outside any git repo or without an ops center app is refused with the resolved path; the recorded `path` is the resolved top level and survives a retargeted link; the link is never changed; a live checkout keeps its branch and working tree and the sync lands by pull request | a clean machine fixture goes from nothing to a running, conformant ops center, and a fixture whose ops center is reached through a symbolic link is adopted in place, with the link, the branch and the working tree unchanged |

Status of each release against the shell consumer's running ops center, and what it already runs that
no release above covers: section 12. A release is built from the running code where section 12 says it
runs, so the running behaviour is the reference and this table is the order of work.

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
6. **Analyzer model call (2026-10-27).** The model call is a no-tools subprocess through
   `model.cmd`. A consumer whose analyzer is an agent job declares the exception with
   `model.mode = agent_job` plus a `reason`, the same pattern as `commit_domains`, under four
   conditions: a post-validation step (a board refresh) may run at the end of the job only through
   the engine's validation entry point, a rebuild fallback inside the job is allowed only when it
   calls the same builder the gate uses, the engine validates the item file against the item
   contract before the routing filter runs, and the `reason` states that the tool policy is the
   prompt and not a technical limit. The job reads the bundle the gate wrote and writes the item
   file, and nothing it runs afterwards reaches the board except through the engine's
   validation. Its output is still validated against the item contract and the routing filter, so the engine keeps that
   guarantee (section 2.6).
7. **Everything the shell consumer runs belongs in the standard (2026-10-28).** The 24 modules in
   section 12.3 run today and go into the standard as they run, not as a trimmed subset. A consumer
   leaves out only what it does not use, by turning the module off in `app.modules` (section 6) or by
   leaving its slot null. Where the running behaviour differs from this design, section 12 says so and
   the design is not weakened to match; the difference is the shell consumer's migration work
   (section 10.1) unless the owner decides the running form is better, in which case the design
   changes in its own PR.

## 12. What the shell consumer's ops center runs today

Source: a read of the running code at the time of the lift (2026-10-28), not a design. Nothing here
loosens a rule above. Each row says whether the running ops center **runs as designed**, **runs
differently** (and how) or has **not built** the item. A row marked `not read` was not read closely
enough to state a fact; it is a gap in this section, not a statement that the item is absent.

### 12.1 What it is

A loopback single operator app: a stdlib Python HTTP server, a React single page app on the kit, file
based state with no database, and no auth layer. The scheduler (the agent runtime's cron) drives every
writer, lane and gate. It deploys by a fast forward onto a live checkout and restarts its service.
Its backend is about 100 modules, 43 of them tests, one module per page or lane, stdlib only except
a word processor library for the yearly review export (a time boxed exception to
`scripting-python.md`, see 12.6). Core copies of the kit, the lint config and a lock file sit inside
the app, exactly as section 1.2 describes for the synced kit.

Two read patterns coexist, which section 2.4 forbids as a steady state: live reads behind a
stale-while-revalidate cache (14 modules: reviews, runners, builds, cost and spend, plans, PR
dependencies, runbook releases, jobs, work tracker, account pool) and a bundle step that writes
static JSON into the app's public folder every 10 minutes for the board, people and knowledge data.
The design's direction (live reads, no bundle) stands; the bundle is the migration the consumer
finishes in its own steps 8 and 9 (section 10.1).

### 12.2 Status of R1 to R9 and of each design section

| Row | Design item | What runs today | Status |
|---|---|---|---|
| R1 | gate, registry, health, static files | Host check called per route (13 call sites and more), the Origin header read inside each POST handler, one allowlist tuple for POST routes, hand written `if path ==` chains (about 70 routes), `/api/health` returns `{"ok": true}`, unknown POST is 404, and a wildcard `Access-Control-Allow-Origin: *` is still sent on some responses (the defect section 2.2 closes). Body cap constant, traversal check and the one time token route class: not read | runs differently |
| R2 | envelope, error codes, tolerant reader | plain JSON objects per route, the client reads bundled files and API JSON directly | not built |
| R3 | six envelope kinds, schemas, `state.py`, `conformance.py`, `migrate.py`, params schema | one schema for the board file, validated by the contract module; lint config files. No envelope header on state files (121 distinct state file names are referenced by code), no conformance checker, no migrate tool | runs differently |
| R4 | writer, inbox, tombstones, applied ledger, three core approvals, consumption panel | writers are spread across the review, consumption and lane modules and the queued approvals script. Inbox (`approve-inbox.jsonl`), applied ledger (`approve-applied.jsonl`), tombstones, head pin on merges (`--match-head-commit`), consumption panel with its three approvals and typed confirm all exist. No single outward writer, no operation object | runs differently |
| R5 | swr, run helper, engine, gate, routing, heartbeats, sign-in loop, screens | swr (single flight, last good, invalidate after a write), the collector and analyzer chain and its wake gate (12.4), routing rules from a seeded file, job health read from the runtime's jobs file, sign-in health files, the shell, rail, palette and screens. No heartbeat file: liveness comes from the runtime's jobs file (`last_run_at`, `last_status`, `failure_streak`) and one board item per failing job, closed by the next success | runs differently |
| R6 | slot loader, interfaces, null adapters, reference adapters, claim token protocol | none. Integrations are hard wired modules (code host calls spread over modules, the work tracker, the docs home, the agent runtime). The tackle verb binds a board item to an agent session | not built |
| R7 | `automerge.yml`, newest run per check, hold label, draft skip, head pin | merge lanes merge by script with a head pin, honouring freeze and hold (12.3 items 1 to 3). No workflow template. Newest run per check: not read | runs differently |
| R8 | `deploy.py`, both strategies, rollback, drift check, health path | strategy `checkout` only: fast forward the live checkout, install changed scripts atomically (temp file, then move, mode from git), `npm ci` only if the lock changed, build only if a non Python file changed, restart only if Python changed, reset to the previous commit and rebuild when the install or build fails, exit 1 when a live script drifted. No health probe, no releases folder, no `keep_releases` | runs differently |
| R9 | `adopt`, discovery, registration, migration step, downstream app card, report-back | none; adoption was by hand from the core clone. The consumption panel lists consumers | not built |
| 0 | owner rules | estate names are literals in modules | not built (the lift removes them) |
| 1.1, 1.2 | layout, synced copy | server modules and engine are mixed in two folders; only the kit, tokens and lint are synced, the ops center code is the repo itself | runs differently |
| 1.3, 5.1 to 5.3 | slots, null adapters | not built (R6) | not built |
| 2.1 | runtime | stdlib plus three pinned packages with hashes for the export and the agent call; bind address is an environment variable defaulting to loopback; port is not 8766; state lives in a git tracked tree, not outside the repo | runs differently |
| 2.2 | route registry, auth classes, cache class | hand written routes; read is the Host check, write is Host plus Origin; people endpoints send `no-store`, everything else ETag, 304 and gzip | runs differently |
| 2.3 | envelope and error code list | sections return an error key, the shape is per module | not built |
| 2.4 | live reads, TTLs as parameters, no bundle | swr as designed, TTLs are module constants, the bundle remains. Whether every read path is free of writes: not read | runs differently |
| 2.5 | single outward writer | not built; related guards exist (typed confirm, head pin, tombstones, decisions log, fail closed on any code host error) | not built |
| 2.6 | cost gated analyzer | collectors never call a model; a rules file seeded from a seed file; a bundle builder for the model input; output validated against the board schema; a wake gate on a weekday schedule. Gate order and retry constants against 2.6: not read | runs differently |
| 2.7 | job manifest and heartbeats | see R5; no `expected_every_s` or grace manifest | runs differently |
| 3.1 to 3.4 | envelopes, per file schemas, conformance, migrate | not built | not built |
| 4.1 | shell | the rail, header, palette, letter keys and a hash router adapter for kit links; `/api/badges` polled | runs as designed (it is the reference the design copies) |
| 4.2 | screens | the board has Now, Completed, Routing and Alerts; Awareness and Drafts are merged into the board; no Overview page; the work tracker lives at `/jira`; reviews, debt, people, team, knowledge, plans, links, builds, core and infrastructure pages exist | runs differently |
| 4.3 | home route | hard coded to the board | runs differently |
| 4.4 | consumption panel | `core_consumption` module and page, three approvals with typed confirm | runs as designed (it is the source of the design) |
| 4.5 | downstream apps card | not built | not built |
| 6 | params file | none; values live in module constants, environment variables, and state config files (own PR policy, review policy, alert sources, knowledge curation config, cron card map) | not built |
| 7.1, 7.2 | deploy, automerge | see R8 and R7 | runs differently |
| 8 | adopt | not built | not built |

### 12.3 The 24 modules the shell consumer runs

The design's Table A and sections 4 and 5 cover the screens and slots most of these need. This list
is what runs beyond or inside them, so none is dropped. For each: what it does, the state it keeps
(a file name here is a state file under `host.state_dir`), where it sits in the design and the
parameter or slot that turns it off. A consumer that does not use one leaves it off; it is never a
reason to change the module.

1. **Review lane with downtime classification.** Reviews engineer pull requests on a schedule (every
   3 minutes): reads the PR with its head, runs the engine's check, approves, and queues for merge. A
   PR classified as downtime waits for its window (item 2). State: `policy.json`, `queue.json`,
   `health.json`, `held-for-window.json`, `decisions.jsonl` (append only). Rules: the head is
   pinned on every merge, the PR is re-read before an in-app approval and a closed or red PR is
   refused, a tombstone keeps a card from reappearing after an action, any code host error fails
   closed. Maps to slot `review_lanes` and the Reviews screen (A-44, A-45); off with
   `app.modules.lanes`.
2. **Maintenance windows.** Classifies a change as downtime (a deployable app whose kind serves
   traffic, a plan that replaces or deletes a serving or data resource, or an unreadable plan, which
   fails closed) and gives the window math per change class. A held PR shows "Waiting for the
   maintenance window" with "Merge now (override)", which needs a reason and is recorded in
   `window-overrides.json` and `decisions.jsonl`. An own pull request is never held. Maps to the
   `override_window` verb of `gated_deploys` (section 5.3) and the `freeze_source` slot; the
   classifier is core code and the window table is a parameter.
3. **Own pull request lane with sign off cards.** A bounded standing lane that merges the owner's own
   pull requests under a policy file: never a red check, a freeze or a hold. Sign off cards and
   directions (the two state files below) record the owner's decision. State: `own-pr-policy.json`, `own-pr-merge.json`, `own-pr-signoffs.json`,
   `own-pr-directions.json`. Maps to the `own_pr_lane` field of the lane manifest (section 5.3); the
   merge is a writer operation once R4 ships.
4. **Own sync pull request auto fix.** For the ops center repo's own nightly sync pull requests: every
   5 minutes the lane lists them, classifies each, and for a fixable problem (a red check, a merge
   conflict) starts one fix session under the same caps as item 1. It never merges, approves, labels
   or comments; the code host's auto merge lands the pull request once the checks are green. Kill
   switch `autofix.own_sync_pr` (section 6).
5. **Core pull request lane.** Every 5 minutes lists the owner's open pull requests on the core
   (base main, not draft, no hold label, branch not on the deny list) and merges one only when every
   check on the head is green with none pending, the merge state is clean, and the head has been
   quiet for a minimum age and was seen unchanged on a previous pass; the first failing reason wins
   and is recorded. Parameter `automerge.hold_label`.
6. **Merge queue.** Puts a pull request into the main branch's merge queue and proves it got there: it
   reads the pull request, cancels a stale auto merge request (which would make a later auto merge a
   silent no-op), enqueues, then re-reads until the pull request is queued, merged or (a repo with no
   merge queue only) has an auto merge request. Anything else raises. Review threads the owner left
   open must be resolved first because the branch requires it.
7. **Queued docs approvals.** Drains an approval inbox into the docs home every minute and appends an
   applied ledger (`approve-inbox.jsonl`, `approve-applied.jsonl`). Sent back proposals are rewritten
   by a gate every 30 minutes (item 21). Maps to the writer and approvals inbox (sections 2.5, 4.5) and
   slot `docs_home`.
8. **Change freeze gate.** Syncs freeze windows from the work tracker into `change-freeze.json`; the
   board shows a freeze strip and the lanes refuse to merge inside a window. Maps to slot
   `freeze_source` (A-26).
9. **Terraform plan gate with a held queue.** Finds workflow runs waiting on the plan environment.
   An ordinary plan is approved automatically. A pull request that changes how the pipeline works
   (workflow code, the owners file, the exclusions list, or constructs that run code or reach the
   network during plan) is held in `queue.json` for the owner's review, and the agent is woken only to
   write a private assessment for a held pull request and sha that has none. It fails closed and
   backs off after 3 consecutive failures (1 hour, then 4 hours). Runs every minute. Maps to slot
   `gated_deploys` (A-47) with the verbs in section 5.3.
10. **Privileged apply review and owner roots.** A queue (`privileged-queue.json`,
    `privileged-health.json`) for applies that change identity or rights, and a table of which
    infrastructure roots a given owner may apply (`terraform-roots.json`). Maps to `gated_deploys`
    (`accept_risk`, `decide_fix`, `approve`); roots are a parameter.
11. **Dark launches.** Acting automation ships with its switch off (a repository variable). One Enable
    click on the board turns it on after a dry run; Disable turns it off. State: `dark-launches.json`
    and `dark-launches-log.jsonl`. Routes `/api/dark-launches/dry-run`, `/enable`, `/disable`. This is
    the shell consumer's form of the writer's `live` switch (section 2.5): the core adopts it as the
    standard way a rule goes live, so a rule's `live` flag and a dark launch are one mechanism.
12. **Cron card map, run now and watcher chip.** Maps each scheduled job to the board card it feeds,
    offers Run now, and shows a watcher chip when a job is failing. State: `cron-card-map.json`. Reads
    the runtime's jobs file read only. Maps to slot `runtime` (A-80, A-89) and section 2.7.
13. **Builds page and update from main.** Lists the pipelines the consumer builds and what landed
    on each, and offers `update-from-main` for a pipeline branch. Maps to slot `pipelines` (A-88);
    off with `app.modules.builds`.
14. **Image watch and desktop pool.** A failed image build raises one board item with the failing job
    and step, the result line from the log and the buttons Rerun failed jobs, Close the window and Open
    run; nothing reruns or closes by itself, the buttons go through the approval path. The pool read
    gives the evidence for the destroy approval of a pool roll: every retiring host in drain mode with
    no sessions and at least one new host available, from one read only cloud call per pool, cached for
    a minute, bounded by a timeout; a failed read says so and never turns into a pass. State:
    `desktop-image-watch.json`. Optional module; a consumer without a desktop pool leaves it off.
15. **Runbook releases.** After the owner approves and merges a pull request that removes runbooks,
    records the delete set approved from that pull request's plan, follows the deploy runs on main,
    and offers Release deletes only when the newest main run failed on the destroy guard alone. Optional
    module; the releases go through the approval path.
16. **Browser status.** Flags the shared automation browser when its window has been visible longer than
    an alert age or the service has been down longer than another, and offers a one click hide. The
    launcher is the single source of the mode; this module only reads it and times it. Optional
    module; the service label is a parameter.
17. **Model accounts, spend and fallback.** Reads the ledger of model usage (`anthropic-ledger.jsonl`),
    the account kinds, and the fallback state (`llm-fallback.json`, `anthropic-account-kinds.json`),
    and shows spend per account. Maps to slots `spend`, `plan_limits` and `runtime` (A-85, A-86, A-90).
18. **Sprint close, retro row, ticket progress and needs me.** Nightly sprint close out, a drafted
    retro row, per ticket progress notes and a "needs me" list from the work tracker. State:
    `sprint-watch-snapshot.json`, `sprint-close-state.json`, `ticket-progress.json`,
    `retro-rows.json`. Maps to slot `work_tracker` (A-35 to A-39); the gates are collectors.
19. **1:1 board and yearly review export.** The people group: a topic board per report, team
    performance, and a yearly review exported to a word processor file. State: `one-on-one-topics.json`,
    `team-performance.json`, `history-master.json`. People data stays local, never passes the writer
    and is deleted after `people.retention_days` (section 11 item 5). Slot `people`, off by default
    (B-30); the export is the one place a non stdlib package is needed (12.6).
20. **Links reachability check.** Weekly: resolves every catalog host and sends one HEAD per link
    without following redirects (a sign in redirect counts as alive). A link is dead at once when its
    host does not resolve or it answers 404 or 410; a timeout, refusal or TLS failure counts only if the
    previous run also failed for that link, and links flagged on network are skipped. The Links page
    shows a Not reachable pill. State: `link-health.json`, `link-edits.json`. The link catalog is a
    parameter file and holds no estate names in core.
21. **Knowledge proposals, queued approvals and sent back rewrite.** The Knowledge screen (A-70 to
    A-74) with publish mode per class, the approval inbox of item 7, and a gate that rewrites a sent
    back proposal. State: `confluence-proposals.json` (renamed `docs-proposals.json` in core),
    `knowledge-curation-config.json`, `doc-gaps.json`, `doc-inventory.json`, `doc-handled.json`.
22. **Plans tracker reconcile.** A gate that reconciles the plans library with the tracker, on a weekday
    schedule. Maps to the Plans screen (A-77).
23. **Dependency graph of pull requests and the ops search.** One dependency model for the open pull
    requests so the board never asks for an approval that cannot pass yet because the pull request
    waits on another. A child waits on a parent through a line in its body ("Waits on", "Lands after",
    "Stacked on"), through its commits containing another open pull request's head, or through a
    destroy attributed to the parent by the own pull request lane. The search fans one query out across
    the board items (open and completed), tackle sessions, plans, 1:1 topics, state notes and the agent
    runtime's chat sessions and returns grouped, ranked hits with a deep link; the tracker is searched
    live in a separate scope. Stdlib only and read only. Maps to the Reviews dependency wait (section
    4.2) and the Search screen (A-9).
24. **Cron catalog fixer, sitrep, hermetic test home, reviews visibility check.** A nightly wake gate
    that wakes the model only when an enabled job has a name outside "<Area> - <what it does>" or no
    catalog description, so quiet nights cost no model run; a weekday morning sitrep of what waits on
    the owner; a hermetic test home, a throwaway home that mirrors the installed layout from the
    checkout so no test reads or writes the real agent home or state tree; and a reviews visibility
    check every 30 minutes (its script is live only and was not read). Maps to the core engine jobs in
    section 4.2 (sitrep, visibility, A-54 and A-93). The hermetic home becomes
    `opscenter/testing/hermetic_home.py`, the base of `testing/fixtures.py` (section 1.1).

Deploy and update jobs that run beside the 24 are in 12.5.

### 12.4 The analyzer chain as it runs

Collectors (no model call) write candidates; routing rules from a rules file (seeded from a seed
file) filter them; a bundle builder assembles the model input; a wake gate on a weekday schedule
(every 15 minutes in working hours) decides whether the model runs and wakes the agent only when
there is something to do (the last output line `{"wakeAgent": false}` is the contract); the output
is validated against the board schema, then the handled state is merged (`action-handled.json`: a
handled item stays handled unless new evidence arrives) and the bundle is published. The board
verbs are Resolve, Snooze, Ignore, Ignore forever, Undo, Route elsewhere and Tackle
(`action-tackle.json`). This is section 2.6 with a different shape; the gate order and retry
constants have not been diffed and R5 does that diff before it ships.

### 12.5 Deploy, refresh and kit sync as they run

- Refresh: every 10 minutes rebuilds the bundle. Daily full build: 06:00 rebuilds the app. Deploy: every
  5 minutes, silent when the main branch has not moved (R8 row above).
- Kit and lint sync: the consumer's sync script and the nightly in the app, with a lock file, a sync
  check, an exceptions check and a UI lint in the build's `prebuild` step, and a bundle size budget in
  `build`. A kit drift sync job that opens an upgrade pull request exists and is paused.
- Self hosted runners: 11 CI jobs run on a consumer's own runners; the runner label is overridable
  by a repository variable (parameter `ci.runner_labels`).

### 12.6 Differences the standard keeps, and why

- **No wildcard CORS, a gate on every verb, the envelope, the single writer.** The running code does
  not meet these (R1, R2, R4); the design stands and the consumer migrates (section 10.1).
- **One non stdlib package.** The yearly review export needs a word processor library, and one import
  comes from the agent's own checkout. The design keeps stdlib only for the core; the export is a
  declared exception recorded with `scripting-python.md` and lives in the optional people module
  only, so a consumer that does not use it has no third party code.
- **State outside the repo.** The running state tree is inside a git tracked repo, which section 2.1
  forbids for a deploy that must not touch data. The consumer's deploy copes because it only fast
  forwards code; the design keeps the rule and `deploy.py` (R8) enforces it.
- **A hard coded home route and estate literals.** Both go to parameters (section 6) when the module
  is lifted; a lifted module never carries a literal.

### 12.7 Lift status (2026-10-28)

Where each module of 12.3 stands in the core. Lifted code carries its tests, runs in core CI and has no estate
name (the verification patterns return zero hits over `opscenter/`). A module not listed as lifted is not a module
the standard drops: it is waiting on something named here.

| Item | Module | Status |
|---|---|---|
| 1 | review lane engine | not lifted: the review engine, the auto-fix session starter and the lane scripts are not in the handoff snapshot |
| 2 | maintenance windows | lifted: `lanes/maintenance_window.py` (change classes `standard` and `restricted`, windows as policy data) |
| 3 | own pull request lane, decision cards | lifted: `server/modules/own_lane.py`, `decision_cards.py`; the lane scripts wait on the auto-fix session starter |
| 4, 5 | own sync auto fix, core pull request lane | not lifted: both need the auto-fix session starter |
| 6 | merge queue | lifted: `lanes/merge_queue.py`, `gh_run_jobs.py` |
| 7 | queued docs approvals | not lifted: needs the docs write guard, not in the snapshot |
| 8 | change freeze gate | lifted: `lanes/freeze_gate.py` |
| 9, 10 | plan gate, privileged apply review | plan gate lifted: `lanes/tfplan_gate.py` with a reference sign-off store; the privileged lane is a plug-in seam (`set_privileged_gate`) |
| 11 | dark launches | lifted: `server/modules/dark_launches.py` |
| 12 | cron card map, run now | lifted: `server/modules/cron_pulse.py` (parameters in 12.8) |
| 13 | builds page | lifted as an app page; its server module (`builds.py`) is not |
| 14, 15, 16 | image watch and pool, runbook releases, browser status | lifted: `image_watch.py`, `desktop_pool.py`, `runbook_releases.py`, `browser_status.py` |
| 17 | model accounts, spend, fallback | not lifted, by decision: the running module reads another tool's OAuth tokens from the agent's credential pool and calls an undocumented usage endpoint with a borrowed client user agent. The standard keeps the `spend` and `plan_limits` slots (section 5.3); an adapter is the consumer's own, on a documented usage source. The spend page is lifted in the app |
| 18 | sprint close, retro, ticket progress, needs me | sprint close gate lifted (`gates/`); the rest not lifted |
| 19 | 1:1 board, yearly export | not lifted: the module is built on a directory pull, calendar and meeting adapters and a roster; it waits on the people slot interface (roster, calendar, meetings) and on the exception for a document export library. The pages are lifted in the app |
| 20 | links check | lifted: `server/modules/link_health.py` (catalog is the consumer's file) |
| 21 | knowledge proposals | lifted: proposal rewrite gate, applied log, `engine/publish_mode.py`; the queued approvals applier is not |
| 22 | plans reconcile | lifted: `gates/plans_reconcile_gate.py` |
| 23 | pull request dependencies, search | lifted: `server/modules/pr_deps.py`, `ops_search.py` |
| 24 | cron catalog gate, sitrep, hermetic test home, reviews visibility check | cron catalog gate and hermetic home lifted; the sitrep and the visibility check scripts are not in the snapshot |
| (2.4) | swr, alerts, review tombstones, paths | lifted: `server/modules/` |
| (2.6) | analyzer: contract, handled match, first seen | lifted: `engine/`; routing, the collector and the bundle builder are not in the snapshot or need the collector |
| (4) | the app | lifted: `opscenter/app`, all 114 source files, typecheck, unit tests and build in CI; the browser tests are `npm run test:browser` |

Server modules and pages that exist in the running app but whose server half is not lifted (people, tracker, review engine
pages) render only when their slot is on; the app reads the running API shapes until the envelope and registry (R1, R2)
land.

### 12.8 Module parameters (the five modules that named estate repositories or files)

Each of these modules was tied to named repositories or one estate file. They lift as optional modules whose estate
facts are parameters (section 6): a value in `local/params.json`, or the environment variable the module header names
(the server reads the params file and sets them). No default names an estate; a required value that is missing makes
the module report `unavailable` and hide its UI (section 1.3), never guess.

| Module (item) | Parameter | Default | Meaning |
|---|---|---|---|
| `cron_pulse` (12) | `cron_pulse.repos` | `{"primary": "owner/primary", "secondary": "owner/secondary"}` | repo key to `owner/name`: the repositories whose Reviews pages carry a jobs strip; a job that names exactly one of them is mapped to its page |
| `cron_pulse` | `cron_pulse.branch_key` | `[A-Z][A-Z0-9]+-\d{3,5}` | regex of the ticket key at the start of a branch name, so a job that names `KEY-1234-slug` watches `KEY-1234-*` |
| `link_health` (20) | `links.catalog_file`, `links.catalog_rel` | `<root>/local/links-catalog.json`, same | the consumer's catalog file and its path in the repo; the catalog is the consumer's data, never core |
| `link_health` | `links.repo`, `links.repo_dir` | `owner/ops-center`, `<repos>/ops-center` | where a Swap or Remove edit opens its pull request |
| `link_health` | `links.git_name`, `links.git_email`, `links.changelog_tool` | `ops-center`, a noreply address, none | identity of the edit commit; an optional script that writes the changelog entry before the commit |
| `runbook_releases` (15) | `releases.repo`, `releases.self_login` | `owner/repo`, `owner-login` | the repo and the owner's login recorded as the dispatcher |
| `runbook_releases` | `releases.workflow`, `releases.plan_job`, `releases.tier`, `releases.watch[]` | `deploy-runbooks.yml`, `terraform plan (runbooks {tier})`, `prod`, runbook paths | the guarded deploy workflow, its plan job name, the tier whose deletes it releases, and the paths whose change alters what a dispatch plans |
| `desktop_pool` (14) | `pool.subscription`, `pool.resource_group` | none (required) | the cloud scope the read only host pool GET runs in |
| `desktop_pool` | `pool.prefix`, `pool.host_prefix`, `pool.roll_workflow` | `hostpool-`, `host`, `.github/workflows/pool-roll.yml` | pool and session host naming, and the workflow that marks a card as a pool roll |
| `publish_mode` (21) | `docs.host`, `docs.changelog_title`, `docs.digest_tz` | `https://docs.example.invalid/wiki`, `(?i)\bchangelog$`, `UTC` | base URL of version and history links, the title a changelog page must match, and the zone the digest groups days in |

Behaviour that is not a parameter: a failed read is `unknown` and never a pass; every edit goes through a pull request
and CI is the gate (no `--no-verify`); a class of proposal is `staged` unless the owner set it to `auto`.

### 12.9 The auto-fix starter (items 3 to 5)

`lanes/autofix.py` starts one agent session to fix one of the owner's own pull requests held for a fixable problem. It
refuses every other author, keeps one session per (pull request, head, problem), caps sessions per pull request per day, and
gives up with a reason the board shows under Needs me. Everything the running code knew about its repositories, people and
tools is a parameter or a plug-in:

| Part | Parameter or plug-in | Default |
|---|---|---|
| targets | `AUTOFIX_TARGETS` file `{"skills": [...], "targets": {name: {repo, notes, skill, build, identity, catalog, sync_branch_prefix}}}` | `<state>/autofix-targets.json`; absent means no target notes, no build skill |
| limits | policy `autofix.enabled`, `max_sessions_per_day`, `run_budget_s` | on, 3, 5400 |
| pre-push gate | `AUTOFIX_PREFLIGHT_CMD`, `AUTOFIX_REVIEW_CMD` templates with `{target}` and `{worktree}`; exit 0 pass, 1 findings printed, 2 environment problem (a failure) | unset: the session runs the repo's own tests |
| agent runtime | `set_runtime(obj)` (`busy_session`, `launch`, `finished_sessions`, `archive`); `HermesRuntime` is the reference adapter | `NullRuntime`: never busy, launch recorded only |
| held files | `AUTOFIX_HELD_GATE` module with `path_reasons(files)` (the plan gate) | every `.github/` path |

A `build` target batches fixes into one push per round and loads its build skill; a target with a `catalog` appends
`CATALOG ADD` lines from a session's result to it (deduped); a target with `sync_branch_prefix` gives branches outside the
prefix the notes of `<target>-feature`. The brief tells the session to commit as the target's `identity` (a noreply
address where the repo rejects real ones), never to merge, approve, label or weaken a check.

### 12.10 The reviews visibility check (item 24)

`lanes/reviews_visibility.py` proves that every open item behind the Reviews pages sits in a tab with an action and that the card
agrees with the lane that owns it. It raises one board item per finding (`contradiction`, `invisible`, `stuck`), updates it in place
and closes it when the condition clears; it reads the live Reviews bundles, the lanes' own pull request state and the code host, and
writes only its own state file and the board store.

Lane parameters (`local/params.json` `reviews_visibility`, or the environment variable):

| Parameter | Variable | Default | Meaning |
|---|---|---|---|
| `lanes` | `RV_LANES` | none (required) | `{"primary": {repo, own_state}, "secondary": {repo, own_state}}`: the repo and the own pull request lane's state file of each lane. The primary lane also carries privileged plans, owner roots and runbook releases; a consumer with one lane omits `secondary` |
| `self_login` | `RV_SELF_LOGIN` | `owner-login` | the owner's login (which pull requests are the owner's) |
| `owner` | `RV_OWNER` | `owner` | the owner field of the board items it raises |
| `own_check` | `RV_OWN_CHECK` | none | the lane's live check, a command with `{pr}` and `{lane}` that prints the lane verdict JSON; without it the live read is skipped |
| `refresh` | `RV_REFRESH` | none | an optional command that refreshes the ops center data after a change |
| `base` | `RV_BASE` | `http://127.0.0.1:8766` | the ops center base URL |

Thresholds (privileged assessment 20 minutes, plan never parsed 10, in flight 20, the owner's pull request waiting 30, an owner root
in flight 30, a runbook release 60, a waiting deployment 6, a new pull request not picked up 20 and 15) are constants in the module.

