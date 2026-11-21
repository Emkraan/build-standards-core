// The counters row at the top of the Action Center: what waits on me, one tile per source, each a link to its page.
// The numbers and the order come from lib/counterRow.ts so a test can load them without the browser (issue 308, item 6).

import { Link } from 'react-router-dom'
import { useActionCounts } from '../lib/counts'
import { anythingWaiting, counterTiles } from '../lib/counterRow'
import { useApprovals, useJiraNeedsMe, useOneOnOnes } from '../lib/data'
import { peopleSlot } from '../lib/peopleSlot'
import { trackerSlot } from '../lib/trackerSlot'

export default function CounterRow() {
  const counts = useActionCounts()
  const { data: needs } = useJiraNeedsMe()
  const { data: approvals } = useApprovals()
  const { data: oo } = useOneOnOnes()
  // The work tile is the tracker slot's own number, so it exists only while the slot answers.
  const trackerWaiting = trackerSlot(needs) === 'on' ? (needs?.items.length ?? 0) + (approvals?.pending?.length ?? 0) : null
  // The 1:1 tile is the people slot's own number, so it exists only while the slot answers.
  const oneOnOneTopics = oo && peopleSlot(oo) === 'on' ? oo.people.reduce((n, p) => n + p.counts.open, 0) : null
  const tiles = counterTiles({ counts, trackerWaiting, oneOnOneTopics })
  const waiting = anythingWaiting(tiles)
  return (
    <section className="ac-counters" aria-label="What waits on me">
      <ul>
        {tiles.map((t) => (
          <li key={t.key}>
            <Link className="ac-counter" data-tone={t.count > 0 ? t.tone : 'none'} to={t.to}>
              <span className="ac-counter-n">{t.count}</span>
              <span className="ac-counter-l">{t.label}</span>
            </Link>
          </li>
        ))}
      </ul>
      {!waiting && <p className="muted ac-counters-calm">Nothing is waiting on me right now.</p>}
    </section>
  )
}
