import { describe, expect, it, vi } from 'vitest';
import { BrowserAuthError, CacheLookupPolicy, InteractionRequiredAuthError, ServerError } from '@azure/msal-browser';
import type { AccountInfo, IPublicClientApplication } from '@azure/msal-browser';
import { RETURN_TO_KEY, createAuth, safeReturnTo } from '../../../shell-packages/app-client/src';
import type { AuthOptions } from '../../../shell-packages/app-client/src';

const ORIGIN = window.location.origin;

const ACCOUNT = { homeAccountId: 'acct-1', username: 'user-1' } as unknown as AccountInfo;

interface FakeMsal {
  initialize: ReturnType<typeof vi.fn>;
  handleRedirectPromise: ReturnType<typeof vi.fn>;
  getActiveAccount: () => AccountInfo | null;
  setActiveAccount: (a: AccountInfo | null) => void;
  getAllAccounts: () => AccountInfo[];
  acquireTokenSilent: ReturnType<typeof vi.fn>;
  acquireTokenRedirect: ReturnType<typeof vi.fn>;
  loginRedirect: ReturnType<typeof vi.fn>;
  logoutRedirect: ReturnType<typeof vi.fn>;
  ssoSilent: ReturnType<typeof vi.fn>;
  addEventCallback: (cb: (e: { eventType: string }) => void) => string;
  emit: (eventType: string) => void;
  accounts: AccountInfo[];
}

function fakeMsal(accounts: AccountInfo[] = [ACCOUNT], redirect: unknown = null): FakeMsal {
  let active: AccountInfo | null = null;
  const cbs: Array<(e: { eventType: string }) => void> = [];
  const m: FakeMsal = {
    accounts,
    initialize: vi.fn(async () => undefined),
    handleRedirectPromise: vi.fn(async () => redirect),
    getActiveAccount: () => active,
    setActiveAccount: (a) => {
      active = a;
    },
    getAllAccounts: () => m.accounts,
    acquireTokenSilent: vi.fn(async () => ({ accessToken: 'tok' })),
    acquireTokenRedirect: vi.fn(async () => undefined),
    loginRedirect: vi.fn(async () => undefined),
    logoutRedirect: vi.fn(async () => undefined),
    ssoSilent: vi.fn(async () => {
      throw new InteractionRequiredAuthError('interaction_required');
    }),
    addEventCallback: (cb) => {
      cbs.push(cb);
      return 'id';
    },
    emit: (eventType) => cbs.forEach((cb) => cb({ eventType })),
  };
  return m;
}

function make(msal: FakeMsal, over: Partial<AuthOptions> = {}) {
  const navigate = vi.fn();
  const auth = createAuth({
    clientId: 'client',
    tenantId: 'tenant',
    apiScope: 'api://x/access_as_user',
    mode: 'shell',
    loginAttemptKey: 'test:login-attempt-at',
    ownsPath: (p) => !/^\/(example|xerox|klaxon|talos)(\/|$)/.test(p),
    msal: msal as unknown as IPublicClientApplication,
    navigate,
    ...over,
  });
  return { auth, navigate };
}

describe('safeReturnTo', () => {
  it('accepts same-origin paths and same-origin absolute URLs', () => {
    expect(safeReturnTo('/example/users?q=1#x', ORIGIN)).toBe('/example/users?q=1#x');
    expect(safeReturnTo(`${ORIGIN}/xerox/devices`, ORIGIN)).toBe('/xerox/devices');
  });

  it('rejects protocol-relative, backslash, control characters, other origins and scripts', () => {
    for (const bad of ['//evil.com', '/\\evil.com', '/\t/evil.com', 'https://evil.com/x', 'javascript:alert(1)', 'example', '', '   ']) {
      expect(safeReturnTo(bad, ORIGIN)).toBeNull();
    }
    expect(safeReturnTo(null, ORIGIN)).toBeNull();
    for (const dots of ['/.//evil.com', '/a/..//evil.com', '/example/..//evil.com', '/./\\evil.com', `${ORIGIN}/.//evil.com`]) {
      expect(safeReturnTo(dots, ORIGIN)).toBeNull();
    }
    expect(safeReturnTo('/' + 'a'.repeat(3000), ORIGIN)).toBeNull();
  });

  it('rejects the bare root unless allowed', () => {
    expect(safeReturnTo('/', ORIGIN)).toBeNull();
    expect(safeReturnTo('/', ORIGIN, { allowRoot: true })).toBe('/');
  });
});

