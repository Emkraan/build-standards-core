/* useResource: an SWR-style hook over a ResourceStore. Every component that asks for the same
   key shares one request and one copy of the answer. Cached data renders at once and is
   revalidated when stale. Polling pauses while the tab is hidden. */

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import type { Api, GetOptions } from './api';
import { defaultStore } from './cache';
import type { ResourceStore } from './cache';

export interface UseResourceOptions {
  /** Freshness window in ms. Data younger than this is not refetched on mount. Default 0. */
  ttl?: number | undefined;
  store?: ResourceStore | undefined;
  /** false = do not fetch (for example while signed out). Cached data is still returned. */
  enabled?: boolean | undefined;
  /** Poll every N ms while the tab is visible. */
  refreshInterval?: number | undefined;
  /** Refetch when the tab becomes visible again and the data is stale (default true with refreshInterval). */
  revalidateOnFocus?: boolean | undefined;
}

export interface UseResourceResult<T> {
  data: T | undefined;
  error: unknown;
  /** No data yet and a request is in flight (or about to start). */
  loading: boolean;
  /** A request is in flight, with or without data. */
  validating: boolean;
  /** Epoch ms of the data, 0 when none. */
  updatedAt: number;
  /** Fetch now, sharing an in-flight request. */
  refresh: () => Promise<T | undefined>;
}

function isVisible(): boolean {
  return typeof document === 'undefined' || document.visibilityState !== 'hidden';
}

export function useResource<T>(
  key: string | null,
  fetcher: () => Promise<T>,
  { ttl = 0, store = defaultStore, enabled = true, refreshInterval, revalidateOnFocus }: UseResourceOptions = {},
): UseResourceResult<T> {
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const active = Boolean(key) && enabled;

  const subscribe = useCallback((cb: () => void) => (key ? store.subscribe(key, cb) : () => undefined), [store, key]);
  const getSnap = useCallback(() => (key ? store.snapshot<T>(key) : store.snapshot<T>('')), [store, key]);
  const snap = useSyncExternalStore(subscribe, getSnap, getSnap);

  const run = useCallback(
    (force: boolean) => {
      if (!key) return Promise.resolve(undefined);
      return store.fetch<T>(key, () => fetcherRef.current(), { ttl, force }).catch(() => undefined);
    },
    [store, key, ttl],
  );

  // Mount and key change: fetch unless fresh.
  useEffect(() => {
    if (!active) return;
    void run(false);
  }, [active, run]);

  // An invalidation (logout, account change) empties the snapshot without changing the key, so the
  // effect above does not run again. Refetch when an active key has nothing and nothing in flight.
  const empty = snap.data === undefined && snap.at === 0 && snap.error === undefined && !snap.validating;
  useEffect(() => {
    if (!active || !empty) return;
    void run(false);
  }, [active, empty, run]);

  // Polling, paused while hidden.
  useEffect(() => {
    if (!active || !refreshInterval || refreshInterval < 1000) return undefined;
    const every = refreshInterval;
    const timer = window.setInterval(() => {
      if (isVisible()) void run(true);
    }, every);
    return () => window.clearInterval(timer);
  }, [active, refreshInterval, run]);

  // Back to a visible tab: revalidate if the data aged past the window (or the poll interval).
  const focus = revalidateOnFocus ?? Boolean(refreshInterval);
  useEffect(() => {
    if (!active || !focus || typeof document === 'undefined') return undefined;
    const onVis = () => {
      if (!isVisible() || !key) return;
      const span = refreshInterval && refreshInterval > ttl ? refreshInterval : ttl;
      if (!store.isFresh(key, span)) void run(true);
    };
    document.addEventListener('visibilitychange', onVis);
    return () => document.removeEventListener('visibilitychange', onVis);
  }, [active, focus, key, refreshInterval, ttl, store, run]);

  return {
    data: snap.data,
    error: snap.error,
    loading: snap.data === undefined && (snap.validating || (active && snap.at === 0 && snap.error === undefined)),
    validating: snap.validating,
    updatedAt: snap.at,
    refresh: () => run(true),
  };
}

/** useResource bound to an Api: the key is the path and the answer lands in the api's cache. */
export function useApiResource<T>(
  api: Api,
  path: string | null,
  opts: Omit<UseResourceOptions, 'store'> & Pick<GetOptions, 'ttl'> = {},
): UseResourceResult<T> {
  // Persisted identity reads (/me, my-permissions) load from sessionStorage before the first
  // snapshot, so the shell paints at once. Once per mount, and hydrate() seeds the store without
  // notifying subscribers, so it never updates another component during this render.
  useState(() => {
    if (path) api.hydrate();
    return null;
  });
  const ttl = opts.ttl ?? (path ? api.ttlFor(path) : 0);
  return useResource<T>(path, () => api.request<T>(path as string), { ...opts, ttl, store: api.store });
}
