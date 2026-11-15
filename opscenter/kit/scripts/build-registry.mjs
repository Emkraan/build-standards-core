#!/usr/bin/env node
/*
 * build-registry.mjs: generates the module registry of a multi-module shell from the modules'
 * manifests (the web shell standard, section 3). Nobody edits the list by hand: a module joins
 * the shell by adding its manifest.
 *
 * Usage:
 *   node scripts/build-registry.mjs --manifests "modules/* /module.json" --out src/generated/registry.ts
 *        [--check] [--root .] [--fallback-icon Box] [--types @build-standards/kit]
 *        [--accents path/to/accents.json] [--extra-accents a,b] [--allow-keys a,b,x-*]
 *        [--validate-with path/to/check.mjs]
 *
 *   --manifests <glob>  Manifest files, relative to --root. `*` matches within one path segment
 *                       (no `**`). Repeat for several patterns. Default: modules/* /module.json
 *   --out <file>        The generated TypeScript file (relative to --root).
 *   --check             Write nothing. Exit 1 when the committed file differs from what the
 *                       manifests generate (the staleness check CI runs).
 *   --fallback-icon     The icon name a module with no icon gets. Default Box.
 *   --types <module>    Where the generated file imports RegistryEntry from. Default
 *                       @build-standards/kit.
 *   --accents <file>    The accent names file. Default: the kit's accents.json when it is found
 *                       next to this script's kit copy (kit-core or the core's kit/src).
 *
 *   --extra-accents    Host accent names added to the kit list (repeatable, comma separated). The
 *                       host defines the CSS for them. Default: none.
 *   --allow-keys        Manifest keys the host owns (repeatable, comma separated). A name ending in
 *                       `*` is a prefix, so `x-*` allows every key that starts with `x-`. An allowed
 *                       key is validated as JSON, carried through into the generated entry and typed
 *                       from its values. Default: none, so an unknown key is still an error.
 *   --validate-with     A module whose default export (or `validate` export) is called as
 *                       `(manifest, { label, dir, root })` for every manifest and returns a list of
 *                       problem strings (or nothing). Only the command line loads it, see runCli.
 *
 * A manifest is ASCII JSON with id, name, accent and optionally route, icon, order and
 * description (see the ModuleManifest type in the kit). The id is a lowercase slug, unique, and
 * the first segment of the route. Routes are unique. The accent is a kit accent name.
 *
 * Host keys are written after the seven kit fields, sorted by name. The file then exports
 * `ModuleExtras` (the inferred shape of the host keys, optional where a manifest omits one) and,
 * with `--extra-accents`, `ModuleAccent`, and types `MODULES` as `RegistryEntry<ModuleExtras,
 * ModuleAccent>`. With neither option the output is the same as before.
 *
 * Exit codes: 0 written or current, 1 invalid manifests or a stale file, 2 bad arguments.
 */
import { existsSync, readdirSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ID = /^[a-z0-9][a-z0-9_-]{0,63}$/;
const ICON = /^[A-Za-z][A-Za-z0-9]*$/;
const ASCII = /^[\x09\x0a\x0d\x20-\x7e]*$/;
const KEYS = new Set(['id', 'name', 'route', 'accent', 'icon', 'order', 'description']);
const DEFAULT_GLOB = 'modules/*/module.json';
const EXTENSION_NAME = /^[A-Za-z_][A-Za-z0-9_-]*\*?$/;
const ACCENT_NAME = /^[a-z][a-z0-9-]*$/;
const FORBIDDEN_KEYS = new Set(['__proto__', 'constructor', 'prototype']);
const HERE = dirname(fileURLToPath(import.meta.url));

function splitList(value) {
  return value.split(',').map((v) => v.trim()).filter(Boolean);
}

/** True when `key` is one the host allowed: an exact name, or a prefix entry ending in `*`. */
export function isAllowedKey(key, allowKeys = []) {
  if (KEYS.has(key) || FORBIDDEN_KEYS.has(key)) return false;
  return allowKeys.some((a) => (a.endsWith('*') ? a.length > 1 && key.startsWith(a.slice(0, -1)) : a === key));
}

export function parseArgs(argv) {
  const opts = { manifests: [], out: '', check: false, root: '.', fallbackIcon: 'Box', types: '@build-standards/kit', accents: '', extraAccents: [], allowKeys: [], validateWith: '' };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    const next = () => {
      i += 1;
      if (i >= argv.length) throw new Error(`${a} needs a value`);
      return argv[i];
    };
    if (a === '--manifests') opts.manifests.push(next());
    else if (a === '--out') opts.out = next();
    else if (a === '--check') opts.check = true;
    else if (a === '--root') opts.root = next();
    else if (a === '--fallback-icon') opts.fallbackIcon = next();
    else if (a === '--types') opts.types = next();
    else if (a === '--accents') opts.accents = next();
    else if (a === '--extra-accents') opts.extraAccents.push(...splitList(next()));
    else if (a === '--allow-keys') opts.allowKeys.push(...splitList(next()));
    else if (a === '--validate-with') opts.validateWith = next();
    else throw new Error(`unknown argument ${a}`);
  }
  if (!opts.out) throw new Error('--out is required');
  if (!ICON.test(opts.fallbackIcon)) throw new Error(`--fallback-icon "${opts.fallbackIcon}" is not an icon name`);
  for (const name of opts.extraAccents) if (!ACCENT_NAME.test(name)) throw new Error(`--extra-accents \"${name}\" is not an accent name (lowercase letters, digits, -)`);
  for (const name of opts.allowKeys) {
    const bare = name.replace(/\*$/, '');
    if (!EXTENSION_NAME.test(name) || FORBIDDEN_KEYS.has(bare)) throw new Error(`--allow-keys \"${name}\" is not a key name (a name, or a prefix ending in *)`);
    if (KEYS.has(name)) throw new Error(`--allow-keys \"${name}\" is already a manifest key`);
  }
  if (!opts.manifests.length) opts.manifests.push(DEFAULT_GLOB);
  return opts;
}

