// shell-packages/app-server: shared server plumbing for the APIs behind a multi-module shell.
//
// Pure ESM with no runtime dependencies, so a deploy can vendor it into a server bundle and a
// CommonJS server can require() it on a current Node. Every vendor call is injected or read from
// an environment variable, so nothing here needs an SDK.
//
//   createGroupResolver  per-oid cache of a user's directory groups (TTL, LRU bound, single flight,
//                        failures never cached, optionally scoped to the groups the app references)
//   checkMemberGroups    batched directory checkMemberGroups for a referenced list
//   createTokenCache     cached, single-flight bearer token (platform managed identity)
//   corsOptions          the options object for the cors middleware, with preflight caching
//   originGuard          403 for a write, or a preflighted request, from an origin off the allowlist
//   serverTiming         Server-Timing header plus one structured log line per request
//   recordTiming / timed record named marks on the current request
//   whatsNewHandler      GET handler for a module's release notes, behind the module's own access check
//   gatewayGuard         accept a request only when it carries the gateway token the tier's API
//                        gateway adds, log only until enforcement is on

import { createPublicKey, verify as cryptoVerify } from "node:crypto";

// --- Group resolver ---

/**
 * @typedef {"hit" | "miss" | "shared" | "error" | "none"} GroupCacheStatus
 * hit     served from the cache
 * miss    this request made the Graph call
 * shared  joined a Graph call another request already had in flight
 * error   the Graph call (or the referenced group read) failed (fail closed,
 *         [] returned, nothing cached)
 * none    no oid, or no group is referenced, nothing looked up
 */

/**
 * Trimmed, lowercased, de-duplicated and sorted group object ids.
 * @param {unknown} ids
 * @returns {string[]}
 */
export function normalizeGroupIds(ids) {
  if (!Array.isArray(ids)) return [];
  const out = new Set();
  for (const id of ids) {
    const v = String(id ?? "").trim().toLowerCase();
    if (v) out.add(v);
  }
  return [...out].sort();
}

/**
 * Short, stable fingerprint of a normalized group id list (FNV-1a, two 32 bit
 * lanes). It is a cache key, not a security boundary: a cached answer is only
 * ever a subset of the ids it was asked about, and a hit is filtered by the
 * current list as well.
 * @param {string[]} ids
 * @returns {string}
 */
function fingerprintOf(ids) {
  const text = ids.join(",");
  let a = 0x811c9dc5;
  let b = 0x01000193 ^ text.length;
  for (let i = 0; i < text.length; i++) {
    const c = text.charCodeAt(i);
    a = Math.imul(a ^ c, 0x01000193) >>> 0;
    b = Math.imul(b ^ c, 0x5bd1e995) >>> 0;
  }
  return `${ids.length}:${a.toString(16)}${b.toString(16)}`;
}

/**
 * Per-oid cache of a user's group object ids.
 *
 * fetchGroups(oid) returns the user's group ids on success. Returning null or
 * undefined, or throwing, means the lookup FAILED: the caller gets [] (fail
 * closed, exactly like the uncached code) and nothing is cached, so the next
 * request retries. An empty array is a real answer and is cached.
 *
 * groupIds (optional) returns the group object ids the app's authorization
 * actually references (role assignments, configured access groups). With it,
 * fetchGroups(oid, ids) is asked only about those ids (checkMemberGroups below
 * does that in one or a few small Graph calls), the answer is limited to them,
 * and the cache entry is tied to a fingerprint of the list, so a new group
 * grant takes effect on the next request with no stale negative answer.
 * groupIds is read on every lookup (keep it cheap), one read shared by
 * concurrent lookups. A null, undefined or thrown answer falls back to the last
 * list read successfully for at most ttlMs (the list lives in the same
 * database, so it cannot change while that read fails), and past that fails
 * the lookup closed with nothing cached. An empty list returns [] with no
 * Graph call.
 *
 * @param {{
 *   fetchGroups: (oid: string, groupIds?: string[]) => Promise<string[] | null | undefined>,
 *   groupIds?: string[] | (() => Promise<string[] | null | undefined> | string[] | null | undefined),
 *   ttlMs?: number,
 *   maxEntries?: number,
 *   now?: () => number,
 *   onError?: (err: unknown, oid: string) => void,
 * }} options
 */
