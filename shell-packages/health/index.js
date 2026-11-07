// shell-packages/health: the two read patterns behind a status page.
//
//   createSwrReader   answer from the last reading, refresh it in the background one pass at a time (single flight),
//                     keep the last good reading through a failed refresh, and say how old the answer is
//   healthRoute       the public liveness route: one reading per subsystem, a 503 only when a critical one is down,
//                     and no raw error text on the wire in production
//
// A status page (a probe of every app, a cloud inventory) must never wait on the thing it reports on: a slow or
// failing probe would take the page down with it. The reader answers at once from what it last saw.

/**
 * Stale-while-revalidate over one async read.
 * @template T
 * @param {{
 *   read: () => Promise<T>,
 *   staleMs?: number,
 *   now?: () => number,
 *   log?: Pick<Console, "error">,
 *   onError?: (error: unknown) => void,
 * }} options
 *   staleMs: how old a reading may be before a read triggers a refresh (default 30000)
 * @returns {{
 *   get: () => { value: T | null, at: number | null, ageMs: number | null, refreshing: boolean, lastError: string | null },
 *   refresh: () => Promise<void>,
 * }}
 */
export function createSwrReader(options) {
  const { read } = options || /** @type {any} */ ({});
  if (typeof read !== "function") throw new TypeError("createSwrReader needs a read function");
  const staleMs = options.staleMs ?? 30_000;
  const now = options.now || Date.now;
  const log = options.log || console;
  /** @type {T | null} */ let value = null;
  /** @type {number | null} */ let at = null;
  /** @type {Promise<void> | null} */ let inflight = null;
  /** @type {string | null} */ let lastError = null;

  /** Refresh once. A pass already running is shared; a failure keeps the last good reading and never rejects. */
  function refresh() {
    if (inflight) return inflight;
    inflight = (async () => {
      try {
        const next = await read();
        value = next;
        at = now();
        lastError = null;
      } catch (e) {
        lastError = e instanceof Error ? e.message : String(e);
        log.error(`[health] refresh failed, keeping the last reading: ${lastError}`);
        if (options.onError) options.onError(e);
      } finally {
        inflight = null;
      }
    })();
    return inflight;
  }

  return {
    /** The last reading with its real age, never waiting. Starts a refresh when there is none or it is stale. */
    get() {
      const age = at === null ? null : now() - at;
      if (age === null || age >= staleMs) void refresh();
      return { value, at, ageMs: age, refreshing: inflight !== null, lastError };
    },
    refresh,
  };
}

/**
 * The public liveness route. No auth: it is for uptime monitors and the console, and it is the fail-soft boot's
 * safety valve: a startup task that failed does not exit the process, this route says which subsystem is down.
 * @param {{ get: Function }} router an express Router
 * @param {{
 *   version: string,
 *   critical: Record<string, () => Promise<{ ok: boolean, [k: string]: unknown }>>,
 *   info?: Record<string, () => Record<string, unknown>>,
 *   env?: Record<string, string | undefined>,
 *   path?: string,
 *   log?: Pick<Console, "error">,
 * }} options critical: each check answers { ok, ... } and a throw counts as down; info: readings that never change the status
 */
export function healthRoute(router, options) {
  const env = options.env || process.env;
  const log = options.log || console;
  const isProd = () => env.NODE_ENV === "production";
  router.get(options.path || "/", async (/** @type {any} */ _req, /** @type {any} */ res) => {
    /** @type {Record<string, unknown>} */
    const subsystems = {};
    let healthy = true;
    for (const [name, check] of Object.entries(options.critical)) {
      const started = Date.now();
      try {
        const r = await check();
        subsystems[name] = { latencyMs: Date.now() - started, ...r };
        if (r.ok !== true) healthy = false;
      } catch (e) {
        healthy = false;
        const err = /** @type {{ message?: string, code?: string }} */ (e) || {};
        // The raw message can name a host, an account or a database, so it never goes on the wire in production.
        log.error(`[health] ${name} check failed: ${err.message}`);
        subsystems[name] = { ok: false, latencyMs: Date.now() - started, error: isProd() ? "Unreachable" : err.message, ...(err.code ? { code: err.code } : {}) };
      }
    }
    for (const [name, read] of Object.entries(options.info || {})) {
      try { subsystems[name] = read(); } catch { subsystems[name] = { error: "unavailable" }; }
    }
    res.status(healthy ? 200 : 503).json({
      status: healthy ? "ok" : "degraded",
      version: options.version,
      env: env.NODE_ENV || "development",
      uptimeSeconds: Math.round(process.uptime()),
      timestamp: new Date().toISOString(),
      subsystems,
    });
  });
}
