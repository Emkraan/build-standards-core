// Group lookups scoped to the groups an app references: batched checkMemberGroups
// and a cache keyed by the referenced list.
import "./consumer-preset.js";
import { test } from "node:test";
import assert from "node:assert/strict";
import { checkMemberGroups, createGroupResolver, normalizeGroupIds } from "../../../shell-packages/app-server/index.js";

/** @param {number} n */
const gid = (n) => `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;

/**
 * A synthetic Graph. member is the set of ids the user is in. Records each call.
 * @param {{ member?: Set<string>, status?: (call: number) => number, delay?: number }} [opts]
 */
function fakeGraph(opts = {}) {
  const member = opts.member || new Set();
  /** @type {Array<{ url: string, init: any }>} */
  const calls = [];
  let inFlight = 0;
  let peak = 0;
  /** @param {string} url @param {any} init */
  async function fetch(url, init) {
    calls.push({ url, init });
    const n = calls.length;
    inFlight++;
    peak = Math.max(peak, inFlight);
    await new Promise((r) => setTimeout(r, opts.delay || 1));
    inFlight--;
    const status = opts.status ? opts.status(n) : 200;
    const ids = /** @type {string[]} */ (JSON.parse(init.body).groupIds);
    return {
      ok: status >= 200 && status < 300,
      status,
      json: async () => ({ value: ids.filter((id) => member.has(id)).map((id) => id.toUpperCase()) }),
    };
  }
  return { fetch, calls, get peak() { return peak; } };
}

const quiet = () => {};

test("normalizeGroupIds trims, lowercases, de-duplicates and sorts", () => {
  assert.deepEqual(normalizeGroupIds([" B ", "a", "A", "", null, "b"]), ["a", "b"]);
  assert.deepEqual(normalizeGroupIds(undefined), []);
});

test("checkMemberGroups: more than 20 ids are split into batches of 20 that run in parallel", async () => {
  const ids = Array.from({ length: 45 }, (_, i) => gid(i));
  const g = fakeGraph({ member: new Set([gid(3), gid(21), gid(44)]), delay: 5 });
  const out = await checkMemberGroups({ oid: "OID-1", groupIds: ids, getToken: async () => "t", fetch: g.fetch, log: quiet });
  assert.deepEqual(out, [gid(3), gid(21), gid(44)]);
  assert.equal(g.calls.length, 3);
  assert.deepEqual(g.calls.map((c) => JSON.parse(c.init.body).groupIds.length), [20, 20, 5]);
  assert.equal(g.peak, 3, "the batches run in parallel");
  const first = /** @type {{ url: string, init: any }} */ (g.calls[0]);
  assert.match(first.url, /\/v1\.0\/directoryObjects\/OID-1\/checkMemberGroups$/);
  assert.equal(first.init.method, "POST");
  assert.equal(first.init.headers.Authorization, "Bearer t");
  assert.ok(first.init.signal, "every call carries a timeout signal");
});

test("checkMemberGroups: an empty list makes no Graph call, an answer never carries an id that was not asked", async () => {
  const g = fakeGraph();
  assert.deepEqual(await checkMemberGroups({ oid: "o", groupIds: [], getToken: async () => "t", fetch: g.fetch, log: quiet }), []);
  assert.equal(g.calls.length, 0);
  /** @param {string} _u @param {any} _i */
  const extra = async (_u, _i) => ({ ok: true, status: 200, json: async () => ({ value: [gid(1), gid(99)] }) });
  assert.deepEqual(await checkMemberGroups({ oid: "o", groupIds: [gid(1)], getToken: async () => "t", fetch: extra, log: quiet }), [gid(1)]);
});

test("checkMemberGroups: no oid, no token, a failed batch or a network error is null, and a 401 drops the token", async () => {
  const ids = Array.from({ length: 25 }, (_, i) => gid(i));
  assert.equal(await checkMemberGroups({ oid: "", groupIds: ids, getToken: async () => "t", fetch: fakeGraph().fetch, log: quiet }), null);
  assert.equal(await checkMemberGroups({ oid: "o", groupIds: ids, getToken: async () => null, fetch: fakeGraph().fetch, log: quiet }), null);
  let dropped = 0;
  const g = fakeGraph({ status: (n) => (n === 2 ? 401 : 200) });
  assert.equal(await checkMemberGroups({ oid: "o", groupIds: ids, getToken: async () => "t", fetch: g.fetch, onUnauthorized: () => { dropped++; }, log: quiet }), null);
  assert.equal(dropped, 1);
  const boom = async () => { throw new Error("socket hang up"); };
  assert.equal(await checkMemberGroups({ oid: "o", groupIds: ids, getToken: async () => "t", fetch: boom, log: quiet }), null);
  const tokenThrows = async () => { throw new Error("imds down"); };
  assert.equal(await checkMemberGroups({ oid: "o", groupIds: ids, getToken: tokenThrows, fetch: fakeGraph().fetch, log: quiet }), null);
});

test("checkMemberGroups: ids that are not object ids are skipped, so one bad row never fails the lookup", async () => {
  const logs = /** @type {string[]} */ ([]);
  const g = fakeGraph({ member: new Set([gid(1)]) });
  const out = await checkMemberGroups({ oid: "o", groupIds: [gid(1), "Display Name", "group-a", gid(2)], getToken: async () => "t", fetch: g.fetch, log: (m) => logs.push(m) });
  assert.deepEqual(out, [gid(1)]);
  assert.deepEqual(JSON.parse(/** @type {any} */ (g.calls[0]).init.body).groupIds, [gid(1), gid(2)]);
  assert.ok(logs.some((m) => /skipped 2 id/.test(m)));
  const none = fakeGraph();
  assert.deepEqual(await checkMemberGroups({ oid: "o", groupIds: ["nope"], getToken: async () => "t", fetch: none.fetch, log: quiet }), []);
  assert.equal(none.calls.length, 0);
});

test("checkMemberGroups: at most `concurrency` batches are in flight", async () => {
  const ids = Array.from({ length: 200 }, (_, i) => gid(i));
  const g = fakeGraph({ member: new Set([gid(199)]), delay: 3 });
  assert.deepEqual(await checkMemberGroups({ oid: "o", groupIds: ids, getToken: async () => "t", fetch: g.fetch, log: quiet }), [gid(199)]);
  assert.equal(g.calls.length, 10);
  assert.equal(g.peak, 4, "default 4 lanes");
  const one = fakeGraph({ delay: 2 });
  await checkMemberGroups({ oid: "o", groupIds: ids, getToken: async () => "t", fetch: one.fetch, concurrency: 1, log: quiet });
  assert.equal(one.peak, 1);
});

test("checkMemberGroups: a 401 drops the token even when another batch failed first", async () => {
  const ids = Array.from({ length: 40 }, (_, i) => gid(i));
  let dropped = 0;
  /** @param {string} _u @param {any} init */
  const f = async (_u, init) => {
    const first = JSON.parse(init.body).groupIds[0] === gid(0);
    await new Promise((r) => setTimeout(r, first ? 1 : 10));
    return { ok: false, status: first ? 500 : 401, json: async () => ({}) };
  };
  assert.equal(await checkMemberGroups({ oid: "o", groupIds: ids, getToken: async () => "t", fetch: f, onUnauthorized: () => { dropped++; }, log: quiet }), null);
  assert.equal(dropped, 1);
});

test("checkMemberGroups: a throttled batch is retried once, a second 429 fails the lookup", async () => {
  let n = 0;
  /** @param {string} _u @param {any} init */
  const once = async (_u, init) => (++n === 1
    ? { ok: false, status: 429, headers: { get: () => "0.01" }, json: async () => ({}) }
    : { ok: true, status: 200, json: async () => ({ value: JSON.parse(init.body).groupIds }) });
  assert.deepEqual(await checkMemberGroups({ oid: "o", groupIds: [gid(1)], getToken: async () => "t", fetch: once, log: quiet }), [gid(1)]);
  assert.equal(n, 2);
  let m = 0;
  const always = async () => { m++; return { ok: false, status: 429, headers: { get: () => "0" }, json: async () => ({}) }; };
  assert.equal(await checkMemberGroups({ oid: "o", groupIds: [gid(1)], getToken: async () => "t", fetch: always, log: quiet }), null);
  assert.equal(m, 2);
});

test("scoped resolver: a static list works like a provider, and a hit is filtered by the current list", async () => {
  const r = createGroupResolver({ groupIds: [gid(1), gid(2)], fetchGroups: async () => [gid(1), gid(2)] });
  assert.deepEqual(await r.resolve("oid-a"), [gid(1), gid(2)]);
  assert.equal((await r.lookup("oid-a")).cache, "hit");
});

test("scoped resolver: only the referenced ids are asked about and the answer is cached", async () => {
  let referenced = [gid(2), gid(1)];
  /** @type {string[][]} */
  const asked = [];
  const r = createGroupResolver({
    groupIds: () => referenced,
    fetchGroups: async (_oid, ids) => { asked.push(/** @type {string[]} */ (ids)); return [gid(1)]; },
  });
  assert.deepEqual(await r.lookup("oid-a"), { groups: [gid(1)], cache: "miss" });
  assert.deepEqual(await r.lookup("OID-A"), { groups: [gid(1)], cache: "hit" });
  assert.deepEqual(asked, [[gid(1), gid(2)]]);
  referenced = [gid(1), gid(2)]; // same set, different order: still a hit
  assert.equal((await r.lookup("oid-a")).cache, "hit");
});

test("scoped resolver: the cache key changes with the grant set, so a new group grant applies on the next request", async () => {
  let referenced = [gid(1)];
  const member = new Set([gid(1), gid(2)]);
  let calls = 0;
  const r = createGroupResolver({
    groupIds: async () => referenced,
    fetchGroups: async (_oid, ids) => { calls++; return (ids || []).filter((id) => member.has(id)); },
  });
  assert.deepEqual(await r.lookup("oid-a"), { groups: [gid(1)], cache: "miss" });
  referenced = [gid(1), gid(2)]; // an admin granted a role to group 2
  assert.deepEqual(await r.lookup("oid-a"), { groups: [gid(1), gid(2)], cache: "miss" }, "no stale negative answer");
  assert.equal((await r.lookup("oid-a")).cache, "hit");
  referenced = [gid(2)]; // the group 1 grant was removed
  assert.deepEqual(await r.lookup("oid-a"), { groups: [gid(2)], cache: "miss" });
  assert.equal(calls, 3);
});

test("scoped resolver: an answer is limited to the referenced ids", async () => {
  const r = createGroupResolver({ groupIds: () => [gid(1)], fetchGroups: async () => [gid(1), gid(7)] });
  assert.deepEqual(await r.resolve("oid-a"), [gid(1)]);
});

test("scoped resolver: no referenced groups means no Graph call", async () => {
  let calls = 0;
  const r = createGroupResolver({ groupIds: () => [], fetchGroups: async () => { calls++; return []; } });
  assert.deepEqual(await r.lookup("oid-a"), { groups: [], cache: "none" });
  assert.equal(calls, 0);
});

test("scoped resolver: a failed Graph call or referenced group read is not cached and fails closed", async () => {
  let graphFails = true;
  let listFails = false;
  const errors = /** @type {unknown[]} */ ([]);
  let calls = 0;
  const r = createGroupResolver({
    groupIds: async () => { if (listFails) throw new Error("db down"); return [gid(1)]; },
    fetchGroups: async () => { calls++; return graphFails ? null : [gid(1)]; },
    onError: (e) => errors.push(e),
  });
  assert.deepEqual(await r.lookup("oid-a"), { groups: [], cache: "error" });
  assert.equal(r.size, 0);
  graphFails = false;
  assert.deepEqual(await r.lookup("oid-a"), { groups: [gid(1)], cache: "miss" });
  listFails = true;
  assert.deepEqual(await r.lookup("oid-a"), { groups: [], cache: "error" }, "a list read failure fails closed, even with a cached entry");
  assert.equal(errors.length, 1);
  listFails = false;
  assert.equal((await r.lookup("oid-a")).cache, "hit");
  const nullList = createGroupResolver({ groupIds: () => null, fetchGroups: async () => { calls++; return [gid(1)]; } });
  const before = calls;
  assert.deepEqual(await nullList.lookup("oid-a"), { groups: [], cache: "error" });
  assert.equal(calls, before);
});

test("scoped resolver: a list read failure never falls back to an older list, so a removed grant cannot keep granting", async () => {
  let listFails = false;
  let referenced = [gid(1)];
  let calls = 0;
  const r = createGroupResolver({
    groupIds: async () => { if (listFails) throw new Error("db down"); return referenced; },
    fetchGroups: async (_o, ids) => { calls++; return (ids || []).filter((id) => id === gid(1)); },
    onError: () => {},
  });
  assert.deepEqual(await r.resolve("oid-a"), [gid(1)]);
  referenced = []; // the grant is removed (on another instance)
  listFails = true; // and this instance cannot read the list
  assert.deepEqual(await r.lookup("oid-a"), { groups: [], cache: "error" }, "no access from the old list");
  assert.deepEqual(await r.lookup("oid-b"), { groups: [], cache: "error" });
  listFails = false;
  assert.deepEqual(await r.lookup("oid-a"), { groups: [], cache: "none" }, "the removal applies once the list reads again");
  assert.equal(calls, 1);
});

test("scoped resolver: concurrent lookups share one list read", async () => {
  let reads = 0;
  const r = createGroupResolver({
    groupIds: async () => { reads++; await new Promise((x) => setTimeout(x, 3)); return [gid(1)]; },
    fetchGroups: async (oid) => [oid === "oid-a" ? gid(1) : gid(9)],
  });
  await Promise.all(["oid-a", "oid-b", "oid-c", "oid-a"].map((o) => r.lookup(o)));
  assert.equal(reads, 1);
  await r.lookup("oid-a");
  assert.equal(reads, 2, "a later lookup reads the list again");
});

test("scoped resolver: when no group is referenced any more, the cached entry is dropped", async () => {
  let referenced = [gid(1)];
  let calls = 0;
  const r = createGroupResolver({ groupIds: () => referenced, fetchGroups: async () => { calls++; return [gid(1)]; } });
  await r.resolve("oid-a");
  assert.equal(r.size, 1);
  referenced = [];
  assert.deepEqual(await r.lookup("oid-a"), { groups: [], cache: "none" });
  assert.equal(r.size, 0);
  referenced = [gid(1)];
  assert.equal((await r.lookup("oid-a")).cache, "miss", "the old entry is not served when the grant comes back");
  assert.equal(calls, 2);
});

test("checkMemberGroups: a batch Graph rejects with 400 is asked one id at a time, a rejected id counts as not a member", async () => {
  const ids = [gid(1), gid(2), gid(3)];
  /** @type {string[][]} */
  const asked = [];
  /** @param {string} _u @param {any} init */
  const f = async (_u, init) => {
    const batch = /** @type {string[]} */ (JSON.parse(init.body).groupIds);
    asked.push(batch);
    if (batch.includes(gid(2))) return { ok: false, status: 400, json: async () => ({}) };
    return { ok: true, status: 200, json: async () => ({ value: batch }) };
  };
  assert.deepEqual(await checkMemberGroups({ oid: "o", groupIds: ids, getToken: async () => "t", fetch: f, log: quiet }), [gid(1), gid(3)]);
  assert.deepEqual(asked, [ids, [gid(1)], [gid(2)], [gid(3)]]);
  const fiveHundred = async () => ({ ok: false, status: 500, json: async () => ({}) });
  assert.equal(await checkMemberGroups({ oid: "o", groupIds: ids, getToken: async () => "t", fetch: fiveHundred, log: quiet }), null, "other failures still fail closed");
  const allBad = async () => ({ ok: false, status: 400, json: async () => ({}) });
  assert.equal(await checkMemberGroups({ oid: "o", groupIds: ids, getToken: async () => "t", fetch: allBad, log: quiet }), null, "Graph rejecting every id is a failed lookup, never member of nothing");
  assert.equal(await checkMemberGroups({ oid: "o", groupIds: [gid(1)], getToken: async () => "t", fetch: allBad, log: quiet }), null, "the same for a single id");
});

test("scoped resolver: a fresh lookup (a write) reads live and refreshes the cache", async () => {
  const member = new Set([gid(1)]);
  let calls = 0;
  const r = createGroupResolver({ groupIds: () => [gid(1)], fetchGroups: async (_o, ids) => { calls++; return (ids || []).filter((id) => member.has(id)); } });
  assert.deepEqual(await r.resolve("oid-a"), [gid(1)]);
  member.delete(gid(1)); // removed from the group in the directory
  assert.deepEqual(await r.resolve("oid-a"), [gid(1)], "a read may serve the cached answer");
  assert.deepEqual(await r.lookup("oid-a", { fresh: true }), { groups: [], cache: "miss" }, "a write sees the removal at once");
  assert.deepEqual(await r.lookup("oid-a"), { groups: [], cache: "hit" });
  assert.equal(calls, 2);
});

test("scoped resolver: concurrent lookups share one Graph call, and an invalidate during the list read keeps the answer out of the cache", async () => {
  let calls = 0;
  /** @type {(v: string[]) => void} */
  let release = () => {};
  const gate = new Promise((r) => { release = r; });
  let gated = false;
  const r = createGroupResolver({
    groupIds: async () => (gated ? gate : [gid(1)]),
    fetchGroups: async () => { calls++; await new Promise((x) => setTimeout(x, 2)); return [gid(1)]; },
  });
  const all = await Promise.all(Array.from({ length: 10 }, () => r.lookup("oid-a")));
  assert.equal(calls, 1);
  assert.equal(all.filter((x) => x.cache === "shared").length, 9);
  r.clear();
  gated = true;
  const pending = r.lookup("oid-b");
  r.invalidate("oid-b");
  release([gid(1)]);
  assert.equal((await pending).cache, "miss");
  gated = false;
  assert.equal((await r.lookup("oid-b")).cache, "miss", "the answer read across the invalidate was not cached");
});

test("scoped resolver: checkMemberGroups plugs in as fetchGroups", async () => {
  const ids = Array.from({ length: 30 }, (_, i) => gid(i));
  const g = fakeGraph({ member: new Set([gid(25)]) });
  const r = createGroupResolver({
    groupIds: () => ids,
    fetchGroups: (oid, groupIds) => checkMemberGroups({ oid, groupIds: groupIds || [], getToken: async () => "t", fetch: g.fetch, log: quiet }),
  });
  assert.deepEqual(await r.resolve("oid-a"), [gid(25)]);
  assert.deepEqual(await r.resolve("oid-a"), [gid(25)]);
  assert.equal(g.calls.length, 2, "two batches once, then the cache");
});

test("bad groupIds option throws", () => {
  assert.throws(() => createGroupResolver({ fetchGroups: async () => [], groupIds: /** @type {any} */ ("x") }), /groupIds/);
});
