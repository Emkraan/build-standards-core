// shell-packages/home-pins: the pages a person pins on the console Home, stored per person on the server.
//
//   GET    /pins   the caller's pinned pages
//   PUT    /pins   pin or re-label one page (idempotent)
//   DELETE /pins   unpin one page
//
// Every route is behind `gate` (the permission that shows the Home tab). Pins belong to the caller (the verified
// token's email, lowercased): nobody can read or write another person's. A pin must name a page the manifests
// declare, so a pin never carries a made up route. Pins are personal shortcuts and display only, the target page
// enforces its own access, so they are not audited.
//
// Schema: console_home_pins(user_email text 3..254 lowercase, module_id text '^[a-z][a-z0-9-]{1,31}$', route text
// 1..120 '^/[A-Za-z0-9/_:.-]*$' without '//', label text 1..60 printable ASCII without < >, position int 0..1000
// default 0, created_at timestamptz default now(), primary key (user_email, module_id, route)), and an index on
// (user_email, position, created_at). The route checks every rule first; the CHECKs are the backstop.

export const MAX_PINS = 12;
const LABEL_MAX = 60;
const PRINTABLE = /^[ -~]+$/;

/**
 * The routes each module declares, from the manifests the shell loaded.
 * @param {ReadonlyArray<{ id: string, pages?: ReadonlyArray<{ route: string }> }>} modules
 * @returns {Map<string, Set<string>>}
 */
export function declaredRoutes(modules) {
  return new Map(modules.map((m) => [m.id, new Set((m.pages || []).map((p) => p.route))]));
}

/**
 * Validate a pin body against the declared routes. Returns the clean pin or an error text.
 * @param {unknown} body
 * @param {Map<string, Set<string>>} routes
 * @returns {{ pin: { moduleId: string, route: string, label: string } } | { error: string }}
 */
export function validatePin(body, routes) {
  if (!body || typeof body !== "object" || Array.isArray(body)) return { error: "Send a JSON object." };
  const { moduleId, route, label } = /** @type {Record<string, unknown>} */ (body);
  if (typeof moduleId !== "string" || !routes.has(moduleId)) return { error: "Unknown tool." };
  if (typeof route !== "string" || !routes.get(moduleId)?.has(route)) return { error: "That page is not one this tool declares." };
  if (typeof label !== "string") return { error: "A label is required." };
  const clean = label.trim();
  if (clean.length < 1 || clean.length > LABEL_MAX || !PRINTABLE.test(clean) || /[<>]/.test(clean)) {
    return { error: `The label is 1 to ${LABEL_MAX} plain characters, no angle brackets.` };
  }
  return { pin: { moduleId, route, label: clean } };
}

/**
 * @param {{ get: Function, put: Function, delete: Function }} router an express Router
 * @param {{
 *   db: { query: (text: string, params?: unknown[]) => Promise<{ rows: any[] }> },
 *   gate: Function,
 *   caller: (req: any) => { email?: string | null } | null | undefined,
 *   modules: ReadonlyArray<{ id: string, pages?: ReadonlyArray<{ route: string }> }>,
 *   max?: number,
 * }} options
 */
export function homePinRoutes(router, options) {
  const { db, gate, caller } = options;
  const max = options.max ?? MAX_PINS;
  const routes = declaredRoutes(options.modules);

  /** @param {any} req @returns {string} */
  const emailOf = (req) => String(caller(req)?.email || "").toLowerCase();

  /** @param {string} email */
  async function readPins(email) {
    const { rows } = await db.query(
      `SELECT module_id AS "moduleId", route, label FROM console_home_pins WHERE user_email = $1 ORDER BY position, created_at LIMIT ${max}`,
      [email],
    );
    return rows;
  }

  router.get("/pins", gate, async (/** @type {any} */ req, /** @type {any} */ res, /** @type {any} */ next) => {
    try {
      const email = emailOf(req);
      if (!email) return res.status(401).json({ error: "Sign in again." });
      res.set("Cache-Control", "no-store");
      res.json({ pins: await readPins(email), max });
    } catch (e) { next(e); }
  });

  router.put("/pins", gate, async (/** @type {any} */ req, /** @type {any} */ res, /** @type {any} */ next) => {
    try {
      const email = emailOf(req);
      if (!email) return res.status(401).json({ error: "Sign in again." });
      const v = validatePin(req.body, routes);
      if ("error" in v) return res.status(400).json({ error: v.error });
      const { pin } = v;
      // One statement: a re-label of an existing pin, or a new pin only while the person is under the limit.
      const { rows } = await db.query(
        `INSERT INTO console_home_pins (user_email, module_id, route, label, position)
           SELECT $1, $2, $3, $4, COALESCE((SELECT MAX(position) + 1 FROM console_home_pins WHERE user_email = $1), 0)
            WHERE EXISTS (SELECT 1 FROM console_home_pins WHERE user_email = $1 AND module_id = $2 AND route = $3)
               OR (SELECT COUNT(*) FROM console_home_pins WHERE user_email = $1) < ${max}
           ON CONFLICT (user_email, module_id, route) DO UPDATE SET label = EXCLUDED.label
           RETURNING route`,
        [email, pin.moduleId, pin.route, pin.label],
      );
      if (rows.length === 0) return res.status(409).json({ error: `You can pin up to ${max} pages. Unpin one first.` });
      res.json({ pins: await readPins(email), max });
    } catch (e) { next(e); }
  });

  router.delete("/pins", gate, async (/** @type {any} */ req, /** @type {any} */ res, /** @type {any} */ next) => {
    try {
      const email = emailOf(req);
      if (!email) return res.status(401).json({ error: "Sign in again." });
      const moduleId = String((req.query && req.query.moduleId) || "");
      const route = String((req.query && req.query.route) || "");
      if (!routes.has(moduleId) || !routes.get(moduleId)?.has(route)) return res.status(400).json({ error: "Unknown page." });
      await db.query("DELETE FROM console_home_pins WHERE user_email = $1 AND module_id = $2 AND route = $3", [email, moduleId, route]);
      res.json({ pins: await readPins(email), max });
    } catch (e) { next(e); }
  });
}
