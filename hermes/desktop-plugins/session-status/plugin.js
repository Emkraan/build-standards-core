// Session Status v2
// Purpose: a text badge on every sidebar row that can never disagree with the row's own dot.
// v1 inferred state from gateway events and missed any session that was already running or finished
// before the plugin loaded. v2 reads the app's resolved state from core's own SessionStatusDot
// (the one primitive the app says plugins must use), so the badge and the dot are the same fact.
// Events are used only for what core does not track: elapsed turn time and Failed / Stopped.
import { atom, host, SessionStatusDot, STATUSBAR_AREAS, SESSION_ROW_AREAS, useValue } from '@hermes/plugin-sdk'
import { useEffect, useRef, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const LONG_TURN_MS = 45000
const LIVE = new Set(['working', 'stalled', 'needs-input'])

// stored id -> { core, since, turnStart }  (core = the app's own dot state)
const $rows = atom({})
// stored id -> { kind: 'failed' | 'stopped', at }
const $ended = atom({})

const refs = {}
const runtimeToStored = {}
const titles = {}
const pendingStart = {}
let ctxRef = null
let lastRefresh = 0

const COLORS = {
  'needs-input': 'var(--ui-warning, #f59e0b)',
  working: 'var(--ui-accent)',
  stalled: 'var(--ui-accent)',
  background: 'var(--ui-text-tertiary)',
  unread: 'var(--ui-success)',
  failed: 'var(--ui-danger, #ef4444)',
  stopped: 'var(--ui-text-tertiary)'
}

// Core paints each state with a distinct class set (session-status-dot.tsx DOT_VARIANTS).
function readCore(root) {
  const dot = root.querySelector('[class*="rounded-full"]')
  if (!dot) return 'idle'
  const c = String(dot.className)
  if (c.includes('bg-amber-500')) return 'needs-input'
  if (c.includes('bg-(--ui-accent)')) return 'working'
  if (c.includes('border-(--ui-accent)')) return 'stalled'
  if (c.includes('border-(--ui-text-tertiary)')) return 'background'
  if (c.includes('bg-(--ui-success)')) return 'unread'
  if (c.includes('border-(--ui-text-quaternary)')) return 'draft'
  const label = String(dot.getAttribute('aria-label') || '')
  if (/input/i.test(label)) return 'needs-input'
  if (/unread|finished/i.test(label)) return 'unread'
  if (/running/i.test(label)) return 'working'
  return 'idle'
}

function elapsed(ms) {
  const s = Math.max(0, Math.floor(ms / 1000))
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m`
  return `${Math.floor(m / 60)}h ${m % 60}m`
}

function notifyOs(stored, title, body) {
  if (!ctxRef) return
  try {
    ctxRef.os.notify({
      title,
      body,
      onActivate: () => {
        if (stored) host.openSession(stored)
      }
    })
  } catch (e) {
    console.warn('[session-status] notify failed', e)
  }
}

function setRow(id, entry) {
  $rows.set({ ...$rows.get(), [id]: entry })
}

function setEnded(id, value) {
  const all = { ...$ended.get() }
  if (value) all[id] = value
  else delete all[id]
  $ended.set(all)
}

// Called whenever a row's core dot state is (re)read.
function observe(id, core) {
  const prev = $rows.get()[id]
  if (prev && prev.core === core) return
  const now = Date.now()
  const wasLive = Boolean(prev) && LIVE.has(prev.core)
  const isLive = LIVE.has(core)
  let turnStart = prev ? prev.turnStart : 0
  if (isLive && !wasLive) {
    // A turn we watched start is timed from the start event or now. A turn already running when we
    // first saw the row has no known start, so it shows no clock rather than a wrong one.
    turnStart = pendingStart[id] && now - pendingStart[id] < 15000 ? pendingStart[id] : prev ? now : 0
    delete pendingStart[id]
    setEnded(id, null)
  }
  if (!isLive) turnStart = wasLive ? turnStart : 0
  setRow(id, { core, since: now, turnStart })
  if (!prev) return

  if (core === 'needs-input' && prev.core !== 'needs-input') {
    notifyOs(id, 'Waiting on you', titles[id] || 'A session needs your answer')
    return
  }
  if (wasLive && !isLive) {
    const took = prev.turnStart ? now - prev.turnStart : 0
    // message.complete may land just after the dot flips, so decide on a short delay.
    setTimeout(() => {
      const ended = $ended.get()[id]
      if (ended && Date.now() - ended.at < 8000) {
        notifyOs(id, ended.kind === 'failed' ? 'Session failed' : 'Session stopped', titles[id] || '')
      } else if (took >= LONG_TURN_MS) {
        notifyOs(id, 'Session finished', titles[id] || '')
      }
    }, 1500)
  }
}

function effective(id, rows, ended) {
  const row = rows[id]
  if (!row) return null
  const e = ended[id]
  if (e && (row.core === 'idle' || row.core === 'unread')) return e.kind
  return row.core
}

async function refreshMap() {
  const now = Date.now()
  if (now - lastRefresh < 2000) return
  lastRefresh = now
  try {
    const res = await host.request('session.active_list', {})
    for (const row of (res && res.sessions) || []) {
      if (!row.id || !row.session_key) continue
      runtimeToStored[row.id] = row.session_key
      if (row.title) titles[row.session_key] = row.title
    }
  } catch (e) {
    console.warn('[session-status] active_list failed', e)
  }
}

async function storedFor(runtimeId) {
  if (!runtimeToStored[runtimeId]) {
    lastRefresh = 0
    await refreshMap()
  }
  return runtimeToStored[runtimeId] || null
}

async function handleEvent(ev) {
  const type = ev && ev.type
  const rid = ev && ev.session_id
  if (!type || !rid) return
  if (type === 'session.info') {
    const p = ev.payload || {}
    if (p.stored_session_id) runtimeToStored[rid] = p.stored_session_id
    if (p.stored_session_id && typeof p.title === 'string' && p.title) titles[p.stored_session_id] = p.title
    return
  }
  if (type === 'session.reclaimed') {
    delete runtimeToStored[rid]
    return
  }
  if (type === 'message.start') {
    const stored = await storedFor(rid)
    if (!stored) return
    setEnded(stored, null)
    const row = $rows.get()[stored]
    if (row && LIVE.has(row.core) && !row.turnStart) setRow(stored, { ...row, turnStart: Date.now() })
    else pendingStart[stored] = Date.now()
    return
  }
  if (type === 'message.complete') {
    const status = ev.payload && ev.payload.status
    const stored = await storedFor(rid)
    if (!stored) return
    if (status === 'error' || status === 'interrupted') {
      setEnded(stored, { kind: status === 'error' ? 'failed' : 'stopped', at: Date.now() })
      if (host.state.focusedStoredSessionId.get() === stored) setTimeout(() => setEnded(stored, null), 6000)
    } else {
      setEnded(stored, null)
    }
  }
}

function pill(color, hollow, text) {
  return jsx('span', {
    className: 'shrink-0 rounded-full px-1.5 text-[0.625rem] font-medium leading-4',
    style: hollow
      ? { color, boxShadow: `inset 0 0 0 1px ${color}` }
      : { color, background: `color-mix(in srgb, ${color} 16%, transparent)` },
    children: text
  })
}

function useTick(active) {
  const [, setN] = useState(0)
  useEffect(() => {
    if (!active) return undefined
    const t = setInterval(() => setN(n => n + 1), 1000)
    return () => clearInterval(t)
  }, [active])
}

function SessionBadge({ sessionId }) {
  const probe = useRef(null)
  const rows = useValue($rows)
  const ended = useValue($ended)

  useEffect(() => {
    const root = probe.current
    if (!root) return undefined
    refs[sessionId] = (refs[sessionId] || 0) + 1
    const sync = () => observe(sessionId, readCore(root))
    sync()
    const mo = new MutationObserver(sync)
    mo.observe(root, { subtree: true, childList: true, attributes: true, attributeFilter: ['class', 'aria-label'] })
    return () => {
      mo.disconnect()
      refs[sessionId] -= 1
      if (refs[sessionId] <= 0) {
        delete refs[sessionId]
        const { [sessionId]: _gone, ...rest } = $rows.get()
        $rows.set(rest)
      }
    }
  }, [sessionId])

  const state = effective(sessionId, rows, ended)
  const row = rows[sessionId]
  useTick(state === 'working' || state === 'stalled')

  // The probe is core's own dot, hidden. Its class and label are the single source of truth.
  const hidden = jsx('span', {
    ref: probe,
    'aria-hidden': 'true',
    style: { display: 'none' },
    children: jsx(SessionStatusDot, { storedSessionId: sessionId })
  })

  let badge = null
  if (state === 'needs-input') badge = pill(COLORS[state], false, 'Needs you')
  else if (state === 'working') badge = pill(COLORS[state], false, row && row.turnStart ? elapsed(Date.now() - row.turnStart) : 'Working')
  else if (state === 'stalled') badge = pill(COLORS[state], true, row && row.turnStart ? `Quiet ${elapsed(Date.now() - row.turnStart)}` : 'Quiet')
  else if (state === 'background') badge = pill(COLORS[state], true, 'Background')
  else if (state === 'unread') badge = pill(COLORS[state], false, 'Done')
  else if (state === 'failed') badge = pill(COLORS[state], false, 'Failed')
  else if (state === 'stopped') badge = pill(COLORS[state], false, 'Stopped')

  return jsxs('span', { className: 'contents', children: [hidden, badge] })
}

function nextTarget(rows, ended) {
  const order = ['needs-input', 'failed', 'stopped', 'unread']
  for (const want of order) {
    const hit = Object.keys(rows)
      .filter(id => effective(id, rows, ended) === want)
      .sort((a, b) => rows[a].since - rows[b].since)[0]
    if (hit) return hit
  }
  return null
}

function SummaryChip() {
  const rows = useValue($rows)
  const ended = useValue($ended)
  const counts = { 'needs-input': 0, working: 0, failed: 0, unread: 0 }
  for (const id of Object.keys(rows)) {
    const s = effective(id, rows, ended)
    if (s === 'stalled') counts.working += 1
    else if (s === 'stopped') counts.failed += 1
    else if (counts[s] !== undefined) counts[s] += 1
  }
  const names = { 'needs-input': 'waiting', working: 'working', failed: 'failed', unread: 'done' }
  const parts = ['needs-input', 'working', 'failed', 'unread'].filter(k => counts[k] > 0)
  if (!parts.length) return null
  const target = nextTarget(rows, ended)
  return jsx('button', {
    type: 'button',
    title: target ? 'Open the next session that needs attention' : 'Session status',
    className: 'inline-flex h-full items-center gap-2 px-1.5 text-[0.6875rem] hover:bg-(--chrome-action-hover)',
    onClick: () => {
      if (target) host.openSession(target)
      else host.notify({ kind: 'info', message: 'Nothing needs attention right now.' })
    },
    children: parts.map(k =>
      jsxs(
        'span',
        {
          className: 'inline-flex items-center gap-1',
          style: { color: COLORS[k] },
          children: [
            jsx('span', {
              'aria-hidden': 'true',
              className: 'inline-block size-1.5 rounded-full',
              style: { background: COLORS[k] }
            }),
            `${counts[k]} ${names[k]}`
          ]
        },
        k
      )
    )
  })
}

export default {
  id: 'session-status',
  name: 'Session Status',
  register(ctx) {
    ctxRef = ctx
    refreshMap()
    const poll = setInterval(refreshMap, 5000)

    // Opening a session acknowledges a Failed or Stopped marker.
    const offFocus = host.state.focusedStoredSessionId.subscribe(stored => {
      if (stored && $ended.get()[stored]) setEnded(stored, null)
    })

    ctx.onEvent('*', ev => {
      handleEvent(ev).catch(e => console.warn('[session-status] event failed', e))
    })

    ctx.onDispose(() => {
      clearInterval(poll)
      offFocus()
      ctxRef = null
    })

    ctx.register({
      id: 'row-badge',
      area: SESSION_ROW_AREAS.trailing,
      data: { render: ({ sessionId }) => jsx(SessionBadge, { sessionId }) }
    })

    ctx.register({
      id: 'summary-chip',
      area: STATUSBAR_AREAS.left,
      order: 90,
      render: () => jsx(SummaryChip, {})
    })
  }
}
