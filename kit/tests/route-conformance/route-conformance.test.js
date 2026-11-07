// shell-packages/route-conformance: each check on fixture route sources written to a temp directory, so every
// failure branch is exercised (a check that never failed proves nothing).
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { routeTable, checkRoutes, checkGates, checkAuthOrder, checkNoLiteralKeys, checkNoErrorDetail, DEFAULT_GATE } from "../../../shell-packages/route-conformance/index.js";

/** @type {string} */ let root;
before(() => { root = fs.mkdtempSync(path.join(os.tmpdir(), "route-conf-")); });
after(() => { fs.rmSync(root, { recursive: true, force: true }); });

/** @param {Record<string, string>} files @returns {string} a fresh directory holding the files */
function dir(files) {
  const d = fs.mkdtempSync(path.join(root, "d-"));
  for (const [n, s] of Object.entries(files)) fs.writeFileSync(path.join(d, n), s);
  return d;
}

const GOOD = {
  "people.js": `const router = require("express").Router();
router.get("/", rbac.requirePermission("tab:people"), async (req, res) => { res.json([]); });
router.post("/", rbac.requirePermission("action:people:edit"), async (req, res) => { res.json({}); });
router.delete("/:id", rbac.requireAnyPermission(["action:people:delete"]), async (req, res) => { res.json({}); });
`,
  "health.js": `router.get("/", (req, res) => res.json({ ok: true }));\n`,
  "admin.js": `router.put("/x", rbac.requireWildcard(), async (_req, res) => { res.end(); });\n`,
};

test("routeTable reads every declaration with the gates between the path and the handler", () => {
  const { table, declared } = routeTable(dir(GOOD));
  assert.equal(declared, 5);
  assert.deepEqual(table.map((r) => r.key), ["admin.js PUT /x", "health.js GET /", "people.js GET /", "people.js POST /", "people.js DELETE /:id"]);
  assert.match(table.find((r) => r.key === "people.js GET /")?.args || "", /requirePermission\("tab:people"\)/);
  assert.doesNotMatch(table.find((r) => r.key === "health.js GET /")?.args || "", DEFAULT_GATE);
});

test("checkRoutes: a conforming set passes when the one open route has a stated reason", () => {
  const routesDir = dir(GOOD);
  assert.deepEqual(checkRoutes({ routesDir, allow: { "health.js GET /": "public liveness probe" } }), []);
});

test("checkRoutes: a route with no gate and no reason fails", () => {
  const routesDir = dir({ ...GOOD, "new.js": `router.get("/open", async (req, res) => { res.json({}); });\n` });
  assert.deepEqual(checkRoutes({ routesDir, allow: { "health.js GET /": "probe" } }), ["new.js GET /open: no server-side gate and no listed reason"]);
});

test("checkRoutes: a reason listed for a route that no longer exists, and an empty reason, fail", () => {
  const routesDir = dir(GOOD);
  const problems = checkRoutes({ routesDir, allow: { "health.js GET /": "probe", "gone.js GET /": "was a probe", "health.js GET /x": "  " } });
  assert.ok(problems.includes("gone.js GET /: listed in the allowlist but no such route"));
  assert.ok(problems.includes("health.js GET /x: listed in the allowlist but no such route"));
  assert.ok(problems.includes("health.js GET /x: the listed reason is empty"));
});

test("checkRoutes: a declaration the parser cannot read is reported, never skipped", () => {
  const routesDir = dir({ "odd.js": "const p = '/x';\nrouter.get(p, rbac.requirePermission('tab:a'), (req, res) => res.end());\nrouter.get(\"/ok\", rbac.requirePermission(\"tab:a\"), async (req, res) => {});\n" });
  const problems = checkRoutes({ routesDir });
  assert.equal(problems.length, 1);
  assert.match(problems[0] || "", /1 route declaration\(s\) the conformance parser could not read/);
});

test("checkRoutes: a minimum route count catches an empty or moved routes folder, and a router under another name is read", () => {
  assert.match(checkRoutes({ routesDir: dir({ "a.js": "// nothing\n" }), minRoutes: 3 }).join("\n"), /expected at least 3 route\(s\), saw 0/);
  const named = dir({ "a.js": `api.get("/a", rbac.requirePermission("tab:a"), async (req, res) => {});\n` });
  assert.deepEqual(checkRoutes({ routesDir: named, router: "api" }), []);
  assert.match(checkRoutes({ routesDir: named }).join("\n"), /expected at least 1/);
});

