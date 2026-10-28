import type { SegmentedOption, StatusTone } from '@kit'
import {
  Button,
  Card,
  EmptyState,
  IconSearch,
  Input,
  Modal,
  ModalSection,
  Pill,
  Segmented,
  Skeleton,
  Toolbar,
  useConfirm,
  useToast,
} from '@kit'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useCopyDialog } from '../components/CopyDialog'
import { HubHeader } from '../components/HubHeader'
import { Markdown } from '../components/Markdown'
import { LoadError } from '../components/StateBlocks'
import type { PlanFreshness, PlanItem, PlanProject, PlanUntracked, PlanUntrackedRow } from '../lib/data'
import { fetchPlanFile, postPlanArchive, postPlanCreate, postPlanDismiss, postPlanRestore, usePlans } from '../lib/data'
import './Plans.css'

// Plans: what we are actively building and the plans behind it, read live from state/plans.
//   Projects: one card per projects/<slug>/ folder, driven by its tracker.md front matter (status,
//             summary, next step, tickets) and its Next steps checkboxes, plus the project's documents.
//   Library:  standalone plans in SBAR form (library/*.md).
//   Archive:  finished or dropped work. Archive and Restore move files, nothing is ever deleted here.
// Messages are not tracked at all: they go straight to Teams, Outlook or the chat. The file format
// lives in state/plans/.format.md.

// Strip a leading --- front matter block. The reader shows those keys as its own header instead.
function stripFront(text: string): string {
  const lines = text.split('\n')
  if (lines[0]?.trim() !== '---') return text
  const end = lines.findIndex((l, i) => i > 0 && l.trim() === '---')
  if (end < 0 || end > 80) return text
  return lines.slice(end + 1).join('\n')
}

type View = 'projects' | 'library' | 'archive'
const VIEWS: View[] = ['projects', 'library', 'archive']

const STATUS_TONE: Record<string, StatusTone> = {
  active: 'info',
  'in-progress': 'info',
  approved: 'success',
  current: 'neutral',
  proposed: 'accent',
  paused: 'warning',
  parked: 'neutral',
  done: 'success',
}
const statusLabel = (s: string) => (s ? s.charAt(0).toUpperCase() + s.slice(1).replace(/-/g, ' ') : '')

const fmtDay = (ymd: string) => {
  const d = new Date(`${ymd}T12:00:00`)
  if (Number.isNaN(d.getTime())) return ymd
  const now = new Date()
  const days = Math.round(
    (new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() -
      new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()) /
      86400000,
  )
  if (days === 0) return 'today'
  if (days === 1) return 'yesterday'
  if (days > 1 && days < 7) return `${days} days ago`
  return d.toLocaleDateString(
    [],
    d.getFullYear() === now.getFullYear() ? { month: 'short', day: 'numeric' } : { month: 'short', day: 'numeric', year: 'numeric' },
  )
}

function StatusPill({ status }: { status: string }) {
  return (
    <Pill tone={STATUS_TONE[status] || 'neutral'} dot>
      {statusLabel(status)}
    </Pill>
  )
}

function Tickets({ d }: { d: PlanItem }) {
  if (!d.tickets.length) return null
  return (
    <span className="pl-tix">
      {d.tickets.map((k) => {
        const st = d.ticket_status[k]
        return (
          <a
            key={k}
            className={`pl-tix-link${st?.done ? ' is-done' : ''}`}
            href={`https://atlassian_host/browse/${k}`}
            target="_blank"
            rel="noreferrer noopener"
            data-tip={st ? `${k}: ${st.status}` : k}
            onClick={(e) => e.stopPropagation()}
          >
            {k}
          </a>
        )
      })}
    </span>
  )
}

