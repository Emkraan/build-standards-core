// Date: 2026-11-25
// Purpose: item 10 of issue 376. Each table of the parity spec (issue 327, section 5) is rendered by the built app from a fake /api and read back
// from the page: the heading cells in order, and the width of every column that declares one. tableColumns.test.mjs reads the source, this reads
// what the browser drew, so a column that is declared but never drawn, or drawn at another width, fails here.
// Run: npm run build && OPSCENTER_BROWSER_TESTS=1 CHROME_BIN=<chrome> node --test tests/renderedTables.test.mjs
// One local server serves dist/, the fake /api and the fake data/ files. Own Chrome tab in the shared browser (tests/sharedBrowser.mjs).
// Skips with a stated reason when dist/ or Chrome is missing on a machine with no browser provided, and fails in CI (tests/browserGate.mjs).
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { createServer } from 'node:http'
import { dirname, extname, join, normalize } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { browserGate } from './browserGate.mjs'
import { closeTab, openTab, sharedBrowser } from './sharedBrowser.mjs'
import { FLEX, SPEC } from './tableSpec.mjs'

const APP = join(dirname(fileURLToPath(import.meta.url)), '..')
const DIST = join(APP, 'dist')
const CHROME =
  process.env.CHROME_BIN ||
  ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium'].find((p) => existsSync(p)) ||
  '/usr/bin/google-chrome'
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.json': 'application/json', '.woff2': 'font/woff2' }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const skip = browserGate({ chrome: CHROME, dist: DIST })

