# Shell shared packages

Applies to a multi-module shell ([web-shell.md](web-shell.md)). A shell keeps its cross-module logic in a few
shared packages that every module's client and server import, so a rule has one implementation. This document
says which packages a shell has, what each owns, which parts the core ships as code, and where the
core already states the rule.

## 1. The packages

| Package | Owns | Core status |
|---|---|---|
| Module contract (`console-modules`) | The per-module manifest ([web-shell-manifest.md](web-shell-manifest.md)): the validator, the registry checks, the permission source and peer helpers, the layout merge with its typed contracts, the generated registry and its staleness check | Code: `shell-packages/console-modules/`. The generator is `kit/scripts/build-registry.mjs` ([web-shell.md](web-shell.md) section 3) |
| RBAC core (`rbac`) | What permission data means: accessible tabs, the grant ceiling, assignable roles, view-as, client access helpers | Code: `shell-packages/rbac/` |
| Client package (`app-client`) | One sign-in boot, token renewal, the API client and its cache, resource hooks, the live feed strip | Code: `shell-packages/app-client/` (TypeScript source). Rules: [web-client-runtime.md](web-client-runtime.md) sections 1 to 3, 5 and 6, [web-shell.md](web-shell.md) section 8 |
| External tools package (`external-tools`) | Tools that live outside the shell's repository, kept in data and shown in the launcher: validation, who may see a tool, the audited admin routes | Code: `shell-packages/external-tools/`. Opt in. Rules: section 5.7 |
| Announcements package (`announcements`) | Platform announcements for the console feed strip: validation, the cached active read, the audited admin routes | Code: `shell-packages/announcements/`. Opt in. Rules: section 5.6 |
| Jobs package (`jobs`) | Scheduled jobs inside a tool's API: a daily runner in Eastern time with a live on/off switch per job, and the `GET /jobs` contract the console Scheduled jobs tab reads | Code: `shell-packages/jobs/`. Opt in. Rules: section 5.4 |
| Audit package (`audit`) | A Postgres audit log with a tamper-evident hash chain: write, transaction, reads, `verify` | Code: `shell-packages/audit/`. Opt in. Rules: section 5.5 |
| Settings package (`settings`) | A sealed secret box and plain application settings the console edits at runtime | Code: `shell-packages/settings/`. Opt in. Rules: section 5.5 |
| Server package (`app-server`) | Group cache, directory token, CORS and origin guard, Server-Timing, gateway token check, request telemetry with its export retry, What's new handler | Code: `shell-packages/app-server/`. Rules: [web-api-runtime.md](web-api-runtime.md) sections 1 to 7 |

The code is plain ESM with hand-written `.d.ts` files, no runtime dependency and no build step, so a CommonJS
server and a bundled client both import it. A shell takes it by copying the folder into its shared packages
directory and recording the core release in its lock file; the core's CI proves it with the tests listed in
section 6. Nothing here syncs into a consumer on its own.

## 2. Module contract

`validateManifest(manifest)` returns a list of problem strings and never throws. `validateRegistry(manifests)`
adds what one file cannot show: unique ids, the `console` module, a permission source that exists, owns its
permissions and matches the module's shape, base, `me` path, gateway, prefix and scope env, and peer permission
ids that name a module which exists, owns its permissions and is not shape `console`. The helpers are
`peerRef`, `peerModules`, `permissionSourceId`, `ownsPermissions`, `canOpen` (any-of over a `has` the host
supplies) and `autoDescription`.

Every answer is display routing. A module's own server enforces each page and action ([rbac.md](rbac.md)
principle 1); the rail showing an entry never grants it.

The problem strings name the module a "tool" and `autoDescription` writes "Pages: A, B and C." and "This tool" for a
manifest with no name. That is the wording the Olympus shell shipped with and its users read, so the core keeps it.

### 2.1 The layout merge

One rule turns the manifests plus an admin's saved layout into what the shell renders. It is pure and
deterministic, takes the admin's rows as plain arrays (the store behind them is the shell's own), and never throws on
a bad row: a bad row is skipped.

