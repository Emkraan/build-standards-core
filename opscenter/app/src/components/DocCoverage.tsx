import type { SegmentedOption, StatusTone, TableColumn } from '@kit'
import { Button, Card, CardHead, EmptyState, Field, Modal, ModalSection, Pill, Segmented, Skeleton, Table, Textarea, Toolbar } from '@kit'
import { useState } from 'react'
import type { DocGap, DocThing } from '../lib/data'
import { hermesSessionUrl, postDocHandle, postDocTackle, useDocCoverage, useTackleSessions } from '../lib/data'
import { LinkButton, LivePill, LoadError } from './StateBlocks'

// Documentation coverage: the registry of everything we run (doc-inventory.json) joined with
// the latest documentation audit (doc-gaps.json), served by /api/doc-coverage. Since 
// (2026-10-12) this is the ONLY home for documentation gaps: they never reach the Action
// Center. Each thing has Tackle (a doc-<id> Hermes session), Snooze (7 days) and Ignore (until
// the audit finds a new gap). The Knowledge nav badge counts the things that need me.
// Kit build: Card with a Toolbar view switch, a sortable kit Table, a kit Modal per thing.

const TONE: Record<string, StatusTone> = { high: 'danger', medium: 'warning', low: 'neutral', none: 'success' }
const RANK: Record<string, number> = { high: 3, medium: 2, low: 1, none: 0 }
const WIKI = 'https://atlassian_host/wiki/spaces/it/pages/'
type View = 'open' | 'handled' | 'all'

const day = (iso?: string) => (iso ? new Date(iso).toLocaleDateString([], { month: 'short', day: 'numeric' }) : '')

function statusText(t: DocThing, live: boolean): string {
  if (!t.on_board) return 'kept off'
  if (live) return 'in Hermes'
  if (t.handled?.act === 'snoozed') return `snoozed to ${day(t.handled.until)}`
  if (t.handled?.act === 'ignored') return 'ignored'
  if (t.open) return 'needs me'
  return '-'
}

function StatusCell({ t, live }: { t: DocThing; live: boolean }) {
  if (!t.on_board) return <span className="dc-faint">kept off</span>
  if (live) return <LivePill>in Hermes</LivePill>
  if (t.handled?.act === 'snoozed') return <span className="dc-soft">snoozed to {day(t.handled.until)}</span>
  if (t.handled?.act === 'ignored') return <span className="dc-faint">ignored</span>
  if (t.open)
    return (
      <Pill tone={TONE[t.priority] || 'warning'} dot>
        needs me
      </Pill>
    )
  return <span className="dc-faint">-</span>
}

function Actions({ t, onChange }: { t: DocThing; onChange: () => void }) {
  const { data: sessions, reload } = useTackleSessions()
  const rec = sessions?.[`doc-${t.id}`] || t.tackle || undefined
  const [ask, setAsk] = useState(false)
  const [ctx, setCtx] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const opening = busy || rec?.state === 'launching' || rec?.state === 'claimed'
  const live = !!rec?.live && !!rec.session_id

  if (!t.on_board) return <p className="dc-note">{t.board_note || 'Kept off my board.'}</p>

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    setErr('')
    try {
      await fn()
      onChange()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }
  const tackle = () =>
    run(async () => {
      await postDocTackle(t.id, ctx.trim())
      setAsk(false)
      setCtx('')
      reload()
    })

  return (
    <div className="dc-actions">
      <div className="dc-btns">
        {t.gaps.length > 0 &&
          (opening ? (
            <Button size="sm" variant="primary" loading>
              Opening in Hermes...
            </Button>
          ) : (
            <Button
              size="sm"
              variant="primary"
              onClick={() => setAsk((a) => !a)}
              data-tip="Stage the missing pages as Knowledge proposals in a Hermes session. Nothing publishes until I approve it here."
            >
              {ask ? 'Cancel' : rec?.session_id ? 'Tackle again' : 'Tackle now'}
            </Button>
          ))}
        {rec?.session_id && !opening && (
          <LinkButton href={hermesSessionUrl(rec.session_id)}>
            {live ? 'Open session' : rec.state === 'resolved' ? 'Open thread (done)' : 'Open thread'}
          </LinkButton>
        )}
        {t.handled ? (
          <Button size="sm" disabled={busy} onClick={() => run(() => postDocHandle(t.id, 'restore'))}>
            Restore
          </Button>
        ) : (
          t.gaps.length > 0 && (
            <>
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => run(() => postDocHandle(t.id, 'snooze'))}>
                Snooze 7 days
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                data-tip="Hidden until the audit finds a new gap for this thing"
                onClick={() => run(() => postDocHandle(t.id, 'ignore'))}
              >
                Ignore
              </Button>
            </>
          )
        )}
      </div>
      {ask && !opening && (
        <div className="dc-ask">
          <Field label="Tackle now: additional context" optional hint="Cmd+Enter starts.">
            <Textarea
              rows={3}
              value={ctx}
              onChange={(e) => setCtx(e.target.value)}
              placeholder="Anything the assistant should know first? (optional, Cmd+Enter starts)"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) tackle()
              }}
              autoFocus
            />
          </Field>
          <div className="dc-btns dc-ask-btns">
            <Button size="sm" variant="ghost" onClick={() => setAsk(false)}>
              Back
            </Button>
            <Button size="sm" variant="primary" onClick={tackle} loading={busy}>
              Start in Hermes
            </Button>
          </div>
        </div>
      )}
      {(err || rec?.state === 'failed') && (
        <p className="dc-err" role="alert">
          {err || rec?.error || 'Could not open Hermes.'}
        </p>
      )}
    </div>
  )
}

