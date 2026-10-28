// Reviews hub: everything waiting on my review or merge, one sub-tab per repo.
// platform = engineer PR escalations, held terraform plans, privileged deployments,
// my PRs. team = lane escalations and my green PRs waiting on my admin merge. ops_center and Core get
// one tab each with the same Needs me / In progress / Recently shipped layout (RepoReviews.tsx).
import { Skeleton } from '@kit'
import { Navigate, useParams } from 'react-router-dom'
import { HubHeader } from '../components/HubHeader'
import { PulseStrip } from '../components/Watcher'
import { useActionCounts } from '../lib/counts'
import { useAresReviews, useplatformReviews, useRepoReviews } from '../lib/data'
import AresSection from './AresReviews'
import { PlatformSection } from './PlatformReviews'
import RepoSection from './RepoReviews'
import { StateLegend } from './reviews/parts'
import './ReviewsHub.css'

// Repos with their own tab beside platform and team, slug -> label (repo_reviews.py LABELS).
const OTHER = [
  { slug: 'ops_center', label: 'ops_center' },
  { slug: 'build-standards-core', label: 'Core' },
] as const
const REPOS = ['platform', 'team', ...OTHER.map((o) => o.slug)] as string[]

export default function Reviews() {
  const { repo, tab } = useParams()
  const { data: oly, error: olyErr } = useplatformReviews()
  const { data: team, error: aresErr } = useAresReviews()
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
    if ((!oly && !olyErr) || (!team && !aresErr))
      return (
        <div className="hub">
          <Skeleton variant="card" label="Loading reviews" />
        </div>
      )
    // Land on the repo that needs me (platform first), so the sidebar badge leads somewhere real.
    const olyN = oly?.counts.needs_me || 0
    const aresN = team?.counts.needs_me || 0
    const firstOther = OTHER.find((o) => (otherNeed(o.slug) || 0) > 0)
    const first = olyN > 0 ? 'platform' : aresN > 0 ? 'team' : firstOther ? firstOther.slug : 'platform'
    return <Navigate to={`/reviews/${first}`} replace />
  }
  return (
    <div className="hub">
      <HubHeader
        eyebrow="Operate"
        title="Reviews"
        subtitle="Everything waiting on my review or merge, one tab per repo"
        tabs={[
          { to: '/reviews/platform', label: 'platform', n: oly?.counts.needs_me, live: counts.olyWorking > 0 },
          { to: '/reviews/team', label: 'team', n: team?.counts.needs_me, live: counts.aresWorking > 0 },
          ...OTHER.map((o) => ({
            to: `/reviews/${o.slug}`,
            label: o.label,
            n: otherNeed(o.slug),
            live: (otherRepo(o.slug)?.in_progress || []).some((p) => !!p.working),
          })),
        ]}
      />
      <PulseStrip jobs={(repo === 'team' ? team : repo === 'platform' ? oly : otherRepo(repo))?.cron_pulse?.jobs} />
      <StateLegend />
      {repo === 'team' ? (
        <AresSection tab={tab} />
      ) : repo === 'platform' ? (
        <PlatformSection tab={tab} />
      ) : (
        <RepoSection slug={repo} tab={tab} />
      )}
    </div>
  )
}

// Old /platform and /platform/<tab> bookmarks and relay links land on the same view.
export function PlatformRedirect() {
  const { tab } = useParams()
  return <Navigate to={tab ? `/reviews/platform/${tab}` : '/reviews/platform'} replace />
}
