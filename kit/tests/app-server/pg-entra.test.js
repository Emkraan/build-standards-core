// pgPoolConfig / pgEntraPassword tests. All data is synthetic.
import { test } from "node:test";
import assert from "node:assert/strict";
import { pgPoolConfig, pgEntraPassword, pgUserForToken, usesPgEntraAuth, PG_ENTRA_SCOPE } from "../../../shell-packages/app-server/index.js";

const ENTRA = { PGHOST: "h.example", PGDATABASE: "d", PGUSER: "demo-x-api" };

test("Entra mode needs an empty DATABASE_URL plus PGHOST, PGDATABASE and PGUSER", () => {
  assert.equal(usesPgEntraAuth(ENTRA), true);
  assert.equal(usesPgEntraAuth({ ...ENTRA, DATABASE_URL: "postgres://x" }), false);
  assert.equal(usesPgEntraAuth({ PGHOST: "h", PGDATABASE: "d" }), false);
});

test("Entra config has TLS, a password function and no connection string", () => {
  const c = pgPoolConfig(ENTRA);
  assert.equal(c.host, "h.example");
  assert.equal(c.user, "demo-x-api");
  assert.equal(typeof c.password, "function");
  assert.equal(c.connectionString, undefined);
  assert.deepEqual(c.ssl, { rejectUnauthorized: false });
});

test("URL mode keeps the URL, TLS off only for a local URL or sslmode=disable", () => {
  assert.equal(pgPoolConfig({ DATABASE_URL: "postgres://u@localhost/x" }).ssl, false);
  assert.deepEqual(pgPoolConfig({ DATABASE_URL: "postgres://db-host/x" }).ssl, { rejectUnauthorized: false });
  assert.equal(pgPoolConfig({ DATABASE_URL: "postgres://db-host/x?sslmode=disable" }).ssl, false);
  assert.deepEqual(pgPoolConfig({ DATABASE_URL: "postgres://u@localhost/x", NODE_ENV: "production" }).ssl, { rejectUnauthorized: false });
});

test("the password is a cached token, refreshed inside the 5 minute skew, failures not cached", async () => {
  let calls = 0;
  /** @type {string[]} */
  const scopes = [];
  const pw = pgEntraPassword({ getToken: async (s) => { scopes.push(s); calls++; return { token: `t${calls}`, expiresAt: Date.now() + 3600_000 }; } });
  assert.equal(await pw(), "t1");
  assert.equal(await pw(), "t1");
  assert.deepEqual(scopes, [PG_ENTRA_SCOPE]);
  let n = 0;
  const short = pgEntraPassword({ getToken: async () => { n++; return { token: `s${n}`, expiresOnTimestamp: Date.now() + 120_000 }; } });
  assert.equal(await short(), "s1");
  assert.equal(await short(), "s2");
  let f = 0;
  const flaky = pgEntraPassword({ getToken: async () => { f++; if (f === 1) throw new Error("boom"); return { token: "ok", expiresAt: Date.now() + 3600_000 }; } });
  await assert.rejects(flaky(), /boom/);
  assert.equal(await flaky(), "ok");
});

test("no token source is an error, never a blank password", async () => {
  const pw = pgEntraPassword({ getToken: async () => null });
  await assert.rejects(pw(), /No Entra access token/);
  delete process.env.IDENTITY_ENDPOINT;
  await assert.rejects(pgEntraPassword()(), /No Entra access token/);
});