export function createGroupResolver(options) {
  const { fetchGroups, groupIds, ttlMs = 300000, maxEntries = 5000, now = Date.now, onError } = options || /** @type {any} */ ({});
  if (typeof fetchGroups !== "function") throw new TypeError("createGroupResolver: fetchGroups must be a function");
  if (groupIds !== undefined && typeof groupIds !== "function" && !Array.isArray(groupIds)) {
    throw new TypeError("createGroupResolver: groupIds must be a function or an array");
  }
  // A static list is read the same way as a provider.
  const readGroupIds = Array.isArray(groupIds) ? () => groupIds : groupIds;
  if (!(ttlMs > 0)) throw new TypeError("createGroupResolver: ttlMs must be positive");
  if (!(maxEntries >= 1)) throw new TypeError("createGroupResolver: maxEntries must be at least 1");

  /** @type {Map<string, { groups: string[], exp: number, scope: string }>} insertion order = LRU order */
  const cache = new Map();
  /** @type {Map<string, { gen: string, promise: Promise<string[] | null> }>} keyed by oid and scope */
  const inflight = new Map();
  // Bumped by invalidate()/clear() so a Graph call that started before the
  // invalidation never writes its (possibly stale) answer back.
  /** @type {Map<string, number>} */
  const generations = new Map();
  let epoch = 0;
  // The fingerprint of the last referenced list, reused while the list is unchanged.
  let lastIds = "";
  let lastScope = "";
  // One referenced-list read shared by concurrent lookups.
  /** @type {Promise<unknown> | null} */
  let listRead = null;

  /** @param {string} key */
  const genOf = (key) => `${epoch}:${generations.get(key) || 0}`;

  /** @param {string} key @param {string[]} groups @param {string} scope */
  function store(key, groups, scope) {
    cache.delete(key);
    cache.set(key, { groups, exp: now() + ttlMs, scope });
    while (cache.size > maxEntries) {
      const oldest = cache.keys().next().value;
      if (oldest === undefined) break;
      cache.delete(oldest);
    }
  }

  /** @param {unknown} oid @returns {string} */
  const keyOf = (oid) => String(oid || "").trim().toLowerCase();

  /** @param {unknown} err @param {string} key */
  function report(err, key) {
    if (!onError) return;
    try { onError(err, key); } catch { /* a logging hook never breaks auth */ }
  }

  /** @param {string} key */
  function drop(key) {
    cache.delete(key);
    generations.set(key, (generations.get(key) || 0) + 1);
    // The generation map only needs to outlive in-flight calls.
    if (generations.size > maxEntries * 2) {
      generations.clear();
      epoch++;
    }
  }

  /**
   * The referenced ids and their fingerprint, null when the read failed, or
   * undefined when no groupIds option was given.
   * @param {string} key
   * @returns {Promise<{ ids: string[], scope: string } | null | undefined>}
   */
  async function scopeFor(key) {
    if (!readGroupIds) return undefined;
    const provider = readGroupIds;
    let raw;
    try {
      if (!listRead) {
        const p = (async () => provider())();
        listRead = p;
        p.then(() => { if (listRead === p) listRead = null; }, () => { if (listRead === p) listRead = null; });
      }
      raw = await listRead;
    } catch (err) {
      report(err, key);
      raw = null;
    }
    /** @type {string[]} */
    let ids;
    // A failed list read fails closed (no group access) and is never replaced
    // by an older list: a grant removed meanwhile, possibly on another
    // instance, must not keep granting.
    if (Array.isArray(raw)) {
      ids = normalizeGroupIds(raw);
    } else {
      return null;
    }
    const text = ids.join(",");
    if (text !== lastIds || !lastScope) {
      lastIds = text;
      lastScope = fingerprintOf(ids);
    }
    return { ids, scope: lastScope };
  }

  /**
   * fresh: skip the cached entry and read Graph now (the answer refreshes the
   * cache). Use it where a stale grant matters most, for example on
   * state-changing requests.
   * @param {unknown} oid
   * @param {{ fresh?: boolean }} [opts]
   * @returns {Promise<{ groups: string[], cache: GroupCacheStatus }>}
   */
  async function lookup(oid, opts) {
    const key = keyOf(oid);
    if (!key) return { groups: [], cache: "none" };
    if (opts && opts.fresh) drop(key);
    // Taken before any await, so an invalidate() or clear() at any point during
    // this lookup (the referenced group read included) keeps its answer out of
    // the cache.
    const gen = genOf(key);

    const scoped = await scopeFor(key);
    if (scoped === null) return { groups: [], cache: "error" };
    if (scoped && scoped.ids.length === 0) {
      cache.delete(key);
      return { groups: [], cache: "none" };
    }
    const scope = scoped ? scoped.scope : "";
    const allowed = scoped ? new Set(scoped.ids) : null;

    const hit = cache.get(key);
    if (hit) {
      if (hit.exp > now() && hit.scope === scope) {
        // Refresh LRU position.
        cache.delete(key);
        cache.set(key, hit);
        return { groups: allowed ? hit.groups.filter((g) => allowed.has(g)) : [...hit.groups], cache: "hit" };
      }
      // Expired, or the referenced groups changed since it was read.
      cache.delete(key);
    }

    const flightKey = `${key}|${scope}`;
    const running = inflight.get(flightKey);
    if (running && running.gen === gen) {
      const groups = await running.promise;
      return groups ? { groups: [...groups], cache: "shared" } : { groups: [], cache: "error" };
    }

    const promise = (async () => {
      try {
        const out = await (scoped ? fetchGroups(key, [...scoped.ids]) : fetchGroups(key));
        if (!Array.isArray(out)) return null;
        // A scoped answer never carries a group the app did not ask about.
        if (allowed) return normalizeGroupIds(out).filter((g) => allowed.has(g));
        return out.map((g) => String(g).toLowerCase()).filter(Boolean);
      } catch (err) {
        report(err, key);
        return null;
      }
    })();
    const entry = { gen, promise };
    inflight.set(flightKey, entry);
    let groups;
    try {
      groups = await promise;
    } finally {
      if (inflight.get(flightKey) === entry) inflight.delete(flightKey);
    }
    if (!groups) return { groups: [], cache: "error" };
    if (genOf(key) === gen) store(key, groups, scope);
    return { groups: [...groups], cache: "miss" };
  }

  return {
    lookup,
    /** @param {unknown} oid @param {{ fresh?: boolean }} [opts] @returns {Promise<string[]>} */
    async resolve(oid, opts) {
      return (await lookup(oid, opts)).groups;
    },
    /** Drop one user's cached groups (call after changing their membership). @param {unknown} oid */
    invalidate(oid) {
      const key = keyOf(oid);
      if (key) drop(key);
    },
    /** Drop every cached entry. */
    clear() {
      cache.clear();
      inflight.clear();
      generations.clear();
      listRead = null;
      epoch++;
    },
    /** Number of cached users (for health and tests). */
    get size() {
      return cache.size;
    },
  };
}

// A directory object id. Anything else can never name a group, and Graph rejects
// the whole checkMemberGroups call when one id is malformed.
const OBJECT_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/**
 * Which of groupIds the directory object oid is a member of (transitively),
 * through Graph POST /directoryObjects/{oid}/checkMemberGroups. Graph takes at
 * most 20 ids per call, so a longer list is split into batches, at most
 * `concurrency` in flight at once. The cost no longer grows with how many
 * groups the person is in, only with how many groups the app references.
 *
 * An id that is not an object id (a stray display name or typo in the app's
 * data) is skipped with a log line, and a batch Graph rejects with 400 is
 * asked again one id at a time (a rejected id counts as not a member), so one
 * bad row can never fail every lookup. A 429 (throttled) batch is retried once
 * after Retry-After (at most 2 seconds).
 *
 * Returns the matching ids (lowercase, sorted, never an id that was not asked
 * about), [] when no valid id is left (no Graph call), or null when the lookup
 * FAILED: no oid, no token, a non-2xx answer or a network error in ANY batch.
 * Never throws. A 401 in any batch calls onUnauthorized so the app can drop its
 * cached token.
 *
 * @param {{
 *   oid: string,
 *   groupIds: string[],
 *   getToken: () => Promise<string | null | undefined>,
 *   fetch?: (url: string, init: any) => Promise<{ ok: boolean, status: number, json: () => Promise<any>, headers?: any }>,
 *   onUnauthorized?: () => void,
 *   timeoutMs?: number,
 *   batchSize?: number,
 *   concurrency?: number,
 *   log?: (message: string) => void,
 * }} options
 * @returns {Promise<string[] | null>}
 */
