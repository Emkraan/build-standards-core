# First-Party Build Standard

Version: 2.4 | Last reviewed: 2026-10-06 | Status: current | Scope: web (first-party)

**Canonical source:** this repo. This doc is the source of truth. Where a reference implementation differs, the implementation
is fixed, or the consumer records an explicit exception (README, "Source of truth and explicit
exceptions").

This doc covers architecture, the API contract, auth, data access, RBAC and engineering practice.
Related standards (not repeated here):

- Visual system: [Web Design System](web-ui.md)
- Pipelines, required checks, auto-merge, deploy and releases:
  [CI/CD and Release Standard](ci-cd-release.md)
- SQLite on the app platform: [Data Safety - SQLite](data-safety-sqlite.md)
- People data (Graph, team roster): [Identity and People Data](identity-and-people-data.md)

---

## 1. Stack

- **Client:** React 18 + TypeScript 5 + Vite 5 + Tailwind CSS v3, Recharts v3 for charts,
  lucide-react icons.
- **Server:** Node 22 + Express 4 + TypeScript (ESM, `.js` import specifiers in compiled output).
- **Data:** better-sqlite3, a single-file DB. No ORM; prepared statements only. The journal mode
  is environment-dependent (DELETE on the cloud host, WAL locally), see
  [Data Safety](data-safety-sqlite.md).
- **Shared types:** a `shared/` folder of TypeScript types used by both client and server
  (permissions, api, auth, domain types), imported via the `@shared/*` path alias. It is a source
  folder, not a pnpm workspace package. A repo that does split shared code into workspace packages
  keeps one Node pin across all of them and the pin check covers each package's `engines`.
- **Auth:** the app platform **platform-level auth** (the identity provider) for an app behind the platform, with the API checking the bearer token and groups ([Web API Runtime](web-api-runtime.md) section 6). An app that signs in itself with an OIDC library (a single page app calling its own API, [Web Client Runtime](web-client-runtime.md)) uses the client library for sign-in and the same bearer validation on the API. A local app has no auth layer ([Local ops app](local-ops-app.md)). Pick one model per app type and say which in the app's docs.
- **Hosting:** the app platform (Linux, `NODE:22-lts`). The client is built into `server/public`
  and served by the same process. Infra as code in `infra/` (Bicep).
- **Tooling:** pnpm workspaces, turbo, Biome (lint and format), vitest, Playwright + axe.
- **Config precedence:** `client/tailwind.config.js` is the active config (`.js` wins over
  `.ts`). Never keep a divergent `.ts` copy; it silently drifts.

### Node version pin

Node 22 is pinned everywhere, with one pin file and one value: `.nvmrc`, `package.json` `engines.node` (`>=22 <23`), in the root and in every workspace package, and every
`NODE_VERSION` / `node-version` in the workflows. better-sqlite3 is a native module whose ABI is
locked to the Node major it was built on, so a build on another major crashes the app on startup
(exit 1, before any output). `scripts/check-node-pin.mjs` fails CI on any mismatch, and Dependabot
ignores `@types/node` majors above 22.

## 2. Repository layout

```text
example-org-hub/
  package.json          # packageManager pnpm@12.8.1; root scripts call turbo / pnpm --filter
  pnpm-workspace.yaml   # workspaces: client, server; allowBuilds; security overrides
  turbo.json            # build / typecheck / test / lint tasks
  biome.json            # lint + format (2 spaces, single quotes, width 120)
  commitlint.config.mjs # conventional commits, same type list as the PR title lint
  client/               # React app (src/core = shell/design system/charts/auth; src/tools/<tool>)
  server/               # Express (src/core = db/middleware/lib/routes; src/tools/<tool>/router.ts)
  shared/               # types shared by client and server (types/*.ts)
  e2e/                  # Playwright smoke + axe, a11y-baseline.json
  scripts/              # CI gates and deploy packaging (see the CI/CD standard)
  infra/                # Bicep (App Service, platform-level auth authsettingsV2)
  docs/                 # DEPLOYMENT.md (runbooks), integration notes
```

### Commands (root)

| Command | What it does |
|---|---|
| `pnpm install --frozen-lockfile` | install; the lockfile is never regenerated in CI |
| `pnpm run typecheck` | `turbo run typecheck` (client and server) |
| `pnpm run lint` | `biome lint .` |
| `pnpm run lint:fix` | `biome check --write .` |
| `pnpm run test` | `turbo run test` (vitest) |
| `pnpm run build:all` | `turbo run build` (client into `server/public`, server `tsc`) |
| `pnpm run check:rbac` / `check:openapi` | RBAC/SysArch lockstep and OpenAPI checks |
| `pnpm run check:unicode` / `check:node-pin` | banned Unicode scan, Node pin check |
| `pnpm run check:dialogs` | fails on browser-native `confirm` / `prompt` / `alert` in client code |
| `pnpm run test:e2e` | Playwright smoke + axe |
| `pnpm run check:bundle-size` | bundle budget; `bundle-size:update` rewrites the baseline |
| `pnpm run dev:server` / `dev:client` | local dev |

### Per-tool structure

```text
client/src/tools/<tool>/
  index.tsx      # module root: <ToolModule> with its own <Routes>
  api.ts         # all apiFetch calls for this tool
  views/         # sub-views (optional)

server/src/tools/<tool>/
  router.ts      # Express Router; mounted at /api/<tool> in server/src/index.ts
```

## 3. API contract

- Every endpoint returns the envelope `ApiResponse<T>` from `shared/types/api.ts`:
  `{ success: true, data }` or `{ success: false, error }`. Never `res.sendStatus`; always JSON, so
  clients can parse errors.
- The client uses a single **`apiFetch<T>`** wrapper per tool: `credentials: 'include'`, wraps
  `res.json()` in try/catch, throws `json.error` on `success: false`. Fire-and-forget writes (usage
  logging) use `.catch(() => {})`.
- Mutations are `POST/PUT/DELETE`; reads are `GET`. An upstream WAF may block authenticated
  POST-with-body in some environments (TD-007): if a write returns 403 in production but GET works,
  it is a network/security WAF rule, not the app.
- Every new route is reflected in the OpenAPI document; `check:openapi` fails CI otherwise.
- Ops routes for pipelines (`/api/ops/*`) use a Bearer secret instead of platform-level auth, see the
  [CI/CD standard](ci-cd-release.md#6-deploy).

## 4. Auth (platform-level auth)

- The server trusts the `x-ms-client-principal` header (base64 JSON claims: email, name, groups,
  oid). `authsettingsV2`, `requireAuthentication: true`, `RedirectToLoginPage`, token store on.
- platform-level auth is **method-agnostic**: it does not discriminate GET vs POST.
- Excluded paths: `/health` and `/api/ops/*` only (pipelines have no identity provider identity).
- Dev: `DEV_BYPASS_AUTH=true` (+ `DEV_USER_*`) in development or test only (never staging or an unset environment), and a boot preflight refuses a production start while the bypass or a dev user is set; a client dev-fallback user seeds
  a full-access identity when `/api/me` is unreachable, so the UI renders without a backend.
- `ENFORCE_EASY_AUTH=true` fails closed in production when platform-level auth is not confirmed in front.

### `AuthUser` shape (shared type, `shared/types/auth.ts`)

```ts
interface AuthUser {
  name: string; firstName: string; email: string; objectId: string;
  groups: string[];                   // identity provider group IDs
  role: Role;                         // display role key (highest rank matched)
  primaryRole: Role;                  // same; use for display
  roleLabel: string;                  // human label for display role
  permissions: string[];              // effective union (or ['*'] for full admins)
  rolePermissions: Record<string, string[]>; // per-role sets for View-As preview
  rolesMeta: Record<string, RoleMeta>;       // label/color/rank/isSystem/isAdmin per role key
  hasAccess: boolean;                 // authenticated AND has at least one grant
  grantSource: string;                // 'bootstrap' | 'code' | 'user' | 'group'
}
```

## 5. Data and migrations

- One DB module (`server/src/core/db/index.ts`) owns the schema (`CREATE TABLE IF NOT EXISTS`),
  prepared-statement helpers, and a `runMigration(key, fn)` runner tracked in `applied_migrations`
  (each key runs once). Idempotent backfills use `INSERT OR IGNORE` / `ON CONFLICT`.
- **Migrations are forward-only and additive:** new tables, guarded `ADD COLUMN` (`hasColumn`),
  keyed data migrations. Never drop, rename or rebuild a table or column, and never add a
  `NOT NULL` column without a default (it breaks rollback to older code). The CI
  `migration-safety` job enforces this.
- No `Date.now()` / `Math.random()` assumptions in migrations beyond SQLite `datetime('now')`.
- Seeds run on first init (empty-table guard); migrations cover upgrades of existing DBs, so nobody
  loses access or data on deploy.
- **The DB is opened only through `initDb`** (via the lifecycle in `server/src/core/db/lifecycle.ts`).
  No script, route or tool opens the database file directly. The full rule set is in
  [Data Safety - SQLite](data-safety-sqlite.md).
- People are never seeded or created from name-only data; see
  [Identity and People Data](identity-and-people-data.md).

## 6. RBAC / access control (the model)

The full, canonical access-control rules (guards, scope, ownership, no-escalation, the
route-guard CI gate, the add-a-tool checklist) are in the [RBAC Standard](rbac.md). This
section summarizes the data model.

- **Permissions** - named strings, convention `tools.<tool>.<resource>.<action>` (+ `hub.<action>`
  for hub-level). A `PERMISSION_CATALOG` (label/description/**group**) drives the admin matrix,
  grouped by tool. Granularity is **per-capability**: each tool exposes View + its meaningful
  actions (e.g. On-Call view/swap/roster/generate; Ops view + workload.view; Team Links view/manage).
- **`hub.admin` is an umbrella** - `checkPermission` treats it as implying every `hub.admin.*`
  sub-right (access/roles/audit/health). `*` implies everything.
- **Roles** - DB `roles` (key, label, color, rank, is_system, is_admin). 4 seeded system roles
  (Super Admin / Engineer / Analyst / Viewer) + admin-created custom roles. `role_permissions`
  holds arbitrary per-role permission sets; an `is_admin` role implicitly holds `*`.
- **Grants** - DB `access_grants`: each user email OR identity provider group maps to one role
  (`UNIQUE(subject_type, subject)`). Authenticating grants nothing; access requires a grant.
- **Resolution = ADDITIVE UNION.** A user's effective permissions = the union across EVERY matched
  grant (their direct grant + all mapped identity provider group grants). Display role = highest rank; any
  matched admin role contributes `*`. (In `server/src/core/middleware/auth.ts`.)
- **Enforcement** - server-side `authorize(p)` / `authorize.any(...)` (aliases
  `requirePermission` / `requireAnyPermission`) on every route, returning JSON 401/403; CI fails
  any unguarded route. See [RBAC Standard section 3](rbac.md#3-guards-server). Prefer **path-scoped granular gates** for tools with
  sub-sections: a blanket `requireAnyPermission(...all sub-rights)` to open the tool + per-path
  `requirePermission(specific)` (the umbrella keeps full admins passing all). Client `can(p)` is
  show/hide only - never the security boundary.
- **Code super-admin pattern** - a `CODE_SUPER_ADMINS` list in the DB module asserts a `hub-admin`
  grant on **every startup** (`ON CONFLICT DO UPDATE`), guaranteeing admin access in code
  (independent of the `BOOTSTRAP_ADMIN_EMAILS` env break-glass). `isCodeSuperAdmin(email)` guards
  every mutation that could remove/downgrade them (delete-user, downgrade-grant, revoke-grant); the
  seen-users API flags them `isProtected` so the UI disables the controls.
- **Admin UX** - ONE unified **Access Control** plane (segmented sub-nav: Roles & Permissions |
  Grants | Effective Access), on the design system. The **Effective Access** resolver mirrors the
  server union client-side: pick a person -> resolved role + contributing grants + effective
  permissions grouped by tool. Role badges MUST pass freshly-fetched label/color (the auth user's
  `rolesMeta` is captured at login and goes stale after a rename).

## 7. Navigation and tools manifest

A single `TOOLS` manifest (`client/src/navigation.ts`) is the source for the hub grid, the hub
sidebar, the tool sidebar sub-nav, and the Cmd+K command palette.

This section describes a single app whose tools are folders of one build. A shell that hosts several
modules generates its registry and its one icon map from per-module manifests instead
([web-shell.md](web-shell.md) section 3), and the hand-kept `TOOLS` array and `ICON_MAP` rule below
do not apply to it.

### `ToolManifest`

```ts
interface ToolManifest {
  id: string;
  label: string; description: string;
  icon: string;             // Lucide icon name (must exist in every ICON_MAP)
  path: string;             // root path e.g. '/on-call'
  viewPermission: Permission;               // single permission gating visibility
  viewAnyPermission?: Permission[];         // show tool if can ANY - for tools with granular sub-rights
  accessPrefixes?: string[];                // permission key prefixes that also open the tool (e.g. a guest prefix), never narrower than the server
  visibleTo?: (subject: Subject) => boolean; // extra test for scoped grants a permission list cannot express, ANDed with the checks above
  hiddenWithPermission?: Permission;        // hide this entry from callers who hold this permission (a page folded into one they can already open)
  hue?: string;                             // the tool's categorical hue name (web-ui.md section 17), never a colour literal
  status: 'active' | 'beta' | 'coming-soon';
  iconClass: string;        // Tailwind classes for the icon container
  nav: NavLink[];           // sub-nav items for the tool sidebar
}
```

`Subject` is the signed-in caller as the auth context holds it: the effective permissions plus the
scoped grants ([RBAC](rbac.md)).

### `NavLink`

```ts
interface NavLink {
  label: string; path: string; icon: string;
  permission?: Permission;      // show if can(permission)
  permissions?: Permission[];   // show if canAny - for items gated by "A OR B"
  external?: boolean;           // opens in new tab with ExternalLink indicator
  previewFlag?: string;         // shown only while Preview mode is on and this flag is registered
  end?: boolean;                // exact-match active state; set on a section root that has child
                                // pages (e.g. '/team-links/raci') so it is not highlighted on them
}
```

### Visibility helpers (exported from `navigation.ts`)

```ts
canViewTool(tool: ToolManifest, can: (p: Permission) => boolean, subject?: Subject): boolean
// -> (tool.viewAnyPermission?.some(can) ?? can(tool.viewPermission))
//    && (!tool.hiddenWithPermission || !can(tool.hiddenWithPermission))
//    && (!tool.visibleTo || !subject || tool.visibleTo(subject))

canViewNavItem(item: NavLink, can: (p: Permission) => boolean, preview?: (flag: string) => boolean): boolean
// -> (item.permissions?.some(can) ?? (item.permission ? can(item.permission) : true))
//    && (!item.previewFlag || (preview?.(item.previewFlag) ?? false))
```

The route guard admits a caller who holds any permission under the tool's `accessPrefixes`,
globally or scoped, so it is never narrower than the server; the server still enforces every route.
`previewFlag` builds a whole area behind a flag on production with no branch deploy: the entry and
its routes appear only for a viewer who turned Preview mode on, and only for a registered flag.
**Acceptance (test):** a tool with `hiddenWithPermission` is hidden from a caller holding that
permission; a nav item with an unregistered or switched-off flag is hidden; a caller holding only a
permission under an access prefix reaches the tool.

### Usage sites

- `HubPage.tsx` - `visible = TOOLS.filter(t => t.status === 'coming-soon' || canViewTool(t, can))`
- `HubSidebar.tsx` - same filter (only non-coming-soon)
- `ToolSidebar.tsx` - `tool.nav.filter(item => canViewNavItem(item, can))`; active state uses
  `end={item.end ?? item.path === tool.path}`
- `App.tsx ProtectedAdmin` - `canViewTool(TOOLS.find(t => t.id === 'admin')!, can)`

### ICON_MAP consistency

Every tool icon string used in `TOOLS` must exist as a key in **every** `ICON_MAP` object:
`HubPage`, `CommandPalette`, `HubSidebar`, `ToolSidebar`. They are separate maps - keep in sync.

### Admin tool nav item gating

Admin sub-nav items carry **specific** sub-rights (not the blanket umbrella), so granular-admin
users see only their permitted sections:

- Overview: no permission (all admin variants see it)
- Access Control: `permissions: [HUB_ADMIN_ACCESS, HUB_ADMIN_ROLES]`
- Audit Log: `permission: HUB_ADMIN_AUDIT`
- System Health: `permission: HUB_ADMIN_HEALTH`

`checkPermission` umbrella logic ensures a full admin (`hub.admin`) still passes all of these
because `hub.admin -> hub.admin.*` is the defined umbrella rule.

### Hosting one tool's pages inside another tool

When a tool becomes a sub-section of another (reference: RACI under Team Links,
`/team-links/raci`), keep its own permissions and gate each section separately:

- Host manifest: `viewAnyPermission: [HOST_VIEW, GUEST_VIEW]` and add the guest prefix to
  `accessPrefixes` (e.g. `['tools.team-links.', 'tools.raci.']`) so either right opens it.
- Every nav item carries its own `permission` (host pages `HOST_VIEW`, guest pages `GUEST_VIEW`);
  no un-gated items once the tool is shared.
- Every route in the host module checks the same permission (`can(P) ? <Page /> : <Denied />`);
  `Denied` sends a guest-only user to the guest section rather than the hub.
- The server API stays where it was, under the guest's own guards; nothing changes there.
- Remove the guest's `TOOLS` entry and redirect its old root (`/raci/*` -> `/team-links/raci/*`)
  so deep links keep working.

## 8. Verification gate

A change is not done until all of these hold:

1. `pnpm run typecheck`, `pnpm run lint` and `pnpm run test` pass locally; `pnpm run build:all`
   builds.
2. The change is verified in the running app, in **both dark and light** themes, with no console
   errors, and a screenshot is kept as proof. Dev has no live external data for some tools; use an
   isolated Vite preview harness with representative data when needed.
3. Every required CI check is green on the PR (the list is in the
   [CI/CD standard](ci-cd-release.md#2-required-ci-checks)). CI is the gate, not a
   suggestion: no check is skipped, and a lowered threshold needs a written reason.
4. Security- or system-wide changes get an adversarial review (independent critics by dimension,
   then a verifying synthesis). Fix confirmed findings; document intentional deviations.

### 8.1 One local gate

Ship one script, run as `pnpm run verify`, that runs what CI runs: typecheck, lint,
every `check:*` guard, the full build, the bundle-size check, the tests and the same pinned static
analysis scan CI uses. A finding that would only surface after merge then fails before push. CI
stays the gate; the script is the same gate run early, and it must fail on the first non-zero step.

## 9. Engineering practice

- **Small, self-contained PRs** with a conventional-commit title (it becomes the squash subject and
  drives the semver bump), a descriptive body, squash-merged to `main`, branch deleted. Keep the app
  working at every merge (build additively, swap at the end). Versions are computed by the deploy
  workflow from commit subjects; do not hand-bump versions per PR.
- No em dashes, curly quotes, NBSP, zero-width characters or other banned Unicode in code files
  (`check:unicode` enforces it); first person in the owner's deliverables; assess clinical impact
  before any infrastructure change.
- **State files** (`app-state/engineering-state/`) are rewritten to stay current
  (append-only for `technical-debt.md`).
- **Standards stay current.** If a change here alters a convention, pattern, CI rule or design
  token, update this repo (`this repo`) in the same piece of work.

## 10. Global search (hybrid semantic)

Every first-party app with more than one kind of record gets one global search that covers
everything the user can see, opened from the top-bar search pill, Cmd/Ctrl+K and `/`. The UI is
the command palette in [Web Design System section 13](web-ui.md#13-global-search-palette).
Reference implementation: the local ops app Command Center v1.2.0 (`the command-center app/server.py`
`/api/search` + `index.html` `buildIndex` / `hybridSearch`).

### Ranking: lexical first, semantic blended in

- **Lexical (always on, client or server):** BM25 over every record, field-weighted (title 3x,
  body 1x, parent/project name lower), light stemming, a curated domain synonym list
  (device/endpoint/laptop, cert/certificate/renewal, MDM/ExampleMDM/OtherMDM/the device-management system,
  ticket/ExampleITSM/CHG/INC, and so on), typo tolerance (Damerau edit distance 1, or 2 for words
  of 7+ characters, also matched against the synonym dictionary), prefix match on the word being
  typed, and soft-AND (documents covering more query words rank higher). Filter tokens such as
  `is:open`, `is:overdue` and `is:high` narrow lexically and skip semantic.
- **Semantic (when available):** cosine similarity between a query embedding and cached document
  embeddings. Final score = 0.55 x normalized lexical + 0.45 x normalized semantic. Results that
  match only semantically are included above a threshold and labeled "Related by meaning".
- Lexical results paint immediately; semantic results arrive after a ~180 ms debounce and
  re-rank in place. A stale response (the query changed) is dropped.

### Embeddings: where they run

- **Patient or otherwise sensitive data never goes to an external embedding API.** Local tools
  use **Ollama** on the same machine (Homebrew install, `brew services`), model
  **`nomic-embed-text`** (about 262 MB). Hosted apps use only an embedding endpoint that has been
  approved for that data class; until one is approved, hosted apps ship lexical-only, which is a
  complete, compliant implementation on its own.
- `nomic-embed-text` requires task prefixes, each followed by one space: `search_document:` on
  indexed text and `search_query:` on the query. Omitting them measurably degrades recall.
- Thresholds are model-specific and must be calibrated with a nonsense query when the model
  changes. For `nomic-embed-text`: unrelated text scores about 0.45 to 0.52, real matches 0.6+;
  server floor 0.45, client normalization floor 0.5, semantic applied only when the best score
  exceeds 0.56, semantic-only results kept at normalized 0.4 or higher.

### Index and cache

- One document per searchable object (record, note, attachment, project, activity entry) with a
  **stable key** shared by server and client (`task:<id>`, `note:task:<id>:<i>`,
  `file:<id>:<i>`, `project:<id>`, `activity:<ts>`). The server returns `{key, score}` only;
  the client owns display and the access-filtered document set.
- Embeddings are cached by **SHA-1 of the document text**, so only new or edited text is
  re-embedded. The cache records the model name and is discarded on a model change. Writes are
  atomic (temp file + rename); orphaned vectors are pruned. Batch embed calls (64 per request).
- In multi-user apps, search results are filtered by the same access rules as the records
  themselves (section 6) before they leave the server. Never return a key the caller cannot read.
- **File contents are indexed, not just names.** The full-text index keeps up to 100,000 characters
  of text per file, so a hit shows the matching passage with the query words highlighted, not only
  a file name.
- **The index reports its own health.** A health endpoint returns the documents whose source
  changed after they were indexed (stale), the files the indexer skipped and why, and saved links
  that no longer resolve. The search page shows a line when any count is non-zero.

### Degradation

`/api/search` returns `{available: false}` when the embedding service is down or the model is
missing; the UI falls back to lexical search and says so in the palette footer
("Keyword search only"). Search must never fail or block because the model is unavailable.

## 11. Live data from integrations

Integrations (the hub's API-key ingest platform) are the single path for real operational data.
Any view that shows a number an integration already owns (a fleet count, an online/offline split,
a version distribution) reads it from the integration's latest snapshot. It never copies it into
seed data or authored content, where it goes stale.

- **Declare, don't copy.** Bind the element to the integration declaratively. In Systems
  Architecture a node carries `props.liveBinding` (`integration`, `countProp`, `countTrue`,
  `groupBy`, `distinct`, `excludeWhenTrue`, `labelTemplate`; type `ArchLiveBinding` in
  `shared/types/systems-architecture.ts`).
- **Overlay at read time, never write back.** The server computes the live values when the record
  is read (`server/src/tools/systems-architecture/liveData.ts`, applied in `GET /:key`). The stored
  record stays the authored baseline, so routine ingests never create version-history entries or
  edits.
- **Degrade to the authored value.** With no snapshot, or a failed computation, the element keeps
  its authored values and is marked `no-data`. A fetch must never fail because an integration is
  empty or malformed.
- **Show provenance and staleness.** The server stamps `liveData` (integration, `ingestedAt`,
  `staleDays`, `stale` from the integration's `staleAfterDays`). The UI shows the source and
  ingest time, with a warning when stale.
- **Aggregate only.** Bindings produce counts and distributions, never per-record detail, so a
  diagram does not become a second copy of the inventory.

---

**Bottom line:** new first-party builds start from this document, the
[Web Design System](web-ui.md) and the hub code. Match its tokens, primitives,
no-edge-bar accent rule, orange discipline, API envelope, platform-level auth, additive-union RBAC, CI gates
and verification gate. Deviate only with a documented reason.

## 12. Multi-module shell

Details are in [web-shell.md](web-shell.md): the two shapes (several apps on one origin, or one
shell with many modules), the generated registry, standalone-or-hosted modules, per-module CSS and
storage scope, one accent per mounted module and the safe return-target bounce.
