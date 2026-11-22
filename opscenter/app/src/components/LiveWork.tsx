// The Live tab of the Action Center: what is acting right now. It merges the live tackle sessions and the consumer's active builds feed
// into one list. It reads and links only. Stopping something is a side effect with its own design under standards/automation-safety.md
// (issue 308, item 5). The decisions live in lib/liveWork.ts so a test can load them without the browser.

import type { SegmentedOption, StatusTone } from '@kit'
import { EmptyState, Pill, Segmented, Skeleton } from '@kit'
import { useState } from 'react'
import { ageText } from '../lib/activeBuilds'
import { useActiveBuilds, useTackleSessions } from '../lib/data'
import type { LiveState } from '../lib/liveWork'
import { firstLiveState, LIVE_STATE_LABEL, LIVE_STATES, liveByState, liveMode } from '../lib/liveWork'
import { LoadError } from './StateBlocks'

const STATE_TONE: Record<string, StatusTone> = { stuck: 'warning', running: 'success', launching: 'neutral', failed: 'danger', finished: 'neutral' }

export default function LiveWork() {
  const [picked, setPicked] = useState<LiveState | null>(null)
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
  const by = liveByState(sessions, builds)
  const view = picked ?? firstLiveState(by)
  const options: SegmentedOption<LiveState>[] = LIVE_STATES.map((k) => ({ value: k, label: `${LIVE_STATE_LABEL[k]} ${by[k].length}` }))
  return (
    <>
    <Segmented label="Work by state" options={options} value={view} onChange={setPicked} />
    {by[view].length === 0 && <EmptyState compact pose="idle" title={`Nothing is ${LIVE_STATE_LABEL[view].toLowerCase()}.`} />}
    <ul className="ac-live" aria-label="Acting now">
      {by[view].map((r) => (
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
    </>
  )
}
