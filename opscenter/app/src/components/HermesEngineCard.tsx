import { Button, Card, CardHead, HueTile, IconRefresh, Pill, Skeleton } from '@kit'
import { useEffect, useState } from 'react'
import { type HermesBusy, type HermesRestartStatus, postHermesRestart, relTime, useHermesRestart, useNow } from '../lib/data'

// Always-on Hermes engine control (Infrastructure > Overview). Restart is always one click away and
// shows live progress: queued, waiting for idle (with what is still running), then each restart
// phase as the LaunchAgent ai.ops_center.hermes-restart reports it in running.json. The Ops Center
// server is not part of Hermes, so this card stays up while the backend restarts.
const KIND: Record<HermesBusy['kind'], string> = {
  session: 'Session',
  subagent: 'Subagents',
  cron: 'Cron',
  process: 'Background process',
  gateway: 'Gateway',
  input: 'Waiting on me',
  unknown: 'Unknown',
}

const PHASES: { key: string; label: string; match: string[] }[] = [
  { key: 'queued', label: 'Queued', match: [] },
  { key: 'idle', label: 'Waiting for idle', match: [] },
  { key: 'fence', label: 'Close backend to new work', match: ['start', 'fence'] },
  { key: 'backend', label: 'Restart backend', match: ['backend', 'backend_wait'] },
  { key: 'gateway', label: 'Restart gateway', match: ['gateway'] },
  { key: 'done', label: 'Done', match: [] },
]

function currentPhase(d: HermesRestartStatus): number {
  if (d.running) {
    const i = PHASES.findIndex((p) => p.match.includes(d.running?.phase || ''))
    return i < 0 ? 2 : i
  }
  if (d.pending) return 1
  return -1
}

function Progress({ d }: { d: HermesRestartStatus }) {
  const cur = currentPhase(d)
  if (cur < 0) return null
  return (
    <ol className="hermes-steps" aria-label="Restart progress">
      {PHASES.map((p, i) => {
        const state = i < cur ? 'done' : i === cur ? 'current' : 'todo'
        return (
          <li key={p.key} data-state={state}>
            <span className="hermes-step-dot" aria-hidden="true">
              {state === 'current' ? <span className="spin" /> : state === 'done' ? '\u2713' : ''}
            </span>
            {p.label}
          </li>
        )
      })}
    </ol>
  )
}

function LastResult({ last }: { last: NonNullable<HermesRestartStatus['last']> }) {
  const bad = last.steps.find((s) => !s.ok)
  return (
    <p className="infra-muted">
      Last restart {relTime(last.at)}:{' '}
      {last.ok ? `finished in ${last.seconds}s` : `did not finish (${bad ? `${bad.step}: ${bad.why}` : 'no step reported'})`}.
    </p>
  )
}

export default function HermesEngineCard() {
  const { data, error, refresh, mutate } = useHermesRestart()
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  useNow(5_000)
  const active = !!(data?.pending || data?.running)
  // Poll every 3 s while a restart is queued or running, so each phase shows as it happens.
  useEffect(() => {
    if (!active) return
    const id = window.setInterval(refresh, 3_000)
    return () => window.clearInterval(id)
  }, [active, refresh])

  const act = (action: 'now' | 'idle' | 'cancel') => {
    setBusy(true)
    setErr('')
    postHermesRestart(action)
      .then((d) => mutate(() => d))
      .catch((e) => setErr(String(e).replace(/^Error: /, '')))
      .finally(() => setBusy(false))
  }

  const icon = (
    <HueTile hue="violet" size="md">
      <IconRefresh />
    </HueTile>
  )
  if (!data) {
    return (
      <Card className="hermes-engine">
        <CardHead title="Hermes engine" icon={icon} />
        {error ? <p className="infra-muted">Status unavailable: {error}</p> : <Skeleton variant="card" label="Loading Hermes status" />}
      </Card>
    )
  }

  const dash = data.dashboard
  const gw = data.gateway
  const pill = data.running ? (
    <Pill tone="info" className="ui-pill-live">
      <span className="spin" aria-hidden="true" />
      restarting
    </Pill>
  ) : data.pending ? (
    <Pill tone="warning" dot>
      queued
    </Pill>
  ) : data.alert === 'failed' ? (
    <Pill tone="danger" dot>
      last restart failed
    </Pill>
  ) : data.alert === 'stale' ? (
    <Pill tone="warning" dot>
      needs restart
    </Pill>
  ) : (
    <Pill tone="success" dot>
      running
    </Pill>
  )

  const running = data.busy.length
  const names = data.busy.slice(0, 3).map((b) => `${KIND[b.kind]} "${b.label.replace(/^Subagent: /, '')}"`)
  const what = running
    ? `${running} running now: ${names.join(', ')}${running > 3 ? ` and ${running - 3} more` : ''}.`
    : 'Nothing is running right now.'
  const quietMin = Math.ceil(Math.max(0, (data.quiet_needed_s ?? 300) - (data.quiet_s ?? 0)) / 60)

  let line = `${what} A restart waits until everything is idle, so a click never cuts off running work.`
  if (data.running) {
    line = `${data.running.label || 'Restarting'}. Started ${relTime(data.running.since)}. Chat drops for under a minute and reconnects on its own.`
  } else if (data.pending) {
    line = `${data.pending.reason}. Queued ${relTime(data.pending.requested_at)}. ${what} ${
      running
        ? 'It starts the moment that work finishes.'
        : data.pending.mode === 'idle' && quietMin > 0
          ? `It starts after ${quietMin} more quiet minute${quietMin === 1 ? '' : 's'}.`
          : 'It starts within a minute.'
    }`
  }

  return (
    <Card className="hermes-engine" tone={data.alert === 'failed' ? 'red' : data.alert ? 'amber' : undefined}>
      <CardHead
        title="Hermes engine"
        subtitle={[
          dash?.started && `backend up ${relTime(dash.started).replace(' ago', '')}`,
          gw?.started && `gateway up ${relTime(gw.started).replace(' ago', '')}`,
        ]
          .filter(Boolean)
          .join(', ')}
        icon={icon}
        controls={pill}
      />
      <p className="hermes-line">{line}</p>
      <Progress d={data} />
      {data.last && !active && <LastResult last={data.last} />}
      {err && <p className="infra-muted">{err}</p>}
      <div className="infra-area-foot hermes-actions">
        {data.running ? null : data.pending ? (
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => act('cancel')}>
            Cancel restart
          </Button>
        ) : (
          <>
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => act('idle')}>
              After 5 quiet minutes
            </Button>
            <Button size="sm" variant="primary" loading={busy} disabled={busy} onClick={() => act('now')}>
              Restart Hermes
            </Button>
          </>
        )}
      </div>
    </Card>
  )
}
