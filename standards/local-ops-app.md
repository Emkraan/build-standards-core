# Local Ops App Standard

Version: 1.3 | Last reviewed: 2026-10-21 | Status: current | Scope: web (local tools)

How to build a local, single-operator first-party tool: a small server and scripted engine on the
operator's own machine, with a web UI that follows the first-party design system. This doc is the source of truth. Where a reference implementation differs, the implementation
is fixed, or the consumer records an explicit exception (README, "Source of truth and explicit
exceptions"). This standard is for
tools that are not deployed to the cloud host and have exactly one user. Multi-user hub tools follow the
[First-Party Build Standard](web-build.md) instead.

## 1. When this pattern applies

- One operator, one machine, data in a local state directory, no hosted infrastructure.
- The tool reads other systems (mail, chat, source control, schedulers) and shows or drafts. It
  never sends or changes anything on the operator's behalf.
- A model may summarize or draft, but only behind a cost gate (section 4).

## 2. Stack

| Layer | Choice |
|---|---|
| Server and engine | Python 3 standard library only (`http.server`, `urllib`, `sqlite3` read-only where needed, `unittest`). No third-party Python packages. |
| Front end | React, TypeScript, Vite, `react-router-dom`. The UI library is the core kit (next row) and nothing else: no third-party UI component library. Charts come from the kit's chart entry (its optional peer), not a second chart library. |
| Styling | The core token sheets and kit stylesheet (next row), then `app.css` for app-specific classes only. Per-app accent by the kit accent, never a token redefinition. An app that does not take the core yet uses the plain-CSS port of the [Web Design System](web-ui.md#plain-css-port-no-tailwind) (`theme.css` plus `app.css`) until it adopts. |
| Core baseline | The app consumes the core in the `direct` way (README "Direction", `CONSUMING.md`): the component kit from `kit-core/`, the token sheets from `tokens-core/`, both synced copies never hand-edited, and app-specific code in `src/` and `app.css` only. |
| Package manager | pnpm 12 through corepack (`packageManager` in `package.json`, `corepack prepare pnpm@12.9.1 --activate` in CI), `pnpm install --frozen-lockfile`. |
| Lint and test | Biome (`biome lint src`), Vitest, `tsc --noEmit` as part of `build`. |

pnpm 12 blocks dependency install scripts by default. List the build steps the app needs in
`pnpm-workspace.yaml` (next to `package.json`):

```yaml
allowBuilds:
  '@biomejs/biome': true
  esbuild: true
```

Layout:

```text
server/      server.py (SPA + JSON API), infra.py (read-only infra views), search.py
engine/      collect.py, analyze.py, refresh.py (cron entry), common.py, conformance.py
contract/    neutral contract markdown + schemas/*.schema.json
app/         React/Vite front end (src/theme.css, src/app.css, src/ui.tsx, src/pages/*)
tools/       deploy-local.sh and one-off helpers
tests/       stdlib unit tests and fixtures
scripts/     check-ascii.mjs
```

## 3. The neutral contract

The data files and the HTTP API are specified in a neutral contract
(`contract/direct-contract.md`) with a JSON Schema per file or API section in
`contract/schemas/`. Collectors and UI can then be swapped independently, and the contract names no
organization, person or role. Identity and deployment facts live only in the deployment's
`config.json` in the state directory, which is never committed.

- **Envelope:** every response is `{ "success": true, "data": ... }` or
  `{ "success": false, "error": "text" }` (same shape as the hub's ApiResponse).
- **File list:** `action-center.json`, `handled.json`, `drafts.json`, `backlog.json`,
  `inbound.json` (the spool), `tackle.json`, `activity.json`. Each has exactly one named writer
  (for example the analyzer is the only writer of `action-center.json`, the server is the only
  writer of `handled.json`). State files are written atomically (write a temp file, `os.replace`).
- **Fingerprints:** an item's `fp` is a stable identifier for an issue across analyzer runs. The
  analyzer is shown the previous open items and reuses an `fp` when the issue is the same; user
  actions (`handled`: resolved, snoozed, ignored, ignored forever) are keyed by `fp`, so they
  survive re-analysis.
- **Conformance checker:** `engine/conformance.py <state dir> [--server URL]` validates the state
  files, and with `--server` every infrastructure section, against the schemas. It is stdlib only
  and supports the small schema subset the schemas use (`type`, `required`, `properties`, `items`,
  `values`, `enum`). CI runs it against a fixture state directory (`tests/fixtures/state`).
- **Contract changes** update the contract markdown, the schemas, the fixtures and the
  conformance tests in the same PR.

## 4. The cost-gated analyzer

Scripted work is free; a model call is not. The rule is structural:

- **Collectors never call a model.** `collect.py` reads mail and chat through the directory API
  (delegated token), applies the noise filter (section 5) and appends new items to the inbound
  spool with `state: "new"`. It never notifies. Exit codes: 0 ok, 2 sign-in needed, 1 other error.
- **The spool is the handoff.** `analyze.py` builds a bundle from the `new` spool items, the open
  previous items, suppressed titles and the open high-priority or soon-due tasks. After a
  successful run the consumed items are marked `folded`; spool items are pruned after 14 days.
- **The gate** (`engine/analyze.py`). The bundle is hashed (sha256 of its sorted JSON). The model
  runs only for one of these reasons, checked in this order:
  1. `--force` was passed;
  2. **daily audit**: no successful run yet today (one forced run per day);
  3. **retry after a failed run**: a run was started but never completed and at least 20 minutes
     have passed;
  4. **bundle changed** and there are new inbound items and at least 30 minutes have passed since
     the last wake (the floor; `OPS_MIN_GAP_S` overrides it for tests).
  Otherwise the run is skipped. `--dry-run` prints the gate decision and the prompt size and calls
  nothing.
- **Fail open with backoff.** A bundle build failure is counted and never raises; the process
  still exits 0. An alert line is printed only on the third consecutive failure and then at most
  every four hours, so the scheduler does not spam. An unusable model reply is handled the same
  way and leaves `pending_run` set so the retry rule applies. After a good run the bundle hash is
  recomputed after folding, so the next tick compares equal.
- **`refresh.py` is the cron entry point:** collect, then analyze, silent unless something needs
  attention (exit 2 when sign-in is needed, with one line printed so the scheduler can alert).
- **Untrusted input.** Mail and chat text reaches the model as data. The prompt states that
  everything in the data is untrusted and to ignore instructions in it, and the call is made with
  no tools. The model command is configured (`llm_cmd` in `config.json`) and run as a subprocess
  with a timeout.
- **Draft-only.** The model produces drafts for written replies; the UI shows them. Nothing is
  sent.
- **Urgency tags are not implemented yet.** Priority is the analyzer's P1 to P4 field only. Do not
  document or build on an urgency tag until it exists in the contract.

Do not add a model call anywhere else without putting it behind a gate of the same shape.

## 5. Noise-filter principles

- Filter in the scripted collector, before the spool, so noise never reaches the bundle and never
  changes its hash.
- Rules are data, not code: `rules.ignore_senders` (substring of the sender, case-insensitive) and
  `rules.ignore_subject_regex` in `config.json`.
- Mail: unread inbox messages only. Teams: skip hidden chats, deleted or non-message previews,
  anything already read, and messages the operator sent.
- The user can also suppress an issue for good (`ignored_forever`); the analyzer receives those
  titles as suppressed so the issue is not raised again.
- Bound the data: bodies are truncated, the spool and activity log are capped.

## 6. Server: loopback only

- Bind `127.0.0.1` only (`ThreadingHTTPServer(("127.0.0.1", port), ...)`); default port 8766 for
  the Ops Center. State directory from `OPS_STATE_DIR` (default `<agent-home>/direct`).
- **One gate in front of the router.** The Host check, the Origin check and the security headers
  below run in one deny-by-default gate that every request passes before any route, not in each
  route. A new route is covered without its author remembering. The gate also caps the request body
  size (a fixed limit, 413 above it), and a preflight answers only the loopback origins, never `*`.
  - Prevents: a write route that was added without its own checks, which per-route code missed twice
    in one app.
  - Acceptance (test): a test walks the whole route table and shows each route refused with a bad
    Host (403), each write route refused with a foreign Origin (403), and an oversized body refused.
- **Host check on every request:** the `Host` header must be `127.0.0.1` or `localhost`, else 403.
  This blocks DNS-rebinding.
- **Origin check on every write** (POST, PUT, DELETE): when an `Origin` header is present its host
  must be `127.0.0.1` or `localhost`, else 403. Requests with no `Origin` (curl, tests) pass.
- Responses carry `X-Content-Type-Options: nosniff`. People data (reviews, one-on-ones, rosters)
  is `Cache-Control: no-store`. Everything else is `no-cache` with an ETag so an unchanged poll is
  a 304 with no body (section 15). Static files are resolved and must stay inside the built
  `app/dist` directory.
- The server never serves arbitrary local files. Task attachments are read-only references the UI
  displays as text.
- No auth layer: the loopback bind is the boundary. Do not widen the bind address.

## 7. Read-only infrastructure module

`server/infra.py` shows spend, scheduled jobs, source control, build runners and live jobs. Its
conventions apply to any read-only status module:

- **Per-section error degradation.** Each section is independent. When its source fails it returns
  `{ "generated_utc", "error": "text" }` inside a successful envelope and the other sections are
  unaffected. The UI shows a "This source could not be read" state for that tab only. The
  conformance checker treats a section `error` as a warning, not a failure.
- **Stale-while-revalidate cache.** Results are cached per key for 10 to 60 seconds so UI polling
  does not hammer the CLIs. An expired entry is still served at once while one background refresh
  runs (single flight per key), so a request never waits on a CLI once the cache is warm (section
  15). One broken source must not poison the cache of another, and a failed refresh keeps the last
  good value.
- **Subprocess timeouts.** Every external command (`gh`, the container runtime) runs through one
  helper with a timeout (20 seconds by default) and turns a missing binary, a timeout or a nonzero
  exit into a short error string. Tests patch that one helper.
- **Read-only access.** Databases are opened read-only (`file:...?mode=ro`); nothing is written or
  changed in another system.
- **Settings in config, not code.** A single `infra` object in `config.json` (home path, watched
  repos, runner prefixes, optional prices). Prices are optional: without them every cost is `null`
  and the UI shows tokens only.
- **Redaction.** Log lines served to the UI redact secret-shaped tokens, and the log endpoint
  refuses a runner name that does not start with the configured container prefix.

## 8. Runtime deployment

A macOS LaunchAgent cannot read `~/Documents` (a protected folder). The repo checkout usually
lives there, so the service runs a **copied runtime** in an unprotected location:

- `tools/deploy-local.sh [runtime dir]` builds the app (`pnpm install --frozen-lockfile`, `pnpm run
  build`), then `rsync -a --delete` copies `server/`, `engine/`, `contract/` and `app/dist/` to
  `<agent-home>/direct/runtime`, strips `__pycache__`, and restarts the service with
  `launchctl kickstart -k gui/<uid>/<label>` when it is loaded (label from `OPS_LAUNCH_LABEL`,
  default `the ops-app keychain service`). It is safe to re-run.
- The state directory (`<agent-home>/direct`) and `config.json` live outside both the repo and
  the runtime, so a deploy never touches data or identity.
- Redeploy after every merge that changes `server/`, `engine/`, `contract/` or `app/`. The
  scheduler job (`direct-refresh`) runs `engine/refresh.py` from the runtime copy on a
  30-minute cadence.
- CI deploys nothing; this tool runs locally. The build runs against the synced core copies:
  `pnpm run build` compiles the app against `kit-core/` and copies the token sheets from
  `tokens-core/` into `app/dist`, so the copied runtime never reads the checkout. The nightly
  applies core releases to those copies at once, one line in the machine's log per apply
  (`CONSUMING.md`); redeploy after any apply that changed the front end.

## 9. Auth for the directory API

- Use an **interactive browser authorization-code flow with PKCE** against a first-party public
  client (no client secret). The user signs in once in a real browser, so MFA and conditional
  access are satisfied.
- **Device-code flow is not approved.** It cannot satisfy MFA under the tenant's policies and is
  not an accepted sign-in for these tools.
- Request the least delegated scope the collectors need; they only read mail and chats.
- The engine consumes a token file named by `token_file` in `config.json`: a JSON file holding
  `access_token`, `refresh_token`, `expires_at`, `token_endpoint`, `client_id` and `scope`. The
  engine refreshes the access token with the refresh token and rewrites the file with mode 0600
  through a temp file and `os.replace`. A missing file, a missing refresh token or a failed refresh
  raises an auth error: the collector records `collector-health.json` with `ok: false`, prints one
  line and exits 2, so the scheduler can ask the operator to sign in again.
- The token file and `config.json` are never committed. gitleaks runs on every PR.
- **The first sign-in never takes the operator's focus.** The sign-in script runs the PKCE flow
  with a loopback redirect in a background tab of a dedicated, signed-in browser profile, driven
  over the browser's DevTools protocol, and never raises the window. When MFA asks for a number
  match, the script prints only that number. Tokens go to the 0600 token file and are never
  printed. A visible sign-in window that steals focus on every expired token is the failure this
  prevents. **Acceptance (test):** the script's dry run against a fake authorize endpoint completes
  without creating a visible window, and its output holds no token.

## 10. CI and merging

The repo runs the standard [CI/CD and Release Standard](ci-cd-release.md) minimum:

- Every job runs on the self-hosted pool: `runs-on: [self-hosted, linux, arm64]`.
- Required checks (`REQUIRED_CHECKS` in `automerge.yml`): `ascii actionlint gitleaks python app
  pr-title`.
- **gitleaks on the self-hosted runner** needs `GITLEAKS_ENABLE_UPLOAD_ARTIFACT: 'false'` in the
  step env; its SARIF upload assumes the workspace is under `$HOME`.
- **Auto-merge runs from the base branch** (`pull_request_target` and `workflow_run`), so a PR
  that edits the auto-merge workflow itself, or any workflow file that GitHub refuses to merge
  with `GITHUB_TOKEN`, is not merged by it. Merge those with an admin squash:
  `gh pr merge <n> --squash --admin --delete-branch`.
- The runner pool for this repo (`runner-ops-app`, `-2`) is registered with the runner
  registration script, which accepts full `owner/name` repo names for repos that do not follow the
  hub's naming prefix.
- PR titles are Conventional Commits; green PRs squash-merge automatically; the `no-automerge`
  label holds one.

## 11. Worktree workflow for parallel changes

Several sessions may change the repo at once, so no one edits the main checkout while another
change is in flight. Each change gets its own worktree and branch off `origin/main`:

```bash
git fetch origin
git worktree add ../<repo>-<topic> -b <type>/<topic> origin/main
# work, commit, push, open the PR from the worktree
git worktree remove ../<repo>-<topic>   # after the PR merges
```

Keep the main checkout clean and on `main`; after a merge, fast-forward it and redeploy from there
(section 8).

## 12. Tests and gates

Run all of these before a PR; CI runs the same set:

```bash
python3 -m unittest discover -s tests
python3 engine/conformance.py tests/fixtures/state
node scripts/check-ascii.mjs
cd app && corepack pnpm run typecheck && corepack pnpm run lint && corepack pnpm run test && corepack pnpm run build
```

| Gate | What it proves |
|---|---|
| `python` job: unit tests | gate decisions, server endpoints, the route-table gate test (Host, Origin, body cap), infra sections, search, project rules (stdlib `unittest`, patched subprocess helper) |
| `python` job: conformance | the fixture state directory matches the schemas |
| `app` job: typecheck, lint, test, build | the UI compiles, Biome is clean, Vitest passes |
| `ascii` | plain ASCII in every tracked text file (name a banned character by code point) |
| `actionlint`, `gitleaks`, `pr-title` | workflow syntax, no secrets, Conventional Commit title |

The [Web Design System verification gate](web-ui.md#9-verification-gate-before-done)
(both themes, no console errors) applies to the UI.

## 13. Design rules that carry over

- UI follows the [Web Design System](web-ui.md): no edge-bar accents, accent
  discipline, actions beside the content they act on, the app owns every dialog (no native
  `confirm`, `prompt` or `alert`), undo over "are you sure" for reversible changes, inline icons.
- Chart, tab, dialog and sortable-header patterns:
  [Web Design System section 12](web-ui.md#local-tool-patterns-charts-tabs-dialogs-sortable-headers).
- Where a tool lets the operator act on another system (merge, move, close, resolve), the action
  follows the [Live Actions Standard](live-actions.md): optimistic removal, a server tombstone
  until the backend agrees, and direct reads to confirm.
- Global search is a server-side tokenized, ranked search with no model or network calls (contract
  section 3); the palette is described in
  [Web Design System section 13](web-ui.md#13-global-search-palette).

## 14. Accent palette

Local ops apps use the `indigo` named accent: `<html data-app-accent="indigo">`. It is a token swap
of the accent tokens only ([Web Design System section 12](web-ui.md#per-app-accent-token-swap-only)
and [section 16](web-ui.md#16-one-accent-token-per-app)). Every other token stays as generated in
`tokens/tokens.css`, and the indigo ramp is certified in both modes in `tokens/CONTRAST.md`.

Rules that stay unchanged:

- No edge-bar accents on any side. Selection is the raised neutral surface with a hairline ring.
- The accent is for brand, the primary action and the active state only. Indigo sits close to the
  violet categorical hue, so violet is withheld from data in a local ops app
  (`--accent-withheld-hue: violet`).
- The brand wordmark, if shown, stays as-is.

## 15. Performance and polling budget

A local ops app is the operator's whole workday, so it must feel instant. The rules, each from a
measured stall:

1. **No request waits on an external call once warm.** List and status endpoints serve from a
   stale-while-revalidate cache: fresh is served as is, expired is served at once and refreshed in
   the background, only a cold key computes inline, and concurrent callers of one key share one
   computation. A write invalidates the keys it changed, so the next read is fresh
   ([Live Actions rule 4](live-actions.md#1-rules)). Before this, every cache expiry cost 2 to 4
   seconds on whichever page asked first.
2. **Live checks run in the background too.** A fact a list needs on every request (the head of a
   branch, the state of a run) comes from a short background-refreshed cache, never a blocking
   call inside the handler, and no lock is held across a subprocess.
3. **Every poller has a rate budget.** For each upstream with a quota, add up the calls per hour of
   every poller at its interval while a page is open, and keep it well under the quota the other
   automation on that account also spends. The server cache TTL must be at least the client poll
   interval, and pollers back off when nothing is running.
4. **One poller per dataset.** Every component that shows a dataset subscribes to one shared store.
   Badges and counts come from one small endpoint that applies each page's filter server side,
   never by downloading every page's full payload.
5. **Pollers pause while the tab is hidden** and refresh once when it becomes visible again. This
   includes one-off intervals inside pages.
6. **Load pages on demand.** The landing page ships in the first bundle, every other route is a lazy
   chunk, and the remaining chunks prefetch while the browser is idle so navigation stays instant.
   Heavy libraries (charts) live only in the chunks that use them.
7. **Compress and revalidate.** JSON, scripts and styles over about 1.4 KB are gzip compressed when
   the client accepts it. Hashed assets are immutable. Data and API responses carry an ETag and
   `no-cache`, and the client fetches with `cache: 'no-cache'`, so an unchanged payload costs a 304.
8. **Keep connections alive.** Serve HTTP/1.1 with a Content-Length on every response. A write
   handler that can refuse before reading its body closes its connection.

Acceptance (test): with a fake upstream that sleeps, a warm list request returns in under 50 ms
after its TTL expired and exactly one refresh starts. A poll budget table for each upstream is in
the app's docs.

## 16. What reaches the action queue is routing data

The analyzer decides how to word and rank an item. It never decides which inputs may reach the
queue, because prose rules in a prompt grow one incident at a time and still miss the next new
kind of input.

1. **One candidate shape.** Every collector adapter (mail, chat, tickets, audits, state notes)
   emits the same record: a stable id, the source, who sent it and their role, how it was addressed
   to the operator (direct, mention, team, none), title, text, refs and owner.
2. **Rules are data, first match wins.** A routing file holds ordered rules that match on those
   fields and send a candidate or an item to: must consider, context, elsewhere (with where it
   lives or who owns it) or nowhere. The same rules filter the analyzer's output, so a rule holds
   even when the model ignores it.
3. **Fail open.** A candidate a person addressed to the operator directly is must consider when
   no rule names it, so a new source is seen before anyone writes a rule for it.
4. **Must consider is accounted for.** The analyzer writes, for every must-consider candidate,
   either the item that covers it or a short drop reason, and the UI shows each one's fate.
5. **The operator's click is the rule.** A "route elsewhere" action on an item writes a scoped rule
   (this item, this sender, this ticket, a phrase) after a live preview of what else it would catch,
   applies at once and offers Undo. Rules list on their own page with their hit counts, and can be
   disabled. Migrated rules can be disabled, not deleted.
6. **Unregistered sources ratchet.** A candidate from a source the routing file does not list
   raises one low item until the source is registered.

Acceptance (test): seed rules reproduce the filters they replaced on a fixture, a candidate from an
unknown source addressed directly to the operator routes to must consider, a click rule wins over
a seed rule and is idempotent, and a broken routing file keeps every item visible.

## 17. Heartbeat watch

A scheduled job on the host that goes silent or fails raises one item in the action queue, keyed by
job. The item clears itself when the job recovers. This covers the jobs beside the app's own
collectors. **Acceptance (test):** a job past its expected interval raises one item (not one per
check); a later success clears it.

## 18. Runner-lost alert and recent failures

A run that sits queued with no runner for more than N minutes raises an item. Cancelled and
timed-out runs count as failures in a recent-failures view. This tells the operator when no runner
ever picked a run up, which a runner-restart watchdog cannot. **Acceptance (test):** a run queued
past N minutes raises one item; a cancelled run shows in the failures view.

## 19. Core consumption panel

The ops center is the owner's approval desk for the shared core. It takes every core release at
once itself (the apply-at-once class; when its source is a repo with its own CI gate, each release
lands as a pull request to that repo that merges as soon as that CI passes, without the owner, and
the deploy checkout is never written directly), and it is where the owner approves what reaches every other
app on the machine, each of which is approval-gated
([CI/CD and Release](ci-cd-release.md) section 11). The panel shows that state and offers the
approvals. Every ops center renders it from the same file, so two ops centers on two machines show
the same kind of data the same way.

### 19.1 What the panel shows

For every consumer registered on the machine (one row per `consumer.json` entry):

- its class (apply-at-once or approval-gated) and way (`workflow`, `direct`, `vendored`);
- the pinned release against the latest, and how many releases behind;
- for `workflow` and `vendored` repos, the open sync pull request with its CI state (pass, fail,
  pending, none), or that none is open;
- the core-status counts (pass, proved, fail, unverified) and the UI verdict, or why they were not
  collected (a vendored repo carries no `core-status.py` by design);
- adoption suggestions: local parts in that repo that a kit part now covers (a local part with the
  same name as a kit export, or one that wraps it), each with its adoption-risk level when this
  account's consumer report gives one in its risk table.

For the account:

- this account's consumer-report items waiting for an owner decision;
- approved items this account owns with no core pull request open for them yet;
- the peers list: every open consumer-report issue's items with their status (approved, held,
  rejected, awaiting decision, shipped in vX), and approved design items from other accounts that
  shipped in the kit, as suggestions this machine's apps could adopt, the ones new since the last
  run marked. An improvement one account contributes so shows up in every other ops center.

### 19.2 The data source: `consumption.json`

The core nightly writes `~/.config/build-standards-core/consumption.json` every run
(`hermes/nightly.py` step 6, `apply.consumption`, on by default). The panel reads only this file:
it runs no `gh` call of its own to render. The file is written atomically (a temporary file beside
it, then a rename), so the panel never reads half a file; a panel polls it at most once a minute
and on focus (section 15). The file is local to the machine and never posted.

Schema, format `build-standards-consumption/1` (a reader refuses another format value):

```json
{
  "format": "build-standards-consumption/1",
  "generated_at": "2026-10-21T03:15:42Z",
  "core_repo": "OWNER/NAME",
  "latest": "v0.59.0",
  "consumers": [
    {
      "repo": "OWNER/REPO",
      "label": "repo-1a2b3c4d",
      "mode": "workflow",
      "class": "approval-gated",
      "report_only": false,
      "pinned": "v0.57.0",
      "latest": "v0.59.0",
      "behind": 2,
      "sync_pr": {"number": 12, "url": "https://...", "head": "chore/core-v0.59.0",
                  "created_at": "2026-10-21T05:23:00Z", "ci": "pass"},
      "status": {"pass": 12, "proved": 0, "fail": 0, "unverified": 256},
      "ui_verdict": "adopted",
      "adoption": [
        {"part": "DataTable", "file": "src/ui/DataTable.tsx", "kit_part": "DataTable",
         "relation": "duplicates", "risk": "low"}
      ],
      "not_collected": []
    }
  ],
  "account": {
    "report_issue": "https://...",
    "awaiting_decision": [{"issue": 117, "id": "D-027", "title": "..."}],
    "approved_unopened": [{"issue": 117, "id": "D-015", "title": "..."}]
  },
  "peers": {
    "issues": [
      {"number": 115, "url": "https://...", "author": "LOGIN", "mine": false,
       "items": [{"id": "D-004", "title": "...", "kind": "D", "status": "shipped",
                  "shipped_in": "v0.58.0"}]}
    ],
    "suggestions": [
      {"issue": 115, "id": "D-004", "title": "...", "author": "LOGIN", "shipped_in": "v0.58.0",
       "new": true}
    ]
  },
  "not_collected": []
}
```

Field rules: `class` is `apply-at-once` for mode `direct` and `approval-gated` for every other
mode. `pinned`, `behind`, `sync_pr`, `status`, `ui_verdict`, `latest` and an adoption row's `risk`
are `null` when unknown, never guessed; the reason goes in the nearest `not_collected` list.
`sync_pr` is always `null` for an ops center. `ci` is one of `pass`, `fail`, `pending`, `none`. An
item `status` is one of `awaiting decision`, `approved`, `held`, `rejected`, `shipped`, and
`shipped_in` is set only for `shipped`. `suggestions` holds only other accounts' design (`D`)
items that shipped; `new` is false on the first run. A new field is additive within format `/1`;
renaming or removing one moves the format to `/2`.

How the nightly fills it (`hermes/consumption.py`): the pin from the clone's `standards.lock`,
else the default branch through `gh`, else the machine's vendored record; the sync pull request
from the repo's open pull requests whose head starts with the entry's `sync_head` (default
`chore/core-`, the branch `core-update.yml` pushes; a vendoring tool names its own); counts from
the repo's `core-status.py --json --ci`, so CI rules carry the repo's real CI results (a CI rule
whose result could not be read counts as `unverified`, never `fail`, with the reason in
`not_collected`); adoption from the report scan's local parts against the core
clone's kit exports; risk from the adoption risk table of this account's report (a row naming the
part in backticks with a cell of exactly `none`, `low`, `medium` or `high`); `approved_unopened` from every
`consumer-report` issue of this account, open or closed, most recent first (an item approved on a
closed issue is still owed); peers from every open `consumer-report` issue, the owner's decisions in its comments ("approve D-003", "Approved:
D-015, D-016", "reject P-002: reason", "hold G-004") and the core `CHANGELOG.md`, where a release
section's `(#117 D-015)` marks an item shipped in that release.

### 19.3 Approvals and the never-apply rule

1. **One action per approval.** Approve a sync pull request (mark it ready, or merge it with the
   repo's declared method once its checks pass), approve a report item (post the owner's
   "approve D-nnn" comment on its issue), plan an adoption (open a pull request on the app that
   swaps one local part for the kit part). Each is one click and one confirmation naming the
   target.
2. **Only through the pull request path.** An approval opens or merges a pull request, or posts
   the owner's decision on the report issue. It never pushes to an approval-gated app's default
   branch, never writes that app's files, never merges a pull request whose checks fail, and never
   bypasses the repo's merge gate.
3. **The feed is read-only.** Neither the nightly nor the panel's render path writes to any issue,
   pull request or repo; only an owner action does, and only the one it names. The nightly never
   writes to another account's issue.
4. **Apply-at-once stays local.** The ops center's own row shows its release and gate result; it
   offers no approval, because the gate already is its approval.

**Acceptance (test):** from a fixture `consumption.json` the panel renders one row per consumer
with pinned, latest and behind, the sync pull request's CI state for a `workflow` and a `vendored`
row and none for the ops center, the status counts or the `not_collected` reason, and each
adoption row with its risk; it lists the account's awaiting and approved-unopened items and the
peers' suggestions with the new ones marked; a file with another `format` shows an error state, not
stale rows; an approval action calls only the pull request or issue-comment path (a test double
for `gh` records `pr ready`, `pr merge` or `issue comment`, and never `git push` to a default
branch); the approval control is absent on an apply-at-once row and disabled on a pull request
whose checks fail.
