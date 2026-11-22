// The Ops Center navigation: rail groups, their destinations and hues, and the sub-pages the
// command palette can jump to. One list feeds the rail, the palette and the G shortcuts.
import type { NavHue } from '@kit'
import type { ReactNode } from 'react'
import type { ExtensionPage } from '../lib/extensions'
import { extensionPath } from '../lib/extensions'
import { NAV_LAYOUT } from '../lib/config'
import type { NavLayout } from '../lib/navLayout'
import { arrange } from '../lib/navLayout'
import {
  IconBook,
  IconChart,
  IconFile,
  IconKanban,
  IconLink,
  IconMessage,
  IconPullRequest,
  IconServer,
  IconWrench,
  IconZap,
} from '../components/icons'

export type BadgeKey = 'action' | 'oneonone' | 'reviews' | 'jira' | 'knowledge' | 'debt' | 'operations' | 'links'

export interface NavDef {
  to: string
  label: string
  icon: ReactNode
  hue?: NavHue
  badge?: BadgeKey
  /** G then this key jumps here. */
  key: string
  /** Sub-pages (tabs) listed in the command palette. */
  pages?: { to: string; label: string }[]
  /** An optional slot: the item exists only while that slot is on (opscenter/DESIGN.md 12.14 and 12.67). */
  slot?: 'tracker' | 'people'
  /** A page a consumer added through the extension manifest (opscenter/DESIGN.md 12.69). It has no badge and no shortcut. */
  extension?: true
  /** The number a consumer page asks the rail to show beside it. */
  count?: number
}

// The rail items in the core's own order (one flat rail, opscenter/DESIGN.md 12.72). The layout parameter (lib/navLayout.ts) relabels,
// reorders or groups them. Completed lives inside Action Center, Review History inside Team. Work tracking holds Sprint / Needs me /
// Backlog / Changes (JSM approvals), and its badge counts only what waits on me (changes pending my approval).
export interface NavGroupDef {
  label: string
  items: NavDef[]
}

export const ITEMS: NavDef[] = [
  {
    to: '/action',
    label: 'Action Center',
    icon: <IconZap />,
    hue: 'brand',
    badge: 'action',
    key: 'a',
    pages: [{ to: '/action/completed', label: 'Completed' }],
  },
  {
    to: '/work',
    label: 'Work tracking',
    icon: <IconKanban />,
    hue: 'blue',
    badge: 'jira',
    key: 'j',
    slot: 'tracker',
    pages: [
      { to: '/work/needs-me', label: 'Tickets that need my call' },
      { to: '/work/backlog', label: 'Backlog' },
      { to: '/work/changes', label: 'Changes waiting on my approval' },
    ],
  },
  {
    to: '/reviews',
    label: 'Pull requests',
    icon: <IconPullRequest />,
    hue: 'teal',
    badge: 'reviews',
    key: 'r',
    pages: [
      { to: '/reviews/platform', label: 'platform' },
      { to: '/reviews/platform/mine', label: 'platform, my PRs' },
      { to: '/reviews/team', label: 'team' },
      { to: '/reviews/ops_center', label: 'ops center' },
      { to: '/reviews/build-standards-core', label: 'Core' },
    ],
  },
  {
    to: '/platform',
    label: 'Platform',
    icon: <IconServer />,
    hue: 'violet',
    badge: 'operations',
    key: 'i',
    pages: [
      { to: '/platform/builds', label: 'Builds and releases' },
      { to: '/platform/automation/jobs', label: 'Scheduled jobs' },
      { to: '/platform/automation/ci', label: 'CI, backup and GitHub' },
      { to: '/platform/cost/spend', label: 'LLM spend' },
      { to: '/platform/cost/core', label: 'Core consumption' },
    ],
  },
  { to: '/debt', label: 'Debt and improvements', icon: <IconWrench />, hue: 'amber', badge: 'debt', key: 'd' },
  // The people pages sit behind the people slot (opscenter/DESIGN.md 12.14): the items exist only while it is on.
  { to: '/people', label: '1:1s', icon: <IconMessage />, hue: 'green', badge: 'oneonone', key: 'o', slot: 'people' },
  {
    to: '/team',
    label: 'Team',
    icon: <IconChart />,
    hue: 'red',
    key: 't',
    slot: 'people',
    pages: [
      { to: '/team/members', label: 'Member reviews' },
      { to: '/team/yearly', label: 'Yearly review' },
      { to: '/team/history', label: 'Trends' },
    ],
  },
  {
    to: '/knowledge',
    label: 'Knowledge',
    icon: <IconBook />,
    hue: 'blue',
    badge: 'knowledge',
    key: 'k',
    pages: [
      { to: '/knowledge/coverage', label: 'Doc coverage' },
      { to: '/knowledge/history', label: 'History' },
    ],
  },
  // Project trackers and the SBAR plan library from state/plans. Messages are never tracked.
  { to: '/plans', label: 'Plans', icon: <IconFile />, hue: 'teal', key: 'f' },
  // The admin consoles and references.
  { to: '/links', label: 'Links', icon: <IconLink />, hue: 'green', badge: 'links', key: 'l' },
]

export const NAV: NavDef[] = ITEMS

/** The rail a viewer sees: an item behind a slot that is not on is dropped, a consumer page follows the core items, and the layout parameter relabels, orders and groups them. */
export function groupsFor(people: boolean, tracker = true, extra: ExtensionPage[] = [], layout: NavLayout = NAV_LAYOUT): NavGroupDef[] {
  const shown = [
    ...ITEMS.filter((i) => (i.slot !== 'people' || people) && (i.slot !== 'tracker' || tracker)),
    ...extra.map(extensionItem),
  ]
  return arrange(shown, layout).map((g) => ({
    label: g.label,
    items: g.items.map((i) => ({ ...i, pages: i.pages?.map((p) => ({ to: p.to, label: `${i.label}: ${p.label}` })) })),
  }))
}

/** A consumer page as a rail item. It comes after the core items of its group, so it never moves one, and it takes no G shortcut. */
function extensionItem(p: ExtensionPage): NavDef {
  return { to: extensionPath(p.id), label: p.title, icon: <IconLink />, hue: 'blue', key: '', extension: true, count: p.count ?? 0 }
}

/** The rail entry that owns a path (for the active marker and the header title). */
export function navFor(pathname: string): NavDef | undefined {
  return groupsFor(true, true)
    .flatMap((g) => g.items)
    .find((n) => pathname === n.to || pathname.startsWith(`${n.to}/`))
}
