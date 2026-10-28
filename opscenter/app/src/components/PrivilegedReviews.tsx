// Privileged GitHub environment approvals (governance, entra-privileged,
// destroy) and pending vendor secrets, shown on the private platform reviews
// Needs me tab. Approve / Reject go through server.py, which re-verifies the
// run is still waiting at the same commit before deciding it as me.
import type { TableColumn } from '@kit'
import { Button, Card, CardHead, EmptyState, Field, IconCheck, IconWarning, Input, Modal, ModalSection, Table } from '@kit'
import { useState } from 'react'
import type { PendingSecret, PrivItem } from '../lib/data'
import { postPrivDecision, relTime, useplatformReviews } from '../lib/data'
import { depConfirm, unblocks } from '../lib/deps'
import type { Tone } from '../pages/reviews/parts'
import {
  age,
  ErrorLine,
  Line,
  LinkButton,
  Locked,
  PrRef,
  Reasons,
  ResultNote,
  ReviewItem,
  riskTone,
  Tag,
  TextToggle,
} from '../pages/reviews/parts'
import { ApprovalBriefView } from './ApprovalBrief'
import { DepTag, DepWaitLines, UnblocksLine } from './DepWait'

const envTone = (e: string): Tone => (e === 'destroy' ? 'alert' : e === 'entra-privileged' ? 'warn' : 'info')
const ACT_LABEL: Record<string, string> = {
  create: 'add',
  update: 'change',
  delete: 'destroy',
  replace: 'replace',
  import: 'import',
  forget: 'forget',
}

function ConfirmModal({
  it,
  act,
  onCancel,
  onConfirm,
}: {
  it: PrivItem
  act: 'approve' | 'reject' | 'retry' | null
  onCancel: () => void
  onConfirm: (act: 'approve' | 'reject' | 'retry', typed: string) => void
}) {
  // approving a run whose PR waits on another PR is Approve anyway, said plainly.
  const anyway = it.phase === 'waiting_dep' && it.deps ? depConfirm('Approve this run', it.deps).split('\n\n')[1] : ''
  const [typed, setTyped] = useState('')
  const [last, setLast] = useState<'approve' | 'reject' | 'retry'>('approve')
  // Keep the last verb while the dialog plays its exit animation.
  const shown = act ?? last
  if (act && act !== last) setLast(act)
  const need = it.typed_confirm && shown !== 'reject'
  const ok = !need || typed.trim() === it.confirm_name
  const verb = shown === 'approve' ? 'Approve' : shown === 'retry' ? 'Retry' : 'Reject'
  // Approving a Destroy run deletes resources, and Reject is always the destructive verb.
  const danger = shown === 'reject' || it.environment === 'destroy'
  const close = () => {
    setTyped('')
    onCancel()
  }
  return (
    <Modal
      open={act !== null}
      onClose={close}
      role="alertdialog"
      size="md"
      title={shown === 'retry' ? `Retry ${it.env_label} deployment with my earlier approval` : `${verb} ${it.env_label} deployment`}
      subtitle={
        <>
          {it.workflow_name || it.workflow} run {it.run_id} at {it.head_sha.slice(0, 8)}
          {it.pr ? ` (PR #${it.pr.number})` : ''}. Posts &quot;
          {shown === 'reject' ? 'Changes requested' : 'Approved after review'}
          &quot; as me.
        </>
      }
      icon={danger ? <IconWarning /> : <IconCheck />}
      hue={danger ? 'red' : 'green'}
      footerStart={
        <span className="rh-modal-hint">
          The server re-checks that the run is still waiting on {it.environment} at this commit before deciding.
        </span>
      }
      primaryAction={{
        label: anyway && shown === 'approve' ? 'Approve anyway' : verb,
        danger: danger || (!!anyway && shown === 'approve'),
        disabled: !ok,
      }}
      onSubmit={(e) => {
        e.preventDefault()
        if (!ok) return
        const t = typed.trim()
        setTyped('')
        onConfirm(shown, t)
      }}
    >
      {shown === 'retry' && it.failed_apply && (
        <ModalSection title="What failed last time">
          <p className="rh-modal-text">
            Run {it.failed_apply.run_id} applied this same plan and failed: {it.failed_apply.error || 'no error line'}. Retry only if the
            cause is fixed.
          </p>
        </ModalSection>
      )}
      {shown === 'approve' && anyway && (
        <ModalSection title="It waits on another PR">
          <p className="rh-modal-text">{anyway}</p>
        </ModalSection>
      )}
      {shown !== 'reject' && it.plan && (
        <ModalSection title="Plan">
          <p className="rh-modal-text">
            {it.plan.add} add, {it.plan.change} change, <b className={it.plan.destroy ? 'rh-bad' : ''}>{it.plan.destroy} destroy</b>
            {it.environment === 'entra-privileged' && it.entra.length > 0 && (
              <>
                {' '}
                &middot; grants{' '}
                {it.entra
                  .filter((e) => e.change !== 'remove')
                  .map((e) => `${e.permission} (${e.kind})`)
                  .join(', ')}
              </>
            )}
          </p>
        </ModalSection>
      )}
      {need && (
        <ModalSection>
          <Field label={`Type ${it.confirm_name} to confirm`} required>
            <Input
              className="rh-mono"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              placeholder={it.confirm_name}
              spellCheck={false}
              autoComplete="off"
              data-autofocus=""
            />
          </Field>
        </ModalSection>
      )}
    </Modal>
  )
}