| Function | Answers |
|---|---|
| `effectiveLayout(manifests, overrides, { registryIds })` | `{ modules, orphaned }`. A code entry with no override renders at its code default and is flagged `isNew` (a cue for the admin only). An override whose code entry is gone is reported in `orphaned` and never rendered. A page's `requires` always comes from code: an override cannot change it. A custom link renders only with a valid https `href`, and its optional permission must be in that module's `registryIds` when the ids are given. A hidden group hides its entries; an entry moved to a missing group falls back to its code group. A module's description is the admin's text, else the manifest's, else `autoDescription`. Modules sort by `order`, then id |
| `visibleNav(module, has)` | What one caller sees of a module: hidden entries and groups dropped, entries the caller cannot open dropped, empty groups dropped. `has` is the module's own permission check |
| `landingRoute(module, has)` | The first landing route whose page the caller can open, else the first page they can open, else `null`. A hidden page still counts, so hiding a rail entry never strands someone whose only page it is |
| `visibleTiles(module, dashboard, has)` | A dashboard's tiles in admin order, hidden tiles and tiles without the caller's permission dropped |
| `homeContributions(modules, hasFor)` | The Home actions and feeds whose permission the caller holds in the module's own answer. `hasFor(module)` returns that module's `has`, or `null` while the answer is not known: a module with no answer contributes nothing (fail closed). A peer id never opens a Home entry; a disabled module contributes nothing |
| `moduleForPath(pathname, moduleIds)` | The module a path belongs to: the first segment when it names a module, else `console` |

