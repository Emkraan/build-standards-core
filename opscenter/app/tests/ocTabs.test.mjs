// Page-level accessibility and hide rules of the ops center tabs that read an optional provider: Docs drift (Knowledge),
// the sprint trend and the closed sprints (Jira) and Live automation (Operations). Each page is rendered from a fake /api in
// the light and the dark theme and checked with axe-core (no critical or serious violation), and each is proved hidden when
// its provider is not configured.
// Run: npm run build && node --test tests/ocTabs.test.mjs
// One local server serves dist/ and the fake /api, so nothing reaches a real backend. Own Chrome port and profile dir.
// Skips with a stated reason when dist/ or Chrome is missing on a machine with no browser provided; in CI, or with
// CHROME_BIN set, it fails instead (tests/browserGate.mjs).
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
const CHROME =
  process.env.CHROME_BIN ||
  ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium'].find((p) => existsSync(p)) ||
  '/usr/bin/google-chrome'
const AXE_SRC = readFileSync(createRequire(import.meta.url).resolve('axe-core/axe.min.js'), 'utf8')
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.json': 'application/json', '.woff2': 'font/woff2' }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// ---- fixtures: what each provider answers. A null fixture is a provider that is not configured (the server has no route: 404). ----
const driftRow = (n, extra = {}) => ({
  thing: `app-${n}`,
  page: `page-${n}`,
  title: `Runbook ${n}`,
  link: `https://example.invalid/docs/${n}`,
  basis: 'footer-commit',
  since: '2026-11-01T00:00:00Z',
  commits: 10 - n,
  files: [`src/mod${n}.py`],
  files_total: 1,
  edited: '2026-10-20T00:00:00Z',
  status: 'behind',
  detail: '',
  ...extra,
})
const DRIFT = {
  fetched_utc: '2026-11-10T12:00:00+00:00',
  run: { id: 4242, created: '2026-11-10T06:00:00Z', head: 'abcdef0123456789', url: 'https://example.invalid/runs/4242' },
  counts: { behind: 2, current: 5, 'no-footer': 1 },
  bases: { 'footer-commit': 7 },
  total: 8,
  behind: [driftRow(1), driftRow(2)],
  behind_total: 2,
  no_verdict: [driftRow(3, { status: 'no-footer', basis: 'none', commits: 0 })],
  facts: [
    {
      thing: 'app-1',
      name: 'App One',
      version: '1.2.0',
      latest_release: '1.2.0',
      home: 'https://example.invalid/home',
      readme: { status: 'current' },
      changelog: { status: 'gaps', missing: ['1.1.0'] },
    },
  ],
  preview: null,
  pending_run: null,
  errors: 0,
  error: null,
  refreshing: false,
}

// ---- OC-18 fixtures: the sprint trend, the closed list and one closed sprint (the server answers only ids from the list) ----
const sprintRow = (id, n, extra = {}) => ({
  id,
  name: `Sprint ${id}`,
  start: `2026-0${n}-01T00:00:00Z`,
  end: `2026-0${n}-14T00:00:00Z`,
  active: false,
  items: 10 + n,
  done: 8 + n,
  points: 20 + n,
  points_done: 15 + n,
  carried: 2,
  ...extra,
})
const TREND = { generated_utc: '2026-11-10T12:00:00Z', sprints: [sprintRow(31, 8), sprintRow(32, 9), sprintRow(33, 10, { active: true, done: 3 })] }
const CLOSED = {
  generated_utc: '2026-11-10T12:00:00Z',
  sprints: [31, 32].map((id) => ({ id, name: `Sprint ${id}`, start: '2026-09-01T00:00:00Z', end: '2026-09-14T00:00:00Z', complete: '2026-09-15T00:00:00Z' })),
}
const jiraItem = (key, status_category, mine, extra = {}) => ({
  key,
  summary: `Ticket ${key}`,
  status: status_category === 'done' ? 'Done' : 'In Progress',
  status_category,
  issuetype: 'Task',
  priority: 'Medium',
  points: 3,
  assignee: 'Fixture Person',
  assignee_id: 'u1',
  parent_key: '',
  parent_summary: '',
  updated: '2026-09-10T00:00:00Z',
  due: '',
  carry: 0,
  planned_sprint: null,
  url: `https://example.invalid/browse/${key}`,
  mine,
  ...extra,
})
const CLOSED_ONE = {
  generated_utc: '2026-11-10T12:00:00Z',
  sprint: { id: 31, name: 'Sprint 31', board_id: 1, start: '2026-09-01T00:00:00Z', end: '2026-09-14T00:00:00Z' },
  me: 'u1',
  items: [jiraItem('FIX-1', 'done', true), jiraItem('FIX-2', 'indeterminate', false), jiraItem('FIX-3', 'done', false)],
}
const ACTIVE = { generated_utc: '2026-11-10T12:00:00Z', sprint: { id: 33, name: 'Sprint 33', board_id: 1, start: '2026-11-01T00:00:00Z', end: '2026-11-14T00:00:00Z' }, me: 'u1', items: [jiraItem('FIX-9', 'indeterminate', true)] }

