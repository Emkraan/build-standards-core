/* The API client every console uses: bearer token from the shared auth, the same error contract
   the per-app copies had, one request for identical concurrent GETs, a small
   stale-while-revalidate cache with a per-key freshness window, and opt-in sessionStorage
   persistence for identity reads only. */

import type { Auth } from './auth';
import { createStore, isStale, staleError } from './cache';
import type { ResourceSnapshot, ResourceStore } from './cache';

export interface ApiError extends Error {
  status?: number | undefined;
  /** "invalid_path" when a path would leave the API base (the call never goes out). */
  code?: string | undefined;
  details?: unknown;
  /** The parsed error body, verbatim (for example a 409 naming the conflicting resource). */
  payload?: unknown;
}

export type QueryParams = Record<string, string | number | boolean | null | undefined>;

export interface RequestOptions extends Omit<RequestInit, 'body' | 'headers'> {
  headers?: Record<string, string> | undefined;
  /** Serialized as JSON. */
  body?: unknown;
  /** Token scope override for one call. */
  scope?: string | undefined;
  /**
   * 401 handling for this call. "throw" makes it a side read (polls, the feed): its token is
   * acquired silently only, interaction required and a 401 reject with status 401, and it never
   * starts a sign-in or a redirect. A "login" override cannot turn a "throw" client back into
   * an interactive one.
   */
  on401?: 'login' | 'throw' | undefined;
}

export interface GetOptions {
  /** Freshness window override for this call, in ms. */
  ttl?: number | undefined;
  /** Revalidate even when fresh. */
  force?: boolean | undefined;
}

export interface ApiDetails {
  error_message?: string;
  error_description?: string;
  message?: string;
  detail?: string;
  error?: string | { message?: string };
  errors?: Array<{ message?: string }>;
}

export interface CreateApiOptions {
  /** The API root including /api, for example https://gw/console/api. Empty string in dev (Vite proxy). */
  baseUrl: string;
  auth: Pick<Auth, 'acquireToken' | 'loginOn401' | 'accountId' | 'onAccountChange' | 'onLogout' | 'apiScope'>;
  /** Token scope for this API. Defaults to the auth's apiScope. */
  scope?: string | undefined;
  /** Storage namespace, one per app and API (for example "shell" or "example.console"). */
  namespace: string;
  /**
   * Paths whose answers may persist in sessionStorage so the shell paints at once and then
   * revalidates. Identity reads only (/me, my-permissions). Nothing else is ever persisted.
   */
  persist?: readonly string[] | undefined;
  /** Freshness windows in ms by path. A key ending in "*" matches a prefix. */
  ttl?: Readonly<Record<string, number>> | undefined;
  /** Window for GETs not named in ttl. Default 0: identical concurrent GETs share a request, nothing is reused after. */
  defaultTtl?: number | undefined;
  /** "throw" makes a 401 reject with status 401 instead of starting sign-in (for side reads such as the feed). */
  on401?: 'login' | 'throw' | undefined;
  /** How an upstream detail joins the message. Default "msg: detail". */
  joinDetail?: ((msg: string, detail: string) => string) | undefined;
  fetch?: typeof fetch | undefined;
  storage?: Storage | null | undefined;
}

export interface Api {
  readonly store: ResourceStore;
  readonly baseUrl: string;
  /** Any method, no caching. Identical concurrent GETs with no custom headers still share one request. */
  request<T = unknown>(path: string, options?: RequestOptions): Promise<T>;
  /** A cached GET: fresh data comes from the cache, else one shared request. */
  get<T = unknown>(path: string, options?: GetOptions): Promise<T>;
  /** The cached answer for a path without a request (persisted identity reads included). */
  peek<T = unknown>(path: string): ResourceSnapshot<T>;
  /** The freshness window that applies to a path. */
  ttlFor(path: string): number;
  invalidate(prefix?: string): void;
  /** Drop every cached and persisted answer. Runs on logout and on account change. */
  clear(): void;
  /** Load persisted identity reads now (also runs on the first get or peek). */
  hydrate(): void;
}

const PERSIST_VERSION = 'v1';

function defaultJoin(msg: string, detail: string): string {
  return `${msg}: ${detail}`;
}

