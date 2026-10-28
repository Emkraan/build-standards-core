import type { TableColumn } from '@kit'
import { Badge, Card, CardHead, EmptyState, Input, Skeleton, StatTile, Table } from '@kit'
import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Tkt } from '../components/ui'
import type { TeamPerformance as TP } from '../lib/data'
import { useData } from '../lib/data'
import { ChartLegend, ChartTip, usePeopleChart } from './people/chart'
import { PersonCard, PersonRail } from './people/PersonCard'
import './Team.css'

type Tone = 'good' | 'warn' | 'alert'
const TONE = (pct: number): Tone => (pct >= 90 ? 'good' : pct >= 75 ? 'warn' : 'alert')
const STAT_TONE = { good: 'success', warn: 'warning', alert: 'danger' } as const
const TONE_HUE = { good: 'green', warn: 'amber', alert: 'red' } as const

type OpenItem = TP['metrics'][string]['not_done'][number]
type SprintRow = { sprint: string; done: number; assigned: number; delivered: number; committed: number }

const SPRINT_COLS: TableColumn<SprintRow>[] = [
  { key: 'sprint', header: 'Sprint' },
  { key: 'done', header: 'Done', numeric: true, render: (r) => `${r.done}/${r.assigned}` },
  { key: 'delivered', header: 'Points', numeric: true, render: (r) => `${r.delivered}/${r.committed}` },
]

const OPEN_COLS: TableColumn<OpenItem>[] = [
  { key: 'key', header: 'Key', width: '120px', render: (x) => <Tkt id={x.key} /> },
  { key: 'status', header: 'Status', width: '140px' },
  { key: 'priority', header: 'Priority', width: '110px' },
  { key: 'summary', header: 'Summary', render: (x) => <span className="tp-dim">{x.summary}</span> },
]