export async function checkMemberGroups(options) {
  const {
    oid, groupIds, getToken, onUnauthorized,
    fetch: doFetch = globalThis.fetch,
    timeoutMs = 10000,
    batchSize = 20,
    concurrency = 4,
    log = (/** @type {string} */ m) => console.log(m),
  } = options || /** @type {any} */ ({});
  const key = String(oid || "").trim();
  if (!key) return null;
  const all = normalizeGroupIds(groupIds);
  const ids = all.filter((id) => OBJECT_ID.test(id));
  if (ids.length < all.length) log(`[graph] checkMemberGroups skipped ${all.length - ids.length} id(s) that are not object ids`);
  if (!ids.length) return [];
  const size = Math.max(1, Math.min(20, Math.floor(batchSize) || 20));
  const lanes = Math.max(1, Math.floor(concurrency) || 1);
  try {
    const token = await getToken();
    if (!token) {
      log("[graph] no token, cannot check group membership");
      return null;
    }
    /** @type {string[][]} */
    const batches = [];
    for (let i = 0; i < ids.length; i += size) batches.push(ids.slice(i, i + size));
    const url = `https://graph.microsoft.com/v1.0/directoryObjects/${encodeURIComponent(key)}/checkMemberGroups`;
    let unauthorized = false;
    let failed = false;
    // Ids Graph rejected one at a time. When it rejects every id, the call
    // itself is broken (not the data), so the lookup fails instead of reading
    // as "member of nothing" and being cached.
    let rejected = 0;
    /** @type {unknown[]} */
    const member = [];

    /** @param {string[]} batch @returns {Promise<unknown[]>} */
    async function ask(batch) {
      for (let attempt = 0; ; attempt++) {
        const res = await doFetch(url, {
          method: "POST",
          // core-exception: the directory call is made with the server's own token, not a caller's
          headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
          body: JSON.stringify({ groupIds: batch }),
          signal: AbortSignal.timeout(timeoutMs),
          // node-fetch 2 also honours its own timeout option (the global fetch ignores it).
          timeout: timeoutMs,
        });
        if (res.status === 400) {
          // Graph rejects the whole call for one id it will not accept (for
          // example a deleted or malformed object). Ask about each id on its
          // own, so only the rejected ids count as "not a member" and the
          // rest still answer. Any other failure still fails the lookup.
          if (batch.length === 1) {
            log(`[graph] checkMemberGroups rejected ${batch[0]}, counted as not a member`);
            rejected += 1;
            return [];
          }
          /** @type {unknown[]} */
          const out = [];
          for (const id of batch) out.push(...(await ask([id])));
          return out;
        }
        if (res.status === 429 && attempt === 0) {
          const after = Number(res.headers && typeof res.headers.get === "function" ? res.headers.get("retry-after") : NaN);
          await new Promise((r) => setTimeout(r, Number.isFinite(after) && after > 0 ? Math.min(after * 1000, 2000) : 500));
          continue;
        }
        if (!res.ok) {
          if (res.status === 401) unauthorized = true;
          throw new Error(`checkMemberGroups failed: ${res.status}`);
        }
        const data = /** @type {{ value?: unknown[] }} */ (await res.json());
        return Array.isArray(data?.value) ? data.value : [];
      }
    }

    // A fixed number of lanes pull batches in order. Every batch runs to the
    // end (allSettled semantics), so a 401 is always seen even when another
    // batch failed first.
    let next = 0;
    async function lane() {
      while (next < batches.length) {
        const batch = /** @type {string[]} */ (batches[next++]);
        try {
          member.push(...(await ask(batch)));
        } catch (err) {
          if (!failed) log(`[graph] ${/** @type {Error} */ (err)?.message || "checkMemberGroups failed"}`);
          failed = true;
        }
      }
    }
    await Promise.all(Array.from({ length: Math.min(lanes, batches.length) }, lane));
    if (unauthorized && onUnauthorized) {
      try { onUnauthorized(); } catch { /* never breaks the lookup */ }
    }
    if (failed) return null;
    if (rejected > 0 && rejected === ids.length) {
      log("[graph] checkMemberGroups rejected every id, lookup failed");
      return null;
    }
    const asked = new Set(ids);
    return normalizeGroupIds(member).filter((g) => asked.has(g));
  } catch (err) {
    log(`[graph] checkMemberGroups error: ${/** @type {Error} */ (err)?.message || err}`);
    return null;
  }
}

// --- Token cache ---

/**
 * Parse an expires_on value the way a platform managed identity returns it
 * (unix seconds, possibly as a string) or a date string. Unparseable values get
 * a conservative 55 minute lifetime.
 * @param {unknown} raw
 * @param {() => number} [now]
 * @returns {number} epoch ms
 */
export function parseExpiresOn(raw, now = Date.now) {
  const n = Number(raw);
  if (Number.isFinite(n) && n > 1_000_000_000) return n * 1000;
  if (typeof raw === "string") {
    const d = Date.parse(raw);
    if (Number.isFinite(d)) return d;
  }
  return now() + 55 * 60 * 1000;
}

/**
 * Cached, single-flight bearer token. fetchToken returns { token, expiresAt }
 * (epoch ms) or null. A null or a throw is not cached, so the next call retries.
 * The token is refreshed refreshSkewMs before it expires.
 *
 * @param {{
 *   fetchToken: () => Promise<{ token: string, expiresAt: number } | null | undefined>,
 *   refreshSkewMs?: number,
 *   now?: () => number,
 * }} options
 */
export function createTokenCache(options) {
  const { fetchToken, refreshSkewMs = 5 * 60 * 1000, now = Date.now } = options || /** @type {any} */ ({});
  if (typeof fetchToken !== "function") throw new TypeError("createTokenCache: fetchToken must be a function");
  /** @type {{ token: string, expiresAt: number } | null} */
  let current = null;
  /** @type {Promise<string | null> | null} */
  let pending = null;
  // Bumped by clear() so a fetch that started before the clear never writes
  // its token back into the cache.
  let gen = 0;

  return {
    /** @returns {Promise<string | null>} */
    get() {
      if (current && current.expiresAt - refreshSkewMs > now()) return Promise.resolve(current.token);
      if (pending) return pending;
      // Promise.resolve().then() runs fetchToken on a later tick, so even a
      // synchronous throw becomes a rejection of THIS promise, and the cleanup
      // below only clears the slot it owns. A failure is never left cached.
      const myGen = gen;
      const p = Promise.resolve()
        .then(() => fetchToken())
        .then((out) => {
          if (!out || !out.token) return null;
          if (myGen === gen) current = { token: out.token, expiresAt: Number(out.expiresAt) || now() + 55 * 60 * 1000 };
          return out.token;
        })
        .finally(() => {
          if (pending === p) pending = null;
        });
      pending = p;
      return p;
    },
    /** Drop the cached token (for example after the target answered 401). */
    clear() {
      current = null;
      pending = null;
      gen++;
    },
  };
}

// --- CORS ---

/**
 * Options for the cors middleware. The allowlist is exact match, a request
 * with no Origin header (same origin, curl, server to server) is allowed, and
 * credentials stay off (auth is a bearer token, never a cookie).
 *
 * reject picks what a disallowed browser Origin gets, so each app keeps its
 * current behaviour:
 *   "omit"  cb(null, false): the request proceeds with no CORS headers
 *   "error" cb(new Error("Origin <o> not allowed by CORS")): the error handler answers
 *
 * maxAge (seconds) lets the browser cache a preflight, so a bearer-token JSON
 * call does not pay an OPTIONS round trip every time. Chromium caps it at 7200.
 *
 * @param {{
 *   allowedOrigins: string[],
 *   reject?: "omit" | "error",
 *   methods?: string[],
 *   allowedHeaders?: string[],
 *   exposedHeaders?: string[],
 *   maxAge?: number,
 * }} options
 */
export function corsOptions(options) {
  const {
    allowedOrigins,
    reject = "omit",
    methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allowedHeaders = ["Content-Type", "X-Requested-With", "Authorization"],
    exposedHeaders,
    maxAge = 7200,
  } = options || /** @type {any} */ ({});
  if (!Array.isArray(allowedOrigins)) throw new TypeError("corsOptions: allowedOrigins must be an array");
  if (reject !== "omit" && reject !== "error") throw new TypeError('corsOptions: reject must be "omit" or "error"');
  const allowed = new Set(allowedOrigins);

  /** @type {{ origin: (origin: string | undefined, cb: (err: Error | null, allow?: boolean) => void) => void, credentials: false, methods: string[], allowedHeaders: string[], exposedHeaders?: string[], maxAge: number }} */
  const out = {
    origin(origin, cb) {
      if (!origin || allowed.has(origin)) return cb(null, true);
      if (reject === "error") return cb(new Error(`Origin ${origin} not allowed by CORS`));
      return cb(null, false);
    },
    credentials: false,
    methods: [...methods],
    allowedHeaders: [...allowedHeaders],
    maxAge,
  };
  if (exposedHeaders) out.exposedHeaders = [...exposedHeaders];
  return out;
}

const SIMPLE_METHODS = new Set(["GET", "HEAD", "POST"]);
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
const SIMPLE_CONTENT_TYPES = new Set(["application/x-www-form-urlencoded", "multipart/form-data", "text/plain"]);

