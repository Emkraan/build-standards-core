/* One "the system is processing" signal (UI standard, "One processing indicator"). A store counts the requests in
   flight; `BusyIndicator` reads it and shows one slim bar, so no page has to remember its own spinner. Nothing is
   patched unless the app asks: wire it by `trackBusy(promise)` around the app's own client, or call
   `installBusyTracking()` once to have `window.fetch` report same-origin API calls itself. Background work that
   should not raise the bar (a refresh timer, a poll) runs inside `quietly(...)`. The store never blocks input and
   cancels nothing unless the app opts in: `installBusyTracking({ cancel: true })` lets a read be stopped (the person
   cancels it from the indicator, the route changes, or the page is left) and, for runs the server can stop, tells the
   server too. Writes are never aborted from here: stopping one half way leaves an outcome nobody can see. */

import { useSyncExternalStore } from 'react';
import { isBrowser } from './env';

/** The message a request rejects with when the person cancels it. */
export const CANCELLED_MESSAGE = 'Request cancelled';
/** The message when the page was left first. A toast can drop it: nobody is looking at that page any more. */
export const LEFT_PAGE_MESSAGE = 'The page was left before the request finished';
/** Reads that finish inside this window after a route change are left alone, so quick shared calls behave as before. */
export const NAV_GRACE_MS = 1500;

export interface BusyState {
  /** Requests in flight that are being counted. */
  count: number;
  /** In-flight reads that Cancel would stop. */
  cancellable: number;
  /** Something in flight changes data (not a GET, HEAD or a POST that only reads): the label reads Saving. */
  writing: boolean;
  /** When the oldest one started (ms since the epoch), or 0 when idle. */
  since: number;
}

const IDLE: BusyState = { count: 0, cancellable: 0, writing: false, since: 0 };
let state: BusyState = IDLE;
const listeners = new Set<() => void>();
interface Entry {
  write: boolean;
  started: number;
  /** Stops the request. Present only for a read the app allowed to be stopped. */
  abort?: ((reason: string) => void) | undefined;
  /** The route the request was started from, for aborting reads that outlive their page. */
  route?: string | undefined;
  path?: string | undefined;
  /** Set for runs the server can stop on request. */
  runId?: string | undefined;
}
const live = new Set<Entry>();
let quietDepth = 0;

