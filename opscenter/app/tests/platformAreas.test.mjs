import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { areaRows, areasNeedingMe, ownerLine, rollupLine, statusWord } from '../src/lib/platformAreas.ts'

const area = (section, status = 'healthy', over = {}) => ({ section, label: section, owner: null, status, needs_me: 0, worth_a_look: 0, healthy: 1, lines: 0, ...over })

test('an area row is the server row as it came, in the server order', () => {
  const rows = [area('a', 'needs_me'), area('b'), area('c', 'worth_a_look')]
  assert.deepEqual(areaRows({ areas: rows }).map((r) => r.section), ['a', 'b', 'c'])
})

test('a server that sent no areas field is told apart from one that sent an empty list', () => {
  assert.equal(areaRows({}), null)
  assert.equal(areaRows({ areas: null }), null)
  assert.equal(areaRows(null), null)
  assert.equal(areaRows(undefined), null)
  assert.deepEqual(areaRows({ areas: [] }), [])
})

test('a status is a word, and an unknown one is shown as sent and never called healthy', () => {
  assert.equal(statusWord('needs_me'), 'Needs me')
  assert.equal(statusWord('worth_a_look'), 'Worth a look')
  assert.equal(statusWord('healthy'), 'Healthy')
  assert.equal(statusWord('degraded'), 'Degraded')
  assert.notEqual(statusWord('degraded'), 'Healthy')
  assert.equal(statusWord(''), 'Unknown')
})

test('an owner is said in words and none named is said plainly, never left blank', () => {
  assert.equal(ownerLine(area('a', 'healthy', { owner: 'Platform team' })), 'Owner: Platform team')
  assert.equal(ownerLine(area('a')), 'No owner named')
  assert.equal(ownerLine(area('a', 'healthy', { owner: '' })), 'No owner named')
})

test('the rollup counts areas that need me, not problem lines', () => {
  const rows = [area('a', 'needs_me', { lines: 5 }), area('b', 'needs_me', { lines: 1 }), area('c', 'worth_a_look', { lines: 2 }), area('d')]
  assert.equal(areasNeedingMe(rows), 2)
  assert.equal(rollupLine(rows), '4 areas, 2 need me.')
})

test('the rollup line is singular for one and says none when nothing needs me', () => {
  assert.equal(rollupLine([area('a', 'needs_me')]), '1 area, 1 needs me.')
  assert.equal(rollupLine([area('a'), area('b')]), '2 areas, none needs me.')
  assert.equal(rollupLine([]), '0 areas, none needs me.')
})

// The rollup reads and shows. A control that changes an area is a separate decision with its own confirmation.
test('the areas rollup has no write path: no post function, no fetch, no button', () => {
  for (const f of ['../src/lib/platformAreas.ts', '../src/components/PlatformAreas.tsx']) {
    let src
    try {
      src = readFileSync(new URL(f, import.meta.url), 'utf8').replace(/\/\/.*$/gm, '')
    } catch {
      continue
    }
    assert.equal(/\bpost[A-Z]\w*/.test(src), false, `${f} must not call a post function`)
    assert.equal(/fetch\(|method:\s*'(POST|DELETE|PUT)'/.test(src), false, `${f} must not send a request`)
    assert.equal(/<button|onClick=/.test(src), false, `${f} must not draw a button`)
  }
})