describe('createAuth boot', () => {
  it('adopts the first account and renders in place with nothing to route', async () => {
    const msal = fakeMsal();
    const { auth, navigate } = make(msal);
    const res = await auth.boot();
    expect(res).toEqual({ forwarded: false, account: ACCOUNT });
    expect(msal.getActiveAccount()).toBe(ACCOUNT);
    expect(navigate).not.toHaveBeenCalled();
  });

  it('forwards a returning sign-in to a module named in the state, once', async () => {
    const msal = fakeMsal([ACCOUNT], { account: ACCOUNT, state: '/example/users' });
    const { auth, navigate } = make(msal);
    const res = await auth.boot();
    expect(res.forwarded).toBe(true);
    expect(navigate).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith('/example/users');
  });

  it('routes a shell target in place without a reload', async () => {
    const msal = fakeMsal([ACCOUNT], { account: ACCOUNT, state: '/estate?x=1' });
    const { auth, navigate } = make(msal);
    const spy = vi.spyOn(window.history, 'replaceState');
    try {
      const res = await auth.boot();
      expect(res.forwarded).toBe(false);
      expect(navigate).not.toHaveBeenCalled();
      expect(spy.mock.calls[0]?.slice(1)).toEqual(['', '/estate?x=1']);
      expect(window.location.pathname).toBe('/estate');
    } finally {
      window.history.replaceState(null, '', '/');
      spy.mockRestore();
    }
  });

  it('ignores a state that is not a same-origin path', async () => {
    const msal = fakeMsal([ACCOUNT], { account: ACCOUNT, state: '//evil.com/x' });
    const { auth, navigate } = make(msal);
    expect((await auth.boot()).forwarded).toBe(false);
    expect(navigate).not.toHaveBeenCalled();
  });

  it('falls back to the start page MSAL recorded for a redirect started without a state', async () => {
    window.sessionStorage.setItem('msal.client.request.origin', `${ORIGIN}/klaxon/alerts`);
    const msal = fakeMsal([ACCOUNT], { account: ACCOUNT, state: '' });
    const { auth, navigate } = make(msal);
    expect((await auth.boot()).forwarded).toBe(true);
    expect(navigate).toHaveBeenCalledWith('/klaxon/alerts');
  });

  it('consumes the shell returnTo a module bounce stored, only with an account', async () => {
    window.sessionStorage.setItem(RETURN_TO_KEY, '/xerox/devices');
    const signedOut = make(fakeMsal([]));
    expect((await signedOut.auth.boot()).forwarded).toBe(false);
    expect(window.sessionStorage.getItem(RETURN_TO_KEY)).toBe('/xerox/devices');

    const { auth, navigate } = make(fakeMsal());
    expect((await auth.boot()).forwarded).toBe(true);
    expect(navigate).toHaveBeenCalledWith('/xerox/devices');
    expect(window.sessionStorage.getItem(RETURN_TO_KEY)).toBeNull();
  });

  it('shell boot moves a module ?returnTo into the session and off the URL', async () => {
    window.history.replaceState(null, '', '/?returnTo=%2Fexample%2Fusers%3Fq%3D1&x=2');
    try {
      const signedOut = make(fakeMsal([]));
      await signedOut.auth.boot();
      expect(window.sessionStorage.getItem(RETURN_TO_KEY)).toBe('/example/users?q=1');
      expect(window.location.search).toBe('?x=2');
      await signedOut.auth.login();
      expect(signedOut.auth.msal.loginRedirect).toHaveBeenCalledWith(expect.objectContaining({ state: '/example/users?q=1' }));

      window.history.replaceState(null, '', '/?returnTo=%2F.%2F%2Fevil.com');
      window.sessionStorage.clear();
      await make(fakeMsal([])).auth.boot();
      expect(window.sessionStorage.getItem(RETURN_TO_KEY)).toBeNull();
      expect(window.location.search).toBe('');
    } finally {
      window.history.replaceState(null, '', '/');
    }
  });

  it('a shell with no ownsPath navigates every target instead of routing it in place', async () => {
    const msal = fakeMsal([ACCOUNT], { account: ACCOUNT, state: '/example/users' });
    const { auth, navigate } = make(msal, { ownsPath: undefined });
    expect((await auth.boot()).forwarded).toBe(true);
    expect(navigate).toHaveBeenCalledWith('/example/users');
  });

  it('drops a stored returnTo that is not same-origin', async () => {
    window.sessionStorage.setItem(RETURN_TO_KEY, '/\\evil.com');
    const { auth, navigate } = make(fakeMsal());
    expect((await auth.boot()).forwarded).toBe(false);
    expect(navigate).not.toHaveBeenCalled();
    expect(window.sessionStorage.getItem(RETURN_TO_KEY)).toBeNull();
  });

  it('never treats a module returnTo store as its own (modules ignore the shell key)', async () => {
    window.sessionStorage.setItem(RETURN_TO_KEY, '/xerox/devices');
    const { auth, navigate } = make(fakeMsal(), { mode: 'module', basePath: '/example/', ownsPath: undefined });
    expect((await auth.boot()).forwarded).toBe(false);
    expect(navigate).not.toHaveBeenCalled();
  });
});

