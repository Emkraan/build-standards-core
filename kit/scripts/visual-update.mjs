#!/usr/bin/env node
/*
 * visual-update.mjs: refreshes the visual gate baselines (kit/visual/baselines/linux).
 *
 * Usage (from kit/):
 *   npm run visual:update                 # default: regenerate in CI and download the result
 *   npm run visual:update -- --docker     # regenerate locally in the pinned Playwright image
 *   npm run visual:update -- --local      # regenerate on this machine (linux only, as CI does)
 *
 * CI is the source of truth. The default mode dispatches the visual workflow on the current
 * branch with update-baselines on, waits for it, and replaces the linux baselines with the
 * visual-baselines artifact. Push the branch first. Review the new images, then commit them by
 * name. --docker runs the same image as CI (amd64, so it is slow under emulation on arm64 hosts).
 * Baselines made on macOS or Windows land in their own folder and are never committed.
 *
 * Exit codes: 0 baselines written, 1 a step failed, 2 bad arguments.
 */
import { execFileSync, spawnSync } from 'node:child_process';
import { existsSync, readFileSync, rmSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const kitDir = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const baselineDir = resolve(kitDir, 'visual/baselines/linux');
const WORKFLOW = 'visual.yml';
const ARTIFACT = 'visual-baselines';

function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, { stdio: 'inherit', cwd: kitDir, ...opts });
  if (r.status !== 0) {
    console.error(`visual-update: ${cmd} ${args.join(' ')} failed (exit ${r.status ?? 'signal'})`);
    process.exit(1);
  }
}

function out(cmd, args) {
  return execFileSync(cmd, args, { cwd: kitDir, encoding: 'utf8' }).trim();
}

function playwrightVersion() {
  const pkg = JSON.parse(readFileSync(resolve(kitDir, 'node_modules/@playwright/test/package.json'), 'utf8'));
  return pkg.version;
}

function local() {
  if (process.platform !== 'linux') {
    console.error('visual-update: --local only makes committed baselines on linux. Use the default (CI) or --docker.');
    process.exit(2);
  }
  run('npm', ['run', 'gallery:build']);
  run('npx', ['playwright', 'test', '--update-snapshots']);
}

function docker() {
  if (!existsSync(resolve(kitDir, 'node_modules/@playwright/test'))) {
    console.error('visual-update: run npm ci first so the Playwright version can be read.');
    process.exit(1);
  }
  const image = `mcr.microsoft.com/playwright:v${playwrightVersion()}-noble`;
  const repoDir = resolve(kitDir, '..');
  // node_modules lives in a named volume so the host install (other OS binaries) is not used.
  run('docker', [
    'run', '--rm', '--platform', 'linux/amd64', '--ipc=host',
    '-v', `${repoDir}:/repo`, '-v', 'bsc-kit-visual-node-modules:/repo/kit/node_modules',
    '-w', '/repo/kit', '-e', 'CI=1', image,
    'bash', '-lc', 'git config --global --add safe.directory "*" && npm ci && npm run gallery:build && npx playwright test --update-snapshots',
  ]);
}

function fromCi() {
  const branch = out('git', ['rev-parse', '--abbrev-ref', 'HEAD']);
  const head = out('git', ['rev-parse', 'HEAD']);
  const remote = out('git', ['ls-remote', 'origin', `refs/heads/${branch}`]).split(/\s+/)[0] ?? '';
  if (remote !== head) {
    console.error(`visual-update: push ${branch} first (origin has ${remote || 'nothing'}, local is ${head}).`);
    process.exit(1);
  }
  const started = new Date();
  run('gh', ['workflow', 'run', WORKFLOW, '--ref', branch, '-f', 'update-baselines=true']);
  let id = '';
  for (let i = 0; i < 30 && !id; i += 1) {
    spawnSync('sleep', ['5']);
    const runs = JSON.parse(
      out('gh', ['run', 'list', '--workflow', WORKFLOW, '--branch', branch, '--event', 'workflow_dispatch', '--limit', '5', '--json', 'databaseId,createdAt,headSha']),
    );
    const match = runs.find((r) => r.headSha === head && new Date(r.createdAt) >= new Date(started.getTime() - 60_000));
    if (match) id = String(match.databaseId);
  }
  if (!id) {
    console.error('visual-update: the dispatched run did not show up. Check gh run list --workflow visual.yml.');
    process.exit(1);
  }
  console.log(`visual-update: waiting for run ${id}`);
  run('gh', ['run', 'watch', id, '--exit-status']);
  rmSync(baselineDir, { recursive: true, force: true });
  run('gh', ['run', 'download', id, '-n', ARTIFACT, '-D', baselineDir]);
  console.log(`visual-update: baselines replaced from run ${id}. Review git status, then commit them by name.`);
}

const args = process.argv.slice(2);
const mode = args[0] ?? '--ci';
if (args.length > 1 || !['--ci', '--docker', '--local'].includes(mode)) {
  console.error('usage: node scripts/visual-update.mjs [--ci | --docker | --local]');
  process.exit(2);
}
if (mode === '--local') local();
else if (mode === '--docker') docker();
else fromCi();
