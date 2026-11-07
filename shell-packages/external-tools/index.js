// shell-packages/external-tools: tools that do not live in the shell's repository (a dashboard first), kept in data
// and shown in the tool launcher after the modules. Validation, row mapping, who may see a tool, and the audited
// admin routes.
//
// Visibility is display only. An external tool keeps enforcing its own access, so hiding a tool from someone never
// grants or removes anything there.
//
// Audience, chosen per tool and never "everyone":
//   permission - the caller holds that console permission (the console RBAC, wildcard included)
//   group      - the caller is a member of that directory group, resolved on the server
// Any failure (permission read, group lookup, database) fails closed: the tool is not shown.
//
// Schema: console_external_tools(id text pk '^[a-z0-9][a-z0-9-]{0,63}$', name text 1..60 printable ASCII without < >,
// url text https only with no user info 9..300, icon text default 'ExternalLink', hue text default 'brand', tagline
// text <= 120, description text <= 400, sort_order int 0..100000, enabled bool default true, audience_kind text
// in (group, permission), group_id text null or a GUID, permission text null or tab:<name> or action:<name>:<verb>,
// group_label text null <= 120, created_by, created_at, updated_by, updated_at). The route checks every rule first;
// CHECK constraints on the table are the backstop (a 23514 answers 400, a duplicate id 23505 answers 409).

/** The hues a tool may use: the same list as console-modules HUES (a test holds them equal). */
export const HUES = ["brand", "amber", "blue", "green", "red", "teal", "violet"];

export const ID_RE = /^[a-z0-9][a-z0-9-]{0,63}$/;
const ICON_RE = /^[A-Z][A-Za-z0-9]{1,40}$/;
export const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const PRINTABLE = /^[\x20-\x7e]*$/;

const NAME_MAX = 60;
const URL_MAX = 300;
const TAGLINE_MAX = 120;
const DESCRIPTION_MAX = 400;
const GROUP_LABEL_MAX = 120;
export const ORDER_MAX = 100000;
export const MAX_TOOLS = 50;
const KINDS = ["group", "permission"];
const FIELDS = ["id", "name", "url", "icon", "hue", "tagline", "description", "order", "enabled", "audience"];

/** A failed validation: answered 400 with the field the editor highlights. */
export class Invalid extends Error {
  /** @param {string} field @param {string} message */
  constructor(field, message) {
    super(message);
    this.field = field;
  }
}

/** @param {unknown} v @returns {v is Record<string, any>} */
const isObj = (v) => !!v && typeof v === "object" && !Array.isArray(v);

/**
 * Plain printable ASCII text, trimmed, no markup brackets.
 * @param {unknown} v @param {string} field @param {number} max @param {boolean} required
 * @returns {string}
 */
function plain(v, field, max, required) {
  if (v === undefined || v === null || v === "") {
    if (required) throw new Invalid(field, `${field} is required.`);
    return "";
  }
  if (typeof v !== "string") throw new Invalid(field, `${field} must be text.`);
  const s = v.trim();
  if (!PRINTABLE.test(s)) throw new Invalid(field, `${field} must be plain ASCII text.`);
  if (/[<>]/.test(s)) throw new Invalid(field, `${field} must be plain text, without < or >.`);
  if (s.length > max) throw new Invalid(field, `${field} must be ${max} characters or fewer.`);
  if (!s.length && required) throw new Invalid(field, `${field} is required.`);
  return s;
}

