// shell-packages/route-conformance: the proof for web-shell-server.md section 1 rule 3 (every route is gated or says
// why not), as plain functions a consumer's own test calls. A valid tenant token proves identity only, so every
// console route (reads included) must carry a server-side permission gate. These checks read the route sources
// (node:fs, test time only) and answer a list of problem strings, empty when the code conforms:
//
//   routeTable(routesDir)                       every `router.<verb>("<path>", ...)` declaration, with its gate arguments
//   checkRoutes({ routesDir, allow })           a route with no gate and no listed reason, a declaration the parser could
//                                               not read, a reason listed for a route that no longer exists
//   checkGates(table, file, expected)           one file's route table is exactly the expected set, each on its own gate
//   checkAuthOrder({ indexSource, ... })        only the public routes sit before the sign-in check, every other router after
//   checkNoLiteralKeys(dirs)                    no literal HMAC key in a route or lib source
//   checkNoErrorDetail(file)                    a permission middleware 500 carries no internal error detail
//
// The route files are CommonJS or ESM with `router.get("/path", ...gates, handler)` declarations on one router
// variable (default name `router`). A route written another way (a computed path, a router under another name) is
// reported as unreadable, never skipped, so the table cannot silently shrink.

import fs from "node:fs";
import path from "node:path";

