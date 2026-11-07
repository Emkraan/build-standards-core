import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Mock } from 'vitest';
import { createOidcAuth } from '../../../shell-packages/app-client/src';
import type { OidcAuthOptions, OidcManagerLike, OidcUser } from '../../../shell-packages/app-client/src';

// A fake OIDC manager with synthetic users only. The sign-in is the real createAuth over the adapter.

const NOW = () => Math.floor(Date.now() / 1000);

function user(over: Partial<OidcUser> = {}): OidcUser {
  return { access_token: 'tok-1', expires_at: NOW() + 3600, refresh_token: 'refresh-1', scope: 'openid api', profile: { sub: 'sub-1', email: 'user-1', name: 'User One' }, ...over };
}

type Methods = 'getUser' | 'signinRedirect' | 'signinRedirectCallback' | 'signinSilent' | 'signoutRedirect' | 'removeUser';
type Mocked = { [K in Methods]: Mock<OidcManagerLike[K]> };
interface Fake extends Omit<OidcManagerLike, Methods>, Mocked {
  stored: OidcUser | null;
  loaded: Array<(u: OidcUser) => void>;
  unloaded: Array<() => void>;
}

function fake(stored: OidcUser | null = user()): Fake {
  const m: Fake = {
    stored,
    loaded: [],
    unloaded: [],
    getUser: vi.fn(async () => m.stored),
    signinRedirect: vi.fn(async () => undefined),
    signinRedirectCallback: vi.fn(async () => user({ state: '/example/users' })),
    signinSilent: vi.fn(async () => user({ access_token: 'tok-2' })),
    signoutRedirect: vi.fn(async () => undefined),
    removeUser: vi.fn(async () => undefined),
    events: {
      addUserLoaded: (cb) => { m.loaded.push(cb); },
      addUserUnloaded: (cb) => { m.unloaded.push(cb); },
    },
  };
  return m;
}

function make(manager: Fake, over: Partial<OidcAuthOptions> = {}) {
  const navigate = vi.fn();
  const auth = createOidcAuth(manager, {
    clientId: 'oidc-client',
    apiScope: 'api',
    mode: 'shell',
    loginAttemptKey: 'test-oidc:login-attempt-at',
    ownsPath: (p) => !/^\/(example)(\/|$)/.test(p),
    authority: 'https://id.example.test',
    navigate,
    ...over,
  });
  return { auth, navigate };
}

afterEach(() => {
  window.history.replaceState(null, '', '/');
  window.sessionStorage.clear();
});

describe('createOidcAuth boot', () => {
  it('adopts the stored user as the account and renders in place', async () => {
    const { auth } = make(fake());
    const res = await auth.boot();
    expect(res.forwarded).toBe(false);
    expect(auth.accountId()).toBe('sub-1');
    expect(auth.getAccount()?.username).toBe('user-1');
  });

  it('with no stored user boots signed out', async () => {
    const { auth } = make(fake(null));
    const res = await auth.boot();
    expect(res.account).toBeNull();
    expect(auth.accountId()).toBe('');
  });

  it('completes a returning sign-in from the URL, routes the stored target and strips the provider parameters', async () => {
    window.history.replaceState(null, '', '/?code=abc&state=xyz&keep=1');
    const mgr = fake(null);
    mgr.signinRedirectCallback.mockImplementation(async () => {
      mgr.stored = user({ state: '/example/users' });
      return mgr.stored;
    });
    const { auth, navigate } = make(mgr);
    const res = await auth.boot();
    expect(mgr.signinRedirectCallback).toHaveBeenCalledTimes(1);
    expect(auth.accountId()).toBe('sub-1');
    expect(res.forwarded).toBe(true);
    expect(navigate).toHaveBeenCalledWith('/example/users');
    expect(window.location.search).toBe('?keep=1');
  });

  it('a state that is not a same-origin path never routes', async () => {
    window.history.replaceState(null, '', '/?code=abc&state=xyz');
    const mgr = fake(null);
    mgr.signinRedirectCallback.mockImplementation(async () => {
      mgr.stored = user({ state: '//evil.example/x' });
      return mgr.stored;
    });
    const { auth, navigate } = make(mgr);
    const res = await auth.boot();
    expect(res.forwarded).toBe(false);
    expect(navigate).not.toHaveBeenCalled();
  });

  it('a failed callback does not break boot, is reported, and the parameters are removed', async () => {
    window.history.replaceState(null, '', '/?error=access_denied&state=xyz');
    const mgr = fake(null);
    mgr.signinRedirectCallback.mockRejectedValue(new Error('state mismatch'));
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const { auth } = make(mgr);
    const res = await auth.boot();
    warn.mockRestore();
    expect(res.account).toBeNull();
    expect((res.error as Error).message).toBe('state mismatch');
    expect(window.location.search).toBe('');
  });

  it('ignores a URL that has a code but no state', async () => {
    window.history.replaceState(null, '', '/?code=abc');
    const mgr = fake(null);
    const { auth } = make(mgr);
    await auth.boot();
    expect(mgr.signinRedirectCallback).not.toHaveBeenCalled();
  });
});