function AvdSummary({ it }: { it: PrivItem }) {
  const rel = it.release
  const win = rel?.window
  return (
    <div className="rh-plan">
      <h4 className="rh-h">Waiting job</h4>
      <p className="rh-modal-text">{rel?.job || 'Not read yet. Open the run before approving.'}</p>
      {rel?.stage_text && <p className="rh-modal-text">Approving means: {rel.stage_text}.</p>}
      <h4 className="rh-h">Window on main (manual-installs.json)</h4>
      {win ? (
        <p className="rh-modal-text">
          {win.date} &middot; {win.engineer}: {win.summary}
        </p>
      ) : rel?.window_read === false ? (
        <ErrorLine>Could not read manual-installs.json on main. Open the run before approving.</ErrorLine>
      ) : (
        <ErrorLine>No window entry on main for run {it.run_id}. The second gate (job 2) will refuse until it is recorded.</ErrorLine>
      )}
    </div>
  )
}

function ReleaseSummary({ it }: { it: PrivItem }) {
  if (it.environment === 'avd-image') return <AvdSummary it={it} />
  const pending = it.release?.pending
  if (pending == null) return <ErrorLine>What this release ships is not read yet. Open the run before approving.</ErrorLine>
  if (!pending) return <ErrorLine>No Pending release entry in the app_e CHANGELOG at this commit.</ErrorLine>
  return (
    <div className="rh-plan">
      <h4 className="rh-h">Ships (CHANGELOG, Pending release at {it.head_sha.slice(0, 8)})</h4>
      <pre className="rh-mono rh-pre">{pending}</pre>
    </div>
  )
}

function PlanSummary({ it }: { it: PrivItem }) {
  const [open, setOpen] = useState(it.environment === 'destroy')
  if (it.environment === 'app_e-build' || it.environment === 'app_e-release' || it.environment === 'avd-image')
    return <ReleaseSummary it={it} />
  const p = it.plan
  if (!p) {
    return <ErrorLine>Plan not readable yet ({it.plan_source || 'not fetched'}). Do not approve blind; open the run.</ErrorLine>
  }
  const dl = new Set(it.data_loss.map((d) => d.address))
  return (
    <div className="rh-plan">
      <span>
        <b>{p.add}</b> add &middot; <b>{p.change}</b> change &middot; <b className={p.destroy ? 'rh-bad' : ''}>{p.destroy}</b> destroy
        {p.replace ? (
          <>
            {' '}
            &middot; <b className="rh-bad">{p.replace}</b> replace
          </>
        ) : null}{' '}
        &middot; <span className="rh-muted">from {it.plan_source}</span> &middot;{' '}
        <TextToggle onClick={() => setOpen((o) => !o)} expanded={open}>
          {open ? 'hide' : 'show'} {p.resources.length} resource(s)
        </TextToggle>
      </span>
      {open && (
        <ul className="rh-res">
          {p.resources.map((r) => (
            <li key={`${r.action}-${r.address}-${r.root || ''}`} data-act={r.action}>
              <span className="rh-act">{ACT_LABEL[r.action] || r.action}</span> <code>{r.address}</code>
              {dl.has(r.address) && <span className="rh-bad"> data loss</span>}
            </li>
          ))}
        </ul>
      )}
      <Reasons items={p.errors.slice(0, 5)} />
    </div>
  )
}

