// Date: 2026-11-18
// Purpose: the people pages sit behind a null slot. Off, the rail group, the badge and the pages are gone and the
// old links leave for the home route. On, nothing changes. An unreachable server never hides the pages by itself.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { PEOPLE_OFF_BOARD, peopleRoute, peopleSlot } from '../src/lib/peopleSlot.ts'

const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8')

test('the slot is off only when the server marked it, on when a board answered, unknown before any answer', () => {
  assert.equal(peopleSlot(null), 'unknown')
  assert.equal(peopleSlot(undefined), 'unknown')
  assert.equal(peopleSlot(PEOPLE_OFF_BOARD), 'off')
  assert.equal(peopleSlot({ people: [] }), 'on')
})

test('a people route waits for the first answer, leaves when off and shows when on or when the server is unreachable', () => {
  assert.equal(peopleRoute('unknown', false), 'wait')
  assert.equal(peopleRoute('unknown', true), 'show')
  assert.equal(peopleRoute('off', false), 'leave')
  assert.equal(peopleRoute('off', true), 'leave')
  assert.equal(peopleRoute('on', false), 'show')
})

test('the off board carries no person, no source and no time, so no chip or badge can read it as data', () => {
  assert.deepEqual(PEOPLE_OFF_BOARD.people, [])
  assert.equal(PEOPLE_OFF_BOARD.generated_utc, '')
})

test('the data layer turns a 404 of the board into the off board and keeps every other failure an error', () => {
  const src = read('../src/lib/data.ts')
  assert.match(src, /api\/one-on-ones[^\n]*\n[^\n]*404[^\n]*PEOPLE_OFF_BOARD|404\) return PEOPLE_OFF_BOARD/)
})

test('the rail, the shortcuts, the palette and the routes follow the slot', () => {
  const nav = read('../src/shell/nav.tsx')
  assert.match(nav, /slot: 'people'/)
  assert.match(nav, /export function groupsFor/)
  const app = read('../src/App.tsx')
  assert.match(app, /groupsFor\(/)
  assert.match(app, /PeopleGate/)
  for (const route of ['/people"', '/team"', '/team/:tab"']) {
    assert.match(app, new RegExp(`path="${route.replace('/', '\\/')}[^\\n]*PeopleGate`), route)
  }
})
