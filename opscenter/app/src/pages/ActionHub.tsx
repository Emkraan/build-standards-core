// Action Center hub: everything that turns into an action item lives here.
// Now = action table + approvals, Completed = resolved items, Routing = the rules and
// what they did, Alerts = what my scheduled jobs reported or where they failed
// (the chat replacement, 2026-10-16). Drafts and
// Plans were retired 2026-10-06 (unused).
import { useParams } from 'react-router-dom'
import { HubHeader } from '../components/HubHeader'
import { useActionCounts } from '../lib/counts'
import ActionCenter from './ActionCenter'
import ActionRouting from './ActionRouting'
import Alerts from './Alerts'
import Completed from './Completed'
import './Action.css'

export default function ActionHub() {
  const { tab } = useParams()
  const c = useActionCounts()
  return (
    <div className="hub">
      <HubHeader
        eyebrow="Operate"
        title="Action Center"
        tabs={[
          { to: '/action', label: 'Now', n: c.actions, end: true },
          { to: '/action/alerts', label: 'Alerts', n: c.alerts },
          { to: '/action/completed', label: 'Completed' },
          { to: '/action/routing', label: 'Routing' },
        ]}
      />
      <div className="hub-body">
        {tab === 'alerts' ? <Alerts /> : tab === 'completed' ? <Completed /> : tab === 'routing' ? <ActionRouting /> : <ActionCenter />}
      </div>
    </div>
  )
}
