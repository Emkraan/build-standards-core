/**
 * Session children (desktop half).
 * Live view of sessions spawned from a parent session. Data comes from the Python half
 * (~/.hermes/plugins/session-children, GET /api/plugins/session-children/summary).
 * Surfaces: sidebar row badge on the parent, "Spawned sessions" pane, status bar chip.
 */
import { atom, host, SESSION_ROW_AREAS, STATUSBAR_AREAS, useValue } from '@hermes/plugin-sdk'
import { useEffect, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'session-children'
const COLORS = {
  running: 'var(--ui-accent)',
  done: 'var(--ui-success)',
  failed: 'var(--ui-danger)',
  lost: 'var(--ui-warning)'
}
const LABELS = { running: 'Running', done: 'Done', failed: 'Failed', lost: 'Lost' }

const $data = atom({ running: 0, by_parent: {}, by_child: {}, skew: 0 })
let pollTimer = null

async function refresh(ctx) {
  try {
    const res = await ctx.rest('/summary', { timeoutMs: 4000 })
    if (res && res.by_parent) $data.set({ ...res, skew: Date.now() - res.now * 1000 })
  } catch (e) {
    // Backend not enabled yet (plugins.enabled) or gateway restarting: keep the last data.
  }
}

function elapsed(ms) {
  const s = Math.max(0, Math.floor(ms / 1000))
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  return m < 60 ? `${m}m ${String(s % 60).padStart(2, '0')}s` : `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m`
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

function summarize(children) {
  const c = { running: 0, done: 0, failed: 0, lost: 0 }
  for (const ch of children || []) c[ch.state] = (c[ch.state] || 0) + 1
  return c
}

function clip(text, n) {
  return text.length > n ? `${text.slice(0, n - 1)}...` : text
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
  if (c.running) return pill(COLORS.running, false, `${c.running} running`)
  if (c.failed) return pill(COLORS.failed, true, `${c.failed} failed`)
  if (c.lost) return pill(COLORS.lost, true, `${c.lost} lost`)
  return pill(COLORS.done, true, `${c.done} done`)
}

function ChildRow({ child, skew }) {
  const running = child.state === 'running'
  const startedMs = child.started_at * 1000 + skew
  const endMs = child.finished_at ? child.finished_at * 1000 + skew : Date.now()
  return jsxs('button', {
    type: 'button',
    className:
      'flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs hover:bg-(--chrome-action-hover)',
    onClick: () => host.openSession(child.id),
    children: [
      jsx('span', {
        'aria-hidden': 'true',
        className: running ? 'inline-block size-2 shrink-0 animate-pulse rounded-full' : 'inline-block size-2 shrink-0 rounded-full',
        style: { background: COLORS[child.state] }
      }),
      jsx('span', { className: 'min-w-0 flex-1 truncate font-medium', children: child.title }),
      jsx('span', {
        className: 'min-w-0 flex-[2] truncate text-(--ui-text-tertiary)',
        children: running ? child.activity || 'working' : LABELS[child.state] + (child.archived ? ' (archived)' : '')
      }),
      jsx('span', {
        className: 'shrink-0 tabular-nums text-(--ui-text-tertiary)',
        children: `${child.tool_calls} calls`
      }),
      jsx('span', { className: 'w-16 shrink-0 text-right tabular-nums', children: elapsed(endMs - startedMs) })
    ]
  })
}

function ChildrenPane() {
  const data = useValue($data)
  const focused = useValue(host.state.focusedStoredSessionId)
  const children = (focused && data.by_parent[focused]) || []
  useTick(children.some(ch => ch.state === 'running'))
  if (!children.length) {
    return jsx('div', {
      className: 'p-3 text-xs text-(--ui-text-tertiary)',
      children: 'No spawned sessions from this chat in the last 30 minutes.'
    })
  }
  const sorted = [...children].sort((a, b) => (a.state === 'running' ? -1 : 0) - (b.state === 'running' ? -1 : 0) || b.started_at - a.started_at)
  return jsx('div', {
    className: 'flex h-full flex-col gap-0.5 overflow-auto p-2',
    children: sorted.map(ch => jsx(ChildRow, { child: ch, skew: data.skew }, ch.id))
  })
}

function Chip() {
  const data = useValue($data)
  if (!data.running) return null
  return jsxs('span', {
    className: 'inline-flex h-full items-center gap-1 px-1.5 text-[0.6875rem]',
    style: { color: COLORS.running },
    title: 'Sessions spawned from other sessions that are still running',
    children: [
      jsx('span', { 'aria-hidden': 'true', className: 'inline-block size-1.5 animate-pulse rounded-full', style: { background: COLORS.running } }),
      `${data.running} spawned running`
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
      data: { placement: 'bottom', dock: { pane: 'workspace', pos: 'bottom' }, height: '190px' }
    })
    ctx.register({ id: 'chip', area: STATUSBAR_AREAS.left, order: 91, render: () => jsx(Chip, {}) })
  }
}