const VERBS = "get|post|put|patch|delete|all";
/** What counts as a gate in a route's arguments: the shell RBAC middleware names. */
export const DEFAULT_GATE = /\brequirePermission\(|\brequireAnyPermission\(|\brequireWildcard\(/;

/** @param {string} name */
const esc = (name) => name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/**
 * Every route declaration in the .js files of a directory.
 * @param {string} routesDir
 * @param {{ router?: string, ext?: string[] }} [options] router: the router variable name
 * @returns {{ table: { key: string, args: string }[], declared: number }}
 *   key is "<file> <VERB> <path>", args is the text between the path and the handler (the gates)
 */
export function routeTable(routesDir, options = {}) {
  const r = esc(options.router || "router");
  const decl = new RegExp(`\\b${r}\\.(${VERBS})\\(\\s*"([^"]*)",`, "g");
  const any = new RegExp(`\\b${r}\\.(${VERBS})\\(`, "g");
  const handlerStart = /(?:async\s*)?\(\s*_?req\b|\)\);/;
  const exts = options.ext || [".js", ".mjs", ".cjs"];
  /** @type {{ key: string, args: string }[]} */
  const table = [];
  let declared = 0;
  for (const f of fs.readdirSync(routesDir).filter((n) => exts.some((e) => n.endsWith(e))).sort()) {
    const src = fs.readFileSync(path.join(routesDir, f), "utf8");
    declared += (src.match(any) || []).length;
    const ms = [...src.matchAll(decl)];
    ms.forEach((m, i) => {
      const start = (m.index || 0) + m[0].length;
      const end = i + 1 < ms.length ? (ms[i + 1]?.index || src.length) : src.length;
      const seg = src.slice(start, end);
      const h = handlerStart.exec(seg);
      table.push({ key: `${f} ${(m[1] || "").toUpperCase()} ${m[2]}`, args: h ? seg.slice(0, h.index) : seg });
    });
  }
  return { table, declared };
}

/**
 * Every route carries a server-side permission gate or a stated reason, and no reason is stale.
 * @param {{
 *   routesDir: string,
 *   allow?: Record<string, string>,
 *   gate?: RegExp,
 *   router?: string,
 *   minRoutes?: number,
 * }} options allow maps "<file> <VERB> <path>" to the reason the route has no gate
 * @returns {string[]}
 */
export function checkRoutes(options) {
  const allow = options.allow || {};
  const gate = options.gate || DEFAULT_GATE;
  const { table, declared } = routeTable(options.routesDir, options.router ? { router: options.router } : {});
  /** @type {string[]} */
  const problems = [];
  if (table.length !== declared) problems.push(`${declared - table.length} route declaration(s) the conformance parser could not read (use a string literal path)`);
  const min = options.minRoutes ?? 1;
  if (table.length < min) problems.push(`expected at least ${min} route(s), saw ${table.length}`);
  for (const [key, reason] of Object.entries(allow)) if (!String(reason || "").trim()) problems.push(`${key}: the listed reason is empty`);
  for (const r of table) if (!allow[r.key] && !gate.test(r.args)) problems.push(`${r.key}: no server-side gate and no listed reason`);
  const live = new Set(table.map((r) => r.key));
  for (const k of Object.keys(allow)) if (!live.has(k)) problems.push(`${k}: listed in the allowlist but no such route`);
  return problems;
}

/**
 * One file's routes are exactly the expected set and each carries its own gate, so a route added to the file, or
 * moved to a broader gate, fails until it is classified.
 * @param {{ key: string, args: string }[]} table from routeTable
 * @param {string} file the route file name, for example "console.js"
 * @param {Record<string, RegExp | null>} expected "<VERB> <path>" to the pattern its gate must match (null: ungated, listed elsewhere)
 * @returns {string[]}
 */
export function checkGates(table, file, expected) {
  /** @type {string[]} */
  const problems = [];
  const mine = table.filter((r) => r.key.startsWith(`${file} `));
  const have = new Set(mine.map((r) => r.key.slice(file.length + 1)));
  for (const k of Object.keys(expected)) if (!have.has(k)) problems.push(`${file} ${k}: expected route is missing`);
  for (const r of mine) {
    const k = r.key.slice(file.length + 1);
    if (!(k in expected)) { problems.push(`${r.key}: route table changed, classify the new route`); continue; }
    const want = expected[k];
    if (want && !want.test(r.args)) problems.push(`${r.key}: must carry ${want}`);
  }
  return problems;
}

/**
 * Only the public routes sit before the sign-in check in the server entry, and every other router mounts after it.
 * @param {{
 *   indexSource: string,
 *   authMount?: string,
 *   publicPaths?: string[],
 *   prefix?: string,
 * }} options authMount: the exact statement that mounts the sign-in check; publicPaths: paths that may precede it
 * @returns {string[]}
 */
export function checkAuthOrder(options) {
  const src = options.indexSource;
  const authMount = options.authMount || 'app.use("/api", requireAuth);';
  const publicPaths = options.publicPaths || ["/api/", "/api/health", "/api/version"];
  const prefix = options.prefix || "/api";
  /** @type {Set<string>} */
  const problems = new Set();
  const auth = src.indexOf(authMount);
  if (auth < 0) return [`the sign-in mount ${authMount} is missing`];
  const mount = new RegExp(`app\\.(?:use|get|post|put|patch|delete)\\(\\s*"(${esc(prefix)}[A-Za-z0-9_/-]*)"`, "g");
  for (const m of src.slice(0, auth).matchAll(mount)) {
    const p = m[1] || "";
    if (!publicPaths.includes(p)) problems.add(`${p} is mounted before the sign-in check and is not a listed public path`);
  }
  const router = new RegExp(`^app\\.use\\("${esc(prefix)}/([a-z0-9-]+)",`, "gm");
  for (const m of src.matchAll(router)) {
    const p = `${prefix}/${m[1]}`;
    if (publicPaths.includes(p)) continue;
    if ((m.index || 0) < auth && ![...problems].some((x) => x.startsWith(`${p} `))) problems.add(`${p} is mounted before the sign-in check`);
  }
  return [...problems];
}

/**
 * No source file passes a literal string as the key of an HMAC.
 * @param {string[]} dirs directories of .js sources
 * @returns {string[]}
 */
export function checkNoLiteralKeys(dirs) {
  /** @type {string[]} */
  const problems = [];
  const literal = /createHmac\(\s*"[^"]*"\s*,\s*"[^"]+"\s*\)/;
  for (const dir of dirs) {
    for (const f of fs.readdirSync(dir).filter((n) => /\.(c|m)?js$/.test(n)).sort()) {
      if (literal.test(fs.readFileSync(path.join(dir, f), "utf8"))) problems.push(`${path.join(dir, f)}: literal HMAC key`);
    }
  }
  return problems;
}

/**
 * A response with status 500 never carries an internal error detail (a `details:` on the same line).
 * @param {string} file the permission middleware source
 * @returns {string[]}
 */
export function checkNoErrorDetail(file) {
  return fs.readFileSync(file, "utf8").split("\n")
    .map((l, i) => ({ l, n: i + 1 }))
    .filter(({ l }) => /status\(500\)/.test(l) && /details:/.test(l))
    .map(({ n }) => `${file}:${n}: a 500 response returns error details to the caller`);
}
