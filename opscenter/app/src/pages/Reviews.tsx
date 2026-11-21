// Reviews hub: everything waiting on my review or merge, one sub-tab per repo.
// platform = engineer PR escalations, held terraform plans, privileged deployments,
// my PRs. team = lane escalations and my green PRs waiting on my admin merge. ops_center and Core get
// one tab each with the same Needs me / In progress / Recently shipped layout (RepoReviews.tsx).
import { Skeleton } from '@kit'
import { Navigate, useParams } from 'react-router-dom'
import { HubHeader } from '../components/HubHeader'
import { PulseStrip } from '../components/Watcher'
import { useActionCounts } from '../lib/counts'
import { useTeamReviews, usePlatformReviews, useRepoReviews } from '../lib/data'
import TeamSection from './TeamReviews'
import { PlatformSection } from './PlatformReviews'
import RepoSection from './RepoReviews'
import { StateLegend } from './reviews/parts'
import './ReviewsHub.css'
import { pageTitle } from '../lib/config'

// Repos with their own tab beside platform and team, slug -> label (repo_reviews.py LABELS).
const OTHER = [
  { slug: 'ops_center', label: 'ops_center' },
  { slug: 'build-standards-core', label: 'Core' },
] as const
const REPOS = ['platform', 'team', ...OTHER.map((o) => o.slug)] as string[]

export default function Reviews() {
  const { repo, tab } = useParams()
  const { data: platformLane, error: platformErr } = usePlatformReviews()
  const { data: team, error: teamErr } = useTeamReviews()
  const { data: other } = useRepoReviews()
  const counts = useActionCounts()
  const otherRepo = (slug: string) => other?.repos.find((r) => r.slug === slug)
  const otherNeed = (slug: string) => otherRepo(slug)?.counts?.needs_me
  // The old single Other repos tab lands on the first repo that needs me.
  if (repo === 'repos') {
    const hit = OTHER.find((o) => (otherNeed(o.slug) || 0) > 0) || OTHER[0]
    return <Navigate to={`/reviews/${hit.slug}`} replace />
  }
  if (!repo || !REPOS.includes(repo)) {
    // Wait for both counts (or an error) before choosing, or it always lands on platform.
    if ((!platformLane && !platformErr) || (!team && !teamErr))
      return (
        <div className="hub">
          <Skeleton variant="card" label="Loading reviews" />
        </div>
      )
    // Land on the repo that needs me (platform first), so the sidebar badge leads somewhere real.
    const platformN = platformLane?.counts.needs_me || 0
    const teamN = team?.counts.needs_me || 0
    const firstOther = OTHER.find((o) => (otherNeed(o.slug) || 0) > 0)
    const first = platformN > 0 ? 'platform' : teamN > 0 ? 'team' : firstOther ? firstOther.slug : 'platform'
    return <Navigate to={`/reviews/${first}`} replace />
  }
  return (
    <div className="hub">
      <HubHeader
        eyebrow="Operate"
        title={pageTitle('/reviews', 'Pull requests')}
        subtitle="Everything waiting on my review or merge, one tab per repo"
        tabs={[
          { to: '/reviews/platform', label: 'platform', n: platformLane?.counts.needs_me, live: counts.platformWorking > 0 },
          { to: '/reviews/team', label: 'team', n: team?.counts.needs_me, live: counts.teamWorking > 0 },
          ...OTHER.map((o) => ({
            to: `/reviews/${o.slug}`,
            label: o.label,
            n: otherNeed(o.slug),
            live: (otherRepo(o.slug)?.in_progress || []).some((p) => !!p.working),
          })),
        ]}
      />
      <PulseStrip jobs={(repo === 'team' ? team : repo === 'platform' ? platformLane : otherRepo(repo))?.cron_pulse?.jobs} />
      <StateLegend />
      {repo === 'team' ? (
        <TeamSection tab={tab} />
      ) : repo === 'platform' ? (
        <PlatformSection tab={tab} />
      ) : (
        <RepoSection slug={repo} tab={tab} />
      )}
    </div>
  )
}
