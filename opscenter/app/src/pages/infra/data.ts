// Live stores, formatters, tone rules and the health rollup shared by every Infrastructure tab.
import type { StatTone, StatusTone } from '@kit'
import { useEffect, useState } from 'react'
import { createLiveStore, fetchApi, relTime } from '../../lib/data'
import type { AccountLimit, Cron, Github, LiveJobs, LlmAccount, LlmAccounts, PR, Run, RunnerFleet, Snapshot, Spend } from './types'

export const useRunners = createLiveStore(() => fetchApi<RunnerFleet>('/api/infra/runners'), 30_000)
export const useSpend = createLiveStore(() => fetchApi<Spend>('/api/infra/spend'), 120_000)
export const useCron = createLiveStore(() => fetchApi<Cron>('/api/infra/cron'), 30_000)
export const useGithub = createLiveStore(() => fetchApi<Github>('/api/infra/github'), 30_000)
export const useAccounts = createLiveStore(() => fetchApi<LlmAccounts>('/api/infra/accounts'), 60_000)
export const useLiveJobs = createLiveStore(() => fetchApi<LiveJobs>('/api/infra/live-jobs'), 6_000)

/** Health level used by the rollup: good, watch, or action needed. */
export type Level = 'good' | 'warn' | 'alert'

export const LEVEL_TONE: Record<Level, StatusTone> = { good: 'success', warn: 'warning', alert: 'danger' }
export const LEVEL_STAT: Record<Level, StatTone> = { good: 'success', warn: 'warning', alert: 'danger' }

export const usd = (n: number) => `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
export const short = (repo: string) => repo.split('/')[1] || repo
export const fmtTok = (n: number) =>
  n >= 1e9 ? `${(n / 1e9).toFixed(2)}B` : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : String(n)
export const ts = (iso: string | null | undefined) => (iso ? new Date(iso).getTime() : null)

export function healthTone(h: string): StatusTone {
  return h === 'ok' ? 'success' : h === 'failing' ? 'danger' : h === 'overdue' ? 'warning' : h === 'paused' ? 'neutral' : 'info'
}
/** Sort rank for job health: the worst first when sorted ascending. */
export const HEALTH_RANK: Record<string, number> = { failing: 0, overdue: 1, pending: 2, ok: 3, paused: 4 }

export function kindTone(kind: string): StatusTone {
  return kind === 'script' ? 'success' : kind === 'gated agent' ? 'info' : 'warning'
}
export function runTone(r: Run): StatusTone {
  if (r.status !== 'completed') return 'info'
  if (r.conclusion === 'success') return 'success'
  if (r.conclusion === 'skipped' || r.conclusion === 'cancelled' || r.conclusion === 'neutral') return 'neutral'
  return 'danger'
}
export function prTone(p: PR): StatusTone {
  if (p.checks.fail) return 'danger'
  if (p.checks.pending) return 'info'
  return 'success'
}
export function stateTone(status: string, conclusion: string | null): StatusTone {
  if (status === 'queued' || status === 'waiting' || status === 'pending') return 'warning'
  if (status !== 'completed') return 'info'
  if (conclusion === 'success') return 'success'
  if (conclusion === 'skipped' || conclusion === 'cancelled' || conclusion === 'neutral') return 'neutral'
  return 'danger'
}
export function stateLabel(status: string, conclusion: string | null): string {
  if (status === 'completed') return conclusion || 'done'
  return status.replace('_', ' ')
}

export function nextIn(iso: string | null): string {
  if (!iso) return ''
  const m = Math.round((new Date(iso).getTime() - Date.now()) / 60000)
  if (m < 0) return `${-m}m late`
  if (m < 60) return `in ${m}m`
  if (m < 1440) return `in ${Math.floor(m / 60)}h ${m % 60}m`
  return `in ${Math.floor(m / 1440)}d`
}

export function resetIn(iso: string | null, now: number): string {
  if (!iso) return 'reset time unknown'
  const t = new Date(iso)
  const m = Math.max(0, Math.round((t.getTime() - now) / 60000))
  const left =
    m < 60 ? `${m}m` : m < 1440 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${Math.floor(m / 1440)}d ${Math.floor((m % 1440) / 60)}h`
  const sameDay = new Date(now).toDateString() === t.toDateString()
  const at = t.toLocaleString(
    'en-US',
    sameDay ? { hour: 'numeric', minute: '2-digit' } : { weekday: 'short', hour: 'numeric', minute: '2-digit' },
  )
  return `resets in ${left} (${at})`
}

export const fmtWhen = (iso: string | null | undefined) =>
  iso
    ? `${new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })} (${relTime(iso)})`
    : 'never'

export function limitLevel(l: AccountLimit): Level {
  if (l.severity !== 'normal' || l.percent >= 90) return 'alert'
  return l.percent >= 70 ? 'warn' : 'good'
}

/** The limit closest to blocking us decides the account tone. */
export function teamHeadroom(a: LlmAccount): AccountLimit | undefined {
  return [...a.limits].sort((x, y) => y.percent - x.percent)[0]
}

export function latestSnapshot(fleet: RunnerFleet): Snapshot | null {
  const b = fleet.backup
  return b && 'id' in (b.latest || {}) ? (b.latest as Snapshot) : null
}

function daysLeftInMonth(): number {
  const now = new Date()
  const end = new Date(now.getFullYear(), now.getMonth() + 1, 1)
  return Math.max(0, (end.getTime() - now.getTime()) / 86_400_000)
}

export interface Projection {
  value: number
  rate: number
  basis: string
  real: boolean
}

// Real projected Enterprise bill: Anthropic's billed figure so far plus the current burn for the
// rest of the month. The burn comes from Anthropic's own snapshots once a full day is recorded
// (it then includes claude.ai and Cowork), otherwise from Hermes calls billed since the switch.
export function enterpriseProjection(spend: Spend | null | undefined, ent: LlmAccount | undefined): Projection | null {
  if (!spend) return null
  const hist = ent?.spend_history
  const real = hist?.rate_per_day != null
  const rate = real ? (hist?.rate_per_day as number) : spend.totals.billed_rate_per_day
  const base = ent?.spend ? ent.spend.used_usd : spend.totals.billed_mtd
  const basis = real
    ? `Anthropic burn over the last ${hist?.rate_basis_days} days`
    : `Hermes fallback burn since the Team switch (${spend.rate_basis_days} days)`
  return { value: base + rate * daysLeftInMonth(), rate, basis, real: !!ent?.spend }
}

/** A clock that ticks every second while active (live durations). */
export function useTick(active: boolean): number {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (!active) return
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [active])
  return now
}

export function dur(start: string | null, end: string | null, now: number): string {
  if (!start) return ''
  const ms = (end ? new Date(end).getTime() : now) - new Date(start).getTime()
  if (ms < 0) return '0s'
  const sec = Math.round(ms / 1000)
  return sec < 60 ? `${sec}s` : `${Math.floor(sec / 60)}m ${String(sec % 60).padStart(2, '0')}s`
}
