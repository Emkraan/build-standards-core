import { test, before } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import express from "express";
import { P } from "./consumer-preset.js";
import { requestTelemetry, parseSettingString, safeMessage, serverTiming, isDeclaredRoute, setConsumerPreset, getConsumerPreset } from "../../../shell-packages/app-server/index.js";

const CONN = "InstrumentationKey=00000000-0000-0000-0000-000000000000;IngestionEndpoint=https://eastus-8.in.applicationinsights.azure.com/;ApplicationId=11111111-1111-1111-1111-111111111111";
const AAD = "Authorization=AAD";

/**
 * Fake client modules that record what the adapter does with them.
 * @param {{ exportCode?: number, exportError?: unknown, throwOnStart?: boolean }} [opts]
 */
function fakeClient(opts = {}) {
  /** @type {any} */
  const seen = { exporterOptions: null, spans: [], resource: null, exportCalls: 0, closed: false, flushed: false };
  class AzureMonitorTraceExporter {
    /** @param {any} o */
    constructor(o) { seen.exporterOptions = o; }
    /** @param {any[]} _spans @param {(r: any) => void} done */
    export(_spans, done) { seen.exportCalls++; done({ code: opts.exportCode || 0, error: opts.exportError }); }
  }
  class BatchSpanProcessor {
    /** @param {any} exporter */
    constructor(exporter) { this.exporter = exporter; }
  }
  class BasicTracerProvider {
    /** @param {any} o */
    constructor(o) {
      if (opts.throwOnStart) throw new Error("boom Bearer eyJabcdefghijklmnopqrstuvwxyz0123456789");
      seen.resource = o.resource;
      this.processor = o.spanProcessors[0];
    }
    /** @param {string} name */
    getTracer(name) {
      seen.tracerScope = name;
      return {
        /** @param {string} name @param {any} o */
        startSpan: (name, o) => {
          /** @type {any} */
          const span = { name, kind: o.kind, startTime: o.startTime, attributes: o.attributes, status: undefined, endTime: undefined };
          return {
            /** @param {any} s */
            setStatus: (s) => { span.status = s; },
            /** @param {number} t */
            end: (t) => { span.endTime = t; seen.spans.push(span); },
          };
        },
      };
    }
    async forceFlush() {
      seen.flushed = true;
      await new Promise((resolve) => this.processor.exporter.export(seen.spans, resolve));
    }
    async shutdown() { seen.closed = true; }
  }
  const load = () => ({
    exporter: { AzureMonitorTraceExporter },
    traceBase: { BasicTracerProvider, BatchSpanProcessor },
    resources: { resourceFromAttributes: (/** @type {any} */ a) => ({ attributes: a }) },
  });
  return { seen, load };
}

/** @param {Partial<import("../../../shell-packages/app-server/index.js").RequestLogRecord>} over */
function record(over = {}) {
  return /** @type {import("../../../shell-packages/app-server/index.js").RequestLogRecord} */ ({ msg: "request", method: "GET", route: "/api/users/:id", status: 200, ms: 41.2, timings: { jwt: 3.1, rbac: 30.5 }, ...over });
}

const tokenOk = async () => ({ token: "t0k3n", expiresAt: Date.now() + 3600_000 });

// The sink names a request only by a template serverTiming resolved from route
// definitions. Declare the ones these tests send through a real Express app.
before(async () => {
  const app = express();
  app.use(serverTiming({ log: null }));
  for (const p of ["/api/users/:id", "/api/admin/roles", "/api/healthy-things/:id", "/api/health/deep"]) app.get(p, (_req, res) => { res.end(); });
  const server = app.listen(0, "127.0.0.1");
  await new Promise((r) => server.once("listening", () => r(undefined)));
  const addr = /** @type {import("node:net").AddressInfo} */ (server.address());
  await (await fetch(`http://127.0.0.1:${addr.port}/api/users/x`)).text();
  await new Promise((r) => server.close(() => r(undefined)));
  assert.equal(isDeclaredRoute("/api/healthy-things/:id"), true);
});

test("parseSettingString: lowercases keys, keeps values, ignores junk", () => {
  assert.deepEqual(parseSettingString("Authorization=AAD;ClientId=abc; junk ;=x"), { authorization: "AAD", clientid: "abc" });
  assert.equal(parseSettingString(CONN).ingestionendpoint, "https://eastus-8.in.applicationinsights.azure.com/");
  assert.deepEqual(parseSettingString(undefined), {});
});

test("requestTelemetry: off and silent when the connection string is not set, client never loaded", () => {
  let loaded = false;
  const lines = /** @type {string[]} */ ([]);
  const t = requestTelemetry({ connectionString: "", authenticationString: AAD, load: () => { loaded = true; return /** @type {any} */ ({}); }, log: (l) => lines.push(l) });
  assert.equal(t.enabled, false);
  assert.equal(t.sink, null);
  assert.equal(loaded, false);
  assert.deepEqual(lines, []);
});

