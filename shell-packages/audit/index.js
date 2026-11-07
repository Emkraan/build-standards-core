// shell-packages/audit: a Postgres audit log with a tamper-evident hash chain, as one factory.
//
// Each entry's hash is HMAC-SHA256 (key from the environment variable named by `hmacEnv`, default
// AUDIT_HMAC_SECRET) over the canonical JSON of the entry including the previous entry's hash. Without a
// secret it falls back to plain SHA-256 so a dev database still chains; verify() reports the mode. The
// table (audit_log) is the consumer's; the columns this package reads and writes are in the schema below.
//
//   createAudit({ db, env, hmacEnv, clientIp, log })
//     write        one entry, non-fatal: a logging failure never breaks the mutation that triggered it
//     transaction  run a change and its audit entries in one database transaction (commit or roll back together)
//     list / listAll / count / stats   reads for an audit page
//     verify       walk the chain and report the first break (edited entry, removed entry, deleted head)
//     extractContext / auditHash / canonicalizeEntry / lastChainedHash
//   stableStringify, canonicalizeEntry, csvCell, clientPublicIp, ZERO_HASH   pure helpers
//
// Schema (created by the consumer's migration): audit_log(id uuid pk, created_at timestamptz default now(),
// ts timestamptz, schema_version int, actor_email text, actor_name text, actor_json jsonb, action text,
// target text, outcome text, context_ip text, context_user_agent text, context_request_id text,
// context_method text, context_path text, details_json jsonb, prev_hash text, hash text,
// search_tsv tsvector for the free text search of list()).
//
// `db` is `{ query(text, params), getClient() }` where getClient answers a pool client with query and
// release (only transaction() needs it). Writes are serialised by an in-process queue, so a deploy runs one
// writer process, or the consumer adds its own cross-process lock around write().

import crypto from "node:crypto";

export const ZERO_HASH = "0".repeat(64);

/**
 * @typedef {{ email?: string | null, name?: string | null, oid?: string | null }} AuditActor
 * @typedef {{ ip: string | null, userAgent: string | null, requestId: string | null, method: string | null, path: string | null }} AuditContext
 * @typedef {{ id: string, ts: string, schemaVersion: number, actor: AuditActor, action: string, target: string | null, outcome: string,
 *   context: AuditContext, details: Record<string, unknown>, prevHash?: string | null, hash?: string }} AuditEntry
 * @typedef {{ req?: any, outcome?: string, before?: unknown, after?: unknown, changed?: unknown, errorMessage?: string }} AuditWriteOpts
 * @typedef {{ action?: string, actor?: string, outcome?: string, target?: string, startDate?: string, endDate?: string, q?: string }} AuditQuery
 * @typedef {{ items: AuditEntry[], total: number, page: number, limit: number, pages: number }} AuditListResult
 * @typedef {Record<string, any>} AuditLogRow
 */

// Deterministic JSON: recursively sort object keys so the canonical form is
// reproducible REGARDLESS of key order. Essential because actor/details/context
// are stored as jsonb, which does NOT preserve insertion order - so the hash
// computed at write time (in-memory) must match the hash recomputed at verify
// time (read back from jsonb).
/** @param {unknown} value @returns {string} */
export function stableStringify(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return "[" + value.map(stableStringify).join(",") + "]";
  const keys = Object.keys(value).filter((k) => /** @type {Record<string, unknown>} */ (value)[k] !== undefined).sort();
  return "{" + keys.map((k) => JSON.stringify(k) + ":" + stableStringify(/** @type {Record<string, unknown>} */ (value)[k])).join(",") + "}";
}

/** @param {AuditEntry} entry @returns {string} */
export function canonicalizeEntry(entry) {
  const { id, ts, schemaVersion, actor, action, target, outcome, context, details, prevHash } = entry;
  return stableStringify({ id, ts, schemaVersion, actor, action, target, outcome, context, details, prevHash });
}

/**
 * Clean the inbound connection's remote address into a bare IP, or null.
 * @param {any} req
 * @returns {string|null}
 */
export function clientPublicIp(req) {
  let ip = req && req.ip;
  if (typeof ip !== "string") return null;
  ip = ip.trim();
  if (!ip) return null;
  // IPv4-mapped IPv6 to IPv4.
  if (ip.toLowerCase().startsWith("::ffff:")) ip = ip.slice(7);
  // "1.2.3.4:5678" to strip the source port Azure appends to X-Forwarded-For.
  const v4 = ip.match(/^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):\d+$/);
  if (v4) ip = /** @type {string} */ (v4[1]);
  // "[::1]:5678" to bracketed IPv6 with a port.
  const v6 = ip.match(/^\[(.+)\]:\d+$/);
  if (v6) ip = /** @type {string} */ (v6[1]);
  ip = ip.trim();
  return ip || null;
}

