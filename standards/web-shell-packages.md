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
| Client package (`app-client`) | One sign-in boot, token renewal, the API client and its cache, resource hooks, the live feed strip | Standard only: [web-client-runtime.md](web-client-runtime.md) sections 1 to 3, 5 and 6, [web-shell.md](web-shell.md) section 8 |
| Server package (`app-server`) | Group cache, directory token, CORS and origin guard, Server-Timing, request telemetry, gateway token check, What's new handler | Standard only: [web-api-runtime.md](web-api-runtime.md) sections 1 to 7 |

The code is plain ESM with hand-written `.d.ts` files, no runtime dependency and no build step, so a CommonJS
server and a bundled client both import it. A shell takes it by copying the folder into its shared packages
directory and recording the core release in its lock file; the core's CI proves it with the tests listed in
section 4. Nothing here syncs into a consumer on its own.

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

## 4. Tests

| File | Proves |
|---|---|
| `kit/tests/shell-console-modules.test.ts` | The validator accepts the fixtures, ignores unknown keys, rejects 24 mutations and never throws; the registry checks for source and peer ids; the launcher description fits |
| `kit/tests/shell-rbac.test.ts` | The ceiling, fail-closed stale ids, the wildcard rule, view-as, tab computation and the client helpers |
| `tests/test_console_module_schema.py` | The same manifest fixtures against the JSON schema ([web-shell-manifest.md](web-shell-manifest.md)) |

The kit workflow runs on a change under `shell-packages/` or the manifest fixtures.

## 5. Not in the core yet

The client and server packages as code, and the admin layout merge. The standards above already state their
rules; each lands as its own piece with tests, and until then a shell keeps its own implementation and meets the
rules in the linked sections.
