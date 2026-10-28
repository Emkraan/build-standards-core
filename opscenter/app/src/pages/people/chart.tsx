// Chart helpers for the People pages: colours resolved from the live tokens through the kit chart
// theme (so every chart recolours on a theme switch), and one theme-aware tooltip callout.
import type { CategoricalHue, ChartTheme } from '@kit'
import { categoricalPalette, useChartTheme } from '@kit'
import { useMemo } from 'react'
import './people.css'

export interface PeopleChart {
  t: ChartTheme
  /** Bright colour of a categorical hue (falls back to the first series colour when withheld). */
  hue: (h: CategoricalHue) => string
  axisTick: { fill: string; fontSize: number }
}

export function usePeopleChart(): PeopleChart {
  const t = useChartTheme()
  return useMemo(() => {
    const pal = categoricalPalette()
    const map = new Map(pal.map((s) => [s.name, s.color]))
    return {
      t,
      hue: (h: CategoricalHue) => map.get(h) || t.series[0] || 'currentColor',
      axisTick: { fill: t.axis, fontSize: 11 },
    }
  }, [t])
}

interface TipRow {
  name?: string | number
  value?: unknown
  color?: string
  dataKey?: unknown
}

/** Tooltip callout: passed as an element (`content={<ChartTip />}`), Recharts fills the props. */
export function ChartTip({
  active,
  payload,
  label,
  suffix,
}: {
  active?: boolean
  payload?: readonly TipRow[]
  label?: unknown
  suffix?: string
}) {
  if (!active || !payload?.length) return null
  return (
    <div className="pp-tip">
      {label !== undefined && label !== '' ? <div className="pp-tip-label">{String(label)}</div> : null}
      {payload.map((p) => (
        <div key={String(p.dataKey ?? p.name)} className="pp-tip-row">
          <i style={{ background: p.color }} aria-hidden="true" />
          <span>{p.name}</span>
          <b>
            {String(p.value ?? '')}
            {suffix || ''}
          </b>
        </div>
      ))}
    </div>
  )
}

/** A small legend under a chart, dots in the series colours. */
export function ChartLegend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <div className="pp-legend">
      {items.map((x) => (
        <span key={x.label}>
          <i style={{ background: x.color }} aria-hidden="true" />
          {x.label}
        </span>
      ))}
    </div>
  )
}
