// Client action rules on the real built app, driven in a headless Chrome of its own.
// Run: npm run build && node --test tests/liveActions.test.mjs
// One local server serves dist/ and a fake /api (team reviews only), so nothing reaches a real
// backend. Own Chrome port and profile dir. Skips with a stated reason when dist/ or Chrome is missing on a machine with no browser provided.
// In CI, or with CHROME_BIN set, it fails instead (tests/browserGate.mjs).
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { createServer } from 'node:http'
import { tmpdir } from 'node:os'
import { dirname, extname, join, normalize } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { browserGate, chromeArgs } from './browserGate.mjs'

const APP = join(dirname(fileURLToPath(import.meta.url)), '..')
const DIST = join(APP, 'dist')
// CI runners carry Chrome under /usr/bin, a Mac carries it under /Applications. The first one present wins.
const CHROME = process.env.CHROME_BIN || ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium'].find((path) => existsSync(path)) || '/usr/bin/google-chrome'
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.json': 'application/json', '.woff2': 'font/woff2' }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const SHA = (c) => c.repeat(40)

const pr = (n, extra = {}) => ({
  pr: n,
  title: `Fixture PR ${n}`,
  url: `https://example.invalid/pr/${n}`,
  author: 'engineer',
  mine: false,
  head_sha: SHA(String(n % 10)),
  branch: `b${n}`,
  draft: false,
  mergeable: 'MERGEABLE',
  checks: { red: [], pending: [], total: 3 },
  kind: 'escalated',
  why: 'fixture',
  rules: [],
  ...extra,
})

function reviews(needs) {
  return {
    generated_utc: '2026-10-27T12:00:00Z',
    repo: 'team',
    needs_me: needs,
    in_progress: [],
    shipped: [],
    counts: { needs_me: needs.length, in_progress: 0, shipped: 0 },
  }
}

