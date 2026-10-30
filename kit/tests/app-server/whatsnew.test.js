// whatsNewHandler / whatsNewNotes tests. All data is synthetic.
import "./consumer-preset.js";
import { test } from "node:test";
import assert from "node:assert/strict";
import { whatsNewHandler, whatsNewNotes } from "../../../shell-packages/app-server/index.js";

const notes = {
  tool: {
    changelog: "https://docs.example.com/changelog",
    releases: [
      { version: "2.0.0", labels: ["New features", "Bug fixes"], highlight: "Schedule reports from the Reports page." },
      { version: "1.9.0", labels: ["Removed the CVE-2026-0001 workaround"] },
      { version: "1.8.0", labels: ["Security improvements"], highlight: "caf\u00e9" },
      { version: "not-a-version", labels: ["Bug fixes"] },
    ],
  },
  other: { changelog: "javascript:alert(1)", releases: [] },
};

/** A tiny response double. */
function fakeRes() {
  /** @type {{ status: number, body: any, headers: Record<string, string> }} */
  const out = { status: 200, body: undefined, headers: {} };
  const res = {
    status(/** @type {number} */ n) { out.status = n; return res; },
    json(/** @type {any} */ b) { out.body = b; return res; },
    set(/** @type {string} */ k, /** @type {string} */ v) { out.headers[k] = v; return res; },
  };
  return { res, out };
}

test("whatsNewNotes keeps only known labels, safe text and x.y.z versions", () => {
  const r = whatsNewNotes(notes, "tool");
  assert.equal(r.changelog, "https://docs.example.com/changelog");
  assert.deepEqual(r.releases, [
    { version: "2.0.0", labels: ["New features", "Bug fixes"], highlight: "Schedule reports from the Reports page." },
    { version: "1.8.0", labels: ["Security improvements"] },
  ]);
  assert.deepEqual(whatsNewNotes(notes, "other"), { releases: [], changelog: null });
  assert.deepEqual(whatsNewNotes(notes, "missing"), { releases: [], changelog: null });
  assert.deepEqual(whatsNewNotes(notes, "__proto__"), { releases: [], changelog: null });
  assert.deepEqual(whatsNewNotes(null, "tool"), { releases: [], changelog: null });
});

test("whatsNewHandler answers only callers the tool lets in", async () => {
  const handler = whatsNewHandler({ notes, moduleId: "tool", allow: async (req) => req.ok === true });
  const yes = fakeRes();
  await handler({ ok: true }, yes.res);
  assert.equal(yes.out.status, 200);
  assert.equal(yes.out.body.releases.length, 2);
  assert.equal(yes.out.headers["Cache-Control"], "private, max-age=300");
  const no = fakeRes();
  await handler({ ok: false }, no.res);
  assert.equal(no.out.status, 403);
  assert.deepEqual(no.out.body, { error: "Forbidden" });
  // A truthy non-boolean is not a yes.
  const loose = whatsNewHandler({ notes, moduleId: "tool", allow: () => /** @type {any} */ ("yes") });
  const l = fakeRes();
  await loose({}, l.res);
  assert.equal(l.out.status, 403);
});

test("whatsNewHandler fails closed when the access check throws", async () => {
  const handler = whatsNewHandler({ notes, moduleId: "tool", allow: async () => { throw new Error("db down"); } });
  const { res, out } = fakeRes();
  const err = console.error;
  console.error = () => {};
  try { await handler({}, res); } finally { console.error = err; }
  assert.equal(out.status, 500);
  assert.equal(out.body.releases, undefined);
});

test("whatsNewHandler needs a module id and an allow function", () => {
  assert.throws(() => whatsNewHandler(/** @type {any} */ ({ notes, allow: () => true })), /moduleId/);
  assert.throws(() => whatsNewHandler(/** @type {any} */ ({ notes, moduleId: "tool" })), /allow/);
});
