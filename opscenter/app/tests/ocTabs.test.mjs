// Page-level accessibility and hide rules of the ops center tabs that read an optional provider: Docs drift (Knowledge),
// the sprint trend and the closed sprints (Jira) and Live automation (Operations). Each page is rendered from a fake /api in
// the light and the dark theme and checked with axe-core (no critical or serious violation), and each is proved hidden when
// its provider is not configured.
// Run: npm run build && node --test tests/ocTabs.test.mjs
// One local server serves dist/ and the fake /api, so nothing reaches a real backend. Own Chrome port and profile dir.
// Skips with a stated reason when dist/ or Chrome is missing on a machine with no browser provided; in CI, or with
// CHROME_BIN set, it fails instead (tests/browserGate.mjs).
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
  start: `2026-${String(n).padStart(2, '0')}-01T00:00:00Z`,
  end: `2026-${String(n).padStart(2, '0')}-14T00:00:00Z`,
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

// ---- OC-20 fixtures: one acting launch, one still dark. A launch is acting while its live switch reads on. ----
const launch = (id, live, status, extra = {}) => ({
  id,
  title: `Launch ${id}`,
  repo: 'owner/repo',
  environment: 'production',
  variable: `LAUNCH_${id.toUpperCase()}_ENABLED`,
  workflow: 'automation.yml',
  status,
  live,
  dry_run: { state: 'passed', at: '2026-11-09T12:00:00Z', url: 'https://example.invalid/runs/9' },
  can_dry_run: true,
  can_enable: live !== 'on',
  can_disable: live === 'on',
  ...extra,
})
const launches = () => ({ launches: [launch('alpha', 'on', 'enabled'), launch('beta', 'off', 'dark')], error: null })

// A configured tracker answers needs me and approvals even when nothing waits. `needsMe: null` is a tracker slot that is off (no routes, a 404).
const NEEDS_ME = { generated_utc: '2026-11-10T12:00:00Z', live_ok: true, live_error: '', count: 0, items: [] }
const APPROVALS = { generated_utc: '2026-11-10T12:00:00Z', pending: [], inflight: [] }
const engItem = (n, extra = {}) => ({
  uid: `td-00000${n}`,
  id: `TD-${n}`,
  kind: 'TD',
  title: `Debt entry ${n}`,
  line: n,
  status: 'open',
  outcome: 'open',
  bucket: 'todo',
  severity: 'medium',
  goals: ['G1'],
  effort: 'small',
  owner: '',
  date: '2026-11-0' + n,
  body: '',
  snoozed: null,
  children: [],
  ...extra,
})
const ENG = {
  generated_utc: '2026-11-10T12:00:00Z',
  counts: {},
  items: [
    engItem(1, { severity: 'high' }),
    engItem(2, { severity: 'high', effort: 'large' }),
    engItem(3, { severity: 'low', goals: ['G2'] }),
  ],
}
// What the server counts for the Action Center row: two open actions, one alert, one platform problem, three debt entries,
// and a builds feed with one run waiting on an environment approval.
const BADGES = {
  action_open: ['fp-1', 'fp-2'],
  debt: 3,
  knowledge: 0,
  alerts: 1,
  problems: { items: [], counts: { needs_me: 1, worth_a_look: 0, healthy: 0, running: 0, total: 1, by_section: { ci: 1 }, by_item: { ci: 1 } } },
  builds: { running: 2, waiting: 1 },
}
// Pull requests that need a decision from me, one lane each. Every field the lanes' own cards read is given a plain value.
const LANE_BASE = { generated_utc: '2026-11-10T12:00:00Z', in_progress: [], shipped: [], acted: [] }
const TEAM_PR = (pr, title, kind) => ({ pr, title, kind, url: `https://example.test/pull/${pr}`, author: 'someone', mine: false, head_sha: 'a'.repeat(40), draft: false, checks: {} })
const REPO_PR = (pr, title, kind) => ({ pr, title, kind, repo: 'ops_center', slug: 'ops_center', url: `https://example.test/pull/${pr}`, author: 'someone', mine: false, head_sha: 'b'.repeat(40), draft: false, updated: null })
const PLATFORM = { ...LANE_BASE, repo: 'platform', needs_me: [], counts: { needs_me: 1, in_progress: 0, shipped: 0 }, needs_me_rows: [{ kind: 'plan', pr: 12, title: 'Plan page', what: 'Approve the plan' }], my_prs: [] }
const TEAM = { ...LANE_BASE, repo: 'team', needs_me: [TEAM_PR(7, 'Fix the sync', 'escalated'), TEAM_PR(8, 'My own change', 'direction')], counts: { needs_me: 2, in_progress: 0, shipped: 0 } }
const REPOS = { generated_utc: '2026-11-10T12:00:00Z', counts: { needs_me: 1, in_progress: 0 }, repos: [{ repo: 'ops_center', slug: 'ops_center', error: null, needs_me: [REPO_PR(3, 'Red checks', 'checks')], in_progress: [], acted: [] }] }
// The consumer's builds feed. Times are epoch seconds relative to the real clock, since the panel ages rows against Date.now().
const nowS = () => Math.floor(Date.now() / 1000)
const BUILD = (id, title, state, over = {}) => ({ id, title, state, started: nowS() - 900, finished: null, activity: null, activity_at: null, outcome: null, url: null, kind: null, ...over })
const buildsFeed = (builds, error = null) => ({
  fetched_utc: '2026-11-19T15:00:00Z',
  counts: { running: builds.filter((x) => x.state === 'running').length, stuck: builds.filter((x) => x.state === 'stuck').length, failed: builds.filter((x) => x.state === 'failed').length, finished: builds.filter((x) => x.state === 'finished').length, total: builds.length },
  builds,
  truncated: 0,
  error,
})
const agentBuilds = () => buildsFeed([
  BUILD('b1', 'Fix the importer', 'running', { activity: 'running tests', activity_at: nowS() - 10 * 60 }),
  BUILD('b2', 'Docs pass', 'stuck', { activity_at: nowS() - 3 * 3600, url: 'https://example.test/session/b2' }),
  BUILD('b3', 'Old cleanup', 'finished', { finished: nowS() - 7200 }),
])
// Live tackle sessions in the shape GET /api/tackle returns, keyed by item. One is acting, one is history.
const tackleSessions = () => ({
  sessions: {
    fp1: { title: 'Tighten the importer', session: 's1', pid: 11, state: 'running', started: new Date(Date.now() - 20 * 60e3).toISOString(), last_active: new Date(Date.now() - 5 * 60e3).toISOString(), log: '', live: true, ticket: 'WORK-77' },
    fp2: { title: 'Old finished chat', session: 's2', pid: 12, state: 'finished', started: new Date(Date.now() - 9 * 3600e3).toISOString(), log: '', live: false },
  },
})
// GET /api/hermes-restart when plugins changed after the engine started: the banner shows its choices.
const RESTART_STALE = { alert: 'stale', safe: true, busy: [], quiet_s: 600, quiet_needed_s: 300, pending: null, running: null, last: null }
const extPages = () => [
  { id: 'reports', title: 'Reports', group: 'Operate', kind: 'list', url: null, lede: 'Reports waiting for a look' },
  { id: 'docs', title: 'Team docs', group: 'Knowledge', kind: 'link', url: 'https://docs.example.test/home', lede: null },
]
const extManifest = (pages = extPages(), error = null) => ({ fetched_utc: '2026-11-19T15:00:00Z', pages, truncated: 0, error })
const extRows = (page, rows, error = null) => ({ fetched_utc: '2026-11-19T15:00:00Z', page, rows, truncated: 0, error })
const EXT_ROWS = [
  { id: 'r1', title: 'Cache the group lookups', detail: 'Cuts the cold start', state: 'Open', url: 'https://tool.example.test/r1', at: '2026-11-18' },
  { id: 'r2', title: '<img src=x onerror=window.__pwned=1>', detail: null, state: null, url: null, at: null },
  { id: 'r3', title: 'A row with an unsafe address', detail: null, state: 'Open', url: null, at: null },
]
const fixtures = () => ({
  restart: null,
  tackle: tackleSessions(),
  extensions: null,
  extRows: null,
  agentBuilds: agentBuilds(),
  platform: PLATFORM,
  team: TEAM,
  repos: REPOS,
  badges: BADGES,
  eng: ENG,
  drift: DRIFT,
  trend: TREND,
  closed: CLOSED,
  closedOne: CLOSED_ONE,
  active: ACTIVE,
  needsMe: NEEDS_ME,
  approvals: APPROVALS,
  launches: launches(),
  posts: [],
})

