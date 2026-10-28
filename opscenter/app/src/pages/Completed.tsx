// Completed: a readable log of what I closed out of the Action Center.
// Grouped by day, one compact row per item (priority, title, owner, Hermes
// flag); click a row to expand the why / action / outcome / tickets. A
// Dismissed view shows what I ignored or snoozed so nothing silently vanishes.
// Item text comes from the snapshot stored at handle time (server.py), with
// the live synthesis as an overlay, so rotated-out items still read properly.
// Built on the kit: StatTile hero numbers, Segmented view switch, Toolbar filter, day Cards with a
// disclosure row each (the log is chronological, so it is a list, not a sortable table).
import type { SegmentedOption, StatusTone } from '@kit'
import {
  Badge,
  Button,
  Card,
  CardHead,
  EmptyState,
  IconChevronRight,
  IconSearch,
  Input,
  Pill,
  Segmented,
  Skeleton,
  StatTile,
  Toolbar,
  useToast,
} from '@kit'
import { useEffect, useMemo, useState } from 'react'
import { LinkButton, LoadError } from '../components/StateBlocks'
import { Tkt } from '../components/ui'
import type { HandledEntry, TackleSession } from '../lib/data'
import { fetchHandled, fetchTackle, hermesSessionUrl, onLiveTick, postHandled, useData } from '../lib/data'

interface Item {
  fp: string
  priority?: string
  title?: string
  why?: string
  action?: string
  owner?: string
  refs?: string[]
}

type View = 'completed' | 'dismissed'

const TONE = (p = ''): StatusTone => (/critical/i.test(p) ? 'danger' : /high/i.test(p) ? 'warning' : /med/i.test(p) ? 'info' : 'neutral')

const TKT_RE = /^([A-Z][A-Z0-9]+)-\d+$/i

const dayKey = (iso: string) => {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? 'Unknown' : d.toLocaleDateString('en-CA')
}
const dayLabel = (key: string) => {
  const today = new Date().toLocaleDateString('en-CA')
  const y = new Date(Date.now() - 86_400_000).toLocaleDateString('en-CA')
  if (key === today) return 'Today'
  if (key === y) return 'Yesterday'
  const d = new Date(`${key}T12:00:00`)
  return Number.isNaN(d.getTime()) ? key : d.toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' })
}
const timeOf = (iso: string) => {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}
const ACT_LABEL: Record<string, string> = { ignored: 'Ignored', ignored_forever: 'Ignored always', snoozed: 'Snoozed' }

