// shell-packages/external-tools: every field's validation, the audience rules, who sees a tool in GET /mine
// (permission, group, fail closed on a failed group read), the gating of the admin routes, audited writes with
// before and after, reorder and delete, on an in-memory table. Synthetic data only.
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import express from "express";
import { HUES as CORE_HUES } from "../../../shell-packages/console-modules/index.js";
import { HUES, validateTool, toTool, publicTool, auditShape, visibleTools, externalToolRoutes, Invalid, MAX_TOOLS, ID_RE } from "../../../shell-packages/external-tools/index.js";

const G1 = "11111111-1111-4111-8111-111111111111";
const G2 = "22222222-2222-4222-8222-222222222222";

/** @type {Map<string, any>} */
let ROWS = new Map();
/** @type {any[]} */
const AUDITS = [];
let TICK = 0;
let DB_DOWN = false;
let AUDIT_DOWN = false;
/** @type {any} */ let SNAP = null;
/** @type {any[]} */ let STAGED = [];

/** @param {string} sql @param {any[]} p */
async function fake(sql, p = []) {
  const q = sql.replace(/\s+/g, " ").trim();
  if (DB_DOWN) throw new Error("db down");
  if (/^SELECT \* FROM console_external_tools WHERE id = \$1/.test(q)) return { rows: ROWS.has(p[0]) ? [{ ...ROWS.get(p[0]) }] : [] };
  if (/^SELECT \* FROM console_external_tools ORDER BY/.test(q)) return { rows: [...ROWS.values()].sort((a, b) => a.sort_order - b.sort_order || a.id.localeCompare(b.id)).map((r) => ({ ...r })) };
  if (/^SELECT count\(\*\)/.test(q)) return { rows: [{ n: ROWS.size }] };
  if (/^INSERT INTO console_external_tools/.test(q)) {
    if (ROWS.has(p[0])) throw Object.assign(new Error("dup"), { code: "23505" });
    ROWS.set(p[0], {
      id: p[0], name: p[1], url: p[2], icon: p[3], hue: p[4], tagline: p[5], description: p[6], sort_order: p[7], enabled: p[8],
      audience_kind: p[9], group_id: p[10], permission: p[11], group_label: p[12], created_by: p[13], updated_by: p[13],
      created_at: `t${++TICK}`, updated_at: `t${TICK}`,
    });
    return { rows: [] };
  }
  if (/^UPDATE console_external_tools SET name/.test(q)) {
    Object.assign(ROWS.get(p[0]), {
      name: p[1], url: p[2], icon: p[3], hue: p[4], tagline: p[5], description: p[6], sort_order: p[7], enabled: p[8],
      audience_kind: p[9], group_id: p[10], permission: p[11], group_label: p[12], updated_by: p[13], updated_at: `t${++TICK}`,
    });
    return { rows: [] };
  }
  if (/^UPDATE console_external_tools SET sort_order/.test(q)) { Object.assign(ROWS.get(p[0]), { sort_order: p[1], updated_by: p[2] }); return { rows: [] }; }
  if (/^DELETE FROM console_external_tools WHERE id = \$1/.test(q)) { ROWS.delete(p[0]); return { rows: [] }; }
  throw new Error(`unexpected SQL in the fake: ${q.slice(0, 120)}`);
}
const db = { query: fake };
/** A transaction that stages its audit entries until commit and restores the rows on rollback. */
const audit = {
  async transaction(/** @type {Function} */ work) {
    SNAP = new Map([...ROWS].map(([k, v]) => [k, { ...v }])); STAGED = [];
    try {
      const out = await work({ query: fake }, async (/** @type {any} */ actor, /** @type {string} */ action, /** @type {string | null} */ target, /** @type {any} */ details, /** @type {any} */ opts) => {
        if (AUDIT_DOWN) throw new Error("audit down");
        STAGED.push({ actor: actor.email, action, target, details: { ...details, before: opts && opts.before, after: opts && opts.after } });
      });
      if (out && out.rollback) ROWS = SNAP; else AUDITS.push(...STAGED);
      return out;
    } catch (e) { ROWS = SNAP; throw e; }
  },
};

