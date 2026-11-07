// shell-packages/announcements: validation, the active window cache and the audited admin routes, on an in-memory
// announcements table and a transaction that stages audit entries until commit.
import { test } from "node:test";
import assert from "node:assert/strict";
import express from "express";
import { TONES, TITLE_MAX, BODY_MAX, HREF_MAX, STATE_SQL, cleanText, cleanHref, validate, toApi, stateOf, createAnnouncements, announcementRoutes } from "../../../shell-packages/announcements/index.js";

const ID1 = "11111111-1111-4111-8111-111111111111";
const ID2 = "22222222-2222-4222-8222-222222222222";
const ID3 = "33333333-3333-4333-8333-333333333333";
const quiet = { error() {} };

function harness() {
  /** @type {any[]} */ let rows = [];
  /** @type {any[]} */ const audits = [];
  const state = { auditDown: false, nextStart: /** @type {Date | null} */ (null), activeQueries: 0, begin: 0, commit: 0, rollback: 0, failInsertWith: /** @type {string | null} */ (null) };
  const query = async (/** @type {string} */ sql, /** @type {any[]} */ params = []) => {
    // the database computes `state` with STATE_SQL on its own clock
    const withState = (/** @type {any} */ r) => ({ ...r, state: r.expired_at || (r.ends_at && new Date(r.ends_at).getTime() <= Date.now()) ? "expired" : new Date(r.starts_at).getTime() > Date.now() ? "scheduled" : "live" });
    if (/WHERE starts_at <= now\(\)/.test(sql)) {
      state.activeQueries += 1;
      const now = Date.now();
      return { rows: rows.filter((r) => new Date(r.starts_at).getTime() <= now && (!r.ends_at || new Date(r.ends_at).getTime() > now) && !r.expired_at) };
    }
    if (/min\(starts_at\) AS next_start/.test(sql)) return { rows: [{ next_start: state.nextStart }] };
    if (/^INSERT INTO announcements/.test(sql.trim())) {
      if (state.failInsertWith) throw Object.assign(new Error("check"), { code: "23514", constraint: state.failInsertWith });
      assert.match(sql, /ON CONFLICT \(id\) DO NOTHING/);
      const [id, tone, title, body, href, starts_at, ends_at, by] = params;
      if (rows.some((r) => r.id === id)) return { rows: [] };
      const row = { id, tone, title, body, href, starts_at, ends_at, created_by: by, updated_by: by, created_at: new Date(), updated_at: new Date(), expired_at: null };
      rows.push(row);
      return { rows: [withState(row)] };
    }
    if (/^SELECT[\s\S]*FROM announcements WHERE id = \$1/.test(sql.trim())) return { rows: rows.filter((r) => r.id === params[0]).map(withState) };
    if (/^UPDATE announcements/.test(sql.trim())) {
      const row = rows.find((r) => r.id === params[0]);
      if (!row) return { rows: [] };
      if (/expired_at = now\(\)/.test(sql)) row.expired_at = new Date();
      else for (const m of [...sql.matchAll(/(\w+) = \$(\d+)/g)].filter((x) => x[1] !== "id" && x[1] !== "updated_by")) row[/** @type {string} */ (m[1])] = params[Number(m[2]) - 1];
      return { rows: [withState(row)] };
    }
    if (/^DELETE FROM announcements/.test(sql.trim())) { rows = rows.filter((r) => r.id !== params[0]); return { rows: [] }; }
    if (/FROM announcements ORDER BY/.test(sql)) return { rows: rows.map(withState) };
    return { rows: [] };
  };
  /** @type {any[] | null} */ let snapshot = null;
  /** @type {any[]} */ let staged = [];
  const audit = {
    async transaction(/** @type {Function} */ work) {
      const client = { query: (/** @type {string} */ sql, /** @type {any[]} */ p) => query(sql, p) };
      state.begin += 1; snapshot = rows.map((r) => ({ ...r })); staged = [];
      try {
        const out = await work(client, async (/** @type {any} */ actor, /** @type {string} */ action, /** @type {string | null} */ target, /** @type {any} */ details, /** @type {any} */ opts) => {
          if (state.auditDown) throw new Error("audit_log unavailable");
          staged.push({ actor, action, target, details, opts });
        });
        if (out && out.rollback) { state.rollback += 1; rows = /** @type {any[]} */ (snapshot); } else { state.commit += 1; audits.push(...staged); }
        return out;
      } catch (e) {
        state.rollback += 1; rows = /** @type {any[]} */ (snapshot);
        throw e;
      }
    },
  };
  const caller = { email: "op@example.com" };
  const store = createAnnouncements({ db: { query } });
  const router = express.Router();
  /** @type {{ allowed: boolean }} */
  const gate = { allowed: true };
  announcementRoutes(router, { db: { query }, audit, store, manage: (/** @type {any} */ _req, /** @type {any} */ res, /** @type {any} */ next) => (gate.allowed ? next() : res.status(403).json({ error: "Forbidden" })), caller: () => caller, log: quiet });
  return { get rows() { return rows; }, set rows(v) { rows = v; }, audits, state, caller, store, router, gate };
}

