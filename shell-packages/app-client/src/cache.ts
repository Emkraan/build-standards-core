/* A small keyed resource store: single-flight fetches, a per-key freshness window and
   subscribers, so every component that asks for the same key shares one request and one copy
   of the answer (stale-while-revalidate). */

export interface ResourceSnapshot<T = unknown> {
  readonly data: T | undefined;
  readonly error: unknown;
  /** Epoch ms of the last successful fetch, 0 when never fetched. */
  readonly at: number;
  /** A fetch for this key is in flight. */
  readonly validating: boolean;
}

export interface FetchOptions {
  /** Freshness window in ms. Fresh data is returned without a request. 0 = always fetch (in-flight requests are still shared). */
  ttl?: number | undefined;
  /** Fetch even when fresh. An in-flight request is still shared. */
  force?: boolean | undefined;
}

export interface ResourceStore {
  snapshot<T>(key: string): ResourceSnapshot<T>;
  subscribe(key: string, listener: () => void): () => void;
  fetch<T>(key: string, fetcher: () => Promise<T>, opts?: FetchOptions): Promise<T>;
  set<T>(key: string, data: T, at?: number): void;
  /** Put data under an empty key without notifying anyone (at 0, so it counts as stale). */
  seed<T>(key: string, data: T): void;
  isFresh(key: string, ttl: number): boolean;
  /**
   * Drop cached data for keys equal to or starting with the prefix (all keys when omitted). A
   * caller waiting on a fetch that started before the invalidation gets one started after it.
   */
  invalidate(prefix?: string): void;
  /** Drop everything for a session change. Waiting callers reject with a stale error. */
  clear(): void;
  /** Called after every successful fetch or set, for persistence. */
  onData(cb: (key: string, data: unknown, at: number) => void): () => void;
}

/** The error a fetch rejects with when the store was cleared while it was in flight. */
export interface StaleError extends Error {
  stale: true;
}

export function staleError(): StaleError {
  const err = new Error('The request was dropped because the session changed.') as StaleError;
  err.stale = true;
  return err;
}

export function isStale(err: unknown): err is StaleError {
  return Boolean(err && typeof err === 'object' && (err as { stale?: unknown }).stale === true);
}

const EMPTY: ResourceSnapshot<never> = Object.freeze({ data: undefined, error: undefined, at: 0, validating: false });

interface Entry {
  snap: ResourceSnapshot;
  promise: Promise<unknown> | null;
  /** Bumped by invalidate/clear so a late response from before the clear is dropped. */
  epoch: number;
}

export function createStore({ now = () => Date.now() }: { now?: () => number } = {}): ResourceStore {
  const entries = new Map<string, Entry>();
  const listeners = new Map<string, Set<() => void>>();
  const dataListeners = new Set<(key: string, data: unknown, at: number) => void>();
  let epoch = 0;
  // Bumped only by clear() (logout, account change). A fetch from an older session rejects as
  // stale. A plain invalidate() keeps the session, so its waiting callers are re-run instead.
  let session = 0;

  function entry(key: string): Entry {
    let e = entries.get(key);
    if (!e) {
      e = { snap: EMPTY, promise: null, epoch };
      entries.set(key, e);
    }
    return e;
  }

  function emit(key: string): void {
    const set = listeners.get(key);
    if (set) for (const l of [...set]) l();
  }

  function update(key: string, patch: Partial<ResourceSnapshot>): void {
    const e = entry(key);
    e.snap = Object.freeze({ ...e.snap, ...patch });
    emit(key);
  }

  function isFresh(key: string, ttl: number): boolean {
    const e = entries.get(key);
    if (!e || e.snap.at === 0 || e.snap.data === undefined) return false;
    return ttl > 0 && now() - e.snap.at < ttl;
  }

  function fetch<T>(key: string, fetcher: () => Promise<T>, { ttl = 0, force = false }: FetchOptions = {}): Promise<T> {
    const e = entry(key);
    if (e.promise) return e.promise as Promise<T>;
    if (!force && isFresh(key, ttl)) return Promise.resolve(e.snap.data as T);

    const started = e.epoch;
    const startedSession = session;
    // An invalidation (not a clear) while this fetch was in flight: its answer predates the
    // invalidation, so the waiting callers get a fetch that started after it (the one a new
    // caller already started, or a new one).
    const again = () => fetch<T>(key, fetcher, { ttl });
    // Set right after the fetch starts. The stale branch compares against it.
    let self: Promise<T> | null = null;
    // A fetcher that throws synchronously settles before the entry records the promise, and the
    // entry must then never record it.
    let settled = false;
    const p = (async () => {
      let data: T;
      try {
        data = await fetcher();
      } catch (err) {
        settled = true;
        // Cleared while in flight (logout, account change): nothing from the old session,
        // not even its error, reaches a caller.
        if (isStale(err) || session !== startedSession) {
          // A stale error from the fetcher while this store was not cleared (a hook on
          // defaultStore reading an API whose own cache was cleared) leaves this fetch as the
          // entry's promise. Release it, so the next fetch or poll of the key starts a new
          // request instead of getting this rejection forever.
          const cur = entries.get(key);
          if (cur && cur.promise === self) {
            cur.promise = null;
            update(key, { validating: false });
          }
          throw isStale(err) ? err : staleError();
        }
        const cur = entries.get(key);
        if (cur && cur.epoch !== started) return again();
        if (cur) {
          cur.promise = null;
          // Keep the last good data on a failed revalidation (stale beats empty).
          update(key, { error: err, validating: false });
        }
        throw err;
      }
      settled = true;
      if (session !== startedSession) throw staleError();
      const cur = entries.get(key);
      if (!cur || cur.epoch !== started) return again();
      const at = now();
      cur.promise = null;
      update(key, { data, error: undefined, at, validating: false });
      for (const cb of dataListeners) cb(key, data, at);
      return data;
    })();
    self = p;
    if (!settled) {
      e.promise = p;
      update(key, { validating: true });
    }
    return p;
  }

  function set<T>(key: string, data: T, at: number = now()): void {
    update(key, { data, error: undefined, at });
    for (const cb of dataListeners) cb(key, data, at);
  }

  function seed<T>(key: string, data: T): void {
    const e = entry(key);
    if (e.snap.data !== undefined) return;
    e.snap = Object.freeze({ ...e.snap, data, at: 0 });
  }

  function invalidate(prefix?: string): void {
    epoch += 1;
    for (const [key, e] of entries) {
      if (prefix === undefined || key === prefix || key.startsWith(prefix)) {
        e.epoch = epoch;
        e.promise = null;
        e.snap = EMPTY;
        emit(key);
      }
    }
  }

  return {
    snapshot<T>(key: string) {
      return (entries.get(key)?.snap ?? EMPTY) as ResourceSnapshot<T>;
    },
    subscribe(key, listener) {
      let set = listeners.get(key);
      if (!set) {
        set = new Set();
        listeners.set(key, set);
      }
      set.add(listener);
      return () => {
        set.delete(listener);
        if (set.size === 0) listeners.delete(key);
      };
    },
    fetch,
    set,
    seed,
    isFresh,
    invalidate,
    clear: () => {
      session += 1;
      invalidate();
    },
    onData(cb) {
      dataListeners.add(cb);
      return () => dataListeners.delete(cb);
    },
  };
}

/** The store useResource uses when none is passed. */
export const defaultStore: ResourceStore = createStore();
