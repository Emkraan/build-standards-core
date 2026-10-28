// The detail dialog for one Hermes cron job: what it does, schedule, spend, delivery and recent runs.
// Shared by the Scheduled jobs tab and the "Jobs feeding this page" strip on Reviews, so it brings its
// own stylesheet (every selector in it is infra- scoped).
import { Badge, Modal, ModalSection } from '@kit'
import type { ReactNode } from 'react'
import { relTime } from '../../lib/data'
import '../Infrastructure.css'
import { fmtWhen, healthTone, kindTone, nextIn, usd, useCron, useSpend } from './data'
import { KeyValues, StatePill } from './parts'
import type { CronJob } from './types'

const DELIVER_LABEL = (d: string) =>
  d === 'local' ? 'local only (no ping)' : d === 'origin' ? 'back to where it was created' : d.startsWith('chat') ? 'chat' : d

const KIND_TEXT = (kind: string) =>
  kind === 'script'
    ? 'script only, no model'
    : kind === 'gated agent'
      ? 'gated agent: a script decides whether the model runs'
      : 'agent: model runs every tick'

export function HealthPill({ j }: { j: CronJob }) {
  return (
    <StatePill tone={healthTone(j.health)}>
      {j.health}
      {j.failure_streak ? ` x${j.failure_streak}` : ''}
    </StatePill>
  )
}

export function JobModal({ job: j, open, onClose }: { job: CronJob | undefined; open: boolean; onClose: () => void }) {
  const spend = useSpend().data
  if (!j) return null
  const cost = spend?.jobs.find((x) => x.id === j.id)
  const rows: [string, ReactNode][] = [
    ['Schedule', <code key="s">{j.schedule}</code>],
    ['Next run', j.next_run_at ? `${fmtWhen(j.next_run_at).split(' (')[0]} (${nextIn(j.next_run_at)})` : '-'],
    ['Last run', fmtWhen(j.last_run_at)],
    ['Last status', j.last_status || '-'],
    ['Type', KIND_TEXT(j.kind)],
    ['Model', j.model || '-'],
    ['Delivery', DELIVER_LABEL(j.deliver || '')],
    ['Script', j.script ? <code key="sc">agent_home/scripts/{j.script}</code> : '-'],
    ['Skills', j.skills.length ? j.skills.join(', ') : '-'],
    ['Workdir', j.workdir ? <code key="w">{j.workdir.replace(/^\/Users\/[^/]+/, '~')}</code> : '-'],
    ['Runs completed', j.runs_total != null ? String(j.runs_total) : '-'],
    ['Logs 7d', String(j.outputs_d7)],
    ['Created', fmtWhen(j.created_at)],
    ['Job id', <code key="id">{j.id}</code>],
  ]
  if (cost)
    rows.splice(6, 0, [
      'Spend',
      `${usd(cost.billed_today)} billed today, ${usd(cost.billed_d7)} billed last 7 days (${cost.fallback_runs_d7} of ${cost.runs_d7} runs fell back to Enterprise), ${usd(cost.included_d7)} covered by Team, list price ${usd(cost.per_run_d7)}/run`,
    ])
  const failing = j.health === 'failing'
  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title={j.name}
      subtitle={j.category}
      hue={failing ? 'red' : j.health === 'overdue' ? 'amber' : 'blue'}
      cancelLabel="Close"
    >
      <div className="infra-pills">
        <StatePill tone={kindTone(j.kind)}>{j.kind}</StatePill>
        <HealthPill j={j} />
        {!j.enabled && <Badge>disabled</Badge>}
      </div>
      <ModalSection title="What it does">
        {j.description ? (
          <p className="infra-prose">{j.description}</p>
        ) : (
          <p className="infra-muted">No description recorded for this job yet.</p>
        )}
        {j.paused_reason && <p className="infra-muted">Paused: {j.paused_reason}</p>}
      </ModalSection>
      {(j.last_error || j.delivery_error) && (
        <ModalSection title="Errors">
          <pre className="infra-error">
            {j.last_error ? `Last error: ${j.last_error}` : ''}
            {j.delivery_error ? `${j.last_error ? '\n' : ''}Delivery error: ${j.delivery_error}` : ''}
          </pre>
        </ModalSection>
      )}
      <ModalSection title="Details">
        <KeyValues rows={rows} />
      </ModalSection>
      {j.recent_outputs.length > 0 && (
        <ModalSection title="Recent outputs" description={`agent_home/cron/output/${j.id}/`}>
          <ul className="infra-list">
            {j.recent_outputs.map((o) => (
              <li key={o.file}>
                <code>{o.file}</code>{' '}
                <span className="infra-muted">
                  {relTime(o.at)}, {o.bytes.toLocaleString()} bytes
                </span>
              </li>
            ))}
          </ul>
        </ModalSection>
      )}
    </Modal>
  )
}

/** Open the dialog for a job by id. Mount only while open, so the cron feed is read only on demand. */
export function JobModalById({ id, onClose }: { id: string; onClose: () => void }) {
  const { data, error } = useCron()
  const job = data?.jobs.find((j) => j.id === id)
  if (data && !job)
    return (
      <Modal open onClose={onClose} title="Job not found" cancelLabel="Close">
        <p className="infra-muted">Hermes has no cron job with id {id} anymore.</p>
      </Modal>
    )
  if (!job)
    return (
      <Modal open onClose={onClose} title="Loading job" cancelLabel="Close">
        <p className="infra-muted">{error ? `Could not read the cron feed: ${error}` : 'Reading the cron feed...'}</p>
      </Modal>
    )
  return <JobModal job={job} open onClose={onClose} />
}
