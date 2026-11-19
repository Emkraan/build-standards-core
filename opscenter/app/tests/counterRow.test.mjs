import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import { anythingWaiting, counterTiles } from '../src/lib/counterRow.ts'

const counts = (over = {}) => ({
  actions: 0, debt: 0, knowledge: 0, knowledgePending: 0, knowledgeDocs: 0, links: 0, operations: 0, operationsItems: [],
  alerts: 0, platform: 0, team: 0, reviews: 0, other: 0, myPrs: 0, myPrsWorking: 0, platformMine: 0, platformWorking: 0,
  teamMine: 0, teamWorking: 0, ...over,
})
const tiles = (over = {}, extra = {}) => counterTiles({ counts: counts(over), trackerWaiting: null, builds: null, ...extra })
const keys = (t) => t.map((x) => x.key)

test('the base row has the six tiles every consumer has, in reading order', () => {
  assert.deepEqual(keys(tiles()), ['actions', 'reviews', 'alerts', 'operations', 'knowledge', 'debt'])
})

test('the work tile appears only while the tracker slot supplies a number, and sits after reviews', () => {
  assert.equal(keys(tiles()).includes('work'), false)
  const t = tiles({}, { trackerWaiting: 4 })
  assert.deepEqual(keys(t).slice(0, 4), ['actions', 'reviews', 'work', 'alerts'])
  assert.equal(t.find((x) => x.key === 'work').count, 4)
})

test('a tracker slot that is on with nothing waiting still shows a zero, and an off slot shows nothing', () => {
  assert.equal(tiles({}, { trackerWaiting: 0 }).find((x) => x.key === 'work').count, 0)
  assert.equal(tiles({}, { trackerWaiting: null }).find((x) => x.key === 'work'), undefined)
})

test('the builds tile appears only when the feed is served and turns to warn while a run waits', () => {
  assert.equal(tiles().find((x) => x.key === 'builds'), undefined)
  const calm = tiles({}, { builds: { running: 3, waiting: 0 } }).find((x) => x.key === 'builds')
  assert.equal(calm.tone, 'calm')
  assert.equal(calm.count, 0)
  assert.equal(tiles({}, { builds: { running: 0, waiting: 2 } }).find((x) => x.key === 'builds').tone, 'warn')
})

test('reviews links to the platform lane first and the team lane when only that has items', () => {
  assert.equal(tiles({ platform: 2, team: 1, reviews: 3 }).find((x) => x.key === 'reviews').to, '/reviews/platform')
  assert.equal(tiles({ platform: 0, team: 2, reviews: 2 }).find((x) => x.key === 'reviews').to, '/reviews/team')
  assert.equal(tiles({}).find((x) => x.key === 'reviews').to, '/reviews/platform')
})

test('debt is information only, so a pile of debt alone is not something waiting on me', () => {
  assert.equal(anythingWaiting(tiles({ debt: 40 })), false)
  assert.equal(anythingWaiting(tiles({ debt: 40, alerts: 1 })), true)
  assert.equal(anythingWaiting(tiles({ actions: 1 })), true)
})

// A tile that links to a path no route serves would bounce the reader to the Action Center without a word, which is how the first
// draft of the builds tile pointed at a legacy redirect. Every tile target must match a route in App.tsx, taking the :param segments as wildcards.
test('every tile points at a route that App.tsx serves and is not a legacy redirect', () => {
  const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')
  const routes = [...app.matchAll(/<Route path="([^"]+)" element=\{([^}]*(?:\{[^}]*\}[^}]*)*)\}/g)].map((m) => ({ path: m[1], element: m[2] }))
  const matches = (path, to) => {
    const a = path.split('/')
    const b = to.split('/')
    return a.length === b.length && a.every((seg, i) => seg.startsWith(':') || seg === b[i])
  }
  const all = counterTiles({
    counts: counts(),
    trackerWaiting: 1,
    builds: { running: 1, waiting: 1 },
  })
  for (const tile of all) {
    const hit = routes.filter((r) => matches(r.path, tile.to))
    assert.ok(hit.length > 0, `${tile.key}: no route serves ${tile.to}`)
    const best = hit.sort((x, y) => x.path.split(':').length - y.path.split(':').length)[0]
    assert.ok(!/OldRoute|Navigate/.test(best.element), `${tile.key}: ${tile.to} is a redirect (${best.path})`)
  }
})