export default function TeamPerformance() {
  const { data, error } = useData<TP>('team-performance.json')
  const [selected, setSelected] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const chart = usePeopleChart()
  if (error) return <EmptyState title="Could not load team performance data." />
  if (!data) return <Skeleton variant="card" count={3} label="Loading team performance" />

  const meta = Object.values(data.sprint_meta || {})
  const span = meta.length
    ? `${meta.map((m) => m.start).sort()[0]} to ${
        meta
          .map((m) => m.end)
          .sort()
          .slice(-1)[0]
      }`
    : ''
  const names = data.engineers
  const active = selected && names.includes(selected) ? selected : names[0]
  const m = data.metrics[active]
  const first = active.split(' ')[0]
  const n = data.narrative[active] || { verdict: '', strengths: [], watch: [], blocked_on_me: [] }
  const acts = data.action_items[active] || []
  const tone = TONE(m.completion_pct)

  const sprintRows: SprintRow[] = Object.entries(m.per_sprint).map(([sprint, s]) => ({
    sprint,
    done: s.done,
    assigned: s.assigned,
    delivered: s.points_delivered,
    committed: s.points_committed,
  }))
  const perSprint = sprintRows.map((s) => ({ sprint: s.sprint, Done: s.done, Open: s.assigned - s.done }))
  const doneColor = chart.t.status.completed
  const openColor = chart.t.status.notStarted

  return (
    <div className="tp pp-table">
      <p className="pp-lede">
        {data.sprints.join(' + ')} &middot; {span} &middot; synthesized {(data.generated_utc || '').slice(0, 10)}
      </p>

      {data.team_summary && (
        <Card className="tp-read">
          <CardHead title="Team read" />
          <p className="tp-read-text">{data.team_summary}</p>
        </Card>
      )}

      <div className="pp-label">Engineers</div>
      <PersonRail label="Pick an engineer">
        {names.map((name) => {
          const em = data.metrics[name]
          const t = TONE(em.completion_pct)
          return (
            <PersonCard
              key={name}
              name={name}
              selected={active === name}
              onPick={() => setSelected(name)}
              sub={`${em.done}/${em.assigned} done`}
              aside={
                <Badge tone={STAT_TONE[t]} dot>
                  {em.completion_pct}%
                </Badge>
              }
            />
          )
        })}
      </PersonRail>

      <div className="stat-grid kpi-strip pp-stats">
        <StatTile
          label={`${first}: completion`}
          value={`${m.completion_pct}%`}
          tone={STAT_TONE[tone]}
          hint={`${m.done} of ${m.assigned} done`}
        />
        <StatTile
          label="Points delivered"
          value={`${m.points_delivered}/${m.points_committed}`}
          tone="info"
          hint="delivered of committed"
        />
        <StatTile
          label="High/Highest"
          value={`${m.high_priority.done}/${m.high_priority.assigned}`}
          tone="accent"
          hint="done of assigned"
        />
        <StatTile
          label="Open"
          value={m.not_done.length}
          tone={m.not_done.length ? 'warning' : 'success'}
          hint={`Carryover ${m.carryover.length}`}
        />
      </div>

      <div className="tp-main">
        <Card tone={TONE_HUE[tone]}>
          <CardHead title={active} subtitle="This cycle, sprint by sprint" />
          {n.verdict && <p className="tp-verdict">{n.verdict}</p>}
          <Table caption={`${first}: sprint by sprint`} columns={SPRINT_COLS} rows={sprintRows} rowKey={(r) => r.sprint} sortable={false} />
          <div className="tp-strip">
            <span>
              Total{' '}
              <b>
                {m.done}/{m.assigned}
              </b>{' '}
              done,{' '}
              <b>
                {m.points_delivered}/{m.points_committed}
              </b>{' '}
              points
            </span>
            <span>
              Mid-cycle intake <b>{m.mid_cycle_intake}</b>
            </span>
            <span>
              Median lead (fresh) <b>{m.lead_time.fresh_median_days ?? '-'}d</b>
            </span>
          </div>
          {m.lead_time.aged_backlog_cleared.length > 0 && (
            <p className="tp-note">
              Cleared aged backlog: {m.lead_time.aged_backlog_cleared.map((a) => `${a.key} (${Math.round(a.lead_days)}d)`).join(', ')}
            </p>
          )}
        </Card>

        <Card>
          <CardHead title="Throughput by sprint" subtitle="Done and still open, per sprint" />
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={perSprint} margin={{ top: 10, right: 10, left: -18, bottom: 0 }}>
              <CartesianGrid stroke={chart.t.grid} strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="sprint" tick={chart.axisTick} axisLine={{ stroke: chart.t.grid }} tickLine={false} />
              <YAxis tick={chart.axisTick} axisLine={false} tickLine={false} allowDecimals={false} />
              <Tooltip content={<ChartTip />} cursor={{ fill: chart.t.grid, fillOpacity: 0.35 }} />
              <Bar dataKey="Done" stackId="a" fill={doneColor} />
              <Bar dataKey="Open" stackId="a" fill={openColor} radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
          <ChartLegend
            items={[
              { label: 'Done', color: doneColor },
              { label: 'Open', color: openColor },
            ]}
          />
        </Card>
      </div>

      <div className="pp-grid-3 tp-bullets">
        <Bullets title="Strengths" items={n.strengths} hue="green" />
        <Bullets title="Watch" items={n.watch} hue="amber" />
        <Bullets title="Blocked on me" items={n.blocked_on_me} hue="blue" />
      </div>

      {acts.length > 0 && (
        <>
          <div className="pp-label">Action items for {first}</div>
          <div className="pp-grid-2">
            {acts.map((a, i) => (
              <Card key={i} tone={a.priority === 'P1' ? 'red' : undefined}>
                <div className="tp-act-top">
                  <Badge tone={a.priority === 'P1' ? 'danger' : a.priority === 'P2' ? 'warning' : 'success'}>{a.priority}</Badge>
                  <b>{a.title}</b>
                </div>
                <p className="tp-note">{a.why}</p>
                <p className="tp-do">
                  <b>Do:</b> {a.action}
                </p>
              </Card>
            ))}
          </div>
        </>
      )}

      {m.not_done.length > 0 && (
        <>
          <div className="pp-label">{first}'s open items</div>
          <Card>
            <CardHead
              title={`${m.not_done.length} open item${m.not_done.length === 1 ? '' : 's'}`}
              controls={
                <Input
                  type="search"
                  className="tp-filter"
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder="Filter items"
                  aria-label="Filter open items"
                />
              }
            />
            <Table
              caption={`${first}'s open items`}
              columns={OPEN_COLS}
              rows={m.not_done}
              rowKey={(x) => x.key}
              filter={q}
              noMatch={<EmptyState compact title="No matching items" body="Try a shorter or different filter." />}
            />
          </Card>
        </>
      )}
    </div>
  )
}

function Bullets({ title, items, hue }: { title: string; items: string[]; hue: 'green' | 'amber' | 'blue' }) {
  if (!items || items.length === 0) return null
  return (
    <Card tone={hue}>
      <CardHead title={title} level={3} />
      <ul className="pp-list">
        {items.map((it, i) => (
          <li key={i}>{it}</li>
        ))}
      </ul>
    </Card>
  )
}
