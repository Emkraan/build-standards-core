/* One MSAL boot for the whole shell. The shell and every module share one origin, one SPA app
   registration and one localStorage token cache, so a shell session is visible to every module and
   a module never renders its own sign-in. */

import { CacheLookupPolicy, EventType, PublicClientApplication } from '@azure/msal-browser';
import type { AccountInfo, AuthenticationResult, Configuration, EventMessage, IPublicClientApplication } from '@azure/msal-browser';
import { safeReturnTo } from './returnTo';

/** The shell owns the sign-in surface. A module bounces a signed-out caller to it. */
export type AuthMode = 'shell' | 'module';

/** The session key the shell's sign-in page stores a module's ?returnTo under. */
export const RETURN_TO_KEY = 'shell.returnTo';

export interface AuthError extends Error {
  status?: number | undefined;
  interactionRequired?: boolean | undefined;
  /** "sign_in_loop": a token redirect for this scope already ran inside the loop window. */
  code?: string | undefined;
}

export interface AuthOptions {
  clientId: string;
  tenantId: string;
  /** Defaults to https://login.microsoftonline.com/<tenantId>. */
  authority?: string | undefined;
  /** The default API scope, for example api://<api>/access_as_user. Empty means no token. */
  apiScope: string;
  mode: AuthMode;
  /** Local `vite dev` with no client id: no Entra flow, the API's dev identity applies. */
  devBypass?: boolean | undefined;
  /** sessionStorage key of the 401 loop guard, one per app (for example "example:login-attempt-at"). */
  loginAttemptKey: string;
  /** Where logout lands, relative to the origin. Shell "/signed-out", modules "/". */
  postLogoutPath?: string | undefined;
  /**
   * Whether a same-origin path belongs to this SPA, so a stored target is routed with
   * history.replaceState instead of a reload. Modules default to their base path. The shell passes
   * a check that excludes the module prefixes. Without one the shell owns nothing, so every target is
   * a full navigation (a module path is never swallowed by the shell router).
   */
  ownsPath?: ((path: string) => boolean) | undefined;
  /** The module's base path ("/example/"). Used by the default ownsPath. Without it a module owns no
   *  path, so every return target is a full navigation. */
  basePath?: string | undefined;
  /** Test seams. */
  msal?: IPublicClientApplication | undefined;
  navigate?: ((url: string) => void) | undefined;
  window?: Window | undefined;
}

export interface TokenOptions {
  /** false = silent only. On interaction required it throws err.interactionRequired instead of redirecting. */
  interactive?: boolean | undefined;
}

export interface BootResult {
  /** True when boot sent the page to another SPA. Do not render. */
  forwarded: boolean;
  account: AccountInfo | null;
  /** Why a returning redirect failed (consent denied, state mismatch, an AADSTS error). Boot still completes. */
  error?: unknown;
}

export interface Auth {
  readonly msal: IPublicClientApplication;
  readonly devBypass: boolean;
  readonly mode: AuthMode;
  readonly apiScope: string;
  readonly loginRequest: { scopes: string[] };
  initialize(): Promise<void>;
  /** initialize, handleRedirectPromise, adopt the account, route a stored target. Call once before render. */
  boot(): Promise<BootResult>;
  getAccount(): AccountInfo | null;
  /** Stable id of the signed-in account ("dev" under the bypass, "" when signed out). */
  accountId(): string;
  acquireToken(scope?: string, opts?: TokenOptions): Promise<string | null>;
  /** Start token acquisition early so the first API call does not wait on a refresh. */
  warm(scope?: string): void;
  login(returnTo?: string | null): Promise<void>;
  logout(): Promise<void>;
  /** Modules: true to render, false while bouncing to the shell sign-in. */
  ensureSessionOrBounce(): Promise<boolean>;
  /** The 401 path shared by every API client. Loop-guarded: a second 401 inside a minute throws. */
  loginOn401(): Promise<never>;
  onAccountChange(cb: (accountId: string) => void): () => void;
  onLogout(cb: () => void): () => void;
}

const DEV_CLIENT_ID = '11111111-1111-1111-1111-111111111111';
const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]', '::1']);
/** How long a 401 waits on the sign-in navigation before it gives up and rejects. */
const SIGN_IN_WAIT_MS = 20_000;
const LOOP_WINDOW_MS = 60_000;
/**
 * Silent failures that only an interactive sign-in can clear. The hidden-iframe renewal can never
 * finish on this origin (the redirect URI page is served with X-Frame-Options DENY), so a silent
 * call that still reaches it ends in one of these after the MSAL wait instead of a token.
 */
