import { test } from "node:test";
import assert from "node:assert/strict";
import { createGroupResolver, createTokenCache, parseExpiresOn } from "../../../shell-packages/app-server/index.js";

/** @returns {{ now: () => number, advance: (ms: number) => void }} */
function clock(start = 1_000_000) {
  let t = start;
  return { now: () => t, advance: (ms) => { t += ms; } };
}

/** @template T @returns {{ promise: Promise<T>, resolve: (v: T) => void, reject: (e: unknown) => void }} */
function deferred() {
  /** @type {(v: T) => void} */ let resolve = () => {};
  /** @type {(e: unknown) => void} */ let reject = () => {};
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise: /** @type {Promise<T>} */ (promise), resolve, reject };
}

test("cache hit: the second lookup inside the TTL does not call Graph", async () => {
  let calls = 0;
  const r = createGroupResolver({ fetchGroups: async () => { calls++; return ["G1", "g2"]; } });
  assert.deepEqual(await r.lookup("OID-1"), { groups: ["g1", "g2"], cache: "miss" });
  assert.deepEqual(await r.lookup("oid-1"), { groups: ["g1", "g2"], cache: "hit" });
  assert.equal(calls, 1);
});

test("returned arrays are copies, so a caller cannot corrupt the cache", async () => {
  const r = createGroupResolver({ fetchGroups: async () => ["g1"] });
  const first = await r.resolve("a");
  first.push("injected");
  assert.deepEqual(await r.resolve("a"), ["g1"]);
});

test("TTL expiry: a lookup after ttlMs calls Graph again", async () => {
  const c = clock();
  let calls = 0;
  const r = createGroupResolver({ fetchGroups: async () => { calls++; return [`g${calls}`]; }, ttlMs: 1000, now: c.now });
  assert.deepEqual(await r.resolve("a"), ["g1"]);
  c.advance(999);
  assert.deepEqual(await r.resolve("a"), ["g1"]);
  c.advance(2);
  assert.deepEqual(await r.lookup("a"), { groups: ["g2"], cache: "miss" });
  assert.equal(calls, 2);
});

test("default TTL is 5 minutes", async () => {
  const c = clock();
  let calls = 0;
  const r = createGroupResolver({ fetchGroups: async () => { calls++; return []; }, now: c.now });
  await r.resolve("a");
  c.advance(299_999);
  await r.resolve("a");
  assert.equal(calls, 1);
  c.advance(2);
  await r.resolve("a");
  assert.equal(calls, 2);
});

test("single flight: concurrent lookups for one oid share one Graph call", async () => {
  let calls = 0;
  /** @type {ReturnType<typeof deferred<string[]>>} */
  const d = deferred();
  const r = createGroupResolver({ fetchGroups: () => { calls++; return d.promise; } });
  const all = Promise.all(Array.from({ length: 25 }, () => r.lookup("a")));
  const other = r.lookup("b");
  d.resolve(["g1"]);
  const results = await all;
  await other;
  assert.equal(calls, 2, "one call for a, one for b");
  assert.equal(results.filter((x) => x.cache === "miss").length, 1);
  assert.equal(results.filter((x) => x.cache === "shared").length, 24);
  for (const x of results) assert.deepEqual(x.groups, ["g1"]);
});

test("failure is not cached: fail closed to [] and retry on the next request", async () => {
  let calls = 0;
  const outcomes = [null, undefined, "throw", ["g1"]];
  const errors = [];
  const r = createGroupResolver({
    fetchGroups: async () => {
      const o = outcomes[calls++];
      if (o === "throw") throw new Error("graph 503");
      return /** @type {any} */ (o);
    },
    onError: (e) => errors.push(e),
  });
  assert.deepEqual(await r.lookup("a"), { groups: [], cache: "error" });
  assert.deepEqual(await r.lookup("a"), { groups: [], cache: "error" });
  assert.deepEqual(await r.lookup("a"), { groups: [], cache: "error" });
  assert.equal(r.size, 0);
  assert.deepEqual(await r.lookup("a"), { groups: ["g1"], cache: "miss" });
  assert.deepEqual(await r.lookup("a"), { groups: ["g1"], cache: "hit" });
  assert.equal(calls, 4);
  assert.equal(errors.length, 1);
});

test("concurrent waiters on a failed call all fail closed and nothing is cached", async () => {
  /** @type {ReturnType<typeof deferred<string[]>>} */
  const d = deferred();
  const r = createGroupResolver({ fetchGroups: () => d.promise });
  const all = Promise.all([r.lookup("a"), r.lookup("a"), r.lookup("a")]);
  d.reject(new Error("boom"));
  for (const x of await all) assert.deepEqual(x.groups, []);
  assert.equal(r.size, 0);
});