const FIXTURES = { drift: DRIFT, trend: TREND, closed: CLOSED, closedOne: CLOSED_ONE, active: ACTIVE }

function fakeBackend(fx) {
  const json = (res, code, body) => res.writeHead(code, { 'content-type': 'application/json' }).end(JSON.stringify(body))
  return (req, res, path) => {
    if (!path.startsWith('/api/')) return false
    const url = new URL(req.url, 'http://x')
    const table = {
      '/api/docs-drift': fx.drift,
      '/api/jira/sprint-trend': fx.trend,
      '/api/jira/sprints': fx.closed,
      '/api/jira/sprint': url.searchParams.get('id') ? fx.closedOne : fx.active,
    }
    const body = table[path]
    if (body === undefined || body === null) return json(res, 404, { error: 'not found' }), true
    return json(res, 200, body), true
  }
}

function serve(backend) {
  const srv = createServer((req, res) => {
    const path = normalize(decodeURIComponent((req.url || '/').split('?')[0]))
    if (backend(req, res, path)) return
    const file = join(DIST, path === '/' || path === '.' ? 'index.html' : path)
    if (!file.startsWith(DIST) || !existsSync(file)) return res.writeHead(404).end()
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
    if (m.id && pending.has(m.id)) {
      pending.get(m.id)(m)
      pending.delete(m.id)
    }
  })
  const send = (method, params = {}) =>
    new Promise((r) => {
      const i = ++id
      pending.set(i, r)
      ws.send(JSON.stringify({ id: i, method, params }))
    })
  const evaluate = async (expression) => {
    const m = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
    if (m.result?.exceptionDetails) throw new Error(JSON.stringify(m.result.exceptionDetails))
    return m.result?.result?.value
  }
  const waitFor = async (expression, what, ms = 10000) => {
    const end = Date.now() + ms
    while (Date.now() < end) {
      if (await evaluate(expression)) return
      await sleep(100)
    }
    throw new Error(`timed out waiting for ${what}`)
  }
  return { send, evaluate, waitFor, close: () => ws.close() }
}

const skip = browserGate({ chrome: CHROME, dist: DIST })

async function withApp(fx, body) {
  const srv = await serve(fakeBackend(fx))
  const profile = mkdtempSync(join(tmpdir(), 'oc-tabs-chrome-'))
  const port = 9300 + Math.floor(Math.random() * 400)
  const chrome = spawn(CHROME, chromeArgs({ port, profile }), { stdio: 'ignore', detached: true })
  const exited = new Promise((r) => chrome.once('exit', r))
  try {
    const s = await cdpSession(port)
    await s.send('Page.enable')
    const origin = `http://127.0.0.1:${srv.address().port}/index.html`
    await body(s, origin)
    s.close()
  } finally {
    try {
      process.kill(-chrome.pid, 'SIGKILL')
    } catch {
      chrome.kill('SIGKILL')
    }
    await Promise.race([exited, new Promise((r) => setTimeout(r, 5000))])
    srv.close()
    try {
      rmSync(profile, { recursive: true, force: true, maxRetries: 20, retryDelay: 100 })
    } catch (e) {
      console.warn(`could not remove the browser profile ${profile}: ${e.code || e.message}`)
    }
  }
}

// Open a route in a theme and wait until `ready` (an expression) is true.
async function visit(s, origin, route, theme, ready, what) {
  await s.send('Page.navigate', { url: `${origin}#${route}` })
  await s.waitFor(`document.querySelectorAll('#root *').length > 20`, 'the shell to render')
  await s.evaluate(`localStorage.setItem('shell.theme', '${theme}'); document.documentElement.setAttribute('data-theme', '${theme}'); true`)
  await s.waitFor(ready, what)
  await sleep(400)
}

