// The active builds panel on the Action Center: agent work that is running, stuck, failed or finished, from the consumer's own feed.
// It reads and links only. A Stop action is held back until it has its own design under standards/automation-safety.md (issue 308,
// items 7 and 26). The decisions live in lib/activeBuilds.ts so a test can load them without the browser.

import { useActiveBuilds } from '../lib/data'
import { orderedBuilds, panelMode, rowAge, safeLink, stateWord, summaryLine } from '../lib/activeBuilds'

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
            return (
              <li key={b.id} data-state={b.state}>
                <span className="ac-builds-state">{stateWord(b.state)}</span>
                <span className="ac-builds-title">{title}</span>
                <span className="ac-builds-age muted">{[b.activity, rowAge(b, now)].filter(Boolean).join(', ')}</span>
              </li>
            )
          })}
        </ul>
      )}
      {data.truncated > 0 && <p className="muted ac-builds-note">{data.truncated} more not shown.</p>}
    </section>
  )
}
