// Header facts that ride on every page: the next 1:1 chip and the sync indicator, plus the live
// feed strip items built from the same counts the rail badges use.
import type { FeedItem, HealthLine } from '@kit'
import { Link, useNavigate } from 'react-router-dom'
import { awayAnnouncement, type TeamAwayData } from '../components/TeamAway'
import { useActionCounts } from '../lib/counts'
import type { OneOnOnes } from '../lib/data'
import {
  relTime,
  useApprovals,
  useBrowserStatus,
  useData,
  useDocCoverage,
  useEngBacklog,
  useLlmFallback,
  useNow,
  useOneOnOnes,
} from '../lib/data'

interface FeedFreeze {
  in_freeze: boolean
  current: { name: string; start: string; end: string; exception?: string } | null
  next: { name: string; start: string; end: string; days_out: number } | null
}
const md = (iso: string) => new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
const SEVERITY: Record<FeedItem['tone'], number> = { critical: 0, warning: 1, info: 2, success: 3 }

/** Change-freeze status as a feed announcement (CAB workbook mirror, freeze.json). Red in a window, amber inside 7 days. */
function freezeAnnouncement(f: FeedFreeze | null): Omit<FeedItem, 'id'> | null {
  if (!f) return null
  if (f.in_freeze && f.current) {
    return {
      tone: 'critical',
      title: `Change freeze is on: ${f.current.name}, until ${md(f.current.end)}.`,
      body: `${f.current.exception || 'Break-fix only'}.`,
    }
  }
  if (!f.next) return { tone: 'success', title: 'No change freeze.', body: 'Nothing on the CAB calendar.' }
  const d = f.next.days_out
  const span = `${f.next.name}, ${md(f.next.start)} to ${md(f.next.end)}.`
  if (d <= 7) return { tone: 'warning', title: `Change freeze starts in ${d} day${d === 1 ? '' : 's'}.`, body: span }
  return { tone: 'info', title: 'No change freeze.', body: `Next: ${span} ${d} days out.` }
}

function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

function nextMeeting(data: OneOnOnes | null, now: number) {
  if (!data) return null
  const upcoming = data.people
    .filter((p) => p.meeting && new Date(p.meeting.end || p.meeting.start).getTime() > now)
    .sort((a, b) => new Date(a.meeting?.start ?? 0).getTime() - new Date(b.meeting?.start ?? 0).getTime())
  const p = upcoming[0]
  if (!p?.meeting) return { p: null, live: false, mins: 0, rel: '' }
  const s = new Date(p.meeting.start).getTime()
  const live = now >= s
  const mins = Math.max(0, Math.round((s - now) / 60000))
  const rel = live ? 'now' : mins < 60 ? `in ${mins}m` : `in ${Math.floor(mins / 60)}h ${mins % 60}m`
  return { p, live, mins, rel }
}

export function NextOneOnOne() {
  const now = useNow(15_000)
  const { data } = useOneOnOnes()
  const m = nextMeeting(data, now)
  if (!m) return null
  const { p, live, mins, rel } = m
  if (!p?.meeting) return <span className="next-chip idle">No more 1:1s today</span>
  return (
    <Link to={`/people?p=${p.first.toLowerCase()}`} className={`next-chip ${live ? 'live' : mins <= 30 ? 'soon' : ''}`}>
      <span className="next-dot" aria-hidden="true" />
      <span className="next-chip-text">
        Next 1:1 <b>{p.first}</b> {clock(p.meeting.start)} &middot; {rel} &middot; {p.counts.open} open
      </span>
    </Link>
  )
}

export function SyncChip() {
  const { data: oo, error } = useOneOnOnes()
  useNow(30_000)
  if (error) return <span className="sync-chip stale">sync failed</span>
  if (!oo) return null
  return (
    <span className="sync-chip" data-tip="When the 1:1 board and its feeds last synced">
      synced {relTime(oo.generated_utc)}
    </span>
  )
}

