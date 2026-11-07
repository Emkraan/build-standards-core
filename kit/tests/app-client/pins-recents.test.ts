import { describe, expect, it, vi } from 'vitest';
import { createRecents, createServerPinsStore } from '../../../shell-packages/app-client/src';
import type { Pin } from '../../../shell-packages/app-client/src';

// The server pins store and the per-account recents, on fakes. Synthetic data only.

const pin = (over: Partial<Pin> = {}): Pin => ({ moduleId: 'klaxon', route: '/compose', label: 'Compose', ...over });

function server(initial: Pin[] = [], max = 12) {
  let pins = [...initial];
  const request = vi.fn(async (path: string, options: { method?: string; body?: unknown } = {}) => {
    if (options.method === 'PUT') {
      const p = options.body as Pin;
      pins = [...pins.filter((x) => !(x.moduleId === p.moduleId && x.route === p.route)), p];
    } else if (options.method === 'DELETE') {
      const q = new URL(path, 'http://x').searchParams;
      pins = pins.filter((x) => !(x.moduleId === q.get('moduleId') && x.route === q.get('route')));
    }
    return { pins, max };
  });
  return { request, get pins() { return pins; } };
}

describe('createServerPinsStore', () => {
  it('starts loading, reads once for any number of callers, and answers the list and the limit', async () => {
    const s = server([pin()], 5);
    const store = createServerPinsStore({ request: s.request });
    expect(store.snapshot()).toEqual({ status: 'loading', pins: [], max: 12 });
    store.load();
    store.load();
    await store.reload();
    expect(s.request).toHaveBeenCalledTimes(1);
    expect(s.request).toHaveBeenCalledWith('/home/pins', { on401: 'throw' });
    expect(store.snapshot()).toEqual({ status: 'ready', pins: [pin()], max: 5 });
  });

  it('keeps the same snapshot object until something changes, and tells listeners when it does', async () => {
    const store = createServerPinsStore({ request: server().request });
    const a = store.snapshot();
    expect(store.snapshot()).toBe(a);
    const seen = vi.fn();
    const off = store.subscribe(seen);
    await store.reload();
    expect(seen).toHaveBeenCalledTimes(1);
    expect(store.snapshot()).not.toBe(a);
    off();
    await store.pin(pin());
    expect(seen).toHaveBeenCalledTimes(1);
  });

  it('is denied, never throwing, when the read is refused or answers something else', async () => {
    const refused = createServerPinsStore({ request: async () => { throw new Error('403'); } });
    await refused.reload();
    expect(refused.snapshot().status).toBe('denied');
    const odd = createServerPinsStore({ request: async () => ({ nope: true }) });
    await odd.reload();
    expect(odd.snapshot().status).toBe('denied');
  });

  it('pins, re-labels and unpins through the server answer, and returns null on success', async () => {
    const s = server();
    const store = createServerPinsStore({ request: s.request, path: '/api/pins' });
    await store.reload();
    expect(await store.pin(pin())).toBeNull();
    expect(s.request).toHaveBeenCalledWith('/api/pins', { method: 'PUT', body: pin(), on401: 'throw' });
    expect(store.snapshot().pins).toEqual([pin()]);
    expect(await store.pin(pin({ label: 'New' }))).toBeNull();
    expect(store.snapshot().pins).toEqual([pin({ label: 'New' })]);
    expect(await store.unpin(pin({ moduleId: 'a b', route: '/x?y' }))).toBeNull();
    expect(s.request).toHaveBeenLastCalledWith('/api/pins?moduleId=a%20b&route=%2Fx%3Fy', { method: 'DELETE', on401: 'throw' });
    expect(await store.unpin(pin())).toBeNull();
    expect(store.snapshot().pins).toEqual([]);
  });

  it('answers one plain sentence on a failed write and leaves the list alone', async () => {
    const store = createServerPinsStore({ request: async (_p, o) => { if (o?.method) throw new Error('You can pin up to 12 pages.'); return { pins: [pin()], max: 12 }; } });
    await store.reload();
    expect(await store.pin(pin({ route: '/x' }))).toBe('You can pin up to 12 pages.');
    expect(store.snapshot().pins).toEqual([pin()]);
    const bare = createServerPinsStore({ request: async (_p, o) => { if (o?.method) throw {}; return { pins: [], max: 12 }; } });
    expect(await bare.pin(pin())).toBe('Could not save the pin.');
  });

  it('ignores entries that are not pins and a non-positive limit', async () => {
    const store = createServerPinsStore({ request: async () => ({ pins: [pin(), { moduleId: 1 }, null, { moduleId: 'a', route: '/', label: 'x' }], max: 0 }), max: 7 });
    await store.reload();
    expect(store.snapshot()).toEqual({ status: 'ready', pins: [pin(), { moduleId: 'a', route: '/', label: 'x' }], max: 7 });
  });

  it('reset drops the state, lets a new read start, and discards the answer of one in flight', async () => {
    let release: (v: unknown) => void = () => undefined;
    const request = vi.fn((_p: string) => new Promise<unknown>((r) => { release = r; }));
    const store = createServerPinsStore({ request });
    store.load();
    store.reset();
    release({ pins: [pin()], max: 12 });
    await Promise.resolve();
    await Promise.resolve();
    expect(store.snapshot().status).toBe('loading');
    store.load();
    expect(request).toHaveBeenCalledTimes(2);
  });
});

