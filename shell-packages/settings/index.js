// shell-packages/settings: sealed secrets and plain application settings for the console to edit at runtime.
//
//   createSecretbox({ info, masterEnv, env })   AES-256-GCM for an integration secret entered in a Settings tab
//   createAppSettings({ db, ttlMs, now })       non-secret settings, one jsonb value per name, with a short cache
//
// Secrets never go in app settings: seal them with the secretbox and store the sealed string.

import crypto from "node:crypto";

/**
 * Symmetric encryption for console-configured integration secrets (a third party API token entered in a
 * Settings tab). AES-256-GCM with a key derived by HKDF from a dedicated master (the environment variable
 * named by `masterEnv`, default SECRETBOX_MASTER_KEY, normally a Key Vault secret). The `info` string
 * domain-separates the derivation, so the master is never used directly as a cipher key and one master can
 * back several independent derivations: use a different `info` per purpose, and bump its version to rotate
 * the derived key. `info` is required and must stay fixed, since changing it makes every stored secret
 * unreadable.
 *
 * Ciphertext format: "v1.<iv>.<tag>.<ct>" (base64url segments). Rotating the master invalidates stored
 * secrets (they must be re-entered): acceptable for re-pasteable API tokens, and the failure mode is a clean
 * "not configured" (open answers null), never a crash.
 * @param {{ info: string, masterEnv?: string, env?: Record<string, string | undefined> }} options
 */
export function createSecretbox(options) {
  const { info } = options || /** @type {any} */ ({});
  if (typeof info !== "string" || !info) throw new TypeError("createSecretbox needs an info string (the domain separation label)");
  const masterEnv = options.masterEnv || "SECRETBOX_MASTER_KEY";
  const env = options.env || process.env;
  const masterSecret = () => String(env[masterEnv] || "");

  function deriveKey() {
    const master = masterSecret();
    if (!master) return null;
    return Buffer.from(crypto.hkdfSync("sha256", Buffer.from(master, "utf8"), Buffer.alloc(0), info, 32));
  }

  return {
    /** True when a master key is configured. */
    isAvailable() {
      return !!masterSecret();
    },

    /**
     * Encrypt a UTF-8 string to "v1.iv.tag.ct" (base64url). Throws when there is no master.
     * @param {string} plaintext
     * @returns {string}
     */
    seal(plaintext) {
      const key = deriveKey();
      if (!key) throw new Error(`Secret storage unavailable: ${masterEnv} is not set`);
      const iv = crypto.randomBytes(12);
      const cipher = crypto.createCipheriv("aes-256-gcm", key, iv);
      const ct = Buffer.concat([cipher.update(plaintext, "utf8"), cipher.final()]);
      const tag = cipher.getAuthTag();
      return ["v1", iv.toString("base64url"), tag.toString("base64url"), ct.toString("base64url")].join(".");
    },

    /**
     * Decrypt "v1.iv.tag.ct" to a UTF-8 string, or null on any failure (no master, wrong key, tampered value,
     * malformed input). Callers treat null as "not configured".
     * @param {unknown} sealed
     * @returns {string | null}
     */
    open(sealed) {
      try {
        const key = deriveKey();
        if (!key || typeof sealed !== "string") return null;
        const parts = sealed.split(".");
        const [v, ivB64, tagB64, ctB64] = parts;
        if (parts.length !== 4 || v !== "v1" || !ivB64 || !tagB64 || !ctB64) return null;
        const decipher = crypto.createDecipheriv("aes-256-gcm", key, Buffer.from(ivB64, "base64url"));
        decipher.setAuthTag(Buffer.from(tagB64, "base64url"));
        return Buffer.concat([decipher.update(Buffer.from(ctB64, "base64url")), decipher.final()]).toString("utf8");
      } catch {
        return null;
      }
    },
  };
}

/**
 * Non-secret application settings (an app_settings table: name text primary key, value jsonb, updated_by text,
 * updated_at timestamptz) with a short in-process cache. For operator-tunable, non-sensitive config the console
 * edits at runtime: feature toggles, display defaults. The cache is per instance, so a change on another
 * instance shows within `ttlMs`.
 * @param {{ db: { query: (text: string, params?: unknown[]) => Promise<{ rows: any[] }> }, ttlMs?: number, now?: () => number }} options
 */
export function createAppSettings(options) {
  const { db } = options || /** @type {any} */ ({});
  if (!db || typeof db.query !== "function") throw new TypeError("createAppSettings needs a db with query()");
  const ttlMs = options.ttlMs ?? 30_000;
  const now = options.now || Date.now;
  /** @type {Map<string, { value: unknown, at: number }>} */
  const cache = new Map();

  return {
    /**
     * @param {string} name
     * @param {unknown} [fallback] what to answer when the name has no row (default an empty object)
     * @returns {Promise<unknown>}
     */
    async getSetting(name, fallback = {}) {
      const hit = cache.get(name);
      if (hit && now() - hit.at < ttlMs) return hit.value;
      const { rows } = await db.query("SELECT value FROM app_settings WHERE name = $1", [name]);
      const value = rows[0]?.value ?? fallback;
      cache.set(name, { value, at: now() });
      return value;
    },

    /**
     * @param {string} name
     * @param {unknown} value
     * @param {string | null} [actorEmail]
     */
    async setSetting(name, value, actorEmail) {
      await db.query(
        `INSERT INTO app_settings (name, value, updated_by, updated_at)
         VALUES ($1, $2::jsonb, $3, now())
         ON CONFLICT (name) DO UPDATE
           SET value = EXCLUDED.value, updated_by = EXCLUDED.updated_by, updated_at = now()`,
        [name, JSON.stringify(value ?? {}), actorEmail || null],
      );
      cache.delete(name);
    },
  };
}
