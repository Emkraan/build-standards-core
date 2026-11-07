import { test } from "node:test";
import assert from "node:assert/strict";
import { createUserBinding } from "../../../shell-packages/app-server/index.js";

const OID_A = "7aec030a-c907-40cc-9787-cb339d028cfd";
const OID_B = "11111111-2222-3333-4444-555555555555";
const PERSON = { oid: OID_A, name: "CA-Person One", upn: "person-ca@example.com", mail: "person+admin@example.com", created: "2023-01-01T00:00:00Z" };

/** @param {Record<string, any>} byEmail @param {Record<string, any>} [byOid] */
function fakeDirectory(byEmail, byOid = {}) {
  return /** @type {any} */ ({
    resolve: async (/** @type {string} */ e) => byEmail[String(e).toLowerCase()] || null,
    names: async (/** @type {string[]} */ ids) => new Map(ids.filter((i) => byOid[i]).map((i) => [i, byOid[i]])),
  });
}

test("bind: an object id the client sent is confirmed and the stored email becomes the sign-in name", async () => {
  const b = createUserBinding({ db: { query: async () => ({ rows: [] }) }, getToken: async () => null,
    directory: fakeDirectory({}, { [OID_A]: PERSON }) });
  const r = await b.bind({ email: "person+admin@example.com", oid: OID_A.toUpperCase() });
  assert.deepEqual({ ...r, release: undefined }, { email: "person-ca@example.com", oid: OID_A, name: "CA-Person One", bound: true, release: undefined });
});

test("bind: an email alone is looked up, and an unknown person stays on the email as typed", async () => {
  const b = createUserBinding({ db: { query: async () => ({ rows: [] }) }, getToken: async () => null,
    directory: fakeDirectory({ "person+admin@example.com": PERSON }) });
  assert.equal((await b.bind({ email: "Person+admin@example.com" })).oid, OID_A);
  assert.deepEqual({ ...(await b.bind({ email: "Ghost@example.com" })), release: undefined }, { email: "ghost@example.com", oid: null, name: null, bound: false, release: undefined });
  // a made-up object id the directory does not know is not trusted
  assert.equal((await b.bind({ email: "ghost@example.com", oid: OID_B })).oid, null);
});

test("withNames adds the full name and current sign-in name by object id", async () => {
  const b = createUserBinding({ db: { query: async () => ({ rows: [] }) }, getToken: async () => null,
    directory: fakeDirectory({}, { [OID_A]: PERSON }) });
  const out = await b.withNames([{ userEmail: "x", userOid: OID_A }, { userEmail: "legacy", userOid: null }]);
  assert.equal(out[0]?.userName, "CA-Person One");
  assert.equal(out[0]?.userUpn, "person-ca@example.com");
  assert.equal(out[1]?.userName, null);
});

test("backfill stamps rows stored under the sign-in name, counts the rest, and retires an identical unbound twin", async () => {
  /** @type {Array<[string, unknown[]]>} */
  const writes = [];
  const db = { query: async (/** @type {string} */ sql) => sql.includes("FROM role_assignments")
    ? { rows: [{ id: "a1", user_email: "person-ca@example.com", created_at: "2024-01-01T00:00:00Z" }, { id: "a2", user_email: "ghost@example.com" }, { id: "a3", user_email: "person-ca@example.com", created_at: "2024-01-01T00:00:00Z" }] }
    : { rows: [] } };
  const mutate = async (/** @type {string} */ sql, /** @type {unknown[] | undefined} */ params) => {
    writes.push([sql, params || []]);
    if (params && params[1] === "a3") throw Object.assign(new Error("dup"), { code: "23505" });
    return { rows: /^UPDATE role_assignments t/.test(sql) ? [{ id: "a3" }] : [] };
  };
  const b = createUserBinding({ db, mutate, getToken: async () => null, log: () => {},
    directory: fakeDirectory({ "person-ca@example.com": PERSON }) });
  assert.deepEqual(await b.backfill(), { stamped: 2, unresolved: 1, skipped: 0 });
  assert.deepEqual(writes[0]?.[1], [OID_A, "a1"]);
  assert.ok(writes.some(([sql, p]) => /^UPDATE role_assignments t SET user_email/.test(sql) && p[0] === "a3"));
});