/** @type {any} */
let CALLER = { email: "synthetic.admin@example.com", name: "Synthetic Admin", oid: "oid-1", groups: [], roles: [] };
/** @type {Set<string>} */
let PERMS = new Set();
let PERM_ERROR = false;
/** @type {string[] | null} */
let LIVE_GROUPS = [];
let LIVE_CALLS = 0;
const LOOKUP = { fn: async () => { LIVE_CALLS += 1; return LIVE_GROUPS === null ? [] : LIVE_GROUPS; } };
const REGISTRY = [{ id: "tab:home", label: "Home" }, { id: "tab:estate", label: "Estate" }, { id: "action:console:external-tools", label: "External tools" }, { id: "tab:console-admin" }];

// What a consumer wires: the groups in the token first, then its own resolver (a failed lookup is not a crash).
async function callerGroups(/** @type {any} */ req, /** @type {string[]} */ wanted) {
  /** @type {Set<string>} */
  const held = new Set();
  for (const g of Array.isArray(req.user.groups) ? req.user.groups : []) if (wanted.includes(String(g).toLowerCase())) held.add(String(g).toLowerCase());
  const oid = typeof req.user.oid === "string" ? req.user.oid : "";
  if (wanted.every((g) => held.has(g)) || !oid) return held;
  try { for (const g of await LOOKUP.fn()) if (wanted.includes(String(g).toLowerCase())) held.add(String(g).toLowerCase()); } catch { /* fail closed to what the token proves */ }
  return held;
}
const router = express.Router();
const quiet = { error() {} };
externalToolRoutes(router, {
  db, audit, log: quiet,
  manage: (/** @type {any} */ _req, /** @type {any} */ res, /** @type {any} */ next) => (PERMS.has("*") || PERMS.has("action:console:external-tools") ? next() : res.status(403).json({ error: "Forbidden" })),
  caller: () => CALLER,
  permissions: () => REGISTRY,
  callerGroups,
  callerHasPermission: async (_req, p) => { if (PERM_ERROR) throw new Error("rbac down"); return PERMS.has("*") || PERMS.has(p); },
});

/**
 * @param {string} method @param {string} url @param {any} [body]
 * @returns {Promise<{ status: number, body: any, headers: Record<string, string> }>}
 */
function api(method, url, body) {
  return new Promise((resolve, reject) => {
    /** @type {any} */
    const req = { method, url, originalUrl: url, path: url, headers: {}, body: body === undefined ? {} : body, query: {}, params: {}, get: () => "", user: CALLER };
    /** @type {any} */
    const res = {
      statusCode: 200, headers: {},
      status(/** @type {number} */ c) { this.statusCode = c; return this; },
      json(/** @type {any} */ b) { resolve({ status: this.statusCode, body: b, headers: this.headers }); return this; },
      set(/** @type {string} */ k, /** @type {string} */ v) { this.headers[k] = v; return this; },
      setHeader() {}, end() { resolve({ status: this.statusCode, body: null, headers: this.headers }); },
    };
    /** @type {any} */ (router).handle(req, res, (/** @type {any} */ err) => (err ? reject(err) : resolve({ status: 404, body: null, headers: {} })));
  });
}

const ADMIN = "action:console:external-tools";

/** @param {Record<string, any>} [over] */
const tool = (over = {}) => ({
  id: "grafana", name: "Grafana", url: "https://grafana.example.invalid/", icon: "Gauge", hue: "amber",
  tagline: "Dashboards", description: "Synthetic dashboards.", order: 10, enabled: true,
  audience: { kind: "group", groupId: G1, groupLabel: "Synthetic Grafana users" }, ...over,
});

