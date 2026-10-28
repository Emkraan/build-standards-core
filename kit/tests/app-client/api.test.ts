import { describe, expect, it, vi } from 'vitest';
import { createApi, qs } from '../../../shell-packages/app-client/src';
import type { CreateApiOptions } from '../../../shell-packages/app-client/src';

function fakeAuth(id = 'acct-1') {
  let current = id;
  const accountCbs: Array<(id: string) => void> = [];
  const logoutCbs: Array<() => void> = [];
  return {
    apiScope: 'api://test/access_as_user',
    acquireToken: vi.fn(async (): Promise<string | null> => 'tok'),
    loginOn401: vi.fn(() => new Promise<never>(() => undefined)),
    accountId: () => current,
    onAccountChange: (cb: (id: string) => void) => {
      accountCbs.push(cb);
      return () => undefined;
    },
    onLogout: (cb: () => void) => {
      logoutCbs.push(cb);
      return () => undefined;
    },
    switchTo(next: string) {
      current = next;
      accountCbs.forEach((cb) => cb(next));
    },
    logout() {
      logoutCbs.forEach((cb) => cb());
    },
  };
}

function res(status: number, body: unknown): Response {
  return new Response(typeof body === 'string' ? body : JSON.stringify(body), { status });
}

function make(fetchImpl: (url: string, init?: RequestInit) => Promise<Response>, over: Partial<CreateApiOptions> = {}) {
  const auth = fakeAuth();
  const fetchMock = vi.fn(fetchImpl);
  const api = createApi({
    baseUrl: 'https://gw/console/api',
    auth,
    namespace: 'test',
    fetch: fetchMock as unknown as typeof fetch,
    ...over,
  });
  return { api, auth, fetchMock };
}

