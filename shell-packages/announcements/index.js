// shell-packages/announcements: platform announcements for the console feed strip. Validation, the cached read of
// the announcements whose window is open now, and the audited admin routes.
//
// Rows live in an `announcements` table the consumer creates (schema below). Text only: the consoles render title
// and body as plain text, so the checks here are about length, control characters and the link target, not markup.
//
//   validate / cleanText / cleanHref / toApi / stateOf   pure
//   createAnnouncements({ db })                          listActive (cached, never outlives a window edge), invalidate
//   announcementRoutes(router, options)                  GET /, POST /, PUT /:id, POST /:id/expire, DELETE /:id
//
// Schema: announcements(id uuid pk, tone text check in (info, success, warning, critical), title text 1..120,
// body text <= 400, href text null or a path or https url <= 300, starts_at timestamptz default now(), ends_at
// timestamptz null, expired_at timestamptz null, created_by text, created_at timestamptz default now(), updated_by
// text, updated_at timestamptz default now(), check (ends_at is null or ends_at > starts_at)), and an index on
// (starts_at, ends_at). The constraint names are the ones PostgreSQL gives them (announcements_check,
// announcements_href_check, announcements_title_check, announcements_body_check, announcements_tone_check).

/**
 * @typedef {{ id: string, tone: string, title: string, body: string, href: string | null, starts_at: string | Date,
 *   ends_at: string | Date | null, expired_at: string | Date | null, created_by: string | null, created_at: string | Date,
 *   updated_by: string | null, updated_at: string | Date }} AnnouncementRow
 */

export const TONES = ["info", "success", "warning", "critical"];
export const TITLE_MAX = 120;
export const BODY_MAX = 400;
export const HREF_MAX = 300;
// A schedule further out than this is almost certainly a typo in the year.
const MAX_WINDOW_MS = 400 * 24 * 60 * 60 * 1000;
const ACTIVE_TTL_MS = 15 * 1000;
const ACTIVE_LIMIT = 10;

// C0 controls, DEL and C1 controls, plus the zero-width and bidi override
// characters that could make a title read differently from what was typed.
// Newlines are folded to spaces first: the feed strip shows one line per item,
// and the editor says so.
const CONTROL_CHARS = "\\u0000-\\u001f\\u007f-\\u009f\\u200b-\\u200f\\u202a-\\u202e\\u2060-\\u2069\\ufeff";
const CONTROL = new RegExp(`[${CONTROL_CHARS}]`, "g");
// A link is rejected outright (not cleaned) if it holds any of those or whitespace.
const HREF_BAD = new RegExp(`[${CONTROL_CHARS}\\s]`);
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** @param {unknown} v */
export function cleanText(v) {
  if (typeof v !== "string") return "";
  return v.replace(/[\r\n\t]+/g, " ").replace(CONTROL, "").replace(/\s+/g, " ").trim();
}

/**
 * A same-origin path ("/estate", "/dialpad/users") or an https URL, or null.
 * Rejects protocol-relative ("//host") and backslash ("/\\host") targets, and
 * every other scheme.
 * @param {unknown} v
 * @returns {{ ok: true, value: string | null } | { ok: false, error: string }}
 */
export function cleanHref(v) {
  if (v === undefined || v === null || v === "") return { ok: true, value: null };
  if (typeof v !== "string") return { ok: false, error: "Link must be text." };
  const raw = v.trim();
  const tooLong = { ok: /** @type {const} */ (false), error: `Link must be ${HREF_MAX} characters or fewer.` };
  if (raw.length > HREF_MAX) return tooLong;
  if (HREF_BAD.test(raw)) return { ok: false, error: "Link cannot contain spaces, control, zero-width or bidi characters." };
  if (raw.startsWith("/")) {
    if (raw.startsWith("//") || raw.startsWith("/\\")) return { ok: false, error: "Link must be a path on this site or an https URL." };
    return { ok: true, value: raw };
  }
  let url;
  try { url = new URL(raw); } catch { return { ok: false, error: "Link must be a path on this site or an https URL." }; }
  if (url.protocol !== "https:") return { ok: false, error: "Link must be a path on this site or an https URL." };
  // The stored value is the normalized URL (percent-encoded path, punycode
  // host), which can be longer than what was typed. The limit is on that.
  const value = url.toString();
  if (value.length > HREF_MAX) return tooLong;
  return { ok: true, value };
}

