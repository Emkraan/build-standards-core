# Web API Runtime Standard

Version: 1.0 | Last reviewed: 2026-10-14 | Status: current | Scope: web (Node and Express APIs
behind a gateway, on small app hosting plans)

How a first-party API resolves identity, answers the browser, measures itself and reports telemetry
without paying for it on every request. Every rule here was proved on a platform of several single
page apps sharing one origin behind an API gateway, each backed by a small Node Express API that
checks a bearer token and the caller's directory groups. This doc is the source of truth. Where a
reference implementation differs, the implementation is fixed, or the consumer records an explicit
exception (README, "Source of truth and explicit exceptions").

Related: [RBAC](rbac.md) (the permission model these checks feed), [First-Party Build
Standard](web-build.md) (stack, API envelope, auth), [Web Client Runtime](web-client-runtime.md)
(the browser side of the same calls), [Secrets and Credentials](secrets-and-credentials.md)
(managed identity before secrets).

Each rule names the failure it prevents and its acceptance line. Evidence is a measured number from
the platform the rule came from.

---

## 1. Identity group resolution

1. **Never call the directory per request.** Group membership (a transitive membership lookup in the directory) is resolved once per user and cached, never once per API call.
   - Prevents: a page that fires many API calls doing one directory round trip per call.
   - Evidence: a dashboard making 12 calls did 12 directory lookups at 2 to 4 s each, and the first permission check took 6.6 s.
   - Acceptance (test): a test sends several requests for one user and asserts the directory fake was called once.
2. **Per-user cache with a short TTL.** Cached groups live about 5 minutes, keyed by the user's object id, in a bounded LRU so memory stays flat however many users sign in.
   - Prevents: unbounded growth on a small plan, and a membership change that never takes effect.
   - Acceptance (test): entries expire after the TTL and the cache never holds more than its bound.
3. **Single-flight per user.** Concurrent misses for the same user share one in-flight lookup.
   - Prevents: a burst of parallel calls at page load starting one lookup each before the first one fills the cache.
   - Acceptance (test): N concurrent requests for a cold user produce one directory call.
4. **Failures are never cached and fail closed.** A failed or timed-out lookup returns no groups for that request (access denied or a retryable error) and leaves no cache entry.
   - Prevents: a transient directory outage pinning a user to an empty group set, or worse, a failure read as full access.
   - Acceptance (test): a failing fake denies the request, and the next request retries the directory.
5. **Writes read groups live.** Any request that changes data resolves the caller's groups from the directory, bypassing the cache. A write is any method except GET, HEAD and OPTIONS, plus every POST not on a tested allowlist of read-shaped POSTs (search, report and export calls), so an unlisted POST counts as a write. Reads tolerate the TTL.
   - Prevents: a user removed from a group keeping write access for the rest of the TTL.
   - Acceptance (test): remove a user from the fake's group, then a write is refused at once while a read may still pass inside the TTL, and a test fails when a new POST route is on neither the write path nor the read-shaped allowlist.
6. **In-app membership changes invalidate the cache.** When the app itself adds or removes a member, it drops the affected users' cache entries in the same request.
   - Prevents: an administrator granting access and the user still seeing "no access" for five minutes.
   - Acceptance (test): after an in-app grant the next request for that user misses the cache.
7. **Look up only what is used, in batches, and never refill after an invalidation.** The resolver asks the directory only about the groups the apps reference (a membership check over that list, not every group the user is in). It sends at most 20 ids per call with at most 4 calls in flight, falls back to one id per call when a batch answers 400, and retries a 429 once after the time the directory asks for. A generation counter per user is raised by every invalidation (rule 6), and an in-flight lookup that started under an older generation returns its result to its caller but never writes it to the cache.
   - Prevents: a user in hundreds of groups paging the whole list on every miss, one bad id failing a whole batch, a throttle read as "no groups", and a stale lookup that started before a grant or removal refilling the cache with the old answer.
   - Acceptance (test): a user in more groups than the app references causes a lookup of the referenced ids only; 45 ids make three calls with no more than 4 in flight; a batch that answers 400 is retried id by id; a 429 is retried once; an invalidation during an in-flight lookup leaves the cache empty for that user.

## 2. Directory token

1. **Cache the managed identity token for the directory.** The API gets its directory token from its managed identity and reuses it until shortly before expiry, never per lookup.
   - Prevents: a token request in front of every cache miss, doubling the cost of a cold lookup.
   - Acceptance (test): two lookups in a row request one token.
2. **Drop the token on a 401.** A 401 from the directory clears the cached token, and the lookup retries once with a fresh one.
   - Prevents: a revoked or rotated token failing every lookup until the process restarts.
   - Acceptance (test): a fake that answers 401 once is retried once with a new token.

