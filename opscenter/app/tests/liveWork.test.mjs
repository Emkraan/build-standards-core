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
  const [r] = liveSessions({ a: sess({ ticket: 'WORK-1', started: iso(NOW - 900), last_active: iso(NOW - 60) }) })
  assert.equal(r.ticket, 'WORK-1')
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

test('the Work by state control files every row under needs me, running, waiting, stuck or just finished', async () => {
  const { liveByState, firstLiveState, LIVE_STATES } = await import('../src/lib/liveWork.ts')
  const b = (id, state) => ({ id, title: id, state, started: 1000, activity_at: null, finished: state === 'finished' || state === 'failed' ? 2000 : null, url: null, kind: null, outcome: null, activity: null })
  const feed = { configured: true, fetched_utc: 'x', counts: {}, builds: [b('r', 'running'), b('s', 'stuck'), b('f', 'failed'), b('d', 'finished')], truncated: 0, error: null }
  const sessions = { fp1: { state: 'launching', live: true, title: 'Opening one', started: '2026-11-21T00:00:00Z' }, fp2: { state: 'running', live: true, title: 'Running one', started: '2026-11-21T00:00:00Z' } }
  const by = liveByState(sessions, feed)
  assert.deepEqual(LIVE_STATES, ['needs', 'running', 'waiting', 'stuck', 'finished'])
  assert.deepEqual(by.needs.map((r) => r.id), ['build:f'])
  assert.deepEqual(by.running.map((r) => r.id).sort(), ['build:r', 'session:fp2'])
  assert.deepEqual(by.waiting.map((r) => r.id), ['session:fp1'])
  assert.deepEqual(by.stuck.map((r) => r.id), ['build:s'])
  assert.deepEqual(by.finished.map((r) => r.id), ['build:d'])
  assert.equal(firstLiveState(by), 'needs')
  assert.equal(firstLiveState({ needs: [], running: [], waiting: [], stuck: [], finished: [] }), 'running')
})

test('a failed builds source files nothing, so a broken feed never reads as calm', async () => {
  const { liveByState } = await import('../src/lib/liveWork.ts')
  const feed = { configured: true, fetched_utc: 'x', counts: {}, builds: [{ id: 'f', title: 'f', state: 'failed' }], truncated: 0, error: 'boom' }
  assert.equal(liveByState({}, feed).needs.length, 0)
})

test('the lanes the rows name feed the Lane select, and a lane keeps its rows in the Engineer PRs, Scheduled jobs and Sessions sections', async () => {
  const { liveByState, liveLanes, liveSections } = await import('../src/lib/liveWork.ts')
  const b = (id, lane, pr) => ({ id, title: id, state: 'running', started: 1000, activity_at: null, finished: null, url: null, kind: null, outcome: null, activity: null, lane, pr: pr ? { number: 1, url: null, state: 'open', red: 0 } : null })
  const feed = { configured: true, fetched_utc: 'x', counts: {}, builds: [b('a', 'infra', true), b('c', 'infra', false), b('d', 'apps', true), b('e', null, false)], truncated: 0, error: null }
  const sessions = { fp: { state: 'running', live: true, title: 'S', started: '2026-11-21T00:00:00Z' } }
  const rows = liveByState(sessions, feed).running
  assert.deepEqual(liveLanes(rows), ['apps', 'infra'])
  const all = liveSections(rows, '')
  assert.deepEqual([all.prs.length, all.jobs.length, all.sessions.length], [2, 2, 1])
  const infra = liveSections(rows, 'infra')
  assert.deepEqual([infra.prs.map((r) => r.id), infra.jobs.map((r) => r.id), infra.sessions.length], [['build:a'], ['build:c'], 0])
  assert.deepEqual(liveLanes(liveByState({}, { ...feed, builds: [b('e', null, false)] }).running), [])
})

test('a session row carries its newest progress report as a note, and none when it has not reported', async () => {
  const { liveSessions } = await import('../src/lib/liveWork.ts')
  const s = (reports) => ({ fp: { state: 'running', live: true, title: 'S', started: '2026-11-21T00:00:00Z', reports } })
  assert.equal(liveSessions(s([{ at: 'a', text: 'halfway' }, { at: 'b', text: 'older' }]))[0].note, 'halfway')
  assert.equal(liveSessions(s(undefined))[0].note, null)
  assert.equal(liveSessions(s([]))[0].note, null)
})