const IFRAME_FAILURE_CODES = new Set([
  'monitor_window_timeout',
  'empty_window_error',
  'hash_empty_error',
  'hash_does_not_contain_known_properties',
  'block_iframe_reload',
]);

/**
 * Entra answers that mean the session itself expired or was revoked, so a sign-in redirect gets
 * a working refresh token. MSAL can return these as a plain invalid_grant ServerError instead of
 * an InteractionRequiredAuthError.
 *   700084 SPA refresh token past its 24 hour lifetime
 *   700082 refresh token expired from inactivity
 *   700081 refresh token past its maximum lifetime
 *   70008  refresh token expired or revoked
 *   70043  refresh token expired by a sign-in frequency policy
 *   50173  grant revoked (password change or reset)
 *   50133  session invalid after a password expiry or change
 *   50132  session revoked or SSO session expired
 *   50089  flow token expired
 *   50078, 50079, 50076  MFA or a new registration needed again
 */
const SESSION_EXPIRY_AADSTS = new Set(['700084', '700082', '700081', '70008', '70043', '50173', '50133', '50132', '50089', '50078', '50079', '50076']);
/** MSAL suberrors that mean the same thing as the codes above. */
const SESSION_EXPIRY_SUBERRORS = new Set(['bad_token', 'token_expired', 'user_password_expired']);
/**
 * invalid_grant answers that are configuration, not session expiry. A sign-in cannot fix them,
 * so they are reported at once and never redirected.
 *   65001, 65004, 90094  consent missing or declined
 *   70011  invalid scope
 *   500011, 700016, 7000112  resource or app not found or disabled
 *   650052, 650057  app missing a service principal or permission
 *   50105  user not assigned to the app
 *   53000, 53001, 53002, 53003  Conditional Access device, compliance or block
 */
const CONFIG_AADSTS = new Set(['65001', '65004', '90094', '70011', '500011', '700016', '7000112', '650052', '650057', '50105', '53000', '53001', '53002', '53003']);

interface MsalLikeError {
  name?: unknown;
  errorCode?: unknown;
  subError?: unknown;
  errorNo?: unknown;
  errorMessage?: unknown;
  message?: unknown;
}

function asMsalError(err: unknown): MsalLikeError | null {
  return err && typeof err === 'object' ? (err as MsalLikeError) : null;
}

/**
 * The AADSTS number on an MSAL error, from errorNo or the message text. Matched on fields, never
 * instanceof, so an error from a second copy of MSAL in a bundle reads the same.
 */
export function aadstsCode(err: unknown): string | null {
  const e = asMsalError(err);
  if (!e) return null;
  if (typeof e.errorNo === 'string' && /^\d+$/.test(e.errorNo)) return e.errorNo;
  if (typeof e.errorNo === 'number') return String(e.errorNo);
  for (const text of [e.errorMessage, e.message]) {
    if (typeof text !== 'string') continue;
    const m = /AADSTS(\d+)/.exec(text);
    if (m?.[1]) return m[1];
  }
  return null;
}

/**
 * Error codes MSAL reports for a token only interaction can clear (its
 * InteractionRequiredAuthError codes and the Entra server codes it wraps). Matched on the code
 * as well as the error name, so an error that carries one of these codes under another name
 * (a wrapper, another MSAL copy or version) still takes the interaction path.
 */
const INTERACTION_REQUIRED_CODES = new Set([
  'interaction_required',
  'login_required',
  'consent_required',
  'no_tokens_found',
  'native_account_unavailable',
  'refresh_token_expired',
  'bad_token',
]);

/**
 * How a plain invalid_grant is handled. "expiry": a known session expiry, redirect. "config": a
 * known configuration error, report it and never redirect. "unknown" (no code, or a code Entra
 * adds later): one redirect behind the loop guard, so a new expiry code never strands the user
 * and a new configuration code ends in one clear error instead of a loop.
 */
