// Live counts for sidebar and tab badges. Reads the same bundled JSON and the
// same localStorage keys the pages write, so a click on a page updates the
// badge immediately.

import { useAresReviews, useBadges, useLocalStore, useplatformReviews, useRepoReviews } from './data'
import { problemCount } from '../pages/operations/sections'
import { aresPrWorking, olyPrWorking } from './ownPrs'

export { aresPrWorking, olyMineNeedsMe, olyPrWorking } from './ownPrs'

type HandledMap = Record<string, { act: string; at: string; until?: string }>

// Matches STUCK_MS in pages/Knowledge.tsx: a decision the applier has not recorded by then comes back.
const KC_STUCK_MS = 10 * 60 * 1000

export interface ActionCounts {
  actions: number
  debt: number
  knowledge: number
  knowledgePending: number
  knowledgeDocs: number
  links: number
  // Operations: the sum of the problem list's per-section counts (one source for the rail, the tabs and the Overview).
  operations: number
  operationsItems: string[]
  // Alerts tab: job runs I have not acknowledged (server truth from /api/badges).
  alerts: number
  platform: number
  team: number
  reviews: number
  other: number
  // my open PRs across both repos, and how many have something running on them right now
  myPrs: number
  myPrsWorking: number
  olyMine: number
  olyWorking: number
  aresMine: number
  aresWorking: number
}

export function useActionCounts(): ActionCounts {
  // Server truth in one small payload (/api/badges): Action Center fps the server has not handled.
  // Local entries are offline clicks not yet pushed, the page writes them through on its next mount.
  const [local] = useLocalStore<HandledMap>('ac-handled-v1', {})
  // Knowledge proposals I approved or rejected on the page (same key Knowledge.tsx writes).
  const [kcSent] = useLocalStore<Record<string, { act: string; at: string }>>('kc-sent-v1', {})
  const { data: badges } = useBadges()
  const handled: HandledMap = local

  // platform reviews 'Needs me' (escalations + held terraform plans, merged per PR server-side)
  const { data: oly } = useplatformReviews()
  // team 'Needs me' (lane escalations + my green PRs waiting on my admin merge)
  const { data: team } = useAresReviews()
  // My other repos (backup, UI standard): failing, stale or review-requested PRs
  const { data: other } = useRepoReviews()
  const now = Date.now()
  const isHandled = (fp: string) => {
    const h = handled[fp]
    if (!h) return false
    if (h.act === 'snoozed' && h.until) return new Date(h.until).getTime() > now
    return h.act !== 'snoozed'
  }
  const olyMinePrs = oly?.my_prs || []
  const aresMinePrs = [...(team?.needs_me || []), ...(team?.in_progress || [])].filter((p) => p.mine)
  const olyWorking = olyMinePrs.filter(olyPrWorking).length
  const aresWorking = aresMinePrs.filter(aresPrWorking).length
  // Knowledge: proposals still staged minus ones I decided on the page in the last 10 minutes
  // (the applier records them within a minute, after that the page treats them as stuck and they count again).
  const knowledgePending = (badges?.knowledge_pending || []).filter((fp) => {
    const s = kcSent[fp]
    return !s || now - Date.parse(s.at) > KC_STUCK_MS
  }).length
  const knowledgeDocs = badges?.knowledge_docs ?? (badges?.knowledge_pending ? 0 : badges?.knowledge || 0)
  return {
    actions: (badges?.action_open || []).filter((fp) => !isHandled(fp)).length,
    debt: badges?.debt || 0,
    knowledge: knowledgePending + knowledgeDocs,
    knowledgePending,
    knowledgeDocs,
    links: badges?.links || 0,
    operations: problemCount(badges?.problems),
    operationsItems: (badges?.problems?.items || []).filter((i) => i.tone !== 'healthy').map((i) => `${i.label}: ${i.headline}`),
    alerts: badges?.alerts || 0,
    platform: oly?.counts.needs_me || 0,
    team: team?.counts.needs_me || 0,
    other: other?.counts.needs_me || 0,
    reviews: (oly?.counts.needs_me || 0) + (team?.counts.needs_me || 0) + (other?.counts.needs_me || 0),
    myPrs: olyMinePrs.length + aresMinePrs.length,
    myPrsWorking: olyWorking + aresWorking,
    olyMine: olyMinePrs.length,
    olyWorking,
    aresMine: aresMinePrs.length,
    aresWorking,
  }
}
