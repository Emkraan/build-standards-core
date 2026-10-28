import { Tabs as KitTabs } from '@kit'
import { useLocation, useNavigate } from 'react-router-dom'

export interface TabDef {
  to: string
  label: string
  n?: number
  end?: boolean
  // live = something under this tab is working right now (spinner next to the label)
  live?: boolean
}

/** The tab whose route owns the path: an exact match first, then the longest prefix (not `end`). */
export function activeTab(tabs: TabDef[], pathname: string): TabDef | undefined {
  const exact = tabs.find((t) => t.to === pathname)
  if (exact) return exact
  return tabs.filter((t) => !t.end && pathname.startsWith(`${t.to}/`)).sort((a, b) => b.to.length - a.to.length)[0]
}

// Route-backed tabs for the hub pages, rendered by the kit Tabs (raised neutral selection, arrow
// keys, scroll into view, edge fades). The selected tab is the current route, so deep links and
// reload keep it. small = the second-level row inside a hub section (Reviews > platform > Needs me).
export function Tabs({ tabs, small, label = 'Section tabs' }: { tabs: TabDef[]; small?: boolean; label?: string }) {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  // A bare hub path (/debt) shows its first tab, the same default the pages render.
  const current = activeTab(tabs, pathname) ?? tabs[0]
  return (
    <KitTabs
      label={label}
      variant={small ? 'pills' : 'default'}
      className={small ? 'oc-tabs oc-tabs-sm' : 'oc-tabs'}
      value={current?.to ?? ''}
      onChange={(to) => {
        if (to !== pathname) navigate(to)
      }}
      items={tabs.map((t) => ({
        id: t.to,
        label: t.label,
        badge:
          t.live || (t.n !== undefined && t.n > 0) ? (
            <>
              {t.live && <span className="spin tab-spin" role="img" aria-label="working" />}
              {t.n !== undefined && t.n > 0 && t.n}
            </>
          ) : undefined,
      }))}
    />
  )
}