/** @param {any} router @param {string} method @param {string} url @param {any} [body] */
function call(router, method, url, body) {
  return new Promise((resolve, reject) => {
    /** @type {any} */
    const req = { method, url, originalUrl: url, path: url, headers: {}, body: body === undefined ? {} : body, query: {}, params: {}, get: () => "" };
    /** @type {any} */
    const res = {
      statusCode: 200,
      status(/** @type {number} */ c) { this.statusCode = c; return this; },
      json(/** @type {any} */ b) { resolve({ status: this.statusCode, body: b }); return this; },
      setHeader() {}, set() { return this; },
      end() { resolve({ status: this.statusCode, body: null }); },
    };
    router.handle(req, res, (/** @type {any} */ err) => (err ? reject(err) : resolve({ status: 404, body: null })));
  });
}

test("cleanHref accepts site paths and https only", () => {
  assert.deepEqual(cleanHref("/estate"), { ok: true, value: "/estate" });
  assert.deepEqual(cleanHref("https://example.com/x"), { ok: true, value: "https://example.com/x" });
  assert.deepEqual(cleanHref(""), { ok: true, value: null });
  for (const bad of ["//evil.com", "/\\evil.com", "javascript:alert(1)", "http://plain.example", "data:text/html,x", "/a b", 42]) assert.equal(cleanHref(bad).ok, false, String(bad));
});

test("cleanHref limits apply to the stored form and reject bidi and zero-width characters", () => {
  assert.equal(cleanHref("/estate\u202e").ok, false);
  assert.equal(cleanHref("https://example.com/a\u200bb").ok, false);
  const long = `https://example.com/${"\u00e9".repeat(120)}`;
  assert.ok(long.length <= HREF_MAX);
  assert.equal(cleanHref(long).ok, false);
});

test("cleanText folds newlines and strips control, zero-width and bidi characters", () => {
  assert.equal(cleanText("Pay\u202eyalp now\u200b"), "Payyalp now");
  assert.equal(cleanText(" a\n\tb  c "), "a b c");
  assert.equal(cleanText(5), "");
});

test("validate folds control characters and checks the window", () => {
  const now = Date.parse("2026-10-14T12:00:00Z");
  const ok = validate({ id: ID1, title: " Maint\u0007enance\ntonight ", body: "Saturday", tone: "warning" }, { now });
  assert.equal(ok.ok, true);
  assert.equal(/** @type {any} */ (ok).value.title, "Maintenance tonight");
  assert.equal(/** @type {any} */ (ok).value.ends_at, null);
  for (const bad of [
    { id: ID1, title: "" }, { id: ID1, title: "x".repeat(TITLE_MAX + 1) }, { id: ID1, title: "x", body: "y".repeat(BODY_MAX + 1) },
    { id: ID1, title: "x", tone: "loud" }, { id: ID1, title: "x", extra: 1 },
    { id: ID1, title: "x", startsAt: "2026-10-15T00:00:00Z", endsAt: "2026-10-14T00:00:00Z" },
    { id: ID1, title: "x", startsAt: "2028-01-01T00:00:00Z" }, { id: ID1, title: "x", endsAt: "2028-01-01T00:00:00Z" },
    { id: ID1, title: "x", startsAt: "not a date" }, { id: "not-a-uuid", title: "x" }, { title: "x" },
  ]) assert.equal(validate(bad, { now }).ok, false, JSON.stringify(bad));
  assert.equal(validate(/** @type {any} */ ([]), { now }).ok, false);
  assert.equal(validate({ id: ID1, title: "x" }, { now, partial: true }).ok, false, "an edit cannot change the id");
  assert.deepEqual([...TONES], ["info", "success", "warning", "critical"]);
});

test("validate on an edit checks the new window against the stored one", () => {
  const now = Date.parse("2026-10-14T12:00:00Z");
  const current = { starts_at: "2026-10-14T13:00:00Z", ends_at: null };
  assert.equal(validate({ endsAt: "2026-10-14T12:30:00Z" }, { now, partial: true, current: /** @type {any} */ (current) }).ok, false);
  assert.equal(validate({ endsAt: "2026-10-14T14:00:00Z" }, { now, partial: true, current: /** @type {any} */ (current) }).ok, true);
});

