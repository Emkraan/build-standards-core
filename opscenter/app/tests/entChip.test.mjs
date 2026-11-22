// Date: 2026-11-21
// Purpose: the header chip for an open Enterprise billing incident (issue 327, parity spec section 2.2): none without an incident, the time left
// from the server's close time, and no invented time when the server sent none.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { entChip } from '../src/lib/entChip.ts'

const NOW = Date.parse('2026-11-21T12:00:00Z')

test('no incident draws no chip', () => {
  assert.equal(entChip(null, NOW), null)
  assert.equal(entChip({ active: null }, NOW), null)
})

test('an open incident counts down to the server close time, in hours and minutes', () => {
  const c = entChip({ active: { closes_utc: '2026-11-21T12:41:30Z' } }, NOW)
  assert.equal(c.text, 'Enterprise on, 0 h 41 min left')
  assert.equal(c.short, 'Ent on')
  assert.equal(entChip({ active: { closes_utc: '2026-11-21T14:05:00Z' } }, NOW).text, 'Enterprise on, 2 h 5 min left')
})

test('a missing, malformed or past close time leaves out the time left', () => {
  for (const closes_utc of [undefined, null, 'nonsense', '2026-11-21T11:00:00Z', '2026-11-21T12:00:30Z']) {
    assert.equal(entChip({ active: { closes_utc } }, NOW).text, 'Enterprise on', String(closes_utc))
  }
})
