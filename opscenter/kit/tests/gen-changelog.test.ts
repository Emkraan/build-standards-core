import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';

const SCRIPT = resolve(__dirname, '../scripts/gen-changelog.mjs');
const dirs: string[] = [];

// A throwaway identity for the temporary repositories, assembled at run time.
const IDENTITY = { name: 'Kit Test', email: ['kit-test', 'example.invalid'].join('@') };

function tempRepo(): string {
  const dir = mkdtempSync(join(tmpdir(), 'kit-changelog-'));
  dirs.push(dir);
  git(dir, ['init', '-q']);
  return dir;
}

function git(dir: string, args: string[], date = '2026-10-01T12:00:00Z'): void {
  const r = spawnSync('git', ['-C', dir, '-c', 'commit.gpgsign=false', ...args], {
    encoding: 'utf8',
    env: {
      ...process.env,
      GIT_AUTHOR_NAME: IDENTITY.name,
      GIT_AUTHOR_EMAIL: IDENTITY.email,
      GIT_COMMITTER_NAME: IDENTITY.name,
      GIT_COMMITTER_EMAIL: IDENTITY.email,
      GIT_AUTHOR_DATE: date,
      GIT_COMMITTER_DATE: date,
    },
  });
  if (r.status !== 0) throw new Error(r.stderr);
}

function commit(dir: string, message: string, date?: string): void {
  git(dir, ['commit', '-q', '--allow-empty', '-m', message], date);
}

function commitFile(dir: string, file: string, message: string, date?: string): void {
  mkdirSync(dirname(join(dir, file)), { recursive: true });
  writeFileSync(join(dir, file), message);
  git(dir, ['add', '--', file], date);
  git(dir, ['commit', '-q', '-m', message], date);
}

function run(dir: string, out: string, ...extra: string[]) {
  return runEnv({}, dir, out, ...extra);
}

function runEnv(env: Record<string, string>, dir: string, out: string, ...extra: string[]) {
  // The ceiling keeps git from finding a repository above the temporary directory.
  const base: Record<string, string | undefined> = { ...process.env, GIT_CEILING_DIRECTORIES: dirname(dir) };
  delete base['CHANGELOG_ALLOW_EMPTY'];
  return spawnSync(process.execPath, [SCRIPT, '--repo', dir, '--out', out, ...extra], {
    encoding: 'utf8',
    env: { ...base, ...env },
  });
}

afterEach(() => {
  for (const d of dirs.splice(0)) rmSync(d, { recursive: true, force: true });
});

