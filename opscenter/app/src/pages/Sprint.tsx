// Jira hub > Sprint: the active sprint scoped to me (default) or the team
// team. Time-vs-done pace bars, per-person progress for the team, a board by
// status category, and inline status changes / back-to-backlog on MY items
// only. Closing is deliberately not here: it runs through my closure-comment
// process (server refuses done-category transitions too).
// Kit build: Toolbar (scope Segmented, refresh), a sprint Card, StatTile strip, Avatar person
// tiles with the raised .is-selected state, and board columns of issue cards.
import type { DotTone, SegmentedOption, StatTone } from '@kit'
import {
  Avatar,
  Badge,
  Button,
  Card,
  CardHead,
  EmptyState,
  Pill,
  Segmented,
  Skeleton,
  StatTile,
  StatusDot,
  Toolbar,
  useConfirm,
} from '@kit'
import { useMemo, useState } from 'react'
import { confirmText } from '../components/confirmText'
import { InHermes } from '../components/InHermes'
import { LinkButton, LoadError } from '../components/StateBlocks'
import { TackleJira } from '../components/TackleJira'
import type { JiraTransition, SprintItem } from '../lib/data'
import { fetchTransitions, postSprintRemove, postTransition, useBacklog, useJiraSprint, useLocalStore, useNow } from '../lib/data'
import { fmtDate, priorityTone, TOKEN_HINT } from './Backlog'

type Scope = 'mine' | 'team'
type Tone = 'good' | 'warn' | 'alert'
interface View {
  scope: Scope
  hideDone: boolean
  person: string
}

const DAY = 864e5
const STALE_DAYS = 5
const COLS: { cat: string; label: string; dot: DotTone }[] = [
  { cat: 'new', label: 'To Do', dot: 'neutral' },
  { cat: 'indeterminate', label: 'In Progress', dot: 'info' },
  { cat: 'done', label: 'Done', dot: 'success' },
]
const STAT_TONE: Record<Tone, StatTone> = { good: 'success', warn: 'warning', alert: 'danger' }

const catOf = (i: SprintItem) => (['new', 'indeterminate', 'done'].includes(i.status_category) ? i.status_category : 'new')
const isHold = (i: SprintItem) => /hold/i.test(i.status)
const firstName = (n: string) => n.split(' ')[0]
const errText = (e: unknown) => (e instanceof Error ? e.message : String(e))

function sprintClock(start: string, end: string, now: number) {
  const s = Date.parse(start)
  const e = Date.parse(end)
  if (Number.isNaN(s) || Number.isNaN(e) || e <= s) return null
  const days = Math.max(1, Math.round((e - s) / DAY))
  return {
    days,
    day: Math.min(days, Math.max(1, Math.floor((now - s) / DAY) + 1)),
    left: Math.max(0, Math.ceil((e - now) / DAY)),
    pct: Math.max(0, Math.min(100, ((now - s) / (e - s)) * 100)),
  }
}

function stats(items: SprintItem[], now: number) {
  const by = (c: string) => items.filter((i) => catOf(i) === c)
  const done = by('done')
  const pts = items.reduce((n, i) => n + (i.points ?? 0), 0)
  return {
    total: items.length,
    done: done.length,
    prog: by('indeterminate').length,
    todo: by('new').length,
    hold: items.filter((i) => catOf(i) === 'new' && isHold(i)).length,
    stale: items.filter((i) => catOf(i) === 'indeterminate' && (now - Date.parse(i.updated)) / DAY >= STALE_DAYS).length,
    pts,
    ptsDone: done.reduce((n, i) => n + (i.points ?? 0), 0),
    pct: items.length ? (done.length / items.length) * 100 : 0,
  }
}

// Done-% judged against time elapsed, not an absolute bar: mid-sprint 40%
// done is fine, so a static 90/75 threshold would paint everyone red.
function paceTone(donePct: number, timePct: number): Tone {
  if (donePct >= timePct - 10) return 'good'
  if (donePct >= timePct - 25) return 'warn'
  return 'alert'
}

/** A progress track. Data mark, not an accent: the fill length is the value. */
function Bar({ pct, tone, label }: { pct: number; tone: Tone | 'time'; label: string }) {
  return (
    <div className="sp-bar" role="img" aria-label={`${label} ${Math.round(pct)}%`}>
      <div className={`sp-fill ${tone}`} style={{ width: `${pct}%` }} />
    </div>
  )
}

