// 1:1 Board. Discussion topics for my direct reports plus person and person, assembled by
// one_on_ones.py from analyzed sources only: my curated agenda, Action Center items the
// inbound monitor flagged for them, the weekly assessment, and topics I add. Raw Teams
// and mail threads attach to the topic they belong to and never list on their own.
// No extra LLM call. I mark each topic Discussed or Not needed (one-on-ones.json), and
// book "owner & <first> 1:1" Teams meetings from here when none is on the calendar.
// Built on the shared kit (Card, Badge, Segmented, Toolbar, Modal, Field) since 2026-10-13.

import type { CategoricalHue, DotTone, SegmentedOption } from '@kit'
import {
  Badge,
  Button,
  Card,
  CardHead,
  EmptyState,
  Field,
  IconCheck,
  IconChevronDown,
  IconChevronRight,
  IconPlus,
  Input,
  Modal,
  ModalSection,
  Segmented,
  Skeleton,
  StatusDot,
  Textarea,
  Tone,
  Toolbar,
  useConfirm,
} from '@kit'
import type { KeyboardEvent, MouseEvent } from 'react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import AlertBanner from '../components/AlertBanner'
import { useCopyDialog } from '../components/CopyDialog'
import { HubHeader } from '../components/HubHeader'
import { Tkt } from '../components/ui'
import type { Availability, OneOnOnes as Board, BusyBlock, Report, ScheduleResult, Topic, TopicState } from '../lib/data'
import { fetchAvailability, postSchedule, postTopicAdd, postTopicRemove, postTopicState, relTime, useNow, useOneOnOnes } from '../lib/data'
import { Meter, PersonCard, PersonRail } from './people/PersonCard'
import './OneOnOnes.css'

const GROUPS: { key: 'report' | 'partner'; label: string }[] = [
  { key: 'report', label: 'Direct reports' },
  { key: 'partner', label: 'Director and product owner' },
]

type Filter = 'all' | Topic['source']

const SRC: Record<Topic['source'], { label: string; hue: CategoricalHue }> = {
  agenda: { label: 'Agenda', hue: 'blue' },
  action: { label: 'Flagged by monitor', hue: 'amber' },
  me: { label: 'Added by me', hue: 'green' },
  review: { label: 'Weekly assessment', hue: 'teal' },
  teams: { label: 'Teams', hue: 'violet' },
  mail: { label: 'Mail', hue: 'blue' },
}

const FILTERS: { key: Filter; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'agenda', label: 'Agenda' },
  { key: 'action', label: 'Flagged' },
  { key: 'review', label: 'Assessment' },
  { key: 'me', label: 'Mine' },
]

const PRIO_TONE: Record<string, 'danger' | 'warning' | 'info'> = { P1: 'danger', P2: 'warning', P3: 'info' }

function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

function shortWhen(iso: string): string {
  const d = new Date(iso)
  return `${d.toLocaleDateString([], { weekday: 'short', month: 'numeric', day: 'numeric' })} ${clock(iso)}`
}

type MeetTone = 'next' | 'now' | 'done' | 'later' | 'none' | 'gap'
const MEET_DOT: Record<MeetTone, DotTone> = {
  now: 'success',
  next: 'warning',
  gap: 'warning',
  later: 'info',
  done: 'neutral',
  none: 'neutral',
}

function meetingState(r: Report, now: number): { label: string; tone: MeetTone } {
  const m = r.meeting
  if (!m) {
    if (r.next_1on1) return { label: `Next 1:1 ${shortWhen(r.next_1on1.start)}`, tone: 'later' }
    return r.schedule_needed ? { label: 'No 1:1 in 3 weeks', tone: 'gap' } : { label: 'No 1:1 today', tone: 'none' }
  }
  const s = new Date(m.start).getTime()
  const e = m.end ? new Date(m.end).getTime() : s + 30 * 60000
  if (now >= e) return { label: `${clock(m.start)} \u00b7 done`, tone: 'done' }
  if (now >= s) return { label: `Now \u00b7 until ${clock(m.end || m.start)}`, tone: 'now' }
  const mins = Math.round((s - now) / 60000)
  const rel = mins < 60 ? `in ${mins}m` : `in ${Math.floor(mins / 60)}h ${mins % 60}m`
  return { label: `${clock(m.start)} \u00b7 ${rel}`, tone: mins <= 30 ? 'next' : 'later' }
}