## 3. CORS

1. **Send Access-Control-Max-Age 7200.** Preflight responses carry the browser cap (7200 seconds) so a browser asks once per two hours, not once per call.
   - Prevents: every authenticated JSON call (an Authorization header makes it non-simple) paying a full preflight round trip first.
   - Acceptance (test): an OPTIONS request from a listed origin returns Access-Control-Max-Age 7200.
2. **Keep an origin guard behind CORS.** The API refuses writes and preflighted requests whose Origin is not on the list, independent of the CORS headers.
   - Prevents: a preflight cached for two hours letting a removed origin keep calling the API after its removal.
   - Acceptance (test): a write with an unlisted Origin returns 403 even when no preflight happened, whichever layer refuses it. A CORS layer that rejects in error mode must map to 403, never a 500.
3. **CORS lives in the app only, never at the hosting platform.** The hosting platform's own CORS setting stays empty for every API. The app's CORS layer and origin guard (rules 1 and 2) are the one place origins are decided.
   - Prevents: a platform-level CORS answer hiding the app's own: a platform list that reflected any origin let an unlisted origin through an app that refused it, and a platform rule that answered every preflight with 400 left a whole shell rendering empty.
   - Acceptance (CI): a check reads each API's hosting configuration (IaC or the platform's exported settings) and fails when a platform CORS origin list is set.

## 4. Server timing and request log

1. **Send Server-Timing marks to allowlisted origins.** Each response carries marks for the costly steps (token check, group lookup with hit, miss or shared, permission check), with Timing-Allow-Origin set, only when the request Origin is on the list.
   - Prevents: guessing where a slow call spent its time, and leaking internal timing to any origin.
   - Acceptance (test): a listed origin gets Server-Timing and Timing-Allow-Origin, an unlisted one gets neither.
2. **One structured log line per request, nothing personal.** The line holds method, route template, status, duration and the timing marks. It never holds the URL, query string, token, user name, email or object id.
   - Prevents: slow calls with no record, and logs that become a store of personal data and tokens.
   - Acceptance (test): a request with a query string and a bearer token logs one line that contains neither, and the production middleware list holds no stock access logger (combined format logs the URL, query string and client address).

## 5. Telemetry

1. **Route names come only from declared route templates.** The route name is read from the router's declared templates (walk the router definitions at startup), never built from the request path or the mount path values. A request that matches no declared template is named `-`.
   - Prevents: ids, emails and other values in paths reaching telemetry. A heuristic that replaced id-looking segments with a regex let a concrete lowercase id through.
   - Acceptance (test): requests with ids, emails and unknown paths produce only declared templates or `-`.
2. **Health probes are not sent.** Requests to the health endpoint are not recorded as telemetry.
   - Prevents: probe traffic dominating request counts and cost on a small plan.
   - Acceptance (test): a health request produces no telemetry item.
3. **Keyless ingestion.** Local (key) auth is off on the telemetry resource. The API sends with its managed identity, which holds only the metrics publisher role on that resource.
   - Prevents: an ingestion key in configuration that anyone can copy to send forged telemetry.
   - Acceptance (review): the resource has local auth disabled and the identity holds only the publisher role.
4. **One telemetry component per API with a daily cap, and no stray alert mail.** Each API reports to its own component with a daily ingestion cap. The anomaly alert rule the platform creates on its own is disabled or kept from mailing a shared action group.
   - Prevents: one noisy API spending the whole budget, and an auto-created rule mailing a shared group about an app it does not own.
   - Acceptance (review): every component has a cap and no auto-created rule targets a shared group.
5. **Telemetry never blocks startup and flushes on SIGTERM.** The exporter starts after the server listens, its failure is logged and ignored, and a SIGTERM handler flushes with a short timeout before exit.
   - Prevents: an unreachable ingestion endpoint keeping the API down, and the last requests before a restart going missing.
   - Acceptance (test): with an unreachable endpoint the server still answers, and SIGTERM exits within the timeout.
6. **Prefer the lightweight exporter on small plans.** Use a plain trace SDK with the vendor exporter, not the vendor's all-in-one distribution.
   - Prevents: slow cold starts and memory pressure, and raw URLs in telemetry (the all-in-one package records them by default).
   - Evidence: 39 MB and 0.4 s cold import for the exporter against 154 MB and 5.3 s for the distribution.
   - Acceptance (review): the API's dependencies hold the exporter, not the distribution.
