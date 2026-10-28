// Route names come only from route definitions. These tests run real Express 4
// apps through serverTiming and check the name in the log record for mounts with params, nested routers,
// camelCase and digit literals, unknown paths and 404s.
import { test } from "node:test";
import assert from "node:assert/strict";
import express from "express";
import { serverTiming, mountTemplateOf } from "../../../shell-packages/app-server/index.js";

/**
 * Mount serverTiming (log and sink) on a fresh app, let `define` add routes,
 * request every path in order, and return the log routes.
 * @param {(app: import("express").Express) => void} define
 * @param {string[]} paths
 */
async function run(define, paths) {
  /** @type {string[]} */
  const lines = [];
  /** @type {string[]} */
  const routes = [];
  const app = express();
  app.use(serverTiming({ log: (l) => lines.push(l), sink: (r) => { routes.push(r.route); } }));
  define(app);
  const server = app.listen(0, "127.0.0.1");
  await new Promise((r) => server.once("listening", () => r(undefined)));
  const addr = /** @type {import("node:net").AddressInfo} */ (server.address());
  /** @type {number[]} */
  const statuses = [];
  try {
    for (const p of paths) {
      const res = await fetch(`http://127.0.0.1:${addr.port}${p}`);
      await res.text();
      statuses.push(res.status);
    }
    await new Promise((r) => setTimeout(r, 20));
  } finally {
    await new Promise((r) => server.close(() => r(undefined)));
  }
  return { routes, lines, statuses };
}

/** @type {import("express").RequestHandler} */
const ok = (_req, res) => { res.json({ ok: true }); };

test("a router mounted on a path with params is named by its declared templates, never the concrete id", async () => {
  const { routes, lines } = await run((app) => {
    const device = express.Router({ mergeParams: true });
    device.get("/", ok);
    device.get("/apps/:appId", ok);
    app.use("/api/devices/:id", device);
  }, [
    "/api/devices/laptop-jdoe",
    "/api/devices/laptop-jdoe/",
    "/api/devices/john.doe/apps/secret-token-value",
    "/api/devices/0f8fad5b-d9cb-469f-a165-70867728950e/apps/x?email=someone@example.com",
  ]);
  assert.deepEqual(routes, ["/api/devices/:id", "/api/devices/:id", "/api/devices/:id/apps/:appId", "/api/devices/:id/apps/:appId"]);
  const everything = JSON.stringify({ routes, lines });
  assert.doesNotMatch(everything, /jdoe|john|secret-token|0f8fad5b|example|email=/);
});

test("nested routers with params at every level", async () => {
  const { routes } = await run((app) => {
    const leaf = express.Router({ mergeParams: true });
    leaf.get("/:leafId", ok);
    const mid = express.Router({ mergeParams: true });
    mid.use("/:midId/leaves", leaf);
    app.use("/api/trees/:treeId/branches", mid);
  }, ["/api/trees/oak/branches/north/leaves/abc"]);
  assert.deepEqual(routes, ["/api/trees/:treeId/branches/:midId/leaves/:leafId"]);
});

test("camelCase and digit literals in declared templates keep their names", async () => {
  const { routes } = await run((app) => {
    const r = express.Router();
    r.get("/deskPhones/e911v2", ok);
    r.get("/2fa", ok);
    r.get("/o365users-sync", ok);
    app.use("/api/m365-licenses.v2", r);
    app.get("/api/v1/deskPhones/:deskPhoneId", ok);
  }, ["/api/m365-licenses.v2/deskPhones/e911v2", "/api/m365-licenses.v2/2fa", "/api/m365-licenses.v2/o365users-sync", "/api/v1/deskPhones/abc123"]);
  assert.deepEqual(routes, ["/api/m365-licenses.v2/deskPhones/e911v2", "/api/m365-licenses.v2/2fa", "/api/m365-licenses.v2/o365users-sync", "/api/v1/deskPhones/:deskPhoneId"]);
});

test("unknown paths, 404s and middleware-only responses are '-'", async () => {
  const { routes, statuses, lines } = await run((app) => {
    // Answered by middleware on a mount (no route matched), like a 401 gate.
    app.use("/api/locked", (_req, res) => { res.status(401).end(); });
    const r = express.Router();
    r.get("/known", ok);
    app.use("/api/things/:id", r);
  }, ["/api/locked/laptop-jdoe", "/api/things/laptop-jdoe/unknown", "/nope/john.doe"]);
  assert.deepEqual(statuses, [401, 404, 404]);
  assert.deepEqual(routes, ["-", "-", "-"]);
  assert.doesNotMatch(JSON.stringify(lines), /jdoe|john/);
});

test("the same router mounted at two paths gets the prefix of the mount that matched", async () => {
  const { routes } = await run((app) => {
    const r = express.Router({ mergeParams: true });
    r.get("/:id", ok);
    app.use("/api/users", (_req, _res, next) => next(), r);
    app.use("/api/admins/:tenant", r);
  }, ["/api/users/abc", "/api/admins/acme/abc"]);
  assert.deepEqual(routes, ["/api/users/:id", "/api/admins/:tenant/:id"]);
});

test("an error handler after the route keeps the declared name", async () => {
  const { routes, statuses } = await run((app) => {
    const r = express.Router();
    r.get("/:id", () => { throw new Error("boom"); });
    app.use("/api/items", r);
    app.use((/** @type {any} */ _err, /** @type {any} */ _req, /** @type {any} */ res, /** @type {any} */ _next) => { res.status(500).end(); });
  }, ["/api/items/laptop-jdoe"]);
  assert.deepEqual(statuses, [500]);
  assert.deepEqual(routes, ["/api/items/:id"]);
});

test("a mount that cannot be proven (regexp or array path, sub-app) is '-'", async () => {
  const { routes } = await run((app) => {
    const r = express.Router();
    r.get("/x", ok);
    app.use(/^\/api\/re\/[a-z-]+/, r);
    app.use(["/api/a", "/api/b"], r);
    const sub = express();
    sub.get("/y", ok);
    app.use("/api/sub", sub);
    app.get(/^\/api\/rx\/.*$/, ok);
  }, ["/api/re/laptop-jdoe/x", "/api/a/x", "/api/sub/y", "/api/rx/john.doe"]);
  assert.deepEqual(routes, ["-", "-", "-", "-"]);
});

test("a route added after the first request is resolved on its first use", async () => {
  const { routes } = await run((app) => {
    app.get("/api/first", ok);
    app.get("/api/add", (_req, res) => { app.get("/api/late/:id", ok); res.end(); });
  }, ["/api/first", "/api/add", "/api/late/laptop-jdoe"]);
  assert.deepEqual(routes, ["/api/first", "/api/add", "/api/late/:id"]);
});

test("mountTemplateOf rebuilds and proves declared mount paths", () => {
  const app = express();
  const r = express.Router();
  app.use("/api/devices/:id", r);
  app.use("/api/opt/:a?", r);
  app.use("/api/m365-licenses.v2/", r);
  app.use(r);
  app.use(/^\/re/, r);
  const stack = /** @type {any} */ (app)._router.stack.filter((/** @type {any} */ l) => l.handle === r);
  assert.deepEqual(stack.map(mountTemplateOf), ["/api/devices/:id", "/api/opt/:a?", "/api/m365-licenses.v2", "", null]);
  assert.equal(mountTemplateOf(null), null);
  assert.equal(mountTemplateOf({ regexp: /^\/a\/?(?=\/|$)/i, keys: [] }), null, "no Layer class to prove it with");
});
