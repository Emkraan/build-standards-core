import { describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import {
  ConsoleFeed,
  FEED_SIDE_KEY,
  createApi,
  createStore,
  healthStatusOf,
  mergeHealth,
  mergeItems,
  defaultStore,
  parseFeed,
  useApiResource,
  useConsoleFeed,
  useResource,
} from '../../../shell-packages/app-client/src';
import type { FeedEntry } from '../../../shell-packages/app-client/src';
import { staleError } from '../../../shell-packages/app-client/src/cache';

function auth() {
  return {
    apiScope: 'api://test/access_as_user',
    acquireToken: vi.fn(async () => 'tok'),
    loginOn401: vi.fn(() => new Promise<never>(() => undefined)),
    accountId: () => 'acct',
    onAccountChange: () => () => undefined,
    onLogout: () => () => undefined,
  };
}

describe('useResource', () => {
  it('two components asking for the same key share one request and one answer', async () => {
    const store = createStore();
    const fetcher = vi.fn(async () => ({ connected: true }));
    function Banner() {
      const { data } = useResource('/connector/me', fetcher, { store, ttl: 30_000 });
      return <p>banner {data ? 'on' : 'off'}</p>;
    }
    function Insights() {
      const { data, loading } = useResource('/connector/me', fetcher, { store, ttl: 30_000 });
      return <p>insights {loading ? 'loading' : data ? 'on' : 'off'}</p>;
    }
    render(
      <>
        <Banner />
        <Insights />
      </>,
    );
    expect(screen.getByText('insights loading')).toBeTruthy();
    await screen.findByText('banner on');
    await screen.findByText('insights on');
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it('renders cached data at once and revalidates when stale', async () => {
    const store = createStore();
    store.set('/me', { v: 'cached' }, 1);
    const fetcher = vi.fn(async () => ({ v: 'fresh' }));
    function Me() {
      const { data } = useResource<{ v: string }>('/me', fetcher, { store, ttl: 60_000 });
      return <p>{data?.v}</p>;
    }
    render(<Me />);
    expect(screen.getByText('cached')).toBeTruthy();
    await screen.findByText('fresh');
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it('does not refetch fresh data on mount, and skips while disabled', async () => {
    const store = createStore();
    store.set('/x', 1);
    const fetcher = vi.fn(async () => 2);
    function X({ on }: { on: boolean }) {
      const { data } = useResource('/x', fetcher, { store, ttl: 60_000, enabled: on });
      return <p>x {String(data)}</p>;
    }
    const { rerender } = render(<X on={false} />);
    rerender(<X on />);
    await act(async () => undefined);
    expect(fetcher).not.toHaveBeenCalled();
    expect(screen.getByText('x 1')).toBeTruthy();
  });

  it('refetches a mounted key after the store is invalidated', async () => {
    const store = createStore();
    let n = 0;
    const fetcher = vi.fn(async () => {
      n += 1;
      return `user${n}`;
    });
    function Me() {
      const { data, loading } = useResource('/me', fetcher, { store, ttl: 60_000 });
      return <p>{loading ? 'loading' : `me ${String(data)}`}</p>;
    }
    render(<Me />);
    await screen.findByText('me user1');
    act(() => store.clear());
    await screen.findByText('me user2');
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it('useApiResource paints a persisted identity read before its request', async () => {
    window.sessionStorage.setItem('hydr.api.v1.account', 'acct');
    window.sessionStorage.setItem('hydr.api.v1:/me', JSON.stringify({ at: 1, data: { name: 'cached' } }));
    let release: (r: Response) => void = () => undefined;
    const fetchMock = vi.fn(() => new Promise<Response>((r) => (release = r)));
    const api = createApi({ baseUrl: 'https://gw/api', auth: auth(), namespace: 'hydr', persist: ['/me'], fetch: fetchMock as unknown as typeof fetch });
    function Me() {
      const { data, loading } = useApiResource<{ name: string }>(api, '/me');
      return <p>{loading ? 'loading' : `me ${String(data?.name)}`}</p>;
    }
    render(<Me />);
    // The first render already has the persisted answer, then it revalidates.
    expect(screen.getByText('me cached')).toBeTruthy();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await act(async () => release(new Response(JSON.stringify({ name: 'fresh' }), { status: 200 })));
    await screen.findByText('me fresh');
  });

  it('polls while visible and pauses while hidden', async () => {
    vi.useFakeTimers();
    try {
      const store = createStore();
      const fetcher = vi.fn(async () => 1);
      function P() {
        useResource('/p', fetcher, { store, refreshInterval: 60_000 });
        return null;
      }
      render(<P />);
      await act(async () => undefined);
      expect(fetcher).toHaveBeenCalledTimes(1);
      await act(async () => {
        vi.advanceTimersByTime(60_000);
      });
      expect(fetcher).toHaveBeenCalledTimes(2);

      const vis = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
      await act(async () => {
        vi.advanceTimersByTime(180_000);
      });
      expect(fetcher).toHaveBeenCalledTimes(2);

      vis.mockReturnValue('visible');
      await act(async () => {
        document.dispatchEvent(new Event('visibilitychange'));
      });
      expect(fetcher).toHaveBeenCalledTimes(3);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('createStore stale rejections', () => {
  it('a stale rejection from a fetcher releases the key, so the next fetch retries', async () => {
    // A hook on one store reading an API whose own cache was cleared: the fetcher rejects as
    // stale while this store was never cleared.
    const store = createStore();
    const fetcher = vi.fn().mockRejectedValueOnce(staleError()).mockResolvedValueOnce({ v: 2 });
    await expect(store.fetch('k', fetcher)).rejects.toMatchObject({ stale: true });
    expect(store.snapshot('k').validating).toBe(false);
    await expect(store.fetch('k', fetcher)).resolves.toEqual({ v: 2 });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it('a fetcher that throws synchronously never leaves the key stuck', async () => {
    const store = createStore();
    let first = true;
    const fetcher = () => {
      if (first) {
        first = false;
        throw staleError();
      }
      return Promise.resolve('ok');
    };
    await expect(store.fetch('k', fetcher)).rejects.toMatchObject({ stale: true });
    await expect(store.fetch('k', fetcher)).resolves.toBe('ok');
    expect(store.snapshot('k').validating).toBe(false);
  });

  it('a polled useResource recovers after a stale rejection instead of loading forever', async () => {
    const store = createStore();
    let calls = 0;
    const fetcher = () => {
      calls += 1;
      return calls === 1 ? Promise.reject(staleError()) : Promise.resolve('fresh');
    };
    function Probe() {
      const r = useResource('stale-key', fetcher, { store, refreshInterval: 20 });
      return <p>{r.data === undefined ? 'loading' : String(r.data)}</p>;
    }
    render(<Probe />);
    expect(await screen.findByText('fresh', {}, { timeout: 2000 })).toBeTruthy();
  });
});

describe('feed helpers', () => {
  it('reads both health shapes', () => {
    expect(healthStatusOf({ status: 'ok' })).toBe('ok');
    expect(healthStatusOf({ ok: true })).toBe('ok');
    expect(healthStatusOf({ ok: false })).toBe('degraded');
    expect(healthStatusOf({ status: 'down' })).toBe('down');
    expect(healthStatusOf(null)).toBe('unknown');
  });

  it('parses a feed and drops malformed items', () => {
    const feed = parseFeed({
      health: { status: 'degraded', label: '1 of 5 services need attention' },
      items: [
        { id: 'a', tone: 'warning', title: 'Printer Module unreachable', href: '/estate' },
        { id: 'b', tone: 'loud', title: 'bad tone' },
        { tone: 'info', title: 'no id' },
        'junk',
      ],
    });
    expect(feed?.health).toEqual({ status: 'degraded', label: '1 of 5 services need attention' });
    expect(feed?.items.map((i) => i.id)).toEqual(['a']);
    expect(parseFeed({ health: { status: 'weird' } })?.health.status).toBe('unknown');
    expect(parseFeed(null)).toBeNull();
  });

  it('merges health: the module being unreachable wins, then the worst status', () => {
    const platform = { status: 'ok' as const, label: 'All systems normal' };
    expect(mergeHealth('Example Shell', { status: 'ok', failed: true }, platform)).toEqual({ status: 'down', label: 'Example Shell API unreachable, retrying' });
    expect(mergeHealth('Example Shell', { status: 'degraded', failed: false }, platform).status).toBe('degraded');
    expect(mergeHealth('Example Shell', { status: 'ok', failed: false }, platform)).toEqual(platform);
    const bad = { status: 'down' as const, label: '3 of 5 services down' };
    expect(mergeHealth('Example Shell', { status: 'degraded', failed: false }, bad)).toEqual(bad);
    expect(mergeHealth('Example Shell', { status: 'ok', failed: false }, null)).toEqual({ status: 'ok', label: 'Example Shell online' });
    expect(mergeHealth('Example Shell', null, null)).toEqual({ status: 'unknown', label: 'Checking status' });
    // The module answered but its status is unknown: the platform line still shows.
    expect(mergeHealth('Example Shell', { status: 'unknown', failed: false }, platform)).toEqual(platform);
  });

  it('orders items by severity, platform first on a tie, unique and capped', () => {
    const p: FeedEntry[] = [
      { id: 'p1', tone: 'info', title: 'Maintenance tonight' },
      { id: 'p2', tone: 'warning', title: 'Printer degraded' },
    ];
    const t: FeedEntry[] = [
      { id: 't1', tone: 'critical', title: 'Connector disconnected' },
      { id: 't2', tone: 'info', title: '3 blocked numbers' },
      { id: 'p1', tone: 'info', title: 'duplicate' },
    ];
    expect(mergeItems(p, t).map((i) => i.id)).toEqual(['t1', 'p2', 'p1', 't2']);
    const many = Array.from({ length: 30 }, (_, i) => ({ id: `i${i}`, tone: 'info' as const, title: 'x' }));
    expect(mergeItems(many, [])).toHaveLength(12);
  });
});

describe('ConsoleFeed', () => {
  function feedApi(body: unknown, status = 200) {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(body), { status }));
    const api = createApi({ baseUrl: 'https://gw/console/api', auth: auth(), namespace: 'feedtest', on401: 'throw', fetch: fetchMock as unknown as typeof fetch });
    return { api, fetchMock };
  }

  /** The module's own client, interactive (the default on401 "login") like every console's. */
  function toolClient(answer: () => Promise<Response>, a = auth()) {
    const fetchMock = vi.fn(answer);
    const api = createApi({ baseUrl: 'https://gw/module/api', auth: a, namespace: 'tooltest', fetch: fetchMock as unknown as typeof fetch });
    return { api, fetchMock, auth: a };
  }

  function module(status: number, body: unknown) {
    return toolClient(async () => new Response(JSON.stringify(body), { status })).api;
  }

  it('renders the mascot, the merged health line and the platform plus module items', async () => {
    const { api, fetchMock } = feedApi({
      health: { status: 'ok', label: 'All systems normal' },
      items: [{ id: 'ann-1', tone: 'info', title: 'Maintenance window', body: 'Saturday 22:00', href: '/admin' }],
    });
    const navigate = vi.fn();
    const { container } = render(
      <ConsoleFeed
        app="Example Shell"
        consoleApi={api}
        toolApi={module(200, { ok: true })}
        items={[{ id: 'connector', tone: 'critical', title: 'Connector disconnected' }]}
        navigate={navigate}
      />,
    );
    await screen.findByText('All systems normal');
    expect(fetchMock).toHaveBeenCalledWith('https://gw/console/api/feed', expect.anything());
    expect(container.querySelector('.presenter-figure svg')).toBeTruthy();
    // Most severe first: the module's critical item leads.
    expect(screen.getByText('Connector disconnected')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Show item 2 of 2' }));
    fireEvent.click(await screen.findByText('Maintenance window'));
    expect(navigate).toHaveBeenCalledWith('/admin');
  });

  it('keeps the strip and says so when the module API is down', async () => {
    const { api } = feedApi({ health: { status: 'ok', label: 'All systems normal' }, items: [] });
    render(
      <ConsoleFeed
        app="Example Shell"
        consoleApi={api}
        toolApi={
          toolClient(async () => {
            throw new TypeError('Failed to fetch');
          }).api
        }
      />,
    );
    await screen.findByText('Example Shell API unreachable, retrying');
  });

  it('reads a 2xx health body in an unknown shape as online, and a 401 as not unreachable', async () => {
    const { api } = feedApi({ health: { status: 'unknown', label: '' }, items: [] });
    render(<ConsoleFeed app="Example Shell" consoleApi={api} toolApi={module(200, { healthy: true })} />);
    await screen.findByText('Example Shell online');
  });

  it('a 401 from the module health shows the platform line, not unreachable', async () => {
    const { api } = feedApi({ health: { status: 'ok', label: 'All systems normal' }, items: [] });
    render(
      <ConsoleFeed
        app="Example Shell"
        consoleApi={api}
        toolApi={module(401, {})}
      />,
    );
    await screen.findByText('All systems normal');
    expect(screen.queryByText(/unreachable/)).toBeNull();
  });

  it('keeps the module health in the console API store, so a logout drops it', async () => {
    const { api } = feedApi({ health: { status: 'ok', label: 'All systems normal' }, items: [] });
    render(<ConsoleFeed app="Store Check" consoleApi={api} toolApi={module(200, { ok: true })} />);
    await waitFor(() => expect(api.store.snapshot('feed:Store Check:health').data).toEqual({ ok: true }));
    expect(defaultStore.snapshot('feed:Store Check:health').data).toBeUndefined();
  });

  it('keeps the unreachable line while the next retry runs', async () => {
    const { api } = feedApi({ health: { status: 'ok', label: 'All systems normal' }, items: [] });
    let calls = 0;
    let finish: (r: Response) => void = () => undefined;
    const { api: toolApi } = toolClient(() => {
      calls += 1;
      return calls === 1 ? Promise.reject(new TypeError('Failed to fetch')) : new Promise<Response>((r) => (finish = r));
    });
    function Harness() {
      const state = useConsoleFeed({ app: 'Example Shell', consoleApi: api, toolApi });
      return <p>{state.health.label}</p>;
    }
    render(<Harness />);
    await screen.findByText('Example Shell API unreachable, retrying');
    let retry: Promise<unknown> = Promise.resolve();
    await act(async () => {
      retry = api.store.fetch('feed:Example Shell:health', () => toolApi.request('/health', { on401: 'throw' }), { force: true }).catch(() => undefined);
    });
    // The retry is in flight: the line still says unreachable.
    expect(screen.getByText('Example Shell API unreachable, retrying')).toBeTruthy();
    await act(async () => {
      finish(new Response(JSON.stringify({ ok: true }), { status: 200 }));
      await retry;
    });
    expect(await screen.findByText('All systems normal')).toBeTruthy();
  });

  it('the feed poll and the module health never start a sign-in, even on interactive clients', async () => {
    const a = auth();
    const fetchMock = vi.fn(async () => new Response('{}', { status: 401 }));
    // Both clients use the default on401 "login".
    const consoleApi = createApi({ baseUrl: 'https://gw/console/api', auth: a, namespace: 'feed-login', fetch: fetchMock as unknown as typeof fetch });
    const toolApi = createApi({ baseUrl: 'https://gw/module/api', auth: a, namespace: 'module-login', fetch: fetchMock as unknown as typeof fetch });
    render(<ConsoleFeed app="Example Shell" consoleApi={consoleApi} toolApi={toolApi} toolHealthPath="/healthz" />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect((fetchMock.mock.calls as unknown as Array<[string]>).map((c) => c[0]).sort()).toEqual(['https://gw/console/api/feed', 'https://gw/module/api/healthz']);
    await waitFor(() => expect(consoleApi.store.snapshot(FEED_SIDE_KEY).error).toMatchObject({ status: 401 }));
    await waitFor(() => expect(consoleApi.store.snapshot('feed:Example Shell:health').error).toMatchObject({ status: 401 }));
    expect(a.loginOn401).not.toHaveBeenCalled();
    for (const call of a.acquireToken.mock.calls as unknown as Array<[unknown, unknown]>) expect(call[1]).toEqual({ interactive: false });
    // A 401 is not unreachable: the line waits on the platform instead.
    expect(screen.queryByText(/unreachable/)).toBeNull();
  });

  it('the feed side read never shares a fetch with an interactive /feed resource on the same client', async () => {
    const a = auth();
    let release: (r: Response) => void = () => undefined;
    const fetchMock = vi.fn(() => new Promise<Response>((r) => (release = r)));
    const consoleApi = createApi({ baseUrl: 'https://gw/console/api', auth: a, namespace: 'feed-split', fetch: fetchMock as unknown as typeof fetch });
    function Interactive() {
      useApiResource(consoleApi, '/feed');
      return null;
    }
    render(
      <>
        <Interactive />
        <ConsoleFeed app="shell" consoleApi={consoleApi} toolApi={null} />
      </>,
    );
    // Two fetches, one per mode, instead of one shared in flight request.
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect((a.acquireToken.mock.calls as unknown as Array<[unknown, { interactive?: boolean } | undefined]>).some((c) => c[1]?.interactive === false)).toBe(true);
    release(new Response('{}', { status: 200 }));
  });

  it('invalidate on the /feed prefix also refreshes the feed side read', async () => {
    const a = auth();
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ items: [] }), { status: 200, headers: { 'content-type': 'application/json' } }));
    const consoleApi = createApi({ baseUrl: 'https://gw/console/api', auth: a, namespace: 'feed-inval', fetch: fetchMock as unknown as typeof fetch });
    render(<ConsoleFeed app="shell" consoleApi={consoleApi} toolApi={null} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    act(() => consoleApi.store.invalidate('/feed'));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it('a feed poll that needs a sign-in reads as a 401, never a redirect', async () => {
    const a = auth();
    a.acquireToken.mockRejectedValue(Object.assign(new Error('interaction_required'), { interactionRequired: true }));
    const fetchMock = vi.fn(async () => new Response('{}', { status: 200 }));
    const consoleApi = createApi({ baseUrl: 'https://gw/console/api', auth: a, namespace: 'feed-ir', fetch: fetchMock as unknown as typeof fetch });
    const { api: toolApi } = toolClient(async () => new Response('{}', { status: 200 }), a);
    render(<ConsoleFeed app="Example Shell" consoleApi={consoleApi} toolApi={toolApi} />);
    await waitFor(() => expect(consoleApi.store.snapshot('feed:Example Shell:health').error).toMatchObject({ status: 401 }));
    await waitFor(() => expect(consoleApi.store.snapshot(FEED_SIDE_KEY).error).toMatchObject({ status: 401 }));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(a.loginOn401).not.toHaveBeenCalled();
  });

  it('shows the module health alone when no console API is configured', async () => {
    render(<ConsoleFeed app="shell" consoleApi={null} toolApi={module(200, { status: 'ok' })} />);
    await waitFor(() => expect(screen.getByText('shell online')).toBeTruthy());
  });

  it('never makes a script href clickable', async () => {
    const { api } = feedApi({ health: { status: 'ok', label: 'ok' }, items: [{ id: 'x', tone: 'info', title: 'Click me', href: 'javascript:alert(1)' }] });
    vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    render(<ConsoleFeed app="shell" consoleApi={api} />);
    const title = await screen.findByText('Click me');
    expect(title.closest('button')).toBeNull();
  });
});