// Registry and cron-catalog findings (internal tooling, all low). Collapsed by default, one line
// per finding. "N things ...: a.ps1, b.ps1" texts split into a sentence plus a list of chips.
function Finding({ text }: { text: string }) {
  const m = text.match(/^(.*?):\s+(.+?)\.?$/)
  const items = m ? m[2].split(/,\s+/) : []
  if (!m || items.length < 2) return <>{text.replace(/\.$/, '')}</>
  return (
    <>
      {m[1]}
      <div className="dc-chips">
        {items.map((x) => (
          <code key={x}>{x}</code>
        ))}
      </div>
    </>
  )
}

function Housekeeping({ groups }: { groups: { id: string; name: string; gaps: DocGap[] }[] }) {
  const total = groups.reduce((n, g) => n + g.gaps.length, 0)
  if (!total) return null
  return (
    <details className="dc-house">
      <summary>
        Registry and cron catalog housekeeping <span>{total} low findings, internal tooling only</span>
      </summary>
      {groups.map((g) => (
        <div key={g.id} className="dc-house-group">
          <div className="dc-house-name">
            {g.name} <span>({g.gaps.length})</span>
          </div>
          <ul>
            {g.gaps.map((x) => (
              <li key={x.id}>
                <Finding text={x.text} />
              </li>
            ))}
          </ul>
        </div>
      ))}
    </details>
  )
}