// ---- fixtures: what each page is given. Anything not listed answers 404, which the shell treats as "not configured". ----
const engItem = (n, extra = {}) => ({
  uid: `td-00000${n}`, id: `TD-${n}`, kind: 'TD', title: `Debt entry ${n}`, line: n, status: 'open', outcome: 'open', bucket: 'todo',
  severity: 'medium', goals: ['G1'], effort: 'small', owner: '', date: `2026-11-0${n}`, body: '', snoozed: null, children: [], ...extra,
})
const jiraItem = (key, summary, extra = {}) => ({
  key, summary, status: 'To Do', status_category: 'new', issuetype: 'Task', priority: 'Medium', points: 3, assignee: 'Avery Stone', assignee_id: 'a1',
  parent_key: '', parent_summary: '', updated: '2026-11-09T12:00:00Z', due: '', carry: 0, planned_sprint: null, url: `https://example.test/browse/${key}`, ...extra,
})
const FIXTURES = {
  api: {
    '/api/one-on-ones': { generated_utc: '2026-11-10T12:00:00Z', people: [], sources: { agenda_items: 0, calendar_ok: true } },
    '/api/ac-routing': {
      rules: [], sources: { teams: 'Teams', mail: 'Mail' }, defaults: {}, people: {}, error: null,
      report: {
        generated_utc: '2026-11-10T12:00:00Z', considered: 2,
        considered_list: [
          { cid: 'c1', source: 'teams', actor: 'Avery Stone', title: 'A message I must consider', received: '2026-11-09T12:00:00Z', rule: 'default' },
          { cid: 'c2', source: 'mail', actor: 'Casey Lane', title: 'A mail I must consider', received: '2026-11-09T13:00:00Z', rule: 'default' },
        ],
        routed_away: [], items_routed_away: [], unregistered: [], errors: [],
      },
    },
    '/api/jira/needs-me': { generated_utc: '2026-11-10T12:00:00Z', count: 0, items: [] },
    '/api/jira/sprint': { generated_utc: '2026-11-10T12:00:00Z', sprint: { id: 2, name: 'Sprint 2', board_id: 1, start: '2026-10-15', end: '2026-10-28' }, me: 'Sam Owner', items: [] },
    '/api/jira/approvals': { generated_utc: '2026-11-10T12:00:00Z', pending: [], inflight: [] },
    '/api/jira/backlog': {
      generated_utc: '2026-11-10T12:00:00Z',
      active_sprint: { id: 2, name: 'Sprint 2', board_id: 1, start: '2026-10-15', end: '2026-10-28' },
      count: 2,
      items: [
        jiraItem('ITEA-11', 'A planned backlog item', { planned_sprint: { id: 2, name: 'Sprint 2' } }),
        jiraItem('ITEA-12', 'An unplanned backlog item', { priority: 'Highest', points: null }),
      ],
    },
    '/api/infra/spend': {
      generated_utc: '2026-11-10T12:00:00Z', sessions: 3, estimated_sessions: 0, ledger_since_utc: '2026-10-01T00:00:00Z', rate_basis_days: 7,
      months: [{ month: '2026-10', cron: 5, interactive: 3, total: 8, billed: 4, included: 3, unattributed: 1, sessions: 3, jobs: [] }],
      totals: {
        today: 1, d7: 5, d30: 8, mtd: 8, cron_d7: 4, interactive_d7: 1, projected_month: 20, billed_rate_per_day: 0.5, billed_projected_month: 15,
        billed_today: 0.5, included_today: 0.3, unattributed_today: 0.2, billed_d7: 3, included_d7: 1.5, unattributed_d7: 0.5, billed_mtd: 4, included_mtd: 3, unattributed_mtd: 1,
        cron_billed_d7: 2, cron_included_d7: 1, cron_unattributed_d7: 1, interactive_billed_d7: 1, interactive_included_d7: 0.5, interactive_unattributed_d7: 0,
      },
      daily: [{ date: '2026-11-09', cron: 1, interactive: 0.5, billed: 0.5, included: 0.5, unattributed: 0.5 }],
      jobs: [{ id: 'j1', name: 'Nightly sweep', runs_d7: 7, cost_d7: 2, per_run_d7: 0.29, cost_today: 0.3, cost_d30: 8, active: true, billed_d7: 1.5, billed_today: 0.2, included_d7: 0.4, unattributed_d7: 0.1, fallback_runs_d7: 1 }],
    },
    '/api/infra/accounts': {
      generated_utc: '2026-11-10T12:00:00Z',
      accounts: [{
        credential: 'team-1', priority: 1, kind: 'claude_team', kind_label: 'Claude Team', org: 'Org', seat_tier: null, rate_limit_tier: null, limits: [],
        spend: null, pool_status: null, pool_error: null, pool_reset_at: null, cooling_down: false, routing: true, fetched_utc: '2026-11-10T12:00:00Z', error: null,
        tokens: {
          session: { calls: 4, input: 1000, output: 500, cache_read: 2000, cache_write: 300, total: 3800 },
          week: { calls: 40, input: 10000, output: 5000, cache_read: 20000, cache_write: 3000, total: 38000 },
          today: { calls: 8, input: 2000, output: 1000, cache_read: 4000, cache_write: 600, total: 7600 },
        },
      }],
      ledger: { since_utc: '2026-10-01T00:00:00Z', rows: 10, unattributed_d7: { calls: 0, total: 0, aux_calls: 0 } },
    },
    '/api/eng-backlog': { generated_utc: '2026-11-10T12:00:00Z', counts: {}, items: [engItem(1, { severity: 'high' }), engItem(2, { severity: 'high', effort: 'large' }), engItem(3, { severity: 'low' })] },
  },
  data: {
    'action-center.json': {
      headline: 'One item needs me.', generated_utc: '2026-11-10T12:00:00Z', dropped: [],
      items: [{ fp: 'fp-1', key: 'k1', priority: 'high', title: 'Decide the thing', why: 'It blocks a release.', action: 'Pick one.', owner: 'Avery Stone', refs: ['ITEA-1'], sources: ['teams'] }],
    },
    'team-performance.json': {
      generated_utc: '2026-11-10T12:00:00Z',
      sprints: ['Sprint 1', 'Sprint 2'],
      sprint_ids: [1, 2],
      sprint_meta: { 'Sprint 1': { name: 'Sprint 1', start: '2026-10-01', end: '2026-10-14' }, 'Sprint 2': { name: 'Sprint 2', start: '2026-10-15', end: '2026-10-28' } },
      engineers: ['Avery Stone'],
      metrics: {
        'Avery Stone': {
          assigned: 10, done: 8, completion_pct: 80, points_committed: 20, points_delivered: 16,
          per_sprint: {
            'Sprint 1': { assigned: 5, done: 4, points_committed: 10, points_delivered: 8 },
            'Sprint 2': { assigned: 5, done: 4, points_committed: 10, points_delivered: 8 },
          },
          carryover: [{ key: 'ITEA-1', status: 'In Progress', summary: 'Carried item' }],
          not_done: [{ key: 'ITEA-2', status: 'In Progress', priority: 'High', points: 3, summary: 'An open item' }],
          rejected: [],
          lead_time: { n: 4, median_days: 3, fresh_median_days: 2, aged_backlog_cleared: [] },
          mid_cycle_intake: 1, high_priority: { assigned: 2, done: 1 }, issue_types: { Task: 10 },
        },
      },
      narrative: { 'Avery Stone': { verdict: 'Steady.', strengths: ['Reliable'], watch: [], blocked_on_me: [] } },
      action_items: { 'Avery Stone': [] },
      team_summary: 'A steady window.',
      drafts: [],
    },
    'history-master.json': {
      schema: 3,
      run_count: 1,
      runs: [
        {
          run_key: '2026-10', assessed_utc: '2026-10-29T12:00:00Z', sprints: ['Sprint 1'], sprint_ids: [1], period_start: '2026-10-01', period_end: '2026-10-14', year: '2026', month: 'October', team_summary: 'Fine.',
          engineers: [{
            name: 'Avery Stone', entra_id: null, title: null, assigned: 5, done: 4, completion_pct: 80, points_committed: 10, points_delivered: 8, carryover: 1, open: 1,
            mid_cycle_intake: 0, high_assigned: 1, high_done: 1, median_lead_fresh: 2, aged_backlog_cleared: 0, verdict: 'Steady.',
          }],
        },
      ],
    },
  },
}