/** @param {unknown} v @returns {Date | null | undefined} undefined = invalid */
function parseDate(v) {
  if (v === undefined || v === null || v === "") return null;
  if (typeof v !== "string" && typeof v !== "number") return undefined;
  const d = new Date(v);
  return Number.isFinite(d.getTime()) ? d : undefined;
}

/**
 * Validate a create (partial = false) or update (partial = true) body.
 * @param {Record<string, unknown>} body
 * @param {{ partial?: boolean, current?: AnnouncementRow | null, now?: number }} [opts]
 * @returns {{ ok: true, value: Record<string, unknown> } | { ok: false, error: string, field: string }}
 */
export function validate(body, { partial = false, current = null, now = Date.now() } = {}) {
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return { ok: false, error: "Expected a JSON object.", field: "body" };
  }
  const known = new Set(["tone", "title", "body", "href", "startsAt", "endsAt"]);
  if (!partial) known.add("id");
  for (const k of Object.keys(body)) {
    if (!known.has(k)) return { ok: false, error: `Unknown field "${k}".`, field: k };
  }
  /** @type {Record<string, unknown>} */
  const out = {};

  // A create carries the id the editor generated, so a retry is recognised.
  if (!partial) {
    if (typeof body.id !== "string" || !UUID_RE.test(body.id)) {
      return { ok: false, error: "A create needs an id (a UUID). Reopen the editor and try again.", field: "form" };
    }
    out.id = body.id.toLowerCase();
  }

  if (!partial || "tone" in body) {
    const tone = body.tone === undefined && !partial ? "info" : body.tone;
    if (typeof tone !== "string" || !TONES.includes(tone)) return { ok: false, error: `Tone must be one of ${TONES.join(", ")}.`, field: "tone" };
    out.tone = tone;
  }
  if (!partial || "title" in body) {
    const title = cleanText(body.title);
    if (!title) return { ok: false, error: "Title is required.", field: "title" };
    if (title.length > TITLE_MAX) return { ok: false, error: `Title must be ${TITLE_MAX} characters or fewer.`, field: "title" };
    out.title = title;
  }
  if (!partial || "body" in body) {
    const text = cleanText(body.body);
    if (text.length > BODY_MAX) return { ok: false, error: `Body must be ${BODY_MAX} characters or fewer.`, field: "body" };
    out.body = text;
  }
  if (!partial || "href" in body) {
    const h = cleanHref(body.href);
    if (!h.ok) return { ok: false, error: h.error, field: "href" };
    out.href = h.value;
  }

  let starts = current ? new Date(current.starts_at) : new Date(now);
  let ends = current && current.ends_at ? new Date(current.ends_at) : null;
  if (!partial || "startsAt" in body) {
    const d = parseDate(body.startsAt);
    if (d === undefined) return { ok: false, error: "Start must be a date and time.", field: "startsAt" };
    starts = d || new Date(now);
    out.starts_at = starts;
  }
  if (!partial || "endsAt" in body) {
    const d = parseDate(body.endsAt);
    if (d === undefined) return { ok: false, error: "End must be a date and time.", field: "endsAt" };
    ends = d;
    out.ends_at = ends;
  }
  if (ends && ends.getTime() <= starts.getTime()) return { ok: false, error: "End must be after the start.", field: "endsAt" };
  if (starts.getTime() - now > MAX_WINDOW_MS) return { ok: false, error: "Start is more than a year out.", field: "startsAt" };
  if (ends && ends.getTime() - now > MAX_WINDOW_MS) return { ok: false, error: "End is more than a year out.", field: "endsAt" };
  return { ok: true, value: out };
}

/** @param {AnnouncementRow} r */
export function toApi(r) {
  return {
    id: r.id,
    tone: r.tone,
    title: r.title,
    body: r.body,
    href: r.href,
    startsAt: new Date(r.starts_at).toISOString(),
    endsAt: r.ends_at ? new Date(r.ends_at).toISOString() : null,
    expiredAt: r.expired_at ? new Date(r.expired_at).toISOString() : null,
    createdBy: r.created_by,
    createdAt: new Date(r.created_at).toISOString(),
    updatedBy: r.updated_by,
    updatedAt: new Date(r.updated_at).toISOString(),
  };
}

// The live/scheduled/expired state, worked out by the database clock (the same
// clock the feed's active-window read uses) so the Admin list and the feed never
// disagree. Select it as `state` next to the row.
export const STATE_SQL = `CASE
    WHEN expired_at IS NOT NULL OR (ends_at IS NOT NULL AND ends_at <= now()) THEN 'expired'
    WHEN starts_at > now() THEN 'scheduled'
    ELSE 'live' END AS state`;

