// a card whose PR waits on another PR. The server decides it (pr_deps.py): which PRs it
// waits on, what each one needs next, and which one to do first. These cards are not counted on
// Needs me and keep only Approve anyway, because approving now would likely fail or be redone.
import type { DepView } from '../lib/data'
import { prUrl } from '../lib/config'
import { Line, Tag } from '../pages/reviews/parts'

const ref = (n: number, url?: string) => (
  <a href={url || prUrl(n)} target="_blank" rel="noreferrer">
    #{n}
  </a>
)

/** "#347" while it is open, "#347 Owner apply" once merged with a step still owed. */
const stepOf = (v: DepView, n: number) => v.steps?.[String(n)] || v.waiting.find((w) => w.pr === n)?.step || ''

/** "Do this first: #N" plus one "Waiting on #N: <what #N needs next>" line per unmet parent. */
export function DepWaitLines({ v }: { v: DepView }) {
  const urls = Object.fromEntries(v.waiting.map((w) => [w.pr, w.url]))
  return (
    <>
      <Line>
        <b>
          Do this first:{' '}
          {v.first.map((n, i) => (
            <span key={n}>
              {i > 0 && ', '}
              {ref(n, urls[n])}
              {stepOf(v, n) && ` ${stepOf(v, n)}`}
            </span>
          ))}
          .
        </b>
        {v.chain.length > 1 && (
          <>
            {' '}
            Order:{' '}
            {v.chain.map((n, i) => (
              <span key={n}>
                {i > 0 && ', then '}
                {ref(n, urls[n])}
                {stepOf(v, n) && ` ${stepOf(v, n)}`}
              </span>
            ))}
            , then this PR.
          </>
        )}
      </Line>
      {v.waiting.map((w) => (
        <Line key={w.pr}>
          Waiting on {ref(w.pr, w.url)}: {w.need}
        </Line>
      ))}
      {v.notes.map((n) => (
        <Line key={n}>{n}</Line>
      ))}
    </>
  )
}

/** The status tag for a card that waits on another PR. */
export function DepTag({ v }: { v: DepView }) {
  return <Tag tone="warn">waits on {v.waiting.map((w) => (w.step ? `#${w.pr} ${w.step}` : `#${w.pr}`)).join(', ')}</Tag>
}

export function UnblocksLine({ prs }: { prs: number[] }) {
  if (prs.length === 0) return null
  return (
    <Line>
      <b>Do this first.</b>{' '}
      {prs.map((n, i) => (
        <span key={n}>
          {i > 0 && (i === prs.length - 1 ? ' and ' : ', ')}
          {ref(n)}
        </span>
      ))}{' '}
      {prs.length === 1 ? 'waits' : 'wait'} on it.
    </Line>
  )
}
