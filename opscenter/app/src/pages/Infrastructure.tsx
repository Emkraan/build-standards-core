// Infrastructure hub (/infra and /infra/:tab): live, read-only views of LLM spend, scheduled jobs,
// live CI jobs, runners and backup, and GitHub. Each tab lives in src/pages/infra/.
import type { ComponentType } from 'react'
import { useParams } from 'react-router-dom'
import { HubHeader } from '../components/HubHeader'
import Ci from './infra/Ci'
import { useAreas, useRunners } from './infra/data'
import Github from './infra/Github'
import Jobs from './infra/Jobs'
import LiveJobs from './infra/LiveJobs'
import Overview from './infra/Overview'
import Spend from './infra/Spend'
import './Infrastructure.css'

const TAB_BODY: Record<string, ComponentType> = {
  spend: Spend,
  jobs: Jobs,
  live: LiveJobs,
  ci: Ci,
  github: Github,
}

export default function Infrastructure() {
  const { tab } = useParams()
  const { areas } = useAreas()
  const n = (k: string) => areas.find((a) => a.key === k)?.issues
  const fleet = useRunners().data
  const liveN = fleet ? fleet.queued.length + fleet.running.length : 0
  const Body = (tab && TAB_BODY[tab]) || Overview
  return (
    <div className="hub infra">
      <HubHeader
        eyebrow="Platform"
        title="Infrastructure"
        tabs={[
          { to: '/infra', label: 'Overview', end: true },
          { to: '/infra/spend', label: 'LLM spend', n: (n('spend') || 0) + (n('accounts') || 0) || undefined },
          { to: '/infra/jobs', label: 'Scheduled jobs', n: n('jobs') },
          { to: '/infra/live', label: 'Live jobs', n: liveN || undefined, live: !!fleet && fleet.running.length > 0 },
          { to: '/infra/ci', label: 'CI and backup', n: n('ci') },
          { to: '/infra/github', label: 'GitHub', n: n('github') },
        ]}
      />
      <div className="hub-body">
        <Body />
      </div>
    </div>
  )
}
