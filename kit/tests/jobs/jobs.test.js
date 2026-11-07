// shell-packages/jobs: the daily runner, its claim, the on/off switch and the GET/PUT contract.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createScheduler, jobRoutes, occurrence, nextRun, describeDaily, CATCH_UP_MS, nextCron, describeCron, parseCron, nextAutomation, describeAutomation, nextScheduled } from "../../../shell-packages/jobs/index.js";

/** An in-memory scheduled_jobs table that answers the scheduler's statements. */
function fakeDb() {
  /** @type {Map<string, any>} */
  const rows = new Map();
  return {
    rows,
    /** @param {string} sql @param {any[]} [p] */
    async query(sql, p = []) {
      const s = sql.replace(/\s+/g, " ").trim();
      if (s.startsWith("CREATE TABLE") || s.startsWith("ALTER TABLE")) return { rows: [] };
      if (s.startsWith("SELECT")) return { rows: [...rows.values()] };
      if (s.startsWith("INSERT INTO scheduled_jobs (id, enabled, updated_by")) {
        const r = rows.get(p[0]) || { id: p[0] };
        const skip = !rows.has(p[0]) ? p[3] : (r.enabled ? r.skip_until : (p[4] ?? r.skip_until));
        rows.set(p[0], { ...r, enabled: p[1], updated_by: p[2], updated_at: new Date(), skip_until: skip ?? null });
        return { rows: [] };
      }
      if (s.startsWith("INSERT INTO scheduled_jobs (id, enabled)")) {
        if (!rows.has(p[0])) rows.set(p[0], { id: p[0], enabled: p[1], last_run_at: null });
        return { rows: [] };
      }
      if (s.startsWith("UPDATE scheduled_jobs SET last_run_at")) {
        const r = rows.get(p[0]);
        if (!r || !r.enabled || (r.last_run_at && !(new Date(r.last_run_at) < new Date(p[1])))) return { rows: [] };
        if (r.skip_until && !(new Date(r.skip_until) < new Date(p[1]))) return { rows: [] };
        Object.assign(r, { last_run_at: p[2], last_status: "running", last_result: null, finished_at: null });
        return { rows: [{ id: p[0] }] };
      }
      if (s.startsWith("UPDATE scheduled_jobs SET last_status")) {
        Object.assign(rows.get(p[0]), { last_status: p[1], last_result: JSON.parse(p[2]), finished_at: new Date() });
        return { rows: [] };
      }
      throw new Error(`unexpected SQL ${s}`);
    },
  };
}

const job = (/** @type {Partial<import("../../../shell-packages/jobs/index.js").JobDef>} */ over = {}) => ({
  id: "orphan-devices", name: "Orphan devices", description: "d", at: "03:30", source: "apps/avd/server/lib/device-care.js",
  run: async () => ({ deleted: 1 }), ...over,
});

test("occurrence lands on Eastern wall time across daylight saving", () => {
  // EDT (UTC-4) and EST (UTC-5)
  assert.equal(occurrence("03:30", new Date("2026-10-30T12:00:00Z")).toISOString(), "2026-10-30T07:30:00.000Z");
  assert.equal(occurrence("03:30", new Date("2026-11-02T12:00:00Z")).toISOString(), "2026-11-02T08:30:00.000Z");
  // the fall-back day itself: 03:30 is after the change, so EST
  assert.equal(occurrence("03:30", new Date("2026-11-01T12:00:00Z")).toISOString(), "2026-11-01T08:30:00.000Z");
  assert.equal(nextRun("03:30", new Date("2026-10-30T08:00:00Z")).toISOString(), "2026-10-31T07:30:00.000Z");
  assert.equal(describeDaily("03:30"), "Every day at 3:30 AM Eastern");
  assert.equal(describeDaily("00:05"), "Every day at 12:05 AM Eastern");
  assert.equal(describeDaily("13:00"), "Every day at 1:00 PM Eastern");
});