/** Files under root that match a glob in which `*` matches inside one path segment. Sorted. */
export function expandGlob(root, pattern) {
  const parts = pattern.split('/').filter((p) => p && p !== '.');
  if (parts.includes('..') || parts.includes('**')) throw new Error(`pattern "${pattern}" may not use .. or **`);
  let dirs = [''];
  parts.forEach((part, index) => {
    const last = index === parts.length - 1;
    const re = new RegExp(`^${part.split('*').map((s) => s.replace(/[.+?^${}()|[\]\\]/g, '\\$&')).join('[^/]*')}$`);
    const found = [];
    for (const dir of dirs) {
      const abs = join(root, dir);
      if (!existsSync(abs)) continue;
      for (const entry of readdirSync(abs, { withFileTypes: true })) {
        if (!re.test(entry.name)) continue;
        if (last ? entry.isFile() : entry.isDirectory()) found.push(dir ? `${dir}/${entry.name}` : entry.name);
      }
    }
    dirs = found;
  });
  return dirs.sort();
}

/** The accent names, or null when no accents file is found. */
export function loadAccents(explicit) {
  const candidates = explicit
    ? [resolve(explicit)]
    : [resolve(HERE, '../kit-core/theme/accents.json'), resolve(HERE, '../src/theme/accents.json'), resolve(HERE, '../kit/src/theme/accents.json')];
  for (const file of candidates) {
    if (!existsSync(file)) continue;
    const data = JSON.parse(readFileSync(file, 'utf8'));
    if (Array.isArray(data.accents)) return data.accents;
  }
  if (explicit) throw new Error(`accents file ${explicit} not found`);
  return null;
}

/** Problems with one parsed manifest. `label` names it in the messages. */
export function validateManifest(m, label, accents, options = {}) {
  const { allowKeys = [] } = options;
  const errs = [];
  const bad = (text) => errs.push(`${label}: ${text}`);
  if (m === null || typeof m !== 'object' || Array.isArray(m)) return [`${label}: must be a JSON object`];
  for (const key of Object.keys(m)) if (!KEYS.has(key) && !isAllowedKey(key, allowKeys)) bad(`unknown key ${key}`);
  if (typeof m.id !== 'string' || !ID.test(m.id)) bad('id must be a lowercase slug (letters, digits, - or _, at most 64)');
  if (typeof m.name !== 'string' || !m.name.trim()) bad('name must be a non-empty string');
  if (typeof m.accent !== 'string' || !m.accent) bad('accent is required');
  else if (accents && !accents.includes(m.accent)) bad(`accent ${m.accent} is not a kit accent`);
  if (m.icon !== undefined && (typeof m.icon !== 'string' || !ICON.test(m.icon))) bad('icon must be an icon name (letters and digits)');
  if (m.order !== undefined && !Number.isInteger(m.order)) bad('order must be an integer');
  if (m.description !== undefined && (typeof m.description !== 'string' || !m.description.trim())) bad('description must be a non-empty string');
  if (m.route !== undefined) {
    if (typeof m.route !== 'string' || !/^\/[A-Za-z0-9_-]+(\/[A-Za-z0-9_-]+)*$/.test(m.route)) {
      bad('route must be a path like /name with plain segments and no trailing slash');
    } else if (typeof m.id === 'string' && m.route.split('/')[1] !== m.id) {
      bad(`route ${m.route} must start with /${m.id}`);
    }
  }
  return errs;
}