function IssueCard({
  it,
  showWho,
  now,
  onChanged,
  onRemoved,
}: {
  it: SprintItem
  showWho: boolean
  now: number
  onChanged: (key: string, status: string, cat: string) => void
  onRemoved: (key: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [trans, setTrans] = useState<JiraTransition[] | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const { confirm: ask, dialog } = useConfirm()
  const cat = catOf(it)
  const done = cat === 'done'
  const age = (now - Date.parse(it.updated)) / DAY
  const stale = cat === 'indeterminate' && age >= STALE_DAYS
  const overdue = !!it.due && !done && Date.parse(it.due) + DAY < now
  const colLabel = COLS.find((c) => c.cat === cat)?.label

  const toggle = async () => {
    const next = !open
    setOpen(next)
    setErr(null)
    if (next && trans === null) {
      try {
        setTrans((await fetchTransitions(it.key)).transitions)
      } catch (e) {
        setErr(errText(e))
        setTrans([])
      }
    }
  }
  const go = async (t: JiraTransition) => {
    setBusy(t.id)
    setErr(null)
    try {
      const r = await postTransition(it.key, t.id)
      onChanged(it.key, r.status, r.status_category)
    } catch (e) {
      setErr(errText(e))
      setBusy(null)
    }
  }
  const pull = async () => {
    const ok = await ask({
      ...confirmText(`Pull ${it.key} out of the sprint and back to my backlog? Jira logs it as a scope change.`),
      confirmLabel: 'Pull from sprint',
    })
    if (!ok) return
    setBusy('pull')
    setErr(null)
    try {
      await postSprintRemove(it.key)
      onRemoved(it.key)
    } catch (e) {
      setErr(errText(e))
      setBusy(null)
    }
  }

  // One button per target status (the tracker has both "Start Task" and "In Progress"
  // landing on In Progress), never the status it is already in.
  const moves = (trans || []).filter(
    (t, idx, arr) => t.allowed && t.to !== it.status && arr.findIndex((x) => x.allowed && x.to === t.to) === idx,
  )
  const hasCloser = (trans || []).some((t) => t.to_category === 'done')
  const mineInTeam = it.mine && showWho

  return (
    <article className={`sp-card${done ? ' done' : ''}${mineInTeam ? ' tone hue-blue' : ''}`}>
      {dialog}
      <div className="sp-card-top">
        <a className="tkt" href={it.url} target="_blank" rel="noreferrer">
          {it.key}
        </a>
        <InHermes ticket={it.key} />
        {!done && (
          <Pill tone={priorityTone(it.priority)} dot>
            {it.priority || 'None'}
          </Pill>
        )}
        {it.status !== colLabel && <Badge tone={isHold(it) ? 'warning' : 'neutral'}>{it.status}</Badge>}
        {it.points !== null && <span className="sp-pts">{it.points} pts</span>}
      </div>
      <div className="sp-sum">{it.summary}</div>
      <div className="sp-meta">
        {showWho && (
          <span className="sp-who">
            <Avatar name={it.assignee || 'Unassigned'} size="sm" />
            {it.mine ? 'Me' : firstName(it.assignee)}
          </span>
        )}
        <span className="sp-type">{it.issuetype}</span>
        {it.parent_key && (
          <a
            className="sp-epic"
            href={`https://atlassian_host/browse/${it.parent_key}`}
            target="_blank"
            rel="noreferrer"
            title={`${it.parent_key} ${it.parent_summary}`}
          >
            {it.parent_summary || it.parent_key}
          </a>
        )}
        {!done && it.carry > 0 && <Pill tone={it.carry >= 3 ? 'danger' : 'warning'}>carried {it.carry}x</Pill>}
        {stale && <Pill tone="warning">no update {Math.floor(age)}d</Pill>}
        {overdue && <Pill tone="danger">due {fmtDate(it.due)}</Pill>}
      </div>
      {it.mine && !done && (
        <div className="sp-act">
          <div className="sp-act-row">
            <Button size="sm" onClick={toggle} disabled={!!busy} aria-expanded={open}>
              {open ? 'Cancel' : 'Update'}
            </Button>
            <TackleJira issueKey={it.key} summary={it.summary} compact />
          </div>
          {open && (
            <div className="sp-menu">
              {trans === null && <Skeleton variant="line" label="Loading transitions..." />}
              {moves.map((t) => (
                <Button key={t.id} size="sm" variant="primary" disabled={!!busy} loading={busy === t.id} onClick={() => go(t)}>
                  {busy === t.id ? 'Moving...' : t.to}
                </Button>
              ))}
              <Button size="sm" variant="ghost" disabled={!!busy} loading={busy === 'pull'} onClick={pull}>
                {busy === 'pull' ? 'Moving...' : 'Back to backlog'}
              </Button>
              {hasCloser && (
                <p className="sp-note">
                  Closing needs a closure comment, so it is not a button here.{' '}
                  <a href={it.url} target="_blank" rel="noreferrer">
                    Open in Jira
                  </a>{' '}
                  or use Tackle and pick "Close the ticket in Jira" when the work is done.
                </p>
              )}
            </div>
          )}
          {err && (
            <p className="sp-err" role="alert">
              {err}
            </p>
          )}
        </div>
      )}
    </article>
  )
}

export default function Sprint() {
  const { data, error, loading, refresh, mutate } = useJiraSprint()
  const backlog = useBacklog()
  const now = useNow(60_000)
  const [view, setView] = useLocalStore<View>('jira-sprint-view-v1', { scope: 'mine', hideDone: false, person: '' })
  const sp = data?.sprint ?? null
  const all = useMemo(() => data?.items || [], [data])
  const team = view.scope === 'team'
  const scoped = team ? all : all.filter((i) => i.mine)
  const shown = team && view.person ? scoped.filter((i) => i.assignee === view.person) : scoped
  const st = stats(shown, now)
  const allSt = stats(all, now)
  const clock = sp ? sprintClock(sp.start, sp.end, now) : null
  const tone = clock ? paceTone(st.pct, clock.pct) : undefined

  const people = useMemo(() => {
    const m = new Map<string, SprintItem[]>()
    for (const i of all) m.set(i.assignee, [...(m.get(i.assignee) || []), i])
    return [...m.entries()]
      .map(([name, items]) => ({ name, mine: items.some((i) => i.mine), st: stats(items, now) }))
      .sort((a, b) => Number(a.mine) - Number(b.mine) || b.st.total - b.st.done - (a.st.total - a.st.done))
  }, [all, now])

  const setScope = (scope: Scope) => setView((v) => ({ ...v, scope, person: '' }))
  const onChanged = (key: string, status: string, cat: string) =>
    mutate((d) => ({
      ...d,
      items: d.items.map((i) => (i.key === key ? { ...i, status, status_category: cat, updated: new Date().toISOString() } : i)),
    }))
  const onRemoved = (key: string) => {
    mutate((d) => ({ ...d, items: d.items.filter((i) => i.key !== key) }))
    window.setTimeout(() => backlog.refresh(), 5000)
  }

  const columns = COLS.filter((c) => !(view.hideDone && c.cat === 'done'))
  const scopes: SegmentedOption<Scope>[] = [
    { value: 'mine', label: 'Mine' },
    { value: 'team', label: 'team team' },
  ]

  return (
    <div className="page">
      <p className="jr-lede">
        {team ? 'Every team item in the active sprint.' : 'My items in the active sprint.'} Updates write straight to Jira. I can only
        change my own items here.
      </p>

      <Toolbar
        label="Sprint controls"
        onRefresh={() => refresh()}
        refreshing={loading}
        updatedAt={data ? Date.parse(data.generated_utc) || null : null}
      >
        <Segmented label="Sprint scope" options={scopes} value={view.scope} onChange={setScope} />
      </Toolbar>

      {error && !data && (
        <Card>
          <LoadError title="Could not load the sprint from Jira" error={error} hint={TOKEN_HINT} />
        </Card>
      )}
      {!data && !error && (
        <div className="sp-loading">
          <Skeleton variant="card" label="Loading the sprint from Jira..." />
          <Skeleton variant="table" count={4} columns={3} />
        </div>
      )}
      {data && !sp && (
        <Card>
          <EmptyState title="No active sprint on the board right now." pose="shrug" />
        </Card>
      )}

      {sp && (
        <Card className="sp-band" elevated>
          <CardHead
            icon={<StatusDot tone="success" label="Active sprint" />}
            title={sp.name}
            subtitle={
              <>
                {fmtDate(sp.start)} to {fmtDate(sp.end)}
                {clock && (
                  <>
                    {' '}
                    &middot; Day {clock.day} of {clock.days} &middot;{' '}
                    {clock.left === 0 ? 'ends today' : `${clock.left} day${clock.left === 1 ? '' : 's'} left`}
                  </>
                )}
              </>
            }
            controls={
              <LinkButton external href={`https://atlassian_host/secure/RapidBoard.jspa?rapidView=${sp.board_id}`}>
                Board in Jira &rarr;
              </LinkButton>
            }
          />
          {clock && (
            <div className="sp-bars">
              <span>Time elapsed</span>
              <Bar pct={clock.pct} tone="time" label="Time elapsed" />
              <span className="sp-bars-n">{Math.round(clock.pct)}%</span>
              <span>{team ? (view.person ? `${firstName(view.person)} done` : 'Team done') : 'My items done'}</span>
              <Bar pct={st.pct} tone={tone ?? 'good'} label="Done" />
              <span className="sp-bars-n">{Math.round(st.pct)}%</span>
            </div>
          )}
          {sp.goal && <p className="sp-goal">Goal: {sp.goal}</p>}
        </Card>
      )}

      {sp && (
        <div className="jr-stats sp-stats kpi-strip">
          <StatTile value={st.total} label={team ? (view.person ? `${firstName(view.person)}'s items` : 'team items') : 'my items'} />
          <StatTile
            value={`${st.done}/${st.total}`}
            label={`done, ${tone === 'good' ? 'on pace' : 'behind pace'}`}
            tone={tone ? STAT_TONE[tone] : 'accent'}
          />
          <StatTile
            value={st.prog}
            label={st.stale ? `in progress (${st.stale} quiet ${STALE_DAYS}d+)` : 'in progress'}
            tone={st.stale ? 'warning' : 'info'}
          />
          <StatTile value={st.todo} label={st.hold ? `to do (${st.hold} on hold)` : 'to do'} hue="teal" />
          <StatTile value={`${st.ptsDone}/${st.pts}`} label="points done" hue="violet" />
        </div>
      )}

      {sp && team && (
        <Card>
          <CardHead title="team team" subtitle="Click a person to filter the board" />
          <div className="sp-people">
            <button
              type="button"
              aria-pressed={!view.person}
              className={`sp-person${!view.person ? ' is-selected' : ''}`}
              onClick={() => setView((v) => ({ ...v, person: '' }))}
            >
              <div className="sp-person-top">
                <b>Everyone</b>
                <span>
                  {allSt.done}/{all.length} done
                </span>
              </div>
              <Bar pct={allSt.pct} tone={clock ? paceTone(allSt.pct, clock.pct) : 'good'} label="Everyone done" />
              <div className="sp-person-sub">{people.length} people</div>
            </button>
            {people.map((p) => (
              <button
                type="button"
                key={p.name}
                aria-pressed={view.person === p.name}
                className={`sp-person${view.person === p.name ? ' is-selected' : ''}`}
                onClick={() => setView((v) => ({ ...v, person: v.person === p.name ? '' : p.name }))}
              >
                <div className="sp-person-top">
                  <span className="sp-person-name">
                    <Avatar name={p.name || 'Unassigned'} size="sm" />
                    <b>{p.mine ? 'Me' : p.name}</b>
                  </span>
                  <span>
                    {p.st.done}/{p.st.total} done
                  </span>
                </div>
                <Bar pct={p.st.pct} tone={clock ? paceTone(p.st.pct, clock.pct) : 'good'} label={`${p.name} done`} />
                <div className="sp-person-sub">
                  {p.st.prog} in progress &middot; {p.st.todo} to do &middot; {p.st.ptsDone}/{p.st.pts} pts
                  {p.st.stale ? ` \u00b7 ${p.st.stale} quiet` : ''}
                </div>
              </button>
            ))}
          </div>
        </Card>
      )}

      {sp && (
        <>
          <div className="sp-board-ctl">
            <Button size="sm" aria-pressed={view.hideDone} onClick={() => setView((v) => ({ ...v, hideDone: !v.hideDone }))}>
              {view.hideDone ? `Show done (${st.done})` : 'Hide done'}
            </Button>
            {data && (
              <span className="sp-note">
                Synced {new Date(data.generated_utc).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
              </span>
            )}
          </div>
          <div className="sp-board">
            {columns.map((c) => {
              const items = shown.filter((i) => catOf(i) === c.cat).sort((a, b) => Number(isHold(a)) - Number(isHold(b)))
              const pts = items.reduce((n, i) => n + (i.points ?? 0), 0)
              return (
                <section key={c.cat} className="sp-col" aria-label={c.label}>
                  <div className="sp-col-head">
                    <StatusDot tone={c.dot} pulse={false} />
                    <span>{c.label}</span>
                    <Badge>{items.length}</Badge>
                    {pts > 0 && <span className="sp-col-pts">{pts} pts</span>}
                  </div>
                  {items.length === 0 && <p className="sp-col-empty">Nothing here</p>}
                  {items.map((it) => (
                    <IssueCard key={it.key} it={it} showWho={team} now={now} onChanged={onChanged} onRemoved={onRemoved} />
                  ))}
                </section>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}
