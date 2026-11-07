// shell-packages/audit: the hash chain, its verification and the write paths, on an in-memory audit_log.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createAudit, stableStringify, csvCell, clientPublicIp, canonicalizeEntry, ZERO_HASH } from "../../../shell-packages/audit/index.js";

const quiet = { error() {} };

/** An in-memory audit_log that answers the statements the package issues. Rows keep the order they were inserted. */
function fakeDb() {
  /** @type {any[]} */
  let rows = [];
  let failInsert = false;
  const exec = async (/** @type {string} */ sql, /** @type {any[]} */ p = [], /** @type {any[]} */ table = rows) => {
    const s = sql.replace(/\s+/g, " ").trim();
    if (s.startsWith("SELECT hash FROM audit_log")) {
      const last = [...table].reverse().find((r) => r.hash);
      return { rows: last ? [{ hash: last.hash }] : [] };
    }
    if (s.startsWith("INSERT INTO audit_log")) {
      if (failInsert) throw new Error("insert refused");
      table.push({
        id: p[0], ts: new Date(p[1]), schema_version: p[2], actor_email: p[3], actor_name: p[4], actor_json: JSON.parse(p[5]),
        action: p[6], target: p[7], outcome: p[8], context_ip: p[9], context_user_agent: p[10], context_request_id: p[11],
        context_method: p[12], context_path: p[13], details_json: JSON.parse(p[14]), prev_hash: p[15], hash: p[16],
      });
      return { rows: [] };
    }
    if (s.startsWith("SELECT id, ts, schema_version") && s.includes("ORDER BY created_at ASC")) return { rows: table.map((r) => ({ ...r })) };
    if (s.startsWith("SELECT COUNT(*)")) return { rows: [{ c: table.length }] };
    if (s.startsWith("SELECT * FROM audit_log") && s.includes("LIMIT")) return { rows: [...table].reverse().slice(p[p.length - 1], p[p.length - 1] + p[p.length - 2]) };
    if (s.startsWith("SELECT * FROM audit_log")) return { rows: [...table].reverse() };
    throw new Error(`unexpected ${s}`);
  };
  const db = {
    get rows() { return rows; },
    set rows(v) { rows = v; },
    setFailInsert(/** @type {boolean} */ v) { failInsert = v; },
    query: (/** @type {string} */ sql, /** @type {any[]} */ p) => exec(sql, p),
    transactions: /** @type {string[]} */ ([]),
    async getClient() {
      /** @type {any[]} */
      let staged = [];
      return {
        async query(/** @type {string} */ sql, /** @type {any[]} */ p) {
          if (sql === "BEGIN") { staged = []; db.transactions.push("BEGIN"); return { rows: [] }; }
          if (sql === "COMMIT") { rows.push(...staged); db.transactions.push("COMMIT"); return { rows: [] }; }
          if (sql === "ROLLBACK") { staged = []; db.transactions.push("ROLLBACK"); return { rows: [] }; }
          // reads see committed rows plus this transaction's own, so a second entry chains off the first
          return exec(sql, p, sql.startsWith("INSERT") ? staged : [...rows, ...staged]);
        },
        release() { db.transactions.push("release"); },
      };
    },
  };
  return db;
}

const actor = { email: "a@example.com", name: "A", oid: "oid-a", groups: ["not stored"] };

test("write chains each entry off the previous hash, the first off the genesis hash", async () => {
  const db = fakeDb();
  const audit = createAudit({ db, env: {}, log: quiet });
  const a = await audit.write(actor, "role:create", "role:Op", { x: 1 });
  const b = await audit.write(actor, "role:delete", "role:Op");
  assert.ok(a && b);
  assert.equal(db.rows[0].prev_hash, ZERO_HASH);
  assert.equal(db.rows[1].prev_hash, a.hash);
  assert.equal(db.rows[1].hash, b.hash);
  // only the three identifying actor fields are stored, never the token claims or groups
  assert.deepEqual(db.rows[0].actor_json, { email: "a@example.com", name: "A", oid: "oid-a" });
});

test("verify: an intact chain is ok and reports the secret mode", async () => {
  const db = fakeDb();
  const plain = createAudit({ db, env: {}, log: quiet });
  await plain.write(actor, "a", null);
  await plain.write(actor, "b", null);
  const r = await plain.verify();
  assert.equal(r.ok, true);
  assert.equal(r.length, 2);
  assert.equal(r.secretMode, "sha256-nosecret");
  const keyed = createAudit({ db: fakeDb(), env: { AUDIT_HMAC_SECRET: "k" }, log: quiet });
  await keyed.write(actor, "a", null);
  assert.equal((await keyed.verify()).secretMode, "hmac-sha256");
});

