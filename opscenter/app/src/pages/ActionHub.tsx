// Action Center hub: everything that turns into an action item lives here.
// Now = action table + approvals, Completed = resolved items, Routing = the rules and
// what they did, Alerts = what my scheduled jobs reported or where they failed
// (the chat replacement, 2026-10-16), Live = what is acting right now (live sessions and the builds feed).
// Drafts and Plans were retired 2026-10-06 (unused).
import { lazy, Suspense } from 'react'
import { useParams } from 'react-router-dom'
import { HubHeader } from '../components/HubHeader'
import { useActionCounts } from '../lib/counts'
import { useActiveBuilds, useTackleSessions } from '../lib/data'
import { liveCount } from '../lib/liveWork'
import ActionCenter from './ActionCenter'
import ActionRouting from './ActionRouting'
import Alerts from './Alerts'
import Completed from './Completed'
import './Action.css'

// The Live tab loads after first paint so the Now tab keeps its first load budget.
const LiveWork = lazy(() => import('../components/LiveWork'))

export default function ActionHub() {
  const { tab } = useParams()
  const c = useActionCounts()
  const { data: sessions } = useTackleSessions()
  const { data: builds } = useActiveBuilds()
  const live = liveCount(sessions, builds)
  return (
    <div className="hub">
      <HubHeader
        eyebrow="Operate"
        title="Action Center"
        subtitle="What needs me now, what is acting right now, and what my jobs reported."
        tabs={[
          { to: '/action', label: 'Now', n: c.actions, end: true },
          { to: '/action/live', label: 'Live', n: live || undefined },
          { to: '/action/alerts', label: 'Alerts', n: c.alerts },
          { to: '/action/completed', label: 'Completed' },
          { to: '/action/routing', label: 'Routing' },
        ]}
      />
      <div className="hub-body">
        {tab === 'live' ? (
          <Suspense fallback={null}>
            <LiveWork />
          </Suspense>
        ) : tab === 'alerts' ? (
          <Alerts />
        ) : tab === 'completed' ? <Completed /> : tab === 'routing' ? <ActionRouting /> : <ActionCenter />}
      </div>
    </div>
  )
}
