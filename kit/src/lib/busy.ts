/* One "the system is processing" signal (UI standard, "One processing indicator"). A store counts the requests in
   flight; `BusyIndicator` reads it and shows one slim bar, so no page has to remember its own spinner. Nothing is
   patched unless the app asks: wire it by `trackBusy(promise)` around the app's own client, or call
   `installBusyTracking()` once to have `window.fetch` report same-origin API calls itself. Background work that
   should not raise the bar (a refresh timer, a poll) runs inside `quietly(...)`. The store never blocks input and
   never cancels a request: cancelling a read, or stopping one on the server, is the app's own. */

import { useSyncExternalStore } from 'react';
import { isBrowser } from './env';

export interface BusyState {
  /** Requests in flight that are being counted. */
  count: number;
  /** Something in flight changes data (not a GET, HEAD or a POST that only reads): the label reads Saving. */
  writing: boolean;
  /** When the oldest one started (ms since the epoch), or 0 when idle. */
  since: number;
}

const IDLE: BusyState = { count: 0, writing: false, since: 0 };
let state: BusyState = IDLE;
const listeners = new Set<() => void>();
const live = new Set<{ write: boolean; started: number }>();
let quietDepth = 0;

function refresh(): void {
  let writing = false;
  let since = 0;
  for (const t of live) {
    if (t.write) writing = true;
    if (!since || t.started < since) since = t.started;
  }
  state = live.size === 0 ? IDLE : { count: live.size, writing, since };
  for (const l of listeners) l();
}

/** Runs `fn` with counting off for any request it starts synchronously (timers, background refresh). */
export function quietly<T>(fn: () => T): T {
  quietDepth++;
  try {
    return fn();
  } finally {
    quietDepth--;
  }
}

/**
 * Counts `work` as busy until it settles, and returns it unchanged. `write` says it changes data (label "Saving").
 * Inside `quietly` it is not counted.
 */
export function trackBusy<T>(work: Promise<T>, options: { write?: boolean | undefined } = {}): Promise<T> {
  if (quietDepth > 0) return work;
  const entry = { write: !!options.write, started: Date.now() };
  live.add(entry);
  refresh();
  const done = () => {
    live.delete(entry);
    refresh();
  };
  work.then(done, done);
  return work;
}

export function getBusyState(): BusyState {
  return state;
}

/** The busy state, kept current. */
export function useBusy(): BusyState {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => state,
    () => IDLE,
  );
}

export interface BusyTrackingOptions {
  /** Which requests count. Default: same-origin paths that start with `/api/`. */
  match?: ((url: URL, method: string) => boolean) | undefined;
  /** Last path segments of POSTs that only read (a search, a report run): they read as Loading, not Saving. Default none. */
  readOnlyPosts?: Iterable<string> | undefined;
}

let uninstall: (() => void) | null = null;

/**
 * Makes `window.fetch` report matching calls to the store. Opt in, once, at startup; it returns the function that
 * puts the original back. A second call while installed does nothing and returns the same function. It only
 * observes: the request, its signal and its result are the caller's own.
 */
export function installBusyTracking(options: BusyTrackingOptions = {}): () => void {
  if (uninstall) return uninstall;
  if (!isBrowser) return () => undefined;
  const original = window.fetch;
  const readOnly = new Set(options.readOnlyPosts ?? []);
  const match = options.match ?? ((url: URL) => url.origin === window.location.origin && url.pathname.startsWith('/api/'));
  window.fetch = function patched(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
    let url: URL | null = null;
    try {
      const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      url = new URL(raw, window.location.href);
    } catch {
      url = null;
    }
    const method = (init?.method ?? (typeof input === 'object' && 'method' in input ? input.method : 'GET')).toUpperCase();
    const result = original.call(window, input, init);
    if (!url || !match(url, method)) return result;
    const last = url.pathname.split('/').filter(Boolean).pop() ?? '';
    const write = method !== 'GET' && method !== 'HEAD' && !(method === 'POST' && readOnly.has(last));
    return trackBusy(result, { write });
  };
  const patched = window.fetch;
  uninstall = () => {
    if (window.fetch === patched) window.fetch = original;
    uninstall = null;
  };
  return uninstall;
}
