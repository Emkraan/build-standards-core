import { test } from "node:test";
import assert from "node:assert/strict";
import { createUserDirectory } from "../../../shell-packages/app-server/index.js";

const OID_A = "7aec030a-c907-40cc-9787-cb339d028cfd";
const OID_B = "11111111-2222-3333-4444-555555555555";

/**
 * @param {(url: string, init?: any) => any} handler
 * @returns {typeof fetch & { calls: Array<{ url: string, init: any }> }}
 */
function fakeFetch(handler) {
  /** @type {Array<{ url: string, init: any }>} */
  const calls = [];
  const fn = async (/** @type {any} */ url, /** @type {any} */ init) => {
    calls.push({ url: String(url), init });
    const body = handler(String(url), init);
    return /** @type {Response} */ (/** @type {unknown} */ ({ ok: body !== null, status: body === null ? 500 : 200, json: async () => body }));
  };
  return Object.assign(/** @type {typeof fetch} */ (fn), { calls });
}

test("resolve: the account whose sign-in name was typed wins over another account with that mail", async () => {
  const f = fakeFetch(() => ({ value: [
    { id: OID_B, displayName: "Other", mail: "person-ca@example.com", userPrincipalName: "other@example.com" },
    { id: OID_A, displayName: "CA-Person One", mail: "person+admin@example.com", userPrincipalName: "person-ca@example.com" },
  ] }));
  const dir = createUserDirectory({ getToken: async () => "t", fetchImpl: f });
  const u = await dir.resolve("Person-CA@example.com");
  assert.ok(u);
  assert.equal(u.oid, OID_A);
  assert.equal(u.name, "CA-Person One");
  // typing the mail finds the same person
  const f2 = fakeFetch(() => ({ value: [{ id: OID_A, displayName: "CA-Person One", mail: "person+admin@example.com", userPrincipalName: "person-ca@example.com" }] }));
  const u2 = await createUserDirectory({ getToken: async () => "t", fetchImpl: f2 }).resolve("person+admin@example.com");
  assert.ok(u2);
  assert.equal(u2.oid, OID_A);
  assert.equal(u2.upn, "person-ca@example.com");
});

test("resolve: two different people and no match both answer null, and Graph failures never throw", async () => {
  const two = fakeFetch(() => ({ value: [{ id: OID_A, userPrincipalName: "a@x.y" }, { id: OID_B, userPrincipalName: "b@x.y" }] }));
  assert.equal(await createUserDirectory({ getToken: async () => "t", fetchImpl: two }).resolve("shared@x.y"), null);
  const none = fakeFetch(() => ({ value: [] }));
  assert.equal(await createUserDirectory({ getToken: async () => "t", fetchImpl: none }).resolve("nobody@x.y"), null);
  const down = fakeFetch(() => null);
  assert.equal(await createUserDirectory({ getToken: async () => "t", fetchImpl: down }).resolve("a@x.y"), null);
  const noToken = fakeFetch(() => ({ value: [] }));
  assert.equal(await createUserDirectory({ getToken: async () => null, fetchImpl: noToken }).resolve("a@x.y"), null);
  assert.equal(noToken.calls.length, 0);
  const boom = /** @type {typeof fetch} */ (async () => { throw new Error("network"); });
  assert.equal(await createUserDirectory({ getToken: async () => "t", fetchImpl: boom }).resolve("a@x.y"), null);
});

test("names: one batched read, cached inside the TTL, ids that are not GUIDs are skipped", async () => {
  let t = 1000;
  const f = fakeFetch(() => ({ value: [
    { id: OID_A, displayName: "CA-Person One", userPrincipalName: "person-ca@example.com", mail: "person+admin@example.com" },
    { id: OID_B, displayName: "Person Two", userPrincipalName: "person.two@example.com", mail: null },
  ] }));
  const dir = createUserDirectory({ getToken: async () => "t", fetchImpl: f, now: () => t, ttlMs: 60_000 });
  const m = await dir.names([OID_A, OID_B.toUpperCase(), "not-a-guid", null]);
  assert.equal(m.size, 2);
  assert.equal(m.get(OID_A)?.name, "CA-Person One");
  assert.equal(f.calls.length, 1);
  assert.deepEqual(JSON.parse(f.calls[0]?.init.body).ids.sort(), [OID_A, OID_B].sort());
  await dir.names([OID_A, OID_B]);
  assert.equal(f.calls.length, 1);
  t += 61_000;
  await dir.names([OID_A]);
  assert.equal(f.calls.length, 2);
});

test("names: a failed read returns what is cached and does not throw", async () => {
  const dir = createUserDirectory({ getToken: async () => "t", fetchImpl: fakeFetch(() => null) });
  const m = await dir.names([OID_A]);
  assert.equal(m.size, 0);
});
