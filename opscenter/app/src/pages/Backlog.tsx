// Jira hub > Backlog: my open work that is not in the active sprint, with a
// one-click move into it. Items parked in a future sprint group on top so they
// are not lost (the old query dropped them). Live via useBacklog().
// Kit build: StatTile strip, a Toolbar with refresh, type filter and text filter, and one kit
// Table per group (planned / unplanned) sharing the same column widths.
import { IconKanban } from '../components/icons'
import { StatRow } from '../components/StatRow'
import type { SegmentedOption, StatusTone, TableColumn } from '@kit'
import { Badge, Button, Card, CardHead, EmptyState, Field, IconAlert, IconCheck, IconClock, Input, Modal, Pill, Segmented, Select, Skeleton, StatusDot, Table, Toolbar, useToast } from '@kit'
import { useMemo, useState } from 'react'
import { InHermes } from '../components/InHermes'
import { LoadError } from '../components/StateBlocks'
import { TackleJira } from '../components/TackleJira'
import type { BacklogItem } from '../lib/data'
import { postJiraIssue, postSprintMove, useBacklog, useJiraSprint } from '../lib/data'

export function priorityTone(p: string): StatusTone {
  const s = p.toLowerCase()
  if (s === 'highest' || s === 'high') return 'danger'
  if (s === 'medium') return 'warning'
  if (s === 'low' || s === 'lowest') return 'info'
  return 'neutral'
}

const PRIO_RANK: Record<string, number> = { highest: 0, high: 1, medium: 2, low: 3, lowest: 4 }
export const priorityRank = (p: string) => PRIO_RANK[p.toLowerCase()] ?? 5

export function statusTone(cat: string): StatusTone {
  if (cat === 'indeterminate') return 'warning' // In Progress
  if (cat === 'done') return 'success'
  return 'neutral' // To Do / new
}

export function fmtDate(iso: string): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  } catch {
    return iso.slice(0, 10)
  }
}

export const TOKEN_HINT = (
  <>
    If the Atlassian token has lapsed, refresh it with <code>hermes mcp test atlassian</code> and retry.
  </>
)