export default function Completed() {
  const { data } = useData<{ items?: Item[] }>('action-center.json')
  const { toast } = useToast()
  const [handled, setHandled] = useState<Record<string, HandledEntry> | null>(null)
  const [tackle, setTackle] = useState<Record<string, TackleSession>>({})
  const [err, setErr] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const [view, setView] = useState<View>('completed')
  const [open, setOpen] = useState<Record<string, boolean>>({})

  useEffect(() => {
    const pull = () => {
      fetchHandled()
        .then((h) => {
          setHandled(h)
          setErr(null)
        })
        .catch((e) => setErr(String(e)))
      fetchTackle()
        .then(setTackle)
        .catch(() => {})
    }
    const stop = onLiveTick(pull, 20_000)
    pull()
    return stop
  }, [])

  const all = useMemo(() => {
    const live = new Map((data?.items || []).map((it) => [it.fp, it]))
    return Object.entries(handled || {}).map(([fp, h]) => ({
      fp,
      h,
      it: { fp, ...(h.item || {}), ...(live.get(fp) || {}) } as Item,
    }))
  }, [handled, data])

  const completed = all.filter((r) => r.h.act === 'resolved')
  const dismissed = all.filter((r) => r.h.act !== 'resolved')

  const weekAgo = new Date(Date.now() - 7 * 86_400_000).toISOString()
  const thisWeek = completed.filter((r) => r.h.at >= weekAgo).length
  const viaHermes = completed.filter((r) => r.h.via === 'hermes-session' || r.h.session_id || tackle[r.fp]?.session_id).length
  const highClosed = completed.filter((r) => /critical|high/i.test(r.it.priority || '')).length

  const rows = (view === 'completed' ? completed : dismissed)
    .filter(({ it, h }) => {
      if (!q.trim()) return true
      const hay = `${it.title} ${it.why} ${it.action} ${it.owner} ${(it.refs || []).join(' ')} ${h.summary || ''}`.toLowerCase()
      return q
        .toLowerCase()
        .split(/\s+/)
        .every((t) => hay.includes(t))
    })
    .sort((a, b) => b.h.at.localeCompare(a.h.at))

  const groups: [string, typeof rows][] = []
  for (const r of rows) {
    const k = dayKey(r.h.at)
    const g = groups[groups.length - 1]
    if (g && g[0] === k) g[1].push(r)
    else groups.push([k, [r]])
  }

  const reopen = (fp: string, title?: string) => {
    setHandled((prev) => {
      const next = { ...(prev || {}) }
      delete next[fp]
      return next
    })
    postHandled({ fp, act: 'restore' })
      .then(() => toast('success', 'Reopened', { description: `${title || fp} is back on Now.` }))
      .catch((e) => toast('error', 'Could not reopen', { description: String(e) }))
  }

  const views: SegmentedOption<View>[] = [
    { value: 'completed', label: `Completed ${completed.length}` },
    { value: 'dismissed', label: `Dismissed ${dismissed.length}`, tip: 'Ignored, ignored always or snoozed' },
  ]

  return (
    <div className="cmp">
      <div className="cmp-stats kpi-strip">
        <StatTile value={completed.length} label="completed" tone="success" />
        <StatTile value={thisWeek} label="last 7 days" tone="info" />
        <StatTile value={highClosed} label="critical / high" tone={highClosed ? 'warning' : 'accent'} />
        <StatTile value={viaHermes} label="via Hermes" hue="violet" />
      </div>

      <Toolbar label="Completed log controls">
        <Segmented label="Completed or dismissed" options={views} value={view} onChange={setView} />
        <Input
          type="search"
          className="cmp-filter"
          aria-label="Filter the log"
          placeholder="Filter by title, owner, ticket..."
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </Toolbar>

      {err && (
        <Card>
          <LoadError title="Could not load" error={err} />
        </Card>
      )}
      {!err && handled === null && (
        <Card>
          <Skeleton variant="lines" count={6} label="Loading the completed log" />
        </Card>
      )}
      {handled !== null && rows.length === 0 && (
        <Card>
          {q ? (
            <EmptyState compact icon={<IconSearch />} title="Nothing matches." body="Try a shorter or different filter." />
          ) : (
            <EmptyState
              compact
              pose={view === 'completed' ? 'shrug' : 'celebrate'}
              title={view === 'completed' ? 'Nothing completed yet.' : 'Nothing dismissed.'}
            />
          )}
        </Card>
      )}

      <div className="cmp-days">
        {groups.map(([k, list]) => (
          <Card as="section" key={k} className="cmp-day" aria-label={dayLabel(k)}>
            <CardHead title={dayLabel(k)} level={3} controls={<Badge>{list.length}</Badge>} />
            <ul className="cmp-list">
              {list.map(({ fp, h, it }) => {
                const sid = h.session_id || tackle[fp]?.session_id
                const isOpen = !!open[fp]
                const refs = (it.refs || []).filter(Boolean)
                return (
                  <li key={fp} className={`cmp-row${isOpen ? ' is-selected' : ''}`}>
                    <button
                      type="button"
                      className="cmp-main"
                      aria-expanded={isOpen}
                      onClick={() => setOpen((o) => ({ ...o, [fp]: !o[fp] }))}
                    >
                      <span className="cmp-time">{timeOf(h.at)}</span>
                      <span className="cmp-pri">
                        {it.priority && (
                          <Pill tone={TONE(it.priority)} dot>
                            {it.priority}
                          </Pill>
                        )}
                      </span>
                      <span className="cmp-title">{it.title || <span className="cmp-faint">Untitled item ({fp})</span>}</span>
                      {view === 'dismissed' && <Badge className="cmp-act">{ACT_LABEL[h.act] || h.act}</Badge>}
                      {sid && (
                        <Badge hue="violet" data-tip="Worked in a Hermes session">
                          Hermes
                        </Badge>
                      )}
                      {it.owner && <Pill className="cmp-owner">{it.owner}</Pill>}
                      <span className="cmp-caret" aria-hidden="true">
                        <IconChevronRight size={14} />
                      </span>
                    </button>
                    {isOpen && (
                      <div className="cmp-detail">
                        {h.summary && (
                          <div className="cmp-outcome tone hue-green">
                            <div className="cmp-label">Outcome</div>
                            <p>{h.summary}</p>
                          </div>
                        )}
                        {it.why && (
                          <div>
                            <div className="cmp-label">Why it was raised</div>
                            <p>{it.why}</p>
                          </div>
                        )}
                        {it.action && (
                          <div>
                            <div className="cmp-label">Recommended action</div>
                            <p>{it.action}</p>
                          </div>
                        )}
                        {refs.length > 0 && (
                          <div className="cmp-refs">
                            {refs.map((r) => (TKT_RE.test(r) ? <Tkt key={r} id={r} /> : <code key={r}>{r}</code>))}
                          </div>
                        )}
                        <div className="cmp-btns">
                          {sid && (
                            <LinkButton variant="primary" href={hermesSessionUrl(sid)} data-tip={sid}>
                              Open Hermes thread
                            </LinkButton>
                          )}
                          <Button size="sm" onClick={() => reopen(fp, it.title)}>
                            Reopen
                          </Button>
                          {h.act === 'snoozed' && h.until && (
                            <span className="cmp-faint">Returns {new Date(h.until).toLocaleDateString()}</span>
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
