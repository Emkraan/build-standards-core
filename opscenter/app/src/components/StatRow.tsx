// The stat row of a page tab (the reference ds-stat-row): equal columns of tiles, each with an accent chip, a label, a value and an optional
// sub line. A tile with onClick is a button that filters the page. A zero value is muted, never coloured (ops-center-layout rule 22).
import type { ReactNode } from 'react'

export interface Stat {
  key: string
  label: string
  value: ReactNode
  sub?: ReactNode
  icon?: ReactNode
  /** Makes the tile a button, for a tile that filters the page. */
  onClick?: () => void
  active?: boolean
}

const isZero = (v: ReactNode) => v === 0 || v === '0'

export function StatRow({ stats, label = 'Summary' }: { stats: Stat[]; label?: string }) {
  if (stats.length === 0) return null
  return (
    <div className="ds-stat-row" role="group" aria-label={label} style={{ gridTemplateColumns: `repeat(${stats.length}, minmax(0, 1fr))` }}>
      {stats.map((s) => {
        const body = (
          <>
            {s.icon && (
              <span className="ds-stat-chip" aria-hidden="true">
                {s.icon}
              </span>
            )}
            <span className="ds-stat-body">
              <span className="ds-stat-label">{s.label}</span>
              <span className="ds-stat-value" data-zero={isZero(s.value) ? '' : undefined}>
                {s.value}
              </span>
              {s.sub && <span className="ds-stat-sub">{s.sub}</span>}
            </span>
          </>
        )
        return s.onClick ? (
          <button key={s.key} type="button" className="ds-stat" aria-pressed={!!s.active} onClick={s.onClick}>
            {body}
          </button>
        ) : (
          <div key={s.key} className="ds-stat">
            {body}
          </div>
        )
      })}
    </div>
  )
}
