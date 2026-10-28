// Alerts: what my scheduled jobs reported or where they failed. These jobs used to ping chat
// (stopped 2026-10-16, one daily sitrep goes there now). A report clears itself 48 hours after
// the run and needs no acknowledgement. Only a failure does, and only failures count in the badge. A job whose latest run failed stays here and has a high
// item on Now until a later run succeeds (alerts.py raises and closes it on the data refresh).
// Same day-grouped disclosure log as Completed (cmp- recipe in Action.css).
import type { SegmentedOption, StatusTone } from '@kit'
import { Badge, Button, Card, CardHead, EmptyState, IconChevronRight, Pill, Segmented, Skeleton, StatTile, Toolbar, useToast } from '@kit'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Markdown } from '../components/Markdown'
import { LoadError } from '../components/StateBlocks'
import type { OpsAlert } from '../lib/data'
import { postAlertsAck, useAlerts, useBadges, useNow } from '../lib/data'

type View = 'new' | 'reports' | 'acked'

const dayKey = (iso: string) => new Date(iso).toLocaleDateString('en-CA')
const dayLabel = (key: string) => {
  const today = new Date().toLocaleDateString('en-CA')
  const y = new Date(Date.now() - 86_400_000).toLocaleDateString('en-CA')
  if (key === today) return 'Today'
  if (key === y) return 'Yesterday'
  return new Date(`${key}T12:00:00`).toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' })
}
const timeOf = (iso: string) => new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })

function inHours(iso: string, now: number) {
  const h = Math.max(0, Math.round((Date.parse(iso) - now) / 3_600_000))
  return h < 1 ? 'within the hour' : h === 1 ? 'in 1 hour' : `in ${h} hours`
}

function kindTag(a: OpsAlert): { tone: StatusTone; label: string } {
  if (a.open) return { tone: 'danger', label: 'Failing' }
  if (a.kind === 'failure') return { tone: 'warning', label: 'Failed' }
  return { tone: 'info', label: 'Report' }
}

