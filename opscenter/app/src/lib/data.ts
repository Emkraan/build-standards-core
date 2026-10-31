// Central data access. The app is fully static; all data comes from JSON files
// bundled under public/data by bundle_data.py. This hook fetches once and caches.
import { useEffect, useRef, useState } from 'react'

const BASE = import.meta.env.BASE_URL || './'

const cache: Record<string, unknown> = {}

const raw: Record<string, string> = {}
export const POLL_MS = 60_000

// Per-key bookkeeping for the GET cache (web-client-runtime 3.2 to 3.6).
// inflight: the one request a key has going, shared by every caller (3.2).
// gen: bumped by invalidateData, a response that finishes under an older generation never writes the cache (3.5, 3.6).
// loadedAt and ttl: a key with a finite TTL refreshes in the background once older than it (3.3).
const inflight: Record<string, Promise<unknown>> = {}
const gen: Record<string, number> = {}
const loadedAt: Record<string, number> = {}
const ttl: Record<string, number> = {}

// A key never goes stale until a TTL is set for it, so the default read behaves exactly as before.
export function setDataTtl(name: string, ms: number): void {
  ttl[name] = ms
}

// Forget a key: its cached value and any GET still in flight for it, so the next read starts fresh (3.5).
export function invalidateData(name: string): void {
  gen[name] = (gen[name] ?? 0) + 1
  delete inflight[name]
  delete cache[name]
  delete raw[name]
  delete loadedAt[name]
}

function isStale(name: string): boolean {
  const t = ttl[name]
  return t !== undefined && Date.now() - (loadedAt[name] ?? 0) > t
}

// One request per key. Callers that arrive while it is in flight get the same promise (3.2). The entry is
// removed when the request settles, so a rejection leaves nothing stuck and the next read sends a new
// request (3.6). A request started before an invalidate returns its own result but leaves the cache alone.
function requestData<T>(name: string): Promise<T> {
  const running = inflight[name]
  if (running) return running as Promise<T>
  const started = gen[name] ?? 0
  const current = (async (): Promise<T> => {
    const res = await fetch(`${BASE}data/${name}`, { cache: 'no-cache' })
    if (!res.ok) throw new Error(`failed to load ${name}: ${res.status}`)
    const text = await res.text()
    const superseded = (gen[name] ?? 0) !== started
    if (!superseded && raw[name] === text && cache[name]) {
      loadedAt[name] = Date.now()
      return cache[name] as T
    }
    const json = JSON.parse(text) as T
    if (!superseded) {
      raw[name] = text
      cache[name] = json
      loadedAt[name] = Date.now()
    }
    return json
  })()
  inflight[name] = current
  const clear = () => {
    if (inflight[name] === current) delete inflight[name]
  }
  current.then(clear, clear)
  return current
}

// fresh=true bypasses the in-memory cache. Unchanged payloads return the SAME
// object so React skips the re-render on a no-op poll. A cached read past its
// TTL returns the cached value at once and refreshes in the background (3.3).
export async function loadData<T>(name: string, fresh = false): Promise<T> {
  if (!fresh && cache[name]) {
    if (isStale(name) && !inflight[name]) {
      requestData<T>(name).catch((e) => console.warn(`background refresh of ${name} failed`, e))
    }
    return cache[name] as T
  }
  return requestData<T>(name)
}

// Run cb now, on an interval while the tab is visible, and whenever the tab
// regains focus. Returns the cleanup.
export function onLiveTick(cb: () => void, ms: number): () => void {
  const id = window.setInterval(() => {
    if (document.visibilityState === 'visible') cb()
  }, ms)
  const onVis = () => {
    if (document.visibilityState === 'visible') cb()
  }
  document.addEventListener('visibilitychange', onVis)
  return () => {
    window.clearInterval(id)
    document.removeEventListener('visibilitychange', onVis)
  }
}

// Shared live store for a never-cached API endpoint: one poller no matter how
// many components subscribe (sidebar badge + page), started on first
// subscriber, stopped on last. mutate() applies an optimistic local edit.
// refresh() asks the fetcher for a fresh (server-cache-bypassing) read. A
// fetcher that ignores the flag behaves exactly like reload().
export interface LiveState<T> {
  data: T | null
  error: string | null
  at: number
  loading: boolean
  reload: () => void
  refresh: () => void
  mutate: (fn: (d: T) => T) => void
}
export function createLiveStore<T>(fetcher: (fresh?: boolean) => Promise<T>, ms: number): () => LiveState<T> {
  let snap: { data: T | null; error: string | null; at: number } = { data: null, error: null, at: 0 }
  const subs = new Set<() => void>()
  let stop: (() => void) | null = null
  let inflight = false
  const emit = () =>
    subs.forEach((f) => {
      f()
    })
  const load = (fresh: boolean) => {
    if (inflight) return
    inflight = true
    emit()
    fetcher(fresh)
      .then((d) => {
        snap = { data: d, error: null, at: Date.now() }
      })
      .catch((e) => {
        snap = { ...snap, error: String(e) }
      })
      .finally(() => {
        inflight = false
        emit()
      })
  }
  const mutate = (fn: (d: T) => T) => {
    if (snap.data === null) return
    snap = { ...snap, data: fn(snap.data) }
    emit()
  }
  const reload = () => load(false)
  const refresh = () => load(true)
  return function useLiveStore() {
    const [, force] = useState(0)
    useEffect(() => {
      const f = () => force((n) => n + 1)
      subs.add(f)
      if (!stop) {
        reload()
        stop = onLiveTick(reload, ms)
      }
      return () => {
        subs.delete(f)
        if (subs.size === 0 && stop) {
          stop()
          stop = null
        }
      }
    }, [])
    return { ...snap, loading: inflight, reload, refresh, mutate }
  }
}

// Re-render tick for relative-time labels ("2m ago").
export function useNow(ms = 30_000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), ms)
    return () => window.clearInterval(id)
  }, [ms])
  return now
}

// The refresh cron rewrites the bundled JSON in place every 15 minutes, so the
// hook keeps polling instead of fetching once: the board stays live without a
// browser reload.
// One shared poller per dataset (createLiveStore): before this every caller ran its own timer, so a
// page plus the sidebar fetched action-center.json six times a minute.
const dataStores: Record<string, () => LiveState<unknown>> = {}
export function useData<T>(name: string, pollMs = POLL_MS): { data: T | null; error: string | null } {
  const key = `${name}@${pollMs}`
  if (!dataStores[key]) {
    dataStores[key] = createLiveStore<unknown>(() => loadData<unknown>(name, true), pollMs)
  }
  const st = dataStores[key]()
  return { data: (st.data as T | null) ?? (cache[name] as T) ?? null, error: st.data ? null : st.error }
}

// setInterval that only fires while the tab is visible, and once more when it becomes visible again.
export function useVisibleInterval(cb: () => void, ms: number | null): void {
  const ref = useRef(cb)
  ref.current = cb
  useEffect(() => {
    if (ms === null) return
    return onLiveTick(() => ref.current(), ms)
  }, [ms])
}

