// The firm link catalog, ingested 2026-10-26 from the retired M&M Links Google Site
// (sites.google.com/view/mnmlinks). The list lives in catalog.json so the weekly reachability
// check (link_health.py) reads the same file as the page and the Cmd K palette. Edit it by PR.
import type { MarkHue } from '@kit'
import catalog from './catalog.json'

export interface LinkItem {
  name: string
  url: string
  /** A short flag shown as a pill, for example On network or Retired. */
  note?: string
}

export interface LinkGroup {
  id: string
  title: string
  hue: MarkHue
  links: LinkItem[]
}

export const LINK_GROUPS: LinkGroup[] = catalog.groups as LinkGroup[]

/** The host shown beside a link and matched by the filter. */
export function hostOf(url: string): string {
  try {
    return new URL(url).host
  } catch {
    return url
  }
}

/** Two letter mark for a link tile: initials of the first two words, else the first two letters. */
export function monogram(name: string): string {
  const words = name
    .replace(/\(.*?\)/g, ' ')
    .split(/[\s/-]+/)
    .filter((w) => /[A-Za-z0-9]/.test(w))
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase()
  return (words[0] || name).slice(0, 2).toUpperCase()
}
