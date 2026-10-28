import type { SegmentedOption, StatusTone, TableColumn } from '@kit'
import {
  Button,
  Card,
  EmptyState,
  Field,
  IconSearch,
  Input,
  Modal,
  ModalSection,
  Pill,
  Segmented,
  Skeleton,
  Table,
  Textarea,
  Toolbar,
} from '@kit'
import { Fragment, useState } from 'react'
import { Navigate, useParams } from 'react-router-dom'
import { HubHeader } from '../components/HubHeader'
import { LinkButton, LivePill, LoadError } from '../components/StateBlocks'
import type { EngAct, EngItem } from '../lib/data'
import { hermesSessionUrl, postEngDecide, postEngHandle, postEngTackle, useEngBacklog, useTackleSessions } from '../lib/data'
import './EngBacklog.css'

// Debt and improvements: every TD and IMP entry ops_center logs, in one place, so I can decide and
// tackle them as time permits. Source of truth stays the markdown files (technical-debt.md,
// improvement-backlog.md). Approve / Park / Decline / Reopen / Accept risk / Close rewrite that
// entry's Status line in place, Snooze is page-only (7 days), Tackle opens a Hermes session.
// Tackling an improvement that is still a suggestion approves it first.
// Kit build: a Toolbar (kind Segmented, search), a sortable kit Table, and a kit Modal per entry
// with the body and every action (the old inline expanded row).

type ETab = 'decide' | 'todo' | 'parked' | 'snoozed' | 'done'
type Kind = 'all' | 'TD' | 'IMP'
const ETABS: ETab[] = ['decide', 'todo', 'parked', 'snoozed', 'done']
const SEV_TONE: Record<string, StatusTone> = {
  critical: 'danger',
  high: 'danger',
  medium: 'warning',
  low: 'neutral',
}
const SEV_RANK: Record<string, number> = { critical: 4, high: 3, medium: 2, low: 1 }
const OUT_TONE: Record<string, StatusTone> = {
  shipped: 'success',
  resolved: 'success',
  closed: 'success',
  approved: 'info',
  'in-progress': 'info',
  built: 'info',
  suggested: 'warning',
  proposed: 'warning',
  declined: 'neutral',
  withdrawn: 'neutral',
  folded: 'neutral',
  parked: 'neutral',
  deferred: 'neutral',
  accepted: 'neutral',
}

const day = (iso?: string) => (iso ? new Date(iso).toLocaleDateString([], { month: 'short', day: 'numeric' }) : '')

// Entries are short markdown bullet lists. Render "- **Label**: text" as a label line, keep the
// rest as plain paragraphs, and turn **bold** and `code` into markup. No markdown dependency.
function inline(s: string) {
  const parts = s.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
  return parts.map((p, i) => {
    if (p.startsWith('**') && p.endsWith('**')) return <b key={i}>{p.slice(2, -2)}</b>
    if (p.startsWith('`') && p.endsWith('`')) return <code key={i}>{p.slice(1, -1)}</code>
    return <Fragment key={i}>{p}</Fragment>
  })
}
function Body({ text }: { text: string }) {
  const lines = text.split('\n').filter((l) => l.trim())
  return (
    <div className="eb-body">
      {lines.map((l, i) => {
        const m = l.match(/^\s*-\s+(.*)$/)
        return (
          <p key={i} className={m ? 'eb-li' : ''}>
            {inline(m ? m[1] : l)}
          </p>
        )
      })}
    </div>
  )
}

const PLACEHOLDER: Record<string, string> = {
  tackle: 'Anything ops_center should know first? (optional, Cmd+Enter starts)',
  accept: 'Why I accept this risk (required, written into the entry)',
  resolve: 'Why this is closed (required, written into the entry)',
  decline: 'Why not (optional, written into the entry so it is never re-pitched)',
  park: 'When to come back to it (optional)',
}
const ASK_LABEL: Record<string, string> = {
  tackle: 'Start in Hermes',
  accept: 'Accept risk',
  resolve: 'Close',
  decline: 'Decline',
  park: 'Park',
}