// Client-side persistence for handled-state (Resolve/Snooze/Ignore, draft
// sent/archived). The static app has no backend to write to, so these decisions
// live in localStorage exactly like the legacy flat dashboard. To make an
// "ignore always" survive across devices AND stop the analysis cron from
// resurfacing an item, owner exports the handled fingerprints ("Copy handled
// for ops_center") and pastes them back; ops_center records them server-side in
// action-suppressions.json. Same two-tier model as before.
export function useLocalStore<T>(key: string, initial: T): [T, (v: T | ((p: T) => T)) => void] {
  const [val, setVal] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key)
      return raw ? (JSON.parse(raw) as T) : initial
    } catch {
      return initial
    }
  })
  // Keep every hook instance on the same key in sync (sidebar/tab badges read
  // the same stores the pages write), within this tab and across tabs.
  // biome-ignore lint/correctness/useExhaustiveDependencies: initial is a per-render literal; re-subscribing on it would churn listeners
  useEffect(() => {
    const reread = (e: Event) => {
      const k = e instanceof StorageEvent ? e.key : (e as CustomEvent<string>).detail
      if (k !== key) return
      try {
        const raw = localStorage.getItem(key)
        setVal(raw ? (JSON.parse(raw) as T) : initial)
      } catch {
        // unreadable; keep current value
      }
    }
    window.addEventListener('localstore', reread)
    window.addEventListener('storage', reread)
    return () => {
      window.removeEventListener('localstore', reread)
      window.removeEventListener('storage', reread)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  const set = (v: T | ((p: T) => T)) => {
    setVal((prev) => {
      const next = typeof v === 'function' ? (v as (p: T) => T)(prev) : v
      try {
        localStorage.setItem(key, JSON.stringify(next))
      } catch {
        // storage full or blocked; keep in-memory only
      }
      window.setTimeout(() => window.dispatchEvent(new CustomEvent('localstore', { detail: key })), 0)
      return next
    })
  }
  return [val, set]
}

// ---- Shared types (mirror the bundler output) ----
export interface EngineerMetrics {
  assigned: number
  done: number
  completion_pct: number
  points_committed: number
  points_delivered: number
  per_sprint: Record<string, { assigned: number; done: number; points_committed: number; points_delivered: number }>
  carryover: { key: string; status: string; summary: string }[]
  not_done: { key: string; status: string; priority: string; points: number | null; summary: string }[]
  rejected: { key: string; summary: string }[]
  lead_time: {
    n: number
    median_days: number | null
    fresh_median_days: number | null
    aged_backlog_cleared: { key: string; lead_days: number }[]
  }
  mid_cycle_intake: number
  high_priority: { assigned: number; done: number }
  issue_types: Record<string, number>
}

export interface Narrative {
  verdict: string
  strengths: string[]
  watch: string[]
  blocked_on_me: string[]
}

export interface ActionItem {
  priority: string
  title: string
  why: string
  action: string
}

export interface TeamPerformance {
  generated_utc: string
  sprints: string[]
  sprint_ids: number[]
  sprint_meta: Record<string, { name: string; start: string; end: string }>
  engineers: string[]
  metrics: Record<string, EngineerMetrics>
  narrative: Record<string, Narrative>
  action_items: Record<string, ActionItem[]>
  team_summary: string
  drafts: { slug: string; title: string }[]
}

export interface HistoryRun {
  run_key: string
  assessed_utc: string
  sprints: string[]
  sprint_ids: number[]
  period_start: string
  period_end: string
  year: string
  month: string
  team_summary: string
  engineers: {
    name: string
    entra_id: string | null
    title: string | null
    assigned: number
    done: number
    completion_pct: number
    points_committed: number
    points_delivered: number
    carryover: number
    open: number
    mid_cycle_intake: number
    high_assigned: number
    high_done: number
    median_lead_fresh: number | null
    aged_backlog_cleared: number
    verdict: string
    // schema 3+: the full management read for that window (backfilled for older runs)
    review?: {
      strengths: string[]
      watch: string[]
      blocked_on_me: string[]
      action_items: ActionItem[]
    }
  }[]
}
export type HistoryEngineer = HistoryRun['engineers'][number]

export interface ProfilePoint {
  title: string
  detail: string
}

// All-time overall read of one person (state/team-performance/member-profiles.json).
// Rebuilt from every datapoint on record; never scoped to a sprint window.
export interface MemberProfile {
  name: string
  role: string
  evidence: { first_seen: string; last_seen: string; datapoints: number; sources: string[] }
  headline: string
  summary: string
  strengths: ProfilePoint[]
  growth: ProfilePoint[]
  working_style: string[]
  needs_from_me: string[]
  trajectory: { direction: 'rising' | 'steady' | 'mixed' | 'declining' | 'too-early'; detail: string }
  development_focus: string[]
}

export interface MemberProfiles {
  schema: number
  updated_utc: string
  profiles: Record<string, MemberProfile>
}

export interface HistoryMaster {
  schema: number
  run_count: number
  runs: HistoryRun[]
}

export interface Draft {
  slug: string
  title: string
  to: string
  channel: string
  status: string
  created: string
  tags: string[]
  body: string
}

export interface PlanningItem {
  slug: string
  title: string
  status: string
  owner: string
  created: string
  tags: string[]
  doc: string
  repo: string
  tickets: string[]
  body: string
}

// ---- Knowledge curation (served by server.py, not a bundled JSON) ----
export interface Proposal {
  fp: string
  kind: string
  target_id: number | string | null
  target_title: string
  parent_id: number | string | null
  domain: string
  summary: string
  scope_verdict: string
  body_format: string
  body_sha: string
  diff: string
  created_utc: string
  restaged_utc?: string
  feedback?: { reason: string; at: string; pending: boolean; status?: string; response?: string } | null
}
export interface CurationData {
  mode: string
  generated_utc: string
  note: string
  proposals: Proposal[]
}
export interface AppliedRecord {
  fp: string
  result: string
  page_id?: number | string
  title?: string
  when?: string
}

// Fetch a live API endpoint (curation/applied). Unlike loadData, this is never
// cached: curation state and applied outcomes change as the cron runs.
export async function fetchApi<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path.replace(/^\//, '')}`, { cache: 'no-cache' })
  if (!res.ok) throw new Error(`${path} -> ${res.status}`)
  return (await res.json()) as T
}

// POST approve/reject decisions to the same-origin backend, which queues them
// to approve-inbox.jsonl for the guarded applier cron. Loopback-only; no token
// needed client-side.
export async function postApprovals(
  decisions: { fp: string; act: string; body_sha: string; title: string; reason?: string }[],
): Promise<{ queued: number }> {
  const res = await fetch(`${BASE}api/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ decisions }),
  })
  if (!res.ok) {
    const j = await res.json().catch(() => ({}))
    throw new Error((j as { error?: string }).error || `approve -> ${res.status}`)
  }
  return (await res.json()) as { queued: number }
}

// Durable, cross-device Action Center handled state. The static app persists
// Resolve/Snooze/Ignore to localStorage for instant/offline response, but the
// server-side store (action-handled.json, served by server.py) is the
// authority: it survives a cleared browser or a different device AND the
// analysis cron reads it so a handled item stops being re-emitted. On load the
// UI hydrates from here; on every click it writes through.
export interface HandledEntry {
  act: string
  at: string
  until?: string
  via?: string
  summary?: string
  session_id?: string
  item?: { priority?: string; title?: string; why?: string; action?: string; owner?: string; refs?: string[]; sources?: string[] }
}

// Deep link that opens a Hermes desktop thread by session id.
export const hermesSessionUrl = (sid: string) => `hermes://open/${encodeURIComponent(sid)}`
export async function fetchHandled(): Promise<Record<string, HandledEntry>> {
  const res = await fetch(`${BASE}api/action-handled`)
  if (!res.ok) throw new Error(`action-handled -> ${res.status}`)
  const j = (await res.json()) as { handled?: Record<string, HandledEntry> }
  return j.handled || {}
}
export async function postHandled(entry: { fp: string; act: string; at?: string; until?: string }): Promise<void> {
  const res = await fetch(`${BASE}api/action-handled`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(entry),
  })
  if (!res.ok) throw new Error(`action-handled POST -> ${res.status}`)
}

// ---- Alerts (Action Center > Alerts, alerts.py) ----
// Runs of the jobs that used to ping chat. A report clears itself 48 hours after the run, a job
// whose latest run failed stays listed (open) and has an auto-alert- item on the Action Center.
export interface OpsAlert {
  id: string
  job: string
  name: string
  at: string
  kind: 'report' | 'failure'
  body: string
  // md = an agent answer (render as markdown), text = script output (keep the lines)
  fmt: 'md' | 'text'
  acked: string | null
  // false for a report: information that clears itself, no ack and not in the badge
  needs_ack: boolean
  open: boolean
  count: number
  since: string
  expires: string | null
  item_key?: string
}
export interface AlertsData {
  window_hours: number
  alerts: OpsAlert[]
  counts: { unacked: number; failing: number; acked: number; reports: number }
  sources: number
}
// 1:1 agenda cards I already replied to leave the Action Center as small Replied chips.
export interface RepliedCard {
  id: string
  key: string
  person: string
  first: string
  title: string
  replied_at: string | null
}
export const useReplied = createLiveStore(() => fetchApi<{ replied: RepliedCard[] }>('api/action-center/replied'), 30_000)
export async function postReopenReplied(id: string): Promise<{ replied: RepliedCard[] }> {
  const res = await fetch(`${BASE}api/action-center/replied/reopen`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id }),
  })
  if (!res.ok) throw new Error(`replied reopen POST -> ${res.status}`)
  return (await res.json()) as { replied: RepliedCard[] }
}
export const useAlerts = createLiveStore(() => fetchApi<AlertsData>('api/alerts'), 30_000)
export async function postAlertsAck(ids: string[], act: 'ack' | 'unack' = 'ack'): Promise<AlertsData> {
  const res = await fetch(`${BASE}api/alerts/ack`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids, act }),
  })
  if (!res.ok) throw new Error(`alerts ack POST -> ${res.status}`)
  return (await res.json()) as AlertsData
}

// ---- Jira hub (Sprint / Backlog / Changes): live Jira, never bundled ----
// server.py serves these straight from the Atlassian connector (jira_work.py,
// 60s server cache, ?fresh=1 bypasses it). Shared live stores so the sidebar
// badge, the hub tab badges and the pages make one request per endpoint.
export interface ActiveSprint {
  id: number
  name: string
  board_id: number
  start: string
  end: string
  goal?: string
}
export interface JiraItem {
  key: string
  summary: string
  status: string
  status_category: string // new | indeterminate | done
  issuetype: string
  priority: string
  points: number | null
  assignee: string
  assignee_id: string
  parent_key: string
  parent_summary: string
  updated: string
  due: string
  carry: number // closed sprints this issue already sat in
  planned_sprint: { id: number; name: string } | null
  url: string
}
export interface SprintItem extends JiraItem {
  mine: boolean
}
export interface SprintData {
  generated_utc: string
  sprint: ActiveSprint | null
  me: string
  items: SprintItem[]
}
export type BacklogItem = JiraItem
export interface BacklogData {
  generated_utc: string
  active_sprint: ActiveSprint | null
  count: number
  items: BacklogItem[]
}
export interface ChangeRow {
  key: string
  summary: string
  status: string
  requester: string
  change_type: string
  risk: string
  planned_start: string
  planned_end: string
  created: string
  url: string
  portal_url: string
}
export interface ApprovalsData {
  generated_utc: string
  pending: ChangeRow[]
  inflight: ChangeRow[]
}
export interface JiraTransition {
  id: string
  name: string
  to: string
  to_category: string
  allowed: boolean
}

async function jiraGet<T>(path: string, fresh = false): Promise<T> {
  const res = await fetch(`${BASE}${path}${fresh ? `${path.includes('?') ? '&' : '?'}fresh=1` : ''}`, { cache: 'no-cache' })
  const j = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error((j as { error?: string }).error || `${path} -> ${res.status}`)
  return j as T
}
async function jiraPost<T>(path: string, body: Record<string, unknown>): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const j = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error((j as { error?: string }).error || `${path} -> ${res.status}`)
  return j as T
}

export const fetchSprint = (fresh = false) => jiraGet<SprintData>('api/jira/sprint', fresh)
export const fetchBacklog = (fresh = false) => jiraGet<BacklogData>('api/backlog', fresh)
export const fetchApprovals = (fresh = false) => jiraGet<ApprovalsData>('api/change-approvals', fresh)
export const useJiraSprint = createLiveStore(fetchSprint, 5 * 60_000)
export const useBacklog = createLiveStore(fetchBacklog, 5 * 60_000)
export const useApprovals = createLiveStore(fetchApprovals, 5 * 60_000)

// Jira hub > Needs me: active-sprint tickets the nightly close-out could not settle on its own.
// Close it fires the close-out job at once (it writes the closure comment and closes the ticket).
// Keep open is recorded and takes the ticket off the list until the reason changes.
export type NeedsMeDecisionKind = 'close' | 'keep'
export interface NeedsMeDecision {
  decision: NeedsMeDecisionKind
  note: string
  question: string
  at: string
}
export interface NeedsMeItem {
  key: string
  summary: string
  status: string
  url: string
  question: string
  since: string
  days: number | null
  phase: 'needs_me' | 'closing'
  decision: NeedsMeDecision | null
}
export interface NeedsMeData {
  generated_utc: string
  live_ok: boolean
  live_error: string
  count: number
  items: NeedsMeItem[]
}
export const fetchNeedsMe = (fresh = false) => jiraGet<NeedsMeData>('api/jira/needs-me', fresh)
export const useJiraNeedsMe = createLiveStore(fetchNeedsMe, 5 * 60_000)
export const postNeedsMeDecide = (key: string, decision: NeedsMeDecisionKind | 'undo', question: string, note = '') =>
  jiraPost<{ key: string; decision: NeedsMeDecision | null; already: boolean; trigger_error?: string }>('api/jira/needs-me/decide', {
    key,
    decision,
    question,
    note,
  })

export const fetchTransitions = (key: string) =>
  jiraGet<{ key: string; transitions: JiraTransition[] }>(`api/jira/transitions?key=${encodeURIComponent(key)}`)
// Move one backlog issue into the active sprint (confirmed on read-back).
export const postSprintMove = (key: string) => jiraPost<{ key: string; moved_to: { id: number; name: string } }>('api/sprint-move', { key })
// Pull one of my sprint issues back to the backlog (confirmed on read-back).
export const postSprintRemove = (key: string) =>
  jiraPost<{ key: string; removed_from: { id: number; name: string } }>('api/jira/sprint-remove', { key })
// Non-done status change on one of my issues (closing has its own process).
export const postTransition = (key: string, id: string) =>
  jiraPost<{ key: string; status: string; status_category: string; transition: string }>('api/jira/transition', {
    key,
    id,
  })

// ---- Tackle now (starts a chat in the running Hermes desktop app per item) ----
export interface TackleSession {
  title: string
  session: string
  pid: number
  state: 'launching' | 'claimed' | 'running' | 'finished' | 'failed' | 'resolved'
  resolved?: string
  archived?: boolean
  started: string
  log: string
  surface?: 'desktop'
  session_id?: string
  has_context?: boolean
  error?: string
  // Jira key the session works (jira-<KEY> or the item's first ref), last activity across
  // the compression lineage, and live = opening now or running, not archived, active within 72h.
  ticket?: string
  last_active?: string
  live?: boolean
}
export async function fetchTackle(): Promise<Record<string, TackleSession>> {
  const res = await fetch(`${BASE}api/tackle`)
  if (!res.ok) throw new Error(`tackle -> ${res.status}`)
  const j = (await res.json()) as { sessions?: Record<string, TackleSession> }
  return j.sessions || {}
}
export async function postTackle(fp: string, context = '', mode?: 'teams'): Promise<TackleSession> {
  const res = await fetch(`${BASE}api/tackle`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(mode ? { fp, context, mode } : { fp, context }),
  })
  if (!res.ok) {
    const j = await res.json().catch(() => ({}))
    throw new Error((j as { error?: string }).error || `tackle POST -> ${res.status}`)
  }
  return (await res.json()) as TackleSession
}

// Live tackle/discuss sessions (Action Center items and PR discussions share one store).
export const useTackleSessions = createLiveStore(() => fetchTackle(), 10_000)

