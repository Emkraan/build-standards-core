import "./consumer-preset.js";
import { test } from "node:test";
import assert from "node:assert/strict";
import { createExportRetry, isTransientExportFailure, requestTelemetry } from "../../../shell-packages/app-server/index.js";

const CONN = "InstrumentationKey=00000000-0000-0000-0000-000000000000;IngestionEndpoint=https://eastus-8.in.applicationinsights.azure.com/;ApplicationId=11111111-1111-1111-1111-111111111111";
const AAD = "Authorization=AAD";
const TOKEN_FAIL = () => ({ code: 1, error: new Error("Failed to refresh access token.") });
const OK = () => ({ code: 0 });
const FAST = [5, 10, 20];

/** @param {() => boolean} cond @param {number} [ms] */
async function waitFor(cond, ms = 2000) {
  const end = Date.now() + ms;
  while (!cond()) {
    if (Date.now() > end) throw new Error("timed out waiting");
    await new Promise((r) => setTimeout(r, 2));
  }
}

/** @param {string[]} lines @param {string} event */
const events = (lines, event) => lines.map((l) => JSON.parse(l)).filter((l) => l.event === event);

/**
 * A fake exporter send: answers from a script of results (the last one
 * repeats) and records every batch it was given.
 * @param {Array<() => any>} script
 */
function fakeSend(script) {
  /** @type {any[][]} */
  const calls = [];
  let i = 0;
  /** @param {any[]} spans */
  const send = async (spans) => {
    calls.push(spans.slice());
    const next = script[Math.min(i, script.length - 1)];
    i++;
    return next ? next() : OK();
  };
  return { send, calls };
}

test("isTransientExportFailure: only failures where nothing reached ingestion are retried", () => {
  assert.equal(isTransientExportFailure(TOKEN_FAIL()), true);
  assert.equal(isTransientExportFailure({ code: 1, error: Object.assign(new Error("connect"), { code: "ECONNREFUSED" }) }), true);
  assert.equal(isTransientExportFailure({ code: 1, error: Object.assign(new Error("dns"), { code: "ENOTFOUND" }) }), true);
  assert.equal(isTransientExportFailure({ code: 1, error: Object.assign(new Error("busy"), { statusCode: 503 }) }), true);
  assert.equal(isTransientExportFailure({ code: 1, error: Object.assign(new Error("throttled"), { statusCode: 429 }) }), true);
  // These may have landed: a retry could count the requests twice.
  assert.equal(isTransientExportFailure({ code: 1, error: Object.assign(new Error("socket hang up"), { code: "ECONNRESET" }) }), false);
  assert.equal(isTransientExportFailure({ code: 1, error: Object.assign(new Error("The operation timed out"), { name: "AbortError" }) }), false);
  assert.equal(isTransientExportFailure({ code: 1, error: Object.assign(new Error("gateway"), { statusCode: 504 }) }), false);
  assert.equal(isTransientExportFailure({ code: 1, error: Object.assign(new Error("server"), { statusCode: 500 }) }), false);
  assert.equal(isTransientExportFailure({ code: 1, error: Object.assign(new Error("bad token"), { statusCode: 401 }) }), false);
  assert.equal(isTransientExportFailure({ code: 1, error: Object.assign(new Error("Invalid instrumentation key"), { statusCode: 400 }) }), false);
  assert.equal(isTransientExportFailure({ code: 1 }), false);
  assert.equal(isTransientExportFailure({ code: 0, error: new Error("access token") }), false);
  assert.equal(isTransientExportFailure(null), false);
});

test("a token failure then a success keeps every span, done is answered at once, one retried line", async () => {
  const { send, calls } = fakeSend([TOKEN_FAIL, OK]);
  const lines = /** @type {string[]} */ ([]);
  const r = createExportRetry({ send, log: (l) => lines.push(l), delaysMs: FAST });
  /** @type {any[]} */
  const answers = [];
  r.export(["a", "b", "c"], (res) => answers.push(res));
  await waitFor(() => answers.length === 1);
  assert.equal(answers[0].code, 1, "the processor gets the first answer, without waiting for the retry");
  await waitFor(() => r.stats().retried === 3);
  assert.deepEqual(calls, [["a", "b", "c"], ["a", "b", "c"]]);
  assert.equal(answers.length, 1, "done is called once");
  assert.deepEqual(events(lines, "export_retried").map((l) => l.count), [3]);
  assert.equal(events(lines, "export_dropped").length, 0);
  assert.equal(events(lines, "export_failed").length, 0);
  assert.equal(r.stats().buffered, 0);
  r.stop();
});