function serve() {
  const json = (res, code, body) => res.writeHead(code, { 'content-type': 'application/json' }).end(JSON.stringify(body))
  const srv = createServer((req, res) => {
    const path = normalize(decodeURIComponent((req.url || '/').split('?')[0]))
    if (path.startsWith('/api/')) return FIXTURES.api[path] === undefined ? json(res, 404, { error: 'not found' }) : json(res, 200, FIXTURES.api[path])
    if (path.startsWith('/data/')) return FIXTURES.data[path.slice(6)] === undefined ? json(res, 404, { error: 'not found' }) : json(res, 200, FIXTURES.data[path.slice(6)])
    const file = join(DIST, path === '/' || path === '.' ? 'index.html' : path)
    if (!file.startsWith(DIST) || !existsSync(file)) return res.writeHead(404).end()
    res.writeHead(200, { 'content-type': TYPES[extname(file)] || 'application/octet-stream' }).end(readFileSync(file))
  })
  return new Promise((resolve) => srv.listen(0, '127.0.0.1', () => resolve(srv)))
}

async function cdpSession(wsUrl) {
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
      id += 1
      pending.set(id, r)
      ws.send(JSON.stringify({ id, method, params }))
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

// Every table on the page: its heading cells (textContent, so the capitals the style draws do not count) and the rendered width of each.
const READ_TABLES = `[...document.querySelectorAll('table')].map((t) => ({
  headings: [...t.querySelectorAll('thead th')].map((th) => th.textContent.trim()),
  widths: [...t.querySelectorAll('thead th')].map((th) => th.getBoundingClientRect().width),
  declared: [...t.querySelectorAll('thead th')].map((th) => th.style.width || ''),
  table: t.getBoundingClientRect().width,
}))`

async function render(route, ready) {
  const srv = await serve()
  const browser = await sharedBrowser(CHROME)
  const tab = await openTab(browser)
  try {
    const s = await cdpSession(tab.wsUrl)
    await s.send('Page.enable')
    await s.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false })
    await s.send('Page.navigate', { url: `http://127.0.0.1:${srv.address().port}/index.html#${route}` })
    await s.waitFor(`document.querySelectorAll('#root *').length > 20`, 'the shell to render')
    await s.evaluate(`(localStorage.setItem('shell.theme', 'light'), document.documentElement.setAttribute('data-theme', 'light'), true)`)
    try {
      await s.waitFor(ready, `${route} to draw its table`, 8000)
    } catch (e) {
      console.log('STUCK', route, JSON.stringify(await s.evaluate(`({ hash: location.hash, text: document.body.innerText.slice(0, 500), tables: document.querySelectorAll('table').length })`)))
      throw e
    }
    const tables = await s.evaluate(READ_TABLES)
    s.close()
    return tables
  } finally {
    await closeTab(browser, tab.id)
    srv.close()
  }
}

