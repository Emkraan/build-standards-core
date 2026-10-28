// Small building blocks shared by the Infrastructure tabs, all on the kit: feed loading and error
// cards, the usage meter, the working pill, the chart tooltip and legend, key and value lists.
import type { StatusTone } from '@kit'
import { Card, CardHead, EmptyState, IconAlert, Pill, Skeleton } from '@kit'
import type { ReactNode } from 'react'
import type { Level } from './data'

/** Loading skeleton or error state for a whole feed, in the card the feed would fill. */
export function FeedPending({ title, error, what, tiles = false }: { title: string; error: string | null; what: string; tiles?: boolean }) {
  if (error)
    return (
      <Card>
        <CardHead title={title} />
        <EmptyState compact icon={<IconAlert />} hue="red" title={`${what} unavailable`} body={error} />
      </Card>
    )
  return (
    <div className="infra-stack">
      {tiles && (
        <div className="stat-grid">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} variant="card" label={i === 0 ? `Loading ${what.toLowerCase()}` : 'Loading'} />
          ))}
        </div>
      )}
      <Card>
        <CardHead title={title} />
        <Skeleton variant="table" count={5} columns={4} label={`Loading ${what.toLowerCase()}`} />
      </Card>
    </div>
  )
}

/** A usage meter: a track and a fill in the level's hue. */
export function Meter({ pct, level, label }: { pct: number; level: Level; label: string }) {
  const v = Math.max(0, Math.min(100, pct))
  return (
    <div
      className="infra-meter"
      data-level={level}
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(v)}
    >
      <span className="infra-meter-fill" style={{ width: `${v}%` }} />
    </div>
  )
}

/** A status pill. live = something is working right now (spinner ring before the label). */
export function StatePill({ tone, live, children }: { tone: StatusTone; live?: boolean; children: ReactNode }) {
  return (
    <Pill tone={tone} dot={!live} className={live ? 'ui-pill-live' : undefined}>
      {live && <span className="spin" aria-hidden="true" />}
      {children}
    </Pill>
  )
}

/** Muted explanatory text under a section. */
export function Note({ children }: { children: ReactNode }) {
  return <p className="infra-note">{children}</p>
}

/** A two-column key and value list. */
export function KeyValues({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="infra-kv">
      {rows.map(([k, v]) => (
        <div key={k} className="infra-kv-row">
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  )
}

interface TipEntry {
  name?: string | number
  value?: string | number | readonly (string | number)[]
  color?: string
  dataKey?: string | number | ((obj: unknown) => unknown)
}

/** Recharts tooltip on the kit surface. Pass as an element: content={<ChartTip format={usd} />}. */
export function ChartTip({
  active,
  payload,
  label,
  format,
}: {
  active?: boolean
  payload?: readonly TipEntry[]
  label?: string | number
  format: (n: number) => string
}) {
  if (!active || !payload?.length) return null
  const rows = payload.filter((p) => p.value !== undefined && p.value !== null)
  return (
    <div className="infra-tip">
      <div className="infra-tip-label">{label}</div>
      {rows.map((p) => (
        <div key={String(p.name)} className="infra-tip-row">
          <span className="infra-swatch" style={{ background: p.color }} aria-hidden="true" />
          <span className="infra-tip-name">{p.name}</span>
          <b>{format(Number(p.value))}</b>
        </div>
      ))}
    </div>
  )
}

/** A chart legend as kit-styled swatches. */
export function ChartLegend({ items }: { items: { label: string; color: string; line?: boolean }[] }) {
  return (
    <ul className="infra-legend" aria-label="Legend">
      {items.map((i) => (
        <li key={i.label}>
          <span className="infra-swatch" data-line={i.line ? '' : undefined} style={{ background: i.color }} aria-hidden="true" />
          {i.label}
        </li>
      ))}
    </ul>
  )
}