7. **Retry exports and buffer spans through a short outage.** A failed export is retried after 2, 5 and 10 seconds, and unsent spans wait in a bounded buffer of 2,000 spans. When the buffer is full the oldest spans are dropped and one line is logged per outage, never one per span.
   - Prevents: a collector restart of a few seconds dropping every span in flight, and an outage turning into an unbounded memory queue on a small plan.
   - Acceptance (test): with a fake collector down for 8 seconds no span is lost; with it down past the buffer the buffer holds 2,000 spans and one warning is logged.

## 6. Shared runtime package and token checks

1. **One package for the runtime middleware and security helpers, consumed by every API.** Group caching, the directory token, the origin guard, Server-Timing, the request log, telemetry route naming, bearer validation, client address parsing, rate limit keys, the boot preflight and secret sealing live in one shared package that every API imports.
   - Prevents: each API carrying its own copy of the same fix, and copies that drift (one API fixed, three still open).
   - Acceptance (review): no API carries its own copy of these middlewares or helpers.
2. **The shared package has no runtime dependencies.** It uses only the platform's standard library and what the consuming API already passes in.
   - Prevents: a deploy step that vendors workspace packages having to resolve a second dependency tree.
   - Acceptance (review): a check in the consumer's CI asserts the package manifest lists no runtime dependencies.

3. **Validate the bearer token completely.** The shared bearer check verifies the signature against the issuer's published keys with a pinned algorithm allowlist (never `none`, never a symmetric algorithm for a public-key issuer), the issuer, the audience (this API only), expiry and not-before with a small clock skew. Signing keys are cached and refreshed on an unknown key id, at most once per interval, and a failed refresh keeps the previous keys rather than accepting the token.
   - Prevents: a token minted for another API or tenant being accepted, and an algorithm-confusion bypass.
   - Acceptance (test): tokens with a wrong algorithm, issuer, audience, signature or expiry each return 401, and an unknown key id triggers one refresh.
4. **The dev identity is for development and test only.** `DEV_BYPASS_AUTH` is honoured only when the environment is exactly `development` or `test`. A boot preflight refuses to start any other environment (staging, unset, production) while the bypass or a dev user is set.
   - Prevents: a staging or misconfigured host minting a full-access identity.
   - Acceptance (test): a start with the bypass set and the environment staging, unset or production exits non-zero before listening.

## 7. Bearer validation and dev identity

- **Bearer rules.** One signing algorithm (RS256). Accept both issuer versions of the token. The
  audience is the union of the API's own ids. Cache signing keys for 10 minutes and make at most 10
  key fetches a minute, so a flood of unknown key ids is not a flood of key fetches.
- **Dev identity.** A development identity (a bypass user) is allowed only when the environment is
  exactly `development` or `test`. Staging, an unset environment or any other value never mints it.

- **Unset means production.** An unset environment is production, and a production start aborts on a missing critical
  secret or an enabled bypass ([web-shell-server.md](web-shell-server.md) section 5).

**Acceptance (test):** a token signed with another algorithm, a wrong audience and an unknown key id
flood each fail; the dev identity is refused when the environment is unset or `staging`.

## 8. Checklist

- [ ] Groups cached per user, 5 minute TTL, bounded LRU, single-flight.
- [ ] Lookup failures never cached, access fails closed.
- [ ] Writes read groups live, in-app membership changes invalidate.
- [ ] Lookups limited to referenced groups, 20 ids a batch, 4 in flight, 400 and 429 handled, generation guard.
- [ ] Directory token cached and dropped on a 401.
- [ ] Access-Control-Max-Age 7200, origin guard on writes and preflighted requests (403 from whichever layer refuses).
- [ ] No CORS setting at the hosting platform, checked in CI.
- [ ] Bearer token fully validated, dev bypass development or test only, security helpers in the shared package.
- [ ] Server-Timing only for listed origins, with Timing-Allow-Origin.
- [ ] One log line per request with the route template, no URL, query, token or identity.
- [ ] Telemetry route names from declared templates or `-`, health probes skipped.
- [ ] Keyless ingestion, per-API component with a cap, no auto-created rule mailing a shared group.
- [ ] Telemetry starts after listen, flushes on SIGTERM with a timeout.
- [ ] Export retried at 2, 5 and 10 seconds, 2,000-span buffer.
- [ ] Lightweight exporter, not the all-in-one distribution.
- [ ] One shared runtime package, no runtime dependencies.
- [ ] Bearer rules written, dev identity only in development or test.
- [ ] Slow upstream queries: stale-while-refresh cache, single flight, bounded running and waiting counts with 429 beyond, back-off when throttled, one-shot worker per query (section 10).

## 9. Route contracts