function pickDefault(people: Report[], now: number): string | null {
  const live = people.find((p) => {
    const m = p.meeting
    if (!m) return false
    const e = m.end ? new Date(m.end).getTime() : new Date(m.start).getTime() + 30 * 60000
    return e > now
  })
  return (live || people[0])?.name || null
}

function recount(r: Report): Report {
  const n = (s: TopicState) => r.topics.filter((t) => t.state === s).length
  return { ...r, counts: { ...r.counts, open: n('open'), discussed: n('discussed'), not_needed: n('not_needed') } }
}

const HEAD_SUB =
  'Discussion topics for my direct reports, plus person and person: my agenda, items the monitor flagged, and the weekly assessment. Teams and mail threads attach as evidence, not as topics.'

export default function OneOnOnes() {
  const { data, error, at, reload, mutate } = useOneOnOnes()
  const now = useNow(15_000)
  const [sel, setSel] = useState<string | null>(null)
  const [filter, setFilter] = useState<Filter>('all')
  const [showCovered, setShowCovered] = useState(false)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const { showCopy, dialog: copyDialog } = useCopyDialog()
  const { confirm: ask, dialog: confirmDialog } = useConfirm()
  // The schedule dialog stays mounted after close so the kit exit animation plays. n remounts it fresh.
  const [sched, setSched] = useState<{ name: string; open: boolean; n: number } | null>(null)
  const openSched = (name: string) => setSched((s) => ({ name, open: true, n: (s?.n || 0) + 1 }))
  const closeSched = () => setSched((s) => (s ? { ...s, open: false } : s))

  // ?p=<first name> deep link (the "Next 1:1" chip uses it); a new link wins
  // over an earlier click.
  const [params] = useSearchParams()
  const want = (params.get('p') || '').toLowerCase()
  // biome-ignore lint/correctness/useExhaustiveDependencies: reset selection whenever the URL person changes
  useEffect(() => setSel(null), [want])

  const people = useMemo(() => data?.people || [], [data])
  const fromUrl = want ? people.find((p) => p.first.toLowerCase() === want || p.name.toLowerCase() === want)?.name : undefined
  const name = sel && people.some((p) => p.name === sel) ? sel : fromUrl || pickDefault(people, now)
  const person = people.find((p) => p.name === name) || null

  const header = (
    <HubHeader
      eyebrow="People"
      title="1:1 Board"
      subtitle={HEAD_SUB}
      status={
        <span className="oo-live">
          <StatusDot tone={error ? 'warning' : 'success'} label={error ? 'reconnecting' : 'live'} />
          {error ? 'reconnecting' : `live \u00b7 ${relTime(at)}`}
        </span>
      }
    />
  )

  if (error && !data)
    return (
      <div className="oo">
        {header}
        <Card>
          <EmptyState title="Could not load the 1:1 Board." body={error} action={<Button onClick={reload}>Retry</Button>} />
        </Card>
      </div>
    )
  if (!data)
    return (
      <div className="oo">
        {header}
        <Skeleton variant="card" count={3} label="Loading the 1:1 Board" />
      </div>
    )

  const setState = (t: Topic, state: TopicState) => {
    setErr(null)
    mutate((d: Board) => ({
      ...d,
      people: d.people.map((p) =>
        p.name !== t.person
          ? p
          : recount({
              ...p,
              topics: p.topics.map((x) => (x.fp === t.fp ? { ...x, state, state_at: new Date().toISOString(), reopened: false } : x)),
            }),
      ),
    }))
    postTopicState(t.fp, state)
      .then(() => reload())
      .catch((e: Error) => {
        setErr(e.message)
        reload()
      })
  }

  const addTopic = () => {
    const title = draft.trim()
    if (!title || !person || busy) return
    setBusy(true)
    setErr(null)
    postTopicAdd(person.name, title)
      .then(() => {
        setDraft('')
        reload()
      })
      .catch((e: Error) => setErr(e.message))
      .finally(() => setBusy(false))
  }

  const removeTopic = async (t: Topic) => {
    const ok = await ask({
      title: 'Delete this topic?',
      body: `"${t.title}" comes off ${t.person.split(' ')[0]}'s board for good. Add it again if I need it back.`,
      confirmLabel: 'Delete',
      danger: true,
    })
    if (!ok) return
    postTopicRemove(t.fp)
      .then(() => reload())
      .catch((e: Error) => setErr(e.message))
  }

  const topics = person ? person.topics.filter((t) => filter === 'all' || t.source === filter) : []
  const open = topics.filter((t) => t.state === 'open')
  const covered = topics.filter((t) => t.state !== 'open')
  const allOpen = person ? person.topics.filter((t) => t.state === 'open') : []
  const total = person ? person.topics.length : 0
  const done = person ? person.counts.discussed + person.counts.not_needed : 0

  const copyAgenda = async () => {
    if (!person) return
    const day = new Date().toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })
    const text =
      `1:1 with ${person.first} (${day})\n` +
      allOpen.map((t, i) => `${i + 1}. ${t.title}${t.refs.length ? ` [${t.refs.join(', ')}]` : ''}`).join('\n')
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1600)
    } catch {
      showCopy('Copy the agenda', text)
    }
  }

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') addTopic()
    if (e.key === 'Escape') setDraft('')
  }

  const filterOptions: SegmentedOption<Filter>[] = person
    ? FILTERS.flatMap((f) => {
        const n = f.key === 'all' ? person.topics.length : person.topics.filter((t) => t.source === f.key).length
        if (f.key !== 'all' && n === 0) return []
        return [{ value: f.key, label: `${f.label} ${n}` }]
      })
    : []
  const schedTarget = sched ? people.find((p) => p.name === sched.name) : undefined

  return (
    <div className="oo">
      {copyDialog}
      {confirmDialog}
      {header}
      {data.roster?.stale && (
        <AlertBanner tone="warning" title="Directory pull failed, showing the last good titles and addresses">
          Last pulled {relTime(data.roster.as_of)} for {data.roster.names.join(', ')}.
        </AlertBanner>
      )}
      {!!data.roster?.missing?.length && (
        <AlertBanner tone="warning" title="Directory pull failed and no earlier copy exists">
          No title or address yet for {data.roster.missing.join(', ')}.
        </AlertBanner>
      )}

      {GROUPS.map((g) => {
        const members = people.filter((p) => (p.group || 'report') === g.key)
        if (!members.length) return null
        return (
          <section key={g.key} className="oo-group" aria-label={g.label}>
            <div className="pp-label">
              {g.label}
              <Badge>{members.reduce((n, p) => n + p.counts.open, 0)} open</Badge>
            </div>
            <PersonRail label={g.label}>
              {members.map((p) => {
                const ms = meetingState(p, now)
                const pct = p.topics.length ? Math.round(((p.counts.discussed + p.counts.not_needed) / p.topics.length) * 100) : 0
                const pick = () => {
                  setSel(p.name)
                  setShowCovered(false)
                }
                return (
                  <PersonCard
                    key={p.name}
                    name={p.name}
                    selected={p.name === name}
                    tone={ms.tone === 'now' ? 'green' : undefined}
                    dim={ms.tone === 'done'}
                    onPick={pick}
                    sub={
                      <span className={`oo-meet is-${ms.tone}`}>
                        <StatusDot tone={MEET_DOT[ms.tone]} pulse={ms.tone === 'now'} />
                        {ms.label}
                      </span>
                    }
                    aside={
                      <>
                        <span className="pp-count">
                          <b>{p.counts.open}</b>
                          <small>open</small>
                        </span>
                        {p.counts.new > 0 && <Badge tone="accent">{p.counts.new} new</Badge>}
                      </>
                    }
                  >
                    <Meter pct={pct} label={`${pct}% covered`} />
                    {p.schedule_needed && (
                      <Button
                        size="sm"
                        variant="secondary"
                        className="oo-sched"
                        icon={<IconPlus size={14} />}
                        data-tip={`No 1:1 with ${p.first} in the next 3 weeks`}
                        onClick={(e: MouseEvent) => {
                          e.stopPropagation()
                          pick()
                          openSched(p.name)
                        }}
                        onKeyDown={(e) => e.stopPropagation()}
                      >
                        Schedule
                      </Button>
                    )}
                  </PersonCard>
                )
              })}
            </PersonRail>
          </section>
        )
      })}

      {err && (
        <Tone hue="red" className="pp-note" role="alert">
          Could not save: {err}
        </Tone>
      )}

      {person && (
        <Card className="oo-panel">
          <CardHead
            title={person.name}
            subtitle={
              <>
                {person.title}
                {person.last_contact && <> &middot; last heard {relTime(person.last_contact)}</>}
                {person.meeting && (
                  <>
                    {' '}
                    &middot; {person.meeting.subject} {clock(person.meeting.start)}
                    {person.meeting.link && (
                      <>
                        {' '}
                        &middot;{' '}
                        <a href={person.meeting.link} target="_blank" rel="noreferrer">
                          Join
                        </a>
                      </>
                    )}
                  </>
                )}
                {person.next_1on1 && person.next_1on1.start !== person.meeting?.start && (
                  <> &middot; next 1:1 {shortWhen(person.next_1on1.start)}</>
                )}
                {person.schedule_needed && (
                  <>
                    {' '}
                    &middot; <span className="oo-gap">no 1:1 in the next 3 weeks</span>
                  </>
                )}
              </>
            }
            controls={
              <>
                {person.schedule_needed && (
                  <Button size="sm" variant="primary" onClick={() => openSched(person.name)}>
                    Schedule 1:1
                  </Button>
                )}
                <div className="oo-progress">
                  <div className="oo-progress-num">
                    <b>{done}</b>/{total} covered
                  </div>
                  <Meter pct={total ? (done / total) * 100 : 0} tone="success" label={`${done} of ${total} covered`} />
                </div>
              </>
            }
          />

          <Toolbar onRefresh={reload} updatedAt={at || null} label="Topics" className="oo-toolbar">
            <Input
              className="oo-add-input"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKey}
              placeholder={`Add a topic for ${person.first} and press Enter`}
              aria-label={`Add a topic for ${person.first}`}
              maxLength={200}
            />
            <Button size="sm" variant="primary" onClick={addTopic} disabled={!draft.trim()} loading={busy}>
              Add
            </Button>
          </Toolbar>
          <div className="oo-filters">
            <Segmented label="Topic source" options={filterOptions} value={filter} onChange={setFilter} />
            <Button
              size="sm"
              variant="secondary"
              icon={copied ? <IconCheck size={14} /> : undefined}
              onClick={copyAgenda}
              disabled={allOpen.length === 0}
            >
              {copied ? 'Copied' : 'Copy agenda'}
            </Button>
          </div>

          {open.length === 0 && (
            <EmptyState
              compact
              pose={covered.length ? 'celebrate' : undefined}
              title={covered.length ? 'Everything here is covered. Nice.' : 'Nothing to discuss from this source yet.'}
            />
          )}
          <div className="oo-list">
            {open.map((t, i) => (
              <TopicCard key={t.fp} t={t} n={i + 1} onState={setState} onRemove={removeTopic} />
            ))}
          </div>

          {covered.length > 0 && (
            <>
              <Button
                variant="ghost"
                size="sm"
                className="oo-covered-toggle"
                icon={showCovered ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}
                onClick={() => setShowCovered((s) => !s)}
                aria-expanded={showCovered}
              >
                Covered ({covered.length})
              </Button>
              {showCovered && (
                <div className="oo-list is-covered">
                  {covered.map((t) => (
                    <TopicCard key={t.fp} t={t} onState={setState} onRemove={removeTopic} />
                  ))}
                </div>
              )}
            </>
          )}
        </Card>
      )}

      <p className="pp-foot">
        Topics come from my agenda, the Action Center, and the weekly assessment. Teams and mail threads attach to them as evidence.
        Sources: Teams {relTime(data.sources.teams_updated)} &middot; Mail {relTime(data.sources.mail_updated)} &middot; Action Center{' '}
        {relTime(data.sources.action_center_utc)} &middot; weekly assessment {relTime(data.sources.assessment_utc)} &middot; calendar{' '}
        {data.sources.calendar_ok ? 'ok' : 'unavailable'} &middot; 3-week 1:1 check {data.sources.upcoming_ok ? 'ok' : 'unavailable'}
      </p>

      {sched && schedTarget && (
        <ScheduleModal key={sched.n} open={sched.open} person={schedTarget} onClose={closeSched} onBooked={reload} />
      )}
    </div>
  )
}

