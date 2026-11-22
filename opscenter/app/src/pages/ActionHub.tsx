// Action Center hub: everything that turns into an action item lives here.
// Now = action table + approvals, Completed = resolved items, Routing = the rules and
// what they did, Alerts = what my scheduled jobs reported or where they failed
// (the chat replacement, 2026-10-16), Live = what is acting right now (live sessions and the builds feed).
// Drafts and Plans were retired 2026-10-06 (unused).
import { lazy, Suspense } from 'react'
import { Navigate, useParams } from 'react-router-dom'
import { HubHeader } from '../components/HubHeader'
import { useActionCounts } from '../lib/counts'
import { useActiveBuilds, useDrafts, useTackleSessions } from '../lib/data'
import { liveCount } from '../lib/liveWork'
import ActionCenter from './ActionCenter'
import ActionRouting from './ActionRouting'
import Alerts from './Alerts'
import Completed from './Completed'
import './Action.css'

// The Live tab loads after first paint so the Now tab keeps its first load budget.
const LiveWork = lazy(() => import('../components/LiveWork'))
const Drafts = lazy(() => import('../components/Drafts'))

// `fixedTab` is for a route with no :tab segment of its own (/action/drafts); every other tab comes from /action/:tab.
export default function ActionHub({ fixedTab }: { fixedTab?: string }) {
  const { tab: routeTab } = useParams()
  const tab = fixedTab ?? routeTab
  const c = useActionCounts()
  const { data: sessions } = useTackleSessions()
  const { data: builds } = useActiveBuilds()
  const live = liveCount(sessions, builds)
  // The Drafts tab exists only when the server has a drafts provider (a 404 on /api/drafts hides it).
  const { data: drafts } = useDrafts()
  const draftsOn = !!drafts?.configured
  // With no drafts provider the old address leaves for the home tab, as it did when drafts were retired.
  if (tab === 'drafts' && drafts && !drafts.configured) return <Navigate to="/action" replace />
  return (
    <div className="hub">
      <HubHeader
        title="Action Center"
        subtitle="What needs my decision now, what is running, and what already handled itself."
        tabs={[
          { to: '/action', label: 'Needs me', n: c.actions, end: true },
          { to: '/action/live', label: 'Live', n: live || undefined },
          { to: '/action/alerts', label: 'Alerts', n: c.alerts },
          { to: '/action/completed', label: 'Completed' },
          ...(draftsOn ? [{ to: '/action/drafts', label: 'Drafts', n: drafts.drafts.filter((d) => !d.archived).length }] : []),
          { to: '/action/routing', label: 'Routing' },
        ]}
      />
      <div className="hub-body">
        {tab === 'live' ? (
          <Suspense fallback={null}>
            <LiveWork />
          </Suspense>
        ) : tab === 'drafts' && draftsOn ? (
          <Suspense fallback={null}>
            <Drafts />
          </Suspense>
        ) : tab === 'alerts' ? (
          <Alerts />
        ) : tab === 'completed' ? <Completed /> : tab === 'routing' ? <ActionRouting /> : <ActionCenter />}
      </div>
    </div>
  )
}