test("verify: the hmac key changes every hash, and a different key fails the chain", async () => {
  const db = fakeDb();
  await createAudit({ db, env: { AUDIT_HMAC_SECRET: "one" }, log: quiet }).write(actor, "a", null);
  assert.equal((await createAudit({ db, env: { AUDIT_HMAC_SECRET: "one" }, log: quiet }).verify()).ok, true);
  const wrong = await createAudit({ db, env: { AUDIT_HMAC_SECRET: "two" }, log: quiet }).verify();
  assert.equal(wrong.ok, false);
  assert.match(String(wrong.firstBreakReason), /hash mismatch on first chained entry/);
  // hmacEnv names another variable
  const other = createAudit({ db: fakeDb(), env: { MY_KEY: "x" }, hmacEnv: "MY_KEY", log: quiet });
  await other.write(actor, "a", null);
  assert.equal((await other.verify()).secretMode, "hmac-sha256");
});

async function chain(n = 4) {
  const db = fakeDb();
  const audit = createAudit({ db, env: { AUDIT_HMAC_SECRET: "k" }, log: quiet });
  for (let i = 0; i < n; i += 1) await audit.write(actor, `act:${i}`, `t:${i}`, { i });
  return { db, audit };
}

test("verify finds an entry edited after it was written", async () => {
  const { db, audit } = await chain();
  db.rows[2].details_json = { i: 99 };
  const r = await audit.verify();
  assert.equal(r.ok, false);
  assert.equal(r.firstBreakAt, 2);
  assert.match(String(r.firstBreakReason), /entry contents edited after write/);
});

test("verify finds an entry removed from the middle", async () => {
  const { db, audit } = await chain();
  db.rows.splice(1, 1);
  const r = await audit.verify();
  assert.equal(r.ok, false);
  assert.match(String(r.firstBreakReason), /log reordered or an entry removed/);
});

test("verify finds a deleted head: the first surviving entry must link to the genesis hash", async () => {
  const { db, audit } = await chain();
  db.rows.shift();
  const r = await audit.verify();
  assert.equal(r.ok, false);
  assert.equal(r.firstBreakAt, 0);
  assert.match(String(r.firstBreakReason), /leading segment of the log was deleted/);
});

test("verify finds reordered entries", async () => {
  const { db, audit } = await chain();
  [db.rows[1], db.rows[2]] = [db.rows[2], db.rows[1]];
  assert.equal((await audit.verify()).ok, false);
});

test("verify skips rows with no hash (written before the chain) and an empty log is ok", async () => {
  const { db, audit } = await chain(2);
  db.rows.unshift({ ...db.rows[0], id: "legacy", hash: null, prev_hash: null });
  assert.equal((await audit.verify()).ok, true);
  assert.equal((await createAudit({ db: fakeDb(), env: {}, log: quiet }).verify()).ok, true);
});

test("concurrent writes never fork the chain", async () => {
  const db = fakeDb();
  const audit = createAudit({ db, env: { AUDIT_HMAC_SECRET: "k" }, log: quiet });
  await Promise.all(Array.from({ length: 12 }, (_, i) => audit.write(actor, `n:${i}`, null)));
  assert.equal(db.rows.length, 12);
  assert.equal((await audit.verify()).ok, true);
  assert.equal(new Set(db.rows.map((r) => r.prev_hash)).size, 12);
});

test("write is non-fatal: a failed insert resolves null, logs, and the next write still chains", async () => {
  const db = fakeDb();
  const logged = /** @type {string[]} */ ([]);
  const audit = createAudit({ db, env: {}, log: { error: (/** @type {string} */ ...a) => logged.push(a.join(" ")) } });
  db.setFailInsert(true);
  assert.equal(await audit.write(actor, "a", null), null);
  assert.match(logged.join("\n"), /\[audit\] write failed \(non-fatal\): insert refused/);
  db.setFailInsert(false);
  assert.ok(await audit.write(actor, "b", null));
  assert.equal((await audit.verify()).ok, true);
});

test("transaction: entries commit with the change, chain off each other, and verify", async () => {
  const db = fakeDb();
  const audit = createAudit({ db, env: { AUDIT_HMAC_SECRET: "k" }, log: quiet });
  await audit.write(actor, "before", null);
  const out = await audit.transaction(async (_client, record) => {
    await record(actor, "one", "t:1");
    await record(actor, "two", "t:2");
    return "done";
  });
  assert.equal(out, "done");
  assert.deepEqual(db.transactions, ["BEGIN", "COMMIT", "release"]);
  assert.equal(db.rows.length, 3);
  assert.equal((await audit.verify()).ok, true);
});

