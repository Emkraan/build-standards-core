/* The one processing indicator: the busy store, the opt-in fetch tracking and the BusyIndicator. */
import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BusyIndicator, CANCELLED_MESSAGE, LEFT_PAGE_MESSAGE, abortStaleReads, cancelBusyReads, getBusyState, installBusyTracking, quietly, trackBusy } from '../src';

function deferred<T = void>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((a, b) => {
    resolve = a;
    reject = b;
  });
  return { promise, resolve, reject };
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe('trackBusy and quietly', () => {
  it('counts work until it settles, and reads Saving only for a write', async () => {
    const a = deferred();
    const b = deferred();
    const pa = trackBusy(a.promise);
    expect(getBusyState()).toMatchObject({ count: 1, writing: false });
    const pb = trackBusy(b.promise, { write: true });
    expect(getBusyState()).toMatchObject({ count: 2, writing: true });
    a.resolve();
    await pa;
    expect(getBusyState()).toMatchObject({ count: 1, writing: true });
    b.reject(new Error('nope'));
    await expect(pb).rejects.toThrow('nope');
    expect(getBusyState()).toEqual({ count: 0, cancellable: 0, writing: false, since: 0 });
  });

  it('does not count work started inside quietly, and counts it again after', async () => {
    const q = deferred();
    quietly(() => trackBusy(q.promise));
    expect(getBusyState().count).toBe(0);
    const r = deferred();
    const p = trackBusy(r.promise);
    expect(getBusyState().count).toBe(1);
    r.resolve();
    await p;
    q.resolve();
  });
});

describe('installBusyTracking (opt in)', () => {
  it('leaves fetch alone until asked, then reports matching calls and puts the original back', async () => {
    const calls: Array<{ url: string; method: string }> = [];
    const gate = deferred<Response>();
    const original = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), method: init?.method ?? 'GET' });
      return gate.promise;
    });
    window.fetch = original as unknown as typeof fetch;
    const off = installBusyTracking({ readOnlyPosts: ['search'] });
    const p1 = window.fetch('/api/things');
    expect(getBusyState()).toMatchObject({ count: 1, writing: false });
    const p2 = window.fetch('/api/things', { method: 'POST' });
    expect(getBusyState()).toMatchObject({ count: 2, writing: true });
    gate.resolve(new Response('ok'));
    await Promise.all([p1, p2]);
    const p3 = window.fetch('/api/things/search', { method: 'POST' });
    expect(getBusyState()).toMatchObject({ count: 1, writing: false });
    await p3;
    expect(calls).toHaveLength(3);
    off();
    expect(window.fetch).toBe(original);
  });

  it('ignores other origins, non-API paths and quiet calls, and installing twice does nothing', async () => {
    const original = vi.fn(() => Promise.resolve(new Response('ok')));
    window.fetch = original as unknown as typeof fetch;
    const off = installBusyTracking();
    expect(installBusyTracking()).toBe(off);
    await window.fetch('https://other.example/api/x');
    await window.fetch('/static/app.js');
    expect(getBusyState().count).toBe(0);
    const g = deferred<Response>();
    original.mockReturnValueOnce(g.promise);
    quietly(() => void window.fetch('/api/poll'));
    expect(getBusyState().count).toBe(0);
    g.resolve(new Response('ok'));
    off();
  });

  it('returns the very same promise result to the caller (observes, never alters)', async () => {
    const res = new Response('body');
    window.fetch = vi.fn(() => Promise.resolve(res)) as unknown as typeof fetch;
    const off = installBusyTracking();
    await expect(window.fetch('/api/x')).resolves.toBe(res);
    off();
  });
});