/**
 * Server-side Origin check. CORS only decides whether the browser may READ a
 * response. A browser sends a preflight before any request that is not
 * CORS-simple (a method other than GET, HEAD or POST, an Authorization or
 * custom header, or a JSON body), and with Access-Control-Max-Age it reuses an
 * allowed preflight for up to maxAge. Without this guard, an origin removed
 * from the allowlist could keep sending those requests until the cached
 * preflight expired, and with reject "omit" the route would still run.
 *
 * The guard answers 403, before any route runs, to a request whose Origin is
 * present and not on the allowlist when it is either state-changing (POST,
 * PUT, PATCH, DELETE, including a CORS-simple form POST) or a request a
 * browser would have preflighted (for example a GET with a bearer token).
 * Requests with no Origin (agents, curl, server to server), a CORS-simple GET
 * or HEAD, and the OPTIONS preflight itself pass.
 *
 * preflightHeaders: the app's custom request headers that force a preflight
 * (usually the CORS allowedHeaders list). Authorization is always included.
 * Content-Type is judged by value (JSON forces a preflight, a form does not).
 *
 * @param {{ allowedOrigins: string[], preflightHeaders?: string[] }} options
 */
export function originGuard(options) {
  const { allowedOrigins, preflightHeaders = [] } = options || /** @type {any} */ ({});
  if (!Array.isArray(allowedOrigins)) throw new TypeError("originGuard: allowedOrigins must be an array");
  // Browsers send a lowercase origin with no trailing slash. Normalise the
  // configured entries the same way so a cosmetic difference in ALLOWED_ORIGIN
  // never blocks a real caller.
  /** @param {unknown} o */
  const norm = (o) => String(o || "").trim().toLowerCase().replace(/\/+$/, "");
  const allowed = new Set(allowedOrigins.map(norm).filter(Boolean));
  const custom = [...new Set(["authorization", ...preflightHeaders.map((h) => String(h).toLowerCase())])]
    .filter((h) => h && h !== "content-type");

  /** @param {any} req */
  function mustBlock(req) {
    const method = String(req.method || "").toUpperCase();
    if (method === "OPTIONS") return false;
    if (!SAFE_METHODS.has(method)) return true;
    if (!SIMPLE_METHODS.has(method)) return true;
    const h = req.headers || {};
    if (custom.some((name) => h[name] !== undefined)) return true;
    const ct = h["content-type"];
    if (ct !== undefined) {
      const base = (String(ct).split(";")[0] || "").trim().toLowerCase();
      if (!SIMPLE_CONTENT_TYPES.has(base)) return true;
    }
    return false;
  }

  /**
   * @param {any} req
   * @param {any} res
   * @param {(err?: unknown) => void} next
   */
  return function originGuardMiddleware(req, res, next) {
    const origin = req.headers && req.headers.origin;
    if (!origin || allowed.has(norm(origin)) || !mustBlock(req)) return next();
    res.statusCode = 403;
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    res.end(JSON.stringify({ error: "Origin not allowed" }));
  };
}

// --- Server-Timing ---

const TOKEN_RE = /^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$/;
const TIMING_KEY = Symbol.for("shell.app-server.timing");

/**
 * @typedef {{ name: string, dur: number, desc?: string }} TimingMark
 * @typedef {{ start: number, marks: TimingMark[] }} RequestTiming
 */

/** @param {any} req @returns {RequestTiming | undefined} */
function timingOf(req) {
  return req ? req[TIMING_KEY] : undefined;
}

/**
 * Record a named mark on the current request. Repeated names add up (two RBAC
 * checks in one request report their total). A no-op when serverTiming() is
 * not mounted, so library code can call it unconditionally.
 * @param {any} req
 * @param {string} name   a header token, for example "jwt", "groups", "rbac"
 * @param {number} durMs
 * @param {string} [desc] short label, for example "hit" or "miss"
 */
export function recordTiming(req, name, durMs, desc) {
  const t = timingOf(req);
  if (!t || !TOKEN_RE.test(name)) return;
  const dur = Number.isFinite(durMs) && durMs > 0 ? durMs : 0;
  const existing = t.marks.find((m) => m.name === name);
  if (existing) {
    existing.dur += dur;
    if (desc) existing.desc = desc;
  } else {
    t.marks.push(desc ? { name, dur, desc } : { name, dur });
  }
}

/**
 * Time an async step and record it as a mark.
 * @template T
 * @param {any} req
 * @param {string} name
 * @param {() => Promise<T> | T} fn
 * @returns {Promise<T>}
 */
export async function timed(req, name, fn) {
  const t0 = performance.now();
  try {
    return await fn();
  } finally {
    recordTiming(req, name, performance.now() - t0);
  }
}

/** @param {number} n */
const fmt = (n) => (Math.round(n * 10) / 10).toString();

/**
 * Build a Server-Timing header value.
 * @param {TimingMark[]} marks
 * @param {number} totalMs
 */
export function formatServerTiming(marks, totalMs) {
  const parts = marks.map((m) => {
    let s = `${m.name};dur=${fmt(m.dur)}`;
    if (m.desc) s += `;desc="${String(m.desc).replace(/["\\\r\n]/g, "")}"`;
    return s;
  });
  parts.push(`total;dur=${fmt(totalMs)}`);
  return parts.join(", ");
}

// --- Route names from route definitions ---
//
// A request is named only from the templates the app DECLARED (the path given
// to app.use / router.use for every router on the way, and the matched route's
// own path), never from req.baseUrl, req.path or any other request value. The
// router tree is walked once per app (again only when a route shows up that the
// last walk did not see). At the end of a request the matched route object is
// looked up in that table, and its mount chain is checked against the request
// path with the same layer regexps Express matched, so a router mounted at two
// places gets the right prefix. Anything that cannot be resolved this way (no
// route matched, a 404, a sub-app, a regexp or array path, a mount the parser
// does not recognise, two candidates) is named "-". Supports Express 4 (the
// version the shell APIs run), any other router shape resolves to "-".

const MAX_DECLARED_ROUTES = 5000;
const MAX_MOUNT_DEPTH = 16;
/** Every template resolved from a route definition. The telemetry sink sends only these. */
const declaredRoutes = new Set();
/** @type {WeakMap<object, { byRoute: Map<any, RouteEntry[]>, missed: WeakSet<object> }>} */
const routeTables = new WeakMap();
// The tail path-to-regexp 0.1 adds to a non-ending (mount) path: "\/?(?=\/|$)",
// or "(?=\/|$)" for a strict router.
const MOUNT_TAIL_RE = /(?:\\\/\?)?\(\?=\\\/\|\$\)$/;
const PARAM_TOKEN = "(?:\\/([^/]+?))";
const LITERAL_CHAR_RE = /^[A-Za-z0-9_~-]$/;

/**
 * @typedef {{ template: string | null, chain: any[], layer: any }} RouteEntry
 * @typedef {RegExp & { fast_slash?: boolean, fast_star?: boolean }} LayerRegExp
 */

/**
 * The compiled regexp of an Express 4 layer, or null.
 * @param {any} layer
 * @returns {LayerRegExp | null}
 */
function layerRegExp(layer) {
  const re = layer && layer.regexp;
  return re instanceof RegExp ? /** @type {LayerRegExp} */ (re) : null;
}

/**
 * The declared path of a mount layer (app.use("/api/devices/:id", router)),
 * rebuilt from the layer's compiled regexp and proven by compiling the
 * candidate again with the router's own Layer class: the candidate is used only
 * when it compiles to the identical regexp and keys. "" for a root mount, null
 * when it cannot be proven.
 * @param {any} layer
 * @returns {string | null}
 */
