import type { StatusTone, TableColumn } from '@kit'
import { Button, Card, CardHead, EmptyState, Pill, Skeleton, Table, Toolbar } from '@kit'
import { useState } from 'react'
import type { ChangeRow } from '../lib/data'
import { useApprovals } from '../lib/data'
import { LinkButton, LoadError } from './StateBlocks'

// Live JSM changes where I am the approver (server.py /api/change-approvals, read-only).
// Approve/Decline happens in Jira. Each row deep-links to the agent view and portal.
// Rendered on the Jira hub's Changes tab. The Action Center shows only a pointer.
// Kit build: a Card (red tone while anything waits on me) with a Toolbar and two kit Tables.

function riskTone(r: string): StatusTone {
  const s = r.toLowerCase()
  if (s === 'high') return 'danger'
  if (s === 'medium') return 'warning'
  if (s === 'low') return 'success'
  return 'neutral'
}
const RISK_RANK: Record<string, number> = { high: 0, medium: 1, low: 2 }

function fmtWindow(start: string, end: string): string {
  if (!start) return 'no window set'
  const s = new Date(start)
  const opts: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }
  const a = s.toLocaleString('en-US', opts)
  if (!end) return a
  const b = new Date(end).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
  return `${a} - ${b}`
}

export function hoursUntil(iso: string): number | null {
  if (!iso) return null
  return (new Date(iso).getTime() - Date.now()) / 36e5
}

function columns(primary: boolean): TableColumn<ChangeRow>[] {
  return [
    {
      key: 'key',
      header: 'Change',
      width: '120px',
      render: (c) => (
        <a className="tkt" href={c.url} target="_blank" rel="noreferrer">
          {c.key}
        </a>
      ),
    },
    {
      key: 'summary',
      header: 'Summary',
      value: (c) => `${c.summary} ${c.requester}`,
      render: (c) => (
        <div className="bk-sum">
          <span className="bk-title">{c.summary}</span>
          <span className="bk-sub">
            {c.requester || 'unknown requester'} &middot; {fmtWindow(c.planned_start, c.planned_end)}
          </span>
        </div>
      ),
    },
    {
      key: 'planned_start',
      header: 'Window',
      width: '150px',
      value: (c) => c.planned_start || null,
      render: (c) => {
        const h = hoursUntil(c.planned_start)
        const soon = h !== null && h >= 0 && h <= 24
        const past = h !== null && h < 0
        if (primary && soon) return <Pill tone="danger">window in {Math.max(1, Math.round(h ?? 0))}h</Pill>
        if (primary && past) return <Pill tone="danger">window passed</Pill>
        return <span className="bk-faint">{c.planned_start ? fmtWindow(c.planned_start, '') : 'no window set'}</span>
      },
    },
    {
      key: 'risk',
      header: 'Risk',
      width: '120px',
      value: (c) => RISK_RANK[(c.risk || '').toLowerCase()] ?? 3,
      render: (c) =>
        c.risk ? (
          <Pill tone={riskTone(c.risk)} dot>
            {c.risk} risk
          </Pill>
        ) : (
          <span className="bk-faint">-</span>
        ),
    },
    {
      key: 'change_type',
      header: primary ? 'Type' : 'Type and status',
      width: primary ? '110px' : '220px',
      value: (c) => `${c.change_type} ${c.status}`,
      render: (c) => (
        <span className="bk-status">
          {c.change_type && <Pill tone="info">{c.change_type}</Pill>}
          {!primary && <Pill>{c.status}</Pill>}
        </span>
      ),
    },
    {
      key: 'actions',
      header: 'Actions',
      hideHeader: true,
      sortable: false,
      width: primary ? '250px' : '90px',
      render: (c) =>
        primary ? (
          <div className="bk-btns">
            <LinkButton variant="primary" external href={c.portal_url}>
              Review &amp; approve
            </LinkButton>
            <LinkButton external href={c.url}>
              Agent view
            </LinkButton>
          </div>
        ) : (
          <div className="bk-btns">
            <LinkButton external href={c.url}>
              Open
            </LinkButton>
          </div>
        ),
    },
  ]
}

export default function Approvals() {
  const { data, error, loading, refresh } = useApprovals()
  const [showInflight, setShowInflight] = useState(true)

  const pending = data?.pending || []
  const inflight = data?.inflight || []

  return (
    <Card tone={pending.length ? 'red' : undefined}>
      <CardHead
        title="Changes pending my approval"
        subtitle={
          data ? `${pending.length} waiting on me \u00b7 checked ${data.generated_utc.slice(11, 16)}Z` : loading ? 'Checking JSM' : ''
        }
      />
      <Toolbar
        label="Change approval controls"
        onRefresh={() => refresh()}
        refreshing={loading}
        refreshLabel={loading ? 'Checking...' : 'Refresh'}
        actions={
          inflight.length > 0 ? (
            <Button size="sm" variant="ghost" aria-pressed={showInflight} onClick={() => setShowInflight((s) => !s)}>
              {showInflight ? 'Hide' : 'Show'} approved, in flight ({inflight.length})
            </Button>
          ) : undefined
        }
      />
      {error && !data && (
        <LoadError
          title="Could not load changes from JSM"
          error={error}
          hint={
            <>
              If the Atlassian token lapsed, run <code>hermes mcp test atlassian</code> and refresh.
            </>
          }
        />
      )}
      {!data && !error && <Skeleton variant="table" count={3} columns={5} label="Loading changes from JSM" />}
      {data && pending.length === 0 && <EmptyState compact pose="celebrate" title="No changes waiting on my approval." />}
      {pending.length > 0 && (
        <Table
          className="bk-table"
          caption="Changes waiting on my approval"
          columns={columns(true)}
          rows={pending}
          rowKey={(c) => c.key}
          defaultSort={{ key: 'planned_start', dir: 'asc' }}
        />
      )}
      {showInflight && inflight.length > 0 && (
        <>
          <h3 className="jr-group">Approved, in flight ({inflight.length})</h3>
          <Table
            className="bk-table"
            caption="Approved changes in flight"
            columns={columns(false)}
            rows={inflight}
            rowKey={(c) => c.key}
            defaultSort={{ key: 'planned_start', dir: 'asc' }}
          />
        </>
      )}
    </Card>
  )
}