test("an empty group list is a real answer and is cached", async () => {
  let calls = 0;
  const r = createGroupResolver({ fetchGroups: async () => { calls++; return []; } });
  await r.resolve("a");
  assert.deepEqual(await r.lookup("a"), { groups: [], cache: "hit" });
  assert.equal(calls, 1);
});

test("no oid: nothing looked up", async () => {
  let calls = 0;
  const r = createGroupResolver({ fetchGroups: async () => { calls++; return ["g"]; } });
  assert.deepEqual(await r.lookup(""), { groups: [], cache: "none" });
  assert.deepEqual(await r.lookup(undefined), { groups: [], cache: "none" });
  assert.equal(calls, 0);
});

test("LRU bound: the least recently used entry is evicted at maxEntries", async () => {
  const calls = /** @type {string[]} */ ([]);
  const r = createGroupResolver({ fetchGroups: async (oid) => { calls.push(oid); return [oid]; }, maxEntries: 3 });
  await r.resolve("a");
  await r.resolve("b");
  await r.resolve("c");
  await r.resolve("a"); // a becomes most recent, b is now the oldest
  await r.resolve("d"); // evicts b
  assert.equal(r.size, 3);
  assert.equal((await r.lookup("a")).cache, "hit");
  assert.equal((await r.lookup("c")).cache, "hit");
  assert.equal((await r.lookup("d")).cache, "hit");
  assert.equal((await r.lookup("b")).cache, "miss");
  assert.ok(r.size <= 3);
});

test("invalidate drops one user and leaves the rest cached", async () => {
  let calls = 0;
  const r = createGroupResolver({ fetchGroups: async (oid) => { calls++; return [`${oid}-${calls}`]; } });
  await r.resolve("a");
  await r.resolve("b");
  r.invalidate("A");
  assert.equal((await r.lookup("a")).cache, "miss");
  assert.equal((await r.lookup("b")).cache, "hit");
  r.clear();
  assert.equal(r.size, 0);
  assert.equal((await r.lookup("b")).cache, "miss");
});

test("invalidate during an in-flight call: the stale answer is not cached", async () => {
  /** @type {ReturnType<typeof deferred<string[]>>} */
  const d1 = deferred();
  let calls = 0;
  const r = createGroupResolver({ fetchGroups: () => { calls++; return calls === 1 ? d1.promise : Promise.resolve(["fresh"]); } });
  const first = r.lookup("a");
  r.invalidate("a");
  // A request after the invalidation does not join the stale call.
  assert.deepEqual(await r.lookup("a"), { groups: ["fresh"], cache: "miss" });
  d1.resolve(["stale"]);
  await first;
  assert.deepEqual(await r.lookup("a"), { groups: ["fresh"], cache: "hit" });
  assert.equal(calls, 2);
});

test("clear during an in-flight call: the stale answer is not cached", async () => {
  /** @type {ReturnType<typeof deferred<string[]>>} */
  const d1 = deferred();
  let calls = 0;
  const r = createGroupResolver({ fetchGroups: () => { calls++; return calls === 1 ? d1.promise : Promise.resolve(["fresh"]); } });
  const first = r.lookup("a");
  r.clear();
  d1.resolve(["stale"]);
  await first;
  assert.equal(r.size, 0);
  assert.deepEqual(await r.lookup("a"), { groups: ["fresh"], cache: "miss" });
});

test("fresh lookup skips the cache, reads Graph and refreshes the entry", async () => {
  let calls = 0;
  const r = createGroupResolver({ fetchGroups: async () => { calls++; return [`g${calls}`]; } });
  assert.deepEqual(await r.lookup("a"), { groups: ["g1"], cache: "miss" });
  assert.deepEqual(await r.lookup("a", { fresh: true }), { groups: ["g2"], cache: "miss" });
  assert.deepEqual(await r.lookup("a"), { groups: ["g2"], cache: "hit" });
  assert.equal(calls, 2);
});

test("a failed fresh lookup fails closed and drops the old entry", async () => {
  let calls = 0;
  const r = createGroupResolver({ fetchGroups: async () => { calls++; return calls === 2 ? null : ["g"]; } });
  await r.resolve("a");
  assert.deepEqual(await r.lookup("a", { fresh: true }), { groups: [], cache: "error" });
  assert.equal(r.size, 0);
  assert.deepEqual(await r.lookup("a"), { groups: ["g"], cache: "miss" });
});