describe('BusyIndicator', () => {
  it('stays hidden for quick work, shows after 350 ms with the right word, and holds after the last request', async () => {
    const w = deferred();
    render(<BusyIndicator />);
    let p!: Promise<void>;
    act(() => {
      p = trackBusy(w.promise);
    });
    act(() => void vi.advanceTimersByTime(300));
    expect(screen.queryByRole('status')).toBeNull();
    act(() => void vi.advanceTimersByTime(100));
    expect(screen.getByRole('status').getAttribute('aria-label')).toBe('Loading');
    let w2!: Promise<void>;
    const d2 = deferred();
    act(() => {
      w2 = trackBusy(d2.promise, { write: true });
    });
    expect(screen.getByRole('status').getAttribute('aria-label')).toBe('Saving');
    await act(async () => {
      w.resolve();
      d2.resolve();
      await Promise.all([p, w2]);
    });
    act(() => void vi.advanceTimersByTime(400));
    expect(screen.getByRole('status')).toBeTruthy();
    act(() => void vi.advanceTimersByTime(100));
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('never shows for work that finished inside the delay', async () => {
    render(<BusyIndicator />);
    const d = deferred();
    let p!: Promise<void>;
    act(() => {
      p = trackBusy(d.promise);
    });
    act(() => void vi.advanceTimersByTime(200));
    await act(async () => {
      d.resolve();
      await p;
    });
    act(() => void vi.advanceTimersByTime(1000));
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('does not take pointer input and holds still under reduced motion (stylesheet)', async () => {
    const { readFileSync } = await import('node:fs');
    const { resolve } = await import('node:path');
    const css = readFileSync(resolve(__dirname, '../src/styles/kit.css'), 'utf8');
    expect(css).toMatch(/\.busy-dock \{[^}]*pointer-events: none/);
    expect(css).toMatch(/prefers-reduced-motion: reduce\) \{ \.busy-sweep \{ animation: none/);
  });

  it('takes its own words', () => {
    const d = deferred();
    render(<BusyIndicator showAfterMs={0} savingLabel="Guardando" loadingLabel="Cargando" />);
    act(() => void trackBusy(d.promise, { write: true }));
    act(() => void vi.advanceTimersByTime(1));
    expect(screen.getByRole('status').getAttribute('aria-label')).toBe('Guardando');
    d.resolve();
  });
});

/** A fetch that never answers until its signal aborts, then rejects with the abort reason. */
const pending: ((e: Error) => void)[] = [];
afterEach(async () => {
  // Let every request a test left hanging settle, so none leaks into the next test's counts.
  for (const reject of pending.splice(0)) reject(new Error('released'));
  await Promise.resolve();
});

function hangingFetch() {
  const calls: { url: string; init?: RequestInit }[] = [];
  const fn = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), ...(init ? { init } : {}) });
    return new Promise<Response>((_, reject) => {
      pending.push(reject);
      const sig = init?.signal;
      if (sig?.aborted) reject(sig.reason);
      sig?.addEventListener('abort', () => reject(sig.reason), { once: true });
    });
  });
  return { fn, calls };
}
const message = (p: Promise<unknown>) => p.then(() => 'done', (e: Error) => e.message);

describe('stopping reads (opt in with cancel)', () => {
  it('stops every read on cancel with the cancelled message, counts it, and never stops a write', async () => {
    const h = hangingFetch();
    window.fetch = h.fn as unknown as typeof fetch;
    const off = installBusyTracking({ cancel: true });
    const read = message(window.fetch('/api/slow'));
    const write = window.fetch('/api/save', { method: 'POST' });
    expect(getBusyState()).toMatchObject({ count: 2, cancellable: 1, writing: true });
    cancelBusyReads();
    expect(await read).toBe(CANCELLED_MESSAGE);
    expect(getBusyState()).toMatchObject({ count: 1, cancellable: 0 });
    expect(h.calls[1]?.init?.signal).toBeUndefined();
    void write.catch(() => undefined);
    off();
  });

  it('joins the caller signal with its own', async () => {
    const h = hangingFetch();
    window.fetch = h.fn as unknown as typeof fetch;
    const off = installBusyTracking({ cancel: true });
    const mine = new AbortController();
    const read = message(window.fetch('/api/slow', { signal: mine.signal }));
    mine.abort(new DOMException('mine', 'AbortError'));
    expect(await read).toBe('mine');
    off();
  });

  it('leaves the request alone when cancel is off', async () => {
    const h = hangingFetch();
    window.fetch = h.fn as unknown as typeof fetch;
    const off = installBusyTracking();
    void window.fetch('/api/slow');
    expect(h.calls[0]?.init?.signal).toBeUndefined();
    expect(getBusyState().cancellable).toBe(0);
    cancelBusyReads();
    expect(getBusyState().count).toBe(1);
    off();
  });

  it('stops a read that outlived its page after the grace window, never a young one or a kept path', async () => {
    const h = hangingFetch();
    window.fetch = h.fn as unknown as typeof fetch;
    window.history.replaceState(null, '', '/a');
    const off = installBusyTracking({ cancel: true, keepAcrossRoutes: (p) => p.startsWith('/api/session') });
    const slow = message(window.fetch('/api/slow'));
    const kept = window.fetch('/api/session/ping');
    void kept.catch(() => undefined);
    abortStaleReads('/b');
    expect(getBusyState().count).toBe(2);
    vi.advanceTimersByTime(1600);
    abortStaleReads('/a');
    expect(getBusyState().count).toBe(2);
    abortStaleReads('/b');
    expect(await slow).toBe(LEFT_PAGE_MESSAGE);
    expect(getBusyState().count).toBe(1);
    off();
    window.history.replaceState(null, '', '/');
  });

  it('stops every read when the page is hidden', async () => {
    const h = hangingFetch();
    window.fetch = h.fn as unknown as typeof fetch;
    const off = installBusyTracking({ cancel: true });
    const read = message(window.fetch('/api/slow'));
    window.dispatchEvent(new Event('pagehide'));
    expect(await read).toBe(LEFT_PAGE_MESSAGE);
    off();
  });

  it('tags a server stoppable run with an id and tells the server on every stop', async () => {
    const h = hangingFetch();
    window.fetch = h.fn as unknown as typeof fetch;
    const beacon = vi.fn(() => true);
    Object.defineProperty(navigator, 'sendBeacon', { value: beacon, configurable: true });
    const off = installBusyTracking({ cancel: true, readOnlyPosts: ['run'], runs: { match: (u, m) => m === 'POST' && u.pathname === '/api/reports/run', cancelUrl: '/api/reports/runs/cancel' } });
    const run = message(window.fetch('/api/reports/run', { method: 'POST', body: '{}' }));
    const id = new Headers(h.calls[0]?.init?.headers).get('X-Run-Id');
    expect(id).toMatch(/^[0-9a-f-]{32,36}$/);
    cancelBusyReads();
    expect(await run).toBe(CANCELLED_MESSAGE);
    expect(beacon).toHaveBeenCalledTimes(1);
    const [url, blob] = beacon.mock.calls[0] as unknown as [string, Blob];
    expect(url).toBe('/api/reports/runs/cancel');
    expect(JSON.parse(await blob.text())).toEqual({ ids: [id] });
    off();
    Object.defineProperty(navigator, 'sendBeacon', { value: undefined, configurable: true });
  });

  it('falls back to a keepalive POST when the beacon is refused, and ignores a run that is not stoppable', async () => {
    const h = hangingFetch();
    window.fetch = h.fn as unknown as typeof fetch;
    Object.defineProperty(navigator, 'sendBeacon', { value: () => false, configurable: true });
    const off = installBusyTracking({ cancel: true, runs: { match: (u) => u.pathname === '/api/run', cancelUrl: '/api/cancel', header: 'X-Job' } });
    const plain = message(window.fetch('/api/other'));
    const run = message(window.fetch('/api/run'));
    expect(new Headers(h.calls[0]?.init?.headers).has('X-Job')).toBe(false);
    expect(new Headers(h.calls[1]?.init?.headers).has('X-Job')).toBe(true);
    cancelBusyReads();
    await Promise.all([plain, run]);
    const post = h.calls.find((c) => c.url === '/api/cancel');
    expect(post?.init).toMatchObject({ method: 'POST', keepalive: true });
    off();
    Object.defineProperty(navigator, 'sendBeacon', { value: undefined, configurable: true });
  });
});

