// Accessibility gate (web-ui.md 9): axe-core over the built shell in the light and the dark theme.
// Run: npm run build && node --test tests/axe.test.mjs
// Serves dist/ on a random local port and drives a headless Chrome of its own over the DevTools
// protocol (own port, own profile dir). Skips with a stated reason when dist/ or Chrome is missing on a machine with no browser provided.
// In CI, or with CHROME_BIN set, it fails instead (tests/browserGate.mjs).
// Fails on any critical or serious axe violation.
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { createServer } from 'node:http'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { dirname, extname, join, normalize } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { browserGate, chromeArgs } from './browserGate.mjs'

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

async function cdpSession(port) {
  let wsUrl
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

const skip = browserGate({ chrome: CHROME, dist: DIST })

test('axe finds no critical or serious violation in the light and dark theme', { skip, timeout: 120000 }, async () => {
  const srv = await serve()
  const profile = mkdtempSync(join(tmpdir(), 'axe-chrome-'))
  const port = 9400 + Math.floor(Math.random() * 400)
  const chrome = spawn(CHROME, chromeArgs({ port, profile }), { stdio: 'ignore' })
  try {
    const s = await cdpSession(port)
    await s.send('Page.enable')
    for (const theme of ['light', 'dark']) {
      await s.send('Page.navigate', { url: `http://127.0.0.1:${srv.address().port}/index.html#/` })
      await sleep(2500)
      await s.evaluate(`localStorage.setItem('shell.theme', '${theme}'); document.documentElement.setAttribute('data-theme', '${theme}'); true`)
      await sleep(300)
      const rendered = await s.evaluate(`document.querySelectorAll('#root *').length`)
      assert.ok(rendered > 20, `${theme} theme: the shell did not render (${rendered} elements)`)
      await s.evaluate(AXE_SRC + '; true')
      const found = await s.evaluate(`axe.run(document, { resultTypes: ['violations'] }).then(r => r.violations.filter(v => v.impact === 'critical' || v.impact === 'serious').map(v => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, target: v.nodes[0].target.join(' ') })))`)
      assert.deepEqual(found, [], `${theme} theme: ${JSON.stringify(found)}`)
    }
    s.close()
  } finally {
    chrome.kill('SIGKILL')
    srv.close()
    rmSync(profile, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 })
  }
})
