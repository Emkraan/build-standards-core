// The bottom tab bar under 901px (the reference oc-tabbar): the four pages I reach for on a phone and a Menu button that opens the rail
// drawer. Each tab says its count to a screen reader as ", <n> need me". It reads the same nav list and counts as the rail, so a slot that is
// off, or a consumer label from VITE_NAV, shows here too.
import { useShell } from '@kit'
import { NavLink } from 'react-router-dom'
import { IconMenu } from '@kit'
import type { NavDef } from '../shell/nav'

/** The pages the bar offers, in this order, when the rail has them. */
export const TABBAR_ROUTES = ['/action', '/reviews', '/work', '/platform'] as const

export function tabbarItems<T extends { to: string }>(items: T[]): T[] {
  return TABBAR_ROUTES.flatMap((r) => items.filter((i) => i.to === r))
}

export default function MobileTabBar({ items, count }: { items: NavDef[]; count: (n: NavDef) => number }) {
  const shell = useShell()
  return (
    <nav className="oc-tabbar" aria-label="Main">
      {tabbarItems(items).map((n) => {
        const c = count(n)
        return (
          <NavLink key={n.to} to={n.to} className="oc-tab">
            <span className="oc-tab-ic" aria-hidden="true">
              {n.icon}
            </span>
            <span className="oc-tab-label">{n.label}</span>
            {c > 0 && <span className="kit-sr-only">, {c} need me</span>}
          </NavLink>
        )
      })}
      <button type="button" className="oc-tab" onClick={() => shell?.setMobileOpen(true)} aria-label="Menu">
        <span className="oc-tab-ic" aria-hidden="true">
          <IconMenu />
        </span>
        <span className="oc-tab-label">Menu</span>
      </button>
    </nav>
  )
}
