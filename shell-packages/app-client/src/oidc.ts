/* A generic OIDC sign-in (an Authentik broker with an Entra upstream, or any OIDC provider) that plugs into
   createAuth through its existing `msal` seam. The shell and every module still share one boot, one
   loop guard, one return-target rule and one 401 path; only the thing that talks to the identity provider
   changes. The package takes no dependency on an OIDC library: the app builds the manager (oidc-client-ts
   `UserManager`, or anything with the same few methods) and passes it in. `@azure/msal-browser` stays a
   peer, because createAuth imports its event names and lookup policy. */

import { EventType } from '@azure/msal-browser';
import type { AccountInfo, AuthenticationResult, EventMessage, IPublicClientApplication } from '@azure/msal-browser';
import { createAuth } from './auth';
import type { Auth, AuthOptions } from './auth';

/** The part of an oidc-client-ts `User` the adapter reads. */
export interface OidcUser {
  access_token: string;
  /** Seconds since the epoch. */
  expires_at?: number | undefined;
  refresh_token?: string | undefined;
  /** Space separated scopes the token was issued for. */
  scope?: string | undefined;
  /** The `state` passed to the sign-in request: where to land afterwards. */
  state?: unknown;
  expired?: boolean | undefined;
  profile: { sub: string; name?: string | undefined; email?: string | undefined; preferred_username?: string | undefined };
}

/** The part of an oidc-client-ts `UserManager` the adapter calls. */
export interface OidcManagerLike {
  getUser(): Promise<OidcUser | null>;
  signinRedirect(args?: { scope?: string; state?: unknown }): Promise<void>;
  signinRedirectCallback(url?: string): Promise<OidcUser>;
  /** A refresh-token renewal (an iframe renewal is never used by the adapter). */
  signinSilent(args?: { scope?: string }): Promise<OidcUser | null>;
  signoutRedirect(args?: { post_logout_redirect_uri?: string }): Promise<void>;
  removeUser(): Promise<void>;
  events: {
    addUserLoaded(cb: (user: OidcUser) => void): void;
    addUserUnloaded(cb: () => void): void;
  };
}

export interface OidcClientOptions {
  /** The identity provider's host, shown as the account environment. */
  authority?: string | undefined;
  /** Test seams. */
  window?: Window | undefined;
  navigate?: ((url: string) => void) | undefined;
}

type FakeEvent = (event: EventMessage) => void;

/** An error the existing classifier reads as "only an interactive sign-in can clear this". */
function interactionRequired(message: string, cause?: unknown): Error {
  const e = new Error(message) as Error & { errorCode: string; cause?: unknown };
  e.name = 'InteractionRequiredAuthError';
  e.errorCode = 'interaction_required';
  if (cause !== undefined) e.cause = cause;
  return e;
}

function accountOf(user: OidcUser, authority: string): AccountInfo {
  const sub = user.profile.sub;
  return {
    homeAccountId: sub,
    localAccountId: sub,
    environment: authority,
    tenantId: '',
    username: user.profile.email || user.profile.preferred_username || sub,
    name: user.profile.name,
  } as AccountInfo;
}

/**
 * Adapt an OIDC manager to the small slice of MSAL's public client that createAuth uses. Pass the
 * result as `msal` in createAuth, or use createOidcAuth. The signed-in user is held in memory and
 * refreshed from the manager's store on a storage or focus event, so a sign-out in another tab is seen.
 */