// the live Hermes session working each Jira ticket, from any surface (Jira hub tackle
// jira-<KEY>, or an Action Center tackle whose first ref is the ticket). The Jira hub session
// wins when both exist, then the most recently active.
export interface TicketSession extends TackleSession {
  fp: string
  from: 'jira' | 'action'
}
export function liveByTicket(sessions: Record<string, TackleSession> | null | undefined): Map<string, TicketSession> {
  const m = new Map<string, TicketSession>()
  for (const [fp, s] of Object.entries(sessions || {})) {
    if (!s.live || !s.ticket) continue
    const cand: TicketSession = { ...s, fp, from: fp.startsWith('jira-') ? 'jira' : 'action' }
    const cur = m.get(s.ticket)
    const newer = (cand.last_active || cand.started) > (cur?.last_active || cur?.started || '')
    if (!cur || (cand.from === 'jira' && cur.from !== 'jira') || (cand.from === cur.from && newer)) m.set(s.ticket, cand)
  }
  return m
}
// Start a desktop chat to discuss one PR that needs me. The server builds the prompt from
// live review data. Session state shows up in the tackle store under pr-repo-<n>.
export async function postReviewDiscuss(repo: string, pr: number, context = ''): Promise<TackleSession> {
  const res = await fetch(`${BASE}api/reviews/discuss`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ repo, pr, context }),
  })
  if (!res.ok) {
    const j = await res.json().catch(() => ({}))
    throw new Error((j as { error?: string }).error || `discuss POST -> ${res.status}`)
  }
  return (await res.json()) as TackleSession
}

// ---- Documentation coverage (Knowledge page, ) ----
// Registry joined with the daily audit, plus my Snooze/Ignore per thing and Tackle sessions
// (store key doc-<id>). Documentation gaps never reach the Action Center. open_count drives
// the Knowledge nav badge: high/medium things on my board that are not snoozed or ignored.
export interface DocGap {
  id: string
  rule: string
  severity: string
  text: string
  first_seen?: string
}
export interface DocHandled {
  act: 'snoozed' | 'ignored'
  at: string
  until?: string
  key?: string | null
}
export interface DocThing {
  id: string
  name: string
  kind: string
  tier: string
  status: string
  raci_domain: string
  owner_a?: string | null
  owner_r?: string | null
  repo: string
  path: string
  confluence_home?: string | null
  home_title?: string | null
  release?: string
  changelog_file?: string | null
  on_board: boolean
  board_note?: string | null
  surfaced: boolean
  key?: string
  priority: string
  gaps: DocGap[]
  closed: { id: string; text: string; closed_utc: string }[]
  handled?: DocHandled | null
  tackle?: TackleSession | null
  open: boolean
}
export interface DocCoverageData {
  audited_utc?: string | null
  last_error?: string | null
  counts: Record<string, number>
  open_count: number
  things: DocThing[]
  internal: { id: string; name: string; gaps: DocGap[] }[]
  duplicates?: DocGap[]
}
export const useDocCoverage = createLiveStore(() => fetchApi<DocCoverageData>('api/doc-coverage'), 60_000)
async function docPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const j = await res.json().catch(() => ({}))
    throw new Error((j as { error?: string }).error || `${path} -> ${res.status}`)
  }
  return (await res.json()) as T
}
export const postDocHandle = (id: string, act: 'snooze' | 'ignore' | 'restore') =>
  docPost<{ id: string; handled: DocHandled | null }>('api/doc-coverage/handle', { id, act })
export const postDocTackle = (id: string, context = '') =>
  docPost<TackleSession & { fp: string }>('api/doc-coverage/tackle', { id, context })

// ---- Link health: weekly reachability check of the Links page catalog ----
// Written by link_health.py (weekly no-agent cron) to state/dashboard/link-health.json.
export type LinkState = 'ok' | 'warn' | 'dead' | 'skipped'
export interface LinkHealthRow {
  name: string
  group: string
  state: LinkState
  reason: string
  code?: number | null
  since?: string
}
export interface LinkHealthData {
  checked_utc: string | null
  total?: number
  checked?: number
  counts: Partial<Record<LinkState, number>>
  links: Record<string, LinkHealthRow>
  dead: (LinkHealthRow & { url: string; edit?: LinkEdit })[]
  /** Swap or Remove PRs opened from the Links page, by old address, until the deploy drops it. */
  edits?: Record<string, LinkEdit>
}
export interface LinkEdit {
  action: 'swap' | 'remove'
  new_url?: string | null
  pr: number
  pr_url: string
  at: string
}
export interface LinkEditResult {
  status: 'pr' | 'alive'
  pr?: number
  pr_url?: string
  message: string
}
export const useLinkHealth = createLiveStore(() => fetchApi<LinkHealthData>('api/links/health'), 300_000)
export const postLinkEdit = (action: 'swap' | 'remove', url: string, newUrl?: string) =>
  docPost<LinkEditResult>('api/links/edit', { action, url, new_url: newUrl })
export const postLinksCheck = () => docPost<LinkHealthData>('api/links/check', {})

// ---- Dark launches: acting automation that ships with its action off ----
// Registry state/dashboard/dark-launches.json, live variable read through gh by dark_launches.py.
export interface DarkLaunch {
  id: string
  title: string
  repo: string
  environment: string
  variable: string
  workflow: string
  status: 'dark' | 'enabled'
  live: 'on' | 'off' | 'unknown'
  dry_run: { state: 'none' | 'running' | 'passed' | 'failed' | 'unknown'; at?: string; url?: string }
  can_dry_run: boolean
  can_enable: boolean
  can_disable: boolean
}
export const useDarkLaunches = createLiveStore(
  () => fetchApi<{ launches: DarkLaunch[]; error: string | null }>('api/dark-launches'),
  30_000,
)
export const postDarkLaunch = (act: 'dry-run' | 'enable' | 'disable', id: string, confirm?: string) =>
  docPost<{ id: string; done: string[]; already?: boolean }>(`api/dark-launches/${act}`, { id, confirm })

// ---- Action Center routing: rules are data in ac-routing.json ----
export type AcRoute = 'action_center' | 'analysis' | 'elsewhere' | 'nowhere'
export type AcScope = 'all' | 'items' | 'candidates'
export interface AcMatch {
  source?: string
  actor?: string
  actor_role?: string
  key?: string
  key_prefix?: string
  ref_prefix?: string
  refs?: string[]
  owner?: string
  text?: string
  fields?: string[]
  sources_any?: string[]
}
export interface AcRule {
  id: string
  match: AcMatch
  route: AcRoute
  where?: string
  reason?: string
  origin: 'seed' | 'click'
  scope?: AcScope
  created?: string
  disabled?: string
  from_item?: string
  hits: number
}
export interface AcAway {
  cid?: string
  key?: string
  source?: string
  actor?: string
  title?: string
  route: AcRoute
  rule: string
  where?: string
  received?: string
  link?: string
}
export interface AcRoutingData {
  rules: AcRule[]
  sources: Record<string, string>
  defaults: Record<string, string>
  people: Record<string, string[]>
  error?: string | null
  report: {
    generated_utc?: string
    considered?: number
    considered_list?: { cid: string; source: string; actor?: string; title: string; received?: string; link?: string; rule: string }[]
    context?: number
    counts?: Record<string, Record<string, number>>
    routed_away?: AcAway[]
    items_routed_away?: AcAway[]
    unregistered?: string[]
    errors?: string[]
  }
}
export interface AcPreview {
  candidate_count: number
  item_count: number
  candidates: { cid: string; source: string; actor: string; title: string }[]
  items: { key: string; title: string }[]
}
export const useAcRouting = createLiveStore(() => fetchApi<AcRoutingData>('api/ac-routing'), 60_000)
export const postAcPreview = (match: AcMatch, route: AcRoute, scope: AcScope) =>
  docPost<AcPreview>('api/ac-routing/preview', { match, route, scope })
export const postAcRule = (body: { match: AcMatch; route: AcRoute; where?: string; reason?: string; scope?: AcScope; from_fp?: string }) =>
  docPost<{ ok: boolean; rule: AcRule; already: boolean }>('api/ac-routing/rule', body)
export const postAcDisable = (id: string, disabled: boolean) => docPost<{ ok: boolean }>('api/ac-routing/disable', { id, disabled })
export const postAcDelete = (id: string) => docPost<{ ok: boolean; already: boolean }>('api/ac-routing/delete', { id })

// Tackle one of my open Jira items (Sprint or Backlog). The server builds the prompt from the
// live Jira hub row and refuses items that are not mine. Store key: jira-<KEY>.
export async function postJiraTackle(key: string, context = ''): Promise<TackleSession> {
  const res = await fetch(`${BASE}api/jira/tackle`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key, context }),
  })
  if (!res.ok) {
    const j = await res.json().catch(() => ({}))
    throw new Error((j as { error?: string }).error || `jira tackle POST -> ${res.status}`)
  }
  return (await res.json()) as TackleSession
}

// ---- 1:1 Board (live, served by server.py from one_on_ones.py) ----
// Topics for my direct reports, parsed from the inbound Teams/mail monitor
// feeds plus my curated agenda and the weekly assessment. No LLM call.
export type TopicState = 'open' | 'discussed' | 'not_needed'
export interface TopicMsg {
  id: string
  at: string
  who: string
  text: string
}
export interface Topic {
  fp: string
  person: string
  source: 'agenda' | 'action' | 'me' | 'review' | 'teams' | 'mail'
  kind: string
  title: string
  detail?: string
  context?: string | null
  flagged?: boolean
  priority?: string | null
  refs: string[]
  hot?: boolean
  first_at?: string | null
  last_at?: string | null
  messages: TopicMsg[]
  link?: string | null
  state: TopicState
  state_at?: string | null
  note?: string | null
  reopened?: boolean
  related?: string[]
  feed_last_at?: string | null
  link_source?: 'teams' | 'mail'
  my_action?: string
  ac_fp?: string
  action_done_at?: string | null
  told_at?: string | null
}
export interface Meeting {
  subject: string
  start: string
  end: string | null
  link: string | null
}
export interface Report {
  name: string
  first: string
  title: string
  email: string
  group?: 'report' | 'partner'
  meeting: Meeting | null
  next_1on1?: Meeting | null
  schedule_needed?: boolean
  last_contact: string | null
  counts: { open: number; discussed: number; not_needed: number; new: number }
  topics: Topic[]
}
export interface OneOnOnes {
  generated_utc: string
  people: Report[]
  roster?: { stale: boolean; as_of: string | null; names: string[]; missing: string[]; pull_ok: boolean }
  sources: {
    teams_updated?: string
    mail_updated?: string
    assessment_utc?: string
    action_center_utc?: string
    agenda_items: number
    calendar_ok: boolean
    upcoming_ok?: boolean
    one_on_one_days?: number
  }
}
export interface BusyBlock {
  start: string
  end: string
  status: string
}
export interface Availability {
  person: string
  first: string
  email: string
  subject: string
  next_1on1: Meeting | null
  tz: string
  minutes: number
  window: { start: string; end: string }
  me: { busy: BusyBlock[]; error: string | null }
  them: { busy: BusyBlock[]; error: string | null }
  windows: { date: string; start: string; end: string }[]
  suggestions: { start: string; end: string }[]
}
export interface ScheduleResult {
  ok: boolean
  id: string
  subject: string
  start: string
  end: string
  attendee: string | null
  join_url: string | null
  web_link: string | null
  agenda_items: number
  transcription: {
    applied: { allowTranscription?: boolean; recordAutomatically?: boolean } | null
    error: string | null
  }
}