export default function Alerts() {
  const { data, error, mutate } = useAlerts()
  const badges = useBadges()
  const { toast } = useToast()
  const navigate = useNavigate()
  const now = useNow(60_000)
  const [view, setView] = useState<View>('new')
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const [busy, setBusy] = useState(false)

  const all = data?.alerts || []
  // Only a failure needs an acknowledgement. A report is information that clears itself in 48 hours.
  const fresh = all.filter((a) => a.needs_ack && !a.acked)
  const reports = all.filter((a) => !a.needs_ack)
  const acked = all.filter((a) => a.needs_ack && a.acked)
  const rows = view === 'new' ? fresh : view === 'reports' ? reports : acked

  const groups: [string, OpsAlert[]][] = []
  for (const a of rows) {
    const k = dayKey(a.at)
    const g = groups[groups.length - 1]
    if (g && g[0] === k) g[1].push(a)
    else groups.push([k, [a]])
  }

  const send = (ids: string[], act: 'ack' | 'unack') => {
    if (!ids.length) return
    setBusy(true)
    const stamp = new Date().toISOString()
    mutate((d) => ({ ...d, alerts: d.alerts.map((a) => (ids.includes(a.id) ? { ...a, acked: act === 'ack' ? stamp : null } : a)) }))
    postAlertsAck(ids, act)
      .then((d) => {
        mutate(() => d)
        badges.mutate((b) => ({ ...b, alerts: d.counts.unacked }))
        if (ids.length > 1) toast('success', `Acknowledged ${ids.length} alerts`)
      })
      .catch((e) => {
        toast('error', act === 'ack' ? 'Could not acknowledge' : 'Could not restore', { description: String(e) })
      })
      .finally(() => {
        setBusy(false)
      })
  }

  const views: SegmentedOption<View>[] = [
    { value: 'new', label: `Needs ack ${fresh.length}`, tip: 'Failures I have not acknowledged. These are the badge count.' },
    {
      value: 'reports',
      label: `Reports ${reports.length}`,
      tip: 'Information from my jobs. No acknowledgement needed, each clears itself 48 hours after the run.',
    },
    { value: 'acked', label: `Acknowledged ${acked.length}`, tip: 'Read and acknowledged, still inside the 48 hour window' },
  ]
  const failing = data?.counts.failing || 0

  return (
    <div className="cmp">
      <div className="cmp-stats kpi-strip">
        <StatTile value={fresh.length} label="need ack" tone={fresh.length ? 'info' : 'accent'} />
        <StatTile value={reports.length} label="reports" />
        <StatTile value={failing} label="failing now" tone={failing ? 'danger' : 'success'} />
        <StatTile value={acked.length} label="acknowledged" />
        <StatTile value={data?.sources || 0} label="jobs watched" hue="violet" />
      </div>

      <Toolbar label="Alerts controls">
        <Segmented label="New or acknowledged" options={views} value={view} onChange={setView} />
        {view === 'new' && fresh.length > 0 && (
          <Button
            size="sm"
            disabled={busy}
            onClick={() =>
              send(
                fresh.map((a) => a.id),
                'ack',
              )
            }
          >
            Acknowledge all
          </Button>
        )}
      </Toolbar>

      {error && !data && (
        <Card>
          <LoadError title="Could not load alerts" error={error} />
        </Card>
      )}
      {!error && !data && (
        <Card>
          <Skeleton variant="lines" count={6} label="Loading alerts" />
        </Card>
      )}
      {data && rows.length === 0 && (
        <Card>
          <EmptyState
            compact
            pose="celebrate"
            title={
              view === 'new'
                ? 'Nothing needs an acknowledgement.'
                : view === 'reports'
                  ? 'No reports in the last 48 hours.'
                  : 'Nothing acknowledged in the last 48 hours.'
            }
            body={view === 'new' ? 'No job has failed and left an alert unread.' : undefined}
          />
        </Card>
      )}

      <div className="cmp-days">
        {groups.map(([k, list]) => (
          <Card as="section" key={k} className="cmp-day" aria-label={dayLabel(k)}>
            <CardHead title={dayLabel(k)} level={3} controls={<Badge>{list.length}</Badge>} />
            <ul className="cmp-list">
              {list.map((a) => {
                const isOpen = !!open[a.id]
                const tag = kindTag(a)
                return (
                  <li key={a.id} className={`cmp-row${isOpen ? ' is-selected' : ''}`}>
                    <button
                      type="button"
                      className="cmp-main"
                      aria-expanded={isOpen}
                      onClick={() => setOpen((o) => ({ ...o, [a.id]: !o[a.id] }))}
                    >
                      <span className="cmp-time">{timeOf(a.at)}</span>
                      <span className="cmp-pri">
                        <Pill tone={tag.tone} dot>
                          {tag.label}
                        </Pill>
                      </span>
                      <span className="cmp-title">{a.name}</span>
                      {a.count > 1 && <Badge data-tip={`Failed ${a.count} runs in a row`}>x{a.count}</Badge>}
                      <span className="cmp-caret" aria-hidden="true">
                        <IconChevronRight size={14} />
                      </span>
                    </button>
                    {isOpen && (
                      <div className="cmp-detail">
                        {a.fmt === 'md' ? <Markdown body={a.body} /> : <pre className="al-pre">{a.body}</pre>}
                        <p className="cmp-faint">
                          {a.open
                            ? 'Stays here until the next run succeeds. It is a high item on Now.'
                            : a.expires
                              ? `Clears itself ${inHours(a.expires, now)}.`
                              : ''}
                        </p>
                        <div className="cmp-btns">
                          {!a.needs_ack ? null : a.acked ? (
                            <Button size="sm" disabled={busy} onClick={() => send([a.id], 'unack')}>
                              Move back to new
                            </Button>
                          ) : (
                            <Button size="sm" variant="primary" disabled={busy} onClick={() => send([a.id], 'ack')}>
                              Acknowledge
                            </Button>
                          )}
                          {a.open && (
                            <Button size="sm" onClick={() => navigate('/action')}>
                              Open on Now
                            </Button>
                          )}
                        </div>
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          </Card>
        ))}
      </div>
    </div>
  )
}
