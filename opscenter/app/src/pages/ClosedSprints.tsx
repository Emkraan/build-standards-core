// Jira hub > Closed sprints (OC-18): the recent closed sprints, and a read only view of one of them. The list comes from
// /api/jira/sprints and the view from /api/jira/sprint?id=, which the server serves only for an id in that list. Nothing
// here changes a ticket: a closed sprint is history. The tab is hidden when the tracker has no sprint source.
import type { StatusTone, TableColumn } from '@kit'
import { Badge, Card, CardHead, EmptyState, Pill, Segmented, Skeleton, StatTile, Table } from '@kit'
import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { LoadError } from '../components/StateBlocks'
import type { ClosedSprint, SprintData, SprintItem } from '../lib/data'
import { fetchClosedSprint, useClosedSprints } from '../lib/data'
import { fmtDate } from './Backlog'

const CAT_LABEL: Record<string, string> = { done: 'Done', indeterminate: 'In progress', new: 'To do' }
const CAT_TONE: Record<string, StatusTone> = { done: 'success', indeterminate: 'info', new: 'neutral' }
const errText = (e: unknown) => (e instanceof Error ? e.message : String(e))
const span = (s: { start: string; end: string }) => [s.start && fmtDate(s.start), s.end && fmtDate(s.end)].filter(Boolean).join(' to ') || '-'

const LIST_COLUMNS: TableColumn<ClosedSprint>[] = [
  {
    key: 'name',
    header: 'Sprint',
    value: (s) => s.name,
    render: (s) => <Link to={`/jira/closed/${s.id}`}>{s.name || `Sprint ${s.id}`}</Link>,
  },
  { key: 'span', header: 'Dates', value: (s) => s.end || s.start, render: (s) => span(s) },
  { key: 'complete', header: 'Closed', value: (s) => s.complete, render: (s) => (s.complete ? fmtDate(s.complete) : '-') },
]

const ITEM_COLUMNS: TableColumn<SprintItem>[] = [
  {
    key: 'key',
    header: 'Ticket',
    value: (i) => i.key,
    render: (i) => (
      <a href={i.url} target="_blank" rel="noreferrer">
        {i.key}
      </a>
    ),
  },
  { key: 'summary', header: 'Summary', value: (i) => i.summary },
  { key: 'assignee', header: 'Assignee', value: (i) => i.assignee || '', render: (i) => i.assignee || 'Unassigned' },
  {
    key: 'status',
    header: 'Status',
    value: (i) => i.status_category,
    render: (i) => <Pill tone={CAT_TONE[i.status_category] ?? 'neutral'}>{i.status || CAT_LABEL[i.status_category] || '-'}</Pill>,
  },
  { key: 'points', header: 'Points', numeric: true, value: (i) => i.points ?? 0, render: (i) => (i.points === null ? '-' : i.points) },
]

type Scope = 'team' | 'mine'

function OneSprint({ id }: { id: number }) {
  const [data, setData] = useState<SprintData | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [scope, setScope] = useState<Scope>('team')
  useEffect(() => {
    let live = true
    setData(null)
    setErr(null)
    fetchClosedSprint(id)
      .then((d) => live && setData(d))
      .catch((e) => live && setErr(errText(e)))
    return () => {
      live = false
    }
  }, [id])
  const rows = useMemo(() => (data ? data.items.filter((i) => scope === 'team' || i.mine) : []), [data, scope])
  if (err) return <LoadError title="This sprint did not load" error={err} hint={<Link to="/jira/closed">Back to the closed sprints</Link>} />
  if (!data) return <Skeleton variant="lines" count={6} label="Loading the sprint" />
  const done = rows.filter((i) => i.status_category === 'done').length
  const pointsDone = rows.filter((i) => i.status_category === 'done').reduce((n, i) => n + (i.points ?? 0), 0)
  const points = rows.reduce((n, i) => n + (i.points ?? 0), 0)
  return (
    <div className="jr-stack">
      <div>
        <Link to="/jira/closed">All closed sprints</Link>
      </div>
      <p className="jr-lede">A closed sprint is read only: nothing here changes a ticket.</p>
      <Card>
        <CardHead
          title={data.sprint?.name || `Sprint ${id}`}
          subtitle={data.sprint ? span(data.sprint) : undefined}
          controls={
            <Segmented
              label="Whose items"
              value={scope}
              onChange={(v) => setScope(v as Scope)}
              options={[
                { value: 'team', label: 'Team' },
                { value: 'mine', label: 'Mine' },
              ]}
            />
          }
        />
        <div className="jr-stats">
          <StatTile label="Items" value={rows.length} />
          <StatTile label="Done" value={done} tone="success" />
          <StatTile label="Not done" value={rows.length - done} />
          <StatTile label="Points done" value={`${pointsDone} of ${points}`} />
        </div>
        {rows.length === 0 ? (
          <EmptyState compact pose="idle" title="No items in this view." />
        ) : (
          <Table caption="Items in the closed sprint" columns={ITEM_COLUMNS} rows={rows} rowKey={(i) => i.key} defaultSort={null} />
        )}
      </Card>
    </div>
  )
}

/** The closed sprints tab. `/jira/closed` lists them, `/jira/closed/<id>` opens one. */
export default function ClosedSprints() {
  const { sprintId } = useParams()
  const { data, error } = useClosedSprints()
  if (!data) return error ? <LoadError title="The closed sprints did not load" error={error} /> : <Skeleton variant="lines" count={6} label="Loading the closed sprints" />
  if (!data.available) return <EmptyState compact title="No sprint source is configured." />
  if (sprintId !== undefined) {
    const id = Number(sprintId)
    if (!Number.isInteger(id) || !data.sprints.some((s) => s.id === id)) {
      return <LoadError title="That is not one of the recent closed sprints" hint={<Link to="/jira/closed">Back to the closed sprints</Link>} />
    }
    return <OneSprint id={id} />
  }
  return (
    <div className="jr-stack">
      <p className="jr-lede">
        The recent closed sprints, newest first. Open one to read what it held. <Badge tone="neutral">read only</Badge>
      </p>
      <Card>
        <CardHead title="Closed sprints" count={data.sprints.length} />
        <Table caption="Closed sprints" columns={LIST_COLUMNS} rows={data.sprints} rowKey={(s) => String(s.id)} defaultSort={null} />
      </Card>
    </div>
  )
}
