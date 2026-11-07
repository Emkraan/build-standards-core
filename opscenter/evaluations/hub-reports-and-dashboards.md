# Evaluation: the hub's reports and dashboards (R1 to R9, P1 to P4, U1, U2)

Source: the hub's feature inventory (intake issue 117, comment 6607335699, sections 3 and 4). Status of the evidence: read by the hub owner
against the hub code; the entries marked "not found" there have no test yet.

## What the group is

A dashboard surface on top of the intake platform (see hub-log-intake.md): dashboards open populated with one slim filter bar and
click to cross-filter, definitions are data (edit in the UI, import and export, shipped versions never overwrite an edited copy),
panels name a stream and a measure instead of a store, a spreadsheet export, directory and publisher lookups, and a role model.

## Entry by entry

| # | Feature | Generic or hub-specific | In the core today | What the core would need |
|---|---|---|---|---|
| R1 | Dashboards are the consumer surface, Explore is the builder; click to filter | Generic | Kit charts and `chartTheme`; no dashboard shell, no cross-filter state | A dashboard page kit (filter bar, panel grid, cross-filter store). A kit piece, large |
| R2 | Definitions are data: UI edit, JSON import and export, shipped versions seeded by version and never overwriting an edited copy | Generic | Nothing | A definition store with a seed-by-version rule. The rule alone ("a shipped default never overwrites an edited copy; raise the version to roll out") is one sentence |
| R3 | Data-source layer: a panel names a stream and a measure, not a store | Generic | Nothing | An interface between a panel and a source, plus a parity test between two sources. The hub has not built the parity test |
| R4 | Deep links, whole-day filter in a named time zone across a clock change | Generic | The override store's `expires_at_local_midnight` handles the zone arithmetic for one case | A date-range helper shared by server and client; the test for link building is missing in the hub |
| R5 | One workbook with a Summary tab and a tab per panel, no pre-built pivots | Generic | Nothing | A spreadsheet writer. The hub's finding is a rule worth stating: no hand-written workbook part ships until a generated file has been opened in the desktop app on both platforms without a repair prompt |
| R6 | Directory lookup and extension publisher lookup with caches and "not a person" classes | Hub-specific (its directory and catalog), generic cache policy | `identity-and-people-data.md` | The cache policy (people 30 days, misses a day, failures retried after an hour, a name matching two people stored as not found) could be one rule with a test |
| R7 | Events dated more than a day ahead stay off time panels, with a count and a link | Generic | Nothing | A rule: "a wrong device clock never moves a chart" |
| R8 | Theme aware chart colours from one hook | Generic | `kit/src/charts/chartTheme.ts` already does this | Nothing; add a test that both themes are covered |
| R9 | One export helper that quotes cells and neutralises a leading formula character | Generic | Nothing in the kit or the server packages | A shared helper and a rule "every CSV or spreadsheet export goes through the formula guard". This is a security rule, small, and worth taking |
| P1 | Additive roles: effective rights are the union of every matched role plus user grants | Generic, already the standard | `rbac.md` | Nothing |
| P2 | The roles page lists every tool under its own heading | Generic | The shell manifest and roles surface | A test that a tool with its own area gets its own group and that every tool appears; the hub's open pull request is red on exactly this |
| P3 | Role preview is read only except a pinned allowlist of read-only query POSTs | Generic | `rbac` package exposes view-as pieces | The allowlist-of-read-only-POSTs pattern as a rule with a test |
| P4 | Grants follow their report or dashboard (removed on delete, swept after seeding) | Generic | Nothing | A sweep rule: "a grant never outlives the object it names" |
| U1 | One processing indicator: a patched fetch drives an overlay after 350 ms, "Loading" for read-only POSTs and "Saving" otherwise | Generic | Nothing in the kit | A kit hook and overlay; a timing test is missing in the hub |
| U2 | Action buttons coloured by purpose through one data attribute, checked by a script | Generic | `data-act` appears in kit primitives | Check whether the kit already defines the colours; the script gate is the missing part |

## Recommendation

Do not build the dashboards in the core. They sit on the intake platform and on the hub's data, and a dashboard shell is a large kit
piece with one consumer. Take the small, general, rule-shaped parts, each with a test: R9 (the formula guard, a security rule), R5 (the
rule for workbook parts), R7 (future-dated events), R2 (shipped defaults never overwrite an edit), P4 (a grant never outlives its
object), P3 (read-only preview with a pinned allowlist) and P2 (every tool appears on the roles page).

## Decisions for the owner

1. Take the nine rule-shaped items above into the standards? Recommended: yes, one PR, each as a `test` rule the hub proves.
2. Is a dashboard shell a kit piece worth building before a second consumer asks? Recommended: no.
3. Should the shared export helper (R9) live in the shell packages so every tool gets the formula guard? Recommended: yes, it is the one item with a security impact.