test("a due job runs once, and a second instance or a restart does not run it again", async () => {
  const db = fakeDb();
  let runs = 0;
  const a = createScheduler({ db, tool: "avd" });
  const b = createScheduler({ db, tool: "avd" });
  a.register(job({ run: async () => { runs += 1; return { deleted: 2 }; } }));
  b.register(job({ run: async () => { runs += 1; return {}; } }));
  const at = new Date("2026-10-30T07:35:00Z");
  assert.deepEqual(await a.tick(at), ["orphan-devices"]);
  assert.deepEqual(await b.tick(new Date("2026-10-30T07:40:00Z")), []);
  assert.deepEqual(await a.tick(new Date("2026-10-30T08:00:00Z")), []);
  assert.equal(runs, 1);
  const v = /** @type {any} */ ((await a.list())[0]);
  assert.equal(v.lastStatus, "success");
  assert.deepEqual(v.lastResult, { deleted: 2 });
  // the next day runs again
  assert.deepEqual(await a.tick(new Date("2026-10-31T07:31:00Z")), ["orphan-devices"]);
});

test("before its time, or after the catch-up window, nothing runs", async () => {
  const s = createScheduler({ db: fakeDb(), tool: "avd" });
  s.register(job());
  assert.deepEqual(await s.tick(new Date("2026-10-30T07:29:00Z")), []);
  assert.deepEqual(await s.tick(new Date(Date.parse("2026-10-30T07:30:00Z") + CATCH_UP_MS + 60000)), []);
});

test("a job that ships off does not run until it is turned on, and a paused job stops", async () => {
  const db = fakeDb();
  const s = createScheduler({ db, tool: "avd" });
  s.register(job({ defaultEnabled: false }));
  const off = /** @type {any} */ ((await s.list())[0]);
  assert.equal(off.enabled, false);
  assert.equal(off.nextRunAt, null);
  assert.deepEqual(await s.tick(new Date("2026-10-30T07:35:00Z")), []);
  assert.equal(await s.setEnabled("orphan-devices", true, "admin@x", new Date("2026-10-30T07:00:00Z")), true);
  assert.deepEqual(await s.tick(new Date("2026-10-30T07:36:00Z")), ["orphan-devices"]);
  await s.setEnabled("orphan-devices", false, "admin@x");
  assert.deepEqual(await s.tick(new Date("2026-10-31T07:36:00Z")), []);
  assert.equal(await s.setEnabled("nope", true, "admin@x"), false);
});

test("a throwing or failing job is stored as a failure, never thrown", async () => {
  const s = createScheduler({ db: fakeDb(), tool: "avd", log: () => {} });
  s.register(job({ id: "a", run: async () => { throw new Error("boom"); } }));
  s.register(job({ id: "b", run: async () => ({ failed: 2 }) }));
  await s.tick(new Date("2026-10-30T07:35:00Z"));
  const v = /** @type {any[]} */ (await s.list());
  assert.deepEqual(v.map((x) => [x.id, x.lastStatus]), [["a", "failure"], ["b", "failure"]]);
  assert.deepEqual(v[0].lastResult, { error: "boom" });
});

test("register refuses a bad id, time, duplicate or missing field", () => {
  const s = createScheduler({ db: fakeDb(), tool: "avd" });
  assert.throws(() => s.register(job({ id: "Bad Id" })), /kebab-case/);
  assert.throws(() => s.register(job({ at: "3:30" })), /HH:MM/);
  assert.throws(() => s.register(job({ source: "" })), /required/);
  s.register(job());
  assert.throws(() => s.register(job()), /twice/);
  assert.throws(() => createScheduler({ db: fakeDb(), tool: "" }), /tool id/);
});

