/**
 * Session children (desktop half).
 * One pane for all background agent work: workstreams, headless runners, subagents and
 * background processes. Data comes from the Python half (~/.hermes/plugins/session-children,
 * GET /api/plugins/session-children/summary).
 * Surfaces: sidebar row badge on the owning chat, "Spawned sessions" pane, status bar chip.
 */
import { atom, host, SESSION_ROW_AREAS, STATUSBAR_AREAS, useValue } from '@hermes/plugin-sdk'
import { useEffect, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'session-children'

// BEGIN pure helpers (no imports, no host calls: checked on their own by tests/test_core_plugins.py)
const TZ = 'America/New_York'
const KIND_ORDER = ['workstream', 'runner', 'subagent', 'process']
const KIND_TITLES = {
  workstream: 'Workstreams',
  runner: 'Headless runners',
  subagent: 'Subagents',
  process: 'Background processes'
}
const STATE_LABELS = { running: 'Running', finished: 'Finished', failed: 'Failed', stuck: 'Stuck' }
// Running is never red: the accent is the only colour a running item gets.
const COLORS = {
  running: 'var(--ui-accent)',
  finished: 'var(--ui-success)',
  failed: 'var(--ui-danger)',
  stuck: 'var(--ui-warning)'
}
const FADE_AFTER_MS = 10 * 60 * 1000

function etDay(ms) {
  return new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' }).format(ms)
}

// "5:42 PM EST" on the current Eastern day, "Nov 17, 5:42 PM EST" on another. Never UTC.
function formatEt(seconds, nowMs) {
  if (!seconds) return ''
  const ms = seconds * 1000
  const opts = { timeZone: TZ, hour: 'numeric', minute: '2-digit', timeZoneName: 'short' }
  if (etDay(ms) !== etDay(nowMs)) {
    opts.month = 'short'
    opts.day = 'numeric'
  }
  return new Intl.DateTimeFormat('en-US', opts).format(ms)
}

function elapsed(ms) {
  const s = Math.max(0, Math.floor(ms / 1000))
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  return m < 60 ? `${m}m ${String(s % 60).padStart(2, '0')}s` : `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m`
}

function ageText(seconds, nowMs) {
  if (!seconds) return ''
  const s = Math.max(0, Math.floor((nowMs - seconds * 1000) / 1000))
  if (s < 45) return 'just now'
  const m = Math.floor(s / 60)
  if (m < 60) return `${Math.max(1, m)}m ago`
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m ago`
}

function clip(text, n) {
  const t = String(text || '')
  return t.length > n ? `${t.slice(0, n - 3)}...` : t
}

function summarize(items) {
  const c = { running: 0, finished: 0, failed: 0, stuck: 0 }
  for (const it of items || []) c[it.state] = (c[it.state] || 0) + 1
  return c
}

function groupByKind(items) {
  const g = { workstream: [], runner: [], subagent: [], process: [] }
  for (const it of items || []) if (g[it.kind]) g[it.kind].push(it)
  const rank = { stuck: 0, failed: 1, running: 2, finished: 3 }
  for (const k of KIND_ORDER) g[k].sort((a, b) => (rank[a.state] ?? 4) - (rank[b.state] ?? 4) || (b.started_at || 0) - (a.started_at || 0))
  return g
}

// An old finished row fades. A failed or stuck row never does.
function isFaded(it, nowMs) {
  return it.state === 'finished' && !!it.finished_at && nowMs - it.finished_at * 1000 > FADE_AFTER_MS
}

// The second line of a row: when it started, when it last showed life, what happened.
function detailText(it, nowMs) {
  const bits = [`Started ${formatEt(it.started_at, nowMs)}`]
  if (it.state === 'running' || it.state === 'stuck') {
    bits.push(it.activity_at ? `Active ${formatEt(it.activity_at, nowMs)} (${ageText(it.activity_at, nowMs)})` : 'Last activity not recorded')
  } else if (it.finished_at) {
    bits.push(`Ended ${formatEt(it.finished_at, nowMs)}`)
  }
  const tail = it.state === 'running' ? it.activity : it.outcome || it.activity
  if (tail) bits.push(clip(tail, 120))
  if (it.archived) bits.push('archived')
  return bits.join(' \u00b7 ')
}
// END pure helpers

const $data = atom({ running: 0, attention: 0, sections: {}, all: [], by_parent: {}, by_child: {}, skew: 0 })
const $scope = atom('chat')
let pollTimer = null

async function refresh(ctx) {
  try {
    const res = await ctx.rest('/summary', { timeoutMs: 4000 })
    if (res && res.by_parent) $data.set({ ...res, skew: Date.now() - res.now * 1000 })
  } catch (e) {
    // Backend not enabled yet (plugins.enabled) or gateway restarting: keep the last data.
  }
}

function useTick(active) {
  const [, setN] = useState(0)
  useEffect(() => {
    if (!active) return undefined
    const t = setInterval(() => setN(n => n + 1), 1000)
    return () => clearInterval(t)
  }, [active])
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

function RowBadge({ sessionId }) {
  const data = useValue($data)
  const link = data.by_child[sessionId]
  const children = data.by_parent[sessionId]
  if (link) {
    const own = children && children.length ? summarize(children).running : 0
    return jsxs('span', {
      className: 'contents',
      children: [
        own ? pill(COLORS.running, false, `${own} running`) : null,
        jsx('span', {
          className: 'shrink-0 rounded-full px-1.5 text-[0.625rem] font-medium leading-4 text-(--ui-text-tertiary)',
          style: { boxShadow: 'inset 0 0 0 1px var(--ui-stroke-secondary)' },
          title: `Spawned by: ${link.parent_title}`,
          children: `\u21b3 ${clip(link.parent_title, 18)}`
        })
      ]
    })
  }
  if (!children || !children.length) return null
  const c = summarize(children)
  if (c.failed) return pill(COLORS.failed, true, `${c.failed} failed`)
  if (c.stuck) return pill(COLORS.stuck, true, `${c.stuck} stuck`)
  if (c.running) return pill(COLORS.running, false, `${c.running} running`)
  return pill(COLORS.finished, true, `${c.finished} done`)
}

function ItemRow({ item, skew, nowMs }) {
  const running = item.state === 'running'
  const alarm = item.state === 'failed' || item.state === 'stuck'
  const startedMs = (item.started_at || 0) * 1000
  const endMs = item.finished_at ? item.finished_at * 1000 : nowMs
  const color = COLORS[item.state] || COLORS.stuck
  return jsxs('button', {
    type: 'button',
    disabled: !item.open_id,
    className:
      'flex w-full flex-col gap-0.5 rounded px-2 py-1 text-left text-xs enabled:hover:bg-(--chrome-action-hover) disabled:cursor-default',
    style: {
      opacity: isFaded(item, nowMs) ? 0.55 : 1,
      background: alarm ? `color-mix(in srgb, ${color} 10%, transparent)` : undefined,
      boxShadow: alarm ? `inset 2px 0 0 ${color}` : undefined
    },
    onClick: () => item.open_id && host.openSession(item.open_id),
    children: [
      jsxs('span', {
        className: 'flex w-full items-center gap-2',
        children: [
          jsx('span', {
            'aria-hidden': 'true',
            className: running ? 'inline-block size-2 shrink-0 animate-pulse rounded-full' : 'inline-block size-2 shrink-0 rounded-full',
            style: { background: color }
          }),
          jsx('span', { className: 'min-w-0 flex-1 truncate font-medium', title: item.title, children: item.title }),
          pill(color, !running, STATE_LABELS[item.state] || item.state),
          jsx('span', { className: 'w-16 shrink-0 text-right tabular-nums', children: elapsed(endMs - startedMs) })
        ]
      }),
      jsx('span', {
        className: 'truncate pl-4',
        style: { color: alarm ? color : 'var(--ui-text-tertiary)' },
        title: detailText(item, nowMs),
        children: detailText(item, nowMs)
      })
    ]
  })
}

function Section({ kind, items, info, skew, nowMs }) {
  const c = summarize(items)
  const counts = [c.running ? `${c.running} running` : '', c.stuck ? `${c.stuck} stuck` : '', c.failed ? `${c.failed} failed` : ''].filter(Boolean).join(', ')
  let empty = null
  if (!items.length) {
    const unavailable = info && info.ok === false
    empty = jsx('div', {
      className: 'px-2 pb-1 text-xs',
      style: { color: unavailable ? COLORS.stuck : 'var(--ui-text-tertiary)' },
      children: unavailable ? info.note : (info && info.note) || 'None in the last 30 minutes.'
    })
  }
  return jsxs('div', {
    className: 'flex flex-col gap-0.5',
    children: [
      jsxs('div', {
        className: 'flex items-baseline gap-2 px-2 pt-1 text-[0.6875rem] font-semibold uppercase tracking-wide text-(--ui-text-secondary)',
        children: [KIND_TITLES[kind], jsx('span', { className: 'font-normal normal-case text-(--ui-text-tertiary)', children: counts || (items.length ? 'all finished' : '') })]
      }),
      empty,
      ...items.map(it => jsx(ItemRow, { item: it, skew, nowMs }, it.id))
    ]
  })
}

function ScopeButton({ label, active, onClick }) {
  return jsx('button', {
    type: 'button',
    onClick,
    className: 'rounded px-2 py-0.5 text-[0.6875rem] hover:bg-(--chrome-action-hover)',
    style: active ? { boxShadow: 'inset 0 0 0 1px var(--ui-stroke-secondary)', fontWeight: 600 } : { color: 'var(--ui-text-tertiary)' },
    children: label
  })
}

function ChildrenPane() {
  const data = useValue($data)
  const scope = useValue($scope)
  const focused = useValue(host.state.focusedStoredSessionId)
  const mine = (focused && data.by_parent[focused]) || []
  const all = data.all || []
  const items = scope === 'all' ? all : mine
  const nowMs = Date.now() - (data.skew || 0)
  useTick(all.some(it => it.state === 'running' || it.state === 'stuck'))
  const groups = groupByKind(items)
  return jsxs('div', {
    className: 'flex h-full flex-col gap-1 overflow-auto p-2',
    children: [
      jsxs('div', {
        className: 'flex items-center gap-1',
        children: [
          jsx(ScopeButton, { label: `This chat (${mine.length})`, active: scope !== 'all', onClick: () => $scope.set('chat') }),
          jsx(ScopeButton, { label: `All chats (${all.length})`, active: scope === 'all', onClick: () => $scope.set('all') })
        ]
      }),
      ...KIND_ORDER.map(kind => jsx(Section, { kind, items: groups[kind], info: (data.sections || {})[kind], skew: data.skew, nowMs }, kind))
    ]
  })
}

function Chip() {
  const data = useValue($data)
  if (!data.running && !data.attention) return null
  return jsxs('span', {
    className: 'inline-flex h-full items-center gap-2 px-1.5 text-[0.6875rem]',
    title: 'Background agent work: running now, and failed or stuck items that need a look',
    children: [
      data.running
        ? jsxs('span', {
            className: 'inline-flex items-center gap-1',
            style: { color: COLORS.running },
            children: [
              jsx('span', { 'aria-hidden': 'true', className: 'inline-block size-1.5 animate-pulse rounded-full', style: { background: COLORS.running } }),
              `${data.running} background running`
            ]
          })
        : null,
      data.attention ? jsx('span', { style: { color: COLORS.failed }, children: `${data.attention} need a look` }) : null
    ]
  })
}

export default {
  id: ID,
  name: 'Session children',
  register(ctx) {
    refresh(ctx)
    pollTimer = setInterval(() => refresh(ctx), 3000)
    ctx.onDispose(() => {
      clearInterval(pollTimer)
      pollTimer = null
    })

    ctx.register({
      id: 'row-badge',
      area: SESSION_ROW_AREAS.trailing,
      data: { render: ({ sessionId }) => jsx(RowBadge, { sessionId }) }
    })
    ctx.register({
      id: 'children-pane',
      area: 'panes',
      title: 'Spawned sessions',
      render: () => jsx(ChildrenPane, {}),
      data: { placement: 'bottom', dock: { pane: 'workspace', pos: 'bottom' }, height: '280px' }
    })
    ctx.register({ id: 'chip', area: STATUSBAR_AREAS.left, order: 91, render: () => jsx(Chip, {}) })
  }
}
