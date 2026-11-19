// Filters for the Debt and improvements page. Run: node --test tests/debtFilters.test.mjs
import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  NO_DEBT_FILTERS,
  activeFilterCount,
  applyDebtFilters,
  effortBand,
  hasFoldedEntries,
  isFoldedInto,
  optionsFor,
} from '../src/lib/debtFilters.ts'

const row = (over = {}) => ({ kind: 'TD', severity: 'medium', goals: [], effort: 'small', status: 'open', ...over })

test('effort groups by its leading size word and by a stated duration, and reads anything else as unsized', () => {
  for (const [text, band] of [
    ['small', 's'],
    ['S', 's'],
    ['Small (about 1 hour)', 's'],
    ['small to medium', 's'],
    ['small, one PR', 's'],
    ['medium', 'm'],
    ['about half a day', 's'],
    ['3 days', 'm'],
    ['2 weeks', 'l'],
    ['large', 'l'],
    ['', 'unsized'],
    ['depends on the vendor', 'unsized'],
  ]) {
    assert.equal(effortBand(text), band, text)
  }
})

test('no filter set keeps every row', () => {
  const rows = [row(), row({ severity: 'high' }), row({ kind: 'IMP', goals: ['G1'] })]
  assert.equal(applyDebtFilters(rows, NO_DEBT_FILTERS).length, 3)
  assert.equal(activeFilterCount(NO_DEBT_FILTERS), 0)
})

test('severity, goal, effort and status each narrow the list and combine', () => {
  const rows = [
    row({ severity: 'high', effort: 'small' }),
    row({ severity: 'high', effort: 'medium' }),
    row({ kind: 'IMP', severity: '', goals: ['G1', 'G3'], effort: 'S', status: 'Suggested' }),
    row({ kind: 'IMP', severity: '', goals: ['G2'], effort: 'medium', status: 'approved' }),
  ]
  assert.equal(applyDebtFilters(rows, { ...NO_DEBT_FILTERS, severity: 'high' }).length, 2)
  assert.equal(applyDebtFilters(rows, { ...NO_DEBT_FILTERS, goal: 'G3' }).length, 1)
  assert.equal(applyDebtFilters(rows, { ...NO_DEBT_FILTERS, effort: 'm' }).length, 2)
  assert.equal(applyDebtFilters(rows, { ...NO_DEBT_FILTERS, status: 'suggested' }).length, 1)
  const both = { ...NO_DEBT_FILTERS, severity: 'high', effort: 'm' }
  assert.equal(applyDebtFilters(rows, both).length, 1)
  assert.equal(activeFilterCount(both), 2)
})

test('the fold toggles read the parent and children the server already links', () => {
  const parent = row({ children: ['td-aaaaaa'] })
  const child = row({ parent_uid: 'td-bbbbbb' })
  const plain = row()
  assert.ok(hasFoldedEntries(parent) && !hasFoldedEntries(child) && !hasFoldedEntries(plain))
  assert.ok(isFoldedInto(child) && !isFoldedInto(parent))
  const rows = [parent, child, plain]
  assert.deepEqual(applyDebtFilters(rows, { ...NO_DEBT_FILTERS, hasFolded: true }), [parent])
  assert.deepEqual(applyDebtFilters(rows, { ...NO_DEBT_FILTERS, foldedInto: true }), [child])
  assert.equal(activeFilterCount({ ...NO_DEBT_FILTERS, hasFolded: true, foldedInto: true }), 2)
})

test('the options a filter offers are counted, most common first, with blanks left out', () => {
  const rows = [row({ severity: 'high' }), row({ severity: 'high' }), row({ severity: 'low' }), row({ severity: '' })]
  assert.deepEqual(optionsFor(rows, (r) => [r.severity]), [
    { value: 'high', n: 2 },
    { value: 'low', n: 1 },
  ])
  const goals = [row({ goals: ['G1', 'G2'] }), row({ goals: ['G2'] })]
  assert.deepEqual(optionsFor(goals, (r) => r.goals), [
    { value: 'G2', n: 2 },
    { value: 'G1', n: 1 },
  ])
})