export default function Backlog() {
  const { data, error, loading, refresh, mutate } = useBacklog()
  const sprintStore = useJiraSprint()
  const { toast } = useToast()
  const [moving, setMoving] = useState<Record<string, boolean>>({})
  const [typeFilter, setTypeFilter] = useState<string>('all')
  const [q, setQ] = useState('')
  const [adding, setAdding] = useState<{ summary: string; cls: 'planned' | 'bau' | 'unplanned'; busy: boolean } | null>(null)

  const sprint = data?.active_sprint

  const move = async (item: BacklogItem) => {
    setMoving((m) => ({ ...m, [item.key]: true }))
    try {
      const r = await postSprintMove(item.key)
      // Optimistic removal: the search index lags a few seconds behind the
      // write, so an immediate re-query can still list the moved item.
      mutate((d) => ({ ...d, count: Math.max(0, d.count - 1), items: d.items.filter((i) => i.key !== item.key) }))
      toast('success', `${item.key} moved into ${r.moved_to.name}`)
      window.setTimeout(() => sprintStore.refresh(), 5000)
    } catch (e) {
      toast('error', `${item.key}: ${e instanceof Error ? e.message : String(e)}`, { persistent: true })
    } finally {
      setMoving((m) => {
        const n = { ...m }
        delete n[item.key]
        return n
      })
    }
  }

  const types = useMemo(() => (data ? Array.from(new Set(data.items.map((i) => i.issuetype))).sort() : []), [data])
  const shown = useMemo(
    () => (data ? (typeFilter === 'all' ? data.items : data.items.filter((i) => i.issuetype === typeFilter)) : []),
    [data, typeFilter],
  )
  const planned = shown.filter((i) => i.planned_sprint)
  const unplanned = shown.filter((i) => !i.planned_sprint)
  const highCount = data ? data.items.filter((i) => ['high', 'highest'].includes(i.priority.toLowerCase())).length : 0
  const inProgressCount = data ? data.items.filter((i) => i.status_category === 'indeterminate').length : 0

  const typeOptions: SegmentedOption<string>[] = data
    ? [
        { value: 'all', label: `All (${data.count})` },
        ...types.map((t) => ({ value: t, label: `${t} (${data.items.filter((i) => i.issuetype === t).length})` })),
      ]
    : []

  const columns: TableColumn<BacklogItem>[] = [
    {
      key: 'key',
      header: 'Key',
      width: '140px',
      render: (item) => (
        <span className="bk-key">
          <a className="tkt" href={item.url} target="_blank" rel="noreferrer">
            {item.key}
          </a>
          <InHermes ticket={item.key} />
        </span>
      ),
    },
    {
      key: 'summary',
      header: 'Summary',
      value: (item) => `${item.summary} ${item.parent_key ?? ''} ${item.parent_summary ?? ''}`,
      render: (item) => (
        <div className="bk-sum">
          <span className="bk-title">{item.summary}</span>
          {item.parent_key && (
            <span className="bk-sub">
              Epic{' '}
              <a href={`https://atlassian_host/browse/${item.parent_key}`} target="_blank" rel="noreferrer">
                {item.parent_key}
              </a>{' '}
              {item.parent_summary}
            </span>
          )}
        </div>
      ),
    },
    {
      key: 'priority',
      header: 'Priority',
      width: '108px',
      value: (item) => priorityRank(item.priority),
      render: (item) => (
        <Pill tone={priorityTone(item.priority)} dot>
          {item.priority || 'None'}
        </Pill>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      width: '170px',
      render: (item) => (
        <span className="bk-status">
          <Pill tone={statusTone(item.status_category)}>{item.status}</Pill>
          {item.planned_sprint && <Pill tone="info">planned: {item.planned_sprint.name}</Pill>}
        </span>
      ),
    },
    { key: 'issuetype', header: 'Type', width: '96px', render: (item) => <span className="bk-type">{item.issuetype}</span> },
    {
      key: 'points',
      header: 'Pts',
      width: '64px',
      numeric: true,
      value: (item) => item.points,
      render: (item) => (item.points !== null ? item.points : <span className="bk-faint">-</span>),
    },
    {
      key: 'actions',
      header: 'Actions',
      hideHeader: true,
      sortable: false,
      width: '310px',
      render: (item) => (
        <div className="bk-btns">
          <Button size="sm" onClick={() => move(item)} loading={!!moving[item.key]} disabled={!sprint}>
            {moving[item.key] ? 'Moving...' : 'Move To Current Sprint'}
          </Button>
          <TackleJira issueKey={item.key} summary={item.summary} compact />
        </div>
      ),
    },
  ]

  const table = (rows: BacklogItem[], caption: string) => (
    <Table
      className="bk-table"
      caption={caption}
      columns={columns}
      rows={rows}
      rowKey={(r) => r.key}
      filter={q}
      defaultSort={{ key: 'priority', dir: 'asc' }}
      empty={<EmptyState compact title="Nothing in this group." />}
      noMatch={<EmptyState compact title="No matching items" body="Try a shorter or different filter." />}
    />
  )

  return (
    <div className="page">
      <p className="jr-lede">My open work not in the current sprint. Move an item straight into the active sprint.</p>

      <StatRow
        label="Backlog summary"
        stats={[
          { key: 'items', label: 'Backlog items', value: data ? data.count : '-', icon: <IconKanban /> },
          { key: 'high', label: 'High and highest', value: highCount, icon: <IconAlert /> },
          { key: 'prog', label: 'In progress outside the sprint', value: inProgressCount, icon: <IconClock /> },
          { key: 'sprint', label: 'Active sprint', value: sprint ? sprint.name : 'none', icon: <IconCheck /> },
        ]}
      />

      {error && !data && (
        <Card>
          <LoadError title="Could not load the backlog from Jira" error={error} hint={TOKEN_HINT} />
        </Card>
      )}

      {!data && !error && (
        <Card>
          <Skeleton variant="table" count={6} columns={6} label="Loading the backlog from Jira" />
        </Card>
      )}

      {data && data.items.length === 0 && (
        <Card>
          <EmptyState
            pose="celebrate"
            title="Nothing in the backlog."
            body="Everything assigned to me is either closed or already in the current sprint."
          />
        </Card>
      )}

      {data && data.items.length > 0 && (
        <Card>
          <CardHead
            title="My backlog"
            subtitle={`${shown.length}${typeFilter !== 'all' ? ` of ${data.count}` : ''} item${shown.length === 1 ? '' : 's'}`}
            controls={
              sprint ? (
                <Badge tone="success" dot>
                  {sprint.name}
                </Badge>
              ) : (
                <StatusDot tone="danger" label="No active sprint" showLabel />
              )
            }
          />
          <Toolbar
            label="Backlog controls"
            onRefresh={() => refresh()}
            refreshing={loading}
            updatedAt={Date.parse(data.generated_utc) || null}
            actions={
              <Button size="sm" onClick={() => setAdding({ summary: '', cls: 'planned', busy: false })}>
                Add an item
              </Button>
            }
          >
            <Segmented label="Issue type" options={typeOptions} value={typeFilter} onChange={setTypeFilter} />
            <Input
              type="search"
              className="jr-filter"
              aria-label="Filter the backlog"
              placeholder="Filter key, summary, epic"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </Toolbar>

          <Modal open={!!adding} onClose={() => setAdding(null)} size="md" title="Add a backlog item">
            {adding && (
              <form
                onSubmit={async (e) => {
                  e.preventDefault()
                  setAdding({ ...adding, busy: true })
                  try {
                    const r = await postJiraIssue(adding.summary, adding.cls)
                    toast('success', `${r.key} added to my backlog`)
                    setAdding(null)
                    refresh()
                  } catch (err) {
                    toast('error', err instanceof Error ? err.message : String(err), { persistent: true })
                    setAdding({ ...adding, busy: false })
                  }
                }}
              >
                <Field label="What needs doing">
                  <Input value={adding.summary} onChange={(e) => setAdding({ ...adding, summary: e.target.value })} maxLength={200} required />
                </Field>
                <Field label="Kind of work">
                  <Select value={adding.cls} onChange={(e) => setAdding({ ...adding, cls: e.target.value as 'planned' | 'bau' | 'unplanned' })}>
                    <option value="planned">Planned</option>
                    <option value="bau">BAU</option>
                    <option value="unplanned">Unplanned</option>
                  </Select>
                </Field>
                <Button type="submit" loading={adding.busy} disabled={adding.busy || !adding.summary.trim()}>
                  Add it
                </Button>
              </form>
            )}
          </Modal>

          {planned.length > 0 && (
            <>
              <h3 className="jr-group">Planned for a future sprint ({planned.length})</h3>
              {table(planned, 'Planned for a future sprint')}
              <h3 className="jr-group">Unplanned ({unplanned.length})</h3>
            </>
          )}
          {table(unplanned, 'Unplanned backlog items')}
        </Card>
      )}
    </div>
  )
}