test("jobRoutes: GET lists with canManage, PUT switches and audits, bad input is refused", async () => {
  const s = createScheduler({ db: fakeDb(), tool: "avd" });
  s.register(job({ defaultEnabled: false }));
  /** @type {Record<string, any>} */ const routes = {};
  const router = { get: (/** @type {string} */ p, /** @type {any} */ _g, /** @type {Function} */ h) => { routes[`GET ${p}`] = h; }, put: (/** @type {string} */ p, /** @type {any} */ _g, /** @type {Function} */ h) => { routes[`PUT ${p}`] = h; } };
  /** @type {any[]} */ const audits = [];
  jobRoutes(router, { scheduler: s, read: () => {}, manage: () => {}, canManage: () => true, caller: () => ({ email: "admin@x" }),
    audit: async (/** @type {any} */ _r, /** @type {string} */ a, /** @type {string} */ t, /** @type {any} */ d) => { audits.push([a, t, d]); } });
  const res = () => { const r = /** @type {any} */ ({ code: 200, body: null }); r.status = (/** @type {number} */ c) => { r.code = c; return r; }; r.json = (/** @type {any} */ b) => { r.body = b; return r; }; return r; };
  const next = (/** @type {unknown} */ e) => { throw e; };
  let r = res(); await routes["GET /jobs"]({}, r, next);
  assert.equal(r.body.tool, "avd"); assert.equal(r.body.canManage, true); assert.equal(r.body.jobs[0].enabled, false);
  r = res(); await routes["PUT /jobs/:id"]({ params: { id: "orphan-devices" }, body: { enabled: "yes" } }, r, next);
  assert.equal(r.code, 400);
  r = res(); await routes["PUT /jobs/:id"]({ params: { id: "nope" }, body: { enabled: true } }, r, next);
  assert.equal(r.code, 404);
  r = res(); await routes["PUT /jobs/:id"]({ params: { id: "orphan-devices" }, body: { enabled: true } }, r, next);
  assert.equal(r.body.job.enabled, true);
  assert.deepEqual(audits, [["jobs:on", "job:orphan-devices", { before: { enabled: false }, after: { enabled: true } }]]);
});

const N = new Date("2026-10-30T05:00:00Z");
const iso = (/** @type {Date | null} */ d) => (d ? d.toISOString() : null);

test("nextCron: daily, weekly, every N minutes and the 6-field Function timer form", () => {
  assert.equal(iso(nextCron("17 9 * * *", N)), "2026-10-30T09:17:00.000Z");
  assert.equal(iso(nextCron("0 11 * * 6", N)), "2026-10-31T11:00:00.000Z");
  assert.equal(iso(nextCron("*/15 * * * *", N)), "2026-10-30T05:15:00.000Z");
  assert.equal(iso(nextCron("0 */5 * * * *", N)), "2026-10-30T05:05:00.000Z");
  assert.equal(iso(nextCron("0 0 1 * *", N)), "2026-11-01T00:00:00.000Z");
  assert.throws(() => parseCron("30 0 */5 * * *"), /seconds/);
  assert.throws(() => parseCron("61 * * * *"), /range/);
  assert.throws(() => parseCron("@daily"), /5 fields/);
});

test("describeCron reads the common shapes and falls back to the expression", () => {
  assert.equal(describeCron("0 30 6 * * *"), "Every day at 06:30 UTC");
  assert.equal(describeCron("0 11 * * 6"), "Every Saturday at 11:00 UTC");
  assert.equal(describeCron("*/15 * * * *"), "Every 15 minutes");
  assert.equal(describeCron("5 * * * *"), "Every hour at :05");
  assert.equal(describeCron("0 9 1 * *"), "Cron 0 9 1 * * (UTC)");
});

test("nextAutomation: hourly, daily, weekly and monthly in Eastern time", () => {
  const z = "America/New_York";
  const four = { frequency: /** @type {const} */ ("Hour"), interval: 4, timezone: z, startTime: "2026-10-08T22:00:00-04:00" };
  assert.equal(iso(nextAutomation(four, N)), "2026-10-30T06:00:00.000Z");
  assert.equal(describeAutomation(four), "Every 4 hours from 10:00 PM Eastern");
  const day = { frequency: /** @type {const} */ ("Day"), interval: 1, timezone: z, startTime: "2026-10-10T03:30:00-04:00" };
  assert.equal(iso(nextAutomation(day, N)), "2026-10-30T07:30:00.000Z");
  // after the fall-back the same wall time is an hour later in UTC
  assert.equal(iso(nextAutomation(day, new Date("2026-11-02T00:00:00Z"))), "2026-11-02T08:30:00.000Z");
  const week = { frequency: /** @type {const} */ ("Week"), interval: 1, timezone: z, startTime: "2026-10-17T22:00:00-04:00", weekDays: ["Saturday"] };
  assert.equal(iso(nextAutomation(week, N)), "2026-11-01T02:00:00.000Z");
  const month = { frequency: /** @type {const} */ ("Month"), interval: 1, timezone: z, startTime: "2026-11-06T09:30:00-05:00", monthDays: [6] };
  assert.equal(iso(nextAutomation(month, N)), "2026-11-06T14:30:00.000Z");
  assert.equal(describeAutomation(month), "Monthly on day 6 at 9:30 AM Eastern");
  assert.throws(() => nextAutomation({ ...day, timezone: "UTC" }, N), /not supported/);
});

