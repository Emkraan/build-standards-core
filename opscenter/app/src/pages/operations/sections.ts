// The Operations hub: everything we run, in sections with one tab per item (/operations/<section>/<item>, DESIGN.md 12.46).
// The section keys and titles are the problem list's defaults (problems.py: builds, automation, cost); the build items
// are whatever products the pipelines feed carries, so a consumer's products need no change here. Counts and the working
// state of an item come from the server's problem list and nowhere else.
import type { HubSection } from '@kit'
import { hubPath } from '@kit'
import type { Builds, Problems } from '../../lib/data'

export const OPERATIONS_BASE = '/operations'

// Items that are always part of the hub; the build items are added from the feed.
const AUTOMATION = [
  { key: 'jobs', label: 'Scheduled jobs' },
  { key: 'ci', label: 'CI, backup and GitHub' },
]
const COST = [
  { key: 'spend', label: 'LLM spend' },
  { key: 'core', label: 'Core consumption' },
]

const titleCase = (s: string) => s.replace(/[_-]+/g, ' ').replace(/^./, (c) => c.toUpperCase())

/** The build items: the products of the pipelines feed, named by the problem list when it has them. */
export function buildItems(builds: Builds | null | undefined, problems: Problems | null | undefined): { key: string; label: string }[] {
  const out: { key: string; label: string }[] = []
  const add = (key: string, label?: string) => {
    if (key && !out.some((i) => i.key === key)) out.push({ key, label: label || titleCase(key) })
  }
  for (const p of problems?.items ?? []) if (p.section === 'builds') add(p.item, p.label)
  for (const p of builds?.pipelines ?? []) add(p.product, problems?.items.find((i) => i.section === 'builds' && i.item === p.product)?.label)
  return out
}

/** The sections with their counts and working state from the problem list. */
export function operationsSections(builds: Builds | null | undefined, problems: Problems | null | undefined): HubSection[] {
  const by = problems?.counts.by_item ?? {}
  const running = (section: string, key: string) => !!problems?.items.some((i) => i.section === section && i.item === key && i.running)
  const make = (section: string, label: string, items: { key: string; label: string }[]): HubSection => ({
    key: section,
    label,
    items: items.map((i) => ({ key: i.key, label: i.label, count: by[`${section}/${i.key}`] || undefined, live: running(section, i.key) || undefined })),
  })
  const builds_ = buildItems(builds, problems)
  return [
    ...(builds_.length ? [make('builds', 'Builds and releases', builds_)] : []),
    make('automation', 'Automation', AUTOMATION),
    make('cost', 'Cost and standards', COST),
  ]
}

/** Every item of the hub flat, for the command palette and the old-link redirects. */
export function operationsPath(sections: readonly HubSection[], key: string): string {
  return hubPath(OPERATIONS_BASE, sections, key)
}

/** Where an old route lands: /builds, /core and /infra/<tab> (the live tab and GitHub moved into CI). */
export const OLD_INFRA_TAB: Record<string, string> = {
  spend: 'spend',
  jobs: 'jobs',
  live: 'ci',
  ci: 'ci',
  github: 'ci',
}

/** The rail badge: the sum of the problem list's per-section counts, the same numbers the section tabs show. */
export function problemCount(problems: Problems | null | undefined): number {
  return Object.values(problems?.counts.by_section ?? {}).reduce((t, n) => t + n, 0)
}
