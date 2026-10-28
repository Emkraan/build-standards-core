// Core consumption (/core, build-standards-core local-ops-app.md section 19). Renders the nightly
// consumption.json the server reads (no gh call on the render path): per consumer the class, way,
// pin against latest, the sync pull request and its CI, status counts or why they were not
// collected, the UI verdict and adoption suggestions with risk, then my report items and the
// peers' shipped suggestions. Approvals are one click and one confirmation naming the target, and
// the server runs only gh pr ready, gh pr merge (when checks pass) or gh issue comment.
import type { StatusTone } from '@kit'
import { Button, Card, CardHead, EmptyState, Pill, Table, useConfirm, useToast } from '@kit'
import type { ReactNode } from 'react'
import { useState } from 'react'
import { HubHeader } from '../components/HubHeader'
import { LinkButton, LoadError } from '../components/StateBlocks'
import type { CoreCi, CoreConsumption, CoreItem, CoreRow } from '../lib/data'
import { postCoreItem, postCorePr, relTime, useCoreConsumption } from '../lib/data'
import './CoreConsumption.css'

const CI_TONE: Record<CoreCi, StatusTone> = { pass: 'success', fail: 'danger', pending: 'warning', none: 'neutral' }
const RISK_TONE: Record<string, StatusTone> = { none: 'success', low: 'success', medium: 'warning', high: 'danger' }
const ITEM_TONE: Record<string, StatusTone> = {
  approved: 'success',
  shipped: 'info',
  held: 'warning',
  rejected: 'danger',
  'awaiting decision': 'warning',
}

function Pin({ r }: { r: CoreRow }) {
  if (!r.pinned) return <span className="cc-muted">unknown</span>
  const behind = r.behind
  return (
    <span className="cc-pin">
      <span className="cc-mono">{r.pinned}</span>
      <span className="cc-muted">
        {' '}
        of <span className="cc-mono">{r.latest ?? '?'}</span>
      </span>
      {behind != null && <Pill tone={behind === 0 ? 'success' : 'warning'}>{behind === 0 ? 'current' : `${behind} behind`}</Pill>}
    </span>
  )
}

function SyncCell({ r }: { r: CoreRow }) {
  if (!r.sync_applies) return <span className="cc-muted">none (takes every release at once)</span>
  const pr = r.sync_pr
  if (!pr) return <span className="cc-muted">none open</span>
  return (
    <span className="cc-sync">
      <a href={pr.url} target="_blank" rel="noreferrer">
        #{pr.number}
      </a>
      <Pill tone={CI_TONE[pr.ci] ?? 'neutral'} dot>
        CI {pr.ci}
      </Pill>
      {pr.created_at && <span className="cc-muted">opened {relTime(pr.created_at)}</span>}
    </span>
  )
}

function StatusCell({ r }: { r: CoreRow }) {
  const s = r.status
  return (
    <div className="cc-stack">
      {s ? (
        <span className="cc-counts">
          <Pill tone="success">{s.pass} pass</Pill>
          <Pill tone="info">{s.proved} proved</Pill>
          <Pill tone={s.fail > 0 ? 'danger' : 'neutral'}>{s.fail} fail</Pill>
          <Pill tone="neutral">{s.unverified} unverified</Pill>
        </span>
      ) : null}
      {r.ui_verdict ? <span className="cc-muted">UI: {r.ui_verdict}</span> : null}
      {r.not_collected.map((n) => (
        <span key={n} className="cc-muted">
          Not collected: {n}
        </span>
      ))}
    </div>
  )
}

