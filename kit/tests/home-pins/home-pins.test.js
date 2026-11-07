// shell-packages/home-pins: gated on the Home permission, per person, a pin must name a declared page, bounded
// label, the pin limit, idempotent put, delete only your own. An in-memory table. Synthetic data only.
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import express from "express";
import { homePinRoutes, validatePin, declaredRoutes, MAX_PINS } from "../../../shell-packages/home-pins/index.js";

/** @type {any[]} */
let PINS = [];
let TICK = 0;
/** @type {Set<string>} */
let PERMS = new Set(["tab:home"]);
/** @type {any} */
let CALLER = { email: "Op.One@example.com", oid: "o1", groups: [], roles: [] };
const MODULES = [
  { id: "console", pages: [{ route: "/" }, { route: "/admin" }] },
  { id: "klaxon", pages: [{ route: "/compose" }, { route: "/active" }, { route: "/a" }, { route: "/b" }, { route: "/c" }, { route: "/d" }, { route: "/e" }, { route: "/f" }] },
  { id: "pager", pages: [{ route: "/p1" }, { route: "/p2" }, { route: "/p3" }, { route: "/p4" }] },
];

/** @param {string} sql @param {any[]} p */
async function fake(sql, p = []) {
  const q = sql.replace(/\s+/g, " ").trim();
  if (/^SELECT module_id AS "moduleId"/.test(q)) {
    return { rows: PINS.filter((r) => r.user_email === p[0]).sort((a, b) => a.position - b.position || a.t - b.t).slice(0, 12).map((r) => ({ moduleId: r.module_id, route: r.route, label: r.label })) };
  }
  if (/^INSERT INTO console_home_pins/.test(q)) {
    const mine = PINS.filter((r) => r.user_email === p[0]);
    const existing = mine.find((r) => r.module_id === p[1] && r.route === p[2]);
    if (existing) { existing.label = p[3]; return { rows: [{ route: p[2] }] }; }
    if (mine.length >= Number(/< (\d+)/.exec(q)?.[1] ?? 12)) return { rows: [] };
    PINS.push({ user_email: p[0], module_id: p[1], route: p[2], label: p[3], position: mine.length, t: ++TICK });
    return { rows: [{ route: p[2] }] };
  }
  if (/^DELETE FROM console_home_pins/.test(q)) {
    PINS = PINS.filter((r) => !(r.user_email === p[0] && r.module_id === p[1] && r.route === p[2]));
    return { rows: [] };
  }
  throw new Error(`unexpected SQL in the fake: ${q.slice(0, 100)}`);
}
const db = { query: fake };
const router = express.Router();
homePinRoutes(router, {
  db, modules: MODULES, caller: () => CALLER,
  gate: (/** @type {any} */ _q, /** @type {any} */ res, /** @type {any} */ next) => (PERMS.has("*") || PERMS.has("tab:home") ? next() : res.status(403).json({ error: "Forbidden" })),
});

/**
 * @param {string} method @param {string} url @param {any} [body] @param {Record<string, string>} [query]
 * @returns {Promise<{ status: number, body: any }>}
 */
function api(method, url, body, query = {}) {
  return new Promise((resolve, reject) => {
    /** @type {any} */
    const req = { method, url, originalUrl: url, path: url, headers: {}, body: body === undefined ? {} : body, query, params: {}, get: () => "", user: CALLER };
    /** @type {any} */
    const res = {
      statusCode: 200,
      status(/** @type {number} */ c) { this.statusCode = c; return this; },
      json(/** @type {any} */ b) { resolve({ status: this.statusCode, body: b }); return this; },
      set() { return this; }, setHeader() {}, end() { resolve({ status: this.statusCode, body: null }); },
    };
    /** @type {any} */ (router).handle(req, res, (/** @type {any} */ err) => (err ? reject(err) : resolve({ status: 404, body: null })));
  });
}

beforeEach(() => {
  PINS = []; TICK = 0; PERMS = new Set(["tab:home"]);
  CALLER = { email: "Op.One@example.com", oid: "o1", groups: [], roles: [] };
});

const pin = (/** @type {Record<string, any>} */ over = {}) => ({ moduleId: "klaxon", route: "/compose", label: "Compose", ...over });

test("every route needs tab:home", async () => {
  PERMS = new Set();
  for (const [m, u] of [["GET", "/pins"], ["PUT", "/pins"], ["DELETE", "/pins"]]) {
    assert.equal((await api(m, u, pin(), { moduleId: "klaxon", route: "/compose" })).status, 403, `${m} ${u}`);
  }
});

test("a pin is stored under the lowercased caller email and only that caller reads it", async () => {
  const put = await api("PUT", "/pins", pin());
  assert.equal(put.status, 200);
  assert.deepEqual(put.body.pins, [{ moduleId: "klaxon", route: "/compose", label: "Compose" }]);
  assert.equal(PINS[0].user_email, "op.one@example.com");
  CALLER = { email: "other@example.com", oid: "o2", groups: [], roles: [] };
  assert.deepEqual((await api("GET", "/pins")).body.pins, []);
  // another person's delete does nothing to the first person's pin
  await api("DELETE", "/pins", undefined, { moduleId: "klaxon", route: "/compose" });
  assert.equal(PINS.length, 1);
});

