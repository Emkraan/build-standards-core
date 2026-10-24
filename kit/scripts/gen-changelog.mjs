#!/usr/bin/env node
/*
 * gen-changelog.mjs: builds the What's new data for the BuildCard from git history (web-ui.md
 * sections 22 and 25).
 *
 * Usage:
 *   node kit-core/scripts/gen-changelog.mjs --out src/generated/changelog.json [--version 1.4.0]
 *        [--repo .] [--path apps/console] [--max-releases 10] [--max-items 12] [--allow-empty]
 *
 * Options:
 *   --path <dir>   Only commits that touch this folder (relative to --repo). Repeat for several
 *                  folders. For an app inside a larger repository. Default: the whole log.
 *   --allow-empty  For builds that only prove the app compiles (a CI job in a mirror or backup
 *                  repository whose history has no conventional commits, or a shallow checkout).
 *                  An empty or unusable history writes an empty What's new with a notice instead
 *                  of failing, and an existing file with entries is still kept. Never use it for
 *                  the build you ship. CHANGELOG_ALLOW_EMPTY=1 in the environment does the same.
 *
 * Rules:
 *   feat becomes New, perf Improved, fix Fixed. Every other type is dropped.
 *   PR numbers, commit hashes, links and scopes are stripped from the text.
 *   A "Changelog:" line in the commit body replaces the subject ("Changelog: skip" drops it).
 *   Semver tags (v1.2.0) split the history into releases. Commits after the newest tag belong to
 *   --version (default: the version in package.json). Without tags, each day is one release.
 *
 * Deploy pitfall: a source upload carries no git history. Run this in CI from a full-history
 * checkout (fetch-depth: 0) and ship the file with the app. When git is unavailable and the output
 * file already holds entries, the file is kept. Otherwise the script fails: a build with no history
 * must fail rather than ship a disabled build card.
 *
 * Exit codes: 0 written (or kept), 1 no usable history, 2 bad arguments.
 */
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const TYPES = { feat: 'new', perf: 'improved', fix: 'fixed' };
const LABELS = { new: 'new', improved: 'improved', fixed: 'fixed' };
const FIELD = '\u001f';
const RECORD = '\u001e';

export function parseArgs(argv) {
  const opts = { out: '', version: '', repo: '.', paths: [], maxReleases: 10, maxItems: 12, allowEmpty: false };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    const next = () => {
      i += 1;
      if (i >= argv.length) throw new Error(`${a} needs a value`);
      return argv[i];
    };
    if (a === '--out') opts.out = next();
    else if (a === '--version') opts.version = next();
    else if (a === '--repo') opts.repo = next();
    else if (a === '--path') opts.paths.push(next());
    else if (a === '--max-releases') opts.maxReleases = Number(next());
    else if (a === '--max-items') opts.maxItems = Number(next());
    else if (a === '--allow-empty') opts.allowEmpty = true;
    else throw new Error(`unknown argument ${a}`);
  }
  if (!opts.out) throw new Error('--out is required');
  return opts;
}

