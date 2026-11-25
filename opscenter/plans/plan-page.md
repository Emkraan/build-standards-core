# The plan page: a downstream page, not a core screen

Decision of 2026-11-18 (issue 305). A consumer that keeps plans, situation and recommendation
briefs, or an archive of briefings shows them on its own page. The core builds no screen for it. The
core already reads a folder of markdown plans (`server/modules/plans.py`, `PLANS_DIR`), and that is
all it ships. This page records the contract a consumer follows when its own plan page needs more
than that, so a second consumer can lift the page without a rewrite.

## The contract

The page follows the local-ops contract rules of [Local Ops App](../../standards/local-ops-app.md)
section 3:

1. **A neutral contract.** The page reads one state file whose shape is described without a tool,
   an organization or a person: a list of plans, each with an id, a title, a status word, a summary,
   an updated date and an archived flag. Names and identities live in the deployment's own
   parameters and never in the file's shape or the page's code.
2. **One named writer.** Exactly one job writes the file, atomically (a temp file, then
   `os.replace`). The page and every other job only read it. A page action that changes a plan
   (archive, restore) goes through the one writer, never to the file directly.
3. **A schema.** The file has a JSON Schema beside the consumer's other contract schemas, in the
   small subset the conformance checker supports (`type`, `required`, `properties`, `items`,
   `enum`).
4. **A fixture.** A fixture state directory holds a valid file with one active, one done and one
   archived plan, so the page and the checker run against known data.
5. **A test.** A test runs the checker over the fixture, renders the page from it, and proves the
   empty case (no file, an empty list) renders an empty state and not an error.

## What stays out of the core

- No plan screen, route, tab or navigation entry in the core app.
- No plan state file or schema in the core contract. A consumer adds its own, and any plan
  adapter is a slot (an optional page behind a null default, shown only when its slot is on).

## Design: a briefing archive on a data-only page (issue 376 item 3)

Status: built as option A with the cap of 20 and no manifest tool (`links` on a row, DESIGN 12.106, 2026-11-25). Option B stays open until a second consumer asks, and the cap can be revisited.

### The ask

A page that lists each generated briefing with its earlier dated versions (never deleted), grouped by document, each one openable.

### Where the core stands

The decision above holds: the core builds no briefing screen. What changed is what a consumer can build without one. A data-only extension page (DESIGN 12.80) lists rows from a manifest file, and since 12.106 a row can link to a local document inside `OPSCENTER_DOCUMENT_ROOTS`. So one row per briefing document, with a `doc` link to its latest version, is possible today and is grouped by document because each document is one row. Two things are still missing.

1. **Earlier versions are not openable.** A row has one link. Its `fields` are text only, so the dated versions can be named in the drawer but not opened.
2. **Nothing writes the manifest.** The core serves files and never lists a folder (12.106 says so on purpose), so some job has to turn an archive folder into rows.

### Proposal

**Core, small: a `links` list on a row.** `links: [{label, doc? or url?}]`, at most 20, each checked by the same rules as the row's own link (`url` must be http or https, `doc` must resolve inside a document root, otherwise that entry is dropped and the row says how many were not available). The drawer shows them as a list of links under the row's fields. This is the only core change, it is additive, and a row without `links` keeps the shape it has. The tests are the ones 12.106 already has, applied to the list, plus the cap and the dropped entry.

**Consumer: one writer.** Following the contract above, one job scans the consumer's archive folder and writes the manifest atomically. A suggested layout, which is a convention and not a core rule, is `<document name>/<YYYY-MM-DD>-<document name>.<ext>`. For each document name the job writes one row: the title, the state of the latest version, `doc` for the latest, `links` for the earlier ones newest first with the date as the label, and an `at` of the latest date. The job only adds files to the archive and never deletes one, so the never-deleted requirement is a property of the writer and its folder, not of the page, and the core still never writes to a root.

### Options considered

| Option | Result |
|---|---|
| A. `links` on a row plus a consumer writer (proposed) | Meets the ask with one additive core change. Keeps decision 305. The consumer owns the layout. |
| B. A core tool that builds the manifest from a folder layout | Saves a second consumer from writing the scan. Fixes a filename convention in the core, and it is the first thing to add if two consumers ask for it. Not proposed now. |
| C. A core briefing screen that scans a folder | Contradicts decision 305, needs the core to list a folder (which 12.106 refuses), and ties the core to one filename convention. Rejected. |

### Acceptance for the build

1. A row with `links` shows each reachable entry as a link in the drawer, drops an entry outside the roots, and shows the dropped count. A row without it is unchanged.
2. The client draws only a web address or the exact document address, as it does for the row link.
3. A fixture archive of two documents, one with three versions, produces two rows and the three earlier links in date order, and the test fails if a version is lost.
4. DESIGN 12.106 and the changelog name the new key.

### Questions for the core owner

1. Is A acceptable, given decision 305?
2. Is 20 earlier versions per row the right cap, or should older ones be reached another way?
3. Should B be built now so the consumer does not carry the scan, or only when a second consumer needs it?