**Unknown keys are carried, not dropped.** A key the contract does not name, on a module, a group, a page, a link or a
tile (a consumer's own `jobs` list, say), comes through `effectiveLayout` as a deep copy on the matching output
entry, so a reader of the layout finds it. `validateManifest` ignores such keys, as the manifest standard says. A key
that names a field the layout computes (`enabled`, `account`, `basePath` and the like) never shadows the computed value,
and `client` stays out of the output as before.

The types (`ModuleManifest`, `Overrides`, `EffectiveModule`, `NavEntry`, `TileOut` and the rest) are in
`index.d.ts`, so a client that reads the layout is typed instead of `Record<string, any>`. Every answer is display
only, like the rest of section 2.

## 3. RBAC core

Pure functions with no database, no HTTP framework and no UI library. Each module keeps its own permission
registry and its own role, assignment and override tables; the package decides what that data means.

| Function | Side | Purpose |
|---|---|---|
| `permissionsBeyond` | server | Grant ceiling: ids a write would confer that the caller does not hold. The wildcard only from a genuine wildcard holder; an id the registry no longer defines is not dropped (fail closed) |
| `removalBeyond`, `removalCeilingMessage` | server | The removal ceiling ([rbac.md](rbac.md) section 3): deleting a role, an assignment or an override takes away the permissions it confers, so the caller must hold every one of them, and only a genuine wildcard holder removes the wildcard. Pass the permissions of the thing being removed (the role's for a role delete or the assignment of that role, the stored list for an override). Same answer as `permissionsBeyond`, with its own message |
| `annotateRoles`, `assignableRoleIds` | server | Per-role `assignable` and `unknownPermissions` (registry drift) |
| `grantableIds` | server | Registry ids the caller may grant |
| `accessibleTabs` | server | Tabs a permission set opens, computed from the registry, so a client never infers access from id strings |
| `viewAsPreview` | server | A preview under the caller's ceiling, carrying the subject's own ceiling |
| `createAccess`, `canAssignRole`, `canGrantPermission`, `filterRegistry`, `activeGrantable` | client | Show and hide only, fed by what the server sends |
| `cleanOid`, `userRowMatches`, `pickUserRow` | server | Which stored user row (a role assignment or a permission override) binds a person. A grant to a person is bound to their directory object id, which never changes; the email is a label and is the match only for older rows with no object id. A caller whose token has no object id matches only rows that have none (fail closed), and `pickUserRow` prefers the row bound to the id whatever the row order. A rename, a sign-in name change or a reused name never moves or loses a grant that carries an id. Opt in: a module with no `user_oid` column never calls them |
| `stripRetiredPermissions`, `findPermissionLiterals` | build and test | Remove retired ids from stored lists; find permission ids named in source so a registry-conformance test fails on an id the registry lacks |

Grammar: `tab:<name>`, `action:<name>:<verb>` and the wildcard `*`. [rbac.md](rbac.md) section 2 names
permissions `tools.<tool>.<resource>.<action>` and `hub.<area>`. That is a different grammar and a documented
exception, not a failure: the ceiling, assignable-role and view-as functions treat an id as an opaque string and
work with either; `accessibleTabs`, `createAccess(...).hasTab`, `findPermissionLiterals` and the manifest
validator read the `tab:` and `action:` forms. A host on the other grammar uses the first group and keeps its
own tab logic, and records the exception for the manifest rules.

## 4. Client package

TypeScript source that each app compiles itself (no build step). Peer dependencies: React, `@azure/msal-browser` and the
kit (for `FeedStrip` and `safeHref`), imported under the neutral peer name `@shell/kit`. The consumer maps that name to its own
kit once, so no core source is edited whatever the kit package is called (the core's own `kit/` maps it to
`./src/index.ts`). The folder has one entry, `src/index.ts`.

**The kit peer alias.** One line in the client package's `package.json` covers typecheck, test and bundle, because Node
resolution, TypeScript, the test runner and the bundler all follow it:

```json
{ "dependencies": { "@shell/kit": "npm:@example/kit@*" } }
```

`@example/kit` is the consumer's own kit package; in a workspace the alias resolves to the workspace copy (the same
line in the workspace protocol of the package manager in use). A build that cannot use a dependency alias maps
`@shell/kit` instead in `tsconfig` `paths` and in the bundler and test runner alias, as the core's own `kit/` does. Either
way the mapping lives in the consumer's configuration, never in core source.

| Export | Purpose |
|---|---|
| `createAuth` | One sign-in boot for the whole shell. The shell and every module share one origin, one single page app registration and one `localStorage` token cache, so a shell session is visible to every module and a module never renders its own sign-in. `mode: 'shell'` owns the sign-in surface; `mode: 'module'` bounces a signed-out caller to it and gets sent back. Silent renewal first, an interactive redirect only when needed, a loop guard that stops a repeating redirect, and a distinct answer for a configuration error ([web-shell-auth.md](web-shell-auth.md) section 3). `devBypass` skips the sign-in only on a local dev host with no client id |
| `createOidcAuth`, `createOidcClient` | The second sign-in shape ([web-shell-auth.md](web-shell-auth.md) section 2.1): the same `createAuth` over an OIDC manager (oidc-client-ts or anything with its few methods) the app builds and passes in, for a fleet that signs in through an identity broker. The package takes no OIDC dependency |
| `RETURN_TO_KEY`, `safeReturnTo` | The same-origin return target. Protocol relative, backslash and control character targets, other origins and the bare root are refused, and dot segments are resolved before the check |
| `createApi`, `qs` | The API client: bearer token from the shared auth, one error contract (`ApiError` with status and details), one request for identical concurrent GETs, a stale-while-revalidate cache with a freshness window per key, opt-in `sessionStorage` persistence for identity reads only, a configurable answer to a 401 and a cache that a logout or account change clears |
| `createStore`, `defaultStore`, `isStale` | The resource store behind the client and the hooks: subscribers, one request per key, a waiting fetch re-run after an invalidation |
| `useResource`, `useApiResource` | Cached data renders at once and is refreshed in the background; a key per resource, optional refresh interval, `enabled` and `ttl` |
| `ConsoleFeed`, `useConsoleFeed`, `healthStatusOf`, `mergeHealth`, `mergeItems`, `parseFeed` | The feed strip under a module's header: the platform feed (health and announcements) from the console API merged with the module's own items and health, always showing a health line even when one source is down |

The auth options carry no tenant or product value: `clientId`, `tenantId`, `apiScope`, `loginAttemptKey`, `basePath` and
`postLogoutPath` come from the app. The authority defaults to the Microsoft identity platform for the tenant and can be
set.

Two names a shell may already run with are accepted, so adopting the package changes nothing a user can see:

- **Mode.** `mode` is `shell` or `module`; `hub` and `tool` are the same two modes under their older names
  (`isShellMode(mode)` is true for `shell` and `hub`). `auth.mode` reports the name it was given.
- **Return key.** The target a module bounce saved is stored under `RETURN_TO_KEY` (`shell.returnTo`) unless the app
  passes `returnToKey`. `acceptReturnToKeys` lists more keys a target is read from and cleared under, so a target saved
  under an older key before a deploy still lands after it. The key holding a target first wins; the configured key is
  looked at first.

## 5. Server package

Plain ESM, no runtime dependency, every vendor call injected or read from an environment variable. It plugs into an
Express style stack (`req`, `res`, `next`) and the CommonJS servers `require` it.

| Export | Purpose |
|---|---|
| `createGroupResolver`, `normalizeGroupIds` | Per-user cache of directory groups: 5 minute TTL, LRU bound, single flight, failures never cached and failing closed to `[]`. With `groupIds` (the ids the app's authorization references, read on every lookup) only those are asked, and the entry is tied to a fingerprint of the list, so a new grant applies on the next request |
| `checkMemberGroups` | Which of a list of group ids an object is in, through the directory `checkMemberGroups` call: 20 ids per call, bounded concurrency, a rejected batch asked one id at a time, one retry on 429. `[]` when no valid id is left, `null` on failure, never throws |
| `createTokenCache`, `parseExpiresOn` | A cached, single flight managed identity token, renewed before it expires |
| `corsOptions`, `originGuard` | Exact match origins with a cached preflight; `originGuard` refuses a write, or any request a browser would have preflighted, from an origin off the list, so a cached preflight never outlives an origin's removal |
| `serverTiming`, `recordTiming`, `timed` | The `Server-Timing` header and `Timing-Allow-Origin` for allowed origins only, and one JSON log line per request with the route template (from the route definitions, never the request), status, duration and marks. A `sink` option receives each record; `timingKey` also stores the record under a key of the shell's own (`Symbol.for(timingKey)`), the same object, so marks recorded through either key add up |
| `requestTelemetry`, `createExportRetry`, `isTransientExportFailure`, `parseSettingString`, `closeTelemetryOnShutdown` | Request telemetry for `serverTiming`'s `sink` (section 5.1) |
| `whatsNewHandler`, `whatsNewNotes` | A module's release notes behind the module's own access check; labels from a fixed list, versions `x.y.z`, an https changelog link |
| `gatewayGuard`, `verifyGatewayToken`, `createSigningKeyCache` | Accept a request only when it carries the gateway's token ([web-shell-gateway.md](web-shell-gateway.md) section 4): signature against the tenant signing keys (cached, refetched at most once a minute), issuer, tenant, audience, expiry, not before, the gateway identity and the gateway role. No secret. Log only until enforcement is on; `/health` style paths stay open. The header name, the role and the request property are options (section 5.2) |
| `safeMessage` | An error message with bearer tokens and key values removed, short enough to log |
| `createJobLeader`, `jobLockKey` | Run an app's background jobs in one process at a time across every instance and deploy slot (a Postgres session advisory lock on a dedicated connection); section 5.4 |

The gateway guard reads `GATEWAY_ENFORCE`, `GATEWAY_PRINCIPAL_ID`, `GATEWAY_AUDIENCE` and `TENANT_ID` from the
environment (the names are the core's defaults; the consumer preset in 5.2 renames them). With none set and enforcement off it only removes the header; some but not all set logs a
`misconfigured` line at startup. Mount it before the bearer check.

### 5.1 Request telemetry

`requestTelemetry({ load })` returns `{ enabled, sink, flush, close }`. The package keeps no runtime dependency:
the app passes `load`, which `require`s the exporter client (`@azure/monitor-opentelemetry-exporter`,
`@opentelemetry/sdk-trace-base`, `@opentelemetry/resources`) from its own `package.json`, and `load` runs only when
telemetry is on, so a server without the setting never loads the client.

- **On only with Entra auth.** `APPLICATIONINSIGHTS_CONNECTION_STRING` set and
  `APPLICATIONINSIGHTS_AUTHENTICATION_STRING` equal to `Authorization=AAD` (optional `ClientId=<id>` for a
  user assigned identity). There is no key path. Anything missing or failing leaves it off with one log line and
  never throws: startup and requests are never affected.
- **What a request becomes.** One request named `<METHOD> <route template>` with its status, duration and the
  `Server-Timing` marks. It is built only from the `serverTiming` record (route template, never the URL), so no query
  string, header, token, email or address leaves the process. Mark descriptions are sent only when they are short
  lowercase words. Health probe routes are skipped; a route `serverTiming` did not resolve from the route
  definitions is sent as `-`.
- **The export retry.** The exporter runs with offline storage off, so a batch it cannot send is gone. A batch that
  fails with a transient error (no token yet right after a start, an identity endpoint error, a refused
  connection, a 429 or 503) is kept and sent again after 2, 5 and 10 seconds (`retryDelaysMs`), with at most 2000
  spans waiting (`maxBufferedSpans`, oldest dropped first and counted). A timeout, a reset connection or another
  5xx may have landed and is never retried, so a retry cannot count a request twice. Retries run on timers and
  never hold up startup or a request. Outcomes are logged as counts, at most one line per outcome and reason per
  five minutes: `export_retried`, `export_dropped` (reason `retries_exhausted`, `buffer_full`, `timeout`,
  `shutdown`), `export_failed`.
- **Shutdown.** `closeTelemetryOnShutdown(telemetry)` flushes on `SIGTERM` and `SIGINT` (a platform sends `SIGTERM`
  on every restart and deploy), makes one last attempt for waiting batches, waits at most 3 seconds, then lets the
  signal take its normal course. A no-op when telemetry is off.
- **Side effect.** When on it sets `APPLICATIONINSIGHTS_STATSBEAT_DISABLED=true` for the process unless the app
  already set it, so the exporter's own usage pings stay off.

### 5.2 Naming a gateway

A shell names itself once, with `setConsumerPreset({ ... })` at startup (`getConsumerPreset` reads it,
`resetConsumerPreset` is for tests). Every gateway function (`gatewayGuard`, `verifyGatewayToken`,
`takeGatewayHeader`), the telemetry defaults and the timing key read it, and a per-call option still wins.
A field left out keeps the core default, and each call replaces the previous preset. The fields:

| Field | Default | Read by |
|---|---|---|
| `header`, `role`, `requestProperty`, `refusalMessage` | `x-gateway-token`, `gateway`, `gateway`, the gateway message | the guard, `verifyGatewayToken` (role), the strip step |
| `settings.enforce`, `settings.principalId`, `settings.audience`, `settings.tenantId` | `GATEWAY_ENFORCE`, `GATEWAY_PRINCIPAL_ID`, `GATEWAY_AUDIENCE`, `TENANT_ID` | the guard reads these env names, and the `misconfigured` startup line prints the names in force |
| `serviceName`, `tracerScope` | `api`, `app-server` | `requestTelemetry`: the `service.name` used when neither `roleName` nor `WEBSITE_SITE_NAME` is set, and the tracer scope (option `tracerScope` overrides) |
| `timingKey` | `shell.app-server.timing` | the base `Symbol.for` key `serverTiming` and `recordTiming` use |

`gatewayGuard` also takes the names per call, so adopting the package changes nothing on the wire:
`header` (default `x-gateway-token`; matched in any case and removed from `req.headers` and `req.rawHeaders`),
`role` (default `gateway`; `""` skips the role check; `verifyGatewayToken` takes the same value as `role`),
`requestProperty` (default `gateway`; the checked result `{ ok, reason }` is also set under this name, next to
`req.gateway`) and `refusalMessage`. `takeGatewayHeader(req, header)` is the strip step on its own.

Three rules keep a preset from being forgotten or half applied:

- **The guard does not fail open.** `gatewayGuard` throws at startup when no preset was applied and no `enforce` option
  was passed, so a consumer that forgets the preset gets an error instead of a guard that reads the core's setting
  names, finds nothing and admits everything. An empty `setConsumerPreset()` chooses the core names on purpose;
  `enforce: false` runs without enforcement on purpose. `isConsumerPresetApplied()` reports which.
- **Both header names are stripped.** The guard removes the preset's header and the core's own `x-gateway-token` from
  `req.headers` and `req.rawHeaders`, so a token under either name never reaches a handler or a log. Only the preset's
  header is read as the token.
- **`GATEWAY_HEADER` and `GATEWAY_ROLE` follow the preset.** They are live bindings: they hold the core names until a
  preset is applied and the preset's names after, so an importer reads the names in force.

### 5.3 The supported consumer shape

The preset is process global and order dependent: it must be applied before the first `gatewayGuard`, `serverTiming` or
`requestTelemetry` call. The supported shape is one entry file per server package in the consumer, and nothing imports
the core index except that file:

```js
// the consumer's package main (for example server/shell/index.js)
import { setConsumerPreset, GATEWAY_HEADER } from '@example/core-app-server';

setConsumerPreset({
  header: 'x-example-gateway',
  role: 'example:gateway',
  requestProperty: 'exampleGateway',
  settings: { enforce: 'EXAMPLE_ENFORCE', principalId: 'EXAMPLE_PRINCIPAL', audience: 'EXAMPLE_AUDIENCE', tenantId: 'EXAMPLE_TENANT' },
  serviceName: 'example-api',
  tracerScope: '@example/app-server',
  timingKey: 'example.app-server.timing',
});
if (GATEWAY_HEADER !== 'x-example-gateway') throw new Error('consumer preset was not applied');

export * from '@example/core-app-server';
```

1. **Apply, assert, re-export.** The entry applies the preset, asserts it took effect at load (the header check above, so a
   second copy of the core or a changed import order fails at startup, not in production), then re-exports the core index.
2. **One copy.** The apps import the entry, never the core path, so there is one module instance and one preset. A bundler
   that duplicates the core breaks the shared state; the load assertion catches it.
3. **Run the package tests under the preset.** `npm run test:server:consumer` inside `kit` runs the app-server tests with
   `TEST_CONSUMER_PRESET` set to a JSON file (or inline JSON) in the preset's shape; the suite reads every name it needs
   from the preset in force, so the same assertions hold under any naming. The core runs it in CI against
   `kit/tests/app-server/consumer-preset.example.json`; a consumer points it at its own preset file.

### 5.7 External tools

Opt in. `shell-packages/external-tools` lets an admin add a tool the shell does not host (a dashboard first) as data, and
the launcher show it after the modules. The consumer creates the `console_external_tools` table (the schema is at the
top of the file), mounts `externalToolRoutes` and wires four things: `manage` (the permission check for its manage
action, seeded to no role), `permissions` (the registry an audience may name), `callerGroups` and
`callerHasPermission`.

- Visibility is display only. The external tool keeps enforcing its own access, so hiding a tool from someone never grants or removes anything there.
- Every tool names an audience and there is no "everyone": a console permission (the console RBAC, wildcard included) or a directory group (the caller's token groups first, then the consumer's group resolver). Any failure of the permission read, the group lookup or the database fails closed: the tool is not shown. A failed read of the table answers 503 with no tools.
- `GET /mine` (signed in) answers only the tools this caller may see, as `{ id, name, url, icon, hue, tagline, description, order }`; no audience, group id or audit field leaves the server. The other routes are behind `manage`: `GET /` (every tool with its audience and the permission list), `POST /`, `PUT /order` (those tools first, in that order), `PUT /:id` and `DELETE /:id`, at most 50 tools.
- `validateTool` refuses unknown fields and checks each one: the id a lowercase slug, text plain printable ASCII without `<` or `>`, the url https only with no user name or password, an icon name, a hue from `HUES` (the same list as `console-modules`; pass `hues` to change it), a whole number order, and an audience whose permission is one of the `permissionIds` it is given. Each refusal answers 400 with the field the editor highlights.
- Every write runs in `audit.transaction` (section 5.5) with the before and after snapshot, so an audit failure rolls the change back and answers 503. A duplicate id is a 409.
### 5.6 Announcements

Opt in. `shell-packages/announcements` is the store behind a feed strip every signed-in console shows. The consumer
creates the `announcements` table (the schema is at the top of the file), mounts the routes and reads `listActive` in
its own feed route.

- `validate(body, { partial, current, now })` checks a create (needs a client generated UUID `id`) or an edit: tone one of `info`, `success`, `warning`, `critical`; title 1 to 120 characters; body up to 400; the link empty, a path on the site or an https URL; unknown fields refused. Text has control, zero-width and bidi characters removed and newlines folded to spaces (the strip shows one line per item). A link holding any of those, or whitespace, is refused outright, as are `//host`, `/\host` and every scheme but https, and the limit applies to the stored (percent-encoded) form. The window must end after it starts and neither end may be more than 400 days out.
- `createAnnouncements({ db }).listActive()` answers the rows whose window is open now (newest start first, at most 10), cached briefly: the cache never outlives a window boundary (it expires at the earliest of 15 seconds, the first cached row's end and the next scheduled start), a committed write drops it at once, and another instance catches up within 15 seconds. `STATE_SQL` is the live, scheduled or expired state worked out on the database clock, so the admin list and the feed never disagree.
- `announcementRoutes(router, { db, audit, store, manage, caller })` mounts `GET /`, `POST /`, `PUT /:id`, `POST /:id/expire` and `DELETE /:id`, every one behind `manage` (the consumer's permission check for the manage action, reads included, because the list carries scheduled and expired rows nobody else sees). Every write runs in `audit.transaction` (section 5.5): the row is locked with `SELECT ... FOR UPDATE`, changed, and the audit entry written through the same client, so an audit failure rolls the change back and answers 503, and there is never an unaudited change or an audit entry for one that did not commit. A retried create returns the row it already made (200); the same id from another operator is a 409. A database check violation answers 400 with the field it belongs to. Expiring keeps the schedule the operator set and records when it was ended by hand.
### 5.4 Scheduled jobs and the job leader

Opt in. A tool that runs background work in its own API registers it with `createScheduler` (`shell-packages/jobs`)
and serves the contract with `jobRoutes`:

```js
const scheduler = createScheduler({ db, tool: 'demo', offEnv: 'DEMO_JOBS' });
scheduler.register({
  id: 'orphan-cleanup', name: 'Remove orphans', description: '...',
  at: '03:30', source: 'apps/demo/server/lib/scheduled-jobs.js', defaultEnabled: false,
  run: async () => ({ deleted: 0 }),
});
scheduler.start();
jobRoutes(router, { scheduler, read, manage, canManage, caller, audit });
```

- `at` is `HH:MM` Eastern time, every day, and lives in code, so a timing change is a pull request. The on/off switch and the last run live in the tool's own `scheduled_jobs` table, created on start.
- A run is claimed with one `UPDATE`, so two instances never run the same occurrence and a restart never repeats one. A run missed by more than three hours waits for the next day. Turning a job on after its time today skips that occurrence.
- A job that can change something outside the tool ships with `defaultEnabled: false`. `run()` returns a small summary; a non-zero `failed` marks the run a failure. Never return secrets.
- `GET /jobs` answers `{ tool, canManage, jobs }`; `PUT /jobs/:id` with `{ enabled }` turns a job on or off and is audited, and a switch whose audit write fails is put back. The tool names the path in its manifest as `"jobs": { "path": "/admin/jobs" }`; the core carries that key through and a consumer checks it with the `keys` option of `validateManifest` (web-shell-manifest.md section 2).
- The environment variable named by `offEnv` (default `JOBS`) set to `off` stops the runner on an instance.
- The package also parses the schedules of work outside an API for the same tab: `nextCron`, `describeCron` (UTC cron, five fields or six with a zero seconds field), `nextAutomation`, `describeAutomation` and `nextScheduled`.

A scheduler's state is in the database, but a job that keeps its dedupe state in memory (a status snapshot to diff, a
last fired value) fires twice while two processes run it, which happens in a slot swap and when a plan scales past one
instance. `createJobLeader({ name, getClient, start, stop })` makes the jobs run in exactly one process: each process
asks Postgres for a session advisory lock on a dedicated connection (`pool.connect()`), the holder calls `start`,
every other process keeps asking every `retryMs` (15 s). The lock belongs to the connection, so a holder whose process
exits or whose connection drops frees it. The holder pings its connection every `checkMs` (30 s) and calls `stop` at
once when the ping fails; a lock request, check or release that takes longer than `pingTimeoutMs` (10 s) counts as a
lost connection; a `start` that throws gives the lock up. `begin()` starts asking, `end()` stops the jobs and frees the
lock, `isLeader()` reads the state. It needs a direct Postgres connection (session pooling), never a transaction-mode
pooler. `lockPrefix` (default `jobs`) namespaces the 64-bit key `jobLockKey(name, prefix)`; keep it fixed once chosen,
since a process on a different prefix does not see the lock.
### 5.5 Audit log and settings

Opt in. Three small factories a tool's API takes when it keeps its own audit log or lets the console edit its settings.
Each takes the database as `{ query(text, params) }` (the audit log also `getClient()` for transactions) and reads its
environment from an `env` option that defaults to `process.env`.

`createAudit({ db, env, hmacEnv, clientIp, log })` (`shell-packages/audit`) writes entries to the consumer's
`audit_log` table (the columns are listed at the top of the file) and chains them:

- Each entry's hash is HMAC-SHA256 over the canonical JSON of the entry including the previous hash. The canonical form sorts object keys recursively, because the actor, details and context are stored as `jsonb`, which does not keep key order. The key is the variable named by `hmacEnv` (default `AUDIT_HMAC_SECRET`); without it the hash is plain SHA-256 so a dev database still chains, and `verify` reports `secretMode`.
- `write` is non-fatal: a logging failure resolves `null` and never breaks the mutation that triggered it. `transaction(work)` runs a change and its audit entries in one database transaction: `work(client, record)` makes its changes through `client` and calls `record` per entry, which throws on failure and rolls the change back. A returned `{ rollback: true }` rolls back too. A change that must not exist without its audit record uses `transaction`.
- Writes are serialised by an in-process queue (a failed write does not stop the ones behind it), so two concurrent requests never chain off the same previous hash and fork the chain. The queue is per process: run one writer process, or add a cross-process lock around `write`.
- Only the actor's email, name and object id are stored, never the token claims or groups. The caller address comes from `clientIp` (default `clientPublicIp`: strips the source port a platform proxy appends and the IPv4 mapping); never the first `X-Forwarded-For` entry, which the caller controls.
- `verify` walks the chain in order and reports the first break: an entry edited after it was written, an entry removed or reordered, and a deleted head (the first surviving entry must link to the genesis hash). Rows with no hash (written before the chain) are skipped.
- `csvCell` quotes an export cell and puts a leading apostrophe before `=`, `+`, `-`, `@`, tab or carriage return, so a spreadsheet does not run text written by whoever the entry is about.

`createSecretbox({ info, masterEnv, env })` and `createAppSettings({ db, ttlMs, now })` (`shell-packages/settings`):

- The secret box is AES-256-GCM with a key derived by HKDF from a master (the variable named by `masterEnv`, default `SECRETBOX_MASTER_KEY`). `info` is required and domain-separates the derivation, so one master backs several purposes; it must stay fixed because changing it orphans every stored secret. The sealed form is `v1.<iv>.<tag>.<ct>`. `open` answers `null` for no master, a wrong key, a tampered or malformed value and a value with extra segments, and never throws; callers treat `null` as not configured. Rotating the master means re-entering the secrets.
- App settings are one `jsonb` value per name in an `app_settings` table, read through a cache of `ttlMs` (default 30 s) that a write to the same name clears. Secrets never go there: seal them and store the sealed string.

## 6. Tests

| File | Proves |
|---|---|
| `kit/tests/shell-console-modules.test.ts` | The validator accepts the fixtures, ignores unknown keys (and `effectiveLayout` carries them through, `kit/tests/console-modules/layout.test.js`), rejects 24 mutations and never throws; the registry checks for source and peer ids; the launcher description fits |
| `kit/tests/console-modules/*.test.js` | The layout merge on synthetic modules: defaults and the new flag, overrides that move, rename, reorder and hide but never change what a page requires, orphans, custom links, the nav, landing and tile filters, the description order, the permission source and peer checks, Home contributions (shape, bounds, fail closed). Run by `npm run test:server` inside `kit` |
| `kit/tests/rbac/*.test.js` | The object id binding: `cleanOid`, a row bound to an id matching that id only, a legacy row matching the email, a token without an id failing closed, and `pickUserRow` preferring the bound row in any order |
| `kit/tests/shell-rbac.test.ts` | The ceiling, fail-closed stale ids, the wildcard rule, view-as, tab computation and the client helpers |
| `tests/test_console_module_schema.py` | The same manifest fixtures against the JSON schema ([web-shell-manifest.md](web-shell-manifest.md)) |
| `kit/tests/app-client/*.test.ts` | The OIDC sign-in over a fake manager (callback and state routing, parameter stripping, refresh-only renewal, granted scopes, end-session fallback, account changes), and the sign-in boot (silent, redirect, loop guard, return target, module bounce, configuration errors), the API client (token, errors, single flight, cache, 401 handling, persistence), the store, `useResource` and the feed strip, with a fake MSAL client |
| `kit/tests/jobs/*.test.js`, `kit/tests/app-server/job-leader.test.js` | The scheduler on an in-memory table (occurrence on Eastern time across a daylight change, run once across instances, the catch-up window, on and off, the switch audited and undone when the audit fails), the cron and automation helpers, and the job leader (one leader of two processes, ping loss, start failure, the lock prefix) |
| `kit/tests/audit/*.test.js` | The chain on an in-memory log: links off the genesis hash, intact verifies, an edited entry, a removed one, a reordered pair and a deleted head each break it, the key mode, concurrent writes never fork, a failed write is non-fatal and the queue survives, transactions commit and roll back, `csvCell`, the caller address |
| `kit/tests/settings/*.test.js` | The secret box round trip, no master, wrong master, wrong `info`, tampered and malformed values, and the settings cache (ttl, write clears, fallback) |
| `kit/tests/app-server/*.test.js` | The group cache (TTL, bound, single flight, fail closed, scoped lists), CORS and the origin guard, Server-Timing and route naming on real Express apps, the request telemetry (settings, record mapping, flush and close) and its export retry, the release notes handler, and the gateway token check against a local signing key, including a custom header, role and request property and the consumer preset. Run by `npm run test:server` inside `kit`, and again under a consumer preset by `npm run test:server:consumer` |

The kit workflow runs on a change under `shell-packages/` or the manifest fixtures.

## 7. Not in the core

Data, not code: a shell's own manifests, route inventories and role lists. The packages above take them as input.