// The page each spec table lives on: where to load it, and how to know it has drawn.
const PAGES = {
  'components/ActionTable.tsx': { route: '/action', ready: `document.querySelectorAll('table thead th').length > 3` },
  'pages/ActionRouting.tsx': { route: '/action/routing', ready: `document.querySelectorAll('table thead th').length > 1` },
  'pages/Backlog.tsx': { route: '/work/backlog', ready: `document.querySelectorAll('table thead th').length > 3` },
  'pages/infra/Spend.tsx': { route: '/infra/spend', ready: `document.querySelectorAll('table').length >= 3` },
  'pages/EngBacklog.tsx': { route: '/debt', ready: `document.querySelectorAll('table thead th').length > 3` },
  'pages/TeamPerformance.tsx': { route: '/team', ready: `document.querySelectorAll('table thead th').length > 3` },
  'pages/TeamHistory.tsx': { route: '/team/history', ready: `document.querySelectorAll('table thead th').length > 3` },
}

// What a column of the spec must look like on the page. A flexible column declares no width and takes what is left. A px column declares it and, when the
// table has a flexible column to absorb the slack, is drawn at exactly that. A table of only px columns is stretched to fit, every column by the same factor.
// A percent column is drawn at that share of the table.
const TOLERANCE = 2
const px = (w) => (w.endsWith('px') ? Number.parseFloat(w) : null)
function checkTable(spec, rendered) {
  const label = `${spec.table}`
  assert.deepEqual(rendered.declared, spec.columns.map(([, w]) => (w === FLEX ? '' : w)), `${label}: each column declares the width the spec lists`)
  const fixedTotal = spec.columns.reduce((n, [, w]) => n + (px(w) ?? 0), 0)
  const allPx = spec.columns.every(([, w]) => px(w) !== null)
  const factor = allPx ? rendered.table / fixedTotal : 1
  spec.columns.forEach(([header, w], n) => {
    const got = rendered.widths[n]
    assert.ok(got > 0, `${label}: ${header || '(unlabelled)'} is drawn`)
    if (w === FLEX) return
    if (w.endsWith('%')) {
      const want = (Number.parseFloat(w) / 100) * rendered.table
      assert.ok(Math.abs(got - want) <= TOLERANCE, `${label}: ${header} is ${Math.round(got)}px, ${w} of the table is ${Math.round(want)}px`)
      return
    }
    const want = px(w) * (allPx ? factor : 1)
    assert.ok(Math.abs(got - want) <= TOLERANCE, `${label}: ${header} is ${Math.round(got)}px, the spec gives ${Math.round(want)}px${allPx && factor !== 1 ? ` (stretched by ${factor.toFixed(3)})` : ''}`)
  })
}

const byFile = Object.groupBy(SPEC, (t) => t.file)
for (const [file, specs] of Object.entries(byFile)) {
  test(`${file} draws ${specs.map((t) => t.table).join(', ')} as the spec lists`, { skip, timeout: 120000 }, async () => {
    const page = PAGES[file]
    assert.ok(page, `${file} has no entry in PAGES, so its spec tables cannot be rendered`)
    const tables = await render(page.route, page.ready)
    for (const spec of specs) {
      const want = spec.columns.map(([h]) => h)
      const found = tables.filter((t) => JSON.stringify(t.headings) === JSON.stringify(want))
      assert.ok(found.length > 0, `${spec.table}: no table on ${page.route} has the headings ${JSON.stringify(want)}. The page drew ${JSON.stringify(tables.map((t) => t.headings))}`)
      for (const t of found) checkTable(spec, t)
    }
  })
}

test('every spec table has a rendered page', () => {
  for (const file of Object.keys(byFile)) assert.ok(PAGES[file], `${file} is in the spec but has no rendered page`)
  for (const file of Object.keys(PAGES)) assert.ok(byFile[file], `${file} is rendered but is not in the spec, so the entry is stale`)
})
