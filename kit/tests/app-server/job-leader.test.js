// createJobLeader tests. All data is synthetic.
import { test } from "node:test";
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { createJobLeader, jobLockKey } from "../../../shell-packages/app-server/index.js";

/** One fake Postgres holding session advisory locks, shared by every "process". */
function fakeDb() {
  /** @type {Map<string, object>} */
  const locks = new Map();
  let failPing = false;
  const db = {
    locks,
    setFailPing(/** @type {boolean} */ v) { failPing = v; },
    async connect() {
      const c = new EventEmitter();
      const session = {};
      Object.assign(c, {
        released: /** @type {undefined | boolean} */ (undefined),
        async query(/** @type {string} */ sql, /** @type {any[]} */ params = []) {
          if (/pg_try_advisory_lock/.test(sql)) {
            const k = params[0];
            if (!locks.has(k) || locks.get(k) === session) { locks.set(k, session); return { rows: [{ got: true }] }; }
            return { rows: [{ got: false }] };
          }
          if (/pg_advisory_unlock/.test(sql)) { if (locks.get(params[0]) === session) locks.delete(params[0]); return { rows: [{}] }; }
          if (/SELECT 1/.test(sql)) { if (failPing) throw new Error("connection terminated"); return { rows: [{}] }; }
          throw new Error(`unexpected ${sql}`);
        },
        release(/** @type {boolean | undefined} */ destroy) {
          // Destroying the connection ends the session, so Postgres frees its locks.
          if (destroy) for (const [k, v] of locks) if (v === session) locks.delete(k);
          /** @type {any} */ (c).released = !!destroy;
        },
      });
      return c;
    },
  };
  return db;
}

const quiet = { log() {}, warn() {}, error() {} };
const tick = (ms = 5) => new Promise((r) => setTimeout(r, ms));

/** @param {ReturnType<typeof fakeDb>} db @param {{ running: number, starts: number }} counters */
function makeProcess(db, counters) {
  return createJobLeader({
    name: "unit-jobs",
    getClient: () => db.connect(),
    start: () => { counters.running += 1; counters.starts += 1; },
    stop: () => { counters.running -= 1; },
    retryMs: 5,
    checkMs: 5,
    log: quiet,
  });
}

test("jobLockKey is a stable signed 64-bit decimal", () => {
  const k = jobLockKey("job-a");
  assert.equal(k, jobLockKey("job-a"));
  assert.notEqual(k, jobLockKey("job-b"));
  assert.match(k, /^-?\d+$/);
  const n = BigInt(k);
  assert.ok(n >= -(2n ** 63n) && n < 2n ** 63n);
});

test("only one of two processes runs the jobs, the other takes over when it exits", async () => {
  const db = fakeDb();
  const counters = { running: 0, starts: 0 };
  const a = makeProcess(db, counters);
  const b = makeProcess(db, counters);
  a.begin();
  await tick(20);
  b.begin();
  await tick(40);
  assert.equal(counters.running, 1);
  assert.equal(a.isLeader(), true);
  assert.equal(b.isLeader(), false);
  await a.end();
  await tick(40);
  assert.equal(counters.running, 1);
  assert.equal(b.isLeader(), true);
  assert.equal(counters.starts, 2);
  await b.end();
  assert.equal(counters.running, 0);
  assert.equal(db.locks.size, 0);
});

test("a failed ping stops the jobs and drops the connection, which frees the lock", async () => {
  const db = fakeDb();
  const counters = { running: 0, starts: 0 };
  const a = makeProcess(db, counters);
  a.begin();
  await tick(20);
  assert.equal(a.isLeader(), true);
  db.setFailPing(true);
  await tick(15);
  assert.equal(counters.running <= 1, true);
  db.setFailPing(false);
  await tick(40);
  // It lost the lock, stopped, and took it back once the connection was healthy.
  assert.ok(counters.starts >= 2);
  assert.equal(counters.running, 1);
  await a.end();
  assert.equal(counters.running, 0);
});

test("a client error event stops the jobs at once", async () => {
  const db = fakeDb();
  /** @type {any} */
  let held = null;
  const counters = { running: 0, starts: 0 };
  const a = createJobLeader({
    name: "unit-jobs",
    getClient: async () => { held = await db.connect(); return held; },
    start: () => { counters.running += 1; },
    stop: () => { counters.running -= 1; },
    retryMs: 1000,
    checkMs: 1000,
    log: quiet,
  });
  a.begin();
  await tick(20);
  assert.equal(counters.running, 1);
  held.emit("error", new Error("socket closed"));
  assert.equal(counters.running, 0);
  assert.equal(a.isLeader(), false);
  assert.equal(db.locks.size, 0);
  await a.end();
});