1. **Every route has a contract, the API reference is generated and checked, and the exemption list only shrinks.** A contract names a route's method and path, who may call it, its input and its answers, and is bound to the handler where the route is declared. The API reference is generated from the contracts and a CI step fails when it differs from the committed copy. A route that predates the rule sits on an exemption list; a new route never joins it, so the list only shrinks to zero (`core-ci.py list-shrinks` fails a pull request that adds an entry, the parameters row `Shrink-only lists` names the file). **Acceptance (test):** a route with no contract fails the coverage check, a generated reference that differs fails, and a pull request that adds an exemption fails `list-shrinks`.
2. **Every CSV or spreadsheet export goes through one formula guard.** A text value whose first character is `=`, `+`, `-`, `@`, a tab or a carriage return is written with a leading apostrophe (inside the quotes when the cell is quoted), so opening a download never runs a formula. Numbers and booleans are not text and are never mangled. No code builds a CSV line by hand. **Acceptance (test):** a test writes each leading character and a negative number and asserts the guard and the exemption (`opscenter/server/modules/reports/export_csv_test.py`).

## 10. Slow upstream queries

How an API serves a view that is backed by a slow remote query (a log store, a search service, a
metrics backend) without making every viewer wait for it and without a burst of viewers becoming a
burst of upstream queries. The rules came from reports that moved from a local table to a remote
log store. The health-read helper `createSwrReader` ([Shell packages](web-shell-packages.md)
section 5.11) is the same stale-while-refresh pattern for one status reading; a query-keyed cache
follows the same behaviour (answer at once from the last reading, one shared refresh, a failed
refresh keeps the last good reading with its real age) and may be built on it.

1. **Cache the query result and serve it stale while it refreshes.** Each distinct query (the
   normalised parameters, never the caller's identity when the answer is the same for everyone) has
   a cache entry with a fresh window and a stale window. Inside the fresh window the entry is
   served. Inside the stale window the entry is served at once and one refresh starts in the
   background. Only a request with no entry waits for the upstream. A failed refresh keeps the last
   good entry, records the error and is never cached as an answer.
   - Prevents: every repeat view of a report paying the full upstream latency, and an upstream
     outage turning into an empty page for a view that was loaded a minute ago.
   - Evidence: after reports moved from a local table to a remote log store, serving the stale rows
     at once and refreshing in the background removed the wait on repeat views.
   - Acceptance (test): a second request inside the stale window is answered before the fake
     upstream replies and a later request sees the refreshed rows; a failing refresh leaves the last
     good rows and their age in place.
2. **Single flight per query.** Concurrent requests for the same query, and a refresh that is
   already running, share one upstream call.
   - Prevents: a page that opens in many tabs, or a dashboard of identical panels, sending one
     upstream query per request.
   - Acceptance (test): N concurrent requests for a cold query produce one upstream call, and a
     request during a refresh starts none.
3. **Bound the running and the waiting counts, and answer 429 beyond them.** The API runs at most a
   fixed number of upstream queries at once and lets at most a fixed number of further requests
   wait for a slot. A request past both limits is answered 429 with a `Retry-After`, at once, and
   never queued without bound.
   - Prevents: a burst of distinct queries exhausting the upstream's concurrency allowance, the
     server's memory and every other caller's patience at the same time.
   - Acceptance (test): with the limits set to two running and three waiting, ten distinct
     simultaneous queries run two, queue three and answer the other five 429 with `Retry-After`.
4. **Back off when the upstream throttles.** An upstream answer that means "slow down" (429, or a
   throttling error code) opens a back-off: no new upstream query starts until the time the upstream
   names, or an exponentially growing delay with a cap when it names none. Requests in that window
   are served stale where there is an entry and answered 429 with `Retry-After` where there is not.
   - Prevents: retries and refreshes hammering an upstream that has already said no, which lengthens
     the throttle for everyone.
   - Acceptance (test): a fake upstream that answers 429 once stops all upstream calls until the
     back-off ends, stale entries are served during it, and the first call after it succeeds.
5. **Run each query in a worker that exits when it is answered.** The upstream call, its response
   parsing and its row shaping run in a one-shot worker per query (the one-shot worker rule of the web process health standard, `web-process-health.md` rule 1). The worker keeps no connection, pool or cache open
   after the answer, and the main thread receives only the shaped result.
   - Prevents: parsing a large response on the event loop, and idle upstream connections held open
     by a process that serves a few queries an hour.
   - Evidence: a worker per query that exits when answered kept no connection open and kept
     parsing off the main thread.
   - Acceptance (test): a query against a fake upstream answers while a health request is served
     during the parse, and the worker is gone afterwards.
