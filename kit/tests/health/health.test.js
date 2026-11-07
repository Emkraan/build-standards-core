// shell-packages/health: the stale-while-revalidate reader and the public liveness route. Synthetic data only.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createSwrReader, healthRoute } from "../../../shell-packages/health/index.js";

const quiet = { error() {} };

/** A read that waits for release() so a test can hold a refresh in flight. */
function heldRead() {
  /** @type {Array<{ resolve: (v: any) => void, reject: (e: Error) => void }>} */
  const waiting = [];
  let calls = 0;
  return {
    get calls() { return calls; },
    waiting,
    read: () => new Promise((resolve, reject) => { calls += 1; waiting.push({ resolve, reject }); }),
  };
}

test("the first get answers empty at once and starts one refresh; the next get has the reading and its age", async () => {
  let t = 1000;
  const h = heldRead();
  const r = createSwrReader({ read: h.read, now: () => t, log: quiet });
  const first = r.get();
  assert.deepEqual([first.value, first.at, first.ageMs, first.refreshing], [null, null, null, true]);
  assert.equal(h.calls, 1);
  assert.equal(r.get().refreshing, true);
  assert.equal(h.calls, 1, "one pass at a time");
  h.waiting[0]?.resolve({ ok: 1 });
  await r.refresh();
  t += 10;
  const next = r.get();
  assert.deepEqual([next.value, next.at, next.ageMs, next.refreshing, next.lastError], [{ ok: 1 }, 1000, 10, false, null]);
  assert.equal(h.calls, 1, "a fresh reading starts no refresh");
});

test("a stale reading is answered at once while a refresh runs behind it", async () => {
  let t = 0;
  let n = 0;
  const r = createSwrReader({ read: async () => ({ n: (n += 1) }), staleMs: 100, now: () => t, log: quiet });
  await r.refresh();
  t = 99;
  assert.equal(r.get().value?.n, 1);
  assert.equal(n, 1);
  t = 100;
  const stale = r.get();
  assert.equal(stale.value?.n, 1, "the old reading answers, it does not wait");
  assert.equal(stale.ageMs, 100);
  await r.refresh();
  assert.equal(r.get().value?.n, 2);
});

test("a failed refresh keeps the last good reading, records the error, never rejects, and calls onError", async () => {
  let t = 0;
  let fail = false;
  const seen = /** @type {unknown[]} */ ([]);
  const logged = /** @type {string[]} */ ([]);
  const r = createSwrReader({ read: async () => { if (fail) throw new Error("probe down"); return "good"; }, staleMs: 1000, now: () => t, log: { error: (m) => logged.push(m) }, onError: (e) => seen.push(e) });
  await r.refresh();
  fail = true;
  t = 50;
  await r.refresh();
  const got = r.get();
  assert.equal(got.value, "good");
  assert.equal(got.at, 0, "the reading keeps its real age");
  assert.equal(got.lastError, "probe down");
  assert.equal(seen.length, 1);
  assert.match(logged.join("\n"), /refresh failed, keeping the last reading: probe down/);
  fail = false;
  await r.refresh();
  assert.equal(r.get().lastError, null);
});

test("concurrent refreshes share one read, and a read that throws a non-error is recorded as text", async () => {
  let calls = 0;
  const r = createSwrReader({ read: async () => { calls += 1; await Promise.resolve(); return calls; }, log: quiet });
  await Promise.all([r.refresh(), r.refresh(), r.refresh()]);
  assert.equal(calls, 1);
  const odd = createSwrReader({ read: async () => { throw "plain text"; }, log: quiet });
  await odd.refresh();
  assert.equal(odd.get().lastError, "plain text");
});

test("createSwrReader needs a read function", () => {
  assert.throws(() => createSwrReader(/** @type {any} */ ({})), /needs a read function/);
});

function call(router, url = "/") {
  return new Promise((resolve, reject) => {
    /** @type {any} */
    const res = { statusCode: 200, status(/** @type {number} */ c) { this.statusCode = c; return this; }, json(/** @type {any} */ b) { resolve({ status: this.statusCode, body: b }); return this; } };
    router.handle({ method: "GET", url, originalUrl: url, path: url, headers: {}, query: {}, params: {}, get: () => "" }, res, (/** @type {any} */ e) => (e ? reject(e) : resolve({ status: 404 })));
  });
}

import express from "express";

test("healthRoute: all critical checks ok is 200 with the version, each reading, and the info readings", async () => {
  const router = express.Router();
  healthRoute(router, { version: "1.2.3", critical: { database: async () => ({ ok: true, rows: 1 }) }, info: { secrets: () => ({ available: true }) }, env: { NODE_ENV: "production" }, log: quiet });
  const r = /** @type {any} */ (await call(router));
  assert.equal(r.status, 200);
  assert.equal(r.body.status, "ok");
  assert.equal(r.body.version, "1.2.3");
  assert.equal(r.body.env, "production");
  assert.equal(r.body.subsystems.database.ok, true);
  assert.equal(r.body.subsystems.database.rows, 1);
  assert.equal(typeof r.body.subsystems.database.latencyMs, "number");
  assert.deepEqual(r.body.subsystems.secrets, { available: true });
  assert.match(r.body.timestamp, /^\d{4}-\d{2}-\d{2}T/);
});

test("healthRoute: a check that answers not ok, or throws, is degraded with a 503, and info never changes the status", async () => {
  const router = express.Router();
  healthRoute(router, {
    version: "1", env: {}, log: quiet,
    critical: { a: async () => ({ ok: false, why: "full" }), b: async () => { throw Object.assign(new Error("connect ECONNREFUSED db.internal:5432"), { code: "ECONNREFUSED" }); } },
    info: { broken: () => { throw new Error("boom"); } },
  });
  const r = /** @type {any} */ (await call(router));
  assert.equal(r.status, 503);
  assert.equal(r.body.status, "degraded");
  assert.equal(r.body.subsystems.a.why, "full");
  assert.equal(r.body.subsystems.b.ok, false);
  assert.equal(r.body.subsystems.b.error, "connect ECONNREFUSED db.internal:5432", "outside production the real error helps the operator");
  assert.equal(r.body.subsystems.b.code, "ECONNREFUSED");
  assert.deepEqual(r.body.subsystems.broken, { error: "unavailable" });
  assert.equal(r.body.env, "development");
});

test("healthRoute: in production a failed check never puts the raw error on the wire, but it is logged", async () => {
  const router = express.Router();
  const logged = /** @type {string[]} */ ([]);
  healthRoute(router, { version: "1", env: { NODE_ENV: "production" }, log: { error: (m) => logged.push(m) }, critical: { database: async () => { throw new Error("getaddrinfo ENOTFOUND secret-host.example"); } } });
  const r = /** @type {any} */ (await call(router));
  assert.equal(r.status, 503);
  assert.equal(r.body.subsystems.database.error, "Unreachable");
  assert.doesNotMatch(JSON.stringify(r.body), /secret-host/);
  assert.match(logged.join("\n"), /database check failed: getaddrinfo ENOTFOUND secret-host\.example/);
});

test("healthRoute: the path is an option", async () => {
  const router = express.Router();
  healthRoute(router, { version: "1", path: "/live", critical: {}, env: {}, log: quiet });
  assert.equal(/** @type {any} */ (await call(router, "/live")).status, 200);
  assert.equal(/** @type {any} */ (await call(router, "/")).status, 404);
});