async function apiJson<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(
    `${BASE}${path}`,
    body === undefined
      ? { cache: 'no-cache' }
      : {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        },
  )
  if (!res.ok) {
    const j = await res.json().catch(() => ({}))
    throw new Error((j as { error?: string }).error || `${path} -> ${res.status}`)
  }
  return (await res.json()) as T
}
export const fetchOneOnOnes = () => apiJson<OneOnOnes>('api/one-on-ones')
export const postTopicState = (fp: string, state: TopicState, note?: string) =>
  apiJson<{ fp: string }>('api/one-on-ones/status', { fp, state, note })
export const postTopicAdd = (person: string, title: string, detail = '') =>
  apiJson<{ fp: string }>('api/one-on-ones/topic', { person, title, detail })
// Approve button on an automation card. cells carries my edits, when any.
export const postAutomationApprove = (key: string, fp: string, cells?: Record<string, string>, kind?: string) =>
  apiJson<{ ok: boolean; version?: number; edited?: boolean; summary?: string }>('api/automation/approve', { key, fp, cells, kind })
export const postTopicRemove = (fp: string) => apiJson<{ removed: boolean }>('api/one-on-ones/topic', { fp, remove: true })
export const fetchAvailability = (person: string, minutes: number) =>
  apiJson<Availability>(`api/one-on-ones/availability?person=${encodeURIComponent(person)}&minutes=${minutes}`)
export const postSchedule = (body: { person: string; start: string; minutes: number; agenda: string[]; auto_transcribe: boolean }) =>
  apiJson<ScheduleResult>('api/one-on-ones/schedule', body)

// Relative time for "last updated" style labels.
export function relTime(iso: string | number | null | undefined): string {
  if (iso === null || iso === undefined || iso === '') return 'never'
  const t = typeof iso === 'number' ? iso : new Date(iso).getTime()
  if (Number.isNaN(t)) return 'unknown'
  const m = (Date.now() - t) / 60000
  if (m < 1) return 'just now'
  if (m < 60) return `${Math.round(m)}m ago`
  if (m < 1440) return `${Math.round(m / 60)}h ago`
  return `${Math.round(m / 1440)}d ago`
}

// One shared poller for the 1:1 Board (sidebar badge + page).
export const useOneOnOnes = createLiveStore(fetchOneOnOnes, 30_000)

// Yearly performance reviews (Team Performance > Yearly review). Durable,
// year-keyed records on the server. Sections come from the review template
// (state/team-performance/review-template.json, swapped when HR sends the
// official format). Drafts and per-section rewrites run as server-side jobs
// over the full-year evidence (Jira, Teams, mail, meetings, notes, ledgers).
export type ReviewSection = string
export interface ReviewTemplateSection {
  key: string
  title: string
  hint: string
  rows: number
  export: boolean
  private?: boolean
  // Competency format (HR form): rated sections carry their own rating and weight.
  rated?: boolean
  weight?: number | null
  definition?: string | null
}
export interface ReviewScore {
  value: number | null
  rated: number
  total: number
  weight_rated: number
  weight_total: number
  rating: string
  complete: boolean
}
export interface ReviewSectionMeta {
  source: 'draft' | 'refine' | 'manual' | 'undo'
  at: string
  job?: string
  steered?: boolean
}
export interface ReviewAnalysis {
  overview: string
  by_period: { period: string; read: string }[]
  themes: { title: string; read: string; sources: string[] }[]
  on_me: string[]
  confidence: string
  gaps: string[]
  generated_utc?: string
}
export interface ReviewSource {
  key: string
  label: string
  count: number
  detail: string
}
export interface YearlyReview {
  rating: string
  rating_source: '' | 'draft' | 'manager' | 'computed'
  rating_suggestion: { value: string; rationale: string; at?: string } | null
  section_ratings: Record<string, string>
  section_rating_meta: Record<string, { source: '' | 'draft' | 'manager'; at: string; suggested?: string }>
  score: ReviewScore | null
  status: 'draft' | 'final'
  sections: Record<string, string>
  evidence: Record<string, string[]>
  meta: Record<string, ReviewSectionMeta>
  versions: Record<string, { at: string; source: string; chars: number }[]>
  guidance: Record<string, string>
  analysis: ReviewAnalysis | null
  draft: {
    generated_utc?: string | null
    refined_utc?: string | null
    evidence_utc?: string | null
    datapoints?: number | null
    sources?: ReviewSource[] | null
    warnings?: string[]
    job?: string
  } | null
  snapshots: { at: string; reason: string }[]
  created_utc: string | null
  updated_utc: string | null
  finalized_utc: string | null
  events: { at: string; event: string }[]
}
export type ReviewJobState = 'starting' | 'queued' | 'evidence' | 'drafting' | 'drafted' | 'done' | 'failed'
export interface ReviewJob {
  id: string
  year: string
  person: string
  mode: 'full' | 'refine' | 'evidence'
  sections: string[]
  state: ReviewJobState
  stage: string
  steps: string[]
  created_utc: string | null
  started_utc: string | null
  finished_utc: string | null
  error: string | null
  warnings: string[]
  applied_utc: string | null
}
export interface YearlyReviews {
  schema: number
  updated_utc: string | null
  reviews: Record<string, Record<string, YearlyReview>>
  people: string[]
  ratings: Record<string, string>
  scale?: Record<string, number>
  sections: Record<string, string>
  template: { name: string; version: number; sections: ReviewTemplateSection[] }
  jobs: ReviewJob[]
}
export interface ReviewMetrics {
  year: string
  person: string
  first: string
  title: string
  role: string
  period: { start: string; end: string; partial: boolean }
  generated_utc: string
  jira: {
    touched: number
    closed: number
    opened: number
    open_now: number
    high_closed: number
    high_touched: number
    high_open: number
    median_days_new_work: number | null
    median_days_all: number | null
    aged_cleared: number
    open_over_90d: number
    oldest_open_days: number
    points_closed: number
    reported_by_them: number
    closed_by_type: Record<string, number>
    quarters: Record<string, { closed: number; high_closed: number; points: number }>
    top_epics: { epic: string; closed: number; open: number }[]
  }
  comms: {
    teams_1on1: number
    teams_1on1_them: number
    group_by_them: number
    mail_from: number
    mail_to: number
    meetings: number
    one_on_ones: number
    recurring: { subject: string; count: number }[]
    transcripts: number
  }
  series: { month: string; closed: number; opened: number; teams: number; mail: number; meetings: number; ledger: number }[]
  sources: ReviewSource[]
  datapoints: number
  warnings: string[]
}
export const fetchYearlyReviews = () => apiJson<YearlyReviews>('api/yearly-reviews')
export const postYearlyReview = (body: {
  year: string
  person: string
  op?: 'edit' | 'guidance' | 'reset' | 'restore' | 'undo'
  sections?: Record<string, string>
  rating?: string
  section_ratings?: Record<string, string>
  status?: 'draft' | 'final'
  guidance?: Record<string, string>
  section?: string
}) => apiJson<{ review: YearlyReview }>('api/yearly-reviews', body)
export const postReviewDraft = (body: {
  year: string
  person: string
  mode: 'full' | 'refine' | 'evidence'
  sections?: string[]
  guidance?: Record<string, string>
}) => apiJson<{ job: ReviewJob }>('api/yearly-reviews/draft', body)
export const fetchReviewJobs = () => apiJson<{ jobs: ReviewJob[] }>('api/yearly-reviews/jobs')
export const fetchReviewEvidence = (year: string, person: string) =>
  apiJson<{ metrics: ReviewMetrics | null }>(
    `api/yearly-reviews/evidence?year=${encodeURIComponent(year)}&person=${encodeURIComponent(person)}`,
  )
export const yearlyExportUrl = (year: string, person: string) =>
  `${BASE}api/yearly-reviews/export?year=${encodeURIComponent(year)}&person=${encodeURIComponent(person)}`
export const useYearlyReviews = createLiveStore(fetchYearlyReviews, 60_000)
export const useReviewJobs = createLiveStore(fetchReviewJobs, 4_000)

// ---- Global search (served by server.py, never bundled) ----
export interface SearchHit {
  kind: 'action' | 'draft' | 'plan' | 'one-on-one' | 'file' | 'session'
  title: string
  snippet: string
  score: number
  route?: string
  fp?: string
  status?: string
  session_id?: string
  archived?: boolean
  at?: string
  path?: string
  group?: string
  person?: string
  matches?: number
  lines?: number
  source?: string
}
export interface SearchResult {
  q: string
  terms: string[]
  total: number
  groups: Partial<Record<SearchHit['kind'], SearchHit[]>>
  errors?: Record<string, string>
}
export interface JiraHit {
  key: string
  summary: string
  status: string
  type: string
  assignee: string
  updated: string
  url: string
}
export async function fetchSearch(q: string, signal?: AbortSignal): Promise<SearchResult> {
  const res = await fetch(`${BASE}api/search?q=${encodeURIComponent(q)}`, { signal })
  if (!res.ok) throw new Error(`search -> ${res.status}`)
  return (await res.json()) as SearchResult
}
export async function fetchJiraSearch(q: string, signal?: AbortSignal): Promise<JiraHit[]> {
  const res = await fetch(`${BASE}api/search?scope=jira&q=${encodeURIComponent(q)}`, { signal })
  const j = (await res.json()) as { items?: JiraHit[]; error?: string }
  if (!res.ok) throw new Error(j.error || `jira search -> ${res.status}`)
  return j.items || []
}
export async function fetchFileText(path: string): Promise<string> {
  const res = await fetch(`${BASE}api/file?path=${encodeURIComponent(path)}`)
  const j = (await res.json()) as { text?: string; error?: string }
  if (!res.ok) throw new Error(j.error || `file -> ${res.status}`)
  return j.text || ''
}

// ---- Terraform plan reviews (private platform-tfplan-gate queue) ----
export interface TfAssessment {
  summary: string
  changes: string[]
  risk: { level: 'low' | 'medium' | 'high'; why: string }
  recommendation: { action: 'approve' | 'request changes' | 'reject'; why: string }
  checked_at: string
  head_sha?: string
}
/** what changed in the newly held files between my approved head and the new head. */
export interface TfHeldDelta {
  base_sha: string
  head_sha: string
  compare_url: string
  files: { path: string; status?: string; additions: number; deletions: number; url: string }[]
  unchanged: string[]
  unknown: string[]
  error?: string
}

export interface TfReviewItem {
  key: string
  pr: number | null
  title: string
  author: string
  url: string
  head_sha: string
  run_ids: number[]
  held_reasons: string[]
  files: string[]
  first_seen: string
  assessment: TfAssessment | null
  status: string
}
export interface TfDecision {
  ts: string
  pr: number | null
  run: number
  workflow: string
  decision: string
  reasons: string[]
  files_changed: number
}
export interface TfReviews {
  generated_utc: string
  queue_updated: string | null
  pending: TfReviewItem[]
  decisions: TfDecision[]
}
export const fetchTfReviews = () => apiJson<TfReviews>('api/tf-reviews')
export const postTfDecision = (pr: number, act: 'approve' | 'reject') =>
  apiJson<{ pr: number; status: string; runs: number[] }>(`api/tf-reviews/${act}`, { pr })
export const useTfReviews = createLiveStore(fetchTfReviews, 60_000)

