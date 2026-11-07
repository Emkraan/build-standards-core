// shell-packages/settings: the secretbox round trip and failure modes, and the app settings cache.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createSecretbox, createAppSettings } from "../../../shell-packages/settings/index.js";

const INFO = "demo:integration-config:v1";

test("secretbox: seal then open returns the text, the sealed form has the v1 shape and differs each time", () => {
  const box = createSecretbox({ info: INFO, env: { SECRETBOX_MASTER_KEY: "master" } });
  const a = box.seal("token-123");
  const b = box.seal("token-123");
  assert.match(a, /^v1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/);
  assert.notEqual(a, b);
  assert.equal(box.open(a), "token-123");
  assert.equal(box.open(box.seal("")), null, "an empty ciphertext segment is not a sealed value");
  assert.equal(box.open(box.seal("\u00fcn\u00efcode \u2713")), "\u00fcn\u00efcode \u2713");
});

test("secretbox: no master means unavailable, seal throws and open answers null", () => {
  const box = createSecretbox({ info: INFO, env: {} });
  assert.equal(box.isAvailable(), false);
  assert.throws(() => box.seal("x"), /SECRETBOX_MASTER_KEY is not set/);
  const sealed = createSecretbox({ info: INFO, env: { SECRETBOX_MASTER_KEY: "m" } }).seal("x");
  assert.equal(box.open(sealed), null);
  assert.equal(createSecretbox({ info: INFO, env: { SECRETBOX_MASTER_KEY: "m" } }).isAvailable(), true);
});

test("secretbox: a different master, or a different info, cannot open the value", () => {
  const sealed = createSecretbox({ info: INFO, env: { SECRETBOX_MASTER_KEY: "m1" } }).seal("secret");
  assert.equal(createSecretbox({ info: INFO, env: { SECRETBOX_MASTER_KEY: "m2" } }).open(sealed), null);
  assert.equal(createSecretbox({ info: "demo:other:v1", env: { SECRETBOX_MASTER_KEY: "m1" } }).open(sealed), null);
  assert.equal(createSecretbox({ info: INFO, env: { SECRETBOX_MASTER_KEY: "m1" } }).open(sealed), "secret");
});

test("secretbox: a tampered or malformed value opens to null, never throws", () => {
  const box = createSecretbox({ info: INFO, env: { SECRETBOX_MASTER_KEY: "m" } });
  const [v, iv, tag, ct] = box.seal("secret").split(".");
  const flip = (/** @type {string} */ s) => (s.startsWith("A") ? "B" : "A") + s.slice(1);
  for (const bad of [[v, iv, tag, flip(String(ct))], [v, iv, flip(String(tag)), ct], [v, flip(String(iv)), tag, ct], ["v2", iv, tag, ct], [v, iv, tag], [v, iv, tag, ct, "x"]]) {
    assert.equal(box.open(bad.join(".")), null);
  }
  for (const bad of [undefined, null, 5, {}, "", "plain", "v1...", "v1.a.b.c"]) assert.equal(box.open(bad), null);
});

test("secretbox: masterEnv names another variable and info is required", () => {
  const box = createSecretbox({ info: INFO, masterEnv: "MY_MASTER", env: { MY_MASTER: "m" } });
  assert.equal(box.open(box.seal("x")), "x");
  assert.throws(() => createSecretbox({ info: INFO, masterEnv: "MY_MASTER", env: {} }).seal("x"), /MY_MASTER is not set/);
  assert.throws(() => createSecretbox(/** @type {any} */ ({})), /needs an info string/);
  assert.throws(() => createSecretbox({ info: "" }), /needs an info string/);
});

function fakeSettingsDb() {
  /** @type {Map<string, any>} */
  const rows = new Map();
  let reads = 0;
  return {
    rows,
    get reads() { return reads; },
    async query(/** @type {string} */ sql, /** @type {any[]} */ p) {
      if (sql.startsWith("SELECT value")) { reads += 1; return { rows: rows.has(p[0]) ? [{ value: rows.get(p[0]).value }] : [] }; }
      if (sql.includes("INSERT INTO app_settings")) { rows.set(p[0], { value: JSON.parse(p[1]), updated_by: p[2] }); return { rows: [] }; }
      throw new Error(`unexpected ${sql}`);
    },
  };
}

test("app settings: a missing name answers the fallback (default an empty object), a stored value wins", async () => {
  const db = fakeSettingsDb();
  const s = createAppSettings({ db });
  assert.deepEqual(await s.getSetting("flags"), {});
  assert.equal(await s.getSetting("other", "fb"), "fb");
  await s.setSetting("flags", { beta: true }, "a@example.com");
  assert.deepEqual(await s.getSetting("flags"), { beta: true });
  assert.equal(db.rows.get("flags").updated_by, "a@example.com");
  await s.setSetting("nothing", undefined);
  assert.deepEqual(db.rows.get("nothing"), { value: {}, updated_by: null });
});

test("app settings: reads are cached for ttlMs, a write clears its own name, a fallback is cached too", async () => {
  const db = fakeSettingsDb();
  let t = 1000;
  const s = createAppSettings({ db, ttlMs: 100, now: () => t });
  await s.getSetting("a");
  await s.getSetting("a");
  assert.equal(db.reads, 1);
  t += 99;
  await s.getSetting("a");
  assert.equal(db.reads, 1);
  t += 2;
  await s.getSetting("a");
  assert.equal(db.reads, 2);
  await s.getSetting("b");
  await s.setSetting("b", { v: 1 });
  assert.deepEqual(await s.getSetting("b"), { v: 1 });
  assert.equal(db.reads, 4);
  // another name's cache is untouched by a write
  await s.getSetting("a");
  assert.equal(db.reads, 4);
});

test("app settings needs a db with query()", () => {
  assert.throws(() => createAppSettings(/** @type {any} */ ({})), /needs a db/);
});