// ---------------------------------------------------------------- scheduling

const DURATIONS: SegmentedOption<string>[] = [15, 30, 45, 60].map((m) => ({ value: String(m), label: `${m}m` }))
const DAY_START = 7 * 60
const DAY_END = 19 * 60
const HOUR_MARKS = [8, 10, 12, 14, 16, 18]

// Server times are ET with an offset, so the wall clock is the string itself.
const wallMin = (iso: string) => Number(iso.slice(11, 13)) * 60 + Number(iso.slice(14, 16))
const toHHMM = (m: number) => `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`

function fmtWall(hhmm: string): string {
  const h = Number(hhmm.slice(0, 2))
  return `${((h + 11) % 12) + 1}:${hhmm.slice(3, 5)} ${h < 12 ? 'AM' : 'PM'}`
}

function fmtDay(date: string, long = false): string {
  return new Date(`${date}T12:00:00`).toLocaleDateString([], {
    weekday: long ? 'long' : 'short',
    month: 'short',
    day: 'numeric',
  })
}

function agendaText(r: Report): string {
  return r.topics
    .filter((t) => t.state === 'open')
    .map((t) => `- ${t.title}${t.refs.length ? ` [${t.refs.join(', ')}]` : ''}`)
    .join('\n')
}

type Fit = { tone: 'ok' | 'warn' | 'bad'; label: string }
const FIT_TONE = { ok: 'success', warn: 'warning', bad: 'danger' } as const