function ApproveCell({ r, onDone }: { r: CoreRow; onDone: () => void }) {
  const { confirm: ask, dialog } = useConfirm()
  const { toast } = useToast()
  const [busy, setBusy] = useState(false)
  const a = r.approval
  const pr = r.sync_pr
  // The ops center row, and a repo with no sync PR, carry no approval control at all.
  if (a.kind === 'none' || !pr) return <span className="cc-muted">{a.kind === 'none' ? '' : a.reason}</span>
  if (a.kind === 'done') return <Pill tone="success">Approved</Pill>
  const run = async () => {
    const target = a.target || `${r.repo}#${pr.number}`
    const ok = await ask({
      title: `Approve ${target}?`,
      body: (
        <span className="confirm-body">
          I mark it ready if it is a draft, or merge it with the repo's declared method. It only goes through when its checks pass right
          now. Nothing is pushed to the default branch.
        </span>
      ),
      confirmLabel: 'Approve',
    })
    if (!ok) return
    setBusy(true)
    try {
      const res = await postCorePr(r.repo, pr.number, target)
      toast('success', res.done.join('. '))
      onDone()
    } catch (e) {
      toast('error', e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      <Button
        size="sm"
        variant="primary"
        loading={busy}
        disabled={a.kind !== 'enabled'}
        onClick={run}
        data-tip={a.kind === 'disabled' ? a.reason : `Approve ${a.target}`}
      >
        Approve
      </Button>
      {a.kind === 'disabled' && <span className="cc-muted cc-reason">{a.reason}</span>}
      {dialog}
    </>
  )
}

function Consumers({ d, onDone }: { d: CoreConsumption; onDone: () => void }) {
  return (
    <Card>
      <CardHead title="Consumers" subtitle="One row per app registered on this machine" />
      <Table
        caption="Core consumers"
        sortable={false}
        columns={[
          {
            key: 'consumer',
            header: 'Consumer',
            render: (r: CoreRow) => (
              <div className="cc-stack">
                <strong>{r.label}</strong>
                <span className="cc-muted cc-mono">{r.repo}</span>
                <span className="cc-muted">
                  {r.mode} &middot; {r.class}
                  {r.report_only ? ' \u00b7 report only' : ''}
                </span>
              </div>
            ),
          },
          { key: 'pin', header: 'Pinned and latest', render: (r: CoreRow) => <Pin r={r} /> },
          { key: 'sync', header: 'Sync pull request', render: (r: CoreRow) => <SyncCell r={r} /> },
          { key: 'status', header: 'Status and UI', render: (r: CoreRow) => <StatusCell r={r} /> },
          {
            key: 'approve',
            header: 'Approval',
            hideHeader: false,
            render: (r: CoreRow) => <ApproveCell r={r} onDone={onDone} />,
          },
        ]}
        rows={d.consumers}
        rowKey={(r) => r.repo}
        empty={<EmptyState compact title="No consumers registered" body="The core nightly lists them in consumption.json." />}
      />
    </Card>
  )
}

function Adoption({ d }: { d: CoreConsumption }) {
  const rows = d.consumers.flatMap((c) => c.adoption.map((a) => ({ ...a, consumer: c.label })))
  return (
    <Card>
      <CardHead title="Adoption suggestions" subtitle="Local parts that a kit part now covers" />
      <Table
        caption="Adoption suggestions"
        sortable={false}
        columns={[
          { key: 'consumer', header: 'Consumer' },
          {
            key: 'part',
            header: 'Local part',
            render: (a) => (
              <div className="cc-stack">
                <strong>{a.part}</strong>
                <span className="cc-muted cc-mono">{a.file}</span>
              </div>
            ),
          },
          { key: 'kit_part', header: 'Kit part' },
          { key: 'relation', header: 'Relation' },
          {
            key: 'risk',
            header: 'Risk',
            render: (a) =>
              a.risk ? <Pill tone={RISK_TONE[a.risk] ?? 'neutral'}>{a.risk}</Pill> : <span className="cc-muted">not rated</span>,
          },
        ]}
        rows={rows}
        rowKey={(a) => `${a.consumer}:${a.file}:${a.part}`}
        empty={<EmptyState compact title="No adoption suggestions" />}
      />
    </Card>
  )
}

function AwaitingRow({ item, issue, onDone }: { item: CoreItem; issue: number; onDone: () => void }) {
  const { confirm: ask, dialog } = useConfirm()
  const { toast } = useToast()
  const [busy, setBusy] = useState(false)
  const run = async () => {
    const target = `${item.id} on issue #${issue}`
    const ok = await ask({
      title: `Approve ${target}?`,
      body: <span className="confirm-body">I post "approve {item.id}" as my decision on that issue. Nothing else changes.</span>,
      confirmLabel: 'Approve',
    })
    if (!ok) return
    setBusy(true)
    try {
      const res = await postCoreItem(issue, item.id, target)
      toast('success', res.done.join('. '))
      onDone()
    } catch (e) {
      toast('error', e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <li className="cc-item">
      <span className="cc-mono">{item.id}</span>
      <span className="cc-grow">{item.title}</span>
      {item.done ? (
        <Pill tone="success">Approved</Pill>
      ) : (
        <Button size="sm" variant="primary" loading={busy} disabled={!item.can_approve} onClick={run}>
          Approve
        </Button>
      )}
      {dialog}
    </li>
  )
}

function Account({ d, onDone }: { d: CoreConsumption; onDone: () => void }) {
  const a = d.account
  if (!a) return null
  return (
    <Card>
      <CardHead
        title="My report"
        subtitle="Items this account contributed to the core"
        controls={
          a.report_issue ? (
            <LinkButton href={a.report_issue} external>
              Open report issue
            </LinkButton>
          ) : undefined
        }
      />
      <h3 className="cc-sub">Awaiting my decision</h3>
      {a.awaiting_decision.length === 0 ? (
        <EmptyState compact title="Nothing is waiting on my decision" />
      ) : (
        <ul className="cc-list">
          {a.awaiting_decision.map((i) => (
            <AwaitingRow key={`${i.issue}:${i.id}`} item={i} issue={i.issue} onDone={onDone} />
          ))}
        </ul>
      )}
      <h3 className="cc-sub">Approved, no core pull request open yet</h3>
      {a.approved_unopened.length === 0 ? (
        <EmptyState compact title="Every approved item has a pull request" />
      ) : (
        <ul className="cc-list">
          {a.approved_unopened.map((i) => (
            <li key={`${i.issue}:${i.id}`} className="cc-item">
              <span className="cc-mono">{i.id}</span>
              <span className="cc-grow">{i.title}</span>
              <span className="cc-muted">issue #{i.issue}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function Peers({ d }: { d: CoreConsumption }) {
  const p = d.peers
  if (!p) return null
  return (
    <Card>
      <CardHead title="Peers" subtitle="Open consumer reports and what shipped in the kit" />
      <h3 className="cc-sub">
        Suggestions this machine could adopt
        {p.new_count > 0 && <Pill tone="accent">{p.new_count} new</Pill>}
      </h3>
      {p.suggestions.length === 0 ? (
        <EmptyState compact title="No shipped suggestions from other accounts" />
      ) : (
        <ul className="cc-list">
          {p.suggestions.map((s) => (
            <li key={`${s.issue}:${s.id}`} className="cc-item">
              <span className="cc-mono">{s.id}</span>
              <span className="cc-grow">{s.title}</span>
              <span className="cc-muted">
                {s.author} &middot; shipped in {s.shipped_in}
              </span>
              {s.new && <Pill tone="accent">New</Pill>}
            </li>
          ))}
        </ul>
      )}
      <h3 className="cc-sub">Open consumer reports</h3>
      {p.issues.length === 0 ? (
        <EmptyState compact title="No open consumer reports" />
      ) : (
        p.issues.map((iss) => (
          <div key={iss.number} className="cc-issue">
            <div className="cc-issue-head">
              <a href={iss.url} target="_blank" rel="noreferrer">
                #{iss.number}
              </a>
              <span className="cc-muted">{iss.mine ? 'mine' : iss.author}</span>
            </div>
            <ul className="cc-list">
              {iss.items.map((i) => (
                <li key={i.id} className="cc-item">
                  <span className="cc-mono">{i.id}</span>
                  <span className="cc-grow">{i.title}</span>
                  <Pill tone={ITEM_TONE[i.status] ?? 'neutral'}>
                    {i.status}
                    {i.shipped_in ? ` ${i.shipped_in}` : ''}
                  </Pill>
                </li>
              ))}
            </ul>
          </div>
        ))
      )}
    </Card>
  )
}

export default function CoreConsumptionPage() {
  const { data, error, loading, refresh } = useCoreConsumption()
  let body: ReactNode
  if (!data) {
    body = error ? <LoadError title="Could not load the core consumption feed" error={error} /> : <p className="cc-muted">Loading...</p>
  } else if (data.state === 'error') {
    // A wrong format, a missing or a broken file is an error state, never stale rows.
    body = (
      <LoadError
        title="The core consumption feed cannot be shown"
        error={data.message}
        hint="Nothing is rendered until consumption.json is valid."
      />
    )
  } else {
    body = (
      <div className="cc-page">
        <Consumers d={data} onDone={refresh} />
        <Adoption d={data} />
        <Account d={data} onDone={refresh} />
        <Peers d={data} />
      </div>
    )
  }
  return (
    <>
      <HubHeader
        eyebrow="Platform"
        title="Core consumption"
        subtitle="Where each app stands on the shared core, and the approvals that move it"
        status={
          data?.generated_at ? (
            <Pill tone={loading ? 'info' : 'neutral'}>
              Core {data.latest ?? '?'} &middot; feed {relTime(data.generated_at)}
            </Pill>
          ) : undefined
        }
      />
      {body}
    </>
  )
}
