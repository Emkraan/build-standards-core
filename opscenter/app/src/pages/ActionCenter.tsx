import { Button, Pill as KitPill, useToast } from '@kit'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import ActionTable, { type ActionItem } from '../components/ActionTable'
import { hoursUntil } from '../components/Approvals'
import { useCopyDialog } from '../components/CopyDialog'
import DarkLaunches from '../components/DarkLaunches'
import { Card, Empty } from '../components/ui'
import { useActionCounts } from '../lib/counts'
import type { HandledEntry, TackleSession, TeamPerformance } from '../lib/data'
import {
  fetchHandled,
  onLiveTick,
  postHandled,
  postReopenReplied,
  postTackle,
  useApprovals,
  useData,
  useLocalStore,
  useplatformReviews,
  useReplied,
  useTackleSessions,
} from '../lib/data'

interface ActionCenterData {
  headline?: string
  generated_utc?: string
  items?: ActionItem[]
  dropped?: { cid: string; reason: string }[]
  routing?: { rules: number; considered: number; routed_away: number; collector_errors?: string[]; unregistered?: string[]; error?: string }
}
interface Monitors {
  monitors: { name: string; updated: string | null }[]
}

type Handled = Record<string, HandledEntry>

function ago(iso: string | null): { text: string; stale: boolean } {
  if (!iso) return { text: 'no data', stale: true }
  const d = (Date.now() - new Date(iso).getTime()) / 60000
  if (Number.isNaN(d)) return { text: 'no data', stale: true }
  if (d < 60) return { text: `${Math.round(d)}m ago`, stale: d > 90 }
  if (d < 1440) return { text: `${Math.round(d / 60)}h ago`, stale: d > 180 }
  return { text: `${Math.round(d / 1440)}d ago`, stale: true }
}

const NOW = () => new Date().toISOString()

