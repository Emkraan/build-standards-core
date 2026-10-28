// which Hermes cron job watches a review card, when it last ran and runs next, and Run now.
// WatcherChip sits on a card (ReviewItem renders it from the card's `watcher`), PulseStrip lists the
// jobs that feed the page. Clicking Run now flips the card to the animated working state at once
// (optimistic), then polls /api/cron-pulse until Hermes shows the run finished and reloads the cards.
import { Button, Textarea, useToast } from '@kit'
import { useEffect, useState } from 'react'
import type { CardWatch, CronWatcher } from '../lib/data'
import { fetchCronPulse, postCronRun, useAresReviews, useCronPulse, useplatformReviews } from '../lib/data'
import { JobModalById } from '../pages/infra/JobModal'
import { Tag } from '../pages/reviews/parts'

// Runs I started from this page and have not seen finish. Module level so every card on the same job
// flips together and a tab change does not lose the state.
const optimistic = new Map<string, number>()
const subs = new Set<() => void>()
const emit = () => {
  for (const f of subs) f()
}
const OPTIMISTIC_MAX_MS = 6 * 60_000
const OPTIMISTIC_MIN_MS = 6_000

function useOptimistic(): Map<string, number> {
  const [, force] = useState(0)
  useEffect(() => {
    const f = () => force((n) => n + 1)
    subs.add(f)
    return () => {
      subs.delete(f)
    }
  }, [])
  return optimistic
}

function clock(iso?: string | null): string {
  if (!iso) return 'not scheduled'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '?'
  const t = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  const day = new Date()
  if (d.toDateString() === day.toDateString()) return t
  return `${d.toLocaleDateString([], { weekday: 'short' })} ${t}`
}

/** What the page should treat as the job's state right now: server truth OR a run I just asked for. */
export function useJob(w?: CronWatcher | null): { w: CronWatcher | null; working: boolean; asked: boolean } {
  const opt = useOptimistic()
  const { data } = useCronPulse()
  if (!w || !w.id) return { w: w || null, working: false, asked: false }
  const fresh = data?.jobs.find((j) => j.id === w.id)
  const merged = fresh ? { ...w, ...fresh } : w
  const asked = opt.has(w.id)
  return { w: merged, working: merged.running || merged.queued || asked, asked }
}

/** Start a run and follow it to the end. One poller per job, however many cards share it. */
export function useRunNow() {
  const { refresh } = useCronPulse()
  const { reload: reloadOly } = useplatformReviews()
  const { reload: reloadAres } = useAresReviews()
  const { toast } = useToast()
  return async (w: CronWatcher, note?: string) => {
    if (!w.id || optimistic.has(w.id)) return
    const id = w.id
    optimistic.set(id, Date.now())
    emit()
    try {
      const r = await postCronRun(id, note)
      toast('success', r.already ? `${w.name} is already running` : `${w.name} started`)
    } catch (e) {
      optimistic.delete(id)
      emit()
      toast('error', e instanceof Error ? e.message : String(e))
      return
    }
    const began = optimistic.get(id) ?? Date.now()
    const timer = window.setInterval(async () => {
      refresh()
      await new Promise((r) => setTimeout(r, 800))
      const age = Date.now() - began
      const j = await fetchCronPulse(true).catch(() => null)
      const row = j?.jobs.find((x) => x.id === id)
      const live = !!row && (row.running || row.queued)
      if ((!live && age > OPTIMISTIC_MIN_MS) || age > OPTIMISTIC_MAX_MS) {
        window.clearInterval(timer)
        optimistic.delete(id)
        emit()
        refresh()
        reloadOly()
        reloadAres()
        // The agent can take a minute to land a verdict, so a second look catches late changes.
        window.setTimeout(() => {
          reloadOly()
          reloadAres()
        }, 20_000)
      }
    }, 4000)
  }
}

function lastText(w: CronWatcher): string {
  const at = w.last_tick?.at || w.last_run_at
  if (!at) return 'last run unknown'
  const note = w.silent_no_change ? ' (no change)' : w.last_tick?.kind === 'failed' || w.last_status === 'error' ? ' (failed)' : ''
  return `last ${clock(at)}${note}`
}

