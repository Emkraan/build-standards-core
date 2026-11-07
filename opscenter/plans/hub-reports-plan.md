# Plan: the optional reports module (R1 to R9, P1 to P4, U1, U2)

Source: the hub's feature inventory (intake issue 117, comment 6607335699, sections 3 and 4). Decision: build into the core as an opt-in
module (README, "The opt-in contract"). Status of the evidence: the hub's text and named tests only; each entry says whether it is
**specified** or **needs source**. Entries marked "no test" in the hub get a test written here.

## What the module is

Dashboards that open populated with one slim filter bar and click to cross-filter, definitions as data (edited in the UI, JSON import and
export, shipped defaults never overwrite an edited copy), panels that name a stream and a measure instead of a store, a spreadsheet and
CSV export with a formula guard, directory and publisher lookups, and role grants per report and dashboard.

## Module layout (server side, `opscenter/server/modules/reports/`)

| File | Holds | Entries |
|---|---|---|
| `definitions.py` | Definition store, seed by version, import and export, reset | R2 |
| `sources.py` | The data-source slot: a panel names a stream and a measure; the local snapshot source (from log intake) is one provider | R3 |
| `dateranges.py` | Whole-day between filter in a named zone, end day counted in full, across a clock change; future-dated event handling | R4, R7 |
| `export_csv.py` | The shared CSV helper with the formula guard | R9 |
| `export_xlsx.py` | One workbook: a Summary tab and a tab per panel, no pre-built pivots | R5 |
| `directory.py` | Directory lookup slot with the cache policy; publisher lookup slot | R6 |
| `grants.py` | Per-report and per-dashboard role grants, orphan sweep | P1, P4 |

Setting: `OPSCENTER_REPORTS`. Absent: nothing above is imported and no route exists.

## Entry by entry

| # | What is built | Specified or needs source | Tests |
|---|---|---|---|
| R9 | One export helper: quotes cells and prefixes an apostrophe to a value that starts with `=`, `+`, `-`, `@`, tab or CR; every CSV download goes through it | Specified (the rule and the characters). First to build: it is a security rule and also goes into the shell packages for any tool | quoting; each leading character neutralised; inert text in a workbook |
| R5 | One workbook, Summary tab plus a tab per panel, row tabs are real tables; pre-built pivots off with a flag that stays off | Specified (structure, the flag, the reason: hand-written pivot parts crash the desktop spreadsheet app). Rule: no hand-written workbook part ships until a generated file was opened on both platforms | the workbook structure; the pivot flag stays off (the hub has no test) |
| R7 | Events dated more than a day ahead stay off time panels in every range, with a note carrying the count and a link to the rows | Specified | a wrong device clock stays off the charts |
| R4 | Whole-day between filter in a named zone, end day counted in full across a clock change; deep links carry view state | Specified for the filter (`override_store.expires_at_local_midnight` already does the zone arithmetic); needs source for link formats | whole local days across a clock change; inclusive of the last day; link building (the hub has none: written here) |
| R2 | Definitions are data: edit, import and export by key, shipped definitions seeded by version and never overwriting an edited copy, an edit can be reset | Specified | keeps edits across a re-seed; round-trips an export; rejects bad definitions |
| R3 | Panels name a stream and a measure, not a store; the local snapshot is one source, a query source can follow | Specified in principle; the parity test between two sources is not built in the hub | the source contract; parity between two fake sources (written here) |
| R6 | Directory lookup (name, department, title) with a cache (people 30 days, misses a day, failures retried after an hour); computer accounts, the system account and the posting device stored as not a person; a name matching two people stored as not found, never guessed; publisher lookup per extension id | Specified for the cache policy and classes; needs source for the directory and catalog shapes. Planned in the hub, not built: email, hand-entered publishers kept across lookups | caches and classes; ambiguous names; failures retried after an hour |
| R1 | Dashboards open populated with one slim filter bar and click to cross-filter; Explore is the builder | Client side (the kit session); the server serves definitions and panel data | a dropdown choice narrows every panel (kit); click to filter and the absence of a Run button (the hub has none: written here) |
| R8 | Chart colours from one theme hook | Already in the kit (`chartTheme`); add a test that both themes are covered | both themes |
| P1 | Additive roles: effective rights are the union of every matched role plus user grants; per-report and per-dashboard rights are role grants named by key; dashboards and reports have separate global rights | Specified; `rbac.md` already states the additive model | union across roles; per-key grants |
| P2 | The roles page lists every tool under its own heading | Specified; needs the shell manifest (shell session) | a tool with its own area gets its own group; every tool appears (the hub has none) |
| P3 | Role preview is read only except a pinned allowlist of read-only query POSTs | Specified; `rbac` package has view-as pieces | everything else is refused; the two allowed POSTs work |
| P4 | A grant is removed when its report or dashboard is deleted or retired, and swept after seeding | Specified | drops the rights of a deleted report and keeps a live one; the sweep at start |
| U1 | One processing indicator: a patched fetch drives an overlay after 350 ms, "Loading" for read-only POSTs and "Saving" otherwise, background work opts out, input never blocked | Client side (kit); needs source for the opt-out API | delay, labels, non-blocking input (the hub has none: written here) |
| U2 | Action buttons coloured by purpose through one data attribute, checked by a script | Client side (kit), plus a repo check; `data-act` exists in kit primitives | the check fails a button with an action verb and no tag |

## Order

1. R9 (the formula guard), because it is a security rule useful with no module at all.
2. R7, R4, R2, R5 (fully specified).
3. P1, P3, P4 (specified; reuse `rbac`).
4. R3, R6 and the rest when the source arrives.

## Open questions pending the source

1. Link formats for deep links and drill-through (R4).
2. The directory and catalog response shapes (R6).
3. The opt-out API of the processing indicator (U1).
