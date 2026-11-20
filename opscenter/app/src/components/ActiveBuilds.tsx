// The active builds panel: agent work that is running, stuck, failed or finished, from the consumer's own feed. It shows on the Action Center
// and on the Operations overview. A row can carry the pull request that holds the work and one plain sentence on what happened or what to do.
// It reads and links only. A Stop action is held back until it has its own design under standards/automation-safety.md (issue 308,
// items 7 and 26). The decisions live in lib/activeBuilds.ts so a test can load them without the browser.

import { useActiveBuilds } from '../lib/data'
import { orderedBuilds, panelMode, prLine, rowAge, rowNote, safeLink, stateWord, summaryLine } from '../lib/activeBuilds'
import './ActiveBuilds.css'

export default function ActiveBuilds() {
  const { data } = useActiveBuilds()
  const mode = panelMode(data)
  if (mode === 'hidden' || !data || !data.configured) return null
  const now = Date.now() / 1000
  const summary = summaryLine(data.counts)
  return (
    <section className="ac-builds" aria-labelledby="ac-builds-h">
      <h2 id="ac-builds-h">
        Active builds {summary && <span className="muted">({summary})</span>}
      </h2>
      {mode === 'error' && (
        <p className="ac-builds-note" role="status">
          I could not read the build source: {data.error}. This is not the same as nothing running.
        </p>
      )}
      {mode === 'quiet' && <p className="muted ac-builds-note">Nothing is running, stuck or failed.</p>}
      {mode === 'list' && (
        <ul>
          {orderedBuilds(data.builds).map((b) => {
            const href = safeLink(b.url)
            const title = href ? (
              <a href={href} target="_blank" rel="noreferrer noopener">
                {b.title}
              </a>
            ) : (
              <span>{b.title}</span>
            )
            const pr = prLine(b.pr)
            const note = rowNote(b, now)
            return (
              <li key={b.id} data-state={b.state}>
                <span className="ac-builds-state">{stateWord(b.state)}</span>
                <span className="ac-builds-title">{title}</span>
                <span className="ac-builds-age muted">{[b.activity, rowAge(b, now)].filter(Boolean).join(', ')}</span>
                {pr && (
                  <span className="ac-builds-pr">
                    {pr.href ? (
                      <a
                        className="ac-builds-pr-link"
                        href={pr.href}
                        target="_blank"
                        rel="noreferrer noopener"
                        aria-label={`Pull request ${pr.number}, opens the pull request`}
                      >
                        #{pr.number}
                      </a>
                    ) : (
                      <span className="ac-builds-pr-num">#{pr.number}</span>
                    )}
                    <span className="muted">{pr.text}</span>
                  </span>
                )}
                {note && <p className="ac-builds-detail muted">{note}</p>}
              </li>
            )
          })}
        </ul>
      )}
      {data.truncated > 0 && <p className="muted ac-builds-note">{data.truncated} more not shown.</p>}
    </section>
  )
}