/** Build the query string for a list call ("" when empty). Null and undefined values are dropped. */
export function qs(params: QueryParams = {}): string {
  const clean: Record<string, string> = {};
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined) continue;
    clean[k] = String(v);
  }
  const s = new URLSearchParams(clean).toString();
  return s ? `?${s}` : '';
}

function detailOf(d: unknown): string | null {
  if (d && typeof d === 'object') {
    const o = d as ApiDetails;
    const v =
      o.error_message ||
      o.error_description ||
      o.message ||
      o.detail ||
      (typeof o.error === 'string' ? o.error : o.error?.message) ||
      (Array.isArray(o.errors) && o.errors[0]?.message);
    return v ? String(v) : null;
  }
  if (typeof d === 'string' && d) return d;
  return null;
}

/** The top-level error field as text, whether the API sent a string or an { message } object. */
function errorText(e: unknown): string | null {
  if (typeof e === 'string') return e || null;
  if (e && typeof e === 'object') return detailOf(e);
  return null;
}

function unauthorized(): ApiError {
  const err: ApiError = new Error('Unauthorized');
  err.status = 401;
  return err;
}

function invalidPath(): ApiError {
  const err: ApiError = new Error('Refused to send a request outside the API base.');
  err.code = 'invalid_path';
  return err;
}

/**
 * A segment a server may read as "." or "..": the plain forms, dots with trailing spaces or
 * extra dots, a path parameter after them ("..;x", Tomcat and Jetty drop it) and Unicode dot
 * lookalikes that NFKC folds into dots
 * (fullwidth "\uff0e", one and two dot leaders "\u2024" "\u2025").
 */
function isDotSegment(segment: string): boolean {
  for (const form of [segment, segment.normalize('NFKC')]) {
    const bare = form.split(';')[0] ?? form;
    // Only dots and whitespace ("...", ".. "): Windows servers trim trailing dots and spaces.
    if (/^[.\s]+$/.test(bare) && bare.includes('.')) return true;
  }
  return false;
}

/**
 * The bearer token only ever goes to the configured API base. A path must be a plain
 * absolute path under it: no scheme, no protocol-relative "//host", no backslash, no control
 * characters, no "." or ".." segment (raw, percent-encoded, with a ";" parameter or as a
 * Unicode lookalike) and no percent-encoded separator, and the resolved URL must
 * keep the base's origin and stay under its path. Returns the URL to fetch.
 */