function memory() {
  const m = new Map<string, string>();
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), removeItem: (k: string) => void m.delete(k), keys: () => [...m.keys()] };
}

describe('createRecents', () => {
  const make = (account: { id: string | null }, storage = memory(), extra: object = {}) =>
    ({ storage, recents: createRecents({ keyPrefix: 'demo:recent:v1:', accountId: () => account.id, storage, ...extra }) });

  it('records newest first, once per page, and caps the list', () => {
    const { recents } = make({ id: 'a' }, memory(), { max: 3 });
    recents.record({ moduleId: 'm', route: '/1', label: 'One' }, 1);
    recents.record({ moduleId: 'm', route: '/2', label: 'Two' }, 2);
    recents.record({ moduleId: 'm', route: '/1', label: 'One again' }, 3);
    expect(recents.read().map((r) => [r.route, r.label, r.at])).toEqual([['/1', 'One again', 3], ['/2', 'Two', 2]]);
    recents.record({ moduleId: 'm', route: '/3', label: 'Three' }, 4);
    recents.record({ moduleId: 'm', route: '/4', label: 'Four' }, 5);
    expect(recents.read().map((r) => r.route)).toEqual(['/4', '/3', '/1']);
  });

  it('keeps one trail per account and files an unsigned person under anon', () => {
    const who = { id: 'a' as string | null };
    const { recents, storage } = make(who);
    recents.record({ moduleId: 'm', route: '/1', label: 'One' });
    who.id = 'b';
    expect(recents.read()).toEqual([]);
    recents.record({ moduleId: 'm', route: '/2', label: 'Two' });
    who.id = null;
    recents.record({ moduleId: 'm', route: '/3', label: 'Three' });
    expect(storage.keys().sort()).toEqual(['demo:recent:v1:a', 'demo:recent:v1:anon', 'demo:recent:v1:b']);
    who.id = 'a';
    expect(recents.read().map((r) => r.route)).toEqual(['/1']);
  });

  it('drops pages the shell no longer declares when read, skips pages it is told to, and trims the label', () => {
    const { recents } = make({ id: 'a' }, memory(), { skip: (p: { moduleId: string; route: string }) => p.moduleId === 'console' && p.route === '/' });
    recents.record({ moduleId: 'console', route: '/', label: 'Home' });
    recents.record({ moduleId: 'm', route: '/gone', label: 'Gone' });
    recents.record({ moduleId: 'm', route: '/kept', label: 'x'.repeat(100) });
    recents.record({ moduleId: '', route: '/x', label: 'No module' });
    expect(recents.read().length).toBe(2);
    expect(recents.read((p) => p.route !== '/gone').map((r) => r.route)).toEqual(['/kept']);
    expect(recents.read()[0]?.label.length).toBe(60);
  });

  it('clear removes the trail, and a damaged or unavailable store reads as empty and never throws', () => {
    const { recents, storage } = make({ id: 'a' });
    recents.record({ moduleId: 'm', route: '/1', label: 'One' });
    recents.clear();
    expect(recents.read()).toEqual([]);
    storage.setItem('demo:recent:v1:a', 'not json');
    expect(recents.read()).toEqual([]);
    storage.setItem('demo:recent:v1:a', '{"a":1}');
    expect(recents.read()).toEqual([]);
    storage.setItem('demo:recent:v1:a', JSON.stringify([{ moduleId: 'm', route: '/ok', label: 'ok', at: 1 }, { moduleId: 'm' }, { moduleId: 'm', route: '/r', label: 'l', at: 'x' }]));
    expect(recents.read().map((r) => r.route)).toEqual(['/ok']);
    const throwing = { getItem: () => { throw new Error('off'); }, setItem: () => { throw new Error('full'); }, removeItem: () => { throw new Error('off'); } };
    const r2 = createRecents({ keyPrefix: 'k:', accountId: () => 'a', storage: throwing });
    expect(r2.read()).toEqual([]);
    expect(() => { r2.record({ moduleId: 'm', route: '/1', label: 'One' }); r2.clear(); }).not.toThrow();
  });
});