export function createOidcClient(manager: OidcManagerLike, options: OidcClientOptions = {}): IPublicClientApplication {
  const win = options.window ?? (typeof window === 'undefined' ? undefined : window);
  const authority = options.authority ?? '';
  let current: OidcUser | null = null;
  let active: AccountInfo | null = null;
  const callbacks: FakeEvent[] = [];
  const emit = (eventType: string): void => {
    for (const cb of callbacks) {
      try {
        cb({ eventType } as EventMessage);
      } catch {
        /* a listener never breaks the client */
      }
    }
  };

  const setUser = (user: OidcUser | null): void => {
    current = user;
    // The active account is the signed-in user: a different user loaded (another tab signed in as
    // someone else) replaces it, a signed-out manager clears it.
    if (!user || (active && active.homeAccountId !== user.profile.sub)) active = null;
  };
  const accounts = (): AccountInfo[] => (current ? [accountOf(current, authority)] : []);

  async function refresh(): Promise<void> {
    const before = current?.profile.sub ?? null;
    let user: OidcUser | null = null;
    try {
      user = await manager.getUser();
    } catch {
      user = null;
    }
    setUser(user);
    const after = current?.profile.sub ?? null;
    if (before !== after) emit(after ? EventType.LOGIN_SUCCESS : EventType.ACCOUNT_REMOVED);
  }

  const covers = (user: OidcUser, scopes: string[]): boolean => {
    if (!user.scope) return true;
    const granted = new Set(user.scope.split(/\s+/).filter(Boolean));
    return scopes.every((s) => granted.has(s));
  };

  const client = {
    async initialize(): Promise<void> {
      manager.events.addUserLoaded((user) => {
        const changed = current?.profile.sub !== user.profile.sub;
        setUser(user);
        if (changed) emit(EventType.LOGIN_SUCCESS);
      });
      manager.events.addUserUnloaded(() => {
        setUser(null);
        emit(EventType.ACCOUNT_REMOVED);
      });
      try {
        win?.addEventListener('storage', () => void refresh());
        win?.addEventListener('focus', () => void refresh());
      } catch {
        /* no window events (tests) */
      }
      current = await manager.getUser().catch(() => null);
    },
    addEventCallback(cb: FakeEvent): string {
      callbacks.push(cb);
      return String(callbacks.length);
    },
    getAllAccounts: accounts,
    getActiveAccount: (): AccountInfo | null => active,
    setActiveAccount(account: AccountInfo | null): void {
      active = account;
    },
    async handleRedirectPromise(): Promise<AuthenticationResult | null> {
      const search = win?.location.search ?? '';
      const params = new URLSearchParams(search);
      if (!params.has('state') || !(params.has('code') || params.has('error'))) return null;
      // The callback reads the code and state from the URL. Whatever it answers, the provider's
      // parameters are removed from the address so a reload never replays them.
      try {
        const user = await manager.signinRedirectCallback(win?.location.href);
        setUser(user);
        return { account: accountOf(user, authority), accessToken: user.access_token, state: typeof user.state === 'string' ? user.state : '' } as unknown as AuthenticationResult;
      } finally {
        try {
          for (const k of ['code', 'state', 'session_state', 'iss', 'error', 'error_description']) params.delete(k);
          const rest = params.toString();
          win?.history.replaceState(win.history.state, '', win.location.pathname + (rest ? `?${rest}` : '') + win.location.hash);
        } catch {
          /* history unavailable */
        }
      }
    },
    async acquireTokenSilent(request: { scopes: string[]; account?: AccountInfo }): Promise<AuthenticationResult> {
      let user = current ?? (await manager.getUser().catch(() => null));
      if (!user) throw interactionRequired('No signed-in user.');
      setUser(user);
      const fresh = (u: OidcUser): boolean => !u.expired && (u.expires_at === undefined || u.expires_at * 1000 > Date.now() + 30_000);
      if (!covers(user, request.scopes)) throw interactionRequired(`The session was not granted ${request.scopes.join(' ')}.`);
      if (!fresh(user)) {
        // Refresh-token renewal only. Without one the session is over and only a sign-in clears it.
        if (!user.refresh_token) throw interactionRequired('The session expired.');
        try {
          const renewed = await manager.signinSilent();
          if (!renewed) throw new Error('renewal returned no user');
          user = renewed;
          setUser(user);
        } catch (e) {
          throw interactionRequired('The session could not be renewed.', e);
        }
      }
      return {
        accessToken: user.access_token,
        account: accountOf(user, authority),
        scopes: request.scopes,
        expiresOn: user.expires_at ? new Date(user.expires_at * 1000) : null,
      } as unknown as AuthenticationResult;
    },
    async acquireTokenRedirect(request: { scopes: string[]; state?: string }): Promise<void> {
      await manager.signinRedirect({ scope: ['openid', ...request.scopes].join(' '), state: request.state });
    },
    async loginRedirect(request: { scopes: string[]; state?: string }): Promise<void> {
      await manager.signinRedirect({ scope: request.scopes.join(' '), state: request.state });
    },
    async logoutRedirect(request?: { postLogoutRedirectUri?: string }): Promise<void> {
      try {
        await manager.signoutRedirect(request?.postLogoutRedirectUri ? { post_logout_redirect_uri: request.postLogoutRedirectUri } : undefined);
      } catch (e) {
        // A provider with no end-session endpoint: clear the local session and land on the same page.
        await manager.removeUser();
        setUser(null);
        if (request?.postLogoutRedirectUri && (options.navigate || win)) (options.navigate ?? ((u: string) => win?.location.replace(u)))(request.postLogoutRedirectUri);
        else throw e;
      }
    },
  };
  return client as unknown as IPublicClientApplication;
}

export interface OidcAuthOptions extends Omit<AuthOptions, 'msal' | 'tenantId' | 'authority'> {
  /** The identity provider's host, shown as the account environment. */
  authority?: string | undefined;
}

/**
 * createAuth over an OIDC manager: the same Auth (boot, tokens, login, logout, the 401 path, module
 * bounce) with the sign-in done by the provider the manager points at. `clientId` is the OIDC client id
 * and `apiScope` an OIDC scope string (for example "api").
 */
export function createOidcAuth(manager: OidcManagerLike, options: OidcAuthOptions): Auth {
  return createAuth({
    ...options,
    tenantId: '',
    authority: options.authority ?? '',
    msal: createOidcClient(manager, { authority: options.authority, window: options.window, navigate: options.navigate }),
  });
}