describe('BusyIndicator cancel chip', () => {
  it('shows the elapsed time after 5 s, offers Cancel request only for reads that can be stopped, and stops them', async () => {
    const h = hangingFetch();
    window.fetch = h.fn as unknown as typeof fetch;
    const off = installBusyTracking({ cancel: true });
    render(<BusyIndicator />);
    let read!: Promise<string>;
    act(() => {
      read = message(window.fetch('/api/slow'));
    });
    act(() => void vi.advanceTimersByTime(1000));
    expect(screen.getByRole('status')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Cancel request' })).toBeNull();
    act(() => void vi.advanceTimersByTime(4600));
    expect(screen.getByText(/Loading, 5s/)).toBeTruthy();
    await act(async () => {
      screen.getByRole('button', { name: 'Cancel request' }).click();
      expect(await read).toBe(CANCELLED_MESSAGE);
    });
    act(() => void vi.advanceTimersByTime(600));
    expect(screen.queryByRole('status')).toBeNull();
    off();
  });

  it('shows the chip but no Cancel while only a write is in flight, and takes its own words and handler', () => {
    const d = deferred();
    const onCancel = vi.fn();
    render(<BusyIndicator cancelAfterMs={1000} cancelLabel="Stop" onCancel={onCancel} />);
    act(() => void trackBusy(d.promise, { write: true }));
    act(() => void vi.advanceTimersByTime(1600));
    expect(screen.getByText(/Saving, 1s/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Stop' })).toBeNull();
    d.resolve();
    const e = deferred();
    act(() => void trackBusy(e.promise, { abort: () => undefined }));
    act(() => void vi.advanceTimersByTime(1100));
    act(() => screen.getByRole('button', { name: 'Stop' }).click());
    expect(onCancel).toHaveBeenCalledTimes(1);
    e.resolve();
  });

  it('stops reads of the page left behind when the route changes', async () => {
    const h = hangingFetch();
    window.fetch = h.fn as unknown as typeof fetch;
    window.history.replaceState(null, '', '/a');
    const off = installBusyTracking({ cancel: true });
    const { rerender } = render(<BusyIndicator route="/a" />);
    const read = message(window.fetch('/api/slow'));
    act(() => void vi.advanceTimersByTime(2000));
    rerender(<BusyIndicator route="/b" />);
    expect(await read).toBe(LEFT_PAGE_MESSAGE);
    off();
    window.history.replaceState(null, '', '/');
  });

  it('keeps the chip clickable while the bar itself takes no input (stylesheet)', async () => {
    const { readFileSync } = await import('node:fs');
    const { resolve } = await import('node:path');
    const css = readFileSync(resolve(__dirname, '../src/styles/kit.css'), 'utf8');
    expect(css).toMatch(/\.busy-dock \{[^}]*pointer-events: none/);
    expect(css).toMatch(/\.busy-chip \{[^}]*pointer-events: auto/);
  });
});