/** @param {unknown} v @returns {string} */
function toolUrl(v) {
  const field = "url";
  if (typeof v !== "string" || !v.length || v.length > URL_MAX || !/^[!-~]+$/.test(v)) throw new Invalid(field, `url must be an https URL of ${URL_MAX} characters or fewer.`);
  if (!v.toLowerCase().startsWith("https://")) throw new Invalid(field, "url must be an https URL.");
  let u;
  try { u = new URL(v); } catch { throw new Invalid(field, "url must be an https URL."); }
  if (u.protocol !== "https:" || !u.hostname) throw new Invalid(field, "url must be an https URL.");
  // No credentials in the URL, checked on the raw text as well so nothing hides in the parse.
  if (u.username || u.password || /^https:\/\/[^/?#]*@/i.test(v)) throw new Invalid(field, "url must not carry a user name or password.");
  return v;
}

/**
 * @param {unknown} a @param {Iterable<string>} permissionIds
 * @returns {{ kind: "group", groupId: string, groupLabel: string | null } | { kind: "permission", permission: string }}
 */
function audience(a, permissionIds) {
  if (!isObj(a)) throw new Invalid("audience", "audience is required: choose an Entra group or a console permission.");
  for (const k of Object.keys(a)) if (!["kind", "groupId", "groupLabel", "permission"].includes(k)) throw new Invalid(`audience.${k}`, `Unknown field ${k}.`);
  if (typeof a.kind !== "string" || !KINDS.includes(a.kind)) throw new Invalid("audience.kind", "audience.kind must be group or permission.");
  if (a.kind === "group") {
    if (a.permission !== undefined && a.permission !== null) throw new Invalid("audience.permission", "A group audience carries no permission.");
    if (typeof a.groupId !== "string" || !UUID_RE.test(a.groupId)) throw new Invalid("audience.groupId", "audience.groupId must be the Entra group object id (a GUID).");
    const label = plain(a.groupLabel, "audience.groupLabel", GROUP_LABEL_MAX, false);
    return { kind: "group", groupId: a.groupId.toLowerCase(), groupLabel: label || null };
  }
  if (a.groupId !== undefined && a.groupId !== null) throw new Invalid("audience.groupId", "A permission audience carries no group.");
  if (a.groupLabel !== undefined && a.groupLabel !== null && a.groupLabel !== "") throw new Invalid("audience.groupLabel", "A permission audience carries no group label.");
  if (typeof a.permission !== "string" || !a.permission.length) throw new Invalid("audience.permission", "audience.permission is required.");
  const known = new Set(permissionIds);
  if (!known.has(a.permission)) throw new Invalid("audience.permission", "audience.permission must be a console permission id from the registry.");
  return { kind: "permission", permission: a.permission };
}

/**
 * Validate a full tool body (create, or update where the id comes from the path).
 * @param {unknown} body
 * @param {{ id?: string, permissionIds: Iterable<string>, hues?: readonly string[] }} o id fixed by the path (the body may repeat it); permissionIds are the console permission ids an audience may name; hues the allowed hues (default HUES)
 */
export function validateTool(body, o) {
  const hues = o.hues || HUES;
  if (!isObj(body)) throw new Invalid("form", "Send the tool as a JSON object.");
  for (const k of Object.keys(body)) if (!FIELDS.includes(k)) throw new Invalid(k, `Unknown field ${k}.`);
  const id = o.id !== undefined ? o.id : body.id;
  if (typeof id !== "string" || !ID_RE.test(id)) throw new Invalid("id", "id must be a lowercase slug of letters, digits and hyphens, up to 64 characters.");
  if (o.id !== undefined && body.id !== undefined && body.id !== o.id) throw new Invalid("id", "id cannot be changed.");
  const name = plain(body.name, "name", NAME_MAX, true);
  const url = toolUrl(body.url);
  const icon = body.icon === undefined || body.icon === null ? "ExternalLink" : body.icon;
  if (typeof icon !== "string" || !ICON_RE.test(icon)) throw new Invalid("icon", "icon must be an icon name.");
  const hue = body.hue === undefined || body.hue === null ? "brand" : body.hue;
  if (typeof hue !== "string" || !hues.includes(hue)) throw new Invalid("hue", `hue must be one of ${hues.join(", ")}.`);
  const tagline = plain(body.tagline, "tagline", TAGLINE_MAX, false);
  const description = plain(body.description, "description", DESCRIPTION_MAX, false);
  let order = 0;
  if (body.order !== undefined && body.order !== null) {
    if (typeof body.order !== "number" || !Number.isInteger(body.order) || body.order < 0 || body.order > ORDER_MAX) throw new Invalid("order", `order must be a whole number from 0 to ${ORDER_MAX}.`);
    order = body.order;
  }
  if (body.enabled !== undefined && typeof body.enabled !== "boolean") throw new Invalid("enabled", "enabled must be true or false.");
  const enabled = body.enabled === undefined ? true : body.enabled;
  return { id, name, url, icon, hue, tagline, description, order, enabled, audience: audience(body.audience, o.permissionIds) };
}

/** @typedef {ReturnType<typeof validateTool>} ToolInput */

/** @param {Record<string, any>} r a console_external_tools row */
export function toTool(r) {
  return {
    id: r.id, name: r.name, url: r.url, icon: r.icon, hue: r.hue, tagline: r.tagline, description: r.description,
    order: r.sort_order, enabled: r.enabled,
    audience: r.audience_kind === "group"
      ? { kind: "group", groupId: r.group_id, groupLabel: r.group_label || null }
      : { kind: "permission", permission: r.permission },
    createdBy: r.created_by || null, createdAt: r.created_at || null, updatedBy: r.updated_by || null, updatedAt: r.updated_at || null,
  };
}

/** What the launcher gets: no audience, no group id, no audit fields. @param {ReturnType<typeof toTool>} t */
export function publicTool(t) {
  return { id: t.id, name: t.name, url: t.url, icon: t.icon, hue: t.hue, tagline: t.tagline, description: t.description, order: t.order };
}

/** The audit snapshot of a tool (no timestamps). @param {ReturnType<typeof toTool> | null} t */
export function auditShape(t) {
  if (!t) return null;
  const { createdAt: _c, updatedAt: _u, ...rest } = t;
  return rest;
}

// -- Who may see a tool ------------------------------------------------------------------------
// Visibility is decided on the server, failing closed: any failure of the permission read or the group lookup
// means the tool is not shown. The two lookups are the consumer's: `callerGroups(wanted)` answers the subset of
// the wanted lowercase group object ids the caller is in (the groups in the signed in token, then the consumer's
// group resolver), and `callerHasPermission(permission)` answers whether the console RBAC grants it, wildcard
// included.

/**
 * The tools this caller may see: enabled, and the audience satisfied. Fails closed per tool.
 * @param {ReturnType<typeof toTool>[]} tools
 * @param {{
 *   callerGroups: (wanted: string[]) => Promise<Set<string>>,
 *   callerHasPermission: (permission: string) => Promise<boolean>,
 *   log?: Pick<Console, "error">,
 * }} o
 */
export async function visibleTools(tools, o) {
  const log = o.log || console;
  const on = tools.filter((t) => t.enabled);
  const wanted = [...new Set(on.filter((t) => t.audience.kind === "group").map((t) => /** @type {string} */ (/** @type {any} */ (t.audience).groupId).toLowerCase()))];
  /** @type {Set<string>} */
  let groups = new Set();
  if (wanted.length) {
    try { groups = await o.callerGroups(wanted); } catch (e) { log.error("[external-tools] group lookup failed:", /** @type {Error} */ (e).message); }
  }
  /** @type {Map<string, boolean>} */
  const perms = new Map();
  const out = [];
  for (const t of on) {
    const a = /** @type {any} */ (t.audience);
    let ok = false;
    if (a.kind === "group") ok = groups.has(String(a.groupId).toLowerCase());
    else if (a.kind === "permission") {
      if (!perms.has(a.permission)) {
        let held = false;
        try { held = (await o.callerHasPermission(a.permission)) === true; } catch (e) { log.error("[external-tools] permission read failed:", /** @type {Error} */ (e).message); }
        perms.set(a.permission, held);
      }
      ok = perms.get(a.permission) === true;
    }
    if (ok) out.push(t);
  }
  return out.sort((x, y) => x.order - y.order || x.id.localeCompare(y.id)).map(publicTool);
}

/** @typedef {{ query: (text: string, params?: unknown[]) => Promise<{ rows: any[] }> }} Q */

/** An audit write that failed: the transaction rolls back and the caller gets a 503. */
class AuditUnavailable extends Error {
  constructor() {
    super("The audit log is unavailable, so the change was not saved. Try again.");
  }
}

/**
 * @param {Pick<Console, "error">} log
 * @param {(...a: any[]) => Promise<unknown>} record
 * @param {any[]} args
 */
async function auditOrThrow(log, record, ...args) {
  try {
    await record(...args);
  } catch (e) {
    log.error("[console] external tools audit write failed, rolling back:", /** @type {Error} */ (e).message);
    throw new AuditUnavailable();
  }
}

/**
 * The admin and launcher routes on a router the tool owns.
 *
 *   GET    /mine     signed in. Only the tools this caller may see: enabled and the audience satisfied on the
 *                    server, failing closed on any lookup error. No audience detail leaves the server.
 *   GET    /         every tool with its audience, plus the console permissions an audience may name.
 *   POST   /         create.   PUT /order  reorder.   PUT /:id  replace.   DELETE /:id  delete.
 *
 * Every admin route is behind `manage` (the consumer's permission check). Every write runs in one transaction with
 * its audit entry (before and after), so an audit failure rolls the change back and answers 503.
 * @param {{ get: Function, post: Function, put: Function, delete: Function }} router an express Router
 * @param {{
 *   db: Q,
 *   audit: { transaction: (work: (client: any, record: (...a: any[]) => Promise<unknown>) => Promise<any>) => Promise<any> },
 *   manage: Function,
 *   caller: (req: any) => { email?: string | null },
 *   permissions: () => Array<{ id: string, label?: string }>,
 *   callerGroups: (req: any, wanted: string[]) => Promise<Set<string>>,
 *   callerHasPermission: (req: any, permission: string) => Promise<boolean>,
 *   log?: Pick<Console, "error">,
 * }} o
 */
export function externalToolRoutes(router, o) {
  const { db, audit, manage, caller: identify } = o;
  const log = o.log || console;
  const permissionList = () => o.permissions().map((e) => ({ id: e.id, label: e.label || e.id }));
  const permissionIds = () => o.permissions().map((e) => e.id);

/** @param {unknown} e @param {any} res @param {any} next */
function fail(e, res, next) {
  if (e instanceof Invalid) return res.status(400).json({ error: e.message, details: { field: e.field } });
  if (e instanceof AuditUnavailable) return res.status(503).json({ error: e.message });
  const pg = /** @type {{ code?: string }} */ (e);
  if (pg?.code === "23505") return res.status(409).json({ error: "A tool with that id already exists.", details: { field: "id" } });
  if (pg?.code === "23514") return res.status(400).json({ error: "The change did not pass a database check.", details: { field: "form" } });
  return next(e);
}

/** @param {any} req @returns {string | null} */
function actorEmail(req) {
  const c = identify(req);
  return c && c.email ? String(c.email).toLowerCase().slice(0, 320) : null;
}


/** @param {Q} q @param {string} [id] */
async function readTools(q, id) {
  const sql = "SELECT * FROM console_external_tools" + (id ? " WHERE id = $1" : "") + " ORDER BY sort_order, id";
  const { rows } = await q.query(sql, id ? [id] : []);
  return rows.map(toTool);
}

const COLS = "name, url, icon, hue, tagline, description, sort_order, enabled, audience_kind, group_id, permission, group_label";
/** @param {ReturnType<typeof validateTool>} t @returns {unknown[]} */
function params(t) {
  const a = /** @type {any} */ (t.audience);
  return [t.name, t.url, t.icon, t.hue, t.tagline, t.description, t.order, t.enabled, a.kind,
    a.kind === "group" ? a.groupId : null, a.kind === "permission" ? a.permission : null, a.kind === "group" ? a.groupLabel : null];
}

router.get("/mine", async (req, res) => {
  res.set("Cache-Control", "private, no-store");
  let tools;
  try {
    tools = await readTools(db);
  } catch (e) {
    log.error("[console] external tools read failed:", /** @type {Error} */ (e).message);
    return res.status(503).json({ error: "External tools are unavailable." });
  }
  try {
    return res.json({ tools: await visibleTools(tools, { callerGroups: (wanted) => o.callerGroups(req, wanted), callerHasPermission: (p) => o.callerHasPermission(req, p), log }) });
  } catch (e) {
    // Fail closed: nothing is shown when the audience cannot be decided.
    log.error("[console] external tools audience failed:", /** @type {Error} */ (e).message);
    return res.json({ tools: [] });
  }
});

router.get("/", manage, async (_req, res, next) => {
  try {
    res.set("Cache-Control", "private, no-store");
    // The console permissions an audience can name, from the registry (the admin picker's list).
    res.json({ tools: await readTools(db), permissions: permissionList() });
  } catch (e) { next(e); }
});

router.post("/", manage, async (req, res, next) => {
  try {
    const t = validateTool(req.body, { permissionIds: permissionIds() });
    const caller = identify(req);
    const actor = actorEmail(req);
    const out = await audit.transaction(async (client, record) => {
      const { rows } = await client.query("SELECT count(*)::int AS n FROM console_external_tools");
      if ((rows[0]?.n || 0) >= MAX_TOOLS) return { rollback: true, status: 400, body: { error: `At most ${MAX_TOOLS} external tools.`, details: { field: "form" } } };
      await client.query(
        `INSERT INTO console_external_tools (id, ${COLS}, created_by, updated_by, created_at, updated_at)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $14, clock_timestamp(), clock_timestamp())`,
        [t.id, ...params(t), actor]
      );
      const [after] = await readTools(client, t.id);
      await auditOrThrow(log, record, caller, "console:external-tool-create", `external-tool:${t.id}`, {}, { req, after: auditShape(after || null) });
      return { status: 201, body: after };
    });
    res.status(out.status).json(out.body);
  } catch (e) { fail(e, res, next); }
});

// PUT /order - { ids: [...] } places those tools first in that order (10, 20, ...).
router.put("/order", manage, async (req, res, next) => {
  try {
    const body = req.body && typeof req.body === "object" ? req.body : {};
    for (const k of Object.keys(body)) if (k !== "ids") throw new Invalid(k, `Unknown field ${k}.`);
    const ids = body.ids;
    if (!Array.isArray(ids) || !ids.length || ids.length > MAX_TOOLS || ids.some((i) => typeof i !== "string" || !ID_RE.test(i))) {
      throw new Invalid("ids", "ids must be a list of tool ids.");
    }
    if (new Set(ids).size !== ids.length) throw new Invalid("ids", "ids must not repeat.");
    const caller = identify(req);
    const actor = actorEmail(req);
    const out = await audit.transaction(async (client, record) => {
      const before = await readTools(client);
      const have = new Set(before.map((t) => t.id));
      const unknown = ids.filter((i) => !have.has(i));
      if (unknown.length) return { rollback: true, status: 404, body: { error: "Unknown tool", details: { field: "ids" } } };
      for (let i = 0; i < ids.length; i += 1) {
        await client.query("UPDATE console_external_tools SET sort_order = $2, updated_by = $3, updated_at = clock_timestamp() WHERE id = $1", [ids[i], (i + 1) * 10, actor]);
      }
      const after = await readTools(client);
      await auditOrThrow(log, record, caller, "console:external-tool-reorder", "external-tools", { ids },
        { req, before: before.map((t) => ({ id: t.id, order: t.order })), after: after.map((t) => ({ id: t.id, order: t.order })) });
      return { status: 200, body: { tools: after } };
    });
    res.status(out.status).json(out.body);
  } catch (e) { fail(e, res, next); }
});

router.put("/:id", manage, async (req, res, next) => {
  try {
    const id = String(req.params.id || "");
    if (!ID_RE.test(id)) return res.status(404).json({ error: "Tool not found" });
    const t = validateTool(req.body, { id, permissionIds: permissionIds() });
    const caller = identify(req);
    const actor = actorEmail(req);
    const out = await audit.transaction(async (client, record) => {
      const { rows } = await client.query("SELECT * FROM console_external_tools WHERE id = $1 FOR UPDATE", [id]);
      if (!rows[0]) return { rollback: true, status: 404, body: { error: "Tool not found" } };
      const before = toTool(rows[0]);
      await client.query(
        `UPDATE console_external_tools SET name = $2, url = $3, icon = $4, hue = $5, tagline = $6, description = $7,
           sort_order = $8, enabled = $9, audience_kind = $10, group_id = $11, permission = $12, group_label = $13,
           updated_by = $14, updated_at = clock_timestamp() WHERE id = $1`,
        [id, ...params(t), actor]
      );
      const [after] = await readTools(client, id);
      await auditOrThrow(log, record, caller, "console:external-tool-update", `external-tool:${id}`, {},
        { req, before: auditShape(before), after: auditShape(after || null) });
      return { status: 200, body: after };
    });
    res.status(out.status).json(out.body);
  } catch (e) { fail(e, res, next); }
});

router.delete("/:id", manage, async (req, res, next) => {
  try {
    const id = String(req.params.id || "");
    if (!ID_RE.test(id)) return res.status(404).json({ error: "Tool not found" });
    const caller = identify(req);
    const out = await audit.transaction(async (client, record) => {
      const { rows } = await client.query("SELECT * FROM console_external_tools WHERE id = $1 FOR UPDATE", [id]);
      if (!rows[0]) return { rollback: true, status: 404, body: { error: "Tool not found" } };
      const before = toTool(rows[0]);
      await client.query("DELETE FROM console_external_tools WHERE id = $1", [id]);
      await auditOrThrow(log, record, caller, "console:external-tool-delete", `external-tool:${id}`, {}, { req, before: auditShape(before) });
      return { status: 200, body: { ok: true } };
    });
    res.status(out.status).json(out.body);
  } catch (e) { fail(e, res, next); }
});
}