/** @param {AnnouncementRow & { state?: string }} r @param {number} [now] */
export function stateOf(r, now = Date.now()) {
  if (r.state === "live" || r.state === "scheduled" || r.state === "expired") return r.state;
  if (r.expired_at) return "expired";
  if (r.ends_at && new Date(r.ends_at).getTime() <= now) return "expired";
  if (new Date(r.starts_at).getTime() > now) return "scheduled";
  return "live";
}

/**
 * The cached read of the announcements whose window is open now, and the write-side invalidation.
 * @param {{ db: { query: (text: string, params?: unknown[]) => Promise<{ rows: any[] }> } }} options
 */
export function createAnnouncements(options) {
  const { db } = options || /** @type {any} */ ({});
  if (!db || typeof db.query !== "function") throw new TypeError("createAnnouncements needs a db with query()");
/** @type {{ until: number, rows: AnnouncementRow[] } | null} */
let _active = null;
/** @type {Promise<AnnouncementRow[]> | null} */
let _activeInflight = null;
// Bumped by invalidate() so a read that started before a write never repopulates
// the cache with the pre-write rows.
let _gen = 0;

/**
 * The announcements whose window is open now, newest start first, capped.
 * Cached briefly (every open console polls the feed). The cache never outlives
 * a window boundary: it expires at the earliest of ACTIVE_TTL_MS, the first
 * cached row's end and the next scheduled start, and a hit re-checks each
 * row's end. A write drops this instance's cache at once. Another App Service
 * instance catches up within ACTIVE_TTL_MS (15 seconds), which is fine for a
 * manual edit.
 * @returns {Promise<AnnouncementRow[]>}
 */
async function listActive() {
  const now = Date.now();
  if (_active && now < _active.until) return _active.rows.filter((r) => isOpenAt(r, now));
  if (_activeInflight) return _activeInflight;
  const gen = _gen;
  _activeInflight = (async () => {
    try {
      const [active, upcoming] = await Promise.all([
        db.query(
          `SELECT * FROM announcements
            WHERE starts_at <= now() AND (ends_at IS NULL OR ends_at > now())
              AND expired_at IS NULL
            ORDER BY starts_at DESC, created_at DESC
            LIMIT ${ACTIVE_LIMIT}`
        ),
        db.query(
          `SELECT min(starts_at) AS next_start FROM announcements
            WHERE starts_at > now() AND expired_at IS NULL`
        ),
      ]);
      const rows = active.rows;
      let until = Date.now() + ACTIVE_TTL_MS;
      for (const r of rows) {
        if (r.ends_at) until = Math.min(until, new Date(r.ends_at).getTime());
      }
      const next = upcoming.rows[0]?.next_start;
      if (next) until = Math.min(until, new Date(next).getTime());
      if (gen === _gen) _active = { until, rows };
      return rows;
    } finally {
      if (gen === _gen) _activeInflight = null;
    }
  })();
  return _activeInflight;
}

/** @param {AnnouncementRow} r @param {number} now */
function isOpenAt(r, now) {
  return !r.expired_at && new Date(r.starts_at).getTime() <= now && (!r.ends_at || new Date(r.ends_at).getTime() > now);
}

function invalidate() {
  _gen += 1;
  _active = null;
  _activeInflight = null;
}

  return { listActive, invalidate };
}

/** An audit write that failed: the transaction rolls back and the caller gets a 503. */
class AuditUnavailable extends Error {
  constructor() {
    super("The audit log is unavailable, so the change was not saved. Try again.");
    this.status = 503;
  }
}

/**
 * The Announcements admin routes on a router the tool owns: list, create, edit, expire and delete, every one gated by
 * `manage` (reads included, because the list carries scheduled and expired rows nobody else sees) and every write
 * run in one transaction with its audit entry (audit.transaction), so there is never an unaudited change or an audit
 * entry for a change that did not commit. A create carries a client generated id, so a retried or double submitted
 * create returns the row it already made instead of publishing a duplicate.
 * @param {{ get: Function, post: Function, put: Function, delete: Function }} router an express Router
 * @param {{
 *   db: { query: (text: string, params?: unknown[]) => Promise<{ rows: any[] }> },
 *   audit: { transaction: (work: (client: any, record: (actor: any, action: string, target: string | null, details?: Record<string, unknown>, opts?: any) => Promise<unknown>) => Promise<any>) => Promise<any> },
 *   store: ReturnType<typeof createAnnouncements>,
 *   manage: Function,
 *   caller: (req: any) => { email?: string | null },
 *   log?: Pick<Console, "error">,
 * }} options
 */