// ---- reader: one document in a sheet, relative .md links open the sibling in place ----
function Reader({
  d,
  onOpenRel,
  onMove,
}: {
  d: PlanItem
  onOpenRel: (id: string) => void
  onMove: (target: { id: string; version: string; name: string }, restore: boolean) => Promise<void>
}) {
  const [text, setText] = useState<string | null | undefined>(undefined)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState(false)
  const { showCopy, dialog: copyDialog } = useCopyDialog()

  useEffect(() => {
    let live = true
    setText(undefined)
    setErr('')
    fetchPlanFile(d.id, d.version)
      .then((r) => live && setText(r.text))
      .catch((e) => live && setErr(e instanceof Error ? e.message : String(e)))
    return () => {
      live = false
    }
  }, [d.id, d.version])

  const copyPath = async () => {
    try {
      await navigator.clipboard.writeText(d.path)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1600)
    } catch {
      showCopy('Copy the file path', d.path)
    }
  }
  const move = async () => {
    setBusy(true)
    setErr('')
    try {
      await onMove({ id: d.id, version: d.version, name: d.title }, d.archived)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }
  const openRel = (href: string) => {
    const base = d.id.split('/').slice(0, -1)
    for (const part of href.split('/')) {
      if (part === '..') base.pop()
      else if (part && part !== '.') base.push(part)
    }
    onOpenRel(base.join('/'))
  }

  return (
    <>
      <div className="pl-r-head">
        <div className="pl-r-meta">
          <Pill tone="neutral">{d.type_label}</Pill>
          <StatusPill status={d.status} />
          <span className="pl-faint">Updated {fmtDay(d.updated)}</span>
          {d.owner && <span className="pl-faint">Owner {d.owner}</span>}
          <Tickets d={d} />
        </div>
        <div className="pl-btns">
          <Button size="sm" variant="ghost" onClick={copyPath}>
            {copied ? 'Copied' : 'Copy path'}
          </Button>
          {d.name !== 'tracker.md' && (
            <Button
              size="sm"
              variant="secondary"
              loading={busy}
              onClick={move}
              data-tip={d.archived ? 'Moves it back where it came from' : 'Moves it to state/plans/archive/'}
            >
              {d.archived ? 'Restore' : 'Archive'}
            </Button>
          )}
        </div>
        {err && (
          <p className="pl-err" role="alert">
            {err}
          </p>
        )}
      </div>
      {d.summary && (
        <ModalSection title="Summary">
          <p className="pl-summary">{d.summary}</p>
          {d.next && (
            <p className="pl-next" style={{ marginTop: 'var(--space-3)' }}>
              <b>Next</b>
              {d.next}
            </p>
          )}
        </ModalSection>
      )}
      <ModalSection title="Document">
        {text === undefined && !err ? (
          <Skeleton variant="lines" count={10} label="Loading the document" />
        ) : text === null ? (
          <EmptyState compact title="Too large to preview" body="Copy the path and open it in an editor." />
        ) : (
          <Markdown body={stripFront(text || '')} onLink={openRel} />
        )}
      </ModalSection>
      {copyDialog}
    </>
  )
}

// ---- freshness: work that landed after the tracker was last updated ----
const EVENT_VERB: Record<string, string> = { merged: 'merged', opened: 'opened', status: 'moved' }

function FreshPill({ f }: { f?: PlanFreshness }) {
  if (!f) return null
  if (f.state === 'error')
    return (
      <Pill tone="neutral" data-tip={`Could not check PRs and tickets: ${f.errors[0] || 'read failed'}`}>
        Check failed
      </Pill>
    )
  if (!f.behind) return null
  const tip = f.events.map((e) => `${e.ref} ${EVENT_VERB[e.kind] || e.kind} ${fmtDay(e.day)}`).join(', ')
  return (
    <Pill tone="warning" dot data-tip={`Work landed after this tracker was updated: ${tip}`}>
      Behind
    </Pill>
  )
}

function FreshLine({ f }: { f?: PlanFreshness }) {
  if (!f?.behind) return null
  return (
    <p className="pl-behind">
      <b>Since the tracker</b>
      {f.events.map((e, i) => (
        <span key={`${e.ref}-${e.kind}`}>
          {i > 0 && ', '}
          <a href={e.url} target="_blank" rel="noreferrer noopener" data-tip={e.title} onClick={(ev) => ev.stopPropagation()}>
            {e.ref}
          </a>{' '}
          {EVENT_VERB[e.kind] || e.kind} {fmtDay(e.day)}
        </span>
      ))}
    </p>
  )
}

