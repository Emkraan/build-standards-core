// Jira hub: everything I track in Atlassian, one sidebar entry. Sprint is the
// landing tab (what is current and where my items stand), Needs me is sprint
// tickets the nightly close-out could not settle without my call, Backlog is my
// open work outside the sprint, Changes is JSM change requests waiting on my
// approval. Tabs are routes (/jira, /jira/needs-me, /jira/backlog,
// /jira/changes). Every ticket key links straight to Jira.
import { useParams } from 'react-router-dom'
import Approvals from '../components/Approvals'
import { HubHeader } from '../components/HubHeader'
import { useApprovals, useBacklog, useJiraNeedsMe, useJiraSprint } from '../lib/data'
import Backlog from './Backlog'
import NeedsMe from './NeedsMe'
import Sprint from './Sprint'
import './Jira.css'

function Changes() {
  return (
    <div className="page">
      <p className="jr-lede">
        JSM change requests where I am the approver. Approve or decline in the portal, the rows link straight to it.
      </p>
      <Approvals />
    </div>
  )
}

export default function JiraHub() {
  const { tab } = useParams()
  const { data: sp } = useJiraSprint()
  const { data: bl } = useBacklog()
  const { data: ap } = useApprovals()
  const { data: nm } = useJiraNeedsMe()
  const myOpen = sp ? sp.items.filter((i) => i.mine && i.status_category !== 'done').length : undefined
  const body = tab === 'backlog' ? <Backlog /> : tab === 'changes' ? <Changes /> : tab === 'needs-me' ? <NeedsMe /> : <Sprint />
  return (
    <div className="hub">
      <HubHeader
        eyebrow="Operate"
        title="Jira"
        subtitle="My sprint, the tickets waiting on my call, my backlog and the changes waiting on my approval, live from Jira."
        tabs={[
          { to: '/jira', label: sp?.sprint ? `Sprint: ${sp.sprint.name}` : 'Sprint', n: myOpen, end: true },
          { to: '/jira/needs-me', label: 'Needs me', n: nm?.count },
          { to: '/jira/backlog', label: 'Backlog', n: bl?.count },
          { to: '/jira/changes', label: 'Changes', n: ap?.pending.length },
        ]}
      />
      <div className="hub-body">{body}</div>
    </div>
  )
}