function ScheduleModal({ open, person, onClose, onBooked }: { open: boolean; person: Report; onClose: () => void; onBooked: () => void }) {
  const [minutes, setMinutes] = useState(30)
  const [avail, setAvail] = useState<Availability | null>(null)
  const [loadErr, setLoadErr] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [date, setDate] = useState('')
  const [time, setTime] = useState('')
  const [agenda, setAgenda] = useState(() => agendaText(person))
  const [auto, setAuto] = useState(true)
  const [sending, setSending] = useState(false)
  const [sendErr, setSendErr] = useState<string | null>(null)
  const [booked, setBooked] = useState<ScheduleResult | null>(null)

  // biome-ignore lint/correctness/useExhaustiveDependencies: attempt is a retry counter that forces a refetch
  useEffect(() => {
    let live = true
    setAvail(null)
    setLoadErr(null)
    fetchAvailability(person.name, minutes)
      .then((a) => {
        if (!live) return
        setAvail(a)
        const first = a.suggestions[0]
        setDate((d) => d || (first ? first.start.slice(0, 10) : a.windows[0]?.date || ''))
        setTime((t) => t || (first ? first.start.slice(11, 16) : '10:00'))
      })
      .catch((e: Error) => live && setLoadErr(e.message))
    return () => {
      live = false
    }
  }, [person.name, minutes, attempt])

  const offsetFor = (d: string): string => {
    const iso = avail?.windows.find((w) => w.date === d)?.start || avail?.window.start || ''
    return iso.match(/([+-]\d{2}:\d{2}|Z)$/)?.[1] || '-04:00'
  }

  const onDay = (b: BusyBlock, d: string) => b.start.slice(0, 10) <= d && b.end.slice(0, 10) >= d
  const span = (b: BusyBlock, d: string): [number, number] => [
    b.start.slice(0, 10) < d ? 0 : wallMin(b.start),
    b.end.slice(0, 10) > d ? 24 * 60 : wallMin(b.end),
  ]

  const startMin = time ? Number(time.slice(0, 2)) * 60 + Number(time.slice(3, 5)) : null
  // biome-ignore lint/correctness/useExhaustiveDependencies: helpers are module-pure; recompute is keyed on the real inputs
  const fit = useMemo<Fit | null>(() => {
    if (!avail || !date || startMin === null) return null
    const s = startMin
    const e = s + minutes
    const clash = (list: BusyBlock[]) =>
      list.filter((b) => {
        if (!onDay(b, date)) return false
        const [bs, be] = span(b, date)
        return bs < e && be > s
      })
    if (new Date(`${date}T${time}:00${offsetFor(date)}`).getTime() < Date.now() - 60_000)
      return { tone: 'bad', label: 'That time has passed' }
    const mine = clash(avail.me.busy)
    const theirs = clash(avail.them.busy)
    const firm = (l: BusyBlock[]) => l.some((b) => b.status !== 'tentative')
    if (firm(mine) && firm(theirs)) return { tone: 'bad', label: 'We are both busy then' }
    if (firm(mine)) return { tone: 'bad', label: 'I am busy then' }
    if (firm(theirs)) return { tone: 'bad', label: `${person.first} is busy then` }
    if (mine.length || theirs.length) return { tone: 'warn', label: 'Overlaps a tentative hold' }
    const win = avail.windows.find((w) => w.date === date)
    if (!win || wallMin(win.start) > s || e > wallMin(win.end)) return { tone: 'warn', label: 'Outside our shared working hours' }
    return { tone: 'ok', label: 'We are both free' }
  }, [avail, date, time, minutes, person.first])

  const lines = agenda
    .split('\n')
    .map((l) => l.replace(/^\s*(?:[-*\u2022]|\d+[.)])\s*/, '').trim())
    .filter(Boolean)

  const send = () => {
    if (!date || !time || sending) return
    setSending(true)
    setSendErr(null)
    postSchedule({ person: person.name, start: `${date}T${time}`, minutes, agenda: lines, auto_transcribe: auto })
      .then((r) => {
        setBooked(r)
        onBooked()
      })
      .catch((e: Error) => setSendErr(e.message))
      .finally(() => setSending(false))
  }

  const pct = (m: number) => `${((Math.min(Math.max(m, DAY_START), DAY_END) - DAY_START) / (DAY_END - DAY_START)) * 100}%`
  const track = (list: BusyBlock[], who: string) => {
    const win = avail?.windows.find((w) => w.date === date)
    const ws = win ? wallMin(win.start) : DAY_END
    const we = win ? wallMin(win.end) : DAY_END
    return (
      <div className="oo-track" role="img" aria-label={`${who}: busy blocks on ${date}`}>
        <span className="off" style={{ left: 0, width: pct(ws) }} />
        <span className="off" style={{ left: pct(we), right: 0 }} />
        {list
          .filter((b) => onDay(b, date))
          .map((b, i) => {
            const [bs, be] = span(b, date)
            if (Math.min(be, DAY_END) <= Math.max(bs, DAY_START)) return null
            return (
              <span
                key={i}
                className={`busy ${b.status}`}
                style={{ left: pct(bs), width: `calc(${pct(be)} - ${pct(bs)})` }}
                title={`${fmtWall(toHHMM(bs))} to ${fmtWall(toHHMM(Math.min(be, 1439)))} ${b.status}`}
              />
            )
          })}
        {startMin !== null && (
          <span className="slot" style={{ left: pct(startMin), width: `calc(${pct(startMin + minutes)} - ${pct(startMin)})` }} />
        )}
      </div>
    )
  }

  const today = new Date().toLocaleDateString('en-CA')
  const maxDay = new Date(Date.now() + 120 * 86400000).toLocaleDateString('en-CA')
  const subject = avail?.subject || `owner & ${person.first} 1:1`
  const tr = booked?.transcription
  const whenLabel =
    date && time
      ? `${fmtDay(date, true)}, ${fmtWall(time)} to ${fmtWall(toHHMM(Math.min((startMin || 0) + minutes, 1439)))} ET`
      : 'Pick a time'

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      hue="blue"
      icon={<IconPlus />}
      title={booked ? `\u2713 Booked and sent: ${subject}` : subject}
      subtitle={`Schedule 1:1 \u00b7 Teams meeting from my calendar \u00b7 invite to ${person.email} \u00b7 times in ET`}
      busy={sending}
      cancelLabel={booked ? null : 'Cancel'}
      footerStart={
        booked ? (
          booked.web_link ? (
            <a className="btn oo-link-btn" data-variant="secondary" data-size="sm" href={booked.web_link} target="_blank" rel="noreferrer">
              Open in Outlook
            </a>
          ) : undefined
        ) : (
          <span className="oo-who">{whenLabel}</span>
        )
      }
      primaryAction={
        booked
          ? { label: 'Done', onClick: onClose }
          : {
              label: sending ? 'Booking...' : fit?.tone === 'bad' ? 'Send invite anyway' : 'Send invite',
              onClick: send,
              disabled: !date || !time || sending || fit?.label === 'That time has passed',
            }
      }
    >
      {booked ? (
        <ModalSection
          title={`${fmtDay(booked.start.slice(0, 10), true)}, ${fmtWall(booked.start.slice(11, 16))} to ${fmtWall(booked.end.slice(11, 16))} ET`}
        >
          <ul className="oo-booked">
            <li>
              Invite sent to {booked.attendee || person.email} with {booked.agenda_items} agenda items in the body
            </li>
            <li>
              Teams meeting{booked.join_url ? ' with join link' : ''} &middot; transcription{' '}
              {tr?.applied?.allowTranscription ? 'allowed' : 'not confirmed'}
              {tr?.applied?.recordAutomatically ? ', records and transcribes automatically from the start' : ''}
            </li>
            {tr?.error && <li className="is-warn">Meeting options: {tr.error}</li>}
          </ul>
        </ModalSection>
      ) : (
        <>
          <ModalSection title="Suggested times" description="Both calendars free, inside shared working hours, next 2 weeks">
            {loadErr ? (
              <Tone hue="red" className="pp-note" role="alert">
                Could not read free/busy: {loadErr}
                {/sign-in|login|reauth/i.test(loadErr) ? ' (run ops_center-calendar.py --login)' : ''}
                <Button size="sm" variant="ghost" onClick={() => setAttempt((n) => n + 1)}>
                  Retry
                </Button>
              </Tone>
            ) : !avail ? (
              <div className="oo-sugg" aria-busy="true">
                {[0, 1, 2, 3, 4, 5].map((i) => (
                  <Skeleton key={i} variant="line" count={1} className="oo-sugg-skel" label="Loading suggested times" />
                ))}
              </div>
            ) : avail.suggestions.length === 0 ? (
              <p className="oo-hint">No shared openings in the next two weeks. Pick a time below.</p>
            ) : (
              <div className="oo-sugg">
                {avail.suggestions.map((s) => {
                  const d = s.start.slice(0, 10)
                  const t = s.start.slice(11, 16)
                  const on = d === date && t === time
                  return (
                    <button
                      key={s.start}
                      type="button"
                      className={`oo-slot${on ? ' is-selected' : ''}`}
                      aria-pressed={on}
                      onClick={() => {
                        setDate(d)
                        setTime(t)
                      }}
                    >
                      <small>{fmtDay(d)}</small>
                      <b>{fmtWall(t)}</b>
                    </button>
                  )
                })}
              </div>
            )}
            {avail && (avail.me.error || avail.them.error) && (
              <Tone hue="amber" className="pp-note oo-gap-note">
                {avail.them.error ? `${person.first}'s free/busy: ${avail.them.error}. ` : ''}
                {avail.me.error ? `My free/busy: ${avail.me.error}.` : ''}
              </Tone>
            )}
          </ModalSection>

          <ModalSection title="When">
            <div className="oo-pick">
              <Field label="Date">
                <Input type="date" value={date} min={today} max={maxDay} onChange={(e) => setDate(e.target.value)} />
              </Field>
              <Field label="Start">
                <Input type="time" value={time} step={900} onChange={(e) => setTime(e.target.value)} />
              </Field>
              <div className="field">
                <span className="field-label">Length</span>
                <Segmented label="Length" options={DURATIONS} value={String(minutes)} onChange={(v) => setMinutes(Number(v))} />
              </div>
              {fit && (
                <Badge tone={FIT_TONE[fit.tone]} dot className="oo-fit">
                  {fit.label}
                </Badge>
              )}
            </div>
            {avail && date && (
              <div className="oo-day">
                <span />
                <div className="oo-hours" aria-hidden="true">
                  {HOUR_MARKS.map((h) => (
                    <span key={h} style={{ left: pct(h * 60) }}>
                      {((h + 11) % 12) + 1}
                      {h < 12 ? 'a' : 'p'}
                    </span>
                  ))}
                </div>
                <span>Me</span>
                {track(avail.me.busy, 'Me')}
                <span>{person.first}</span>
                {track(avail.them.busy, person.first)}
              </div>
            )}
          </ModalSection>

          <ModalSection
            title="Agenda"
            description={`${lines.length} item${lines.length === 1 ? '' : 's'} from the open topics \u00b7 goes in the invite, ${person.first} will see it`}
          >
            <Textarea
              className="oo-agenda-edit"
              aria-label="Agenda"
              value={agenda}
              onChange={(e) => setAgenda(e.target.value)}
              rows={Math.min(12, Math.max(4, lines.length + 1))}
              placeholder="- One line per agenda item"
            />
            <label className="oo-check">
              <input type="checkbox" checked readOnly disabled />
              <span>Transcription allowed on the Teams meeting</span>
            </label>
            <label className="oo-check">
              <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
              <span>Record and transcribe automatically when the meeting starts</span>
            </label>
          </ModalSection>

          {sendErr && (
            <Tone hue="red" className="pp-note" role="alert">
              Could not book: {sendErr}
            </Tone>
          )}
        </>
      )}
    </Modal>
  )
}

