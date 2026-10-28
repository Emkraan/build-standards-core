// GET cache rules for the client data layer (web-client-runtime 3.2, 3.3, 3.5, 3.6).
// Run: node --test tests/dataCache.test.mjs
// Loads src/lib/data.ts through Vite's SSR loader with a fake document, window and a fetch whose
// responses the test releases by hand. Nothing touches the network or a real browser.
import assert from 'node:assert/strict'
import { after, before, beforeEach, test } from 'node:test'
import { createServer } from 'vite'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

let vite
let data
let calls
let pending

// Every fetch waits for the test to answer it, so a request can be held in flight.
function fakeFetch(url) {
  return new Promise((resolve, reject) => {
    calls.push(String(url))
    pending.push({
      ok: (body) => resolve(new Response(JSON.stringify(body), { status: 200 })),
      fail: (status) => resolve(new Response('', { status })),
      boom: (err) => reject(err),
    })
  })
}

const tick = () => new Promise((r) => setTimeout(r, 0))

before(async () => {
  globalThis.document = { visibilityState: 'visible', addEventListener() {}, removeEventListener() {} }
  globalThis.window = { setInterval, clearInterval, location: {}, addEventListener() {}, removeEventListener() {} }
  vite = await createServer({
    server: { middlewareMode: true, hmr: false, watch: null },
    // Own dependency cache and no dependency scan: two test files share node_modules otherwise, and
    // when they start together one waits forever on the other's optimizer run.
    cacheDir: mkdtempSync(join(tmpdir(), 'vite-test-')),
    optimizeDeps: { noDiscovery: true, include: [] },
    appType: 'custom', logLevel: 'silent' })
  data = await vite.ssrLoadModule('/src/lib/data.ts')
})

after(async () => {
  await vite?.close()
})

beforeEach(() => {
  calls = []
  pending = []
  globalThis.fetch = fakeFetch
  for (const k of ['a.json', 'b.json', 'c.json', 'd.json', 'e.json', 'f.json']) data.invalidateData(k)
})

// core-rule: web-client-runtime.3.2
test('three concurrent GETs of one path produce one request and share one promise', async () => {
  const one = data.loadData('a.json')
  const two = data.loadData('a.json')
  const three = data.loadData('a.json', true)
  assert.equal(calls.length, 1, 'one request for three callers')
  pending[0].ok({ n: 1 })
  const [x, y, z] = await Promise.all([one, two, three])
  assert.deepEqual(x, { n: 1 })
  assert.equal(x, y)
  assert.equal(y, z, 'all callers get the same object')
  assert.equal(calls.length, 1)
})

// core-rule: web-client-runtime.3.2
test('different paths do not share a request', async () => {
  const p = [data.loadData('a.json'), data.loadData('b.json')]
  assert.equal(calls.length, 2)
  pending[0].ok({ k: 'a' })
  pending[1].ok({ k: 'b' })
  assert.deepEqual(await Promise.all(p), [{ k: 'a' }, { k: 'b' }])
})

// core-rule: web-client-runtime.3.3
test('a stale key returns the cached value and starts one background refresh', async () => {
  data.setDataTtl('c.json', 10)
  const first = data.loadData('c.json')
  pending[0].ok({ v: 1 })
  assert.deepEqual(await first, { v: 1 })
  await new Promise((r) => setTimeout(r, 30))
  const second = data.loadData('c.json')
  const third = data.loadData('c.json')
  assert.deepEqual(await second, { v: 1 }, 'the cached value comes back at once')
  assert.deepEqual(await third, { v: 1 })
  assert.equal(calls.length, 2, 'exactly one background refresh started')
  pending[1].ok({ v: 2 })
  await tick()
  await tick()
  // A long TTL for the read-back, so a slow runner cannot make the fresh value stale again before it.
  data.setDataTtl('c.json', 60_000)
  assert.deepEqual(await data.loadData('c.json'), { v: 2 }, 'the refresh updated the cache')
  assert.equal(calls.length, 2)
})

// core-rule: web-client-runtime.3.3
test('each key has its own TTL and a key with none never goes stale', async () => {
  data.setDataTtl('d.json', 10)
  const d = data.loadData('d.json')
  const e = data.loadData('e.json')
  pending[0].ok({ k: 'd' })
  pending[1].ok({ k: 'e' })
  await Promise.all([d, e])
  await new Promise((r) => setTimeout(r, 30))
  await data.loadData('e.json')
  assert.equal(calls.length, 2, 'the key without a TTL stays fresh')
  await data.loadData('d.json')
  assert.equal(calls.length, 3, 'only the key with a TTL refreshed')
  pending[2].ok({ k: 'd' })
})

// core-rule: web-client-runtime.3.5
test('a GET in flight during a write is not returned to a caller that reads after the invalidate', async () => {
  const earlier = data.loadData('a.json')
  assert.equal(calls.length, 1)
  data.invalidateData('a.json')
  const later = data.loadData('a.json')
  assert.equal(calls.length, 2, 'the read after the invalidate sent its own request')
  pending[1].ok({ v: 'new' })
  pending[0].ok({ v: 'old' })
  assert.deepEqual(await later, { v: 'new' })
  assert.deepEqual(await earlier, { v: 'old' }, 'the earlier caller keeps its own result')
  assert.deepEqual(await data.loadData('a.json'), { v: 'new' }, 'the stale response never reached the cache')
  assert.equal(calls.length, 2)
})

// core-rule: web-client-runtime.3.6
test('after a rejected GET the next read sends a new request', async () => {
  const bad = data.loadData('f.json')
  pending[0].fail(500)
  await assert.rejects(bad, /500/)
  const again = data.loadData('f.json')
  assert.equal(calls.length, 2, 'no stuck in-flight entry')
  pending[1].ok({ v: 1 })
  assert.deepEqual(await again, { v: 1 })
  const net = data.loadData('b.json')
  pending[2].boom(new Error('network down'))
  await assert.rejects(net, /network down/)
  const retry = data.loadData('b.json')
  assert.equal(calls.length, 4)
  pending[3].ok({ v: 2 })
  await retry
})

// core-rule: web-client-runtime.3.6
test('a stale rejection never overwrites newer data', async () => {
  const old = data.loadData('a.json')
  data.invalidateData('a.json')
  const fresh = data.loadData('a.json')
  pending[1].ok({ v: 'newer' })
  await fresh
  pending[0].fail(503)
  await assert.rejects(old, /503/)
  assert.deepEqual(await data.loadData('a.json'), { v: 'newer' })
  assert.equal(calls.length, 2, 'the rejected request left the newer entry alone')
})