function Assessment({ it }: { it: PrivItem }) {
  const a = it.assessment
  if (!a)
    return (
      <div className="rh-inset rh-muted">Assessment in progress (written by the gate's review step; usually within a few minutes).</div>
    )
  return (
    <div className="rh-inset">
      <p>{a.summary}</p>
      <h4 className="rh-h">What changes</h4>
      <ul>
        {a.changes.map((c, i) => (
          <li key={i}>{c}</li>
        ))}
      </ul>
      {a.permissions && a.permissions.length > 0 && (
        <>
          <h4 className="rh-h">Graph permissions</h4>
          <ul>
            {a.permissions.map((p) => (
              <li key={`${p.app}-${p.permission}-${p.kind}`}>
                <b>{p.app}</b> gets <code>{p.permission}</code> ({p.kind === 'application' ? 'application, tenant-wide' : 'delegated'}
                ): {p.reaches}
              </li>
            ))}
          </ul>
        </>
      )}
      {a.removed && a.removed.length > 0 && (
        <>
          <h4 className="rh-h">Removed (data loss: {a.data_loss})</h4>
          <ul>
            {a.removed.map((r) => (
              <li key={r.address}>
                <code>{r.address}</code> {r.data_loss ? <b className="rh-bad">loses data</b> : 'no data'}
                {r.note ? ` - ${r.note}` : ''}
              </li>
            ))}
          </ul>
        </>
      )}
      {a.governance_changes && a.governance_changes.length > 0 && (
        <>
          <h4 className="rh-h">Policy / identity / DNS</h4>
          <ul>
            {a.governance_changes.map((g, i) => (
              <li key={i}>
                [{g.kind}] <code>{g.target}</code>: {g.change}
              </li>
            ))}
          </ul>
        </>
      )}
      <p>
        <b>Risk ({a.risk.level}):</b> {a.risk.why}
      </p>
      <p>
        <b>Recommendation:</b> {a.recommendation.action} - {a.recommendation.why}
      </p>
      {a.checked_at && <p className="rh-line">assessed {relTime(a.checked_at)}</p>}
    </div>
  )
}

export function PrivNeedItem({ it, now }: { it: PrivItem; now: number }) {
  const { reload, mutate } = useplatformReviews()
  const [ask, setAsk] = useState<'approve' | 'reject' | 'retry' | null>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const a = age(it.since, now)
  const risk = it.assessment?.risk.level || it.auto_risk?.floor
  const grants = it.entra.filter((e) => e.change !== 'remove')
  const locked = it.phase === 'in_flight'
  const failed = it.status === 'blocked_failed_apply' ? it.failed_apply : null
  const dep = it.phase === 'waiting_dep' ? it.deps : undefined
  const { data } = useplatformReviews()
  const firstFor = dep ? [] : unblocks(data?.deps, it.pr?.number ?? null)
  // The raw run data. Under a brief it sits in the collapsed Details, the brief explains it.
  const raw = (
    <>
      <Reasons items={it.held_reasons} />
      <PlanSummary it={it} />
      {grants.length > 0 && (
        <ul className="rh-grants">
          {grants.map((e) => (
            <li key={`${e.app}-${e.permission}-${e.kind}`}>
              <Tag tone={riskTone(e.risk)}>{e.kind === 'application' ? 'application' : e.kind}</Tag> <b>{e.app || '?'}</b>{' '}
              <code>{e.permission}</code>
              {e.description ? <span className="rh-muted"> {e.description}</span> : null}
            </li>
          ))}
        </ul>
      )}
      {it.data_loss.length > 0 && <ErrorLine>Deletes data-bearing: {it.data_loss.map((d) => d.address).join(', ')}</ErrorLine>}
      {!failed && <Assessment it={it} />}
    </>
  )

  const go = async (act: 'approve' | 'reject' | 'retry', typed: string) => {
    setAsk(null)
    setBusy(true)
    setMsg(null)
    try {
      const r = await postPrivDecision(act, it.key, it.head_sha, typed || undefined, !!dep && act === 'approve')
      setMsg({ ok: true, text: `${r.status} run ${r.run} (${r.environment})` })
      // A card that waited on another PR was never counted on Needs me.
      mutate((d) => ({
        ...d,
        privileged: d.privileged.filter((n) => n.key !== it.key),
        counts: {
          ...d.counts,
          needs_me: dep ? d.counts.needs_me : d.counts.needs_me - 1,
        },
      }))
      setTimeout(reload, 1500)
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <ReviewItem
      pulse={it}
      working={locked}
      state="needs_you"
      top={
        <>
          {locked && (
            <Tag tone="info" live>
              {it.assessment ? 're-checking' : 'assessing'}
            </Tag>
          )}
          <PrRef href={it.run_url}>run {it.run_id}</PrRef>
          {dep && <DepTag v={dep} />}
          <Tag tone={envTone(it.environment)}>{it.env_label}</Tag>
          {it.unexpected && <Tag tone="alert">unexpected</Tag>}
          {failed && <Tag tone="alert">Apply failed</Tag>}
          {!failed &&
            (it.assessment ? (
              <Tag tone={riskTone(risk)}>{risk} risk</Tag>
            ) : (
              <Tag tone="neutral">assessing (floor {it.auto_risk?.floor})</Tag>
            ))}
          {!failed && it.assessment && (
            <Tag tone={it.assessment.recommendation.action === 'approve' ? 'good' : 'alert'}>
              recommend {it.assessment.recommendation.action}
            </Tag>
          )}
          {(it.brief?.wait_for || []).map((w) => (
            <Tag key={w.number} tone="alert">
              wait for #{w.number}
            </Tag>
          ))}
          <Tag tone={a.old ? 'alert' : 'neutral'}>waiting on you {a.text}</Tag>
        </>
      }
      title={
        // The written brief names what the plan really changes, which is not always the PR the run started from.
        it.brief?.source === 'model' && it.brief.title ? (
          <span>{it.brief.title}</span>
        ) : it.pr ? (
          <>
            <a href={it.pr.url} target="_blank" rel="noreferrer">
              PR #{it.pr.number}
            </a>{' '}
            {it.pr.title}
          </>
        ) : (
          <span>{it.workflow_name || it.workflow} (no merged PR found for this commit)</span>
        )
      }
      meta={
        it.brief?.ask ? (
          <>
            Run started from{' '}
            {it.pr ? (
              <a href={it.pr.url} target="_blank" rel="noreferrer">
                PR #{it.pr.number}
              </a>
            ) : (
              `commit ${it.head_sha.slice(0, 8)}`
            )}
            . Paused at {it.env_label} until you approve or reject it.
          </>
        ) : (
          <>
            The {it.workflow_name || it.workflow.replace('.github/workflows/', '')} workflow, started by a {it.event} to {it.head_branch} at
            commit {it.head_sha.slice(0, 8)}
            {it.pr ? `, the merge of PR #${it.pr.number}${it.pr.author ? ` by ${it.pr.author}` : ''}` : ''}
            {it.actor ? `, run by ${it.actor}` : ''}. It is paused at the {it.env_label} environment until you approve or reject it.
          </>
        )
      }
      actions={
        <>
          {locked ? (
            <Locked />
          ) : failed ? (
            <>
              {/* the plan equals one I approved whose apply failed. Retry reuses that approval. */}
              {!it.unexpected && (
                <Button size="sm" variant="primary" loading={busy} onClick={() => setAsk('retry')}>
                  {busy ? 'Working...' : 'Retry with my earlier approval'}
                </Button>
              )}
              <Button size="sm" variant="danger" disabled={busy} onClick={() => setAsk('reject')}>
                Request changes
              </Button>
            </>
          ) : (
            <>
              {/* Approve only renders when the server would take it: assessed and on main. */}
              {!it.unexpected && it.assessment && (
                <Button size="sm" variant={dep ? 'secondary' : 'primary'} loading={busy} onClick={() => setAsk('approve')}>
                  {busy ? 'Working...' : dep ? 'Approve anyway' : 'Approve'}
                </Button>
              )}
              {!dep && (
                <Button size="sm" variant="danger" disabled={busy} onClick={() => setAsk('reject')}>
                  Reject
                </Button>
              )}
            </>
          )}
          <LinkButton href={it.run_url}>{failed ? 'Open waiting run' : 'Open run'}</LinkButton>
          {failed && <LinkButton href={failed.run_url}>Open failed run</LinkButton>}
        </>
      }
    >
      {failed && (
        <>
          <ErrorLine>
            Apply failed in run {failed.run_id}
            {failed.failed_at ? ` ${relTime(failed.failed_at)}` : ''}: {failed.error || 'no error line in the job log'}
          </ErrorLine>
          <Line>
            This plan is identical to the one I approved in run {failed.run_id}, so I am not asking for a fresh review. Run {it.run_id} is
            the new run waiting at the {it.env_label} environment. Retry uses my earlier approval, Request changes rejects this run.
          </Line>
        </>
      )}
      {dep ? <DepWaitLines v={dep} /> : it.blocked && <Line>{it.blocked}</Line>}
      <UnblocksLine prs={firstFor} />
      {it.unexpected && !locked && <Line>Not on main, so this environment cannot be approved. Reject it.</Line>}
      {it.data_loss.length > 0 && (
        <ErrorLine>
          This run deletes {it.data_loss.length} resource(s) that hold data, and that data is gone once it runs. The brief names them.
        </ErrorLine>
      )}
      {it.brief && !failed ? (
        <ApprovalBriefView
          repo="platform"
          card={`priv:${it.key}`}
          brief={it.brief}
          reload={reload}
          detailsLabel="Details: hold reasons, plan resources, Graph grants and the gate assessment"
        >
          {raw}
        </ApprovalBriefView>
      ) : (
        raw
      )}
      <ResultNote msg={msg} />
      <ConfirmModal it={it} act={ask} onCancel={() => setAsk(null)} onConfirm={go} />
    </ReviewItem>
  )
}

function CopyLink({ url }: { url: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <TextToggle
      onClick={() => {
        navigator.clipboard?.writeText(url).then(() => {
          setCopied(true)
          setTimeout(() => setCopied(false), 1500)
        })
      }}
    >
      {copied ? 'copied' : 'copy link'}
    </TextToggle>
  )
}

const SECRET_COLS: TableColumn<PendingSecret>[] = [
  { key: 'app', header: 'App', value: (s) => s.app },
  {
    key: 'secret',
    header: 'Secret',
    value: (s) => s.secret,
    render: (s) => <code>{s.secret}</code>,
  },
  {
    key: 'vault',
    header: 'Vault',
    value: (s) => s.vault,
    render: (s) => <code>{s.vault}</code>,
  },
  { key: 'tier', header: 'Tier', value: (s) => s.tier },
  {
    key: 'writer',
    header: 'Designated writer',
    value: (s) => s.writer,
    render: (s) => s.writer || <span className="rh-muted">not set</span>,
  },
  {
    key: 'age',
    header: 'Age',
    numeric: true,
    value: (s) => s.age_days,
    render: (s) => (
      <span className={(s.age_days || 0) >= 3 ? 'rh-bad' : ''}>
        {s.age_days === null || s.age_days === undefined ? '?' : `${s.age_days}d`}
      </span>
    ),
  },
  {
    key: 'links',
    header: 'Links',
    hideHeader: true,
    sortable: false,
    render: (s) => (
      <span className="rh-cell-links">
        <a href={s.portal_url} target="_blank" rel="noreferrer">
          Key Vault
        </a>{' '}
        <CopyLink url={s.portal_url} />
      </span>
    ),
  },
]

export function PendingSecrets() {
  const { data } = useplatformReviews()
  const [q, setQ] = useState('')
  const s = data?.waiting_on_others?.secrets
  if (!s) return null
  const items = s.items || []
  const sub =
    s.status === 'ok'
      ? `${items.length} vendor secret(s) still at placeholder \u00b7 checked ${s.updated ? relTime(s.updated) : 'never'}`
      : s.status === 'not_available'
        ? 'secrets-pending.py is not on main yet'
        : s.status === 'never_run'
          ? 'not checked yet'
          : `check ${s.status}${s.last_ok ? `, last good ${relTime(s.last_ok)}` : ''}`
  return (
    <Card as="section">
      <CardHead
        title="Waiting on others"
        subtitle={sub}
        controls={
          items.length > 0 ? (
            <Input
              className="rh-filter"
              type="search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Filter"
              aria-label="Filter secrets"
            />
          ) : undefined
        }
      />
      {s.error && s.status !== 'not_available' && <ErrorLine>{s.error}</ErrorLine>}
      {items.length === 0 ? (
        <EmptyState compact title={s.status === 'ok' ? 'No vendor secrets waiting on a writer.' : 'Nothing to show.'} />
      ) : (
        <Table
          caption="Vendor secrets still at placeholder"
          columns={SECRET_COLS}
          rows={items}
          rowKey={(x) => `${x.vault}-${x.secret}`}
          filter={q}
          noMatch={<EmptyState compact title="No matching secrets" />}
        />
      )}
    </Card>
  )
}
