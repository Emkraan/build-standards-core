// Gateway guard. Synthetic keys and tokens only: a local RSA key pair stands in for the
// tenant signing keys, and every id below is made up.
import { test } from "node:test";
import assert from "node:assert/strict";
import { generateKeyPairSync, sign } from "node:crypto";
import express from "express";
import {
  gatewayGuard,
  verifyGatewayToken,
  takeGatewayHeader,
  gatewayAudiences,
  parseGatewayEnforce,
  createSigningKeyCache,
  GATEWAY_HEADER,
  setConsumerPreset,
  getConsumerPreset,
  resetConsumerPreset,
  CONSUMER_PRESET_DEFAULTS,
} from "../../../shell-packages/app-server/index.js";

const TENANT = "11111111-2222-3333-4444-555555555555";
const GATEWAY_OID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";
const OTHER_OID = "99999999-8888-7777-6666-555555555555";
const AUD = "api://00000000-1111-2222-3333-444444444444";
const KID = "test-kid-1";

const { privateKey, publicKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
const other = generateKeyPairSync("rsa", { modulusLength: 2048 });
const jwk = publicKey.export({ format: "jwk" });

/** @param {any} obj */
const b64 = (obj) => Buffer.from(JSON.stringify(obj)).toString("base64url");

/**
 * @param {Record<string, unknown>} [over]
 * @param {{ alg?: string, kid?: string, key?: import("node:crypto").KeyObject }} [opt]
 */
function mint(over = {}, opt = {}) {
  const now = Math.floor(Date.now() / 1000);
  const header = { alg: opt.alg ?? "RS256", typ: "JWT", kid: opt.kid ?? KID };
  const claims = {
    aud: AUD,
    iss: `https://sts.windows.net/${TENANT}/`,
    tid: TENANT,
    oid: GATEWAY_OID,
    idtyp: "app",
    roles: ["gateway"],
    nbf: now - 10,
    exp: now + 3600,
    ...over,
  };
  const input = `${b64(header)}.${b64(claims)}`;
  const sig = sign("RSA-SHA256", Buffer.from(input), opt.key ?? privateKey).toString("base64url");
  return `${input}.${sig}`;
}

const keys = createSigningKeyCache({ tenantId: TENANT, fetchKeys: async () => ({ keys: [{ ...jwk, kid: KID, use: "sig" }] }) });
const ENV = { TENANT_ID: TENANT, GATEWAY_PRINCIPAL_ID: GATEWAY_OID, GATEWAY_AUDIENCE: AUD };
const cfg = { tenantId: TENANT, principalId: GATEWAY_OID, audiences: gatewayAudiences(`${AUD},${AUD.replace("api://", "")}`), keys };

test("a token from the tier's gateway identity passes", async () => {
  assert.deepEqual(await verifyGatewayToken(mint(), cfg), { ok: true });
  assert.deepEqual(await verifyGatewayToken(mint({ iss: `https://login.microsoftonline.com/${TENANT}/v2.0`, aud: AUD.replace("api://", "") }), cfg), { ok: true });
});

test("every bad token is refused with its reason", async () => {
  const now = Math.floor(Date.now() / 1000);
  const cases = [
    [undefined, "missing"],
    ["abc", "malformed"],
    ["a.b.c d", "malformed"],
    [mint({}, { alg: "HS256" }), "alg"],
    [mint({ tid: OTHER_OID }), "tenant"],
    [mint({ iss: "https://evil.example.test/" }), "issuer"],
    [mint({ aud: "api://other" }), "audience"],
    [mint({ exp: now - 3600 }), "expired"],
    [mint({ nbf: now + 3600 }), "not_yet_valid"],
    [mint({ oid: OTHER_OID }), "principal"],
    [mint({ idtyp: "user" }), "principal"],
    [mint({ roles: [] }), "role"],
    [mint({ roles: undefined }), "role"],
    [mint({}, { kid: "unknown-kid" }), "unknown_key"],
    [mint({}, { key: other.privateKey }), "signature"],
  ];
  for (const [token, reason] of cases) {
    assert.deepEqual(await verifyGatewayToken(/** @type {any} */ (token), cfg), { ok: false, reason }, String(reason));
  }
});

test("audiences are exactly the configured values and enforce parses strictly", () => {
  assert.deepEqual(gatewayAudiences("api://x, y, y").sort(), ["api://x", "y"]);
  assert.deepEqual(gatewayAudiences(undefined), []);
  assert.equal(parseGatewayEnforce(" ON "), true);
  assert.equal(parseGatewayEnforce("true"), false);
  assert.equal(parseGatewayEnforce(undefined), false);
});

test("signing keys: a failed read is not cached and reports unavailable", async () => {
  let calls = 0;
  let t = 0;
  const k = createSigningKeyCache({
    tenantId: TENANT,
    now: () => t,
    fetchKeys: async () => {
      calls += 1;
      if (calls === 1) throw new Error("boom");
      return { keys: [{ ...jwk, kid: KID }] };
    },
  });
  assert.equal(await k.get(KID), undefined);
  assert.equal(await k.get(KID), undefined);
  assert.equal(calls, 1, "a failed read is not retried inside the refetch window");
  t = 120000;
  assert.ok(await k.get(KID));
  assert.equal(await k.get("nope"), null);
  assert.equal(calls, 2, "unknown kid inside the refetch window does not refetch");
});

test("signing keys: an outage after a good read keeps serving the last good keys, one read per window", async () => {
  let calls = 0;
  let t = 0;
  let up = true;
  const k = createSigningKeyCache({
    tenantId: TENANT,
    now: () => t,
    fetchKeys: async () => {
      calls += 1;
      if (!up) throw new Error("down");
      return { keys: [{ ...jwk, kid: KID }] };
    },
  });
  k.warm();
  assert.ok(await k.get(KID));
  assert.equal(calls, 1, "warm and the first get share one read");
  up = false;
  t = 700000;
  assert.ok(await k.get(KID), "stale keys still serve when the refresh fails");
  assert.ok(await k.get(KID));
  assert.ok(await k.get(KID));
  assert.equal(calls, 2, "one failed refresh per window, not one per request");
});

test("the header is removed from headers and rawHeaders even with no settings", async () => {
  const mw = gatewayGuard({ env: {}, log: () => {} });
  const req = { path: "/api/things", headers: { [GATEWAY_HEADER]: "tok", a: "1" }, rawHeaders: ["A", "1", "X-Gateway-Token", "tok", "x-gateway-token", "tok2"] };
  let called = false;
  mw(req, {}, () => { called = true; });
  assert.ok(called);
  assert.deepEqual(req.headers, { a: "1" });
  assert.deepEqual(req.rawHeaders, ["A", "1"]);
});

test("some but not all settings logs misconfigured at startup", () => {
  /** @type {string[]} */
  const lines = [];
  gatewayGuard({ env: { GATEWAY_PRINCIPAL_ID: GATEWAY_OID, GATEWAY_AUDIENCE: AUD }, log: (l) => lines.push(l) });
  assert.ok(lines.some((l) => l.includes('"misconfigured"') && l.includes("TENANT_ID")));
});

test("log only does not wait on a slow signing key read", async () => {
  /** @type {(v: any) => void} */
  let release = () => {};
  const slow = { get: () => new Promise((r) => { release = r; }) };
  const mw = gatewayGuard({ env: { ...ENV }, keys: slow, log: () => {} });
  const req = { path: "/api/things", headers: { [GATEWAY_HEADER]: mint() }, rawHeaders: [] };
  let called = false;
  mw(req, {}, () => { called = true; });
  assert.ok(called, "next ran before the key read settled");
  release(undefined);
});

/**
 * @param {import("../../../shell-packages/app-server/index.js").GatewayGuardOptions} opts
 */
async function serve(opts) {
  const app = express();
  /** @type {string[]} */
  const lines = [];
  /** @type {any[]} */
  const seenHeaders = [];
  app.use(gatewayGuard({ log: (l) => lines.push(l), keys, ...opts }));
  app.get("/health", (_req, res) => res.json({ ok: true }));
  app.get("/api/version", (_req, res) => res.json({ v: 1 }));
  app.get("/", (_req, res) => res.json({ root: true }));
  app.get("/api/things", (req, res) => {
    seenHeaders.push(req.headers[GATEWAY_HEADER]);
    res.json({ ok: true });
  });
  const server = app.listen(0);
  await new Promise((r) => server.once("listening", r));
  const port = /** @type {import("node:net").AddressInfo} */ (server.address()).port;
  /** @param {string} p @param {Record<string, string>} [h] */
  const get = (p, h = {}) => fetch(`http://127.0.0.1:${port}${p}`, { headers: h });
  return { get, lines, seenHeaders, close: () => new Promise((r) => server.close(r)) };
}


test("log only (default): direct calls still work and are logged once per window", async () => {
  const s = await serve({ env: { ...ENV } });
  try {
    assert.equal((await s.get("/api/things")).status, 200);
    assert.equal((await s.get("/api/things")).status, 200);
    const refused = s.lines.filter((l) => l.includes("would_refuse"));
    assert.equal(refused.length, 1);
    assert.match(refused[0] ?? "", /"reason":"missing"/);
    assert.match(s.lines[0] ?? "", /"gateway":"log_only"/);
  } finally {
    await s.close();
  }
});

test("log only with no settings at all changes nothing and logs nothing per request", async () => {
  const s = await serve({ env: {} });
  try {
    assert.equal((await s.get("/api/things")).status, 200);
    assert.equal(s.lines.length, 1);
    assert.match(s.lines[0] ?? "", /"configured":false/);
  } finally {
    await s.close();
  }
});

test("enforce: no token is 403, a good token passes and the header is removed, health stays open", async () => {
  const s = await serve({ env: { ...ENV, GATEWAY_ENFORCE: "on" } });
  try {
    assert.equal((await s.get("/api/things")).status, 403);
    assert.equal((await s.get("/api/things", { [GATEWAY_HEADER]: mint({ oid: OTHER_OID }) })).status, 403);
    assert.equal((await s.get("/api/things", { [GATEWAY_HEADER]: mint() })).status, 200);
    assert.deepEqual(s.seenHeaders, [undefined]);
    assert.equal((await s.get("/health")).status, 200);
    assert.equal((await s.get("/api/version")).status, 200);
  } finally {
    await s.close();
  }
});

test("enforce with unreadable signing keys fails closed with 503", async () => {
  const dead = createSigningKeyCache({ tenantId: TENANT, fetchKeys: async () => { throw new Error("down"); } });
  const s = await serve({ env: { ...ENV, GATEWAY_ENFORCE: "on" }, keys: dead });
  try {
    assert.equal((await s.get("/api/things", { [GATEWAY_HEADER]: mint() })).status, 503);
  } finally {
    await s.close();
  }
});

test("enforce without settings refuses everything but health", async () => {
  const s = await serve({ env: { GATEWAY_ENFORCE: "on" } });
  try {
    assert.equal((await s.get("/api/things", { [GATEWAY_HEADER]: mint() })).status, 403);
    assert.equal((await s.get("/health")).status, 200);
  } finally {
    await s.close();
  }
});

test("platform pings are still refused but log as platform_ping, never as refused", async () => {
  const s = await serve({ env: { ...ENV, GATEWAY_ENFORCE: "on" } });
  try {
    assert.equal((await s.get("/", { "user-agent": "AlwaysOn" })).status, 403);
    assert.equal((await s.get("/robots933456.txt", { "user-agent": "HealthCheck/1.0" })).status, 403);
    await new Promise((r) => setTimeout(r, 20));
    const kinds = s.lines.slice(1).map((l) => JSON.parse(l).gateway);
    assert.deepEqual(kinds, ["platform_ping"]);
    assert.match(s.lines[1] ?? "", /"reason":"missing"/);
  } finally {
    await s.close();
  }
});

test("a ping path is a real refusal when it carries a bearer token, and other paths ignore the user agent", async () => {
  const s = await serve({ env: { ...ENV, GATEWAY_ENFORCE: "on" } });
  try {
    assert.equal((await s.get("/", { authorization: "Bearer x" })).status, 403);
    assert.equal((await s.get("/api/things", { "user-agent": "AlwaysOn" })).status, 403);
    await new Promise((r) => setTimeout(r, 20));
    const kinds = s.lines.slice(1).map((l) => JSON.parse(l).gateway);
    assert.deepEqual(kinds, ["refused"]);
  } finally {
    await s.close();
  }
});

test("platform_ping and refused keep separate log windows", async () => {
  let clock = 0;
  const s = await serve({ env: { ...ENV, GATEWAY_ENFORCE: "on" }, now: () => clock });
  try {
    await s.get("/");
    await s.get("/api/things");
    await s.get("/");
    clock = 61000;
    await s.get("/");
    await new Promise((r) => setTimeout(r, 20));
    const out = s.lines.slice(1).map((l) => JSON.parse(l));
    assert.deepEqual(out.map((o) => o.gateway), ["platform_ping", "refused", "platform_ping"]);
    assert.equal(out[2].count, 2);
  } finally {
    await s.close();
  }
});

test("log only: a ping is logged as platform_ping and still served", async () => {
  const s = await serve({ env: { ...ENV } });
  try {
    assert.equal((await s.get("/")).status, 200);
    await new Promise((r) => setTimeout(r, 50));
    assert.deepEqual(s.lines.slice(1).map((l) => JSON.parse(l).gateway), ["platform_ping"]);
  } finally {
    await s.close();
  }
});

// A shell with its own header, role and request property passes them as options.
const CUSTOM_HEADER = "x-shell-gateway";
const CUSTOM_ROLE = "shell:gateway";

/** @param {Record<string, unknown>} [opts] */
async function serveCustom(opts = {}) {
  const app = express();
  /** @type {any[]} */
  const seen = [];
  app.use(gatewayGuard({
    log: () => {},
    keys,
    env: { ...ENV, GATEWAY_ENFORCE: "on" },
    header: CUSTOM_HEADER,
    role: CUSTOM_ROLE,
    requestProperty: "shellGateway",
    ...opts,
  }));
  app.get("/api/things", (req, res) => {
    const r = /** @type {any} */ (req);
    seen.push({ headers: { ...req.headers }, raw: [...req.rawHeaders], shellGateway: r.shellGateway, gateway: r.gateway });
    res.json({ ok: true });
  });
  const server = app.listen(0);
  await new Promise((r) => server.once("listening", r));
  const port = /** @type {import("node:net").AddressInfo} */ (server.address()).port;
  /** @param {Record<string, string>} h */
  const get = (h) => fetch(`http://127.0.0.1:${port}/api/things`, { headers: h });
  return { get, seen, close: () => new Promise((r) => server.close(r)) };
}

test("a custom header and role: the token under the custom name passes and the header is stripped", async () => {
  const s = await serveCustom();
  try {
    assert.equal((await s.get({ [CUSTOM_HEADER]: mint({ roles: [CUSTOM_ROLE] }) })).status, 200);
    const got = s.seen[0];
    assert.equal(got.headers[CUSTOM_HEADER], undefined);
    assert.ok(!got.raw.some((/** @type {string} */ h) => h.toLowerCase() === CUSTOM_HEADER));
    assert.deepEqual(got.shellGateway, { ok: true, reason: "ok" });
    assert.deepEqual(got.gateway, got.shellGateway, "req.gateway is set next to the custom property");
  } finally {
    await s.close();
  }
});

test("a custom header and role: the core's header and role no longer count", async () => {
  const s = await serveCustom();
  try {
    assert.equal((await s.get({ [GATEWAY_HEADER]: mint({ roles: [CUSTOM_ROLE] }) })).status, 403, "wrong header");
    assert.equal((await s.get({ [CUSTOM_HEADER]: mint() })).status, 403, "token carries the core role, not the custom one");
    assert.equal(s.seen.length, 0);
  } finally {
    await s.close();
  }
});

test("a custom header is stripped from req.headers whatever the settings", async () => {
  const mw = gatewayGuard({ env: {}, log: () => {}, header: "X-Shell-Gateway" });
  const req = { path: "/api/things", headers: { [CUSTOM_HEADER]: "tok", [GATEWAY_HEADER]: "keep", a: "1" }, rawHeaders: ["X-Shell-Gateway", "tok", "A", "1"] };
  let called = false;
  mw(req, {}, () => { called = true; });
  assert.ok(called);
  assert.deepEqual(req.headers, { [GATEWAY_HEADER]: "keep", a: "1" }, "only the configured header goes");
  assert.deepEqual(req.rawHeaders, ["A", "1"]);
});

test("takeGatewayHeader reads, removes and defaults to the core header", () => {
  const a = { headers: { [GATEWAY_HEADER]: "t1" }, rawHeaders: ["X-Gateway-Token", "t1"] };
  assert.equal(takeGatewayHeader(a), "t1");
  assert.deepEqual(a, { headers: {}, rawHeaders: [] });
  const b = { headers: { [CUSTOM_HEADER]: ["t2", "t3"] }, rawHeaders: [] };
  assert.equal(takeGatewayHeader(b, "X-Shell-Gateway"), "t2");
  assert.deepEqual(b.headers, {});
});

test("an empty role skips the role check and a refusal message can be set", async () => {
  const s = await serveCustom({ role: "", refusalMessage: "Use the gateway." });
  try {
    assert.equal((await s.get({ [CUSTOM_HEADER]: mint({ roles: [] }) })).status, 200);
    const res = await s.get({});
    assert.equal(res.status, 403);
    assert.equal(/** @type {any} */ (await res.json()).message, "Use the gateway.");
  } finally {
    await s.close();
  }
});

test("verifyGatewayToken takes the role from its settings", async () => {
  assert.deepEqual(await verifyGatewayToken(mint({ roles: [CUSTOM_ROLE] }), { ...cfg, role: CUSTOM_ROLE }), { ok: true });
  assert.deepEqual(await verifyGatewayToken(mint({ roles: [CUSTOM_ROLE] }), cfg), { ok: false, reason: "role" });
});

// --- Consumer preset: set once, read by every gateway function ---

const PRESET = {
  header: "X-Shell-Gateway",
  role: CUSTOM_ROLE,
  requestProperty: "shellGateway",
  refusalMessage: "Use the shell gateway.",
  settings: { enforce: "SHELL_ENFORCE", principalId: "SHELL_PRINCIPAL", audience: "SHELL_AUDIENCE", tenantId: "SHELL_TENANT" },
};
const PRESET_ENV = { SHELL_TENANT: TENANT, SHELL_PRINCIPAL: GATEWAY_OID, SHELL_AUDIENCE: AUD, SHELL_ENFORCE: "on" };

test("preset: with no preset the core defaults stand", () => {
  resetConsumerPreset();
  assert.deepEqual(getConsumerPreset(), CONSUMER_PRESET_DEFAULTS);
  assert.equal(getConsumerPreset().header, GATEWAY_HEADER);
});

test("preset: verifyGatewayToken, takeGatewayHeader and the guard read it with no per-call options", async () => {
  setConsumerPreset(PRESET);
  try {
    assert.equal(getConsumerPreset().header, CUSTOM_HEADER, "header is lower cased");
    assert.deepEqual(await verifyGatewayToken(mint({ roles: [CUSTOM_ROLE] }), cfg), { ok: true });
    assert.deepEqual(await verifyGatewayToken(mint(), cfg), { ok: false, reason: "role" });
    assert.equal(takeGatewayHeader({ headers: { [CUSTOM_HEADER]: "tok" }, rawHeaders: [] }), "tok");

    const app = express();
    /** @type {any[]} */
    const seen = [];
    app.use(gatewayGuard({ log: () => {}, keys, env: PRESET_ENV }));
    app.get("/api/things", (req, res) => {
      const r = /** @type {any} */ (req);
      seen.push({ headers: { ...req.headers }, shellGateway: r.shellGateway, gateway: r.gateway });
      res.json({ ok: true });
    });
    const server = app.listen(0);
    await new Promise((r) => server.once("listening", r));
    const port = /** @type {import("node:net").AddressInfo} */ (server.address()).port;
    /** @param {Record<string, string>} h */
    const get = (h) => fetch(`http://127.0.0.1:${port}/api/things`, { headers: h });
    try {
      assert.equal((await get({ [CUSTOM_HEADER]: mint({ roles: [CUSTOM_ROLE] }) })).status, 200);
      assert.equal(seen[0].headers[CUSTOM_HEADER], undefined, "the preset header is stripped");
      assert.deepEqual(seen[0].shellGateway, { ok: true, reason: "ok" });
      assert.deepEqual(seen[0].gateway, seen[0].shellGateway);
      const refused = await get({ [CUSTOM_HEADER]: mint() });
      assert.equal(refused.status, 403);
      assert.equal(/** @type {any} */ (await refused.json()).message, "Use the shell gateway.");
    } finally {
      await new Promise((r) => server.close(r));
    }
  } finally {
    resetConsumerPreset();
  }
});

test("preset: a per-call option still overrides it", async () => {
  setConsumerPreset(PRESET);
  try {
    assert.deepEqual(await verifyGatewayToken(mint(), { ...cfg, role: "gateway" }), { ok: true });
    assert.equal(takeGatewayHeader({ headers: { "x-other": "tok" }, rawHeaders: [] }, "x-other"), "tok");
    const lines = /** @type {string[]} */ ([]);
    const mw = gatewayGuard({ env: { ...PRESET_ENV, SHELL_TENANT: "nope" }, log: (l) => lines.push(l), header: "x-call-header", tenantId: TENANT });
    const req = { path: "/api/things", headers: { "x-call-header": "t", [CUSTOM_HEADER]: "keep" }, rawHeaders: [] };
    mw(req, {}, () => {});
    assert.deepEqual(req.headers, { [CUSTOM_HEADER]: "keep" });
    assert.ok(!lines.some((l) => l.includes("misconfigured")), "the tenant came from the option");
  } finally {
    resetConsumerPreset();
  }
});

test("preset: the misconfigured log prints the setting names the consumer configured", () => {
  setConsumerPreset(PRESET);
  try {
    const lines = /** @type {string[]} */ ([]);
    gatewayGuard({ env: { SHELL_PRINCIPAL: "not-a-guid" }, log: (l) => lines.push(l) });
    const mis = lines.map((l) => JSON.parse(l)).find((o) => o.gateway === "misconfigured");
    assert.deepEqual(mis.missing_or_invalid, ["SHELL_PRINCIPAL", "SHELL_TENANT", "SHELL_AUDIENCE"]);
  } finally {
    resetConsumerPreset();
  }
  const lines = /** @type {string[]} */ ([]);
  gatewayGuard({ env: { GATEWAY_PRINCIPAL_ID: "not-a-guid" }, log: (l) => lines.push(l) });
  const mis = lines.map((l) => JSON.parse(l)).find((o) => o.gateway === "misconfigured");
  assert.deepEqual(mis.missing_or_invalid, ["GATEWAY_PRINCIPAL_ID", "TENANT_ID", "GATEWAY_AUDIENCE"]);
});

test("preset: each call replaces the last, empty fields fall back, an empty role skips the role check", async () => {
  setConsumerPreset(PRESET);
  setConsumerPreset({ header: "  ", role: "" });
  try {
    const p = getConsumerPreset();
    assert.equal(p.header, GATEWAY_HEADER);
    assert.equal(p.requestProperty, "gateway");
    assert.deepEqual(p.settings, CONSUMER_PRESET_DEFAULTS.settings);
    assert.deepEqual(await verifyGatewayToken(mint({ roles: [] }), cfg), { ok: true });
    assert.throws(() => { /** @type {any} */ (p).header = "x"; });
  } finally {
    resetConsumerPreset();
  }
});