test("transaction: a throw, or a returned rollback, leaves no entry; a failing record rolls the change back", async () => {
  const db = fakeDb();
  const audit = createAudit({ db, env: {}, log: quiet });
  await assert.rejects(audit.transaction(async (_c, record) => { await record(actor, "x", null); throw new Error("boom"); }), /boom/);
  assert.equal(db.rows.length, 0);
  assert.deepEqual(db.transactions.slice(0, 3), ["BEGIN", "ROLLBACK", "release"]);
  const r = await audit.transaction(async (_c, record) => { await record(actor, "y", null); return { rollback: true }; });
  assert.deepEqual(r, { rollback: true });
  assert.equal(db.rows.length, 0);
  db.setFailInsert(true);
  await assert.rejects(audit.transaction(async (_c, record) => { await record(actor, "z", null); }), /insert refused/);
  assert.equal(db.rows.length, 0);
  // a queue poisoned by a failed write still runs the next one
  db.setFailInsert(false);
  assert.ok(await audit.write(actor, "after", null));
});

test("extractContext: a request gives ip, user agent, request id, method and path; no request gives the same five nulls", () => {
  const audit = createAudit({ db: fakeDb(), env: {}, log: quiet });
  assert.deepEqual(audit.extractContext(null), { ip: null, userAgent: null, requestId: null, method: null, path: null });
  const ctx = audit.extractContext({ ip: "::ffff:20.1.2.3:1348", headers: { "user-agent": "u".repeat(300), "x-forwarded-for": "6.6.6.6" }, id: "r1", method: "POST", originalUrl: "/a?b=1" });
  assert.equal(ctx.ip, "20.1.2.3");
  assert.equal(ctx.userAgent?.length, 240);
  assert.deepEqual([ctx.requestId, ctx.method, ctx.path], ["r1", "POST", "/a?b=1"]);
  const custom = createAudit({ db: fakeDb(), env: {}, clientIp: () => "9.9.9.9", log: quiet });
  assert.equal(custom.extractContext({ ip: "1.1.1.1", headers: {} }).ip, "9.9.9.9");
});

test("clientPublicIp strips the port and the IPv4 mapping and fails to null", () => {
  assert.equal(clientPublicIp({ ip: "20.110.113.70:1348" }), "20.110.113.70");
  assert.equal(clientPublicIp({ ip: "::ffff:1.2.3.4" }), "1.2.3.4");
  assert.equal(clientPublicIp({ ip: "[2001:db8::1]:5678" }), "2001:db8::1");
  for (const bad of [null, {}, { ip: 5 }, { ip: "  " }]) assert.equal(clientPublicIp(bad), null);
});

test("stableStringify and canonicalizeEntry do not depend on key order, and undefined keys are dropped", () => {
  assert.equal(stableStringify({ b: 1, a: { d: [1, { z: 1, y: 2 }], c: undefined } }), stableStringify({ a: { c: undefined, d: [1, { y: 2, z: 1 }] }, b: 1 }));
  const e = { id: "1", ts: "t", schemaVersion: 1, actor: {}, action: "a", target: null, outcome: "success", context: {}, details: { b: 1, a: 2 }, prevHash: ZERO_HASH };
  assert.equal(canonicalizeEntry(e), canonicalizeEntry({ ...e, details: { a: 2, b: 1 } }));
});

test("csvCell quotes separators and neutralises a formula start", () => {
  assert.equal(csvCell("plain"), "plain");
  assert.equal(csvCell('a,"b"'), '"a,""b"""');
  assert.equal(csvCell(null), "");
  for (const f of ["=1+1", "+1", "-1", "@x", "\tx", "\rx"]) assert.ok(csvCell(f).startsWith("'") || csvCell(f).startsWith('"\''), f);
});

test("list pages newest first and count answers the row count", async () => {
  const { audit } = await chain(3);
  assert.equal(await audit.count(), 3);
  const page = await audit.list({}, { page: 1, limit: 2 });
  assert.equal(page.total, 3);
  assert.deepEqual(page.items.map((i) => i.action), ["act:2", "act:1"]);
  assert.equal(page.pages, 2);
  assert.deepEqual((await audit.list({}, { page: 2, limit: 2 })).items.map((i) => i.action), ["act:0"]);
});

test("createAudit needs a db with query()", () => {
  assert.throws(() => createAudit(/** @type {any} */ ({})), /needs a db/);
});
