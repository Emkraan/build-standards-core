// CI and backup tab: the self-hosted runner fleet on the Lima VM and the nightly state backup.
import type { StatusTone, TableColumn } from '@kit'
import { Badge, Card, CardHead, EmptyState, IconAlert, StatTile, Table, Toolbar } from '@kit'
import type { ReactNode } from 'react'
import { postInfraTaskRun, relTime, useInfraTasks } from '../../lib/data'
import { RunButton } from '../operations/RunButton'
import { latestSnapshot, short, ts, useRunners } from './data'
import { FeedPending, KeyValues, StatePill } from './parts'
import type { FleetJob, RunnerFleet } from './types'

type Runner = RunnerFleet['runners'][number]

const RUNNER_COLUMNS: TableColumn<Runner>[] = [
  {
    key: 'name',
    header: 'Runner',
    value: (r) => `${r.name} ${r.labels.join(' ')}`,
    render: (r) => (
      <div className="infra-cell">
        <span className="infra-cell-title">{r.name}</span>
        <span className="infra-cell-sub">{r.labels.join(', ')}</span>
      </div>
    ),
  },
  { key: 'status', header: 'Status', render: (r) => <StatePill tone={r.status === 'online' ? 'success' : 'danger'}>{r.status}</StatePill> },
  {
    key: 'busy',
    header: 'Load',
    value: (r) => (r.busy ? 'busy' : 'idle'),
    render: (r) => (
      <StatePill tone={r.busy ? 'info' : 'neutral'} live={r.busy}>
        {r.busy ? 'busy' : 'idle'}
      </StatePill>
    ),
  },
]

type QueueRow = FleetJob & { running: boolean }

const QUEUE_COLUMNS: TableColumn<QueueRow>[] = [
  {
    key: 'workflow',
    header: 'Job',
    value: (j) => `${j.workflow} ${j.branch} ${j.name}`,
    render: (j) => (
      <div className="infra-cell">
        <span className="infra-cell-title">
          <a href={j.url} target="_blank" rel="noreferrer">
            {j.workflow}
          </a>
        </span>
        <span className="infra-cell-sub">
          {j.branch} &middot; {j.name}
        </span>
      </div>
    ),
  },
  {
    key: 'running',
    header: 'State',
    value: (j) => (j.running ? 'running' : 'queued'),
    render: (j) => (
      <StatePill tone={j.running ? 'info' : 'warning'} live={j.running}>
        {j.running ? 'running' : 'queued'}
      </StatePill>
    ),
  },
  {
    key: 'created',
    header: 'Since',
    value: (j) => ts(j.created),
    render: (j) => <span className="infra-muted">{relTime(j.created)}</span>,
  },
]