// ---- platform reviews (private; platform-pr-review queue + tfplan holds) ----
export interface OlyPlan {
  ran?: boolean
  run_url?: string
  conclusion?: string | null
  add?: number
  change?: number
  destroy?: number
  replace?: number
  import?: number
  destroyed?: string[]
  replaced?: string[]
  note?: string
  summary?: string
}
export interface OlyBreakdown {
  summary: string
  changes: (string | { file: string; behaviour: string })[]
  plan: OlyPlan | string | null
  risk: { level: 'low' | 'medium' | 'high'; why: string }
  rules: (string | { rule: string; reason?: string; where?: string })[]
  recommendation: { action: 'approve' | 'request changes' | 'reject'; why: string }
  checked_at?: string
}
// (pr_deps.py): what one PR waits on. Only unmet parents are listed. first = do these first,
// chain = every unmet PR ahead of this one in order, lines = the plain "Waiting on #N: ..." text.
export interface DepWaiting {
  pr: number
  title: string
  url: string
  kind: 'merged' | 'merged_applied' | 'owner_applied'
  kind_text: string
  stage: 'open' | 'apply' | 'owner'
  // Short name of what a merged parent still owes ('main apply', 'Owner apply'), '' while it is open.
  step?: string
  merged?: boolean
  need: string
  sources: ('body' | 'branch' | 'destroys')[]
  text: string
}
export interface DepView {
  waiting: DepWaiting[]
  chain: number[]
  first: number[]
  lines: string[]
  notes: string[]
  first_line: string
  // What a merged PR in the chain still owes, keyed by PR number ("347": "Owner apply").
  steps?: Record<string, string>
}
export interface OlyNeed extends CardWatch {
  key: string
  // Server truth (10/13): needs_me = the action would go through now, in_flight = locked with a reason.
  // waiting_dep = the PR waits on another PR, not counted, only Approve anyway.
  // waiting_threads = I approved, it waits on other people's open review conversations.
  phase?: 'needs_me' | 'in_flight' | 'waiting_dep' | 'waiting_threads'
  deps?: DepView
  threads_wait?: OlyThreadWait | null
  // the approval posted but the merge did not queue. The card stays here with the reason.
  merge_error?: string[] | null
  // live-actions 1.9: the merge was accepted for later (merge queue or auto-merge). pending = in flight
  // with no actions until a direct read shows the end state, ejected = it left the queue and the actions are back.
  merge_pending?: { kind: 'queued' | 'auto'; state: 'pending' | 'ejected'; text: string; position?: number | null } | null
  blocked?: string | null
  pr: number | null
  title: string
  author: string
  url: string
  head_sha: string
  sources: ('review' | 'tfplan')[]
  since: string
  breakdown: OlyBreakdown | null
  plan: OlyPlan | null
  tfplan: {
    key: string
    held_reasons: string[]
    files: string[]
    run_ids: number[]
    head_sha: string
    working?: string | null
    new_held?: string[] | null
    held_delta?: TfHeldDelta | null
  } | null
  brief?: ApprovalBrief
  // the name to type on this card so the post-merge privileged apply of the same plan is covered.
  confirm_needed?: string | null
  // what Approve does on this engineer PR right now. Absent = it merges as usual.
  window?: OlyWindow | null
}
// an open review conversation someone else started (review_threads.read).
export interface OlyThread {
  id: string
  starter: string
  automated: boolean
  path: string | null
  line: number | null
  outdated: boolean
  url: string | null
  last_author: string
  last_text: string
  replies: number
}
export interface OlyThreadWait {
  pr: number
  head_sha: string
  at: string
  checked_at?: string
  threads: OlyThread[]
  last_error?: string
}
// maintenance window view (maintenance_hold.window_view): plain prose plus the facts it is built from.
export interface OlyWindow {
  class?: 'not_ccc' | 'ccc' | 'both'
  class_label?: string
  in_window?: boolean
  opens_utc?: string | null
  opens_words?: string | null
  phrase?: string
  stale?: boolean
  unknown?: boolean
  held_on_approve?: boolean
  reasons?: string[]
  brief: { down: string; when: string; override: string } | null
}
export interface OlyHeld {
  pr: number
  title: string
  author: string
  url: string
  head_sha: string
  held_at: string
  approved_by?: string
  hits: { kind: string; system: string | null; reason: string; where?: string }[]
  last_check?: string | null
  last_check_at?: string | null
  comment_posted_at?: string | null
  // held = waiting for its window, in_flight = a new push drops the hold, gone = closed or merged.
  phase: 'held' | 'in_flight' | 'gone'
  note?: string | null
  window: OlyWindow
}
export interface OlyProgress extends CardWatch {
  pr: number
  title: string
  author: string
  url: string
  head_sha: string
  status: string
  open_findings?: number
  last_action?: string
  last_action_at?: string
  rounds?: number
}
export interface OlyShipped {
  pr: number
  title: string
  author: string
  url: string
  status: string
  when: string
  merged_at?: string | null
  approved_by?: string
}
export interface PrivResource {
  address: string
  action: string
  type: string
  root?: string | null
}
export interface PrivEntra {
  app: string | null
  permission: string
  kind: 'application' | 'delegated' | 'unknown'
  change: string
  risk?: 'low' | 'medium' | 'high'
  description?: string | null
  source?: string
}
export interface PrivAssessment {
  summary: string
  changes: string[]
  risk: { level: 'low' | 'medium' | 'high'; why: string }
  recommendation: { action: 'approve' | 'reject'; why: string }
  permissions?: { app: string; permission: string; kind: 'application' | 'delegated'; reaches: string }[]
  removed?: { address: string; data_loss: boolean; note?: string }[]
  data_loss?: 'yes' | 'no' | 'possible'
  governance_changes?: { kind: string; target: string; change: string }[]
  checked_at?: string
}
export interface PrivItem extends CardWatch {
  key: string
  // Server truth (10/13): needs_me = the action would go through now, in_flight = locked with a reason.
  // waiting_dep = its PR waits on another PR, not counted, only Approve anyway.
  phase?: 'needs_me' | 'in_flight' | 'waiting_dep'
  deps?: DepView
  blocked?: string | null
  environment: 'governance' | 'entra-privileged' | 'destroy' | 'app_e-build' | 'app_e-release' | 'avd-image'
  env_label: string
  workflow: string
  workflow_name?: string
  run_id: number
  run_attempt?: number
  run_url: string
  event: string
  head_branch: string
  head_sha: string
  actor?: string
  pr: { number: number; title: string; url: string; author: string; merged_at?: string | null } | null
  unexpected: boolean
  held_reasons: string[]
  plan_source: string | null
  plan: {
    add: number
    change: number
    destroy: number
    replace?: number
    import?: number
    resources: PrivResource[]
    roots: { name: string | null; summary: string }[]
    errors: string[]
  } | null
  entra: PrivEntra[]
  data_loss: { address: string; type: string; action: string }[]
  governance: { class: string; address: string; action: string; type: string }[]
  // app_e release gates carry what ships instead of a plan (null pending = not read yet).
  release?: {
    pending?: string | null
    title?: string | null
    // avd-image: which job waits and this run's window entry on main (window_read false = read failed).
    kind?: string
    job?: string | null
    stage?: number | null
    stage_text?: string | null
    window?: { run_id: string; date?: string; engineer?: string; summary?: string } | null
    window_read?: boolean
  } | null
  auto_risk?: { floor: 'low' | 'medium' | 'high'; reasons: string[] }
  confirm_name: string
  typed_confirm: boolean
  since: string
  assessment: PrivAssessment | null
  status: string
  // status blocked_failed_apply = same plan as a run I approved whose apply failed.
  failed_apply?: {
    fingerprint: string
    key: string
    run_id: number
    run_url: string
    job_url?: string | null
    error?: string | null
    failed_at?: string | null
    pr?: number | null
  } | null
  files?: string[]
  brief?: ApprovalBrief
  decided_at?: string
  decided_by?: string
}
// an Owner-applied platform root (applied as owner_admin_account from a saved plan).
export interface OwnerRoot extends CardWatch {
  key: string
  name: string
  tier: string
  state: 'planning' | 'applying' | 'pending' | 'clean' | 'error' | 'auth'
  main_sha?: string
  planned_at?: string
  pending_since?: string | null
  finished?: string
  started?: string
  stale?: boolean
  error?: string | null
  plan_sha256?: string | null
  counts?: { add: number; change: number; destroy: number; replace: number; import: number } | null
  resources?: { address: string; type: string; action: string }[]
  last_apply?: { at: string; result: string; sha?: string; verified?: boolean }
  // The newest failed apply, kept across re-plans until an apply lands.
  last_apply_error?: { at: string; message: string } | null
  // Server truth (10/13): main moved past this plan, so it is being redone and cannot be applied.
  main_moved?: boolean
  // needs_me = I can act now, in_flight = a plan or apply runs (or main moved), idle = clean.
  phase?: 'needs_me' | 'in_flight' | 'idle'
  // Plain facts for the meta line: the main commit's subject and whether it is still the latest main.
  main_subject?: string
  main_latest?: boolean
  brief?: ApprovalBrief
}
// runbook-root deletes I approved, released from Needs me once the main deploy run stops on its guard.
export type RunbookReleaseState = 'waiting' | 'ready' | 'mismatch' | 'error' | 'releasing' | 'released' | 'failed' | 'done' | 'unknown'
export interface RunbookReleaseRun {
  id: number
  url: string
  event: string
  status: string
  conclusion: string | null
  head_sha: string
  created_at: string
}
export interface RunbookRelease extends CardWatch {
  pr: number
  title: string
  url: string
  tier: string
  approved: string[] | null
  approved_at: string
  state: RunbookReleaseState
  why?: string
  run?: RunbookReleaseRun | null
  extra?: string[]
  missing?: string[]
  errors?: string[]
  destroyed?: string[]
  brief?: ApprovalBrief
  dispatched_at?: string
}
export const postRunbookRelease = (pr: number, run_id: number) =>
  apiJson<{ pr: number; done: string[] }>('api/platform-reviews/release-deletes', { pr, run_id })
// the one Azure sign-in prompt the Owner-root cards share. waiting = the prompt is open,
// replanning = signed in and every root is being re-planned, done or failed = how it ended.
export interface OwnerSignin {
  state: 'waiting' | 'replanning' | 'done' | 'failed' | null
  started?: string | null
  finished?: string | null
  user?: string | null
  error?: string | null
}
export const postOwnerRoot = (act: 'plan' | 'plan-all' | 'apply' | 'signin', body: Record<string, string> = {}) =>
  apiJson<{ done: string[] }>(`api/owner-roots/${act}`, body)
