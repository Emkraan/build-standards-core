# Shell API and gateway per tier

Applies to a multi-module shell ([web-shell.md](web-shell.md)) that has its own API (the console API) next to
the APIs of its modules, all reached through one gateway per tier. It describes the layout as it runs. The
server runtime rules (group cache, CORS, origin guard, Server-Timing, telemetry, bearer validation) are in
[web-api-runtime.md](web-api-runtime.md) and are not repeated; the token and rights model is in
[web-shell-auth.md](web-shell-auth.md); how a change ships is in [web-shell-deploy.md](web-shell-deploy.md).

## 1. What the console API is

One Node Express API owned by the shell. It serves what only the shell knows: the caller's identity and
navigation, the saved layout and tile order, announcements, settings, the RBAC admin for its own roles, an
access overview across modules, estate health and a relay to a module's API for a few shell-initiated reads. It
has its own database, and a module's API keeps its own.

Boot order: preflight, then migrations, then the RBAC bootstrap, then listen. A migration or seed failure is
logged and does not exit, so the health route reports it ([ci-cd-release.md](ci-cd-release.md) section 6 gates
a deploy on that route). Preflight fails a production start that lacks a required setting (database, audit
secret, token audience, tenant, allowed origins) or carries a development identity or a localhost origin.
Migrations are applied by the server at boot, one transaction per file, recorded in a table; they are
forward-only and additive ([ci-cd-release.md](ci-cd-release.md) section 7).

## 2. Middleware order

The order is part of the contract: a guard placed after the body parser or the routers protects less.

| # | Middleware | Effect |
|---|---|---|
| 1 | Server-Timing and request log | One log line per request; skips the health routes ([web-api-runtime.md](web-api-runtime.md) section 4) |
| 2 | Security headers, access log | Content security policy is the front end's job here, so it is off on the API |
| 3 | CORS | Exact-match allowlist from one comma-separated setting, no credentials, preflight cached 7200 seconds ([web-api-runtime.md](web-api-runtime.md) section 3) |
| 4 | Origin guard | A write, or any request a browser would have preflighted, from an origin off the allowlist gets 403. No `Origin` passes |
| 5 | Gateway guard | Section 4 |
| 6 | JSON body (1 MB limit), request id | |
| 7 | Rate limit on `/api/` | Per client address, a fixed window (default 200 requests per 60 seconds), both values settings |
| 8 | Public routes | Health, version, and the root ping. Nothing else |
| 9 | Authentication on `/api` | A valid delegated token ([web-shell-auth.md](web-shell-auth.md) section 4). Everything below needs a signed-in caller |
| 10 | Group overage | Completes the caller's groups once for every route when the token carries none |
| 11 | Routers | Section 3 |
| 12 | Error handler | `{ error, details }`; in production a 5xx answers a generic message and no details |

## 3. Route areas

A shell API groups its routes by purpose. Each area names the permission that gates it
([web-shell-auth.md](web-shell-auth.md) section 5); the route list itself is the API's own documentation.

| Area | Holds | Gate |
|---|---|---|
| Public | Health, version | none |
| Identity and navigation | The caller, their permissions and tabs, the feed strip data, version | sign-in only |
| Layout | Modules, groups, items, tiles and bundles the admin saved, and the caller's resolved layout | read: sign-in; write: a layout permission |
| External tools | Launcher entries outside the shell | write: its own permission |
| Announcements and settings | Banner text, shell settings | a manage permission each |
| RBAC admin | Roles, assignments, overrides, audit | admin permissions under the grant ceiling |
| Access overview | One person's access across modules, sign-in assignment upkeep | its own tab permission |
| Estate health | Probe readings of each module's API | a tab permission |
| Relay | A shell-initiated read of a module's API with the caller's own token | the module's server decides; the shell's check only decides whether to forward |

**The floor is sign-in, on purpose.** The shell's database knows only the shell's roles, so a "holds a role
somewhere" floor would lock out a person who holds only a module's role. The identity, feed, layout read,
relay-peer and version routes therefore need only sign-in and scope what they carry inside.

## 4. The gateway token

A tier's API management service sits in front of every API. Its policy mints a short-lived token with the
service's managed identity and sets it in a header; the API checks it before anything else.

| Item | Rule |
|---|---|
| Header | A fixed header name. The guard deletes it from the request (parsed and raw headers) first, so nothing downstream reads it, and the gateway deletes any caller-supplied copy |
| Check | RS256 signature against the tenant signing keys (cached 10 minutes, a refetch at most once a minute, a failed read never cached), the platform audience, and that the caller principal is the tier's gateway identity |
| Settings | Enforce (`on` refuses, anything else only logs), the gateway principal id, the audience list, the tenant id |
| Refusal | 403 with a fixed message when absent or wrong; 503 when the keys cannot be read |
| Exempt | The health routes (the platform and a shell server's cross-module probes call them directly), the root ping |
| Where it applies | Every API behind the gateway, listed in one place per tier so a new API gets the policy; a CI check requires enforcement on every API |

Cross-module calls made by the shell's server (relay, estate probes, the access overview) go to the module's
own host directly with the caller's own token. They skip the gateway, which is why the health routes are exempt.

## 5. Layout per tier

Two tiers run the same shape; only the tier word in each name changes. Roles, not names:

| Role | Technology | Notes |
|---|---|---|
| Web | A static host project per tier | Builds the one bundle ([web-shell-deploy.md](web-shell-deploy.md) section 2); rewrites every module prefix to the one index page |
| Bare root | An edge service rule | Redirects to the web host |
| API gateway | One custom domain per tier on one edge profile, origin the tier's API management service | Route `/*`, HTTPS only; an alias domain per tier |
| One API per module | `/<module>` on the gateway, backend the module's App Service | The API definition is generated from the app's deploy descriptor (`edge` block: path, display name, backend, optional OpenAPI), so a new API appears without a manual edit |
| Gateway token policy | One list of the APIs that receive the policy | An App Service API must be listed here |
| Database | One per API | Not shared across modules |
| CORS origins | The tier's web host and its bare root, nothing else | One setting |

One edge profile can serve both tiers' hostnames; one infrastructure root per tier builds the API management
service.

**How a call travels.**

1. The bundle bakes one base URL per API (`<gateway>/<module>`) and one scope per API at build time
   ([web-shell-auth.md](web-shell-auth.md) section 4).
2. The call is `<gateway>/<module>/api/...` with a bearer token and `X-Requested-With`.
3. The edge forwards to the API management service, which routes by API path to the App Service and adds the
   gateway header.
4. The App Service checks the gateway token, then the user token, then the route's permission.
