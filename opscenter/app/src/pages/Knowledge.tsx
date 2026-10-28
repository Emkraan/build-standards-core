import type { StatusTone, TableColumn } from '@kit'
import { Badge, Button, Card, CardHead, EmptyState, Field, Pill, Skeleton, StatusDot, Table, Textarea } from '@kit'
import { useEffect, useState } from 'react'
import { Navigate, useParams } from 'react-router-dom'
import DocCoverage from '../components/DocCoverage'
import { HubHeader } from '../components/HubHeader'
import { AutoPublishDigest, PublishModeCard } from '../components/PublishMode'
import { LoadError } from '../components/StateBlocks'
import type { AppliedRecord, CurationData, Proposal } from '../lib/data'
import { fetchApi, postApprovals, useDocCoverage, useLocalStore, useVisibleInterval } from '../lib/data'
import './Knowledge.css'

// Knowledge hub on the kit: proposal Cards with a kit CardHead and Buttons, a kit Table for what
// the applier recorded, and kit EmptyState and Skeleton for empty and
// loading states.

const STUCK_MS = 10 * 60 * 1000

const KIND_TONE = (k: string): StatusTone => {
  const s = k.toLowerCase()
  if (s === 'create') return 'success'
  if (s === 'lint-fix') return 'warning'
  if (s === 'move' || s === 'rename' || s === 'merge') return 'info'
  return 'neutral'
}

function DiffView({ diff }: { diff: string }) {
  if (!diff) return <p className="kc-note">New page. Use Preview page to read the full body before approving.</p>
  return (
    <details className="kc-diffwrap">
      <summary>View diff</summary>
      <pre className="kc-diff">
        {diff.split('\n').map((line, i) => {
          const cls =
            line.startsWith('+') && !line.startsWith('+++')
              ? 'add'
              : line.startsWith('-') && !line.startsWith('---')
                ? 'del'
                : line.startsWith('@@')
                  ? 'hunk'
                  : ''
          return (
            <span key={i} className={`kc-line ${cls}`}>
              {`${line}\n`}
            </span>
          )
        })}
      </pre>
    </details>
  )
}

const RESULT_TONE = (r: string): 'success' | 'neutral' | 'warning' =>
  r === 'published' ? 'success' : r === 'rejected' ? 'neutral' : 'warning'

const APPLIED_COLUMNS: TableColumn<AppliedRecord & { i: number }>[] = [
  {
    key: 'title',
    header: 'Proposal',
    value: (a) => a.title || a.fp,
    render: (a) => (
      <span className="kc-applied">
        <StatusDot tone={RESULT_TONE(a.result)} pulse={false} />
        {a.title || a.fp}
      </span>
    ),
  },
  {
    key: 'result',
    header: 'Result',
    width: '140px',
    render: (a) => <Pill tone={RESULT_TONE(a.result)}>{a.result}</Pill>,
  },
  {
    key: 'when',
    header: 'When',
    width: '170px',
    value: (a) => a.when || null,
    render: (a) => <span className="kc-faint">{a.when ? `${a.when.slice(0, 16).replace('T', ' ')}Z` : '-'}</span>,
  },
]

// Knowledge hub: tabs are routes like the rest of the Ops Center. Proposals (landing) is the
// approval queue, Doc coverage is the documentation audit, History is what I already
// decided and what the applier published.
type KTab = 'proposals' | 'coverage' | 'history'
const KTABS: KTab[] = ['proposals', 'coverage', 'history']

function Lede({ children }: { children: React.ReactNode }) {
  return <p className="kc-lede">{children}</p>
}

