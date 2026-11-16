// The time rule (Ops Center Layout rule 21): a clock time carries the zone abbreviation, never UTC and never a trailing Z, a bare
// calendar date keeps its own day, and a relative time is spelled out. Run: node --test tests/time.test.mjs
import assert from 'node:assert/strict'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { after, before, test } from 'node:test'
import { createServer } from 'vite'

let vite
let t
before(async () => {
  vite = await createServer({
    server: { middlewareMode: true, hmr: false, watch: null },
    cacheDir: mkdtempSync(join(tmpdir(), 'vite-test-')),
    optimizeDeps: { noDiscovery: true, include: [] },
    appType: 'custom',
    logLevel: 'silent',
  })
  t = await vite.ssrLoadModule('/src/lib/time.ts')
  t.setTimeZone('America/New_York')
})
after(async () => {
  await vite?.close()
})

test('a winter stamp reads EST and a summer stamp reads EDT', () => {
  assert.equal(t.clockTime('2026-11-16T04:20:00Z'), '11:20 PM EST')
  assert.equal(t.clockTime('2026-07-04T16:05:00Z'), '12:05 PM EDT')
  assert.equal(t.stamp('2026-11-16T04:20:00Z'), 'Sun, Nov 15, 11:20 PM EST')
  assert.equal(t.fullTime('2026-11-16T04:20:00Z'), 'Nov 15, 2026, 11:20 PM EST')
})

test('the zone is a parameter and a change takes effect at once', () => {
  t.setTimeZone('America/Los_Angeles')
  assert.equal(t.clockTime('2026-11-16T04:20:00Z'), '8:20 PM PST')
  t.setTimeZone('America/New_York')
  assert.equal(t.clockTime('2026-11-16T04:20:00Z'), '11:20 PM EST')
})

test('no formatter output carries UTC wording or a Z stamp', () => {
  const samples = ['2026-11-16T04:20:00Z', '2026-07-04T16:05:00.123Z', 1_794_000_000_000, new Date(0)]
  for (const s of samples) {
    for (const f of [t.clockTime, t.stamp, t.fullTime, t.dayName, t.longDay]) {
      assert.doesNotMatch(f(s), /UTC|GMT|\d{2}:\d{2}Z|\dZ\b/, `${f.name}(${s})`)
    }
  }
})

test('a bare calendar date keeps its own day and the day key follows the zone', () => {
  assert.equal(t.dayName('2026-11-15'), 'Nov 15')
  assert.equal(t.dayKey('2026-11-16T04:20:00Z'), '2026-11-15')
})

test('an empty or unreadable value reads as empty, never as a date', () => {
  for (const f of [t.clockTime, t.stamp, t.fullTime, t.dayName, t.dayKey]) {
    assert.equal(f(null), '')
    assert.equal(f('garbage'), '')
  }
})

test('relative times are spelled out', () => {
  const now = Date.parse('2026-11-16T12:00:00Z')
  assert.equal(t.relAgo('2026-11-16T11:59:40Z', now), 'just now')
  assert.equal(t.relAgo('2026-11-16T11:55:00Z', now), '5 minutes ago')
  assert.equal(t.relAgo('2026-11-16T11:59:00Z', now), '1 minute ago')
  assert.equal(t.relAgo('2026-11-16T09:00:00Z', now), '3 hours ago')
  assert.equal(t.relAgo('2026-11-11T12:00:00Z', now), '5 days ago')
  assert.equal(t.relAgo(null, now), 'never')
  assert.equal(t.relAgo('', now, 'no data'), 'no data')
  assert.equal(t.relAgo('garbage', now), 'unknown')
  assert.equal(t.relIn('2026-11-16T12:05:00Z', now), 'in 5 minutes')
  assert.doesNotMatch(t.relAgo('2026-11-11T12:00:00Z', now), /\dd ago|\dh ago|\dm ago/)
})

test('spans read in plain words and an age is in whole minutes', () => {
  assert.equal(t.spanWords(45), '45 seconds')
  assert.equal(t.spanWords(1), '1 second')
  assert.equal(t.spanWords(600), 'about 10 minutes')
  assert.equal(t.spanWords(7200), 'about 2 hours')
  assert.equal(t.ageMinutes('2026-11-16T11:30:00Z', Date.parse('2026-11-16T12:00:00Z')), 30)
  assert.equal(t.ageMinutes(null), null)
})
