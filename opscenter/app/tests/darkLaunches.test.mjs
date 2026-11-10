// Where a dark launch is listed: an acting one leaves the Action Center for Live automation, every other one stays.
// Run: node --test tests/darkLaunches.test.mjs
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { isActing, splitLaunches } from '../src/lib/darkLaunches.ts'

const l = (id, live, status) => ({ id, live, status })

test('a launch is acting while its live switch reads on, whatever the registry last recorded', () => {
  assert.equal(isActing(l('a', 'on', 'enabled')), true)
  assert.equal(isActing(l('b', 'on', 'dark')), true)
})

test('an unreadable switch counts as acting only when the registry recorded enabled, never as off', () => {
  assert.equal(isActing(l('c', 'unknown', 'enabled')), true)
  assert.equal(isActing(l('d', 'unknown', 'dark')), false)
})

test('a launch whose switch reads off is not acting, even when the registry still says enabled', () => {
  assert.equal(isActing(l('e', 'off', 'enabled')), false)
  assert.equal(isActing(l('f', 'off', 'dark')), false)
})

test('splitLaunches keeps every launch in exactly one list and keeps the order', () => {
  const all = [l('a', 'on', 'enabled'), l('b', 'off', 'dark'), l('c', 'unknown', 'enabled'), l('d', 'off', 'enabled'), l('e', 'unknown', 'dark')]
  const { acting, dark } = splitLaunches(all)
  assert.deepEqual(acting.map((x) => x.id), ['a', 'c'])
  assert.deepEqual(dark.map((x) => x.id), ['b', 'd', 'e'])
  assert.equal(acting.length + dark.length, all.length)
})

test('an empty registry gives two empty lists', () => {
  assert.deepEqual(splitLaunches([]), { acting: [], dark: [] })
})