test("a failure that keeps going drops the batch after the last retry and counts it", async () => {
  const { send, calls } = fakeSend([TOKEN_FAIL]);
  const lines = /** @type {string[]} */ ([]);
  const r = createExportRetry({ send, log: (l) => lines.push(l), delaysMs: FAST });
  r.export(["a", "b"], () => {});
  await waitFor(() => r.stats().dropped === 2);
  assert.equal(calls.length, 1 + FAST.length, "the first send plus one retry per delay");
  const dropped = events(lines, "export_dropped");
  assert.equal(dropped.length, 1);
  assert.equal(dropped[0].count, 2);
  assert.equal(dropped[0].reason, "retries_exhausted");
  assert.equal(dropped[0].error, "Failed to refresh access token.");
  assert.equal(r.stats().buffered, 0);
  await new Promise((res) => setTimeout(res, 60));
  assert.equal(calls.length, 1 + FAST.length, "nothing is sent after the drop");
  r.stop();
});

test("the buffer cap holds: the oldest spans are dropped and counted, the newest are sent", async () => {
  /** @type {Array<() => any>} */
  const script = [TOKEN_FAIL];
  const { send, calls } = fakeSend(script);
  const lines = /** @type {string[]} */ ([]);
  const r = createExportRetry({ send, log: (l) => lines.push(l), delaysMs: [60_000], maxBuffered: 5 });
  r.export(["a", "b", "c"], () => {});
  r.export(["d", "e", "f"], () => {});
  await waitFor(() => calls.length === 2 && r.stats().buffered === 5);
  assert.equal(r.stats().batches, 2);
  const full = events(lines, "export_dropped").filter((l) => l.reason === "buffer_full");
  assert.deepEqual(full.map((l) => l.count), [1]);
  for (let i = 0; i < 10; i++) r.export([`x${i}`, `y${i}`], () => {});
  await waitFor(() => calls.length === 12 && r.stats().dropped === 1 + 20);
  assert.equal(r.stats().buffered, 5, "never more than the cap waits");
  // The ingestion side recovers: the last attempt sends what is left, newest first kept.
  script.splice(0, script.length, OK);
  await r.drain(500);
  assert.deepEqual(calls.slice(12).flat().sort(), ["x8", "x9", "y7", "y8", "y9"]);
  r.stop();
});

test("a successful export sends the waiting batches at once instead of waiting for the timer", async () => {
  const { send, calls } = fakeSend([TOKEN_FAIL, OK]);
  const lines = /** @type {string[]} */ ([]);
  const r = createExportRetry({ send, log: (l) => lines.push(l), delaysMs: [60_000] });
  r.export(["first"], () => {});
  await waitFor(() => r.stats().buffered === 1);
  r.export(["second"], () => {});
  await waitFor(() => r.stats().retried === 1, 1000);
  assert.deepEqual(calls, [["first"], ["second"], ["first"]]);
  assert.deepEqual(events(lines, "export_retried").map((l) => l.count), [1]);
  r.stop();
});

test("a failure that is not transient is not retried and goes to onFailure", async () => {
  const { send, calls } = fakeSend([() => ({ code: 1, error: Object.assign(new Error("forbidden"), { statusCode: 403 }) })]);
  /** @type {any[]} */
  const failed = [];
  const r = createExportRetry({ send, log: () => {}, delaysMs: FAST, onFailure: (spans) => failed.push(spans) });
  r.export(["a"], () => {});
  await waitFor(() => failed.length === 1);
  await new Promise((res) => setTimeout(res, 40));
  assert.equal(calls.length, 1);
  assert.equal(r.stats().buffered, 0);
  r.stop();
});

test("outcome lines are rate limited per reason and carry counts only, never span content", async () => {
  let clock = 1_800_000_000_000;
  const { send } = fakeSend([TOKEN_FAIL]);
  const lines = /** @type {string[]} */ ([]);
  const r = createExportRetry({ send, log: (l) => lines.push(l), now: () => clock, delaysMs: [] });
  r.export([{ name: "GET /api/users/:id", attributes: { "user.email": "jdoe at console.example.test" } }], () => {});
  r.export([{ name: "x" }, { name: "y" }], () => {});
  await waitFor(() => r.stats().dropped === 3);
  assert.deepEqual(events(lines, "export_dropped").map((l) => l.count), [1], "the second drop waits for the window");
  clock += 5 * 60 * 1000;
  r.export([{ name: "z" }], () => {});
  await waitFor(() => r.stats().dropped === 4);
  assert.deepEqual(events(lines, "export_dropped").map((l) => l.count), [1, 3]);
  r.stop();
  assert.doesNotMatch(lines.join("\n"), /example\.test|jdoe|api\/users/);
});

