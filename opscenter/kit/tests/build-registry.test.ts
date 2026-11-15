/* The registry generator (web shell standard, section 3): a manifest added without regenerating
   fails the staleness check, and a module with no icon gets the fallback. */
import { spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import {
  buildRegistry,
  expandGlob,
  isAllowedKey,
  jsonType,
  loadAccents,
  parseArgs,
  readManifests,
  run,
  validateManifest,
  validateRegistry,
} from '../scripts/build-registry.mjs';
import { MODULES } from './fixtures/registry-host/registry';
import type { ModuleAccent, ModuleExtras } from './fixtures/registry-host/registry';
import type { AppAccent, GeneratedRegistry, ModuleDescriptor, ModuleManifest, RegistryEntry } from '../src';

type HostEntry = RegistryEntry<ModuleExtras, ModuleAccent>;
const SCRIPT = resolve(__dirname, '../scripts/build-registry.mjs');
const dirs: string[] = [];
afterEach(() => {
  while (dirs.length) rmSync(dirs.pop() as string, { recursive: true, force: true });
});

function project(files: Record<string, string | object>): string {
  const root = mkdtempSync(join(tmpdir(), 'kit-registry-'));
  dirs.push(root);
  for (const [name, body] of Object.entries(files)) write(root, name, body);
  return root;
}

function write(root: string, name: string, body: string | object): void {
  const file = join(root, name);
  mkdirSync(dirname(file), { recursive: true });
  writeFileSync(file, typeof body === 'string' ? body : `${JSON.stringify(body, null, 2)}\n`);
}

const manifest = (id: string, extra: Record<string, unknown> = {}) => ({ id, name: `Name ${id}`, accent: 'teal', ...extra });

function cli(root: string, ...args: string[]) {
  const out: string[] = [];
  const err: string[] = [];
  const code = run(['--root', root, '--out', 'src/registry.ts', ...args], { out: (l) => out.push(l), err: (l) => err.push(l) });
  return { code, out: out.join('\n'), err: err.join('\n') };
}

const TWO = {
  'modules/b/module.json': manifest('b', { order: 2, icon: 'Gear' }),
  'modules/a/module.json': manifest('a', { order: 1 }),
};

describe('parseArgs', () => {
  it('needs --out and defaults the pattern, fallback icon and types', () => {
    expect(() => parseArgs([])).toThrow(/--out is required/);
    const o = parseArgs(['--out', 'x.ts']);
    expect(o.manifests).toEqual(['modules/*/module.json']);
    expect(o.fallbackIcon).toBe('Box');
    expect(o.types).toBe('@build-standards/kit');
    expect(o.check).toBe(false);
  });

  it('reads every option and repeats --manifests', () => {
    const o = parseArgs(['--out', 'x.ts', '--manifests', 'a/*.json', '--manifests', 'b/*.json', '--check', '--root', 'r', '--fallback-icon', 'Dot', '--types', './t', '--accents', 'acc.json']);
    expect(o).toMatchObject({ manifests: ['a/*.json', 'b/*.json'], check: true, root: 'r', fallbackIcon: 'Dot', types: './t', accents: 'acc.json' });
  });

  it('rejects an unknown flag, a missing value and a bad fallback icon', () => {
    expect(() => parseArgs(['--out', 'x', '--nope'])).toThrow(/unknown argument/);
    expect(() => parseArgs(['--out'])).toThrow(/needs a value/);
    expect(() => parseArgs(['--out', 'x', '--fallback-icon', 'a b'])).toThrow(/icon name/);
  });
});

describe('expandGlob', () => {
  it('matches * inside one segment, sorted, files only at the end', () => {
    const root = project({ 'm/z/module.json': {}, 'm/a/module.json': {}, 'm/a/other.json': {}, 'm/file.json': {} });
    expect(expandGlob(root, 'm/*/module.json')).toEqual(['m/a/module.json', 'm/z/module.json']);
    expect(expandGlob(root, 'm/*.json')).toEqual(['m/file.json']);
    expect(expandGlob(root, 'missing/*/module.json')).toEqual([]);
  });

  it('refuses .. and **', () => {
    expect(() => expandGlob('.', '../x/*.json')).toThrow(/may not use/);
    expect(() => expandGlob('.', 'a/**/x.json')).toThrow(/may not use/);
  });

  it('escapes regular expression characters in a literal segment', () => {
    const root = project({ 'a.b/x.json': {}, 'axb/x.json': {} });
    expect(expandGlob(root, 'a.b/x.json')).toEqual(['a.b/x.json']);
  });
});

describe('validateManifest', () => {
  const accents = ['teal', 'blue'];
  it('accepts a minimal and a full manifest', () => {
    expect(validateManifest(manifest('a'), 'f', accents)).toEqual([]);
    expect(validateManifest(manifest('a', { route: '/a/x', icon: 'Box', order: -3, description: 'Short' }), 'f', accents)).toEqual([]);
  });

  it.each([
    [{ ...manifest('A') }, /id must be a lowercase slug/],
    [{ ...manifest('a'), id: undefined }, /id must be/],
    [{ ...manifest('a'), name: ' ' }, /name must be/],
    [{ ...manifest('a'), accent: undefined }, /accent is required/],
    [{ ...manifest('a'), accent: 'mauve' }, /accent mauve is not a kit accent/],
    [manifest('a', { icon: 'two words' }), /icon must be an icon name/],
    [manifest('a', { order: 1.5 }), /order must be an integer/],
    [manifest('a', { description: '' }), /description must be/],
    [manifest('a', { route: 'a' }), /route must be a path/],
    [manifest('a', { route: '/a/' }), /route must be a path/],
    [manifest('a', { route: '//a' }), /route must be a path/],
    [manifest('a', { route: '/b' }), /must start with \/a/],
    [manifest('a', { extra: 1 }), /unknown key extra/],
  ])('rejects %j', (m, pattern) => {
    expect(validateManifest(m, 'f', accents).join('\n')).toMatch(pattern);
  });

  it('rejects a manifest that is not an object', () => {
    expect(validateManifest([], 'f')).toEqual(['f: must be a JSON object']);
    expect(validateManifest(null, 'f')).toEqual(['f: must be a JSON object']);
  });

  it('skips the accent check when no accents are known', () => {
    expect(validateManifest(manifest('a', { accent: 'anything' }), 'f', null)).toEqual([]);
  });
});

describe('validateRegistry', () => {
  it('reports duplicate ids and duplicate routes', () => {
    const e = (label: string, id: string, route?: string) => ({ label, manifest: manifest(id, route ? { route } : {}) as never });
    const errs = validateRegistry([e('x', 'a'), e('y', 'a'), e('z', 'b', '/a')]);
    expect(errs.join('\n')).toMatch(/y: duplicate module id a \(also in x\)/);
    expect(errs.join('\n')).toMatch(/z: duplicate route \/a \(also in x\)/);
  });
});

describe('readManifests', () => {
  it('collects every problem across files instead of stopping at the first', () => {
    const root = project({
      'modules/a/module.json': '{ not json',
      'modules/b/module.json': manifest('b', { accent: 'mauve' }),
      'modules/c/module.json': `{ "id": "c", "name": "Caf\u00e9", "accent": "teal" }`,
      'modules/d/module.json': manifest('d'),
    });
    const { entries, errors } = readManifests(root, ['modules/*/module.json'], ['teal']);
    expect(entries.map((e) => e.manifest.id)).toEqual(['d']);
    expect(errors.join('\n')).toMatch(/modules\/a\/module.json: invalid JSON/);
    expect(errors.join('\n')).toMatch(/modules\/b\/module.json: accent mauve/);
    expect(errors.join('\n')).toMatch(/modules\/c\/module.json: not ASCII/);
    expect(errors).toHaveLength(3);
  });

  it('rejects a non-ASCII file', () => {
    const root = project({ 'modules/c/module.json': '{ "id": "c", "name": "Caf\u00e9", "accent": "teal" }' });
    expect(readManifests(root, ['modules/*/module.json'], null).errors).toEqual(['modules/c/module.json: not ASCII']);
  });

  it('merges several patterns without reading a file twice', () => {
    const root = project({ 'modules/a/module.json': manifest('a'), 'extra/b.json': manifest('b') });
    const { entries, errors } = readManifests(root, ['modules/*/module.json', 'extra/*.json', 'modules/a/module.json'], null);
    expect(errors).toEqual([]);
    expect(entries.map((e) => e.manifest.id)).toEqual(['b', 'a']);
  });
});

describe('buildRegistry', () => {
  const entries = (list: Array<Record<string, unknown>>) => list.map((m) => ({ label: `${String(m['id'])}.json`, manifest: m as never }));

  it('sorts by order then id, resolves defaults and applies the fallback icon', () => {
    const text = buildRegistry(entries([manifest('b', { order: 2, icon: 'Gear' }), manifest('a', { order: 1 }), manifest('c', { order: 1 })]));
    const modules = JSON.parse(text.slice(text.indexOf('= [') + 2, text.indexOf('];') + 1)) as RegistryEntry[];
    expect(modules.map((m) => m.id)).toEqual(['a', 'c', 'b']);
    expect(modules.map((m) => m.icon)).toEqual(['Box', 'Box', 'Gear']);
    expect(modules[0]).toMatchObject({ route: '/a', order: 1 });
  });

  it('writes the icon map with one entry per module and the fallback constant', () => {
    const text = buildRegistry(entries([manifest('a'), manifest('b', { icon: 'Gear' })]), { fallbackIcon: 'Dot' });
    expect(text).toContain('export const FALLBACK_ICON = "Dot";');
    expect(text).toContain('"a": "Dot"');
    expect(text).toContain('"b": "Gear"');
  });

  it('keeps an explicit route and description, and names the types module', () => {
    const text = buildRegistry(entries([manifest('a', { route: '/a/home', description: 'Short' })]), { types: './kit' });
    expect(text).toContain('"route": "/a/home"');
    expect(text).toContain('"description": "Short"');
    expect(text).toContain("import type { RegistryEntry } from './kit';");
  });

  it('is deterministic whatever order the manifests arrive in', () => {
    const one = buildRegistry(entries([manifest('a'), manifest('b')]));
    const two = buildRegistry(entries([manifest('b'), manifest('a')]));
    expect(one).toBe(two);
  });

  it('is plain ASCII with a generated header', () => {
    const text = buildRegistry(entries([manifest('a')]));
    expect(text).toMatch(/^[\x09\x0a\x20-\x7e]*$/);
    expect(text.startsWith('// GENERATED by scripts/build-registry.mjs')).toBe(true);
  });
});

describe('run', () => {
  it('writes the registry, then reports it current', () => {
    const root = project(TWO);
    const first = cli(root);
    expect(first.code).toBe(0);
    expect(first.out).toBe('registry written: a, b');
    const text = readFileSync(join(root, 'src/registry.ts'), 'utf8');
    expect(text).toContain('"id": "a"');
    const check = cli(root, '--check');
    expect(check).toMatchObject({ code: 0, out: 'registry current: 2 modules' });
  });

  it('staleness: a manifest added without regenerating fails the check', () => {
    const root = project(TWO);
    cli(root);
    write(root, 'modules/c/module.json', manifest('c'));
    const check = cli(root, '--check');
    expect(check.code).toBe(1);
    expect(check.err).toMatch(/src\/registry.ts is out of date/);
    expect(cli(root).code).toBe(0);
    expect(cli(root, '--check').code).toBe(0);
  });

  it('staleness: an edited manifest, a removed manifest and a hand edit all fail the check', () => {
    const root = project(TWO);
    cli(root);
    write(root, 'modules/a/module.json', manifest('a', { name: 'Renamed' }));
    expect(cli(root, '--check').code).toBe(1);
    cli(root);
    rmSync(join(root, 'modules/b'), { recursive: true });
    expect(cli(root, '--check').code).toBe(1);
    cli(root);
    writeFileSync(join(root, 'src/registry.ts'), `${readFileSync(join(root, 'src/registry.ts'), 'utf8')}// hand edit\n`);
    expect(cli(root, '--check').code).toBe(1);
  });

  it('--check fails when the file has never been generated, and writes nothing', () => {
    const root = project(TWO);
    expect(cli(root, '--check').code).toBe(1);
    expect(() => readFileSync(join(root, 'src/registry.ts'))).toThrow();
  });

  it('a module with no icon gets the fallback in both the entry and the icon map', () => {
    const root = project({ 'modules/a/module.json': manifest('a') });
    cli(root, '--fallback-icon', 'Dot');
    const text = readFileSync(join(root, 'src/registry.ts'), 'utf8');
    expect(text).toContain('"icon": "Dot"');
    expect(text).toContain('"a": "Dot"');
  });

  it('exits 1 and writes nothing when a manifest is invalid', () => {
    const root = project({ ...TWO, 'modules/c/module.json': manifest('c', { route: '/x' }) });
    const r = cli(root);
    expect(r.code).toBe(1);
    expect(r.err).toMatch(/must start with \/c/);
    expect(() => readFileSync(join(root, 'src/registry.ts'))).toThrow();
  });

  it('exits 1 on a duplicate id across folders', () => {
    const root = project({ 'modules/a/module.json': manifest('x'), 'modules/b/module.json': manifest('x') });
    expect(cli(root).err).toMatch(/duplicate module id x/);
  });

  it('exits 2 on bad arguments and on a missing accents file', () => {
    const root = project(TWO);
    expect(run(['--nope'], { out: () => undefined, err: () => undefined })).toBe(2);
    expect(cli(root, '--accents', join(root, 'missing.json')).code).toBe(2);
  });

  it('validates the accent against an accents file', () => {
    const root = project({ ...TWO, 'accents.json': { accents: ['blue'] } });
    const r = cli(root, '--accents', join(root, 'accents.json'));
    expect(r.code).toBe(1);
    expect(r.err).toMatch(/accent teal is not a kit accent/);
  });

  it('writes an empty registry when there are no modules', () => {
    const root = project({});
    expect(cli(root).out).toBe('registry written: no modules');
  });
});

describe('the kit accents file', () => {
  it('is found next to the script in the core layout', () => {
    const accents = loadAccents();
    expect(accents).toContain('cobalt');
  });
});

describe('command line', () => {
  it('exits with the same codes as run()', () => {
    const root = project(TWO);
    const args = ['--root', root, '--out', 'src/registry.ts'];
    const exec = (...more: string[]) => spawnSync(process.execPath, [SCRIPT, ...args, ...more], { encoding: 'utf8' });
    expect(exec('--check').status).toBe(1);
    expect(exec().status).toBe(0);
    expect(exec('--check').status).toBe(0);
    expect(spawnSync(process.execPath, [SCRIPT, '--bad'], { encoding: 'utf8' }).status).toBe(2);
  });
});

describe('descriptor types', () => {
  it('a module that matches the contract typechecks and one that drifts does not (checked by tsc)', () => {
    const manifestValue: ModuleManifest = { id: 'a', name: 'A', accent: 'teal' };
    const descriptor: ModuleDescriptor<{ path: string }[]> = {
      id: manifestValue.id,
      name: manifestValue.name,
      routes: [{ path: '/' }],
      rail: [{ key: 'home', label: 'Home', route: '/', requires: ['view'] }],
      canSee: (entry) => (entry.requires ?? []).every((p) => p === 'view'),
      accent: manifestValue.accent,
      icon: 'Box',
      feeds: [{ key: 'f', label: 'Feed', load: async () => [] }],
    };
    expect(descriptor.rail.filter(descriptor.canSee)).toHaveLength(1);
    // @ts-expect-error an accent that is not a kit accent is a type error
    const drift: ModuleDescriptor = { ...descriptor, accent: 'mauve' };
    expect(drift.id).toBe('a');
    const registry: GeneratedRegistry = { MODULES: [], ICONS: {}, FALLBACK_ICON: 'Box' };
    expect(registry.MODULES).toEqual([]);
  });
});

describe('host extensions (opt in)', () => {
  const host = (id: string, extra: Record<string, unknown> = {}) =>
    manifest(id, { tagline: 'One line', tags: ['a', 'b'], links: { docs: '/docs' }, ...extra });

  it('parses --allow-keys and --extra-accents as repeatable comma lists and rejects bad names', () => {
    const o = parseArgs(['--out', 'x.ts', '--allow-keys', 'tagline,x-*', '--allow-keys', 'links', '--extra-accents', 'brand', '--extra-accents', 'a-b,c']);
    expect(o.allowKeys).toEqual(['tagline', 'x-*', 'links']);
    expect(o.extraAccents).toEqual(['brand', 'a-b', 'c']);
    expect(o.validateWith).toBe('');
    expect(() => parseArgs(['--out', 'x', '--allow-keys', 'bad key'])).toThrow(/not a key name/);
    expect(() => parseArgs(['--out', 'x', '--allow-keys', '__proto__'])).toThrow(/not a key name/);
    expect(() => parseArgs(['--out', 'x', '--allow-keys', 'name'])).toThrow(/already a manifest key/);
    expect(() => parseArgs(['--out', 'x', '--extra-accents', 'Brand'])).toThrow(/not an accent name/);
  });

  it('isAllowedKey matches exact names and trailing-star prefixes only', () => {
    expect(isAllowedKey('tagline', ['tagline'])).toBe(true);
    expect(isAllowedKey('x-flag', ['x-*'])).toBe(true);
    expect(isAllowedKey('flag', ['x-*'])).toBe(false);
    expect(isAllowedKey('x', ['*'])).toBe(false);
    expect(isAllowedKey('id', ['id'])).toBe(false);
    expect(isAllowedKey('tagline', [])).toBe(false);
  });

  it('keeps rejecting an unknown key by default, and accepts it once allowed', () => {
    expect(validateManifest(host('a'), 'f', ['teal']).join('\n')).toMatch(/unknown key tagline/);
    expect(validateManifest(host('a'), 'f', ['teal'], { allowKeys: ['tagline', 'tags', 'links'] })).toEqual([]);
    expect(validateManifest(manifest('a', { 'x-one': 1 }), 'f', ['teal'], { allowKeys: ['x-*'] })).toEqual([]);
    expect(validateManifest(manifest('a', { other: 1 }), 'f', ['teal'], { allowKeys: ['x-*'] }).join('\n')).toMatch(/unknown key other/);
  });

  it('still validates the kit keys when host keys are allowed', () => {
    expect(validateManifest(host('a', { order: 1.5 }), 'f', ['teal'], { allowKeys: ['tagline', 'tags', 'links'] }).join('\n')).toMatch(/order must be an integer/);
  });

  it('infers a type from the values, optional where a manifest omits the key', () => {
    expect(jsonType(['a', 'b'])).toBe('string');
    expect(jsonType([1, 'a', null, true])).toBe('boolean | null | number | string');
    expect(jsonType([['a'], [1]])).toBe('readonly (number | string)[]');
    expect(jsonType([[]])).toBe('readonly never[]');
    expect(jsonType([{ a: 1 }, { a: 2, b: 'x' }])).toBe('{ readonly a: number; readonly b?: string }');
    expect(jsonType([{}])).toBe('Record<never, never>');
    expect(jsonType([{ 'x-y': 1 }])).toBe('{ readonly "x-y": number }');
  });

  it('carries host keys into the entry after the kit fields, sorted, and types them', () => {
    const text = buildRegistry([
      { label: 'a.json', manifest: host('a') as never },
      { label: 'b.json', manifest: manifest('b', { tagline: 'Other' }) as never },
    ]);
    expect(text).toContain("import type { RegistryEntry } from '@build-standards/kit';");
    expect(text).toContain('export type ModuleExtras = { readonly links?: { readonly docs: string }; readonly tagline: string; readonly tags?: readonly string[] };');
    expect(text).toContain('export const MODULES: readonly RegistryEntry<ModuleExtras>[] =');
    const modules = JSON.parse(text.slice(text.indexOf('= [') + 2, text.indexOf('];') + 1)) as Array<Record<string, unknown>>;
    expect(Object.keys(modules[0] as object)).toEqual(['id', 'name', 'route', 'accent', 'icon', 'order', 'links', 'tagline', 'tags']);
    expect(modules[1]).not.toHaveProperty('links');
  });

  it('writes a host accent type and widens the entry', () => {
    const text = buildRegistry([{ label: 'a.json', manifest: manifest('a', { accent: 'brand' }) as never }], { extraAccents: ['brand', 'alpha'] });
    expect(text).toContain("import type { AppAccent, RegistryEntry } from '@build-standards/kit';");
    expect(text).toContain('export type ModuleAccent = AppAccent | "alpha" | "brand";');
    expect(text).toContain('readonly RegistryEntry<Record<never, never>, ModuleAccent>[]');
  });

  it('leaves the output byte for byte as before when no option is used', () => {
    const text = buildRegistry([{ label: 'a.json', manifest: manifest('a') as never }]);
    expect(text).not.toContain('ModuleExtras');
    expect(text).not.toContain('ModuleAccent');
    expect(text).toContain('export const MODULES: readonly RegistryEntry[] =');
  });

  it('a host accent passes validation only when listed, and the file stays current', () => {
    const root = project({ 'modules/a/module.json': host('a', { accent: 'brand' }) });
    const keys = ['--allow-keys', 'tagline,tags,links'];
    expect(cli(root, ...keys).err).toMatch(/accent brand is not a kit accent/);
    expect(cli(root, ...keys, '--extra-accents', 'brand').code).toBe(0);
    expect(cli(root, ...keys, '--extra-accents', 'brand', '--check').code).toBe(0);
    expect(readFileSync(join(root, 'src/registry.ts'), 'utf8')).toContain('"tagline": "One line"');
    expect(cli(root, '--allow-keys', 'tagline,tags,links,x-*', '--extra-accents', 'brand', '--check').code).toBe(0);
  });

  it('a changed host value makes the check fail', () => {
    const root = project({ 'modules/a/module.json': host('a') });
    const args = ['--allow-keys', 'tagline,tags,links'];
    cli(root, ...args);
    write(root, 'modules/a/module.json', host('a', { tagline: 'Changed' }));
    expect(cli(root, ...args, '--check').code).toBe(1);
  });

  it('a hook adds host checks, labelled by file, and its throw is reported', () => {
    const root = project({
      'modules/a/module.json': host('a'),
      'modules/b/module.json': host('b', { tagline: 'bad' }),
    });
    const args = ['--allow-keys', 'tagline,tags,links'];
    const seen: string[] = [];
    const validate = (m: { id: string; tagline?: string }, ctx: { label: string; dir: string; root: string }) => {
      seen.push(`${ctx.dir}|${ctx.root === resolve(root)}`);
      return m.tagline === 'bad' ? ['tagline may not be bad'] : [];
    };
    const out: string[] = [];
    const err: string[] = [];
    expect(run(['--root', root, '--out', 'src/registry.ts', ...args], { out: (l) => out.push(l), err: (l) => err.push(l) }, { validate })).toBe(1);
    expect(err).toEqual(['modules/b/module.json: tagline may not be bad']);
    expect(seen).toEqual(['modules/a|true', 'modules/b|true']);
    const boom = () => {
      throw new Error('nope');
    };
    const err2: string[] = [];
    run(['--root', root, '--out', 'src/registry.ts', ...args], { out: () => undefined, err: (l) => err2.push(l) }, { validate: boom });
    expect(err2.join('\n')).toMatch(/hook threw \(nope\)/);
  });

  it('run without a hook function refuses --validate-with', () => {
    const root = project({ 'modules/a/module.json': host('a'), 'check.mjs': 'export default () => [];\n' });
    const r = cli(root, '--allow-keys', 'tagline,tags,links', '--validate-with', 'check.mjs');
    expect(r.code).toBe(2);
    expect(r.err).toMatch(/loaded by runCli/);
  });

  it('the command line loads the hook (default or named export) and reports its problems', () => {
    const root = project({
      'modules/a/module.json': host('a', { client: 'wrong' }),
      'check.mjs': "export default (m, ctx) => (m.client === m.id ? [] : [`client ${m.client} must equal the id in ${ctx.dir}`]);\n",
      'named.mjs': 'export const validate = () => undefined;\n',
      'empty.mjs': 'export const x = 1;\n',
    });
    const exec = (...more: string[]) =>
      spawnSync(process.execPath, [SCRIPT, '--root', root, '--out', 'src/registry.ts', '--allow-keys', 'tagline,tags,links,client', ...more], { encoding: 'utf8' });
    const bad = exec('--validate-with', 'check.mjs');
    expect(bad.status).toBe(1);
    expect(bad.stderr).toContain('modules/a/module.json: client wrong must equal the id in modules/a');
    expect(exec('--validate-with', 'named.mjs').status).toBe(0);
    expect(exec('--validate-with', 'empty.mjs')).toMatchObject({ status: 2 });
    expect(exec('--validate-with', 'missing.mjs').stderr).toMatch(/cannot load --validate-with missing.mjs/);
  });

  it('the command line takes the new options', () => {
    const root = project({
      'modules/a/module.json': host('a', { accent: 'brand' }),
      'check.mjs': 'export default () => [];\n',
    });
    const r = spawnSync(
      process.execPath,
      [SCRIPT, '--root', root, '--out', 'src/registry.ts', '--allow-keys', 'tagline,tags,links', '--extra-accents', 'brand', '--validate-with', 'check.mjs'],
      { encoding: 'utf8' },
    );
    expect(r.status).toBe(0);
    expect(r.stdout.trim()).toBe('registry written: a');
  });

  it('the committed host fixture is current and its generated file typechecks (tsc covers tests/)', () => {
    const fixture = resolve(__dirname, 'fixtures/registry-host');
    const r = spawnSync(
      process.execPath,
      [SCRIPT, '--root', fixture, '--out', 'registry.ts', '--allow-keys', 'tagline,tags,links,x-*', '--extra-accents', 'brand', '--types', '../../../src', '--check'],
      { encoding: 'utf8' },
    );
    expect(r.stderr).toBe('');
    expect(r.status).toBe(0);
    const typed: readonly HostEntry[] = MODULES;
    expect(typed.map((m) => m.accent)).toEqual(['brand', 'teal']);
    expect(MODULES[0]?.links?.docs).toBe('/alpha/docs');
  });

  it('prototype-polluting keys are never allowed', () => {
    const raw = '{ "id": "a", "name": "A", "accent": "teal", "__proto__": { "x": 1 } }';
    const root = project({ 'modules/a/module.json': raw });
    expect(readManifests(root, ['modules/*/module.json'], null, { allowKeys: ['tagline'] }).errors.join('\n')).toMatch(/unknown key __proto__/);
  });
});

describe('generic descriptor types', () => {
  type Extra = { readonly tagline: string };
  it('a host extends the manifest, entry and descriptor with its own members (checked by tsc)', () => {
    const m: ModuleManifest<Extra, AppAccent | 'brand'> = { id: 'a', name: 'A', accent: 'brand', tagline: 'T' };
    const entry: RegistryEntry<Extra, AppAccent | 'brand'> = { id: 'a', name: 'A', route: '/a', accent: m.accent, icon: 'Box', order: 0, tagline: m.tagline };
    const registry: GeneratedRegistry<Extra, AppAccent | 'brand'> = { MODULES: [entry], ICONS: {}, FALLBACK_ICON: 'Box' };
    const descriptor: ModuleDescriptor<string[], { client: string }, AppAccent | 'brand'> = {
      id: 'a', name: 'A', routes: [], rail: [], canSee: () => true, accent: 'brand', icon: 'Box', client: 'web',
    };
    expect(registry.MODULES[0]?.tagline).toBe('T');
    expect(descriptor.client).toBe('web');
    // @ts-expect-error a host member that is declared must be present
    const missing: ModuleDescriptor<string[], { client: string }> = { id: 'a', name: 'A', routes: [], rail: [], canSee: () => true, accent: 'teal', icon: 'Box' };
    expect(missing.id).toBe('a');
    // @ts-expect-error the default accent type is still the kit list
    const drift: RegistryEntry = { ...entry, accent: 'brand' };
    expect(drift.id).toBe('a');
  });
});