test("requestTelemetry: refuses to run without Authorization=AAD (no key path)", () => {
  const { load } = fakeClient();
  for (const auth of [undefined, "", "Authorization=Key", "ClientId=abc"]) {
    const lines = /** @type {string[]} */ ([]);
    const t = requestTelemetry({ connectionString: CONN, authenticationString: auth, getToken: tokenOk, load, log: (l) => lines.push(l) });
    assert.equal(t.enabled, false, String(auth));
    assert.equal(t.sink, null);
    assert.match(lines[0] || "", /Authorization=AAD/);
  }
});

test("requestTelemetry: off when there is no managed identity and no token source", () => {
  const saved = { e: process.env.IDENTITY_ENDPOINT, h: process.env.IDENTITY_HEADER };
  delete process.env.IDENTITY_ENDPOINT;
  delete process.env.IDENTITY_HEADER;
  try {
    const { load } = fakeClient();
    const t = requestTelemetry({ connectionString: CONN, authenticationString: AAD, load, log: () => {} });
    assert.equal(t.enabled, false);
    assert.equal(t.reason, "no managed identity in this environment");
  } finally {
    if (saved.e !== undefined) process.env.IDENTITY_ENDPOINT = saved.e;
    if (saved.h !== undefined) process.env.IDENTITY_HEADER = saved.h;
  }
});

test("requestTelemetry: a connection string without an ingestion endpoint is refused", () => {
  const { load } = fakeClient();
  const t = requestTelemetry({ connectionString: "InstrumentationKey=abc", authenticationString: AAD, getToken: tokenOk, load, log: () => {} });
  assert.equal(t.enabled, false);
});

test("requestTelemetry: a client that fails to load or start never throws and logs no secret", () => {
  const lines = /** @type {string[]} */ ([]);
  const t1 = requestTelemetry({ connectionString: CONN, authenticationString: AAD, getToken: tokenOk, load: () => { throw new Error("Cannot find module '@azure/monitor-opentelemetry-exporter'"); }, log: (l) => lines.push(l) });
  assert.equal(t1.enabled, false);
  assert.equal(t1.sink, null);
  assert.match(lines[0] || "", /client failed to start: Cannot find module/);

  const { load } = fakeClient({ throwOnStart: true });
  const t2 = requestTelemetry({ connectionString: CONN, authenticationString: AAD, getToken: tokenOk, load, log: (l) => lines.push(l) });
  assert.equal(t2.enabled, false);
  assert.doesNotMatch(lines.join("\n"), /eyJ/);
});

test("requestTelemetry: exporter gets the connection string, an Entra credential and no offline storage", async () => {
  const { seen, load } = fakeClient();
  const asked = /** @type {any[]} */ ([]);
  const t = requestTelemetry({
    connectionString: CONN,
    authenticationString: "Authorization=AAD;ClientId=22222222-2222-2222-2222-222222222222",
    getToken: async (resource, clientId) => { asked.push([resource, clientId]); return { token: "t0k3n", expiresAt: Date.now() + 3600_000 }; },
    load,
    roleName: "console-api",
    roleVersion: "1.26.2",
    log: () => {},
  });
  assert.equal(t.enabled, true);
  assert.equal(seen.exporterOptions.connectionString, CONN);
  assert.equal(seen.exporterOptions.disableOfflineStorage, true);
  assert.equal("instrumentationKey" in seen.exporterOptions, false);
  const tok = await seen.exporterOptions.credential.getToken(["https://monitor.azure.com//.default"]);
  assert.equal(tok.token, "t0k3n");
  assert.ok(tok.expiresOnTimestamp > Date.now());
  // Cached: a second call does not ask again.
  await seen.exporterOptions.credential.getToken(["https://monitor.azure.com//.default"]);
  assert.deepEqual(asked, [["https://monitor.azure.com/", "22222222-2222-2222-2222-222222222222"]]);
  assert.deepEqual(seen.resource.attributes, { "service.name": "console-api", "service.version": "1.26.2" });
});

test("requestTelemetry: a failed token request yields null (exporter retries later), never a throw", async () => {
  const { seen, load } = fakeClient();
  const t = requestTelemetry({ connectionString: CONN, authenticationString: AAD, getToken: async () => null, load, log: () => {} });
  assert.equal(t.enabled, true);
  assert.equal(await seen.exporterOptions.credential.getToken(["x"]), null);
});

