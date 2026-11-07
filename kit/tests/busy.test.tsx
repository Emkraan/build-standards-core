/* The one processing indicator: the busy store, the opt-in fetch tracking and the BusyIndicator. */
import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BusyIndicator, getBusyState, installBusyTracking, quietly, trackBusy } from '../src';

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
    expect(getBusyState()).toEqual({ count: 0, writing: false, since: 0 });
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
