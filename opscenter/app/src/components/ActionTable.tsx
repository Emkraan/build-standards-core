/*
 * ActionTable - collapsed, sortable, filterable Action Center list with a detail
 * modal.
 *
 * One row per thing that needs me. Rows come from three places and are joined,
 * not duplicated:
 *   - Action Center items (analysis run, direct asks, 1:1 agenda actions)
 *   - 1:1 topics whose action I resolved but have not told the person yet
 *     ("Tell them"), joined back to their item by ac_fp
 * The modal carries the full why/next, the ticket links, every Action Center
 * verb, and the 1:1 controls (discussed / not needed / add to 1:1), so I never
 * have to switch pages to close the loop.
 *
 * Built on the shared kit (kit-core): Table for the list (sortable headers, row
 * click and Enter open the item), Modal for the item, Segmented, Input and Select
 * for the filter row, Button and Pill for the controls, and toasts with Undo for
 * Resolve, Snooze and Ignore (Undo goes through the same restore path).
 */

import type { SegmentedOption, TableColumn } from '@kit'
import { Button, EmptyState, Field, Input, Modal, Pill, Segmented, Select, Table, Textarea, useToast } from '@kit'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import type { HandledEntry, Report, TackleSession, TicketSession, Topic, TopicState } from '../lib/data'
import { hermesSessionUrl, postAcDisable, postAutomationApprove, postTopicAdd, postTopicState, useOneOnOnes } from '../lib/data'
import type { CardState } from '../pages/reviews/parts'
import { CARD_STATE_HUE, StateLegend } from '../pages/reviews/parts'
import { InHermes, sessionHint, useLiveTickets } from './InHermes'
import RouteDialog from './RouteDialog'
import { Tkt } from './ui'
import './ActionTable.css'

export interface ActionItem {
  fp: string
  key?: string
  priority: string
  title: string
  why: string
  action: string
  owner?: string
  refs?: string[]
  sources?: string[]
  one_on_one?: { person: string; first: string; id: string }
  links?: { label: string; url: string }[]
  // Automation cards: a draft to review and edit, plus an Approve button whose
  // handler lives server side on the stored card.
  draft?: { label: string; fields: { key: string; label: string; text: string }[] }
  approve?: { label: string }
  // extra whitelisted buttons on an automation card (desktop image failure: rerun, close the window).
  actions?: { kind: string; label: string }[]
  // When the item first reached the board, never model prose.
  first_seen?: string
}

type Status = 'open' | 'tell' | 'snoozed' | 'ignored' | 'resolved'
type Source = 'analysis' | 'ask' | 'oneonone' | 'file' | 'docs' | 'auto'

interface Row {
  id: string
  item?: ActionItem
  topic?: Topic
  title: string
  priority: string
  prank: number
  person: string
  first: string
  source: Source
  status: Status
  refs: string[]
  since?: string
}

// Age of an item from first_seen, computed in the browser: "today 10:49 AM", "yesterday", "3d".
function sinceText(iso?: string): { short: string; full: string } {
  if (!iso) return { short: '-', full: 'Not recorded' }
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return { short: '-', full: 'Not recorded' }
  const tz = 'America/New_York'
  const ymd = (x: Date) => x.toLocaleDateString('en-CA', { timeZone: tz })
  const full = `On the board since ${d.toLocaleString('en-US', { timeZone: tz, weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })} ET`
  const days = Math.round((new Date(`${ymd(new Date())}T12:00:00Z`).getTime() - new Date(`${ymd(d)}T12:00:00Z`).getTime()) / 864e5)
  if (days <= 0) return { short: `today ${d.toLocaleTimeString('en-US', { timeZone: tz, hour: 'numeric', minute: '2-digit' })}`, full }
  if (days === 1) return { short: 'yesterday', full }
  return { short: `${days}d`, full }
}