async function axeFindings(s) {
  await s.evaluate(`${AXE_SRC}; true`)
  return s.evaluate(
    `axe.run(document, { resultTypes: ['violations'] }).then(r => r.violations.filter(v => v.impact === 'critical' || v.impact === 'serious').map(v => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, target: v.nodes[0].target.join(' ') })))`,
  )
}

const hasText = (text) => `document.body.innerText.includes(${JSON.stringify(text)})`
const hasTab = (label) => `[...document.querySelectorAll('[role="tab"]')].some((t) => t.textContent.trim().startsWith(${JSON.stringify(label)}))`

// ---- OC-10: Docs drift ----
test('the Docs drift tab shows the newest drift report and has no axe violation in either theme', { skip, timeout: 120000 }, async () => {
  await withApp(FIXTURES, async (s, origin) => {
    for (const theme of ['light', 'dark']) {
      await visit(s, origin, '/knowledge/drift', theme, hasText('Runbook 1'), 'the drift rows')
      assert.ok(await s.evaluate(hasText('Pages behind the code')), `${theme}: the behind table has its heading`)
      assert.ok(await s.evaluate(hasText('Pages with no verdict')), `${theme}: the no verdict table is shown`)
      assert.ok(await s.evaluate(hasTab('Docs drift')), `${theme}: the tab is in the hub`)
      const found = await axeFindings(s)
      assert.deepEqual(found, [], `${theme} theme: ${JSON.stringify(found)}`)
    }
  })
})

test('the Docs drift tab is hidden when no provider is configured, and its route lands on Proposals', { skip, timeout: 60000 }, async () => {
  await withApp({ ...FIXTURES, drift: null }, async (s, origin) => {
    await visit(s, origin, '/knowledge/drift', 'light', `location.hash === '#/knowledge' && ${hasTab('Proposals')}`, 'the redirect to Proposals')
    assert.equal(await s.evaluate(hasTab('Docs drift')), false, 'no Docs drift tab without a provider')
  })
})

// ---- OC-18: sprint trend card and closed sprints ----
test('the sprint trend card and the closed sprints tab have no axe violation in either theme', { skip, timeout: 120000 }, async () => {
  await withApp(FIXTURES, async (s, origin) => {
    for (const theme of ['light', 'dark']) {
      await visit(s, origin, '/jira', theme, hasText('Sprint trend') && hasText('Items in sprint'), 'the sprint trend card')
      assert.ok(await s.evaluate(hasTab('Closed sprints')), `${theme}: the Closed sprints tab is in the hub`)
      let found = await axeFindings(s)
      assert.deepEqual(found, [], `${theme} theme, Sprint tab: ${JSON.stringify(found)}`)
      await visit(s, origin, '/jira/closed', theme, hasText('Closed sprints') && hasText('Sprint 32'), 'the closed sprint list')
      found = await axeFindings(s)
      assert.deepEqual(found, [], `${theme} theme, closed list: ${JSON.stringify(found)}`)
      await visit(s, origin, '/jira/closed/31', theme, hasText('FIX-2'), 'the closed sprint items')
      assert.ok(await s.evaluate(hasText('read only')), `${theme}: the view says it is read only`)
      found = await axeFindings(s)
      assert.deepEqual(found, [], `${theme} theme, closed sprint: ${JSON.stringify(found)}`)
    }
  })
})

test('the sprint trend card and the closed sprints tab are hidden when the tracker has no sprint source', { skip, timeout: 60000 }, async () => {
  await withApp({ ...FIXTURES, trend: null, closed: null }, async (s, origin) => {
    await visit(s, origin, '/jira', 'light', hasText('FIX-9'), 'the active sprint')
    assert.equal(await s.evaluate(hasText('Sprint trend')), false, 'no trend card without a sprint source')
    assert.equal(await s.evaluate(hasTab('Closed sprints')), false, 'no Closed sprints tab without a sprint source')
    await visit(s, origin, '/jira/closed', 'light', `location.hash === '#/jira'`, 'the redirect to the Sprint tab')
  })
})

test('an id that is not in the closed list never opens a sprint view', { skip, timeout: 60000 }, async () => {
  await withApp(FIXTURES, async (s, origin) => {
    await visit(s, origin, '/jira/closed/999', 'light', hasText('not one of the recent closed sprints'), 'the refusal')
    assert.equal(await s.evaluate(hasText('FIX-1')), false, 'no ticket of any sprint is shown')
  })
})