/** Health line and the items that need me, for the kit FeedStrip under the header. */
export function useFeed(refreshedEt: string | undefined): { health: HealthLine; items: FeedItem[] } {
  const nav = useNavigate()
  const now = useNow(30_000)
  const counts = useActionCounts()
  const { data: oo, error: ooErr } = useOneOnOnes()
  const { data: approvals } = useApprovals()
  const { data: docs } = useDocCoverage()
  const { data: eng } = useEngBacklog()
  const { data: fb } = useLlmFallback()
  const { data: br } = useBrowserStatus()
  const { data: ac } = useData<{ headline?: string; team_away?: TeamAwayData }>('action-center.json')
  const { data: freeze } = useData<FeedFreeze>('freeze.json')
  const health: HealthLine = ooErr
    ? { status: 'down', label: 'API unreachable, retrying' }
    : { status: 'ok', label: refreshedEt ? `Live, data refreshed ${refreshedEt}` : 'Live' }
  const items: FeedItem[] = []
  if (fb?.active) {
    items.push({
      id: 'fallback',
      tone: 'critical',
      title: 'Enterprise is billing Hermes while Team has headroom.',
      body: 'Open LLM spend.',
      onOpen: () => nav('/operations/cost/spend'),
    })
  }
  if (br?.alert) {
    items.push({
      id: 'browser',
      tone: 'critical',
      title: br.alert === 'visible' ? 'The automation browser is still showing a window.' : 'The automation browser is down.',
    })
  }
  if (counts.actions > 0) {
    items.push({
      id: 'action',
      tone: 'warning',
      title: `${counts.actions} Action Center item${counts.actions === 1 ? ' needs' : 's need'} me.`,
      body: ac?.headline,
      onOpen: () => nav('/action'),
    })
  }
  if (counts.reviews > 0) {
    items.push({
      id: 'reviews',
      tone: 'warning',
      title: `Reviews: ${counts.reviews} need me.`,
      body: `platform ${counts.platform}, team ${counts.team}, other repos ${counts.other}.`,
      onOpen: () => nav('/reviews'),
    })
  }
  const pending = approvals?.pending.length || 0
  if (pending > 0) {
    items.push({
      id: 'changes',
      tone: 'info',
      title: `JSM: ${pending} change${pending === 1 ? '' : 's'} waiting on my approval.`,
      onOpen: () => nav('/jira/changes'),
    })
  }
  const m = nextMeeting(oo, now)
  if (m?.p?.meeting) {
    const p = m.p
    items.push({
      id: 'oneonone',
      tone: m.live ? 'success' : 'info',
      title: `Next 1:1 with ${p.first} ${m.rel}.`,
      body: `${clock(p.meeting?.start || '')}, ${p.counts.open} open topic${p.counts.open === 1 ? '' : 's'}.`,
      onOpen: () => nav(`/people?p=${p.first.toLowerCase()}`),
    })
  }
  const decide = eng ? eng.items.filter((i) => i.bucket === 'decide' && !i.snoozed).length : 0
  if (decide > 0) {
    items.push({
      id: 'debt',
      tone: 'info',
      title: `${decide} improvement${decide === 1 ? '' : 's'} waiting on my decision.`,
      onOpen: () => nav('/debt'),
    })
  }
  const proposals = counts.knowledgePending
  if (proposals > 0) {
    items.push({
      id: 'knowledge',
      tone: 'info',
      title: `${proposals} Knowledge proposal${proposals === 1 ? '' : 's'} waiting on my approval.`,
      onOpen: () => nav('/knowledge'),
    })
  }
  const gaps = docs?.open_count || 0
  if (gaps > 0) {
    items.push({
      id: 'docs',
      tone: 'info',
      title: `${gaps} documentation gap${gaps === 1 ? '' : 's'} need me.`,
      onOpen: () => nav('/knowledge/coverage'),
    })
  }
  const frz = freezeAnnouncement(freeze)
  if (frz) items.push({ id: 'freeze', ...frz })
  const away = awayAnnouncement(ac?.team_away, new Date(now))
  if (away) items.push({ id: 'team-away', ...away, onOpen: () => nav('/people') })
  // Most severe first so a freeze or someone out today is the first thing the presenter says.
  items.sort((a, b) => SEVERITY[a.tone] - SEVERITY[b.tone])
  return { health, items }
}