test("stateOf is scheduled, live or expired, and prefers the database's own answer", () => {
  const now = Date.parse("2026-10-14T12:00:00Z");
  const row = (/** @type {any} */ o) => ({ starts_at: new Date(now - 1000), ends_at: null, expired_at: null, ...o });
  assert.equal(stateOf(row({}), now), "live");
  assert.equal(stateOf(row({ starts_at: new Date(now + 1000) }), now), "scheduled");
  assert.equal(stateOf(row({ ends_at: new Date(now - 1) }), now), "expired");
  assert.equal(stateOf(row({ expired_at: new Date(now) }), now), "expired");
  assert.equal(stateOf(row({ expired_at: new Date(now), state: "live" }), now), "live");
  assert.match(STATE_SQL, /AS state$/);
  assert.equal(toApi(/** @type {any} */ ({ ...row({}), id: "i", tone: "info", title: "t", body: "", href: null, created_by: "a", created_at: new Date(now), updated_by: "a", updated_at: new Date(now) })).endsAt, null);
});

test("every route is gated: without manage nothing is read or written", async () => {
  const h = harness();
  h.gate.allowed = false;
  for (const [m, u] of [["GET", "/"], ["POST", "/"], ["PUT", `/${ID1}`], ["POST", `/${ID1}/expire`], ["DELETE", `/${ID1}`]]) {
    const r = /** @type {any} */ (await call(h.router, /** @type {string} */ (m), /** @type {string} */ (u), { id: ID1, title: "x" }));
    assert.equal(r.status, 403, `${m} ${u}`);
  }
  assert.equal(h.rows.length, 0);
  assert.equal(h.audits.length, 0);
});

test("create, edit, expire and delete are audited, and the list follows", async () => {
  const h = harness();
  const c = /** @type {any} */ (await call(h.router, "POST", "/", { id: ID1, title: "Maintenance", tone: "warning", body: "Tonight" }));
  assert.equal(c.status, 201);
  assert.equal(c.body.state, "live");
  const u = /** @type {any} */ (await call(h.router, "PUT", `/${ID1}`, { body: "Tomorrow" }));
  assert.equal(u.status, 200);
  assert.equal(u.body.body, "Tomorrow");
  const empty = /** @type {any} */ (await call(h.router, "PUT", `/${ID1}`, {}));
  assert.equal(empty.status, 200, "an edit that changes nothing writes nothing");
  const e = /** @type {any} */ (await call(h.router, "POST", `/${ID1}/expire`));
  assert.equal(e.body.state, "expired");
  const again = /** @type {any} */ (await call(h.router, "POST", `/${ID1}/expire`));
  assert.equal(again.status, 200);
  const list = /** @type {any} */ (await call(h.router, "GET", "/"));
  assert.equal(list.body.announcements.length, 1);
  const d = /** @type {any} */ (await call(h.router, "DELETE", `/${ID1}`));
  assert.equal(d.status, 204);
  assert.deepEqual(h.audits.map((a) => a.action), ["announcements:create", "announcements:update", "announcements:expire", "announcements:delete"]);
  assert.deepEqual(h.audits[1].details, { fields: ["body"] });
  assert.equal(h.audits[0].actor.email, "op@example.com");
  assert.equal(h.rows.length, 0);
});

test("an audit failure rolls the write back and answers 503", async () => {
  const h = harness();
  h.state.auditDown = true;
  const r = /** @type {any} */ (await call(h.router, "POST", "/", { id: ID3, title: "Unaudited", tone: "info" }));
  assert.equal(r.status, 503);
  assert.equal(h.rows.length, 0);
  assert.equal(h.audits.length, 0, "no audit entry for a change that did not commit");
  assert.equal(h.state.rollback, 1);
  h.state.auditDown = false;
  await call(h.router, "POST", "/", { id: ID3, title: "Now audited", tone: "info" });
  h.state.auditDown = true;
  for (const [m, u, b] of [["PUT", `/${ID3}`, { title: "changed" }], ["POST", `/${ID3}/expire`, {}], ["DELETE", `/${ID3}`, {}]]) {
    const x = /** @type {any} */ (await call(h.router, /** @type {string} */ (m), /** @type {string} */ (u), b));
    assert.equal(x.status, 503, `${m} ${u}`);
  }
  assert.equal(h.rows.length, 1);
  assert.equal(h.rows[0].title, "Now audited");
  assert.equal(h.rows[0].expired_at, null);
});