function refresh(): void {
  let writing = false;
  let since = 0;
  let cancellable = 0;
  for (const t of live) {
    if (t.write) writing = true;
    else if (t.abort) cancellable++;
    if (!since || t.started < since) since = t.started;
  }
  state = live.size === 0 ? IDLE : { count: live.size, cancellable, writing, since };
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

export interface TrackOptions {
  /** `write` says it changes data (label "Saving"). */
  write?: boolean | undefined;
  /** How to stop this request, given the reason. Only a read can be stopped from here; for a write it is ignored. */
  abort?: ((reason: string) => void) | undefined;
  route?: string | undefined;
  path?: string | undefined;
  /** An id the server can stop the run by. A stop sends it to the server too (see `runs` of `installBusyTracking`). */
  runId?: string | undefined;
}

/**
 * Counts `work` as busy until it settles, and returns it unchanged. Inside `quietly` it is not counted.
 */
export function trackBusy<T>(work: Promise<T>, options: TrackOptions = {}): Promise<T> {
  if (quietDepth > 0) return work;
  const entry: Entry = { write: !!options.write, started: Date.now(), abort: options.write ? undefined : options.abort, route: options.route, path: options.path, runId: options.runId };
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
  /**
   * Lets a counted read be stopped: the fetch carries a signal of its own (joined with the caller's), so
   * `cancelBusyReads()` (the Cancel button), `abortStaleReads(route)` (the route changed) and leaving the page can stop it.
   * A stopped read rejects with an AbortError whose message is CANCELLED_MESSAGE or LEFT_PAGE_MESSAGE. Writes are
   * never stopped. Default false: the request, its signal and its result are the caller's own.
   */
  cancel?: boolean | undefined;
  /** With `cancel`: paths a route change must not stop, for example shell calls that outlive the page that started them. */
  keepAcrossRoutes?: ((path: string) => boolean) | undefined;
  /**
   * Runs the server can stop on request. A matching request carries an id in `header` (default `X-Run-Id`), and every stop
   * of it also tells the server: a JSON POST of `{ ids }` to `cancelUrl` (a beacon, so it survives the page unloading),
   * because aborting the browser request alone does not reliably reach a server behind a front end that keeps
   * the connection open. Needs `cancel`.
   */
  runs?: { match: (url: URL, method: string) => boolean; cancelUrl: string; header?: string | undefined } | undefined;
}

let uninstall: (() => void) | null = null;
let sendCancel: (ids: string[]) => void = () => undefined;

function newRunId(): string | null {
  if (typeof crypto === 'undefined') return null;
  if (crypto.randomUUID) return crypto.randomUUID();
  const b = new Uint8Array(16);
  crypto.getRandomValues(b);
  return Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
}

function abortWhere(pick: (t: Entry) => boolean, reason: string): void {
  const ids: string[] = [];
  for (const t of [...live]) {
    if (t.write || !t.abort || !pick(t)) continue;
    if (t.runId) ids.push(t.runId);
    t.abort(reason);
  }
  if (ids.length) sendCancel(ids);
}

/** The person pressed Cancel: stop every read in flight that can be stopped. */
export function cancelBusyReads(): void {
  abortWhere(() => true, CANCELLED_MESSAGE);
}

/**
 * The route changed: stop reads still running that belong to the page that was left, once they have lasted
 * `graceMs` (quick shared calls are left alone).
 */
export function abortStaleReads(currentRoute: string, graceMs: number = NAV_GRACE_MS): void {
  const now = Date.now();
  abortWhere((t) => t.route !== undefined && t.route !== currentRoute && now - t.started >= graceMs && !keep(t.path ?? ''), LEFT_PAGE_MESSAGE);
}
let keep: (path: string) => boolean = () => false;

/**
 * Makes `window.fetch` report matching calls to the store. Opt in, once, at startup; it returns the function that
 * puts the original back. A second call while installed does nothing and returns the same function. Without
 * `cancel` it only observes: the request, its signal and its result are the caller's own.
 */
export function installBusyTracking(options: BusyTrackingOptions = {}): () => void {
  if (uninstall) return uninstall;
  if (!isBrowser) return () => undefined;
  const original = window.fetch;
  const readOnly = new Set(options.readOnlyPosts ?? []);
  const match = options.match ?? ((url: URL) => url.origin === window.location.origin && url.pathname.startsWith('/api/'));
  const cancel = !!options.cancel;
  const runs = cancel ? options.runs : undefined;
  keep = options.keepAcrossRoutes ?? (() => false);
  if (runs) {
    sendCancel = (ids) => {
      const body = JSON.stringify({ ids });
      try {
        if (navigator.sendBeacon?.(runs.cancelUrl, new Blob([body], { type: 'application/json' }))) return;
      } catch {
        // fall through to fetch
      }
      try {
        void original
          .call(window, runs.cancelUrl, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body, keepalive: true, credentials: 'same-origin' })
          .catch(() => undefined);
      } catch {
        // best effort: the browser side is already stopped
      }
    };
  }
  // Refresh, close and back or forward: stop every read now so the server stops working for a page that is gone.
  const onHide = () => abortWhere(() => true, LEFT_PAGE_MESSAGE);
  if (cancel) window.addEventListener('pagehide', onHide);
  window.fetch = function patched(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
    let url: URL | null = null;
    try {
      const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      url = new URL(raw, window.location.href);
    } catch {
      url = null;
    }
    const method = (init?.method ?? (typeof input === 'object' && 'method' in input ? input.method : 'GET')).toUpperCase();
    if (!url || !match(url, method) || quietDepth > 0) return original.call(window, input, init);
    const last = url.pathname.split('/').filter(Boolean).pop() ?? '';
    const write = method !== 'GET' && method !== 'HEAD' && !(method === 'POST' && readOnly.has(last));
    if (!cancel || write) return trackBusy(original.call(window, input, init), { write });
    const ctl = new AbortController();
    const theirs = init?.signal ?? (typeof input === 'object' && 'signal' in input ? input.signal : undefined);
    if (theirs) {
      if (theirs.aborted) ctl.abort(theirs.reason);
      else theirs.addEventListener('abort', () => ctl.abort(theirs.reason), { once: true });
    }
    let runId: string | undefined;
    let headers = init?.headers;
    if (runs && runs.match(url, method)) {
      runId = newRunId() ?? undefined;
      if (runId) {
        const h = new Headers(headers ?? (typeof input === 'object' && 'headers' in input ? input.headers : undefined));
        h.set(runs.header ?? 'X-Run-Id', runId);
        headers = h;
      }
    }
    return trackBusy(original.call(window, input, { ...init, ...(headers ? { headers } : {}), signal: ctl.signal }), {
      write: false,
      abort: (reason) => ctl.abort(new DOMException(reason, 'AbortError')),
      route: window.location.pathname,
      path: url.pathname,
      runId,
    });
  };
  const patched = window.fetch;
  uninstall = () => {
    if (window.fetch === patched) window.fetch = original;
    if (cancel) window.removeEventListener('pagehide', onHide);
    sendCancel = () => undefined;
    keep = () => false;
    uninstall = null;
  };
  return uninstall;
}
