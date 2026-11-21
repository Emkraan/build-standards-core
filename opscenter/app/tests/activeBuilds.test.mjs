import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { ageText, durationText, orderedBuilds, panelMode, prLine, rowAge, rowNote, safeLink, stateWord, summaryLine } from '../src/lib/activeBuilds.ts'

const NOW = 1_800_000_000
const b = (id, state, over = {}) => ({ id, title: id, state, started: NOW - 100, finished: null, activity: null, activity_at: null, outcome: null, url: null, kind: null, pr: null, ...over })
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

test('a duration reads in the largest sensible unit and a missing or backwards span gives nothing', () => {
  assert.equal(durationText(null, NOW), '')
  assert.equal(durationText(NOW, null), '')
  assert.equal(durationText(NOW - 20, NOW), 'under a minute')
  assert.equal(durationText(NOW - 59 * 60, NOW), 'about 59 minutes')
  assert.equal(durationText(NOW - 60, NOW), 'about 1 minute')
  assert.equal(durationText(NOW - 3 * 3600, NOW), 'about 3 hours')
  assert.equal(durationText(NOW - 90 * 3600, NOW), 'about 4 days')
  assert.equal(durationText(NOW + 60, NOW), '', 'an end before the start is not a duration')
})

test('a stuck row says how long it has been silent and what to do, using the real silence and no fixed number', () => {
  const stuck = b('s', 'stuck', { started: NOW - 9000, activity_at: NOW - 25 * 60 })
  assert.equal(rowNote(stuck, NOW), 'No output for 25 minutes, check the log before waiting longer')
  assert.equal(rowNote(b('s', 'stuck', { started: NOW - 3 * 3600 }), NOW), 'No output for 3 hours, check the log before waiting longer', 'no output at all is judged from the start')
  assert.equal(rowNote(b('s', 'stuck', { started: null, activity_at: null }), NOW), '', 'no time at all gives no claim')
})

test('a finished row says how long it took and how long ago it ended, and only when both times are real', () => {
  const done = b('d', 'finished', { started: NOW - 59 * 60 - 180, finished: NOW - 180 })
  assert.equal(rowNote(done, NOW), 'Took about 59 minutes, finished 3 min ago')
  assert.equal(rowNote(b('d', 'finished', { started: null, finished: NOW - 180 }), NOW), 'Finished 3 min ago', 'no start means no made up duration')
  assert.equal(rowNote(b('d', 'finished', { started: NOW - 600, finished: null }), NOW), '', 'no end time means no claim of when')
})

test('running and failed rows keep the plain note and a failed row never claims a duration it was not given', () => {
  assert.equal(rowNote(b('r', 'running', { activity_at: NOW - 30 }), NOW), '')
  assert.equal(rowNote(b('x', 'failed', { started: NOW - 600, finished: NOW - 60 }), NOW), 'Ran about 9 minutes, failed 1 min ago')
  assert.equal(rowNote(b('x', 'failed', { started: null, finished: NOW - 60 }), NOW), 'Failed 1 min ago')
  assert.equal(rowNote(b('p', 'paused', { started: NOW - 600 }), NOW), '', 'an unknown state gets no invented note')
})

test('a pull request reads as its number and state, with the failing checks only when the source sent a count', () => {
  const pr = (over = {}) => ({ number: 42, url: 'https://x.test/pull/42', state: 'open', red: 1, ...over })
  assert.deepEqual(prLine(null), null)
  assert.equal(prLine(pr()).text, 'Pull request open, 1 red')
  assert.equal(prLine(pr({ red: 3 })).text, 'Pull request open, 3 red')
  assert.equal(prLine(pr({ red: 0 })).text, 'Pull request open, none red')
  assert.equal(prLine(pr({ red: null })).text, 'Pull request open', 'no count is no claim, never none red')
  assert.equal(prLine(pr({ state: 'merged', red: 2 })).text, 'Pull request merged', 'a merged request has no red to report')
  assert.equal(prLine(pr({ state: 'closed', red: 2 })).text, 'Pull request closed')
  assert.equal(prLine(pr({ state: null })).text, 'Pull request', 'an unknown state is not called open')
  assert.equal(prLine(pr()).number, 42)
})

test('the pull request link is drawn only for http or https', () => {
  assert.equal(prLine({ number: 7, url: 'https://x.test/p/7', state: 'open', red: 0 }).href, 'https://x.test/p/7')
  for (const bad of ['javascript:alert(1)', 'data:text/html,x', '//x.test', '', null]) {
    assert.equal(prLine({ number: 7, url: bad, state: 'open', red: 0 }).href, null, String(bad))
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