test("shutdown does not hang on a send that never answers, and what waited is counted", async () => {
  let hang = false;
  const send = (/** @type {any[]} */ _spans) => (hang ? new Promise(() => {}) : Promise.resolve(TOKEN_FAIL()));
  const lines = /** @type {string[]} */ ([]);
  const r = createExportRetry({ send, log: (l) => lines.push(l), delaysMs: [60_000], sendTimeoutMs: 100 });
  r.export(["a", "b"], () => {});
  await waitFor(() => r.stats().buffered === 2);
  hang = true;
  const start = Date.now();
  await r.drain(50);
  r.stop();
  assert.ok(Date.now() - start < 500, "drain is bounded");
  await waitFor(() => r.stats().dropped === 2, 1000);
  assert.deepEqual(events(lines, "export_dropped").map((l) => [l.reason, l.count]), [["shutdown", 2]]);
});

test("a retry that never answers is dropped after the send timeout, never sent again", async () => {
  let n = 0;
  /** @type {any[][]} */
  const calls = [];
  const send = (/** @type {any[]} */ spans) => { calls.push(spans); n++; return n === 1 ? Promise.resolve(TOKEN_FAIL()) : new Promise(() => {}); };
  const lines = /** @type {string[]} */ ([]);
  const r = createExportRetry({ send, log: (l) => lines.push(l), delaysMs: FAST, sendTimeoutMs: 30 });
  r.export(["a"], () => {});
  await waitFor(() => r.stats().dropped === 1);
  await new Promise((res) => setTimeout(res, 80));
  assert.equal(calls.length, 2, "the first send and one retry only");
  assert.deepEqual(events(lines, "export_dropped").map((l) => l.reason), ["timeout"]);
  r.stop();
});

test("recovery sends waiting batches a few at a time, each success starting the next", async () => {
  let failing = true;
  let active = 0;
  let peak = 0;
  /** @type {any[][]} */
  const calls = [];
  const send = async (/** @type {any[]} */ spans) => {
    calls.push(spans);
    if (failing) return TOKEN_FAIL();
    active++;
    peak = Math.max(peak, active);
    await new Promise((r) => setTimeout(r, 5));
    active--;
    return OK();
  };
  const r = createExportRetry({ send, log: () => {}, delaysMs: [60_000] });
  for (let i = 0; i < 20; i++) r.export([`s${i}`], () => {});
  await waitFor(() => r.stats().buffered === 20);
  failing = false;
  r.export(["fresh"], () => {});
  await waitFor(() => r.stats().retried === 20);
  assert.ok(peak <= 5, `peak concurrency ${peak}`);
  r.stop();
});

test("drain gives up on each hung batch within its timeout and counts it before resolving", async () => {
  let hang = false;
  const send = () => (hang ? new Promise(() => {}) : Promise.resolve(TOKEN_FAIL()));
  const lines = /** @type {string[]} */ ([]);
  const r = createExportRetry({ send, log: (l) => lines.push(l), delaysMs: [60_000] });
  r.export(["a", "b", "c"], () => {});
  await waitFor(() => r.stats().buffered === 3);
  hang = true;
  await r.drain(40);
  assert.equal(r.stats().dropped, 3, "counted inside the drain, not 30 s later");
  r.stop();
  assert.deepEqual(events(lines, "export_dropped").map((l) => [l.reason, l.count]), [["shutdown", 3]]);
});

test("after stop every outcome line is written at once", async () => {
  let release = () => {};
  let n = 0;
  const send = () => { n++; return n === 1 ? Promise.resolve(TOKEN_FAIL()) : new Promise((res) => { release = () => res(OK()); }); };
  const lines = /** @type {string[]} */ ([]);
  const r = createExportRetry({ send, log: (l) => lines.push(l), delaysMs: [5] });
  r.export(["a"], () => {});
  await waitFor(() => n === 2);
  r.stop();
  release();
  await waitFor(() => r.stats().retried === 1);
  assert.deepEqual(events(lines, "export_retried").map((l) => l.count), [1]);
});

test("after stop a transient failure is dropped, not kept", async () => {
  const { send } = fakeSend([TOKEN_FAIL]);
  const lines = /** @type {string[]} */ ([]);
  const r = createExportRetry({ send, log: (l) => lines.push(l), delaysMs: FAST });
  r.stop();
  r.export(["a"], () => {});
  await waitFor(() => r.stats().dropped === 1);
  assert.equal(r.stats().buffered, 0);
  assert.equal(events(lines, "export_dropped")[0].reason, "shutdown");
});

