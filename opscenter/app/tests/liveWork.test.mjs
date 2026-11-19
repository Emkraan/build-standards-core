import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { liveBuilds, liveCount, liveMode, liveRows, liveSessions } from '../src/lib/liveWork.ts'

const NOW = 1_800_000_000
const iso = (s) => new Date(s * 1000).toISOString()
const sess = (over = {}) => ({ title: 'Fix it', session: 's', pid: 1, state: 'running', started: iso(NOW - 600), log: '', live: true, ...over })
const build = (id, state, over = {}) => ({ id, title: id, state, started: NOW - 900, finished: null, activity: null, activity_at: null, outcome: null, url: null, kind: null, ...over })
const feed = (builds, over = {}) => ({ configured: true, fetched_utc: 'x', counts: { running: 0, stuck: 0, failed: 0, finished: 0, total: builds.length }, builds, truncated: 0, error: null, ...over })

test('only a session that is opening or running and marked live is acting', () => {
  const rows = liveSessions({
    a: sess({ title: 'running' }),
    b: sess({ title: 'opening', state: 'launching' }),
    c: sess({ title: 'claimed', state: 'claimed' }),
    d: sess({ title: 'finished', state: 'finished' }),
    e: sess({ title: 'failed', state: 'failed' }),
    f: sess({ title: 'resolved', state: 'resolved' }),
    g: sess({ title: 'archived', archived: true }),
    h: sess({ title: 'not live', live: false }),
  })
  assert.deepEqual(rows.map((r) => r.title).sort(), ['claimed', 'opening', 'running'])
})

test('a claimed session reads as launching, never as running before it is', () => {
  const [r] = liveSessions({ a: sess({ state: 'claimed' }) })
  assert.equal(r.state, 'launching')
})

test('a session carries its ticket and takes its last activity before its start', () => {
  const [r] = liveSessions({ a: sess({ ticket: 'ITEA-1', started: iso(NOW - 900), last_active: iso(NOW - 60) }) })
  assert.equal(r.ticket, 'ITEA-1')
  assert.equal(r.since, NOW - 60)
  assert.equal(liveSessions({ a: sess({ started: 'not a date', last_active: undefined }) })[0].since, null, 'a bad time is no time, not a made up one')
})

test('running and stuck builds are acting, failed and finished ones are not', () => {
  const rows = liveBuilds(feed([build('r', 'running'), build('s', 'stuck'), build('f', 'failed'), build('d', 'finished'), build('p', 'paused')]))
  assert.deepEqual(rows.map((r) => r.id).sort(), ['build:r', 'build:s'])
})

test('a build source that is off, unreadable or failed contributes nothing and never throws', () => {
  assert.deepEqual(liveBuilds(null), [])
  assert.deepEqual(liveBuilds(undefined), [])
  assert.deepEqual(liveBuilds({ configured: false }), [])
  assert.deepEqual(liveBuilds(feed([build('r', 'running')], { error: 'the source failed' })), [])
})

test('only http and https become links on a build', () => {
  const rows = liveBuilds(feed([build('a', 'running', { url: 'https://x.test/a' }), build('b', 'running', { url: 'javascript:alert(1)' }), build('c', 'running', { url: 'file:///etc/passwd' })]))
  assert.deepEqual(rows.map((r) => r.url), ['https://x.test/a', null, null])
})

test('stuck first, then most recent sign of life, a row with no time last, ties keep their order', () => {
  const rows = liveRows(
    { a: sess({ title: 'old session', last_active: iso(NOW - 3000) }), b: sess({ title: 'new session', last_active: iso(NOW - 30) }) },
    feed([build('quiet', 'running', { activity_at: null, started: NOW - 5000 }), build('stuck', 'stuck', { activity_at: NOW - 9000 }), build('fresh', 'running', { activity_at: NOW - 10 })]),
  )
  assert.deepEqual(rows.map((r) => r.title), ['stuck', 'fresh', 'new session', 'old session', 'quiet'])
})

test('ordering never changes the lists it was given', () => {
  const sessions = { a: sess() }
  const f = feed([build('x', 'stuck'), build('y', 'running')])
  const before = JSON.stringify([sessions, f])
  liveRows(sessions, f)
  assert.equal(JSON.stringify([sessions, f]), before)
})

test('the tab is loading until both sources have answered, and a builds provider that is off still counts as answered', () => {
  assert.equal(liveMode(null, null, false), 'loading')
  assert.equal(liveMode({}, null, false), 'loading', 'sessions loaded but builds not yet')
  assert.equal(liveMode(null, { configured: false }, true), 'loading', 'builds answered but sessions not yet')
  assert.equal(liveMode({}, { configured: false }, true), 'quiet')
})

test('a failed builds source is an error and never a calm board, even with sessions acting', () => {
  assert.equal(liveMode({}, feed([], { error: 'down' }), true), 'error')
  assert.equal(liveMode({ a: sess() }, feed([], { error: 'down' }), true), 'error')
})

test('something acting lists, nothing acting is quiet, and the count matches the rows', () => {
  assert.equal(liveMode({ a: sess() }, { configured: false }, true), 'list')
  assert.equal(liveMode({}, feed([build('r', 'running')]), true), 'list')
  assert.equal(liveMode({}, feed([build('f', 'finished')]), true), 'quiet')
  assert.equal(liveCount({ a: sess(), b: sess({ state: 'finished' }) }, feed([build('r', 'running'), build('f', 'failed')])), 2)
  assert.equal(liveCount({}, null), 0)
})

// The tab reads and links. Stopping a session or a build is a side effect with its own design (standards/automation-safety.md).
test('the Live tab has no write path: no post function, no fetch, no button', () => {
  for (const f of ['../src/lib/liveWork.ts', '../src/components/LiveWork.tsx']) {
    let src
    try {
      src = readFileSync(new URL(f, import.meta.url), 'utf8').replace(/\/\/.*$/gm, '')
    } catch {
      assert.fail(`${f} does not exist yet`)
    }
    assert.equal(/\bpost[A-Z]\w*/.test(src), false, `${f} must not call a post function`)
    assert.equal(/fetch\(|method:\s*'(POST|DELETE|PUT)'/.test(src), false, `${f} must not send a request`)
    assert.equal(/<button\b|<Button\b/.test(src), false, `${f} must not draw a button`)
  }
})