function fakeBackend(fx) {
  const json = (res, code, body) => res.writeHead(code, { 'content-type': 'application/json' }).end(JSON.stringify(body))
  return (req, res, path) => {
    if (!path.startsWith('/api/')) return false
    const url = new URL(req.url, 'http://x')
    if (path === '/api/dark-launches/disable' && req.method === 'POST') {
      let raw = ''
      req.on('data', (c) => {
        raw += c
      })
      req.on('end', () => {
        const { id } = JSON.parse(raw || '{}')
        fx.posts.push(`disable ${id}`)
        const l = fx.launches.launches.find((x) => x.id === id)
        if (l) Object.assign(l, { live: 'off', status: 'dark', can_disable: false, can_enable: true })
        json(res, 200, { id, done: ['set the switch to false'] })
      })
      return true
    }
    if (path === '/api/phone-access/pair' && req.method === 'POST') {
      fx.posts.push('pair')
      return json(res, 200, { link: 'app://pair?code=SECRETCODE123', expires_in: 60 }), true
    }
    if ((path === '/api/phone-access/remove' || path === '/api/phone-access/test') && req.method === 'POST') {
      let raw = ''
      req.on('data', (c) => {
        raw += c
      })
      req.on('end', () => {
        fx.posts.push(`${path.split('/').pop()} ${JSON.stringify(JSON.parse(raw || '{}'))}`)
        json(res, 200, { ok: true })
      })
      return true
    }
    const extAct = path.match(/^\/api\/extensions\/([a-z0-9-]+)\/action$/)
    if (extAct && req.method === 'POST') {
      let raw = ''
      req.on('data', (c) => {
        raw += c
      })
      req.on('end', () => {
        fx.posts.push(`ext-action ${extAct[1]} ${JSON.stringify(JSON.parse(raw || '{}'))}`)
        json(res, 200, { ok: true, detail: 'Approved.' })
      })
      return true
    }
    const ext = path.match(/^\/api\/extensions\/([a-z0-9-]+)$/)
    if (ext && fx.extRows) {
      const out = typeof fx.extRows === 'function' ? fx.extRows(ext[1], Number(url.searchParams.get('offset') || 0)) : fx.extRows[ext[1]]
      if (!out) return json(res, 404, extRows(null, [], 'no such page')), true
      return json(res, out.error ? 502 : 200, out), true
    }
    const table = {
      '/api/llm-fallback': fx.fallback,
      '/api/extensions': fx.extensions,
      '/api/phone-access': fx.phone,
      '/api/dark-launches': fx.launches,
      '/api/badges': fx.badges,
      '/api/active-builds': fx.agentBuilds,
      '/api/tackle': fx.tackle,
      '/api/hermes-restart': fx.restart,
      '/api/platform-reviews': fx.platform,
      '/api/team-reviews': fx.team,
      '/api/repo-reviews': fx.repos,
      '/api/plans': fx.plans,
      '/api/eng-backlog': fx.eng,
      '/api/eng-backlog/curation': fx.curation,
      '/api/docs-drift': fx.drift,
      '/api/jira/sprint-trend': fx.trend,
      '/api/jira/sprints': fx.closed,
      '/api/jira/sprint': url.searchParams.get('id') ? fx.closedOne : fx.active,
      '/api/jira/needs-me': fx.needsMe,
      '/api/jira/approvals': fx.approvals,
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

async function withApp(fx, body) {
  const srv = await serve(fakeBackend(fx))
  const browser = await sharedBrowser(CHROME)
  const tab = await openTab(browser)
  try {
    const s = await cdpSession(browser.port, tab.wsUrl)
    await s.send('Page.enable')
    const origin = `http://127.0.0.1:${srv.address().port}/index.html`
    await body(s, origin)
    s.close()
  } finally {
    await closeTab(browser, tab.id)
    srv.close()
  }
}

// Open a route in a theme and wait until `ready` (an expression) is true.
async function visit(s, origin, route, theme, ready, what) {
  await s.send('Page.navigate', { url: `${origin}#${route}` })
  await s.waitFor(`document.querySelectorAll('#root *').length > 20`, 'the shell to render')
  await s.evaluate(`localStorage.setItem('shell.theme', '${theme}'); document.documentElement.setAttribute('data-theme', '${theme}'); true`)
  await s.waitFor(ready, what)
  assert.equal(await s.evaluate(SETTLED_JS), true, `${route}: the page did not stop transitioning`)
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
  await withApp(fixtures(), async (s, origin) => {
    for (const theme of ['light', 'dark']) {
      await visit(s, origin, '/knowledge/drift', theme, hasText('Runbook 1'), 'the drift rows')
      assert.ok(await s.evaluate(hasText('Pages behind the code')), `${theme}: the behind table has its heading`)
      assert.ok(await s.evaluate(hasText('Pages with no verdict')), `${theme}: the no verdict table is shown`)
      assert.ok(await s.evaluate(hasTab('Doc drift')), `${theme}: the tab is in the hub`)
      const found = await axeFindings(s)
      assert.deepEqual(found, [], `${theme} theme: ${JSON.stringify(found)}`)
    }
  })
})

test('the Docs drift tab is hidden when no provider is configured, and its route lands on Proposals', { skip, timeout: 60000 }, async () => {
  await withApp({ ...fixtures(), drift: null }, async (s, origin) => {
    await visit(s, origin, '/knowledge/drift', 'light', `location.hash === '#/knowledge' && ${hasTab('Proposals')}`, 'the redirect to Proposals')
    assert.equal(await s.evaluate(hasTab('Doc drift')), false, 'no Docs drift tab without a provider')
  })
})

// ---- an axe scan must not read a colour in the middle of a theme transition ----
test('a scan after a theme flip waits for the colour transition, so axe never reads a blend of both themes', { skip, timeout: 120000 }, async () => {
  await withApp(fixtures(), async (s, origin) => {
    await visit(s, origin, '/work', 'dark', hasText('Sprint trend'), 'the sprint card')
    // Slow the header chip down so a transition is certainly still running a moment after the flip.
    await s.evaluate(`const st = document.createElement('style'); st.textContent = '.next-chip { transition: color 1.5s linear !important }'; document.head.appendChild(st); true`)
    await s.evaluate(`localStorage.setItem('shell.theme', 'light'); document.documentElement.setAttribute('data-theme', 'light'); true`)
    await sleep(200)
    assert.equal(await s.evaluate(`document.getAnimations().some((a) => a instanceof CSSTransition && a.playState === 'running')`), true, 'the transition is still running, so this test is really testing the wait')
    const t0 = Date.now()
    assert.equal(await s.evaluate(SETTLED_JS), true, 'the wait ended because the transition ended, not because it gave up')
    assert.ok(Date.now() - t0 > 400, 'it waited for the transition and did not return at once')
    assert.equal(await s.evaluate(`getComputedStyle(document.querySelector('.next-chip')).color`), 'rgb(42, 53, 71)', 'the chip holds its settled light colour')
    const found = await axeFindings(s)
    assert.deepEqual(found, [], `no finding once settled: ${JSON.stringify(found)}`)
  })
})

// ---- OC-18: sprint trend card and closed sprints ----
test('the sprint trend card and the closed sprints tab have no axe violation in either theme', { skip, timeout: 120000 }, async () => {
  await withApp(fixtures(), async (s, origin) => {
    for (const theme of ['light', 'dark']) {
      await visit(s, origin, '/work', theme, hasText('Sprint trend') && hasText('Items in sprint'), 'the sprint trend card')
      assert.ok(await s.evaluate(hasTab('Closed sprints')), `${theme}: the Closed sprints tab is in the hub`)
      let found = await axeFindings(s)
      assert.deepEqual(found, [], `${theme} theme, Sprint tab: ${JSON.stringify(found)}`)
      await visit(s, origin, '/work/closed', theme, hasText('Closed sprints') && hasText('Sprint 32'), 'the closed sprint list')
      found = await axeFindings(s)
      assert.deepEqual(found, [], `${theme} theme, closed list: ${JSON.stringify(found)}`)
      await visit(s, origin, '/work/closed/31', theme, hasText('FIX-2'), 'the closed sprint items')
      assert.ok(await s.evaluate(hasText('read only')), `${theme}: the view says it is read only`)
      found = await axeFindings(s)
      assert.deepEqual(found, [], `${theme} theme, closed sprint: ${JSON.stringify(found)}`)
    }
  })
})

test('the sprint trend card and the closed sprints tab are hidden when the tracker has no sprint source', { skip, timeout: 60000 }, async () => {
  await withApp({ ...fixtures(), trend: null, closed: null }, async (s, origin) => {
    await visit(s, origin, '/work', 'light', hasText('FIX-9'), 'the active sprint')
    assert.equal(await s.evaluate(hasText('Sprint trend')), false, 'no trend card without a sprint source')
    assert.equal(await s.evaluate(hasTab('Closed sprints')), false, 'no Closed sprints tab without a sprint source')
    await visit(s, origin, '/work/closed', 'light', `location.hash === '#/work'`, 'the redirect to the Sprint tab')
  })
})

test('an id that is not in the closed list never opens a sprint view', { skip, timeout: 60000 }, async () => {
  await withApp(fixtures(), async (s, origin) => {
    await visit(s, origin, '/work/closed/999', 'light', hasText('not one of the recent closed sprints'), 'the refusal')
    assert.equal(await s.evaluate(hasText('FIX-1')), false, 'no ticket of any sprint is shown')
  })
})

// ---- OC-20: Live automation ----
const clickByText = (sel, text) => `(() => { const el = [...document.querySelectorAll(${JSON.stringify(sel)})].find((e) => e.textContent.trim() === ${JSON.stringify(text)}); if (!el) return false; el.click(); return true })()`

test('the Live automation tab lists the acting launch, and the Action Center keeps only the dark one, in both themes', { skip, timeout: 120000 }, async () => {
  await withApp(fixtures(), async (s, origin) => {
    for (const theme of ['light', 'dark']) {
      await visit(s, origin, '/platform/automation/live-automation', theme, hasText('Launch alpha'), 'the acting launch')
      assert.ok(await s.evaluate(hasTab('Live automation')), `${theme}: the item is in the Automation section`)
      assert.equal(await s.evaluate(hasText('Launch beta')), false, `${theme}: a dark launch is not listed as live`)
      assert.ok(await s.evaluate(`!!document.querySelector('[role="switch"][aria-checked="true"]')`), `${theme}: the launch has its Disable switch, on`)
      let found = await axeFindings(s)
      assert.deepEqual(found, [], `${theme} theme, Live automation: ${JSON.stringify(found)}`)
      await visit(s, origin, '/platform', theme, hasText('Live automation') && hasText('Launch alpha'), 'the Overview card')
      found = await axeFindings(s)
      assert.deepEqual(found, [], `${theme} theme, Overview: ${JSON.stringify(found)}`)
      await visit(s, origin, '/action', theme, hasText('Launch beta'), 'the dark launch in the Action Center')
      assert.equal(await s.evaluate(hasText('Launch alpha')), false, `${theme}: the acting launch has left the Action Center`)
      assert.ok(await s.evaluate(hasText('live automation is acting')), `${theme}: the Action Center points to Live automation`)
    }
  })
})

test('the Disable switch asks first, sets the launch back and returns it to the Action Center', { skip, timeout: 60000 }, async () => {
  const fx = fixtures()
  await withApp(fx, async (s, origin) => {
    await visit(s, origin, '/platform/automation/live-automation', 'light', hasText('Launch alpha'), 'the acting launch')
    await s.evaluate(`document.querySelector('[role="switch"]').click(); true`)
    await s.waitFor(hasText('Disable Launch alpha?'), 'the confirmation')
    assert.deepEqual(fx.posts, [], 'nothing is sent before the confirmation')
    assert.ok(await s.evaluate(clickByText('button', 'Disable')), 'the confirm button is there')
    await s.waitFor(`document.body.innerText.includes('Nothing is acting on its own')`, 'the launch to leave Live automation')
    assert.deepEqual(fx.posts, ['disable alpha'])
    await visit(s, origin, '/action', 'light', hasText('Launch alpha') && hasText('Launch beta'), 'both launches back in the Action Center')
  })
})

test('the Live automation tab is hidden when no dark launch is registered', { skip, timeout: 60000 }, async () => {
  await withApp({ ...fixtures(), launches: { launches: [], error: null } }, async (s, origin) => {
    await visit(s, origin, '/platform', 'light', hasText('keep our platform running'), 'the Operations hub')
    await sleep(500)
    assert.equal(await s.evaluate(hasTab('Live automation')), false, 'no Live automation tab without a registry')
    await visit(s, origin, '/platform/automation/live-automation', 'light', `!location.hash.includes('live-automation')`, 'the redirect to the Overview')
  })
})

test('with the tracker slot off the Work tracking item leaves the rail and its page says it needs the tracker slot', { skip, timeout: 60000 }, async () => {
  await withApp({ ...fixtures(), needsMe: null, approvals: null, active: null, trend: null, closed: null }, async (s, origin) => {
    await visit(s, origin, '/work', 'light', hasText('Work tracking needs the tracker slot'), 'the explicit slot state')
    assert.equal(await s.evaluate(`location.hash`), '#/work', 'the address stays: a disabled page is not a redirect')
    assert.equal(await s.evaluate(hasText('OPSCENTER_TRACKER')), true, 'the state names the switch')
    const rail = await s.evaluate(`[...document.querySelectorAll('nav a')].map((a) => a.textContent.trim())`)
    // A rail item carries its badge count on both sides (4Reviews4), so the label is matched after any leading digits.
    assert.ok(!rail.some((t) => /^\d*Work tracking/.test(t)), `no Work tracking item in the rail: ${JSON.stringify(rail)}`)
    assert.ok(rail.some((t) => /^\d*Pull requests/.test(t)), 'the other items stay')
    assert.deepEqual(await axeFindings(s), [], 'the slot state has no axe violation')
  })
})

test('a server with no review config answers the platform reviews without a gate or a policy and the page shows its empty state', { skip, timeout: 60000 }, async () => {
  const empty = { ...fixtures().platform, needs_me_rows: [], counts: { needs_me: 0, in_progress: 0, shipped: 0 }, configured: false, gate: undefined, policy: undefined }
  await withApp({ ...fixtures(), platform: empty }, async (s, origin) => {
    await visit(s, origin, '/reviews/platform', 'light', hasText('Nothing needs you'), 'the empty reviews page')
    assert.equal(await s.evaluate(`!!document.querySelector('nav')`), true, 'the shell is still there')
  })
})

test('old /jira and /operations addresses land on /work and /platform with the tab kept', { skip, timeout: 60000 }, async () => {
  await withApp(fixtures(), async (s, origin) => {
    await visit(s, origin, '/jira/backlog', 'light', `location.hash === '#/work/backlog'`, 'the redirect to Work tracking')
    await visit(s, origin, '/operations/automation/live-automation', 'light', `location.hash.startsWith('#/platform/automation')`, 'the redirect to Platform')
    await visit(s, origin, '/platform/mine', 'light', `location.hash === '#/reviews/platform/mine'`, 'the lane tab keeps its old meaning')
  })
})

test('every hub page has the accent chip and the header names a trail, and at phone width the tab bar shows with no axe violation', { skip, timeout: 120000 }, async () => {
  await withApp(fixtures(), async (s, origin) => {
    await s.send('Emulation.setDeviceMetricsOverride', { width: 1300, height: 900, deviceScaleFactor: 1, mobile: false })
    await visit(s, origin, '/debt', 'light', hasText('Debt and improvements'), 'the Debt page')
    assert.equal(await s.evaluate(`!!document.querySelector('.page-header.ds-head .ds-head-chip svg')`), true, 'the chip carries the rail icon')
    assert.equal(await s.evaluate(`document.querySelector('.header-title').textContent`), 'Improve / Debt and improvements', 'the trail')
    assert.equal(await s.evaluate(`getComputedStyle(document.querySelector('.oc-tabbar')).display`), 'none', 'no tab bar on a wide screen')
    await s.send('Emulation.setDeviceMetricsOverride', { width: 390, height: 800, deviceScaleFactor: 1, mobile: true })
    await s.waitFor(`getComputedStyle(document.querySelector('.oc-tabbar')).display === 'flex'`, 'the tab bar at phone width')
    const tabs = await s.evaluate(`[...document.querySelectorAll('.oc-tabbar .oc-tab-label')].map((e) => e.textContent)`)
    assert.deepEqual(tabs.at(-1), 'Menu')
    assert.ok(tabs.includes('Action Center'), JSON.stringify(tabs))
    assert.deepEqual(await axeFindings(s), [], 'no axe violation at phone width')
    await s.send('Emulation.clearDeviceMetricsOverride')
  })
})

const PHONE = {
  fetched_utc: '2026-11-21T12:00:00Z',
  status: { api_reachable: true, edge_covers_host: true, plugin_pinned: true, plugin_matches_pin: false, only_api_connected: null },
  devices: [{ id: 'dev-1', name: 'Phone A', paired_at: '2026-11-01T00:00:00Z', last_seen: '2026-11-21T11:00:00Z' }],
  truncated: 0,
  error: null,
}

test('Device access shows the setup steps while no phone provider is configured, in both themes', { skip, timeout: 120000 }, async () => {
  await withApp({ ...fixtures(), phone: null }, async (s, origin) => {
    for (const theme of ['light', 'dark']) {
      await visit(s, origin, '/platform/host/device-access', theme, hasText('Device pairing is not set up'), 'the setup steps')
      assert.equal(await s.evaluate(hasText('hermes/phone_access.py plugin')), true, 'the steps name the installer')
      assert.deepEqual(await axeFindings(s), [], `${theme}: no axe violation`)
    }
  })
})

test('Device access pairs with a QR that is never text, lists devices, and confirms Remove', { skip, timeout: 150000 }, async () => {
  const fx = { ...fixtures(), phone: PHONE }
  await withApp(fx, async (s, origin) => {
    await visit(s, origin, '/platform/host/device-access', 'light', hasText('Paired devices') && hasText('Phone A'), 'the page')
    assert.equal(await s.evaluate(hasText('Not OK')), true, 'a failing check reads Not OK')
    assert.equal(await s.evaluate(hasText('Unknown')), true, 'an unknown check reads Unknown')
    await s.evaluate(`[...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Show pairing QR').click(); true`)
    await s.waitFor(`!!document.querySelector('.pair-qr-img svg')`, 'the QR')
    assert.equal(await s.evaluate(`document.documentElement.outerHTML.includes('SECRETCODE123')`), false, 'the link is nowhere in the page')
    assert.equal(await s.evaluate(hasText('clears in')), true, 'the countdown shows')
    assert.deepEqual(await axeFindings(s), [], 'no axe violation with the QR up')
    await s.evaluate(`[...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Hide now').click(); true`)
    await s.waitFor(`!document.querySelector('.pair-qr-img')`, 'the QR clears')
    await s.evaluate(`[...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Remove').click(); true`)
    await s.waitFor(hasText('Remove Phone A?'), 'the confirmation')
    assert.equal(fx.posts.some((p) => p.startsWith('remove')), false, 'nothing is removed before the confirmation')
    await s.evaluate(`[...document.querySelectorAll('button')].filter((b) => b.textContent.trim() === 'Remove').pop().click(); true`)
    await s.waitFor(hasText('Device removed.'), 'the removal')
    assert.ok(fx.posts.includes('remove {"id":"dev-1","confirm":true}'), JSON.stringify(fx.posts))
  })
})

test('a long extension list shows its first window and loads the next on request', { skip, timeout: 120000 }, async () => {
  const all = Array.from({ length: 450 }, (_, i) => ({ id: `r${i}`, title: `Row number ${i}`, detail: null, state: null, url: null, at: null }))
  const fx = fixtures()
  fx.extensions = extManifest()
  fx.extRows = (id, offset) => {
    if (id !== 'reports') return null
    const win = all.slice(offset, offset + 200)
    return { ...extRows(extPages()[0], win), total: all.length, offset, truncated: Math.max(0, all.length - offset - win.length) }
  }
  await withApp(fx, async (s, origin) => {
    await visit(s, origin, '/extensions/reports', 'light', hasText('Row number 199') && hasText('250 more rows'), 'the first window')
    assert.equal(await s.evaluate(hasText('Row number 200')), false, 'the second window is not loaded yet')
    await s.evaluate(`[...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Show more').click(); true`)
    await s.waitFor(`${hasText('Row number 399')} && ${hasText('50 more rows')}`, 'the second window')
    assert.deepEqual(await axeFindings(s), [], 'no axe violation')
  })
})

test('a long Debt list shows 100 rows and loads the next window on request', { skip, timeout: 120000 }, async () => {
  const fx = fixtures()
  fx.eng = { ...ENG, items: Array.from({ length: 250 }, (_, i) => engItem(i + 1, { bucket: 'done', status: 'resolved' })) }
  await withApp(fx, async (s, origin) => {
    await visit(s, origin, '/debt/done', 'light', hasText('Debt entry 100') && hasText('150 left'), 'the first window')
    assert.equal(await s.evaluate(hasText('Debt entry 101')), false, 'the second window is not drawn yet')
    await s.evaluate(`[...document.querySelectorAll('button')].find((b) => b.textContent.includes('more (150 left)')).click(); true`)
    await s.waitFor(`${hasText('Debt entry 200')} && ${hasText('50 left')}`, 'the second window')
  })
})

test('the header shows the Enterprise chip with the time left while an incident is open, and not otherwise', { skip, timeout: 120000 }, async () => {
  const closes = new Date(Date.now() + 41 * 60e3).toISOString()
  const fb = { checked_utc: null, team: null, history: [], active: { id: 'i1', opened_utc: new Date().toISOString(), last_call_utc: new Date().toISOString(), calls: 2, est_usd: 1, sessions: {}, team_session_pct: 10, team_weekly_pct: 10, closes_utc: closes } }
  await withApp({ ...fixtures(), fallback: fb }, async (s, origin) => {
    await s.send('Emulation.setDeviceMetricsOverride', { width: 1300, height: 900, deviceScaleFactor: 1, mobile: false })
    await visit(s, origin, '/action', 'light', `!!document.querySelector('.ent-chip')`, 'the chip')
    assert.match(flat(await s.evaluate(`document.querySelector('.ent-chip-full').textContent`)), /^Enterprise on, 0 h (40|41) min left$/)
    assert.deepEqual(await axeFindings(s), [], 'no axe violation')
  })
  await withApp({ ...fixtures(), fallback: { ...fb, active: null } }, async (s, origin) => {
    await visit(s, origin, '/action', 'light', `document.querySelectorAll('.ac-counter').length > 0`, 'the page')
    assert.equal(await s.evaluate(`!!document.querySelector('.ent-chip')`), false, 'no incident, no chip')
  })
})

test('Debt and improvements shows how many entries the curate job changed this week, and nothing when the job has no log route', { skip, timeout: 120000 }, async () => {
  await withApp({ ...fixtures(), curation: { auto_week_count: 4 } }, async (s, origin) => {
    await visit(s, origin, '/debt/todo', 'light', hasText('Auto-curated this week: 4'), 'the curated line')
  })
  await withApp({ ...fixtures(), curation: null }, async (s, origin) => {
    await visit(s, origin, '/debt/todo', 'light', hasText('Debt entry 3'), 'the rows')
    assert.equal(await s.evaluate(hasText('Auto-curated')), false, 'no route, no line')
  })
})

test('My PRs filters by status, and Stuck keeps only the PRs the lane says nothing will move', { skip, timeout: 120000 }, async () => {
  const mk = (pr, hold) => ({ pr, title: `Change ${pr}`, url: `https://example.test/pull/${pr}`, head_sha: 'a'.repeat(40), labels: [], verdict: 'clean', ai_result: 'SUCCESS', counts: { blocking: 0, high: 1, medium: 2, low: 3 }, blocking: [], findings: [], pending: [], waiting: [], red: [], hold })
  const fx = fixtures()
  fx.platform = { ...PLATFORM, my_prs: [mk(11, { kind: 'waiting', summary: 'A draft with no gate.', parked: 'nogate' }), mk(12, null), mk(13, { kind: 'waiting', summary: 'Another draft with no gate.', parked: 'nogate' })] }
  await withApp(fx, async (s, origin) => {
    await visit(s, origin, '/reviews/platform/mine', 'light', hasText('Change 11') && hasText('Change 12'), 'the three PRs')
    assert.equal(await s.evaluate(hasText('Stuck 2')), true, 'the Stuck count')
    await s.evaluate(`[...document.querySelectorAll('[role=radio], [role=tab], button')].find((b) => b.textContent.trim() === 'Stuck 2').click(); true`)
    await s.waitFor(`${hasText('Change 11')} && ${hasText('Change 13')} && !${hasText('Change 12')}`, 'only the stuck ones')
    assert.deepEqual(await axeFindings(s), [], 'no axe violation')
  })
})

test('the Live tab has a Lane select and one titled list per kind of work when the builds name lanes', { skip, timeout: 120000 }, async () => {
  const fx = fixtures()
  const pr = { number: 5, url: null, state: 'open', red: 0 }
  fx.agentBuilds = buildsFeed([
    BUILD('b1', 'Fix the importer', 'running', { lane: 'infra', pr, activity_at: nowS() - 60 }),
    BUILD('b2', 'Nightly sweep', 'running', { lane: 'infra', activity_at: nowS() - 90 }),
    BUILD('b3', 'Docs pass', 'running', { lane: 'apps', pr, activity_at: nowS() - 120 }),
  ])
  await withApp(fx, async (s, origin) => {
    await visit(s, origin, '/action/live', 'light', hasText('Engineer PRs') && hasText('Scheduled jobs'), 'the sections')
    assert.equal(await s.evaluate(`!!document.querySelector('select[aria-label="Lane"]')`), true, 'the Lane select')
    assert.equal(await s.evaluate(`document.querySelectorAll('.ac-live-sec').length >= 2`), true, 'titled lists')
    await s.evaluate(`(() => { const sel = document.querySelector('select[aria-label="Lane"]'); const set = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set; set.call(sel, 'apps'); sel.dispatchEvent(new Event('change', { bubbles: true })) })()`)
    await s.waitFor(`${hasText('Docs pass')} && !${hasText('Fix the importer')}`, 'only the apps lane')
    assert.deepEqual(await axeFindings(s), [], 'no axe violation')
  })
})

test('the Action Center row shows Stuck plans with the server count and links to Plans', { skip, timeout: 120000 }, async () => {
  const plans = { generated_utc: '2026-11-21T12:00:00Z', root: '/p', projects: [], untracked: [], library: [], archived: { projects: [], library: [] }, counts: { projects: 0, library: 0, archived: 0, stuck: 2 }, jira: { state: 'none', checked_utc: '', errors: [] } }
  await withApp({ ...fixtures(), plans }, async (s, origin) => {
    await visit(s, origin, '/action', 'light', `document.querySelectorAll('.ac-counter').length > 0`, 'the counters row')
    await s.waitFor(`!!document.querySelector('.ac-counter[href="#/plans"]')`, 'the Stuck plans tile')
    assert.equal(await s.evaluate(tileText('Stuck plans')), '2 Stuck plans > #/plans')
  })
})

test('an extension row filters by state, opens a drawer with its fields, and runs a declared action only after a confirmation', { skip, timeout: 150000 }, async () => {
  const rows = [
    { id: 'r1', title: 'Change one', detail: 'Waiting', state: 'Open', url: null, at: null, actions: [{ id: 'approve', label: 'Approve', confirm: 'Approve change one?' }], fields: [{ label: 'Owner', value: 'Sam' }] },
    { id: 'r2', title: 'Change two', detail: null, state: 'Done', url: null, at: null },
    { id: 'r3', title: 'Change three', detail: null, state: 'Open', url: null, at: null },
  ]
  const fx = fixtures()
  fx.extensions = extManifest()
  fx.extRows = { reports: extRows(extPages()[0], rows), docs: extRows(extPages()[1], []) }
  await withApp(fx, async (s, origin) => {
    await visit(s, origin, '/extensions/reports', 'light', hasText('Change one') && hasText('Open 2') && hasText('Done 1'), 'the rows and the state tabs')
    const click = (text) => s.evaluate(`[...document.querySelectorAll('button')].filter((b) => b.textContent.trim() === ${JSON.stringify(text)}).pop().click(); true`)
    await click('Done 1')
    await s.waitFor(`${hasText('Change two')} && !${hasText('Change one')}`, 'only the done row')
    await click('All 3')
    await s.waitFor(hasText('Change one'), 'all rows again')
    await click('Details')
    await s.waitFor(hasText('Sam'), 'the drawer fields')
    await click('Approve')
    await s.waitFor(hasText('Approve change one?'), 'the confirmation')
    assert.equal(fx.posts.some((p) => p.startsWith('ext-action')), false, 'nothing runs before the confirmation')
    await click('Approve')
    await s.waitFor(hasText('Approved.'), 'the result')
    assert.ok(fx.posts.includes('ext-action reports {"row":"r1","action":"approve","confirm":true}'), JSON.stringify(fx.posts))
  })
})

// ---- issue 308: Debt page filters ----
test('the Debt page filters narrow the list and have no axe violation in either theme', { skip, timeout: 120000 }, async () => {
  await withApp(fixtures(), async (s, origin) => {
    for (const theme of ['light', 'dark']) {
      await visit(s, origin, '/debt/todo', theme, hasText('Debt entry 3'), 'the debt rows')
      assert.ok(await s.evaluate(hasText('Debt entry 1')), `${theme}: the first entry is listed`)
      for (const label of ['Kind', 'Severity', 'Goal', 'Effort', 'Status']) {
        assert.ok(await s.evaluate(`!!document.querySelector('select[aria-label="${label}"]')`), `${theme}: the ${label} filter is shown`)
      }
      let found = await axeFindings(s)
      assert.deepEqual(found, [], `${theme} theme, unfiltered: ${JSON.stringify(found)}`)
      // Choose high severity through the real control: the low entry leaves, the two high ones stay.
      await s.evaluate(`(() => {
        const sel = document.querySelector('select[aria-label="Severity"]')
        const set = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set
        set.call(sel, 'high')
        sel.dispatchEvent(new Event('change', { bubbles: true }))
      })()`)
      await sleep(300)
      assert.ok(await s.evaluate(`${hasText('Debt entry 1')} && ${hasText('Debt entry 2')}`), `${theme}: both high entries stay`)
      assert.equal(await s.evaluate(hasText('Debt entry 3')), false, `${theme}: the low entry leaves`)
      assert.ok(await s.evaluate(hasText('Clear 1')), `${theme}: the clear button counts the active filter`)
      found = await axeFindings(s)
      assert.deepEqual(found, [], `${theme} theme, filtered: ${JSON.stringify(found)}`)
      // Clear puts every entry back, which the next theme's pass relies on (the same hash does not reload the page).
      await s.evaluate(`[...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Clear 1').click()`)
      await sleep(300)
      assert.ok(await s.evaluate(hasText('Debt entry 3')), `${theme}: Clear brings the low entry back`)
      assert.equal(await s.evaluate(hasText('Clear 1')), false, `${theme}: the clear button leaves once nothing is filtered`)
    }
  })
})

// ---- issue 308: Action Center counters row ----
// One line per tile: its number, its label and where it links. The app uses hash routes, so a link reads as #/path.
const tileText = (key) =>
  `(() => {
    const t = [...document.querySelectorAll('.ac-counter')].find((a) => a.querySelector('.ac-counter-l').textContent === ${JSON.stringify(key)})
    return t ? t.querySelector('.ac-counter-n').textContent + ' ' + ${JSON.stringify(key)} + ' > ' + t.getAttribute('href') : null
  })()`

test('the Action Center counters row shows each source with its number and link, and has no axe violation in either theme', { skip, timeout: 120000 }, async () => {
  await withApp(fixtures(), async (s, origin) => {
    for (const theme of ['light', 'dark']) {
      await visit(s, origin, '/action', theme, `document.querySelectorAll('.ac-counter').length > 0`, 'the counters row')
      const want = {
        'Action items': '2 Action items > #/action',
        'Platform': '1 Platform > #/platform',
        'Improvements': '3 Improvements > #/debt',
        // The configured tracker answers with nothing waiting, so its tile shows an honest zero.
        'Work': '0 Work > #/work',
      }
      for (const [label, line] of Object.entries(want)) {
        assert.equal(await s.evaluate(tileText(label)), line, `${theme}: ${label}`)
      }
      assert.equal(await s.evaluate(`!!document.querySelector('.ac-counters-calm')`), false, `${theme}: something waits, so no calm line`)
      const found = await axeFindings(s)
      assert.deepEqual(found, [], `${theme} theme: ${JSON.stringify(found)}`)
    }
  })
})

test('the counters row leaves out the work tile when the tracker slot is off and says so plainly when nothing waits', { skip, timeout: 120000 }, async () => {
  const fx = fixtures()
  fx.needsMe = null
  fx.approvals = null
  // No lane has anything waiting either, otherwise the row rightly says something does.
  fx.platform = { ...PLATFORM, needs_me_rows: [], counts: { needs_me: 0, in_progress: 0, shipped: 0 } }
  fx.team = { ...TEAM, needs_me: [], counts: { needs_me: 0, in_progress: 0, shipped: 0 } }
  fx.repos = { ...REPOS, counts: { needs_me: 0, in_progress: 0 }, repos: [{ ...REPOS.repos[0], needs_me: [] }] }
  fx.badges = {
    action_open: [],
    debt: 40,
    knowledge: 0,
    alerts: 0,
    problems: { items: [], counts: { needs_me: 0, worth_a_look: 0, healthy: 0, running: 0, total: 0, by_section: {}, by_item: {} } },
  }
  await withApp(fx, async (s, origin) => {
    await visit(s, origin, '/action', 'light', `document.querySelectorAll('.ac-counter').length > 0 && !!document.querySelector('.ac-counters-calm')`, 'the counters row and its calm line')
    assert.equal(await s.evaluate(tileText('Work')), null, 'no work tile while the slot is off')
    assert.equal(await s.evaluate(tileText('Improvements')), '40 Improvements > #/debt', 'debt still counts')
    assert.ok(await s.evaluate(`!!document.querySelector('.ac-counters-calm')`), 'debt alone is not waiting, so the calm line shows')
  })
})

// ---- issue 308: Action Center waiting on me panel ----
const waitingRows = `[...document.querySelectorAll('.ac-waiting li a')].map((a) => a.querySelector('.ac-waiting-what').textContent + ' | ' + a.querySelector('.ac-waiting-title').textContent + ' > ' + a.getAttribute('href'))`

test('the waiting on me panel lists every lane per repo with the click it needs and links to the Reviews card, in both themes', { skip, timeout: 120000 }, async () => {
  await withApp(fixtures(), async (s, origin) => {
    for (const theme of ['light', 'dark']) {
      await visit(s, origin, '/action', theme, `document.querySelectorAll('.ac-waiting li').length > 0`, 'the waiting panel')
      assert.deepEqual(await s.evaluate(waitingRows), [
        'Approve the plan | #12 Plan page > #/reviews/platform',
        'Approve as me | #7 Fix the sync > #/reviews/team',
        'Give it direction | #8 My own change > #/reviews/team',
        'Checks are failing | #3 Red checks > #/reviews/ops_center',
      ], `${theme}: rows`)
      assert.deepEqual(await s.evaluate(`[...document.querySelectorAll('.ac-waiting-group h3')].map((h) => h.textContent)`), ['Platform', 'Team', 'ops_center'], `${theme}: groups`)
      assert.equal(await s.evaluate(`document.querySelector('.ac-waiting h2').textContent.replace(/\\s+/g, ' ')`), 'Waiting on me now (4)', `${theme}: heading`)
      assert.equal(await s.evaluate(`document.querySelectorAll('.ac-waiting button').length`), 0, `${theme}: the panel has no button, the Reviews card does the work`)
      const found = await axeFindings(s)
      assert.deepEqual(found, [], `${theme} theme: ${JSON.stringify(found)}`)
    }
  })
})

test('the waiting on me panel is absent when no lane has anything waiting', { skip, timeout: 120000 }, async () => {
  const fx = fixtures()
  fx.platform = { ...PLATFORM, needs_me_rows: [], counts: { needs_me: 0, in_progress: 0, shipped: 0 } }
  fx.team = { ...TEAM, needs_me: [], counts: { needs_me: 0, in_progress: 0, shipped: 0 } }
  fx.repos = { ...REPOS, counts: { needs_me: 0, in_progress: 0 }, repos: [{ ...REPOS.repos[0], needs_me: [] }] }
  await withApp(fx, async (s, origin) => {
    await visit(s, origin, '/action', 'light', `document.querySelectorAll('.ac-counter').length > 0`, 'the counters row')
    assert.equal(await s.evaluate(`!!document.querySelector('.ac-waiting')`), false, 'no panel and no empty heading')
  })
})

// ---- issue 308: Action Center active builds panel ----
const buildRows = `[...document.querySelectorAll('.ac-builds li')].map((li) => li.dataset.state + ' | ' + li.querySelector('.ac-builds-title').textContent + ' | ' + li.querySelector('.ac-builds-age').textContent)`

test('the active builds panel lists what needs a look first with its age, links only safe addresses, and has no axe violation in either theme', { skip, timeout: 120000 }, async () => {
  await withApp(fixtures(), async (s, origin) => {
    for (const theme of ['light', 'dark']) {
      await visit(s, origin, '/action', theme, `document.querySelectorAll('.ac-builds li').length > 0`, 'the builds panel')
      assert.deepEqual(await s.evaluate(buildRows), [
        'stuck | Docs pass | 3 h ago',
        'running | Fix the importer | running tests, 10 min ago',
        'finished | Old cleanup | 2 h ago',
      ], `${theme}: rows, stuck first`)
      assert.equal(await s.evaluate(`document.querySelector('.ac-builds h2').textContent.replace(/\\s+/g, ' ').trim()`), 'Active builds (1 stuck, 1 running)', `${theme}: heading`)
      assert.equal(await s.evaluate(`document.querySelectorAll('.ac-builds a').length`), 1, `${theme}: only the row with a link has one`)
      assert.equal(await s.evaluate(`document.querySelector('.ac-builds a').rel`), 'noreferrer noopener', `${theme}: external link is safe`)
      assert.equal(await s.evaluate(`document.querySelectorAll('.ac-builds button').length`), 0, `${theme}: no Stop button, it is held back`)
      const found = await axeFindings(s)
      assert.deepEqual(found, [], `${theme} theme: ${JSON.stringify(found)}`)
    }
  })
})

test('the active builds panel is absent when the consumer has no builds provider', { skip, timeout: 120000 }, async () => {
  const fx = fixtures()
  fx.agentBuilds = null
  await withApp(fx, async (s, origin) => {
    await visit(s, origin, '/action', 'light', `document.querySelectorAll('.ac-counter').length > 0`, 'the counters row')
    await new Promise((r) => setTimeout(r, 600))
    assert.equal(await s.evaluate(`!!document.querySelector('.ac-builds')`), false, 'no panel and no empty heading')
  })
})

test('a failed build source is shown as an error and never as a calm board', { skip, timeout: 120000 }, async () => {
  const fx = fixtures()
  fx.agentBuilds = buildsFeed([], 'the source failed (OSError)')
  await withApp(fx, async (s, origin) => {
    await visit(s, origin, '/action', 'light', `!!document.querySelector('.ac-builds')`, 'the builds panel')
    const text = await s.evaluate(`document.querySelector('.ac-builds').textContent.replace(/\\s+/g, ' ')`)
    assert.match(text, /could not read the build source: the source failed \(OSError\)/)
    assert.match(text, /not the same as nothing running/)
    assert.doesNotMatch(text, /Nothing is running, stuck or failed/, 'an unreadable source must not read as calm')
    const found = await axeFindings(s)
    assert.deepEqual(found, [], JSON.stringify(found))
  })
})

// ---- issue 308: the Live tab, scope lines and the restart link ----
const flat = (text) => String(text).replace(/\s+/g, ' ').trim()
const liveRows = `[...document.querySelectorAll('.ac-live li')].map((li) => li.dataset.kind + ' | ' + li.dataset.state + ' | ' + li.querySelector('.ac-live-title').textContent)`

test('the Live tab lists what is acting, stuck first, counts it on the tab, and has no axe violation in either theme', { skip, timeout: 120000 }, async () => {
  await withApp(fixtures(), async (s, origin) => {
    for (const theme of ['light', 'dark']) {
      await visit(s, origin, '/action/live', theme, `document.querySelectorAll('.ac-live li').length > 0`, 'the Live list')
      const pick = (name) => s.evaluate(`[...document.querySelectorAll('[role=radio], [role=tab], button')].find((b) => b.textContent.trim().startsWith(${JSON.stringify(name)})).click(); true`)
      // The control opens on the first state that has rows; here nothing failed, so it is Running.
      assert.deepEqual(await s.evaluate(liveRows), ['build | running | Fix the importer', 'session | running | Tighten the importer'], `${theme}: builds then sessions, each in its own list`)
      await pick('Stuck')
      await s.waitFor(`document.querySelectorAll('.ac-live li').length === 1`, 'the stuck row')
      assert.deepEqual(await s.evaluate(liveRows), ['build | stuck | Docs pass'], `${theme}: stuck`)
      await pick('Just finished')
      await s.waitFor(`document.querySelectorAll('.ac-live li').length === 1`, 'the finished row')
      assert.deepEqual(await s.evaluate(liveRows), ['build | finished | Old cleanup'], `${theme}: history on request`)
      await pick('Running')
      assert.equal(await s.evaluate(`document.querySelectorAll('.ac-live button').length`), 0, `${theme}: no Stop button`)
      assert.equal(await s.evaluate(`document.querySelector('.ac-live li[data-kind="session"] .ac-live-ticket').textContent`), 'WORK-77', `${theme}: the session carries its ticket`)
      assert.match(flat(await s.evaluate(`document.querySelector('.hub-head').innerText`)), /Live 3\b/, `${theme}: the tab counts three acting`)
      const found = await axeFindings(s)
      assert.deepEqual(found, [], `${theme} theme: ${JSON.stringify(found)}`)
    }
  })
})

// ---- issue 308, item 22: pages a consumer adds through the extension manifest ----
// Read the text in the browser and collapse the whitespace here in Node, so no regex backslash travels inside an evaluate() template string.
const flatEval = async (s, expr) => String(await s.evaluate(expr)).replace(/\s+/g, ' ').trim()

test('a consumer page appears in its rail group after the core items, opens, and draws its rows as text', { skip, timeout: 120000 }, async () => {
  const fx = fixtures()
  fx.extensions = extManifest()
  fx.extRows = { reports: extRows(extPages()[0], EXT_ROWS), docs: extRows(extPages()[1], []) }
  await withApp(fx, async (s, origin) => {
    await visit(s, origin, '/extensions/reports', 'light', `!!document.querySelector('.ext-rows')`, 'the extension page')
    const rail = await s.evaluate(`[...document.querySelectorAll('a[href="#/extensions/reports"], a[href="#/extensions/docs"]')].map((a) => a.textContent.trim())`)
    assert.deepEqual(rail, ['Reports', 'Team docs'], 'both pages are in the rail')
    const groups = await s.evaluate(`[...document.querySelectorAll('a[href="#/extensions/reports"]')].map((a) => a.closest('nav, section, div')?.textContent.includes('Action Center'))`)
    assert.ok(groups.some(Boolean), 'the Reports page sits in the Operate group with the core items')
    const rows = await s.evaluate(`[...document.querySelectorAll('.ext-rows li')].length`)
    assert.equal(rows, 3)
    const markup = await s.evaluate(`document.querySelectorAll('.ext-rows img').length + (window.__pwned ? 1 : 0)`)
    assert.equal(markup, 0, 'a title with markup is drawn as text and runs nothing')
    assert.match(await flatEval(s, `document.querySelector('.ext-rows').textContent`), /<img src=x onerror=window\.__pwned=1>/)
    const links = await s.evaluate(`[...document.querySelectorAll('.ext-rows a')].map((a) => a.getAttribute('href') + '|' + a.rel)`)
    assert.deepEqual(links, ['https://tool.example.test/r1|noreferrer noopener'], 'only the row with a safe address is a link')
    const found = await axeFindings(s)
    assert.deepEqual(found, [], JSON.stringify(found))
    await visit(s, origin, '/extensions/reports', 'dark', `!!document.querySelector('.ext-rows')`, 'the extension page, dark')
    const dark = await axeFindings(s)
    assert.deepEqual(dark, [], JSON.stringify(dark))
  })
})

test('a link page points at the consumer tool and lists no rows', { skip, timeout: 60000 }, async () => {
  const fx = fixtures()
  fx.extensions = extManifest()
  fx.extRows = { reports: extRows(extPages()[0], []), docs: extRows(extPages()[1], []) }
  await withApp(fx, async (s, origin) => {
    await visit(s, origin, '/extensions/docs', 'light', `!!document.querySelector('.ext-link a')`, 'the link page')
    assert.equal(await s.evaluate(`document.querySelector('.ext-link a').getAttribute('href')`), 'https://docs.example.test/home')
    assert.equal(await s.evaluate(`document.querySelectorAll('.ext-rows').length`), 0)
  })
})

test('a consumer with no provider gets nothing in the rail, and a typed address lands on the home page', { skip, timeout: 60000 }, async () => {
  const fx = fixtures()
  await withApp(fx, async (s, origin) => {
    await visit(s, origin, '/extensions/reports', 'light', `location.hash === '#/action'`, 'the redirect home')
    assert.equal(await s.evaluate(`document.querySelectorAll('a[href^="#/extensions/"]').length`), 0)
  })
})

test('a page the manifest does not name lands on the home page', { skip, timeout: 60000 }, async () => {
  const fx = fixtures()
  fx.extensions = extManifest()
  fx.extRows = { reports: extRows(extPages()[0], EXT_ROWS) }
  await withApp(fx, async (s, origin) => {
    await visit(s, origin, '/extensions/never-declared', 'light', `location.hash === '#/action'`, 'the redirect home')
  })
})

test('a failed manifest adds no page, and a failed page read is an error and never an empty list', { skip, timeout: 120000 }, async () => {
  const fx = fixtures()
  fx.extensions = extManifest([], 'the source failed (OSError)')
  await withApp(fx, async (s, origin) => {
    await visit(s, origin, '/action', 'light', `!!document.querySelector('.ac-counter')`, 'the Action Center')
    await new Promise((r) => setTimeout(r, 500))
    assert.equal(await s.evaluate(`document.querySelectorAll('a[href^="#/extensions/"]').length`), 0, 'a failing source adds nothing and invents nothing')
  })
  const fx2 = fixtures()
  fx2.extensions = extManifest()
  fx2.extRows = { reports: extRows(extPages()[0], [], 'the source failed (KeyError)'), docs: extRows(extPages()[1], []) }
  await withApp(fx2, async (s, origin) => {
    await visit(s, origin, '/extensions/reports', 'light', `document.body.textContent.includes('could not be read')`, 'the error')
    const text = await flatEval(s, `document.body.textContent`)
    assert.match(text, /The source could not be read/)
    assert.match(text, /the source failed \(KeyError\)\. This is not the same as nothing to show/)
    assert.doesNotMatch(text, /Nothing to show yet/, 'an unreadable source must not read as calm')
    const found = await axeFindings(s)
    assert.deepEqual(found, [], JSON.stringify(found))
  })
})

// ---- issue 308, item 24: the Platform areas rollup on the Operations overview ----
const AREA_ROWS = [
  { section: 'automation', label: 'Automation and jobs', owner: 'Platform team', status: 'needs_me', needs_me: 1, worth_a_look: 0, healthy: 1, lines: 2 },
  { section: 'builds', label: 'Builds and releases', owner: null, status: 'worth_a_look', needs_me: 0, worth_a_look: 1, healthy: 0, lines: 1 },
  { section: 'cost', label: 'cost', owner: 'Finance <script>window.__pwned=1</script>', status: 'healthy', needs_me: 0, worth_a_look: 0, healthy: 1, lines: 0 },
]
const withAreas = (areas) => ({ ...BADGES, problems: { ...BADGES.problems, ...(areas === undefined ? {} : { areas }) } })

test('the Operations overview shows one row per area with its status, owner and problem lines, as text, in both themes', { skip, timeout: 120000 }, async () => {
  const fx = fixtures()
  fx.badges = withAreas(AREA_ROWS)
  await withApp(fx, async (s, origin) => {
    for (const theme of ['light', 'dark']) {
      await visit(s, origin, '/platform', theme, `!!document.querySelector('.pa-table')`, 'the areas table')
      const text = await flatEval(s, `document.querySelector('.pa').textContent`)
      assert.match(text, /3 areas, 1 needs me\./)
      assert.match(text, /Automation and jobs\s*Needs me\s*Owner: Platform team\s*2/)
      assert.match(text, /Builds and releases\s*Worth a look\s*No owner named\s*1/, 'an area with no owner says so in words')
      assert.match(text, /Owner: Finance <script>window\.__pwned=1<\/script>/, 'owner text with markup is drawn as text')
      assert.equal(await s.evaluate(`window.__pwned ? 1 : 0`), 0, 'nothing in the owner text ran')
      assert.equal(await s.evaluate(`document.querySelectorAll('.pa button, .pa a, .pa input').length`), 0, 'the rollup has no control')
      const found = await axeFindings(s)
      assert.deepEqual(found, [], `${theme}: ${JSON.stringify(found)}`)
    }
  })
})

// ---- issue 308, item 26: the pull request and the plain sentence on an Active builds row, and the panel on Operations ----
const PR_BUILDS = () => buildsFeed([
  BUILD('p1', 'Fix the importer', 'running', { activity: 'running tests', activity_at: nowS() - 60, pr: { number: 42, url: 'https://example.test/pull/42', state: 'open', red: 1 } }),
  BUILD('p2', 'Docs pass', 'stuck', { started: nowS() - 5400, activity_at: nowS() - 25 * 60 }),
  BUILD('p3', 'Old cleanup', 'finished', { started: nowS() - 59 * 60 - 120, finished: nowS() - 120, pr: { number: 7, url: 'javascript:alert(1)', state: 'merged', red: 2 } }),
  BUILD('p4', 'No times at all', 'failed', { started: null, finished: null }),
])

test('the Operations overview shows the Active builds panel with the pull request and the plain sentences, in both themes', { skip, timeout: 150000 }, async () => {
  const fx = fixtures()
  fx.agentBuilds = PR_BUILDS()
  await withApp(fx, async (s, origin) => {
    for (const theme of ['light', 'dark']) {
      await visit(s, origin, '/platform', theme, `!!document.querySelector('.ac-builds li')`, 'the builds panel')
      const text = await flatEval(s, `document.querySelector('.ac-builds').textContent`)
      assert.match(text, /Pull request open, 1 red/, 'an open request names its failing checks')
      assert.match(text, /No output for 25 minutes, check the log before waiting longer/, 'a stuck row says the real silence')
      assert.match(text, /Took about 59 minutes, finished 2 min ago/, 'a finished row says how long it took')
      assert.match(text, /Pull request merged(?!, \d)/, 'a merged request reports no red count')
      assert.doesNotMatch(text, /javascript:/, 'a bad link is never printed as a link')
      assert.equal(await s.evaluate(`[...document.querySelectorAll('.ac-builds a')].map((a) => a.getAttribute('href')).join(',')`), 'https://example.test/pull/42', 'only the http link is drawn')
      assert.equal(await s.evaluate(`document.querySelectorAll('.ac-builds button, .ac-builds input, .ac-builds form').length`), 0, 'the panel has no control that writes')
      // It is styled wherever it mounts: the row is a bordered flex box here, not a bare list item.
      assert.equal(await s.evaluate(`getComputedStyle(document.querySelector('.ac-builds li')).display`), 'flex', `${theme}: the panel stylesheet loads on this page`)
      const found = await axeFindings(s)
      assert.deepEqual(found, [], `${theme}: ${JSON.stringify(found)}`)
    }
  })
})

test('a row from an older feed with no pull request field still draws, and a quiet or failed source never reads as a calm board on Operations', { skip, timeout: 150000 }, async () => {
  const fx = fixtures()
  fx.agentBuilds = buildsFeed([BUILD('o1', 'Plain row', 'running', { activity: 'working' })])
  await withApp(fx, async (s, origin) => {
    await visit(s, origin, '/platform', 'light', `!!document.querySelector('.ac-builds li')`, 'the plain row')
    const text = await flatEval(s, `document.querySelector('.ac-builds').textContent`)
    assert.match(text, /Plain row/)
    assert.doesNotMatch(text, /Pull request/, 'no pull request is named when the feed sent none')
  })
  const bad = fixtures()
  bad.agentBuilds = buildsFeed([], 'the source failed (OSError)')
  await withApp(bad, async (s, origin) => {
    await visit(s, origin, '/platform', 'light', `document.body.textContent.includes('This is not the same as nothing running')`, 'the error')
  })
  const none = fixtures()
  none.agentBuilds = null
  await withApp(none, async (s, origin) => {
    await visit(s, origin, '/platform', 'light', `!!document.querySelector('.infra-stack')`, 'the overview')
    assert.equal(await s.evaluate(`document.querySelectorAll('.ac-builds').length`), 0, 'no provider means no panel on Operations')
  })
})

test('the Live tab says nothing is acting only when both sources answered and nothing is acting', { skip, timeout: 120000 }, async () => {
  const fx = fixtures()
  fx.agentBuilds = null
  fx.tackle = { sessions: {} }
  await withApp(fx, async (s, origin) => {
    await visit(s, origin, '/action/live', 'light', `document.body.textContent.includes('Nothing is acting right now')`, 'the calm line')
    assert.equal(await s.evaluate(`document.querySelectorAll('.ac-live li').length`), 0)
  })
})

test('a failed build source on the Live tab is an error and never a calm board', { skip, timeout: 120000 }, async () => {
  const fx = fixtures()
  fx.agentBuilds = buildsFeed([], 'the source failed (OSError)')
  fx.tackle = { sessions: {} }
  await withApp(fx, async (s, origin) => {
    await visit(s, origin, '/action/live', 'light', `document.body.textContent.includes('not the same as nothing acting')`, 'the error')
    const text = flat(await s.evaluate(`document.body.textContent`))
    assert.match(text, /not the same as nothing acting/)
    assert.doesNotMatch(text, /Nothing is acting right now/)
    const found = await axeFindings(s)
    assert.deepEqual(found, [], JSON.stringify(found))
  })
})

test('every page header now carries a one line scope statement', { skip, timeout: 180000 }, async () => {
  await withApp(fixtures(), async (s, origin) => {
    for (const [route, title] of [['/action', 'Action Center'], ['/debt', 'Debt and improvements'], ['/knowledge', 'Knowledge'], ['/team', 'Team']]) {
      await visit(s, origin, route, 'light', `!!document.querySelector('.hub-head h1, .hub-head h2')`, `the ${title} header`)
      const sub = flat(await s.evaluate(`document.querySelector('.hub-head .page-sub')?.textContent || ''`))
      assert.ok(sub.length > 20, `${title}: a scope line is shown, got ${JSON.stringify(sub)}`)
      assert.equal(/[;\u2014]/.test(sub), false, `${title}: no semicolon or em dash in the line`)
    }
  })
})

test('the restart banner offers its two timings and a link to the engine card on Operations, and has no axe violation', { skip, timeout: 120000 }, async () => {
  const fx = fixtures()
  fx.restart = RESTART_STALE
  await withApp(fx, async (s, origin) => {
    await visit(s, origin, '/action', 'light', `[...document.querySelectorAll('a')].some((a) => a.textContent.trim() === 'More restart options')`, 'the restart link')
    const text = flat(await s.evaluate(`document.body.textContent`))
    assert.match(text, /Restart when idle/)
    assert.match(text, /After 5 quiet minutes/)
    assert.equal(await s.evaluate(`[...document.querySelectorAll('a')].find((a) => a.textContent.trim() === 'More restart options').getAttribute('href')`), '#/platform/host/hermes', 'the link goes to the page that holds the engine card')
    const found = await axeFindings(s)
    assert.deepEqual(found, [], JSON.stringify(found))
  })
})

test('the engine card the restart link points at is on Host and access, not on the overview', { skip, timeout: 120000 }, async () => {
  const fx = fixtures()
  fx.restart = RESTART_STALE
  await withApp(fx, async (s, origin) => {
    await visit(s, origin, '/platform', 'light', `!!document.querySelector('.ac-none, .hub-body, .infra-stack')`, 'the Platform overview')
    await new Promise((r) => setTimeout(r, 800))
    assert.equal(await s.evaluate(`document.querySelectorAll('.hermes-engine').length`), 0, 'the overview no longer holds the engine card')
    assert.equal(await s.evaluate(`[...document.querySelectorAll('[role=tab]')].map((t) => t.textContent.trim().replace(/\\d+$/, '')).join('|')`).then((t) => /Releases|Automation/.test(t) && /Host and access/.test(t) && /Cost and standards/.test(t)), true, 'the five tabs')
    await visit(s, origin, '/platform/host/hermes', 'light', `!!document.querySelector('.hermes-engine')`, 'the engine card on Host and access')
    assert.equal(await s.evaluate(`document.querySelectorAll('.hermes-engine').length`), 1, 'exactly one Hermes engine card')
    assert.match(flat(await s.evaluate(`document.querySelector('.hermes-engine').textContent`)), /Hermes engine/)
  })
})

test('a server that sends no areas shows no rollup, and an empty areas list shows none either', { skip, timeout: 90000 }, async () => {
  for (const areas of [undefined, []]) {
    const fx = fixtures()
    fx.badges = withAreas(areas)
    await withApp(fx, async (s, origin) => {
      await visit(s, origin, '/platform', 'light', hasText('keep our platform running'), 'the Operations hub')
      await new Promise((r) => setTimeout(r, 400))
      assert.equal(await s.evaluate(`document.querySelectorAll('.pa').length`), 0)
    })
  }
})

test('the rollup is on the overview only, not on a tab', { skip, timeout: 90000 }, async () => {
  const fx = fixtures()
  fx.badges = withAreas(AREA_ROWS)
  await withApp(fx, async (s, origin) => {
    await visit(s, origin, '/platform/automation/live-automation', 'light', hasText('Launch alpha'), 'the acting launch')
    assert.equal(await s.evaluate(`document.querySelectorAll('.pa').length`), 0)
  })
})
