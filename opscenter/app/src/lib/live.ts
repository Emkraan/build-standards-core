// The push channel client (Local Ops App section 20). One EventSource for the whole app: the server says which topic moved,
// never what changed, and a store reads the endpoint it already knows. While the channel is connected the stores stretch their
// own timers to a five minute safety net. When it cannot connect, the stores' own timers apply unchanged (the fallback).
// Topics: data:<file>.json for a bundled dataset, a short alias for an endpoint every page reads (setAliases, in step with the
// server's live_bus.ALIASES), api:/api/<path> for any other endpoint.
import { useSyncExternalStore } from 'react'

const BASE = import.meta.env?.BASE_URL || './'

export type LiveStatus = 'connecting' | 'live' | 'reconnecting' | 'off'
export interface LiveSnapshot {
  status: LiveStatus
  /** When the stream last became live, or the last time it dropped, epoch ms (0 before the first connect). */
  since: number
  /** Epoch ms of the last topic event or hello, 0 when none. */
  lastEventAt: number
}

export const BACKOFF_MS = [1000, 2000, 5000, 10_000, 30_000]
/** The safety-net poll while the channel is connected. */
export const STRETCH_MS = 5 * 60_000
export const PRESENCE_DEBOUNCE_MS = 300

let ALIASES: Record<string, string> = {}
/** Short topic names for endpoints every page reads, the same table as live_bus.ALIASES on the server. */
export function setAliases(next: Record<string, string>) {
  ALIASES = { ...next }
}

export function normalizePath(path: string): string {
  const p = path.split('?')[0].replace(/^\.?\/?/, '/')
  return p
}
export function apiTopic(path: string): string {
  const p = normalizePath(path)
  return ALIASES[p] ?? `api:${p}`
}
export function dataTopic(name: string): string {
  return `data:${name}`
}

type Cb = () => void
const subs = new Map<string, Set<Cb>>()
const wants = new Map<string, { path: string | null; ms: number; n: number }>()
const statusSubs = new Set<Cb>()

let es: EventSource | null = null
let snap: LiveSnapshot = { status: 'connecting', since: 0, lastEventAt: 0 }
let streamId: string | null = null
let attempt = 0
let retryTimer: ReturnType<typeof setTimeout> | null = null
let presenceTimer: ReturnType<typeof setTimeout> | null = null
let everLive = false
let started = false
let visHooked = false

function setSnap(next: Partial<LiveSnapshot>) {
  const prev = snap
  snap = { ...snap, ...next }
  if (prev.status !== snap.status || prev.lastEventAt !== snap.lastEventAt) for (const f of statusSubs) f()
}

export function getLiveSnapshot(): LiveSnapshot {
  return snap
}
export function isLive(): boolean {
  return snap.status === 'live'
}
/** The poll interval a store should use right now. */
export function stretchedMs(ms: number): number {
  return isLive() ? Math.max(ms, STRETCH_MS) : ms
}
export function onStatus(cb: Cb): () => void {
  statusSubs.add(cb)
  return () => statusSubs.delete(cb)
}
export function useLiveStatus(): LiveSnapshot {
  return useSyncExternalStore(onStatus, getLiveSnapshot, getLiveSnapshot)
}

function notify(topic: string) {
  subs.get(topic)?.forEach((f) => {
    f()
  })
}
function notifyAll() {
  for (const t of subs.keys()) notify(t)
}

/** Run cb when the topic moves. Starts the channel on the first call. Returns the unsubscribe. */
export function subscribe(topic: string, cb: Cb): () => void {
  const set = subs.get(topic) ?? new Set<Cb>()
  subs.set(topic, set)
  set.add(cb)
  start()
  return () => {
    set.delete(cb)
    if (set.size === 0 && subs.get(topic) === set) subs.delete(topic)
  }
}

