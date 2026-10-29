import { test } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import { corsOptions, originGuard, serverTiming, recordTiming, timed, formatServerTiming } from "../../../shell-packages/app-server/index.js";

/**
 * @param {ReturnType<typeof corsOptions>} opts
 * @param {string | undefined} origin
 * @returns {Promise<{ err: Error | null, allow?: boolean }>}
 */
function decide(opts, origin) {
  return new Promise((resolve) => opts.origin(origin, (err, allow) => resolve({ err, allow })));
}

test("corsOptions: maxAge 7200 by default, credentials off, exact-match allowlist", async () => {
  const o = corsOptions({ allowedOrigins: ["https://console.example.test"] });
  assert.equal(o.maxAge, 7200);
  assert.equal(o.credentials, false);
  assert.deepEqual(o.methods, ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]);
  assert.deepEqual(o.allowedHeaders, ["Content-Type", "X-Requested-With", "Authorization"]);
  assert.equal("exposedHeaders" in o, false);
  assert.deepEqual(await decide(o, "https://console.example.test"), { err: null, allow: true });
  assert.deepEqual(await decide(o, undefined), { err: null, allow: true });
  // No wildcard or prefix matching.
  assert.deepEqual(await decide(o, "https://console.example.test.evil.test"), { err: null, allow: false });
});

test("corsOptions reject 'omit' answers cb(null, false)", async () => {
  const o = corsOptions({ allowedOrigins: ["https://a.test"], reject: "omit" });
  assert.deepEqual(await decide(o, "https://b.test"), { err: null, allow: false });
});

test("corsOptions reject 'error' passes the same Error the apps throw today", async () => {
  const o = corsOptions({ allowedOrigins: ["https://a.test"], reject: "error" });
  const { err } = await decide(o, "https://b.test");
  assert.ok(err instanceof Error);
  assert.equal(err.message, "Origin https://b.test not allowed by CORS");
  assert.deepEqual(await decide(o, "https://a.test"), { err: null, allow: true });
});

test("corsOptions keeps app-specific headers and an explicit maxAge", () => {
  const o = corsOptions({
    allowedOrigins: [],
    allowedHeaders: ["Content-Type", "Authorization", "X-MM-Device"],
    exposedHeaders: ["Content-Disposition"],
    maxAge: 600,
  });
  assert.deepEqual(o.allowedHeaders, ["Content-Type", "Authorization", "X-MM-Device"]);
  assert.deepEqual(o.exposedHeaders, ["Content-Disposition"]);
  assert.equal(o.maxAge, 600);
  assert.throws(() => corsOptions(/** @type {any} */ ({ allowedOrigins: [], reject: "nope" })), /reject/);
  assert.throws(() => corsOptions(/** @type {any} */ ({})), /allowedOrigins/);
});

test("formatServerTiming: marks with optional desc, then total", () => {
  assert.equal(
    formatServerTiming([{ name: "jwt", dur: 3.14159 }, { name: "groups", dur: 0.04, desc: "hit" }], 12.345),
    'jwt;dur=3.1, groups;dur=0;desc="hit", total;dur=12.3',
  );
  assert.equal(formatServerTiming([], 5), "total;dur=5");
  assert.equal(formatServerTiming([{ name: "x", dur: 1, desc: 'a"b' }], 1), 'x;dur=1;desc="ab", total;dur=1');
});

/**
 * Run a tiny http server with serverTiming in front of a handler.
 * @param {Parameters<typeof serverTiming>[0]} opts
 * @param {(req: any, res: any) => Promise<void> | void} handler
 */
