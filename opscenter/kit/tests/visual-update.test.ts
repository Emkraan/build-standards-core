import { describe, expect, it } from 'vitest';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { dockerArgs, parseArgs } from '../scripts/visual-update.mjs';

const KIT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const REPO = resolve(KIT, '..');

describe('visual-update arguments', () => {
  it('with none, keeps the core kit run exactly as before', () => {
    const s = parseArgs([]);
    expect(s).toEqual({ mode: '--ci', root: KIT, baselines: 'visual/baselines/linux', build: 'npm run gallery:build', workflow: 'visual.yml', artifact: 'visual-baselines' });
  });

  it('keeps the three modes', () => {
    for (const m of ['--ci', '--docker', '--local'] as const) expect(parseArgs([m]).mode).toBe(m);
  });

  it('a consumer root has no default build and its own baseline folder, workflow and artifact', () => {
    const s = parseArgs(['--docker', '--root', 'apps/site/visual', '--baselines', 'baselines/linux', '--workflow', 'site-visual.yml', '--artifact', 'site-baselines']);
    expect(s.root).toBe(resolve('apps/site/visual'));
    expect(s.build).toBeNull();
    expect(s).toMatchObject({ baselines: 'baselines/linux', workflow: 'site-visual.yml', artifact: 'site-baselines', mode: '--docker' });
  });

  it('a consumer build command is kept as given', () => {
    expect(parseArgs(['--root', 'x', '--build', 'npm run build']).build).toBe('npm run build');
  });

  it('refuses a typo, a missing value and a value that is another option', () => {
    expect(() => parseArgs(['--dockr'])).toThrow(/unknown argument --dockr/);
    expect(() => parseArgs(['--root'])).toThrow(/--root needs a value/);
    expect(() => parseArgs(['--root', '--docker'])).toThrow(/--root needs a value/);
    expect(() => parseArgs(['stray'])).toThrow(/unknown argument stray/);
  });
});

describe('visual-update docker run', () => {
  const env = { version: '1.50.0', repoDir: REPO };

  it('for the core kit is the command it has always run', () => {
    const a = dockerArgs(parseArgs(['--docker']), env);
    expect(a).toEqual([
      'run', '--rm', '--platform', 'linux/amd64', '--ipc=host',
      '-v', `${REPO}:/repo`, '-v', 'bsc-kit-visual-node-modules:/repo/kit/node_modules',
      '-w', '/repo/kit', '-e', 'CI=1', 'mcr.microsoft.com/playwright:v1.50.0-noble',
      'bash', '-lc', 'git config --global --add safe.directory "*" && npm ci && npm run gallery:build && npx playwright test --update-snapshots',
    ]);
  });

  it('for a consumer root mounts the repository and works inside that root with its own volume', () => {
    const root = resolve(REPO, 'apps/site/visual');
    const a = dockerArgs(parseArgs(['--docker', '--root', root, '--build', 'npm run build']), env);
    expect(a).toContain('/repo/apps/site/visual');
    const volume = a[a.indexOf('-v', a.indexOf('-v') + 1) + 1] ?? '';
    expect(volume).toMatch(/^bsc-visual-node-modules-[0-9a-f]{8}:\/repo\/apps\/site\/visual\/node_modules$/);
    expect(a[a.length - 1]).toBe('git config --global --add safe.directory "*" && npm ci && npm run build && npx playwright test --update-snapshots');
  });

  it('a consumer with no build command runs no build step', () => {
    const a = dockerArgs(parseArgs(['--docker', '--root', resolve(REPO, 'v')]), env);
    expect(a[a.length - 1]).toBe('git config --global --add safe.directory "*" && npm ci && npx playwright test --update-snapshots');
  });

  it('two roots never share a node_modules volume', () => {
    const v = (r: string) => dockerArgs(parseArgs(['--docker', '--root', resolve(REPO, r)]), env).filter((x) => x.includes('node-modules'))[0];
    expect(v('a')).not.toBe(v('b'));
  });
});