export function invalidGrantKind(err: unknown): 'expiry' | 'config' | 'unknown' {
  const e = asMsalError(err);
  const n = aadstsCode(e);
  if (n && CONFIG_AADSTS.has(n)) return 'config';
  if (n && SESSION_EXPIRY_AADSTS.has(n)) return 'expiry';
  if (e && typeof e.subError === 'string' && SESSION_EXPIRY_SUBERRORS.has(e.subError)) return 'expiry';
  return 'unknown';
}

function isNamed(err: MsalLikeError, name: string): boolean {
  return err.name === name;
}

/** True for a sign-in that only an interactive redirect can clear. */
export function needsInteraction(err: unknown): boolean {
  const e = asMsalError(err);
  if (!e) return false;
  // MSAL already classified it (InteractionRequiredAuthError, any copy of MSAL).
  if (isNamed(e, 'InteractionRequiredAuthError')) return true;
  const code = typeof e.errorCode === 'string' ? e.errorCode : '';
  if (INTERACTION_REQUIRED_CODES.has(code)) return true;
  if (code === 'invalid_grant') return invalidGrantKind(e) !== 'config';
  // Defensive: a renewal that still reaches the hidden iframe (another lookup policy, a future
  // MSAL default) ends in one of these, never in a token.
  return IFRAME_FAILURE_CODES.has(code);
}

function isInteractionInProgress(err: unknown): boolean {
  const e = asMsalError(err);
  return Boolean(e && e.errorCode === 'interaction_in_progress');
}

function legacyStartPageKey(clientId: string): string {
  // MSAL v3 records the page an interactive redirect started from under this temporary key.
  // A page not yet on this package may still start redirects without a state, so the shell reads
  // it as a fallback target (validated like any other). This is an MSAL internal: remove the
  // fallback once every page is on this package. If a future MSAL renames the key the only
  // effect is that such a redirect lands on the shell home instead of the module.
  return `msal.${clientId}.request.origin`;
}

