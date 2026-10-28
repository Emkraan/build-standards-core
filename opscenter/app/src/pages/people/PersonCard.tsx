// The person picker card shared by the People pages (1:1 Board, This cycle, Member reviews,
// Yearly review): a kit Card with the kit Avatar, raised with .is-selected when picked, never an
// edge bar. The whole card is the button. Nested controls stop propagation themselves.
import type { CategoricalHue } from '@kit'
import { Avatar, Card } from '@kit'
import type { KeyboardEvent, ReactNode } from 'react'
import './people.css'

export function PersonCard({
  name,
  sub,
  aside,
  children,
  selected,
  tone,
  dim,
  onPick,
}: {
  name: string
  sub?: ReactNode
  /** Right column: a count, a badge or a mark. */
  aside?: ReactNode
  /** Extra rows under the subtitle (progress, a nested button). */
  children?: ReactNode
  selected: boolean
  /** Status wash (for example a meeting in progress). Ignored while selected. */
  tone?: CategoricalHue
  /** Quieter card (a meeting that is already over). */
  dim?: boolean
  onPick: () => void
}) {
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault()
      onPick()
    }
  }
  return (
    <Card
      interactive
      selected={selected}
      tone={selected ? undefined : tone}
      className={`pp-person${dim && !selected ? ' is-dim' : ''}`}
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      onClick={onPick}
      onKeyDown={onKeyDown}
    >
      <Avatar name={name} />
      <span className="pp-person-main">
        <span className="pp-person-name">{name}</span>
        {sub ? <span className="pp-person-sub">{sub}</span> : null}
        {children}
      </span>
      {aside ? <span className="pp-person-aside">{aside}</span> : null}
    </Card>
  )
}

/** A responsive row of PersonCards. */
export function PersonRail({ children, label }: { children: ReactNode; label: string }) {
  return (
    <div className="pp-rail" role="group" aria-label={label}>
      {children}
    </div>
  )
}

/** A thin completion meter (data, not an accent: a full rounded track with a fill). */
export function Meter({ pct, tone = 'accent', label }: { pct: number; tone?: 'accent' | 'success'; label: string }) {
  const v = Math.max(0, Math.min(100, pct))
  return (
    <span
      className="pp-meter"
      data-tone={tone}
      role="meter"
      aria-label={label}
      aria-valuenow={Math.round(v)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <span style={{ width: `${v}%` }} />
    </span>
  )
}