test("the managed identity token is asked again after a miss, and a boot is not lost to one slow answer", async () => {
  const http = await import("node:http");
  let hits = 0;
  const server = http.createServer((_req, res) => {
    hits++;
    if (hits === 1) { res.socket?.destroy(); return; } // the first ask is reset
    if (hits === 2) { res.statusCode = 500; res.end("not ready"); return; }
    res.setHeader("content-type", "application/json");
    res.end(JSON.stringify({ access_token: "msi-token", expires_on: String(Math.floor(Date.now() / 1000) + 3600) }));
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", () => r(null)));
  const { port } = /** @type {import("node:net").AddressInfo} */ (server.address());
  const saved = { e: process.env.IDENTITY_ENDPOINT, h: process.env.IDENTITY_HEADER };
  process.env.IDENTITY_ENDPOINT = `http://127.0.0.1:${port}/msi/token`;
  process.env.IDENTITY_HEADER = "h";
  try {
    const pw = pgEntraPassword({ msiTimeoutMs: 2000, msiRetryDelaysMs: [5, 5] });
    assert.equal(await pw(), "msi-token");
    assert.equal(hits, 3);
    assert.equal(await pw(), "msi-token");
    assert.equal(hits, 3, "the token is cached after the third ask");
  } finally {
    if (saved.e === undefined) delete process.env.IDENTITY_ENDPOINT; else process.env.IDENTITY_ENDPOINT = saved.e;
    if (saved.h === undefined) delete process.env.IDENTITY_HEADER; else process.env.IDENTITY_HEADER = saved.h;
    server.closeAllConnections();
    await new Promise((r) => server.close(r));
  }
});

test("every ask missing gives up after the last one, never a blank password", async () => {
  const http = await import("node:http");
  let hits = 0;
  const server = http.createServer((_req, res) => { hits++; res.statusCode = 503; res.end("no"); });
  await new Promise((r) => server.listen(0, "127.0.0.1", () => r(null)));
  const { port } = /** @type {import("node:net").AddressInfo} */ (server.address());
  const saved = { e: process.env.IDENTITY_ENDPOINT, h: process.env.IDENTITY_HEADER };
  process.env.IDENTITY_ENDPOINT = `http://127.0.0.1:${port}/msi/token`;
  process.env.IDENTITY_HEADER = "h";
  try {
    await assert.rejects(pgEntraPassword({ msiTimeoutMs: 2000, msiRetryDelaysMs: [5, 5] })(), /No Entra access token/);
    assert.equal(hits, 3);
  } finally {
    if (saved.e === undefined) delete process.env.IDENTITY_ENDPOINT; else process.env.IDENTITY_ENDPOINT = saved.e;
    if (saved.h === undefined) delete process.env.IDENTITY_HEADER; else process.env.IDENTITY_HEADER = saved.h;
    await new Promise((r) => server.close(r));
  }
});

test("the Entra pool waits long enough for the token asks, URL mode keeps 10 s", () => {
  assert.equal(pgPoolConfig(ENTRA).connectionTimeoutMillis, 40_000);
  assert.equal(pgPoolConfig({ DATABASE_URL: "postgres://u@localhost/x" }).connectionTimeoutMillis, 10_000);
});

// -- Slot swap warm-up: the login follows the identity in the token ------------------------------------

const jwt = (/** @type {object} */ claims) => `h.${Buffer.from(JSON.stringify(claims)).toString("base64url")}.s`;
const mirid = (/** @type {string} */ tail) => `/subscriptions/s/resourceGroups/demo/providers/Microsoft.Web/sites/${tail}`;

test("pgUserForToken: a slot token gives the slot login, a production token the app login", () => {
  assert.equal(pgUserForToken(jwt({ xms_mirid: mirid("demo-app-api/slots/staging") }), "demo-app-api"), "demo-app-api/slots/staging");
  assert.equal(pgUserForToken(jwt({ xms_mirid: mirid("demo-app-api") }), "demo-app-api/slots/staging"), "demo-app-api");
  assert.equal(pgUserForToken(jwt({ xms_mirid: mirid("demo-app-api/slots/staging") }), "demo-app-api/slots/staging"), "demo-app-api/slots/staging");
});

test("pgUserForToken keeps PGUSER for another app, a missing claim and a bad token", () => {
  assert.equal(pgUserForToken(jwt({ xms_mirid: mirid("demo-other-api") }), "demo-app-api"), "demo-app-api");
  assert.equal(pgUserForToken(jwt({ oid: "x" }), "demo-app-api"), "demo-app-api");
  assert.equal(pgUserForToken("not-a-jwt", "demo-app-api"), "demo-app-api");
  assert.equal(pgUserForToken("", "demo-app-api"), "demo-app-api");
});

class FakeClient {
  /** @param {any} cfg */
  constructor(cfg) {
    this.connectionParameters = { ...cfg };
    this.user = cfg.user;
    this.password = cfg.password;
    /** @type {any} */
    this.connected = null;
  }
  /** @param {any} [cb] */
  connect(cb) {
    this.connected = { user: this.user, password: this.password };
    if (cb) { cb(null); return undefined; }
    return Promise.resolve();
  }
}

test("a pool built with pg signs in as the token's login even when PGUSER is the other slot's", async () => {
  const token = jwt({ xms_mirid: mirid("demo-x-api/slots/staging") });
  const cfg = pgPoolConfig({ PGHOST: "h", PGDATABASE: "d", PGUSER: "demo-x-api" }, { pg: { Client: FakeClient }, getToken: async () => ({ token, expiresAt: Date.now() + 3600_000 }) });
  const c = new cfg.Client(cfg);
  await c.connect();
  assert.deepEqual(c.connected, { user: "demo-x-api/slots/staging", password: token });
  const viaCallback = new cfg.Client(cfg);
  await new Promise((resolve, reject) => viaCallback.connect((/** @type {any} */ e) => (e ? reject(e) : resolve(undefined))));
  assert.equal(viaCallback.connected.user, "demo-x-api/slots/staging");
});

test("a token failure reaches the caller and nothing connects", async () => {
  const cfg = pgPoolConfig({ PGHOST: "h", PGDATABASE: "d", PGUSER: "u" }, { pg: { Client: FakeClient }, getToken: async () => { throw new Error("no identity"); }, msiRetryDelaysMs: [] });
  const c = new cfg.Client(cfg);
  await assert.rejects(c.connect(), /no identity/);
  assert.equal(c.connected, null);
  const cb = new cfg.Client(cfg);
  const err = await new Promise((resolve) => cb.connect(resolve));
  assert.match(String(err), /no identity/);
});

test("without pg in the options the config has no Client and URL mode is untouched", () => {
  assert.equal(pgPoolConfig({ PGHOST: "h", PGDATABASE: "d", PGUSER: "u" }).Client, undefined);
  assert.equal(pgPoolConfig({ DATABASE_URL: "postgres://u@localhost/x" }, { pg: { Client: FakeClient } }).Client, undefined);
});