export function mountTemplateOf(layer) {
  try {
    const re = layerRegExp(layer);
    if (!re) return null;
    if (re.fast_slash) return "";
    if (re.fast_star) return null;
    const src = re.source;
    if (!src.startsWith("^") || !MOUNT_TAIL_RE.test(src)) return null;
    const body = src.slice(1).replace(MOUNT_TAIL_RE, "");
    const keys = Array.isArray(layer.keys) ? layer.keys : [];
    let out = "";
    let k = 0;
    for (let i = 0; i < body.length;) {
      if (body.startsWith(PARAM_TOKEN, i)) {
        const key = keys[k++];
        if (!key || typeof key.name !== "string" || !/^[A-Za-z_]\w*$/.test(key.name)) return null;
        i += PARAM_TOKEN.length;
        const optional = body[i] === "?";
        if (optional) i++;
        out += `/:${key.name}${optional ? "?" : ""}`;
      } else if (body[i] === "\\" && (body[i + 1] === "/" || body[i + 1] === ".")) {
        out += body[i + 1];
        i += 2;
      } else if (LITERAL_CHAR_RE.test(body[i] || "")) {
        out += body[i];
        i++;
      } else {
        return null;
      }
    }
    if (k !== keys.length || !out.startsWith("/")) return null;
    const Layer = layer.constructor;
    if (typeof Layer !== "function") return null;
    const sensitive = !re.flags.includes("i");
    for (const strict of [false, true]) {
      const probe = new Layer(out, { sensitive, strict, end: false }, function probe() {});
      const pre = layerRegExp(probe);
      if (pre && pre.source === src && pre.flags === re.flags
        && JSON.stringify((probe.keys || []).map((/** @type {any} */ x) => [x.name, !!x.optional])) === JSON.stringify(keys.map((/** @type {any} */ x) => [x.name, !!x.optional]))) {
        return out;
      }
    }
    return null;
  } catch {
    return null;
  }
}

/** @param {string} prefix @param {string} path */
function joinTemplate(prefix, path) {
  if (path === "/" && prefix) return prefix;
  return `${prefix}${path}`;
}

/**
 * Walk the app's router tree and index every route by its Route object.
 * @param {any} app
 * @returns {Map<any, RouteEntry[]>}
 */
function buildRouteTable(app) {
  /** @type {Map<any, RouteEntry[]>} */
  const byRoute = new Map();
  const router = app && (app._router || app.router);
  if (!router || !Array.isArray(router.stack)) return byRoute;
  /**
   * @param {any[]} stack
   * @param {string | null} prefix null once a mount on the way is not provable
   * @param {any[]} chain
   * @param {Set<any>} seen
   */
  const walk = (stack, prefix, chain, seen) => {
    if (chain.length > MAX_MOUNT_DEPTH) return;
    for (const layer of stack) {
      if (!layer) continue;
      if (layer.route) {
        const p = layer.route.path;
        const template = prefix !== null && typeof p === "string" && p.startsWith("/") ? joinTemplate(prefix, p) : null;
        if (template && declaredRoutes.size < MAX_DECLARED_ROUTES) declaredRoutes.add(template);
        const list = byRoute.get(layer.route) || [];
        list.push({ template, chain, layer });
        byRoute.set(layer.route, list);
        continue;
      }
      const h = layer.handle;
      if (typeof h === "function" && Array.isArray(h.stack) && !seen.has(h)) {
        const mount = prefix === null ? null : mountTemplateOf(layer);
        walk(h.stack, mount === null ? null : prefix + mount, [...chain, layer], new Set([...seen, h]));
      }
    }
  };
  walk(router.stack, "", [], new Set([router]));
  return byRoute;
}

/**
 * True when the request path goes through this entry's mount chain and route
 * layer, matched the way Express 4 matched it.
 * @param {RouteEntry} entry
 * @param {string} pathname
 */
function chainMatches(entry, pathname) {
  let path = pathname || "/";
  for (const layer of entry.chain) {
    const re = layerRegExp(layer);
    if (!re) return false;
    let matched = "";
    if (!re.fast_slash) {
      const m = re.exec(path);
      if (!m) return false;
      matched = m[0];
    }
    const c = path[matched.length];
    if (c && c !== "/" && c !== ".") return false;
    path = path.slice(matched.length);
    if (path[0] !== "/") path = `/${path}`;
  }
  const re = layerRegExp(entry.layer);
  return !!re && (!!re.fast_slash || re.test(path));
}

/**
 * The declared route template that handled the request, or "-".
 * @param {any} app the app serverTiming is mounted on
 * @param {any} route the Route object Express matched
 * @param {string} pathname the request path (only tested against the declared regexps)
 */
function declaredRouteOf(app, route, pathname) {
  if (!app || (typeof app !== "object" && typeof app !== "function") || !route || typeof route !== "object") return "-";
  let table = routeTables.get(app);
  if (!table || (!table.byRoute.has(route) && !table.missed.has(route))) {
    // First request, or a route registered after the last walk.
    table = { byRoute: buildRouteTable(app), missed: table ? table.missed : new WeakSet() };
    routeTables.set(app, table);
    if (!table.byRoute.has(route)) table.missed.add(route);
  }
  const entries = table.byRoute.get(route);
  if (!entries) return "-";
  const names = new Set();
  for (const e of entries) if (chainMatches(e, pathname)) names.add(e.template);
  if (names.size !== 1) return "-";
  const [name] = names;
  return typeof name === "string" && name ? name : "-";
}

/**
 * True when the route was resolved from a route definition by serverTiming.
 * The telemetry sink sends any other route as "-".
 * @param {string} route
 */
export function isDeclaredRoute(route) {
  return typeof route === "string" && declaredRoutes.has(route);
}

/**
 * Express middleware. Adds a Server-Timing header (named marks plus total) to
 * every response and writes one JSON log line when it finishes:
 *   {"msg":"request","method":"GET","route":"/api/admin/my-permissions","status":200,"ms":41.2,"timings":{"jwt":3.1,"groups":0.1,"rbac":30.5},"desc":{"groups":"hit"}}
 * No URL, query string, header, token or identity is logged.
 *
 * timingAllowOrigins: browser origins that may read the timings. The
 * Server-Timing header is sent only when the request Origin is on this list
 * (or headerForAll is true), with Timing-Allow-Origin echoing that origin. A
 * cross-origin page sees Server-Timing and the resource timing breakdown only
 * with Timing-Allow-Origin. Other callers (curl, scripts, unknown origins) get
 * no timing header. The log line is written for every request either way.
 *
 * @param {{
 *   timingAllowOrigins?: string[],
 *   headerForAll?: boolean,
 *   log?: ((line: string) => void) | null,
 *   sink?: ((record: RequestLogRecord) => void) | null,
 *   skip?: (req: any) => boolean,
 * }} [options]
 */