test("a start that fails gives the lock up for another process", async () => {
  const db = fakeDb();
  const counters = { running: 0, starts: 0 };
  const broken = createJobLeader({
    name: "unit-jobs",
    getClient: () => db.connect(),
    start: async () => { throw new Error("settings reload failed"); },
    stop: () => {},
    retryMs: 1000,
    checkMs: 1000,
    log: quiet,
  });
  broken.begin();
  await tick(20);
  assert.equal(broken.isLeader(), false);
  assert.equal(db.locks.size, 0);
  const good = makeProcess(db, counters);
  good.begin();
  await tick(20);
  assert.equal(good.isLeader(), true);
  assert.equal(counters.running, 1);
  await good.end();
  await broken.end();
});

test("a lost lock while start() is still running stops the jobs once it returns", async () => {
  const db = fakeDb();
  /** @type {any} */
  let held = null;
  /** @type {() => void} */
  let finish = () => {};
  const counters = { running: 0, starts: 0 };
  const a = createJobLeader({
    name: "unit-jobs",
    getClient: async () => { held = await db.connect(); return held; },
    start: () => new Promise((resolve) => { finish = () => { counters.running += 1; resolve(undefined); }; }),
    // stop() with nothing running is a no-op, the way the real apps behave.
    stop: () => { if (counters.running > 0) counters.running -= 1; },
    retryMs: 1000,
    checkMs: 1000,
    log: quiet,
  });
  a.begin();
  await tick(20);
  held.emit("error", new Error("socket closed"));
  assert.equal(counters.running, 0, "stop() must not run before start() has set anything up");
  finish();
  await tick(10);
  assert.equal(counters.running, 0, "jobs started after the loss must be stopped");
  assert.equal(a.isLeader(), false);
  assert.equal(db.locks.size, 0);
  await a.end();
});

test("end() while start() is still running stops the jobs once it returns", async () => {
  const db = fakeDb();
  /** @type {() => void} */
  let finish = () => {};
  const counters = { running: 0, starts: 0 };
  const a = createJobLeader({
    name: "unit-jobs",
    getClient: () => db.connect(),
    start: () => new Promise((resolve) => { finish = () => { counters.running += 1; resolve(undefined); }; }),
    // stop() with nothing running is a no-op, the way the real apps behave.
    stop: () => { if (counters.running > 0) counters.running -= 1; },
    retryMs: 1000,
    checkMs: 1000,
    log: quiet,
  });
  a.begin();
  await tick(20);
  await a.end();
  assert.equal(db.locks.size, 0);
  finish();
  await tick(10);
  assert.equal(counters.running, 0);
});

test("a ping that never answers counts as a lost connection", async () => {
  const db = fakeDb();
  /** @type {any} */
  let held = null;
  let hang = false;
  const counters = { running: 0, starts: 0 };
  const a = createJobLeader({
    name: "unit-jobs",
    getClient: async () => {
      held = await db.connect();
      const query = held.query.bind(held);
      held.query = (/** @type {string} */ sql, /** @type {any[]} */ p) => (hang && /SELECT 1/.test(sql) ? new Promise(() => {}) : query(sql, p));
      return held;
    },
    start: () => { counters.running += 1; counters.starts += 1; },
    stop: () => { counters.running -= 1; },
    retryMs: 5,
    checkMs: 5,
    pingTimeoutMs: 20,
    log: quiet,
  });
  a.begin();
  await tick(20);
  assert.equal(a.isLeader(), true);
  hang = true;
  await tick(60);
  hang = false;
  await tick(60);
  assert.ok(counters.starts >= 2, "it lost the lock on the hung ping and took it back");
  assert.equal(counters.running, 1);
  await a.end();
  assert.equal(counters.running, 0);
});

test("bad options throw", () => {
  assert.throws(() => createJobLeader(/** @type {any} */ ({ name: "x" })), TypeError);
});

test("jobLockKey: the prefix namespaces the key, the default is stable, and createJobLeader uses lockPrefix", async () => {
  assert.equal(jobLockKey("x"), jobLockKey("x", "jobs"));
  assert.notEqual(jobLockKey("x", "app-a"), jobLockKey("x", "app-b"));
  const db = fakeDb();
  let asked = null;
  const pool = { async connect() { const c = await db.connect(); const q = c.query.bind(c); c.query = (/** @type {string} */ sql, /** @type {any[]} */ p) => { if (/pg_try_advisory_lock/.test(sql)) asked = p[0]; return q(sql, p); }; return c; } };
  const leader = createJobLeader({ name: "n", lockPrefix: "app-a", getClient: () => pool.connect(), start() {}, stop() {}, log: { log() {}, warn() {}, error() {} } });
  leader.begin();
  for (let i = 0; i < 20 && !leader.isLeader(); i += 1) await new Promise((r) => setTimeout(r, 5));
  assert.equal(leader.isLeader(), true);
  assert.equal(asked, jobLockKey("n", "app-a"));
  await leader.end();
});