/**
 * Escape one value for the audit CSV export. Quoting alone is NOT enough:
 * Excel/Sheets evaluate a cell whose content starts with = + - @ (or a leading
 * tab/CR) even inside quotes, and audit rows carry caller-influenced text, so an
 * export opened by an admin could execute a payload written by whoever the entry
 * is about. A leading apostrophe neutralizes the formula; the cell still reads
 * correctly as text.
 * @param {unknown} v
 * @returns {string}
 */
export function csvCell(v) {
  let s = v == null ? "" : String(v);
  if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`;
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/**
 * @param {{
 *   db: { query: (text: string, params?: unknown[]) => Promise<{ rows: any[] }>, getClient?: () => Promise<any> },
 *   env?: Record<string, string | undefined>,
 *   hmacEnv?: string,
 *   clientIp?: (req: any) => string | null,
 *   log?: Pick<Console, "error">,
 * }} options
 */
export function createAudit(options) {
  const { db } = options || /** @type {any} */ ({});
  if (!db || typeof db.query !== "function") throw new TypeError("createAudit needs a db with query()");
  const env = options.env || process.env;
  const hmacEnv = options.hmacEnv || "AUDIT_HMAC_SECRET";
  const clientIp = options.clientIp || clientPublicIp;
  const log = options.log || console;

// Chain order is (created_at, id). created_at is `now()` (transaction start,
// microsecond resolution) so serialized writes never actually tie; `id` is only
// there so lastChainedHash() and verify() agree on a deterministic order
// instead of inheriting whatever order Postgres happened to return.
const CHAIN_ORDER_DESC = "created_at DESC, id DESC";
const CHAIN_ORDER_ASC = "created_at ASC, id ASC";


/** @param {string} canonical @returns {string} */
function auditHash(canonical) {
  const secret = String(env[hmacEnv] || "");
  if (secret) return crypto.createHmac("sha256", secret).update(canonical).digest("hex");
  return crypto.createHash("sha256").update(canonical).digest("hex");
}

/** @param {{ query: typeof db.query }} [q] The pool, or a transaction's client. */
async function lastChainedHash(q = db) {
  const { rows } = await q.query(
    `SELECT hash FROM audit_log WHERE hash IS NOT NULL ORDER BY ${CHAIN_ORDER_DESC} LIMIT 1`
  );
  return rows[0]?.hash || ZERO_HASH;
}

// Chain writes are serialized through this in-process promise queue (one per createAudit): write()
// reads the newest hash and then INSERTs, and two concurrent audited requests
// (e.g. the Assignments tab firing one POST per selected role) would otherwise
// both chain off the SAME prevHash - forking the chain and making "Verify
// chain" report a permanent, false tamper alarm. Olympus runs single-instance
// on App Service, so one process-wide queue is sufficient.
let _chainLock = Promise.resolve();

/**
 * @template T
 * @param {() => Promise<T>} fn
 * @returns {Promise<T>}
 */
function serializeChainWrite(fn) {
  const run = _chainLock.then(fn, fn); // run regardless of the previous outcome
  // Keep the lock itself settled-resolved so one failed write can't poison the
  // queue for every write behind it.
  _chainLock = run.then(() => undefined, () => undefined);
  return run;
}

// - Context extraction -

/** @param {any} [req] @returns {AuditContext} */
function extractContext(req) {
  // Consistent shape whether or not there's a request - verify() always
  // reconstructs the 5-field object, so write() must hash the same shape (a bare
  // null here would mismatch on system/scheduler writes).
  if (!req) return { ip: null, userAgent: null, requestId: null, method: null, path: null };
  // NEVER read X-Forwarded-For[0] here: App Service APPENDS the real client
  // address to whatever the caller sent, so element [0] is attacker-controlled -
  // a forged value would be hashed into the chain as valid provenance and would
  // also ride into the audit CSV export. `req.ip` is the trust-proxy-resolved
  // address; clientPublicIp() strips the "<ip>:<port>" suffix Azure adds.
  const ip = clientIp(req) || req.ip || null;
  const ua = req.headers?.["user-agent"] || null;
  return {
    ip,
    userAgent: ua ? String(ua).slice(0, 240) : null,
    requestId: req.id || null,
    method: req.method || null,
    path: req.originalUrl || req.url || null,
  };
}

// - Write -

// Actors arrive as the caller identity from auth-jwt, which carries the ENTIRE
// decoded token on `_claims` (aud/iss/exp/nonce plus the groups array, which
// then appears twice). Persisting that would put raw token claims in the DB,
// bloat every audit row from ~150B to 5-10KB for a heavily-grouped user, and
// ship the bloat back on every Audit page load. Only the three identifying
// fields are stored - and it is the STORED object that gets hashed, so the
// chain stays self-consistent and older full-actor rows still verify.
/** @param {AuditActor | null | undefined} actor @returns {AuditActor} */
function sanitizeActor(actor) {
  return {
    email: actor?.email || null,
    name: actor?.name || null,
    oid: actor?.oid || null,
  };
}

/**
 * Build, hash and INSERT one entry through `q` (the pool, or a transaction's
 * client). The caller holds the chain lock. Throws on failure.
 * @param {{ query: typeof db.query }} q
 * @param {AuditActor} actor @param {string} action @param {string | null} target
 * @param {Record<string, unknown>} details @param {AuditWriteOpts} opts
 * @returns {Promise<{id: string, hash: string}>}
 */
async function insertEntry(q, actor, action, target, details, opts) {
  const outcome = opts.outcome || "success";
  const mergedDetails = { ...details };
  if (opts.before !== undefined)  mergedDetails.before = opts.before;
  if (opts.after !== undefined)   mergedDetails.after = opts.after;
  if (opts.changed !== undefined) mergedDetails.changed = opts.changed;
  if (opts.errorMessage)          mergedDetails.errorMessage = opts.errorMessage;

  const context = extractContext(opts.req);
  const storedActor = sanitizeActor(actor);
  const ts = new Date().toISOString();
  const id = crypto.randomUUID();
  const prevHash = await lastChainedHash(q);

  const entry = {
    id,
    ts,
    schemaVersion: 1,
    actor: storedActor,
    action,
    target: target || null,
    outcome,
    context,
    details: mergedDetails,
    prevHash,
  };
  const hash = auditHash(canonicalizeEntry(entry));

  await q.query(
    `INSERT INTO audit_log
       (id, ts, schema_version, actor_email, actor_name, actor_json,
        action, target, outcome,
        context_ip, context_user_agent, context_request_id, context_method, context_path,
        details_json, prev_hash, hash)
     VALUES
       ($1, $2, $3, $4, $5, $6::jsonb,
        $7, $8, $9,
        $10, $11, $12, $13, $14,
        $15::jsonb, $16, $17)`,
    [
      id, ts, entry.schemaVersion,
      storedActor.email, storedActor.name, JSON.stringify(storedActor),
      action, target || null, outcome,
      context?.ip || null, context?.userAgent || null, context?.requestId || null,
      context?.method || null, context?.path || null,
      JSON.stringify(mergedDetails), prevHash, hash,
    ]
  );
  return { id, hash };
}

/**
 * Write an audit entry. Non-fatal: logs and resolves null on failure.
 * @param {AuditActor} actor   {email,name,oid,groups}
 * @param {string} action  e.g. "role:create"
 * @param {string | null} target  e.g. "role:Operator"
 * @param {Record<string, unknown>} [details]
 * @param {AuditWriteOpts} [opts]  {req, outcome, before, after, changed, errorMessage}
 * @returns {Promise<{id: string, hash: string} | null>}
 */
async function write(actor, action, target, details = {}, opts = {}) {
  try {
    // Everything from "read the newest hash" to "INSERT" runs inside the queue
    // so no two writers can chain off the same prevHash. `ts` and `id` are
    // minted in there too, so their order matches the chain's.
    return await serializeChainWrite(() => insertEntry(db, actor, action, target, details, opts));
  } catch (e) {
    log.error("[audit] write failed (non-fatal):", /** @type {Error} */ (e).message);
    return null;
  }
}

/**
 * Run `work` in one database transaction whose audit entries commit or roll
 * back with the change. `work(client, record)` makes its changes through
 * `client` and calls `record(actor, action, target, details, opts)` for each
 * audit entry, which INSERTs through the same client and throws on failure.
 * The chain lock is held from BEGIN to COMMIT: an entry chains off committed
 * rows only, and no other writer can read the newest hash while this one is
 * uncommitted (that would fork the chain). A thrown error, or a returned
 * `{ rollback: true }`, rolls everything back.
 * @template T
 * @param {(client: any, record: (actor: AuditActor, action: string, target: string | null, details?: Record<string, unknown>, opts?: AuditWriteOpts) => Promise<{id: string, hash: string}>) => Promise<T>} work
 * @returns {Promise<T>}
 */
function transaction(work) {
  return serializeChainWrite(async () => {
    const client = await db.getClient();
    try {
      await client.query("BEGIN");
      const out = await work(client, (actor, action, target, details = {}, opts = {}) =>
        insertEntry(client, actor, action, target, details, opts));
      const rollback = !!(out && typeof out === "object" && /** @type {{ rollback?: boolean }} */ (out).rollback);
      await client.query(rollback ? "ROLLBACK" : "COMMIT");
      return out;
    } catch (e) {
      await client.query("ROLLBACK").catch((re) => {
        log.error("[audit] rollback failed:", /** @type {Error} */ (re).message);
      });
      throw e;
    } finally {
      client.release();
    }
  });
}

// - Reads -

/** @param {AuditLogRow} row @returns {AuditEntry} */
function rowToEntry(row) {
  return {
    id: row.id,
    ts: row.ts,
    schemaVersion: row.schema_version,
    actor: row.actor_json || {},
    action: row.action,
    target: row.target,
    outcome: row.outcome,
    context: {
      ip: row.context_ip,
      userAgent: row.context_user_agent,
      requestId: row.context_request_id,
      method: row.context_method,
      path: row.context_path,
    },
    details: row.details_json || {},
    prevHash: row.prev_hash || undefined,
    hash: row.hash || undefined,
  };
}

/** @param {AuditQuery} q @param {number} [start] */
function buildWhere(q, start = 1) {
  /** @type {string[]} */
  const clauses = [];
  /** @type {(string | number)[]} */
  const params = [];
  let i = start;
  if (q.action)  { clauses.push(`action ILIKE $${i++}`); params.push(`%${q.action}%`); }
  if (q.actor)   { clauses.push(`LOWER(COALESCE(actor_email,'')) LIKE $${i++}`); params.push(`%${q.actor.toLowerCase()}%`); }
  if (q.outcome) { clauses.push(`LOWER(outcome) = $${i++}`); params.push(String(q.outcome).toLowerCase()); }
  if (q.target)  { clauses.push(`target = $${i++}`); params.push(String(q.target)); }
  if (q.startDate) { const t = new Date(q.startDate); if (!isNaN(/** @type {number} */ (/** @type {unknown} */ (t)))) { clauses.push(`created_at >= $${i++}`); params.push(t.toISOString()); } }
  if (q.endDate)   { const t = new Date(q.endDate);   if (!isNaN(/** @type {number} */ (/** @type {unknown} */ (t)))) { clauses.push(`created_at <= $${i++}`); params.push(t.toISOString()); } }
  if (q.q && String(q.q).trim()) {
    clauses.push(`search_tsv @@ plainto_tsquery('english', $${i++})`);
    params.push(String(q.q).trim());
  }
  return { where: clauses.length ? `WHERE ${clauses.join(" AND ")}` : "", params, nextIndex: i };
}

/**
 * @param {AuditQuery} [q]
 * @param {{ page?: number, limit?: number }} [opts]
 * @returns {Promise<AuditListResult>}
 */
async function list(q = {}, { page = 1, limit = 50 } = {}) {
  const pageNum = Math.max(1, Math.floor(page));
  const lim = Math.min(500, Math.max(1, Math.floor(limit)));
  const offset = (pageNum - 1) * lim;

  const { where, params, nextIndex } = buildWhere(q);
  const limIdx = nextIndex;
  const offIdx = nextIndex + 1;

  const listSql = `SELECT * FROM audit_log ${where} ORDER BY created_at DESC LIMIT $${limIdx} OFFSET $${offIdx}`;
  const countSql = `SELECT COUNT(*)::int AS c FROM audit_log ${where}`;

  const { rows } = await db.query(listSql, [...params, lim, offset]);
  const { rows: cr } = await db.query(countSql, params);
  const total = cr[0]?.c || 0;
  return {
    items: rows.map(rowToEntry),
    total,
    page: pageNum,
    limit: lim,
    pages: Math.ceil(total / lim) || 1,
  };
}

/** @param {AuditQuery} [q] @returns {Promise<AuditEntry[]>} */
async function listAll(q = {}) {
  const { where, params } = buildWhere(q);
  const { rows } = await db.query(
    `SELECT * FROM audit_log ${where} ORDER BY created_at DESC`, params
  );
  return rows.map(rowToEntry);
}

async function count() {
  const { rows } = await db.query(`SELECT COUNT(*)::int AS c FROM audit_log`);
  return rows[0]?.c || 0;
}

// - Stats -

/** @param {{ days?: number }} [opts] */
async function stats({ days = 14 } = {}) {
  const sinceIso = new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();

  const perDay = (await db.query(
    `SELECT to_char(ts, 'YYYY-MM-DD') AS day, COUNT(*)::int AS c
       FROM audit_log WHERE created_at >= $1 GROUP BY day ORDER BY day ASC`,
    [sinceIso]
  )).rows.map((r) => ({ day: r.day, count: r.c }));

  const topActors = (await db.query(
    `SELECT COALESCE(actor_email, '\u2014') AS actor, COUNT(*)::int AS c
       FROM audit_log WHERE created_at >= $1 GROUP BY actor ORDER BY c DESC LIMIT 8`,
    [sinceIso]
  )).rows.map((r) => ({ actor: r.actor, count: r.c }));

  const topActions = (await db.query(
    `SELECT action, COUNT(*)::int AS c
       FROM audit_log WHERE created_at >= $1 GROUP BY action ORDER BY c DESC LIMIT 10`,
    [sinceIso]
  )).rows.map((r) => ({ action: r.action, count: r.c }));

  // The REAL windowed total (entries within the last N days) - distinct from
  // all_time_total, so a "last N days" tile never silently shows all-time.
  const totalRow = await db.query(
    `SELECT COUNT(*)::int AS c FROM audit_log WHERE created_at >= $1`, [sinceIso]
  );

  return {
    since: sinceIso,
    days,
    total: totalRow.rows[0]?.c || 0,
    per_day: perDay,
    top_actors: topActors,
    top_actions: topActions,
    all_time_total: await count(),
  };
}

// - Chain verification -

async function verify() {
  const { rows } = await db.query(
    `SELECT id, ts, schema_version, actor_json, action, target, outcome,
            context_ip, context_user_agent, context_request_id, context_method, context_path,
            details_json, prev_hash, hash
       FROM audit_log ORDER BY ${CHAIN_ORDER_ASC}`
  );

  let okFromIndex = null;
  let expectedPrev = ZERO_HASH;
  let firstBreakAt = null;
  let firstBreakReason = null;

  for (let i = 0; i < rows.length; i++) {
    const r = rows[i];
    if (!r.hash) continue;
    const entry = {
      id: r.id,
      ts: r.ts instanceof Date ? r.ts.toISOString() : r.ts,
      schemaVersion: r.schema_version,
      actor: r.actor_json || {},
      action: r.action,
      target: r.target,
      outcome: r.outcome,
      context: {
        ip: r.context_ip,
        userAgent: r.context_user_agent,
        requestId: r.context_request_id,
        method: r.context_method,
        path: r.context_path,
      },
      details: r.details_json || {},
      prevHash: r.prev_hash,
    };
    if (okFromIndex == null) {
      okFromIndex = i;
      expectedPrev = r.hash;
      // The genuine first entry must chain off the genesis (ZERO_HASH). If the
      // first SURVIVING entry does not, a contiguous leading segment (including
      // the real first entry) was deleted; each surviving entry's own hash still
      // matches its contents, so without this check the log would verify as ok.
      if (r.prev_hash !== ZERO_HASH) {
        firstBreakAt = i;
        firstBreakReason = "first surviving entry does not link to the genesis hash: a leading segment of the log was deleted";
        break;
      }
      if (auditHash(canonicalizeEntry(entry)) !== r.hash) {
        firstBreakAt = i;
        firstBreakReason = "hash mismatch on first chained entry: entry contents edited";
        break;
      }
      continue;
    }
    if (r.prev_hash !== expectedPrev) {
      firstBreakAt = i;
      firstBreakReason = `prevHash does not match prior entry's hash: log reordered or an entry removed between ${okFromIndex} and ${i}`;
      break;
    }
    if (auditHash(canonicalizeEntry(entry)) !== r.hash) {
      firstBreakAt = i;
      firstBreakReason = "hash mismatch: entry contents edited after write";
      break;
    }
    expectedPrev = r.hash;
  }

  return {
    ok: firstBreakAt == null,
    length: rows.length,
    chainedCount: rows.filter((r) => r.hash).length,
    okFromIndex,
    firstBreakAt,
    firstBreakReason,
    secretMode: env[hmacEnv] ? "hmac-sha256" : "sha256-nosecret",
  };
}

// - CSV export helper -

  return {
    write,
    transaction,
    list,
    listAll,
    count,
    stats,
    verify,
    extractContext,
    auditHash,
    canonicalizeEntry,
    lastChainedHash,
  };
}