export function createAuth(options: AuthOptions): Auth {
  const win = options.window ?? window;
  const origin = win.location.origin;
  // The bypass only ever applies to a local dev server with no real client id, whatever the
  // caller passes, so a misconfigured build can never skip Entra on a real host.
  const devBypass = Boolean(options.devBypass) && !options.clientId && LOCAL_HOSTS.has(win.location.hostname);
  const clientId = options.clientId || (devBypass ? DEV_CLIENT_ID : '');
  const authority = options.authority || `https://login.microsoftonline.com/${options.tenantId}`;
  const apiScope = options.apiScope || '';
  const mode = options.mode;
  const postLogoutPath = options.postLogoutPath ?? (mode === 'shell' ? '/signed-out' : '/');
  // A module owns its base path only, on a segment boundary ("/example/" never owns
  // "/example-admin"). No base path, or the bare root, owns nothing.
  const basePath = options.basePath ? (options.basePath.endsWith('/') ? options.basePath : `${options.basePath}/`) : '';
  const ownsPath =
    options.ownsPath ??
    (mode === 'shell' || !basePath || basePath === '/'
      ? () => false
      : (path: string) => path === basePath.slice(0, -1) || path.startsWith(basePath));
  const navigate = options.navigate ?? ((url: string) => win.location.replace(url));

  const config: Configuration = {
    auth: {
      clientId,
      authority,
      // Same redirect URI rule as before: the origin root, registered once for the shell and
      // every module.
      redirectUri: origin,
      postLogoutRedirectUri: `${origin}${postLogoutPath}`,
      // The page routes the stored target itself (see boot), so a returning sign-in boots the
      // SPA once instead of once on the redirect URI and again on the start page.
      navigateToLoginRequestUrl: false,
    },
    cache: {
      // localStorage on purpose: the shell and every module share one origin and one cache, so a
      // token acquired on the shell is reused silently by each module.
      cacheLocation: 'localStorage',
      storeAuthStateInCookie: false,
    },
  };

  const msal: IPublicClientApplication = options.msal ?? new PublicClientApplication(config);
  const loginRequest = { scopes: [apiScope, 'openid', 'profile', 'email'].filter(Boolean) };

  const accountListeners = new Set<(id: string) => void>();
  const logoutListeners = new Set<() => void>();
  let lastAccountId: string | null = null;

  let initPromise: Promise<void> | null = null;
  function initialize(): Promise<void> {
    if (!initPromise) {
      initPromise = msal.initialize().then(() => {
        // Another tab signing out or switching accounts changes the shared localStorage cache.
        // MSAL raises account events for it once storage events are on, and the storage and
        // focus listeners below re-check the account as a fallback, so this tab clears its
        // cached answers too.
        const withStorageEvents = msal as IPublicClientApplication & { enableAccountStorageEvents?: () => void };
        if (typeof withStorageEvents.enableAccountStorageEvents === 'function') {
          try {
            withStorageEvents.enableAccountStorageEvents();
          } catch {
            /* the listeners below still cover it */
          }
        }
        try {
          win.addEventListener('storage', (e: StorageEvent) => {
            if (e.storageArea === undefined || e.storageArea === null || e.storageArea === win.localStorage) noteAccount();
          });
          win.addEventListener('focus', () => noteAccount());
          win.document?.addEventListener('visibilitychange', () => {
            if (win.document.visibilityState !== 'hidden') noteAccount();
          });
        } catch {
          /* no window events (tests) */
        }
        if (typeof msal.addEventCallback === 'function') {
          msal.addEventCallback((event: EventMessage) => {
            if (
              event.eventType === EventType.ACCOUNT_ADDED ||
              event.eventType === EventType.ACCOUNT_REMOVED ||
              event.eventType === EventType.LOGIN_SUCCESS ||
              event.eventType === EventType.ACTIVE_ACCOUNT_CHANGED
            ) {
              noteAccount();
            }
          });
        }
      });
    }
    return initPromise;
  }

  function getAccount(): AccountInfo | null {
    return msal.getActiveAccount() || msal.getAllAccounts()[0] || null;
  }

  function accountId(): string {
    if (devBypass) return 'dev';
    return getAccount()?.homeAccountId ?? '';
  }

  function noteAccount(): void {
    const id = accountId();
    if (lastAccountId !== null && lastAccountId !== id) {
      for (const cb of accountListeners) cb(id);
    }
    lastAccountId = id;
  }

  function currentPath(): string {
    return win.location.pathname + win.location.search + win.location.hash;
  }

  function readSession(key: string): string | null {
    try {
      return win.sessionStorage.getItem(key);
    } catch {
      return null;
    }
  }

  function writeSession(key: string, value: string): void {
    try {
      win.sessionStorage.setItem(key, value);
    } catch {
      /* storage unavailable */
    }
  }

  /** Shell: move a module's ?returnTo into the session so login and boot both see it, and drop it from the URL. */
  function adoptReturnToQuery(): void {
    let params: URLSearchParams;
    try {
      params = new URLSearchParams(win.location.search);
    } catch {
      return;
    }
    if (!params.has('returnTo')) return;
    const target = safeReturnTo(params.get('returnTo'), origin);
    if (target) writeSession(RETURN_TO_KEY, target);
    params.delete('returnTo');
    const rest = params.toString();
    try {
      win.history.replaceState(win.history.state, '', win.location.pathname + (rest ? `?${rest}` : '') + win.location.hash);
    } catch {
      /* history unavailable: the query stays, the stored target is still used */
    }
  }

  function removeSession(key: string): void {
    try {
      win.sessionStorage.removeItem(key);
    } catch {
      /* storage unavailable */
    }
  }

  /** Route a validated same-origin target: in place when this SPA owns it, else a replace. */
  function route(target: string): boolean {
    const path = target.split(/[?#]/)[0] ?? target;
    if (ownsPath(path)) {
      if (target !== currentPath()) win.history.replaceState(win.history.state, '', target);
      return false;
    }
    navigate(target);
    return true;
  }

  async function boot(): Promise<BootResult> {
    await initialize();
    if (mode === 'shell') adoptReturnToQuery();
    const legacyStart = readSession(legacyStartPageKey(clientId));
    let result: AuthenticationResult | null = null;
    let redirectError: unknown;
    try {
      result = await msal.handleRedirectPromise();
    } catch (e) {
      // A failed returning sign-in (consent denied, state mismatch, AADSTS) must not break
      // boot, but it is reported so the sign-in page can say why.
      result = null;
      redirectError = e;
      try {
        console.warn('Sign-in redirect failed', e);
      } catch {
        /* no console */
      }
    }
    const withError = <T extends BootResult>(r: T): T => (redirectError === undefined ? r : { ...r, error: redirectError });

    if (result?.account) msal.setActiveAccount(result.account);
    const accounts = msal.getAllAccounts();
    if (!msal.getActiveAccount() && accounts[0]) msal.setActiveAccount(accounts[0]);
    const account = getAccount();
    lastAccountId = accountId();

    if (!account) return withError({ forwarded: false, account: null });

    // A returning interactive sign-in: the request carried its start page as state. A redirect
    // started by a page not yet on this package has no state, so fall back to the start
    // page MSAL recorded.
    let target: string | null = null;
    if (result) {
      target = safeReturnTo(result.state, origin) ?? safeReturnTo(legacyStart, origin);
    }
    // A module bounced a signed-out caller to the shell, which stored the module's path.
    if (mode === 'shell') {
      const stored = safeReturnTo(readSession(RETURN_TO_KEY), origin);
      removeSession(RETURN_TO_KEY);
      target = target ?? stored;
    }
    if (target) return withError({ forwarded: route(target), account });
    return withError({ forwarded: false, account });
  }

  /** Rejects after the sign-in wait, so a call is never left in flight forever. */
  function waitForNavigation(): Promise<never> {
    return new Promise<never>((_resolve, reject) => {
      win.setTimeout(() => {
        const stuck: AuthError = new Error('Sign-in did not start. Reload the page to sign in again.');
        stuck.status = 401;
        stuck.interactionRequired = true;
        reject(stuck);
      }, SIGN_IN_WAIT_MS);
    });
  }

  // Concurrent 401s share one sign-in navigation instead of tripping the loop guard.
  let signingIn: Promise<never> | null = null;

  /** sessionStorage key of the token redirect loop guard, one per scope. */
  function tokenAttemptKey(scope: string): string {
    return `${options.loginAttemptKey}:token:${scope}`;
  }

  function loopError(cause: unknown): AuthError {
    const n = aadstsCode(cause);
    const err: AuthError = new Error(
      `Signed in, but Entra still requires interaction for this app${n ? ` (AADSTS${n})` : ''}. Check the app consent, the API scope and Conditional Access, then reload the page.`,
    );
    err.code = 'sign_in_loop';
    err.interactionRequired = true;
    (err as AuthError & { cause?: unknown }).cause = cause;
    return err;
  }

  // Loop guard stamps, one per scope. A plain timestamp is a redirect this scope started for its
  // own token. "j:<timestamp>" records a scope that joined a navigation another scope (or a 401
  // sign-in) started. That navigation never asked Entra for the joined scope, so the joined scope
  // still gets one redirect of its own after the page returns, and only then does the guard
  // report a loop. Either stamp inside the loop window counts as a recent navigation.
  const JOINED_PREFIX = 'j:';
  function readTokenStamp(scope: string): { at: number; joined: boolean } | null {
    const raw = readSession(tokenAttemptKey(scope));
    if (raw === null) return null;
    const joined = raw.startsWith(JOINED_PREFIX);
    const at = Number(joined ? raw.slice(JOINED_PREFIX.length) : raw);
    const now = Date.now();
    // A stamp from the future (a clock change, a bad write) or an unreadable one is ignored
    // instead of blocking.
    if (!Number.isFinite(at) || at > now || now - at >= LOOP_WINDOW_MS) return null;
    return { at, joined };
  }

  let loopReported = false;
  let configReported = false;
  function reportLoop(cause: unknown): Promise<never> {
    const err = loopError(cause);
    if (!loopReported) {
      loopReported = true;
      try {
        console.error(err.message, cause);
      } catch {
        /* no console */
      }
    }
    return Promise.reject(err);
  }

  /** A caller joins a navigation that is already running and records its scope as joined. */
  function joinNavigation(scope: string, running: Promise<never>, cause: unknown): Promise<never> {
    const stamp = readTokenStamp(scope);
    // This scope already had a redirect of its own and still needs interaction: that is a loop,
    // whatever the other navigation is for.
    if (stamp && !stamp.joined) return reportLoop(cause);
    // A scope that already joined a navigation keeps its first stamp, so riding along on
    // further navigations never resets its window.
    if (stamp) return running;
    const mark = `${JOINED_PREFIX}${Date.now()}`;
    writeSession(tokenAttemptKey(scope), mark);
    return running.catch((e: unknown) => {
      // The shared navigation never left the page, so it does not count for this scope either.
      if (readSession(tokenAttemptKey(scope)) === mark) removeSession(tokenAttemptKey(scope));
      throw e;
    });
  }

  // One interactive redirect at a time, for every caller and every scope. Page load often starts
  // several calls at once, and MSAL rejects every redirect after the first with
  // interaction_in_progress, so later callers wait on the first one instead of failing while the
  // page navigates away. A 401 sign-in that is already running counts too. MSAL asks for one
  // resource per redirect, so a caller for another scope joins without its scope being requested.
  // The guard records it as joined (see readTokenStamp).
  let redirecting: Promise<never> | null = null;
  let redirectingScope: string | null = null;
  function redirectForToken(scope: string, account: AccountInfo, cause: unknown): Promise<never> {
    // Another caller for the same scope waits on that scope's own redirect.
    if (redirecting && redirectingScope === scope) return redirecting;
    if (redirecting) return joinNavigation(scope, redirecting, cause);
    if (signingIn) return joinNavigation(scope, signingIn, cause);
    // The loop guard runs BEFORE the redirect. A token for this scope that still needs
    // interaction within a minute of its own last redirect is not an expired session (consent,
    // scope, Conditional Access), so another redirect would only bounce the page again. A scope
    // that only joined another navigation gets this one redirect of its own first.
    const stamp = readTokenStamp(scope);
    if (stamp && !stamp.joined) return reportLoop(cause);
    const now = Date.now();
    writeSession(tokenAttemptKey(scope), String(now));
    const run = (async (): Promise<never> => {
      try {
        // A full-page redirect. It lands on the origin root and boot sends the caller back
        // here through the state. The page is navigating away, so the call waits for it (a
        // caller must not send its request without a token while the redirect runs).
        await msal.acquireTokenRedirect({ scopes: [scope], account, state: safeReturnTo(currentPath(), origin, { allowRoot: true }) ?? '/' });
      } catch (e) {
        // Another interaction (a sign-in redirect) already runs: wait for that navigation. This
        // scope joined it, so the guard records it as joined: a token that still needs
        // interaction once it lands gets one redirect of its own, then is reported as a loop.
        if (!isInteractionInProgress(e)) {
          // This redirect never started, so it does not count toward the loop guard.
          removeSession(tokenAttemptKey(scope));
          throw e;
        }
        writeSession(tokenAttemptKey(scope), `${JOINED_PREFIX}${now}`);
      }
      try {
        return await waitForNavigation();
      } catch (stuck) {
        // The page never left, so no redirect came back: a slow or blocked navigation is not
        // a loop, and the next call may redirect again.
        removeSession(tokenAttemptKey(scope));
        throw stuck;
      }
    })();
    redirecting = run;
    redirectingScope = scope;
    // Once it settles (the page did not leave), a later call may try again.
    run.catch(() => {
      if (redirecting === run) {
        redirecting = null;
        redirectingScope = null;
      }
    });
    return run;
  }

  async function acquireToken(scope: string = apiScope, { interactive = true }: TokenOptions = {}): Promise<string | null> {
    if (devBypass) return null;
    await initialize();
    if (!scope) return null;
    const account = getAccount();
    if (!account) return null;
    try {
      // Cache and refresh token only. MSAL's default falls back to a hidden iframe once the
      // refresh token expires (24 hours for an SPA), and that iframe cannot load the redirect URI
      // here, so every call waited out the iframe timeout and failed without reaching the API.
      // Skipping it turns an expired session into interaction required at once, and the
      // full-page redirect below renews it through the Entra session cookie.
      const res = await msal.acquireTokenSilent({
        scopes: [scope],
        account,
        cacheLookupPolicy: CacheLookupPolicy.AccessTokenAndRefreshToken,
      });
      // A token arrived, so the last redirect for this scope worked: the loop guard resets.
      if (readSession(tokenAttemptKey(scope)) !== null) {
        removeSession(tokenAttemptKey(scope));
        loopReported = false;
      }
      return res.accessToken;
    } catch (err) {
      if (needsInteraction(err)) {
        if (interactive) return redirectForToken(scope, account, err);
        (err as AuthError).interactionRequired = true;
      } else if (interactive && asMsalError(err)?.errorCode === 'invalid_grant') {
        // A configuration problem (consent, scope, Conditional Access, assignment) is never
        // redirected. It keeps the MSAL error (and its AADSTS message) for the caller, carries
        // code sign_in_config, and is logged once per page instead of on every call.
        (err as AuthError).code = 'sign_in_config';
        if (!configReported) {
          configReported = true;
          const n = aadstsCode(err);
          try {
            console.error(
              `Entra refused a token for this app${n ? ` (AADSTS${n})` : ''}. Check the app consent, the API scope, Conditional Access and the user assignment.`,
              err,
            );
          } catch {
            /* no console */
          }
        }
      } else if (!interactive && asMsalError(err)?.errorCode === 'invalid_grant') {
        // A silent-only caller (a side read) reads every token grant failure as needing a
        // sign-in, so it lands on its 401 path instead of looking like an outage.
        (err as AuthError).interactionRequired = true;
      }
      throw err;
    }
  }

  function warm(scope: string = apiScope): void {
    acquireToken(scope, { interactive: false }).catch(() => undefined);
  }

  async function login(returnTo?: string | null): Promise<void> {
    await initialize();
    // A module never runs its own interactive sign-in: the shell owns it.
    if (mode === 'module') {
      bounceToShell(safeReturnTo(returnTo ?? null, origin));
      return;
    }
    const stored = safeReturnTo(readSession(RETURN_TO_KEY), origin);
    const state = safeReturnTo(returnTo ?? stored ?? currentPath(), origin, { allowRoot: true }) ?? '/';
    await msal.loginRedirect({ ...loginRequest, state });
  }

  async function logout(): Promise<void> {
    await initialize();
    for (const cb of logoutListeners) {
      try {
        cb();
      } catch {
        /* a cache clear must never block sign-out */
      }
    }
    removeSession(RETURN_TO_KEY);
    await msal.logoutRedirect({ postLogoutRedirectUri: `${origin}${postLogoutPath}` });
  }

  function bounceToShell(target?: string | null): void {
    const returnTo = target || win.location.pathname + win.location.search;
    navigate(`${origin}/?returnTo=${encodeURIComponent(returnTo)}`);
  }

  async function ensureSessionOrBounce(): Promise<boolean> {
    await initialize();
    if (devBypass) return true;
    if (getAccount()) return true;
    if (mode === 'shell') return false;
    // No silent SSO here. ssoSilent is the hidden iframe the origin root refuses to be framed in
    // (X-Frame-Options DENY), so it only ever waited out the MSAL timeout (about 10 s) before
    // this same bounce. The shell runs the sign-in and sends the caller straight back.
    try {
      bounceToShell();
    } catch {
      /* navigation failed, nothing else to do */
    }
    return false;
  }

  function loginOn401(): Promise<never> {
    if (signingIn) return signingIn;
    const last = Number(readSession(options.loginAttemptKey) || 0);
    if (Date.now() - last < LOOP_WINDOW_MS) {
      const err: AuthError = new Error(
        'Signed in, but the API rejected the token (401). Check API_AUDIENCE on the server and VITE_API_SCOPE on the frontend.',
      );
      err.status = 401;
      return Promise.reject(err);
    }
    try {
      win.sessionStorage.setItem(options.loginAttemptKey, String(Date.now()));
    } catch {
      /* storage unavailable */
    }
    if (mode === 'shell') login(currentPath()).catch(() => undefined);
    else bounceToShell();
    // The page is navigating away. Wait for it, and reject if the navigation never happens so
    // a cached read is not left in flight forever.
    const run = new Promise<never>((_resolve, reject) => {
      win.setTimeout(() => {
        const err: AuthError = new Error('Sign-in did not start. Reload the page to sign in again.');
        err.status = 401;
        reject(err);
      }, SIGN_IN_WAIT_MS);
    });
    signingIn = run;
    run.catch(() => {
      if (signingIn === run) signingIn = null;
    });
    return run;
  }

  return {
    msal,
    devBypass,
    mode,
    apiScope,
    loginRequest,
    initialize,
    boot,
    getAccount,
    accountId,
    acquireToken,
    warm,
    login,
    logout,
    ensureSessionOrBounce,
    loginOn401,
    onAccountChange(cb) {
      accountListeners.add(cb);
      return () => accountListeners.delete(cb);
    },
    onLogout(cb) {
      logoutListeners.add(cb);
      return () => logoutListeners.delete(cb);
    },
  };
}