// ---- project card ----
function ProjectCard({ p, onOpen, onArchive }: { p: PlanProject; onOpen: (id: string) => void; onArchive: () => void }) {
  const t = p.tracker
  const prog = t?.progress
  const pct = prog && prog.total ? Math.round((prog.done / prog.total) * 100) : 0
  return (
    <Card>
      <div className="pl-proj">
        <div className="pl-proj-top">
          {t ? (
            <button type="button" className="pl-proj-title" onClick={() => onOpen(t.id)}>
              {p.title}
            </button>
          ) : (
            <span className="pl-proj-title">{p.title}</span>
          )}
          <span className="pl-proj-pills">
            <FreshPill f={p.freshness} />
            <StatusPill status={p.status} />
          </span>
        </div>
        {t && <Tickets d={t} />}
        {t?.summary ? (
          <p className="pl-summary">{t.summary}</p>
        ) : (
          !t && <p className="pl-faint">No tracker.md yet in this project folder.</p>
        )}
        {t?.next && (
          <p className="pl-next">
            <b>Next</b>
            {t.next}
          </p>
        )}
        <FreshLine f={p.freshness} />
        {prog && prog.total > 0 && (
          <div className="pl-progress" aria-label={`${prog.done} of ${prog.total} steps done`}>
            <div className="pl-bar">
              <span style={{ width: `${pct}%` }} />
            </div>
            <span>
              {prog.done} of {prog.total} steps
            </span>
          </div>
        )}
        {p.docs.length > 0 && (
          <ul className="pl-docs" aria-label="Documents">
            {p.docs.map((d) => (
              <li key={d.id}>
                <button type="button" className="pl-doc" onClick={() => onOpen(d.id)} data-tip={d.summary || d.name}>
                  <span className="pl-doc-type">{d.type_label}</span>
                  {d.title}
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="pl-proj-foot">
          <span className="pl-faint">Updated {fmtDay(p.updated)}</span>
          <span style={{ display: 'flex', gap: 'var(--space-2)' }}>
            {t && (
              <Button size="sm" variant="primary" onClick={() => onOpen(t.id)}>
                Open tracker
              </Button>
            )}
            <Button size="sm" variant="ghost" onClick={onArchive} data-tip="Moves the whole project folder to state/plans/archive/">
              Archive
            </Button>
          </span>
        </div>
      </div>
    </Card>
  )
}

function PlanRow({
  d,
  onOpen,
  action,
  onAction,
  busy,
}: {
  d: PlanItem
  onOpen: () => void
  action: string
  onAction: () => void
  busy: boolean
}) {
  return (
    <li className="pl-row">
      <button type="button" className="pl-row-main" onClick={onOpen}>
        <span className="pl-row-top">
          <span className="pl-row-title">{d.title}</span>
          <StatusPill status={d.status} />
          {d.type !== 'plan' && <Pill tone="neutral">{d.type_label}</Pill>}
          {d.type === 'plan' && !d.sbar && <Pill tone="warning">Not SBAR</Pill>}
        </span>
        {d.summary && <span className="pl-row-sum">{d.summary}</span>}
      </button>
      <span className="pl-row-side">
        <Tickets d={d} />
        <span className="pl-faint">{fmtDay(d.updated)}</span>
        <Button size="sm" variant="ghost" loading={busy} onClick={onAction}>
          {action}
        </Button>
      </span>
    </li>
  )
}

// builds with real PR activity that no tracker names. A build that runs on a borrowed key or
// from a session brief never reached this page (the platform access redesign, 10/19 to 10/20).
// Done trackers whose only open ticket is an intake. Nothing for us to do, they archive on their own
// once person's work ticket off the intake closes, so they sit in a compact strip below the live work.
function AwaitingStrip({
  rows,
  onOpen,
  onArchive,
}: {
  rows: PlanProject[]
  onOpen: (id: string) => void
  onArchive: (p: PlanProject) => void
}) {
  if (!rows.length) return null
  return (
    <Card className="pl-awaiting">
      <h3 className="pl-sec">Done, waiting on a work ticket</h3>
      <p className="pl-faint">
        Built and complete. The work ran against the intake, and each card archives itself once person creates the work ticket off it and the
        nightly close-out closes that ticket.
      </p>
      <ul className="pl-rows">
        {rows.map((p) => {
          const t = p.tracker
          const intakes = Object.entries(t?.ticket_status || {}).filter(([, v]) => v.intake && !v.done)
          return (
            <li key={p.id} className="pl-row">
              <div className="pl-row-main">
                <div className="pl-row-top">
                  <Pill tone="success" dot>
                    Done
                  </Pill>
                  {intakes.map(([k, v]) => (
                    <a key={k} href={v.url} target="_blank" rel="noreferrer" data-tip={`Intake ${k}: ${v.status}`}>
                      {k}
                    </a>
                  ))}
                  <span className="pl-faint">No work ticket yet</span>
                </div>
                <div className="pl-row-title">{p.title}</div>
                {t?.summary && <div className="pl-row-sum">{t.summary}</div>}
              </div>
              <div className="pl-untracked-acts">
                {t && (
                  <Button size="sm" variant="ghost" onClick={() => onOpen(t.id)}>
                    Open tracker
                  </Button>
                )}
                <Button size="sm" variant="ghost" onClick={() => onArchive(p)} data-tip="Archive now instead of waiting">
                  Archive
                </Button>
              </div>
            </li>
          )
        })}
      </ul>
    </Card>
  )
}

function UntrackedStrip({
  u,
  busy,
  onCreate,
  onDismiss,
}: {
  u: PlanUntracked
  busy: string
  onCreate: (r: PlanUntrackedRow) => void
  onDismiss: (r: PlanUntrackedRow) => void
}) {
  if (u.state === 'error') return <p className="pl-note">Untracked work check failed ({u.errors[0] || 'unknown error'}).</p>
  if (!u.rows.length) return null
  return (
    <Card className="pl-untracked">
      <h3 className="pl-sec">Untracked work</h3>
      <p className="pl-faint">
        Ticket keys with {u.min_prs} or more PRs in the last {u.window_days} days that no tracker names.
      </p>
      <ul className="pl-rows">
        {u.rows.map((r) => (
          <li key={r.key} className="pl-row">
            <div className="pl-row-main">
              <div className="pl-row-top">
                <a href={r.url} target="_blank" rel="noreferrer">
                  {r.key}
                </a>
                {r.ticket_status && <Pill tone={r.ticket_done ? 'neutral' : 'info'}>{r.ticket_status}</Pill>}
                <span className="pl-faint">{r.prs.length} PRs</span>
              </div>
              <div className="pl-row-title">{r.ticket_title || r.prs[0]?.title}</div>
              <div className="pl-row-sum">
                {r.prs.slice(0, 6).map((p, i) => (
                  <span key={p.ref}>
                    {i > 0 && ', '}
                    <a href={p.url} target="_blank" rel="noreferrer" data-tip={p.title}>
                      {p.ref.replace(/^\S+ /, '')}
                    </a>
                  </span>
                ))}
                {r.prs.length > 6 && ` and ${r.prs.length - 6} more`}
              </div>
            </div>
            <div className="pl-untracked-acts">
              <Button
                size="sm"
                disabled={busy === r.key}
                onClick={() => onCreate(r)}
                data-tip={`Writes state/plans/projects/${r.slug}/tracker.md`}
              >
                Create tracker
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={busy === r.key}
                onClick={() => onDismiss(r)}
                data-tip="Not a project. Stops listing this key."
              >
                Not a project
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  )
}

export default function Plans() {
  const { data, error, reload } = usePlans()
  const { toast } = useToast()
  const { confirm: ask, dialog } = useConfirm()
  const [params, setParams] = useSearchParams()
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState('')
  const view = (VIEWS as string[]).includes(params.get('view') || '') ? (params.get('view') as View) : 'projects'
  const openId = params.get('d')

  const setParam = (k: string, v: string | null) =>
    setParams(
      (p) => {
        const n = new URLSearchParams(p)
        if (v) n.set(k, v)
        else n.delete(k)
        return n
      },
      { replace: true },
    )
  const open = (id: string | null) => setParam('d', id)

  const all: PlanItem[] = data
    ? [
        ...[...data.projects, ...data.archived.projects].flatMap((p) => (p.tracker ? [p.tracker, ...p.docs] : p.docs)),
        ...data.library,
        ...data.archived.library,
      ]
    : []
  const shown = openId ? all.find((d) => d.id === openId) : undefined

  const needle = q.trim().toLowerCase()
  const hit = (d: PlanItem) =>
    !needle || `${d.title} ${d.summary} ${d.next} ${d.tickets.join(' ')} ${d.name}`.toLowerCase().includes(needle)
  const projHit = (p: PlanProject) =>
    !needle || p.title.toLowerCase().includes(needle) || (p.tracker ? hit(p.tracker) : false) || p.docs.some(hit)
  const allProjects = (data?.projects || []).filter(projHit)
  const projects = allProjects.filter((p) => !p.awaiting_ticket)
  const awaiting = allProjects.filter((p) => p.awaiting_ticket)
  const library = (data?.library || []).filter(hit)
  const archProjects = (data?.archived.projects || []).filter(projHit)
  const archLibrary = (data?.archived.library || []).filter(hit)

  const move = async (target: { id: string; version: string; name: string }, restore: boolean) => {
    const r = restore ? await postPlanRestore(target.id, target.version) : await postPlanArchive(target.id, target.version)
    open(null)
    toast('success', `${restore ? 'Restored' : 'Archived'} ${target.name}`, {
      description: restore ? `Back in state/plans/${r.to}` : 'Moved to state/plans/archive/. Restore brings it back.',
    })
    reload()
  }
  const quick = async (target: { id: string; version: string; name: string }, restore: boolean, confirmFirst = false) => {
    if (confirmFirst) {
      const ok = await ask({
        title: `Archive ${target.name}?`,
        body: 'Moves the whole project folder, tracker and documents, to state/plans/archive/. Nothing is deleted and Restore brings it back.',
        confirmLabel: 'Archive',
      })
      if (!ok) return
    }
    setBusy(target.id)
    try {
      await move(target, restore)
    } catch (e) {
      toast('error', `Could not move ${target.name}`, { description: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusy('')
    }
  }

  const createTracker = async (r: PlanUntrackedRow) => {
    const ok = await ask({
      title: `Create a tracker for ${r.key}?`,
      body: `Writes state/plans/projects/${r.slug}/tracker.md with the ${r.prs.length} PRs found. It starts as a skeleton, so reconcile it against live before relying on it.`,
      confirmLabel: 'Create tracker',
    })
    if (!ok) return
    setBusy(r.key)
    try {
      const res = await postPlanCreate(r.key, r.slug, r.ticket_title || r.key)
      toast('success', `Tracker created for ${r.key}`, { description: `state/plans/${res.path}` })
      reload()
      open(res.path)
    } catch (e) {
      toast('error', `Could not create a tracker for ${r.key}`, { description: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusy('')
    }
  }
  const dismissUntracked = async (r: PlanUntrackedRow) => {
    setBusy(r.key)
    try {
      await postPlanDismiss(r.key)
      toast('success', `${r.key} will not be listed again`, { description: 'Kept in state/plans/.untracked-ignore.json' })
      reload()
    } catch (e) {
      toast('error', `Could not dismiss ${r.key}`, { description: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusy('')
    }
  }

  const counts = data?.counts
  const tabs: SegmentedOption<View>[] = [
    { value: 'projects', label: `Projects${counts ? ` (${counts.projects})` : ''}` },
    { value: 'library', label: `Plan library${counts ? ` (${counts.library})` : ''}` },
    { value: 'archive', label: `Archive${counts ? ` (${counts.archived})` : ''}` },
  ]
  const lede = {
    projects:
      'One tracker per thing we are actively building. The card shows where it stands, the next step and progress on the tracker checklist. The project documents open from the card.',
    library: 'Standalone plans in SBAR form (Situation, Background, Assessment, Recommendation) that are not a build yet.',
    archive: 'Finished or dropped projects and plans. Restore moves one back. Nothing here is deleted.',
  }[view]
  const jiraNote =
    data && (data.jira.state === 'error' || data.jira.state === 'stale')
      ? `Ticket status check failed (${data.jira.errors[0] || 'unknown error'}).`
      : ''

  return (
    <div className="hub">
      <HubHeader
        eyebrow="Knowledge"
        title="Plans"
        subtitle="What we are building and the plans behind it. Messages are not tracked here, they go straight to Teams, Outlook or the chat."
      />
      <div className="hub-body">
        <div className="page">
          <Toolbar label="Plans" onRefresh={reload} updatedAt={data ? new Date(data.generated_utc) : null}>
            <Segmented label="View" options={tabs} value={view} onChange={(v) => setParam('view', v === 'projects' ? null : v)} />
            <Input
              type="search"
              aria-label="Search plans"
              placeholder="Search title, summary, ticket"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </Toolbar>
          <p className="pl-lede" style={{ marginTop: 'var(--space-3)' }}>
            {lede}
          </p>
          {jiraNote && <p className="pl-note">{jiraNote}</p>}
          {error && !data ? (
            <LoadError title="Could not load state/plans" error={error} />
          ) : !data ? (
            <Skeleton variant="lines" count={10} label="Loading plans" />
          ) : view === 'projects' ? (
            <>
              {data.untracked && !needle && (
                <UntrackedStrip u={data.untracked} busy={busy} onCreate={createTracker} onDismiss={dismissUntracked} />
              )}
              {projects.length ? (
                <div className="pl-grid">
                  {projects.map((p) => (
                    <ProjectCard
                      key={p.id}
                      p={p}
                      onOpen={open}
                      onArchive={() => quick({ id: p.id, version: p.version, name: p.title }, false, true)}
                    />
                  ))}
                </div>
              ) : (
                <EmptyState
                  compact
                  icon={needle ? <IconSearch /> : undefined}
                  title={needle ? 'No matching project' : 'No active projects'}
                />
              )}
              <AwaitingStrip
                rows={awaiting}
                onOpen={open}
                onArchive={(p) => quick({ id: p.id, version: p.version, name: p.title }, false, true)}
              />
            </>
          ) : view === 'library' ? (
            <Card>
              {library.length ? (
                <ul className="pl-rows">
                  {library.map((d) => (
                    <PlanRow
                      key={d.id}
                      d={d}
                      onOpen={() => open(d.id)}
                      action="Archive"
                      busy={busy === d.id}
                      onAction={() => quick({ id: d.id, version: d.version, name: d.title }, false)}
                    />
                  ))}
                </ul>
              ) : (
                <EmptyState
                  compact
                  icon={needle ? <IconSearch /> : undefined}
                  title={needle ? 'No matching plan' : 'The plan library is empty'}
                />
              )}
            </Card>
          ) : (
            <Card>
              {!archProjects.length && !archLibrary.length ? (
                <EmptyState compact title={needle ? 'Nothing matching in the archive' : 'The archive is empty'} />
              ) : (
                <>
                  {archProjects.length > 0 && <h3 className="pl-sec">Projects</h3>}
                  <ul className="pl-rows">
                    {archProjects.map((p) => {
                      const head: PlanItem | undefined = p.tracker || p.docs[0]
                      return head ? (
                        <PlanRow
                          key={p.id}
                          d={{ ...head, title: p.title, status: p.status }}
                          onOpen={() => open(head.id)}
                          action="Restore"
                          busy={busy === p.id}
                          onAction={() => quick({ id: p.id, version: p.version, name: p.title }, true)}
                        />
                      ) : null
                    })}
                  </ul>
                  {archLibrary.length > 0 && <h3 className="pl-sec">Plans</h3>}
                  <ul className="pl-rows">
                    {archLibrary.map((d) => (
                      <PlanRow
                        key={d.id}
                        d={d}
                        onOpen={() => open(d.id)}
                        action="Restore"
                        busy={busy === d.id}
                        onAction={() => quick({ id: d.id, version: d.version, name: d.title }, true)}
                      />
                    ))}
                  </ul>
                </>
              )}
            </Card>
          )}
        </div>
      </div>

      <Modal
        open={!!shown}
        onClose={() => open(null)}
        variant="sheet"
        size="lg"
        hue="teal"
        title={shown?.title || ''}
        subtitle={shown?.id}
        cancelLabel="Close"
      >
        {shown && <Reader key={shown.id} d={shown} onOpenRel={(id) => open(id)} onMove={move} />}
      </Modal>
      {dialog}
    </div>
  )
}
