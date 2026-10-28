/* The core registry generator accepts the multi-module shell manifest shape (web-shell-manifest.md):
   the shell's own keys pass as host extensions, `brand` as an extra accent, and the staleness check
   holds. The same fixtures are validated against the JSON schema by tests/test_console_module_schema.py. */
import { mkdtempSync, mkdirSync, copyFileSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { run } from '../scripts/build-registry.mjs';

const FIXTURES = resolve(__dirname, '../../tests/fixtures/console-module');
const HOST_KEYS = 'tagline,client,api,rbac,groups,pages,links,tiles,landing,whatsnew,home,x-*';
const dirs: string[] = [];
afterEach(() => {
  while (dirs.length) rmSync(dirs.pop() as string, { recursive: true, force: true });
});

function project(): string {
  const root = mkdtempSync(join(tmpdir(), 'kit-console-manifest-'));
  dirs.push(root);
  mkdirSync(join(root, 'apps'));
  for (const f of readdirSync(FIXTURES)) copyFileSync(join(FIXTURES, f), join(root, 'apps', f));
  return root;
}

function gen(root: string, ...extra: string[]) {
  const out: string[] = [];
  const err: string[] = [];
  const code = run(
    ['--root', root, '--manifests', 'apps/*.module.json', '--out', 'registry.ts', '--allow-keys', HOST_KEYS, '--extra-accents', 'brand', ...extra],
    { out: (l) => out.push(l), err: (l) => err.push(l) },
  );
  return { code, out: out.join('\n'), err: err.join('\n') };
}

describe('shell module manifests through the core generator', () => {
  it('generates every fixture, sorted by order, and carries the host keys', () => {
    const root = project();
    const r = gen(root);
    expect(r.err).toBe('');
    expect(r.code).toBe(0);
    const text = readFileSync(join(root, 'registry.ts'), 'utf8');
    expect(text.indexOf('"console"')).toBeLessThan(text.indexOf('"alerts"'));
    expect(text.indexOf('"alerts"')).toBeLessThan(text.indexOf('"fleet"'));
    for (const key of ['tagline', 'rbac', 'pages', 'home', 'whatsnew', 'x-host']) expect(text).toContain(`"${key}"`);
  });

  it('the staleness check passes after a build and fails after a manifest changes', () => {
    const root = project();
    expect(gen(root).code).toBe(0);
    expect(gen(root, '--check').code).toBe(0);
    const f = join(root, 'apps', 'fleet.module.json');
    const changed = readFileSync(f, 'utf8').replace('"order": 25', '"order": 26');
    expect(changed).not.toBe(readFileSync(f, 'utf8'));
    writeFileSync(f, changed);
    expect(gen(root, '--check').code).toBe(1);
  });

  it('without the host flags a shell key is an unknown key and the accent brand is rejected', () => {
    const root = project();
    const err: string[] = [];
    const code = run(['--root', root, '--manifests', 'apps/*.module.json', '--out', 'registry.ts'], { out: () => {}, err: (l) => err.push(l) });
    expect(code).toBe(1);
    expect(err.join('\n')).toMatch(/unknown key|accent/);
  });
});