/** Problems across the whole set: duplicate ids and routes. */
export function validateRegistry(entries) {
  const errs = [];
  const ids = new Map();
  const routes = new Map();
  for (const { label, manifest } of entries) {
    if (ids.has(manifest.id)) errs.push(`${label}: duplicate module id ${manifest.id} (also in ${ids.get(manifest.id)})`);
    else ids.set(manifest.id, label);
    const route = manifest.route ?? `/${manifest.id}`;
    if (routes.has(route)) errs.push(`${label}: duplicate route ${route} (also in ${routes.get(route)})`);
    else routes.set(route, label);
  }
  return errs;
}

/** Read every manifest. Returns { entries: [{ label, manifest }], errors }. */
export function readManifests(root, patterns, accents, options = {}) {
  const { allowKeys = [], validate } = options;
  const files = [...new Set(patterns.flatMap((p) => expandGlob(root, p)))].sort();
  const entries = [];
  const errors = [];
  for (const label of files) {
    const raw = readFileSync(join(root, label), 'utf8');
    if (!ASCII.test(raw)) {
      errors.push(`${label}: not ASCII`);
      continue;
    }
    let manifest;
    try {
      manifest = JSON.parse(raw);
    } catch (e) {
      errors.push(`${label}: invalid JSON (${e.message})`);
      continue;
    }
    const problems = validateManifest(manifest, label, accents, { allowKeys });
    if (!problems.length && validate) {
      const dir = label.includes('/') ? label.slice(0, label.lastIndexOf('/')) : '.';
      try {
        const found = validate(manifest, { label, dir, root });
        if (Array.isArray(found)) for (const text of found) problems.push(`${label}: ${text}`);
      } catch (e) {
        problems.push(`${label}: the --validate-with hook threw (${e.message})`);
      }
    }
    if (problems.length) errors.push(...problems);
    else entries.push({ label, manifest });
  }
  errors.push(...validateRegistry(entries));
  return { entries, errors };
}

/** The host keys of one manifest (everything outside the kit set), sorted by name. */
function hostKeys(m) {
  return Object.fromEntries(Object.keys(m).filter((k) => !KEYS.has(k)).sort().map((k) => [k, m[k]]));
}

const typeKey = (k) => (/^[A-Za-z_][A-Za-z0-9_]*$/.test(k) ? k : JSON.stringify(k));

/** A TypeScript type for JSON values: the union of what each value is. Objects merge by key. */
export function jsonType(values) {
  const kinds = new Set();
  const objects = [];
  const items = [];
  for (const v of values) {
    if (v === null) kinds.add('null');
    else if (Array.isArray(v)) {
      kinds.add('array');
      items.push(...v);
    } else if (typeof v === 'object') objects.push(v);
    else kinds.add(typeof v);
  }
  const parts = [...kinds].filter((k) => k !== 'array').sort();
  if (kinds.has('array')) parts.push(items.length ? arrayType(jsonType(items)) : 'readonly never[]');
  if (objects.length) parts.push(objectType(objects));
  return parts.join(' | ') || 'never';
}

const arrayType = (inner) => (inner.includes(' ') ? `readonly (${inner})[]` : `readonly ${inner}[]`);

function objectType(objects) {
  const keys = [...new Set(objects.flatMap((o) => Object.keys(o)))].sort();
  if (!keys.length) return 'Record<never, never>';
  const fields = keys.map((k) => {
    const have = objects.filter((o) => k in o);
    return `readonly ${typeKey(k)}${have.length < objects.length ? '?' : ''}: ${jsonType(have.map((o) => o[k]))}`;
  });
  return `{ ${fields.join('; ')} }`;
}

/** The ModuleExtras type of all host keys, or '' when no manifest carries one. */
function inferExtras(hostLists) {
  return hostLists.some((h) => Object.keys(h).length) ? objectType(hostLists) : '';
}

