// Build time parameters of the app (local/params.json, passed to the build as VITE_ variables).
// A value that is not set falls back to a neutral default, never to an estate name.
import type { NavLayout } from './navLayout'
import { parseNavLayout } from './navLayout'

export const PRIMARY_REPO: string = import.meta.env.VITE_PRIMARY_REPO ?? 'owner/primary'
export const APP_SUBTITLE: string = import.meta.env.VITE_APP_SUBTITLE ?? ''
export const prUrl = (n: number | string | null): string => `https://github.com/${PRIMARY_REPO}/pull/${n}`
// The rail layout: labels, order, flat or grouped (lib/navLayout.ts, opscenter/DESIGN.md 12.72). Unset is the default flat rail.
export const NAV_LAYOUT: NavLayout = parseNavLayout(import.meta.env.VITE_NAV)
/** A page title is its rail label (ops-center-layout rule 22), so a consumer label from VITE_NAV renames both. */
export const pageTitle = (route: string, label: string): string => NAV_LAYOUT.labels[route] ?? label