test("nextScheduled picks the soonest cron of a row", () => {
  assert.equal(iso(nextScheduled({ engine: "github", cron: ["0 11 * * 6", "17 9 * * *"] }, N)), "2026-10-30T09:17:00.000Z");
  assert.equal(nextScheduled({ engine: "github", cron: [] }, N), null);
});

test("jobRoutes: a switch whose audit write fails is put back and the request fails", async () => {
  const db = fakeDb();
  const scheduler = createScheduler({ db, tool: "t", log: () => {} });
  scheduler.register({ id: "a", name: "A", description: "d", at: "03:30", source: "x.js", defaultEnabled: false, run: async () => ({}) });
  /** @type {Record<string, Function>} */ const handlers = {};
  const router = { get: (/** @type {string} */ p, /** @type {any[]} */ ...h) => { handlers[`GET ${p}`] = h[h.length - 1]; }, put: (/** @type {string} */ p, /** @type {any[]} */ ...h) => { handlers[`PUT ${p}`] = h[h.length - 1]; } };
  jobRoutes(/** @type {any} */ (router), { scheduler, read: () => {}, manage: () => {}, canManage: () => true, caller: () => ({ email: "a@b" }), audit: async () => { throw new Error("audit down"); } });
  /** @type {unknown} */ let failed = null;
  const res = { status: () => res, json: () => res };
  await /** @type {Function} */ (handlers["PUT /jobs/:id"])({ params: { id: "a" }, body: { enabled: true } }, res, (/** @type {unknown} */ e) => { failed = e; });
  assert.match(String(failed), /audit down/);
  const [job] = await scheduler.list();
  assert.equal(job?.enabled, false);
});

test("turning a job on after today's time waits for tomorrow, even inside the catch-up window", async () => {
  const db = fakeDb();
  let runs = 0;
  const s = createScheduler({ db, tool: "avd", log: () => {} });
  s.register(job({ defaultEnabled: false, run: async () => { runs += 1; return {}; } }));
  const four = new Date("2026-10-30T08:00:00Z"); // 04:00 Eastern, 30 minutes after 03:30
  await s.setEnabled("orphan-devices", true, "a@b", four);
  // No faked last run: the tab shows Never until the job really runs.
  assert.equal((await s.list())[0]?.lastRunAt, null);
  assert.deepEqual(await s.tick(new Date("2026-10-30T08:05:00Z")), []);
  assert.equal(runs, 0);
  assert.deepEqual(await s.tick(new Date("2026-10-31T07:35:00Z")), ["orphan-devices"]);
  assert.equal(runs, 1);
  // Turned on before today's time, it runs today.
  const db2 = fakeDb();
  const s2 = createScheduler({ db: db2, tool: "avd", log: () => {} });
  s2.register(job({ defaultEnabled: false }));
  await s2.setEnabled("orphan-devices", true, "a@b", new Date("2026-10-30T07:00:00Z"));
  assert.deepEqual(await s2.tick(new Date("2026-10-30T07:35:00Z")), ["orphan-devices"]);
});

test("a run whose summary cannot be stored is a failure, and the next job still runs", async () => {
  const db = fakeDb();
  const s = createScheduler({ db, tool: "t", log: () => {} });
  /** @type {any} */ const loop = {}; loop.self = loop;
  s.register(job({ id: "a", run: async () => loop }));
  s.register(job({ id: "b" }));
  assert.deepEqual(await s.tick(new Date("2026-10-30T07:35:00Z")), ["a", "b"]);
  const [a, b] = /** @type {any[]} */ (await s.list());
  assert.equal(a.lastStatus, "failure");
  assert.match(String(a.lastResult.error), /could not be stored/);
  assert.equal(b.lastStatus, "success");
});