test("bind: a sign-in name reused by a new person is released from the old person's row first", async () => {
  /** @type {Array<[string, unknown[]]>} */
  const writes = [];
  const mutate = async (/** @type {string} */ sql, /** @type {unknown[] | undefined} */ params) => { writes.push([sql, params || []]); return { rows: [] }; };
  const b = createUserBinding({ db: { query: async () => ({ rows: [] }) }, mutate, getToken: async () => null,
    directory: fakeDirectory({}, { [OID_B]: { oid: OID_B, name: "New Hire", upn: "shared.name@example.com", mail: null } }) });
  const r = await b.bind({ email: "shared.name@example.com", oid: OID_B });
  assert.equal(r.oid, OID_B);
  assert.equal(writes.length, 0, "bind is a read only lookup, nothing is written before the route's checks");
  await r.release();
  assert.equal(writes.length, 2);
  for (const [sql, params] of writes) {
    assert.match(sql, /SET user_email = lower\(user_email\) \|\| '#' \|\| lower\(user_oid\)/);
    assert.match(sql, /user_oid IS NOT NULL AND lower\(user_oid\) <> \$2/);
    assert.deepEqual(params, ["shared.name@example.com", OID_B]);
  }
});

test("bind: an unresolved person releases nothing", async () => {
  let writes = 0;
  const b = createUserBinding({ db: { query: async () => ({ rows: [] }) }, mutate: async () => { writes += 1; return { rows: [] }; }, getToken: async () => null, directory: fakeDirectory({}) });
  assert.equal((await b.bind({ email: "ghost@example.com" })).bound, false);
  assert.equal(writes, 0);
});

test("bind: an object id that does not belong to the typed name is not trusted", async () => {
  const b = createUserBinding({ db: { query: async () => ({ rows: [] }) }, mutate: async () => ({ rows: [] }), getToken: async () => null,
    directory: fakeDirectory({}, { [OID_A]: PERSON }) });
  const r = await b.bind({ email: "someone.else@example.com", oid: OID_A });
  assert.equal(r.oid, null);
  assert.equal((await b.bind({ email: "person+admin@example.com", oid: OID_A })).oid, OID_A);
  assert.equal((await b.bind({ email: "person-ca@example.com", oid: OID_A })).oid, OID_A);
});

test("backfill stamps the override stored under the sign-in name first and leaves the mail-keyed twin for a manual merge", async () => {
  /** @type {Array<[string, unknown[]]>} */
  const writes = [];
  const db = { query: async (/** @type {string} */ sql) => sql.includes("FROM permission_overrides")
    ? { rows: [{ id: "o-mail", user_email: "person+admin@example.com", created_at: "2024-01-01T00:00:00Z" }, { id: "o-upn", user_email: "person-ca@example.com", created_at: "2024-01-01T00:00:00Z" }] }
    : { rows: [] } };
  let stamped = false;
  const mutate = async (/** @type {string} */ sql, /** @type {unknown[] | undefined} */ params) => {
    writes.push([sql, params || []]);
    if (/^UPDATE permission_overrides SET user_oid/.test(sql)) { if (stamped) throw Object.assign(new Error("dup"), { code: "23505" }); stamped = true; }
    return { rows: [] };
  };
  const b = createUserBinding({ db, mutate, getToken: async () => null, log: () => {},
    directory: fakeDirectory({ "person+admin@example.com": PERSON, "person-ca@example.com": PERSON }) });
  assert.deepEqual(await b.backfill(), { stamped: 1, unresolved: 0, skipped: 1 });
  assert.deepEqual(writes[0]?.[1], [OID_A, "o-upn"]);
});

test("backfill stamps a row stored under the directory mail (the CA twin) so it starts to apply", async () => {
  /** @type {string[]} */
  const sqls = [];
  const db = { query: async (/** @type {string} */ sql) => sql.includes("FROM permission_overrides")
    ? { rows: [{ id: "o-mail", user_email: "person+admin@example.com", created_at: "2024-01-01T00:00:00Z" }] } : { rows: [] } };
  const mutate = async (/** @type {string} */ sql) => { sqls.push(sql); return { rows: [] }; };
  const b = createUserBinding({ db, mutate, getToken: async () => null, log: () => {},
    directory: fakeDirectory({ "person+admin@example.com": PERSON }) });
  assert.deepEqual(await b.backfill(), { stamped: 1, unresolved: 0, skipped: 0 });
  assert.equal(sqls.length, 1);
  assert.match(sqls[0] || "", /^UPDATE permission_overrides SET user_oid/);
});