export default function CiTab() {
  const { data, error, refresh, loading, at } = useRunners()
  const tasks = useInfraTasks()
  if (!data) return <FeedPending title="CI runners and backup" error={error} what="Runner status" tiles />
  const online = data.runners.filter((r) => r.status === 'online').length
  const busy = data.runners.filter((r) => r.busy).length
  const vmUp = data.vm?.status === 'Running'
  const b = data.backup
  const latest = latestSnapshot(data)
  // The judgement of whether CI and backup are healthy is the server's (the Overview card and the tab count read the problem
  // list); this tab only shows facts and the status word the backup itself reported.
  const backupTone: StatusTone = b?.status === 'ok' ? 'success' : 'neutral'
  const queue: QueueRow[] = [...data.running.map((j) => ({ ...j, running: true })), ...data.queued.map((j) => ({ ...j, running: false }))]
  return (
    <div className="infra-stack">
      <div className="stat-grid">
        <StatTile value={`${online}/${data.runners.length}`} label="runners online" hue="blue" />
        <StatTile value={busy} label="runners busy" hue="blue" />
        <StatTile value={data.queued.length} label="jobs queued" hue="blue" />
        <StatTile value={latest ? relTime(latest.time) : 'never'} label="last state backup" hue="blue" />
      </div>
      <div className="infra-grid">
        <Card>
          <CardHead
            title="Self-hosted runners"
            subtitle={`${short(data.repo)} on Lima VM ${data.vm?.name ?? '(missing)'}`}
            controls={
              <>
                <StatePill tone={vmUp ? 'success' : 'danger'}>VM {data.vm?.status ?? 'not found'}</StatePill>
                {data.vm && (
                  <Badge>
                    {data.vm.cpus} vCPU / {data.vm.memory_gib} GiB / {data.vm.disk_gib} GiB disk
                  </Badge>
                )}
                {data.minutes && (
                  <Badge>
                    hosted minutes {data.minutes.hosted_used}/{data.minutes.included}
                  </Badge>
                )}
              </>
            }
          />
          <Toolbar
            label="Runner links"
            onRefresh={refresh}
            refreshing={loading}
            updatedAt={at || null}
            actions={
              <>
                <a className="btn" data-variant="secondary" data-size="sm" href={data.links.actions} target="_blank" rel="noreferrer">
                  Actions
                </a>
                <a className="btn" data-variant="secondary" data-size="sm" href={data.links.pulls} target="_blank" rel="noreferrer">
                  Pull requests
                </a>
                <a className="btn" data-variant="secondary" data-size="sm" href={data.links.runners} target="_blank" rel="noreferrer">
                  Runner settings
                </a>
              </>
            }
          />
          {data.errors.length > 0 && (
            <p className="tone hue-red infra-alert" role="alert">
              <IconAlert />
              <span>{data.errors.join(' | ')}</span>
            </p>
          )}
          <Table
            caption="Self-hosted runners"
            columns={RUNNER_COLUMNS}
            rows={data.runners}
            rowKey={(r) => r.name}
            empty={<EmptyState compact icon={<IconAlert />} hue="red" title="No runners registered." />}
          />
          {queue.length > 0 && (
            <div className="infra-block">
              <div className="infra-eyebrow">Running and queued jobs</div>
              <Table
                caption="Running and queued jobs"
                columns={QUEUE_COLUMNS}
                rows={queue}
                rowKey={(j) => String(j.id)}
                defaultSort={null}
              />
            </div>
          )}
        </Card>
        <Card>
          <CardHead
            title="State backup"
            subtitle="the nightly backup and the restore drill"
            controls={
              <>
                {(tasks.data?.tasks ?? []).map((t) => (
                  <RunButton
                    key={t.name}
                    label={t.label}
                    title={t.label}
                    inputs={t.inputs}
                    refusal={t.running ? { kind: 'running', reason: 'This task is already running.' } : undefined}
                    start={(req) => postInfraTaskRun(t.name, req.inputs)}
                    onStarted={tasks.refresh}
                  />
                ))}
              </>
            }
          />
          {!b ? (
            <EmptyState compact icon={<IconAlert />} hue="amber" title="No backup has run yet." />
          ) : (
            <KeyValues
              rows={[
                [
                  'Status',
                  <span key="s" className="infra-pills">
                    <StatePill tone={backupTone}>{b.status}</StatePill>
                    <span className="infra-muted">{b.message}</span>
                  </span>,
                ],
                ...(latest
                  ? ([
                      [
                        'Latest snapshot',
                        <span key="l">
                          <code>{latest.id}</code> {relTime(latest.time)}
                        </span>,
                      ],
                      ['Size', `${(latest.bytes / 2 ** 30).toFixed(2)} GiB, ${latest.files.toLocaleString()} files`],
                    ] as [string, ReactNode][])
                  : []),
                ['Integrity check', relTime(b.checked_utc)],
                [
                  'Restore drill',
                  b.drill ? (
                    <span key="d" className="infra-pills">
                      <StatePill tone={b.drill.result === 'pass' ? 'success' : 'danger'}>{b.drill.result}</StatePill>
                      <span className="infra-muted">{relTime(b.drill.ran_utc)}</span>
                    </span>
                  ) : (
                    <StatePill key="d" tone="warning">
                      not run yet
                    </StatePill>
                  ),
                ],
              ]}
            />
          )}
        </Card>
      </div>
    </div>
  )
}
