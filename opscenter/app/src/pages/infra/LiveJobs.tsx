// Live jobs tab (runner repo): run, job and step progress polled every 3 seconds, with a live log
// tail for the step running now.
import { Card, CardHead, EmptyState, IconAlert, IconChevronDown, IconChevronRight, StatusDot } from '@kit'
import { useEffect, useState } from 'react'
import { fetchApi, onLiveTick, relTime } from '../../lib/data'
import { dur, stateLabel, stateTone, useLiveJobs, useTick } from './data'
import { FeedPending, StatePill } from './parts'
import type { JobLog, LiveJob, LiveRun } from './types'

function LogTail({ runner }: { runner: string }) {
  const [log, setLog] = useState<JobLog | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    const pull = () =>
      fetchApi<JobLog>(`/api/infra/job-log?runner=${encodeURIComponent(runner)}&lines=40`)
        .then((d) => {
          if (alive) {
            setLog(d)
            setErr(null)
          }
        })
        .catch((e) => {
          if (alive) setErr(String(e))
        })
    pull()
    const stop = onLiveTick(pull, 2000)
    return () => {
      alive = false
      stop()
    }
  }, [runner])
  if (err) return <p className="infra-muted">Log unavailable: {err}</p>
  if (!log) return <p className="infra-muted">Connecting to {runner}...</p>
  if (!log.live) return <p className="infra-muted">No step output yet on {runner}.</p>
  return (
    <pre className="infra-log" aria-label={`Live log from ${runner}`}>
      {log.lines.join('\n')}
    </pre>
  )
}

/** One job with its step bar. liveLog tails the step log from our own runner VM (off for hosted runners). */
export function JobRow({ job, now, liveLog = true }: { job: LiveJob; now: number; liveLog?: boolean }) {
  const running = job.status === 'in_progress'
  const [open, setOpen] = useState(false)
  const show = open || running
  const done = job.steps.filter((s) => s.status === 'completed').length
  const current = job.steps.find((s) => s.status === 'in_progress')
  return (
    <div className="infra-job" data-running={running ? '' : undefined}>
      <button type="button" className="infra-job-head" onClick={() => setOpen(!open)} aria-expanded={show}>
        <StatusDot tone={running ? 'success' : 'neutral'} pulse={running} label={running ? 'running' : 'idle'} />
        <span className="infra-job-name">{job.name}</span>
        <span className="infra-muted">{job.runner || (job.status === 'completed' ? 'not run' : 'waiting for runner')}</span>
        <span className="infra-muted infra-push">
          {job.steps.length ? `${done}/${job.steps.length} steps` : ''}
          {current ? ` \u00b7 ${current.name}` : ''}
        </span>
        <span className="infra-muted infra-mono">{dur(job.started, job.completed, now)}</span>
        <StatePill tone={stateTone(job.status, job.conclusion)} live={running}>
          {stateLabel(job.status, job.conclusion)}
        </StatePill>
      </button>
      {job.steps.length > 0 && (
        <div className="infra-steps" role="img" aria-label={`${done} of ${job.steps.length} steps complete`}>
          {job.steps.map((st) => (
            <span
              key={st.n}
              className="infra-step"
              data-tone={stateTone(st.status, st.conclusion)}
              data-tip={`${st.name}: ${stateLabel(st.status, st.conclusion)}`}
            />
          ))}
        </div>
      )}
      {show && (
        <div className="infra-job-body">
          <ol className="infra-step-list">
            {job.steps.map((st) => (
              <li key={st.n}>
                <span className="infra-muted infra-mono infra-step-n">{st.n}</span>
                <span className="infra-step-name">{st.name}</span>
                <span className="infra-muted infra-mono">{dur(st.started, st.completed, now)}</span>
                <StatePill tone={stateTone(st.status, st.conclusion)} live={st.status === 'in_progress'}>
                  {stateLabel(st.status, st.conclusion)}
                </StatePill>
              </li>
            ))}
          </ol>
          {running && job.runner && liveLog && <LogTail runner={job.runner} />}
          <a href={job.url} target="_blank" rel="noreferrer" className="btn" data-variant="ghost" data-size="sm">
            Open job on GitHub &rarr;
          </a>
        </div>
      )}
    </div>
  )
}

