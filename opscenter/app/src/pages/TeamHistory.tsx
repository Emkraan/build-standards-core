import type { SegmentedOption, TableColumn } from '@kit'
import { Badge, Card, CardHead, EmptyState, Input, Segmented, Skeleton, Table, Toolbar } from '@kit'
import { useMemo, useState } from 'react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { HistoryMaster } from '../lib/data'
import { useData } from '../lib/data'
import { ChartLegend, ChartTip, usePeopleChart } from './people/chart'
import './Team.css'

const SERIES: SegmentedOption<string>[] = [
  { value: 'completion_pct', label: 'Completion %' },
  { value: 'points_delivered', label: 'Points delivered' },
  { value: 'done', label: 'Tickets done' },
  { value: 'carryover', label: 'Carryover' },
  { value: 'mid_cycle_intake', label: 'Mid-cycle intake' },
]

interface LedgerRow {
  id: string
  period: string
  month: string
  sprints: string
  name: string
  completion: number
  delivered: number
  committed: number
  done: number
  assigned: number
  carryover: number
  intake: number
}

const LEDGER_COLS: TableColumn<LedgerRow>[] = [
  {
    key: 'period',
    header: 'Period',
    render: (r) => (
      <span className="th-period">
        <b>{r.period}</b>
        <small>{r.month}</small>
      </span>
    ),
  },
  { key: 'sprints', header: 'Sprints' },
  { key: 'name', header: 'Engineer' },
  {
    key: 'completion',
    header: 'Completion',
    numeric: true,
    render: (r) => (
      <Badge tone={r.completion >= 90 ? 'success' : r.completion >= 75 ? 'warning' : 'danger'} dot>
        {r.completion}%
      </Badge>
    ),
  },
  { key: 'delivered', header: 'Pts deliv.', numeric: true, render: (r) => `${r.delivered}/${r.committed}` },
  { key: 'done', header: 'Done', numeric: true, render: (r) => `${r.done}/${r.assigned}` },
  { key: 'carryover', header: 'Carry', numeric: true },
  { key: 'intake', header: 'Intake', numeric: true },
]

export default function TeamHistory() {
  const { data, error } = useData<HistoryMaster>('history-master.json')
  const [metric, setMetric] = useState('completion_pct')
  const [year, setYear] = useState<string>('all')
  const [q, setQ] = useState('')
  const chart = usePeopleChart()

  const { runs, years, engineers, chartData } = useMemo(() => {
    if (!data) return { runs: [], years: [], engineers: [], chartData: [] }
    let runs = [...data.runs].sort((a, b) => (a.period_end || '').localeCompare(b.period_end || ''))
    const years = Array.from(new Set(runs.map((r) => r.year))).sort()
    if (year !== 'all') runs = runs.filter((r) => r.year === year)
    const engineers = Array.from(new Set(runs.flatMap((r) => r.engineers.map((e) => e.name)))).sort()
    // One point per sprint. The two earlier four-week reads overlap their sprints,
    // so the chart skips them (the ledger below still lists them).
    const perSprint = runs.filter((r) => (r.sprint_ids || []).length === 1)
    const chartData = (perSprint.length ? perSprint : runs).map((r) => {
      const row: Record<string, string | number> = { label: r.sprints.join('+'), period: r.period_end }
      r.engineers.forEach((e) => {
        row[e.name] = (e as unknown as Record<string, number>)[metric]
      })
      return row
    })
    return { runs, years, engineers, chartData }
  }, [data, metric, year])

  const ledger = useMemo<LedgerRow[]>(
    () =>
      runs.flatMap((r) =>
        r.engineers.map((e) => ({
          id: `${r.run_key}-${e.name}`,
          period: r.period_end,
          month: r.month,
          sprints: r.sprints.join(', '),
          name: e.name,
          completion: e.completion_pct,
          delivered: e.points_delivered,
          committed: e.points_committed,
          done: e.done,
          assigned: e.assigned,
          carryover: e.carryover,
          intake: e.mid_cycle_intake,
        })),
      ),
    [runs],
  )

  if (error) return <EmptyState title="Could not load review history." />
  if (!data) return <Skeleton variant="card" count={2} label="Loading review history" />

  const single = runs.length < 2
  const label = SERIES.find((s) => s.value === metric)?.label
  const color = (i: number) => chart.t.series[i % chart.t.series.length]

  return (
    <div className="th pp-table">
      <p className="pp-lede">
        Month-over-month and year-over-year record for performance reviews &middot; {data.run_count} assessment run(s) on file
      </p>

      <Toolbar label="Trend filters">
        <Segmented label="Metric" options={SERIES} value={metric} onChange={setMetric} />
        <Segmented
          label="Year"
          options={[{ value: 'all', label: 'All' }, ...years.map((y) => ({ value: y, label: y }))]}
          value={year}
          onChange={setYear}
        />
      </Toolbar>

      <Card>
        <CardHead
          title={`Trend: ${label}`}
          subtitle={
            single
              ? 'One run recorded so far. The trend line fills in as each sprint closes.'
              : `${runs.length} runs, one line per engineer`
          }
        />
        <ResponsiveContainer width="100%" height={320}>
          <LineChart data={chartData} margin={{ top: 12, right: 20, left: -10, bottom: 0 }}>
            <CartesianGrid stroke={chart.t.grid} strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="label" tick={chart.axisTick} axisLine={{ stroke: chart.t.grid }} tickLine={false} />
            <YAxis tick={chart.axisTick} axisLine={false} tickLine={false} />
            <Tooltip content={<ChartTip />} cursor={{ stroke: chart.t.grid }} />
            {engineers.map((e, i) => (
              <Line key={e} type="monotone" dataKey={e} stroke={color(i)} strokeWidth={2.5} dot={{ r: 4, fill: color(i) }} connectNulls />
            ))}
          </LineChart>
        </ResponsiveContainer>
        <ChartLegend items={engineers.map((e, i) => ({ label: e, color: color(i) }))} />
      </Card>

      <div className="pp-label">Run ledger</div>
      <Card>
        <CardHead
          title="Every assessment run"
          subtitle="One row per engineer per run, newest first"
          controls={
            <Input
              type="search"
              className="tp-filter"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Filter runs"
              aria-label="Filter runs"
            />
          }
        />
        <Table
          caption="Run ledger"
          columns={LEDGER_COLS}
          rows={ledger}
          rowKey={(r) => r.id}
          filter={q}
          defaultSort={{ key: 'period', dir: 'desc' }}
          empty={<EmptyState compact title="No runs recorded for this year" />}
          noMatch={<EmptyState compact title="No matching runs" body="Try a shorter or different filter." />}
        />
      </Card>
    </div>
  )
}
