import type { TableColumn } from '@kit'
import { Button, Card, CardHead, EmptyState, Input, Table, useConfirm } from '@kit'
import { useState } from 'react'
import type { TfDecision, TfReviewItem } from '../lib/data'
import { postTfDecision, relTime, useNow, useTfReviews } from '../lib/data'
import { age, PrRef, Reasons, ResultNote, ReviewItem, recTone, riskTone, Tag, TextToggle } from '../pages/reviews/parts'
import { prUrl } from '../lib/config'
import { confirmText } from './confirmText'

// Private platform-tfplan-gate queue: PR Terraform plans held for my review
// because they change how the pipeline works. Approve/Reject decides the
// pending terraform-plan deployments on GitHub via server.py.

function Item({ it, now }: { it: TfReviewItem; now: number }) {
  const { reload, mutate } = useTfReviews()
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [showFiles, setShowFiles] = useState(false)
  const { confirm: ask, dialog } = useConfirm()
  const waited = age(it.first_seen, now)
  const a = it.assessment

  const act = async (kind: 'approve' | 'reject') => {
    if (it.pr === null) return
    const verb = kind === 'approve' ? 'APPROVE' : 'REJECT (changes requested)'
    const ok = await ask({
      ...confirmText(`${verb} the terraform-plan deployments for PR #${it.pr} at ${it.head_sha.slice(0, 8)}?`),
      confirmLabel: kind === 'approve' ? 'Approve' : 'Reject',
      danger: kind === 'reject',
    })
    if (!ok) return
    setBusy(true)
    setMsg(null)
    try {
      const r = await postTfDecision(it.pr, kind)
      setMsg({ ok: true, text: `${r.status} ${r.runs.length} run(s)` })
      mutate((d) => ({ ...d, pending: d.pending.filter((p) => p.key !== it.key) }))
      setTimeout(reload, 1500)
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <ReviewItem
      state="needs_you"
      top={
        <>
          <PrRef href={it.url}>{it.pr !== null ? `#${it.pr}` : 'run'}</PrRef>
          {a ? <Tag tone={riskTone(a.risk.level)}>{a.risk.level} risk</Tag> : <Tag tone="neutral">assessing</Tag>}
          {a && <Tag tone={recTone(a.recommendation.action)}>recommend {a.recommendation.action}</Tag>}
          <Tag tone={waited.old ? 'alert' : 'neutral'}>waiting {waited.text}</Tag>
        </>
      }
      title={it.title}
      meta={
        <>
          {it.author} &middot; {it.head_sha.slice(0, 8)} &middot; {it.run_ids.length} run(s) &middot;{' '}
          <TextToggle onClick={() => setShowFiles((s) => !s)} expanded={showFiles}>
            {it.files.length} file(s)
          </TextToggle>
        </>
      }
      actions={
        it.pr !== null ? (
          <>
            <Button size="sm" variant="primary" loading={busy} onClick={() => act('approve')}>
              {busy ? 'Working...' : 'Approve'}
            </Button>
            <Button size="sm" variant="danger" disabled={busy} onClick={() => act('reject')}>
              Reject
            </Button>
          </>
        ) : undefined
      }
    >
      {dialog}
      <Reasons items={it.held_reasons} />
      {showFiles && (
        <ul className="rh-files">
          {it.files.map((f) => (
            <li key={f}>
              <code>{f}</code>
            </li>
          ))}
        </ul>
      )}
      {a && (
        <div className="rh-inset">
          <p>{a.summary}</p>
          <ul>
            {a.changes.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
          <p>
            <b>Risk:</b> {a.risk.why}
          </p>
          <p>
            <b>Recommendation:</b> {a.recommendation.action} - {a.recommendation.why}
          </p>
          <p className="rh-line">assessed {relTime(a.checked_at)}</p>
        </div>
      )}
      <ResultNote msg={msg} />
    </ReviewItem>
  )
}


// The plan gate's decision log, newest first. Sortable and filterable like every data table.
const AUTO_COLS: TableColumn<TfDecision>[] = [
  {
    key: 'ts',
    header: 'When (UTC)',
    value: (d) => d.ts,
    render: (d) => <span className="rh-mono">{d.ts.slice(0, 16).replace('T', ' ')}Z</span>,
    width: '170px',
  },
  {
    key: 'pr',
    header: 'PR',
    value: (d) => d.pr,
    render: (d) => <PrRef href={prUrl(d.pr)}>#{d.pr}</PrRef>,
    width: '90px',
  },
  { key: 'workflow', header: 'Workflow', value: (d) => d.workflow.split('/').pop() },
  {
    key: 'files',
    header: 'Files',
    numeric: true,
    value: (d) => d.files_changed,
    render: (d) => `${d.files_changed} file(s)`,
    width: '110px',
  },
]

// mode 'full' = the original card (pending holds + auto-approvals).
// mode 'auto' = only the recent auto-approvals list: on the platform reviews
// page the pending holds render in the unified Needs me list instead.
export default function TfReviews({ mode = 'full' }: { mode?: 'full' | 'auto' }) {
  const { data } = useTfReviews()
  const now = useNow(60_000)
  const [showAuto, setShowAuto] = useState(false)
  const [q, setQ] = useState('')
  const pending = data?.pending || []
  const auto = (data?.decisions || []).filter((d) => d.decision === 'approved')
  const filter = (
    <Input
      className="rh-filter"
      type="search"
      value={q}
      onChange={(e) => setQ(e.target.value)}
      placeholder="Filter"
      aria-label="Filter auto-approvals"
    />
  )
  const table = (
    <Table
      caption="Recent terraform-plan auto-approvals"
      columns={AUTO_COLS}
      rows={auto}
      rowKey={(d) => `${d.run}-${d.ts}`}
      filter={q}
      defaultSort={{ key: 'ts', dir: 'desc' }}
      maxHeight="440px"
      empty={<EmptyState compact title="No recent auto-approvals." />}
      noMatch={<EmptyState compact title="No matching auto-approvals" />}
    />
  )
  if (mode === 'auto') {
    return (
      <Card as="section">
        <CardHead
          title="Terraform plan auto-approvals"
          subtitle={`${auto.length} recent \u00b7 platform terraform-plan gate`}
          controls={auto.length > 0 ? filter : undefined}
        />
        {table}
      </Card>
    )
  }
  if (!pending.length) return null
  return (
    <Card as="section">
      <CardHead
        title="Terraform plan reviews"
        subtitle={`${pending.length} held for me \u00b7 platform terraform-plan`}
        controls={
          auto.length > 0 ? (
            <>
              {showAuto && filter}
              <Button size="sm" variant="ghost" aria-expanded={showAuto} onClick={() => setShowAuto((s) => !s)}>
                {showAuto ? 'Hide' : 'Show'} recent auto-approvals ({auto.length})
              </Button>
            </>
          ) : undefined
        }
      />
      <div className="rh-list">
        {pending.map((it) => (
          <Item key={it.key} it={it} now={now} />
        ))}
      </div>
      {showAuto && <div className="rh-after">{table}</div>}
    </Card>
  )
}