export default function Knowledge() {
  const { tab: rawTab } = useParams()
  const { data: docs } = useDocCoverage()
  const [cur, setCur] = useState<CurationData | null>(null)
  const [applied, setApplied] = useState<AppliedRecord[]>([])
  const [error, setError] = useState<string | null>(null)
  // Local record of what was sent this session, so the UI reflects the decision
  // immediately. The durable outcome comes back via /api/applied once the cron
  // runs. Keyed by fp -> {act, queued}.
  const [sent, setSent] = useLocalStore<Record<string, { act: string; at: string }>>('kc-sent-v1', {})
  const [flash, setFlash] = useState<{ text: string; bad: boolean } | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  // A decision the applier has not recorded within STUCK_MS is treated as lost and the card
  // comes back, so a dropped queue entry can never hide a proposal for good.
  const [now, setNow] = useState(() => Date.now())
  // Reject opens a reason box. "changes" = send back for rewrite (proposal stays staged),
  // "rejected" = drop it for good. Either way the reason is recorded.
  const [rejecting, setRejecting] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const load = () => {
    fetchApi<CurationData>('api/curation')
      .then(setCur)
      .catch((e) => setError(String(e)))
    fetchApi<{ applied: AppliedRecord[] }>('api/applied')
      .then((d) => setApplied(d.applied || []))
      .catch(() => {})
  }

  useEffect(load, [])
  // While a send-back is being rewritten, poll so the card flips to "Rewritten" on its own.
  const rewriting = (cur?.proposals || []).some((p) => p.feedback?.pending && p.feedback.status !== 'blocked')
  useVisibleInterval(load, rewriting ? 15000 : null)

  // Only proposals still staged count, so old local decisions do not keep the poll alive.
  const waiting = (cur?.proposals || []).some((p) => sent[p.fp] && !applied.some((a) => a.fp === p.fp))
  useVisibleInterval(
    () => {
      setNow(Date.now())
      load()
    },
    waiting ? 60000 : null,
  )

  const decide = async (p: Proposal, act: 'approved' | 'rejected' | 'changes', why?: string) => {
    setBusy(p.fp)
    setFlash(null)
    try {
      const r = await postApprovals([{ fp: p.fp, act, body_sha: p.body_sha, title: p.target_title, reason: why }])
      if (act !== 'changes') setSent((prev) => ({ ...prev, [p.fp]: { act, at: new Date().toISOString() } }))
      setRejecting(null)
      setReason('')
      setFlash({
        bad: false,
        text:
          act === 'approved'
            ? `Approved. Applying within ~1 min (guarded write + read-back verify). Queued ${r.queued}.`
            : act === 'changes'
              ? `Sent back with your note. The rewrite starts within a minute and the new version comes back here for approval.`
              : `Rejected with your reason recorded. Nothing publishes.`,
      })
      // refresh applied outcomes shortly after, in case the cron already ran
      setTimeout(load, act === 'changes' ? 500 : 4000)
    } catch (e) {
      setFlash({ bad: true, text: `Could not reach the approval backend: ${String(e)}. Is the Ops Center server running?` })
    } finally {
      setBusy(null)
    }
  }

  const undo = (fp: string) =>
    setSent((prev) => {
      const next = { ...prev }
      delete next[fp]
      return next
    })

  if (rawTab && !KTABS.includes(rawTab as KTab)) return <Navigate to="/knowledge" replace />

  const props = cur?.proposals || []
  const appliedFps = new Set(applied.map((a) => a.fp))
  const isStuck = (fp: string) => !!sent[fp] && !appliedFps.has(fp) && now - Date.parse(sent[fp].at) > STUCK_MS
  const pending = props.filter((p) => !appliedFps.has(p.fp) && (!sent[p.fp] || isStuck(p.fp)))
  const decided = props.filter((p) => appliedFps.has(p.fp) || (sent[p.fp] && !isStuck(p.fp)))

  // Land on whatever needs me: pending proposals first, then open documentation gaps.
  if (cur && !rawTab && pending.length === 0 && (docs?.open_count || 0) > 0) return <Navigate to="/knowledge/coverage" replace />
  const tab: KTab = (rawTab as KTab) || 'proposals'

  const modeNote =
    cur?.mode === 'staged'
      ? 'staged \u00b7 Confluence is read-only; nothing publishes until I approve'
      : 'AUTONOMOUS \u00b7 approved-scope changes apply automatically; these are for review'

  const flashBox = flash && (
    <div className={`kc-flash tone ${flash.bad ? 'hue-red' : 'hue-blue'}`} role="status">
      {flash.text}
    </div>
  )

  const renderProposal = (p: Proposal, isDecided: boolean) => {
    const rec = applied.find((a) => a.fp === p.fp)
    const localAct = sent[p.fp]?.act
    const stuck = !rec && isStuck(p.fp)
    const status = rec
      ? rec.result
      : stuck
        ? 'stuck'
        : localAct === 'approved'
          ? 'approved (queued)'
          : localAct === 'rejected'
            ? 'rejected'
            : ''
    const isApplied = !!rec
    const url = p.target_id ? `https://atlassian_host/wiki/spaces/it/pages/${p.target_id}` : null
    const publishedUrl =
      rec && rec.result === 'published' && rec.page_id ? `https://atlassian_host/wiki/spaces/it/pages/${rec.page_id}` : null
    const statusTone: StatusTone = stuck ? 'warning' : status === 'published' ? 'success' : status === 'rejected' ? 'neutral' : 'accent'
    return (
      <Card key={p.fp} as="article" tone={stuck ? 'amber' : undefined} className={isDecided ? 'kc-prop is-decided' : 'kc-prop'}>
        <CardHead
          level={3}
          title={p.target_title}
          subtitle={p.domain || undefined}
          controls={
            <>
              <Pill tone={KIND_TONE(p.kind)} dot>
                {p.kind}
              </Pill>
              {status && <Badge tone={statusTone}>{status}</Badge>}
            </>
          }
        />
        <p className="kc-summary">{p.summary}</p>
        <div className="kc-meta">
          <Badge tone={p.scope_verdict === 'ALLOW' ? 'success' : 'danger'} className="kc-mono">
            scope: {p.scope_verdict || '?'}
          </Badge>
          {url && (
            <a href={url} target="_blank" rel="noreferrer">
              {String(p.target_id)}
            </a>
          )}
          {p.body_format && <span className="kc-faint">{p.body_format}</span>}
          {!publishedUrl && (
            <a href={`api/curation/preview/${p.fp}`} target="_blank" rel="noreferrer" className="kc-strong">
              Preview page
            </a>
          )}
        </div>
        <DiffView diff={p.diff} />
        {stuck && (
          <div className="kc-flash tone hue-amber">
            <b>Stuck:</b> I {localAct} this at {sent[p.fp].at.slice(11, 16)}Z and the applier has no record of it after{' '}
            {Math.round(STUCK_MS / 60000)} minutes. Nothing was published. Decide again to re-queue it.
          </div>
        )}
        {p.feedback && (
          <div className={`kc-flash tone ${p.feedback.pending && p.feedback.status === 'blocked' ? 'hue-red' : 'hue-violet'}`}>
            {p.feedback.pending && p.feedback.status === 'blocked' ? (
              <>
                <b>Could not rewrite after your note:</b> {p.feedback.reason}
                {p.feedback.response ? ` \u00b7 Why: ${p.feedback.response}` : ''}
              </>
            ) : p.feedback.pending ? (
              <>
                <b>
                  {p.feedback.status === 'rewriting' ? 'Rewriting now' : 'Sent back, rewrite starting'} ({p.feedback.at.slice(11, 16)}Z):
                </b>{' '}
                {p.feedback.reason}
              </>
            ) : (
              <>
                <b>Rewritten{p.restaged_utc ? ` ${p.restaged_utc.slice(0, 16).replace('T', ' ')}Z` : ''} after your note:</b>{' '}
                {p.feedback.reason}
                {p.feedback.response ? ` \u00b7 What changed: ${p.feedback.response}` : ''}
              </>
            )}
          </div>
        )}
        {publishedUrl && (
          <div className="kc-meta">
            <Badge tone="success" dot>
              published
            </Badge>
            <a href={publishedUrl} target="_blank" rel="noreferrer">
              {String(rec?.page_id)}
            </a>
          </div>
        )}
        <div className="kc-btns">
          {isDecided ? (
            <Button size="sm" disabled={isApplied} onClick={() => undo(p.fp)}>
              {isApplied ? 'Applied' : 'Undo'}
            </Button>
          ) : rejecting === p.fp ? (
            <div className="kc-reject">
              <Field label="What is wrong or missing?" required hint="This note drives the rewrite, or is recorded if I reject for good.">
                <Textarea
                  autoFocus
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="What is wrong or missing? This note drives the rewrite."
                  rows={4}
                />
              </Field>
              <div className="kc-btns">
                <Button
                  size="sm"
                  variant="primary"
                  loading={busy === p.fp}
                  disabled={!reason.trim()}
                  onClick={() => decide(p, 'changes', reason.trim())}
                >
                  Send back for rewrite
                </Button>
                <Button
                  size="sm"
                  variant="danger"
                  disabled={busy === p.fp || !reason.trim()}
                  onClick={() => decide(p, 'rejected', reason.trim())}
                >
                  Reject for good
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setRejecting(null)
                    setReason('')
                  }}
                >
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            <>
              <Button size="sm" variant="primary" loading={busy === p.fp} onClick={() => decide(p, 'approved')}>
                {busy === p.fp ? 'Sending...' : 'Approve'}
              </Button>
              <Button
                size="sm"
                disabled={busy === p.fp}
                onClick={() => {
                  setRejecting(p.fp)
                  setReason('')
                }}
              >
                Reject...
              </Button>
            </>
          )}
        </div>
      </Card>
    )
  }

  const historyN = decided.length + applied.length

  const loadingBlock = (
    <div className="kc-stack">
      <Skeleton variant="card" label="Loading curation" />
      <Skeleton variant="card" />
    </div>
  )

  const proposalsTab = (
    <div className="page">
      <Lede>
        Staged Confluence changes waiting on my approval &middot; {modeNote}
        {cur?.generated_utc ? ` \u00b7 generated ${cur.generated_utc.slice(0, 16).replace('T', ' ')}Z` : ''}
      </Lede>
      {flashBox}
      <PublishModeCard />
      {error ? (
        <Card>
          <LoadError title="Could not load curation" error={error} />
        </Card>
      ) : !cur ? (
        loadingBlock
      ) : pending.length === 0 ? (
        <Card>
          <EmptyState
            pose="celebrate"
            title="Nothing waiting on me."
            body="The nightly knowledge job and Tackle sessions stage Confluence changes here for my approval. Confluence stays read-only until I approve."
          />
        </Card>
      ) : (
        <div className="kc-stack">{pending.map((p) => renderProposal(p, false))}</div>
      )}
    </div>
  )

  const coverageTab = (
    <div className="page">
      <Lede>Gaps against our documentation standard for everything we run. They live here, never on the Action Center.</Lede>
      <DocCoverage bare />
    </div>
  )

  const historyTab = (
    <div className="page">
      <Lede>Proposals I decided and what the applier published or dropped.</Lede>
      {flashBox}
      <AutoPublishDigest />
      {error ? (
        <Card>
          <LoadError title="Could not load curation" error={error} />
        </Card>
      ) : !cur ? (
        loadingBlock
      ) : (
        <>
          {historyN === 0 && (
            <Card>
              <EmptyState title="No decisions yet." />
            </Card>
          )}
          {applied.length > 0 && (
            <>
              <h2 className="kc-section">Recently applied</h2>
              <Table
                className="kc-table"
                caption="Recently applied proposals"
                columns={APPLIED_COLUMNS}
                rows={applied.slice(0, 12).map((a, i) => ({ ...a, i }))}
                rowKey={(a) => a.fp + a.i}
                defaultSort={null}
              />
            </>
          )}
          {decided.length > 0 && (
            <>
              <h2 className="kc-section">Decided</h2>
              <div className="kc-stack">{decided.map((p) => renderProposal(p, true))}</div>
            </>
          )}
        </>
      )}
    </div>
  )

  return (
    <div className="hub">
      <HubHeader
        eyebrow="Knowledge"
        title="Knowledge"
        tabs={[
          { to: '/knowledge', label: 'Proposals', n: cur ? pending.length : undefined, end: true },
          { to: '/knowledge/coverage', label: 'Doc coverage', n: docs?.open_count },
          { to: '/knowledge/history', label: 'History' },
        ]}
      />
      <div className="hub-body">{tab === 'coverage' ? coverageTab : tab === 'history' ? historyTab : proposalsTab}</div>
    </div>
  )
}
