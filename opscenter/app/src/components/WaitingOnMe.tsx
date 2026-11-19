// The waiting on me panel on the Action Center: every pull request that needs a decision from me, grouped by repo.
// It only lists and links. The click itself is on the Reviews card, which holds the one guarded Approve and merge flow
// (issue 308, item 8). The grouping lives in lib/waitingOnMe.ts so a test can load it without the browser.

import { Link } from 'react-router-dom'
import { useRepoReviews, usePlatformReviews, useTeamReviews } from '../lib/data'
import { waitingGroups, waitingTotal } from '../lib/waitingOnMe'

export default function WaitingOnMe() {
  const { data: platform } = usePlatformReviews()
  const { data: team } = useTeamReviews()
  const { data: other } = useRepoReviews()
  const groups = waitingGroups(platform, team, other)
  const total = waitingTotal(groups)
  if (!total) return null
  return (
    <section className="ac-waiting" aria-labelledby="ac-waiting-h">
      <h2 id="ac-waiting-h">
        Waiting on me now <span className="muted">({total})</span>
      </h2>
      {groups.map((g) => (
        <div className="ac-waiting-group" key={g.slug}>
          <h3>{g.label}</h3>
          <ul>
            {g.rows.map((r) => (
              <li key={`${g.slug}-${r.pr}`}>
                <Link to={r.to}>
                  <span className="ac-waiting-what">{r.what}</span>
                  <span className="ac-waiting-title">
                    #{r.pr} {r.title}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  )
}