test("sink: one SERVER span per request named by method and route template, with status and duration", () => {
  const { seen, load } = fakeClient();
  let clock = 1_800_000_000_000;
  const t = requestTelemetry({ connectionString: CONN, authenticationString: AAD, getToken: tokenOk, load, log: () => {}, now: () => clock });
  assert.ok(t.sink);
  t.sink(record({ desc: { groups: "hit" } }));
  clock += 10;
  t.sink(record({ method: "post", route: "/api/admin/roles", status: 503, ms: 12, timings: {} }));
  assert.equal(seen.spans.length, 2);
  const [a, b] = seen.spans;
  assert.equal(a.name, "GET /api/users/:id");
  assert.equal(a.kind, 1);
  assert.ok(Math.abs(a.endTime - a.startTime - 41.2) < 0.01);
  assert.deepEqual(a.attributes, {
    "http.request.method": "GET",
    "http.route": "/api/users/:id",
    "http.response.status_code": 200,
    "timing.jwt": 3.1,
    "timing.rbac": 30.5,
    "timing.groups.desc": "hit",
  });
  assert.equal(a.status, undefined);
  assert.equal(b.name, "POST /api/admin/roles");
  assert.deepEqual(b.status, { code: 2 });
});

test("sink: never carries a URL, query string, email or token, even if a record is malformed", () => {
  const { seen, load } = fakeClient();
  const t = requestTelemetry({ connectionString: CONN, authenticationString: AAD, getToken: tokenOk, load, log: () => {} });
  assert.ok(t.sink);
  t.sink(record({
    timings: { "bad name": 1, ok: 2 },
    desc: { ok: "someone at console.example.test", jwt: "eyJhbGciOiJIUzI1NiJ9.payload.sig", groups: "eyJhbGciOiJIUzI1NiJ9", rbac: "a b", upsert: "12345" },
  }));
  const span = seen.spans[0];
  const blob = JSON.stringify(span);
  assert.doesNotMatch(blob, /example\.test|eyJ|\?|url/i);
  assert.deepEqual(Object.keys(span.attributes).sort(), ["http.request.method", "http.response.status_code", "http.route", "timing.ok"]);
});

test("sink: ignores non-request records and never throws", () => {
  const { seen, load } = fakeClient();
  const t = requestTelemetry({ connectionString: CONN, authenticationString: AAD, getToken: tokenOk, load, log: () => {} });
  assert.ok(t.sink);
  const sink = t.sink;
  assert.doesNotThrow(() => sink(/** @type {any} */ (null)));
  assert.doesNotThrow(() => sink(/** @type {any} */ ({ msg: "other" })));
  assert.doesNotThrow(() => sink(/** @type {any} */ ({ msg: "request", timings: 5, desc: "x" })));
  assert.equal(seen.spans.length, 1);
  assert.equal(seen.spans[0].name, "GET -");
});

test("export failures are logged once per window with the credential redacted", async () => {
  const { load } = fakeClient({ exportCode: 1, exportError: new Error("401 Bearer eyJabcdefghijklmnopqrstuvwxyz0123 InstrumentationKey=abc") });
  const lines = /** @type {string[]} */ ([]);
  let clock = 1_800_000_000_000;
  const t = requestTelemetry({ connectionString: CONN, authenticationString: AAD, getToken: tokenOk, load, log: (l) => lines.push(l), now: () => clock });
  assert.ok(t.sink);
  t.sink(record());
  await t.flush();
  await t.flush();
  const failures = lines.filter((l) => l.includes("export_failed"));
  assert.equal(failures.length, 1);
  assert.doesNotMatch(failures[0] || "", /eyJ|InstrumentationKey=abc/);
  clock += 5 * 60 * 1000;
  await t.flush();
  assert.equal(lines.filter((l) => l.includes("export_failed")).length, 2);
  await t.close();
});

test("safeMessage: strips bearer tokens, JWTs and keys and caps the length", () => {
  assert.equal(safeMessage(new Error("Bearer abc.def")), "Bearer [redacted]");
  assert.equal(safeMessage("InstrumentationKey=1234;x"), "InstrumentationKey=[redacted];x");
  assert.equal(safeMessage("x".repeat(500)).length, 200);
});

test("sink: health probes are skipped and a route that was not declared is sent as '-'", () => {
  const { seen, load } = fakeClient();
  const t = requestTelemetry({ connectionString: CONN, authenticationString: AAD, getToken: tokenOk, load, log: () => {} });
  assert.ok(t.sink);
  t.sink(record({ route: "/health" }));
  t.sink(record({ route: "/api/health/deep" }));
  t.sink(record({ route: "/api/users/someone at console.example.test" }));
  t.sink(record({ route: "/api/users/:id?code=abc" }));
  t.sink(record({ route: "/api/users/a%40b" }));
  t.sink(record({ route: "/api/healthy-things/:id" }));
  assert.deepEqual(seen.spans.map((/** @type {any} */ x) => x.name), ["GET -", "GET -", "GET -", "GET /api/healthy-things/:id"]);
  assert.doesNotMatch(JSON.stringify(seen.spans), /example\.test|code=|%40/);
});