beforeEach(() => {
  ROWS = new Map(); AUDITS.length = 0; STAGED = []; TICK = 0; DB_DOWN = false; AUDIT_DOWN = false;
  CALLER = { email: "synthetic.admin@example.com", name: "Synthetic Admin", oid: "oid-1", groups: [], roles: [] };
  PERMS = new Set([ADMIN]); PERM_ERROR = false; LIVE_GROUPS = []; LIVE_CALLS = 0; LOOKUP.fn = async () => { LIVE_CALLS += 1; return LIVE_GROUPS === null ? [] : LIVE_GROUPS; };
});

// -- Validation ---------------------------------------------------------------------------------

test("create: a valid tool is saved, audited with after, and answered 201", async () => {
  const r = await api("POST", "/", tool());
  assert.equal(r.status, 201);
  assert.equal(r.body.id, "grafana");
  assert.deepEqual(r.body.audience, { kind: "group", groupId: G1, groupLabel: "Synthetic Grafana users" });
  assert.equal(r.body.createdBy, "synthetic.admin@example.com");
  assert.equal(AUDITS.length, 1);
  assert.equal(AUDITS[0].action, "console:external-tool-create");
  assert.equal(AUDITS[0].target, "external-tool:grafana");
  assert.equal(AUDITS[0].actor, "synthetic.admin@example.com");
  assert.equal(AUDITS[0].details.after.name, "Grafana");
  assert.equal("createdAt" in AUDITS[0].details.after, false);
});

test("create: defaults apply to icon, hue, order and enabled", async () => {
  const r = await api("POST", "/", { id: "wiki", name: "Wiki", url: "https://wiki.example.invalid", audience: { kind: "permission", permission: "tab:home" } });
  assert.equal(r.status, 201);
  assert.equal(r.body.icon, "ExternalLink");
  assert.equal(r.body.hue, "brand");
  assert.equal(r.body.order, 0);
  assert.equal(r.body.enabled, true);
  assert.equal(r.body.tagline, "");
});

/** @type {Array<[string, Record<string, any>, string]>} */
const BAD = [
  ["id", { id: "Bad Id" }, "id"],
  ["id", { id: "" }, "id"],
  ["id", { id: "a".repeat(65) }, "id"],
  ["name", { name: "" }, "name"],
  ["name", { name: "x".repeat(61) }, "name"],
  ["name", { name: "Gr<b>" }, "name"],
  ["name", { name: "Gr\u00e4fana" }, "name"],
  ["name", { name: 7 }, "name"],
  ["url", { url: "http://grafana.example.invalid/" }, "url"],
  ["url", { url: "javascript:void(0)" }, "url"],
  ["url", { url: "https://user:pw@grafana.example.invalid/" }, "url"],
  ["url", { url: "https://user@grafana.example.invalid/" }, "url"],
  ["url", { url: "https://grafana.example.invalid/ x" }, "url"],
  ["url", { url: `https://grafana.example.invalid/${"a".repeat(300)}` }, "url"],
  ["url", { url: "" }, "url"],
  ["url", { url: "https://" }, "url"],
  ["icon", { icon: "not an icon" }, "icon"],
  ["icon", { icon: "gauge" }, "icon"],
  ["hue", { hue: "pink" }, "hue"],
  ["tagline", { tagline: "x".repeat(121) }, "tagline"],
  ["tagline", { tagline: "a<b" }, "tagline"],
  ["description", { description: "x".repeat(401) }, "description"],
  ["description", { description: "uses <script>" }, "description"],
  ["description", { description: "caf\u00e9" }, "description"],
  ["order", { order: -1 }, "order"],
  ["order", { order: 1.5 }, "order"],
  ["order", { order: 100001 }, "order"],
  ["order", { order: "3" }, "order"],
  ["enabled", { enabled: "yes" }, "enabled"],
  ["unknown field", { owner: "x" }, "owner"],
  ["audience missing", { audience: undefined }, "audience"],
  ["audience everyone", { audience: { kind: "everyone" } }, "audience.kind"],
  ["audience group id", { audience: { kind: "group", groupId: "not-a-guid" } }, "audience.groupId"],
  ["audience group id missing", { audience: { kind: "group" } }, "audience.groupId"],
  ["audience group with permission", { audience: { kind: "group", groupId: G1, permission: "tab:home" } }, "audience.permission"],
  ["audience group label markup", { audience: { kind: "group", groupId: G1, groupLabel: "a<b" } }, "audience.groupLabel"],
  ["audience permission unknown", { audience: { kind: "permission", permission: "action:nope:nothing" } }, "audience.permission"],
  ["audience permission missing", { audience: { kind: "permission" } }, "audience.permission"],
  ["audience permission with group", { audience: { kind: "permission", permission: "tab:home", groupId: G1 } }, "audience.groupId"],
  ["audience extra key", { audience: { kind: "permission", permission: "tab:home", x: 1 } }, "audience.x"],
];
for (const [name, over, field] of BAD) {
  test(`create: rejects ${name}`, async () => {
    const r = await api("POST", "/", { ...tool(), ...over });
    assert.equal(r.status, 400);
    assert.equal(r.body.details.field, field);
    assert.equal(ROWS.size, 0, "nothing written");
    assert.equal(AUDITS.length, 0);
  });
}

