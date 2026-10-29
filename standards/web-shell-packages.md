# Shell shared packages

Applies to a multi-module shell ([web-shell.md](web-shell.md)). A shell keeps its cross-module logic in a few
shared packages that every module's client and server import, so a rule has one implementation. This document
says which packages a shell has, what each owns, which parts the core ships as code, and where the
core already states the rule.

## 1. The packages

| Package | Owns | Core status |
|---|---|---|
| Module contract (`console-modules`) | The per-module manifest ([web-shell-manifest.md](web-shell-manifest.md)): the validator, the registry checks, the permission source and peer helpers, the generated registry and its staleness check | Code: `shell-packages/console-modules/`. The generator is `kit/scripts/build-registry.mjs` ([web-shell.md](web-shell.md) section 3) |
| RBAC core (`rbac`) | What permission data means: accessible tabs, the grant ceiling, assignable roles, view-as, client access helpers | Code: `shell-packages/rbac/` |
| Client package (`app-client`) | One sign-in boot, token renewal, the API client and its cache, resource hooks, the live feed strip | Code: `shell-packages/app-client/` (TypeScript source). Rules: [web-client-runtime.md](web-client-runtime.md) sections 1 to 3, 5 and 6, [web-shell.md](web-shell.md) section 8 |
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

The admin layout merge (the rule that turns manifest defaults plus an admin's saved placements, renames and
hidden entries into what the rail renders, with new and orphaned markers and a page's permission always coming
from code) is not in the core yet. It is tied to a console admin store and is lifted with the ops center.

## 3. RBAC core

Pure functions with no database, no HTTP framework and no UI library. Each module keeps its own permission
registry and its own role, assignment and override tables; the package decides what that data means.

| Function | Side | Purpose |
|---|---|---|
| `permissionsBeyond` | server | Grant ceiling: ids a write would confer that the caller does not hold. The wildcard only from a genuine wildcard holder; an id the registry no longer defines is not dropped (fail closed) |
| `annotateRoles`, `assignableRoleIds` | server | Per-role `assignable` and `unknownPermissions` (registry drift) |
| `grantableIds` | server | Registry ids the caller may grant |
| `accessibleTabs` | server | Tabs a permission set opens, computed from the registry, so a client never infers access from id strings |
| `viewAsPreview` | server | A preview under the caller's ceiling, carrying the subject's own ceiling |
| `createAccess`, `canAssignRole`, `canGrantPermission`, `filterRegistry`, `activeGrantable` | client | Show and hide only, fed by what the server sends |
| `stripRetiredPermissions`, `findPermissionLiterals` | build and test | Remove retired ids from stored lists; find permission ids named in source so a registry-conformance test fails on an id the registry lacks |

Grammar: `tab:<name>`, `action:<name>:<verb>` and the wildcard `*`. [rbac.md](rbac.md) section 2 names
permissions `tools.<tool>.<resource>.<action>` and `hub.<area>`. That is a different grammar and a documented
exception, not a failure: the ceiling, assignable-role and view-as functions treat an id as an opaque string and
work with either; `accessibleTabs`, `createAccess(...).hasTab`, `findPermissionLiterals` and the manifest
validator read the `tab:` and `action:` forms. A host on the other grammar uses the first group and keeps its
own tab logic, and records the exception for the manifest rules.

## 4. Client package

TypeScript source that each app compiles itself (no build step). Peer dependencies: React, `@azure/msal-browser` and the
kit (`@build-standards/kit`, for `FeedStrip` and `safeHref`). The folder has one entry, `src/index.ts`.

| Export | Purpose |
|---|---|
| `createAuth` | One sign-in boot for the whole shell. The shell and every module share one origin, one single page app registration and one `localStorage` token cache, so a shell session is visible to every module and a module never renders its own sign-in. `mode: 'shell'` owns the sign-in surface; `mode: 'module'` bounces a signed-out caller to it and gets sent back. Silent renewal first, an interactive redirect only when needed, a loop guard that stops a repeating redirect, and a distinct answer for a configuration error ([web-shell-auth.md](web-shell-auth.md) section 3). `devBypass` skips the sign-in only on a local dev host with no client id |
| `RETURN_TO_KEY`, `safeReturnTo` | The same-origin return target. Protocol relative, backslash and control character targets, other origins and the bare root are refused, and dot segments are resolved before the check |
| `createApi`, `qs` | The API client: bearer token from the shared auth, one error contract (`ApiError` with status and details), one request for identical concurrent GETs, a stale-while-revalidate cache with a freshness window per key, opt-in `sessionStorage` persistence for identity reads only, a configurable answer to a 401 and a cache that a logout or account change clears |
| `createStore`, `defaultStore`, `isStale` | The resource store behind the client and the hooks: subscribers, one request per key, a waiting fetch re-run after an invalidation |
| `useResource`, `useApiResource` | Cached data renders at once and is refreshed in the background; a key per resource, optional refresh interval, `enabled` and `ttl` |
| `ConsoleFeed`, `useConsoleFeed`, `healthStatusOf`, `mergeHealth`, `mergeItems`, `parseFeed` | The feed strip under a module's header: the platform feed (health and announcements) from the console API merged with the module's own items and health, always showing a health line even when one source is down |

The auth options carry no tenant or product value: `clientId`, `tenantId`, `apiScope`, `loginAttemptKey`, `basePath` and
`postLogoutPath` come from the app. The authority defaults to the Microsoft identity platform for the tenant and can be
set.

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

The gateway guard reads `GATEWAY_ENFORCE`, `GATEWAY_PRINCIPAL_ID`, `GATEWAY_AUDIENCE` and `TENANT_ID` from the
environment. With none set and enforcement off it only removes the header; some but not all set logs a
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

`gatewayGuard` takes the names a shell already runs with, so adopting the package changes nothing on the wire:
`header` (default `x-gateway-token`; matched in any case and removed from `req.headers` and `req.rawHeaders`),
`role` (default `gateway`; `""` skips the role check; `verifyGatewayToken` takes the same value as `role`),
`requestProperty` (default `gateway`; the checked result `{ ok, reason }` is also set under this name, next to
`req.gateway`) and `refusalMessage`. `takeGatewayHeader(req, header)` is the strip step on its own.

## 6. Tests

| File | Proves |
|---|---|
| `kit/tests/shell-console-modules.test.ts` | The validator accepts the fixtures, ignores unknown keys, rejects 24 mutations and never throws; the registry checks for source and peer ids; the launcher description fits |
| `kit/tests/shell-rbac.test.ts` | The ceiling, fail-closed stale ids, the wildcard rule, view-as, tab computation and the client helpers |
| `tests/test_console_module_schema.py` | The same manifest fixtures against the JSON schema ([web-shell-manifest.md](web-shell-manifest.md)) |
| `kit/tests/app-client/*.test.ts` | The sign-in boot (silent, redirect, loop guard, return target, module bounce, configuration errors), the API client (token, errors, single flight, cache, 401 handling, persistence), the store, `useResource` and the feed strip, with a fake MSAL client |
| `kit/tests/app-server/*.test.js` | The group cache (TTL, bound, single flight, fail closed, scoped lists), CORS and the origin guard, Server-Timing and route naming on real Express apps, the request telemetry (settings, record mapping, flush and close) and its export retry, the release notes handler, and the gateway token check against a local signing key, including a custom header, role and request property. Run by `npm run test:server` inside `kit` |

The kit workflow runs on a change under `shell-packages/` or the manifest fixtures.

## 7. Not in the core yet

The admin layout merge. The standards above already state their rules; each
lands as its own piece with tests, and until then a shell keeps its own implementation and meets the rules in the
linked sections.
