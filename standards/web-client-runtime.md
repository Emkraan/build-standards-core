# Web Client Runtime Standard

Version: 1.0 | Last reviewed: 2026-10-14 | Status: current | Scope: web (single page apps that sign
in with an OIDC library and call their own API). Sections 3.7, 3.8 and 6 also apply to any web app that
polls an API, including a local app or an app behind platform-level auth.

How a single page app boots its sign-in, renews tokens, calls its API and loads its code so the
first paint is fast and a long-lived session never strands the user. The rules name MSAL terms where
that library is the common case, and apply the same way to any OIDC client library. Every rule was
proved on a platform of several single page apps sharing one origin behind an API gateway. This doc
is the source of truth. Where a reference implementation differs, the implementation is fixed, or
the consumer records an explicit exception (README, "Source of truth and explicit exceptions").

Related: [Web API Runtime](web-api-runtime.md) (the server side of the same calls), [Web Design
System](web-ui.md) (shell, feed strip, per-app storage), [Live Actions](live-actions.md) (caches
and invalidation after a write), [Local Ops App](local-ops-app.md) (stale-while-revalidate and
polling budgets).

Each rule names the failure it prevents and its acceptance line. Evidence is a measured number from
the platform the rule came from.

---

## 1. Auth boot

1. **One canonical boot sequence.** The app initializes the auth library, handles the redirect response, sets the active account, then renders. The stored return target is routed in-app (MSAL `navigateToLoginRequestUrl: false`), never by a second full page load.
   - Prevents: a sign-in return booting the app two or three times (one load for the redirect, another for the library's own navigation to the stored URL).
   - Acceptance (test): a simulated sign-in return renders the target route with one boot and no extra navigation.
2. **One boot module for every app.** The boot sequence lives in the shared client package (section 5), not in each app.
   - Prevents: apps on the same origin drifting into different boot orders, where one app's fix never reaches the others.
   - Acceptance (review): no app calls the auth library's initialize or redirect handling itself.
3. **An app without a session bounces once, and the return target is validated.** An app with no session sends the user to sign in with the current in-app path as the return target. On return the target is accepted only when it is a same-origin path: it starts with a single `/`, and it is rejected when protocol-relative (`//`), when it holds a backslash or a control character, when it is longer than 2,048 characters, or when it resolves to another origin. A rejected target routes to the app home.
   - Prevents: an open redirect through an unchecked return target, and a sign-in loop on a malformed one.
   - Acceptance (test): each rejected form routes to the app home, and a valid deep link returns to itself.
4. **An account change clears the old account's state.** When the active account changes (in this tab or another through the shared cache), cached API data and error state for the old account are cleared and the app re-boots for the new one.
   - Prevents: one user seeing another's data or a stale error after switching accounts.
   - Acceptance (test): switching account in a second tab clears cached data and the error banner in the first.

## 2. Token renewal without hidden iframes

1. **Never depend on hidden-iframe renewal when the origin denies framing.** When the app origin sends X-Frame-Options DENY (or a frame-ancestors policy that blocks itself), silent renewal uses the refresh token and never the hidden iframe fallback. Either MSAL cache lookup policy qualifies: refresh-token-only, or cache-then-refresh (the cached access token first, then the refresh token), as long as no iframe is created.
   - Prevents: renewal that waits for an iframe the browser refuses to load, then fails.
   - Evidence: users with a session older than 24 hours saw "API unreachable" with zero API calls sent.
   - Acceptance (test): with an expired access token and a valid refresh token, renewal succeeds with no iframe created.
2. **Iframe timeouts mean interaction required.** Timeout errors from the silent path (MSAL monitor_window_timeout and its relatives) are treated as interaction required, so the user is sent to sign in once.
   - Prevents: a timeout surfacing as a network failure that no retry can fix.
   - Acceptance (test): a silent call that fails with a timeout code starts one interactive sign-in.
3. **Only real session expiry redirects.** Interaction required is decided by the session-expiry codes (expired or missing session, refresh token expired). Consent and conditional access policy errors are shown to the user once and never start a redirect.
   - Prevents: a redirect loop where the identity provider keeps answering the same policy error.
   - Acceptance (test): a consent error renders a message and starts no redirect.
4. **Check the loop guard before redirecting.** A guard (a counter or timestamp in session storage) is read before every interactive redirect, and a tripped guard shows a sign-in button instead.
   - Prevents: an endless redirect loop when the guard is only written after the redirect started.
   - Acceptance (test): two redirects inside the guard window show the button and start no third redirect.
5. **Single-flight the interactive redirect.** One redirect promise is shared by every caller, and the library's interaction in progress error is treated as "already redirecting".
   - Prevents: parallel API calls each starting a redirect, and an interaction in progress error shown as a failure.
   - Acceptance (test): five concurrent calls that need interaction start one redirect and report no error.
6. **Match errors by name and code too.** Error checks compare the error name and code as well as instanceof.
   - Prevents: a second copy of the auth library in the bundle (two apps or a workspace package resolving their own) making every instanceof check false.
   - Acceptance (test): an error object from a different library copy with the same name and code is classified the same way.

## 3. API client

1. **The bearer token goes only to the configured API base.** The client attaches the token only to paths under the configured base, and rejects absolute URLs, protocol-relative paths, backslashes, path traversal and encoded dot segments.
   - Prevents: a token sent to another host through a crafted or careless path.
   - Acceptance (test): each rejected form throws before any request leaves, and no token is attached.
2. **Identical GETs in flight share one request.** A GET for a key that is already in flight returns the same promise.
   - Prevents: a page whose components each ask for the same data sending the same call several times at load.
   - Acceptance (test): three concurrent GETs of one path produce one request.
3. **Stale-while-revalidate with a per-key TTL.** Cached reads return at once and refresh in the background when older than their TTL, and each key may set its own TTL. A poll interval on the page meets this when every cached read is refreshed at least that often; no cached value lives forever.
   - Prevents: a blank page on every navigation, and slow data refreshed as often as fast data.
   - Acceptance (test): a stale key returns the cached value and starts one background refresh.
4. **Persist only identity reads, and always as stale.** Only identity reads (who am I, my permissions) persist to sessionStorage so the shell paints at once on load. They are always treated as stale, and cleared on sign-out and on an account change.
   - Prevents: a blank shell while identity loads, and one user's permissions painting for the next user on a shared browser.
   - Acceptance (test): a reload paints from storage and refetches, sign-out and an account switch clear it.
5. **Invalidate drops in-flight GETs.** Invalidating a key also forgets any in-flight GET for it, so the next read starts fresh.
   - Prevents: a caller after a write receiving the pre-mutation response that was already on its way.
   - Acceptance (test): a GET in flight during a write is not returned to a caller that reads after the invalidate.
6. **A rejected refresh leaves no stuck entry.** A failed or superseded request removes its in-flight entry, and a stale rejection never overwrites newer data.
   - Prevents: a key that stays "loading" forever after one network error.
   - Acceptance (test): after a rejected GET the next read sends a new request.
7. **Background polls never navigate.** A poll passes its own on-401 handler that throws, so only a user-started call may send the user to sign in.
   - Prevents: a background poll redirecting the user away from unsaved work.
   - Acceptance (test): a 401 on a poll throws to the poller and starts no navigation.
8. **Polls pause while the tab is hidden.** Polling stops on visibility hidden and resumes, with one immediate refresh, when the tab is visible again.
   - Prevents: hidden tabs spending API and directory capacity all day.
   - Acceptance (test): no poll fires while the document is hidden.
   - Kit part: `usePolling` implements this rule (pause while hidden, one refresh on resume, no overlapping polls).

## 4. Bundles

1. **Lazy routes, first page started at boot, the rest prefetched on idle.** Every route is a lazy chunk. The route the user landed on starts loading during boot, and the other routes prefetch when the browser is idle.
   - Prevents: one large entry chunk that holds every page, and a pause on the first navigation after load.
   - Evidence: entry chunks fell from 637 KB to 91 KB and from 866 KB to 244 KB, and time to content fell from 4.3 s to 0.6 s together with the API runtime fixes.
   - Acceptance (review): the build reports an entry chunk under the budget the consumer sets.
2. **Long-lived vendor chunks.** The framework and the auth library build into their own named chunks so an app release does not change their hashes.
   - Prevents: every deploy forcing every user to download the framework again.
   - Acceptance (review): the build config names the vendor chunks and their hashes survive an app-only change.
3. **Large inline assets become hashed files.** Images, fonts and data above a few kilobytes are emitted as hashed files, not inlined into the script.
   - Prevents: a large base64 asset parsed on every load and invalidated with every script change.
   - Acceptance (review): no inline asset above the bundler's inline limit is in the entry chunk.

## 5. Shared client package

1. **One client package for every app on the origin.** Auth boot, token renewal, the API client and polling live in one package that every app imports.
   - Prevents: one app fixed and the others still stranding users, as happened with renewal (section 2).
   - Acceptance (review): no app carries its own token or fetch wrapper.
2. **One token cache across apps on the same origin.** Apps on one origin share the auth library's cache location and client configuration, so signing in to one signs in to all.
   - Prevents: a second sign-in when the user moves between apps, and two caches renewing the same session.
   - Acceptance (test): after signing in to one app, another app on the origin acquires a token silently.

## 6. Live feed strip

1. **Every app shows the same live strip from one feed endpoint.** A health line and platform announcements come from one feed endpoint that requires sign-in and no extra permission, and every app renders them with the shared component.
   - Prevents: each app inventing its own banner, so an outage notice appears in one app and not the next.
   - Acceptance (review): every app mounts the shared strip against the one feed endpoint.
2. **Per-app items are gated by the user's own permissions.** The feed adds items for an app only when the caller holds that app's permissions, and each app may add its own items to the strip.
   - Prevents: a feed that leaks one app's items to users who cannot open it.
   - Acceptance (test): a user without an app's permission receives none of its items.

## 7. Checklist

- [ ] One boot: initialize, handle redirect, set the account, route the target in-app.
- [ ] Refresh-token renewal where framing is denied (refresh-token-only or cache-then-refresh), no iframe fallback.
- [ ] Timeouts mean interaction required, policy errors never redirect.
- [ ] Loop guard read before redirecting, one shared redirect promise.
- [ ] Errors matched by name and code.
- [ ] Bearer only to the API base, unsafe paths rejected.
- [ ] GET dedupe, stale-while-revalidate with per-key TTL.
- [ ] Only identity reads persisted, cleared on sign-out and account change.
- [ ] Invalidate drops in-flight GETs, rejections leave nothing stuck.
- [ ] Polls never navigate and pause while hidden.
- [ ] Lazy routes, idle prefetch, named vendor chunks, hashed assets.
- [ ] One client package and one token cache per origin.
- [ ] One feed endpoint for the strip, per-app items gated by permission.
