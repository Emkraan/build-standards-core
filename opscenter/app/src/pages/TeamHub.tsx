// Team hub: the current assessment cycle, each member's review record, the
// annual review I write once a year, and the month-over-month trend. One
// sidebar entry; tabs are routes (/team, /team/members, /team/yearly,
// /team/history).
import { useParams } from 'react-router-dom'
import { HubHeader } from '../components/HubHeader'
import { useYearlyReviews } from '../lib/data'
import MemberReviews from './MemberReviews'
import TeamHistory from './TeamHistory'
import TeamPerformance from './TeamPerformance'
import YearlyReview from './YearlyReview'
import './Team.css'

export default function TeamHub() {
  const { tab } = useParams()
  const { data: yr } = useYearlyReviews()
  const year = String(new Date().getFullYear())
  const recs = yr?.reviews?.[year] || {}
  const roster = yr?.people || []
  const notFinal = roster.filter((n) => recs[n]?.status !== 'final').length
  const body =
    tab === 'history' ? <TeamHistory /> : tab === 'members' ? <MemberReviews /> : tab === 'yearly' ? <YearlyReview /> : <TeamPerformance />
  return (
    <div className="hub">
      <HubHeader
        eyebrow="People"
        title="Team Performance"
        tabs={[
          { to: '/team', label: 'This cycle', end: true },
          { to: '/team/members', label: 'Member reviews' },
          { to: '/team/yearly', label: `Yearly review ${year}`, n: yr ? notFinal : undefined },
          { to: '/team/history', label: 'Trends' },
        ]}
      />
      <div className="hub-body">{body}</div>
    </div>
  )
}