export function serverTiming(options = {}) {
  const { timingAllowOrigins = [], headerForAll = false, log = (line) => console.log(line), sink = null, skip } = options;
  const tao = new Set(timingAllowOrigins);

  /**
   * @param {any} req
   * @param {any} res
   * @param {(err?: unknown) => void} next
   */
  return function serverTimingMiddleware(req, res, next) {
    /** @type {RequestTiming} */
    const timing = { start: performance.now(), marks: [] };
    req[TIMING_KEY] = timing;
    let headerMs = 0;
    // The app this middleware is mounted on (a sub-app swaps req.app while it
    // runs, so read it now).
    const app = req.app;

    // Keep the last Route object Express matched. Express clears req.route when
    // it leaves a router, and an error handler or the finish event runs after
    // that. Only the Route object is kept, its name comes from the definitions.
    /** @type {any} */
    let matched = req.route;
    try {
      Object.defineProperty(req, "route", {
        configurable: true,
        enumerable: true,
        get() { return matched; },
        set(v) { if (v) matched = v; },
      });
    } catch { /* fall back to reading req.route at finish */ }

    const origWriteHead = res.writeHead;
    res.writeHead = function patchedWriteHead(/** @type {any[]} */ ...args) {
      try {
        headerMs = performance.now() - timing.start;
        const origin = req.headers && req.headers.origin;
        const allowedOrigin = !!origin && tao.has(origin);
        if (!res.headersSent && (allowedOrigin || headerForAll)) {
          res.setHeader("Server-Timing", formatServerTiming(timing.marks, headerMs));
          if (allowedOrigin) res.setHeader("Timing-Allow-Origin", origin);
        }
        if (!res.headersSent && tao.size) {
          // The header depends on the Origin, so caches must key on it.
          const vary = String(res.getHeader("Vary") || "");
          if (!/(^|,)\s*origin\s*(,|$)/i.test(vary)) res.setHeader("Vary", vary ? `${vary}, Origin` : "Origin");
        }
      } catch { /* timing never breaks a response */ }
      return origWriteHead.apply(this, args);
    };

    let done = false;
    const finish = (/** @type {boolean} */ aborted) => {
      if (done) return;
      done = true;
      try {
        if (skip && skip(req)) return;
        /** @type {Record<string, number>} */
        const timings = {};
        /** @type {RequestLogRecord} */
        const record = {
          msg: "request",
          method: String(req.method || ""),
          route: declaredRouteOf(app, matched || req.route, String(req.originalUrl || req.url || "").split("?")[0] || "/"),
          status: aborted && !res.headersSent ? 0 : res.statusCode,
          ms: Math.round((performance.now() - timing.start) * 10) / 10,
          timings,
        };
        /** @type {Record<string, string>} */
        const descs = {};
        for (const m of timing.marks) {
          timings[m.name] = Math.round(m.dur * 10) / 10;
          if (m.desc) descs[m.name] = m.desc;
        }
        if (Object.keys(descs).length) record.desc = descs;
        if (aborted) record.aborted = true;
        if (log) log(JSON.stringify(record));
        if (sink) sink(record);
      } catch { /* logging never breaks a response */ }
    };
    res.once("finish", () => finish(false));
    res.once("close", () => finish(!res.writableFinished));
    next();
  };
}

/**
 * @typedef {{
 *   msg: "request",
 *   method: string,
 *   route: string,
 *   status: number,
 *   ms: number,
 *   timings: Record<string, number>,
 *   desc?: Record<string, string>,
 *   aborted?: boolean,
 * }} RequestLogRecord
 */

/**
 * Remove anything that looks like a credential or key from an error message
 * before it is logged, and keep it short.
 * @param {unknown} err
 */
export function safeMessage(err) {
  const msg = err && typeof err === "object" && "message" in err ? String(/** @type {any} */ (err).message) : String(err);
  return msg
    .replace(/Bearer\s+[A-Za-z0-9._~+/=-]+/gi, "Bearer [redacted]")
    .replace(/eyJ[A-Za-z0-9._-]{20,}/g, "[redacted]")
    .replace(/(Key|ClientId)=[^;\s]+/gi, "$1=[redacted]")
    .slice(0, 200);
}

// --- What's new ---

/** The only labels a release note may carry (the shell release notes build writes them). */
export const WHATS_NEW_LABELS = Object.freeze(["New features", "Security improvements", "Bug fixes", "Faster performance", "Maintenance and reliability"]);

/**
 * One tool's notes from a server's generated whatsnew.json, cleaned: unknown labels dropped, text
 * printable ASCII, versions x.y.z, the changelog https or null. A tool with no notes answers an empty list.
 * @param {unknown} notes the parsed whatsnew.json
 * @param {string} moduleId
 * @returns {{ releases: Array<{ version: string, labels: string[], highlight?: string }>, changelog: string | null }}
 */
export function whatsNewNotes(notes, moduleId) {
  const entry = notes && typeof notes === "object" && Object.prototype.hasOwnProperty.call(notes, moduleId)
    ? /** @type {Record<string, any>} */ (notes)[moduleId] : null;
  /** @type {string | null} */
  let changelog = null;
  try {
    if (entry && typeof entry.changelog === "string" && new URL(entry.changelog).protocol === "https:") changelog = entry.changelog;
  } catch { changelog = null; }
  /** @type {Array<{ version: string, labels: string[], highlight?: string }>} */
  const releases = [];
  for (const r of Array.isArray(entry?.releases) ? entry.releases : []) {
    if (!r || typeof r.version !== "string" || !/^\d+\.\d+\.\d+$/.test(r.version)) continue;
    const labels = WHATS_NEW_LABELS.filter((l) => Array.isArray(r.labels) && r.labels.includes(l));
    const highlight = typeof r.highlight === "string" && /^[\x20-\x7e]{1,160}$/.test(r.highlight) ? r.highlight : "";
    if (labels.length === 0 && !highlight) continue;
    releases.push({ version: r.version, labels, ...(highlight ? { highlight } : {}) });
    if (releases.length >= 5) break;
  }
  return { releases, changelog };
}

/**
 * GET handler for one tool's release notes. The server is the access boundary: `allow(req)` is the
 * tool's own entry check (any role on the tool), so the notes of a tool reach only people who can
 * open it. A denied caller gets 403, a failed check 500, and nothing about the notes either way.
 * @param {{ notes: unknown, moduleId: string, allow: (req: any) => boolean | Promise<boolean> }} options
 */
export function whatsNewHandler(options) {
  const { notes, moduleId, allow } = options || /** @type {any} */ ({});
  if (typeof moduleId !== "string" || !moduleId) throw new TypeError("whatsNewHandler: moduleId is required");
  if (typeof allow !== "function") throw new TypeError("whatsNewHandler: allow must be a function");
  const body = whatsNewNotes(notes, moduleId);
  /** @param {any} req @param {any} res */
  return async (req, res) => {
    let ok = false;
    try {
      ok = (await allow(req)) === true;
    } catch (e) {
      console.error(`[whatsnew] ${moduleId} access check failed:`, safeMessage(e));
      return res.status(500).json({ error: "Permission check failed" });
    }
    if (!ok) return res.status(403).json({ error: "Forbidden" });
    res.set("Cache-Control", "private, max-age=300");
    return res.json(body);
  };
}


// --- Gateway guard ---
//
// Every module API is meant to be reached through the tier's API gateway only. The gateway adds a directory access token
// minted by its own managed identity in the X-Gateway-Token header (the gateway's managed identity authentication policy
// writing to a variable, so the caller's Authorization header is untouched). This guard
// checks that token: RS256 signature against the tenant signing keys, issuer, tenant, audience,
// expiry and not-before, and that the token belongs to the tier's gateway identity (oid). No secret is
// involved. The token must also carry the gateway app role (gateway), which only the gateway
// identity is assigned. Until GATEWAY_ENFORCE is "on" a request that fails the check is only
// logged, and with no settings at all the guard does nothing.

