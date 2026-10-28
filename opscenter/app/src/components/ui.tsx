// Compatibility layer: the app's original primitive names, rendered by the shared kit
// (kit-core) so every page takes the standard look before it migrates. New code imports the kit
// directly. Pill keeps the live spinner the app needs (the kit has no working pill).
import type { CategoricalHue, StatTone, StatusTone } from '@kit'
import { CardHead, EmptyState, Card as KitCard, Pill as KitPill, StatTile } from '@kit'
import type { ReactNode } from 'react'
import './ui.css'

type Tone = 'good' | 'warn' | 'alert'

/** A titled card. `accent` washes it in a categorical hue (the .tone recipe, never an edge bar). */
export function Card({ title, sub, children, accent }: { title?: string; sub?: string; children: ReactNode; accent?: CategoricalHue }) {
  return (
    <KitCard tone={accent}>
      {title && <CardHead title={title} subtitle={sub} />}
      {children}
    </KitCard>
  )
}

const STAT_TONE: Record<Tone, StatTone> = { good: 'success', warn: 'warning', alert: 'danger' }

/** A hero KPI, rendered by the kit StatTile (the only stat primitive, web-ui.md rule 4). */
export function Kpi({ value, label, tone }: { value: string | number; label: string; tone?: Tone }) {
  return <StatTile value={value} label={label} tone={tone ? STAT_TONE[tone] : 'accent'} />
}

export function Progress({ pct, tone }: { pct: number; tone?: Tone }) {
  const t = tone || (pct >= 90 ? 'good' : pct >= 75 ? 'warn' : 'alert')
  return (
    <div className="progress">
      <div className={`progress-fill ${t}`} style={{ width: `${Math.max(0, Math.min(100, pct))}%` }} />
    </div>
  )
}

const PILL_TONE: Record<string, StatusTone> = { good: 'success', warn: 'warning', alert: 'danger', info: 'info', neutral: 'neutral' }

// live = something is actively working right now (spinner ring before the label).
export function Pill({
  children,
  tone,
  live,
}: {
  children: ReactNode
  tone?: 'good' | 'warn' | 'alert' | 'info' | 'neutral'
  live?: boolean
}) {
  return (
    <KitPill tone={PILL_TONE[tone || 'neutral']} className={live ? 'ui-pill-live' : undefined}>
      {live && <span className="spin" aria-hidden="true" />}
      {children}
    </KitPill>
  )
}

export function Tkt({ id }: { id: string }) {
  return (
    <a className="tkt" href={`https://atlassian_host/browse/${id}`} target="_blank" rel="noreferrer">
      {id}
    </a>
  )
}

/** A calm empty line inside a card, rendered by the kit EmptyState (compact). */
export function Empty({ children }: { children: ReactNode }) {
  if (typeof children === 'string') return <EmptyState compact title={children} />
  // EmptyState takes a plain-text title, so mixed content goes in the body slot.
  return (
    <div className="empty-state" data-compact="">
      <div className="empty-body">{children}</div>
    </div>
  )
}