/** The chip: Watcher: <job> - next 7:23 PM - last 7:08 PM (no change), plus Run now. */
export function WatcherChip({ pulse }: { pulse: CardWatch }) {
  const { w, working } = useJob(pulse.watcher)
  const run = useRunNow()
  const [scoped, setScoped] = useState(false)
  const [note, setNote] = useState('')
  if (pulse.unwatched || !w) {
    return (
      <div className="rh-watch rh-watch-none">
        <span>{pulse.paused_job ? `Nothing is watching this (${pulse.paused_job} is paused)` : 'Nothing is watching this'}</span>
      </div>
    )
  }
  if (w.server) {
    return (
      <div className="rh-watch">
        <span className="rh-watch-text">
          <b>Refreshed by:</b> {w.name}
          {w.cadence ? ` \u00b7 ${w.cadence}` : ''}
        </span>
      </div>
    )
  }
  return (
    <div className="rh-watch" data-working={working || undefined}>
      <span className="rh-watch-text">
        <b>Watcher:</b> {w.name}
        {working ? (
          <>
            {' \u00b7 '}
            <Tag tone="info" live>
              {w.running ? 'running now' : 'starting'}
            </Tag>
          </>
        ) : (
          <>
            {' \u00b7 '}next {clock(w.next_run_at)}
            {' \u00b7 '}
            {lastText(w)}
          </>
        )}
        {(w.also?.length ?? 0) > 0 && <span className="rh-watch-also"> {`\u00b7 +${w.also?.length} more`}</span>}
      </span>
      {w.request_error && <span className="rh-watch-err">{w.request_error}</span>}
      <span className="rh-watch-actions">
        {!working && (
          <button type="button" className="rh-textbtn" aria-expanded={scoped} onClick={() => setScoped((s) => !s)}>
            Add a note
          </button>
        )}
        <Button size="sm" disabled={working || w.enabled === false} onClick={() => run(w, scoped ? note.trim() : '')}>
          {working ? 'Running...' : 'Run now'}
        </Button>
      </span>
      {scoped && !working && (
        <div className="rh-watch-note">
          <Textarea
            rows={2}
            maxLength={600}
            value={note}
            placeholder="Focus on PR 361"
            aria-label="Note for this run"
            onChange={(e) => setNote(e.target.value)}
          />
        </div>
      )}
    </div>
  )
}

/** The jobs that feed the page, one aligned row each: name, next run, Details (the job dialog) and Run now. */
export function PulseStrip({ jobs }: { jobs?: CronWatcher[] }) {
  const run = useRunNow()
  const opt = useOptimistic()
  const { data } = useCronPulse()
  const [detail, setDetail] = useState<string | null>(null)
  const list = (jobs || []).map((j) => ({ ...j, ...(data?.jobs.find((x) => x.id === j.id) || {}) }))
  if (list.length === 0) return null
  return (
    <section className="rh-pulse" aria-label="Cron jobs feeding this page">
      <h2 className="rh-pulse-label">Jobs feeding this page</h2>
      <ul className="rh-pulse-list">
        {list.map((j) => {
          const working = j.running || j.queued || (!!j.id && opt.has(j.id))
          return (
            <li key={j.id || j.name} className="rh-pulse-job" data-working={working || undefined}>
              <span className="rh-pulse-name" title={j.name}>
                {j.name}
              </span>
              <span className="rh-pulse-when">
                {working ? (
                  <Tag tone="info" live>
                    running
                  </Tag>
                ) : (
                  <>
                    next {clock(j.next_run_at)}
                    {j.silent_no_change ? ' \u00b7 quiet' : ''}
                  </>
                )}
              </span>
              <span className="rh-pulse-actions">
                {j.id && (
                  <Button size="sm" variant="ghost" aria-haspopup="dialog" onClick={() => setDetail(j.id)}>
                    Details
                  </Button>
                )}
                {!j.server && (
                  <Button size="sm" disabled={working || j.enabled === false} onClick={() => run(j)}>
                    Run now
                  </Button>
                )}
              </span>
            </li>
          )
        })}
      </ul>
      {detail && <JobModalById id={detail} onClose={() => setDetail(null)} />}
    </section>
  )
}
