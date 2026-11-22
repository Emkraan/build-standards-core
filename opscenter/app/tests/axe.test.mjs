// Accessibility gate (the web-ui-standard doc): axe-core over the built shell in the light and the dark theme.
// Run: npm run build && node --test tests/axe.test.mjs
// Serves dist/ on a random local port and drives a headless Chrome of its own over the DevTools
// protocol (own port, own profile dir). Skips with a stated reason when dist/ or Chrome is missing on a machine with no browser provided.
// In CI, or with CHROME_BIN set, it fails instead (tests/browserGate.mjs).
// Fails on any critical or serious axe violation.
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { createServer } from 'node:http'
import { createRequire } from 'node:module'
import { dirname, extname, join, normalize } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { browserGate } from './browserGate.mjs'
import { closeTab, openTab, sharedBrowser } from './sharedBrowser.mjs'

const APP = join(dirname(fileURLToPath(import.meta.url)), '..')
const DIST = join(APP, 'dist')
const CHROME = process.env.CHROME_BIN || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const AXE_SRC = readFileSync(createRequire(import.meta.url).resolve('axe-core/axe.min.js'), 'utf8')
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.json': 'application/json', '.woff2': 'font/woff2' }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

function serve() {
  const srv = createServer((req, res) => {
    const path = normalize(decodeURIComponent((req.url || '/').split('?')[0]))
    const file = join(DIST, path === '/' || path === '.' ? 'index.html' : path)
    if (!file.startsWith(DIST) || !existsSync(file)) {
      res.writeHead(404).end()
      return
    }
    res.writeHead(200, { 'content-type': TYPES[extname(file)] || 'application/octet-stream' }).end(readFileSync(file))
  })
  return new Promise((resolve) => srv.listen(0, '127.0.0.1', () => resolve(srv)))
}

async function cdpSession(port, tabUrl) {
  let wsUrl = tabUrl
  for (let i = 0; i < 60 && !wsUrl; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()
      wsUrl = list.find((t) => t.type === 'page')?.webSocketDebuggerUrl
    } catch {}
    if (!wsUrl) await sleep(250)
  }
  assert.ok(wsUrl, 'headless Chrome did not expose a page')
  const ws = new WebSocket(wsUrl)
  await new Promise((r) => ws.addEventListener('open', r))
  let id = 0
  const pending = new Map()
  ws.addEventListener('message', (e) => {
    const m = JSON.parse(e.data)
    if (m.id && pending.has(m.id)) (pending.get(m.id)(m), pending.delete(m.id))
  })
  const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })) })
  const evaluate = async (expression) => {
    const m = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
    if (m.result?.exceptionDetails) throw new Error(JSON.stringify(m.result.exceptionDetails))
    return m.result?.result?.value
  }
  return { send, evaluate, close: () => ws.close() }
}

// Resolves true once no CSS transition is still running on the page. Flipping the theme starts colour
// transitions and axe reads the colour it sees at that instant, so a scan taken mid transition measures
// a blend of the two themes (a settled light chip is 5.67 to 1, mid blend it is 1.4 to 3.7). A fixed
// sleep only guesses how long that takes. Looping animations such as the status dots never end, so
// only CSSTransition counts. False means it gave up after about 5 seconds, which a caller must fail on.
const SETTLED_JS = `(async () => {
  const live = () => document.getAnimations().filter((a) => a instanceof CSSTransition && (a.playState === 'running' || a.playState === 'pending'))
  for (let i = 0; i < 100; i++) {
    if (live().length === 0) {
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))
      if (live().length === 0) return true
    }
    await new Promise((r) => setTimeout(r, 50))
  }
  return false
})()`

const skip = browserGate({ chrome: CHROME, dist: DIST })

test('axe finds no critical or serious violation in the light and dark theme', { skip, timeout: 120000 }, async () => {
  const srv = await serve()
  const browser = await sharedBrowser(CHROME)
  const tab = await openTab(browser)
  try {
    const s = await cdpSession(browser.port, tab.wsUrl)
    await s.send('Page.enable')
    for (const theme of ['light', 'dark']) {
      await s.send('Page.navigate', { url: `http://127.0.0.1:${srv.address().port}/index.html#/` })
      await sleep(2500)
      await s.evaluate(`localStorage.setItem('shell.theme', '${theme}'); document.documentElement.setAttribute('data-theme', '${theme}'); true`)
      assert.equal(await s.evaluate(SETTLED_JS), true, `${theme} theme: the page did not stop transitioning`)
      const rendered = await s.evaluate(`document.querySelectorAll('#root *').length`)
      assert.ok(rendered > 20, `${theme} theme: the shell did not render (${rendered} elements)`)
      await s.evaluate(AXE_SRC + '; true')
      const found = await s.evaluate(`axe.run(document, { resultTypes: ['violations'] }).then(r => r.violations.filter(v => v.impact === 'critical' || v.impact === 'serious').map(v => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, target: v.nodes[0].target.join(' ') })))`)
      assert.deepEqual(found, [], `${theme} theme: ${JSON.stringify(found)}`)
    }
    s.close()
  } finally {
    await closeTab(browser, tab.id)
    srv.close()
  }
})
