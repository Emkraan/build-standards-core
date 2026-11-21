// The Operations hub: sections and counts come from the server problem list, every old route redirects with its tab and
// query string, and a deep link resolves to its item. Run: node --test tests/operations.test.mjs
// Loads the pure modules through Vite's SSR loader; nothing touches the network or a browser.
import assert from 'node:assert/strict'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { after, before, test } from 'node:test'
import { createServer } from 'vite'

let vite
let sections
let routes
let kit

before(async () => {
  vite = await createServer({
    server: { middlewareMode: true, hmr: false, watch: null },
    cacheDir: mkdtempSync(join(tmpdir(), 'vite-ops-')),
    optimizeDeps: { noDiscovery: true, include: [] },
    appType: 'custom',
    logLevel: 'silent',
  })
  sections = await vite.ssrLoadModule('/src/pages/operations/sections.ts')
  routes = await vite.ssrLoadModule('/src/pages/operations/routes.ts')
  kit = await vite.ssrLoadModule(new URL('../../kit/src/shell/HubHeader.tsx', import.meta.url).pathname)
})

after(async () => {
  await vite?.close()
})

const item = (section, key, tone, extra = {}) => ({
  id: `${section}/${key}`,
  hub: 'operations',
  section,
  item: key,
  label: key,
  tone,
  headline: `${key} ${tone}`,
  details: [],
  count: tone === 'healthy' ? 0 : 1,
  running: false,
  ...extra,
})

const problems = {
  items: [item('builds', 'app', 'needs_me'), item('builds', 'agent', 'healthy', { running: true }), item('automation', 'jobs', 'worth_a_look'), item('cost', 'spend', 'healthy')],
  counts: {
    needs_me: 1,
    worth_a_look: 1,
    healthy: 2,
    running: 1,
    total: 4,
    by_section: { builds: 1, automation: 1 },
    by_item: { 'builds/app': 1, 'automation/jobs': 1 },
  },
}
const builds = { pipelines: [{ product: 'app' }, { product: 'agent' }, { product: 'app' }] }

test('the build items are the products of the feed, each once, in feed order', () => {
  assert.deepEqual(sections.buildItems(builds, problems).map((i) => i.key), ['app', 'agent'])
  assert.deepEqual(sections.buildItems(builds, null).map((i) => i.label), ['App', 'Agent'])
})

test('section and item counts are lookups in the server list, never computed from data', () => {
  const secs = sections.operationsSections(builds, problems)
  assert.deepEqual(secs.map((s) => s.key), ['builds', 'automation', 'host', 'cost'])
  const by = Object.fromEntries(secs.flatMap((s) => s.items.map((i) => [`${s.key}/${i.key}`, i.count])))
  assert.equal(by['builds/app'], 1)
  assert.equal(by['builds/agent'], undefined)
  assert.equal(by['automation/jobs'], 1)
  assert.equal(by['cost/spend'], undefined)
  assert.equal(secs[0].items[1].live, true)
})

test('the rail badge is the sum of the per-section counts of the same list', () => {
  assert.equal(sections.problemCount(problems), 2)
  assert.equal(sections.problemCount(null), 0)
  const tabs = sections.operationsSections(builds, problems).flatMap((s) => s.items).reduce((t, i) => t + (i.count || 0), 0)
  assert.equal(tabs, sections.problemCount(problems))
})

test('without a builds feed there is no builds section and the others stay', () => {
  assert.deepEqual(sections.operationsSections(null, null).map((s) => s.key), ['automation', 'host', 'cost'])
})

test('every old route redirects and keeps its tab, query string and hash', () => {
  const r = routes.redirectOld
  assert.equal(r('/builds', '?run=7', '#x'), '/platform/builds?run=7#x')
  assert.equal(r('/core', '?pr=3'), '/platform/cost/core?pr=3')
  assert.equal(r('/infra'), '/platform')
  assert.equal(r('/infra/spend', '?w=7'), '/platform/cost/spend?w=7')
  assert.equal(r('/infra/jobs', '?q=a'), '/platform/automation/jobs?q=a')
  assert.equal(r('/infra/ci'), '/platform/automation/ci')
  assert.equal(r('/infra/live', '?x=1'), '/platform/automation/ci?x=1')
  assert.equal(r('/infra/github'), '/platform/automation/ci')
  assert.equal(r('/infra/unknown', '?z=1'), '/platform?z=1')
  assert.equal(r('/infra/jobs/'), '/platform/automation/jobs')
  assert.equal(r('/reviews'), null)
})

test('an old route ends on an item or the overview within one more hop, with its query string', () => {
  const secs = sections.operationsSections(builds, problems)
  for (const [path, search] of [['/builds', '?a=1'], ['/core', '?a=1'], ['/infra', '?a=1'], ['/infra/spend', '?a=1'], ['/infra/jobs', '?a=1'], ['/infra/ci', '?a=1'], ['/infra/live', '?a=1'], ['/infra/github', '?a=1']]) {
    let to = routes.redirectOld(path, search)
    assert.ok(to.startsWith('/platform') && to.endsWith('?a=1'), to)
    for (let hop = 0; hop < 2; hop++) {
      const [, , section, itemKey] = to.split('?')[0].split('/')
      const hub = kit.resolveHubRoute('/platform', secs, section, itemKey)
      if (hub.kind !== 'redirect') break
      to = `${hub.to}?a=1`
    }
    const [, , section, itemKey] = to.split('?')[0].split('/')
    assert.notEqual(kit.resolveHubRoute('/platform', secs, section, itemKey).kind, 'redirect', `${path} -> ${to}`)
  }
})

test('a deep link resolves to its item and an unknown one goes to the section or the overview', () => {
  const secs = sections.operationsSections(builds, problems)
  assert.equal(kit.resolveHubRoute('/platform', secs, 'automation', 'ci').kind, 'item')
  assert.equal(kit.resolveHubRoute('/platform', secs, undefined, undefined).kind, 'overview')
  assert.equal(kit.resolveHubRoute('/platform', secs, 'automation', 'nope').to, '/platform/automation/jobs')
  assert.equal(kit.resolveHubRoute('/platform', secs, 'jobs', undefined).to, '/platform/automation/jobs')
})