test("put is idempotent and re-labels", async () => {
  await api("PUT", "/pins", pin());
  const r = await api("PUT", "/pins", pin({ label: "New alert" }));
  assert.equal(r.body.pins.length, 1);
  assert.equal(r.body.pins[0].label, "New alert");
});

test("input is validated: unknown tool, undeclared page, bad labels, bad body", async () => {
  assert.equal((await api("PUT", "/pins", pin({ moduleId: "nope" }))).status, 400);
  assert.equal((await api("PUT", "/pins", pin({ route: "/not-a-page" }))).status, 400);
  assert.equal((await api("PUT", "/pins", pin({ route: "https://evil.example/x" }))).status, 400);
  assert.equal((await api("PUT", "/pins", pin({ label: "" }))).status, 400);
  assert.equal((await api("PUT", "/pins", pin({ label: "x".repeat(61) }))).status, 400);
  assert.equal((await api("PUT", "/pins", pin({ label: "<b>hi</b>" }))).status, 400);
  assert.equal((await api("PUT", "/pins", pin({ label: "caf\u00e9" }))).status, 400);
  assert.equal((await api("PUT", "/pins", pin({ label: 5 }))).status, 400);
  assert.equal((await api("PUT", "/pins", [])).status, 400);
  assert.equal((await api("DELETE", "/pins", undefined, { moduleId: "klaxon", route: "/zzz" })).status, 400);
  assert.equal(PINS.length, 0);
});

test("the 13th pin is refused with 409 and nothing is written", async () => {
  const pages = MODULES.flatMap((m) => (m.pages || []).map((p) => ({ moduleId: m.id, route: p.route })));
  assert.ok(pages.length > 13);
  for (const pg of pages.slice(0, 12)) assert.equal((await api("PUT", "/pins", { ...pg, label: "p" })).status, 200);
  const extra = pages[12];
  assert.equal((await api("PUT", "/pins", { ...extra, label: "p" })).status, 409);
  assert.equal(PINS.length, 12);
  // re-labelling one at the limit still works
  assert.equal((await api("PUT", "/pins", { ...pages[0], label: "renamed" })).status, 200);
});

test("delete removes just that pin", async () => {
  await api("PUT", "/pins", pin());
  await api("PUT", "/pins", pin({ route: "/active", label: "Active" }));
  const r = await api("DELETE", "/pins", undefined, { moduleId: "klaxon", route: "/compose" });
  assert.deepEqual(r.body.pins.map((/** @type {any} */ x) => x.route), ["/active"]);
});


test("a different limit applies, and a missing email is a 401", async () => {
  const small = express.Router();
  homePinRoutes(small, { db, modules: MODULES, caller: () => CALLER, max: 2, gate: (/** @type {any} */ _q, /** @type {any} */ _r, /** @type {any} */ next) => next() });
  const call = (/** @type {string} */ m, /** @type {string} */ u, /** @type {any} */ b) => new Promise((resolve, reject) => {
    /** @type {any} */
    const req = { method: m, url: u, originalUrl: u, path: u, headers: {}, body: b, query: {}, params: {}, get: () => "" };
    /** @type {any} */
    const res = { statusCode: 200, status(/** @type {number} */ c) { this.statusCode = c; return this; }, json(/** @type {any} */ x) { resolve({ status: this.statusCode, body: x }); return this; }, set() { return this; }, end() { resolve({ status: this.statusCode, body: null }); } };
    small.handle(req, res, (/** @type {any} */ err) => (err ? reject(err) : resolve({ status: 404, body: null })));
  });
  assert.equal(/** @type {any} */ (await call("PUT", "/pins", { moduleId: "klaxon", route: "/a", label: "a" })).status, 200);
  assert.equal(/** @type {any} */ (await call("PUT", "/pins", { moduleId: "klaxon", route: "/b", label: "b" })).status, 200);
  const full = /** @type {any} */ (await call("PUT", "/pins", { moduleId: "klaxon", route: "/c", label: "c" }));
  assert.equal(full.status, 409);
  assert.match(full.body.error, /up to 2 pages/);
  CALLER = { email: "", oid: "o9" };
  assert.equal(/** @type {any} */ (await call("GET", "/pins")).status, 401);
  assert.equal(/** @type {any} */ (await call("PUT", "/pins", { moduleId: "klaxon", route: "/a", label: "a" })).status, 401);
  assert.equal(/** @type {any} */ (await call("DELETE", "/pins")).status, 401);
});

test("validatePin and declaredRoutes: only declared pages, trimmed labels", () => {
  const routes = declaredRoutes(MODULES);
  assert.deepEqual(routes.get("pager"), new Set(["/p1", "/p2", "/p3", "/p4"]));
  assert.deepEqual(validatePin({ moduleId: "pager", route: "/p1", label: "  Pager one " }, routes), { pin: { moduleId: "pager", route: "/p1", label: "Pager one" } });
  assert.deepEqual(validatePin({ moduleId: "pager", route: "/nope", label: "x" }, routes), { error: "That page is not one this tool declares." });
  assert.deepEqual(validatePin(null, routes), { error: "Send a JSON object." });
  assert.equal(MAX_PINS, 12);
  assert.deepEqual(declaredRoutes([{ id: "bare" }]).get("bare"), new Set());
});
