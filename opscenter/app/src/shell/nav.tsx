// The Ops Center navigation: rail groups, their destinations and hues, and the sub-pages the
// command palette can jump to. One list feeds the rail, the palette and the G shortcuts.
import type { NavHue } from '@kit'
import type { ReactNode } from 'react'
import {
  IconBook,
  IconChart,
  IconFile,
  IconKanban,
  IconLink,
  IconMessage,
  IconPackage,
  IconPullRequest,
  IconServer,
  IconWrench,
  IconZap,
} from '../components/icons'

export type BadgeKey = 'action' | 'oneonone' | 'reviews' | 'jira' | 'knowledge' | 'debt' | 'infra' | 'builds' | 'core' | 'links'

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
}

// Completed lives inside Action Center, Review History inside Team Performance. Jira holds
// Sprint / Backlog / Changes (JSM approvals), and its badge counts only what waits on me
// (changes pending my approval).
export const GROUPS: { label: string; items: NavDef[] }[] = [
  {
    label: 'Operate',
    items: [
      {
        to: '/action',
        label: 'Action Center',
        icon: <IconZap />,
        hue: 'brand',
        badge: 'action',
        key: 'a',
        pages: [{ to: '/action/completed', label: 'Action Center: Completed' }],
      },
      {
        to: '/jira',
        label: 'Jira',
        icon: <IconKanban />,
        hue: 'blue',
        badge: 'jira',
        key: 'j',
        pages: [
          { to: '/jira/needs-me', label: 'Jira: Tickets that need my call' },
          { to: '/jira/backlog', label: 'Jira: Backlog' },
          { to: '/jira/changes', label: 'Jira: Changes waiting on my approval' },
        ],
      },
      {
        to: '/reviews',
        label: 'Reviews',
        icon: <IconPullRequest />,
        hue: 'teal',
        badge: 'reviews',
        key: 'r',
        pages: [
          { to: '/reviews/platform', label: 'Reviews: platform' },
          { to: '/reviews/platform/mine', label: 'Reviews: platform, my PRs' },
          { to: '/reviews/team', label: 'Reviews: team' },
          { to: '/reviews/ops_center', label: 'Reviews: ops center' },
          { to: '/reviews/build-standards-core', label: 'Reviews: Core' },
        ],
      },
      { to: '/debt', label: 'Debt & IMP', icon: <IconWrench />, hue: 'amber', badge: 'debt', key: 'd' },
    ],
  },
  {
    label: 'People',
    items: [
      { to: '/people', label: '1:1 Board', icon: <IconMessage />, hue: 'green', badge: 'oneonone', key: 'o' },
      {
        to: '/team',
        label: 'Team Performance',
        icon: <IconChart />,
        hue: 'red',
        key: 't',
        pages: [
          { to: '/team/members', label: 'Team: Member reviews' },
          { to: '/team/yearly', label: 'Team: Yearly review' },
          { to: '/team/history', label: 'Team: Trends' },
        ],
      },
    ],
  },
  {
    label: 'Knowledge',
    items: [
      {
        to: '/knowledge',
        label: 'Knowledge',
        icon: <IconBook />,
        hue: 'blue',
        badge: 'knowledge',
        key: 'k',
        pages: [
          { to: '/knowledge/coverage', label: 'Knowledge: Doc coverage' },
          { to: '/knowledge/history', label: 'Knowledge: History' },
        ],
      },
      // Project trackers and the SBAR plan library from state/plans. Messages are never tracked.
      { to: '/plans', label: 'Plans', icon: <IconFile />, hue: 'teal', key: 'f' },
      // The firm admin consoles and references (replaced the M&M Links Google Site, 2026-10-26).
      { to: '/links', label: 'Links', icon: <IconLink />, hue: 'green', badge: 'links', key: 'l' },
    ],
  },
  {
    label: 'Platform',
    items: [
      { to: '/builds', label: 'Builds', icon: <IconPackage />, hue: 'violet', badge: 'builds', key: 'b' },
      { to: '/core', label: 'Core consumption', icon: <IconPackage />, hue: 'blue', badge: 'core', key: 'c' },
      {
        to: '/infra',
        label: 'Infrastructure',
        icon: <IconServer />,
        badge: 'infra',
        key: 'i',
        pages: [
          { to: '/infra/spend', label: 'Infrastructure: LLM spend' },
          { to: '/infra/jobs', label: 'Infrastructure: Scheduled jobs' },
          { to: '/infra/live', label: 'Infrastructure: Live jobs' },
          { to: '/infra/ci', label: 'Infrastructure: CI and backup' },
          { to: '/infra/github', label: 'Infrastructure: GitHub' },
        ],
      },
    ],
  },
]

export const NAV: NavDef[] = GROUPS.flatMap((g) => g.items)

/** The rail entry that owns a path (for the active marker and the header title). */
export function navFor(pathname: string): NavDef | undefined {
  return NAV.find((n) => pathname === n.to || pathname.startsWith(`${n.to}/`))
}
