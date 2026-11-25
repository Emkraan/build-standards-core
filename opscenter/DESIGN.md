# Core ops center: design

Status: the design is a target and the code is the lifted reference. Read section 12.67 first: it says which
files of the layout in 1.1 exist in the current release, which were built under another name and which are not built,
and where each consumer extension point lives. Section 12 records what the shell consumer's running ops center does,
row by row against sections 2 to 9, and the owner's decision (section 11, item 7) that every module it runs belongs
in the standard.

Inputs: `standards/local-ops-app.md` (the ops center rules today), the web-ui-standard doc,
the web-shell-standard doc, the web-api-runtime-standard doc, `standards/rules.json`, `opscenter/kit/README.md`,
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

The layout below is the target. 12.67 lists which of these files exist today and which are not built.

```text
opscenter/
  DESIGN.md            this file
  CONTRACT.md          the neutral contract (routes, state files, slots, parameters); replaces the
                       per-app contract/ops-center-contract.md
  server/              stdlib Python HTTP server and API modules
    app.py             entry: bind, gate, registry, static files
    gate.py            Host and Origin guard, body cap, security headers, preflight
    registry.py        route registry (method, path, auth class, schema, handler)
    live_bus.py        push channel: topic versions, the event stream, tab presence (Local Ops App 20)
    live_watch.py      push channel loops: data scan, source watch, warm loop
    live_routes.py     GET /api/live, POST /api/live/presence and the loop wiring
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

The ops center is consumed as a synced copy, never hand edited. Its UI kit (`kit/`) and design tokens
(`tokens/`) are part of `opscenter/` and travel inside that copy: they are the ops center's own UI code,
not a separate shared copy.

```text
<consumer ops center repo>/
  opscenter-core/      synced copy of the core opscenter/ (except DESIGN.md, tests/, adopt/), kit/ and tokens/ included
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
- The build compiles `opscenter-core/app` against `opscenter-core/kit/` and `local/slots/*/ui` (slot UI is
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

1. Build: `pnpm install --frozen-lockfile`, `pnpm run build` against `opscenter-core/kit/` and `local/slots`.
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
   (`--ops-center PATH`). Syncs `opscenter-core/` (kit and tokens inside it) and the overlay with
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
| 1 | review lane engine | lifted: `lanes/pr_review.py`, `own_pr_merge.py`, `destroy_followup.py`, `model_bump.py`; the policy is data with a documented schema (`lanes/REVIEW_POLICY.md`, 12.12) |
| 2 | maintenance windows | lifted: `lanes/maintenance_window.py` (change classes `standard` and `restricted`, windows as policy data) |
| 3 | own pull request lane, decision cards | lifted: `server/modules/own_lane.py`, `decision_cards.py`, `lanes/own_pr_merge.py` |
| 4, 5 | own sync auto fix, core pull request lane | lifted: `lanes/own_sync_lane.py`, `lanes/core_pr_lane.py` (12.16) |
| 6 | merge queue | lifted: `lanes/merge_queue.py`, `gh_run_jobs.py` |
| 7 | queued docs approvals | lifted: `lanes/queued_approvals.py` with the docs home adapter as a command that defaults to nothing (12.17); the documentation audit it can trigger is the consumer's |
| 8 | change freeze gate | lifted: `lanes/freeze_gate.py` |
| 9, 10 | plan gate, privileged apply review | plan gate lifted: `lanes/tfplan_gate.py` with a reference sign-off store; the privileged lane is lifted too (`server/modules/privileged_reviews.py`, 12.28) and the seam (`set_privileged_gate`) stays for a consumer lane |
| 11 | dark launches | lifted: `server/modules/dark_launches.py` |
| 12 | cron card map, run now | lifted: `server/modules/cron_pulse.py` (parameters in 12.8) |
| 13 | builds page | lifted: the app page and `server/modules/builds.py` (12.20) |
| 14, 15, 16 | image watch and pool, runbook releases, browser status | lifted: `image_watch.py`, `desktop_pool.py`, `runbook_releases.py`, `browser_status.py` |
| 17 | model accounts, spend, fallback | lifted as a provider slot (owner decision): the page, routes, routing and cooldown, caching, last good copy, spend history, ledger reader and fallback watch are core (`server/modules/model_accounts.py`, `model_fallback.py`, 12.22); the accounts come from a `ModelAccountsProvider`, null by default (an empty page). The credential pool read and the vendor usage endpoint are not in core: a provider that declares a pool read is refused at load unless the consumer enables it |
| 18 | sprint close, retro, ticket progress, needs me | lifted: `gates/sprint_close_gate.py`, `tracker/` (`work.py`, `needs_me.py`, `ticket_progress.py`, `retro_row.py`, the reference `driver.py`) and `gates/retro_row_gate.py` (12.15) |
| 19 | 1:1 board, yearly export | lifted: `people/` (`one_on_ones.py`, `team_away.py`, `yearly_reviews.py`) with the four adapters as commands and files with a null default (12.14); the yearly drafter is the consumer's command |
| 20 | links check | lifted: `server/modules/link_health.py` (catalog is the consumer's file) |
| 21 | knowledge proposals | lifted: proposal rewrite gate, applied log, `engine/publish_mode.py`; the queued approvals applier is item 7 |
| 22 | plans reconcile | lifted: `gates/plans_reconcile_gate.py` |
| 23 | pull request dependencies, search | lifted: `server/modules/pr_deps.py`, `ops_search.py` |
| 24 | cron catalog gate, sitrep, hermetic test home, reviews visibility check | cron catalog gate, hermetic home, reviews visibility check and the sitrep (`gates/sitrep.py`, `sitrep_prerun.py`) lifted; the live ref check is `engine/ref_status.py` (12.18) |
| (tools) | export path map, per pull request changelog tool | lifted: `tools/livepath.py`, `tools/changelog.py` (both configured by JSON files, `tools/README.md`) |
| (collector) | inbound mail and chat monitor gates | lifted: `gates/inbound_mail_gate.py`, `inbound_chat_gate.py`, `inbound_score.py` (12.19) |
| (2.4) | swr, alerts, review tombstones, paths | lifted: `server/modules/` |
| (2.6) | analyzer: contract, handled match, first seen, routing, collector, bundle builder, wake gate | lifted: `engine/` (`contract`, `handled`, `first_seen`, `routing`, `collect`, `analysis_bundle`, `board_build`), `gates/action_center_gate.py`, `server/modules/routing_api.py` (12.13) |
| (server modules, debt page) | debt and improvements page server half | lifted: `server/modules/eng_backlog.py` (12.25) |
| (doc audit) | documentation audit and coverage page | lifted: `engine/doc_audit.py`, `server/modules/doc_coverage.py` (12.26); the docs home read is a driver the consumer supplies |
| (runtime restart) | runtime restart card | lifted: `server/modules/runtime_restart.py`; the restart is a consumer script (12.35) |
| (platform reviews) | the platform reviews page server half | lifted: `server/modules/platform_reviews.py`; every estate value is the review config `platform` object (12.47) |
| (badges) | sidebar badges payload | lifted: `server/modules/badges.py` (12.48) |
| (problem list) | the single source of counts | lifted: `server/modules/problems.py`, `builds.pipeline_state`, `infra.badge_problems` (12.50) |

| (run contract) | start buttons: workflow dispatch, maintenance tasks, scheduled job run now | lifted: `builds.dispatch`, `infra.task_run`, `cron_pulse.run` (12.49) |
| (PR landing) | structured ask for PR cards | lifted: `lanes/pr_landing.py` (12.42) |
| (label hold) | hold label explainer | lifted: `lanes/label_hold.py` (12.44) |
| (maintenance hold) | maintenance window hold for the review pages | lifted: `lanes/maintenance_hold.py` (12.41) |
| (review helpers) | live code host facts and review conversations | lifted: `server/modules/live_truth.py`, `lanes/review_threads.py` (12.27) |
| (privileged reviews) | privileged deployments lane and review config | lifted: `server/modules/privileged_reviews.py`, `review_config.py` (12.28) |
| (repo reviews) | other repos review page | lifted: `server/modules/repo_reviews.py` (12.29) |
| (plan reviews) | plan review queue | lifted: `server/modules/tf_reviews.py` (12.30) |
| (plan context) | facts for apply cards | lifted: `server/modules/tf_context.py`; principal names are a provider slot (12.40) |
| (approval brief) | brief on decision cards | lifted: `server/modules/approval_brief.py`; the model is a consumer command (12.45) |
| (card brief) | brief for non-PR cards | lifted: `server/modules/card_brief.py`; estate wording is one data file, pool roll evidence an optional module (12.43) |
| (host pool view) | optional pool evidence on a pool roll card | lifted: `server/modules/pool_view.py`, off by default; the read is a consumer command (12.46) |
| (other repo reviews) | second repo review page | lifted: `server/modules/other_reviews.py`; the escalation source is a consumer command (12.31) |
| (plans) | plans page | lifted: `server/modules/plans.py` (12.32) |
| (infrastructure) | infrastructure page | lifted: `server/modules/infra.py`; the runtime-bound feeds are a provider slot (12.33) |
| (owner-applied roots) | owner apply page | lifted: `server/modules/owner_roots.py`; the cloud is a provider slot (12.34) |
| (server modules, core consumption) | the core consumption panel's server half | lifted: `server/modules/core_consumption.py` (12.24) |
| (sessions and cards) | session on it, launch session resolver, curation front door, inbound files, CI test runner, page renderer | lifted from the reference: `pr_sessions.py`, `tackle_session.py`, `eng_curate.py` (with the `eng_backlog.py` additions), `people/inbound_files.py`, `tools/ci_tests.py`, `engine/doc_render.py`; the resolved-card return (OC-23) was already in `engine/handled.py` (12.56) |
| (run watches, status files) | main watch, red nightly drift streak, unknown never in sync, a lapsed sign-in never silent | lifted: `lanes/run_watches.py`, `server/modules/status_source.py`; written from the inventory text and test names, no reference code (12.55) |
| (owner roots ahead of main) | ahead-of-main card and apply locks, owner apply guard, ahead more than two days card, draft gate block | lifted: `owner_roots.py` (holds, guard that fails closed with `--allow-pr` and `--allow-missing-status`, terminal `--log-start` and `--log-done`, ahead card), `lanes/pr_gate.py`; the branch apply flow that records a hold is the consumer's (12.54), and the live reads behind open PR coverage and the detection of an unrecorded branch apply are the consumer's provider hooks `open_pr_addresses` and `detect_ahead` |
| (freeze lane) | human freeze bypass, CI-only exemption, GraphQL labeler, stale green re-run | lifted: `lanes/freeze_bypass.py`, `lanes/freeze_ci_only.py` and the lane changes in `own_pr_merge.py`; the CI-only classifier and the PR read are from the inventory text, not from reference code (12.53) |
| (overrides and self-healing) | gate overrides, no stale reason after an action, transient failures heal themselves | lifted: `server/modules/override_store.py` (the store, fail closed), the stale saved plan re-plan in `owner_roots.py`; the override gate and the card state are the consumer's and the kit's (12.52) |
| (layout adoption) | the approved ops center layout in the app | lifted: the Operations hub (`opscenter/app/src/pages/Operations.tsx`, `pages/operations/`), the kit sectioned header, Overview cards and run dialog, redirects and the route lock file (12.51) |
| (server) | the running server and its routes | lifted as a generic server: `server/` (12.21); the agent session routes are the runtime slot (12.23) and every page half is lifted |
| (4) | the app | lifted: `opscenter/app`, all 114 source files, typecheck, unit tests and build in CI; the browser tests are `npm run test:browser` |

The server (12.21) is lifted as a generic one: the gate, the registry, static serving, the action handled and approvals stores and the
routes of every lifted module. The routes that start agent sessions are the runtime slot (12.23); every page's server half is in `server/modules/` and what is estate is configuration or a provider slot (12.28 to 12.47).
The pages whose server half is optional (people, tracker, review lanes) render only when their slot is on.

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

### 12.11 The pre-push gate and the build procedure (items 3 to 5)

The auto-fix starter (12.9) runs a consumer's pre-push gate as a command, and the build procedure (`opscenter/pr-build/PROCEDURE.md`)
says when. The gate is the contract below; a consumer's own gate implements it, and the reference implementation of the checks is
`lanes/preflight.py`, whose targets come from the same targets file as the auto-fix starter (profile keys: `repo`, `policy`,
`lane_engine`, `plan_matcher`, `prompts`, `branch_rule`, `catalog`, `version_file`, `version_regex`, `js_gate`, `selftest_paths`; top
level `self_login`, `author_name`, `author_email`, `attribution_extra`). The lane engine and the plan matcher are modules named by
path (the plan matcher is `lanes/tfplan_gate.py`), each skipped when unset; the OpenAI reviewer's key comes from a command
(`PREFLIGHT_OPENAI_KEY_CMD`), never a file or a parameter.

| Part | Contract |
|---|---|
| command | `AUTOFIX_PREFLIGHT_CMD` and `AUTOFIX_REVIEW_CMD`, templates with `{target}` and `{worktree}`; `run`, `review`, `review-template` and `design-template` are the four verbs |
| exit | 0 pass (warnings allowed), 1 failures printed with the fix, 2 environment problem (a failure, fail closed); `review`: 0 clean or round budget spent, 1 unrefuted highs, 2 reviewers unavailable |
| writes | only `<worktree git dir>/preflight-*.json`, the self review file, `local-review.json` and `design-check.md`; never a push, never a code host write |
| checks | repository gates for what changed, hygiene (ASCII and dashes, version bump, branch rule, conflict, attribution, secrets), the lane dry run as expected sign offs, overlap with other open pull requests, the catalog's scriptable rules, the self review gate (diff hash file with `FIXED` and `PRE-TRIAGE` lines), the local independent review (at most 3 rounds, `REFUTED` and `OPEN-HIGH` lines), and the design check for acting automation (eight questions) |
| per repository | a profile in the targets file (12.9): repo, policy file, whether the plan matcher applies, review prompt paths, branch rule, identity |

`finding-catalog.md` is the learning loop: the auto-fix starter appends `CATALOG ADD` lines from a session's result to a target's
catalog file.

### 12.12 The review lane engine (items 1 and 3)

`lanes/pr_review.py` is the engine behind the engineer pull request review: the wake gate, the deterministic check,
the one approve path and the maintenance window hold. `lanes/own_pr_merge.py` is the owner's own pull request lane,
which loads the engine as a module and the auto-fix starter (`autofix.py`) for a held pull request.
`destroy_followup.py` and `model_bump.py` are the two helpers the gate script calls on each tick. The schema of the
policy both read is `lanes/REVIEW_POLICY.md`; nothing about a repository, a tier or a person is in the code.

What is a parameter, and where:

| Fact | Where it comes from |
|---|---|
| repository, owner login, approve identity | the policy file (`repo`, `self_login`, `approve_as`); `destroy_followup` reads `OPSCENTER_REPO`; `model_bump` reads its targets file |
| targets | `primary` and `secondary` (`--target`); a targets file (`OPSCENTER_REVIEW_TARGETS`, JSON) overrides `repo`, `tag`, `ticket`, directories and file names per target |
| tier names | `OPSCENTER_PROD_TIER` (default `prod`), `OPSCENTER_TIERS` (default `prod\|dev`) for the destroy follow-up; `trust_rules.dev_tier_only.prod_tier` and `maintenance_window.tier` in the policy |
| engineer branch prefix | `OPSCENTER_BRANCH_PREFIX` (default `ticket-`), read by the branch drift rule |
| lane label in cards and gate lines | `OPSCENTER_LANE_LABEL` (default `primary`) |
| words a posted comment may not contain | `OPSCENTER_FORBIDDEN_WORDS`, added to the built in list (bot, assistant, co-authored-by) |
| state and cache | `OPSCENTER_STATE_DIR`, `OPSCENTER_AGENT_HOME` (`lanes/paths.py`), `OPRG_STATE_DIR`, `OPRG_CACHE_DIR` |

Plug-ins and seams: the draft gate (`OPSCENTER_DRAFT_GATE`, a file that provides `parse(body)`, `evaluate(gate, repo, gh)`
and `summary(results)`; absent, a draft is held with the reason "no draft gate plug-in is configured" and never
guessed ready), the sign-off store (`tfplan_gate.set_signoff_store`, 12.3), and the auto-fix starter
(`autofix.py`, 12.9, whose runtime, pre-push gate and targets are already plug-ins).

Differences from the running lane, marked honestly:

- The reference sign-off store gained `review`, `plan_facts`, `path_of` and `latest_epoch`. The running store was not in the
  snapshot, so these were written from the tests the lane ships: a sign-off carries to a later head only when every hit is
  covered by fingerprint and the plan adds no destroy, replace or grant the signed plan did not hold. A consumer with its own
  store keeps its rules and must provide the same four functions.
- The default forbidden word list no longer names the estate's tools; a consumer adds its own through the environment.
- The policy fixtures are examples with neutral names; the running policies stay the consumer's data.
- `model_bump.py` had no test in the snapshot; `model_bump_test.py` covers the target settings only.

### 12.13 The analyzer inputs (item (2.6))

The collector turns every source into one candidate shape, `routing.py` decides where each belongs from rules that are
data, `analysis_bundle.py` assembles the model's input, `action_center_gate.py` decides whether the job runs, and
`board_build.py` composes the served board from the job's file. Nothing here calls a model.

Parameters: the collector reads one JSON file (`OPSCENTER_COLLECT_CONFIG`, default `<state>/dashboard/collector.json`), every key
optional and no default naming an estate:

| Key | Default | Meaning |
|---|---|---|
| `owner_name` | `the owner` (or `OPSCENTER_OWNER_NAME`) | the owner's display name: their own messages are not asks, their tickets land on them |
| `ref_regex` | `KEY-123` style, bare `#123` ignored | what counts as a ticket or change reference in a text |
| `ask_days` | 3 | how far back mail and chat count |
| `mail_feed` | `<agent home>/feeds/mail.json` | the mail feed file (`{"items": [...]}`, fields `received`, `direct_ask`, `direct_to_me`, `from_name`, `from_addr`, `subject`, `body_text`, `preview`, `web_link`) |
| `chat_feeds[]` | none | `{prefix, label, path, team_posts}` per chat platform; the prefix names the source ids (`<prefix>.1on1`, `.mention`, `.channel`, `.channel_reply`, `.group`) |
| `tracker_snapshot`, `tracker_base_url` | `<state>/tracker-snapshot.json`, none | `{"tickets": {KEY: {status, priority, duedate}}, "last_check_utc"}` and the browse URL prefix |
| `state_files` | `<state>/current-state.md`, `risk-radar.md`, `unplanned-work-ledger.md`, `decisions-log.md` | the markdown state files the state adapter and the bundle read |
| `doc_gaps_file` | `<dashboard>/doc-gaps.json` | the documentation audit's store |

Plug-ins, each a python file named by an environment variable, each optional (absent means nothing is added):

| Variable | Contract |
|---|---|
| `OPSCENTER_PEOPLE` | `roster()` returning `[{name, group}]` (the roster slot, DESIGN.md 12.14), optional `agenda_action_items()` and `harvest(force)` |
| `OPSCENTER_BOARD_SOURCES` | a JSON list of files, each with `action_items()` returning board items (keys `oo-`, `file-`, `auto-` are reserved for the ops center's own) and optional `harvest_feeds()` |
| `OPSCENTER_REF_STATUS` | `resolve(text)` returning `{refs, done, errors}` and `finished(items)` returning `{key: reason}`: live status of the tickets and pull requests a text names, used by the bundle and to close an auto item whose references are all done |
| `OPSCENTER_TEAM_AWAY` | `snapshot()` returning `{people: [...]}`: who is out, shown above the list |

The bundle step writes to `OPSCENTER_BUNDLE_OUT` (default `<state>/public-data`), copies the datasets named in
`OPSCENTER_BUNDLE_DATASETS` through, reads monitor files from `OPSCENTER_MONITORS`, and stamps the refresh time in
`OPSCENTER_TZ`. The design's direction is live reads with no bundle (2.4); this is the step a consumer still on a bundle runs.

Differences from the running code, marked honestly: the running collector had Teams, Slack, Jira and a named owner in
its adapters. They are generic here (`chat_feeds`, `tracker`, `owner_name`), so the source ids are `chat.*`, `tracker.assigned`
and so on and a consumer's routing file renames its own. The seed rules in `engine/fixtures/routing-seed.json` are examples,
not the running rules. The running wake gate wrote its bundle under a fixed temporary path; it writes under the gate state dir.

### 12.14 The people slot (item 19)

The slot is the code in `opscenter/people` plus four adapters the consumer supplies. Nothing about a person, a tenant or a
tool is in the code; the parameters file `OPSCENTER_PEOPLE_PARAMS` (default `<state>/people-params.json`) carries it, every
key optional:

| Key | Default | Meaning |
|---|---|---|
| `owner_name`, `owner_email` | `the owner`, none | the owner's identity: their own messages are not topics, their address is not an attendee |
| `roster` | none | `[{name, first, email, title, group}]`, `group` `report` (default) or `partner`. A report carries no title or address in code: the directory pull owns them |
| `calendar_tz` | `UTC` | the zone the calendar reads wall clock times in |
| `feeds` | `<agent home>/feeds/chat.json`, `mail.json` | the message feeds |
| `roster_pull_file`, `calendar_cmd`, `meetings_cmd` | none | the roster, calendar and meetings adapters |
| `meeting_subject` | `{owner} and {first}: 1:1` | the invite subject, with `{owner}`, `{first}`, `{name}` |
| `retention_days` | 45 | how long the ledger keeps a topic (section 11 item 5) |
| `ticket_regex`, `ticket_url_regex`, `mail_noise_regex`, `partner_invite_regex`, `excluded_title_regex` | generic | what a ticket key is, which mail subjects are never topics, standing invites, and titles that never belong on the board |
| `team_name`, `drafter_cmd` | `Team`, none | the yearly store's header and the drafting job command (a list; the job is passed as `--job <file>`) |

The four slots, each with its null default (the board renders, and the part that needs it reports itself unavailable):

1. **Roster.** `roster_pull_file` is a JSON list (or `{"value": [...]}`) of `{displayName, jobTitle, mail}` rows from the
   consumer's directory. The pull wins whenever it parses and writes the last good copy (`roster-last-pull.json`, a digest
   guards it from hand edits); the copy is read only when the pull fails and the board shows it stale with its age. Never raises.
2. **Calendar.** `calendar_cmd` prints today's events as JSON (a list, or `{"value": [...]}`) with `subject`,
   `start.dateTime`, `end.dateTime` (wall clock in `calendar_tz`), `attendees[].emailAddress.address`, `isCancelled`,
   `onlineMeeting.joinUrl`, `webLink`. Ten minute cache; the last good pull is kept on a failure.
3. **Meetings.** `meetings_cmd` is run with `upcoming --days N`, `availability --email E --days D --minutes M`,
   `create` (the request as JSON on stdin) and `away --emails A,B --days D`. The last stdout line is JSON; exit 0 ok, 2 sign in
   needs a refresh, 3 service error, 4 bad input; an error prints `{"error": ..., "reauth"?: true}`. `create` carries
   `auto_transcribe` and `what_if` (a dry run) and returns `{id, subject, start, end, join_url, transcription}`. A 90 second guard
   refuses a second booking for the same person.
4. **Message feeds.** Read only files `{"updated", "items": [...]}`. Chat items: `created`, `chat_id` or `channel`, `chat_type`
   (`oneOnOne` marks a 1:1), `from_name`, `id`, `text`, `chat_topic`, `web_url`. Mail items: `received`, `from_addr`, `from_name`,
   `subject`, `conversation_id`, `id`, `preview`, `web_link`. A missing or corrupt file yields no topics.

Wiring: `one_on_ones.py` is the `OPSCENTER_PEOPLE` plug-in of the collector and the board composer (12.13: `roster()`,
`agenda_action_items()`, `harvest(force)`), and `team_away.py` is `OPSCENTER_TEAM_AWAY` (`snapshot()`). The server routes
(`/api/one-on-ones` and its availability, status, topic and schedule writes, the yearly review routes) call the module
functions `board()`, `availability()`, `schedule()`, `set_status()`, `add_topic()`, `remove_topic()` and the yearly store's
`upsert()`, `start_job()`, `get_all()` and `export_docx()`; they are loopback and same origin only, and people endpoints send
`no-store` (section 2.2). State files: `one-on-one-topics.json`, `one-on-ones.json`, `one-on-one-seen.json`,
`roster-last-pull.json`, `team-away.json` and the `team-performance/yearly-reviews*` files, all written atomically.

Differences from the running code, marked honestly: the roster, the owner identity, the subject format, the zone and the
ticket and noise patterns were literals and are parameters; the calendar and meetings helpers were scripts of one cloud
mail and calendar tenant and are commands behind the contract above (the helpers themselves are the consumer's and are not
in core); the drafter that reads the full year evidence and calls a model is the consumer's command (`drafter_cmd`); the
topic source names (`teams`, `mail`) and the `teams_updated` field keep the names the app already reads. The yearly export
could not be run here without python-docx (pinned in `people/requirements.txt` for the pinned requirements rule): its test is skipped when the package is missing.

While the slot is off (`OPSCENTER_PEOPLE` unset, the default) the people pages render nothing and cost nothing. The server
adds no people route (`one_on_ones` and `yearly_reviews` are skipped when the route table is built), so `GET /api/one-on-ones`
answers 404. The app reads that 404 as the off state, not as a failure: the People group leaves the rail, the shortcuts and
the palette, the sync chip is not drawn, and `/people`, `/team` and `/team/:tab` (all still in `routes.lock.json`) show the
"needs the people slot" state (12.72), which replaced the redirect to the home route. Before the first answer a people route
waits, and an unreachable server still shows the page so its own error is read. Tests: `app/tests/peopleSlot.test.mjs` for the decision, `server/server_test.py` for the route table with the
slot off and on.

### 12.15 The work tracker adapter (item 18)

`tracker/work.py` is the one place the ops center talks to the issue tracker; the sprint close gate's scanner, the Needs me tab,
the ticket progress job and the retro row all use it (or the same driver). It runs one command per call:
`<driver_cmd> <tool> '<json args>'`, which prints the JSON-RPC result of one tool call (`{"result": {"content": [{"text": ...}],
"isError"?: ...}}`) and exits 0; a non zero exit, non JSON output or `isError` raises `TrackerError` (HTTP 502 on the server).
The tool names are the tracker connector's (`searchJiraIssuesUsingJql`, `getJiraIssue`, `editJiraIssue`,
`getTransitionsForJiraIssue`, `transitionJiraIssue`, `atlassianUserInfo`, `addCommentToJiraIssue`, and the wiki tools the retro row
uses); `tracker/driver.py` is the reference driver for the Atlassian MCP endpoint and reads its endpoint and token file from
`TRACKER_ENDPOINT` and `TRACKER_TOKEN_FILE`.

Parameters (`OPSCENTER_TRACKER_PARAMS`, default `<state>/tracker-params.json`, every key optional, no default naming an estate):

| Key | Default | Meaning |
|---|---|---|
| `site_id`, `browse_url` | none | the tracker site and the browse URL prefix |
| `driver_cmd` | the reference driver | the command list that runs one call |
| `project`, `team_clause` | none | the project the active sprint is read from, and a JQL clause that scopes a view to the owner's team |
| `sprint_field`, `points_field` | `customfield_10020`, `customfield_10016` | the Sprint and story points field ids |
| `email_domain` | any | the address domain a roster email must have to be used in a query |
| `owner_name` | `the owner` | assignee match, tracker owner match, card owner |
| `change_jql`, `change_pending_statuses`, `change_inflight_statuses`, `change_fields`, `portal_url_template` | none | the changes pending the owner's approval (read only); no `change_jql` means no data |
| `intake_parent`, `tz`, `banned_words`, `model_cmd` | none, `UTC`, none, none | ticket progress: the epic whose children are intake, the working day zone, extra words a posted comment may never contain, the model command (a prompt on stdin, JSON reply on stdout) |
| `close_out_cmd` | none | needs me: starts the close-out job now (without it the scheduler's gate picks the decision up) |
| `retro` | none | the retro row: `parent_page`, `board_id`, `row_name`, `repos`, `gh_author`, `title_match`, `page_url`, `rules`, `banned_words` |
| `reauth_cmd` | none | an optional command that refreshes the tracker sign-in after a 401 |

The roster for a report's sprint items comes from the people plug-in (`OPSCENTER_PEOPLE`, 12.14). Writes are limited to issues
assigned to the owner, confirmed on read-back, and never close a ticket (closing runs through the closure comment process);
`what_if` runs every guard read and skips the write.

Differences from the running code, marked honestly: the site and board ids, the team and change field ids, the browse and portal
URLs, the owner name and the intake epic were literals and are parameters; the retro rules default to a neutral list (the
running rules are the owner's own wording and stay the consumer's `retro.rules`); the posted progress comment keeps the owner's
first person voice (the draft is posted as the owner); the running code reached the model through another module of the app and
now reaches it through `model_cmd`, so the model draft is off until a command is configured; the retro row had no test in the
snapshot and `retro_row_test.py` is new. The fingerprint parity test between a card id and the board skips when the board
composer (12.13) is not in the tree.

### 12.16 The core and sync pull request lanes (items 4 and 5)

`lanes/core_pr_lane.py` merges the owner's green pull requests on the core repository and `lanes/own_sync_lane.py` auto-fixes
the owner's nightly sync pull requests; both hand a hold a session can fix to `autofix.py` (12.9). Parameters are policy files
(`<state dir>/core-review/lane-policy.json` and `<state dir>/sync-review/own-pr-policy.json`, every key optional) and
environment variables (`CORELANE_*`, `MXLANE_*`); no default names a repository or a person (`repo` `owner/core`, `self_login`
`owner-account`). The core lane's after merge sync is `CORELANE_SYNC_CMD`, none by default. The fixer needs a targets entry per lane
(`core`, `sync`, and `sync-feature` for a feature branch) in `AUTOFIX_TARGETS`; for `core` the entry carries `extra_fixable`
(`[["local checks fail", "local-checks"], ["version needs a bump", "version-bump"], ["changelog entry", "changelog"]]`), which this
lift added to `autofix.problem_of` (a target's own needles, tried after the built in ones).

### 12.17 The queued approvals applier (item 7)

`lanes/queued_approvals.py` applies the approvals the owner clicked on the Knowledge page. Writes go only through
`docs_write_guard.py` (5.2: scope proof, create and update only, every decision logged); reads (the read back, the live page for
the append only check, the title lookup) go through the docs home adapter, `DOCS_HOME_CMD` (a JSON list that runs one call:
`<cmd> <tool> '<json args>'` prints the JSON-RPC result, the work tracker driver contract of 12.15). With no adapter every read fails
closed: a create stays queued (`RETRY`), nothing is written and the run exits 0. Parameters: `AQA_DASH` (default
`<state>/dashboard`), `AQA_GUARD` (a wrapper that supplies the guard's token provider), `DOCS_GUARD_CONFIG` (the allowed roots a
title lookup is scoped to), `DOCS_CLOUD_ID`, `AQA_AUDIT` (the consumer's documentation audit, run after a write). State files:
`approve-inbox.jsonl`, `approve-applied.jsonl`, `docs-proposals.json`, `proposals/<fp>.body`, `knowledge-curation-config.json`.
Differences from the running code: the tenant, the two tree roots, the driver path, the corporate certificate and the audit path
were literals and are parameters; the proposals store is `docs-proposals.json` (the gate's name); the test for the documentation
audit's duplicate check stayed out with the audit, which is not lifted.

### 12.18 The live ref check (item 24 remainder)

`engine/ref_status.py` is the plug-in behind `OPSCENTER_REF_STATUS` (12.13) and the sitrep's reference block (12.7 item 24). It
extracts the pull requests (`<prefix> PR #12`, a bare `PR #12` means the default repository) and tracker keys a text names, reads
their state live (the code host through `gh`, the tracker through a driver command) and reports which are finished. Parameters:
`REF_STATUS_REPOS` (JSON prefix to `owner/repo`, plus `default`), `REF_STATUS_KEY_REGEX`, `REF_STATUS_TRACKER_CMD` and
`REF_STATUS_SITE` (the 12.15 driver contract; none means ticket lookups report an error), `REF_STATUS_APPLY_WORKFLOW`. A read error never
marks anything finished. Differences from the running code: the repository and prefix map, the driver path and the key pattern were
literals and are parameters.

### 12.19 The inbound monitor gates

`gates/inbound_mail_gate.py` and `gates/inbound_chat_gate.py` are the wake gates of the two inbound monitors (the `collector` slot's
mail and chat feeds); `gates/inbound_score.py` is the noise filter they share. The pullers are the consumer's commands: the mail
gate runs `GATE_MAIL_PULLER` (a command list printing `{"messages": [...], "checkpoint", "new_checkpoint"}`), the chat gate runs the
sources of `GATE_CHAT_SOURCES` (each a list of commands printing `{"messages": [...]}`, exit 3 for "another pull holds the lock", optional
sentinels that wake with a fix text). The contract of the checkpoint handoff is unchanged: the gate pulls once and spools the batch, so
the agent never re-pulls. Kept items accumulate (`gatelib.accumulate`); an urgent keep reason (`urgent-signal`, `flagged-high-importance`,
`novel-alert`, `count-spike`, `firing-unresolved`) wakes now, anything else waits for a drain hour (`GATE_DRAIN_HOURS`). Every sender,
subject shape, bot, channel and name is data in `INBOUND_SCORE_CONFIG`; with none the scorer is a pass through that drops only
recorder bots. Differences from the running code: the vendor sender and subject lists, the ticket and incident patterns, the second chat
platform and the owner's name were literals; the Teams and Slack gates are one chat gate with sources; the hard coded interpreter and
puller paths are parameters. `gates/README.md` lists the variables.

### 12.20 The builds module (item 13)

`server/modules/builds.py` reads the runs of the pipelines named in `BUILDS_CONFIG` (default `<state>/builds-config.json`: `repo`,
`owner`, `branch_regex`, `pipelines[]` of `{key, product, label, workflow, refusal, summary}`, `summary_regex`, `landed`
(`{product: command list}`), `privileged_queue`); with no pipeline the page is empty. A landed command prints the JSON facts of what
landed for its product (recorded versus live, a `drift` list, an `errors` list); what it reads (a release record, a device management
service, a storage account) is the consumer's. The write is the one guarded action: Update from main re-reads the run, the branch and
the newest run live, refuses unless the run is a refused deploy on a branch matching `branch_regex` whose head the owner wrote, then
merges main into the branch through the merge API (201 merged, 204 re-run, 409 the conflicting files). Differences from the running
code: the product pipelines, the landed readers (a release record plus a device management read and a storage blob for one product,
the release list for another), the owner login and the ticket branch pattern were literals; the shared `infra` helpers it imported are
now `ghview.py`.

### 12.21 The server

`server/` is a stdlib HTTP server written for the core, not a copy of the running one (that file was tied to modules not yet lifted and to
the agent session routes below, and answered every origin with a wildcard CORS header).

- `gate.py`: the Host and Origin guard. A Host outside loopback and `OPSCENTER_ALLOWED_HOSTS` is 403; a write whose `Origin` or
  `Sec-Fetch-Site` is not the same origin is 403; a preflight is answered only for an origin listed in `OPSCENTER_PLUGIN_ORIGINS`, echoing
  that origin, never `*`. Body cap `OPSCENTER_MAX_BODY` (default 1 MiB, 413). Security headers on every response; reads of private
  pages (people, one to ones, yearly reviews) and every write are `no-store`.
- `registry.py`: `Registry.add/get/post`, a `Request` (`arg`, `payload`, `groups`, `body`), the read and write kinds (a write on GET, or a read
  on POST, is refused at registration), and the error mapping: a handler's `status` or `code` int wins, `ValueError` is 400, `KeyError` 404,
  anything else 502 with a fixed `read failed` body (the detail goes to the server log, not the client).
- `app.py`: static files from `OPSCENTER_DIST` jailed to that directory (symlinks and `..` refused) with single page fallback, ETag and 304, gzip;
  `OPSCENTER_HOST` (default loopback) and `OPSCENTER_PORT` (default 8766).
- `stores.py`, `routes.py`: `/api/health`, `/api/action-handled` (GET, POST with snapshot of the item from the served board, `restore`),
  `/api/approve` (approved and rejected go to the approvals inbox, changes to the proposal feedback file, optionally reworded by
  `OPSCENTER_REWRITE_CMD`), and the routes of every lifted module in `server/modules/` and the tracker and people packages; a module that is not
  in the tree is skipped, so a consumer that lifts fewer pages gets fewer routes.
- The routes that start an agent session are the runtime slot (12.23, null default). Every page's server half is in `server/modules/` (12.7); what is
  estate is configuration or a provider slot with a null default.

### 12.22 Model accounts provider slot (item 17)

`server/modules/model_accounts.py` builds the document the Spend page reads (`GET /api/infra/accounts`: `generated_utc`, `accounts[]`,
`ledger`; the field names are the app's `LlmAccount` and `LlmAccounts` types, plus `billing_model` and `limits[].window_s`).
`model_fallback.py` is the watch behind `GET /api/llm-fallback`. `GET` and `POST /api/infra/fallback-order` read the order and, when the
provider can, write it (501 when it cannot). A server thread calls `sample()` every 600 s so spend snapshots accrue with the page closed.

What core does: shape and clean the provider's reading; pick the routing account (the lowest priority one that is not cooling down and has no
error; cooling is an exhausted status with a reset in the future, or an hour from its status time when none is given, or any limit at 100
percent with a future reset); cache each read for `USAGE_TTL` (stale while revalidate); keep the last good copy per account and serve it marked
`stale` when a read fails; remember each account's billing model; record spend snapshots (on change, or hourly) and derive daily charges, a
partial first day, period rollover and a 7 day burn rate; tail the per call ledger JSONL (`ts, cred_id, input_tokens, output_tokens,
cache_read_tokens, cache_write_tokens, kind`; `OPSCENTER_MODEL_LEDGER`) into token windows (today, 7 days, month, and the session and week
from a limit's `resets_at` minus its `window_s`) and an unattributed count; run the fallback watch (a call billed to a usage account while the
first seat account is under `OPSCENTER_FALLBACK_HEADROOM_PCT`, default 90, opens an incident that closes after an hour without such calls; the
estimate comes from a rates file, `OPSCENTER_MODEL_RATES`, and is 0 without one). Day boundaries use `OPSCENTER_DISPLAY_UTC_OFFSET_HOURS`.

The provider (`OPSCENTER_MODEL_ACCOUNTS_PROVIDER=path/to/file.py:ClassName`, default none) supplies `credentials()` and `read_usage(cred_id)`
(contract in the module docstring) and optionally `set_fallback_order(ids)` and `stale_host()`. Differences from the running code: the
running code read one agent's credential pool and called a vendor usage endpoint with a bearer token; both stay in the consumer's provider.
Core has no network call and no credential store read, and a test asserts the module source names neither. A provider that sets
`needs_credential_pool_read = True` raises `ProviderRefused` (403 on the route) at load unless `OPSCENTER_MODEL_ACCOUNTS_ALLOW_POOL_READ=1`
(tested both ways). The running code's `llm_accounts.accounts()` is `list_accounts()` split in two (provider reads, core shapes); the interface
of C2 is `list_accounts`, `fallback_order`, `account_kinds` and `spend_history` on core, with `credentials` and `read_usage` on the provider.
The ledger writer (an agent plugin) and the cron wrapper (`python3 model_fallback.py` prints a new incident's message) are the consumer's.

### 12.23 The runtime slot

`server/runtime_slot.py` serves Tackle now, Discuss and the session list. The core owns the store, the prompt, the routes and the states
the app shows; the consumer supplies one command, `OPSCENTER_RUNTIME_CMD` (a JSON list or a shell-split string; default none).

- Null default: `GET /api/tackle` answers `{sessions: {}, runtime: {configured: false, state: "no runtime configured"}}` and every start
  answers 501 `no runtime configured`, before anything is read or run.
- `<cmd> start '<json>'`, in `{fp, kind (item, jira, pr, doc), title, prompt, context, mode}`, out `{session_id, pid?, log?, surface?}`.
  The prompt is built in core from the served board item (or the tracker row for `jira-<KEY>`, mine and open only), never from client text,
  and ends with how the session resolves itself (`POST /api/tackle/resolve {fp, summary}` on `OPSCENTER_PUBLIC_URL`).
- `<cmd> status '{session_ids: [...]}'`, optional, out `{session_id: {state, last_active, archived}}`; a command that cannot answer (nonzero
  exit) leaves the stored states as they are. Both verbs have a 60 s timeout; a nonzero exit, bad JSON or a missing binary records the
  session as `failed` with the error and a retry starts a new one.
- Store `<state>/dashboard/action-tackle.json` keyed by fp (the app's `TackleSession` shape: `title, session, pid, state, resolved, archived,
  started, log, surface, session_id, has_context, error, ticket, last_active, live`). `live` is launching or running, not archived, active
  within 72 hours. A start for an fp with a live session returns it.
- Routes: `GET /api/tackle`, `POST /api/tackle {fp, context, mode}`, `POST /api/tackle/resolve`, `POST /api/jira/tackle {key, context}`,
  `POST /api/pr/discuss {repo, pr, context}` (a discussion of the pull request by repository and number). Differences from the running code:
  it launched one agent's desktop chat and matched sessions by prompt in that agent's database; that is the consumer's command now.

### 12.24 The core consumption panel

`server/modules/core_consumption.py` reads only the consumption feed (`~/.config/build-standards-core/consumption.json`, or
`CORE_CONSUMPTION_FILE`; format `build-standards-consumption/1`, any other format is an error state with no rows) and turns it into the panel's
rows; the read path makes no gh call, and the result is cached 60 s. Approvals are the only writes, each a single gh call (`CORE_CONSUMPTION_GH`
names the binary): `pr ready`, `pr merge` (only when the live checks pass, by the repository's declared method, pinned to the head the owner
saw) or `issue comment` with the owner's decision text. It never pushes, never writes another app's files and never bypasses a merge gate. An
approval stays shown as done until a newer feed replaces the snapshot that still lists the item. Routes: `GET /api/core-consumption`,
`POST /api/core-consumption/approve-pr` and `approve-item`. The module needed no change beyond the formatter: it already had no estate names.

### 12.26 Documentation audit and coverage

`engine/doc_audit.py` is the daily audit (a cron script, no model call). It checks every thing of the registry (`<state>/dashboard/doc-inventory.json`)
against rules R1 to R12 and writes the durable gap store (`doc-gaps.json`); a failed run keeps the previous store and records `last_error`. One run
at a time (flock), `--report`, `--dry-run` and `--wait-lock` as before. The rules: R1 a docs home page exists (tier A live is high); R2 the
required page types under it (tier A: design, runbook, troubleshooting, release process, changelog, and a quick card when the thing has a service
desk; tier B: a runbook and a changelog); R3 a changelog per release (repository file or docs home page, held to each release after a week); R4 render
drift (repository docs changed long after the newest page); R5 review age; R6 metadata (owner, version); R7 placement under the expected parent;
R8 a machine readable release marker; R9 things in the repositories no registry entry covers; R10 agent jobs with no catalog description; R11
duplicate page titles in the configured trees; R12 shipped changes the close-out found undescribed. The store carries first seen, a generation that
bumps when a new gap opens (the key `doc-<id>-g<n>`), closed gaps and the surface slice (high and medium things, capped at 5).

The docs home is read only and is a slot: the driver in `DOCS_HOME_CMD` (the contract of `lanes/queued_approvals.py`, section 12.17) answers
`getConfluencePage` and `searchConfluenceUsingCql`; with none configured the audit fails closed. The running code imported the write guard's
session class and read another tool's token file; neither is in core. Estate specifics are `DOC_AUDIT_CONFIG` (repos, ownership page id, link prefix,
duplicate roots, close-out state, job files, discovery of directories and loose file trees, owner exclusions); every key is optional.

`server/modules/doc_coverage.py` is the Knowledge page's server half: the registry joined with the store, Snooze (7 days) and Ignore (this generation
only) in `doc-handled.json`, `open_count` for the badge (open things plus one per duplicate set), and the tackle item. Routes `GET /api/doc-coverage`,
`POST /api/doc-coverage/handle` and `/tackle`; tackle runs through the runtime slot (12.23) and answers 501 without a runtime. The running prompt's
skill names and write guard instructions were the agent's own and are not in core (`DOC_AUDIT_WIKI_URL` supplies the link prefix for the prompt).

### 12.25 Debt and improvements

`server/modules/eng_backlog.py` parses every `TD-NNN` (technical debt) and `IMP-NNN` (improvement) heading of two markdown files
(`ENGBL_TD`, default `<root>/engineering-state/technical-debt.md`; `ENGBL_IMP`, default `<root>/state/improvement-backlog.md`) into the
page's rows: bucket (decide, todo, parked, done), outcome, severity (debt), goals and effort (improvements), owner, date, body. The files stay
the source of truth. A decision (approve, park, decline, reopen for improvements; accept, resolve for debt) rewrites only that entry's
Status line in place under a file lock and keeps the old text after "Earlier:"; accepting a risk or closing debt needs a reason, and an entry
whose heading is not unique is refused. Snooze is page-only (7 days, `ENGBL_HANDLED`). Routes: `GET /api/eng-backlog`, `POST
/api/eng-backlog/decide`, `/handle` and `/tackle`. Tackle goes through the runtime slot (12.23): the entry as written and its source file
become the session's prompt, and with no runtime configured the route answers 501. Differences from the running code: the long first-person
session prompt (skills to load, message and comment rules, a resolve script path) was the agent's own and is not in core; the session's
instructions are the runtime command's.

### 12.27 Review helpers

`server/modules/live_truth.py` answers, from a short cache refreshed in a background thread, `pr_heads(repo)` (open PR number to head sha),
`run(repo, run_id)` (status, head, attempt, environments a waiting run needs) and `pr_state(repo, pr)` (state, head, in queue, auto-merge armed,
position; it reuses `lanes/merge_queue.read`). The first read of a key blocks once, later reads never wait, and a read that fails is `None`
(unknown), which never hides a card: the action endpoint re-verifies at click time. The code host binary is `LIVE_TRUTH_GH`, else `GH_BIN`, else `gh`.

`lanes/review_threads.py` takes the caller's `gh(args, timeout=60, raw=False)` runner. `read` lists unresolved review conversations on a PR,
`others` drops the owner's own (the merge queue resolves those), `notify` posts one PR comment that @-tags each author not named by an earlier
comment (automated authors are listed, never tagged; the comment carries a marker naming the head and thread ids so a second call posts nothing),
and `resolve` resolves one thread only when it is open on that PR. Every read failure raises `ThreadError`, so a caller fails closed.



### 12.35 Runtime restart card

`server/modules/runtime_restart.py` serves `GET` and `POST /api/hermes-restart` (the path the lifted app calls). The restart is never done by this server, so nothing here can take the backend down while work is running: a Python file the consumer supplies (`OPSCENTER_RUNTIME_RESTART_SCRIPT`) exposes `status()` (pending, last result, stale, busy jobs, safe), `request(mode, note, who)` for mode `now` or `idle`, and `cancel()`, and does the restart itself. The card's `alert` is `pending` when a restart is queued, `failed` when the last one failed and was not refused, and `stale` when plugins or config changed after the runtime started. With no script the card is empty (`configured` false) and a POST is 501; a script that cannot be loaded degrades to an error on the card, never an exception; an action other than now, idle or cancel is 400. The module in the handoff named one agent runtime and its script path; core names neither.

### 12.28 Review config and the privileged deployments lane

`server/modules/review_config.py` holds every estate value the review pages need in one JSON file (`OPSCENTER_REVIEWS_CONFIG`, default
`<state>/reviews-config.json`, read on every call): `owner` (the login every decision is made as), `plan_repo`, `plan_env`, `privileged_envs`
(environment to label), `typed_confirm`, `other_repo`, `core_lane_repo`, `repo_reviews`. A missing or unreadable file is the null default:
each page answers its empty state, and a write raises `NotConfigured` (status 501) naming the missing value.

`server/modules/privileged_reviews.py` reads the queue file the consumer's plan gate writes (`<state>/tf-review/privileged-queue.json`,
`TFGATE_STATE_DIR`) and the cached pending secrets list (`TFGATE_CACHE_DIR`). `decide` (approve, reject, or retry for a plan whose apply failed
after an earlier approval) re-verifies under a lock: the queued commit equals the one clicked, the typed confirm name for an environment in
`typed_confirm`, the run is still waiting on that environment at the same attempt, approvals only on `main`, and the pending deployment ids
exist. Only then does it decide the pending deployment through the code host and log the decision. An approve is refused while the run's plan
is identical to one whose apply failed (retry is the path), and an optional guard (the other-PR dependency check when the platform page is
present) can refuse it. Routes: `GET /api/privileged-reviews`, `POST /api/platform-reviews/deployment/approve`, `/reject`, `/retry` (the path
the app already calls). Nothing is decided automatically.

### 12.29 Repo reviews

`server/modules/repo_reviews.py` serves the other repos page for the repos in `repo_reviews` (review_config; none configured is an empty page).
A PR needs the owner when a check is failing (the failing job's log is read once per head and the changed files it names are listed), when it
is green and mergeable but unmerged for 30 minutes, or when the owner's review is requested; a PR a lane is working is in progress. Rows come
from the consumer's lanes through files the core already reads: `own_lane` state for the repos in `autofix_lanes` (the sentence after a fix
clears is `autofix_after`), and the core merge lane's state file (`CORE_LANE_STATE`, default under the agent home) for `core_lane_repo`, which
is ignored when absent, stale (15 minutes), failing, off or a dry run. In owner mode a PR that clears every gate is the core owner's to merge
in version order, never the owner's to act on. Open issues the owner opened or is assigned are listed by who moves next (a reply from someone
else, or quiet for `REPO_REVIEWS_ISSUE_QUIET_DAYS`, needs the owner); with no `owner` configured there are no issue rows. Routes:
`GET /api/repo-reviews` (decorated with the cron pulse when that module is present), `POST /api/repo-reviews/rerun` (re-runs the failed jobs
at the head the owner saw, refused when the PR moved on, 400 for an unlisted repo).

### 12.30 Plan reviews

`server/modules/tf_reviews.py` reads the queue the consumer's plan gate writes (`<state>/tf-review/queue.json`, `TFGATE_STATE_DIR`) and the gate's decisions log. `GET /api/tf-reviews` returns pending held PRs (with the assessment only when it is for the current head), parked holds (the owner's PR still being moved by something else, not the owner's yet) and recent decisions. `POST /api/tf-reviews/approve` and `/reject` take `{pr}`: under a lock the PR must be open at the queued head, and each run still waiting at that head has its pending plan deployment decided (the environment is `plan_env`, the repo `plan_repo`, the identity `owner`, all from review_config 12.28; a 5xx from the code host is retried three times). A run that still fails keeps the card pending and the answer names it, so a card never vanishes with a run held. The decision stores the content fingerprints of the held hits: an approval can carry from them, a rejection revokes them. The owner's approve of the owner's own PR records the one sign-off, and a reject revokes it, through the sign-off store (`lanes/signoff_store.py`, or the module named by `OPSCENTER_SIGNOFF_MODULE` offering `record`, `revoke` and `OWN`). `approve_for_signoff(pr, head)` approves a PR's waits on the same head from a sign-off elsewhere, touching only a pending card for that exact head. With no repo, environment or owner configured the page is empty and a decision is 501.

present) can refuse it. Routes: `GET /api/privileged-reviews`, `POST /api/platform-reviews/deployment/approve`, `/reject`, `/retry` (the path
the app already calls). Nothing is decided automatically.

### 12.42 PR landing facts

`lanes/pr_landing.py` builds the deterministic part of a PR approval card from facts only; a model never decides which root a merge applies. `compact_plan` reduces the PR plan run to per-root counts and a capped resource list. `landing(plan_rows, files, roots_spec)` says, per planned root and tier, whether the merge applies it: only the apply tier is applied by the merge (other tiers are applied from the branch before it), a root absent from the spec is an app root picked when the PR changed a shared module or its own folder, a root with no pipeline applier (`owner`) is never applied by the merge, and a spec'd root lands when the PR changed a path it watches (its folder plus the spec's watch list) or `deploy.json` inputs it reads. An unreadable file list is `unknown` and claims nothing; a plan that never ran is `no_plan`, one that could not be read is `plan_unread`. Each root carries its counts, the access grants and identity objects the plan changes, its applier, the gate that follows (the destroy gate when it destroys and the applier is covered) and the reason. `needs_confirm` is true when what lands destroys or changes identity objects, which is when the Approve and merge click asks for the typed name. `structure` returns the card fields for the owner's own PR (`pr_signoff`) and an engineer PR (`pr_engineer`): the ask, who asked (with the ticket from the branch or title), the rows that say why it waits on the owner, risks, what the click does, and the typed-name field. `check_prose` refuses a model brief that says a root the merge does not apply is applied. The estate values are `OPSCENTER_LANDING_CONFIG` (default `<state>/landing-config.json`, every key optional): `apply_tier` (default `prod`), `shared_modules` (path prefixes, default none), `gates` (applier to what follows; `tfapply` defaults to none), `destroy_gate` and `destroy_appliers`. No route: the approval brief page that calls it is lifted separately.

### 12.40 Plan context

`server/modules/tf_context.py` gives the approval brief (12.45) the facts it cannot get from the plan alone. Open PRs that touch the same root: the open PR list of `plan_repo` (review_config 12.28) is read in a background thread (single flight, refreshed after 120 seconds, unknown after 900, never reported as no overlap when it could not be read) and each PR's changed files are matched to a root's directory, its tier vars file and the local modules it calls, all read from origin/main of the local clone (`TF_CONTEXT_REPO`, spec path `TF_CONTEXT_SPEC`, default `.github/terraform-roots.json`, schema in 12.34); applying from main while such a PR is open undoes or pre-empts it. The plan text is parsed into resources (address, action, attributes, ids added or removed) with one plain sentence per resource, and the .tf files that declare a plan's resources tie a privileged run to the roots it really changes. Principal ids are resolved to names only through the consumer's provider (`TF_CONTEXT_PROVIDER=path/to/file.py:ClassName` with an optional `resolve_principal(id) -> {name, kind}`): the old module ran a cloud CLI session of the owner for this, which core does not, so with no provider names are unknown and the brief says so. A page GET never waits on the code host or the provider.

### 12.44 Label hold explainer

`lanes/label_hold.py` answers three things about one of the owner's PRs sitting on a hold label (default `do-not-merge`, `OPSCENTER_HOLD_LABELS` comma separated): who applied the label and when (the label event on the PR timeline, cached 10 minutes), the newest entry of the decisions log (`OPRG_DECISIONS_LOG`, default `<state>/decisions-log.md`) that names the PR and uses hold wording, and which blocking review findings the owner's triage markers (`<!-- triage:<head> H1 H2 -->`, posted after the newest review comment for that head) already answer. `triage_context` feeds the approval brief; `describe` writes the plain sentence and the next step, ASCII only and with no semicolons. The override label (`OPSCENTER_OVERRIDE_LABEL`, default `ai-review-override`) is applied only when the review verdict for the head is blocked and every blocking id is triaged. Pure helpers take their inputs as arguments; the code host runner is the caller's `gh(args, raw=False)`. Times display in `OPSCENTER_TZ` (default UTC). The server module `other_reviews` imports it optionally for the triage context. No route: it is a library the review pages call.

### 12.41 Maintenance window hold

`lanes/maintenance_hold.py` is the review pages' half of the maintenance window (the lane's half is `lanes/maintenance_window.py`, 12.2, whose window math and wording it imports so the card and the lane always agree). `need_view` says what an engineer PR's approval would do right now: nothing special, or held until the next window of its class (`standard`, `restricted`, or `both` when the systems it touches are unknown, which waits for a time both are open), with the plain reasons and the override wording. `hold` approves without enqueueing, records the hold in the held-for-window file and posts the one window comment per head (a comment with a forbidden word, a semicolon or an em dash is refused; `FORBIDDEN` is a bot, AI, assistant and co-author check the consumer extends with `OPSCENTER_COMMENT_FORBIDDEN`). `held_cards` phases each held PR against the live heads (held, in flight when new commits landed, gone when closed). `override` is the emergency merge on a held card: pinned to the held head, a reason of 8 to 300 characters required, merged through `lanes/merge_queue.enqueue`, recorded in the overrides sidecar and the decisions log as `window_override`. Everything is passed in `cfg_io` (gh, repo, log, held_path, overrides_path, verify_head, set_queue, self_login), so the module names no repo, login or path. There is no route of its own: the platform review page that calls it serves the override. The old module's change-control wording (two system classes and an emergency change request name) is the standard `standard` and `restricted` classes and a plain emergency override here.

### 12.45 Approval brief

`server/modules/approval_brief.py` writes the brief the Reviews cards show where the owner must decide: what the change does, what the click approves, and what the review raised with a recommendation, in plain prose. A card always has the deterministic draft built from its hold data; a model-written brief replaces it only when it was generated for the same head and hold signature and passes the style rules (no bullets, no banned marks, the plan counts and landing facts must agree). Generation runs in the background (at most two at a time, 240 seconds each, three attempts per head and hold with a 30 minute backoff) and never blocks a page load; the cache is `<state>/dashboard/approval-briefs.json` keyed by repo, PR and head. The prompt carries the PR description, the diff with secret-looking files withheld and inline secret values redacted, the plan job logs, the findings, the owner's triage replies and override and any branch drift. The model is the consumer's command, `APPROVAL_BRIEF_MODEL_CMD`: the prompt on stdin, a JSON reply on stdout; with none configured nothing is generated and every card keeps the draft. The repos are `plan_repo` and `other_repo` (review_config 12.28, lane keys `plan` and `other`), `APPROVAL_BRIEF_TIERS` names the deployment tiers a path can contain (default `dev,prod`), `APPROVAL_BRIEF_POLICY` is the review policy file whose rule reasons are read, and the plain sentence for a policy rule id is data (`APPROVAL_BRIEF_RULES`, default `<state>/approval-brief-rules.json`, two generic rules built in). Landing facts come from `pr_landing`, and cards for owner applies, privileged deployments and runbook releases from `card_brief` (12.42); both are optional imports, so without them a PR card has no landing facts and there are no cards of those kinds. `decorate_plan(data)` and `decorate_other(data)` attach briefs to the two pages' payloads for the server to call; the plan page module is looked up lazily as `platform_reviews` and the other repo's as `other_reviews`. Route: `POST /api/reviews/brief {repo, pr}` or `{repo, card}` starts a fresh brief (400 for an unconfigured repo, 404 for a card that asks nothing). CLI: `approval_brief.py force|show <plan|other> <pr|card id>`.

### 12.43 Card brief

`server/modules/card_brief.py` gives the cards that are not pull requests (lanes `owner` for an owner apply, `priv` for a privileged deployment paused at an environment, `release` for a runbook delete release held by a destroy guard) what a PR card has: the three paragraphs of the approval brief (12.41, which owns the store, the queue, validation and the model call), an ask line, who asked and who applies it, a table of every access grant the plan adds or removes (identity, role, what the role allows, where), a table of the other changes, why this needs the owner and the exact effect of the click. Every Terraform apply card checks the open PRs that change the same root (tf_context, 12.40): when one exists the card says plainly, from code and never from the model, that applying now would undo or pre-empt it and recommends waiting, and a model brief that fails to name every overlapping PR is rejected. The model gate holds until the overlap check is current. The auto-approve rule is described card by card: it clears a run only when every change is inert, and when it does not, the sentence names why. What is the consumer's is data in `CARD_BRIEF_DATA` (default `<state>/card-brief-data.json`, every key optional, none assumes an estate): `admin` (the account that applies owner roots), `root_why` and `root_why_default` (why no pipeline may apply a root), `env_why` (why only the owner approves an environment), `tier_plain`, `auto_rule`, `image_gate_envs` and `release_envs` (environments whose run continues an image build gate or ships a pending release rather than applying a plan), `release_target` and `release_workflow` (what a runbook release deletes from and the workflow that runs it), and `host_group_roles`, `host_resource_groups`, `host_vm_prefix` (the sign-in grants to a group on pool hosts the auto-approve rule counts as inert; none configured means it never does). Pool roll evidence is an optional module `avd_pool` (`is_roll(workflow)`, `evidence(resources, pool_roll, blocking)`): without it no card is a pool roll, and the lane keeps its `avd-pool-roll` block kind for the app. The owner is `owner` in review_config (12.28): a login equal to it reads as You. Display names of logins come from the code host through the approval brief's runner and a 24 hour cache. Nothing here reads a credential.

### 12.31 Other repo reviews

`server/modules/other_reviews.py` serves the review page of `other_repo` (review_config 12.28), shaped like the plan page. Needs the owner: an engineer PR the consumer's review lane escalated (at the head it escalated on; newer commits are in progress until the lane re-checks), the owner's own PR the own-PR lane holds only for the owner's sign-off on a policy rule (the rules are named from the policy file, `OPSCENTER_OTHER_POLICY`), the owner's own PR auto-fix gave up on (direction, no merge button), and, while the own-PR lane is not running, the owner's green PR (ready to merge). In progress: every other open PR, with what the lane is doing. Shipped: merged in 14 days. Three things only the consumer knows are slots, all optional: `OPSCENTER_ESCALATIONS_CMD` prints a JSON list of `{pr, card, reason, recommendation, status, head}` (null default: no escalations; a command that cannot be read marks Needs me rows unknown and an unverified approve re-reads it), `OPSCENTER_OWN_LANE_CMD` is the lane's `check <pr> --target <lane>` command (default `lanes/own_pr_merge.py`), and the lane target is `other_lane` (default `other`). Writes are pinned to the head the owner saw: `merge` rebase-merges the owner's own PR with the maintainer bypass (re-checked live with the lane, only a pure sign-off hold or a passing PR merges, red checks and conflicts refuse), `approve` approves an escalated engineer PR (never the owner's own), `decide_fix` records the owner's choice on a decision card. With no `other_repo` the page is empty and a write is 501. Routes: `GET /api/team-reviews` (decorated with the cron pulse), `POST /api/team-reviews/merge`, `/approve`, `/decide-fix`; the app, its hooks and its page use the neutral lane name `team` (`TeamReviews`, `useTeamReviews`, `postTeamReview`). The earlier paths with the `team_prefix` name stay served as aliases of the same handlers so an older app build keeps working. The triage context the approval brief reads (`label_hold`) is optional: without that module the row carries none.

### 12.32 Plans

`server/modules/plans.py` indexes `PLANS_DIR` (default `<state>/plans`): one tracker per project being built (`projects/<slug>/tracker.md` and that project's documents), standalone SBAR plans in `library/`, and `archive/`. Front matter is the source of every title, type, status and summary; nothing outside the folder is read or written (paths are jailed, a path outside is 403). `GET /api/plans` returns the index (no plans folder is an empty page), `GET /api/plans/file?path=` one file's text, `POST /api/plans/archive` and `/restore` move one file or a whole project into or out of `archive/` on the owner's click (a stale `version` is 409), and `POST /api/plans/create` and `/dismiss` write a skeleton tracker for an untracked ticket key or stop listing it. Freshness: each active tracker is compared with the PRs naming its tickets (by title or by the key as the start of the branch) and with its tickets' status changes; anything that landed after the tracker was last written (file time, capped at the end of its claimed updated day) marks the card behind, and an unreadable check is reported as unknown, never as fresh. The code host is read in a background thread, never on a page GET. Ticket status comes from `engine/ref_status.py` (12.13). What is estate is data: `PLANS_CONFIG` (default `<state>/plans-config.json`) holds `default_repo`, `untracked_repos` (none disables the untracked strip), `project` and `extra_prefixes` (the ticket key prefixes; none configured accepts any `ABC-123` style key) and `browse_url`; `project` and `browse_url` fall back to the tracker parameters (12.15).

### 12.33 The infrastructure page

`server/modules/infra.py` serves `GET /api/infra/{github,runners,live-jobs,job-log,spend,cron,badge}`. Three are generic code host reads: `github` (the open PRs of `INFRA_REPOS` with a per-check pass, fail and pending summary that keeps only the newest result per check, recent runs, workflows whose newest main run is red), `runners` (the registered runners of `INFRA_RUNNER_REPO`, its queued and running runs, hosted Actions minutes only when `INFRA_BILLING_USER` is set) and `live-jobs` (recent runs with per-job and per-step progress; the rate budget is 6 seconds while a run is active and 30 idle, and a completed run's jobs are cached for the process lifetime). Nothing names a repo, an account or a host; with none configured each view is empty. What lives in the consumer's own runtime is a provider slot, `OPSCENTER_INFRA_PROVIDER=path/to/file.py:ClassName`, every method optional: `spend()` (the Spend payload the page draws), `cron()` (scheduled jobs and the scheduler heartbeat age), `vm()` (the runner VM), `backup()`, `job_log(runner, lines)` (a running step's log, which the code host only serves after completion), `health()` (a list of `(level, detail)`, anything but `OK` is a problem), `fallback_active()`. A missing method answers the empty shape (spend and cron are well formed and empty; a log is 501). The provider is a file the consumer owns: no database, scheduler file or ledger of any tool is read by core. `badge` returns the Infrastructure nav badge: failing or overdue scheduled jobs, a silent scheduler, workflows red on main is not counted here, an active fallback and the provider's failed health checks (cached 10 minutes). The Spend page's account and fallback feeds are the model accounts provider (12.22); the combined `/api/badges` payload is not served by core yet.

### 12.34 Owner-applied roots

`server/modules/owner_roots.py` is the owner's apply path for Terraform roots no pipeline identity may apply (a root with `applied_by` owner in the roots spec, `OWNER_ROOTS_SPEC`, default `.github/terraform-roots.json`, read from the clone `OWNER_ROOTS_REPO`). `plan` and `plan-all` fetch origin/main into a private worktree, run `terraform plan` per root and tier and keep the saved plan file (mode 0600) with its SHA-256; a clean plan clears the card. `apply` runs only when the card is pending, the digest the owner saw equals the saved plan's digest and the file's, the worktree is still on the planned main, the owner typed the root name and the plan is under a day old; it applies exactly that file, deletes it, and always re-plans to verify (`owner_apply_started`, `_done`, `_verified` or `_unverified` in the decision log, `OWNER_ROOTS_DECISIONS`). One operation runs at a time under a file lock and workers are detached so a server restart does not kill them; a background job re-plans every root when main moves past a plan or the newest plan is two hours old. A failed apply stays on the card across re-plans with its kind and next step, and the same failure on the same main twice raises one Action Center item (and a lock-restore failure raises at once). Failure kinds are generic (locks not restored, forbidden, sign-in expired, state lock, plan changed) and a provider can add its own. Routes: `GET /api/owner-roots`, `POST /api/owner-roots/{plan,plan-all,apply,signin}`. Nothing in this module knows a cloud. The consumer's provider (`OWNER_ROOTS_PROVIDER=path/to/file.py:ClassName`, every method optional) supplies `expected_identity` and `identity()` (the signed-in account must equal it before a plan or an apply), `signin_cmd()` (the interactive prompt the Sign in button runs one at a time; on success as the expected account every root is re-planned by itself), `backend_args(tier_spec, backend)` (extra `terraform init` arguments), `before_apply(deletes, log)` and `after_apply(state, log)` (for example lift and restore resource locks around the ids the plan deletes; an error from `after_apply` fails the apply as `LOCKS NOT RESTORED` and wins over the apply result), and `error_kinds()`. With no provider there is no identity check, no sign-in, no backend arguments and no hooks. The old module's cloud locks, tenant and account names were the consumer's and are not in core: this is the one lift that needed a rewrite of its cloud parts, and the provider is where they go.

### 12.48 Sidebar badges

`server/modules/badges.py` serves `GET /api/badges`, the sidebar counts in one small payload with the same filters as each page (live-actions rule 10), so a count never disagrees with the page it points at. `action_open` is the served board's fingerprints (`OPSCENTER_SERVED_BOARD`, default `<state>/public-data/action-center.json`) that are not handled in the server's handled store, where a snooze counts only until it ends. `debt`, `links`, `builds`, `core`, `alerts` and `knowledge_docs` come from `eng_backlog`, `link_health`, `builds`, `core_consumption`, `alerts` and `doc_coverage`; `knowledge_pending` comes from an optional `curation` module offering `public()` and `knowledge` is the pending count plus the documentation gaps; `infra` is `infra.badge_problems()`. Each section is guarded on its own: a module not in the tree or a source that cannot be read is that section's zero value and never an error, except that an infrastructure check that raises shows as one problem so unknown never reads as clear. Local-host only is the server gate's rule (12.21). Nothing in the module names an estate.

### 12.46 Host pool view

`server/modules/pool_view.py` is the optional, read-only evidence on the Destroy approval card of a host pool roll (the card kind `avd-pool-roll` the app draws). A roll's delete step removes the retired session hosts, so before the owner approves the card says what the pool looks like now: every retiring host in drain mode with 0 sessions, and at least one new host Available and accepting sessions. The retiring hosts are read from the plan (VM resources deleted or replaced whose name matches `host_regex`, which names a `pool` and a `num`). Off by default: with no `roll_workflow` configured no card is a pool roll and nothing is read. The read is the consumer's command, `POOL_VIEW_CMD`, called as `<cmd> hosts <pool resource name>` and printing `{"hosts": [{name, status, allow_new_session, sessions}]}`, so a cloud session and its credentials stay the consumer's and core calls no cloud tool. Configuration is the JSON file `POOL_VIEW_CONFIG` (default `<state>/pool-view.json`) with `roll_workflow`, `pool_prefix`, `host_regex`, `subscription`, `resource_group`, `api_version` and `cmd`, each overridable by `POOL_VIEW_<KEY>`; the last three and `subscription` reach the command as `POOL_VIEW_SUBSCRIPTION`, `POOL_VIEW_RESOURCE_GROUP` and `POOL_VIEW_API_VERSION`. A read is cached for a minute, bounded by a 25 second timeout, never blocks a page GET (a cold key answers `checking` and refreshes in the background), and a failed read answers `unknown` and leaves the card as it was: it never turns into a pass. Statuses: `ok` (recommend approving), `attention` (something is missing, named), `checking`, `unknown`.

### 12.47 Platform reviews

`server/modules/platform_reviews.py` is the page that gathers every card the owner decides on for the repo `plan_repo` (review_config 12.28): the review lane's escalations, in-progress and shipped items (`<state>/platform-review/queue.json`, written by the consumer's review script and agent), held plan runs (tf_reviews 12.30), privileged deployments (12.28), owner applies (12.34), runbook delete releases and the owner's own PRs with their hold classification, sign-off, Approve and merge and the PR review verdict. Routes: `GET /api/platform-reviews` (with the approval brief and cron pulse additions when those modules are present), `POST /api/platform-reviews/{approve,request-changes,window-override,resolve-thread,triage,decide-fix,remove-hold-label,accept-risk,approve-merge,release-deletes}`; the deployment decisions are 12.28. A background tick (`thread_wait_tick`, 60 seconds) posts an approval held on open review conversations once none remain. Every write re-verifies the head the owner saw and fails closed; with no `plan_repo` or `owner` the page is empty and a write is 501.

Estate values are the `platform` object of the review config file (`OPSCENTER_REVIEWS_CONFIG`), each with a null default: `tiers` ({prod, dev} role to the consumer's tier name, default the role name), `dispatch_tiers` (tiers whose destroys the destroy workflow starts, default the prod tier), `destroy_workflow` (none: no destroy is dispatched and the card says so), `default_branch` (main), `roots_manifest_path` (`.github/terraform-roots.json`) and `app_manifest_name` (none: no app-root rule), `guard_job_regex` (default `^terraform plan \\((\\S+) ({tiers})\\)$`, the plan job that fails only on the destroy guard), `plan_environment` (none: no plan-wait logic), `privileged_label` (Privileged), `applier_texts` (applier name to a sentence, default "<applier> applies it"), `review_script_path` (the consumer's review script, called as `check <pr>` with a 180 second timeout and a 300 second cache per PR and head; none: engine checks are off and rows say the check is unavailable), `ai_review_marker`, `ai_review_data_prefix`, `ai_review_check_name` and `override_label` (none: the review verdict is not parsed and Accept the risk is off), `forbidden_text_pattern` (none: no filter on posted text) and `default_changes_text` (none: the request-changes body is required), `merge_flags` (`--rebase --admin`), `shipped_days` (14), `own_lane_every_min` (10), `assistant_name` and `operator_display_name`. Principal names in grant text come from tf_context's provider (12.40); with none the short id is shown.

The sign-off store is the consumer's to replace (`OPSCENTER_SIGNOFF_MODULE`); the contract this page needs is `record(pr, head, lane, source, hits, plan, extra=)` (extra keys also at the top of the record), `active`, `revoke`, `covers`, `review` (returning `ok`, `new`, `plan_new` and `carried`), `plan_facts` (grants, final, unverifiable, resources, destroy and replace counts) and `confirm_needed`; `lanes/signoff_store.py` is the reference implementation. The module reads no token and no private file of any tool.

### 12.50 The single problem list

The rail badge, the section and item tab counts and the Overview cards read one server-side list, `problems.collect()`, carried by `GET /api/badges` as `problems`. The client applies no threshold of its own. An item is one thing the owner runs: `{id, hub, section, item, label, tone, headline, details, count, running, url}` with `tone` one of `needs_me` (red: a pipeline whose newest finished run on main failed, a failing or overdue scheduled job or a silent scheduler, a failed health check, an active model fallback, approvals waiting), `worth_a_look` (amber: runners offline, a workflow red on main in a watched repo) or `healthy`; `details` has at most four lines; `count` is the number of problem lines the item has (two failing jobs and a stale heartbeat are 3), 0 when healthy; `running` is true while a run is in flight and is drawn as a spinner, never red. The list is `{items, counts}`, items ordered needs_me, then worth_a_look, then healthy; `counts` has `needs_me`, `worth_a_look`, `healthy` (item counts), `running`, `total`, `lines` (the sum of every count, the rail badge), `by_section` and `by_item` (key `section/item`), the last two summing the counts of items that are not healthy, so a tab count is a lookup and the tabs add up to the badge. Where an item lives is configuration, `OPSCENTER_PROBLEM_MAP` (default `<state>/problem-map.json`): `{hub, <source key>: {hub, section, item, label}}` with source keys `builds:<product>`, `jobs`, `ci`, `spend` and `core`; the defaults are the hub `operations` and the sections `builds`, `automation` and `cost`. A source that is not in the tree, or is not configured, contributes no item; one that raises is a needs_me item, never clear.

**The problems provider (slot).** `OPSCENTER_PROBLEMS_PROVIDER` (`path/to/file.py:ClassName`, null by default) lets a consumer add its own sources and live facts without changing `problems.py`; every method is optional: `headlines()` returns `{key: "live facts"}` and sets the headline of any item by its source key, healthy or not (the area cards lead with versions, runners online, spend against the projection); a headline may be a map `{headline, details, label, url}` (details and url only on a healthy item, so a problem keeps its own lines); `healthy()` adds items that are fine but have live facts to show; a needs_me or worth_a_look source may carry `count` when its lines are a summary; `running()` returns the keys with a run in flight, any item, drawn as a spinner and never red; `needs_me()` and `worth_a_look()` return `[{key, section, item, label, headline?, details, running?, url?}]` for what waits on the owner (a refused deploy waiting on a click, a run waiting on an approval) and what is worth a look (spend headroom at 70 percent or more, an account that could not be read). A source whose key is already an item adds its lines and raises its tone (never lowers it); a new key is a new item. A provider that cannot be loaded or raises is one needs_me item.

**Current state vs history.** `builds.pipeline_state(runs)` gives each feed pipeline `state`: `current` (the run in flight), `failed` (true only while the newest FINISHED run on main failed: a later green run on main clears it, a branch run never counts, cancelled is not a failure), `last_main` and `history` (the ids of every older finished run, which the card folds away so a fixed failure never reads as current). `builds.main_failure_items` and `main_failures` read it. Pipelines are ordered by latest activity (one with a run in flight on top), runs newest first.

**Infrastructure.** `infra.badge_problems()` returns `{count, items, areas, looks}`: `areas` (`jobs`, `spend`, `ci`) are the lines that need the owner, `looks` the lines worth a look, both read from the cache only so a badge never waits on the code host; `infra.configured()` says whether the page has anything to read, and an unconfigured page has no cards.

### 12.49 The run contract (start buttons)

Every runnable thing has a start button in the UI, and the server side of every one follows one contract. Writes are same-origin and loopback only (the server gate, 12.21). The form opens with safe defaults (a dry run) and says plainly when a run will publish; the server says it too (`publishes`). The button only queues the run: environment approvals still gate every job that writes.

**Workflows.** A pipeline entry in `BUILDS_CONFIG` (12.20) may carry `ref` (`main`, the default, or `branch`: main or a branch matching `branch_regex`), `paused`, and `inputs`, a fixed copy of the workflow's own inputs: `{name, type: boolean|choice|string, default, options, pattern, required, help, publishes_when}` (`publishes_when` is the value that makes a run publish: `true` or `false` for a flag, a choice value; none means the input never does). `POST /api/builds/dispatch {pipeline, ref?, inputs?}`: an unknown pipeline is 404; an unknown input name is 400 naming every one; a value that is not one line of plain ASCII, not a boolean for a boolean, not in `options`, missing when required or not matching `pattern` is 400; a ref the workflow may not run from is 400; a paused pipeline, or a run already queued, running or waiting on that ref in the cached feed, is 409 with the reason (the cache is read, never the code host, so a refusal never waits); a start with the same pipeline, ref and inputs inside `dispatch_gap_s` (20) answers `{started: false, already: true}`; otherwise the workflow runs through the code host and the answer is `{started: true, workflow, ref, inputs, publishes}`. A code host failure is 502 with its last line. The feed's pipeline entries carry the same spec as `dispatch`.

**Scheduled jobs.** `POST /api/cron-pulse/<id>/run {note?}` (12.8) runs any job of the runtime now, not only the ones that watch a card: a bad id or note is 400, an unknown job 404, a paused or finished job 409 with the reason, a job already queued or running answers `already`.

**Maintenance tasks.** `INFRA_TASKS` (default `<state>/infra-tasks.json`) lists the tasks the Infrastructure page may start: `{<name>: {label, argv, busy_argv, inputs, log}}`. `GET /api/infra/tasks` lists them with their input spec; `POST /api/infra/backup/run` or `/api/infra/tasks/run {what, inputs?}` follows the same contract (unknown task 404, input errors 400, `busy_argv` exiting 0 means running and is 409, a repeat inside the gap is `already`). The command is the consumer's and runs detached; the accepted inputs reach it as `TASK_INPUT_<NAME>` variables. None configured: nothing can start.

### 12.51 The Operations hub (layout adoption)

The app adopts the ops center layout standard (`standards/ops-center-layout.md`) in one hub, Operations, at `/operations/<section>/<item>`: builds, scheduled jobs, CI and backup, spend and the core, which were four separate pages (`/builds`, `/infra/*`, `/core`). The header is the kit's two-row `HubHeader`; the sections are Builds and releases (one item per product of the pipelines feed), Automation (scheduled jobs, CI with backup and GitHub) and Cost and standards (spend, core consumption), the problem list's default sections (12.50). The Overview is the kit's `HubOverview`: one `AreaCard` per problem-list item grouped under the same section titles in the same order. The rail badge, the section and item tab counts and the Overview all read `GET /api/badges` `problems` (`problemCount` and `operationsSections` in `pages/operations/sections.ts`); the client's own judgments are gone (the four client thresholds that were recorded as `EXC-LAYOUT-4` exceptions, the infra page's area roll-up and the stat tile tones). Builds show current state apart from history from the server's `state` (a pipeline reads failed only while its newest finished run on main failed; older runs fold under History), newest first. Every runnable thing has a start button that opens the kit's `RunDialog` with the server's fixed input spec and safe defaults (dry run on, "Run for real"): Run workflow per pipeline (`POST /api/builds/dispatch`), Run now per scheduled job (`POST /api/cron-pulse/<id>/run`) and the maintenance tasks of `GET /api/infra/tasks`; a 409 refusal shows its reason in the dialog. Old links never break: `/builds`, `/core` and `/infra/<tab>` redirect (`pages/operations/routes.ts`) keeping the query string and hash, a deep link into a hub section resolves to its first item, and `routes.lock.json` lists every route the app has served (RC024). The old Live jobs tab and the GitHub tab are part of the CI item. A test (`tests/operations.test.mjs`) follows every redirect and checks that the counts equal the server list.
### 12.52 Gate overrides and self-healing (layout rules 10 to 12)

**Override store.** `server/modules/override_store.py` is the helper behind a gate override. `OverrideStore(path, log=None, clock=None, qualify=None)`: `set(key, scope, until, who="", **extra)` turns an override on for one key (or `"*"` for all) in a scope (a freeze window id, a release, a day) until an aware datetime; `clear(key, who="")` takes it back; `allowed(key, scope)` is True only for an unexpired entry of exactly this scope for the key or for `all`, and any error, a missing file, a malformed store, a foreign scope or an expired entry is False (fail closed); `status(scope)` lists what is on. The expiry is data, compared on every read, so nothing runs to turn an override off, and a job that does is a finding (RC025). One writer under one lock with an atomic replace, every change appended to `<store>.log.jsonl`. `set(key, scope, until, who, window=None, extra=None)` also stores the id of the window the entry was made in (the scope when none is given) and a JSON map (the head it was made for, who asked), and `entry(key, scope)` reads a live entry back with the same fail-closed rule; `expires_at_local_midnight(tz)` is the expiry for "until the end of the owner's day" in an IANA zone (daylight saving included, an unknown zone is refused). `qualify(key)` is the null-default slot: it raises `OverrideRefused(msg, code)` (403 not the owner's, 409 nothing to override) so only the owner's own open work can be overridden. The gate that reads `allowed()`, the routes that call `set` and `clear` and the confirm on both controls are the consumer's; the override lifts only the one gate it names, every other check still applies.

**Pending next step (rule 11).** `override_store.pending_line(what, within_s)` is the one line a card shows after an action until the next pass replaces it ("Freeze bypassed, re-checked within 3 minutes"); a card never shows the reason the action just removed. The kit part (an override bar, a per-item override button with tag and confirm, and a pending-next-step card state) is the kit's and is not in this change.

**Transient failures (rule 12).** `owner_roots.py` re-plans at once when an apply is refused because the saved plan is stale or the worktree moved since the plan (`STALE_RE`, `_replan_after_stale`): a clean plan clears the card and closes the repeat alert, a plan with changes keeps one plain line asking for a review of the fresh plan, a stale plan never counts toward the repeat alert (`apply_failures` is cleared), and any other failure, a lock left off included, keeps the normal path. The general form is a table of known transient failures each with an automatic recovery; this is the first entry.

**Check.** RC025 (`templates/overlay/scripts/repo_checks.py`, rule 1.10) fails an ops center source in which an override or bypass reader answers yes from an error handler, or a scheduled job clears, expires or revokes an override.

### 12.56 Sessions, curation, inbound files, the CI test runner and the page renderer

**Session on it** (`server/modules/pr_sessions.py`, `working(repo, pr, branch)`). Finds a live session that is working a pull request right now, so the PR card says "session on it" and locks its buttons instead of looking idle. Signals, strongest first: a running delegated task whose goal names the PR or its branch; a live non-cron session dedicated to the PR by title (`PRSESS_TITLE_PATTERNS`, default a "Discuss ... PR #N" and an "Auto-fix <repo> PR #N" title); a live non-cron session whose recent tool calls work in the branch's worktree or push to the branch. Reading or mentioning a PR number is never working it; a finished task, a quiet, ended or cron session does not count; a number that is only the prefix of another does not match; any read error counts as nobody. Read only. Config: `PRSESS_STATE_DB`, `PRSESS_DELEG_DIR`, `PRSESS_REPO_DIRS`.

**Launch session resolver** (`server/modules/tackle_session.py`). A launch from a card binds to the session whose first user message is the staged prompt (`find_prompt_session`, `started_with_prompt`), not the session a desktop plugin reports as focused. The newest match wins, a session that only repeats the prompt later is not the launch, and nothing persisted yet is `None`. Read only on `OPSCENTER_SESSIONS_DB`.

**Curation** (`server/modules/eng_curate.py`, on `eng_backlog.py`). One front door for new debt and improvement entries (`add` scores a finding against every open entry and appends a dated update to a close match or writes a new entry with an id reserved under a lock) and one scheduled pass (`run`) that auto-closes entries whose own status says shipped or resolved, folds an entry into its clear best match (same kind and lane, a margin over the runner-up), and raises one-click hints (every cited PR merged, a retired system mentioned, stale for 60 days, an unreadable status, a duplicate open id). Every automatic action is logged and undoable, nothing is deleted. `eng_backlog.py` gained the status vocabulary (`canonical`), parent and children links for folded rows, the `fold`, `ship`, `withdraw` and `undo` acts, `resolve_id` and the locked, atomic `rewrite_status`. Estate words are configuration: `ENGBL_RETIRED_TERMS`, `ENGBL_REF_PATTERNS`, `ENGBL_PR_ALIASES`, `ENGBL_OWNER`.

**Inbound files** (`people/inbound_files.py`). Files a direct report sends (a chat attachment in a 1:1 or group chat, mail with attachments, a document share naming a report) become one Action Center item each (`file-<hash>`), harvested at pull time by the inbound gates on every message (before triage) and from the rolling feeds as a second path, kept in a durable store, medium when fresh and high after 48 hours, until the owner resolves or ignores it. Config: `INBOUND_FILES_FEEDS`, `INBOUND_FILES_TICKET_RE`, `INBOUND_FILES_TZ`, `INBOUND_FILES_SHARE_SENDERS`.

**CI test runner** (`tools/ci_tests.py`, `ci-tests.json`). Runs each test file in its own process so a module level fixture never leaks into the next, skips the files in the live-state list and prints that list on every run, and runs listed proof tests whose absence fails the run.

**Page renderer** (`engine/doc_render.py`). Repo markdown to docs home HTML (the shallowest heading becomes the top heading, code byte-exact, ASCII normalized, no prose semicolons), `stamp()` for the verified-against footer and `sanitize_check()` with configured internal terms (`DOC_RENDER_INTERNAL_TERMS`). Ordered lists render as bullets, as in the reference.

**Compared and unchanged.** The resolved card that returns when a new message lands under the same key is already in `engine/handled.py` (module and tests identical to the reference apart from wording); nothing to lift.
### 12.58 The optional reports module, parts two to five (dates, definitions, grants, preview)

All of it sits under `server/modules/reports/`, is imported only when `OPSCENTER_REPORTS` is set, and has no import side effect (12.57).

**Dates** (`dateranges.py`, R4 and R7). `parse_between("start,end")`, `whole_day_range(start, end, tz)` and `between(ts, start, end, tz)` take whole days in a named zone with the end day counted in full: the range is half open in UTC, from the local midnight of the start day to the local midnight after the end day, so a 23 or 25 hour day across a clock change is still one day. A bad range, day or zone is refused. `split_future(rows, now)` separates rows dated more than a day ahead (a device with a wrong clock) from every time panel without dropping them, a row with no readable date stays, and `future_note(count)` is the note the panel shows with the count.

**Definitions** (`definitions.py`, R2). Dashboards and reports are JSON definitions `{key, title, panels: [{title, stream, measure}]}` in a store. `seed(defaults, version)` adds a missing key, replaces an unedited copy at a lower version, and never overwrites an edited one; `reset` puts an edit back to the shipped copy; `export` and `import_` round trip a definition by key and a bad definition is refused whole.

**Grants** (`grants.py`, P1 and P4). `effective(roles, user_grants, role_grants)` is the union of every matched role and the user's own grants; reports and dashboards have separate global rights (`reports.view`, `dashboards.view`) and per-object rights named by key (`report:<key>`, `dashboard:<key>`); `GrantStore.on_delete` and `sweep` remove a grant whose object is gone, so a recreated key never inherits an old role's access.

**Preview** (`view_as.py`, P3). `ViewAs(allowed_posts).check(method, path)` refuses every write with "Preview is read-only." except a pinned allowlist of read-only query POSTs (an exact path or a `*` segment); reads always pass.
### 12.59 The workbook export (reports module R5)

`reports/export_xlsx.py` writes one workbook with the standard library only: a Summary tab and one tab per panel, each panel tab a real table (an Excel table with its header row, so it filters and sorts) whose ref matches its rows and whose column names are made unique. Text is always an inline string, so a value like `=1+1` is a text cell and never a formula (no part of the file carries a formula element). Sheet names are made valid (31 characters, none of `[]:*?/\`, unique without regard to case) and table names are unique identifiers; control characters invalid in XML are removed; numbers and booleans keep their types; the output is deterministic. Pre-built pivot tables are off: `PREBUILT_PIVOTS = False`, because hand-written pivot parts pass the Open XML schema check but crash the spreadsheet application for Mac on open. No hand-written workbook part beyond the ones here ships until a generated file has been opened in the application itself, on Mac and Windows, without a repair prompt or a crash. CSV downloads stay available through the formula guard (12.57).

### 12.65 The documentation drift feed (provider slot)

`server/modules/docs_drift.py` is report only: it never writes to the docs home or the code host. The contract (provider methods, the drift report and facts shapes, the status vocabulary, the summary shape and the cache rules) is in the module header and is the document the consumer builds against. The provider is the opt in (`OPSCENTER_DOCS_DRIFT_PROVIDER`); with none, no route exists. The tab (the page that draws the summary) is the app's and is hidden while the slot is null; this section does not add it.
### 12.67 What a consumer can rely on in this release (layout, tracker slot, extension points, jobs, Platform areas)

A consumer adopting the ops center asked five things that this design left open. Each answer is checked against the
tree of the release, not against the layout in 1.1.

**The layout in 1.1 against the tree.** Present as named: `server/app.py`, `gate.py`, `registry.py`, `live_bus.py`,
`live_watch.py`, `live_routes.py`, `modules/`, `engine/collect.py`, `engine/routing.py`, `app/`, `kit/`, `tokens/`.
Built under another name: the state and approvals stores are `server/stores.py`, the optional module switch is
`server/optional.py` with `server/modules/optional_provider.py`, the agent runtime seam is `server/runtime_slot.py`,
the tracker parameters are `tracker/params.py`, and the people parameters are `people/`. Not built, and marked so in
12.2: `server/state.py`, `envelope.py`, `swr.py` (the cache is inside each module), `writer.py`, `approvals.py`,
`heartbeats.py`, `engine/migrate.py`, `conformance.py`, `analyze.py`, `refresh.py`, `deploy/deploy.py`,
`deploy/automerge.yml`, `adopt/adopt.py`, `testing/fixtures.py`, `schemas/`, `slots/interfaces`, `slots/reference`,
`slots/null` and `local/modules.json`. A consumer follows sections 6 and 10 by the table in 12.2, not by the layout.
There is no `local/params.json` and no slot loader in this release. A parameter is an environment variable or a file
the module names, and a slot is an environment variable that holds `path/to/file.py:ClassName` (a provider) or a
command.

**The tracker slot (null by default).** The tracker routes (`/api/jira/*`, `/api/sprint-move`) are registered only
when `OPSCENTER_TRACKER` is on, the same switch as the people slot (12.14). Off, every one of them answers 404 and the
app hides the Jira rail item, its badge, its shortcut and its palette entries, and its pages show the "needs the tracker slot"
state (12.72), which replaced the redirect to the home route. A
consumer on another tracker never sees a 502 from a driver that is not there. On, the reference tracker (`tracker/`)
runs through its driver command and parameters (12.15), and a missing token or site is a real error the page shows. A
consumer on another tracker keeps the slot off and supplies its own pages through the extension point below. The
reference tracker is the only driver in this release. A second driver is a `driver_cmd` that speaks the same call
contract (12.15), not a code change in the core.

**Extension points for pages a consumer adds.** Server: a module that registers its own routes with the route registry
through the optional module switch (`server/optional.py`), each behind its own environment variable and with its own
provider (`path/to/file.py:ClassName`, every method optional, a missing one is the null default). A consumer never
edits a core file for this. App: a consumer adds a rail item and a page by describing them as data through the extension
manifest, which 12.69 defines (`OPSCENTER_EXTENSIONS_PROVIDER`), so a page no longer needs a core change. A slot UI mount
(section 5.1) is not built, and the manifest is the way a consumer reaches the rail.

**What the scheduled jobs card includes.** `server/modules/cron_pulse.py` reads the agent runtime's job file and shows
a job on a Reviews page card only when it maps to that card. A job maps in three ways: its monitor script or prompt
names a repository listed in `CRONPULSE_REPOS`, its monitor script names pull request numbers or `<ticket>-<slug>`
branches (`CRONPULSE_BRANCH_KEY` sets the ticket key pattern), or the card map file names it
(`CRONPULSE_CARD_MAP`, default `state/dashboard/cron-card-map.json`). A job with no monitor script and no listed
repository in its text is not a pull request watcher and is left out on purpose. `CRONPULSE_REPOS` defaults to the
two placeholder names `owner/primary` and `owner/secondary`, so a consumer that does not set it matches no real
repository and a job file of eleven jobs shows none. Set it to a JSON map of key to `owner/name` for every repository
whose Reviews page carries a jobs strip. A job that names nothing parseable goes in the card map with its repository
and lane. The card is a Reviews page strip and not a list of every job: the Operations scheduled jobs page lists every
job in the file.

**The Platform areas contract.** The Operations page groups what the consumer runs into areas, each with a count of
needs me, worth a look and healthy. The data is the problem list in `server/modules/problems.py`, one list that the
rail badge, the tab counts and the Overview cards all read, so they cannot disagree. An item is `{id, hub, section,
item, label, tone, headline, details, count, running, url}`. `tone` is `needs_me`, `worth_a_look` or `healthy`.
`details` has at most four lines. `count` is the number of problem lines and is 0 for a healthy item. `running` is a
run in flight and is drawn as a spinner, never red. The list also carries `counts` (needs me, worth a look, healthy,
running, total, lines, by section and by item). The core builds items for the areas it owns (pipelines, scheduled
jobs, CI and backup, spend, core approvals). A consumer adds areas or live facts without a fork through
`OPSCENTER_PROBLEMS_PROVIDER` (`path/to/file.py:ClassName`, every method optional: `headlines`, `healthy`, `running`,
`needs_me`, `worth_a_look`) and places an item by `OPSCENTER_PROBLEM_MAP` (a JSON file, default
`<state>/problem-map.json`, which sets the hub, section, item and label of each source key). The list also carries
`areas`, one row per section with a status, the counts and an owner from the problem map, and the Operations overview shows
them as a table. 12.69 defines both.

**Where the parity items live.** Issue 308 lists 24 things a consumer's running ops center has that core lacked. This is the
record of where each is in core, checked against the code in v2.22.0.

| Items | Where |
|---|---|
| 1 flat rail | A layout choice. Core groups the same destinations under Operate, People, Knowledge and Platform, each with its need me badge |
| 2 work tracking page | A layout choice. `/jira` holds the same sprint, backlog and changes content, behind the tracker slot (v2.18.0) |
| 3 Platform page | The Operations overview, with one card per area over the problem list (`problems.py`) and, above them, the areas rollup table with an owner per area (12.69, v2.22.0) |
| 4 header strip | The feed in `shell/HeaderBits.tsx` (live data line, synced chip, improvements waiting, and a warning when the Enterprise fallback is billing) and `HermesRestartBanner.tsx`, which links to the engine card on the Operations overview (v2.21.0) |
| 5 Action Center tabs | Now, Live (v2.21.0), Alerts, Completed and Routing |
| 6, 8 counters and waiting on me | The Now tab (v2.20.0). The waiting panel only links to the Reviews card, so there is no second path around the typed confirmation |
| 7, 26 active builds | The Now tab panel, the Live tab and the Operations overview, over the provider slot in 12.68 (v2.20.0, v2.21.0, v2.23.0), read only. A row can name its pull request with the failing checks and carries a plain sentence on what happened or what to do (12.68) |
| 9, 10, 11 views, columns, Routing | The Action Center and its Routing tab |
| 12, 13 Reviews | One tab per repo with a working state, the Needs me, In progress, My PRs and Recently shipped sections, the Stuck state, and the blocking, high, medium and low rollup |
| 14, 17 Debt filters, Knowledge endpoints | v2.19.0 |
| 15 1:1 cards | The shared person card with the avatar and the coverage meter, in Direct reports and Director and product owner groups |
| 16, 18, 19 Team, Plans, Links | Already in core |
| 20, 21, 23 | v2.18.0 and the 12.67 text above (layout, tracker slot, what the jobs card includes) |
| 22 extension point | The server manifest and the rail, palette and route in the app, read only (12.69, v2.22.0). A consumer adds a page as data and never edits a core file |
| 24 Platform areas contract | The problem list carries `areas` with an owner and label from the problem map, and the Operations overview draws them (12.69, v2.22.0) |

Two items are layout choices and not defects, 1 and 2. Two things are left out of core on purpose. A Stop action on a
running build is a side effect with no existing route and needs its own design under `standards/automation-safety.md`.
`POST /api/automation/approve` is a consumer contract about what approving an automation table row means.

### 12.68 The active builds feed (provider slot, read only)

`server/modules/active_builds.py` reports agent work that is running, stuck, failed or finished, for the Active builds panel on the Now tab and on the Operations overview. It is a provider slot like 12.65: the consumer supplies where sessions come from and how it knows one is alive, and the core owns the row shape, the four states, the limits and the route. The contract (provider methods, the build shape, the summary shape) is in the module header and is the document the consumer builds against. The provider is the opt in (`OPSCENTER_BUILDS_PROVIDER`), with none no route exists and the panel is hidden.

Three rules differ from 12.65 on purpose. The route is read only and closed until the provider authorises `active-builds.read`, and the module has no way to start or stop anything. Nothing is cached, because a build shown as running after it died is worse than showing nothing, so every request asks the provider again under an 8 second limit. A source that fails, is slow or returns something that is not a list is reported as an error and drawn as "I could not read the build source", never as an empty board, since nothing running and unable to tell are different answers. This is the agent work feed. The Builds tab of the Operations hub is the release pipeline, a different thing, and the counters row tile "Builds waiting" counts that pipeline.

A Stop action is held back. It is a side effect with no existing route, so it needs its own design under `standards/automation-safety.md` (live re-verification and a typed confirmation) before the panel gets a button.

A build row may carry an optional `pr` block (issue 308, item 26): `{number, url?, state?, red?}`. The number must be a positive whole number or the whole block is dropped. The state is open, merged or closed and anything else is left unset, never read as open. The failing check count `red` is a whole number from zero up to 999, and a source that sends no count leaves it unset, so the row never says "none red" for a count nobody sent. The link follows the same http or https rule as the row link. A row with no block carries `pr: null`, so a client does not have to guess, and an older source that never sends one keeps working. The row reads "Pull request open, 1 red" for an open request, and a merged or closed request reports no check count because there is nothing left to fix.

Each row also gets one plain sentence from `rowNote` in `lib/activeBuilds.ts`, from times the source really sent. A stuck row says "No output for 25 minutes, check the log before waiting longer", where the span is measured from the last output (or from the start when it never produced any) and the client holds no fixed threshold of its own, because the server already decided the row is stuck. A finished row says "Took about 59 minutes, finished 2 min ago" and a failed one "Ran about 9 minutes, failed 1 min ago". A missing start leaves out the duration, a missing end leaves out the "ago", and a span that runs backwards is no span. A running row gets no sentence. The panel has its own stylesheet, imported by the component, so it is styled on every page that mounts it.

### 12.69 Pages a consumer adds, and the Platform areas rollup (issue 308, items 22 and 24)

This section supersedes two statements in 12.67. 12.67 says a consumer cannot add a rail item or a page without a core
change, and that the problem list holds no owner field. Both are now false, and this is the contract that replaces them.

**Extension pages (item 22).** A consumer adds a page and a rail item without a core change by describing the page as data.
The core serves nothing of its own here. A module `server/modules/extensions.py` registers two read only routes when the
optional switch `OPSCENTER_EXTENSIONS_PROVIDER` (`path/to/file.py:ClassName`) is set, and with it unset there are no routes
and the rail shows nothing extra. The provider has two methods, both optional. `extensions(now)` returns the manifest, a list
of pages `{id, title, group, kind, url, lede}`, and `extension_rows(page_id, now)` returns the rows of one list page,
`{id, title, detail, state, url, at}`.

| Part | Rule |
|---|---|
| `GET /api/extensions` | `{fetched_utc, pages, truncated, error}`. At most 12 pages. 404 when no provider is set. |
| `GET /api/extensions/<id>` | `{fetched_utc, page, rows, truncated, error}`. At most 200 rows. 404 for an id the manifest does not name. 502 when the source failed, with the same body and the reason in `error`. |
| `kind` | `list` draws the rows. `link` draws one link to a tool the consumer runs and has no rows. |
| `id` | `^[a-z0-9][a-z0-9-]{0,38}[a-z0-9]$`. It cannot be a path the core serves (the list is checked against the real route table by a test), so a consumer page can never shadow `/builds`, `/people` or another core page. |
| `group` | One of the four rail groups the core has. Any other value is forced to Platform, so a consumer cannot invent a rail group. |
| Links | `http` or `https` only. Any other scheme is dropped, so a row link is never a `javascript:` address. |
| Text | Carries no markup. The client draws every field as text, so a title with markup shows as characters and runs nothing. |
| Caching | None. Every answer is fresh, so a page the consumer removed leaves the rail at once. |
| A failing source | Is an error and never an empty manifest. The rail adds no page while the source fails, and an open page shows that the source could not be read, which is not the same as nothing to show. |

The rail puts a consumer page after the core items of its group, so it never moves a core item, and it takes no keyboard
shortcut and no badge. The command palette lists it. A route for a page the manifest does not name goes to the home page,
so a removed page or a typed address never shows a broken one. The page is read only: no button, no request that changes
anything, and a test fails if one is added. The page component is a lazy chunk, so the first load budget is not spent on a
page most consumers never open.

**Platform areas (item 24).** The problem list now carries `areas`, one row per section that has an item:
`{section, label, owner, status, needs_me, worth_a_look, healthy, lines}`. `status` is the worst tone among the section's
items. The three counts are items by tone and `lines` is the same unit as every other count in the list, so the rows add up
to `counts.lines` and cannot disagree with the badge. The rows are worst first, then by section. The owner and the label come
from an optional `areas` block of the problem map, keyed by section: `{"areas": {"<section>": {"label": "...", "owner":
"..."}}}`. With no entry the label is the section name and the owner is null, because the core never invents an owner, and
the page then says "No owner named" in words and never leaves a blank. An entry for a section with no item adds no row, and a
malformed entry is ignored. Text from the map is collapsed to one line and clipped to 60 characters. A problem list that
cannot be built still carries `areas: []`, so a page can tell an empty answer from a broken one, and a server older than
this field sends no `areas` at all, which the client treats as no rollup and not as an empty one.

The Operations overview shows the rollup above the area cards, as a read only table with one row per area (status, owner,
problem lines) and a line that counts areas needing me. It is on the overview only, not on a tab, and it is a lazy chunk.

### 12.72 The rail is a parameter, and a disabled slot says so (issue 326, items 1 to 3)

This section supersedes the redirect rule in 12.14 and 12.67 ("an old link leaves for the home route"). A redirect made a disabled
page look like a broken route, so the page now says what it needs.

**The rail is a consumer parameter.** The core's default is one flat rail with no group headings, in this order and with these
labels: Action Center, Work tracking, Pull requests, Platform, Debt and improvements, 1:1s, Team, Knowledge, Plans, Links, each
with its own need-me badge (the route paths follow in 12.73). A consumer sets labels, order and flat versus grouped
with one build time variable, `VITE_NAV` (read by `app/src/lib/navLayout.ts`), a JSON object, every key optional:

| Key | Default | Meaning |
|---|---|---|
| `layout` | `flat` | `flat` is the default flat rail. `grouped` draws group headings. |
| `labels` | none | `{"/work": "Jira"}`: a label per route path. A route not named keeps the core label (the header, the palette and the shortcut sheet follow it). |
| `order` | core order | route paths, first to last. A route not named follows in core order. |
| `groups` | Today (`/action`), Deliver (`/work`, `/reviews`, `/platform`), Improve (`/debt`), People (`/people`, `/team`), Knowledge (`/knowledge`, `/plans`, `/links`) | `[{"label": "Operate", "items": ["/action"]}]`, used only by `grouped`. A page no group names (a consumer extension page) still shows, in a last group called More, and is never dropped. |

A value that does not parse, or names no known route, falls back to the default for that key, so a typo never empties the rail. A
group with no visible item (its slot is off) is not drawn. Pages a consumer adds through the extension manifest (12.69) follow the
core items of the flat rail. The slot rules are unchanged: with the people slot off the 1:1s and Team items leave the rail, with the
tracker slot off Work tracking leaves it.

**A disabled slot says so.** `/work` and its tabs show "Work tracking needs the tracker slot", and `/people`, `/team` and
`/team/:tab` show "1:1s needs the people slot" or "Team needs the people slot". The state names the switch (`OPSCENTER_TRACKER`,
`OPSCENTER_PEOPLE`) and the section that says what the consumer supplies. The address does not change. The route decision is
`show`, `wait` or `off` (`peopleRoute`, `trackerRoute`); before the first answer the page waits, and an unreachable server still shows
the page so its own error is read. What a consumer supplies to turn each page on: for Work tracking, `OPSCENTER_TRACKER` on and a
`driver_cmd` that speaks the call contract of 12.15 (the tools the Needs me, Sprint, Backlog and Changes views call); for 1:1s and
Team, `OPSCENTER_PEOPLE` and the four adapters of 12.14 (roster, calendar, meetings, message feeds), each optional with a null
default. A plain data file form that feeds these pages without a driver or provider is 12.74.

**An empty state never blanks the app.** A server with no review configuration answers the platform reviews without a `gate` or a
`policy` object, and the page read both without a guard: it threw while rendering and, with no boundary around the routed page,
blanked the whole app, so the Pull requests page and every page after it showed nothing. The page now reads both as optional (the
footer says nothing about a policy the server did not name), and the routed page sits in the kit's page error boundary keyed by the
route, so a page that throws shows a crash panel while the rail and header keep working and another page clears it. The Links page
renders from its own catalog and was blank only because the app was.

### 12.73 Work tracking is /work and Platform is /platform (issue 327)

The rail takes the reference routes. Work tracking is `/work` (with `/work/:tab` and `/work/:tab/:sprintId`) and Platform is `/platform`
(with `/platform/:section` and `/platform/:section/:item`). The old `/jira*` and `/operations*` addresses stay as redirects to the same
tab with the query string and hash kept (`lib/legacyRoutes.ts`, rule 9: an old link never breaks), and so do `/builds`, `/core`, `/infra`
and `/backlog`. `/platform` used to redirect into the platform review lane; its three lane tabs (`/platform/progress`, `/platform/mine`,
`/platform/shipped`) still do, and every other `/platform` address is the hub. `routes.lock.json` lists both the new and the old routes.
The `VITE_NAV` keys (12.72) are route paths, so a consumer names `/work` and `/platform`; the default groups use them.

### 12.74 The data file form of the tracker and people slots (issue 326, items 2 and 4)

A consumer on another tracker, or with no tracker, supplies Work tracking, 1:1s and Team as plain JSON files in the state directory
(`server/modules/data_slots.py`). It turns the slot on for the pages without a driver command and without a provider file. Read only:
no write route is registered, so approvals, ticket moves and 1:1 edits are absent (a button that needs one is not drawn or answers 404).

| Switch | Pages it turns on | Files (under `<state>/slots/`) |
|---|---|---|
| `OPSCENTER_TRACKER_FILES=1` | Work tracking: Sprint, Needs me, Backlog, Changes | `tracker/sprint.json`, `tracker/backlog.json`, `tracker/approvals.json`, `tracker/needs-me.json` |
| `OPSCENTER_PEOPLE_FILES=1` | 1:1s, and the people gate for Team | `people/board.json` |

Each file is one JSON object in the shape its page already reads (the `SprintData`, `BacklogData`, `ApprovalsData`, `NeedsMeData` and
`OneOnOneBoard` types in `app/src/lib/data.ts`; every key the page needs is also its own empty default):

| File | Keys | Notes |
|---|---|---|
| `tracker/sprint.json` | `sprint` (`{id, name, start, end, active}` or null), `me`, `items[]` (`{key, summary, status, status_category, mine, priority, points, url, ...}`) | No sprint means the Sprint tab says so. |
| `tracker/backlog.json` | `active_sprint`, `items[]` | `count` defaults to the length of `items`. |
| `tracker/approvals.json` | `pending[]`, `inflight[]` | The Changes tab rows. |
| `tracker/needs-me.json` | `items[]` (`{key, summary, status, url, question, since, days, phase, decision}`) | `phase` is `needs_me` or `closing`; `count` defaults to the number of `needs_me` rows. |
| `people/board.json` | `people[]`, `sources` | One entry per person with their topics. |

A missing file is the empty page, never a 404, because a 404 means the slot is off. A file that is not a JSON object, or whose list
key is not a list, is an error the page shows (502), never a calm empty page. `generated_utc` is the file's modification time unless the
file carries one. Closed sprints and the sprint trend are not part of this form, so those tabs stay hidden. The Team pages already read
plain datasets (`team-performance.json`, `member-profiles.json` and `history-master.json`, served as `/data/<name>`), so with the
people gate on, a consumer supplies those three files and nothing else; each is a file the reference people provider writes. The
form is the contract for a consumer that produces the files itself (a nightly export, a script). It is not a second driver: a consumer
that wants writes uses the provider and driver forms of 12.14 and 12.15.

### 12.75 Page chrome and shell pieces (issue 327, parity spec sections 2 and 3)

Every page header takes the rail icon of its page as a 40px accent chip beside the title (`icon` of the kit `PageHeader` and `HubHeader`,
`ds-head`): a 24px title, a 14px one line sub and a soft accent wash at the start edge. The icon is read from the navigation list by route
(`components/HubHeader.tsx`), so the chip and the rail never disagree. No page draws an eyebrow line (ops-center-layout rule 17); the group
is part of the header trail instead.

- **Header trail.** The header title is "<Group> / <Page> / <Tab>" (`breadcrumb`, `groupOf` in `lib/navLayout.ts`), plain text and never a link.
  The group comes from the grouped layout's groups (12.72) in every layout, the tab only when the address is one of the page's listed tabs.
- **Notice tray.** The system notices above a page (fallback model, browser window, engine restart, review gate) are the kit `Notice` row inside
  one `section.notice-tray`: a tone icon, a one line title, at most one action and a chevron that opens the detail. An empty tray takes no space.
  `AlertBanner` keeps its name and renders that row.
- **Mobile tab bar.** Under 901px a bottom bar offers Action Center, Pull requests, Work tracking and Platform (when the rail has them, with
  the consumer labels) and a Menu button that opens the rail drawer; a count is said to a screen reader as ", <n> need me". The search
  trigger is compact there.
- **Stat row.** `StatRow` (`components/StatRow.tsx`) is the row of equal tiles each page tab uses: an 81px tile with a 32px accent chip, label,
  value and optional sub line; a tile with a handler is a button that filters the page, and a zero value is muted, never coloured. Two columns
  under 901px.
- **Bundle budget.** The first load budget goes from 150 to 160 KB gzip: the kit chrome (page chip, notice row) and the tab bar load with the shell
  on every route.

### 12.76 Platform has five tabs (issue 327, parity spec section 5.4)

Platform is Overview, Releases, Automation, Host and access and Cost and standards. The section keys stay as they were (`builds`, `automation`,
`cost`, plus `host`) because the server's problem list names them, so old deep links and counts keep working; only the labels changed
(`builds` is Releases) and `host` is new. Overview opens with a three tile stat row (Needs me, Worth a look, Healthy, counted from the area
rows) and no longer holds the Hermes engine card: that is Host and access, item Hermes (`/platform/host/hermes`), and the restart banner
links there. The pairing and device screens are further items of Host and access. The Knowledge tab is labelled Doc drift, and the Team
yearly tab already carries its year.



### 12.77 Pairing and alerts on Platform, Host and access (issue 327, second comment)

`Host and access` has a Device access item (`/platform/host/device-access`) for the phone app, built on standards/hermes-api-access.md sections 5
and 6. It is a provider slot (`server/modules/phone_pairing.py`, `OPSCENTER_PHONE_PROVIDER=path/to/file.py:ClassName`, every method optional):
`status()` (five checks, each true, false or unknown), `devices()`, `pair()` (one time link), `test(id)`, `remove(id)` and `authorize(headers, action,
key)` (actions `phone.read`, `phone.pair`, `phone.test`, `phone.remove`; the null default refuses everything). With no provider there is no route and
the page shows an empty state with the setup steps (install the pinned plugin, stage the key and certificates, set the provider).

- **Pair a device.** A button asks the provider for the link and the page draws it as a QR for 60 seconds, then clears it (or on Hide now, or when the
  page goes away). The route is `POST /api/phone-access/pair`, answers `Cache-Control: no-store`, and answers 403 to any request that carries a
  forwarding header (`X-Forwarded-For`, `Forwarded`, `X-Real-IP`, `Via`): a client that reached the server through a proxy, which is what a LAN client
  looks like, never gets the link. The server keeps, logs and caches nothing of it, the page never holds it in state or in the DOM as text (the QR is a
  vector image with no text node), and it is never put in a URL.
- **Paired devices.** A list with Test notification and Remove. Each opens a confirmation first, and the server refuses either without
  `confirm: true`, so a stray request changes nothing.
- **Status.** API server reachable, edge certificate covers the host, push plugin pinned, installed plugin matches the pin, and only the API server is
  connected. An unknown check reads Unknown, never OK. A source that fails shows an error and never an empty list.
- The QR is drawn with `qrcode-generator` in a chunk loaded when the button is pressed, so it costs the first load nothing.

### 12.78 Action Center: Needs me and the stat row (issue 327, parity spec section 5.1)

The first Action Center tab is Needs me (it was Now) and the page subtitle is the reference sentence. The counters row is the reference stat
row: tiles of 81px with the label over the value, in this order: Action items, Pull requests, Work (while the tracker slot is on), Platform,
Improvements, 1:1 topics (while the people slot is on). Each is a link to the page that holds it, and a source that is off leaves its tile out
instead of showing zero. Alerts and Knowledge have their own tab and rail badge, and Builds waiting is on Platform, so none of them is a tile
any more. The reference also shows a Stuck plans tile; it needs a count of plans that stopped moving, which the core does not serve, so it is
not drawn.

### 12.79 Work tracking stat rows (issue 327, parity spec section 5.2)

The Sprint, Needs me and Backlog tabs open with the shared `StatRow` instead of the hero KPI strip, with the reference labels: Sprint has My items
(Team items in the team scope), Done with its pace, In progress, To do and Points done; Needs me has Waiting on my call, Oldest wait and Closing
now; Backlog has Backlog items, High and highest, In progress outside the sprint and Active sprint. The Mine or team scope control, the sprint
selector and the board were already as specified. Column widths of the Backlog and Changes tables follow in the table width slice.

### 12.80 Extension pages: a data-only manifest file and windows of rows (issue 326 items 7 and 9)

A consumer declares extension pages as data with `OPSCENTER_EXTENSIONS_FILE=<path>`, a JSON file `{"pages": [...], "rows": {"<page id>": [...]}}`
with the page and row shapes of 12.69, and writes no code (`extensions.FileProvider`). It is read on every request, so an edit shows at once, and
a missing or malformed file is an error the page shows, never an empty manifest. It is the same slot as `OPSCENTER_EXTENSIONS_PROVIDER`, which
wins when both are set.

A list page is no longer cut at 200 rows. The route takes `offset` and `limit` (at most 200 a window) and answers `total` (at most 5000),
`offset` and `truncated` (the rows after this window). The page shows the first window and a Show more button that loads the next, which is a
read and the only control an extension page has. Row actions, state filter tabs and the detail drawer are 12.91. Search and a row link to a local document are not built.

### 12.81 Debt lists draw one window at a time (issue 327, parity spec section 5.5)

Done holds several hundred entries, so every Debt tab draws 100 rows (`DEBT_WINDOW`, `pageDebtRows` in `lib/debtFilters.ts`) and a "Show 100 more (n left)"
button grows the window. The window starts over when the tab, the kind or any filter changes. A text search spans the whole list and shows
every match, so a search never hides a hit behind the window. The Kind filter of 12.76's neighbour (`Kind` select) duplicates the All, Tech debt
and Improvements segmented control above it; both stay because the segmented control is the reference and the select keeps an old link working.

### 12.82 Alerts and Completed stat rows, and the shell values checked (issue 327, parity spec sections 2 and 5.1)

Alerts opens with Need ack, Reports, Failing now and Jobs watched, and Completed with Completed, Last 7 days, Critical or high and Via Hermes, in the shared
`StatRow` (the Acknowledged tile is gone, the Acknowledged view of the segmented control holds that list). The Alerts and Completed segmented views and
the Links status line already matched. Shell values were measured in a real browser at 1314 by 998 against section 2: rail 58px collapsed on the surface-1
background, items 41 by 38 at 14px and weight 600, version pill 25 by 18 at 9px, hub strip padding 12px 24px 0, presenter 56px, header 54px, search
button 32px: all equal to the spec, and the rail pin, the glider and the version pill are kit parts already in the shell, so no shell code changed. The
ent-chip ("Enterprise on, n h n min left") needs the end time of an Enterprise window, which the core does not serve, so it is not drawn.

### 12.83 Team stat rows (issue 327, parity spec section 5.7)

This cycle (per person: completion with done of assigned, Points delivered, High and highest, Open with its carryover), Member reviews (Datapoints drawn on,
Months on record, Trajectory) and Yearly review (Work items completed, High priority closed, Median turnaround, Long-standing cleared, Open now, Items raised)
open with the shared `StatRow`. Their labels already matched the spec except High and highest. The Knowledge tabs carry no stat row in the spec and keep
theirs (the Docs drift tab's own tiles).

### 12.84 Pull requests grants table and the Live tab control (issue 327, parity spec sections 5.1 and 5.3)

The per-repo Pull requests tabs (a working dot and a count per repo, Needs me, In progress, My PRs, Recently shipped) already matched. The why table of an approval
brief (Kind, What, Severity, Where) takes the reference column widths (9, 42, 11 and 38 percent) and upper case headers. The Live tab opens with the Work by state
control: Needs me (failed builds), Running (running builds and sessions), Waiting (sessions still opening), Stuck and Just finished (finished builds), each with its
count, opening on the first state that has rows. The tab badge still counts only what is acting. The reference Lane select and its Engineer PRs and Scheduled jobs
sections need a repo lane on each row, which neither feed carries, so they are not drawn.

### 12.85 The Enterprise chip in the header (issue 327, parity spec section 2.2)

While a fallback watch incident is open (`GET /api/llm-fallback`), the header carries a warning chip between the sync chip and the theme
toggle: "Enterprise on, 0 h 41 min left" on a wide header and "Ent on" on a narrow one, opening LLM spend. The time left counts to `closes_utc`, which the server adds to
the open incident (one quiet period after the last leak call, the moment the watch closes it by itself), so the client holds no threshold. A missing or past
close time leaves out the time left rather than guessing. No incident draws no chip.

### 12.86 Table column widths (issue 327, parity spec section 4 and 5)

The Action table, the Backlog, Debt, Doc history and the Team throughput tables already carried the spec widths. This adds the rest the spec measures: Scheduled jobs
(Type 117, Schedule 133, Last run 88, Next 78, Logs 7d 86, Health 103, the Job column takes the rest), the Team run ledger (Period 152, Sprints 208, Engineer 201,
Completion 153, Pts deliv. 133, Done 101, Carry 103, Intake 110), the sprint throughput (Sprint 223, Done 188, Points 216) and the Routing Considered table
(Input 42 percent, What happened 58 percent, the reference 488 and 674 pixels at the capture width). Widths the spec gives for the Changes and Doc coverage tables are
not set: their tables are drawn by consumer data shapes that vary, and a fixed width there would clip the longer text.

### 12.87 The Auto-curated line on Debt, and no eyebrows (issues 326 item 6 and 327)

Debt and improvements shows "Auto-curated this week: N" in its header, N being how many entries the curate job changed on its own in the last 7 days, counted from the job's own
log (`GET /api/eng-backlog/curation`, `auto_week_count`, the whole week and not the 30 rows `auto_week` lists). A server without the route draws no line. The subtitle is the
reference sentence. No hub page passes an eyebrow any more (ops-center-layout rule 17): the header trail carries the group.

### 12.88 The status filter on My PRs (issue 326 item 5)

My PRs opens with a Status control: All, Needs you, In progress, Waiting, Stuck and Ready, each with its count. A row's state is the one `platformPrState` already gives
(every branch reads a field the server set), so Stuck is the lane's own answer that nothing will move the PR on its own (a draft with no gate to clear, an auto-fix that
gave up), and the client adds no age threshold of its own. The findings rollup per PR (blocking, high, medium and low counts) was already on each card.

### 12.89 A lane on active builds, and the Live tab Lane select (issue 327)

An active builds row may carry `lane` (up to 40 characters, the repo lane or area the work belongs to); absent is null and is never guessed. The Live tab then shows a Lane select
beside the Work by state control (only when some row names a lane) and lists the chosen state as titled sections: Engineer PRs (builds that carry a pull request), Scheduled
jobs (builds without one) and Sessions. A source that names no lane gets no select and the same sections.

### 12.90 The Stuck plans tile (issue 327)

The Plans feed counts open plans that stopped moving: an active project whose newest file has not changed for the stuck limit, and an in-progress library plan the same way (`counts.stuck`,
`stuck` on each row). The limit is `OPSCENTER_PLAN_STUCK_DAYS` (default 14), decided on the server like every other threshold (ops-center-layout rule 4). A done, parked or proposed plan is
waiting by design and is never stuck. The Action Center row shows Stuck plans between Platform and Improvements while the feed answers with a count, linking to Plans.

### 12.91 Extension rows: actions, state tabs and the detail drawer (issues 326 item 8 and 327)

A row may declare up to four `actions` (`{id, label, confirm?}`) and up to twelve `fields` (`{label, value}`). Rows that carry two or more distinct `state` values get a State control
(All and each state with its count). A row with fields or actions has a Details button that opens a drawer with its detail, its fields and one button per action. An action runs only
after a kit confirmation (the action's `confirm` text), by `POST /api/extensions/<id>/action` with `{row, action, confirm: true}`. The server refuses it without `confirm: true`, refuses an
action the row itself does not declare (404, searched through every window of rows), and asks the provider's `authorize(headers, "extensions.act", key)`, separate from `extensions.read`
(the null default refuses). The provider's optional `extension_action(page_id, row_id, action_id) -> {ok, detail?}` does the work; a provider without it answers 501. The data-only
file form (12.80) records a decision instead of running anything (12.106). The browser only ever sees the declared menu, never the provider.

### 12.92 Document backed plan library entries (cutover comment item 11)

The plan library reads markdown, and a consumer whose plans are word processor documents or wiki pages can still list them: `library/<name>.link.json` is
`{"title": ..., "url": ..., "status"?, "summary"?, "owner"?, "updated"?}` (a library folder file, or its archive twin; never inside a project). The row shows the title, the
status, a Document pill and the summary, and opens the url in a new tab (http or https only), or the document on this machine when the file names a `path` instead of a url (12.106). Nothing of the document is read here, so the row has no preview and no Archive.
A file that does not parse, has no title or carries another kind of url is left out, never drawn half. The plan counts include these entries.

### 12.106 Local documents: one safe route, row links, plan entries and decisions on a data-only page (issue 376 items 2 and 9)

A consumer whose documents sit on the machine (word processor files, archived briefings, pdf) names the folders they live in with `OPSCENTER_DOCUMENT_ROOTS` (several, separated by the platform path separator, at most eight). Unset, the feature is off: no route exists and a path is never turned into a link. This is the only way a local file reaches the browser, and it is the same rule for every caller, so a page row and a plan entry cannot differ in what they allow.

`GET /api/documents/file?root=<n>&path=<relative path>` serves one file, read only. The address holds a root number and a path under it, never an absolute path, so the browser never learns where a root lives. Every request is checked again from nothing: the real path (links followed) must be inside the named root, no part of the path under the root may start with a dot, and the file must be a regular file of an allowed type, at most 50 MB. A `..`, an absolute path, a link that points out of the root, a hidden file or folder, a missing file and a root number that is not there all answer 404. A root that is not a number answers 400. The allowed types are pdf, txt, md, csv and the Word, Excel and PowerPoint formats (docx, xlsx, pptx, doc, xls, ppt). Pdf and the plain text types are shown in the browser (text is sent as `text/plain`), every other type is sent as a download, and html, svg and script types are not on the list, so a document can never run in the ops center's own origin. The client draws such an address as a link only in the exact shape the server makes (`safeHref`), so a row cannot smuggle any other address in.

A page row may carry `doc`, a path relative to a root or absolute inside one. The row then links to the document when the file is there and allowed. A named document that is not there or not allowed leaves the row with no link and `doc: "missing"`, and the page says Document not available beside the title. A row without `doc` keeps the shape it always had, and `url` wins when both are given. A library entry (`library/<name>.link.json`, 12.92) may carry `path` instead of `url` on the same rule, and an entry whose path is not allowed is left out like any other bad entry. Pdf and text open as a preview in the browser tab, the Office types download, and no conversion happens.

A row may also carry `links`, up to 20 entries of `{label, url or doc}`, for the other documents that belong to it (the earlier dated versions of a briefing, for example). Each entry is checked by the same rules as the row's own link: `url` must be http or https and `doc` must resolve inside a document root, and an entry that fails, has no label or comes after the twentieth is dropped and counted in `links_missing`. The detail drawer lists the surviving links in the order the writer gave them and says how many were not available, and the client draws an address only when `safeHref` accepts it. A row that declares no `links` has neither key. This is what lets a briefing archive be a data-only page with no core screen (the design in `opscenter/plans/plan-page.md`): one row per document, the latest version as the row's own link, the earlier ones as `links`, written by the consumer's one manifest writer.

The drawer is rendered by a browser test (`ocTabs.test.mjs`, a row with earlier versions): the links in the written order with `target=_blank` and `rel="noopener noreferrer"`, the script address never in the page, the count line (the server's dropped count plus any the client refused), a links only row getting the Details button, the "Document not available" label beside a row whose document is missing, and an axe scan in both themes taken after the drawer's opening animation has finished.

A data-only page (12.80) can now declare row `actions`. With no provider code there is nothing for an action to run, so it records a decision: `<manifest file>.decisions.json` holds, per page and row, the action, its label, the `state` the action declares (the row's pill afterwards, default the label) and a UTC time. A later decision on the same row replaces the earlier one, the row's detail drawer shows a Decision field, and the manifest file itself is never written. The same confirmation, declared-action and authorisation rules apply as for a provider page, and an action the row does not declare records nothing. This covers an Accept, Reject or Defer list. It does not run commands, call a service or change another file, and a consumer that needs that supplies a provider with `extension_action` (12.91).

What this does not do: it does not list a folder, search documents, convert them, or write to a root. `OPSCENTER_DOCUMENT_ROOTS` has no default and is not under the state dir, so a consumer that moves the state tree sets it on its own (it is listed in `SETTINGS.md`, 12.104).

### 12.93 The consumer upgrade step (cutover comment, delivery path)

`tools/upgrade.py` is the documented upgrade step a nightly sync runs after it pulls a release: build the app, then `python3 opscenter/tools/upgrade.py --target <service dir>
--restart-cmd "<restart the service>" --smoke-url http://127.0.0.1:<port>/api/health`. It stages a copy of the opscenter folder (the built `app/dist`, the server and the python
modules; build sources, `node_modules`, caches and tests left out) beside the target, swaps it in keeping the replaced copy as `opscenter.prev`, restarts, and polls the smoke url
until it answers 200 with JSON. A failed restart or smoke check puts the previous copy back, restarts again and exits 1, so nothing is left half swapped; exit 2 means there was no built
app to copy. `--dry-run` stages, counts and removes the staging copy. The restart command is the operator's own and is run as given.

A smoke url proves one thing, that something answers, and a server that started with a module that failed to load answers too. `--base-url http://127.0.0.1:<port>` runs the full check instead: `GET /api/health` answers 200 with JSON, `GET /api/routes` reports at least `--min-routes` routes (default 1, a consumer sets the number its own server registers, and a module that failed to load shows as a lower count), and `GET /` renders the page (HTML that holds the app root element) with every `/assets/` file it names answering 200. The checks are polled until `--timeout` and the last failure is printed, so a slow start is waited for and a failure says which check failed. A failed check rolls back exactly as a failed restart does. `GET /api/routes` is a new read only route that returns `{"count": <number of registered routes>}` and nothing else, so `/api/health` keeps its shape.

A launch agent on macOS cannot read the Documents, Desktop or Downloads folder, and a synced Documents folder is a link to another place, so the tool resolves both paths before it compares them. When `--target` is inside one of them it exits 2 before it changes anything and says why, and `--allow-protected` goes on for a service that has been granted that access. This covers the service location the tool writes. It cannot test what the service reads at run time, because the tool runs as the operator and not as the launch agent: state, plans and document paths the service reads must also sit outside those folders (or the service be granted access), and the consumer sets them from the settings table.

### 12.94 Rail badges for consumer pages, and when the Stop action is designed (issue 326 items 10 and 12)

A consumer page may carry `count` (a whole number from 0 to 999; anything else is dropped), and the rail shows it as the badge beside the page; zero draws none. Ordering inside a group
is the order the consumer declared (12.69), which a consumer already controls, and a route outside `extensions/` stays out on purpose: an extension page never shadows a core address
(`RESERVED_IDS`), so the page prefix is the contract.

The Stop action on a running build is still held back, and this says how it will be built so a consumer knows what to expect. It is a write with a side effect, so it follows
standards/automation-safety.md: a provider method `stop_build(id)` behind its own authorisation `active-builds.stop` (the read route's `active-builds.read` never grants it), a live
re-read of the build at click time that refuses anything that is no longer running, a typed confirmation of the build's title, one audit line per stop, and no Stop on a build the source did
not mark stoppable. It lands as its own pull request when the provider contract is agreed; until then the Live tab and the Active builds panel stay read only.

### 12.95 The item bound build loop: claim token, report, bind, prompt and one launch at a time (cutover comment capability 1)

The runtime slot (`server/runtime_slot.py`, `OPSCENTER_RUNTIME_CMD`) already started a session for an item and resolved it. It now carries the rest of the loop the cutover comment asked for.

- **Claim token.** Every start makes a random claim token, tells it to the session in its prompt and keeps only its SHA-256 in the store (`claim_hash`, which never leaves the server). `POST /api/tackle/resolve` and
  `POST /api/tackle/report` need that token (compared in constant time) or `owner: true`, which only the app sends, so a session can resolve and report only the item it was started for (403 otherwise).
- **Report.** `POST /api/tackle/report {fp, text, claim, pct?}` keeps the session's last five progress lines (`reports`, newest first, text cut at 300 characters, `pct` only when a whole number 0 to 100). The Live tab shows the newest as a note on the session row.
- **Bind.** `POST /api/tackle/bind {fp, session_id, surface?}` attaches a session the runtime opened on its own (a desktop session the owner started from the item) to the item; the row becomes running.
- **Prompt.** `POST /api/tackle/prompt {fp, text}` sends the owner's line into a live session through the runtime's optional `prompt` verb (`prompt '<json>'` in `{fp, session_id, text}`, out `{}`); a runtime without it, or a failing one, answers 501, and a session that is not live answers 404.
- **One launch at a time.** A start waits up to `OPSCENTER_LAUNCH_HOLD_S` (default 90 seconds) for the launch in flight, then answers 429 and starts nothing, so two clicks never open two sessions.

Resolving with the archive of the chat scheduled after is the runtime's to do on the resolve it receives; the core does not see the chat.

### 12.96 Change approvals with a live write switch (cutover comment capability 2)

The Changes tab lists the changes waiting on the owner (12.15). It now also lets the owner approve or decline one (`server/modules/change_approvals.py`). The core owns the decision
log (`<state>/dashboard/change-approvals.json`, the last 200 decisions) and the switch; the consumer owns the write, as `OPSCENTER_APPROVALS_CMD` (`decide '<json {key, decision, note}>'` printing
`{ok, detail?}`). **The switch starts off and a decision is then only logged as a dry run** ("would approve CHG-12"), which calls nothing. `POST /api/approvals/switch {live, confirm: true}` turns writes
on, and refuses (409) when no command is configured. With the switch on, a decision (`POST /api/approvals/decide {key, decision, note?, confirm: true}`, a key like ABC-123, approve or decline) first asks
the tracker, when it is on, whether the change still waits on the owner and refuses (409) when it does not or the tracker cannot be read, so a change decided elsewhere is never decided twice; then it
runs the command and logs the result, with a failed command logged as not ok and never as done. Every write needs `confirm: true`, and the page asks a confirmation that says whether the click is live or a
dry run. `GET /api/approvals/queue` gives `{live, can_go_live, decisions}` for the switch and the five most recent decisions under the table.

### 12.97 The document pipeline (cutover comment capability 3)

A provider slot (`server/modules/doc_pipeline.py`, `OPSCENTER_DOCS_PIPELINE_PROVIDER=path/to/file.py:ClassName`, every method optional) for documents that need writing. The consumer supplies the queue (exports,
merged pull requests, meetings, knowledge gaps, each with a plain `source`), the drafting, the preview text and the library write; the core owns the states, the transitions and the guard. States: queued, drafted,
suggested, approved, rejected, published, kept in `<state>/dashboard/doc-pipeline.json` with a short history per document.

- **Draft and preview.** Draft asks the provider for a draft and its version (the version changes whenever the text does); the Knowledge Documents tab shows the text as a Word-style page.
- **Suggest changes in place.** A suggestion on a drafted or approved document is recorded, forwarded to the drafter when it has a `suggest` method, and drops any approval.
- **Decide.** Approve or reject needs `confirm: true` and the version the owner read; a draft that changed since answers 409.
- **Restore.** A rejected or published document goes back to drafted, with a confirmation.
- **Guarded publish.** Publish needs `confirm: true`, an approved state and the approved version, then re-reads the draft and refuses (409) when its version moved on after the approval; only then does it call the provider's
  `publish`. Nothing else in the core reaches the library. A new draft of an approved document drops the approval.

Authorisation is the provider's `authorize(headers, action, key)` with `docs.read` and `docs.write` (the null default refuses all). With no provider there is no route and the Documents tab is hidden. A queue that cannot be
read is an error the tab shows, never an empty queue.

### 12.98 The freeze strip and go-live notices (cutover comment capability 8)

The header already shows the change freeze from `change-freeze.json` (the change system's windows, mirrored by the consumer): red inside a window, amber inside seven days. A window may now carry `kind: "go-live"`.
`freeze_status` (`engine/board_build.py`) keeps such a window out of `in_freeze`, `current` and `next` and lists the current and upcoming ones as `go_live` (at most five, with `days_out`) in `freeze.json`. The header
shows the nearest one as an info notice, "Go-live in 2 days: <name>. For awareness. This is not a change freeze.", beside the freeze status and never as a freeze: a go-live never turns the strip red and never blocks
the freeze gate. Windows with no kind are freezes as before.

### 12.99 Backlog writes behind the tracker slot (cutover comment capability 7)

The tracker slot's write form (the reference tracker, 12.15; not the data file form of 12.74, which is read only) gains two writes on the owner's own items, both with `what_if` and a read back before they report:

- `POST /api/jira/issue {summary, class, description?, priority?}` creates one item in the configured project, assigned to the owner. `class` is `planned`, `bau` or `unplanned`: the BAU and unplanned defaults are labels set by the
  tracker parameters `bau_label` and `unplanned_label` (default BAU and Unplanned), the issue type by `issue_type` (default Task). A missing project is a 409, a bad class or an empty summary a 400, and an item whose summary does not read back is an error.
  The Backlog tab has an Add an item form.
- `POST /api/jira/issue/update {key, summary?, priority?, description?}` changes one of the owner's own items (403 for anyone else's, 400 for nothing to change).

**Complete is not a new route.** Closing an item already has a process: the sprint close-out asks the owner (needs me), the owner decides and the close-out writes the closure comment and the transition (12.15, `transition` refuses done targets).
A second way to close from the backlog would bypass that comment, so completing stays on the existing path; this is recorded as the default on issue 327.

### 12.100 Drafts: archive, restore and threaded reply drafts, never sent (cutover comment capability 5)

A provider slot (`server/modules/drafts.py`, `OPSCENTER_DRAFTS_PROVIDER=path/to/file.py:ClassName`, every method optional) for the drafts the owner keeps in a mailbox. The provider lists them (`drafts()`),
archives and restores one, and creates a reply draft threaded under a conversation (`reply(thread, text)`, which makes a draft in the mailbox and sends nothing). **The core has no send route and no delete route**: a draft can be archived
and brought back and nothing more, and `drafts_test.py` asserts the route table and that the module has no send or delete call. Every write needs `confirm: true` and the provider's `drafts.write` authorisation (`drafts.read` for the
list; the null default refuses all). The Action Center has a Drafts tab (the old `/action/drafts` address leaves for the home tab when there is no provider) with Archive, Restore and a show archived toggle, each behind a confirmation.
A source that cannot be read is an error the tab shows, never an empty list.

### 12.101 Status files and freshness; what else of capability 9 the core already has (cutover comment capability 9)

`GET /api/status-files` (`server/modules/status_files.py`) lists the `*.json` files directly inside the dashboard dataset folder with name, size, last write time and age, oldest first, and the server decides which are stale
(`OPSCENTER_STATUS_FRESH_MIN`, default 1440 minutes, a bad value falls back): ops-center-layout rule 4, the client holds no threshold. It never reads a file's contents, skips dot files, folders and symlinks, and lists at most 200.
Platform, Host and access has a Status files item with a fresh and stale stat row and the table. The rest of the capability is already in the core and is recorded here so a consumer does not look for it twice: **search** across action
items, sessions, 1:1 topics, state files and Jira is the Search page (`/search`, `ops_search.py`); **plan limits** and **spend** are Platform, Cost and standards, LLM spend; **runner pool health** is the host pool view on the Destroy
approval card and Platform, Automation (`desktop_pool.py`, `pool_view.py`), and **CI runner capacity** is Platform, Infrastructure, CI and backup (`/api/infra/runners`: runners online of the total, runners busy, jobs queued, the running and queued jobs, and hosted minutes used against the minutes included); the **core consumption view** (version and drift) is Platform, Cost and standards, Core.

### 12.102 Collectors and the analyzer: meetings, priority sender rules, and what stays the consumer's (cutover comment capability 10)

The collector (`engine/collect.py`) already reads mail, chat, the tracker snapshot, the state files and the documentation gaps with no model, routes every candidate by data (`ac-routing.json`) and hands the analyzer only what belongs
on the board; the analyzer is cost gated by the wake gate (a bundle whose content hash is unchanged does not wake it, 12.9 and `analysis_bundle.py`). This adds the two parts that were missing.

- **Meetings, without a model.** `from_meetings` reads `meetings_feed` (default `<agent home>/feeds/meetings.json`, `{"items": [{id, subject, start, organizer, attendees, summary, action_items: [{owner, text}], web_link}]}`, written
  by the consumer's own meeting collector) and makes one candidate per meeting that has a summary or an action item, source `meetings.transcript` (register it in `ac-routing.json` like any source: until then it is reported as
  unregistered, never silently routed). An action item that names the owner reads as addressed to the owner (direct); a meeting whose actions are all for others is context (none). Only the summary and the extracted action lines
  go in; the transcript's own words never do. The meeting digest is this: one candidate per meeting, which the analyzer folds into an item like any other.
- **Priority sender rules.** The routing file may carry `priority_floor: {"roles": {"leader": "high"}, "senders": {"Name": "critical"}}` (the contract priorities; a role or lower cased sender name picks the least priority). A candidate from
  such a sender gets `priority_floor` in the bundle, and `contract.validate(..., floors)` refuses an item that covers it below the floor (`floors_of(bundle)` builds the map; the wake gate saves it as `floors` beside `must_cids`, and
  `wake_floors_for` reads it under the same rule as the cids: only for the run that wrote the file; with no floors saved the check is skipped and says so, never guessed). So "a director or a manager is at least P1" is a rule in data, set by the
  consumer's own word for P1, with no client threshold.

What stays the consumer's, by the posted default: auth heal and heartbeat sync (scripts of the consumer's own sign-in and scheduler), and the collectors that talk to its mail, chat and calendar services, which write the feeds above.

### 12.104 One table of every setting (issue 376 item 8)

`opscenter/SETTINGS.md` lists every environment variable the ops center code reads: 343 at the time of writing, with the default as written in the code, whether that default sits under the state dir, and the files that read it. It is generated, never edited. `python3 opscenter/tools/settings_inventory.py --write` rewrites it and `--check` fails when it is stale, and the unit test `settings_inventory_test.py` runs the same comparison, so a setting added without regenerating the table fails the build. The scan reads the source with the syntax tree (`os.environ.get`, `os.environ[...]`, `os.getenv`, the provider loader, the switch reader and the binary finder), so a variable named only in a comment is not counted and a variable built from a string is not found (none is built that way today).

The "Under the state dir" column answers the question a consumer asks when it moves the state tree: yes means the default follows `OPSCENTER_STATE_DIR` (or the dashboard folder inside it), "no, a path" means the default is built from the root, a home or a literal path and the consumer sets it when it uses that feature, and a dash means the value is not a path.

Several defaults sit under the root and not under the state dir (the improvement digest and its handled and curation files, the automation actions store, and the lane state folder `OPSCENTER_LANE_STATE_DIR` among them), so moving `OPSCENTER_STATE_DIR` alone does not move them. This section records that and changes no behaviour: the table marks each of them "no, a path", and a consumer that moves the state dir sets those variables too. Making them follow the state dir is a separate change, because tests that set only the root would then pick up a state dir left by an earlier test.

### 12.103 Ignore a whole thread (capability 6), and what the core already does for capabilities 4 and 6 (cutover comment)

**Ignore always by whole thread.** A routing rule may match `thread`, the exact conversation id of a mail conversation or a chat (case-insensitive), and the collector now puts `thread` on its candidates: a mail conversation id, `chat:<chat id>`
for a chat, `channel:<id>` for a channel thread. A rule `{match: {thread: "chat:abc"}, route: "nowhere"}` therefore drops every message of that thread, now and later, not only the one clicked. The rule is data in `ac-routing.json`, so Restore is
deleting or disabling the rule, and the Routing tab's Rules view lists who made it and when. A candidate with no thread never matches a thread rule.

**Awareness.** The rest of the Awareness capability is the routing model that was already here: the routes are `action_center` (must be considered), `analysis` (context the analyzer may fold in, which is where an unsure item goes: it is
never a board item on its own), `elsewhere` and `nowhere`; Ignore, Ignore always, Snooze and Restore are click rules inserted at the top so a newer call wins; and the Dismissed view lists each handled item with the act, when and by whom
(`via`), keyed by fingerprint (`action-handled.json`).

**Ideas (capability 4).** Debt and improvements already decides ideas: an improvement in Needs decision is approved, parked or declined, reopened, shipped or withdrawn (`ACTS` in `eng_backlog.py`, each stored in the entry's Status line and undoable), and
Approve and tackle sends it to a build through the runtime slot (12.95). The digest the ideas come from is configurable (`ENGBL_IMP` and `ENGBL_TD` name the files). The consumer's accept, reject and defer are approve, decline and park.

### 12.105 A column parity test for the spec tables (issue 376 item 10)

Two tests share one spec. `opscenter/app/tests/tableSpec.mjs` holds the column list of each table the parity spec (issue 327, section 5) describes, as data. `tableColumns.test.mjs` reads the column arrays and the heading cells from the page source, so it needs no browser and runs in `npm test`. `renderedTables.test.mjs` renders the built app in the shared headless browser against a small fake `/api` and fake `data/` files, then reads what the page drew: the heading cells in order, the width each column declares, and the width the browser gave it. It runs with the other browser tests (`npm run test:browser`, which `browser.test.mjs` collects) and needs `npm run build` first.

A rendered width is checked the way the browser lays a table out. A flexible column declares no width. A px column in a table that has a flexible column is drawn at exactly that width (2 px of rounding allowed). A table of only px columns is stretched to fill its card, every column by the same factor, so each is checked against its spec width times that factor. A percent column is checked as that share of the table. Each page entry in the test names the route and the fake data it needs, a missing entry fails, and an entry for a table that left the spec fails.

The rendered test covers the Action Center table, Routing considered, Backlog (which draws two tables with these columns), the three Spend tables, Debt and improvements, and the three Team tables. It does not cover the Reviews grants table, the heading only entry that needs a pull request brief to draw, nor the `DRIFT` tables below. Those two are read from the source only.

Two lists. `SPEC` is the tables that match today: the Action Center table, Routing considered, Backlog, the three Spend tables, Debt and improvements, the two Team tables, the run ledger and the Reviews grants table. For each, the headings, their order and every declared width must equal the spec, so a renamed heading, a moved column or a changed width fails. `DRIFT` is the spec tables the app does not match yet, each with the reason: Scheduled jobs (an extra unlabelled action column after Health), Changes (no Type and status column, the last column is labelled Actions) and the workflow runs table (the first heading reads When (UTC)). The test fails when a `DRIFT` table starts to match, so the entry must move to `SPEC` and the list cannot go stale. A consumer that changes a table on purpose edits the list in the same pull request.

### 12.71 Two test rules: wait for transitions, and run a class alone

Two defects in the core's own tests showed up while building 12.70. Neither was a product bug, and each is now a rule the tests enforce.

**A scan waits for transitions, it does not sleep.** The theme flip starts colour transitions (the header chip has a 120 ms one), and axe reads whatever colour the element has at that instant. A settled light chip measures 5.67 to 1 and a dark one 6.79 to 1, against 4.5, but halfway through the flip the text is a blend of both themes and measures between 1.4 and 3.7. The old helper flipped the theme and slept a guessed 400 ms, so a slow runner could scan mid blend and report a contrast failure on a component that was fine. The tests now call one step, `SETTLED_JS`, that resolves true once no `CSSTransition` is running (two animation frames apart, so a transition that starts late is seen) and returns false after about 5 seconds, which the caller must fail on. Only transitions count. The status dots and the logo loop forever by design, so waiting on every animation would never finish. `axe.test.mjs` and `ocTabs.test.mjs` both use it, and a browser test slows the chip to 1.5 s, flips the theme and proves the wait lasts as long as the transition and ends on the settled colour. CPU load alone could not reproduce the failure, because Chrome stops starting well before the chip is late, so the proof forces the slow transition directly.

**Every server test class passes alone.** `tests/test_opscenter_lanes.py` loads the server test modules into one process, so a class that works only because an earlier class imported something first is invisible there. `optional_test.py` had two such classes (`Builds` and `Extensions`) that imported a provider module before `routes`, and `routes` is what puts `server/modules` on the path. Run alone, as a person does when chasing a failure, they errored with `No module named 'optional_provider'` in 0.07 s and read as a code fault. The order is fixed, and `EachClassRunsAlone` runs every test class of `optional_test` in its own process and fails by class name. It reads the class list from the source and fails if it finds fewer than six, so it cannot pass by looking at nothing.

### 12.70 The follow-up items 25 to 28 on issue 308

The issue body lists items 1 to 24. A follow-up comment on it adds 25 to 28, and the 12.67 table above stops at 24, so this section records them. Each was checked against the code on main and not from the issue text.

| Item | State | Where |
|---|---|---|
| 25 work tracking tabs | In core | Sprint has the mine or team scope, Hide done and the Synced stamp (`pages/Sprint.tsx`). Backlog has the issue type filter and Move To Current Sprint (`pages/Backlog.tsx`). Changes lists change requests where the owner is the approver (`pages/JiraHub.tsx`). Needs me carries its counters and empty state |
| 26 derived build state | Closed in v2.23.0 | The stuck and finished sentences, the pull request on a row and the panel on the Operations overview (12.68). Before this release a row had no field for a pull request, so it could not say "Pull request open, 1 red" |
| 27 Knowledge | In core | Proposals has the publish mode switch (`components/PublishMode.tsx`). Doc coverage is the registry of what runs, joined with the daily audit, with a tier, a responsible and accountable owner per row (`owner_r` and `owner_a`), gap counts by priority and a filter. Docs drift is report only. History has Page history and Revert to previous version |
| 28 scope sub-lines | Closed in v2.23.0 | Every core page draws a `HubHeader` with a subtitle, which is its scope line, and the Action Center tab body sits under the Action hub header. v2.21.0 added the line to the four pages that had none. `tests/scopeLines.test.mjs` now reads every page file that draws a header and fails by name when one has no subtitle or a literal line is too short or holds a semicolon or an em dash |

The Stop action and `POST /api/automation/approve` stay out of the core for the reasons in 12.68 and 12.67.

### 12.66 The sprint trend and the closed sprint view

`tracker/sprint_trend.py` holds the rules, `tracker/work.py` the reads, caches (closed sprints one hour, trend thirty minutes, one past sprint ten minutes) and the routes. Honest limits: the figures are "items in the sprint now" and "done today", not a count at sprint start; the closed list shows only sprints that held the team's issues; a tracker without a Jira style sprint field supplies `tracker_closed_sprints` and `tracker_sprint_items` (rows `{key, status_category, points, later_sprint}`, where `later_sprint` is the source's own answer to "also in a sprint that started later"). The trend card (tiles with the 85 and 70 percent tones) is the app's and is not in this section.
### 12.64 Documentation audit rules R13, R15 and R16 (opt in)

`engine/doc_audit.py` gains three rules, each off until its input exists. R13 reads the docs home as html through the same driver as the other rules; R15 needs the registry key `archive_page`; R16 needs the config key `mirror`. The registry's `things[].status` is `live | wip | retired` (`retired_note` is free text the audit ignores). R16 injects `run` and `now` so a test gives a clock and a fake runner; the file compare is the git blob sha (`sha1("blob <len>\0" + bytes)`), a fresh file inside the grace window is not drift, and a deletion is not tracked. The moved-page rule of the consumer is not lifted.

### 12.63 The optional modules at the server (routes, providers, the off state)

`server/optional.py` registers the log intake and reports routes, each only when its setting (`OPSCENTER_LOG_INTAKE`, `OPSCENTER_REPORTS`) is on; `routes.build()` calls it after every other module. With both absent the route table, the background task list, the file system and the imported modules are exactly what they were without the modules (a test starts a fresh interpreter to check imports).

- Providers: `OPSCENTER_LOG_INTAKE_PROVIDER` and `OPSCENTER_REPORTS_PROVIDER` name `path/to/file.py:ClassName`, loaded by `modules/optional_provider.py` (the same contract as the other provider slots; every method optional). Log intake: `verify_key`, `authorize`, `on_rows`, `audit`, `audit_event`, `sink`, `extra_reserved`. Reports: `authorize`, `source`, `dashboards`.
- Authorization: the core's trust boundary is the loopback port and it has no user model, so `authorize(headers, action, key)` is the one slot for who may do what, with a null default that refuses everything. Actions: `log-streams.read|write`, `dashboards.read|write`, `reports.run`. Per-key rights (`reports/grants.py`) are the consumer's `authorize` to apply.
- The device route is the only route a device calls: `X-Api-Key` through `verify_key` (null refuses every key). The server's body cap (`OPSCENTER_MAX_BODY`, default 1 MiB) applies before a stream's own post size, and the consumer's proxy must pass the route and add its host name to `OPSCENTER_ALLOWED_HOSTS`.
- Writes are POST: a save takes the definition as the body (or `{def}`), a dashboard save is `POST /api/dashboards/<key>`, a delete `POST /api/dashboards/<key>/delete`; the keys `run`, `import` and `export` are reserved.

### 12.62 The optional reports engine (R3, the report spec, the source slot and dashboard runs)

Optional: `reports/query.py`, `reports/sources.py` and `reports/dashboards.py` are imported only when used. A report is a small structured spec, never SQL: `{match, filters, groupBy, metrics, columns, sort, limit}`; `check_spec` refuses unknown fields, operators and metrics with a reason before anything runs, values are bound parameters, and the SQL is assembled only from fixed fragments over one stream's own rows. The lookups cache (`log_directory`, `log_catalog`) is attached to the intake connection as `lk`, so a looked-up field (`@user`, `@email`, `@department`, `@title`, `@publisher`, `@store`) joins in SQL and a person falls back to the name as sent. The report time zone is `OPSCENTER_REPORTS_TZ` (default UTC); the reference had one fixed zone.

- Source slot: `get_stream(key)`, `run(stream, spec)`, optional `options(stream, field, limit)`. The dashboard code never sees a store, so a second source can follow; a test runs two sources and checks the same dashboard result.
- Dashboards: a panel runs its `spec`, or `{metrics: [measure]}` when it has only a measure (enough for a stat tile). A dropdown narrows a panel only when the panel's stream has the field. A stat compares with the period just before the range (needs a time field and a day range) or shows a share. Events dated more than a day ahead are left off every time panel and reported with a report spec that lists them. The reference's worker pool is not here; a `should_stop` callable is checked between panels.

Not here: the routes that serve these, the deep link formats, and any non local source.

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

### 12.61 The optional reports lookups (R6, directory and catalog)

Optional: `reports/directory.py`, `reports/catalog.py` and `reports/lookup_db.py` are imported only when used; nothing runs at import and the database (`OPSCENTER_REPORTS_DB`, default `<state>/reports.db`) is created on first use. Both are slots, not integrations: the consumer supplies `lookup(kind, value)` for the directory and `fetch(id)` for the catalog.

- Directory: keyed by the trimmed lowercase account; the bare name is taken out of `DOMAIN\\sam` and a UPN; resolution tries the account name and then the principal name and only a single match is found. Cache: found 30 days, miss 1 day, error 1 hour; `DirectoryUnavailable` pauses lookups 10 minutes and nothing is cached; at most 200 per run. The reference planned an email field and had not built it; here it is a directory field (`mail`).
- Catalog: id pattern is configuration; found 30 days, miss 7 days, an unavailable store pauses an hour and caches no miss; a person's publisher (`save_known_publisher`) is kept as is, never overwritten, never expires, and removing it returns the id to the lookup; at most 100 per run.

Not here: the service that supplies the slots (the consumer's). Plan items that were not built were dropped by decision on 2026-11-10.
### 12.60 The optional log intake module (E1 to E3, E5, E6, server side)

Optional and never mandatory: the package `server/modules/log_intake/` is imported only when a consumer sets `OPSCENTER_LOG_INTAKE`, and no file in it has an import side effect (no database, thread or route; the database `LOG_INTAKE_DB`, default `<state>/log-intake.db`, is created on first use). Devices post a JSON envelope (`schemaVersion` "1.0", `source`, `snapshotId`, `collectedAt`, `records`) to one route per stream with one key per stream; a stream is data, not code.

- `streams.py`: the pure rules. A sink table must match the configured namespace (`LOG_INTAKE_TABLE_PREFIX`, default `Stream_`, and `LOG_INTAKE_TABLE_SUFFIX`) and anything else is refused before any call. `plan_schema` adds, removes and retypes without ever reusing a column (a retired column stays, a retype allocates a new one, a removal retires one) and flags removals and retypes as destructive; `clean_records` keeps declared typed fields keyed by physical column, puts undeclared keys in one capped `Extra` object, cleans dashes and control characters and drops a row missing a required field. A new stream keeps its data at the sink for 180 days unless another value is given (the reference's code default; its inventory text said 90, and the code is what runs); the post limit per device per hour starts at 6 for a latest stream and 50 for an events stream and is clamped to 1 to 1000.
- `stream_store.py`: streams as data in the module's database, every change audited through the audit slot, a destructive schema edit needs `confirm`, a synced table is never deleted from here and deleting any stream needs its table name typed.
- `ingest.py`: `handle(stream_key, api_key, content_length, body, verify_key=..., on_rows=..., audit=...)` answers 404, 401 (the key slot `verify_key(api_key, integration_key)`; null default refuses every key), 413, 400, 503 with `Retry-After: 900` over the buffer cap, 429 with `Retry-After: 3600` over a device's hourly limit, 202. The device comes from the post's `source`, never from row content.
- `current_store.py` (E5): the latest snapshot per device (a replayed older file never overwrites a newer one) or every post for an events stream (a replay is a no-op), and the event history is purged after the stream's retention.
- `buffer.py` and `forwarder.py` (E2, E6): the local buffer between the receiver and the sink, capped by count and size, and the forwarder that sends batches under a row cap to the sink slot (`name`, `send(table, rows)`, optional `is_ready(table)`); with no sink nothing is buffered.
- `sink_check.py` (E6): the sink access test. `action_allowed`/`check_actions` report a missing right with the role and scope that would grant it (rights that could not be read are "could not be read", never a pass), `diagnose` normalises a sink's own checks, and `send_test_row`/`verify_test_row` send and find a marked row through the real sink path.

Not here (the consumer's): the sink providers, the stream settings page (the kit's) and the enrichment hooks. Plan items that were not built were dropped by decision on 2026-11-10.

### 12.57 The optional reports module (R9, the CSV formula guard)

The reports module is optional and never mandatory: nothing under `server/modules/reports/` is imported by the server unless a consumer sets `OPSCENTER_REPORTS`, and a consumer that does not use it loads, pays for and sees none of it. `reports/export_csv.py` is the first part, and it is a plain helper usable with no module at all: `guard`, `cell` and `to_csv` neutralise a text value that starts with `=`, `+`, `-`, `@`, a tab or a carriage return with a leading apostrophe (inside the quotes when the cell is quoted), leave numbers, booleans and None alone, quote commas, quotes and line breaks with the quotes doubled, and end lines with CRLF. Every CSV download goes through it (web-api-runtime 9.2).

### 12.54 Owner roots ahead of main, the owner apply guard and the draft gate grammar

**Ahead of main** (`server/modules/owner_roots.py`). A pull request can apply an owner-applied root from its own branch before it merges. The consumer's PR apply flow records that with `set_pr_hold(name, tier, pr, head, digest, resources)` (only added, changed, replaced and imported addresses are held). While the PR is ahead of main, main's plan that would destroy or replace an address the PR applied is marked `ahead_of_main`; the card says "Ahead of main, waiting on #N" (`ahead_text`, shown only while the card is pending and held), and Apply is refused by the server (409) and by the worker. A new head is a new apply: the hold names the head it was made for. The hold clears when main contains the PR's merge commit, or when the PR closes unmerged (`refresh_holds`, every `OWNER_ROOTS_HOLD_TTL_S`, 120, and on each plan). Provider hooks, all optional: `pr_state(pr)` returning `(open|merged|closed|unknown, merge_commit)`, `contains(oid, sha)`, `pr_url(pr)` and `owner_name()`. The null default is `unknown`, which keeps every hold: nothing is ever released by a read that failed. Detecting a branch apply nobody recorded (a hand apply) needs the PR plan flow and is not lifted; only recorded holds exist.

**Owner apply guard** (`guard_refusal(name, tier, item)`, `owner_roots.py guard <name> <tier>`, exit 3). Before an apply, and as a read-only command, the guard refuses when any resource the saved plan deletes (a destroy or a replace) is an address a pull request that is still open or unreadable already applied from its branch, whether or not the card was marked, so a stale mark never lets a delete through. A merged or closed PR, a root with no hold, or a plan whose deletes touch nothing the PR applied passes. The apply itself runs `_ahead_refusal`, which uses the card mark first and then the guard.

**Ahead more than two days** (`ahead_items(now)`). An open PR that holds a root ahead of main for more than `OWNER_ROOTS_AHEAD_CARD_S` (default two days) becomes an Action Center item `{key, priority, title, why, action, owner, refs, sources, links}` with the key `ahead-<root>-pr<N>` so a duplicate is never shown; the age runs from the apply, or from detection when the hold was found without a record; a hold with no time is stamped and counts from then; a merged or closed PR is skipped.

**Draft gate grammar** (`lanes/pr_gate.py`, the plug-in `OPSCENTER_DRAFT_GATE` loads). The condition that holds a staged PR as a draft is a fenced block in its description (three backticks and the word gate): one `kind: argument` per line, an indented line continues the line above, blank lines and `#` lines are ignored, a malformed line or an unknown kind is an error and is never met, an empty block is never met. Built-in kinds are `pr-merged: <number>`, `run-success: <workflow> <branch>` (the newest completed run, however old) and `applied: <number>` (merged AND a successful run of the apply workflow on the apply branch that started at or after the merge; a run after the merge that did not succeed is named; the workflow and branch come from policy `own_pr_merge.gate_apply_workflow` and `gate_apply_branch` or `OPSCENTER_GATE_APPLY_WORKFLOW` and `OPSCENTER_GATE_APPLY_BRANCH`, null by default, and the kind is then never met and says so); the consumer adds its own through `OPSCENTER_GATE_KINDS` (a Python file with `KINDS = {kind: fn(arg, repo, run) -> (met, detail)}`). `own_pr_merge.draft_gate` already checks each line against live data and marks the draft ready (12.2); this is the grammar and the checker it loads.

### 12.55 Run watches and status files

**Run watches** (`lanes/run_watches.py`, config `OPSCENTER_RUN_WATCHES`: `{"watches": [{kind, repo, workflow, label, branch, min_streak, owner}]}`). Two watches on the CI runs of a repository, each raising one Action Center item while its condition holds and clearing when a later run succeeds, with the same item shape and a stable key (`main-watch-<workflow>`, `drift-watch-<workflow>`) so the board's key guard never shows a duplicate. The **main** watch: the newest completed run of a watched deploy or apply workflow on the branch decides; a failure or timeout raises one item with the workflow, the failed job (and step), its first error line and the run link; cancelled and skipped runs count neither way. The **drift** watch: when the newest `min_streak` (default 2) scheduled runs on main all failed, one item names each failing job and its error lines and grows with the streak; a scheduled success closes it; a manual run and a run on another branch never count. A watch that cannot be read, or a config that cannot be parsed, is itself an item (unknown, never clear). The error line of a job is its first `Error:` line, else its first `##[error]` annotation, never the runner's exit code line. A failed run's jobs and logs are read once and cached by repo, run id and attempt (bounded to the newest 20; an unread log is not cached), in the process or in the optional `cache_file`. `run_watches.py items` prints the items.

**Status files** (`server/modules/status_source.py`). Two rules for any card that depends on a collector's status file. Unknown is never in sync: `read(path, max_age_s)` answers `ok` only for a fresh, well formed reading; a missing, old, unreadable, malformed or stale-flagged file is `unknown` with the reason (the last data is still returned, marked). A lapsed sign-in is never silent: `collect(fetch, path, lapse_s=14400)` writes the reading, and when the consumer's `is_auth_error` says the sign-in lapsed it keeps the last reading marked stale, counts the lapse from the first failure and exits non-zero once it has lasted `lapse_s` (240 minutes) so the Alerts tab raises it; any other failure exits non-zero at once and never writes a fresh-looking reading.
### 12.53 The freeze lane (human bypass, CI-only exemption, labeler, stale green)

Four additions to the own-PR lane (`lanes/own_pr_merge.py`, 12.2), each opt in or fail closed.

**Human freeze bypass** (`lanes/freeze_bypass.py`, on the override store, 12.52). The lane holds every PR while a freeze window is on. The owner lifts that hold from the ops center for one PR for the current window only (the entry carries the window id, expires with the window and records the head it was made for) or for all own PRs until the next midnight in the freeze file's time zone. The expiry is stored with the entry and compared on every read, so nothing runs at midnight; a missing, unreadable, foreign-window or expired store means no bypass and the freeze holds. `set_pr`, `set_all`, `status` and `bypass_by` are the module's API; the module is the only writer, every change is appended to the store's log, and the lane logs a bypass once per head and source (`note_once`). Only the owner's own open pull requests qualify, through the `read_pr(key)` slot (null default: no single PR can be bypassed). The store file is `OWNPR_FREEZE_BYPASS_FILE` (default `<state>/freeze-bypass.json`). Every other gate (checks, findings, policy rules, conflicts, sign-offs) still applies.

**CI-only exemption** (`lanes/freeze_ci_only.py`, policy `freeze_ci_only`, off by default). A PR that only changes how CI checks pull requests deploys nothing, so a freeze need not hold it. Every changed file must match `ci_paths` (default `.github/workflows/*`, `.github/scripts/*`, `.github/actions/*`); a changed workflow is judged on both sides (PR head and base) and held if either can run on anything but `pull_request` or `merge_group` (`pull_request_target` is held: it runs with the base branch's permissions and secrets), if its file name starts with `_` (a reusable workflow a deploy can call), or if it names a deployment environment outside the allowlist (policy `own_pr_merge.freeze_ci_environments`, null: only `terraform-plan`; an environment block or an expression with no readable name is held); a changed script is judged by every workflow, on either side, that names it directly or through another script, all of which must be pull-request-only; a script no workflow names, an unreadable file, an unparseable `on:` block or a chain deeper than four scripts is held. There is no YAML library, so the `on:` reader is strict and fails closed: an unclosed flow list, an open quote, a block scalar, an anchor, a repeated `on:` key or uneven indentation is unparseable. Decided once per head and logged (`freeze_ci_only` or `freeze_not_ci_only`). The list query carries `baseRefOid`; without it the freeze holds.

**Override labeler from the GraphQL timeline.** `override_by_me` reads the newest `LABELED_EVENT` for the override label from the GraphQL timeline (the newest 100 label events). The REST events list stops at about 300 entries, so on a PR with many deploy events a fresh label was missing and the lane held a PR the owner had overridden, or trusted a stale labeler. A read error is not an override.

**Stale green** (`unstick`, policy `stale_ready_min`, default 20). A PR that stays ready for that many minutes and that the lane never merged has its latest CI run re-run once per head, then one alert line; a PR waiting that long on the AI review result gets the alert only. This is the sync lane's rule (12.2) for the own-PR lane.

