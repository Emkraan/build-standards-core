// The waiting on me panel: every pull request that needs a decision from me, grouped by repo, each row saying what the click is
// and linking to its card on the Reviews page, where the one guarded Approve and merge flow lives. Nothing here writes. The Action
// Center shows the list and the Reviews card does the work, so there is no second, faster path around its typed confirmation and
// its maintenance window check (issue 308, item 8). The grouping is here so a test can load it without the browser.

export interface WaitingRow {
  pr: number
  title: string
  // What I have to do, in the lane's own words.
  what: string
  // Where the card is: the Reviews page for that repo.
  to: string
}

export interface WaitingGroup {
  slug: string
  label: string
  rows: WaitingRow[]
}

export interface PlatformInput {
  needs_me_rows?: { pr: number | null; title: string; what: string }[]
}
export interface TeamInput {
  needs_me: { pr: number; title: string; kind?: string; why?: string }[]
}
export interface RepoInput {
  repos: { slug: string; repo: string; needs_me: { pr: number; title: string; kind?: string; why?: string }[] }[]
}

// What each team lane kind asks of me, the same words the Reviews cards use on their buttons.
const TEAM_ASK: Record<string, string> = {
  escalated: 'Approve as me',
  signoff: 'Approve and merge',
  direction: 'Give it direction',
  ready_to_merge: 'Merge',
}
const REPO_ASK: Record<string, string> = {
  checks: 'Checks are failing',
  review: 'Review requested',
  stale: 'Stale, needs a look',
  conflict: 'Has a merge conflict',
}

/** One group per repo that has something waiting, platform first, then team, then the other repos in the order they were given. */
export function waitingGroups(platform: PlatformInput | null | undefined, team: TeamInput | null | undefined, other: RepoInput | null | undefined): WaitingGroup[] {
  const groups: WaitingGroup[] = []
  const platformRows = (platform?.needs_me_rows ?? [])
    .filter((r) => r.pr !== null)
    .map((r) => ({ pr: r.pr as number, title: r.title, what: r.what, to: '/reviews/platform' }))
  if (platformRows.length) groups.push({ slug: 'platform', label: 'Platform', rows: platformRows })
  const teamRows = (team?.needs_me ?? []).map((p) => ({
    pr: p.pr,
    title: p.title,
    what: TEAM_ASK[p.kind ?? ''] ?? p.why ?? 'Needs my decision',
    to: '/reviews/team',
  }))
  if (teamRows.length) groups.push({ slug: 'team', label: 'Team', rows: teamRows })
  for (const r of other?.repos ?? []) {
    const rows = r.needs_me.map((p) => ({
      pr: p.pr,
      title: p.title,
      what: REPO_ASK[p.kind ?? ''] ?? p.why ?? 'Needs my decision',
      to: `/reviews/${r.slug}`,
    }))
    if (rows.length) groups.push({ slug: r.slug, label: r.repo, rows })
  }
  return groups
}

/** How many rows wait in all, which is what the panel's heading says. */
export function waitingTotal(groups: WaitingGroup[]): number {
  return groups.reduce((n, g) => n + g.rows.length, 0)
}