function Actions({ it, onChange }: { it: EngItem; onChange: () => void }) {
  const { data: sessions, reload } = useTackleSessions()
  const fp = `eng-${it.uid}`
  const rec = sessions?.[fp]
  const [ask, setAsk] = useState<null | 'tackle' | EngAct>(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const opening = busy || rec?.state === 'launching' || rec?.state === 'claimed'
  const live = !!rec?.live && !!rec?.session_id
  const open = it.bucket === 'decide' || it.bucket === 'todo'

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    setErr('')
    try {
      await fn()
      setAsk(null)
      setText('')
      onChange()
      reload()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }
  const submit = () => {
    if (!ask) return
    if (ask === 'tackle') return run(() => postEngTackle(it.uid, text.trim()))
    if ((ask === 'accept' || ask === 'resolve') && !text.trim()) {
      setErr('Add a reason first. It is written into the entry.')
      return
    }
    return run(() => postEngDecide(it.uid, ask, text.trim()))
  }
  const btn = (act: EngAct, label: string, title: string, needsText = false) => (
    <Button
      size="sm"
      className={ask === act ? 'is-selected' : undefined}
      aria-pressed={needsText ? ask === act : undefined}
      disabled={busy}
      data-tip={title}
      onClick={() => (needsText ? setAsk(ask === act ? null : act) : run(() => postEngDecide(it.uid, act)))}
    >
      {label}
    </Button>
  )

  return (
    <div className="eb-actions">
      <div className="eb-btns">
        {open &&
          (opening ? (
            <Button size="sm" variant="primary" loading>
              Opening in Hermes...
            </Button>
          ) : (
            <Button
              size="sm"
              variant="primary"
              onClick={() => setAsk(ask === 'tackle' ? null : 'tackle')}
              data-tip={
                it.bucket === 'decide' ? 'Approves this improvement and works it in a Hermes session' : 'Work this in a Hermes session'
              }
            >
              {ask === 'tackle'
                ? 'Cancel'
                : rec?.session_id
                  ? 'Tackle again'
                  : it.bucket === 'decide'
                    ? 'Approve and tackle'
                    : 'Tackle now'}
            </Button>
          ))}
        {rec?.session_id && !opening && (
          <LinkButton href={hermesSessionUrl(rec.session_id)}>
            {live ? 'Open session' : rec.state === 'resolved' ? 'Open thread (done)' : 'Open thread'}
          </LinkButton>
        )}
        {it.kind === 'IMP' && it.bucket === 'decide' && btn('approve', 'Approve', 'Approved, build it when there is time')}
        {it.kind === 'IMP' && (it.bucket === 'decide' || it.bucket === 'todo') && (
          <>
            {btn('park', 'Park', 'Not now, keep it', true)}
            {btn('decline', 'Decline', 'No, never re-pitch it', true)}
          </>
        )}
        {it.kind === 'IMP' && it.bucket === 'parked' && (
          <>
            {btn('approve', 'Approve', 'Approved, build it when there is time')}
            {btn('decline', 'Decline', 'No, never re-pitch it', true)}
          </>
        )}
        {it.kind === 'IMP' &&
          (it.bucket === 'parked' || it.bucket === 'done') &&
          btn('reopen', 'Reopen as suggestion', 'Back to Needs decision')}
        {it.kind === 'TD' && it.bucket === 'todo' && (
          <>
            {btn('accept', 'Accept risk', 'I accept this risk as is. Needs a reason.', true)}
            {btn('resolve', 'Close', 'Already fixed or no longer applies. Needs a reason.', true)}
          </>
        )}
        {it.kind === 'TD' && it.bucket === 'parked' && btn('resolve', 'Close', 'Already fixed or no longer applies. Needs a reason.', true)}
        {open &&
          (it.snoozed ? (
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => run(() => postEngHandle(it.uid, 'restore'))}>
              Unsnooze
            </Button>
          ) : (
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => run(() => postEngHandle(it.uid, 'snooze'))}>
              Snooze 7 days
            </Button>
          ))}
      </div>
      {ask && !opening && (
        <div className="eb-ask">
          <Field
            label={ask === 'tackle' ? 'Tackle now: additional context' : `${ASK_LABEL[ask]}: note`}
            optional={!(ask === 'accept' || ask === 'resolve')}
            required={ask === 'accept' || ask === 'resolve'}
            hint="Cmd+Enter submits. Back returns to the actions."
          >
            <Textarea
              rows={3}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={PLACEHOLDER[ask] || ''}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit()
              }}
              autoFocus
            />
          </Field>
          <div className="eb-btns">
            <Button size="sm" variant="ghost" onClick={() => setAsk(null)}>
              Back
            </Button>
            <Button size="sm" variant={ask === 'decline' ? 'danger' : 'primary'} onClick={submit} loading={busy}>
              {ASK_LABEL[ask] || 'Park'}
            </Button>
          </div>
        </div>
      )}
      {(err || rec?.state === 'failed') && (
        <p className="eb-err" role="alert">
          {err || rec?.error || 'Could not open Hermes.'}
        </p>
      )}
    </div>
  )
}