test("bad options throw", () => {
  assert.throws(() => createGroupResolver(/** @type {any} */ ({})), /fetchGroups/);
  assert.throws(() => createGroupResolver({ fetchGroups: async () => [], ttlMs: 0 }), /ttlMs/);
  assert.throws(() => createGroupResolver({ fetchGroups: async () => [], maxEntries: 0 }), /maxEntries/);
});

test("token cache: cached until the refresh skew, single flight, failures not cached", async () => {
  const c = clock(1_000_000);
  let calls = 0;
  /** @type {Array<{ token: string, expiresAt: number } | null>} */
  const outcomes = [null, { token: "t1", expiresAt: 1_000_000 + 3_600_000 }, { token: "t2", expiresAt: 1_000_000 + 7_200_000 }];
  const tc = createTokenCache({ fetchToken: async () => outcomes[calls++] ?? null, now: c.now });
  assert.equal(await tc.get(), null);
  const [a, b] = await Promise.all([tc.get(), tc.get()]);
  assert.equal(a, "t1");
  assert.equal(b, "t1");
  assert.equal(calls, 2);
  c.advance(3_600_000 - 300_001);
  assert.equal(await tc.get(), "t1");
  c.advance(2);
  assert.equal(await tc.get(), "t2");
  assert.equal(calls, 3);
});

test("token cache: a throw propagates once and is retried", async () => {
  let calls = 0;
  const tc = createTokenCache({ fetchToken: async () => { calls++; if (calls === 1) throw new Error("imds down"); return { token: "t", expiresAt: Date.now() + 3_600_000 }; } });
  await assert.rejects(tc.get(), /imds down/);
  assert.equal(await tc.get(), "t");
});

test("token cache: a synchronous throw is not left cached", async () => {
  let calls = 0;
  const tc = createTokenCache({
    fetchToken: /** @type {any} */ (() => { calls++; if (calls === 1) throw new Error("sync boom"); return Promise.resolve({ token: "t", expiresAt: Date.now() + 3_600_000 }); }),
  });
  await assert.rejects(tc.get(), /sync boom/);
  assert.equal(await tc.get(), "t");
  assert.equal(calls, 2);
});

test("group resolver: a synchronous throw fails closed and is not cached", async () => {
  let calls = 0;
  const r = createGroupResolver({
    fetchGroups: /** @type {any} */ ((/** @type {string} */ _oid) => { calls++; if (calls === 1) throw new Error("sync boom"); return Promise.resolve(["g"]); }),
  });
  assert.deepEqual(await r.lookup("a"), { groups: [], cache: "error" });
  assert.deepEqual(await r.lookup("a"), { groups: ["g"], cache: "miss" });
});

test("token cache: clear() during an in-flight fetch keeps that token out of the cache", async () => {
  let calls = 0;
  /** @type {Array<(v: { token: string, expiresAt: number }) => void>} */
  const resolvers = [];
  const tc = createTokenCache({ fetchToken: () => { calls++; return new Promise((r) => resolvers.push(r)); } });
  const first = tc.get();
  await Promise.resolve();
  tc.clear();
  const second = tc.get();
  await new Promise((r) => setTimeout(r, 0));
  /** @type {any} */ (resolvers[0])({ token: "old", expiresAt: Date.now() + 3_600_000 });
  /** @type {any} */ (resolvers[1])({ token: "new", expiresAt: Date.now() + 3_600_000 });
  assert.equal(await first, "old");
  assert.equal(await second, "new");
  assert.equal(await tc.get(), "new");
  assert.equal(calls, 2);
});

test("parseExpiresOn handles unix seconds, strings and garbage", () => {
  assert.equal(parseExpiresOn("1700000000"), 1_700_000_000_000);
  assert.equal(parseExpiresOn(1700000000), 1_700_000_000_000);
  assert.equal(parseExpiresOn("2026-01-01T00:00:00Z"), Date.parse("2026-01-01T00:00:00Z"));
  assert.equal(parseExpiresOn("nope", () => 10), 10 + 55 * 60 * 1000);
  assert.equal(parseExpiresOn(undefined, () => 10), 10 + 55 * 60 * 1000);
  assert.equal(parseExpiresOn("", () => 10), 10 + 55 * 60 * 1000);
  assert.equal(parseExpiresOn(0, () => 10), 10 + 55 * 60 * 1000);
});