export function resolveApiUrl(baseUrl: string, path: string): string {
  if (typeof path !== 'string' || !path.startsWith('/') || path.startsWith('//')) throw invalidPath();
  if (/[\\\u0000-\u001f\u007f]/.test(path)) throw invalidPath();
  const pathname = path.split(/[?#]/)[0] ?? '';
  for (const seg of pathname.split('/')) {
    try {
      decodeURIComponent(seg);
    } catch {
      throw invalidPath();
    }
    // Decode until stable, so a proxy or server that decodes again ("%252e%252e") cannot turn
    // a segment into a dot segment or a separator.
    let decoded = seg;
    for (let i = 0; i < 8; i += 1) {
      const next = decoded.replace(/%([0-9a-f]{2})/gi, (_m, hex: string) => String.fromCharCode(parseInt(hex, 16)));
      if (next === decoded) break;
      decoded = next;
    }
    if (/%[0-9a-f]{2}/i.test(decoded)) throw invalidPath();
    // An encoded separator (%2f, %5c) or control character inside one segment: a proxy or
    // server that decodes before routing sees a different path than this check did.
    if (/[\\/\u0000-\u001f\u007f]/.test(decoded)) throw invalidPath();
    // The same segment decoded as UTF-8, so an encoded lookalike ("%EF%BC%8E") is folded too.
    let text = seg;
    for (let i = 0; i < 8; i += 1) {
      let next: string;
      try {
        next = decodeURIComponent(text);
      } catch {
        break;
      }
      if (next === text) break;
      text = next;
    }
    if (isDotSegment(decoded) || isDotSegment(text)) throw invalidPath();
    // A Unicode separator lookalike (fullwidth "\uff0f" or "\uff3c") folds into a real one.
    if (/[\\/]/.test(text.normalize('NFKC'))) throw invalidPath();
  }
  const url = `${baseUrl}${path}`;
  let here = 'http://localhost/';
  try {
    if (typeof location !== 'undefined' && location.href) here = location.href;
  } catch {
    /* no location (worker or test): the base must then be absolute to matter */
  }
  let base: URL;
  let target: URL;
  try {
    base = new URL(baseUrl || '/', here);
    target = new URL(url, here);
  } catch {
    throw invalidPath();
  }
  const root = base.pathname.replace(/\/$/, '');
  if (target.origin !== base.origin) throw invalidPath();
  if (root && target.pathname !== root && !target.pathname.startsWith(`${root}/`)) throw invalidPath();
  return url;
}

export function createApi(options: CreateApiOptions): Api {
  const { auth, namespace } = options;
  const baseUrl = options.baseUrl.replace(/\/$/, '');
  const doFetch = options.fetch ?? ((input: RequestInfo | URL, init?: RequestInit) => fetch(input, init));
  const join = options.joinDetail ?? defaultJoin;
  const persist = new Set(options.persist ?? []);
  const ttls = options.ttl ?? {};
  const defaultTtl = options.defaultTtl ?? 0;
  const clientOn401 = options.on401 ?? 'login';
  const apiScope = options.scope;
  /** The 401 mode of one call: a side read on the client or on the call wins. */
  function modeFor(opts: RequestOptions): 'login' | 'throw' {
    return clientOn401 === 'throw' || opts.on401 === 'throw' ? 'throw' : 'login';
  }
  const store = createStore();
  // Plain GETs in flight, by path. invalidate() marks a matching entry dropped and removes it, so
  // a caller that asks after the invalidation never shares a request started before it, and a
  // direct caller that was waiting on it is re-run against a request started after it.
  interface Shared {
    promise: Promise<unknown>;
    dropped: boolean;
    /** The request that replaced this one after an invalidation. */
    next: Shared | null;
  }
  const inflight = new Map<string, Shared>();
  const superseded = new Map<string, Shared>();
  // Bumped by clear() (logout, account change). A request started before the bump never hands
  // its answer to a caller, cached or direct, and its fetch is aborted.
  let generation = 0;
  const controllers = new Set<AbortController>();

  let storage: Storage | null = null;
  try {
    storage = options.storage === undefined ? window.sessionStorage : options.storage;
  } catch {
    storage = null;
  }
  const prefix = `${namespace}.api.${PERSIST_VERSION}:`;
  const ownerKey = `${namespace}.api.${PERSIST_VERSION}.account`;

  function ttlFor(path: string): number {
    const exact = ttls[path];
    if (typeof exact === 'number') return exact;
    let best = -1;
    let value = defaultTtl;
    for (const [k, v] of Object.entries(ttls)) {
      if (k.endsWith('*') && path.startsWith(k.slice(0, -1)) && k.length > best) {
        best = k.length;
        value = v;
      }
    }
    return value;
  }

  function wipeStorage(): void {
    if (!storage) return;
    try {
      const doomed: string[] = [];
      for (let i = 0; i < storage.length; i += 1) {
        const k = storage.key(i);
        if (k && (k.startsWith(prefix) || k === ownerKey)) doomed.push(k);
      }
      for (const k of doomed) storage.removeItem(k);
    } catch {
      /* storage unavailable */
    }
  }

  function clear(): void {
    generation += 1;
    for (const c of controllers) {
      try {
        c.abort(staleError());
      } catch {
        /* already aborted */
      }
    }
    controllers.clear();
    for (const s of inflight.values()) s.dropped = true;
    inflight.clear();
    superseded.clear();
    store.clear();
    wipeStorage();
  }

  // Hydrate persisted identity reads, but only for the account that wrote them. Lazy: the
  // client is usually created at module load, before auth.boot() knows the account, so this
  // runs on the first read (or an explicit hydrate()) and retries until an account is known.
  // Hydrated answers keep their data but count as stale, so the first read revalidates.
  let hydrated = persist.size === 0;
  function hydrate(): void {
    if (hydrated || !storage) return;
    try {
      const owner = auth.accountId();
      if (!owner) return;
      hydrated = true;
      // Only the account that wrote the answers may read them. A missing owner key (a partial
      // write or a quota failure) is treated like another account's.
      const stored = storage.getItem(ownerKey);
      if (stored !== owner) {
        wipeStorage();
        return;
      }
      for (const path of persist) {
        const raw = storage.getItem(prefix + path);
        if (!raw) continue;
        const parsed = JSON.parse(raw) as { at?: number; data?: unknown };
        if (typeof parsed.at === 'number' && parsed.data !== undefined && store.snapshot(path).data === undefined) {
          // Seeded without notifying, so a hydrate that runs during a render never updates
          // another component mid-render.
          store.seed(path, parsed.data);
        }
      }
    } catch {
      hydrated = true;
      wipeStorage();
    }
  }

  store.onData((key, data, at) => {
    if (!storage || !persist.has(key) || at === 0) return;
    const owner = auth.accountId();
    if (!owner) return;
    try {
      storage.setItem(ownerKey, owner);
      storage.setItem(prefix + key, JSON.stringify({ at, data }));
    } catch {
      /* quota or storage unavailable: persistence is an optimization only */
    }
  });

  auth.onAccountChange(() => clear());
  auth.onLogout(() => clear());

  async function send<T>(path: string, options: RequestOptions = {}): Promise<T> {
    // The session this call belongs to. Every await below is followed by a check, so a call
    // from before a logout or account change never sends, never starts a sign-in and never
    // hands back an answer or an error from the old session.
    const started = generation;
    const stale = () => started !== generation;
    const on401 = modeFor(options);
    // Validate before anything else: a path outside the API base never gets a token.
    const url = resolveApiUrl(baseUrl, path);
    // An empty override falls back to the client's scope, it never means "no token".
    const scope = options.scope || apiScope;
    // A token error rejects the call instead of sending it without a bearer token. null means
    // there is no scope or no account (dev bypass, signed out), and while an interactive
    // redirect runs the call waits for the navigation instead of fetching.
    // A side read (on401 'throw') never starts an interactive sign-in: a token that needs
    // interaction reads as a 401 for that call, so a background poll cannot redirect the page.
    let token: string | null;
    if (on401 === 'throw') {
      try {
        token = await auth.acquireToken(scope, { interactive: false });
      } catch (e) {
        if (stale()) throw staleError();
        if ((e as { interactionRequired?: unknown }).interactionRequired) {
          throw unauthorized();
        }
        throw e;
      }
    } else {
      try {
        token = await auth.acquireToken(scope);
      } catch (e) {
        if (stale()) throw staleError();
        throw e;
      }
    }
    // The session changed while the token was being acquired: nothing goes out, a write least
    // of all.
    if (stale()) throw staleError();
    // Signed out (no account, and not the dev bypass, which reports "dev") with a scope to ask
    // for: a protected call never goes out anonymously. It takes the 401 path instead.
    if (!token && (scope || auth.apiScope) && auth.accountId() === '') {
      if (on401 === 'throw') {
        throw unauthorized();
      }
      return auth.loginOn401();
    }
    const { headers: callerHeaders, body, scope: _scope, on401: _on401, signal: callerSignal, ...rest } = options;
    void _scope;
    void _on401;
    // A caller header can neither drop nor replace the bearer token.
    const extra: Record<string, string> = {};
    for (const [k, v] of Object.entries(callerHeaders ?? {})) {
      if (k.toLowerCase() !== 'authorization') extra[k] = v;
    }
    // clear() aborts the fetch. A caller's own signal still works.
    const controller = new AbortController();
    const onCallerAbort = () => controller.abort(callerSignal?.reason);
    if (callerSignal) {
      if (callerSignal.aborted) controller.abort(callerSignal.reason);
      else callerSignal.addEventListener('abort', onCallerAbort, { once: true });
    }
    controllers.add(controller);
    let res: Response;
    let text: string;
    try {
      try {
        res = await doFetch(url, {
          ...rest,
          signal: controller.signal,
          headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
            ...extra,
            // core-exception: this client package is the one place the bearer header is built
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: body !== undefined && body !== null ? JSON.stringify(body) : undefined,
        } as RequestInit);
      } catch (e) {
        if (stale()) throw staleError();
        throw e;
      }
      // Before any 401 or error handling: an old session's 401 must not start a sign-in for
      // the new one, and its error body must not reach a caller.
      if (stale()) throw staleError();

      if (res.status === 401) {
        if (on401 === 'throw') {
          throw unauthorized();
        }
        return auth.loginOn401();
      }

      try {
        text = await res.text();
      } catch (e) {
        if (stale()) throw staleError();
        throw e;
      }
    } finally {
      controllers.delete(controller);
      callerSignal?.removeEventListener('abort', onCallerAbort);
    }
    if (stale()) throw staleError();

    let data: { error?: unknown; details?: unknown } & Record<string, unknown>;
    let parsed = true;
    try {
      data = text ? JSON.parse(text) : {};
    } catch {
      parsed = false;
      data = { error: text || 'Empty response' };
    }
    if (data === null || typeof data !== 'object') data = { value: data } as typeof data;

    let top = errorText(data.error);
    // A 403 with an empty or non-JSON body is usually a platform or CORS block, not an RBAC
    // denial from our API. A JSON denial keeps its own reason.
    if (res.status === 403) {
      const reason = parsed ? top || detailOf(data) : null;
      if (!reason) {
        const err: ApiError = new Error('Forbidden: check API CORS (ALLOWED_ORIGIN) and that your role grants this action');
        err.status = 403;
        throw err;
      }
      if (data.error === undefined) data.error = reason;
      top = reason;
    }

    if (!res.ok) {
      let msg = top || `Request failed: ${res.status}`;
      const d = data.details;
      const detail = detailOf(d);
      if (detail && !String(msg).includes(detail)) msg = join(msg, detail);
      const err: ApiError = new Error(msg);
      err.status = res.status;
      err.details = d || null;
      err.payload = data;
      throw err;
    }
    return data as T;
  }

  /** One request for identical concurrent plain GETs. rerun: a caller still waiting when the
   *  path was invalidated gets the request started after the invalidation instead. */
  function shared<T>(path: string, rerun: boolean): Promise<T> {
    let entry = inflight.get(path);
    if (!entry) {
      const fresh: Shared = { promise: undefined as unknown as Promise<unknown>, dropped: false, next: null };
      fresh.promise = send<T>(path).finally(() => {
        if (inflight.get(path) === fresh) inflight.delete(path);
      });
      inflight.set(path, fresh);
      // The first request after an invalidation is the one its waiting callers move to.
      const prev = superseded.get(path);
      if (prev) {
        prev.next = fresh;
        superseded.delete(path);
      }
      entry = fresh;
    }
    if (!rerun) return entry.promise as Promise<T>;
    return follow<T>(path, entry, generation);
  }

  function follow<T>(path: string, e: Shared, gen: number): Promise<T> {
    const moveOn = (): Promise<T> | null => {
      if (gen !== generation) throw staleError();
      if (!e.dropped) return null;
      return e.next ? follow<T>(path, e.next, gen) : shared<T>(path, true);
    };
    return e.promise.then(
      (v) => moveOn() ?? (v as T),
      (err: unknown) => {
        if (isStale(err)) throw err;
        const again = moveOn();
        if (again) return again;
        throw err;
      },
    );
  }

  function request<T = unknown>(path: string, options: RequestOptions = {}): Promise<T> {
    const method = (options.method || 'GET').toUpperCase();
    // A side read on an interactive client gets its own request. Sharing would hand a side
    // read's 401 to an interactive caller (no sign-in) or an interactive caller's sign-in to the
    // side read.
    const mode = modeFor(options);
    if (mode !== clientOn401) return send<T>(path, { ...options, on401: mode });
    // Only a plain GET is shared: any other option (scope, headers, fetch settings) could change
    // the answer, so it gets its own request.
    const shareable = method === 'GET' && Object.keys(options).every((k) => k === 'method' || (k === 'on401' && options.on401 === clientOn401));
    if (!shareable) return send<T>(path, options);
    return shared<T>(path, true);
  }

  function invalidate(p?: string): void {
    for (const [k, entry] of inflight) {
      if (p === undefined || k === p || k.startsWith(p)) {
        entry.dropped = true;
        inflight.delete(k);
        superseded.set(k, entry);
      }
    }
    store.invalidate(p);
  }

  function get<T = unknown>(path: string, { ttl, force }: GetOptions = {}): Promise<T> {
    hydrate();
    // The store re-runs a waiting fetch itself after an invalidation, so it shares the raw request.
    return store.fetch<T>(path, () => shared<T>(path, false), { ttl: ttl ?? ttlFor(path), force });
  }

  return {
    store,
    baseUrl,
    request,
    get,
    peek: <T,>(path: string) => {
      hydrate();
      return store.snapshot<T>(path);
    },
    hydrate,
    ttlFor,
    invalidate,
    clear,
  };
}
