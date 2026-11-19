// The Live tab of the Action Center: what is acting right now. It merges the live tackle sessions and the consumer's active builds feed
// into one list. It reads and links only. Stopping something is a side effect with its own design under standards/automation-safety.md
// (issue 308, item 5). The decisions live in lib/liveWork.ts so a test can load them without the browser.

import type { StatusTone } from '@kit'
import { EmptyState, Pill, Skeleton } from '@kit'
import { ageText } from '../lib/activeBuilds'
import { useActiveBuilds, useTackleSessions } from '../lib/data'
import { liveMode, liveRows } from '../lib/liveWork'
import { LoadError } from './StateBlocks'

const STATE_TONE: Record<string, StatusTone> = { stuck: 'warning', running: 'success', launching: 'neutral' }

export default function LiveWork() {
  const { data: sessions, error: sessionsErr } = useTackleSessions()
  const { data: builds, error: buildsErr } = useActiveBuilds()
  // A source that has failed is an error even while its last good copy is still held, so a stale list never reads as current.
  if (sessionsErr) return <LoadError title="Could not read the live sessions" error={sessionsErr} />
  if (buildsErr) return <LoadError title="Could not read the builds feed" error={buildsErr} />
  const mode = liveMode(sessions, builds, builds !== null)
  if (mode === 'loading') return <Skeleton variant="lines" count={4} label="Loading what is acting" />
  if (mode === 'error' && builds && builds.configured) {
    return <LoadError title="I could not read the build source" error={`${builds.error}. This is not the same as nothing acting.`} />
  }
  if (mode === 'quiet') return <EmptyState compact pose="idle" title="Nothing is acting right now." />
  const now = Date.now() / 1000
  return (
    <ul className="ac-live" aria-label="Acting now">
      {liveRows(sessions, builds).map((r) => (
        <li key={r.id} data-state={r.state} data-kind={r.kind}>
          <Pill tone={STATE_TONE[r.state] ?? 'neutral'}>{r.state[0].toUpperCase() + r.state.slice(1)}</Pill>
          <span className="ac-live-title">
            {r.url ? (
              <a href={r.url} target="_blank" rel="noreferrer noopener">
                {r.title}
              </a>
            ) : (
              r.title
            )}
          </span>
          {r.ticket && <span className="ac-live-ticket">{r.ticket}</span>}
          <span className="ac-live-age muted">{r.kind === 'build' ? 'build' : 'session'}{r.since !== null ? `, ${ageText(r.since, now)}` : ''}</span>
        </li>
      ))}
    </ul>
  )
}