test("create: an upper-case group id is stored lower case, a duplicate id is a 409, a body that is not an object is a 400", async () => {
  const up = await api("POST", "/", tool({ audience: { kind: "group", groupId: G1.toUpperCase() } }));
  assert.equal(up.status, 201);
  assert.equal(up.body.audience.groupId, G1);
  assert.equal((await api("POST", "/", tool())).status, 409);
  assert.equal((await api("POST", "/", [])).status, 400);
});

test("create: at most 50 tools", async () => {
  for (let i = 0; i < 50; i += 1) ROWS.set(`t${i}`, { ...tool({ id: `t${i}` }), sort_order: i, audience_kind: "group", group_id: G1, permission: null });
  const r = await api("POST", "/", tool({ id: "one-more" }));
  assert.equal(r.status, 400);
  assert.equal(ROWS.size, 50);
});

// -- Update, reorder, delete ---------------------------------------------------------------------

test("update: replaces the fields, audits before and after, refuses an id change and an unknown tool", async () => {
  await api("POST", "/", tool());
  AUDITS.length = 0;
  const r = await api("PUT", "/grafana", tool({ name: "Grafana prod", audience: { kind: "permission", permission: "tab:estate" }, enabled: false }));
  assert.equal(r.status, 200);
  assert.deepEqual(r.body.audience, { kind: "permission", permission: "tab:estate" });
  assert.equal(r.body.enabled, false);
  assert.equal(ROWS.get("grafana").group_id, null, "the group is cleared when the audience becomes a permission");
  assert.equal(AUDITS[0].action, "console:external-tool-update");
  assert.equal(AUDITS[0].details.before.name, "Grafana");
  assert.equal(AUDITS[0].details.after.name, "Grafana prod");
  assert.equal((await api("PUT", "/grafana", tool({ id: "other" }))).status, 400);
  assert.equal((await api("PUT", "/missing", tool({ id: "missing" }))).status, 404);
  assert.equal((await api("PUT", "/Bad Id", tool())).status, 404);
});

