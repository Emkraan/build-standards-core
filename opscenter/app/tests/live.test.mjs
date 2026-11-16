// The push channel client (src/lib/live.ts): topic names, the safety-net stretch, subscribe and notify, presence, the backoff after a
// drop, and a catch-up read after a reconnect. Loads the module through Vite's SSR loader with a fake EventSource, document and fetch.
// Run: node --test tests/live.test.mjs
import assert from 'node:assert/strict'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { after, afterEach, before, test } from 'node:test'
import { createServer } from 'vite'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

class FakeSource {
  static all = []
  constructor(url) {
    this.url = url
    this.handlers = {}
    this.closed = false
    FakeSource.all.push(this)
  }
  addEventListener(name, fn) {
    this.handlers[name] = fn
  }
  close() {
    this.closed = true
  }
  emit(name, data) {
    this.handlers[name]?.({ data: JSON.stringify(data) })
  }
}

let vite
let live
const posts = []

before(async () => {
  globalThis.EventSource = FakeSource
  globalThis.document = { visibilityState: 'visible', addEventListener() {}, removeEventListener() {} }
  globalThis.fetch = async (url, init) => {
    posts.push({ url: String(url), body: JSON.parse(init.body) })
    return new Response('{}')
  }
  vite = await createServer({
    server: { middlewareMode: true, hmr: false, watch: null },
    cacheDir: mkdtempSync(join(tmpdir(), 'vite-test-')),
    optimizeDeps: { noDiscovery: true, include: [] },
    appType: 'custom',
    logLevel: 'silent',
  })
  live = await vite.ssrLoadModule('/src/lib/live.ts')
})

afterEach(() => {
  live.resetLiveForTests()
  live.setAliases({})
  FakeSource.all.length = 0
  posts.length = 0
})

after(async () => {
  await vite?.close()
})

test('a topic is the data file, an alias, or api: plus the path without its query', () => {
  assert.equal(live.dataTopic('freeze.json'), 'data:freeze.json')
  assert.equal(live.apiTopic('/api/infra/spend?x=1'), 'api:/api/infra/spend')
  assert.equal(live.apiTopic('api/infra/spend'), 'api:/api/infra/spend')
  live.setAliases({ '/api/badges': 'badges' })
  assert.equal(live.apiTopic('/api/badges'), 'badges')
})

test('a store polls on its own interval until the channel is live, then on the five minute safety net', () => {
  assert.equal(live.stretchedMs(10_000), 10_000)
  live.subscribe('x', () => {})
  const es = FakeSource.all[0]
  assert.equal(es.url.endsWith('api/live'), true)
  assert.equal(live.getLiveSnapshot().status, 'connecting')
  es.emit('hello', { id: 'c1' })
  assert.equal(live.isLive(), true)
  assert.equal(live.stretchedMs(10_000), live.STRETCH_MS)
  assert.equal(live.stretchedMs(10 * 60_000), 10 * 60_000)
})

test('a topic event runs the subscribers of that topic and no other', () => {
  const seen = []
  live.subscribe('a', () => seen.push('a'))
  live.subscribe('b', () => seen.push('b'))
  FakeSource.all[0].emit('hello', { id: 'c1' })
  FakeSource.all[0].emit('topic', { t: 'b', v: 'h', at: 1 })
  assert.deepEqual(seen, ['b'])
})

test('an unsubscribed callback is not called again', () => {
  const seen = []
  const off = live.subscribe('a', () => seen.push(1))
  FakeSource.all[0].emit('hello', { id: 'c1' })
  off()
  FakeSource.all[0].emit('topic', { t: 'a', v: 'h', at: 1 })
  assert.deepEqual(seen, [])
})

test('presence is sent once, debounced, with the stream id, visibility and what the tab shows', async () => {
  live.declare('api:/api/x', '/api/x?q=1', 5000)
  live.declare('api:/api/x', '/api/x', 2000)
  live.declare('data:y.json', null, 60000)
  FakeSource.all[0].emit('hello', { id: 'c1' })
  await sleep(live.PRESENCE_DEBOUNCE_MS + 150)
  assert.equal(posts.length, 1)
  assert.ok(posts[0].url.endsWith('api/live/presence'))
  assert.equal(posts[0].body.id, 'c1')
  assert.equal(posts[0].body.visible, true)
  assert.deepEqual(posts[0].body.wants, [
    { topic: 'api:/api/x', path: '/api/x', ms: 2000 },
    { topic: 'data:y.json', ms: 60000 },
  ])
})

test('a drop shows reconnecting, backs off, and a reconnect reads every topic once', async () => {
  const seen = []
  live.subscribe('a', () => seen.push('a'))
  live.subscribe('b', () => seen.push('b'))
  const first = FakeSource.all[0]
  first.emit('hello', { id: 'c1' })
  first.onerror()
  assert.equal(first.closed, true)
  assert.equal(live.getLiveSnapshot().status, 'reconnecting')
  assert.equal(live.isLive(), false)
  assert.equal(live.stretchedMs(10_000), 10_000)
  await sleep(live.BACKOFF_MS[0] + 200)
  assert.equal(FakeSource.all.length, 2)
  FakeSource.all[1].emit('hello', { id: 'c2' })
  assert.equal(live.isLive(), true)
  assert.deepEqual(seen.sort(), ['a', 'b'])
})

test('the first hello does not read every topic, a page that just loaded already holds the content', () => {
  const seen = []
  live.subscribe('a', () => seen.push('a'))
  FakeSource.all[0].emit('hello', { id: 'c1' })
  assert.deepEqual(seen, [])
})

test('a frame that is not JSON is ignored', () => {
  const seen = []
  live.subscribe('a', () => seen.push('a'))
  FakeSource.all[0].handlers.topic({ data: 'not json' })
  assert.deepEqual(seen, [])
})
