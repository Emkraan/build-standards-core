// Scheduled jobs tab: every Hermes cron job with its health, and a detail dialog per job.
import type { TableColumn } from '@kit'
import { Button, Card, CardHead, Field, Input, Table, Toolbar } from '@kit'
import { useState } from 'react'
import { postCronNow, relTime } from '../../lib/data'
import { RunButton } from '../operations/RunButton'
import { HEALTH_RANK, kindTone, nextIn, ts, useCron } from './data'
import { HealthPill, JobModal } from './JobModal'
import { FeedPending, Note, StatePill } from './parts'
import type { CronJob } from './types'

export default function JobsTab() {
  const { data, error, refresh, loading, at } = useCron()
  const [showAll, setShowAll] = useState(false)
  const [filter, setFilter] = useState('')
  const [sel, setSel] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  if (!data) return <FeedPending title="Scheduled jobs" error={error} what="Cron status" />
  const bad = data.jobs.filter((j) => j.health === 'failing' || j.health === 'overdue')
  const hb = data.scheduler_heartbeat_age_s
  const hbOk = hb !== null && hb < 180
  const selJob = sel ? data.jobs.find((j) => j.id === sel) : undefined
  const columns: TableColumn<CronJob>[] = [
    {
      key: 'name',
      header: 'Job',
      value: (j) => `${j.name} ${j.description} ${j.category}`,
      render: (j) => (
        <div className="infra-cell">
          <span className="infra-cell-title">{j.name}</span>
          {j.description && <span className="infra-cell-sub infra-trunc">{j.description}</span>}
          {showAll && (j.last_error || j.delivery_error) && <span className="infra-cell-err">{j.last_error || j.delivery_error}</span>}
        </div>
      ),
    },
    { key: 'kind', header: 'Type', render: (j) => <StatePill tone={kindTone(j.kind)}>{j.kind}</StatePill> },
    { key: 'schedule', header: 'Schedule', render: (j) => <code>{j.schedule}</code> },
    { key: 'last', header: 'Last run', value: (j) => ts(j.last_run_at), render: (j) => (j.last_run_at ? relTime(j.last_run_at) : 'never') },
    { key: 'next', header: 'Next', value: (j) => ts(j.next_run_at), render: (j) => nextIn(j.next_run_at) },
    { key: 'outputs_d7', header: 'Logs 7d', numeric: true },
    { key: 'health', header: 'Health', value: (j) => HEALTH_RANK[j.health] ?? 9, render: (j) => <HealthPill j={j} /> },
    {
      key: 'run',
      header: '',
      render: (j) => (
        <RunButton
          label="Run now"
          title={`Run ${j.name} now`}
          subtitle={j.schedule}
          inputs={[{ name: 'note', type: 'string', default: '', help: 'An optional note the run starts with.' }]}
          refusal={j.enabled ? undefined : { kind: 'paused', reason: j.paused_reason || 'This job is paused.' }}
          start={(req) => postCronNow(j.id, String(req.inputs.note || ''))}
          onStarted={refresh}
          variant="ghost"
        />
      ),
    },
  ]
  return (
    <Card>
      <CardHead
        title="Scheduled jobs"
        subtitle={`${data.jobs.length} jobs, ${bad.length} need attention`}
        controls={
          <>
            <StatePill tone={hbOk ? 'success' : 'danger'}>
              scheduler {hbOk ? 'alive' : 'STALE'} ({hb ?? '?'}s heartbeat)
            </StatePill>
            <StatePill tone={bad.length ? 'danger' : 'success'}>
              {bad.length ? `${bad.length} failing or overdue` : 'all healthy'}
            </StatePill>
          </>
        }
      />
      <Toolbar
        label="Scheduled jobs actions"
        onRefresh={refresh}
        refreshing={loading}
        updatedAt={at || null}
        actions={
          <Button size="sm" variant="secondary" onClick={() => setShowAll((s) => !s)} aria-pressed={showAll}>
            {showAll ? 'Compact' : 'Show errors'}
          </Button>
        }
      >
        <Field label="Filter jobs">
          <Input type="search" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Name, description or category" />
        </Field>
      </Toolbar>
      <Table
        caption="Scheduled jobs"
        columns={columns}
        rows={data.jobs}
        rowKey={(j) => j.id}
        filter={filter}
        onRowActivate={(j) => {
          setSel(j.id)
          setOpen(true)
        }}
        isRowSelected={(j) => open && j.id === sel}
      />
      <Note>
        Click a job for its description, spend and recent runs. script = no model spend. gated agent = a script decides whether the model
        runs. agent = model runs every time. Logs 7d counts output files in the last 7 days (the output folder keeps the newest 50).
        Refreshed {relTime(data.generated_utc)}.
      </Note>
      <JobModal job={selJob} open={open} onClose={() => setOpen(false)} />
    </Card>
  )
}