test("reorder: lists first in order, audited with before and after, rejects unknown and repeated ids", async () => {
  await api("POST", "/", tool({ id: "a", order: 10 }));
  await api("POST", "/", tool({ id: "b", order: 20 }));
  await api("POST", "/", tool({ id: "c", order: 30 }));
  AUDITS.length = 0;
  const r = await api("PUT", "/order", { ids: ["c", "a", "b"] });
  assert.equal(r.status, 200);
  assert.deepEqual(r.body.tools.map((/** @type {any} */ t) => t.id), ["c", "a", "b"]);
  assert.equal(AUDITS[0].action, "console:external-tool-reorder");
  assert.deepEqual(AUDITS[0].details.before.map((/** @type {any} */ t) => t.id), ["a", "b", "c"]);
  assert.deepEqual(AUDITS[0].details.after.map((/** @type {any} */ t) => t.id), ["c", "a", "b"]);
  assert.equal((await api("PUT", "/order", { ids: ["c", "zzz"] })).status, 404);
  assert.equal((await api("PUT", "/order", { ids: ["c", "c"] })).status, 400);
  assert.equal((await api("PUT", "/order", { ids: [] })).status, 400);
  assert.equal((await api("PUT", "/order", { ids: ["c"], extra: 1 })).status, 400);
});

test("delete: removes the row, audits before, 404 when it is gone", async () => {
  await api("POST", "/", tool());
  AUDITS.length = 0;
  const r = await api("DELETE", "/grafana");
  assert.equal(r.status, 200);
  assert.equal(ROWS.size, 0);
  assert.equal(AUDITS[0].action, "console:external-tool-delete");
  assert.equal(AUDITS[0].details.before.id, "grafana");
  assert.equal((await api("DELETE", "/grafana")).status, 404);
});

test("a failed audit write rolls the change back and answers 503", async () => {
  AUDIT_DOWN = true;
  const r = await api("POST", "/", tool());
  assert.equal(r.status, 503);
  assert.equal(ROWS.size, 0, "no unaudited change");
  AUDIT_DOWN = false;
  await api("POST", "/", tool());
  AUDIT_DOWN = true;
  assert.equal((await api("PUT", "/grafana", tool({ name: "Changed" }))).status, 503);
  assert.equal(ROWS.get("grafana").name, "Grafana");
  assert.equal((await api("DELETE", "/grafana")).status, 503);
  assert.equal(ROWS.size, 1);
});

// -- Permission gating ---------------------------------------------------------------------------

test("admin routes need action:console:external-tools, tab:console-admin alone is not enough", async () => {
  await api("POST", "/", tool());
  PERMS = new Set(["tab:console-admin", "action:console:layout", "action:console:modules"]);
  for (const [m, u, b] of /** @type {Array<[string, string, any]>} */ ([
    ["GET", "/", undefined], ["POST", "/", tool({ id: "x" })], ["PUT", "/grafana", tool()], ["PUT", "/order", { ids: ["grafana"] }], ["DELETE", "/grafana", undefined],
  ])) {
    const r = await api(m, u, b);
    assert.equal(r.status, 403, `${m} ${u}`);
  }
  assert.equal(ROWS.size, 1);
  assert.equal(AUDITS.length, 1, "only the setup write");
  PERMS = new Set(["*"]);
  const list = await api("GET", "/");
  assert.equal(list.status, 200, "Super Admin holds it through the wildcard");
  assert.equal(list.body.tools.length, 1);
  assert.ok(list.body.permissions.some((/** @type {any} */ p) => p.id === "tab:home" && p.label), "the registry list for the audience picker");
  assert.ok(list.body.permissions.some((/** @type {any} */ p) => p.id === ADMIN));
});

// -- GET /mine -----------------------------------------------------------------------------------

/** @param {Record<string, any>[]} list */
async function seed(list) { for (const t of list) assert.equal((await api("POST", "/", t)).status, 201); }

test("mine: a permission audience shows the tool to a holder and hides it from a caller without it", async () => {
  await seed([tool({ id: "est", name: "Estate board", audience: { kind: "permission", permission: "tab:estate" } })]);
  PERMS = new Set(["tab:estate"]);
  assert.deepEqual((await api("GET", "/mine")).body.tools.map((/** @type {any} */ t) => t.id), ["est"]);
  PERMS = new Set(["tab:home"]);
  assert.deepEqual((await api("GET", "/mine")).body.tools, []);
  PERMS = new Set(["*"]);
  assert.equal((await api("GET", "/mine")).body.tools.length, 1);
});