test("sink: a route string that no definition produced is sent as '-', whatever its shape", () => {
  const { seen, load } = fakeClient();
  const t = requestTelemetry({ connectionString: CONN, authenticationString: AAD, getToken: tokenOk, load, log: () => {} });
  assert.ok(t.sink);
  const jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJl";
  for (const route of [
    `/api/reset/${jwt}`,
    "/api/devices/LAPTOP-JDOE/apps",
    "/api/devices/laptop-jdoe/apps",
    "/api/users/john.doe",
    "/api/files/secret-token-value",
    "/api/devices/0f8fad5b-d9cb-469f-a165-70867728950e",
    "/api/tickets/123456",
    "/api/users",
    "api/no-leading-slash",
    `/api/${"a".repeat(300)}`,
  ]) t.sink(record({ route }));
  assert.deepEqual(seen.spans.map((/** @type {any} */ x) => x.name), Array(10).fill("GET -"));
  assert.doesNotMatch(JSON.stringify(seen.spans), /eyJ|jdoe|JDOE|john|secret-token|0f8fad5b|123456/);
});

test("credential: a token source that throws yields null, never a rejection", async () => {
  const { seen, load } = fakeClient();
  const t = requestTelemetry({ connectionString: CONN, authenticationString: AAD, getToken: async () => { throw new Error("IMDS down"); }, load, log: () => {} });
  assert.equal(t.enabled, true);
  assert.equal(await seen.exporterOptions.credential.getToken(["x"]), null);
});

test("credential: the default token path calls the App Service identity endpoint for monitor.azure.com", async () => {
  /** @type {any[]} */
  const calls = [];
  const server = http.createServer((req, res) => {
    calls.push({ url: req.url, header: req.headers["x-identity-header"] });
    res.setHeader("content-type", "application/json");
    res.end(JSON.stringify({ access_token: "mi-token", expires_on: String(Math.floor(Date.now() / 1000) + 3600) }));
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(null)));
  const addr = /** @type {import("node:net").AddressInfo} */ (server.address());
  const saved = { e: process.env.IDENTITY_ENDPOINT, h: process.env.IDENTITY_HEADER };
  process.env.IDENTITY_ENDPOINT = `http://127.0.0.1:${addr.port}/msi/token`;
  process.env.IDENTITY_HEADER = "hdr-value";
  try {
    const { seen, load } = fakeClient();
    const t = requestTelemetry({ connectionString: CONN, authenticationString: "Authorization=AAD;ClientId=33333333-3333-3333-3333-333333333333", load, log: () => {} });
    assert.equal(t.enabled, true);
    const tok = await seen.exporterOptions.credential.getToken(["https://monitor.azure.com//.default"]);
    assert.equal(tok.token, "mi-token");
    assert.equal(calls.length, 1);
    const u = new URL(calls[0].url, "http://x");
    assert.equal(u.pathname, "/msi/token");
    assert.equal(u.searchParams.get("resource"), "https://monitor.azure.com/");
    assert.equal(u.searchParams.get("api-version"), "2019-08-01");
    assert.equal(u.searchParams.get("client_id"), "33333333-3333-3333-3333-333333333333");
    assert.equal(calls[0].header, "hdr-value");
  } finally {
    if (saved.e === undefined) delete process.env.IDENTITY_ENDPOINT; else process.env.IDENTITY_ENDPOINT = saved.e;
    if (saved.h === undefined) delete process.env.IDENTITY_HEADER; else process.env.IDENTITY_HEADER = saved.h;
    await new Promise((resolve) => server.close(() => resolve(null)));
  }
});

test("requestTelemetry: service name and tracer scope default from the consumer preset, an option wins", async () => {
  const saved = getConsumerPreset();
  try {
    const a = fakeClient();
    requestTelemetry({ connectionString: CONN, authenticationString: AAD, getToken: tokenOk, load: a.load, log: () => {} });
    assert.equal(a.seen.resource.attributes["service.name"], P.serviceName);
    assert.equal(a.seen.tracerScope, P.tracerScope);

    setConsumerPreset({ serviceName: "example-api", tracerScope: "@example/app-server" });
    const b = fakeClient();
    requestTelemetry({ connectionString: CONN, authenticationString: AAD, getToken: tokenOk, load: b.load, log: () => {} });
    assert.equal(b.seen.resource.attributes["service.name"], "example-api");
    assert.equal(b.seen.tracerScope, "@example/app-server");

    const c = fakeClient();
    requestTelemetry({ connectionString: CONN, authenticationString: AAD, getToken: tokenOk, load: c.load, roleName: "console-api", tracerScope: "own-scope", log: () => {} });
    assert.equal(c.seen.resource.attributes["service.name"], "console-api");
    assert.equal(c.seen.tracerScope, "own-scope");
  } finally {
    setConsumerPreset(saved);
  }
});