export const GATEWAY_HEADER = "x-gateway-token";
export const GATEWAY_EXEMPT_PATHS = Object.freeze(["/health", "/api/version", "/api/health"]);
// The platform's own traffic: Always On pings "/" and the container start probe asks for
// "/robots933456.txt". They are still refused, but logged as platform_ping so "refused" means a
// caller that skipped the gateway. Matched on method, path and no Authorization header, never on the
// user agent, which a caller can set.
export const GATEWAY_PLATFORM_PING_PATHS = Object.freeze(["/", "/robots933456.txt"]);
export const GATEWAY_ROLE = "gateway";

const GUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const JWT_PART_RE = /^[A-Za-z0-9_-]+$/;
const GATEWAY_SKEW_S = 300;

/**
 * "on" (any case, trimmed) turns enforcement on. Anything else, including unset, stays log only.
 * @param {unknown} raw
 */
export function parseGatewayEnforce(raw) {
  return typeof raw === "string" ? raw.trim().toLowerCase() === "on" : raw === true;
}

/**
 * The configured audiences exactly as listed (trimmed, de-duplicated), nothing derived. Each tier
 * lists the identifier URI (v1 token aud) and the client id (v2 token aud) explicitly.
 * @param {string | string[] | undefined | null} raw
 * @returns {string[]}
 */
export function gatewayAudiences(raw) {
  const list = Array.isArray(raw) ? raw : String(raw || "").split(",");
  /** @type {Set<string>} */
  const out = new Set();
  for (const item of list) {
    const a = String(item || "").trim();
    if (a) out.add(a);
  }
  return [...out];
}

/** @param {string} part */
function decodeJwtPart(part) {
  return JSON.parse(Buffer.from(part, "base64url").toString("utf8"));
}

/**
 * Tenant signing keys, cached for ttlMs, single flight. Every read of the key endpoint (first
 * read, TTL refresh, unknown key id, retry after a failure) is spaced at least minRefetchMs apart,
 * so a directory or network outage costs one fetch per window, never one per request. A failed read
 * is never cached and the last good keys keep serving. warm() starts the first read without waiting.
 * @param {{ tenantId: string, fetchKeys?: (url: string) => Promise<any>, ttlMs?: number, minRefetchMs?: number, now?: () => number }} options
 */
export function createSigningKeyCache(options) {
  const ttlMs = options.ttlMs ?? 600000;
  const minRefetchMs = options.minRefetchMs ?? 60000;
  const now = options.now ?? Date.now;
  const url = `https://login.microsoftonline.com/${encodeURIComponent(options.tenantId)}/discovery/v2.0/keys`;
  const fetchKeys = options.fetchKeys ?? (async (/** @type {string} */ u) => {
    const res = await fetch(u, { signal: AbortSignal.timeout(5000) });
    if (!res.ok) throw new Error(`signing key read failed: ${res.status}`);
    return res.json();
  });
  /** @type {Map<string, import("node:crypto").KeyObject>} */
  let keys = new Map();
  let fetchedAt = 0;
  let lastAttempt = -Infinity;
  /** @type {Promise<boolean> | null} */
  let inFlight = null;

  function refresh() {
    if (inFlight) return inFlight;
    lastAttempt = now();
    inFlight = (async () => {
      try {
        const body = await fetchKeys(url);
        /** @type {Map<string, import("node:crypto").KeyObject>} */
        const next = new Map();
        for (const jwk of Array.isArray(body?.keys) ? body.keys : []) {
          if (!jwk || jwk.kty !== "RSA" || typeof jwk.kid !== "string" || (jwk.use && jwk.use !== "sig")) continue;
          try {
            next.set(jwk.kid, createPublicKey({ key: { kty: "RSA", n: jwk.n, e: jwk.e }, format: "jwk" }));
          } catch (err) {
            console.warn(`[gateway] skipped an unreadable signing key: ${safeMessage(err)}`);
          }
        }
        if (next.size === 0) throw new Error("signing key read returned no usable key");
        keys = next;
        fetchedAt = now();
        return true;
      } catch (err) {
        console.warn(`[gateway] signing key read failed: ${safeMessage(err)}`);
        return false;
      } finally {
        inFlight = null;
      }
    })();
    return inFlight;
  }

  return {
    /**
     * @param {string} kid
     * @returns {Promise<import("node:crypto").KeyObject | null | undefined>} null = unknown key, undefined = keys unavailable
     */
    async get(kid) {
      const stale = keys.size === 0 || now() - fetchedAt > ttlMs;
      if (inFlight) await inFlight;
      else if ((stale || !keys.has(kid)) && now() - lastAttempt >= minRefetchMs) await refresh();
      if (keys.has(kid)) return keys.get(kid);
      return keys.size === 0 ? undefined : null;
    },
    /** Start the first read without waiting for it. Never throws. */
    warm() {
      if (keys.size === 0 && !inFlight && now() - lastAttempt >= minRefetchMs) void refresh();
    },
  };
}

/**
 * Check one gateway token. Returns { ok: true } or { ok: false, reason }.
 * @param {string | undefined} token
 * @param {{ tenantId: string, principalId: string, audiences: string[], keys: { get(kid: string): Promise<any> }, role?: string, nowSeconds?: number }} cfg
 * @returns {Promise<{ ok: boolean, reason?: string }>}
 */
export async function verifyGatewayToken(token, cfg) {
  if (!token) return { ok: false, reason: "missing" };
  const parts = String(token).trim().split(".");
  if (parts.length !== 3 || !parts.every((p) => JWT_PART_RE.test(p))) return { ok: false, reason: "malformed" };
  /** @type {any} */
  let header;
  /** @type {any} */
  let claims;
  try {
    header = decodeJwtPart(parts[0] ?? "");
    claims = decodeJwtPart(parts[1] ?? "");
  } catch {
    return { ok: false, reason: "malformed" };
  }
  if (!header || header.alg !== "RS256" || typeof header.kid !== "string") return { ok: false, reason: "alg" };
  if (!claims || typeof claims !== "object") return { ok: false, reason: "malformed" };
  const tid = cfg.tenantId.toLowerCase();
  if (String(claims.tid || "").toLowerCase() !== tid) return { ok: false, reason: "tenant" };
  const issuers = [`https://login.microsoftonline.com/${tid}/v2.0`, `https://sts.windows.net/${tid}/`];
  if (!issuers.includes(String(claims.iss || "").toLowerCase())) return { ok: false, reason: "issuer" };
  const auds = Array.isArray(claims.aud) ? claims.aud : [claims.aud];
  const accepted = cfg.audiences.map((a) => a.toLowerCase());
  if (!auds.some((/** @type {unknown} */ a) => typeof a === "string" && accepted.includes(a.toLowerCase()))) return { ok: false, reason: "audience" };
  const nowS = cfg.nowSeconds ?? Math.floor(Date.now() / 1000);
  if (typeof claims.exp !== "number" || claims.exp + GATEWAY_SKEW_S < nowS) return { ok: false, reason: "expired" };
  if (typeof claims.nbf === "number" && claims.nbf - GATEWAY_SKEW_S > nowS) return { ok: false, reason: "not_yet_valid" };
  if (String(claims.oid || "").toLowerCase() !== cfg.principalId.toLowerCase()) return { ok: false, reason: "principal" };
  if (claims.idtyp !== undefined && claims.idtyp !== "app") return { ok: false, reason: "principal" };
  const role = cfg.role ?? GATEWAY_ROLE;
  if (role && !(Array.isArray(claims.roles) && claims.roles.includes(role))) return { ok: false, reason: "role" };
  const key = await cfg.keys.get(header.kid);
  if (key === undefined) return { ok: false, reason: "keys_unavailable" };
  if (key === null) return { ok: false, reason: "unknown_key" };
  let good = false;
  try {
    good = cryptoVerify("RSA-SHA256", Buffer.from(`${parts[0]}.${parts[1]}`), key, Buffer.from(parts[2] ?? "", "base64url"));
  } catch {
    good = false;
  }
  return good ? { ok: true } : { ok: false, reason: "signature" };
}

