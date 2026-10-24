# Docs and Changelog Standard

Version: 1.1 | Last reviewed: 2026-10-21 | Status: current | Scope: all

What "documented" means for anything a team runs, where the documentation lives, how changelogs
are kept and how gaps are found. This doc is the source of truth. Where a reference implementation
differs, the implementation is fixed, or the consumer records an explicit exception (README,
"Source of truth and explicit exceptions").

The **docs home** is a parameter set in `standards-local/parameters.md`: a wiki space, a docs site
or the repo itself. The rules hold wherever it is.

Related: [PR Review and Merge](pr-review-and-merge.md) (the changelog entry in every PR),
[CI/CD section 3](ci-cd-release.md#3-conventional-commits-and-semver) (versions and the in-app
changelog), [First-Party Build Standard section 9](web-build.md#9-engineering-practice) (standards
change with the code).

---

## 1. Rules

1. **Done means documented.** A change is done when its docs in the docs home match the shipped behaviour, in the same PR when the docs home is the repo, otherwise the day it ships.
   - Prevents: docs that describe last quarter's system, which people follow into an outage.
   - Acceptance (review): the PR or release record links the doc update.
2. **One docs home per thing, and one page set per home.** Every distinct thing a team runs has exactly one home in the docs home, with an overview, a runbook and a changelog. A repo whose docs home is elsewhere points to it from its README.
   - Prevents: three partial copies that disagree, and nobody knowing which one is the record.
   - Acceptance (review): the docs registry lists one home per thing.
3. **One changelog per app, versioned and dated.** Each app keeps one changelog in its docs home. Every shipped change adds an entry headed with the date and version (`## YYYY-MM-DD (vX.Y.Z)`), unreleased work sits under "Pending release", and the release record is the version tag plus the entry.
   - Prevents: releases nobody can explain, and rollbacks to a version with no recorded content.
   - Acceptance (overlay-ci): when the docs home is the repo, the `core-ci.yml` job `core-changelog` fails a PR that moves the version in a version file (parameter, default `package.json`, `pyproject.toml`, `VERSION`) without a `## YYYY-MM-DD (vX.Y.Z)` heading for it in the changelog.
4. **Claims are verified against code and live state.** Every behaviour, setting and UI label a doc states is checked in the code and the running system before it is written. A doc that claims a stronger guarantee than the code gives is a defect.
   - Prevents: plausible prose that is wrong, such as a rollback step the updater cannot perform.
   - Acceptance (review): the page footer names what it was last verified against.
5. **Coverage is audited against a registry.** A registry lists everything the team runs with its tier, docs home, changelog and release source. A deterministic audit compares it with the docs home and raises gaps on the owner's documentation view, not on the operational action queue.
   - Prevents: things nobody documented never surfacing, and doc gaps crowding out operational work.
   - Acceptance (review): the audit runs on a schedule and its last run is recorded with its gap count.
6. **Security gaps go to the risk register, not to published pages.** A weakness found while documenting is logged as risk and raised to its owner. Once the owner accepts a design, the page states the real trust model plainly.
   - Prevents: published instructions for exploiting a gap, and pages that claim a stronger model than the code.
   - Acceptance (review): no open security gap is described on a published page.
7. **Retired things keep their history.** Retiring a thing marks it retired in the registry, adds a note at the top of each page (date, replacement, where any data export lives) and a final changelog entry, and keeps the pages.
   - Prevents: lost context when an old system's data or decisions are needed later.
   - Acceptance (review): retired entries in the registry have the note and the final entry.
8. **Publishing is idempotent and single-flight.** Whatever writes approved pages to the docs home runs one instance at a time under an exclusive lock, records each page the moment it publishes, looks the title up before every create and never creates a page that already exists (it asks for an update instead), and checks that the created title came back unchanged. The coverage audit raises a gap for any title that appears twice in the docs home.
   - Prevents: duplicate pages from two overlapping publisher runs (a scheduled run and a manual one published the same approved set twice, and the docs home suffixed the copies with "(2)"), which readers then find and edit instead of the record.
   - Acceptance (test): two concurrent publisher runs on the same queue create each page once, a create whose title exists is refused, and the audit reports a seeded duplicate.