export function announcementRoutes(router, options) {
  const { db, audit, store, manage, caller: identify } = options;
  const log = options.log || console;

const LIST_LIMIT = 200;
const NOT_FOUND = { error: "Announcement not found" };
const COLS = `*, ${STATE_SQL}`;

/** @param {AnnouncementRow & { state?: string }} r */
function shape(r) {
  return { ...toApi(r), state: stateOf(r) };
}

/** @typedef {(actor: AuditActor, action: string, target: string | null, details?: Record<string, unknown>, opts?: AuditWriteOpts) => Promise<unknown>} AuditRecord */

/**
 * Run `work` in one transaction with its audit entries. `auditOrThrow` must be
 * called with the `record` it is handed. A thrown error or a returned
 * `{ rollback: true }` rolls back. The announcements cache is dropped only
 * after a commit.
 * @template T
 * @param {(client: any, record: AuditRecord) => Promise<T>} work
 * @returns {Promise<T>}
 */
async function inTransaction(work) {
  const out = await audit.transaction(work);
  if (!(out && typeof out === "object" && /** @type {{ rollback?: boolean }} */ (out).rollback)) store.invalidate();
  return out;
}

/**
 * @param {any} client @param {string} id
 * @returns {Promise<(AnnouncementRow & { state: string }) | null>}
 */
async function lockOne(client, id) {
  const { rows } = await client.query(`SELECT ${COLS} FROM announcements WHERE id = $1 FOR UPDATE`, [id]);
  return rows[0] || null;
}

/**
 * Write the audit entry through the transaction, or throw so it rolls back.
 * @param {AuditRecord} record
 * @param {Parameters<AuditRecord>} args
 */
async function auditOrThrow(record, ...args) {
  try {
    await record(...args);
  } catch (e) {
    log.error("[announcements] audit write failed, rolling back:", /** @type {Error} */ (e).message);
    throw new AuditUnavailable();
  }
}

// CHECK constraints by the names PostgreSQL gives them in 0005_announcements.sql
// (column checks are <table>_<column>_check, the table-level window check is
// announcements_check), mapped to the field and message the editor shows.
/** @type {Record<string, { field: string, error: string }>} */
const CHECKS = {
  announcements_check: { field: "endsAt", error: "End must be after the start." },
  announcements_href_check: { field: "href", error: `Link must be a path on this site or an https URL of ${HREF_MAX} characters or fewer.` },
  announcements_title_check: { field: "title", error: `Title must be 1 to ${TITLE_MAX} characters.` },
  announcements_body_check: { field: "body", error: `Body must be ${BODY_MAX} characters or fewer.` },
  announcements_tone_check: { field: "tone", error: `Tone must be one of ${TONES.join(", ")}.` },
};

/** @param {unknown} e @param {any} res @param {(err?: unknown) => void} next */
function fail(e, res, next) {
  if (e instanceof AuditUnavailable) return res.status(503).json({ error: e.message });
  // A CHECK constraint the route-level validation did not catch (a concurrent
  // edit changed the other half of the window): the caller's input, not a 500.
  const pg = /** @type {{ code?: string, constraint?: string }} */ (e);
  if (pg?.code === "23514") {
    const hit = CHECKS[pg.constraint || ""];
    if (hit) return res.status(400).json({ error: hit.error, details: { field: hit.field } });
    return res.status(400).json({ error: "The announcement did not pass a database check.", details: { field: "form" } });
  }
  return next(e);
}

// GET / - every announcement, newest first (live, scheduled and expired).
router.get("/", manage, async (_req, res, next) => {
  try {
    const { rows } = await db.query(
      `SELECT ${COLS} FROM announcements ORDER BY starts_at DESC, created_at DESC LIMIT ${LIST_LIMIT}`
    );
    res.json({ announcements: rows.map(shape) });
  } catch (e) { next(e); }
});

// POST / - create. startsAt empty = now, endsAt empty = until expired by hand.
// `id` is a UUID the editor generates once per new announcement and resends on
// a retry. The first request inserts it (201). A repeat by the same operator
// returns the row it made (200) with no second insert or audit entry. The same
// id from anyone else is a 409.
router.post("/", manage, async (req, res, next) => {
  try {
    const v = validate(req.body);
    if (!v.ok) return res.status(400).json({ error: v.error, details: { field: v.field } });
    const caller = identify(req);
    const by = caller.email || null;
    const x = v.value;
    const out = await inTransaction(async (client, record) => {
      const { rows } = await client.query(
        `INSERT INTO announcements (id, tone, title, body, href, starts_at, ends_at, created_by, updated_by)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $8)
         ON CONFLICT (id) DO NOTHING RETURNING ${COLS}`,
        [x.id, x.tone, x.title, x.body, x.href, x.starts_at, x.ends_at, by]
      );
      const created = rows[0];
      if (!created) {
        const existing = await lockOne(client, /** @type {string} */ (x.id));
        if (existing && by && existing.created_by === by) return { rollback: true, status: 200, body: shape(existing) };
        return { rollback: true, status: 409, body: { error: "That announcement id is already in use. Reopen the editor and try again.", details: { field: "form" } } };
      }
      await auditOrThrow(record, caller, "announcements:create", `announcement:${created.id}`, {}, { req, after: toApi(created) });
      return { status: 201, body: shape(created) };
    });
    res.status(out.status).json(out.body);
  } catch (e) { fail(e, res, next); }
});

// PUT /:id - partial update of any field. Validation runs against the locked row.
router.put("/:id", manage, async (req, res, next) => {
  try {
    const id = String(req.params.id || "");
    if (!UUID_RE.test(id)) return res.status(404).json(NOT_FOUND);
    const caller = identify(req);
    const out = await inTransaction(async (client, record) => {
      const current = await lockOne(client, id);
      if (!current) return { rollback: true, status: 404, body: NOT_FOUND };
      const v = validate(req.body, { partial: true, current });
      if (!v.ok) return { rollback: true, status: 400, body: { error: v.error, details: { field: v.field } } };
      const cols = Object.keys(v.value);
      if (cols.length === 0) return { rollback: true, status: 200, body: shape(current) };
      const sets = cols.map((c, i) => `${c} = $${i + 2}`);
      const { rows } = await client.query(
        `UPDATE announcements SET ${sets.join(", ")}, updated_by = $${cols.length + 2}, updated_at = now()
          WHERE id = $1 RETURNING ${COLS}`,
        [id, ...cols.map((c) => v.value[c]), caller.email || null]
      );
      const row = rows[0];
      await auditOrThrow(record, caller, "announcements:update", `announcement:${id}`, { fields: cols }, { req, before: toApi(current), after: toApi(row) });
      return { status: 200, body: shape(row) };
    });
    res.status(out.status).json(out.body);
  } catch (e) { fail(e, res, next); }
});

// POST /:id/expire - take it off every console now. The schedule the operator
// set is kept as it was. expired_at records when it was ended by hand.
router.post("/:id/expire", manage, async (req, res, next) => {
  try {
    const id = String(req.params.id || "");
    if (!UUID_RE.test(id)) return res.status(404).json(NOT_FOUND);
    const caller = identify(req);
    const out = await inTransaction(async (client, record) => {
      const current = await lockOne(client, id);
      if (!current) return { rollback: true, status: 404, body: NOT_FOUND };
      if (current.state === "expired") return { rollback: true, status: 200, body: shape(current) };
      const { rows } = await client.query(
        `UPDATE announcements SET expired_at = now(), updated_by = $2, updated_at = now()
          WHERE id = $1 RETURNING ${COLS}`,
        [id, caller.email || null]
      );
      const row = rows[0];
      await auditOrThrow(record, caller, "announcements:expire", `announcement:${id}`, {}, { req, before: toApi(current), after: toApi(row) });
      return { status: 200, body: shape(row) };
    });
    res.status(out.status).json(out.body);
  } catch (e) { fail(e, res, next); }
});

// DELETE /:id - remove a row entirely (a mistake, not an expiry).
router.delete("/:id", manage, async (req, res, next) => {
  try {
    const id = String(req.params.id || "");
    if (!UUID_RE.test(id)) return res.status(404).json(NOT_FOUND);
    const caller = identify(req);
    const out = await inTransaction(async (client, record) => {
      const current = await lockOne(client, id);
      if (!current) return { rollback: true, status: 404 };
      await client.query("DELETE FROM announcements WHERE id = $1", [id]);
      await auditOrThrow(record, caller, "announcements:delete", `announcement:${id}`, {}, { req, before: toApi(current) });
      return { status: 204 };
    });
    if (out.status === 404) return res.status(404).json(NOT_FOUND);
    res.status(204).end();
  } catch (e) { fail(e, res, next); }
});
}