// Compact pointer to the Reviews hub (platform + team); renders nothing when N = 0.
// under it, one Now row per platform Needs me item (what it is and the click it needs), each
// linking to Reviews. A row leaves when its card leaves Needs me.
function ReviewsBanner() {
  const { platform, team, reviews } = useActionCounts()
  const { data: oly } = useplatformReviews()
  if (!reviews) return null
  const parts = [platform ? `platform ${platform}` : '', team ? `team ${team}` : ''].filter(Boolean).join(', ')
  const rows = oly?.needs_me_rows || []
  return (
    <>
      <Link className="oly-banner" to={platform ? '/reviews/platform' : '/reviews/team'}>
        <span className="oly-dot" />
        <b>
          Reviews: {reviews} item{reviews === 1 ? '' : 's'} need{reviews === 1 ? 's' : ''} you ({parts})
        </b>
        <span className="oly-go">Review &rarr;</span>
      </Link>
      {rows.length > 0 && (
        <ul className="oly-now" aria-label="platform items that need me now">
          {rows.map((r) => (
            <li key={`${r.kind}-${r.pr ?? r.title}`}>
              <Link to="/reviews/platform">
                <span className="oly-dot" />
                <span className="oly-now-tag">Now</span>
                <span className="oly-now-what">{r.what}</span>
                <span className="oly-now-title">
                  {r.pr ? `#${r.pr} ` : ''}
                  {r.title}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </>
  )
}

// JSM change approvals live on the Jira hub (/jira/changes). Only a compact
// pointer here, hidden when nothing waits on me. Flags the nearest window.
function ChangesBanner() {
  const { data } = useApprovals()
  const pending = data?.pending || []
  if (!pending.length) return null
  const soonest = pending
    .map((c) => hoursUntil(c.planned_start))
    .filter((h): h is number => h !== null)
    .sort((a, b) => a - b)[0]
  const n = pending.length
  return (
    <Link className="oly-banner" to="/jira/changes">
      <span className="oly-dot" />
      <b>
        JSM: {n} change{n === 1 ? '' : 's'} waiting on my approval
      </b>
      {soonest !== undefined && (
        <span className="muted">{soonest < 0 ? 'a window has already passed' : `next window in ${Math.max(1, Math.round(soonest))}h`}</span>
      )}
      <span className="oly-go">Review &rarr;</span>
    </Link>
  )
}

// a 1:1 agenda card I already wrote to that person about leaves the list and the count.
// It stays here as a small Replied chip, one click puts the card back.
function RepliedChips() {
  const { data, mutate } = useReplied()
  const { toast } = useToast()
  const [busy, setBusy] = useState('')
  const list = data?.replied || []
  if (!list.length) return null
  const reopen = (id: string) => {
    setBusy(id)
    postReopenReplied(id)
      .then((d) => {
        mutate(() => d)
        toast('success', 'Reopened. The card returns to the list within a minute.')
      })
      .catch((e: Error) => toast('error', 'Could not reopen', { description: e.message }))
      .finally(() => setBusy(''))
  }
  return (
    <div className="ac-replied" role="group" aria-label="Replied 1:1 cards">
      <KitPill tone="success" dot>
        Replied {list.length}
      </KitPill>
      {list.map((r) => (
        <Button
          key={r.id}
          size="sm"
          variant="ghost"
          disabled={busy === r.id}
          data-tip={`I wrote to ${r.first} about this${r.replied_at ? ` on ${r.replied_at.slice(0, 10)}` : ''}. Click to reopen the card.`}
          onClick={() => reopen(r.id)}
        >
          <span className="ac-replied-text">
            {r.first}: {r.title}
          </span>
        </Button>
      ))}
    </div>
  )
}

export default function ActionCenter() {
  const { data, error } = useData<ActionCenterData>('action-center.json')
  const { data: mon } = useData<Monitors>('monitors.json')
  const { data: tp } = useData<TeamPerformance>('team-performance.json')
  const [handled, setHandled] = useLocalStore<Handled>('ac-handled-v1', {})
  const [copied, setCopied] = useState(false)
  const { showCopy, dialog: copyDialog } = useCopyDialog()
  const [tackle, setTackle] = useState<Record<string, TackleSession>>({})
  const [tackleErr, setTackleErr] = useState<Record<string, string>>({})

  // Poll tackle sessions so a running badge flips to finished on its own.
  // Fed by the shared tackle store (one 10 s poller for every surface, paused while the tab is hidden).
  const { data: tackleLive } = useTackleSessions()
  useEffect(() => {
    if (tackleLive) setTackle(tackleLive)
  }, [tackleLive])

  // mode 'teams' starts a Draft in Teams session, tracked under teams-<fp> so the
  // item's own Tackle session and button are untouched.
  const startTackle = (fp: string, context = '', mode?: 'teams') => {
    const key = mode === 'teams' ? `teams-${fp}` : fp
    setTackleErr((e) => {
      const n = { ...e }
      delete n[fp]
      return n
    })
    setTackle((s) => ({ ...s, [key]: { title: '', session: '', pid: 0, state: 'launching', started: NOW(), log: '' } }))
    postTackle(fp, context, mode)
      .then((rec) => setTackle((s) => ({ ...s, [key]: rec })))
      .catch((err: Error) => {
        setTackle((s) => {
          const n = { ...s }
          delete n[key]
          return n
        })
        setTackleErr((e) => ({ ...e, [fp]: err.message }))
      })
  }

  // Hydrate from the durable server store on mount so a cleared browser or a
  // different device shows the same handled set, and so it matches what the
  // analysis cron reads. Server is authority: its entries overwrite local ones,
  // but any local-only entry (written while the server was unreachable) is kept
  // and pushed up so an offline click is not lost.
  // biome-ignore lint/correctness/useExhaustiveDependencies: setHandled is a stable store setter; the poller must start once
  useEffect(() => {
    let alive = true
    let first = true
    const pull = () =>
      fetchHandled()
        .then((server) => {
          if (!alive) return
          setHandled((local) => {
            const merged: Handled = { ...server }
            for (const [fp, h] of Object.entries(local)) {
              if (!(fp in server)) {
                // Only the first pull pushes offline clicks up; later pulls
                // treat the server as truth (a server-side restore wins).
                if (first) {
                  merged[fp] = h
                  postHandled({ fp, act: h.act, at: h.at, until: h.until }).catch(() => {})
                }
              }
            }
            first = false
            return merged
          })
        })
        .catch(() => {
          // server unreachable (e.g. static preview) - localStorage still works
        })
    // Re-pull so an item resolved from inside its Hermes session flips here.
    const stop = onLiveTick(pull, 20_000)
    pull()
    return () => {
      alive = false
      stop()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Items I just routed elsewhere leave at once (live-actions 1.1). The rule removes them from
  // the served data on the background re-bundle, Undo puts them back.
  const [routed, setRouted] = useState<Set<string>>(new Set())
  const onRouted = (fp: string, on: boolean) =>
    setRouted((s) => {
      const n = new Set(s)
      if (on) n.add(fp)
      else n.delete(fp)
      return n
    })
  const allItems = useMemo(() => (data?.items || []).filter((it) => !routed.has(it.fp)), [data, routed])

  // An item is currently handled if resolved/ignored/ignored_forever, or snoozed
  // and still inside the snooze window. Expired snoozes fall back to active.
  const isHandled = (fp: string) => {
    const h = handled[fp]
    if (!h) return false
    if (h.act === 'snoozed' && h.until) return new Date(h.until).getTime() > Date.now()
    return h.act !== 'snoozed'
  }

  const active = allItems.filter((it) => !isHandled(it.fp))
  const handledItems = allItems.filter((it) => isHandled(it.fp) && handled[it.fp]?.act !== 'resolved')
  const completedCount = Object.values(handled).filter((h) => h.act === 'resolved').length

  const mark = (fp: string, act: string) => {
    setHandled((prev) => {
      const next = { ...prev }
      if (act === 'restore') {
        delete next[fp]
        postHandled({ fp, act: 'restore' }).catch(() => {})
      } else if (act === 'snoozed') {
        const until = new Date(Date.now() + 7 * 864e5).toISOString()
        next[fp] = { act, at: NOW(), until }
        postHandled({ fp, act, at: next[fp].at, until }).catch(() => {})
      } else {
        next[fp] = { act, at: NOW() }
        postHandled({ fp, act, at: next[fp].at }).catch(() => {})
      }
      return next
    })
  }

  // "Copy handled for ops_center": exports the fingerprints owner has actioned so
  // he can paste them back and ops_center persists the ignore_always ones server-side.
  const copyHandled = async () => {
    const lines = Object.entries(handled).map(([fp, h]) => {
      const it = allItems.find((x) => x.fp === fp)
      return `${h.act}\t${fp}\t${it ? it.title : '(item no longer present)'}`
    })
    const payload = `Handled action items (paste to ops_center). Record any ignored_forever in action-suppressions.json:\n${lines.join('\n')}`
    try {
      await navigator.clipboard.writeText(payload)
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    } catch {
      showCopy('Copy handled items', payload)
    }
  }

  return (
    <div>
      <div className="page-head">
        <h1>Action Center</h1>
        <p>
          What needs my attention now
          {data?.generated_utc ? ` \u00b7 synthesized ${data.generated_utc.slice(0, 16).replace('T', ' ')}Z` : ''}
        </p>
      </div>

      {/* JSM approvals and platform reviews live on their own pages, pointers only */}
      <ChangesBanner />
      <ReviewsBanner />

      {/* Actionable synthesized items */}
      <div className="ac-controls">
        <span className="muted">
          {active.length} open{handledItems.length ? ` \u00b7 ${handledItems.length} handled` : ''}
        </span>
        {completedCount > 0 && (
          <Link className="btn" data-variant="ghost" data-size="sm" to="/action/completed">
            {completedCount} completed
          </Link>
        )}
        {handledItems.length > 0 && (
          <Button size="sm" variant="ghost" onClick={copyHandled}>
            {copied ? 'Copied' : 'Copy handled for ops_center'}
          </Button>
        )}
        {copyDialog}
        {data?.routing && (
          <Link
            className="btn"
            data-variant="ghost"
            data-size="sm"
            to="/action/routing"
            title="What the collector considered, what my routing rules sent elsewhere, and what the analysis dropped"
          >
            {data.routing.considered} considered {'\u00b7'} {data.routing.routed_away} routed away {'\u00b7'} {data.dropped?.length ?? 0}{' '}
            dropped
            {data.routing.error || data.routing.collector_errors?.length ? ' \u00b7 check routing' : ''}
          </Link>
        )}
      </div>

      <RepliedChips />

      <DarkLaunches />

      {error && <Empty>Could not load the action center.</Empty>}
      {!error && !data && <Empty>Loading...</Empty>}
      {data && active.length === 0 && handledItems.length === 0 && completedCount === 0 && (
        <Empty>No synthesized action items yet. The analysis cron populates this.</Empty>
      )}
      {data && active.length === 0 && (handledItems.length > 0 || completedCount > 0) && (
        <Empty>All caught up.{handledItems.length ? ` ${handledItems.length} handled item(s) hidden.` : ''}</Empty>
      )}

      {data && (
        <ActionTable
          items={allItems}
          handled={handled}
          mark={mark}
          tackle={tackle}
          tackleErr={tackleErr}
          onTackle={startTackle}
          onRouted={onRouted}
        />
      )}

      {/* Context cards (folded in from the old Overview) */}
      <div className="grid" style={{ marginTop: 18 }}>
        {tp && (
          <Card title="Team performance" sub={tp.sprints.join(' + ')}>
            {tp.engineers.map((name) => {
              const m = tp.metrics[name]
              const tone = m.completion_pct >= 90 ? 'good' : m.completion_pct >= 75 ? 'warn' : 'alert'
              return (
                <div key={name} className="ov-eng">
                  <span>{name}</span>
                  <div className="ov-eng-bar">
                    <div className={`progress-fill ${tone}`} style={{ width: `${m.completion_pct}%` }} />
                  </div>
                  <b>{m.completion_pct}%</b>
                </div>
              )
            })}
            <Link className="ov-link" to="/team">
              View full assessment &rarr;
            </Link>
          </Card>
        )}

        {mon && (
          <Card title="Signal freshness">
            <table>
              <tbody>
                {mon.monitors.map((s) => {
                  const a = ago(s.updated)
                  return (
                    <tr key={s.name}>
                      <td>
                        <span className="dot" style={{ background: a.stale ? 'var(--alert)' : 'var(--good)' }} />
                        {s.name}
                      </td>
                      <td style={{ textAlign: 'right', color: a.stale ? 'var(--alert)' : 'var(--text-secondary)' }}>{a.text}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </Card>
        )}
      </div>
    </div>
  )
}