describe('createAuth tokens', () => {
  it('acquires silently first', async () => {
    const msal = fakeMsal();
    const { auth } = make(msal);
    await auth.boot();
    expect(await auth.acquireToken()).toBe('tok');
    expect(msal.acquireTokenSilent).toHaveBeenCalledWith({
      scopes: ['api://x/access_as_user'],
      account: ACCOUNT,
      cacheLookupPolicy: CacheLookupPolicy.AccessTokenAndRefreshToken,
    });
    expect(msal.acquireTokenRedirect).not.toHaveBeenCalled();
  });

  it('never asks MSAL for the hidden-iframe renewal the redirect URI page refuses', async () => {
    const msal = fakeMsal();
    const { auth } = make(msal);
    await auth.boot();
    await auth.acquireToken();
    await auth.acquireToken('api://other/x', { interactive: false });
    for (const call of msal.acquireTokenSilent.mock.calls) {
      expect(call[0]).toMatchObject({ cacheLookupPolicy: CacheLookupPolicy.AccessTokenAndRefreshToken });
    }
  });

  // The redirect path arms the sign-in wait timer, so these run on fake timers and drain it.
  async function expectRedirect(err: unknown) {
    // Each case is a fresh page session, so the loop guard of the previous case does not apply.
    window.sessionStorage.clear();
    vi.useFakeTimers();
    try {
      const msal = fakeMsal();
      msal.acquireTokenSilent.mockRejectedValueOnce(err);
      const { auth } = make(msal);
      await auth.boot();
      let settled = false;
      const p = auth.acquireToken().then(() => (settled = true), () => (settled = true));
      await vi.advanceTimersByTimeAsync(0);
      expect(msal.acquireTokenRedirect).toHaveBeenCalledTimes(1);
      // The page is navigating away: the call waits instead of failing.
      expect(settled).toBe(false);
      await vi.runAllTimersAsync();
      await p;
    } finally {
      vi.useRealTimers();
    }
  }

  it('an expired refresh token redirects for a new one instead of failing the call', async () => {
    await expectRedirect(new InteractionRequiredAuthError('refresh_token_expired'));
    await expectRedirect(new InteractionRequiredAuthError('no_tokens_found'));
  });

  it('a plain invalid_grant from Entra on the refresh redirects for a known session expiry', async () => {
    await expectRedirect(new ServerError('invalid_grant', 'AADSTS700084: The refresh token was issued to a single page app'));
    await expectRedirect(new ServerError('invalid_grant', 'AADSTS700082: The refresh token has expired due to inactivity'));
    await expectRedirect(new ServerError('invalid_grant', 'expired', undefined, '50173'));
    await expectRedirect(new ServerError('invalid_grant', 'AADSTS50133: Session is invalid due to expiration or recent password change'));
    await expectRedirect(new ServerError('invalid_grant', 'AADSTS70043: The refresh token has expired or is invalid due to sign-in frequency checks'));
    await expectRedirect(new ServerError('invalid_grant', 'no code in the text', 'bad_token'));
  });

  it('an invalid_grant that is a configuration problem is reported, never redirected', async () => {
    const errors = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    for (const message of [
      'AADSTS65001: The user or administrator has not consented to use the application',
      'AADSTS70011: The provided value for the input parameter scope is not valid',
      'AADSTS53000: Device is not in required device state',
      'AADSTS50105: The signed in user is not assigned to a role for the application',
    ]) {
      const msal = fakeMsal();
      msal.acquireTokenSilent.mockRejectedValueOnce(new ServerError('invalid_grant', message));
      const { auth } = make(msal);
      await auth.boot();
      await expect(auth.acquireToken()).rejects.toMatchObject({ errorCode: 'invalid_grant', code: 'sign_in_config' });
      expect(msal.acquireTokenRedirect).not.toHaveBeenCalled();
    }
    errors.mockRestore();
  });

  it('a configuration invalid_grant is logged once per page, not on every call', async () => {
    const errors = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    try {
      const msal = fakeMsal();
      msal.acquireTokenSilent.mockRejectedValue(new ServerError('invalid_grant', 'AADSTS65001: consent'));
      const { auth } = make(msal);
      await auth.boot();
      for (let i = 0; i < 3; i += 1) {
        await expect(auth.acquireToken()).rejects.toMatchObject({ code: 'sign_in_config' });
      }
      expect(errors).toHaveBeenCalledTimes(1);
      expect(String(errors.mock.calls[0]?.[0])).toMatch(/AADSTS65001/);
      expect(msal.acquireTokenRedirect).not.toHaveBeenCalled();
    } finally {
      errors.mockRestore();
    }
  });

  it('an invalid_grant with no code or an unlisted code gets one guarded redirect, so it never strands the user', async () => {
    await expectRedirect(new ServerError('invalid_grant', 'invalid_grant with no code'));
    await expectRedirect(new ServerError('invalid_grant', 'AADSTS9999999: a code added later'));
  });

  it('a silent-only caller reads any invalid_grant as interaction required, so a side read gets its 401', async () => {
    const msal = fakeMsal();
    msal.acquireTokenSilent.mockRejectedValueOnce(new ServerError('invalid_grant', 'AADSTS65001: consent'));
    const { auth } = make(msal);
    await auth.boot();
    await expect(auth.acquireToken('api://other/x', { interactive: false })).rejects.toMatchObject({ errorCode: 'invalid_grant', interactionRequired: true });
    expect(msal.acquireTokenRedirect).not.toHaveBeenCalled();
  });

  it('matches MSAL errors by name and code, so a second copy of MSAL in a bundle still redirects', async () => {
    const foreign = (name: string, errorCode: string, errorMessage = '') => Object.assign(new Error(errorMessage), { name, errorCode, errorMessage, subError: '' });
    await expectRedirect(foreign('InteractionRequiredAuthError', 'interaction_required'));
    await expectRedirect(foreign('ServerError', 'invalid_grant', 'AADSTS700084: expired'));
    await expectRedirect(foreign('BrowserAuthError', 'monitor_window_timeout'));
    // An interaction-required code under another error name still redirects.
    for (const code of ['interaction_required', 'login_required', 'consent_required', 'no_tokens_found', 'refresh_token_expired', 'bad_token']) {
      await expectRedirect(foreign('AuthError', code));
    }
    const msal = fakeMsal();
    msal.acquireTokenSilent.mockRejectedValueOnce(foreign('ServerError', 'invalid_grant', 'AADSTS65001: consent'));
    const { auth } = make(msal);
    await auth.boot();
    await expect(auth.acquireToken()).rejects.toMatchObject({ errorCode: 'invalid_grant' });
    expect(msal.acquireTokenRedirect).not.toHaveBeenCalled();
  });

  it('checks the loop guard before redirecting and reports one clear error once it trips', async () => {
    vi.useFakeTimers();
    const errors = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    try {
      // The session expired and the redirect ran (the page left).
      const before = fakeMsal();
      before.acquireTokenSilent.mockRejectedValue(new InteractionRequiredAuthError('consent_required', 'AADSTS65001: consent'));
      const first = make(before);
      await first.auth.boot();
      void first.auth.acquireToken().catch(() => undefined);
      await vi.advanceTimersByTimeAsync(0);
      expect(before.acquireTokenRedirect).toHaveBeenCalledTimes(1);
      // The page came back (a new page, same tab session) and the token still needs interaction.
      const after = fakeMsal();
      after.acquireTokenSilent.mockRejectedValue(new InteractionRequiredAuthError('consent_required', 'AADSTS65001: consent'));
      const { auth } = make(after);
      await auth.boot();
      const again = await auth.acquireToken().catch((e: unknown) => e);
      const third = await auth.acquireToken().catch((e: unknown) => e);
      // No second redirect: one clear error instead, logged once.
      expect(after.acquireTokenRedirect).not.toHaveBeenCalled();
      expect(again).toMatchObject({ code: 'sign_in_loop', interactionRequired: true });
      expect((again as Error).message).toMatch(/AADSTS65001/);
      expect(third).toMatchObject({ code: 'sign_in_loop' });
      expect(errors).toHaveBeenCalledTimes(1);
      // After the window a new redirect may run.
      await vi.advanceTimersByTimeAsync(60_000);
      void auth.acquireToken().catch(() => undefined);
      await vi.advanceTimersByTimeAsync(0);
      expect(after.acquireTokenRedirect).toHaveBeenCalledTimes(1);
      await vi.runAllTimersAsync();
    } finally {
      errors.mockRestore();
      vi.useRealTimers();
    }
  });

  it('a redirect that never left the page does not count as a loop', async () => {
    vi.useFakeTimers();
    try {
      const msal = fakeMsal();
      msal.acquireTokenSilent.mockRejectedValue(new InteractionRequiredAuthError('interaction_required'));
      const { auth } = make(msal);
      await auth.boot();
      const first = auth.acquireToken().catch((e: unknown) => e);
      await vi.advanceTimersByTimeAsync(21_000);
      expect(await first).toMatchObject({ status: 401, interactionRequired: true });
      // A slow or blocked navigation: the next call redirects again instead of a loop error.
      void auth.acquireToken().catch(() => undefined);
      await vi.advanceTimersByTimeAsync(0);
      expect(msal.acquireTokenRedirect).toHaveBeenCalledTimes(2);
      await vi.runAllTimersAsync();
    } finally {
      vi.useRealTimers();
    }
  });

  it('a redirect that joined another interaction still counts toward the loop guard', async () => {
    const msal = fakeMsal();
    msal.acquireTokenSilent.mockRejectedValueOnce(new InteractionRequiredAuthError('interaction_required'));
    msal.acquireTokenRedirect.mockRejectedValueOnce(Object.assign(new Error('busy'), { errorCode: 'interaction_in_progress' }));
    const { auth } = make(msal);
    await auth.boot();
    void auth.acquireToken().catch(() => undefined);
    await new Promise((r) => setTimeout(r, 0));
    // Recorded as joined: the running interaction never asked for this scope.
    expect(window.sessionStorage.getItem('test:login-attempt-at:token:api://x/access_as_user')).toMatch(/^j:\d+$/);
  });

  it('ignores a loop guard stamp from the future', async () => {
    window.sessionStorage.setItem('test:login-attempt-at:token:api://x/access_as_user', String(Date.now() + 3_600_000));
    const msal = fakeMsal();
    msal.acquireTokenSilent.mockRejectedValueOnce(new InteractionRequiredAuthError('interaction_required'));
    const { auth } = make(msal);
    await auth.boot();
    void auth.acquireToken().catch(() => undefined);
    await new Promise((r) => setTimeout(r, 0));
    expect(msal.acquireTokenRedirect).toHaveBeenCalledTimes(1);
  });

  it('a redirect that fails to start does not count toward the loop guard', async () => {
    const msal = fakeMsal();
    msal.acquireTokenSilent.mockRejectedValue(new InteractionRequiredAuthError('interaction_required'));
    msal.acquireTokenRedirect.mockRejectedValue(Object.assign(new Error('in a frame'), { errorCode: 'redirect_in_iframe' }));
    const { auth } = make(msal);
    await auth.boot();
    await expect(auth.acquireToken()).rejects.toMatchObject({ errorCode: 'redirect_in_iframe' });
    await expect(auth.acquireToken()).rejects.toMatchObject({ errorCode: 'redirect_in_iframe' });
    expect(msal.acquireTokenRedirect).toHaveBeenCalledTimes(2);
  });

  it('a returning redirect that produced a token resets the loop guard for that scope', async () => {
    const msal = fakeMsal();
    const { auth } = make(msal);
    await auth.boot();
    window.sessionStorage.setItem('test:login-attempt-at:token:api://x/access_as_user', String(Date.now()));
    expect(await auth.acquireToken()).toBe('tok');
    expect(window.sessionStorage.getItem('test:login-attempt-at:token:api://x/access_as_user')).toBeNull();
    // Now an expiry redirects again instead of reporting a loop.
    msal.acquireTokenSilent.mockRejectedValueOnce(new InteractionRequiredAuthError('interaction_required'));
    void auth.acquireToken().catch(() => undefined);
    await new Promise((r) => setTimeout(r, 0));
    expect(msal.acquireTokenRedirect).toHaveBeenCalledTimes(1);
  });

  it('a token call waits on a 401 sign-in that is already running instead of starting a redirect', async () => {
    const msal = fakeMsal();
    msal.acquireTokenSilent.mockRejectedValue(new InteractionRequiredAuthError('interaction_required'));
    const { auth } = make(msal);
    await auth.boot();
    void auth.loginOn401().catch(() => undefined);
    let settled = false;
    void auth.acquireToken().then(() => (settled = true), () => (settled = true));
    await new Promise((r) => setTimeout(r, 0));
    expect(msal.loginRedirect).toHaveBeenCalledTimes(1);
    expect(msal.acquireTokenRedirect).not.toHaveBeenCalled();
    expect(settled).toBe(false);
    // The scope that joined the sign-in is recorded in its loop guard.
    expect(window.sessionStorage.getItem('test:login-attempt-at:token:api://x/access_as_user')).toMatch(/^j:\d+$/);
  });

  it('an iframe renewal timeout redirects instead of surfacing as an API timeout', async () => {
    for (const code of ['monitor_window_timeout', 'empty_window_error', 'hash_empty_error', 'hash_does_not_contain_known_properties', 'block_iframe_reload']) {
      await expectRedirect(new BrowserAuthError(code));
    }
  });

  it('other server errors are rethrown without a redirect', async () => {
    const msal = fakeMsal();
    msal.acquireTokenSilent.mockRejectedValueOnce(new ServerError('temporarily_unavailable'));
    const { auth } = make(msal);
    await auth.boot();
    await expect(auth.acquireToken()).rejects.toMatchObject({ errorCode: 'temporarily_unavailable' });
    expect(msal.acquireTokenRedirect).not.toHaveBeenCalled();
  });

  it('a silent-only probe flags an iframe renewal timeout as interaction required', async () => {
    const msal = fakeMsal();
    msal.acquireTokenSilent.mockRejectedValueOnce(new BrowserAuthError('monitor_window_timeout'));
    const { auth } = make(msal);
    await auth.boot();
    await expect(auth.acquireToken('api://other/x', { interactive: false })).rejects.toMatchObject({ interactionRequired: true });
    expect(msal.acquireTokenRedirect).not.toHaveBeenCalled();
  });

  it('a network failure is not a sign-in problem and is rethrown without a redirect', async () => {
    const msal = fakeMsal();
    msal.acquireTokenSilent.mockRejectedValueOnce(new BrowserAuthError('no_network_connectivity'));
    const { auth } = make(msal);
    await auth.boot();
    await expect(auth.acquireToken()).rejects.toMatchObject({ errorCode: 'no_network_connectivity' });
    expect(msal.acquireTokenRedirect).not.toHaveBeenCalled();
  });

  it('redirects only on interaction required, carrying the page as state', async () => {
    const msal = fakeMsal();
    msal.acquireTokenSilent.mockRejectedValueOnce(new InteractionRequiredAuthError('interaction_required'));
    const { auth } = make(msal);
    await auth.boot();
    let settled = false;
    void auth.acquireToken().then(() => (settled = true), () => (settled = true));
    await new Promise((r) => setTimeout(r, 0));
    expect(msal.acquireTokenRedirect).toHaveBeenCalledWith(expect.objectContaining({ state: '/' }));
    // The page is navigating away: the call waits, so no request goes out without a token.
    expect(settled).toBe(false);
  });

  it('rejects a token redirect that never navigates away after the sign-in wait', async () => {
    vi.useFakeTimers();
    try {
      const msal = fakeMsal();
      msal.acquireTokenSilent.mockRejectedValueOnce(new InteractionRequiredAuthError('interaction_required'));
      const { auth } = make(msal);
      await auth.boot();
      const p = auth.acquireToken();
      const seen = p.catch((e: unknown) => e);
      await vi.advanceTimersByTimeAsync(19_000);
      expect(msal.acquireTokenRedirect).toHaveBeenCalled();
      await vi.advanceTimersByTimeAsync(2_000);
      expect(await seen).toMatchObject({ status: 401, interactionRequired: true });
    } finally {
      vi.useRealTimers();
    }
  });

  it('concurrent calls that need interaction share one redirect instead of failing', async () => {
    const msal = fakeMsal();
    msal.acquireTokenSilent.mockRejectedValue(new InteractionRequiredAuthError('interaction_required'));
    // MSAL rejects every redirect after the first.
    msal.acquireTokenRedirect.mockImplementation(async () => {
      if (msal.acquireTokenRedirect.mock.calls.length > 1) throw Object.assign(new Error('busy'), { errorCode: 'interaction_in_progress' });
    });
    const { auth } = make(msal);
    await auth.boot();
    const settled: string[] = [];
    for (let i = 0; i < 3; i += 1) void auth.acquireToken().then(() => settled.push('ok'), (e: Error) => settled.push(e.message));
    await new Promise((r) => setTimeout(r, 0));
    expect(msal.acquireTokenRedirect).toHaveBeenCalledTimes(1);
    // Every caller waits on the one navigation: nothing rejects with interaction_in_progress.
    expect(settled).toEqual([]);
    // A later caller, for another scope too, joins the same redirect.
    void auth.acquireToken('api://other/x').then(() => settled.push('ok'), (e: Error) => settled.push(e.message));
    await new Promise((r) => setTimeout(r, 0));
    expect(msal.acquireTokenRedirect).toHaveBeenCalledTimes(1);
    expect(settled).toEqual([]);
    // The joined scope is recorded in its loop guard as joined, not as its own redirect.
    expect(window.sessionStorage.getItem('test:login-attempt-at:token:api://other/x')).toMatch(/^j:\d+$/);
  });

  it('a scope that joined another scope redirect gets exactly one redirect of its own before the guard reports it', async () => {
    vi.useFakeTimers();
    const errors = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const A = 'api://x/access_as_user';
    const B = 'api://other/x';
    const needsB = (req: { scopes: string[] }) => {
      if (req.scopes[0] === B) throw new InteractionRequiredAuthError('consent_required', 'AADSTS65001: consent');
      return { accessToken: 'tok-a' };
    };
    try {
      // Page 1: scope A starts a redirect, scope B joins it.
      const page1 = fakeMsal();
      page1.acquireTokenSilent.mockRejectedValue(new InteractionRequiredAuthError('interaction_required'));
      const one = make(page1);
      await one.auth.boot();
      void one.auth.acquireToken(A).catch(() => undefined);
      void one.auth.acquireToken(B).catch(() => undefined);
      await vi.advanceTimersByTimeAsync(0);
      expect(page1.acquireTokenRedirect).toHaveBeenCalledTimes(1);
      expect(page1.acquireTokenRedirect).toHaveBeenCalledWith(expect.objectContaining({ scopes: [A] }));
      expect(window.sessionStorage.getItem(`test:login-attempt-at:token:${B}`)).toMatch(/^j:/);

      // Page 2 (the redirect returned): A has its token, B still needs interaction and gets one
      // redirect of its own, for its own scope.
      const page2 = fakeMsal();
      page2.acquireTokenSilent.mockImplementation(async (req: { scopes: string[] }) => needsB(req));
      const two = make(page2);
      await two.auth.boot();
      expect(await two.auth.acquireToken(A)).toBe('tok-a');
      void two.auth.acquireToken(B).catch(() => undefined);
      await vi.advanceTimersByTimeAsync(0);
      expect(page2.acquireTokenRedirect).toHaveBeenCalledTimes(1);
      expect(page2.acquireTokenRedirect).toHaveBeenCalledWith(expect.objectContaining({ scopes: [B] }));

      // Page 3 (B's own redirect returned): B still needs interaction, so the guard reports it.
      const page3 = fakeMsal();
      page3.acquireTokenSilent.mockImplementation(async (req: { scopes: string[] }) => needsB(req));
      const three = make(page3);
      await three.auth.boot();
      const err = await three.auth.acquireToken(B).catch((e: unknown) => e);
      expect(err).toMatchObject({ code: 'sign_in_loop', interactionRequired: true });
      expect(page3.acquireTokenRedirect).not.toHaveBeenCalled();
      expect(errors).toHaveBeenCalledTimes(1);
      await vi.runAllTimersAsync();
    } finally {
      errors.mockRestore();
      vi.useRealTimers();
    }
  });

  it('a scope that already had its own redirect is reported instead of joining another one', async () => {
    const errors = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    try {
      window.sessionStorage.setItem('test:login-attempt-at:token:api://other/x', String(Date.now()));
      const msal = fakeMsal();
      msal.acquireTokenSilent.mockRejectedValue(new InteractionRequiredAuthError('interaction_required'));
      const { auth } = make(msal);
      await auth.boot();
      void auth.acquireToken().catch(() => undefined);
      const err = await auth.acquireToken('api://other/x').catch((e: unknown) => e);
      expect(err).toMatchObject({ code: 'sign_in_loop' });
      expect(msal.acquireTokenRedirect).toHaveBeenCalledTimes(1);
    } finally {
      errors.mockRestore();
    }
  });

  it('a joined scope is cleared from the loop guard when the shared navigation never leaves the page', async () => {
    vi.useFakeTimers();
    try {
      const msal = fakeMsal();
      msal.acquireTokenSilent.mockRejectedValue(new InteractionRequiredAuthError('interaction_required'));
      const { auth } = make(msal);
      await auth.boot();
      const a = auth.acquireToken().catch((e: unknown) => e);
      const b = auth.acquireToken('api://other/x').catch((e: unknown) => e);
      await vi.advanceTimersByTimeAsync(0);
      expect(window.sessionStorage.getItem('test:login-attempt-at:token:api://other/x')).toMatch(/^j:/);
      await vi.advanceTimersByTimeAsync(21_000);
      expect(await a).toMatchObject({ status: 401 });
      expect(await b).toMatchObject({ status: 401 });
      expect(window.sessionStorage.getItem('test:login-attempt-at:token:api://other/x')).toBeNull();
      expect(window.sessionStorage.getItem('test:login-attempt-at:token:api://x/access_as_user')).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('an interaction_in_progress from a second MSAL copy (matched by code) also waits', async () => {
    const msal = fakeMsal();
    msal.acquireTokenSilent.mockRejectedValueOnce(new InteractionRequiredAuthError('interaction_required'));
    msal.acquireTokenRedirect.mockRejectedValueOnce(Object.assign(new Error('busy'), { name: 'BrowserAuthError', errorCode: 'interaction_in_progress' }));
    const { auth } = make(msal);
    await auth.boot();
    let settled = false;
    void auth.acquireToken().then(() => (settled = true), () => (settled = true));
    await new Promise((r) => setTimeout(r, 0));
    expect(settled).toBe(false);
  });

  it('waits on a sign-in that is already running instead of rejecting', async () => {
    const msal = fakeMsal();
    msal.acquireTokenSilent.mockRejectedValueOnce(new InteractionRequiredAuthError('interaction_required'));
    msal.acquireTokenRedirect.mockRejectedValueOnce(Object.assign(new Error('busy'), { errorCode: 'interaction_in_progress' }));
    const { auth } = make(msal);
    await auth.boot();
    let settled = false;
    void auth.acquireToken().then(() => (settled = true), () => (settled = true));
    await new Promise((r) => setTimeout(r, 0));
    expect(settled).toBe(false);
  });

  it('a silent-only probe throws interactionRequired instead of redirecting', async () => {
    const msal = fakeMsal();
    msal.acquireTokenSilent.mockRejectedValueOnce(new InteractionRequiredAuthError('interaction_required'));
    const { auth } = make(msal);
    await auth.boot();
    await expect(auth.acquireToken('api://other/x', { interactive: false })).rejects.toMatchObject({ interactionRequired: true });
    expect(msal.acquireTokenRedirect).not.toHaveBeenCalled();
  });

  it('rethrows any other token error', async () => {
    const msal = fakeMsal();
    msal.acquireTokenSilent.mockRejectedValueOnce(new Error('network'));
    const { auth } = make(msal);
    await auth.boot();
    await expect(auth.acquireToken()).rejects.toThrow('network');
  });

  it('returns null with no account, no scope or the dev bypass', async () => {
    expect(await make(fakeMsal([])).auth.acquireToken()).toBeNull();
    expect(await make(fakeMsal(), { apiScope: '' }).auth.acquireToken()).toBeNull();
    const dev = make(fakeMsal(), { devBypass: true, clientId: '' });
    expect(await dev.auth.acquireToken()).toBeNull();
    expect(dev.auth.accountId()).toBe('dev');
  });

  it('ignores the dev bypass on a real host or with a real client id', async () => {
    const prodWindow = {
      location: { origin: 'https://console.example.test', hostname: 'console.example.test', pathname: '/', search: '', hash: '' },
      sessionStorage: window.sessionStorage,
      history: window.history,
      setTimeout: window.setTimeout.bind(window),
    } as unknown as Window;
    const prod = make(fakeMsal(), { devBypass: true, clientId: '', window: prodWindow });
    expect(prod.auth.devBypass).toBe(false);
    expect(prod.auth.accountId()).toBe('acct-1');
    expect(await prod.auth.acquireToken()).toBe('tok');
    const real = make(fakeMsal(), { devBypass: true, clientId: 'real-client' });
    expect(real.auth.devBypass).toBe(false);
  });
});

describe('createAuth sign-in and 401', () => {
  it('shell login carries the stored module target as state', async () => {
    window.sessionStorage.setItem(RETURN_TO_KEY, '/example/users');
    const msal = fakeMsal([]);
    const { auth } = make(msal);
    await auth.login();
    expect(msal.loginRedirect).toHaveBeenCalledWith(expect.objectContaining({ state: '/example/users' }));
  });

  it('loginOn401 signs in once for concurrent 401s, then throws inside the loop window', async () => {
    vi.useFakeTimers();
    try {
      const msal = fakeMsal();
      const { auth } = make(msal);
      await auth.boot();
      const first = auth.loginOn401();
      const firstSeen = first.catch((e: unknown) => e);
      // A second 401 while the first sign-in navigates shares it instead of tripping the guard.
      const second = auth.loginOn401();
      expect(second).toBe(first);
      await vi.advanceTimersByTimeAsync(0);
      expect(msal.loginRedirect).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(21_000);
      expect(await firstSeen).toMatchObject({ status: 401 });
      // The page never left and the API still says 401 inside the window: the loop guard throws.
      await expect(auth.loginOn401()).rejects.toThrow(/rejected the token/);
      expect(msal.loginRedirect).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('a module bounces a 401 to the shell sign-in with its returnTo, never its own login', async () => {
    const msal = fakeMsal();
    const { auth, navigate } = make(msal, { mode: 'module', basePath: '/example/' });
    await auth.boot();
    void auth.loginOn401();
    expect(navigate).toHaveBeenCalledWith(`${ORIGIN}/?returnTo=${encodeURIComponent('/')}`);
    expect(msal.loginRedirect).not.toHaveBeenCalled();
  });

  it('a module with no session bounces to the shell at once, without the blocked silent SSO iframe', async () => {
    const msal = fakeMsal([]);
    const { auth, navigate } = make(msal, { mode: 'module', basePath: '/example/' });
    expect(await auth.ensureSessionOrBounce()).toBe(false);
    expect(msal.ssoSilent).not.toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledTimes(1);
    expect(navigate.mock.calls[0]?.[0]).toMatch(/\/\?returnTo=/);
  });

  it('a module with a session renders without any sign-in call', async () => {
    const msal = fakeMsal();
    const { auth, navigate } = make(msal, { mode: 'module', basePath: '/example/' });
    await auth.boot();
    expect(await auth.ensureSessionOrBounce()).toBe(true);
    expect(msal.ssoSilent).not.toHaveBeenCalled();
    expect(navigate).not.toHaveBeenCalled();
  });

  it('logout runs the cache clear hooks and lands on the configured page', async () => {
    const msal = fakeMsal();
    const { auth } = make(msal);
    const hook = vi.fn();
    auth.onLogout(hook);
    await auth.logout();
    expect(hook).toHaveBeenCalledTimes(1);
    expect(msal.logoutRedirect).toHaveBeenCalledWith({ postLogoutRedirectUri: `${ORIGIN}/signed-out` });
  });

  it('notifies an account change', async () => {
    const msal = fakeMsal();
    const { auth } = make(msal);
    await auth.boot();
    const cb = vi.fn();
    auth.onAccountChange(cb);
    const other = { homeAccountId: 'acct-2' } as unknown as AccountInfo;
    msal.setActiveAccount(other);
    msal.emit('msal:activeAccountChanged');
    expect(cb).toHaveBeenCalledWith('acct-2');
    msal.emit('msal:activeAccountChanged');
    expect(cb).toHaveBeenCalledTimes(1);
  });

  it('clears on a sign-out or account switch made in another tab', async () => {
    const msal = fakeMsal();
    const { auth } = make(msal);
    await auth.boot();
    const cb = vi.fn();
    auth.onAccountChange(cb);
    // The other tab removed the account from the shared cache. No MSAL event reaches this tab.
    msal.accounts = [];
    msal.setActiveAccount(null);
    window.dispatchEvent(new StorageEvent('storage', { key: 'msal.account.keys', storageArea: window.localStorage }));
    expect(cb).toHaveBeenCalledWith('');
    // The focus fallback catches a switch too.
    msal.accounts = [{ homeAccountId: 'acct-3' } as unknown as AccountInfo];
    window.dispatchEvent(new Event('focus'));
    expect(cb).toHaveBeenLastCalledWith('acct-3');
  });

  it('turns on MSAL account storage events when available', async () => {
    const msal = Object.assign(fakeMsal(), { enableAccountStorageEvents: vi.fn() });
    const { auth } = make(msal);
    await auth.boot();
    expect(msal.enableAccountStorageEvents).toHaveBeenCalledTimes(1);
  });

  it('a module login bounces to the shell instead of starting its own sign-in', async () => {
    const msal = fakeMsal();
    const { auth, navigate } = make(msal, { mode: 'module', basePath: '/example/' });
    await auth.boot();
    await auth.login('/example/users');
    expect(msal.loginRedirect).not.toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledWith(`${ORIGIN}/?returnTo=${encodeURIComponent('/example/users')}`);
    await auth.login('https://evil.example/x');
    expect(navigate).toHaveBeenLastCalledWith(`${ORIGIN}/?returnTo=${encodeURIComponent(window.location.pathname + window.location.search)}`);
  });

  it('a module owns only its base path on a segment boundary, and nothing without one', async () => {
    const back = { account: ACCOUNT, state: '/example-admin/x' };
    const one = make(fakeMsal([ACCOUNT], back), { mode: 'module', basePath: '/example', ownsPath: undefined });
    expect((await one.auth.boot()).forwarded).toBe(true);
    expect(one.navigate).toHaveBeenCalledWith('/example-admin/x');
    const none = make(fakeMsal([ACCOUNT], { account: ACCOUNT, state: '/xerox/devices' }), { mode: 'module', ownsPath: undefined });
    expect((await none.auth.boot()).forwarded).toBe(true);
    expect(none.navigate).toHaveBeenCalledWith('/xerox/devices');
  });

  it('reports a failed returning sign-in without breaking boot', async () => {
    const msal = fakeMsal();
    msal.handleRedirectPromise.mockRejectedValueOnce(new Error('AADSTS65004: consent declined'));
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const { auth } = make(msal);
    const result = await auth.boot();
    expect(result.account).toEqual(ACCOUNT);
    expect((result.error as Error).message).toMatch(/AADSTS65004/);
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});