const SOURCE_LABEL: Record<Source, string> = {
  analysis: 'Analysis',
  ask: 'Direct ask',
  oneonone: '1:1',
  file: 'File',
  docs: 'Docs',
  auto: 'Automation',
}
const STATUS_LABEL: Record<Status, string> = {
  open: 'Open',
  tell: 'Tell them',
  snoozed: 'Snoozed',
  ignored: 'Ignored',
  resolved: 'Done',
}
// Row colours match the review cards: red a tackle failed and nothing moves it, blue a session works
// it now, amber it needs me (or I still owe a word), grey snoozed or ignored, green done.
const ROW_STATE_LABEL: Partial<Record<CardState, string>> = {
  stuck: 'Tackle failed, nothing moves it',
  needs_you: 'Needs me',
  in_progress: 'A session works it now',
  waiting: 'Snoozed or ignored',
  ready: 'Done',
}
const prankOf = (p: string) => (/critical/i.test(p) ? 0 : /high|p1/i.test(p) ? 1 : /med|p2/i.test(p) ? 2 : 3)
const PLABEL = ['critical', 'high', 'medium', 'low']
const isTicket = (r: string) => /^([A-Z][A-Z0-9]+)-\d+/i.test(r)

function sourceOf(it: ActionItem): Source {
  if ((it.key || '').startsWith('file-')) return 'file'
  if ((it.key || '').startsWith('auto-')) return 'auto'
  if (it.one_on_one || (it.sources || []).includes('1:1 agenda')) return 'oneonone'
  // documentation gaps get their own source so they filter apart from operational items.
  if ((it.key || '').startsWith('doc-') || (it.sources || []).some((s) => /documentation gap/i.test(s))) return 'docs'
  if ((it.key || '').startsWith('ask-') || (it.sources || []).some((s) => /direct ask/i.test(s))) return 'ask'
  return 'analysis'
}

function statusOf(h: HandledEntry | undefined): Status {
  if (!h) return 'open'
  if (h.act === 'snoozed') return h.until && new Date(h.until).getTime() > Date.now() ? 'snoozed' : 'open'
  if (h.act === 'resolved') return 'resolved'
  return 'ignored'
}

type View = 'needs' | 'tell' | 'parked' | 'all'
type Act = 'resolved' | 'snoozed' | 'ignored' | 'ignored_forever' | 'restore'

const ACT_TOAST: Record<Exclude<Act, 'restore'>, string> = {
  resolved: 'Resolved',
  snoozed: 'Snoozed for 7 days',
  ignored: 'Ignored',
  ignored_forever: 'Ignored always',
}
const SOURCE_OPTIONS = [
  { value: '', label: 'All sources' },
  ...(Object.keys(SOURCE_LABEL) as Source[]).map((k) => ({ value: k, label: SOURCE_LABEL[k] })),
]

function PrioChip({ prank }: { prank: number }) {
  return (
    <Pill className="at-prio" data-prank={prank}>
      {PLABEL[prank]}
    </Pill>
  )
}

const SOURCE_HUE: Partial<Record<Source, 'violet' | 'amber' | 'teal' | 'blue'>> = {
  oneonone: 'violet',
  file: 'amber',
  docs: 'teal',
  auto: 'blue',
}
function SourceChip({ source }: { source: Source }) {
  const hue = SOURCE_HUE[source]
  return (
    <Pill className="at-src" hue={hue} tone={source === 'ask' ? 'accent' : 'neutral'}>
      {SOURCE_LABEL[source]}
    </Pill>
  )
}