/**
 * Read the gateway header and remove it from every header view Node keeps on the request
 * (req.headers and req.rawHeaders, matched in any case). headersDistinct is built from rawHeaders
 * on first read, so it never sees the value.
 * @param {any} req
 * @returns {string | undefined}
 */
function takeGatewayHeader(req) {
  const h = req && req.headers;
  const raw = h ? h[GATEWAY_HEADER] : undefined;
  if (h) delete h[GATEWAY_HEADER];
  const rh = req && req.rawHeaders;
  if (Array.isArray(rh)) {
    for (let i = rh.length - 2; i >= 0; i -= 2) {
      if (String(rh[i]).toLowerCase() === GATEWAY_HEADER) rh.splice(i, 2);
    }
  }
  return Array.isArray(raw) ? raw[0] : raw;
}

/**
 * Express middleware that admits a request only when it came through the gateway.
 * Settings come from options, else from env (default process.env):
 *   GATEWAY_ENFORCE       "on" = refuse (403, or 503 when the signing keys cannot be read),
 *                              anything else = log only (and nothing at all while unconfigured)
 *   GATEWAY_PRINCIPAL_ID  object id of the tier's gateway managed identity
 *   GATEWAY_AUDIENCE      audience(s) the gateway token is minted for (comma list)
 *   TENANT_ID            tenant id
 * /health, /api/version and /api/health stay open for the deploy smoke test and probes.
 * The header is removed from req.headers and req.rawHeaders before anything else runs, whatever
 * the settings, so nothing downstream logs or forwards it. In log-only mode the request goes on at
 * once and the check runs beside it, so a slow key read never adds latency before enforcement.
 * Some but not all settings present is logged loudly at startup (misconfigured).
 * Refusals log one line per kind and reason per logIntervalMs with a count. A GET or HEAD to a
 * platform ping path with no Authorization header is logged as platform_ping, not (would_)refused.
 * Marks the request "gw" (ok, exempt, or the failure reason) for Server-Timing and telemetry.
 * @param {{ env?: Record<string, string | undefined>, enforce?: boolean | string, principalId?: string, audience?: string | string[], tenantId?: string, exempt?: readonly string[], platformPingPaths?: readonly string[], keys?: { get(kid: string): Promise<any>, warm?: () => void }, fetchKeys?: (url: string) => Promise<any>, log?: (line: string) => void, now?: () => number, logIntervalMs?: number }} [options]
 */
export function gatewayGuard(options = {}) {
  const env = options.env ?? process.env;
  const enforce = parseGatewayEnforce(options.enforce ?? env.GATEWAY_ENFORCE);
  const principalId = String(options.principalId ?? env.GATEWAY_PRINCIPAL_ID ?? "").trim();
  const tenantId = String(options.tenantId ?? env.TENANT_ID ?? "").trim();
  const audiences = gatewayAudiences(options.audience ?? env.GATEWAY_AUDIENCE);
  const exempt = new Set((options.exempt ?? GATEWAY_EXEMPT_PATHS).map((p) => p.replace(/\/+$/, "") || "/"));
  const pings = new Set((options.platformPingPaths ?? GATEWAY_PLATFORM_PING_PATHS).map((p) => p.replace(/\/+$/, "") || "/"));
  const log = options.log ?? ((/** @type {string} */ line) => console.warn(line));
  const now = options.now ?? Date.now;
  const logIntervalMs = options.logIntervalMs ?? 60000;
  const configured = GUID_RE.test(principalId) && GUID_RE.test(tenantId) && audiences.length > 0;
  const keys = configured ? options.keys ?? createSigningKeyCache({ tenantId, fetchKeys: options.fetchKeys, now }) : null;
  if (keys && typeof keys.warm === "function") keys.warm();
  /** @type {Map<string, { count: number, last: number }>} */
  const seen = new Map();

  log(JSON.stringify({ gateway: enforce ? "enforce" : "log_only", configured }));
  const anySet = Boolean(principalId || audiences.length || (options.principalId ?? env.GATEWAY_PRINCIPAL_ID));
  if (!configured && anySet) {
    /** @type {string[]} */
    const bad = [];
    if (!GUID_RE.test(principalId)) bad.push("GATEWAY_PRINCIPAL_ID");
    if (!GUID_RE.test(tenantId)) bad.push("TENANT_ID");
    if (audiences.length === 0) bad.push("GATEWAY_AUDIENCE");
    log(JSON.stringify({ gateway: "misconfigured", missing_or_invalid: bad }));
  }

  /** @param {string} reason @param {boolean} ping */
  function note(reason, ping) {
    const kind = ping ? "platform_ping" : enforce ? "refused" : "would_refuse";
    const key = `${kind}:${reason}`;
    const t = now();
    const s = seen.get(key) ?? { count: 0, last: -Infinity };
    s.count += 1;
    if (t - s.last >= logIntervalMs) {
      log(JSON.stringify({ gateway: kind, reason, count: s.count }));
      s.count = 0;
      s.last = t;
    }
    seen.set(key, s);
  }

  /** @type {(req: any, res: any, next: (err?: unknown) => void) => void} */
  return function gatewayGuardMiddleware(req, res, next) {
    const raw = takeGatewayHeader(req);
    if (!configured && !enforce) {
      next();
      return;
    }
    const path = String(req.path ?? "/").replace(/\/+$/, "") || "/";
    if (exempt.has(path)) {
      recordTiming(req, "gw", 0, "exempt");
      next();
      return;
    }
    const method = String(req.method ?? "GET").toUpperCase();
    const ping = pings.has(path) && (method === "GET" || method === "HEAD") && !req.headers?.authorization;
    const t0 = performance.now();
    const token = raw;
    const check = configured && keys
      ? verifyGatewayToken(token, { tenantId, principalId, audiences, keys })
      : Promise.resolve({ ok: false, reason: "unconfigured" });
    const settled = check.catch(() => ({ ok: false, reason: "error" }));
    if (!enforce) {
      next();
      settled
        .then((result) => {
          if (!result.ok) note(result.reason || "error", ping);
        })
        .catch(() => {});
      return;
    }
    settled
      .then((result) => {
        const reason = result.ok ? "ok" : result.reason || "error";
        recordTiming(req, "gw", performance.now() - t0, reason);
        req.gateway = { ok: result.ok, reason };
        if (result.ok) return next();
        note(reason, ping);
        if (reason === "keys_unavailable") {
          res.status(503).json({ error: "Service unavailable", message: "Try again shortly." });
          return;
        }
        res.status(403).json({ error: "Forbidden", message: "This API is reachable only through the API gateway." });
      })
      .catch(next);
  };
}