/** Tell the server which endpoint this tab shows and how often, so its warm loop reads it while the tab is visible.
 *  A topic with no path (a dataset) is declared too, it only keeps the presence record complete. */
export function declare(topic: string, path: string | null, ms: number): () => void {
  const cur = wants.get(topic)
  if (cur) {
    cur.n += 1
    cur.ms = Math.min(cur.ms, ms)
  } else {
    wants.set(topic, { path, ms, n: 1 })
  }
  start()
  schedulePresence()
  return () => {
    const w = wants.get(topic)
    if (!w) return
    w.n -= 1
    if (w.n <= 0) wants.delete(topic)
    schedulePresence()
  }
}

function visible(): boolean {
  return typeof document === 'undefined' || document.visibilityState === 'visible'
}

export function presenceBody(): { id: string; visible: boolean; wants: { topic: string; path?: string; ms: number }[] } | null {
  if (!streamId) return null
  const list = [...wants.entries()].map(([topic, w]) => (w.path ? { topic, path: normalizePath(w.path), ms: w.ms } : { topic, ms: w.ms }))
  return { id: streamId, visible: visible(), wants: list }
}

function schedulePresence() {
  if (presenceTimer || !streamId) return
  presenceTimer = setTimeout(() => {
    presenceTimer = null
    const body = presenceBody()
    if (!body) return
    fetch(`${BASE}api/live/presence`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).catch(() => {
      // The stream will reconnect and send the presence again on its hello.
    })
  }, PRESENCE_DEBOUNCE_MS)
}

function onVisibility() {
  if (presenceTimer) {
    clearTimeout(presenceTimer)
    presenceTimer = null
  }
  schedulePresence()
}

function open() {
  if (typeof EventSource === 'undefined') {
    setSnap({ status: 'off' })
    return
  }
  let src: EventSource
  try {
    src = new EventSource(`${BASE}api/live`)
  } catch {
    setSnap({ status: 'off' })
    return
  }
  es = src
  src.addEventListener('hello', (e) => {
    try {
      const d = JSON.parse((e as MessageEvent).data) as { id: string }
      streamId = d.id
    } catch {
      return
    }
    attempt = 0
    const reconnect = everLive
    everLive = true
    setSnap({ status: 'live', since: Date.now(), lastEventAt: Date.now() })
    schedulePresence()
    // After an outage the topics may have moved while nothing listened: every store reads once.
    if (reconnect) notifyAll()
  })
  src.addEventListener('topic', (e) => {
    try {
      const d = JSON.parse((e as MessageEvent).data) as { t: string }
      setSnap({ lastEventAt: Date.now() })
      notify(d.t)
    } catch {
      // A frame that is not JSON is ignored.
    }
  })
  src.onerror = () => {
    src.close()
    if (es === src) es = null
    streamId = null
    const wasLive = snap.status === 'live'
    setSnap({ status: 'reconnecting', since: wasLive ? Date.now() : snap.since })
    const delay = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)]
    attempt += 1
    retryTimer = setTimeout(() => {
      retryTimer = null
      open()
    }, delay)
  }
}

/** Open the channel once. Safe to call from anywhere. */
export function start() {
  if (started) return
  started = true
  if (!visHooked && typeof document !== 'undefined') {
    visHooked = true
    document.addEventListener('visibilitychange', onVisibility)
  }
  open()
}

/** Test hook: close everything and forget all state. */
export function resetLiveForTests() {
  es?.close()
  es = null
  if (retryTimer) clearTimeout(retryTimer)
  if (presenceTimer) clearTimeout(presenceTimer)
  retryTimer = presenceTimer = null
  subs.clear()
  wants.clear()
  statusSubs.clear()
  streamId = null
  attempt = 0
  everLive = false
  started = false
  snap = { status: 'connecting', since: 0, lastEventAt: 0 }
  if (visHooked && typeof document !== 'undefined') document.removeEventListener('visibilitychange', onVisibility)
  visHooked = false
}