describe('createOidcAuth tokens', () => {
  it('returns the cached access token while it is fresh', async () => {
    const mgr = fake();
    const { auth } = make(mgr);
    await auth.boot();
    expect(await auth.acquireToken()).toBe('tok-1');
    expect(mgr.signinSilent).not.toHaveBeenCalled();
  });

  it('renews an expired token with the refresh token only', async () => {
    const mgr = fake(user({ expires_at: NOW() - 10 }));
    const { auth } = make(mgr);
    await auth.boot();
    expect(await auth.acquireToken()).toBe('tok-2');
    expect(mgr.signinSilent).toHaveBeenCalledTimes(1);
  });

  it('an expired session with no refresh token needs interaction (silent caller)', async () => {
    const mgr = fake(user({ expires_at: NOW() - 10, refresh_token: undefined }));
    const { auth } = make(mgr);
    await auth.boot();
    await expect(auth.acquireToken('api', { interactive: false })).rejects.toMatchObject({ interactionRequired: true });
    expect(mgr.signinSilent).not.toHaveBeenCalled();
  });

  it('a failed renewal needs interaction', async () => {
    const mgr = fake(user({ expires_at: NOW() - 10 }));
    mgr.signinSilent.mockRejectedValue(new Error('invalid_grant'));
    const { auth } = make(mgr);
    await auth.boot();
    await expect(auth.acquireToken('api', { interactive: false })).rejects.toMatchObject({ interactionRequired: true });
  });

  it('a scope the session was never granted needs interaction, and the interactive path signs in with it', async () => {
    const mgr = fake(user({ scope: 'openid' }));
    const { auth } = make(mgr);
    await auth.boot();
    await expect(auth.acquireToken('api', { interactive: false })).rejects.toMatchObject({ interactionRequired: true });
    void auth.acquireToken('api').catch(() => undefined);
    await vi.waitFor(() => expect(mgr.signinRedirect).toHaveBeenCalled());
    expect(mgr.signinRedirect.mock.calls[0]?.[0]?.scope).toBe('openid api');
  });
});

describe('createOidcAuth sign-in and sign-out', () => {
  it('login starts the provider sign-in with the API and identity scopes and the start page as state', async () => {
    const mgr = fake(null);
    const { auth } = make(mgr);
    await auth.login('/example/users');
    expect(mgr.signinRedirect).toHaveBeenCalledWith({ scope: 'api openid profile email', state: '/example/users' });
  });

  it('a module never signs in itself: it bounces to the shell', async () => {
    const mgr = fake(null);
    const { auth, navigate } = make(mgr, { mode: 'module', basePath: '/example/' });
    await auth.boot();
    expect(await auth.ensureSessionOrBounce()).toBe(false);
    expect(mgr.signinRedirect).not.toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledTimes(1);
    expect(String(navigate.mock.calls[0]?.[0])).toContain('/?returnTo=');
  });

  it('logout runs the listeners, then the provider end-session with the post-logout address', async () => {
    const mgr = fake();
    const { auth } = make(mgr);
    await auth.boot();
    const cleared = vi.fn();
    auth.onLogout(cleared);
    await auth.logout();
    expect(cleared).toHaveBeenCalled();
    expect(mgr.signoutRedirect).toHaveBeenCalledWith({ post_logout_redirect_uri: `${window.location.origin}/signed-out` });
  });

  it('a provider with no end-session endpoint clears the local session and lands on the post-logout page', async () => {
    const mgr = fake();
    mgr.signoutRedirect.mockRejectedValue(new Error('no end_session_endpoint'));
    const { auth, navigate } = make(mgr);
    await auth.boot();
    await auth.logout();
    expect(mgr.removeUser).toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledWith(`${window.location.origin}/signed-out`);
  });
});

describe('createOidcAuth account changes', () => {
  it('a user unloaded by the manager signs this tab out of its cached account', async () => {
    const mgr = fake();
    const { auth } = make(mgr);
    await auth.boot();
    const seen: string[] = [];
    auth.onAccountChange((id) => seen.push(id));
    mgr.stored = null;
    for (const cb of mgr.unloaded) cb();
    expect(auth.accountId()).toBe('');
    expect(seen).toEqual(['']);
  });

  it('a different user loaded by the manager is announced', async () => {
    const mgr = fake();
    const { auth } = make(mgr);
    await auth.boot();
    const seen: string[] = [];
    auth.onAccountChange((id) => seen.push(id));
    for (const cb of mgr.loaded) cb(user({ profile: { sub: 'sub-2' } }));
    expect(seen).toEqual(['sub-2']);
  });
});