test("nextAutomation honors Week and Month intervals, and descriptions use plain spaces", () => {
  // Every 2 weeks on Saturday from Sat Oct 3 2026, 10 PM Eastern: Oct 17, Oct 31, Nov 14.
  const wk = { frequency: /** @type {const} */ ("Week"), interval: 2, timezone: "America/New_York", startTime: "2026-10-03T22:00:00-04:00", weekDays: ["Saturday"] };
  assert.equal(nextAutomation(wk, new Date("2026-10-20T12:00:00Z"))?.toISOString(), "2026-11-01T02:00:00.000Z");
  assert.equal(nextAutomation(wk, new Date("2026-11-02T12:00:00Z"))?.toISOString(), "2026-11-15T03:00:00.000Z");
  // Every 2 months on day 6 from Jun 6 2026, 9:30 AM Eastern: Aug, Oct, Dec.
  const mo = { frequency: /** @type {const} */ ("Month"), interval: 2, timezone: "America/New_York", startTime: "2026-06-06T09:30:00-04:00", monthDays: [6] };
  assert.equal(nextAutomation(mo, new Date("2026-10-07T12:00:00Z"))?.toISOString(), "2026-12-06T14:30:00.000Z");
  assert.equal(describeAutomation(wk), "Every 2 weeks on Saturday at 10:00 PM Eastern");
  assert.equal(describeAutomation(mo), "Every 2 months on day 6 at 9:30 AM Eastern");
  for (const d of [describeAutomation(wk), describeAutomation(mo)]) assert.ok(/^[\x20-\x7e]+$/.test(d), d);
});

test("switching on a job that is already on, after its time, keeps today's pending run", async () => {
  const db = fakeDb();
  const s = createScheduler({ db, tool: "avd", log: () => {} });
  s.register(job({ defaultEnabled: false }));
  await s.setEnabled("orphan-devices", true, "a@b", new Date("2026-10-30T07:00:00Z"));
  // 3:40 AM Eastern, before any tick: someone switches it on again.
  await s.setEnabled("orphan-devices", true, "a@b", new Date("2026-10-30T07:40:00Z"));
  assert.deepEqual(await s.tick(new Date("2026-10-30T07:45:00Z")), ["orphan-devices"]);
  // A job that ships on is never skipped by its first switch.
  const s2 = createScheduler({ db: fakeDb(), tool: "avd", log: () => {} });
  s2.register(job({ id: "on-by-default" }));
  await s2.setEnabled("on-by-default", true, "a@b", new Date("2026-10-30T07:40:00Z"));
  assert.deepEqual(await s2.tick(new Date("2026-10-30T07:45:00Z")), ["on-by-default"]);
  // Off, then on again after its time: today is skipped.
  const s3 = createScheduler({ db: fakeDb(), tool: "avd", log: () => {} });
  s3.register(job({ id: "c", defaultEnabled: false }));
  await s3.setEnabled("c", true, "a@b", new Date("2026-10-29T07:00:00Z"));
  await s3.setEnabled("c", false, "a@b", new Date("2026-10-30T07:00:00Z"));
  await s3.setEnabled("c", true, "a@b", new Date("2026-10-30T07:40:00Z"));
  assert.deepEqual(await s3.tick(new Date("2026-10-30T07:45:00Z")), []);
});

test("start: the offEnv variable set to off stops the runner, the default variable is JOBS", () => {
  const db = fakeDb();
  const prior = { JOBS: process.env.JOBS, CUSTOM_JOBS: process.env.CUSTOM_JOBS };
  try {
    process.env.JOBS = "off";
    const a = createScheduler({ db, tool: "demo" });
    a.start();
    // an off runner holds no timer, so stop() has nothing to clear and a second start stays off
    a.stop();
    delete process.env.JOBS;
    process.env.CUSTOM_JOBS = "OFF";
    const b = createScheduler({ db, tool: "demo", offEnv: "CUSTOM_JOBS" });
    b.start();
    b.stop();
    let ticks = 0;
    const real = globalThis.setInterval;
    globalThis.setInterval = /** @type {any} */ ((/** @type {any} */ ...args) => { ticks += 1; return real(...args); });
    try {
      createScheduler({ db, tool: "demo", offEnv: "CUSTOM_JOBS" }).start();
      assert.equal(ticks, 0);
      delete process.env.CUSTOM_JOBS;
      const c = createScheduler({ db, tool: "demo", offEnv: "CUSTOM_JOBS" });
      c.start();
      c.stop();
      assert.equal(ticks, 1);
    } finally { globalThis.setInterval = real; }
  } finally {
    for (const [k, v] of Object.entries(prior)) { if (v === undefined) delete process.env[k]; else process.env[k] = v; }
  }
});
