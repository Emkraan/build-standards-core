import { Link } from 'react-router-dom'
import { relTime, useLlmFallback } from '../lib/data'
import AlertBanner from './AlertBanner'

// important banner, shown on every page while Enterprise is billing
// Hermes calls that Team had headroom for. Clears itself an hour after the
// last leaked call. The same incident pings chat once when it opens.
// a second line when the desktop backend (launchd ai.hermes.dashboard,
// KeepAlive, independent of the app) predates the debt_id pool patches. Quitting
// the app does not restart it, so the fix is a launchctl kickstart of the
// service. Clears as soon as the service restarts (computed live on every read).
export default function FallbackBanner() {
  const { data } = useLlmFallback()
  const a = data?.active
  const stale = data?.stale_host
  if (!a && !stale) return null
  const top = a
    ? Object.entries(a.sessions)
        .sort((x, y) => y[1].calls - x[1].calls)
        .slice(0, 3)
        .map(([sid, s]) => `${s.platform || '?'} ${sid.startsWith('cron_') ? sid.split('_')[1] : sid.slice(-6)} (${s.calls})`)
        .join(', ')
    : ''
  return (
    <>
      {a && (
        <AlertBanner
          title={`Enterprise is billing Hermes while Team has headroom: ${a.calls} call${a.calls === 1 ? '' : 's'}, about $${a.est_usd.toFixed(2)} at list`}
          action={
            <Link className="btn" data-variant="secondary" data-size="sm" to="/operations/cost/spend">
              Spend &rarr;
            </Link>
          }
        >
          Opened {relTime(a.opened_utc)}, last call {relTime(a.last_call_utc)}. Team {a.team_session_pct ?? '?'}% session,{' '}
          {a.team_weekly_pct ?? '?'}% weekly. {top}
        </AlertBanner>
      )}
      {stale && (
        <AlertBanner title="Restart the Hermes dashboard service">
          The desktop backend (launchd ai.hermes.dashboard, PID {stale.pid}) started {relTime(stale.started_utc)}, before the Enterprise
          leak fixes landed {relTime(stale.patched_utc)}. Quitting the app does not restart it. Run: launchctl kickstart -k gui/$(id
          -u)/ai.hermes.dashboard
        </AlertBanner>
      )}
    </>
  )
}