test("backfill retires a twin the bound row already covers and keeps one that differs", async () => {
  /** @type {string[]} */
  const logs = [];
  const mk = (/** @type {boolean} */ covered) => {
    const db = { query: async (/** @type {string} */ sql) => sql.includes("FROM permission_overrides")
      ? { rows: [{ id: "o-upn", user_email: "person-ca@example.com", created_at: "2024-01-01T00:00:00Z" }, { id: "o-mail", user_email: "person+admin@example.com", created_at: "2024-01-01T00:00:00Z" }] } : { rows: [] } };
    let stamped = false;
    const mutate = async (/** @type {string} */ sql) => {
      if (/^UPDATE permission_overrides SET user_oid/.test(sql)) { if (stamped) throw Object.assign(new Error("dup"), { code: "23505" }); stamped = true; return { rows: [] }; }
      return { rows: covered ? [{ id: "o-mail" }] : [] };
    };
    return createUserBinding({ db, mutate, getToken: async () => null, log: (m) => logs.push(m),
      directory: fakeDirectory({ "person+admin@example.com": PERSON, "person-ca@example.com": PERSON }) });
  };
  assert.deepEqual(await mk(true).backfill(), { stamped: 2, unresolved: 0, skipped: 0 });
  assert.deepEqual(await mk(false).backfill(), { stamped: 1, unresolved: 0, skipped: 1 });
  assert.ok(logs.some((m) => /retired permission_overrides o-mail.*not deleted/.test(m)));
  assert.ok(logs.some((m) => /left for a manual merge/.test(m)));
});

test("bind: an unresolved person is bound false and routes have a message for a 503", async () => {
  const b = createUserBinding({ db: { query: async () => ({ rows: [] }) }, getToken: async () => null, directory: fakeDirectory({}) });
  assert.equal((await b.bind({ email: "ghost@example.com" })).bound, false);
  assert.match(b.unboundMessage, /no grant was saved/);
});

test("nameTaken asks for another row of the same person on the target name and never writes", async () => {
  /** @type {any[]} */ const seen = [];
  let writes = 0;
  const b = createUserBinding({
    db: { query: async (/** @type {string} */ text, /** @type {any} */ params = []) => { seen.push({ text, params }); return { rows: params[0] === "taken@example.com" ? [{ "?column?": 1 }] : [] }; } },
    mutate: async () => { writes += 1; return { rows: [] }; }, getToken: async () => null, directory: fakeDirectory({}) });
  assert.equal(await b.nameTaken("permission_overrides", "Taken@example.com", "o1", OID_A.toUpperCase()), true);
  assert.equal(await b.nameTaken("permission_overrides", "free@example.com", "o1", null), false);
  assert.deepEqual(seen[0].params, ["taken@example.com", "o1", OID_A]);
  assert.match(seen[0].text, /user_oid IS NULL OR lower\(user_oid\) = \$3/);
  assert.equal(writes, 0);
});

test("backfill never binds a mail row to an account created after the grant, or when a date is missing", async () => {
  const run = async (/** @type {string | null} */ rowCreated, /** @type {string | undefined} */ born) => {
    /** @type {string[]} */
    const sqls = [];
    const db = { query: async (/** @type {string} */ sql) => sql.includes("FROM permission_overrides")
      ? { rows: [{ id: "o1", user_email: "person+admin@example.com", created_at: rowCreated }] } : { rows: [] } };
    const b = createUserBinding({ db, mutate: async (/** @type {string} */ sql) => { sqls.push(sql); return { rows: [] }; }, getToken: async () => null, log: () => {},
      directory: fakeDirectory({ "person+admin@example.com": { ...PERSON, created: born } }) });
    return { out: await b.backfill(), sqls };
  };
  assert.deepEqual((await run("2024-01-01T00:00:00Z", "2025-06-01T00:00:00Z")).out, { stamped: 0, unresolved: 0, skipped: 1 });
  assert.deepEqual((await run(null, "2023-01-01T00:00:00Z")).out, { stamped: 0, unresolved: 0, skipped: 1 });
  assert.deepEqual((await run("2024-01-01T00:00:00Z", undefined)).out, { stamped: 0, unresolved: 0, skipped: 1 });
  const ok = await run("2024-01-01T00:00:00Z", "2023-01-01T00:00:00Z");
  assert.deepEqual(ok.out, { stamped: 1, unresolved: 0, skipped: 0 });
});

test("backfill leaves a mail match that is not the CA or admin twin shape unbound", async () => {
  const db = { query: async (/** @type {string} */ sql) => sql.includes("FROM permission_overrides")
    ? { rows: [{ id: "o1", user_email: "someone.old@example.com", created_at: "2024-01-01T00:00:00Z" }] } : { rows: [] } };
  const b = createUserBinding({ db, mutate: async () => ({ rows: [] }), getToken: async () => null, log: () => {},
    directory: fakeDirectory({ "someone.old@example.com": { oid: OID_B, name: "New Hire", upn: "new.hire@example.com", mail: "someone.old@example.com", created: "2023-01-01T00:00:00Z" } }) });
  assert.deepEqual(await b.backfill(), { stamped: 0, unresolved: 0, skipped: 1 });
});