/** The generated file text, deterministic for a set of manifests. */
export function buildRegistry(entries, { fallbackIcon = 'Box', types = '@build-standards/kit', extraAccents = [] } = {}) {
  const modules = entries
    .map(({ manifest: m }) => ({
      id: m.id,
      name: m.name,
      route: m.route ?? `/${m.id}`,
      accent: m.accent,
      icon: m.icon ?? fallbackIcon,
      order: m.order ?? 0,
      ...(m.description !== undefined ? { description: m.description } : {}),
      ...hostKeys(m),
    }))
    .sort((a, b) => a.order - b.order || a.id.localeCompare(b.id));
  const extras = inferExtras(entries.map(({ manifest }) => hostKeys(manifest)));
  const accents = [...new Set(extraAccents)].sort();
  const typeArgs = extras || accents.length ? `<${extras ? 'ModuleExtras' : 'Record<never, never>'}${accents.length ? ', ModuleAccent' : ''}>` : '';
  const imports = ['RegistryEntry', ...(accents.length ? ['AppAccent'] : [])].sort();
  const icons = Object.fromEntries(modules.map((m) => [m.id, m.icon]));
  return [
    '// GENERATED by scripts/build-registry.mjs from the module manifests. Do not edit.',
    '// Regenerate it with the same command, add --check to verify it is current.',
    `import type { ${imports.join(', ')} } from '${types}';`,
    '',
    ...(extras ? [`export type ModuleExtras = ${extras};`, ''] : []),
    ...(accents.length ? [`export type ModuleAccent = AppAccent | ${accents.map((a) => JSON.stringify(a)).join(' | ')};`, ''] : []),
    `export const FALLBACK_ICON = ${JSON.stringify(fallbackIcon)};`,
    '',
    `export const MODULES: readonly RegistryEntry${typeArgs}[] = ${JSON.stringify(modules, null, 2)};`,
    '',
    `export const ICONS: Readonly<Record<string, string>> = ${JSON.stringify(icons, null, 2)};`,
    '',
  ].join('\n');
}

/** Runs the generator. `io` receives output lines, so tests need no process. Returns the exit code. */
export function run(argv, io = { out: console.log, err: console.error }, hooks = {}) {
  let opts;
  try {
    opts = parseArgs(argv);
  } catch (e) {
    io.err(`build-registry: ${e.message}`);
    return 2;
  }
  const root = resolve(opts.root);
  let accents;
  try {
    accents = loadAccents(opts.accents);
  } catch (e) {
    io.err(`build-registry: ${e.message}`);
    return 2;
  }
  if (opts.validateWith && !hooks.validate) {
    io.err('build-registry: --validate-with is loaded by runCli (or pass hooks.validate to run)');
    return 2;
  }
  const accentList = accents ? [...accents, ...opts.extraAccents] : null;
  const { entries, errors } = readManifests(root, opts.manifests, accentList, { allowKeys: opts.allowKeys, validate: hooks.validate });
  if (errors.length) {
    for (const e of errors) io.err(e);
    return 1;
  }
  const body = buildRegistry(entries, { fallbackIcon: opts.fallbackIcon, types: opts.types, extraAccents: opts.extraAccents });
  const out = join(root, opts.out);
  if (opts.check) {
    const current = existsSync(out) ? readFileSync(out, 'utf8') : '';
    if (current !== body) {
      io.err(`${opts.out} is out of date. Run build-registry.mjs without --check and commit the result.`);
      return 1;
    }
    io.out(`registry current: ${entries.length} modules`);
    return 0;
  }
  mkdirSync(dirname(out), { recursive: true });
  writeFileSync(out, body);
  io.out(`registry written: ${entries.map(({ manifest }) => manifest.id).join(', ') || 'no modules'}`);
  return 0;
}

// A native import() of a path known only at run time. It is built with Function so a test runner's
// module transform leaves it alone (that transform cannot sit behind the shebang line).
const importModule = new Function('specifier', 'return import(specifier)');

/** The command line entry: loads the --validate-with module, then runs. Returns the exit code. */
export async function runCli(argv, io = { out: console.log, err: console.error }) {
  let opts;
  try {
    opts = parseArgs(argv);
  } catch (e) {
    io.err(`build-registry: ${e.message}`);
    return 2;
  }
  let validate;
  if (opts.validateWith) {
    try {
      const mod = await importModule(pathToFileURL(resolve(opts.root, opts.validateWith)).href);
      validate = typeof mod.validate === 'function' ? mod.validate : mod.default;
      if (typeof validate !== 'function') throw new Error('it exports no function (default or validate)');
    } catch (e) {
      io.err(`build-registry: cannot load --validate-with ${opts.validateWith}: ${e.message}`);
      return 2;
    }
  }
  return run(argv, io, { validate });
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runCli(process.argv.slice(2)).then((code) => {
    process.exitCode = code;
  });
}