function RunBlock({ run: r, now }: { run: LiveRun; now: number }) {
  const live = r.status !== 'completed'
  const [open, setOpen] = useState(false)
  const ran = r.jobs.filter((j) => j.runner)
  const failed = r.jobs.filter((j) => j.conclusion === 'failure' || j.conclusion === 'timed_out')
  const first =
    ran
      .map((j) => j.started)
      .filter(Boolean)
      .sort()[0] ?? null
  const last =
    ran
      .map((j) => j.completed)
      .filter(Boolean)
      .sort()
      .pop() ?? null
  const tone = stateTone(r.status, r.conclusion)
  return (
    <section className={`infra-run${live ? ' tone hue-blue' : tone === 'danger' ? ' tone hue-red' : ''}`} aria-label={`${r.workflow} run`}>
      {/* Clicking the head of a finished run toggles it too. The chevron is the keyboard control. */}
      <div
        className="infra-run-head"
        data-clickable={live ? undefined : ''}
        onClick={(e) => {
          if (!live && !(e.target as HTMLElement).closest('a, button')) setOpen(!open)
        }}
      >
        {!live && (
          <button
            type="button"
            className="btn infra-run-toggle"
            data-variant="ghost"
            data-size="sm"
            data-icon-only=""
            onClick={() => setOpen(!open)}
            aria-expanded={open}
            aria-label={open ? 'Hide jobs' : 'Show jobs'}
            data-tip={open ? 'Hide jobs' : 'Show jobs'}
          >
            {open ? <IconChevronDown /> : <IconChevronRight />}
          </button>
        )}
        <a href={r.url} target="_blank" rel="noreferrer" className="infra-run-name">
          {r.workflow}
        </a>
        <span className="infra-muted">
          {r.title} &middot; {r.branch} &middot; {r.event}
        </span>
        <span className="infra-muted infra-push">
          {live
            ? `started ${relTime(r.created)}`
            : `${ran.length} jobs${failed.length ? `, ${failed.length} failed` : ''} \u00b7 ${dur(first, last, now)} \u00b7 ${relTime(r.updated)}`}
        </span>
        <StatePill tone={tone} live={live && r.status === 'in_progress'}>
          {stateLabel(r.status, r.conclusion)}
        </StatePill>
      </div>
      {(live || open) && r.jobs.map((j) => <JobRow key={j.id} job={j} now={now} />)}
    </section>
  )
}

export default function LiveJobsTab() {
  const { data, error } = useLiveJobs()
  const now = useTick(!!data?.active)
  if (!data) return <FeedPending title="Live jobs" error={error} what="Live job feed" />
  const active = data.runs.filter((r) => r.status !== 'completed')
  const recent = data.runs.filter((r) => r.status === 'completed').slice(0, 5)
  return (
    <Card>
      <CardHead
        title="Live jobs"
        subtitle={data.active ? 'updating every 3s' : `idle, last checked ${relTime(data.generated_utc)}`}
        controls={
          data.active ? (
            <StatePill tone="info" live>
              live
            </StatePill>
          ) : (
            <StatePill tone="neutral">idle</StatePill>
          )
        }
      />
      {data.errors.length > 0 && (
        <p className="tone hue-red infra-alert" role="alert">
          <IconAlert />
          <span>{data.errors.join(' | ')}</span>
        </p>
      )}
      <div className="infra-stack">
        {active.length === 0 ? (
          <EmptyState compact pose="idle" title="No jobs running or queued." body="New runs appear here within 3 seconds." />
        ) : (
          active.map((r) => <RunBlock key={r.id} run={r} now={now} />)
        )}
      </div>
      {recent.length > 0 && (
        <>
          <div className="infra-eyebrow infra-eyebrow-gap">Recently finished</div>
          <div className="infra-stack">
            {recent.map((r) => (
              <RunBlock key={r.id} run={r} now={now} />
            ))}
          </div>
        </>
      )}
    </Card>
  )
}