// state.needs is what the fake backend serves on every GET. state.stale = keep serving the old list
// after an action, to prove the client does not wait for a refetch to drop the row.
function fakeBackend(state) {
  const json = (res, code, body) => res.writeHead(code, { 'content-type': 'application/json' }).end(JSON.stringify(body))
  return (req, res, path) => {
    if (!path.startsWith('/api/')) return false
    state.calls.push(`${req.method} ${path}`)
    if (path === '/api/team_prefix-reviews' && req.method === 'GET') return json(res, 200, reviews(state.needs)), true
    if (/^\/api\/team_prefix-reviews\/(approve|merge)$/.test(path) && req.method === 'POST') {
      let body = ''
      req.on('data', (c) => {
        body += c
      })
      req.on('end', () => {
        const { pr: n } = JSON.parse(body || '{}')
        state.acted.push(n)
        if (!state.stale) state.needs = state.needs.filter((p) => p.pr !== n)
        json(res, 200, { pr: n, done: ['ok'] })
      })
      return true
    }
    return json(res, 404, { error: 'not in fixture' }), true
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
    if (m.id && pending.has(m.id)) (pending.get(m.id)(m), pending.delete(m.id))
  })
  const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })) })
  const evaluate = async (expression) => {
    const m = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
    if (m.result?.exceptionDetails) throw new Error(JSON.stringify(m.result.exceptionDetails))
    return m.result?.result?.value
  }
  const waitFor = async (expression, what, ms = 8000) => {
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

// In-page helpers, as one expression string. A row is the <article> whose title text names the PR.
const PAGE = `(() => {
  const rows = () => [...document.querySelectorAll('article.rh-item')]
  const row = (n) => rows().find((a) => a.querySelector('.rh-item-title')?.textContent.includes('Fixture PR ' + n))
  const actions = (a) => [...a.querySelectorAll('button, a.btn')]
  const label = (el) => el.textContent.trim()
  const enabled = (el) => !el.disabled && el.getAttribute('aria-disabled') !== 'true'
  const tail = (el) => (el ? Number((el.textContent.match(/(\\d+)\\s*$/) || [])[1] ?? 0) : null)
  const btn = (re) => [...document.querySelectorAll('button')].find((e) => re.test(e.textContent.trim()))
  // Every count the shell shows for this list: the sidebar Reviews badge, the team tab and the Needs me tab.
  const badges = () => ({
    sidebar: tail(document.querySelector('a[href="#/reviews"]')),
    team: tail(btn(/^team\\d*$/)),
    needs: tail(btn(/^Needs me\\d*$/)),
  })
  return { rows, row, actions, label, enabled, badges }
})()`

async function withApp(state, body) {
  const srv = await serve(fakeBackend(state))
  const profile = mkdtempSync(join(tmpdir(), 'live-actions-chrome-'))
  const port = 9800 + Math.floor(Math.random() * 400)
  // Own process group, so the cleanup can stop the browser's helper processes too, not only the parent.
  const chrome = spawn(CHROME, chromeArgs({ port, profile }), { stdio: 'ignore', detached: true })
  const exited = new Promise((r) => chrome.once('exit', r))
  try {
    const s = await cdpSession(port)
    await s.send('Page.enable')
    await s.send('Page.navigate', { url: `http://127.0.0.1:${srv.address().port}/index.html#/reviews/team/needs` })
    await s.waitFor(`document.querySelectorAll('article.rh-item').length > 0`, 'the team rows to render')
    await body(s)
    s.close()
  } finally {
    try {
      process.kill(-chrome.pid, 'SIGKILL')
    } catch {
      chrome.kill('SIGKILL')
    }
    await Promise.race([exited, new Promise((r) => setTimeout(r, 5000))])
    srv.close()
    // A helper process can still be flushing the profile for a moment. A leftover temp folder is not a
    // failure of the behaviour under test, so it is reported and the test result stands.
    try {
      rmSync(profile, { recursive: true, force: true, maxRetries: 20, retryDelay: 100 })
    } catch (e) {
      console.warn(`could not remove the browser profile ${profile}: ${e.code || e.message}`)
    }
  }
}

// core-rule: pr-review-and-merge.1.10
test('a PR with its working flag set renders no action button, only a link to the PR', { skip, timeout: 60000 }, async () => {
  const state = { calls: [], acted: [], needs: [pr(101, { working: true }), pr(102, { checks: { red: [], pending: ['ci'], total: 3 } }), pr(103)] }
  await withApp(state, async (s) => {
    const rows = await s.evaluate(`(() => { const p = ${PAGE}; return [101, 102, 103].map((n) => ({ n, labels: p.actions(p.row(n)).map(p.label), locked: !!p.row(n).querySelector('.rh-locked') })) })()`)
    const byN = Object.fromEntries(rows.map((r) => [r.n, r]))
    // 101 is flagged working by the server, 102 has checks running: both show the indicator and only Open PR.
    for (const n of [101, 102]) {
      assert.deepEqual(byN[n].labels, ['Open PR'], `PR ${n} must show only the PR link, got ${JSON.stringify(byN[n].labels)}`)
      assert.equal(byN[n].locked, true, `PR ${n} shows the working note`)
    }
    // The control: a PR that is not working still has its action button.
    assert.ok(byN[103].labels.includes('Approve as me'), `PR 103 keeps its button, got ${JSON.stringify(byN[103].labels)}`)
  })
})

// core-rule: live-actions.1.13
test('every needs-action fixture renders at least one enabled action', { skip, timeout: 60000 }, async () => {
  const kinds = { 201: 'escalated', 202: 'signoff', 203: 'ready_to_merge', 204: 'direction' }
  const needs = Object.entries(kinds).map(([n, kind]) => pr(Number(n), { kind, mine: kind !== 'escalated' }))
  const state = { calls: [], acted: [], needs }
  await withApp(state, async (s) => {
    const rows = await s.evaluate(`(() => { const p = ${PAGE}; return ${JSON.stringify(Object.keys(kinds).map(Number))}.map((n) => ({ n, enabled: p.actions(p.row(n)).filter(p.enabled).map(p.label) })) })()`)
    for (const r of rows) assert.ok(r.enabled.length > 0, `${kinds[r.n]} PR ${r.n} has no enabled action`)
    // The kinds that carry a decision button show it enabled (direction cards act through Discuss and the decision card).
    const labels = Object.fromEntries(rows.map((r) => [kinds[r.n], r.enabled]))
    assert.ok(labels.escalated.includes('Approve as me'))
    assert.ok(labels.signoff.includes('Approve and merge'))
    assert.ok(labels.ready_to_merge.includes('Merge'))
  })
})

// core-rule: live-actions.1.1
test('a successful action drops the row and its badge count before any refetch', { skip, timeout: 60000 }, async () => {
  // stale: the backend keeps serving the old list, so only the client store can have removed the row.
  const state = { calls: [], acted: [], stale: true, needs: [pr(301), pr(302)] }
  await withApp(state, async (s) => {
    assert.deepEqual(await s.evaluate(`${PAGE}.badges()`), { sidebar: 2, team: 2, needs: 2 }, 'every badge starts at 2')
    const getsBefore = state.calls.filter((c) => c === 'GET /api/team_prefix-reviews').length
    await s.evaluate(`(() => { const p = ${PAGE}; p.actions(p.row(301)).find((b) => p.label(b) === 'Approve as me').click(); return true })()`)
    // The confirm dialog: press its confirm button, labelled the same as the action.
    await s.waitFor(`!!document.querySelector('dialog[open], [role="dialog"], [role="alertdialog"]')`, 'the confirm dialog')
    await s.evaluate(`(() => { const d = document.querySelector('dialog[open], [role="dialog"], [role="alertdialog"]'); [...d.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Approve as me').click(); return true })()`)
    await s.waitFor(`!${PAGE}.row(301)`, 'the row to disappear')
    assert.deepEqual(state.acted, [301])
    const getsAfter = state.calls.filter((c) => c === 'GET /api/team_prefix-reviews').length
    assert.equal(getsAfter, getsBefore, 'the row went away with no refetch of the list')
    assert.ok(await s.evaluate(`!!${PAGE}.row(302)`), 'the other row stays')
    assert.deepEqual(await s.evaluate(`${PAGE}.badges()`), { sidebar: 1, team: 1, needs: 1 }, 'every badge dropped with the row')
    assert.ok(await s.evaluate(`document.body.innerText.includes('PR #301')`), 'the success flash shows')
  })
})
