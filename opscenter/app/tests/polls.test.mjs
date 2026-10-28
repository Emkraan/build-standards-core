// Poll rules for the client data layer. Run: node --test tests/polls.test.mjs
// Loads src/lib/data.ts through Vite's SSR loader (already a dev dependency, no new package) with a
// fake document, window, location and fetch. Nothing touches the network or a real browser.
import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { createServer } from 'vite'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// A document with a switchable visibilityState and a working visibilitychange listener list.
function fakeDocument() {
  const listeners = new Set()
  const doc = {
    visibilityState: 'visible',
    addEventListener: (t, f) => t === 'visibilitychange' && listeners.add(f),
    removeEventListener: (t, f) => t === 'visibilitychange' && listeners.delete(f),
    set(state) {
      doc.visibilityState = state
      for (const f of [...listeners]) f()
    },
    listenerCount: () => listeners.size,
  }
  return doc
}

// A location that records every attempt to navigate.
function fakeLocation() {
  const moves = []
  const loc = { moves }
  for (const k of ['href', 'pathname', 'hash']) {
    Object.defineProperty(loc, k, { get: () => 'http://ops.test/', set: (v) => moves.push(`${k}=${v}`) })
  }
  loc.assign = (u) => moves.push(`assign ${u}`)
  loc.replace = (u) => moves.push(`replace ${u}`)
  loc.reload = () => moves.push('reload')
  return loc
}

let vite
let data
const doc = fakeDocument()
const loc = fakeLocation()

before(async () => {
  globalThis.document = doc
  globalThis.location = loc
  globalThis.window = { setInterval, clearInterval, location: loc, addEventListener() {}, removeEventListener() {} }
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

// core-rule: web-client-runtime.3.7
test('a 401 on a poll throws to the poller and starts no navigation', async () => {
  const seen = []
  globalThis.fetch = async (url) => {
    seen.push(String(url))
    return new Response(JSON.stringify({ error: 'unauthorized' }), { status: 401, headers: { 'content-type': 'application/json' } })
  }
  // The three fetchers the live stores and useData poll with.
  await assert.rejects(() => data.loadData('action-center.json', true), /401/)
  await assert.rejects(() => data.fetchAresReviews(true), /unauthorized/)
  await assert.rejects(() => data.fetchplatformReviews(true), /unauthorized/)
  assert.equal(seen.length, 3, 'every poll reached the fake fetch')
  assert.deepEqual(loc.moves, [], 'no navigation was started by a 401')
})

// core-rule: web-client-runtime.3.7
test('a 401 inside onLiveTick stays with the poller and starts no navigation', async () => {
  globalThis.fetch = async () => new Response('', { status: 401 })
  doc.visibilityState = 'visible'
  const outcomes = []
  const stop = data.onLiveTick(() => {
    data.loadData('action-center.json', true).catch((e) => outcomes.push(String(e.message)))
  }, 15)
  await sleep(80)
  stop()
  assert.ok(outcomes.length >= 2, `the poll ran and failed ${outcomes.length} times`)
  assert.ok(outcomes.every((m) => m.includes('401')))
  assert.deepEqual(loc.moves, [])
})

// core-rule: web-client-runtime.3.8
test('no poll fires while the document is hidden, and one refresh fires when it is visible again', async () => {
  doc.visibilityState = 'visible'
  let fired = 0
  const stop = data.onLiveTick(() => {
    fired++
  }, 10)
  await sleep(45)
  assert.ok(fired >= 2, 'it polls while visible')
  doc.set('hidden')
  const atHide = fired
  await sleep(80)
  assert.equal(fired, atHide, 'no poll fires while hidden')
  doc.set('visible')
  assert.equal(fired, atHide + 1, 'exactly one immediate refresh on becoming visible')
  stop()
  assert.equal(doc.listenerCount(), 0, 'the listener is released on stop')
  const atStop = fired
  await sleep(40)
  assert.equal(fired, atStop, 'nothing fires after stop')
})

// core-rule: web-client-runtime.3.8
test('useVisibleInterval is built on the same visibility gate', async () => {
  const src = await (await import('node:fs/promises')).readFile(new URL('../src/lib/data.ts', import.meta.url), 'utf8')
  const body = src.slice(src.indexOf('export function useVisibleInterval'))
  assert.match(body.slice(0, 400), /onLiveTick\(/)
})
