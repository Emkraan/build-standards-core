#!/usr/bin/env node
/*
 * What's new data for the Ops Center build card (web-ui.md sections 22 and 25).
 *
 * The core generator (scripts/gen-changelog.mjs, synced, never edited) reads the whole repository
 * log. The Ops Center lives inside a larger repository, so this wrapper reads only the commits that
 * touch the app folder and hands them to the core parser (feat = New, perf = Improved, fix = Fixed,
 * a "Changelog:" body line replaces the subject).
 *
 * Usage: node tools/gen-changelog.mjs [--out src/generated/changelog.json]
 * Exit codes: 0 written or kept, 1 no usable history and no earlier file.
 *
 * CHANGELOG_ALLOW_EMPTY=1 is for builds that only prove the app compiles (a CI job in a mirror or
 * backup repository whose history is sync commits, or a shallow checkout). It writes an empty
 * What's new with a notice instead of failing. Never set it for the live build.
 */
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { buildReleases } from '../scripts/gen-changelog.mjs'

const FIELD = '\u001f'
const RECORD = '\u001e'
const app = resolve(dirname(fileURLToPath(import.meta.url)), '..')

const argOut = process.argv.indexOf('--out')
const out = resolve(app, argOut > 0 ? process.argv[argOut + 1] : 'src/generated/changelog.json')
const version = JSON.parse(readFileSync(resolve(app, 'package.json'), 'utf8')).version || ''

const allowEmpty = process.env.CHANGELOG_ALLOW_EMPTY === '1'

function emptyAllowed(why) {
  if (!allowEmpty) return false
  if (!existsSync(dirname(out))) mkdirSync(dirname(out), { recursive: true })
  writeFileSync(out, '[]\n')
  console.log(`gen-changelog: ${why}. CHANGELOG_ALLOW_EMPTY=1, so wrote an empty What's new (compile check only).`)
  return true
}

function existing() {
  try {
    const data = JSON.parse(readFileSync(out, 'utf8'))
    return Array.isArray(data) ? data : []
  } catch {
    return []
  }
}

function readCommits() {
  const raw = execFileSync(
    'git',
    ['-C', app, 'log', '--no-merges', '--date-order', `--format=%H${FIELD}%cs${FIELD}%D${FIELD}%s${FIELD}%b${RECORD}`, '--', '.'],
    { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], maxBuffer: 64 * 1024 * 1024 },
  )
  return raw
    .split(RECORD)
    .map((r) => r.replace(/^\n+/, ''))
    .filter((r) => r.trim())
    .map((r) => {
      const [hash = '', date = '', refs = '', subject = '', body = ''] = r.split(FIELD)
      const tags = refs
        .split(',')
        .map((x) => x.trim())
        .filter((x) => x.startsWith('tag: '))
        .map((x) => x.slice(5))
      return { hash, date, tags, subject, body }
    })
}

let commits = []
try {
  commits = readCommits()
} catch (e) {
  const keep = existing()
  if (keep.length > 0) {
    console.log(`gen-changelog: git history unavailable, keeping ${keep.length} release(s) in ${out}`)
    process.exit(0)
  }
  if (emptyAllowed('git history unavailable')) process.exit(0)
  console.error(`gen-changelog: git history unavailable and no earlier file (${String(e.message || e).split('\n')[0]})`)
  process.exit(1)
}
const releases = buildReleases(commits, { version, maxReleases: 10, maxItems: 12 })
if (releases.length === 0) {
  const keep = existing()
  if (keep.length > 0) {
    console.log(`gen-changelog: no feat, perf or fix commits in the app history, keeping ${keep.length} release(s)`)
    process.exit(0)
  }
  if (emptyAllowed(`${commits.length} app commit(s) but no feat, perf or fix entries`)) process.exit(0)
  console.error(`gen-changelog: ${commits.length} app commit(s) but no feat, perf or fix entries. Refusing to ship an empty What's new.`)
  process.exit(1)
}
if (!existsSync(dirname(out))) mkdirSync(dirname(out), { recursive: true })
writeFileSync(out, `${JSON.stringify(releases, null, 2)}\n`)
console.log(`gen-changelog: wrote ${releases.length} release(s) from ${commits.length} app commit(s) to ${out}`)