export default function ActionTable({
  items,
  handled,
  mark,
  tackle,
  tackleErr,
  onTackle,
  onRouted,
}: {
  items: ActionItem[]
  handled: Record<string, HandledEntry>
  mark: (fp: string, act: string) => void
  tackle: Record<string, TackleSession>
  tackleErr: Record<string, string>
  onTackle: (fp: string, context: string, mode?: 'teams') => void
  /** Route elsewhere succeeded: drop the item now, restore it on Undo. */
  onRouted?: (fp: string, routed: boolean) => void
}) {
  const oo = useOneOnOnes()
  const { toast } = useToast()
  const [routeFor, setRouteFor] = useState<ActionItem | null>(null)
  const people: Report[] = oo.data?.people || []
  const [params, setParams] = useSearchParams()
  const [q, setQ] = useState('')
  const [view, setView] = useState<View>('needs')
  const [prios, setPrios] = useState<number[]>([])
  const [who, setWho] = useState('')
  const [src, setSrc] = useState<'' | Source>('')
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState('')
  const openId = params.get('item') || ''

  // the live Hermes session on a row, its own tackle first, else one working its ticket.
  const liveTickets = useLiveTickets()
  const ownLive = (id: string): TicketSession | undefined => (tackle[id]?.live ? { ...tackle[id], fp: id, from: 'action' } : undefined)
  const ticketLive = (refs: string[]): TicketSession | undefined => {
    const t = (refs[0] || '').toUpperCase()
    return t ? liveTickets.get(t) : undefined
  }
  // Every 1:1 topic that is linked to an Action Center fingerprint.
  const topicByAc = useMemo(() => {
    const m = new Map<string, Topic>()
    for (const p of people) for (const t of p.topics) if (t.ac_fp) m.set(t.ac_fp, t)
    return m
  }, [people])
  const firstOf = useMemo(() => {
    const m = new Map<string, string>()
    for (const p of people) m.set(p.name, p.first)
    return m
  }, [people])
  const boardName = useCallback(
    (raw: string) => {
      const low = raw.toLowerCase()
      return people.find((p) => low.includes(p.name.toLowerCase()) || low === p.first.toLowerCase())?.name || ''
    },
    [people],
  )

  const rows: Row[] = useMemo(() => {
    const out: Row[] = []
    const seen = new Set<string>()
    for (const it of items) {
      const topic = topicByAc.get(it.fp)
      const person = it.one_on_one?.person || boardName(it.owner || '') || it.owner || ''
      let status = statusOf(handled[it.fp])
      if (status === 'resolved' && topic && topic.state === 'open') status = 'tell'
      seen.add(it.fp)
      out.push({
        id: it.fp,
        item: it,
        topic,
        title: it.title,
        priority: it.priority,
        prank: prankOf(it.priority),
        person,
        first: firstOf.get(person) || person.split(' ')[0] || '',
        source: sourceOf(it),
        status,
        refs: it.refs || [],
        since: it.first_seen,
      })
    }
    // Resolved items the analysis no longer emits, still owed a conversation.
    for (const p of people)
      for (const t of p.topics) {
        if (!t.action_done_at || t.state !== 'open' || !t.ac_fp || seen.has(t.ac_fp)) continue
        out.push({
          id: t.ac_fp,
          topic: t,
          title: t.title,
          priority: (t.priority || 'medium').toLowerCase(),
          prank: prankOf(t.priority || ''),
          person: p.name,
          first: p.first,
          source: t.source === 'agenda' ? 'oneonone' : 'analysis',
          status: 'tell',
          refs: t.refs || [],
        })
      }
    return out
  }, [items, handled, topicByAc, firstOf, people, boardName])

  const inView = (r: Row) =>
    view === 'all'
      ? r.status !== 'resolved'
      : view === 'needs'
        ? r.status === 'open'
        : view === 'tell'
          ? r.status === 'tell'
          : r.status === 'snoozed' || r.status === 'ignored'
  const counts = {
    needs: rows.filter((r) => r.status === 'open').length,
    tell: rows.filter((r) => r.status === 'tell').length,
    parked: rows.filter((r) => r.status === 'snoozed' || r.status === 'ignored').length,
  }
  const persons = Array.from(new Set(rows.filter(inView).map((r) => r.person || 'Me'))).sort()
  const needle = q.trim().toLowerCase()
  // Filtered here; the kit Table sorts what is left (priority first, critical on top).
  const shown = rows
    .filter(inView)
    .filter((r) => !prios.length || prios.includes(r.prank))
    .filter((r) => !who || (r.person || 'Me') === who)
    .filter((r) => !src || r.source === src)
    .filter(
      (r) =>
        !needle || [r.title, r.person, r.refs.join(' '), r.item?.why || '', r.item?.action || ''].join(' ').toLowerCase().includes(needle),
    )

  const rowState = (r: Row): CardState => {
    if (r.status === 'resolved') return 'ready'
    if (r.status === 'snoozed' || r.status === 'ignored') return 'waiting'
    if (ownLive(r.id) || ticketLive(r.refs)) return 'in_progress'
    if (tackleErr[r.id] || tackle[r.id]?.state === 'failed') return 'stuck'
    return 'needs_you'
  }

  const open = rows.find((r) => r.id === openId) || null
  // Keeps the last item on screen while the kit Modal plays its exit animation.
  const lastOpen = useRef<Row | null>(null)
  if (open) lastOpen.current = open
  const shownRow = open || lastOpen.current
  const setOpen = useCallback(
    (id: string) => {
      const n = new URLSearchParams(params)
      if (id) n.set('item', id)
      else n.delete('item')
      setParams(n, { replace: true })
    },
    [params, setParams],
  )
  // Tackle context is collected inline in the item modal (no stacked dialog).
  const [askFp, setAskFp] = useState('')
  const [askMode, setAskMode] = useState<'tackle' | 'teams'>('tackle')
  const [ctx, setCtx] = useState('')
  const [editDraft, setEditDraft] = useState(false)
  const [cells, setCells] = useState<Record<string, string>>({})
  // biome-ignore lint/correctness/useExhaustiveDependencies: openId is the trigger; reset the tackle step whenever a different item opens
  useEffect(() => {
    setAskFp('')
    setCtx('')
    setEditDraft(false)
    setCells({})
  }, [openId])

  // Every verb writes through mark() (localStorage plus postHandled). Resolve, Snooze and
  // Ignore are undone through the same restore path, so their toast carries Undo.
  const act = (r: Row, a: Act) => {
    mark(r.id, a)
    if (a === 'restore') {
      toast('info', r.status === 'tell' ? 'Action reopened' : 'Restored', { description: r.title })
      return
    }
    toast('success', ACT_TOAST[a], {
      description: r.title,
      action: { label: 'Undo', onClick: () => mark(r.id, 'restore') },
    })
  }
  const approveDraft = (r: Row) => {
    if (!r.item?.key) return
    setBusy(r.id)
    setErr('')
    postAutomationApprove(r.item.key, r.id, editDraft ? cells : undefined)
      .then(() => {
        setEditDraft(false)
        mark(r.id, 'resolved')
        toast('success', r.item?.approve?.label ? `${r.item.approve.label}: done` : 'Approved', { description: r.title })
      })
      .catch((e: Error) => setErr(`Approve failed: ${e.message}`))
      .finally(() => setBusy(''))
  }
  const runCardAction = (r: Row, a: { kind: string; label: string }) => {
    if (!r.item?.key) return
    setBusy(r.id)
    setErr('')
    postAutomationApprove(r.item.key, r.id, undefined, a.kind)
      .then((res) => {
        mark(r.id, 'resolved')
        toast('success', `${a.label}: done`, { description: res.summary || r.title })
      })
      .catch((e: Error) => setErr(`${a.label} failed: ${e.message}`))
      .finally(() => setBusy(''))
  }
  const startTackle = (fp: string) => {
    onTackle(fp, ctx, askMode === 'teams' ? 'teams' : undefined)
    setAskFp('')
    setCtx('')
  }
  // The kit Modal answers Escape (and the backdrop and close button). First it backs out of
  // the tackle step, the next one closes the item.
  const closeModal = () => {
    if (askFp) setAskFp('')
    else setOpen('')
  }

  const topicAct = (t: Topic, state: TopicState) => {
    setBusy(t.fp)
    setErr('')
    postTopicState(t.fp, state)
      .then(() => {
        oo.mutate((d) => ({
          ...d,
          people: d.people.map((p) => ({
            ...p,
            topics: p.topics.map((x) => (x.fp === t.fp ? { ...x, state, state_at: new Date().toISOString() } : x)),
          })),
        }))
        oo.reload()
      })
      .catch((e: Error) => setErr(e.message))
      .finally(() => setBusy(''))
  }
  const addTo1on1 = (r: Row) => {
    if (!r.person || !r.item) return
    setBusy(r.id)
    setErr('')
    postTopicAdd(r.person, r.title, r.item.action || r.item.why)
      .then(() => {
        oo.reload()
        toast('success', `Added to ${r.first}'s 1:1`, { description: r.title })
      })
      .catch((e: Error) => setErr(e.message))
      .finally(() => setBusy(''))
  }

  const views: SegmentedOption<View>[] = [
    { value: 'needs', label: `Needs me ${counts.needs}` },
    { value: 'tell', label: `Tell them ${counts.tell}`, tip: counts.tell ? 'Done, and I still owe them a word' : undefined },
    { value: 'parked', label: `Snoozed/ignored ${counts.parked}` },
    { value: 'all', label: 'All' },
  ]
  const columns: TableColumn<Row>[] = [
    { key: 'priority', header: 'Priority', width: '104px', value: (r) => r.prank, render: (r) => <PrioChip prank={r.prank} /> },
    {
      key: 'title',
      header: 'Item',
      value: (r) => r.title.toLowerCase(),
      render: (r) => (
        <span className="at-title" title={r.title}>
          <InHermes session={ownLive(r.id) || ticketLive(r.refs)} />
          {r.title}
        </span>
      ),
    },
    {
      key: 'person',
      header: 'Person',
      width: '112px',
      value: (r) => (r.person || 'zzz').toLowerCase(),
      render: (r) => (
        <span className="at-person" title={r.person || 'Mine'}>
          {r.person ? r.first : <i>Me</i>}
        </span>
      ),
    },
    { key: 'source', header: 'Source', width: '112px', value: (r) => r.source, render: (r) => <SourceChip source={r.source} /> },
    { key: 'status', header: '1:1 / status', width: '124px', value: (r) => r.status, render: (r) => <LinkState r={r} /> },
    {
      key: 'refs',
      header: 'Tickets',
      width: '160px',
      sortable: false,
      render: (r) => (
        <span className="at-refs">
          {r.refs.slice(0, 2).map((x) => (
            <code key={x}>{x}</code>
          ))}
          {r.refs.length > 2 && <code>+{r.refs.length - 2}</code>}
        </span>
      ),
    },
    {
      key: 'since',
      header: 'Since',
      width: '108px',
      value: (r) => r.since || '9999',
      render: (r) => {
        const s = sinceText(r.since)
        return (
          <span className="at-since" title={s.full}>
            {s.short}
          </span>
        )
      },
    },
  ]

  return (
    <div className="at">
      <div className="at-bar">
        <Segmented className="at-views" label="Action Center view" options={views} value={view} onChange={setView} />
        <Input
          className="at-search"
          type="search"
          aria-label="Search the Action Center"
          placeholder="Search title, person, ticket..."
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <div className="at-chips" role="group" aria-label="Priority filter">
          {PLABEL.map((p, i) => (
            <Button
              key={p}
              size="sm"
              variant="ghost"
              className="at-chip"
              data-prank={i}
              aria-pressed={prios.includes(i)}
              onClick={() => setPrios((s) => (s.includes(i) ? s.filter((x) => x !== i) : [...s, i]))}
            >
              {p}
            </Button>
          ))}
        </div>
        <Select className="at-sel" aria-label="Person" value={who} onChange={(e) => setWho(e.target.value)}>
          <option value="">Everyone</option>
          {persons.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </Select>
        <Select
          className="at-sel"
          aria-label="Source"
          value={src}
          options={SOURCE_OPTIONS}
          onChange={(e) => setSrc(e.target.value as '' | Source)}
        />
      </div>

      <StateLegend labels={ROW_STATE_LABEL} states={['stuck', 'needs_you', 'in_progress', 'waiting']} />
      <Table
        className="at-table"
        caption="Action Center items"
        columns={columns}
        rows={shown}
        rowKey={(r) => r.id}
        defaultSort={{ key: 'priority', dir: 'asc' }}
        onRowActivate={(r) => setOpen(r.id)}
        isRowSelected={(r) => r.id === openId}
        rowProps={(r) => {
          const s = rowState(r)
          return { className: `at-row hue-${CARD_STATE_HUE[s]}`, 'data-state': s, title: ROW_STATE_LABEL[s] }
        }}
        empty={<EmptyState compact title="Nothing here with these filters." />}
      />

      <Modal
        open={open !== null}
        onClose={closeModal}
        size="lg"
        className={`at-modal${shownRow?.prank === 0 ? ' is-critical' : ''}`}
        title={shownRow?.title ?? ''}
        subtitle={
          shownRow ? (
            <span className="at-m-head">
              <PrioChip prank={shownRow.prank} />
              <SourceChip source={shownRow.source} />
              <span className="at-m-person">{shownRow.person || 'Mine'}</span>
            </span>
          ) : null
        }
        footer={null}
      >
        {shownRow && itemBody(shownRow)}
      </Modal>
      <RouteDialog
        item={routeFor}
        onClose={() => setRouteFor(null)}
        onRouted={(it, rule) => {
          setRouteFor(null)
          closeModal()
          onRouted?.(it.fp, true)
          toast('success', rule.route === 'nowhere' ? 'Routed away' : `Routed to ${rule.where}`, {
            description: it.title,
            action: {
              label: 'Undo',
              onClick: () => {
                postAcDisable(rule.id, true)
                  .then(() => onRouted?.(it.fp, false))
                  .catch((e: Error) => toast('error', 'Undo failed', { description: e.message }))
              },
            },
          })
        }}
      />
    </div>
  )

  // A plain render helper (not a component), so the tackle textarea keeps focus between renders.
  function itemBody(open: Row) {
    return (
      <>
        {open.item?.why && (
          <section className="at-m-sec">
            <b>Why</b>
            <p>{open.item.why}</p>
          </section>
        )}
        {(open.item?.action || open.topic?.my_action || open.topic?.detail) && (
          <section className="at-m-sec">
            <b>Next</b>
            <p>{open.item?.action || open.topic?.my_action || open.topic?.detail}</p>
          </section>
        )}
        {open.refs.length > 0 && (
          <div className="at-m-refs">{open.refs.map((x) => (isTicket(x) ? <Tkt key={x} id={x} /> : <code key={x}>{x}</code>))}</div>
        )}
        {(open.item?.links || []).length > 0 && (
          <div className="at-m-links">
            {(open.item?.links || []).map((l) => (
              <a key={l.url} href={l.url} target="_blank" rel="noreferrer">
                {l.label}
              </a>
            ))}
          </div>
        )}

        {open.item?.draft && (
          <section className="at-m-draft">
            <b>{open.item.draft.label}</b>
            {open.item.draft.fields.map((f) =>
              editDraft ? (
                <Field key={f.key} label={f.label}>
                  <Textarea
                    rows={f.text.length > 400 ? 14 : 5}
                    maxLength={1500}
                    value={cells[f.key] ?? f.text}
                    onChange={(e) => setCells((c) => ({ ...c, [f.key]: e.target.value }))}
                  />
                </Field>
              ) : (
                <div key={f.key} className="at-m-draft-f">
                  <span className="muted">{f.label}</span>
                  <p>{f.text || <i className="muted">(left empty)</i>}</p>
                </div>
              ),
            )}
          </section>
        )}

        {/* 1:1 link: the conversation side of the same item */}
        <div className={`at-m-1on1 ${open.status === 'tell' ? 'warn' : ''}`}>
          {open.topic ? (
            <>
              <div>
                <b>1:1 with {open.first}</b>{' '}
                <span className="muted">
                  {open.status === 'tell'
                    ? 'action done, I still need to tell them'
                    : open.topic.state === 'open'
                      ? 'on the agenda'
                      : open.topic.state === 'discussed'
                        ? 'discussed'
                        : 'not needed'}
                </span>
              </div>
              <div className="at-m-btns">
                {open.topic.state === 'open' ? (
                  <>
                    <Button size="sm" loading={busy === open.topic.fp} onClick={() => topicAct(open.topic as Topic, 'discussed')}>
                      {open.status === 'tell' ? 'Told them' : 'Discussed'}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={busy === open.topic.fp}
                      onClick={() => topicAct(open.topic as Topic, 'not_needed')}
                    >
                      Remove from 1:1
                    </Button>
                  </>
                ) : (
                  <Button size="sm" loading={busy === open.topic.fp} onClick={() => topicAct(open.topic as Topic, 'open')}>
                    Put back on 1:1
                  </Button>
                )}
                <Link className="btn" data-variant="ghost" data-size="sm" to={`/people?p=${encodeURIComponent(open.first)}`}>
                  Open {open.first}&apos;s 1:1
                </Link>
              </div>
            </>
          ) : open.person && firstOf.has(open.person) ? (
            <div className="at-m-btns">
              <span className="muted">Not on {open.first}&apos;s 1:1.</span>
              <Button size="sm" variant="ghost" loading={busy === open.id} onClick={() => addTo1on1(open)}>
                Add to {open.first}&apos;s 1:1
              </Button>
            </div>
          ) : (
            <span className="muted">Mine; no 1:1 link.</span>
          )}
        </div>

        {askFp === open.id ? (
          <div className="at-m-tackle">
            <Field
              label={
                askMode === 'teams'
                  ? 'Draft in Teams: who it goes to and what to say (optional)'
                  : 'Tackle now: additional context (optional)'
              }
              hint={
                askMode === 'teams'
                  ? 'Opens a chat that writes the message and leaves it unsent in your Teams drafts. Cmd+Enter to start, Esc to go back.'
                  : 'Opens a new chat in the Hermes desktop app. Cmd+Enter to start, Esc to go back.'
              }
            >
              <Textarea
                autoFocus
                rows={6}
                maxLength={8000}
                value={ctx}
                placeholder="Key details, constraints, links, people involved, what done looks like..."
                onChange={(e) => setCtx(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) startTackle(open.id)
                }}
              />
            </Field>
            <div className="at-m-btns at-m-tackle-btns">
              <Button size="sm" onClick={() => setAskFp('')}>
                Back
              </Button>
              <Button size="sm" variant="primary" onClick={() => startTackle(open.id)}>
                Start in Hermes
              </Button>
            </div>
          </div>
        ) : (
          <div className="at-m-btns at-m-actions">
            {open.status === 'open' && open.item?.approve && !open.item.draft && (
              // An action card without a draft (e.g. the Vercel watcher's Roll back): one button.
              <Button size="sm" variant="danger" loading={busy === open.id} onClick={() => approveDraft(open)}>
                {busy === open.id ? 'Working...' : open.item.approve.label}
              </Button>
            )}
            {open.status === 'open' &&
              (open.item?.actions || []).map((a) => (
                <Button
                  key={a.kind}
                  size="sm"
                  variant={a.kind === 'avd-close' ? 'danger' : a.kind === 'ticket-dismiss' ? 'ghost' : 'primary'}
                  loading={busy === open.id}
                  disabled={!!busy}
                  onClick={() => runCardAction(open, a)}
                >
                  {a.label}
                </Button>
              ))}
            {open.status === 'open' && open.item?.approve && open.item.draft && (
              <>
                <Button size="sm" variant="primary" loading={busy === open.id} onClick={() => approveDraft(open)}>
                  {busy === open.id ? 'Writing...' : open.item.approve.label}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy === open.id}
                  onClick={() => {
                    if (!editDraft) setCells(Object.fromEntries((open.item?.draft?.fields || []).map((f) => [f.key, f.text])))
                    setEditDraft(!editDraft)
                  }}
                >
                  {editDraft ? 'Cancel edit' : 'Edit'}
                </Button>
              </>
            )}
            {open.status === 'open' && open.item && (
              <>
                {tackle[open.id]?.state === 'launching' || tackle[open.id]?.state === 'claimed' ? (
                  <Button size="sm" variant="primary" loading>
                    Opening in Hermes...
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    variant="primary"
                    onClick={() => {
                      setAskMode('tackle')
                      setAskFp(open.id)
                    }}
                  >
                    {tackle[open.id]?.session_id ? 'Tackle again' : 'Tackle now'}
                  </Button>
                )}
                {tackle[`teams-${open.id}`]?.state === 'launching' || tackle[`teams-${open.id}`]?.state === 'claimed' ? (
                  <Button size="sm" loading>
                    Opening in Hermes...
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    title="Write the message for this item and leave it unsent in Teams"
                    onClick={() => {
                      setAskMode('teams')
                      setAskFp(open.id)
                    }}
                  >
                    Draft in Teams
                  </Button>
                )}
                <Button size="sm" onClick={() => act(open, 'resolved')}>
                  Resolve
                </Button>
                <Button size="sm" onClick={() => act(open, 'snoozed')}>
                  Snooze 7d
                </Button>
                <Button size="sm" variant="ghost" onClick={() => act(open, 'ignored')}>
                  Ignore
                </Button>
                <Button size="sm" variant="ghost" onClick={() => act(open, 'ignored_forever')}>
                  Ignore always
                </Button>
                {onRouted && (
                  <Button
                    size="sm"
                    variant="ghost"
                    title="Make a routing rule so items like this go where they belong, now and in future runs"
                    onClick={() => setRouteFor(open.item ?? null)}
                  >
                    Route elsewhere
                  </Button>
                )}
              </>
            )}
            {open.status !== 'open' && (
              <Button size="sm" onClick={() => act(open, 'restore')}>
                {open.status === 'tell' ? 'Reopen action' : 'Restore'}
              </Button>
            )}
          </div>
        )}
        {(() => {
          const other = ticketLive(open.refs)
          if (!other || other.fp === open.id || !other.session_id) return null
          return (
            <p className="at-m-hint ih-hint">
              {open.refs[0]} is already being worked in Hermes. {sessionHint(other)}{' '}
              <a href={hermesSessionUrl(other.session_id)}>Open that session</a> instead of starting a second one.
            </p>
          )
        })()}
        {tackle[open.id]?.session_id && (
          <p className="at-m-hint">
            In Hermes: <a href={hermesSessionUrl(tackle[open.id].session_id ?? '')}>open thread</a>
          </p>
        )}
        {tackleErr[open.id] && <p className="at-m-hint err">Tackle failed: {tackleErr[open.id]}</p>}
        {err && <p className="at-m-hint err">{err}</p>}
        <p className="at-m-hint">Esc to close.</p>
      </>
    )
  }
}

function LinkState({ r }: { r: Row }) {
  if (r.status === 'tell')
    return (
      <Pill className="at-state at-state-tell" tone="warning">
        Tell {r.first}
      </Pill>
    )
  if (r.status !== 'open') return <Pill className="at-state parked">{STATUS_LABEL[r.status]}</Pill>
  if (!r.topic) return <span className="at-state none">-</span>
  if (r.topic.state === 'open')
    return (
      <Pill className="at-state" hue="violet">
        On 1:1
      </Pill>
    )
  return <Pill className="at-state">{r.topic.state === 'discussed' ? 'Discussed' : 'Off 1:1'}</Pill>
}