9. **One entry per pull request, append-only.** A repo whose docs home is the repo adds exactly one changelog entry per pull request, directly under the text above the entries (newest first), with the fixed heading `## YYYY-MM-DD (vX.Y.Z[, theme])` or, for a change that moves no version, `## YYYY-MM-DD (no version change[, theme])`, and at least one `- ` bullet. Older entries are never edited: every one stays byte for byte. A pull request that only refreshes the core sync's paths in the overlay (`standards-core/`, `tokens-core/`, `lint-core/`, `kit-core/`, `scripts/`, `standards.lock`) needs no entry of its own, because the core's changelog records that change (pr-review-and-merge.md rule 3); the exemption is by changed paths, never by title or label.
   - Prevents: history rewritten after the fact, two pull requests' changes folded into one entry nobody can map back, and an entry slotted under an older one where nobody reads it.
   - Acceptance (overlay-ci): with the parameters row `Changelog entries` set to `per-pr`, the `core-ci.yml` job `core-changelog` (step `changelog-entries`) fails a pull request that adds no entry or more than one, edits an older entry or the text above the entries, uses another heading, or dates the new entry before the one below it. A base commit it cannot read fails the step in CI (a check that cannot see the change proves nothing) and is skipped with a line on a local run.

## 2. The page set

| Page | Holds |
|---|---|
| Home | What it is, owner, status, current version, source, where it runs |
| Runbook | How to operate, recover and release it, with incident history |
| Design | How it works and why, the trust model, dependencies |
| Changelog | One entry per version, newest first |

A small automation may hold all four as sections of one page (overview, design, an operations
runbook section, troubleshooting, how a change ships, a changelog table).

## 3. Writing a changelog entry

- Heading: `## YYYY-MM-DD (vX.Y.Z)` with an optional short theme in the parentheses, or
  `## YYYY-MM-DD (no version change)` for a change that moves no version (rule 9).
- One entry per pull request, newest first, added directly above the previous one; older entries
  are never edited (rule 9).
- Bullets say what changed for the reader and why, not the commit list.
- Breaking changes say what a consumer must do.
- Reconstructing a missing changelog: walk the version file's history in git, one entry per bump,
  dated "no version change" entries for changes without a bump, and unmerged work under "Pending
  release". Mark versions approximate only when no version file exists.

## 4. The coverage audit

- The registry is data, kept where the owner can edit it. Owners come from the team's RACI, not
  from the registry.
- The audit is deterministic (no model), runs daily and keeps the previous result when it fails.
- Each gap has a key with a generation number, never volatile text. Dismissing a gap hides that
  generation, and new evidence bumps it.
- Discovery of new unregistered things only proposes a low gap. It never registers on its own.
- Re-run the audit after publishing a doc set, so the coverage view does not show closed gaps until
  the next scheduled run.
- The audit lists every page in the docs home and raises one gap per duplicate title set (titles
  compared after stripping a "(N)" suffix), keyed on the sorted page ids, and fails closed when a
  listing is truncated.

## 5. Checklist

- [ ] Docs home set in the overlay parameters.
- [ ] Every shipped change reconciled in the docs home.
- [ ] One home and one changelog per thing.
- [ ] Changelog entry dated and versioned, pending work under "Pending release".
- [ ] One entry per pull request, newest first, older entries untouched (`Changelog entries` per-pr).
- [ ] Claims verified in code and live state, footer names the verification.
- [ ] Thing listed in the registry, audit running.
- [ ] No open security gap on a published page.
- [ ] Retired things marked, pages kept with a note and a final entry.
- [ ] Publisher locked and title-checked, audit reports duplicate titles.
