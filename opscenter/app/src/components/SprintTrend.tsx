// Sprint trend (OC-18): team totals for the last closed sprints and the active one, oldest first. The tracker keeps no
// snapshot of what a sprint committed to at its start, so "Items in sprint" is what the sprint holds now and "Done" is
// what the tracker shows as done today; a source that can say what was committed at the start sends `committed` and the
// card shows that column too. Carried is the items that also sit in a later sprint. The card is hidden when the tracker
// has no sprint source (a 404 or 501 on /api/jira/sprint-trend) and says so when the read fails.
import type { TableColumn } from '@kit'
import { Badge, Card, CardHead, ProgressBar, Table } from '@kit'
import type { SprintTrendRow } from '../lib/data'
import { useSprintTrend } from '../lib/data'
import { fmtDate } from '../pages/Backlog'
import { LoadError } from './StateBlocks'

const pts = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1))
const span = (r: { start: string; end: string }) => [r.start && fmtDate(r.start), r.end && fmtDate(r.end)].filter(Boolean).join(' to ') || '-'

function columns(withCommitted: boolean): TableColumn<SprintTrendRow>[] {
  return [
    {
      key: 'name',
      header: 'Sprint',
      value: (r) => r.name,
      render: (r) => (
        <span>
          {r.name || `Sprint ${r.id}`} {r.active && <Badge tone="info">active</Badge>}
        </span>
      ),
    },
    { key: 'span', header: 'Dates', value: (r) => r.start, render: (r) => span(r) },
    ...(withCommitted
      ? [{ key: 'committed', header: 'Committed', numeric: true, value: (r: SprintTrendRow) => r.committed ?? 0, render: (r: SprintTrendRow) => r.committed ?? '-' }]
      : []),
    { key: 'items', header: 'Items in sprint', numeric: true, value: (r) => r.items },
    { key: 'done', header: 'Done', numeric: true, value: (r) => r.done },
    { key: 'carried', header: 'Carried on', numeric: true, value: (r) => r.carried },
    {
      key: 'points',
      header: 'Points done',
      numeric: true,
      value: (r) => r.points_done,
      render: (r) => `${pts(r.points_done)} of ${pts(r.points)}`,
    },
    {
      key: 'bar',
      header: 'Items done',
      sortable: false,
      render: (r) => <ProgressBar value={r.done} max={Math.max(r.items, 1)} tone="info" label={`${r.name || `Sprint ${r.id}`}: ${r.done} of ${r.items} items done`} />,
    },
  ]
}

export default function SprintTrend() {
  const { data, error } = useSprintTrend()
  if (!data) return error ? <LoadError title="The sprint trend did not load" error={error} /> : null
  if (!data.available || data.sprints.length === 0) return null
  return (
    <Card>
      <CardHead
        title="Sprint trend"
        subtitle="The last closed sprints and the active one. Done is what the tracker shows today, not a snapshot from the start of the sprint."
      />
      <Table
        caption="Sprint trend"
        columns={columns(data.sprints.some((r) => r.committed !== undefined))}
        rows={data.sprints}
        rowKey={(r) => String(r.id)}
        defaultSort={null}
      />
    </Card>
  )
}
