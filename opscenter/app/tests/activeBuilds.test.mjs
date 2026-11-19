import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { ageText, orderedBuilds, panelMode, rowAge, safeLink, stateWord, summaryLine } from '../src/lib/activeBuilds.ts'

const NOW = 1_800_000_000
const b = (id, state, over = {}) => ({ id, title: id, state, started: NOW - 100, finished: null, activity: null, activity_at: null, outcome: null, url: null, kind: null, ...over })
const feed = (counts, over = {}) => ({ configured: true, fetched_utc: 'x', counts: { running: 0, stuck: 0, failed: 0, finished: 0, total: 0, ...counts }, builds: [], truncated: 0, error: null, ...over })

test('no provider hides the panel, and so does a state that has not loaded yet', () => {
  assert.equal(panelMode({ configured: false }), 'hidden')
  assert.equal(panelMode(null), 'hidden')
  assert.equal(panelMode(undefined), 'hidden')
})

test('a failed source is an error and never reads as a calm board, even when it also reports zero counts', () => {
  assert.equal(panelMode(feed({}, { error: 'the source failed (OSError)' })), 'error')
  assert.equal(panelMode(feed({ running: 3 }, { error: 'x' })), 'error')
})

test('anything running, stuck or failed lists, nothing live is quiet, and finished history alone does not earn a panel', () => {
  assert.equal(panelMode(feed({ running: 1 })), 'list')
  assert.equal(panelMode(feed({ stuck: 1 })), 'list')
  assert.equal(panelMode(feed({ failed: 1 })), 'list')
  assert.equal(panelMode(feed({})), 'quiet')
  assert.equal(panelMode(feed({ finished: 9, total: 9 })), 'quiet')
})

test('an unknown state is shown as the provider sent it and is never called running', () => {
  assert.equal(stateWord('running'), 'Running')
  assert.equal(stateWord('paused'), 'Paused')
  assert.equal(stateWord(''), 'Unknown')
  assert.notEqual(stateWord('paused'), 'Running')
})

test('stuck first, then failed, then running, then finished, then anything unknown, each group keeping the feed order', () => {
  const rows = [b('f1', 'finished'), b('r1', 'running'), b('u1', 'paused'), b('s1', 'stuck'), b('x1', 'failed'), b('r2', 'running'), b('s2', 'stuck')]
  assert.deepEqual(orderedBuilds(rows).map((x) => x.id), ['s1', 's2', 'x1', 'r1', 'r2', 'f1', 'u1'])
})

test('ordering does not change the list it was given', () => {
  const rows = [b('f1', 'finished'), b('s1', 'stuck')]
  orderedBuilds(rows)
  assert.deepEqual(rows.map((x) => x.id), ['f1', 's1'])
})

test('ages read in the largest sensible unit, and a missing time gives nothing rather than a made up age', () => {
  assert.equal(ageText(null, NOW), '')
  assert.equal(ageText(NOW - 20, NOW), 'just now')
  assert.equal(ageText(NOW - 600, NOW), '10 min ago')
  assert.equal(ageText(NOW - 7200, NOW), '2 h ago')
  assert.equal(ageText(NOW - 86400 * 3, NOW), '3 d ago')
  assert.equal(ageText(NOW + 500, NOW), 'just now', 'a clock a little ahead is not a negative age')
})

test('a running or stuck row is aged by its last output, a finished or failed one by when it ended', () => {
  assert.equal(rowAge(b('a', 'stuck', { started: NOW - 9000, activity_at: NOW - 3600 }), NOW), '1 h ago')
  assert.equal(rowAge(b('a', 'running', { started: NOW - 600 }), NOW), '10 min ago', 'no output yet falls back to the start')
  assert.equal(rowAge(b('a', 'finished', { started: NOW - 9000, finished: NOW - 120, activity_at: NOW - 5000 }), NOW), '2 min ago')
  assert.equal(rowAge(b('a', 'failed', { started: NOW - 9000, finished: null, activity_at: NOW - 300 }), NOW), '5 min ago')
})

test('the summary line leaves out zeros and is empty on a calm board', () => {
  assert.equal(summaryLine({ running: 2, stuck: 1, failed: 0, finished: 5, total: 8 }), '1 stuck, 2 running')
  assert.equal(summaryLine({ running: 0, stuck: 0, failed: 1, finished: 0, total: 1 }), '1 failed')
  assert.equal(summaryLine({ running: 0, stuck: 0, failed: 0, finished: 5, total: 5 }), '')
})

test('only http and https become links', () => {
  assert.equal(safeLink('https://x.test/a'), 'https://x.test/a')
  assert.equal(safeLink('http://x.test/a'), 'http://x.test/a')
  for (const bad of ['javascript:alert(1)', 'data:text/html,x', 'file:///etc/passwd', '//x.test', 'HTTPS://x.test', '', null]) {
    assert.equal(safeLink(bad), null, String(bad))
  }
})

// The panel reads and links. A Stop button is a separate decision with its own confirmation (standards/automation-safety.md), so a
// regression that adds a write path here would quietly create it without that design.
test('the panel has no write path: no post function, no fetch, no button', () => {
  for (const f of ['../src/lib/activeBuilds.ts', '../src/components/ActiveBuilds.tsx']) {
    const src = readFileSync(new URL(f, import.meta.url), 'utf8').replace(/\/\/.*$/gm, '')
    assert.equal(/\bpost[A-Z]\w*/.test(src), false, `${f} must not call a post function`)
    assert.equal(/fetch\(|method:\s*'(POST|DELETE|PUT)'/.test(src), false, `${f} must not send a request`)
    assert.equal(/<button\b/.test(src), false, `${f} must not draw a button`)
  }
})