/** Removes PR numbers, hashes, links and stray punctuation from a note. */
export function cleanText(text) {
  return text
    .replace(/https?:\/\/\S+/g, '')
    .replace(/\(\s*#\d+\s*\)/g, '')
    .replace(/(^|\s)#\d+\b/g, '$1')
    .replace(/\b(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b/g, '')
    .replace(/\(\s*\)/g, '')
    .replace(/\s{2,}/g, ' ')
    .replace(/\s+([,.;:])/g, '$1')
    .trim()
    .replace(/[\s,;:-]+$/, '')
    .replace(/^./, (c) => c.toUpperCase());
}

/** One commit to one note, or null when the commit is not user facing. */
export function noteFromCommit(subject, body) {
  const m = /^(\w+)(?:\([^)]*\))?(!)?:\s*(.+)$/.exec(subject.trim());
  if (!m) return null;
  const type = TYPES[m[1].toLowerCase()];
  if (!type) return null;
  const line = /^changelog:\s*(.*)$/im.exec(body || '');
  let text = m[3];
  if (line) {
    const value = line[1].trim();
    if (!value || /^(skip|none|-)$/i.test(value)) return null;
    text = value;
  }
  const title = cleanText(text);
  return title ? { type, title } : null;
}

function git(repo, args) {
  return execFileSync('git', ['-C', repo, ...args], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], maxBuffer: 64 * 1024 * 1024 });
}

/** Reads every non-merge commit, newest first, with its tags. With `paths`, only the commits that
    touch one of those folders. Throws when git or history is missing. */
export function readCommits(repo, paths = []) {
  const args = ['log', '--no-merges', '--date-order', `--format=%H${FIELD}%cs${FIELD}%D${FIELD}%s${FIELD}%b${RECORD}`];
  if (paths.length > 0) args.push('--', ...paths);
  const raw = git(repo, args);
  return raw
    .split(RECORD)
    .map((r) => r.replace(/^\n+/, ''))
    .filter((r) => r.trim())
    .map((r) => {
      const [hash = '', date = '', refs = '', subject = '', body = ''] = r.split(FIELD);
      const tags = refs
        .split(',')
        .map((x) => x.trim())
        .filter((x) => x.startsWith('tag: '))
        .map((x) => x.slice(5));
      return { hash, date, tags, subject, body };
    });
}

const SEMVER_TAG = /^v?(\d+\.\d+\.\d+(?:[-+][\w.-]+)?)$/;

function titleFor(items) {
  const counts = { new: 0, improved: 0, fixed: 0 };
  for (const it of items) counts[it.type] += 1;
  return Object.entries(counts)
    .filter(([, n]) => n > 0)
    .map(([type, n]) => `${n} ${LABELS[type]}`)
    .join(', ');
}

/** Groups commits into releases, newest first. */
export function buildReleases(commits, { version = '', maxReleases = 10, maxItems = 12 } = {}) {
  const tagged = commits.some((c) => c.tags.some((t) => SEMVER_TAG.test(t)));
  const groups = [];
  let current = null;
  for (const c of commits) {
    const tag = c.tags.find((t) => SEMVER_TAG.test(t));
    let key;
    if (tagged) key = tag ? tag.replace(/^v/, '') : current ? current.version : version || 'next';
    else key = current && current.date === c.date ? current.version : groups.length === 0 ? version || c.date.replace(/-/g, '.') : c.date.replace(/-/g, '.');
    if (!current || current.version !== key) {
      current = { version: key, date: c.date, items: [] };
      groups.push(current);
    }
    const note = noteFromCommit(c.subject, c.body);
    if (note && !current.items.some((i) => i.title === note.title)) current.items.push(note);
  }
  return groups
    .filter((g) => g.items.length > 0)
    .slice(0, maxReleases)
    .map((g) => {
      const items = g.items.slice(0, maxItems);
      return { version: g.version, date: g.date, title: titleFor(items), items };
    });
}

function readExisting(file) {
  try {
    const data = JSON.parse(readFileSync(file, 'utf8'));
    return Array.isArray(data) ? data : [];
  } catch {
    return [];
  }
}

function packageVersion(repo) {
  for (const dir of [process.cwd(), resolve(repo)]) {
    const f = resolve(dir, 'package.json');
    if (existsSync(f)) {
      try {
        const v = JSON.parse(readFileSync(f, 'utf8')).version;
        if (typeof v === 'string' && v) return v;
      } catch {
        // Not readable. Try the next candidate.
      }
    }
  }
  return '';
}

function writeEmpty(out, opts, why, log) {
  mkdirSync(dirname(out), { recursive: true });
  writeFileSync(out, '[]\n');
  log.log(`gen-changelog: ${why}. --allow-empty is set, so wrote an empty What's new to ${opts.out} (compile check only, never ship it).`);
  return 0;
}

export function main(argv, log = console, env = process.env) {
  let opts;
  try {
    opts = parseArgs(argv);
  } catch (e) {
    log.error(`gen-changelog: ${e.message}`);
    return 2;
  }
  if (env.CHANGELOG_ALLOW_EMPTY === '1') opts.allowEmpty = true;
  const out = resolve(opts.out);
  const scope = opts.paths.length > 0 ? ` touching ${opts.paths.join(', ')}` : '';
  let commits;
  try {
    commits = readCommits(opts.repo, opts.paths);
  } catch (e) {
    const existing = readExisting(out);
    const reason = String(e.stderr || e.message || e).trim().split('\n')[0];
    if (existing.length > 0) {
      log.log(`gen-changelog: git history unavailable (${reason}). Keeping ${existing.length} release(s) in ${opts.out}.`);
      return 0;
    }
    if (opts.allowEmpty) return writeEmpty(out, opts, `git history unavailable (${reason})`, log);
    log.error(`gen-changelog: git history is empty or unavailable (${reason}). Run this in CI from a full-history checkout (fetch-depth: 0) and ship the file with the app.`);
    return 1;
  }
  if (commits.length === 0) {
    if (opts.allowEmpty) return writeEmpty(out, opts, `no commits${scope}`, log);
    log.error(`gen-changelog: git history is empty${scope}. Refusing to write an empty changelog.`);
    return 1;
  }
  try {
    if (git(opts.repo, ['rev-parse', '--is-shallow-repository']).trim() === 'true') {
      log.error('gen-changelog: warning: shallow clone, older releases are missing. Use fetch-depth: 0.');
    }
  } catch {
    // Older git without the flag. Carry on.
  }
  const releases = buildReleases(commits, {
    version: opts.version || packageVersion(opts.repo),
    maxReleases: opts.maxReleases,
    maxItems: opts.maxItems,
  });
  if (releases.length === 0 && !opts.allowEmpty) {
    log.error(`gen-changelog: ${commits.length} commit(s)${scope} but no feat, perf or fix entries. Refusing to ship an empty What's new.`);
    return 1;
  }
  mkdirSync(dirname(out), { recursive: true });
  writeFileSync(out, `${JSON.stringify(releases, null, 2)}\n`);
  if (releases.length === 0) log.log(`gen-changelog: ${commits.length} commit(s)${scope} but no feat, perf or fix entries. --allow-empty is set (compile check only, never ship it).`);
  log.log(`gen-changelog: wrote ${releases.length} release(s) from ${commits.length} commit(s)${scope} to ${opts.out}`);
  return 0;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)));
}
