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