describe('gen-changelog', () => {
  it('fails on empty history and writes nothing', () => {
    const dir = tempRepo();
    const out = join(dir, 'changelog.json');
    const r = run(dir, out);
    expect(r.status).toBe(1);
    expect(r.stderr).toMatch(/empty or unavailable/);
    expect(existsSync(out)).toBe(false);
  });

  it('fails when no commit is user facing', () => {
    const dir = tempRepo();
    commit(dir, 'chore: initial');
    const r = run(dir, join(dir, 'changelog.json'));
    expect(r.status).toBe(1);
    expect(r.stderr).toMatch(/no feat, perf or fix entries/);
  });

  it('keeps feat, perf and fix, strips references and prefers a Changelog line', () => {
    const dir = tempRepo();
    commit(dir, 'feat(ui): add bulk export (#12)', '2026-10-01T09:00:00Z');
    commit(dir, 'chore: bump dependencies', '2026-10-01T10:00:00Z');
    commit(dir, 'fix: handle empty rows, see https://example.invalid/x and 1a2b3c4d', '2026-10-02T09:00:00Z');
    commit(dir, 'perf(search): speed up filtering\n\nChangelog: Search results appear twice as fast', '2026-10-02T10:00:00Z');
    commit(dir, 'feat: internal flag\n\nChangelog: skip', '2026-10-02T11:00:00Z');
    const out = join(dir, 'changelog.json');
    const r = run(dir, out, '--version', '1.4.0');
    expect(r.status, r.stderr).toBe(0);
    const data = JSON.parse(readFileSync(out, 'utf8')) as { version: string; date: string; title: string; items: { type: string; title: string }[] }[];
    expect(data).toHaveLength(2);
    expect(data[0]).toMatchObject({ version: '1.4.0', date: '2026-10-02', title: '1 improved, 1 fixed' });
    expect(data[0]?.items).toEqual([
      { type: 'improved', title: 'Search results appear twice as fast' },
      { type: 'fixed', title: 'Handle empty rows, see and' },
    ]);
    expect(data[1]).toMatchObject({ version: '2026.10.01', items: [{ type: 'new', title: 'Add bulk export' }] });
  });

  it('groups by semver tags when the history has them', () => {
    const dir = tempRepo();
    commit(dir, 'feat: first feature', '2026-09-01T09:00:00Z');
    git(dir, ['tag', 'v1.0.0']);
    commit(dir, 'fix: a later fix', '2026-09-03T09:00:00Z');
    const out = join(dir, 'changelog.json');
    expect(run(dir, out, '--version', '1.0.1').status).toBe(0);
    const data = JSON.parse(readFileSync(out, 'utf8')) as { version: string }[];
    expect(data.map((d) => d.version)).toEqual(['1.0.1', '1.0.0']);
  });

  it('keeps a shipped file when git is unavailable', () => {
    const dir = mkdtempSync(join(tmpdir(), 'kit-changelog-nogit-'));
    dirs.push(dir);
    const out = join(dir, 'changelog.json');
    writeFileSync(out, JSON.stringify([{ version: '1.0.0', date: '2026-09-01', title: '1 new', items: [{ type: 'new', title: 'X' }] }]));
    const r = run(dir, out);
    expect(r.status, r.stderr).toBe(0);
    expect(r.stdout).toMatch(/Keeping 1 release/);
  });

  it('reads only the commits that touch --path folders', () => {
    const dir = tempRepo();
    commitFile(dir, 'apps/console/a.txt', 'feat: console search', '2026-10-01T09:00:00Z');
    commitFile(dir, 'apps/other/b.txt', 'feat: other app export', '2026-10-01T10:00:00Z');
    commitFile(dir, 'libs/c.txt', 'fix: shared parser', '2026-10-01T11:00:00Z');
    const out = join(dir, 'changelog.json');
    const r = run(dir, out, '--version', '2.0.0', '--path', 'apps/console', '--path', 'libs');
    expect(r.status, r.stderr).toBe(0);
    const data = JSON.parse(readFileSync(out, 'utf8')) as { items: { title: string }[] }[];
    expect(data.flatMap((d) => d.items.map((i) => i.title)).sort()).toEqual(['Console search', 'Shared parser']);
    expect(r.stdout).toMatch(/touching apps\/console, libs/);
  });

  it('fails on a --path no commit touches, unless --allow-empty', () => {
    const dir = tempRepo();
    commitFile(dir, 'apps/other/b.txt', 'feat: other app export');
    const out = join(dir, 'changelog.json');
    const r = run(dir, out, '--path', 'apps/console');
    expect(r.status).toBe(1);
    expect(r.stderr).toMatch(/empty touching apps\/console/);
    expect(existsSync(out)).toBe(false);
    const ok = run(dir, out, '--path', 'apps/console', '--allow-empty');
    expect(ok.status, ok.stderr).toBe(0);
    expect(JSON.parse(readFileSync(out, 'utf8'))).toEqual([]);
  });

  it('writes an empty What\'s new for a history without conventional commits under --allow-empty', () => {
    const dir = tempRepo();
    commit(dir, 'Sync from upstream');
    const out = join(dir, 'changelog.json');
    const r = run(dir, out, '--allow-empty');
    expect(r.status, r.stderr).toBe(0);
    expect(r.stdout).toMatch(/compile check only/);
    expect(JSON.parse(readFileSync(out, 'utf8'))).toEqual([]);
  });

  it('writes an empty file without git history when CHANGELOG_ALLOW_EMPTY=1', () => {
    const dir = mkdtempSync(join(tmpdir(), 'kit-changelog-nogit-'));
    dirs.push(dir);
    const out = join(dir, 'gen', 'changelog.json');
    expect(run(dir, out).status).toBe(1);
    const r = runEnv({ CHANGELOG_ALLOW_EMPTY: '1' }, dir, out);
    expect(r.status, r.stderr).toBe(0);
    expect(JSON.parse(readFileSync(out, 'utf8'))).toEqual([]);
  });

  it('still keeps a shipped file over an empty one under --allow-empty', () => {
    const dir = mkdtempSync(join(tmpdir(), 'kit-changelog-nogit-'));
    dirs.push(dir);
    const out = join(dir, 'changelog.json');
    writeFileSync(out, JSON.stringify([{ version: '1.0.0', date: '2026-09-01', title: '1 new', items: [{ type: 'new', title: 'X' }] }]));
    const r = run(dir, out, '--allow-empty');
    expect(r.status, r.stderr).toBe(0);
    expect(r.stdout).toMatch(/Keeping 1 release/);
  });

  it('rejects missing arguments', () => {
    const r = spawnSync(process.execPath, [SCRIPT], { encoding: 'utf8' });
    expect(r.status).toBe(2);
  });
});
