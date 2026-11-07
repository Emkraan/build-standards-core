#!/usr/bin/env node
/*
 * visual-update.mjs: refreshes the visual gate baselines (kit/visual/baselines/linux).
 *
 * Usage (from kit/):
 *   npm run visual:update                 # default: regenerate in CI and download the result
 *   npm run visual:update -- --docker     # regenerate locally in the pinned Playwright image
 *   npm run visual:update -- --local      # regenerate on this machine (linux only, as CI does)
 *
 * A consumer refreshes its own baselines, against the kit it syncs, with the same script and the
 * options below (run from anywhere inside the consumer repo; paths are relative to --root):
 *   node kit/scripts/visual-update.mjs --docker --root apps/site/visual \
 *     --baselines baselines/linux --build "npm run build"
 *   --root <dir>        the project that holds the Playwright config and the committed baselines
 *   --baselines <path>  the baseline folder inside --root (default visual/baselines/linux)
 *   --build <command>   run before the screenshots (default: the gallery build for the kit itself,
 *                       nothing for another root)
 *   --workflow <file>   the repo's visual workflow for the default mode (default visual.yml)
 *   --artifact <name>   the baselines artifact that workflow uploads (default visual-baselines)
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
import { createHash } from 'node:crypto';
import { dirname, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const kitDir = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const DEFAULTS = Object.freeze({
  mode: '--ci',
  root: kitDir,
  baselines: 'visual/baselines/linux',
  build: null,
  workflow: 'visual.yml',
  artifact: 'visual-baselines',
});
const VALUE_OPTIONS = { '--root': 'root', '--baselines': 'baselines', '--build': 'build', '--workflow': 'workflow', '--artifact': 'artifact' };

/**
 * Read the arguments into settings. Throws a usage error on anything it does not know, so a typo
 * never starts a CI run or a docker container. The kit's own run (no options) keeps its gallery build.
 * @param {string[]} argv
 */
export function parseArgs(argv) {
  const o = { ...DEFAULTS };
  let custom = false;
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--ci' || a === '--docker' || a === '--local') o.mode = a;
    else if (a !== undefined && a in VALUE_OPTIONS) {
      const v = argv[i + 1];
      if (v === undefined || v.startsWith('--')) throw new Error(`${a} needs a value`);
      o[VALUE_OPTIONS[a]] = v;
      if (a === '--root') custom = true;
      i += 1;
    } else throw new Error(`unknown argument ${a}`);
  }
  o.root = resolve(o.root);
  if (o.build === null && !custom) o.build = 'npm run gallery:build';
  return o;
}

/**
 * The docker run for a settings object: the pinned Playwright image of the root's own install, the
 * repository mounted, and node_modules in a named volume so the host install (other OS binaries) is never used.
 * @param {ReturnType<typeof parseArgs>} o @param {{ version: string, repoDir: string }} env
 */
export function dockerArgs(o, env) {
  const rel = relative(env.repoDir, o.root).split('\\').join('/');
  const work = rel ? `/repo/${rel}` : '/repo';
  const volume = o.root === kitDir ? 'bsc-kit-visual-node-modules' : `bsc-visual-node-modules-${createHash('sha256').update(o.root).digest('hex').slice(0, 8)}`;
  const steps = ['git config --global --add safe.directory "*"', 'npm ci', ...(o.build ? [o.build] : []), 'npx playwright test --update-snapshots'];
  return [
    'run', '--rm', '--platform', 'linux/amd64', '--ipc=host',
    '-v', `${env.repoDir}:/repo`, '-v', `${volume}:${work}/node_modules`,
    '-w', work, '-e', 'CI=1', `mcr.microsoft.com/playwright:v${env.version}-noble`,
    'bash', '-lc', steps.join(' && '),
  ];
}

/** The settings of the run in progress (set by main). */
let S = { ...DEFAULTS };
let ROOT = kitDir;

function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, { stdio: 'inherit', cwd: ROOT, ...opts });
  if (r.status !== 0) {
    console.error(`visual-update: ${cmd} ${args.join(' ')} failed (exit ${r.status ?? 'signal'})`);
    process.exit(1);
  }
}

function out(cmd, args) {
  return execFileSync(cmd, args, { cwd: ROOT, encoding: 'utf8' }).trim();
}

function playwrightVersion() {
  const pkg = JSON.parse(readFileSync(resolve(ROOT, 'node_modules/@playwright/test/package.json'), 'utf8'));
  return pkg.version;
}

function local() {
  if (process.platform !== 'linux') {
    console.error('visual-update: --local only makes committed baselines on linux. Use the default (CI) or --docker.');
    process.exit(2);
  }
  if (S.build) run('bash', ['-lc', S.build]);
  run('npx', ['playwright', 'test', '--update-snapshots']);
}

function docker() {
  if (!existsSync(resolve(ROOT, 'node_modules/@playwright/test'))) {
    console.error('visual-update: run npm ci first so the Playwright version can be read.');
    process.exit(1);
  }
  const repoDir = out('git', ['rev-parse', '--show-toplevel']);
  run('docker', dockerArgs(S, { version: playwrightVersion(), repoDir }));
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
  run('gh', ['workflow', 'run', S.workflow, '--ref', branch, '-f', 'update-baselines=true']);
  let id = '';
  for (let i = 0; i < 30 && !id; i += 1) {
    spawnSync('sleep', ['5']);
    const runs = JSON.parse(
      out('gh', ['run', 'list', '--workflow', S.workflow, '--branch', branch, '--event', 'workflow_dispatch', '--limit', '5', '--json', 'databaseId,createdAt,headSha']),
    );
    const match = runs.find((r) => r.headSha === head && new Date(r.createdAt) >= new Date(started.getTime() - 60_000));
    if (match) id = String(match.databaseId);
  }
  if (!id) {
    console.error(`visual-update: the dispatched run did not show up. Check gh run list --workflow ${S.workflow}.`);
    process.exit(1);
  }
  console.log(`visual-update: waiting for run ${id}`);
  run('gh', ['run', 'watch', id, '--exit-status']);
    rmSync(baselineDir, { recursive: true, force: true });
  run('gh', ['run', 'download', id, '-n', S.artifact, '-D', baselineDir]);
  console.log(`visual-update: baselines replaced from run ${id}. Review git status, then commit them by name.`);
}

function main(argv) {
  try {
    S = parseArgs(argv);
  } catch (e) {
    console.error(`visual-update: ${e.message}`);
    console.error('usage: node scripts/visual-update.mjs [--ci | --docker | --local] [--root <dir>] [--baselines <path>] [--build <command>] [--workflow <file>] [--artifact <name>]');
    process.exit(2);
  }
  ROOT = S.root;
  if (S.mode === '--local') local();
  else if (S.mode === '--docker') docker();
  else fromCi();
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main(process.argv.slice(2));