export default function DocCoverage({ bare = false }: { bare?: boolean }) {
  const { data: d, error: err, reload } = useDocCoverage()
  const { data: sessions } = useTackleSessions()
  const [open, setOpen] = useState<string | null>(null)
  const [view, setView] = useState<View | null>(null)

  if (err && !d)
    return (
      <Card>
        <CardHead title="Documentation coverage" />
        <LoadError title="Could not load" error={err} />
      </Card>
    )
  if (!d)
    return (
      <Card>
        <Skeleton variant="table" count={6} columns={6} label="Loading documentation coverage" />
      </Card>
    )

  const isLive = (t: DocThing) => !!(sessions?.[`doc-${t.id}`] || t.tackle)?.live
  const handledCount = d.things.filter((t) => t.handled).length
  const v: View = view ?? (d.open_count > 0 ? 'open' : 'all')
  const rows = d.things
    .filter((t) => (v === 'open' ? t.open : v === 'handled' ? !!t.handled : true))
    .sort(
      (a, b) =>
        Number(b.open) - Number(a.open) ||
        RANK[b.priority] - RANK[a.priority] ||
        b.gaps.length - a.gaps.length ||
        a.name.localeCompare(b.name),
    )
  const sub =
    `Registry of everything we run, checked daily at 05:00 against our documentation standard` +
    (d.audited_utc ? ` \u00b7 last audit ${d.audited_utc.slice(0, 16).replace('T', ' ')}Z` : '') +
    ` \u00b7 gaps: ${d.counts.high || 0} high, ${d.counts.medium || 0} medium, ${d.counts.low || 0} low` +
    ` \u00b7 ${d.open_count} need me`

  const views: SegmentedOption<View>[] = [
    { value: 'open', label: `Needs me (${d.open_count})` },
    { value: 'handled', label: `Snoozed or ignored (${handledCount})` },
    { value: 'all', label: `All (${d.things.length})` },
  ]
  const columns: TableColumn<DocThing>[] = [
    {
      key: 'name',
      header: 'Thing',
      value: (t) => `${t.name} ${t.repo}/${t.path || ''}`,
      render: (t) => (
        <span className="dc-thing">
          <span className="dc-name">{t.name}</span>
          <span className="dc-faint">
            {t.repo}/{t.path || ''} {t.status === 'wip' ? '\u00b7 in development' : ''}
          </span>
        </span>
      ),
    },
    { key: 'tier', header: 'Tier', width: '64px' },
    {
      key: 'owner',
      header: 'Owner (R / A)',
      width: '210px',
      value: (t) => `${t.owner_r || '?'} / ${t.owner_a || '?'} ${t.raci_domain || ''}`,
      render: (t) => (
        <span className="dc-thing">
          <span>
            {t.owner_r || '?'} / {t.owner_a || '?'}
          </span>
          <span className="dc-faint">{t.raci_domain}</span>
        </span>
      ),
    },
    {
      key: 'home',
      header: 'Confluence home',
      width: '260px',
      value: (t) => t.home_title || t.confluence_home || null,
      render: (t) =>
        t.confluence_home ? (
          <a href={WIKI + t.confluence_home} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
            {t.home_title || t.confluence_home}
          </a>
        ) : (
          <Pill tone="danger">none</Pill>
        ),
    },
    {
      key: 'gaps',
      header: 'Gaps',
      width: '120px',
      value: (t) => RANK[t.priority] * 100 + t.gaps.length,
      render: (t) => <Pill tone={TONE[t.priority] || 'neutral'}>{t.gaps.length ? `${t.gaps.length} \u00b7 ${t.priority}` : 'clean'}</Pill>,
    },
    {
      key: 'status',
      header: 'Status',
      width: '150px',
      value: (t) => statusText(t, isLive(t)),
      render: (t) => <StatusCell t={t} live={isLive(t)} />,
    },
  ]
  const shown = open ? d.things.find((t) => t.id === open) : undefined

  return (
    <>
      {!bare && <h2 className="dc-section">Documentation coverage</h2>}
      <Card>
        <CardHead title="Documentation coverage" subtitle={sub} />
        {d.last_error && (
          <div className="dc-banner tone hue-amber" role="status">
            Last audit failed, showing the previous result: {d.last_error}
          </div>
        )}
        {!!d.duplicates?.length && (
          <div className="dc-banner tone hue-amber" role="status">
            {d.duplicates.length === 1 ? '1 duplicate page set' : `${d.duplicates.length} duplicate page sets`} in our Confluence trees.
            Keep the first page of each set and delete the copies.
            <ul>
              {d.duplicates.map((g) => (
                <li key={g.id}>{g.text}</li>
              ))}
            </ul>
          </div>
        )}
        <Toolbar label="Coverage view">
          <Segmented label="Which things" options={views} value={v} onChange={setView} />
        </Toolbar>
        <Table
          className="dc-table"
          caption="Documentation coverage by thing"
          columns={columns}
          rows={rows}
          rowKey={(t) => t.id}
          defaultSort={null}
          onRowActivate={(t) => setOpen(t.id)}
          isRowSelected={(t) => t.id === open}
          empty={
            <EmptyState
              compact
              pose={v === 'open' ? 'celebrate' : undefined}
              title={v === 'open' ? 'No documentation gaps need me right now.' : 'Nothing snoozed or ignored.'}
            />
          }
        />
        <Housekeeping groups={d.internal.filter((i) => i.gaps.length)} />
      </Card>

      <Modal
        open={!!shown}
        onClose={() => setOpen(null)}
        size="lg"
        hue={shown?.open ? 'amber' : 'green'}
        title={shown?.name ?? ''}
        subtitle={
          shown ? (
            <>
              {shown.repo}/{shown.path || ''} &middot; tier {shown.tier} &middot; {shown.owner_r || '?'} / {shown.owner_a || '?'}
            </>
          ) : undefined
        }
        cancelLabel="Close"
      >
        {shown && (
          <>
            <ModalSection title={shown.gaps.length ? `Open gaps (${shown.gaps.length})` : 'Open gaps'}>
              {shown.gaps.length === 0 ? (
                <p className="dc-note">No open gaps.</p>
              ) : (
                <ul className="dc-gaps">
                  {shown.gaps.map((g) => (
                    <li key={g.id}>
                      <Pill tone={TONE[g.severity] || 'neutral'}>{g.severity}</Pill>
                      <span>
                        {g.text}{' '}
                        <span className="dc-faint">
                          {g.rule}
                          {g.first_seen ? ` \u00b7 since ${g.first_seen.slice(0, 10)}` : ''}
                        </span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              <p className="dc-meta">
                Release marker: {shown.release || 'none'}
                {' \u00b7 '}changelog: {shown.changelog_file || 'none'}
                {shown.key ? ` \u00b7 audit key ${shown.key}` : ''}
                {shown.handled ? ` \u00b7 ${shown.handled.act} ${day(shown.handled.at)}` : ''}
              </p>
              {shown.closed.length > 0 && (
                <p className="dc-meta">
                  Recently closed: {shown.closed.map((c) => `${c.text} (${c.closed_utc.slice(0, 10)})`).join(' \u00b7 ')}
                </p>
              )}
              {shown.confluence_home && (
                <LinkButton external href={WIKI + shown.confluence_home}>
                  {shown.home_title || 'Confluence home'}
                </LinkButton>
              )}
            </ModalSection>
            <ModalSection title="Act on it">
              <Actions t={shown} onChange={reload} />
            </ModalSection>
          </>
        )}
      </Modal>
    </>
  )
}