test("checkRoutes: a custom gate pattern replaces the default", () => {
  const routesDir = dir({ "a.js": `router.get("/a", mustBeAdmin, async (req, res) => {});\n` });
  assert.equal(checkRoutes({ routesDir }).length, 1);
  assert.deepEqual(checkRoutes({ routesDir, gate: /\bmustBeAdmin\b/ }), []);
});

test("checkGates: the file's routes are exactly the expected set on their own gates", () => {
  const { table } = routeTable(dir(GOOD));
  const expected = { "GET /": /requirePermission\("tab:people"\)/, "POST /": /requirePermission\("action:people:edit"\)/, "DELETE /:id": /requireAnyPermission/ };
  assert.deepEqual(checkGates(table, "people.js", expected), []);
  assert.deepEqual(checkGates(table, "people.js", { ...expected, "PUT /:id": /x/ }), ["people.js PUT /:id: expected route is missing"]);
  const { "DELETE /:id": _drop, ...fewer } = expected;
  assert.deepEqual(checkGates(table, "people.js", fewer), ["people.js DELETE /:id: route table changed, classify the new route"]);
  assert.match(checkGates(table, "people.js", { ...expected, "POST /": /requireWildcard/ }).join("\n"), /people\.js POST \/: must carry/);
  assert.deepEqual(checkGates(table, "people.js", { ...expected, "GET /": null }), [], "null lists a route as classified elsewhere");
});

const INDEX_OK = `app.get("/api/", a);
app.get("/api/health", h);
app.use("/api/health", healthRouter);
app.use("/api/version", versionRouter);
app.use("/api", requireAuth);
app.use("/api/people", peopleRouter);
app.use("/api/admin", adminRouter);
`;

test("checkAuthOrder: public routes first, the sign-in check, then every protected router", () => {
  assert.deepEqual(checkAuthOrder({ indexSource: INDEX_OK }), []);
});

test("checkAuthOrder: a router before the sign-in check, a missing mount, and a different public list", () => {
  const early = INDEX_OK.replace('app.use("/api", requireAuth);', 'app.use("/api/people", peopleRouter);\napp.use("/api", requireAuth);');
  assert.match(checkAuthOrder({ indexSource: early }).join("\n"), /\/api\/people is mounted before the sign-in check/);
  assert.deepEqual(checkAuthOrder({ indexSource: "app.use(x);" }), ['the sign-in mount app.use("/api", requireAuth); is missing']);
  assert.deepEqual(checkAuthOrder({ indexSource: early, publicPaths: ["/api/", "/api/health", "/api/version", "/api/people"] }), []);
  const custom = `app.use("/v2/ping", p);\napp.use("/v2", gate());\napp.use("/v2/things", t);\n`;
  assert.deepEqual(checkAuthOrder({ indexSource: custom, authMount: 'app.use("/v2", gate());', prefix: "/v2", publicPaths: ["/v2/ping"] }), []);
  assert.equal(checkAuthOrder({ indexSource: custom, authMount: 'app.use("/v2", gate());', prefix: "/v2", publicPaths: [] }).length, 1);
});

test("checkNoLiteralKeys finds a literal HMAC key and accepts one read from the environment", () => {
  const ok = dir({ "a.js": `crypto.createHmac("sha256", process.env.KEY).update(x);\ncrypto.createHmac("sha256", key).update(x);\n` });
  const bad = dir({ "b.js": `crypto.createHmac("sha256", "hunter2").update(x);\n`, "c.mjs": `createHmac( "sha256" , "k" )\n`, "d.txt": `createHmac("sha256", "x")` });
  assert.deepEqual(checkNoLiteralKeys([ok]), []);
  const problems = checkNoLiteralKeys([ok, bad]);
  assert.equal(problems.length, 2);
  assert.match(problems[0] || "", /b\.js: literal HMAC key/);
});

test("checkNoErrorDetail flags a 500 that returns details and accepts one that does not", () => {
  const ok = path.join(dir({ "rbac.js": `res.status(500).json({ error: "Internal error" });\nres.status(403).json({ error: "Forbidden", details: "Missing permission" });\n` }), "rbac.js");
  const bad = path.join(dir({ "rbac.js": `ok();\nres.status(500).json({ error: "x", details: e.message });\n` }), "rbac.js");
  assert.deepEqual(checkNoErrorDetail(ok), []);
  assert.deepEqual(checkNoErrorDetail(bad), [`${bad}:2: a 500 response returns error details to the caller`]);
});