export interface PendingSecret {
  app: string | null
  secret: string | null
  vault: string | null
  tier: string | null
  writer: string | null
  since?: string | null
  age_days?: number | null
  portal_url: string
}
export interface OlyMyPr extends CardWatch {
  pr: number
  title: string
  url: string
  head_sha: string
  branch?: string
  draft?: boolean
  created?: string
  merge_state?: string
  mergeable?: string
  labels: string[]
  ai_result?: string | null
  verdict?: 'blocked' | 'findings' | 'clean' | 'unavailable' | null
  counts: { blocking?: number; high?: number; medium?: number; low?: number }
  blocking: { id: string; title: string; location: string }[]
  // Blocking and high findings of the review on this head (what a triage reply must cover).
  findings?: { id: string; severity: string; title: string; location: string }[]
  red: string[]
  pending: string[]
  // Checks waiting on an environment approval (held terraform plan runs). Not running.
  waiting?: string[]
  model_bump: boolean
  bump_note?: string
  auto_merge?: { status: string; reason: string } | null
  autofix?: OwnAutofix | null
  brief?: ApprovalBrief
  // the review for this head is blocked, my triage names every blocking id and ai-review-override is not on yet.
  can_accept_risk?: boolean
  // set when it waits on another PR (then no Needs me count and only Approve anyway).
  deps?: DepView
  // Why it is not merged yet. Only 'policy' gets a button (Approve and merge).
  // 'direction' = auto-fix gave up, it needs my direction (counted in Needs me, no button).
  hold?: {
    kind: 'policy' | 'problem' | 'waiting' | 'direction'
    summary: string
    autofix?: OwnAutofix
    next?: string
    plan?: string
    // the row waits on terraform-plan, and the server wrote where that approval sits
    // (on Needs me, parked while a session works the PR, or not taken by the gate yet).
    plan_wait?: boolean
    // parked on main's own unapplied change (the action is a Needs me item elsewhere), not running work
    // 'gate' = a draft parked until the gate in its description passes (the lane re-checks it),
    // 'nogate' = a draft with no gate block, so nothing can ever clear it on its own
    parked?: 'main' | 'gate' | 'nogate'
    gate?: { label: string; ok: boolean; detail: string }[]
    gate_met?: number
    plan_parked?: string
    // another hold owns the row, and plan runs also wait (on Needs me, or not taken yet).
    plan_line?: string
    rules?: { rule: string; where?: string; detail?: string; plain: string }[]
    // the name that covers the post-merge apply when the plan deletes or grants Entra types.
    signoff_confirm?: string | null
    // Pipeline v2: the fix session left a decision only I can make, shown as a card.
    decision?: OwnDecision
    // a do-not-merge hold says who placed it, why, and what stands once it is gone.
    label_hold?: OwnLabelHold
  }
}
export interface OwnLabelHold {
  label: string
  by?: string | null
  at?: string | null
  why?: string | null
  why_at?: string | null
  behind: { kind: 'problem' | 'signoff' | 'unknown' | 'covered'; text: string }[]
  clear: boolean
  signoff_after: boolean
}
export interface OwnDecision {
  question: string
  recommend: string
  options: { id: string; label: string; action: 'fix' | 'override' | 'hold'; effect?: string; reply?: string }[]
}
// What the own-PR auto-fix (own_pr_fixer.py) is doing for one of my PRs.
export interface OwnAutofix {
  // waiting_on: it waits for other PRs to merge, then the lane rebases it by itself
  state: 'running' | 'deferred' | 'gave_up' | 'waiting_on'
  text: string
  since?: string
  waits_on?: number[]
  decision?: OwnDecision
  // A live session working the PR (not the lane's own fixer). Locks the row on any hold.
  session?: string
}
// A PR I just merged or approved here. The server hides it until GitHub and the review lanes catch up.
export interface ReviewActed {
  pr: number
  title: string
  outcome: 'merged' | 'approved' | 'closed'
  note: string
  age_s: number
  // A live read shows the merge or close landed (the PR is no longer open).
  confirmed?: boolean
  // what an approval covered ("plan" = only terraform-plan runs, never the merge) and whether
  // the PR still has a Needs me card (its merge sign-off is still open).
  what?: 'plan' | 'pr' | null
  still_needs_me?: boolean
}
// one row per Needs me item, the same items counts.needs_me adds up.
export interface NeedsMeRow {
  kind: 'plan' | 'review' | 'mine' | 'privileged' | 'owner' | 'release'
  pr: number | null
  title: string
  what: string
}
export interface PlatformReviews {
  needs_me_rows?: NeedsMeRow[]
  cron_pulse?: { jobs: CronWatcher[] }
  acted?: ReviewActed[]
  my_prs?: OlyMyPr[]
  my_prs_error?: string | null
  // Epoch seconds of the last My PRs rebuild (the server refreshes it in the background).
  my_prs_refreshed?: number | null
  generated_utc: string
  queue_updated: string | null
  needs_me: OlyNeed[]
  needs_in_flight?: OlyNeed[]
  // plan and review cards whose PR waits on another PR, the hidden runs of superseded
  // heads, and the dependency view of every open PR that waits on something.
  needs_waiting?: OlyNeed[]
  // approved by me, waiting on other people's open review conversations. Not counted.
  needs_threads?: OlyNeed[]
  superseded_runs?: number[]
  deps?: Record<string, DepView>
  in_progress: OlyProgress[]
  held_for_window?: OlyHeld[]
  held_for_window_error?: string | null
  shipped: OlyShipped[]
  privileged: PrivItem[]
  privileged_recent: PrivItem[]
  privileged_health?: { failures?: number; last_error?: string; updated?: string }
  waiting_on_others: {
    secrets: { status: string; updated?: string; last_ok?: string; error?: string | null; items: PendingSecret[] }
  }
  owner_roots?: {
    items: OwnerRoot[]
    running: boolean
    live_main?: string | null
    updated?: string
    error?: string
    signin?: OwnerSignin | null
  }
  runbook_releases?: RunbookRelease[]
  runbook_releases_error?: string | null
  counts: {
    needs_me: number
    prs?: number
    privileged?: number
    apply_failed?: number
    in_progress: number
    held_for_window?: number
    shipped: number
    secrets_pending?: number
    my_prs?: number
    my_prs_need?: number
    runbook_releases?: number
    waiting_on_prs?: number
  }
  gate: { failures: number; updated?: string; last_error?: string; last_audit_date?: string }
  policy: { path: string; version?: number }
}
export const fetchplatformReviews = () => apiJson<PlatformReviews>('api/platform-reviews')
export const postplatformDecision = (
  act: 'approve' | 'request-changes',
  pr: number,
  head_sha: string,
  text?: string,
  ecr_reason?: string,
  anyway?: boolean,
  confirm_name?: string,
) =>
  apiJson<{ pr: number; act: string; done: string[] }>(`api/platform-reviews/${act}`, {
    pr,
    head_sha,
    text,
    ecr_reason,
    anyway,
    confirm_name,
  })
// resolve one open review conversation on an engineer PR as me.
export const postplatformResolveThread = (pr: number, thread_id: string) =>
  apiJson<{ pr: number; done: string[] }>('api/platform-reviews/resolve-thread', { pr, thread_id })
// Merge now (ECR override) on a PR held for the maintenance window, pinned to the held head.
export const postplatformWindowOverride = (pr: number, head_sha: string, reason: string) =>
  apiJson<{ pr: number; done: string[] }>('api/platform-reviews/window-override', { pr, head_sha, reason })
export type TriageVerdict = 'accepted' | 'refuted' | 'fixed' | 'deferred'
export const postplatformTriage = (pr: number, head_sha: string, items: { id: string; verdict: TriageVerdict; reason: string }[]) =>
  apiJson<{ pr: number; done: string[] }>('api/platform-reviews/triage', { pr, head_sha, items })
export const postplatformDecideFix = (pr: number, head_sha: string, option: string) =>
  apiJson<{ pr: number; done: string[]; pending?: boolean; already?: boolean }>('api/platform-reviews/decide-fix', { pr, head_sha, option })
// The approval brief on a card that asks me to decide (approval_brief.py). source model = written
// from the PR, its plan and the review for this head, draft = built from the hold data while the
// written one is pending or after it failed.
export interface ApprovalBrief {
  does: string
  approving: string
  review: string
  source: 'model' | 'draft'
  head: string
  pending: boolean
  generated_at?: string
  error?: string
  // Non-PR cards (card_brief.py): which card kind the paragraphs describe.
  // pr_signoff = my own PR, pr_engineer = an engineer PR escalated to me (pr_landing.py, ).
  kind?: 'owner' | 'priv' | 'release' | 'pr_signoff' | 'pr_engineer'
  // Deterministic, never from the model: an open PR changes the same Terraform root, so applying
  // from main now would undo or pre-empt it. Shown above the paragraphs.
  warning?: string
  wait_for?: { number: number; title: string; url: string }[]
  overlap_status?: 'ok' | 'checking' | 'unknown'
  overlap_checked_at?: string
  // Non-PR cards, written by the model (card_brief.py v2): the real change, where it came from,
  // anything the tables do not show.
  title?: string
  origin?: string
  notes?: string
  // Non-PR cards, deterministic from the data (card_brief.structure). owner 2026-10-20: what is
  // asked, by who, what exactly I grant, why it needs me instead of auto-approving.
  ask?: string
  asked_by?: { label: string; value: string }[]
  grants?: BriefGrant[]
  changes?: { change: string; what: string; count: number; names: string[] }[]
  why_you?: string
  click?: string
  auto?: { fits: boolean; text: string }
  // desktop pool roll delete card (avd_pool.py, ): the host pool read, retiring hosts drained with 0
  // sessions and a new host serving. status unknown means the read failed, never a pass.
  pool?: BriefPool
  // PR cards (pr_landing.py), deterministic: what the merge applies per Terraform root, why it needs me
  // (each rule and finding), the risks and the typed-name gate on Approve and merge.
  landing?: BriefLanding
  why_rows?: BriefWhy[]
  risks?: string[]
  confirm?: { name: string; why: string; required: boolean }
}
export interface BriefPoolHost {
  name: string
  status: string | null
  allow_new_session: boolean | null
  sessions: number | null
  drained?: boolean
  idle?: boolean
}
export interface BriefPool {
  kind: 'avd-pool-roll'
  status: 'ok' | 'attention' | 'checking' | 'unknown'
  text: string
  checked_at?: string | null
  pools: {
    pool: string
    pool_name: string
    retiring: BriefPoolHost[]
    not_registered: string[]
    new: BriefPoolHost[]
    new_ready: number
    ok: boolean
    problems: string[]
  }[]
}
export interface BriefLandingRow {
  root: string
  tier: string
  add: number | null
  change: number | null
  destroy: number | null
  grants: number
  entra: number
  applier: string
  gate: string
  reason: string
  destroys_named: string[]
}
export interface BriefLanding {
  status: 'ok' | 'unknown' | 'no_plan' | 'plan_unread'
  roots: BriefLandingRow[]
  not_applied: BriefLandingRow[]
  empty: number
}
export interface BriefWhy {
  kind: 'rule' | 'finding'
  label: string
  id: string
  severity: string
  where: string
}
export interface BriefGrant {
  change: 'add' | 'remove'
  who: string
  who_kind: string
  principal_id: string
  role: string
  means: string
  on: string[]
  keys: string[]
  move: boolean
}
// A PR card is named by its number, any other card by its id (owner:<root>:<tier>, priv:<key>, release:<pr>).
export const postReviewBrief = (repo: 'platform' | 'team', target: number | string) =>
  apiJson<{ pr: number | string; head: string; queued: boolean; done: string[] }>(
    'api/reviews/brief',
    typeof target === 'number' ? { repo, pr: target } : { repo, card: target },
  )
// anyway: the PR waits on another PR and I chose Approve anyway. The server refuses without it.
// confirm_name: the typed root name that also covers the post-merge apply.
export const postplatformApproveMerge = (pr: number, head_sha: string, anyway?: boolean, confirm_name?: string) =>
  apiJson<{ pr: number; done: string[] }>('api/platform-reviews/approve-merge', { pr, head_sha, anyway, confirm_name })
// removes the hold label from one of my own PRs, pinned to the head on screen.
export const postplatformRemoveHoldLabel = (pr: number, head_sha: string, label: string) =>
  apiJson<{ pr: number; done: string[]; already?: boolean }>('api/platform-reviews/remove-hold-label', { pr, head_sha, label })
// applies ai-review-override to one of my own PRs for the blocking findings my triage covers. Does not merge.
export const postplatformAcceptRisk = (pr: number, head_sha: string) =>
  apiJson<{ pr: number; done: string[]; already?: boolean }>('api/platform-reviews/accept-risk', { pr, head_sha })
export const postPrivDecision = (act: 'approve' | 'reject' | 'retry', key: string, head_sha: string, confirm?: string, anyway?: boolean) =>
  apiJson<{ key: string; status: string; run: number; environment: string }>(`api/platform-reviews/deployment/${act}`, {
    key,
    head_sha,
    confirm,
    anyway,
  })
export const useplatformReviews = createLiveStore(fetchplatformReviews, 60_000)