test("expire keeps the schedule, and a row deleted meanwhile is a 404", async () => {
  const h = harness();
  const later = new Date(Date.now() + 3_600_000).toISOString();
  const c = /** @type {any} */ (await call(h.router, "POST", "/", { id: ID2, title: "Scheduled", tone: "info", startsAt: later }));
  assert.equal(c.body.state, "scheduled");
  const e = /** @type {any} */ (await call(h.router, "POST", `/${ID2}/expire`));
  assert.equal(e.body.state, "expired");
  assert.equal(e.body.startsAt, later);
  assert.ok(e.body.expiredAt);
  const u = /** @type {any} */ (await call(h.router, "PUT", `/${ID2}`, { title: "Scheduled, typo fixed" }));
  assert.equal(u.body.title, "Scheduled, typo fixed");
  h.rows = [];
  assert.equal(/** @type {any} */ (await call(h.router, "POST", `/${ID2}/expire`)).status, 404);
  assert.equal(/** @type {any} */ (await call(h.router, "PUT", `/${ID2}`, { title: "x" })).status, 404);
  assert.equal(/** @type {any} */ (await call(h.router, "DELETE", `/${ID2}`)).status, 404);
  assert.equal(/** @type {any} */ (await call(h.router, "PUT", "/not-a-uuid", { title: "x" })).status, 404);
});

test("a retried create returns the row it made, with one insert and one audit entry; another operator gets 409", async () => {
  const h = harness();
  const body = { id: ID1, title: "Once only", tone: "info" };
  const first = /** @type {any} */ (await call(h.router, "POST", "/", body));
  const retry = /** @type {any} */ (await call(h.router, "POST", "/", body));
  assert.equal(first.status, 201);
  assert.equal(retry.status, 200);
  assert.equal(retry.body.id, ID1);
  assert.equal(h.rows.length, 1);
  assert.equal(h.audits.filter((a) => a.action === "announcements:create").length, 1);
  h.caller.email = "other@example.com";
  assert.equal(/** @type {any} */ (await call(h.router, "POST", "/", body)).status, 409);
  assert.equal(h.rows.length, 1);
  h.caller.email = "op@example.com";
  const noId = /** @type {any} */ (await call(h.router, "POST", "/", { title: "No id", tone: "info" }));
  assert.equal(noId.status, 400);
  assert.equal(noId.body.details.field, "form");
});

test("a CHECK violation names the field it belongs to", async () => {
  const h = harness();
  for (const [constraint, field] of [["announcements_href_check", "href"], ["announcements_check", "endsAt"], ["announcements_title_check", "title"], ["announcements_body_check", "body"], ["announcements_tone_check", "tone"], ["something_else_check", "form"]]) {
    h.state.failInsertWith = /** @type {string} */ (constraint);
    const r = /** @type {any} */ (await call(h.router, "POST", "/", { id: ID1, title: "x", tone: "info" }));
    assert.equal(r.status, 400, String(constraint));
    assert.equal(r.body.details.field, field, String(constraint));
  }
});

test("listActive is cached briefly, a write clears it, and it never outlives a window boundary", async () => {
  const h = harness();
  const realNow = Date.now;
  let clock = realNow();
  Date.now = () => clock;
  try {
    h.rows = [{ id: ID1, tone: "info", title: "Ends soon", body: "", href: null, starts_at: new Date(clock - 60_000), ends_at: new Date(clock + 2_000), expired_at: null, created_at: new Date(clock), updated_at: new Date(clock) }];
    const before = h.state.activeQueries;
    assert.equal((await h.store.listActive()).length, 1);
    clock += 1_000;
    assert.equal((await h.store.listActive()).length, 1);
    assert.equal(h.state.activeQueries - before, 1, "a hit inside the window is cached");
    clock += 1_500;
    assert.equal((await h.store.listActive()).length, 0, "the cache expired at the row's end");
    // a scheduled start inside the TTL caps the cache at that start
    h.rows.push({ id: ID2, tone: "info", title: "Starts soon", body: "", href: null, starts_at: new Date(clock + 3_000), ends_at: null, expired_at: null, created_at: new Date(clock), updated_at: new Date(clock) });
    h.state.nextStart = new Date(clock + 3_000);
    h.store.invalidate();
    assert.equal((await h.store.listActive()).length, 0);
    clock += 3_500;
    h.state.nextStart = null;
    assert.deepEqual((await h.store.listActive()).map((r) => r.id), [ID2]);
    // a committed write drops the cache at once
    const q = h.state.activeQueries;
    await call(h.router, "POST", "/", { id: ID3, title: "New", tone: "info" });
    assert.ok((await h.store.listActive()).some((r) => r.id === ID3));
    assert.ok(h.state.activeQueries > q);
  } finally {
    Date.now = realNow;
  }
});

test("createAnnouncements and the routes need a db", () => {
  assert.throws(() => createAnnouncements(/** @type {any} */ ({})), /needs a db/);
});