async function withServer(opts, handler) {
  const mw = serverTiming(opts);
  const server = http.createServer((req, res) => {
    mw(req, res, () => { Promise.resolve(handler(req, res)).catch(() => { res.statusCode = 500; res.end(); }); });
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", () => r(undefined)));
  const addr = /** @type {import('node:net').AddressInfo} */ (server.address());
  return { url: `http://127.0.0.1:${addr.port}`, close: () => new Promise((r) => server.close(() => r(undefined))) };
}

const SERVER_TIMING_RE = /^([a-z]+;dur=\d+(\.\d)?(;desc="[a-z]+")?, )*total;dur=\d+(\.\d)?$/;

test("serverTiming: header carries the recorded marks and total, one log line per request", async () => {
  /** @type {string[]} */
  const lines = [];
  /** @type {any[]} */
  const records = [];
  const srv = await withServer(
    { log: (l) => lines.push(l), sink: (r) => records.push(r), timingAllowOrigins: ["https://console.test"] },
    async (req, res) => {
      // Request values never name a route: outside an Express app there is
      // no declared route, so the record says "-" (routes.test.js covers naming).
      req.baseUrl = "/api/users/someone@example.com";
      req.route = { path: "/:id" };
      recordTiming(req, "jwt", 2.5);
      recordTiming(req, "groups", 0.2, "hit");
      await timed(req, "rbac", async () => { await new Promise((r) => setTimeout(r, 5)); });
      recordTiming(req, "rbac", 1); // repeated names add up
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify({ ok: true }));
    },
  );
  try {
    const r = await fetch(`${srv.url}/api/users/someone@example.com?q=secret`, { headers: { Origin: "https://console.test" } });
    await r.text();
    const st = r.headers.get("server-timing") || "";
    assert.match(st, SERVER_TIMING_RE);
    assert.match(st, /^jwt;dur=2\.5, groups;dur=0\.2;desc="hit", rbac;dur=\d+(\.\d)?, total;dur=/);
    const rbacDur = Number(/rbac;dur=([\d.]+)/.exec(st)?.[1]);
    assert.ok(rbacDur >= 5, `rbac ${rbacDur} >= 5`);
    assert.equal(r.headers.get("timing-allow-origin"), "https://console.test");
    assert.match(r.headers.get("vary") || "", /Origin/);

    await new Promise((res) => setTimeout(res, 20));
    assert.equal(lines.length, 1);
    const rec = JSON.parse(/** @type {string} */ (lines[0]));
    assert.equal(rec.msg, "request");
    assert.equal(rec.method, "GET");
    assert.equal(rec.route, "-");
    assert.equal(rec.status, 200);
    assert.equal(typeof rec.ms, "number");
    assert.equal(rec.timings.jwt, 2.5);
    assert.deepEqual(rec.desc, { groups: "hit" });
    // Mark descriptions never land on top-level fields.
    assert.equal(rec.groups, undefined);
    // No raw URL, query string, email or origin in the log line.
    assert.doesNotMatch(lines[0] || "", /someone|example\.com|secret|console\.test/);
    assert.equal(records.length, 1);
  } finally {
    await srv.close();
  }
});

test("serverTiming: no timing headers for an origin off the list or no origin, but the request is still logged", async () => {
  /** @type {string[]} */
  const lines = [];
  const srv = await withServer({ log: (l) => lines.push(l), timingAllowOrigins: ["https://console.test"] }, (req, res) => {
    recordTiming(req, "groups", 1, "miss");
    res.statusCode = 404;
    res.end("nope");
  });
  try {
    const r = await fetch(`${srv.url}/x`, { headers: { Origin: "https://evil.test" } });
    await r.text();
    assert.equal(r.headers.get("server-timing"), null);
    assert.equal(r.headers.get("timing-allow-origin"), null);
    assert.match(r.headers.get("vary") || "", /Origin/);
    const r2 = await fetch(`${srv.url}/x`);
    await r2.text();
    assert.equal(r2.headers.get("server-timing"), null);
    await new Promise((res) => setTimeout(res, 20));
    assert.equal(lines.length, 2);
    const rec = JSON.parse(/** @type {string} */ (lines[0]));
    assert.equal(rec.status, 404);
    assert.equal(rec.route, "-");
  } finally {
    await srv.close();
  }
});

test("serverTiming: skip suppresses the log line but keeps the header", async () => {
  /** @type {string[]} */
  const lines = [];
  const srv = await withServer({ log: (l) => lines.push(l), skip: () => true, headerForAll: true }, (_req, res) => res.end("ok"));
  try {
    const r = await fetch(`${srv.url}/health`);
    await r.text();
    // headerForAll sends the header with no Origin, total only when nothing was marked.
    assert.match(r.headers.get("server-timing") || "", /^total;dur=\d+(\.\d)?$/);
    assert.equal(r.headers.get("timing-allow-origin"), null);
    await new Promise((res) => setTimeout(res, 20));
    assert.equal(lines.length, 0);
  } finally {
    await srv.close();
  }
});

test("recordTiming and timed are no-ops without the middleware", async () => {
  const req = {};
  recordTiming(req, "jwt", 1);
  assert.equal(await timed(req, "rbac", () => 42), 42);
  recordTiming(null, "jwt", 1);
});

/**
 * @param {ReturnType<typeof originGuard>} mw
 * @param {string} method
 * @param {string | undefined} origin
 * @param {Record<string, string>} [headers]
 */
function guard(mw, method, origin, headers = {}) {
  /** @type {{ status: number, body: string, headers: Record<string, string>, nextCalled: boolean }} */
  const out = { status: 200, body: "", headers: {}, nextCalled: false };
  const res = {
    set statusCode(v) { out.status = v; },
    get statusCode() { return out.status; },
    setHeader(/** @type {string} */ k, /** @type {string} */ v) { out.headers[k.toLowerCase()] = v; },
    end(/** @type {string} */ b) { out.body = b; },
  };
  mw({ method, headers: { ...(origin ? { origin } : {}), ...headers } }, res, () => { out.nextCalled = true; });
  return out;
}

const BEARER = { authorization: "Bearer synthetic" };
const JSON_CT = { "content-type": "application/json" };

test("originGuard: a request a browser would preflight is refused from an origin off the allowlist", () => {
  const mw = originGuard({ allowedOrigins: ["https://console.test"], preflightHeaders: ["X-MM-Device"] });
  for (const [m, h] of /** @type {Array<[string, Record<string, string>]>} */ ([
    ["PUT", {}], ["PATCH", {}], ["DELETE", {}], ["post", JSON_CT],
    ["GET", BEARER], ["POST", BEARER], ["GET", { "x-mm-device": "d1" }],
    ["POST", { "content-type": "application/json; charset=utf-8" }],
  ])) {
    const r = guard(mw, m, "https://evil.test", h);
    assert.equal(r.nextCalled, false, `${m} ${JSON.stringify(h)}`);
    assert.equal(r.status, 403);
    assert.deepEqual(JSON.parse(r.body), { error: "Origin not allowed" });
  }
  assert.equal(guard(mw, "GET", "null", BEARER).nextCalled, false);
});

test("originGuard: allowed origins, no Origin, CORS-simple requests and preflights pass unchanged", () => {
  const mw = originGuard({ allowedOrigins: ["https://console.test"] });
  assert.equal(guard(mw, "DELETE", "https://console.test", BEARER).nextCalled, true);
  assert.equal(guard(mw, "DELETE", undefined, BEARER).nextCalled, true);
  assert.equal(guard(mw, "OPTIONS", "https://evil.test").nextCalled, true);
  // A CORS-simple GET or HEAD passes (read only, the response stays unreadable).
  assert.equal(guard(mw, "GET", "https://evil.test").nextCalled, true);
  assert.equal(guard(mw, "HEAD", "https://evil.test").nextCalled, true);
  // A CORS-simple write (form or text POST) is still refused.
  assert.equal(guard(mw, "POST", "https://evil.test", { "content-type": "application/x-www-form-urlencoded" }).nextCalled, false);
  assert.equal(guard(mw, "POST", "https://evil.test", { "content-type": "text/plain;charset=UTF-8" }).nextCalled, false);
  assert.equal(guard(mw, "POST", "https://evil.test").nextCalled, false);
  // Proxy-added headers (X-Forwarded-*, X-ARR-*) are not custom headers.
  assert.equal(guard(mw, "GET", "https://evil.test", { "x-forwarded-for": "1.2.3.4" }).nextCalled, true);
  assert.throws(() => originGuard(/** @type {any} */ ({})), /allowedOrigins/);
});

test("originGuard: configured entries are normalised (case, trailing slash)", () => {
  const mw = originGuard({ allowedOrigins: [" HTTPS://Console.Test/ ", ""] });
  assert.equal(guard(mw, "POST", "https://console.test", BEARER).nextCalled, true);
  assert.equal(guard(mw, "POST", "https://console.test.evil", BEARER).nextCalled, false);
});

test("serverTiming: a timingKey stores the same record under the shell's own key, marks add up", async () => {
  /** @type {any} */
  let own;
  /** @type {any} */
  let core;
  const srv = await withServer({ log: null, timingKey: "shell.test.timing" }, async (req, res) => {
    own = req[Symbol.for("shell.test.timing")];
    core = req[Symbol.for("shell.app-server.timing")];
    recordTiming(req, "jwt", 3);
    own.marks.push({ name: "extra", dur: 1 });
    res.end("ok");
  });
  try {
    const r = await fetch(srv.url, { headers: {} });
    await r.text();
    assert.ok(own && core, "both keys carry a record");
    assert.equal(own, core, "the same object, so marks recorded through either key add up");
    assert.deepEqual(own.marks.map((/** @type {any} */ m) => m.name), ["jwt", "extra"]);
  } finally {
    await srv.close();
  }
});

test("serverTiming: without a timingKey only the core key is set", async () => {
  /** @type {symbol[]} */
  let keys = [];
  const srv = await withServer({ log: null }, async (req, res) => {
    keys = Object.getOwnPropertySymbols(req).filter((s) => String(s.description).includes("timing"));
    res.end("ok");
  });
  try {
    await (await fetch(srv.url)).text();
    assert.deepEqual(keys.map((s) => s.description), ["shell.app-server.timing"]);
  } finally {
    await srv.close();
  }
});