/**
 * Fake exporter client whose export answers from a script. Like the real
 * exporter, a failed batch is answered twice: the failure, then a success.
 * @param {Array<"token" | "ok" | "hang">} script
 */
function scriptedClient(script) {
  /** @type {any} */
  const seen = { exported: [], credential: null, shutdown: false };
  let i = 0;
  class AzureMonitorTraceExporter {
    /** @param {any} o */
    constructor(o) { seen.credential = o.credential; }
    /** @param {any[]} spans @param {(r: any) => void} done */
    export(spans, done) {
      const step = script[Math.min(i, script.length - 1)];
      i++;
      if (step === "hang") return;
      if (step === "token") { done(TOKEN_FAIL()); done(OK()); return; }
      seen.exported.push(...spans);
      done(OK());
    }
  }
  class BatchSpanProcessor {
    /** @param {any} exporter */
    constructor(exporter) { this.exporter = exporter; /** @type {any[]} */ this.pending = []; }
  }
  class BasicTracerProvider {
    /** @param {any} o */
    constructor(o) { this.processor = o.spanProcessors[0]; }
    getTracer() {
      return {
        /** @param {string} name */
        startSpan: (name) => ({ setStatus() {}, end: () => { this.processor.pending.push(name); } }),
      };
    }
    async forceFlush() {
      const batch = this.processor.pending.splice(0);
      if (batch.length) await new Promise((resolve) => this.processor.exporter.export(batch, resolve));
    }
    async shutdown() { await this.forceFlush(); seen.shutdown = true; }
  }
  const load = () => ({
    exporter: { AzureMonitorTraceExporter },
    traceBase: { BasicTracerProvider, BatchSpanProcessor },
    resources: { resourceFromAttributes: (/** @type {any} */ a) => ({ attributes: a }) },
  });
  return { seen, load };
}

const rec = { msg: "request", method: "GET", route: "-", status: 200, ms: 3 };

test("requestTelemetry: the first batch after a start survives a token that is not ready yet", async () => {
  const { seen, load } = scriptedClient(["token", "ok"]);
  const lines = /** @type {string[]} */ ([]);
  const t = requestTelemetry({ connectionString: CONN, authenticationString: AAD, getToken: async () => ({ token: "t", expiresAt: Date.now() + 3600_000 }), load, log: (l) => lines.push(l), retryDelaysMs: FAST });
  assert.ok(t.sink);
  for (let i = 0; i < 9; i++) t.sink(/** @type {any} */ (rec));
  await t.flush();
  await waitFor(() => seen.exported.length === 9);
  assert.equal(events(lines, "export_failed").length, 0);
  assert.deepEqual(events(lines, "export_retried").map((l) => l.count), [9]);
  await t.close();
  assert.equal(seen.shutdown, true);
});

test("requestTelemetry: close stays short when a retry hangs", async () => {
  const { load } = scriptedClient(["token", "hang"]);
  const t = requestTelemetry({ connectionString: CONN, authenticationString: AAD, getToken: async () => null, load, log: () => {}, retryDelaysMs: [5] });
  assert.ok(t.sink);
  t.sink(/** @type {any} */ (rec));
  await t.flush();
  await new Promise((r) => setTimeout(r, 30));
  const start = Date.now();
  await t.close();
  assert.ok(Date.now() - start < 2500, `close took ${Date.now() - start} ms`);
});

test("requestTelemetry: a hung identity endpoint counts as no token after the timeout, never a hung slot", async () => {
  let calls = 0;
  const { seen, load } = scriptedClient(["ok"]);
  const t = requestTelemetry({ connectionString: CONN, authenticationString: AAD, getToken: () => { calls++; return calls === 1 ? new Promise(() => {}) : Promise.resolve({ token: "t", expiresAt: Date.now() + 3600_000 }); }, load, log: () => {}, tokenTimeoutMs: 20 });
  assert.equal(t.enabled, true);
  // The startup request hangs. After the timeout the next caller starts a fresh request.
  await new Promise((r) => setTimeout(r, 40));
  const tok = await seen.credential.getToken(["x"]);
  assert.equal(tok && tok.token, "t");
  assert.equal(calls, 2);
});

test("requestTelemetry: the identity token is asked for at startup without waiting for it", async () => {
  let calls = 0;
  const { load } = scriptedClient(["ok"]);
  const t = requestTelemetry({ connectionString: CONN, authenticationString: AAD, getToken: () => { calls++; return new Promise(() => {}); }, load, log: () => {} });
  assert.equal(t.enabled, true, "startup returned while the token request is still open");
  await new Promise((r) => setTimeout(r, 5));
  assert.equal(calls, 1);
});