function TopicCard({
  t,
  n,
  onState,
  onRemove,
}: {
  t: Topic
  n?: number
  onState: (t: Topic, s: TopicState) => void
  onRemove: (t: Topic) => void
}) {
  const [thread, setThread] = useState(false)
  const src = SRC[t.source]
  const prio = (t.priority || '').toUpperCase()
  const auto = t.source === 'teams' || t.source === 'mail'
  const covered = t.state !== 'open'
  return (
    <article className={`oo-topic st-${t.state}${covered ? ' is-covered' : ''}${t.hot ? ' tone hue-red' : ''}`}>
      <div className="oo-topic-top">
        {n !== undefined && <span className="oo-num">{n}</span>}
        <Badge hue={src.hue}>{auto ? `${src.label} \u00b7 ${t.kind}` : src.label}</Badge>
        {prio && <Badge tone={PRIO_TONE[prio] || 'neutral'}>{prio}</Badge>}
        {t.hot && (
          <Badge tone="danger" dot>
            hot
          </Badge>
        )}
        {t.flagged && t.source !== 'action' && <Badge tone="warning">monitor flagged</Badge>}
        {t.reopened && <Badge tone="info">new reply</Badge>}
        {t.ac_fp && !t.action_done_at && (t.my_action || t.source === 'action') && (
          <Link className="badge oo-ac-link" data-tone="warning" to={`/action?item=${t.ac_fp}`} onClick={(e) => e.stopPropagation()}>
            on Action Center &rarr;
          </Link>
        )}
        {t.action_done_at && t.state === 'open' && (
          <Link className="badge oo-ac-link" data-tone="info" to={`/action?item=${t.ac_fp}`} onClick={(e) => e.stopPropagation()}>
            done, still need to tell them
          </Link>
        )}
        {(t.related?.length || 0) > 0 && (
          <Badge hue="violet">
            {t.related?.length ?? 0} live thread{(t.related?.length ?? 0) > 1 ? 's' : ''}
          </Badge>
        )}
        <span className="oo-when">{auto ? relTime(t.last_at) : t.feed_last_at ? `last message ${relTime(t.feed_last_at)}` : ''}</span>
      </div>
      <div className="oo-title">{t.title}</div>
      {t.detail && <div className="oo-detail">{t.detail}</div>}
      {t.my_action && (
        <div className="oo-detail">
          <b>My action{t.action_done_at ? ' (done)' : ''}:</b> {t.my_action}
        </div>
      )}
      {t.context && (
        <Tone hue="amber" className="oo-why">
          <b>Why</b>
          {t.context}
        </Tone>
      )}
      {(t.refs.length > 0 || t.messages.length > 0 || t.link) && (
        <div className="oo-meta">
          {t.refs.map((r) => (
            <Tkt key={r} id={r} />
          ))}
          {t.messages.length > 0 && (
            <Button size="sm" variant="ghost" onClick={() => setThread((s) => !s)} aria-expanded={thread}>
              {thread ? 'Hide thread' : `Show thread (${t.messages.length})`}
            </Button>
          )}
          {t.link && (
            <a className="btn oo-link-btn" data-variant="ghost" data-size="sm" href={t.link} target="_blank" rel="noreferrer">
              Open in {(t.link_source || t.source) === 'mail' ? 'Outlook' : 'Teams'}
            </a>
          )}
        </div>
      )}
      {thread && (
        <div className="oo-thread">
          {t.messages.map((m, i) => (
            <div key={m.id || i} className={`bubble ${m.who === 'me' ? 'me' : 'them'}`}>
              <div className="bubble-meta">
                {m.who === 'me' ? 'Me' : m.who === 'them' ? t.person.split(' ')[0] : m.who} &middot; {relTime(m.at)}
              </div>
              {m.text}
            </div>
          ))}
        </div>
      )}
      <div className="oo-actions">
        {t.state === 'open' ? (
          <>
            <Button
              size="sm"
              variant="secondary"
              className="oo-discussed"
              icon={<IconCheck size={14} />}
              onClick={() => onState(t, 'discussed')}
            >
              Discussed
            </Button>
            <Button size="sm" variant="ghost" onClick={() => onState(t, 'not_needed')}>
              Not needed
            </Button>
          </>
        ) : (
          <>
            <Badge tone={t.state === 'discussed' ? 'success' : 'neutral'} dot>
              {t.state === 'discussed' ? 'Discussed' : 'Not needed'}
              {t.state_at ? ` \u00b7 ${relTime(t.state_at)}` : ''}
            </Badge>
            <Button size="sm" variant="ghost" onClick={() => onState(t, 'open')}>
              Reopen
            </Button>
          </>
        )}
        {t.source === 'me' && (
          <Button size="sm" variant="ghost" className="oo-delete" onClick={() => onRemove(t)}>
            Delete
          </Button>
        )}
      </div>
    </article>
  )
}