describe('createApi error contract', () => {
  it('sends the bearer token and the CSRF header, and a caller header never drops them', async () => {
    const { api, fetchMock } = make(async () => res(200, { ok: true }));
    await api.request('/relay', { method: 'POST', headers: { 'X-Access-Token': 'up' }, body: { a: 1 } });
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(fetchMock.mock.calls[0]?.[0]).toBe('https://gw/console/api/relay');
    expect(init.headers).toMatchObject({ Authorization: 'Bearer tok', 'X-Requested-With': 'XMLHttpRequest', 'X-Access-Token': 'up' });
    expect(init.body).toBe('{"a":1}');
  });

  it('joins the upstream detail into the message and keeps status, details and payload', async () => {
    const { api } = make(async () => res(409, { error: 'Conflict', details: { error_message: 'Ring exists' }, ring: 'r1' }));
    await expect(api.request('/x')).rejects.toMatchObject({
      message: 'Conflict: Ring exists',
      status: 409,
      details: { error_message: 'Ring exists' },
      payload: { error: 'Conflict', ring: 'r1' },
    });
  });

  it('can join the detail in parentheses (the Example style)', async () => {
    const { api } = make(async () => res(502, { error: 'Example error', details: { error: { message: 'rate limited' } } }), {
      joinDetail: (m, d) => `${m} (${d})`,
    });
    await expect(api.request('/x')).rejects.toThrow('Example error (rate limited)');
  });

  it('reads error_description, string details and errors[0]', async () => {
    const one = make(async () => res(400, { error: 'Bad', details: { error_description: 'desc' } }));
    await expect(one.api.request('/x')).rejects.toThrow('Bad: desc');
    const two = make(async () => res(400, { error: 'Bad', details: 'plain' }));
    await expect(two.api.request('/x')).rejects.toThrow('Bad: plain');
    const three = make(async () => res(400, { details: { errors: [{ message: 'first' }] } }));
    await expect(three.api.request('/x')).rejects.toThrow('Request failed: 400: first');
  });

  it('treats a 403 with no JSON error as a platform or CORS block', async () => {
    const { api } = make(async () => res(403, ''));
    await expect(api.request('/x')).rejects.toThrow(/Forbidden: check API CORS/);
    const rbac = make(async () => res(403, { error: 'Missing permission action:x:y' }));
    await expect(rbac.api.request('/x')).rejects.toMatchObject({ message: 'Missing permission action:x:y', status: 403 });
  });

  it('never sends a scoped call while signed out, it takes the 401 path', async () => {
    const { api, auth, fetchMock } = make(async () => res(200, {}));
    auth.switchTo('');
    auth.acquireToken.mockResolvedValue(null);
    void api.request('/me');
    await new Promise((r) => setTimeout(r, 0));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(auth.loginOn401).toHaveBeenCalledTimes(1);

    const side = make(async () => res(200, {}), { on401: 'throw' });
    side.auth.switchTo('');
    side.auth.acquireToken.mockResolvedValue(null);
    await expect(side.api.request('/feed')).rejects.toMatchObject({ status: 401 });
    expect(side.fetchMock).not.toHaveBeenCalled();

    // The dev bypass reports "dev" and has no token: that call still goes out.
    const dev = make(async () => res(200, { ok: true }));
    dev.auth.switchTo('dev');
    dev.auth.acquireToken.mockResolvedValue(null);
    await expect(dev.api.request('/me')).resolves.toMatchObject({ ok: true });
  });

  it('a side read asks for its token silently and reads interaction required as a 401', async () => {
    const side = make(async () => res(200, { ok: true }), { on401: 'throw' });
    side.auth.acquireToken.mockRejectedValueOnce(Object.assign(new Error('interaction_required'), { interactionRequired: true }));
    await expect(side.api.request('/feed')).rejects.toMatchObject({ status: 401 });
    expect(side.auth.acquireToken).toHaveBeenCalledWith(undefined, { interactive: false });
    expect(side.fetchMock).not.toHaveBeenCalled();
    expect(side.auth.loginOn401).not.toHaveBeenCalled();
  });

  it('a direct request that lands after an account change rejects as stale', async () => {
    let resolve: (r: Response) => void = () => undefined;
    const { api, auth } = make(() => new Promise<Response>((r) => (resolve = r)));
    const p = api.request('/me');
    await new Promise((r) => setTimeout(r, 0));
    auth.switchTo('acct-2');
    resolve(res(200, { user: 'old' }));
    await expect(p).rejects.toMatchObject({ stale: true });
  });

  it('hands a 401 to the auth sign-in path, or throws it for side reads', async () => {
    const { api, auth } = make(async () => res(401, {}));
    const p = api.request('/me');
    await new Promise((r) => setTimeout(r, 0));
    expect(auth.loginOn401).toHaveBeenCalledTimes(1);
    void p;
    const side = make(async () => res(401, {}), { on401: 'throw' });
    await expect(side.api.request('/feed')).rejects.toMatchObject({ status: 401 });
    expect(side.auth.loginOn401).not.toHaveBeenCalled();
  });

  it('a per-call on401 "throw" makes one call a side read on an interactive client', async () => {
    const { api, auth, fetchMock } = make(async () => res(401, {}));
    await expect(api.request('/feed', { on401: 'throw' })).rejects.toMatchObject({ status: 401 });
    expect(auth.loginOn401).not.toHaveBeenCalled();
    expect(auth.acquireToken).toHaveBeenCalledWith(undefined, { interactive: false });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    // Interaction required on the token reads as a 401 too, without a fetch or a sign-in.
    auth.acquireToken.mockRejectedValueOnce(Object.assign(new Error('interaction_required'), { interactionRequired: true }));
    await expect(api.request('/feed', { on401: 'throw' })).rejects.toMatchObject({ status: 401 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(auth.loginOn401).not.toHaveBeenCalled();
  });

  it('a per-call "login" never turns a side-read client interactive', async () => {
    const side = make(async () => res(401, {}), { on401: 'throw' });
    await expect(side.api.request('/feed', { on401: 'login' })).rejects.toMatchObject({ status: 401 });
    expect(side.auth.loginOn401).not.toHaveBeenCalled();
    expect(side.auth.acquireToken).toHaveBeenCalledWith(undefined, { interactive: false });
  });

  it('a per-call side read never shares an in-flight interactive GET, in either direction', async () => {
    const releases: Array<(r: Response) => void> = [];
    const { api, auth, fetchMock } = make(() => new Promise<Response>((r) => releases.push(r)));
    const interactive = api.request('/slow');
    const side = api.request('/slow', { on401: 'throw' });
    const interactive2 = api.request('/slow');
    await new Promise((r) => setTimeout(r, 0));
    // The two interactive GETs share one request, the side read has its own.
    expect(fetchMock).toHaveBeenCalledTimes(2);
    releases[0]?.(res(200, { ok: 1 }));
    releases[1]?.(res(401, {}));
    await expect(interactive).resolves.toEqual({ ok: 1 });
    await expect(interactive2).resolves.toEqual({ ok: 1 });
    await expect(side).rejects.toMatchObject({ status: 401 });
    expect(auth.loginOn401).not.toHaveBeenCalled();
  });

  it('wraps a non-JSON body as the error text', async () => {
    const { api } = make(async () => res(500, 'Bad gateway'));
    await expect(api.request('/x')).rejects.toThrow('Bad gateway');
  });

  it('builds query strings without empty values', () => {
    expect(qs({ a: 1, b: null, c: undefined, d: 'x y' })).toBe('?a=1&d=x+y');
    expect(qs({})).toBe('');
  });
});

describe('createApi tokens and headers', () => {
  it('rejects instead of sending a request without a token when token acquisition fails', async () => {
    const { api, auth, fetchMock } = make(async () => res(200, {}));
    auth.acquireToken.mockRejectedValueOnce(new Error('network down'));
    await expect(api.request('/me')).rejects.toThrow('network down');
    expect(fetchMock).not.toHaveBeenCalled();
    expect(auth.loginOn401).not.toHaveBeenCalled();
  });

  it('waits instead of fetching while an interactive redirect runs', async () => {
    const { api, auth, fetchMock } = make(async () => res(200, {}));
    auth.acquireToken.mockReturnValueOnce(new Promise<never>(() => undefined) as unknown as Promise<string>);
    void api.request('/me');
    await new Promise((r) => setTimeout(r, 0));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('never lets a caller header replace the bearer token', async () => {
    const { api, fetchMock } = make(async () => res(200, {}));
    await api.request('/x', { headers: { authorization: 'Bearer forged', 'X-Access-Token': 'up' } });
    const headers = (fetchMock.mock.calls[0]?.[1] as RequestInit).headers as Record<string, string>;
    expect(headers['Authorization']).toBe('Bearer tok');
    expect(headers['authorization']).toBeUndefined();
    expect(headers['X-Access-Token']).toBe('up');
  });

  it('keeps a JSON 403 reason even without an error field', async () => {
    const { api } = make(async () => res(403, { message: 'Missing permission: action:x:y' }));
    await expect(api.request('/x')).rejects.toMatchObject({ message: 'Missing permission: action:x:y', status: 403 });
  });
});

describe('createApi dedupe and cache', () => {
  it('shares one request between identical concurrent GETs', async () => {
    let resolve: (r: Response) => void = () => undefined;
    const { api, fetchMock } = make(() => new Promise<Response>((r) => (resolve = r)));
    const a = api.request('/connector/me');
    const b = api.request('/connector/me');
    await new Promise((r) => setTimeout(r, 0));
    resolve(res(200, { connected: true }));
    expect(await a).toEqual({ connected: true });
    expect(await b).toEqual({ connected: true });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('never shares writes or GETs with any other option', async () => {
    const { api, fetchMock, auth } = make(async () => res(200, {}));
    await Promise.all([api.request('/x', { method: 'POST' }), api.request('/x', { method: 'POST' })]);
    await Promise.all([api.request('/y', { headers: { A: '1' } }), api.request('/y', { headers: { A: '2' } })]);
    await Promise.all([api.request('/z', { scope: 'api://a/x' }), api.request('/z', { scope: 'api://b/x' })]);
    await Promise.all([api.request('/w', { cache: 'no-store' }), api.request('/w')]);
    expect(fetchMock).toHaveBeenCalledTimes(8);
    expect(auth.acquireToken).toHaveBeenCalledWith('api://b/x');
  });

  it('serves a cached GET inside its ttl and refetches after', async () => {
    vi.useFakeTimers();
    try {
      let n = 0;
      const { api, fetchMock } = make(async () => res(200, { n: ++n }), { ttl: { '/connector/me': 30_000 } });
      expect(await api.get('/connector/me')).toEqual({ n: 1 });
      expect(await api.get('/connector/me')).toEqual({ n: 1 });
      expect(fetchMock).toHaveBeenCalledTimes(1);
      vi.advanceTimersByTime(30_001);
      expect(await api.get('/connector/me')).toEqual({ n: 2 });
      expect(await api.get('/connector/me', { force: true })).toEqual({ n: 3 });
    } finally {
      vi.useRealTimers();
    }
  });

  it('matches prefix ttls and falls back to the default', () => {
    const { api } = make(async () => res(200, {}), { ttl: { '/reports/*': 10, '/reports/blocked*': 20 }, defaultTtl: 5 });
    expect(api.ttlFor('/reports/status')).toBe(10);
    expect(api.ttlFor('/reports/blocked-numbers')).toBe(20);
    expect(api.ttlFor('/users')).toBe(5);
  });

  it('keeps the last good data when a revalidation fails', async () => {
    let fail = false;
    const { api } = make(async () => (fail ? res(500, { error: 'down' }) : res(200, { v: 1 })));
    await api.get('/x');
    fail = true;
    await expect(api.get('/x', { force: true })).rejects.toThrow('down');
    expect(api.peek('/x').data).toEqual({ v: 1 });
  });
});

describe('createApi persistence', () => {
  it('persists only the allowlisted identity reads, per account', async () => {
    const { api } = make(async (url) => res(200, { url }), { persist: ['/me'] });
    await api.get('/me');
    await api.get('/modules');
    const keys = Object.keys(window.sessionStorage);
    expect(keys).toContain('test.api.v1:/me');
    expect(keys).not.toContain('test.api.v1:/modules');
    expect(window.sessionStorage.getItem('test.api.v1.account')).toBe('acct-1');
  });

  it('hydrates a persisted identity read so the shell paints before the request', async () => {
    window.sessionStorage.setItem('test.api.v1.account', 'acct-1');
    window.sessionStorage.setItem('test.api.v1:/modules', JSON.stringify({ at: 1, data: { leaked: true } }));
    window.sessionStorage.setItem('test.api.v1:/me', JSON.stringify({ at: Date.now(), data: { user: 'a' } }));
    const { api, fetchMock } = make(async () => res(200, { user: 'fresh' }), { persist: ['/me'] });
    expect(api.peek('/me').data).toEqual({ user: 'a' });
    expect(api.peek('/modules').data).toBeUndefined();
    expect(fetchMock).not.toHaveBeenCalled();
    // Hydrated data counts as stale even when it was written a moment ago: a get revalidates.
    expect(await api.get('/me', { ttl: 60_000 })).toEqual({ user: 'fresh' });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('hydrates lazily, once the account is known (the client is built before boot)', () => {
    window.sessionStorage.setItem('test.api.v1.account', 'acct-1');
    window.sessionStorage.setItem('test.api.v1:/me', JSON.stringify({ at: 1, data: { user: 'a' } }));
    let owner = '';
    const auth = { ...fakeAuth(''), accountId: () => owner };
    const api = createApi({ baseUrl: 'https://gw/api', auth, namespace: 'test', persist: ['/me'], fetch: vi.fn() as unknown as typeof fetch });
    expect(api.peek('/me').data).toBeUndefined();
    expect(window.sessionStorage.getItem('test.api.v1:/me')).not.toBeNull();
    // boot() adopts the account without an account-change event.
    owner = 'acct-1';
    expect(api.peek('/me').data).toEqual({ user: 'a' });
  });

  it('drops persisted data with no owner key', () => {
    window.sessionStorage.setItem('test.api.v1:/me', JSON.stringify({ at: 1, data: { user: 'b' } }));
    const { api } = make(async () => res(200, {}), { persist: ['/me'] });
    expect(api.peek('/me').data).toBeUndefined();
    expect(window.sessionStorage.getItem('test.api.v1:/me')).toBeNull();
  });

  it('drops persisted data written by another account', () => {
    window.sessionStorage.setItem('test.api.v1.account', 'someone-else');
    window.sessionStorage.setItem('test.api.v1:/me', JSON.stringify({ at: 1, data: { user: 'b' } }));
    const { api } = make(async () => res(200, {}), { persist: ['/me'] });
    expect(api.peek('/me').data).toBeUndefined();
    expect(window.sessionStorage.getItem('test.api.v1:/me')).toBeNull();
  });

  it('clears memory and storage on logout and on account change', async () => {
    const { api, auth } = make(async () => res(200, { user: 'a' }), { persist: ['/me'] });
    await api.get('/me');
    auth.logout();
    expect(api.peek('/me').data).toBeUndefined();
    expect(window.sessionStorage.getItem('test.api.v1:/me')).toBeNull();
    await api.get('/me');
    auth.switchTo('acct-2');
    expect(api.peek('/me').data).toBeUndefined();
    expect(window.sessionStorage.getItem('test.api.v1:/me')).toBeNull();
  });

  it('drops a response that lands after a clear', async () => {
    let resolve: (r: Response) => void = () => undefined;
    const { api, auth } = make(() => new Promise<Response>((r) => (resolve = r)), { persist: ['/me'] });
    const p = api.get('/me');
    await new Promise((r) => setTimeout(r, 0));
    auth.logout();
    resolve(res(200, { user: 'old' }));
    // The waiting caller does not get the old session's answer either.
    await expect(p).rejects.toMatchObject({ stale: true });
    expect(api.peek('/me').data).toBeUndefined();
    expect(window.sessionStorage.getItem('test.api.v1:/me')).toBeNull();
  });
});

function deferred() {
  let resolve: (r: Response) => void = () => undefined;
  const promise = new Promise<Response>((r) => (resolve = r));
  return { promise, resolve };
}

const tick = () => new Promise((r) => setTimeout(r, 0));

describe('createApi only sends the token to its own base', () => {
  const bad = [
    'https://attacker.example/collect',
    'HTTPS://attacker.example/collect',
    '//attacker.example/collect',
    '/\\attacker.example/collect',
    '\\\\attacker.example',
    'javascript:alert(1)',
    'relative/path',
    '',
    '/../admin',
    '/a/../../admin',
    '/%2e%2e/admin',
    '/%2E%2e%2Fadmin',
    '/..%5cadmin',
    '/./x',
    '/x\tq',
    '/%zz',
    '/%252e%252e/admin',
    '/%25252e%25252e/admin',
    '/x/%252F..%252Fadmin',
    // Encoded separators inside a segment.
    '/users/a%2Fb/numbers',
    '/users/a%2fb',
    '/users/a%5Cb',
    '/users/a%255Cb',
    '/x/%00/y',
    // Path parameters after a dot segment (servers that drop ";..." then see "..").
    '/..;/admin',
    '/x/..;jsessionid=1/admin',
    '/.;/admin',
    '/.../admin',
    '/..%20/admin',
    '/%2e%2e%3b/admin',
    // Unicode dot and separator lookalikes that NFKC folds.
    '/\uff0e\uff0e/admin',
    '/%EF%BC%8E%EF%BC%8E/admin',
    '/\u2025/admin',
    '/\u2024/admin',
    '/a\uff0fb',
    '/a%EF%BC%8Fb',
  ];

  it.each(bad)('refuses %j before asking for a token', async (path) => {
    const { api, auth, fetchMock } = make(async () => res(200, {}));
    await expect(api.request(path, { method: 'POST' })).rejects.toMatchObject({ code: 'invalid_path' });
    await expect(api.request(path)).rejects.toMatchObject({ code: 'invalid_path' });
    await expect(api.get(path)).rejects.toMatchObject({ code: 'invalid_path' });
    expect(auth.acquireToken).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refuses the same paths with an empty base (dev proxy) and a path-only base', async () => {
    for (const baseUrl of ['', '/console/api']) {
      const { api, fetchMock } = make(async () => res(200, {}), { baseUrl });
      for (const path of ['//attacker.example/x', 'https://attacker.example/x', '/\\attacker.example/x', '/../x']) {
        await expect(api.request(path)).rejects.toMatchObject({ code: 'invalid_path' });
      }
      expect(fetchMock).not.toHaveBeenCalled();
    }
  });

  it('still sends ordinary paths, query strings and encoded ids', async () => {
    const { api, fetchMock } = make(async () => res(200, {}));
    await api.request('/users/a%40b/numbers?q=../x&next=//y&p=a%2Fb#frag');
    await api.request('/reports/v1.2..final');
    await api.request('/files/50%25');
    await api.request('/notes/caf%C3%A9;v=2');
    expect(fetchMock.mock.calls.map((c) => c[0])).toEqual([
      'https://gw/console/api/users/a%40b/numbers?q=../x&next=//y&p=a%2Fb#frag',
      'https://gw/console/api/reports/v1.2..final',
      'https://gw/console/api/files/50%25',
      'https://gw/console/api/notes/caf%C3%A9;v=2',
    ]);
    const dev = make(async () => res(200, {}), { baseUrl: '' });
    await dev.api.request('/api/me');
    expect(dev.fetchMock.mock.calls[0]?.[0]).toBe('/api/me');
  });
});

describe('createApi session guard', () => {
  it('never sends a write when the session changes while the token is acquired', async () => {
    const { api, auth, fetchMock } = make(async () => res(200, {}));
    let release: (t: string) => void = () => undefined;
    auth.acquireToken.mockReturnValueOnce(new Promise<string>((r) => (release = r)));
    const p = api.request('/users', { method: 'POST', body: { a: 1 } });
    await tick();
    auth.switchTo('acct-2');
    release('old-token');
    await expect(p).rejects.toMatchObject({ stale: true });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('an old 401 never starts a sign-in for the new session', async () => {
    const d = deferred();
    const { api, auth } = make(() => d.promise);
    const p = api.request('/me');
    await tick();
    auth.logout();
    d.resolve(res(401, {}));
    await expect(p).rejects.toMatchObject({ stale: true });
    expect(auth.loginOn401).not.toHaveBeenCalled();
  });

  it.each([403, 409, 500])('an old %i never reaches the caller', async (status) => {
    const d = deferred();
    const { api, auth } = make(() => d.promise);
    const p = api.request('/x', { method: 'POST' });
    await tick();
    auth.switchTo('acct-2');
    d.resolve(res(status, { error: 'old session error' }));
    await expect(p).rejects.toMatchObject({ stale: true });
  });

  it('aborts the fetches in flight on a session change, and a caller signal still aborts', async () => {
    const signals: AbortSignal[] = [];
    const { api, auth } = make((_url, init) => {
      signals.push(init?.signal as AbortSignal);
      return new Promise<Response>((_r, reject) => init?.signal?.addEventListener('abort', () => reject(new Error('aborted'))));
    });
    const p = api.request('/x', { method: 'POST' });
    await tick();
    auth.logout();
    await expect(p).rejects.toMatchObject({ stale: true });
    expect(signals[0]?.aborted).toBe(true);

    const mine = new AbortController();
    const q = api.request('/y', { signal: mine.signal });
    await tick();
    mine.abort();
    await expect(q).rejects.toThrow('aborted');
  });

  it('removes its listener from a long-lived caller signal once the request ends', async () => {
    const { api } = make(async () => res(200, {}));
    const page = new AbortController();
    const add = vi.spyOn(page.signal, 'addEventListener');
    const remove = vi.spyOn(page.signal, 'removeEventListener');
    await api.request('/x', { signal: page.signal });
    await api.request('/y', { signal: page.signal });
    expect(add).toHaveBeenCalledTimes(2);
    expect(remove).toHaveBeenCalledTimes(2);
    expect(remove.mock.calls[0]?.[1]).toBe(add.mock.calls[0]?.[1]);
  });

  it('an empty scope override falls back to the client scope instead of sending anonymously', async () => {
    const { api, auth, fetchMock } = make(async () => res(200, {}), { scope: 'api://own/x' });
    await api.request('/x', { scope: '' });
    expect(auth.acquireToken).toHaveBeenCalledWith('api://own/x');
    auth.switchTo('');
    auth.acquireToken.mockResolvedValue(null);
    fetchMock.mockClear();
    void api.request('/y', { scope: '' });
    await tick();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(auth.loginOn401).toHaveBeenCalledTimes(1);
  });

  it('reads an object-shaped error field as text', async () => {
    const one = make(async () => res(400, { error: { message: 'bad thing' } }));
    await expect(one.api.request('/x')).rejects.toMatchObject({ message: 'bad thing', status: 400 });
    const two = make(async () => res(403, { error: { message: 'Missing permission' } }));
    await expect(two.api.request('/x')).rejects.toMatchObject({ message: 'Missing permission', status: 403 });
  });
});

describe('createApi invalidate', () => {
  it('a GET after invalidate never shares the request from before it', async () => {
    const calls: Array<ReturnType<typeof deferred>> = [];
    const { api, fetchMock } = make((_url, init) => {
      if (init?.method === 'POST') return Promise.resolve(res(200, {}));
      const d = deferred();
      calls.push(d);
      return d.promise;
    });
    const before = api.request('/items');
    await tick();
    await api.request('/items', { method: 'POST', body: { name: 'new' } });
    api.invalidate('/items');
    const after = api.get('/items');
    await tick();
    expect(calls).toHaveLength(2);
    calls[0]?.resolve(res(200, { items: ['old'] }));
    calls[1]?.resolve(res(200, { items: ['old', 'new'] }));
    expect(await after).toEqual({ items: ['old', 'new'] });
    // The direct caller that was waiting is re-run against the post-invalidate request.
    expect(await before).toEqual({ items: ['old', 'new'] });
    expect(api.peek('/items').data).toEqual({ items: ['old', 'new'] });
    expect(fetchMock.mock.calls.filter((c) => (c[1] as RequestInit).method !== 'POST')).toHaveLength(2);
  });

  it('a cached reader waiting across an invalidate gets a request started after it, not a stale error', async () => {
    const calls: Array<ReturnType<typeof deferred>> = [];
    const { api } = make(() => {
      const d = deferred();
      calls.push(d);
      return d.promise;
    });
    const waiting = api.get('/items');
    await tick();
    api.invalidate('/items');
    calls[0]?.resolve(res(200, { v: 'before' }));
    await tick();
    expect(calls).toHaveLength(2);
    calls[1]?.resolve(res(200, { v: 'after' }));
    expect(await waiting).toEqual({ v: 'after' });
    expect(api.peek('/items').data).toEqual({ v: 'after' });
  });

  it('a clear still rejects the waiting callers as stale', async () => {
    const d = deferred();
    const { api, auth } = make(() => d.promise);
    const waiting = api.get('/items');
    const direct = api.request('/items');
    await tick();
    auth.logout();
    d.resolve(res(200, { v: 'old' }));
    await expect(waiting).rejects.toMatchObject({ stale: true });
    await expect(direct).rejects.toMatchObject({ stale: true });
  });
});
