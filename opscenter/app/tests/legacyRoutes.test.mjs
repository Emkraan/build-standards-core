// Date: 2026-11-21
// Purpose: /jira moved to /work and /operations to /platform (issue 327). Every old address lands on the same tab with its
// query and hash, the three old /platform lane tabs still reach the platform review lane, and the app registers both sets.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { movedTo, platformTarget } from '../src/lib/legacyRoutes.ts'

const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8')

test('an old /jira address lands on /work with its tab, sprint id, query and hash', () => {
  assert.equal(movedTo('/jira'), '/work')
  assert.equal(movedTo('/jira/backlog', '?a=1', '#x'), '/work/backlog?a=1#x')
  assert.equal(movedTo('/jira/closed/31'), '/work/closed/31')
  assert.equal(movedTo('/jira/'), '/work')
})

test('an old /operations address lands on /platform with its section, item, query and hash', () => {
  assert.equal(movedTo('/operations'), '/platform')
  assert.equal(movedTo('/operations/automation/jobs', '?q=a'), '/platform/automation/jobs?q=a')
  assert.equal(movedTo('/operations/cost/core', '', '#t'), '/platform/cost/core#t')
})

test('an address that did not move, or only starts with the same letters, stays put', () => {
  for (const p of ['/work', '/platform', '/jiras', '/operationsx', '/reviews/platform', '/action']) assert.equal(movedTo(p), null, p)
})

test('/platform/<tab> keeps meaning the platform review lane for its three old tabs, and is the hub otherwise', () => {
  for (const t of ['progress', 'mine', 'shipped']) assert.deepEqual(platformTarget(t), { kind: 'lane', to: `/reviews/platform/${t}` })
  for (const t of [undefined, 'automation', 'cost', 'builds', 'overview']) assert.deepEqual(platformTarget(t), { kind: 'hub' })
})

test('the app registers the new routes and the old ones as redirects, and the route lock lists both', () => {
  const app = read('../src/App.tsx')
  for (const r of ['/work', '/work/:tab', '/work/:tab/:sprintId']) assert.match(app, new RegExp(`path="${r.replace(/[/:]/g, (c) => '\\' + c)}" element=\\{<TrackerGate>`), r)
  for (const r of ['/jira', '/jira/:tab', '/jira/:tab/:sprintId', '/operations', '/operations/:section', '/operations/:section/:item']) {
    assert.match(app, new RegExp(`path="${r.replace(/[/:]/g, (c) => '\\' + c)}" element=\\{<MovedRoute />\\}`), r)
  }
  const lock = JSON.parse(read('../routes.lock.json')).routes
  for (const r of ['/work', '/work/:tab', '/work/:tab/:sprintId', '/jira', '/jira/:tab', '/operations', '/platform', '/platform/:section']) assert.ok(lock.includes(r), r)
})
