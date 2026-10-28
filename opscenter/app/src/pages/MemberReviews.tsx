// Member reviews: one overall read per person, built from every datapoint on
// record (engineer notes, every assessment run, decisions, unplanned work and
// risk entries) across their full history. Not scoped to any sprint window;
// the per-sprint numbers live on the This cycle and Trends tabs.
//
import type { StatTone } from '@kit'
import { Badge, Card, CardHead, EmptyState, IconChevronRight, Skeleton, StatTile } from '@kit'
import { useMemo } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Tkt } from '../components/ui'
import type { HistoryEngineer, HistoryMaster, HistoryRun, MemberProfile, MemberProfiles } from '../lib/data'
import { useData, useYearlyReviews } from '../lib/data'
import { PersonCard, PersonRail } from './people/PersonCard'
import './MemberReviews.css'

const TICKET = /\b((?:[A-Z][A-Z0-9]+)-\d{2,6})\b/g

// Ticket keys become Jira links; everything else stays plain text.
export function Linked({ text }: { text: string }) {
  const parts = text.split(TICKET)
  return <>{parts.map((p, i) => (i % 2 === 1 ? <Tkt key={i} id={p} /> : <span key={i}>{p}</span>))}</>
}

export interface PersonWindow {
  run: HistoryRun
  e: HistoryEngineer
}

// Still exported for the Yearly review tab, which works per window.
export function windowsFor(h: HistoryMaster | null, name: string): PersonWindow[] {
  if (!h) return []
  const out: PersonWindow[] = []
  for (const run of h.runs) {
    const e = run.engineers.find((x) => x.name === name)
    if (e) out.push({ run, e })
  }
  return out.sort((a, b) => (a.run.period_end || '').localeCompare(b.run.period_end || ''))
}

export function allPeople(h: HistoryMaster | null): string[] {
  const s = new Set<string>()
  h?.runs.forEach((r) => {
    r.engineers.forEach((e) => {
      s.add(e.name)
    })
  })
  return [...s].sort()
}

type BadgeTone = 'success' | 'warning' | 'danger' | 'neutral'
const TRAJ: Record<MemberProfile['trajectory']['direction'], { label: string; tone: BadgeTone; stat: StatTone; glyph: string }> = {
  rising: { label: 'Rising', tone: 'success', stat: 'success', glyph: '\u2197' },
  steady: { label: 'Steady', tone: 'success', stat: 'success', glyph: '\u2192' },
  mixed: { label: 'Mixed', tone: 'warning', stat: 'warning', glyph: '\u2194' },
  declining: { label: 'Declining', tone: 'danger', stat: 'danger', glyph: '\u2198' },
  'too-early': { label: 'Too early', tone: 'neutral', stat: 'info', glyph: '\u2026' },
}

