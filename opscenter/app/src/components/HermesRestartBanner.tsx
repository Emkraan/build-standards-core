import { Button } from '@kit'
import { useState } from 'react'
import { type HermesBusy, postHermesRestart, relTime, useHermesRestart } from '../lib/data'
import AlertBanner from './AlertBanner'

// Idle-aware Hermes restart. Shows when plugins or config changed after the engine started, when
// a restart is queued, or when the last one failed. The buttons only queue the restart: the
// LaunchAgent ai.ops_center.hermes-restart runs it once no session, subagent, cron run or background
// process is active, so a click can never cut off running work.
const KIND: Record<HermesBusy['kind'], string> = {
  session: 'Session',
  subagent: 'Subagents',
  cron: 'Cron',
  process: 'Background process',
  gateway: 'Gateway',
  input: 'Waiting on me',
  unknown: 'Unknown',
}

export default function HermesRestartBanner() {
  const { data, mutate } = useHermesRestart()
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  if (!data?.alert) return null
  const act = (action: 'now' | 'idle' | 'cancel') => {
    setBusy(true)
    setErr('')
    postHermesRestart(action)
      .then((d) => mutate(() => d))
      .catch((e) => setErr(String(e).replace(/^Error: /, '')))
      .finally(() => setBusy(false))
  }
  const running = data.busy.length
  const what = running
    ? `Running now: ${data.busy.map((b) => `${KIND[b.kind]} "${b.label}"`).join(', ')}.`
    : 'Nothing is running right now.'
  let title = 'Hermes needs a restart to load new plugins or settings'
  let body = `${what} The restart waits until everything is idle, then restarts the backend and the gateway. The desktop app reconnects on its own.`
  let action = (
    <>
      <Button size="sm" variant="secondary" loading={busy} disabled={busy} onClick={() => act('now')}>
        Restart when idle
      </Button>
      <Button size="sm" variant="ghost" disabled={busy} onClick={() => act('idle')}>
        After 5 quiet minutes
      </Button>
    </>
  )
  if (data.alert === 'pending' && data.pending) {
    const quietMin = Math.ceil(Math.max(0, (data.quiet_needed_s ?? 300) - (data.quiet_s ?? 0)) / 60)
    title = data.running ? 'Hermes is restarting' : 'A Hermes restart is queued'
    body = data.running
      ? 'The backend and the gateway are restarting. This page reconnects in under a minute.'
      : `${data.pending.reason}. Queued ${relTime(data.pending.requested_at)}. ${what} ${
          running
            ? 'It starts the moment that work finishes.'
            : data.pending.mode === 'idle' && quietMin > 0
              ? `It starts after ${quietMin} more quiet minute${quietMin === 1 ? '' : 's'}.`
              : 'It starts within a minute.'
        }`
    action = data.running ? (
      <></>
    ) : (
      <Button size="sm" variant="ghost" disabled={busy} onClick={() => act('cancel')}>
        Cancel
      </Button>
    )
  } else if (data.alert === 'failed' && data.last) {
    const bad = data.last.steps.find((s) => !s.ok)
    title = 'The last Hermes restart did not finish'
    body = `${relTime(data.last.at)}, ${bad ? `${bad.step}: ${bad.why}` : 'no step reported'}. ${what}`
    action = (
      <Button size="sm" variant="secondary" loading={busy} disabled={busy} onClick={() => act('now')}>
        Retry when idle
      </Button>
    )
  }
  return (
    <AlertBanner tone={data.alert === 'failed' ? 'critical' : 'info'} title={title} action={action}>
      {body}
      {err && ` ${err}`}
    </AlertBanner>
  )
}
