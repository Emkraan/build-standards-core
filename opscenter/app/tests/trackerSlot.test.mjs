// Date: 2026-11-18
// Purpose: the Jira pages sit behind a null tracker slot (DESIGN 12.67). Off, the rail item, the badge reads, the shortcut and
// the pages are gone and the an old link shows the page that names the slot it needs. On, nothing changes. An unreachable server never hides
// the pages by itself. Also pins the two Jira tabs to the paths the server registers (they called two that it did not).
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { TRACKER_OFF, trackerRoute, trackerSlot } from '../src/lib/trackerSlot.ts'

const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8')

test('the slot is off only when the server marked it, on when an answer came, unknown before any answer', () => {
  assert.equal(trackerSlot(null), 'unknown')
  assert.equal(trackerSlot(undefined), 'unknown')
  assert.equal(trackerSlot(TRACKER_OFF), 'off')
  assert.equal(trackerSlot({ items: [] }), 'on')
})

test('a tracker route waits for the first answer, reports off when off and shows when on or when the server is unreachable', () => {
  assert.equal(trackerRoute('unknown', false), 'wait')
  assert.equal(trackerRoute('unknown', true), 'show')
  assert.equal(trackerRoute('off', false), 'off')
  assert.equal(trackerRoute('off', true), 'off')
  assert.equal(trackerRoute('on', false), 'show')
})

test('the off answer carries no ticket and no time, so no chip or badge can read it as data', () => {
  assert.deepEqual(TRACKER_OFF.items, [])
  assert.equal(TRACKER_OFF.count, 0)
  assert.equal(TRACKER_OFF.generated_utc, '')
})

test('the data layer turns a 404 into the off answer for needs me and approvals and keeps every other failure an error', () => {
  const src = read('../src/lib/data.ts')
  assert.match(src, /api\/jira\/needs-me[^\n]*\n[^\n]*\n[^\n]*404\) return \{ \.\.\.TRACKER_OFF/)
  assert.match(src, /api\/jira\/approvals[^\n]*\n[^\n]*\n[^\n]*404\) return \{ generated_utc: ''/)
  assert.match(src, /throw new Error\([^\n]*api\/jira\/needs-me -> /)
  assert.match(src, /throw new Error\([^\n]*api\/jira\/approvals -> /)
})

test('the backlog and changes tabs call the paths the server registers', () => {
  const src = read('../src/lib/data.ts')
  assert.match(src, /jiraGet<BacklogData>\('api\/jira\/backlog'/)
  assert.doesNotMatch(src, /'api\/backlog'/)
  assert.doesNotMatch(src, /'api\/change-approvals'/)
})

test('the rail item, the shortcuts, the palette and the Jira routes follow the slot', () => {
  const nav = read('../src/shell/nav.tsx')
  assert.match(nav, /slot: 'tracker'/)
  assert.match(nav, /export function groupsFor\(people: boolean, tracker = true, extra: ExtensionPage\[\] = \[\], layout: NavLayout = NAV_LAYOUT\)/)
  const app = read('../src/App.tsx')
  assert.match(app, /TrackerGate/)
  assert.match(app, /groupsFor\(people, tracker, extraPages\)/)
  for (const route of ['/work"', '/work/:tab"', '/work/:tab/:sprintId"']) {
    assert.match(app, new RegExp(`path="${route.replace('/', '\\/')}[^\\n]*TrackerGate`), route)
  }
  const palette = read('../src/shell/SearchPalette.tsx')
  assert.match(palette, /groupsFor\(peopleOn, trackerOn, pagesAll\(ext\)\)/)
})