function fmtMonth(iso: string | null | undefined) {
  if (!iso) return '-'
  const d = new Date(iso.length <= 10 ? `${iso}T12:00:00` : iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(undefined, { month: 'short', year: 'numeric' })
}

function monthsSpan(a: string, b: string) {
  const x = new Date(`${a}T12:00:00`)
  const y = new Date(`${b}T12:00:00`)
  if (Number.isNaN(x.getTime()) || Number.isNaN(y.getTime())) return 0
  return Math.max(1, Math.round((y.getTime() - x.getTime()) / (30.44 * 86400000)))
}

function Points({ title, items, hue }: { title: string; items: { title: string; detail: string }[]; hue: 'green' | 'amber' }) {
  if (!items.length) return null
  return (
    <Card tone={hue} className="mr-card">
      <CardHead title={title} level={3} subtitle={`${items.length} on record`} />
      <div className="mr-points">
        {items.map((x, i) => (
          <div key={i} className="mr-point">
            <b>{x.title}</b>
            <p>
              <Linked text={x.detail} />
            </p>
          </div>
        ))}
      </div>
    </Card>
  )
}

function Bullets({ title, items, hue }: { title: string; items: string[]; hue?: 'blue' | 'teal' }) {
  if (!items.length) return null
  return (
    <Card tone={hue} className="mr-card">
      <CardHead title={title} level={3} />
      <ul className="pp-list">
        {items.map((x, i) => (
          <li key={i}>
            <Linked text={x} />
          </li>
        ))}
      </ul>
    </Card>
  )
}

export default function MemberReviews() {
  const { data: prof, error } = useData<MemberProfiles>('member-profiles.json')
  const { data: hist } = useData<HistoryMaster>('history-master.json')
  const { data: yr } = useYearlyReviews()
  const [params, setParams] = useSearchParams()

  const people = useMemo(() => {
    const s = new Set<string>(Object.keys(prof?.profiles || {}))
    allPeople(hist).forEach((n) => {
      s.add(n)
    })
    return [...s].sort()
  }, [prof, hist])

  if (error && !hist) return <EmptyState title="Could not load the member reviews." />
  if (!prof && !hist) return <Skeleton variant="card" count={3} label="Loading reviews" />
  if (!people.length) return <EmptyState title="No one has been reviewed yet." />

  const want = (params.get('p') || '').toLowerCase()
  const name = people.find((n) => n.toLowerCase() === want || n.split(' ')[0].toLowerCase() === want) || people[0]
  const p = prof?.profiles?.[name]
  const first = name.split(' ')[0]
  const years = [
    ...new Set<number>([
      ...windowsFor(hist, name).map((w) => Number(w.run.year)),
      ...Object.keys(yr?.reviews || {})
        .filter((y) => yr?.reviews?.[y]?.[name])
        .map(Number),
      new Date().getFullYear(),
    ]),
  ].sort((a, b) => b - a)
  const traj = p ? TRAJ[p.trajectory.direction] || TRAJ.mixed : null

  return (
    <div className="rv mr">
      <p className="pp-lede">
        My overall read of each person from everything on record: engineer notes, every assessment run, decisions, unplanned work and risk
        entries, across their full history. Sprint numbers live on This cycle and Trends.
      </p>

      <PersonRail label="Pick a person">
        {people.map((n) => {
          const q = prof?.profiles?.[n]
          const t = q ? TRAJ[q.trajectory.direction] || TRAJ.mixed : null
          return (
            <PersonCard
              key={n}
              name={n}
              selected={n === name}
              onPick={() =>
                setParams((prev) => {
                  const next = new URLSearchParams(prev)
                  next.set('p', n.split(' ')[0].toLowerCase())
                  return next
                })
              }
              sub={q ? `${q.evidence.datapoints} datapoints since ${fmtMonth(q.evidence.first_seen)}` : 'Not profiled yet'}
              aside={
                t ? (
                  <Badge tone={t.tone} data-tip={`Trajectory: ${t.label}`} aria-label={`Trajectory: ${t.label}`}>
                    {t.glyph}
                  </Badge>
                ) : undefined
              }
            />
          )
        })}
      </PersonRail>

      {!p || !traj ? (
        <Card>
          <EmptyState title={`No overall review for ${first} yet.`} body="It is written on the next monthly assessment." />
        </Card>
      ) : (
        <>
          <Card elevated className="mr-hero">
            <div className="mr-hero-main">
              <div className="page-eyebrow">Overall review &middot; full history</div>
              <h2 className="mr-name">{p.name}</h2>
              <div className="mr-role">{p.role}</div>
              <p className="mr-headline">{p.headline}</p>
              <p className="mr-summary">
                <Linked text={p.summary} />
              </p>
            </div>
            <div className="mr-hero-stats">
              <StatTile label="Datapoints drawn on" value={p.evidence.datapoints} tone="info" />
              <StatTile
                label="Months on record"
                value={monthsSpan(p.evidence.first_seen, p.evidence.last_seen)}
                tone="accent"
                hint={`${fmtMonth(p.evidence.first_seen)} to ${fmtMonth(p.evidence.last_seen)}`}
              />
              <StatTile label="Trajectory" value={`${traj.glyph} ${traj.label}`} tone={traj.stat} />
            </div>
          </Card>

          <Card className="mr-card">
            <CardHead title={`How ${first} has changed`} level={3} />
            <p className="mr-text">
              <Linked text={p.trajectory.detail} />
            </p>
          </Card>

          <div className="pp-grid-2 mr-row">
            <Points title="Consistent strengths" items={p.strengths} hue="green" />
            <Points title="Where to grow" items={p.growth} hue="amber" />
          </div>

          <div className="pp-grid-3 mr-row">
            <Bullets title="How they work" items={p.working_style} />
            <Bullets title={`What ${first} needs from me`} items={p.needs_from_me} hue="blue" />
            <Bullets title="Development focus" items={p.development_focus} hue="teal" />
          </div>

          <div className="pp-label">Yearly reviews</div>
          <div className="mr-years">
            {years.map((y) => {
              const r = yr?.reviews?.[y]?.[name]
              const label = r ? (r.status === 'final' ? 'Final' : 'Draft') : 'Not started'
              return (
                <Link key={y} className="card card-interactive mr-year" to={`/team/yearly?year=${y}&p=${first.toLowerCase()}`}>
                  <b>{y}</b>
                  <Badge tone={r?.status === 'final' ? 'success' : r ? 'warning' : 'neutral'} dot>
                    {label}
                  </Badge>
                  {r?.rating && <span className="mr-year-rating">{yr?.ratings?.[r.rating] || r.rating}</span>}
                  <span className="mr-year-go">
                    Open <IconChevronRight size={14} />
                  </span>
                </Link>
              )
            })}
          </div>
          <p className="pp-foot">
            Drawn from {p.evidence.sources.join(', ')}. Rebuilt on each monthly assessment. Last rebuilt{' '}
            {prof?.updated_utc ? new Date(prof.updated_utc).toLocaleDateString() : '-'}.
          </p>
        </>
      )}
    </div>
  )
}