test("mine: a group audience shows the tool to a member (token groups, or a live read) and not to an outsider", async () => {
  await seed([tool()]);
  CALLER = { ...CALLER, groups: [G1.toUpperCase()] };
  PERMS = new Set();
  const viaToken = await api("GET", "/mine");
  assert.deepEqual(viaToken.body.tools.map((/** @type {any} */ t) => t.id), ["grafana"]);
  assert.equal(LIVE_CALLS, 0, "the token already proves it");

  CALLER = { ...CALLER, groups: [] };
  LIVE_GROUPS = [G1];
  assert.equal((await api("GET", "/mine")).body.tools.length, 1, "overage: the live read finds it");
  assert.equal(LIVE_CALLS, 1);

  LIVE_GROUPS = [G2];
  assert.deepEqual((await api("GET", "/mine")).body.tools, [], "member of another group only");
});

test("mine: a failed or throwing group lookup fails closed", async () => {
  await seed([tool()]);
  PERMS = new Set();
  LIVE_GROUPS = null;
  assert.deepEqual((await api("GET", "/mine")).body.tools, []);
  const real = LOOKUP.fn;
  LOOKUP.fn = async () => { throw new Error("graph down"); };
  try {
    assert.deepEqual((await api("GET", "/mine")).body.tools, []);
    CALLER = { ...CALLER, groups: [G1] };
    assert.equal((await api("GET", "/mine")).body.tools.length, 1, "what the token proves still counts");
  } finally {
    LOOKUP.fn = real;
  }
});

test("mine: a caller with no oid and no token group sees no group tool", async () => {
  await seed([tool()]);
  PERMS = new Set();
  CALLER = { email: "x@example.com", groups: [], roles: [] };
  LIVE_GROUPS = [G1];
  assert.deepEqual((await api("GET", "/mine")).body.tools, []);
  assert.equal(LIVE_CALLS, 0);
});

test("mine: a failed permission read fails closed for permission tools only", async () => {
  await seed([
    tool({ id: "p", audience: { kind: "permission", permission: "tab:estate" } }),
    tool({ id: "g", order: 20 }),
  ]);
  CALLER = { ...CALLER, groups: [G1] };
  PERM_ERROR = true;
  assert.deepEqual((await api("GET", "/mine")).body.tools.map((/** @type {any} */ t) => t.id), ["g"]);
});

test("mine: disabled tools never show, order is by order then id, and nothing about the audience leaves the server", async () => {
  await seed([
    tool({ id: "zeta", name: "Zeta", order: 5, audience: { kind: "permission", permission: "tab:home" } }),
    tool({ id: "alpha", name: "Alpha", order: 5, audience: { kind: "permission", permission: "tab:home" } }),
    tool({ id: "off", name: "Off", order: 1, enabled: false, audience: { kind: "permission", permission: "tab:home" } }),
    tool({ id: "first", name: "First", order: 1, audience: { kind: "permission", permission: "tab:home" } }),
  ]);
  PERMS = new Set(["tab:home"]);
  const r = await api("GET", "/mine");
  assert.equal(r.status, 200);
  assert.deepEqual(r.body.tools.map((/** @type {any} */ t) => t.id), ["first", "alpha", "zeta"]);
  assert.deepEqual(Object.keys(r.body.tools[0]).sort(), ["description", "hue", "icon", "id", "name", "order", "tagline", "url"]);
  assert.doesNotMatch(JSON.stringify(r.body), /audience|groupId|permission|createdBy/);
  assert.equal(r.headers["Cache-Control"], "private, no-store");
});