// ---- Cron pulse: which Hermes cron job owns a card, next run, Run now ----
export interface CronTick {
  at: string | null
  kind: 'ran' | 'no_change' | 'failed'
}
export interface CronWatcher {
  id: string | null
  name: string
  cadence: string
  enabled?: boolean
  next_run_at?: string | null
  last_run_at?: string | null
  last_status?: string | null
  monitor_gated?: boolean
  last_tick?: CronTick | null
  // The last scheduled tick was a monitor no-change, so no agent ran.
  silent_no_change?: boolean
  running: boolean
  queued: boolean
  running_since?: string | null
  request_error?: string | null
  // true = the Ops Center server refreshes this card itself, no cron job and no Run now
  server?: boolean
  also?: { id: string; name: string }[]
}
// Spread into every review card by the server.
export interface CardWatch {
  watcher?: CronWatcher | null
  unwatched?: boolean
  paused_job?: string | null
}
export interface CronPulse {
  generated_utc?: string
  jobs: CronWatcher[]
}
export const fetchCronPulse = (fresh?: boolean) => apiJson<CronPulse>(fresh ? 'api/cron-pulse?fresh=1' : 'api/cron-pulse')
export const postCronRun = (id: string, note?: string) =>
  apiJson<{ started: boolean; already: boolean; with_note?: boolean; job: CronWatcher }>(`api/cron-pulse/${id}/run`, { note: note || '' })
export const useCronPulse = createLiveStore(fetchCronPulse, 20_000)

// ---- team reviews (private; live GitHub + the team PR review lane's escalations) ----
export interface AresChecks {
  total: number
  red: string[]
  pending: string[]
}
export interface AresPr extends CardWatch {
  // Server truth: the lane re-checks this PR (for example new commits after an escalation).
  working?: boolean
  pr: number
  title: string
  url: string
  author: string
  mine: boolean
  head_sha: string
  branch?: string
  draft: boolean
  merge_state?: string
  mergeable?: string
  review?: string | null
  checks: AresChecks
  created?: string
  updated?: string
  // escalated = engineer PR the review lane escalated (Approve as me)
  // signoff = my PR held only by a policy rule (Approve and merge)
  // direction = my PR auto-fix gave up on (no button)
  // ready_to_merge = my green PR while the own-PR lane is not running (Merge)
  kind?: 'escalated' | 'signoff' | 'direction' | 'ready_to_merge'
  why?: string
  rules?: string[]
  autofix?: OwnAutofix | null
  recommendation?: string
  state?: string
  // live-actions 1.14: the pr-reviews board was unreadable, so whether the lane escalated this PR is
  // unknown. The row stays on Needs me and the approve handler re-verifies the board at click time.
  unknown?: boolean
  // Pipeline v2: a decision only I can make, shown as a card with one button per option.
  decision?: OwnDecision
  brief?: ApprovalBrief
}
export interface AresShipped {
  pr: number
  title: string
  url: string
  author: string
  merged?: string
  sha?: string
}
export interface AresReviews {
  cron_pulse?: { jobs: CronWatcher[] }
  acted?: ReviewActed[]
  generated_utc: string | null
  repo: string
  needs_me: AresPr[]
  in_progress: AresPr[]
  shipped: AresShipped[]
  counts: { needs_me: number; in_progress: number; shipped: number }
  error?: string
  lane_error?: string | null
  own_lane_error?: string | null
}
export const fetchAresReviews = (fresh?: boolean) => apiJson<AresReviews>(fresh ? 'api/team_prefix-reviews?fresh=1' : 'api/team_prefix-reviews')
export const postAresReview = (act: 'merge' | 'approve', pr: number, head_sha: string, unverified?: boolean) =>
  apiJson<{ pr: number; done: string[] }>(`api/team_prefix-reviews/${act}`, unverified ? { pr, head_sha, unverified: true } : { pr, head_sha })
export const postAresDecideFix = (pr: number, head_sha: string, option: string) =>
  apiJson<{ pr: number; done: string[]; pending?: boolean; already?: boolean }>('api/team_prefix-reviews/decide-fix', { pr, head_sha, option })
export const useAresReviews = createLiveStore(fetchAresReviews, 60_000)

// Open PRs in my other repos (outside the platform and team lanes) that need me. Server: repo_reviews.py.
export interface RepoPr extends CardWatch {
  repo: string
  slug: string
  pr: number
  title: string
  url: string
  author: string
  mine: boolean
  head_sha: string
  draft: boolean
  updated: string | null
  kind?: 'checks' | 'review' | 'stale' | 'conflict'
  // Core lane owner mode: place in the core owner's version-order queue.
  owner_queue?: { version: string; place: number; of: number; blocked_by: number[] }
  why?: string
  state?: string
  auto_merge: boolean
  checks: { total: number; red: number; pending: number }
  failing: { name: string; url: string; files: string[] }[]
  running: string[]
  // what the sync PR auto-fix lane is doing for this head (github_user/ops_center_repo only).
  autofix?: { state: string; since?: string; text: string } | null
  working?: boolean
}
// an open issue I opened or am assigned, with who moves next.
export interface RepoIssue {
  repo: string
  slug: string
  issue: number
  title: string
  url: string
  author: string
  comments: number
  last_by: string
  last_at: string
  updated: string | null
  kind?: 'replied' | 'quiet'
  why?: string
  excerpt?: string
  state?: string
}
export interface RepoReviewRepo {
  repo: string
  slug: string
  error: string | null
  needs_me: RepoPr[]
  in_progress: RepoPr[]
  acted: ReviewActed[]
  issues_need?: RepoIssue[]
  issues_waiting?: RepoIssue[]
  issues_error?: string | null
  // One Reviews tab per repo, like platform and team.
  label?: string
  shipped?: RepoShipped[]
  lane?: { name: string | null; updated: string | null; error: string | null }
  counts?: { needs_me: number; in_progress: number; shipped: number }
  cron_pulse?: { jobs: CronWatcher[] }
}
export interface RepoShipped {
  pr: number
  title: string
  url: string
  author: string
  merged: string | null
  sha: string
}
export interface RepoReviews {
  generated_utc: string
  repos: RepoReviewRepo[]
  // needs_me and in_progress include the issue rows.
  counts: { needs_me: number; in_progress: number; issues_need?: number }
}
export const fetchRepoReviews = (fresh?: boolean) => apiJson<RepoReviews>(fresh ? 'api/repo-reviews?fresh=1' : 'api/repo-reviews')
export const postRepoRerun = (repo: string, pr: number, head_sha: string) =>
  apiJson<{ pr: number; done: string[] }>('api/repo-reviews/rerun', { repo, pr, head_sha })
export const useRepoReviews = createLiveStore(fetchRepoReviews, 60_000)

// Server-side Action Center handled state, for badges rendered off the Action Center page
// (the page itself merges it into localStorage on mount). Server is the authority.
export const useHandledServer = createLiveStore(fetchHandled, 30_000)

// Enterprise fallback watch: Hermes calls billed to Enterprise while Team had headroom.
export interface FallbackSession {
  platform: string | null
  calls: number
  est_usd: number
}
export interface FallbackIncident {
  id: string
  opened_utc: string
  last_call_utc: string
  calls: number
  est_usd: number
  sessions: Record<string, FallbackSession>
  team_session_pct: number | null
  team_weekly_pct: number | null
  closed_utc?: string
}
export interface FallbackData {
  checked_utc: string | null
  team: { session_pct: number | null; weekly_pct: number | null; headroom: boolean | null; error: string | null } | null
  active: FallbackIncident | null
  history: FallbackIncident[]
  stale_host?: { pid: number; started_utc: string; patched_utc: string } | null
}
export const fetchLlmFallback = (fresh = false) => jiraGet<FallbackData>('api/llm-fallback', fresh)
export const useLlmFallback = createLiveStore(fetchLlmFallback, 60_000)

// shared automation Edge (CDP 9333). alert is set when it has been left
// visible past 15 minutes or down past 2 minutes. hide returns it to headless.
export interface BrowserStatus {
  mode: 'headless' | 'visible' | 'down' | 'unknown'
  since_utc: string | null
  pages: number
  agent_loaded: boolean
  alert: 'visible' | 'down' | null
  error?: string
}
export const fetchBrowserStatus = (fresh = false) => jiraGet<BrowserStatus>('api/browser-status', fresh)
export const useBrowserStatus = createLiveStore(fetchBrowserStatus, 60_000)
export const postBrowserHide = () => jiraPost<BrowserStatus>('api/browser/hide', {})

// Idle-aware Hermes restart (hermes_engine.py). alert: pending (queued, waits for idle), failed
// (last restart did not finish), stale (plugins or config changed after the engine started).
export interface HermesBusy {
  kind: 'session' | 'subagent' | 'cron' | 'process' | 'gateway' | 'input' | 'unknown'
  label: string
  id?: string
  source?: string
}
export interface HermesRestartStatus {
  alert: 'pending' | 'failed' | 'stale' | null
  safe: boolean
  busy: HermesBusy[]
  quiet_s?: number | null
  quiet_needed_s?: number
  pending?: { mode: 'now' | 'idle'; reason: string; by: string; requested_at: string } | null
  running?: {
    since: string
    reason?: string
    phase?: string
    label?: string
    updated?: string
    steps?: { step: string; ok: boolean; why?: string | null }[]
  } | null
  dashboard?: { started?: string | null; pid?: number | null }
  gateway?: { started?: string | null; pid?: number | null }
  last?: { at: string; ok: boolean; seconds: number; reason: string; steps: { step: string; ok: boolean; why?: string | null }[] } | null
  error?: string
}
export const fetchHermesRestart = (fresh = false) => jiraGet<HermesRestartStatus>('api/hermes-restart', fresh)
export const useHermesRestart = createLiveStore(fetchHermesRestart, 30_000)
export const postHermesRestart = (action: 'now' | 'idle' | 'cancel') => jiraPost<HermesRestartStatus>('api/hermes-restart', { action })

// Debt and improvements page: every TD (engineering-state/technical-debt.md) and IMP
// (state/improvement-backlog.md) entry, parsed live by eng_backlog.py. The markdown files stay
// the source of truth: decide rewrites that entry's Status line in place.
export type EngBucket = 'decide' | 'todo' | 'parked' | 'done'
export interface EngItem {
  uid: string
  id: string
  kind: 'TD' | 'IMP'
  title: string
  line: number
  status: string
  outcome: string
  bucket: EngBucket
  severity: string
  goals: string[]
  effort: string
  owner: string
  date: string
  body: string
  snoozed: { act: string; at: string; until: string } | null
}
export interface EngBacklogData {
  generated_utc: string
  counts: Record<string, number>
  items: EngItem[]
}
export type EngAct = 'approve' | 'park' | 'decline' | 'reopen' | 'accept' | 'resolve'
// Sidebar counts in one small payload (server applies each page's filter, see server.py _badges).
export interface Badges {
  action_open: string[]
  debt: number
  // Proposals waiting on my approval plus open documentation gaps.
  knowledge: number
  // Proposal fps still staged for my approval (the client drops ones I just decided).
  knowledge_pending?: string[]
  knowledge_docs?: number
  links?: number
  // Platform problems for the Infrastructure badge (infra.badge_problems).
  infra?: { count: number; items: string[] }
  // Builds page: runs in flight and runs waiting on an environment approval.
  builds?: { running: number; waiting: number }
  // Alerts tab: job runs I have not acknowledged yet (alerts.py).
  alerts?: number
  // Core consumption page: approvals I can act on now (consumption.json, no gh call).
  core?: number
  // The single problem list that builds, scheduled jobs, CI, spend and core read (problems.py).
  problems?: Problems
}
export const useBadges = createLiveStore(() => fetchApi<Badges>('api/badges'), 30_000)
export const useEngBacklog = createLiveStore(() => fetchApi<EngBacklogData>('api/eng-backlog'), 60_000)

