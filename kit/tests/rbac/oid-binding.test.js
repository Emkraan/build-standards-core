import { test } from "node:test";
import assert from "node:assert/strict";
import { cleanOid, userRowMatches, pickUserRow } from "../../../shell-packages/rbac/index.js";

const OID = "7aec030a-c907-40cc-9787-cb339d028cfd";
const OTHER = "11111111-2222-3333-4444-555555555555";

test("cleanOid accepts a GUID in any case and rejects everything else", () => {
  assert.equal(cleanOid(OID.toUpperCase()), OID);
  assert.equal(cleanOid(" " + OID + " "), OID);
  for (const bad of ["", null, undefined, 5, "person-ca@example.com", OID + "x"]) assert.equal(cleanOid(bad), null);
});

test("a row with an object id matches that id only, whatever the email says", () => {
  const row = { user_oid: OID, user_email: "old-name@example.com" };
  assert.equal(userRowMatches(row, { email: "new-name@example.com", oid: OID.toUpperCase() }), true);
  // the same UPN given to a different person later must not inherit the grant
  assert.equal(userRowMatches(row, { email: "old-name@example.com", oid: OTHER }), false);
  // a token with no object id fails closed against a bound row
  assert.equal(userRowMatches(row, { email: "old-name@example.com" }), false);
});

test("a row without an object id still matches by email, case-insensitively", () => {
  const row = { user_oid: null, user_email: "Person-CA@example.com" };
  assert.equal(userRowMatches(row, { email: "person-ca@EXAMPLE.com", oid: OID }), true);
  assert.equal(userRowMatches(row, { email: "someone@example.com", oid: OID }), false);
  assert.equal(userRowMatches({ user_email: "" }, { email: "" }), false);
});

test("camelCase view rows work the same", () => {
  assert.equal(userRowMatches({ userOid: OID, userEmail: "x@y.z" }, { oid: OID, email: "other@y.z" }), true);
});

test("pickUserRow: the row bound to the object id wins over a legacy email row, whatever the order", () => {
  const legacy = { id: "l", user_email: "person-ca@example.com", user_oid: null };
  const bound = { id: "b", user_email: "old@example.com", user_oid: OID };
  const who = { email: "person-ca@example.com", oid: OID };
  assert.equal(pickUserRow([legacy, bound], who)?.id, "b");
  assert.equal(pickUserRow([bound, legacy], who)?.id, "b");
  assert.equal(pickUserRow([legacy], who)?.id, "l");
  // a row bound to someone else never matches on a shared email
  assert.equal(pickUserRow([{ id: "x", user_email: who.email, user_oid: OTHER }], who), undefined);
  assert.equal(pickUserRow([bound], { email: who.email, oid: null }), undefined);
});