test("mine: a database failure answers 503 and shows nothing", async () => {
  await seed([tool()]);
  DB_DOWN = true;
  const r = await api("GET", "/mine");
  assert.equal(r.status, 503);
  assert.equal(r.body.tools, undefined);
});


// -- The pure parts ------------------------------------------------------------------------------

test("the hue list matches console-modules, and the id pattern, tool cap and error type are exported", () => {
  assert.deepEqual([...HUES], [...CORE_HUES]);
  assert.equal(MAX_TOOLS, 50);
  assert.ok(ID_RE.test("grafana") && !ID_RE.test("Grafana"));
  assert.throws(() => validateTool(null, { permissionIds: [] }), (e) => e instanceof Invalid && e.field === "form");
});

test("validateTool needs the permission ids it is given: an audience naming another id is refused", () => {
  const ok = validateTool({ id: "x", name: "X", url: "https://x.example.invalid", audience: { kind: "permission", permission: "tab:a" } }, { permissionIds: ["tab:a"] });
  assert.equal(ok.audience.kind, "permission");
  assert.throws(() => validateTool({ id: "x", name: "X", url: "https://x.example.invalid", audience: { kind: "permission", permission: "tab:a" } }, { permissionIds: ["tab:b"] }), (e) => e instanceof Invalid && e.field === "audience.permission");
  assert.throws(() => validateTool({ id: "x", name: "X", url: "https://x.example.invalid", hue: "mauve", audience: { kind: "group", groupId: G1 } }, { permissionIds: [], hues: ["mauve2"] }), (e) => e instanceof Invalid && e.field === "hue");
  assert.equal(validateTool({ id: "x", name: "X", url: "https://x.example.invalid", hue: "mauve", audience: { kind: "group", groupId: G1 } }, { permissionIds: [], hues: ["mauve"] }).hue, "mauve");
});

test("toTool, publicTool and auditShape map a row to the API, the launcher and the audit snapshot", () => {
  const row = { id: "g", name: "G", url: "https://g.example.invalid", icon: "Gauge", hue: "teal", tagline: "t", description: "d", sort_order: 3, enabled: true, audience_kind: "group", group_id: G1, group_label: "L", permission: null, created_by: "a", created_at: "c", updated_by: "b", updated_at: "u" };
  const t = toTool(row);
  assert.deepEqual(t.audience, { kind: "group", groupId: G1, groupLabel: "L" });
  assert.deepEqual(Object.keys(publicTool(t)).sort(), ["description", "hue", "icon", "id", "name", "order", "tagline", "url"]);
  assert.equal("createdAt" in /** @type {any} */ (auditShape(t)), false);
  assert.equal(auditShape(null), null);
  assert.deepEqual(toTool({ ...row, audience_kind: "permission", permission: "tab:x" }).audience, { kind: "permission", permission: "tab:x" });
});

test("visibleTools asks the group lookup only for enabled group tools and never for a permission tool", async () => {
  const mk = (/** @type {any} */ o) => toTool({ id: "i", name: "N", url: "https://n.example.invalid", icon: "A1", hue: "brand", tagline: "", description: "", sort_order: 0, enabled: true, audience_kind: "group", group_id: G1, permission: null, ...o });
  /** @type {string[][]} */
  const asked = [];
  const o = { callerGroups: async (/** @type {string[]} */ w) => { asked.push(w); return new Set(w); }, callerHasPermission: async () => true, log: quiet };
  const tools = [mk({ id: "a" }), mk({ id: "b", enabled: false, group_id: G2 }), mk({ id: "c", audience_kind: "permission", permission: "tab:x", group_id: null })];
  assert.deepEqual((await visibleTools(tools, o)).map((t) => t.id), ["a", "c"]);
  assert.deepEqual(asked, [[G1]]);
  asked.length = 0;
  await visibleTools([mk({ id: "c", audience_kind: "permission", permission: "tab:x", group_id: null })], o);
  assert.deepEqual(asked, []);
});
