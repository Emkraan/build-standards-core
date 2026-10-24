# RBAC Standard

Version: 1.8 | Last reviewed: 2026-10-05 | Status: current | Scope: web (first-party)

**Canonical source:** this repo. This doc is the source of truth. Where a reference implementation differs, the implementation
is fixed, or the consumer records an explicit exception (README, "Source of truth and explicit
exceptions"). The worked example below uses the paths
`server/src/core/middleware/rbac.ts`, `shared/types/permissions.ts`, `server/src/apiRoutes.ts` and
`server/scripts/check-route-guards.ts`.

This is the access-control standard for every first-party web build. It is being rolled out in
phases (RBAC v2). Each rule below is tagged **[enforced]** (in the hub code and CI today) or
**[target]** (agreed design, lands in a later phase; build new work so it fits).

Related: identity and platform-level auth in [First-Party Build Standard](web-build.md#4-auth-platform-level-auth),
the people roster in [Identity and People Data](identity-and-people-data.md).

---

## 1. Principles

1. **Server is the boundary.** Every route enforces access on the server. Client `can(p)` is
   show/hide only, never security. **[enforced]**
2. **Deny by default.** Signing in grants nothing. Access comes only from a grant. **[enforced]**
3. **Every route declares its guard.** No route ships without one; CI proves it. **[enforced]**
4. **No escalation.** Nobody can grant, or add to a role, a permission they do not hold. **[enforced]**
5. **Least privilege, real granularity.** Separate view from write actions, and sensitive reads
   from ordinary reads. Never reach for `hub.admin` when a narrower right fits. **[enforced for new work]**
6. **Additive union.** Effective access = the union of every matched grant (direct + groups). **[enforced]**
7. **Changes are audited** with before/after values. **[target]** (phase 3, in review; until it lands only the denied-permission record below is enforced). Access changes are logged as
   `access.*` audit actions with `{ target, before, after }`; every RBAC 403 records the missing
   permission (`{ denied: { anyOf, scope? } }`).

## 2. Permissions

**Naming:** `tools.<tool>.<resource>.<action>` for tool rights, `hub.<area>[.<sub>]` for hub-level
rights. All lowercase, kebab-case segments. **[enforced]**

**Actions:** use the narrowest verb that matches:

| Action | Meaning |
|---|---|
| `view` | Read the tool or resource |
| `view-sensitive` / `view-unpublished` | Read fields or records hidden from ordinary viewers |
| `edit` | Create and change records |
| `manage` | Create, change and delete, plus configuration of the resource |
| `<verb>` | A distinct capability (`swap`, `generate`, `run`) |
| `<action>.others` | The same action on records owned by someone else (see section 4) |

**Registration:** every permission is a `PERMISSIONS` constant and a `PERMISSION_CATALOG` entry
(key, label, description, group) in `shared/types/permissions.ts`. A permission not in the catalog
cannot be assigned. **[enforced]**

**Live registry, not a hand-kept list.** The admin Roles & Permissions page renders only from
`GET /api/admin/roles/registry`, which the server builds at request time from its mounted routers'
guards plus declared handler checks (`server/src/core/middleware/permissionRegistry.ts`), with the
live Systems Architecture categories and tags. Each route is credited to its *narrowest* guards, so
a blanket "open the tool" gate does not inflate a sub-right's route count. **[enforced]**

- A check made inside a handler (field redaction, own-vs-others, per-record scope) is declared next
  to the check with `declarePermissionCheck([perms], 'where')`; a `*` segment marks an open-ended
  family (`tools.systems-architecture.category.*`). **[enforced]**
- A catalog entry that only hides UI and is not enforced by the server is marked `displayOnly: true`
  and shown as "Display only". Use it only when the data is already visible to the tool's view
  right. **[enforced]**
- `pnpm run check:rbac` fails when a catalog permission is enforced nowhere (and not
  `displayOnly`), or when code enforces a permission the catalog does not list. **[enforced]**

**Umbrellas:** `*` implies everything; `hub.admin` implies every `hub.admin.*` sub-right. Do not
add new umbrellas. **[enforced]**

## 3. Guards (server)

Import from `server/src/core/middleware/rbac.ts`. Every route under `/api` is covered by at least one of
these guards, on the route or as a router-level `router.use(...)` registered ahead of it. A route may
stack a blanket guard with a specific one (see tool sections below): **[enforced]**

| Guard | Use for |
|---|---|
| `authorize(PERM)` | One permission |
| `authorize.any(A, B)` | Any one of several (own-or-others pairs, shared pickers) |
| `authorize(PERM, { scope: req => ScopeRef })` | A permission within a scope (section 4) |
| `authenticatedOnly('reason')` | Signed in, no permission. Identity endpoints only (`/auth/me`) |
| `customGuard(handler, perms, 'reason')` | A tool gate that cannot be a fixed list. Avoid |
| `publicRoute('reason')` | Mounted before `authMiddleware` with its own auth (API key, secret) |

`requirePermission` / `requireAnyPermission` are aliases of `authorize` / `authorize.any`, kept so
existing call sites need no change. New code uses `authorize`.

Inside a handler, use `userCan(req, PERM, scope?)` for record-level decisions. Never compare
permission strings by hand (`permissions.includes(...)`): it skips the umbrella and scope rules.

Tool sections: open the tool with a blanket `authorize.any(...all section rights)` and gate each
path with `authorize(specific)`.

**Route-guard CI gate:** protected routers are mounted only through the table in
`server/src/apiRoutes.ts`. `server/scripts/check-route-guards.ts`, run by `pnpm run check:rbac`
in CI, walks that table and fails if any route has no guard. It is a script, not a test, so
importing every router does not dilute coverage. A new tool is added to the table, nowhere else. **[enforced]**

## 4. Scope and ownership

**Scope** narrows where a permission applies. **[enforced]**

- `ScopeRef = { kind, id }` with `kind` one of `category`, `tag`, `on-call-group`, `team`. `id`
  is a stable slug or numeric id, never a display name.
- A user holds a permission globally (`AuthUser.permissions`) or within a scope
  (`AuthUser.scopedPermissions`). A global grant satisfies every scope; a scoped grant only its own.
- The one evaluator is `checkPermission(user, perm, scope?)` in `shared/types/permissions.ts`. The
  server guard, `userCan`, and the client all call it.
- Add a scope kind only for a real, named need. Systems Architecture categories and tags are
  the first users: a scoped grant of `tools.systems-architecture.view` / `.edit` on
  `{ kind: 'category', id: <slug> }` (or view on a `tag`) works like the legacy per-category
  strings (`tools.systems-architecture.category.<slug>.<view|edit>`), which keep working.
  Category and tag scope ids are stored and compared as `slugifyArchToken` slugs.
- Only **enforced** scope kinds are grantable: `ENFORCED_SCOPE_KINDS` in
  `shared/types/permissions.ts` (today `category`, `tag`). The admin API rejects, and the UI does not
  offer, any other kind, so a scoped grant can never silently grant nothing. `on-call-group` and
  `team` are reserved in the schema; a kind joins `ENFORCED_SCOPE_KINDS` in the same change that
  makes a route check it. **[enforced]**
- Tool code that takes a caller for access decisions takes the whole user (`req.user`), never
  `req.user.permissions`, so scoped grants are seen.

**Ownership** ("own records only") is not a scope. Model it as a pair of permissions: the base
action covers the caller's own records, `.others` covers everyone else's (for example
`tools.team-calendar.manage` + `tools.team-calendar.manage.others`). Gate the route with
`authorize.any(base, others)`, then check ownership per record in the handler. **[enforced]**

## 5. Roles and grants

- **Roles** live in the DB (`roles`, `role_permissions`). Seeded system roles plus admin-created
  custom roles. An `is_admin` role implicitly holds `*`. **[enforced]**
- **Grants** map a user (email) or an identity provider group to a role in `access_grants`. Use DB grants,
  not identity provider app roles. An app-role claim is not an input to the evaluator, even during a
  cutover; migrate the roles to grants first, then switch the claim off. New group grants use the group object id. Name-matched group grants still
  resolve, so existing grants keep working; the admin Grants screen flags them "Name-matched
  (legacy)" for re-mapping by object id. Retiring name matching (after every grant is converted)
  is **[target]**.
- **Easy Auth fail-closed:** `ENFORCE_EASY_AUTH=true` makes the server refuse requests when Easy
  Auth is not confirmed. Turn it on only after the post-deploy smoke check's `auth.easy_auth` line
  reports `confirmed`; the App Service portal list does not show platform-injected variables such
  as `WEBSITE_AUTH_ENABLED`. **[enforced]** The hub runs with `ENFORCE_EASY_AUTH=true` since
  2026-10-05; every deploy's smoke check reports `confirmed via WEBSITE_AUTH_ENABLED=True;
  fail-closed ON`. A deploy that reports anything else is a finding.
- **Expiry:** any grant may carry `expires_at` (UTC; NULL = never). Expired grants are ignored at
  resolution. Omitting `expiresAt` when updating a grant keeps its current expiry. **[enforced]**
- **Scoped grants** live in `scoped_grants` (subject + role + scope + optional expiry); a subject
  may hold many. Admin roles are never scoped. A user with only scoped grants has access, with no
  global permissions. **[enforced]**
- Schema changes to grants follow the additive-only migration rule
  ([Data Safety](data-safety-sqlite.md)); the `migration-safety` CI job enforces it.
- **Break-glass:** the `CODE_SUPER_ADMINS` list in the DB module is a deliberate, permanent
  break-glass. It re-asserts a `hub-admin` grant on every startup and cannot be revoked or
  downgraded through the API, and it can never expire. Keep it to one or two named accounts. **[enforced]**

## 6. Admin and delegation

- **No-escalation rule:** `canDelegate(callerPerms, targetPerms)` in `shared/types/permissions.ts`.
  A caller may grant a role, change or revoke a grant, or create, edit or delete a role only if
  they hold every permission involved (the new role, and the subject's current role). `*` is
  delegable only by a `*` holder. **[enforced]**
- **Preview ceiling.** A preview of a role or an access package (View-As or a package preview) never
  shows more than the viewer holds: the server intersects the previewed permissions with the
  viewer's own effective permissions, refuses a preview above that ceiling with 403 and writes an
  audit row naming the viewer and the refused permissions. The no-escalation rule above covers
  grants; this covers previews. **Acceptance (test):** a viewer without `x.manage` previewing a
  role that holds it gets 403 and one audit row.
- **Stored roles that drift from the catalog are flagged.** A stored role or package that holds a
  permission the catalog no longer lists (renamed or retired) is flagged in the admin UI and the
  unknown permission is stripped on its next save, never silently honoured. CI also scans the code
  for permission literals built by concatenation or templates instead of imported from the shared
  permission list, so a permission the catalog check cannot see never ships. **Acceptance (test):**
  a role seeded with a retired id is flagged and saves without it; a template-built permission in a
  fixture file fails the scanner.
- Admin sub-rights are separate permissions (`hub.admin.access`, `.roles`, `.audit`, `.health`).
  Tool administration gets a tool permission (`tools.integrations.manage`), not `hub.admin`. **[enforced]**
- **View-As / impersonation** runs on the server. `POST /api/admin/impersonate` returns a token the
  client sends as `X-Hub-View-As`; it is valid only for the admin who started it, for 60 minutes,
  and every request under it is read-only (non-GET returns 403). `/api/admin/impersonate` is exempt
  so a preview can always be ended. The audit log keeps the admin's email. **[target]** (phase 3, in review)
- **No ownership exceptions during View-As.** Any rule that grants access because the caller
  created or owns a record (for example the Systems Architecture draft creator exception in
  `canViewDiagram`) is skipped while `viewAs` is set, because the admin's email is kept for the
  audit log. A preview must show exactly what the previewed role sees, never the admin's own
  records. This covers every surface that reuses the check, including global search. **[enforced]**
  (hub #222)
- `/auth/me` returns only the caller's own effective access (the previewed role's during View-As).
  No client receives other roles' permission maps (`rolePermissions` is always `{}`). **[enforced]**

## 7. Client

- One permission source: `can(p)` from `AuthContext`, backed by the shared evaluator. **[enforced]**
- Every tool route is wrapped in `ProtectedTool` (`canOpenTool`: any permission under the tool's
  `accessPrefixes`, globally or scoped, so it is never narrower than the server). Hub grid, sidebars
  and the command palette all use `canViewTool` / `canViewNavItem`; scoped access uses a manifest
  `visibleTo(subject)` rule. **[enforced]**
- Never duplicate server access logic in the client. Shared rules live in `shared/` (for example
  `shared/types/systems-architecture-rbac.ts`) and both sides import them; the client passes
  `subject` from `useAuth()`. **[enforced]**
- A tool hosted inside another tool keeps its own permissions: the host lists both in
  `viewAnyPermission` and `accessPrefixes`, and every nav item and route is gated by its own
  section's permission (reference: RACI under Team Links; see [First-Party Build Standard](web-build.md) section 7).

## 8. Adding a tool or route (checklist)

1. Add `PERMISSIONS` constants and `PERMISSION_CATALOG` entries (view + each real action; a
   `.others` variant where records have owners; a `view-sensitive` where fields are sensitive).
2. Guard every route with `authorize` / `authorize.any`. Record-level checks use `userCan`.
3. Mount the router in `server/src/apiRoutes.ts`.
4. Add role defaults in `DEFAULT_ROLE_PERMISSIONS` only if a system role should hold them.
   Any check made inside a handler gets a `declarePermissionCheck` next to it, so it shows on the
   Roles page.
5. Gate the client route, nav item and buttons with the same permissions.
6. Add tests: allowed, denied, and (for owned records) own vs others.
7. `pnpm run test` and `pnpm run check:rbac` (route guards, and catalog in sync with enforcement) pass.
8. If you changed any rule here, update this doc and the CHANGELOG in the same piece of work.

## 9. Roadmap (RBAC v2)

| Phase | Scope | Status |
|---|---|---|
| 0 | No-escalation rule in the admin API | Done (hub #174) |
| 1 | `authorize` guard API, scope model and evaluator, route-guard CI gate, unguarded routes closed, `tools.integrations.manage` | Done (hub #183) |
| 2a | Scoped + expiring grants (additive migration), SysArch categories and tags as scopes, `/me` trimmed, scoped-grant admin API | Done (hub #186) |
| 2b | Admin UI for scoped and expiring grants, client route guards, nav from server gates, shared client/server SysArch helper, View-As umbrella fix | Done (hub #188) |
| 3 | Server-side View-As, audit before/after for access changes (the audit log is the grant history) | In review (hub #209) |
| 3b | Enforced scope kinds only, Easy Auth signal in the smoke check, legacy group flag | Done (hub #213) |
| 3c | Turn on `ENFORCE_EASY_AUTH` | Done (2026-10-05, app setting; smoke check shows fail-closed ON) |
| 3d | Retire name-matched group grants | After every group flagged "Name-matched (legacy)" is re-mapped by object id |

**Author:** the owner
