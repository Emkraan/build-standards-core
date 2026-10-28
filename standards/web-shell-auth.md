# Shell sign-in, scopes and rights

Applies to a multi-module shell ([web-shell.md](web-shell.md)) that signs in once with an identity provider
and calls one API per module. The client boot, silent renewal, API client and return-target rules are
[web-client-runtime.md](web-client-runtime.md) sections 1 to 3; the server-side bearer rules are
[web-api-runtime.md](web-api-runtime.md) section 7; the access model is [rbac.md](rbac.md). This document adds
what changes with several modules and several APIs behind one sign-in. Platform-level sign-in
([web-build.md](web-build.md) section 4) is the other shape and does not use it.

## 1. Sign-in and rights are separate

The identity provider decides **sign-in** only: the platform app requires an assignment, so a person needs one
assignment to enter. That assignment carries no right inside any module. Every right lives in the module's own
database, in its own roles and assignments. Roles in the token's `roles` claim are ignored (a setting turns
the claim off), so a claim can never confer access. The shell keeps the sign-in assignment in step with the
module roles: when it sees a principal hold a role in any module it ensures the assignment, and release and
reconcile are the reverse, each recorded in a ledger.

## 2. Client sign-in

| Item | Rule |
|---|---|
| Flow | Authorization code with PKCE in a single page app. No client secret |
| Pages | Redirect sign-in and redirect token acquisition, no popup. The start page rides in `state` and `boot()` routes it in-app |
| Redirect URI | The origin root. Post-logout goes to a signed-out page |
| Token cache | Local storage, so the shell and every module on the origin share one cache |
| Silent renewal | Cache and refresh token only. The hidden frame is skipped because the origin root refuses framing |
| Config errors | Consent, scope, app or assignment missing and conditional-access codes are never redirected: the call rejects with a marked configuration error, logged once |
| Loop guard | One redirect per scope per minute; a second rejects as a sign-in loop and names the provider code |
| Hub and tool modes | The shell owns sign-in. A module run on its own bounces a signed-out caller to the shell with a validated `returnTo` ([web-shell.md](web-shell.md) section 8) and never signs in itself |
| Dev bypass | Only with no client id on a localhost host; the API's dev identity then applies ([web-api-runtime.md](web-api-runtime.md) section 7) |

## 3. Tokens go only where they belong

The API client sends the bearer token only to its own base URL: a path must be an absolute path under it (no
scheme, no `//host`, no backslash, no dot segment in any encoding, no encoded slash inside a segment), else the
call rejects before a token is requested. A caller header can never replace the token. A token for another
module's scope sent to the shell's server travels in a separate header and is used for exactly one upstream call.

## 4. One scope per API

Every API has one delegated scope on its own app registration. The client asks for a token per scope and
sends it as the bearer. A module never holds a credential.

1. A module's manifest `api` block names `gateway`, `prefix` and `scopeEnv` ([web-shell-manifest.md](web-shell-manifest.md)).
2. The build bakes `VITE_<SCOPEENV>_API_BASE_URL` and `VITE_<SCOPEENV>_API_SCOPE`. A scope env the build does
   not know means no client, so the module is not enterable.
3. The shell builds the module's client from the base URL plus the prefix and the scope. On every request it
   acquires the token for that scope: silent first, a redirect only when interaction is required.
4. A module that declares a permission source shares the source's client, so one permission read answers both.
5. A side read (a feed poll, an estate probe, a peer permission read) asks silently and treats interaction as a
   401, so a page that loads several scopes never starts a redirect storm.

A new API therefore needs its app registration with the scope, an `api` block, and the env pair in the build.

**Acceptance (test):** a call to a path outside the base URL rejects before a token is requested; two scopes
that need interaction produce one redirect; a configuration error is not redirected.

## 5. What the server validates

[web-api-runtime.md](web-api-runtime.md) section 7 sets the signature, issuer and key-cache rules. A shell
API adds:

- **Delegated user tokens only.** A scope claim is present and the token type is absent or `user`. An
  application-only token and an ID token are refused.
- **An audience list.** Each configured entry is accepted as the value itself, the bare app id and the
  `api://` form of it, so an app id and its identifier URI both pass.
- **Identity.** Email from the preferred-username claims (lowercased), the object id, the lowercased group ids.
  The groups come from the token, or from a directory lookup when the token is over the claim limit.

## 6. Where rights are enforced

| Layer | Does | Binding |
|---|---|---|
| Shell client | The manifest `requires` and tile `permission` decide which rail entries and tiles render; the access helpers of [web-shell-packages.md](web-shell-packages.md) answer from what the server sent | Display only |
| Gateway | The gateway token ([web-shell-gateway.md](web-shell-gateway.md) section 4) | Reachability |
| Authentication | A valid delegated token for this API | Signed in |
| Route permission | Every route declares its guard ([rbac.md](rbac.md) section 1); a failed permission read answers 500, never 200 | Authorization |
| Relay | The shell forwards the caller's own token and the module re-checks its own permission | The module is the authority |

Each module keeps its own registry and its own role, assignment and override tables. The RBAC core
([web-shell-packages.md](web-shell-packages.md) section 3) decides what that data means identically on every
server and client. The shell reaches a module's admin API through the manifest `rbac` block: `shape`, `base`
and `me`.

**Permission grammar.** `tab:<name>`, `action:<area>:<verb>` (every action names its parent tab) and the
wildcard `*`; a manifest page may require another module's id as `<module>/<id>`. `rbac.md` section 2 names the
hub grammar (`tools.` and `hub.`): a documented exception, see web-shell-packages.md section 3.

**The wildcard.** Stored as the only entry of a role. It expands to every registry id, so a permission added
later is covered. A genuine wildcard holder alone may grant it, and a per-user override can never hold it. A
code-level break-glass list resolves to it without the database, so a bad RBAC edit cannot lock the shell out;
changing it needs a deploy.

**How a caller's permissions are computed.** Break-glass first; else roles from direct assignments plus
assignments to the caller's groups; none gives the fail-closed "No Access" role; the union of the roles'
permissions (wildcard expanded); the union of the user's override row (supplemental grants only); memoized per
request. A version row bumped by a statement trigger on the three tables makes a grant visible on every
instance by the next check.

## 7. Registering a permission

Each step is code; no admin action registers a permission.

1. Add `{ id, label, tab, description? }` to the module's registry.
2. Gate the route with the permission guard (any-of and wildcard-only variants exist).
3. If a page or tile needs it, add it to `requires` or `permission` in the manifest and regenerate the registry
   ([web-shell.md](web-shell.md) section 3).
4. To give it to existing system roles, add it to the role seed. The seed sync is additive: it adds the id at
   the next boot, never prunes, and reports an operator's removal as seed drift. Leave it out of the seed to
   ship it closed by default.
5. When an id is split, add a successor entry so it unions into every role holding the old id.
6. When an id is withdrawn, add it to the retired list; boot strips it from stored roles and overrides.
7. Operators then grant it under the grant ceiling.

**Acceptance (test):** a registry conformance test fails on a gate that names an id the registry lacks
(`findPermissionLiterals`); a retired id is stripped and never a live one.