// ---- Plans: project trackers and the SBAR plan library in state/plans, read live ----
// Messages are never tracked here (they go straight to Teams, Outlook or the chat).
export type PlanType = 'tracker' | 'plan' | 'brief' | 'record' | 'doc'
export interface PlanTicket {
  status: string
  done: boolean
  // Discovery intake (person turns it into the work ticket). Missing on an old cached read.
  intake?: boolean
  url: string
}
export interface PlanItem {
  id: string
  name: string
  path: string
  section: 'projects' | 'library'
  project: string
  archived: boolean
  type: PlanType
  type_label: string
  title: string
  status: string
  summary: string
  next: string
  owner: string
  updated: string
  tickets: string[]
  ticket_status: Record<string, PlanTicket>
  front_matter: boolean
  sbar: boolean
  version: string
  mtime: string
  size: number
  progress?: { done: number; total: number }
}
export interface PlanProject {
  id: string
  slug: string
  archived: boolean
  title: string
  status: string
  updated: string
  version: string
  tracker: PlanItem | null
  docs: PlanItem[]
  // PRs and ticket moves that landed after the tracker's updated day. Only active trackers.
  freshness?: PlanFreshness
  // Done with only an open intake left: waiting on person's work ticket, listed apart from active work.
  awaiting_ticket?: boolean
}
export interface PlanFreshEvent {
  kind: 'merged' | 'opened' | 'status'
  ref: string
  day: string
  title: string
  url: string
}
export interface PlanFreshness {
  state: 'ok' | 'loading' | 'error'
  behind: boolean
  events: PlanFreshEvent[]
  checked_utc: string
  errors: string[]
}
export interface PlansData {
  generated_utc: string
  root: string
  projects: PlanProject[]
  library: PlanItem[]
  archived: { projects: PlanProject[]; library: PlanItem[] }
  counts: { projects: number; library: number; archived: number }
  untracked?: PlanUntracked
  jira: { state: 'ok' | 'loading' | 'stale' | 'error' | 'none'; checked_utc: string; errors: string[] }
}
// ticket keys with recent PR work that no tracker names
export interface PlanUntrackedRow {
  key: string
  url: string
  slug: string
  ticket_title: string
  ticket_status: string
  ticket_done: boolean
  prs: { ref: string; title: string; url: string; state: string; day: string }[]
}
export interface PlanUntracked {
  state: 'ok' | 'loading' | 'error' | 'none'
  rows: PlanUntrackedRow[]
  checked_utc: string
  errors: string[]
  window_days: number
  min_prs: number
}
export const usePlans = createLiveStore(() => fetchApi<PlansData>('api/plans'), 60_000)
export async function fetchPlanFile(id: string, version?: string): Promise<{ item: PlanItem; text: string | null }> {
  // version keys the request to the file revision the list showed, so a changed file is re-read
  const v = version ? `&v=${encodeURIComponent(version)}` : ''
  return fetchApi<{ item: PlanItem; text: string | null }>(`api/plans/file?path=${encodeURIComponent(id)}${v}`)
}
export interface PlanMove {
  moved: boolean
  already?: boolean
  from: string
  to: string
}
export const postPlanArchive = (path: string, version: string) => docPost<PlanMove>('api/plans/archive', { path, version })
export const postPlanCreate = (key: string, slug: string, title: string) =>
  docPost<{ created: boolean; path: string; id: string }>('api/plans/create', { key, slug, title })
export const postPlanDismiss = (key: string) => docPost<{ dismissed: boolean; key: string }>('api/plans/dismiss', { key })
export const postPlanRestore = (path: string, version: string) => docPost<PlanMove>('api/plans/restore', { path, version })
export const postEngDecide = (uid: string, act: EngAct, note = '') => docPost<EngItem>('api/eng-backlog/decide', { uid, act, note })
export const postEngHandle = (uid: string, act: 'snooze' | 'restore') => docPost<{ uid: string }>('api/eng-backlog/handle', { uid, act })
export const postEngTackle = (uid: string, context = '') =>
  docPost<TackleSession & { fp: string }>('api/eng-backlog/tackle', { uid, context })

// ---- Builds: app_e and endpoint agent pipelines on platform ----
import type { LiveJob } from '../pages/infra/types'
export interface BuildRun {
  id: number
  attempt: number | null
  status: string
  conclusion: string | null
  event: string
  branch: string
  sha: string
  actor: string | null
  created: string
  started: string | null
  updated: string
  url: string
  jobs: LiveJob[]
  error: string | null
  waiting_on: string[]
  approve_here: string[]
  reason: { where: string; message: string } | null
  summary: string | null
  refusal?: BuildRefusal | null
}
// A dev_tier deploy refused because the branch is behind main. The server decides the phase.
export interface BuildRefusal {
  branch: string
  behind: number
  behind_live: number | null
  head: string
  own: boolean | null
  phase: 'needs_action' | 'working' | 'conflict' | 'superseded' | 'info'
  error?: string | null
  files?: string[] | null
}
// One input of a workflow or task, as the server's fixed spec lists it (DESIGN.md 12.49). publishes_when is the value that
// makes a run publish or change something.
export interface RunSpecInput {
  name: string
  type: 'boolean' | 'choice' | 'string'
  default: string | boolean
  options?: string[]
  pattern?: string
  required?: boolean
  help?: string
  publishes_when?: string | boolean
}
// Current state vs history (DESIGN.md 12.50): failed only while the newest finished run on main failed.
export interface PipelineState {
  current: string | null
  failed: boolean
  last_main: string | null
  history: number[]
}
export interface BuildPipeline {
  key: string
  product: string
  label: string
  workflow: string
  url: string
  runs: BuildRun[]
  inputs?: RunSpecInput[]
  ref?: 'main' | 'branch'
  paused?: boolean
  state?: PipelineState
}
export interface app_eLanded {
  recorded: {
    payload?: string
    content_version?: string
    health_version?: string
    released?: string
    source?: string
    bytes?: number
  } | null
  live: { health?: { name?: string; version?: string; modified?: string } | null } | null
  blob: { bytes?: number; modified?: string } | null
  drift: string[]
  errors: string[]
}
export interface AgentLanded {
  latest: { tag: string; version: string; published: string | null; url: string } | null
  main_version: string | null
  pending?: string
  errors: string[]
}
export interface Builds {
  generated_utc: string
  repo: string
  pipelines: BuildPipeline[]
  landed: { app_e?: app_eLanded; agent?: AgentLanded }
  errors: string[]
  running: number
  waiting: number
  active: boolean
}
export async function postUpdateFromMain(body: {
  run: number
  branch: string
  sha: string
}): Promise<{ result: 'merged' | 'rerun' | 'conflict' | 'working'; files?: string[] | null }> {
  const res = await fetch(`${BASE}api/builds/update-from-main`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const j = (await res.json().catch(() => ({}))) as {
    error?: string
    result?: 'merged' | 'rerun' | 'conflict' | 'working'
    files?: string[] | null
  }
  if (!res.ok || !j.result) throw new Error(j.error || `update from main -> ${res.status}`)
  return { result: j.result, files: j.files }
}
export const useBuilds = createLiveStore(() => fetchApi<Builds>('api/builds'), 8_000)

// Start one workflow through the run contract (DESIGN.md 12.49): the server checks every input against its fixed spec,
// refuses a paused or running pipeline (409) and folds a repeated click into the queued run (already).
export interface RunAnswer {
  started: boolean
  already?: boolean
  publishes?: boolean
}
export class RunError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}
async function runPost(path: string, body: Record<string, unknown>): Promise<RunAnswer> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const j = (await res.json().catch(() => ({}))) as { error?: string } & RunAnswer
  if (!res.ok) throw new RunError(j.error || `${path} -> ${res.status}`, res.status)
  return j
}
export const postBuildDispatch = (pipeline: string, ref: string, inputs: Record<string, string | boolean>) =>
  runPost('api/builds/dispatch', { pipeline, ref, inputs })

// Maintenance tasks the Infrastructure page may start (INFRA_TASKS), each with its own input spec.
export interface InfraTask {
  name: string
  label: string
  inputs: RunSpecInput[]
  running?: boolean
}
export const useInfraTasks = createLiveStore(() => fetchApi<{ tasks: InfraTask[] }>('api/infra/tasks'), 30_000)
// Run now for any scheduled job, same contract: a paused or finished job is refused (409), a running one answers already.
export const postCronNow = (id: string, note: string) => runPost(`api/cron-pulse/${id}/run`, { note })
export const postInfraTaskRun = (what: string, inputs: Record<string, string | boolean>) =>
  runPost('api/infra/tasks/run', { what, inputs })

// The one server-side problem list (DESIGN.md 12.50): the rail badge, the tab counts and the Overview read it, the client never
// applies a threshold of its own.
export type ProblemTone = 'needs_me' | 'worth_a_look' | 'healthy'
export interface ProblemItem {
  id: string
  hub: string
  section: string
  item: string
  label: string
  tone: ProblemTone
  headline: string
  details: string[]
  count: number
  running: boolean
  url?: string
}
export interface Problems {
  items: ProblemItem[]
  counts: {
    needs_me: number
    worth_a_look: number
    healthy: number
    running: number
    total: number
    by_section: Record<string, number>
    by_item: Record<string, number>
  }
}

// ---- Core consumption (standard section 19): consumption.json rendered, approvals by gh ----
export type CoreCi = 'pass' | 'fail' | 'pending' | 'none'
export interface CoreApproval {
  kind: 'none' | 'enabled' | 'disabled' | 'done'
  reason: string
  target?: string
}
export interface CoreRow {
  repo: string
  label: string
  mode: 'workflow' | 'ops-center' | 'vendored' | string
  class: string
  report_only: boolean
  pinned: string | null
  latest: string | null
  behind: number | null
  sync_pr: { number: number; url: string; head: string; created_at: string | null; ci: CoreCi } | null
  sync_applies: boolean
  status: { pass: number; proved: number; fail: number; unverified: number } | null
  ui_verdict: string | null
  adoption: { part: string; file: string; kit_part: string; relation: string; risk: string | null }[]
  not_collected: string[]
  approval: CoreApproval
}
export interface CoreItem {
  issue: number
  id: string
  title: string
  can_approve?: boolean
  done?: boolean
}
export interface CoreConsumption {
  state: 'ok' | 'error'
  error?: string
  message?: string
  generated_at?: string
  core_repo?: string
  latest?: string
  consumers: CoreRow[]
  account?: { report_issue: string | null; awaiting_decision: CoreItem[]; approved_unopened: CoreItem[] }
  peers?: {
    issues: {
      number: number
      url: string
      author: string
      mine: boolean
      items: { id: string; title: string; kind: string; status: string; shipped_in?: string }[]
    }[]
    suggestions: { issue: number; id: string; title: string; author: string; shipped_in: string; new: boolean }[]
    new_count: number
  }
  not_collected?: string[]
  needs_me?: number
}
// The panel polls the server at most once a minute and again when the tab regains focus (onLiveTick).
export const useCoreConsumption = createLiveStore(() => fetchApi<CoreConsumption>('api/core-consumption'), 60_000)
export const postCorePr = (repo: string, number: number, confirm: string) =>
  docPost<{ done: string[]; already?: boolean }>('api/core-consumption/approve-pr', { repo, number, confirm })
export const postCoreItem = (issue: number, id: string, confirm: string) =>
  docPost<{ done: string[]; already?: boolean }>('api/core-consumption/approve-item', { issue, id, confirm })