export default function EngBacklog() {
  const { tab: rawTab } = useParams()
  const { data: d, error, reload } = useEngBacklog()
  const { data: sessions } = useTackleSessions()
  const [openUid, setOpenUid] = useState<string | null>(null)
  const [kind, setKind] = useState<Kind>('all')
  const [q, setQ] = useState('')

  if (rawTab && !ETABS.includes(rawTab as ETab)) return <Navigate to="/debt" replace />

  const items = d?.items || []
  const tabOf = (it: EngItem): ETab => (it.snoozed ? 'snoozed' : it.bucket)
  const n = (t: ETab) => items.filter((it) => tabOf(it) === t).length
  const tab: ETab = (rawTab as ETab) || (n('decide') > 0 ? 'decide' : 'todo')
  const rows = items
    .filter((it) => tabOf(it) === tab)
    .filter((it) => kind === 'all' || it.kind === kind)
    .sort((a, b) => (SEV_RANK[b.severity] || 0) - (SEV_RANK[a.severity] || 0) || b.date.localeCompare(a.date) || b.id.localeCompare(a.id))
  const live = (it: EngItem) => !!sessions?.[`eng-${it.uid}`]?.live
  const shownItem = openUid ? items.find((it) => it.uid === openUid) : undefined
  const SUB: Record<ETab, string> = {
    decide: 'Improvements I suggested and you have not decided. Approve, park, decline, or approve and tackle.',
    todo: 'Open technical debt and approved improvements. Tackle when there is time, accept the risk, or close what no longer applies.',
    parked: 'Parked improvements and accepted debt. Kept on record, not on my plate.',
    snoozed: 'Hidden for 7 days, then back in their list.',
    done: 'Resolved debt and shipped, declined or withdrawn improvements.',
  }
  const kinds: SegmentedOption<Kind>[] = [
    { value: 'all', label: 'All' },
    { value: 'TD', label: 'Tech debt' },
    { value: 'IMP', label: 'Improvements' },
  ]
  const columns: TableColumn<EngItem>[] = [
    {
      key: 'id',
      header: 'Id',
      width: '120px',
      value: (it) => it.id,
      render: (it) => (
        <Pill tone={it.kind === 'TD' ? 'danger' : 'info'} dot>
          {it.id}
        </Pill>
      ),
    },
    {
      key: 'title',
      header: 'Item',
      value: (it) => `${it.title} ${it.status} ${it.body}`,
      render: (it) => (
        <span className="eb-item">
          <span className="eb-title">{it.title}</span>
          {live(it) && <LivePill>in Hermes</LivePill>}
        </span>
      ),
    },
    {
      key: 'severity',
      header: kind === 'IMP' ? 'Goal / effort' : kind === 'TD' ? 'Severity / effort' : 'Severity or goal / effort',
      width: '240px',
      value: (it) => (it.kind === 'TD' ? SEV_RANK[it.severity] || 0 : it.goals.join(' ')),
      render: (it) => (
        <span className="eb-sev">
          {it.kind === 'TD' ? (
            it.severity ? (
              <Pill tone={SEV_TONE[it.severity] || 'neutral'}>{it.severity}</Pill>
            ) : (
              <span className="eb-faint">-</span>
            )
          ) : (
            <span className="eb-goal">{it.goals.join(' ') || '-'}</span>
          )}
          {it.effort && <span className="eb-faint">{it.effort.slice(0, 60)}</span>}
        </span>
      ),
    },
    {
      key: 'outcome',
      header: 'Status',
      width: '140px',
      render: (it) => (
        <span className="eb-sev">
          <Pill tone={OUT_TONE[it.outcome] || 'neutral'}>{it.outcome}</Pill>
          {it.snoozed && <span className="eb-faint">until {day(it.snoozed.until)}</span>}
        </span>
      ),
    },
    {
      key: 'date',
      header: 'Date',
      width: '96px',
      value: (it) => it.date || null,
      render: (it) => <span className="eb-date">{it.date ? day(`${it.date}T12:00:00Z`) : '-'}</span>,
    },
  ]

  return (
    <div className="hub">
      <HubHeader
        eyebrow="Operate"
        title="Debt and improvements"
        tabs={[
          { to: '/debt/decide', label: 'Needs decision', n: n('decide') },
          { to: '/debt/todo', label: 'To do', n: n('todo') },
          { to: '/debt/parked', label: 'Parked', n: n('parked') },
          { to: '/debt/snoozed', label: 'Snoozed', n: n('snoozed') },
          { to: '/debt/done', label: 'Done' },
        ]}
      />
      <div className="hub-body">
        <div className="page">
          <p className="eb-lede">
            {SUB[tab]} Source: technical-debt.md and improvement-backlog.md, read live. Decisions are written into the entry itself.
          </p>
          <Card>
            <Toolbar label="Filter entries">
              <Segmented label="Entry kind" options={kinds} value={kind} onChange={setKind} />
              <Input
                type="search"
                className="eb-search"
                aria-label="Search id, title, text"
                placeholder="Search id, title, text"
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />
            </Toolbar>
            {error && !d ? (
              <LoadError title="Could not load the debt and improvement entries" error={error} />
            ) : !d ? (
              <Skeleton variant="table" count={6} columns={5} label="Loading entries" />
            ) : (
              <Table
                className="eb-table"
                caption={`Debt and improvement entries: ${tab}`}
                columns={columns}
                rows={rows}
                rowKey={(it) => it.uid}
                filter={q}
                defaultSort={null}
                onRowActivate={(it) => setOpenUid(it.uid)}
                isRowSelected={(it) => it.uid === openUid}
                empty={<EmptyState compact pose="celebrate" title="Nothing here." />}
                noMatch={<EmptyState compact icon={<IconSearch />} title="No matching entries" body="Try a shorter or different search." />}
              />
            )}
          </Card>
        </div>
      </div>

      <Modal
        open={!!shownItem}
        onClose={() => setOpenUid(null)}
        size="lg"
        hue={shownItem?.kind === 'TD' ? 'red' : 'blue'}
        icon={<span className="eb-m-kind">{shownItem?.kind}</span>}
        title={shownItem ? `${shownItem.id} ${shownItem.title}` : ''}
        subtitle={
          shownItem ? (
            <>
              {shownItem.kind === 'TD' ? 'technical-debt.md' : 'improvement-backlog.md'} line {shownItem.line}
              {shownItem.owner ? ` \u00b7 owner ${shownItem.owner}` : ''}
            </>
          ) : undefined
        }
        cancelLabel="Close"
      >
        {shownItem && (
          <>
            <div className="eb-m-pills">
              <Pill tone={OUT_TONE[shownItem.outcome] || 'neutral'}>{shownItem.outcome}</Pill>
              {shownItem.kind === 'TD' && shownItem.severity && (
                <Pill tone={SEV_TONE[shownItem.severity] || 'neutral'}>{shownItem.severity}</Pill>
              )}
              {shownItem.snoozed && <Pill>snoozed until {day(shownItem.snoozed.until)}</Pill>}
              {live(shownItem) && <LivePill>in Hermes</LivePill>}
            </div>
            <ModalSection title="Entry">
              <Body text={shownItem.body} />
            </ModalSection>
            <ModalSection title="Decide or tackle">
              <Actions it={shownItem} onChange={reload} />
            </ModalSection>
          </>
        )}
      </Modal>
    </div>
  )
}
