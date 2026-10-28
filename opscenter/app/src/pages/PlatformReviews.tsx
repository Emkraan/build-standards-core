// platform sub-tab of the Reviews hub (private): engineer PRs the automated review escalated
// to me, held terraform-plan runs, what the automation is iterating on, and
// what shipped in the last 14 days. Actions go through server.py as github_user.
import type { TableColumn } from '@kit'
import { Button, Card, CardHead, EmptyState, Field, Input, StatusDot, Table, Textarea, useConfirm, useToast } from '@kit'
import { useState } from 'react'
import AlertBanner from '../components/AlertBanner'
import { ApprovalBriefView } from '../components/ApprovalBrief'
import { confirmText } from '../components/confirmText'
import { DecisionCard } from '../components/DecisionCard'
import { DepTag, DepWaitLines, UnblocksLine } from '../components/DepWait'
import { DiscussPr } from '../components/DiscussPr'
import { EcrForm, HeldItem, WindowBrief } from '../components/MaintenanceHold'
import { OwnerFlightPoll, OwnerRootItem } from '../components/OwnerRoots'
import { PendingSecrets, PrivNeedItem } from '../components/PrivilegedReviews'
import { needsRelease, RunbookReleaseItem } from '../components/RunbookReleases'
import { Tabs } from '../components/Tabs'
import TfReviews from '../components/TfReviews'
import { TriagePr } from '../components/TriagePr'
import { olyMineNeedsMe, olyPrWorking, useActionCounts } from '../lib/counts'
import type { OlyBreakdown, OlyMyPr, OlyNeed, OlyPlan, OlyShipped, OlyThreadWait, TfHeldDelta } from '../lib/data'
import {
  postplatformAcceptRisk,
  postplatformApproveMerge,
  postplatformDecision,
  postplatformRemoveHoldLabel,
  postplatformResolveThread,
  relTime,
  useNow,
  useplatformReviews,
} from '../lib/data'
import { depConfirm, unblocks } from '../lib/deps'
import { olyPrState, PR_STATE_LABEL, type PrState, type PrStateView } from '../lib/ownPrs'
import type { Tone } from './reviews/parts'
import {
  actedNow,
  age,
  ErrorCard,
  ErrorLine,
  JustActed,
  Line,
  LinkButton,
  LoadingCard,
  Locked,
  PrRef,
  Reasons,
  ResultNote,
  ReviewItem,
  recTone,
  riskTone,
  Tag,
  TextToggle,
} from './reviews/parts'

function PlanLine({ plan }: { plan: OlyPlan | string | null | undefined }) {
  if (!plan) return null
  if (typeof plan === 'string') return <span>{plan}</span>
  if (plan.ran === false) return <span className="rh-muted">{plan.note || 'terraform-ci did not run'}</span>
  if (plan.summary && plan.add === undefined) return <span>{plan.summary}</span>
  const d = plan.destroy || 0
  const r = plan.replace || 0
  return (
    <span>
      <b>{plan.add || 0}</b> add &middot; <b>{plan.change || 0}</b> change &middot; <b className={d ? 'rh-bad' : ''}>{d}</b> destroy
      {r ? (
        <>
          {' '}
          &middot; <b className="rh-bad">{r}</b> replace
        </>
      ) : null}
      {plan.import ? <> &middot; {plan.import} import</> : null}
      {plan.run_url && (
        <>
          {' '}
          &middot;{' '}
          <a href={plan.run_url} target="_blank" rel="noreferrer">
            terraform-ci {plan.conclusion || ''}
          </a>
        </>
      )}
    </span>
  )
}

// a re-ask after my approval links only the newly held files' diff since the head I approved.
function HeldDeltaLine({ d }: { d: TfHeldDelta }) {
  const since = d.base_sha.slice(0, 8)
  return (
    <Line>
      Changed since my approval of {since}:{' '}
      {d.files.map((f, i) => (
        <span key={f.path}>
          {i ? ', ' : ''}
          <a href={f.url} target="_blank" rel="noreferrer">
            <code>{f.path}</code>
          </a>{' '}
          <span className="rh-muted">
            +{f.additions} -{f.deletions}
          </span>
        </span>
      ))}
      {d.unchanged.length > 0 && (
        <>
          {d.files.length ? '. ' : ''}
          <span className="rh-muted">Same between the two heads (main moved under it): {d.unchanged.join(', ')}</span>
        </>
      )}
      {d.unknown.length > 0 && (
        <>
          {d.files.length || d.unchanged.length ? '. ' : ''}
          <span className="rh-muted">
            {d.error ? 'Could not read the delta' : 'Not in the compare list'}: {d.unknown.join(', ')}
          </span>
        </>
      )}{' '}
      &middot;{' '}
      <a href={d.compare_url} target="_blank" rel="noreferrer">
        Open the diff
      </a>
    </Line>
  )
}

function Breakdown({ b, plan }: { b: OlyBreakdown; plan: OlyPlan | null }) {
  return (
    <div className="rh-inset">
      <p>{b.summary}</p>
      <h4 className="rh-h">What changes</h4>
      <ul>
        {b.changes.map((c, i) => (
          <li key={i}>{typeof c === 'string' ? c : `${c.file} -> ${c.behaviour}`}</li>
        ))}
      </ul>
      <h4 className="rh-h">Plan</h4>
      <p>
        <PlanLine plan={b.plan || plan} />
      </p>
      <h4 className="rh-h">Escalation rule</h4>
      <Reasons items={b.rules.map((r) => (typeof r === 'string' ? r : `${r.rule}: ${r.reason || ''}${r.where ? ` (${r.where})` : ''}`))} />
      <p>
        <b>Risk ({b.risk.level}):</b> {b.risk.why}
      </p>
      <p>
        <b>Recommendation:</b> {b.recommendation.action} - {b.recommendation.why}
      </p>
      {b.checked_at && <p className="rh-line">assessed {relTime(b.checked_at)}</p>}
    </div>
  )
}

function NeedItem({ it, now }: { it: OlyNeed; now: number }) {
  const locked = it.phase === 'in_flight'
  // I approved, it waits on other people's open conversations. Resolve per thread is the action.
  const tw = it.phase === 'waiting_threads' ? it.threads_wait : undefined
  // the PR waits on another PR. Not counted, and the only action is Approve anyway.
  const dep = it.phase === 'waiting_dep' ? it.deps : undefined
  const { data, reload, mutate } = useplatformReviews()
  const firstFor = dep ? [] : unblocks(data?.deps, it.pr)
  const { toast } = useToast()
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [showRc, setShowRc] = useState(false)
  const [text, setText] = useState('')
  // typing the confirm name here lets the post-merge privileged apply of this same plan go
  // through without a second card. Optional: left blank, the privileged card asks as before.
  const [typed, setTyped] = useState('')
  const [showFiles, setShowFiles] = useState(false)
  const [showEcr, setShowEcr] = useState(false)
  // A card that waits on another PR keeps its review details folded, the waiting lines lead.
  const [showDetail, setShowDetail] = useState(false)
  const { confirm: ask, dialog } = useConfirm()
  const a = age(it.since, now)
  const b = it.breakdown
  // Approve on a change that takes a system down outside its window approves now and merges
  // in the window. Merge now (ECR override) is the separate emergency path with a reason.
  const w = it.window
  const holds = !!w?.held_on_approve
  const heldReasons = it.tfplan && it.tfplan.held_reasons.length > 0 && !b?.rules.length ? <Reasons items={it.tfplan.held_reasons} /> : null

  const act = async (kind: 'approve' | 'request-changes', ecrReason?: string) => {
    if (it.pr === null) return
    if (dep) return actAnyway(it.pr)
    const blocked = (b?.rules || []).some((r) => (typeof r === 'string' ? r : r.rule).includes('ai-review-blocking'))
    const what =
      kind === 'approve'
        ? `${ecrReason ? 'APPROVE AND MERGE NOW (ECR override)' : 'APPROVE'} PR #${it.pr} as you${blocked ? ' (this applies ai-review-override: you are overriding its blocking findings)' : ''}${it.sources.includes('tfplan') ? ' and approve its pending terraform-plan runs' : ''}`
        : `REQUEST CHANGES on PR #${it.pr}${it.sources.includes('tfplan') ? ' and reject its pending terraform-plan runs' : ''}`
    const windowNote =
      kind === 'approve' && w?.brief
        ? ecrReason
          ? `\n\n${w.brief.down} It merges now, outside the ${w.class_label} window. Your reason is recorded: ${ecrReason}`
          : holds
            ? `\n\n${w.brief.down} It is approved now and held. ${w.brief.when}`
            : ''
        : ''
    // Approve also queues the merge, so it is the destructive one (danger, Cancel takes focus).
    const ok = await ask({
      ...confirmText(`${what} at ${it.head_sha.slice(0, 8)}?${windowNote}`),
      confirmLabel: kind === 'approve' ? (ecrReason ? 'Merge now' : holds ? 'Approve, merge in window' : 'Approve') : 'Request changes',
      danger: kind === 'approve',
    })
    if (!ok) return
    setBusy(true)
    setMsg(null)
    try {
      const confirmName = kind === 'approve' && it.confirm_needed && typed.trim() === it.confirm_needed ? typed.trim() : undefined
      const r = await postplatformDecision(kind, it.pr, it.head_sha, text.trim() || undefined, ecrReason, undefined, confirmName)
      setMsg({ ok: true, text: r.done.join('; ') || 'done' })
      const notShipped = (r as { waiting_threads?: boolean }).waiting_threads || r.done.some((d) => d.startsWith('merge not queued'))
      if (kind === 'approve' && notShipped) {
        // held on open conversations, or the merge did not queue. The card stays, reloaded.
        toast('info', `PR #${it.pr}: ${r.done[0]}`)
        reload()
        return
      }
      mutate((d) => ({
        ...d,
        needs_me: d.needs_me.filter((n) => n.key !== it.key),
        acted: kind === 'approve' && it.pr != null ? [actedNow(it.pr, it.title || '', 'approved'), ...(d.acted || [])] : d.acted,
        counts: { ...d.counts, needs_me: Math.max(0, d.counts.needs_me - 1) },
      }))
      toast('success', `PR #${it.pr}: ${r.done.join('; ') || 'done'}`)
      setTimeout(reload, 1500)
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusy(false)
    }
  }

  const actAnyway = async (pr: number) => {
    if (!dep) return
    const what = `Approve PR #${pr}${it.sources.includes('tfplan') ? ' and its pending terraform-plan runs' : ''}`
    const ok = await ask({ ...confirmText(depConfirm(what, dep)), confirmLabel: 'Approve anyway', danger: true })
    if (!ok) return
    setBusy(true)
    setMsg(null)
    try {
      const r = await postplatformDecision('approve', pr, it.head_sha, undefined, undefined, true)
      setMsg({ ok: true, text: r.done.join(', ') || 'done' })
      // Not counted on Needs me, so only the waiting list changes.
      mutate((d) => ({
        ...d,
        needs_waiting: (d.needs_waiting || []).filter((n) => n.key !== it.key),
        acted: [actedNow(pr, it.title || '', 'approved', 'approved anyway'), ...(d.acted || [])],
      }))
      toast('success', `PR #${pr}: ${r.done.join(', ') || 'done'}`)
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
      state={dep ? 'waiting' : 'needs_you'}
      working={locked}
      top={
        <>
          {dep && <DepTag v={dep} />}
          {tw && <Tag tone="info">approved, waiting on conversations</Tag>}
          {it.merge_error && it.merge_error.length > 0 && (
            <Tag tone="alert">{it.merge_pending?.state === 'ejected' ? 'left the merge queue' : 'merge did not queue'}</Tag>
          )}
          {locked && (
            <Tag tone="info" live>
              {it.merge_pending ? 'merge queued' : 're-checking'}
            </Tag>
          )}
          <PrRef href={it.url}>{it.pr !== null ? `#${it.pr}` : 'run'}</PrRef>
          {it.sources.map((s) => (
            <Tag key={s} tone="info">
              {s === 'review' ? 'PR review' : 'terraform-plan hold'}
            </Tag>
          ))}
          {b ? <Tag tone={riskTone(b.risk?.level)}>{b.risk?.level} risk</Tag> : <Tag tone="neutral">assessing</Tag>}
          {b && <Tag tone={recTone(b.recommendation?.action)}>recommend {b.recommendation?.action}</Tag>}
          <Tag tone={a.old ? 'alert' : 'neutral'}>waiting {a.text}</Tag>
        </>
      }
      title={it.title}
      meta={
        <>
          {it.author} &middot; {it.head_sha.slice(0, 8)}
          {it.tfplan && (
            <>
              {' '}
              &middot; {it.tfplan.run_ids.length} plan run(s) &middot;{' '}
              <TextToggle onClick={() => setShowFiles((s) => !s)} expanded={showFiles}>
                {it.tfplan.files.length} file(s)
              </TextToggle>
            </>
          )}
        </>
      }
      actions={
        locked ? (
          <>
            <Locked />
            {it.url && <LinkButton href={it.url}>Open PR</LinkButton>}
          </>
        ) : tw && it.pr !== null ? (
          <>
            <Button size="sm" disabled={busy} aria-expanded={showRc} onClick={() => setShowRc((s) => !s)}>
              Request changes
            </Button>
            <DiscussPr repo="platform" pr={it.pr} />
            <LinkButton href={it.url}>Open PR</LinkButton>
          </>
        ) : dep && it.pr !== null ? (
          <>
            <Button size="sm" variant="secondary" loading={busy} onClick={() => act('approve')}>
              {busy ? 'Working...' : 'Approve anyway'}
            </Button>
            <LinkButton href={it.url}>Open PR</LinkButton>
          </>
        ) : it.pr !== null ? (
          <>
            <Button size="sm" variant="primary" loading={busy} onClick={() => act('approve')}>
              {busy ? 'Working...' : it.merge_error?.length ? 'Retry merge' : holds ? 'Approve, merge in window' : 'Approve as me'}
            </Button>
            {holds && !showEcr && (
              <Button size="sm" variant="secondary" disabled={busy} onClick={() => setShowEcr(true)}>
                Merge now (ECR override)
              </Button>
            )}
            <Button size="sm" disabled={busy} aria-expanded={showRc} onClick={() => setShowRc((s) => !s)}>
              Request changes
            </Button>
            <DiscussPr repo="platform" pr={it.pr} />
            <LinkButton href={it.url}>Open PR</LinkButton>
          </>
        ) : undefined
      }
    >
      {dialog}
      {dep ? <DepWaitLines v={dep} /> : it.blocked && <Line>{it.blocked}</Line>}
      {tw && it.pr !== null && <ThreadWait w={tw} pr={it.pr} />}
      {it.merge_error && it.merge_error.length > 0 && (
        <ErrorLine>
          Approved on GitHub, but {it.merge_pending?.state === 'ejected' ? 'it ' : 'the merge did not queue: '}
          {it.merge_error.join('; ')}
        </ErrorLine>
      )}
      <UnblocksLine prs={firstFor} />
      {holds && w && it.pr !== null && <WindowBrief w={w} pr={it.pr} />}
      {showEcr && holds && !locked && <EcrForm busy={busy} onSubmit={(r) => act('approve', r)} onCancel={() => setShowEcr(false)} />}
      {showFiles && it.tfplan && (
        <ul className="rh-files">
          {it.tfplan.files.map((f) => (
            <li key={f}>
              <code>{f}</code>
            </li>
          ))}
        </ul>
      )}
      {it.tfplan?.held_delta && it.tfplan.held_delta.head_sha === it.tfplan.head_sha && <HeldDeltaLine d={it.tfplan.held_delta} />}
      {it.tfplan?.working && <Line>Note: {it.tfplan.working}. The plan still waits on my approval.</Line>}
      {dep && (
        <Line>
          <TextToggle onClick={() => setShowDetail((x) => !x)} expanded={showDetail}>
            {showDetail ? 'Hide the review details' : 'Show the review details'}
          </TextToggle>
        </Line>
      )}
      {dep && !showDetail ? null : it.brief && it.pr !== null ? (
        <ApprovalBriefView repo="platform" pr={it.pr} brief={it.brief} reload={reload}>
          {heldReasons}
          {b && <Breakdown b={b} plan={it.plan} />}
        </ApprovalBriefView>
      ) : (
        <>
          {heldReasons}
          {b && <Breakdown b={b} plan={it.plan} />}
        </>
      )}
      {it.confirm_needed && !dep && !locked && it.pr !== null && (
        <div className="rh-rc">
          <Field
            label={`Type ${it.confirm_needed} to also cover the post-merge apply`}
            optional
            hint="The plan deletes something or grants Entra permissions. With the name typed, the apply after merge runs without a second card as long as its plan matches this one. Leave it blank and the privileged card asks me again."
          >
            <Input
              className="rh-mono"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              placeholder={it.confirm_needed}
              spellCheck={false}
              autoComplete="off"
            />
          </Field>
        </div>
      )}
      {showRc && (
        <div className="rh-rc">
          <Field label="Review comment" optional>
            <Textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={3}
              placeholder="Optional note, posted as my review comment (my voice, no tool names)"
            />
          </Field>
          <Button size="sm" variant="primary" disabled={busy} onClick={() => act('request-changes')}>
            Post request changes
          </Button>
        </div>
      )}
      <ResultNote msg={msg} />
    </ReviewItem>
  )
}

// the open conversations my held approval waits on. The person who raised each one resolves
// it on GitHub (they were tagged once in a PR comment). Resolve here closes it as me.
function ThreadWait({ w, pr }: { w: OlyThreadWait; pr: number }) {
  const { reload } = useplatformReviews()
  const { toast } = useToast()
  const { confirm: ask, dialog } = useConfirm()
  const [busy, setBusy] = useState<string | null>(null)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const resolve = async (t: OlyThreadWait['threads'][number]) => {
    const where = t.path ? `${t.path}${t.line ? ` line ${t.line}` : ''}` : 'the PR'
    const last = w.threads.length === 1
    const ok = await ask({
      ...confirmText(
        `Resolve ${t.automated ? 'the automated review' : `${t.starter}'s`} conversation on ${where} as you?${last ? ' It is the last open one, so your approval posts and the merge queues right away.' : ''}`,
      ),
      confirmLabel: last ? 'Resolve and merge' : 'Resolve',
      danger: last,
    })
    if (!ok) return
    setBusy(t.id)
    setMsg(null)
    try {
      const r = await postplatformResolveThread(pr, t.id)
      setMsg({ ok: true, text: r.done.join('; ') })
      toast('success', `PR #${pr}: ${r.done.join('; ')}`)
      setTimeout(reload, 1000)
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusy(null)
    }
  }
  return (
    <>
      {dialog}
      <Line>
        I tagged the people who raised these in one PR comment. Each person resolves their own conversation once it is handled. Your
        approval posts and the merge queues on its own when none are open (checked every 90 seconds). A new push brings the card back for a
        fresh approval.
      </Line>
      <ul className="rh-files">
        {w.threads.map((t) => (
          <li key={t.id}>
            <strong>{t.automated ? 'Automated review' : t.starter}</strong> on <code>{t.path || 'the PR'}</code>
            {t.line ? ` line ${t.line}` : ''}
            {t.outdated ? ' (outdated)' : ''}: {t.last_text || '(no text)'}
            {t.replies > 1 ? ` (last reply by ${t.last_author})` : ''} {t.url && <LinkButton href={t.url}>Open</LinkButton>}{' '}
            <Button size="sm" variant="secondary" loading={busy === t.id} disabled={!!busy} onClick={() => resolve(t)}>
              Resolve
            </Button>
          </li>
        ))}
      </ul>
      {w.last_error && <ErrorLine>Last try to post the approval failed: {w.last_error}</ErrorLine>}
      <ResultNote msg={msg} />
    </>
  )
}

const BEHIND_LABEL = { problem: 'Open', signoff: 'Sign-off', unknown: 'Unchecked', covered: 'Covered' }

function NeedsMe() {
  const { data, error } = useplatformReviews()
  const now = useNow(60_000)
  if (error && !data) return <ErrorCard title="Could not load platform reviews" error={error} />
  if (!data) return <LoadingCard label="Loading platform reviews" />
  // My PRs the own-PR lane holds for me by policy ("needs me: <rule>").
  // same rule the server counts with (olyMineNeedsMe), so the list and the badge agree.
  const mineNeed = (data.my_prs || []).filter(olyMineNeedsMe)
  // cards whose PR waits on another PR. Not counted, listed in chain order with Approve anyway.
  const chainKey = (v?: { first: number[]; chain: number[] }) => (v ? v.first[0] * 1000 + v.chain.length : 0)
  const mineWait = (data.my_prs || []).filter((p) => (p.hold?.kind === 'policy' || p.hold?.kind === 'direction') && !!p.deps)
  const needWait = [...(data.needs_waiting || [])].sort((x, y) => chainKey(x.deps) - chainKey(y.deps) || (x.pr || 0) - (y.pr || 0))
  const privWait = (data.privileged || []).filter((p) => p.phase === 'waiting_dep')
  const waitCount = mineWait.length + needWait.length + privWait.length
  // Owner-applied roots with a pending plan, a failure, or an expired sign-in.
  // The server decides the phase (main moved, plan running), so a card is only here when I can act on it.
  const ownerItems = data.owner_roots?.items || []
  const ownerNeed = ownerItems.filter((r) => r.phase === 'needs_me')
  const ownerFlight = ownerItems.filter((r) => r.phase === 'in_flight' && (r.pending_since || r.main_moved || r.state === 'applying'))
  const ownerRunning = !!data.owner_roots?.running
  const liveMain = data.owner_roots?.live_main || null
  const ownerSignin = data.owner_roots?.signin || null
  // runbook-root deletes to release, and releases that went wrong, count. In-flight ones show below.
  const releases = data.runbook_releases || []
  const releaseNeed = releases.filter(needsRelease)
  const releaseOther = releases.filter((r) => !needsRelease(r))
  // Server truth (10/13): only cards whose action would go through count. The rest render locked below.
  const privNeed = (data.privileged || []).filter((p) => (p.phase || 'needs_me') === 'needs_me')
  const privFlight = (data.privileged || []).filter((p) => p.phase === 'in_flight')
  const needFlight = data.needs_in_flight || []
  const total = data.needs_me.length + privNeed.length + mineNeed.length + ownerNeed.length + releaseNeed.length
  return (
    <div className="rh-stack">
      <Card as="section">
        <CardHead
          title={
            <span className="rh-title-dot">
              <StatusDot tone={total ? 'danger' : 'success'} label={total ? 'Waiting on me' : 'All clear'} pulse={false} />
              Needs me
            </span>
          }
          subtitle={`${total} item(s) \u00b7 privileged deployments, Owner applies, escalations, held terraform plans, my PRs waiting on my sign-off, and my PRs auto-fix could not clear`}
        />
        {total === 0 ? (
          <EmptyState
            compact
            pose="celebrate"
            title="Nothing needs you."
            body="Governance, Entra consent and Destroy deployments, engineer PRs that trip a policy rule, and held Terraform plans land here."
          />
        ) : (
          <div className="rh-list">
            {privNeed.map((it) => (
              <PrivNeedItem key={it.key} it={it} now={now} />
            ))}
            {ownerNeed.map((it) => (
              <OwnerRootItem key={it.key} it={it} running={ownerRunning} liveMain={liveMain} signin={ownerSignin} now={now} />
            ))}
            {releaseNeed.map((it) => (
              <RunbookReleaseItem key={`rb-${it.pr}`} it={it} />
            ))}
            {data.needs_me.map((it) => (
              <NeedItem key={it.key} it={it} now={now} />
            ))}
            {mineNeed.map((p) => (
              <MyPrRow key={`mine-${p.pr}`} p={p} />
            ))}
          </div>
        )}
        {ownerFlight.length + privFlight.length + needFlight.length > 0 && (
          <div className="rh-list">
            <OwnerFlightPoll />
            <h3 className="rh-subhead">Working, actions return when it finishes</h3>
            {privFlight.map((it) => (
              <PrivNeedItem key={it.key} it={it} now={now} />
            ))}
            {ownerFlight.map((it) => (
              <OwnerRootItem key={it.key} it={it} running={ownerRunning} liveMain={liveMain} signin={ownerSignin} now={now} />
            ))}
            {needFlight.map((it) => (
              <NeedItem key={it.key} it={it} now={now} />
            ))}
          </div>
        )}
        {(data.needs_threads || []).length > 0 && (
          <div className="rh-list">
            <h3 className="rh-subhead">Approved, waiting on review conversations, not counted</h3>
            {(data.needs_threads || []).map((it) => (
              <NeedItem key={it.key} it={it} now={now} />
            ))}
          </div>
        )}
        {waitCount > 0 && (
          <div className="rh-list">
            <h3 className="rh-subhead">Waiting on another PR, not counted</h3>
            <p className="rh-line">
              Each of these waits on another PR first, so approving now would likely fail or be redone. Each card returns above once what it
              waits on clears. Approve anyway is there if you know it can pass now.
            </p>
            {privWait.map((it) => (
              <PrivNeedItem key={it.key} it={it} now={now} />
            ))}
            {needWait.map((it) => (
              <NeedItem key={it.key} it={it} now={now} />
            ))}
            {mineWait.map((p) => (
              <MyPrRow key={`mine-wait-${p.pr}`} p={p} />
            ))}
          </div>
        )}
        {releaseOther.length > 0 && (
          <div className="rh-list">
            <h3 className="rh-subhead">Runbook deletes in flight or finished today</h3>
            {releaseOther.map((it) => (
              <RunbookReleaseItem key={`rb-${it.pr}`} it={it} />
            ))}
          </div>
        )}
        {data.runbook_releases_error && <ErrorLine>Runbook deletes unreadable: {data.runbook_releases_error}</ErrorLine>}
        <JustActed items={data.acted} />
      </Card>
      <PendingSecrets />
      <TfReviews mode="auto" />
    </div>
  )
}

const verdictTone = (v?: string | null): Tone =>
  v === 'blocked' ? 'alert' : v === 'unavailable' ? 'warn' : v === 'clean' ? 'good' : v === 'findings' ? 'info' : 'neutral'

const STATE_TONE: Record<PrState, Tone> = {
  needs_you: 'warn',
  in_progress: 'info',
  waiting: 'neutral',
  stuck: 'alert',
  ready: 'good',
}

// Where the PR is at, in two plain sentences: why it sits there and what moves it next.
function StateLine({ s }: { s: PrStateView }) {
  return (
    <Line>
      <b>{s.state === 'needs_you' ? 'Waiting on you' : s.state === 'ready' ? 'Ready' : PR_STATE_LABEL[s.state]}:</b> {s.why} <b>Next:</b>{' '}
      {s.next}
    </Line>
  )
}

const PARKED: Record<string, { tone: Tone; label: (h: OlyMyPr['hold']) => string }> = {
  gate: { tone: 'neutral', label: (h) => `parked: gate ${h?.gate_met ?? 0} of ${h?.gate?.length ?? 0}` },
  main: { tone: 'neutral', label: () => 'waits on main apply' },
  nogate: { tone: 'warn', label: () => 'draft, no gate' },
}

function MyPrRow({ p }: { p: OlyMyPr }) {
  const { data, reload, mutate } = useplatformReviews()
  const dep = p.deps
  const firstFor = dep ? [] : unblocks(data?.deps, p.pr)
  const { toast } = useToast()
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const c = p.counts || {}
  const hold = p.hold
  const rules = hold?.rules || []
  const { confirm: ask, dialog } = useConfirm()
  // when the roots this merge applies delete something or change Entra objects, Approve and
  // merge stays off until I type the name. The brief decides (it knows which roots land), the hold's
  // own name is the fallback while the brief has no landing table. It is also stored for the 
  // carry, so the post-merge apply of the same plan does not ask me again.
  const [typed, setTyped] = useState('')
  const confirmName = dep ? null : p.brief?.landing ? (p.brief.confirm?.name ?? null) : (hold?.signoff_confirm ?? null)
  const confirmOk = !confirmName || typed.trim() === confirmName
  // Only a pure policy hold (everything passes, a rule needs my sign-off) gets a button.
  // Real problems are fixed on the branch and the lane merges them, so they get no merge button.
  const approve = async () => {
    if (!confirmOk) return
    // The brief's approving paragraph says in prose what this click does. The rule list is the fallback.
    const what = p.brief?.approving || `You are signing off on: ${rules.map((r) => r.plain).join('. ')}.`
    const ok = await ask(
      dep
        ? { ...confirmText(depConfirm(`Approve and merge PR #${p.pr}`, dep)), confirmLabel: 'Approve anyway', danger: true }
        : {
            ...confirmText(`Approve and merge PR #${p.pr} at ${p.head_sha.slice(0, 8)}?\n\n${what}`),
            confirmLabel: 'Approve and merge',
            danger: true,
          },
    )
    if (!ok) return
    setBusy(true)
    setMsg(null)
    try {
      const r = await postplatformApproveMerge(p.pr, p.head_sha, !!dep, confirmName ? typed.trim() : undefined)
      // Gone from Needs me and My PRs at once. The server keeps it hidden until GitHub agrees.
      // A row that waited on another PR was never counted, so the count stays.
      mutate((d) => ({
        ...d,
        my_prs: (d.my_prs || []).filter((x) => x.pr !== p.pr),
        acted: [actedNow(p.pr, p.title, 'merged'), ...(d.acted || [])],
        counts: { ...d.counts, needs_me: dep ? d.counts.needs_me : Math.max(0, d.counts.needs_me - 1) },
      }))
      toast('success', `PR #${p.pr}: ${r.done.join(', ')}`)
      setTimeout(reload, 1500)
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusy(false)
    }
  }
  const lh = hold?.label_hold
  // my click on Remove hold label. The confirm says what stands once it is gone.
  const removeHold = async () => {
    if (!lh) return
    const after = lh.behind.length
      ? `Still standing after that:\n${lh.behind.map((b) => `- ${b.text}`).join('\n')}`
      : 'Nothing else holds it. The lane merges it within 3 minutes.'
    const ok = await ask({
      ...confirmText(`Remove ${lh.label} from PR #${p.pr} at ${p.head_sha.slice(0, 8)}?\n\n${after}`),
      confirmLabel: 'Remove hold label',
      danger: lh.behind.length === 0,
    })
    if (!ok) return
    setBusy(true)
    setMsg(null)
    try {
      const r = await postplatformRemoveHoldLabel(p.pr, p.head_sha, lh.label)
      toast('success', `PR #${p.pr}: ${r.done.join(', ')}`)
      setTimeout(reload, 1500)
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusy(false)
    }
  }
  // my triage already answers every blocking finding on this head, so the one thing missing is
  // the ai-review-override label. This applies it as me and merges nothing.
  const acceptRisk = async () => {
    const ok = await ask({
      ...confirmText(
        `Accept the risk on PR #${p.pr} at ${p.head_sha.slice(0, 8)}?\n\n` +
          'This applies the ai-review-override label for the blocking findings I already triaged on this head. ' +
          'It does not merge the PR. The lane re-checks it within 3 minutes, then the card shows ' +
          (lh ? 'Remove hold label or Approve and merge.' : 'Approve and merge.') +
          '\n\nA new push removes the label and asks again.',
      ),
      confirmLabel: 'Accept the risk',
      danger: true,
    })
    if (!ok) return
    setBusy(true)
    setMsg(null)
    try {
      const r = await postplatformAcceptRisk(p.pr, p.head_sha)
      toast('success', `PR #${p.pr}: ${r.done.join(', ')}`)
      setTimeout(reload, 1500)
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusy(false)
    }
  }
  const fixing = hold?.autofix?.state === 'running'
  const deferred = hold?.autofix?.state === 'deferred'
  const working = olyPrWorking(p)
  const [triaging, setTriaging] = useState(false)
  // A held PR with blocking or high findings on this head can be triaged from here.
  const decision = !working && hold?.kind === 'direction' ? hold.decision : undefined
  const canTriage = !working && !decision && (hold?.kind === 'direction' || hold?.kind === 'problem') && (p.findings?.length ?? 0) > 0
  const reviewRunning = !p.verdict && !p.ai_result && p.pending.length > 0
  // Parked on purpose: its own pill, never "lane working".
  const parked = PARKED[hold?.parked ?? '']
  const holdTone: Tone = parked
    ? parked.tone
    : deferred
      ? 'info'
      : working && (hold?.kind === 'policy' || hold?.kind === 'direction')
        ? 'info'
        : hold?.kind === 'policy'
          ? 'warn'
          : hold?.kind === 'direction'
            ? 'alert'
            : hold?.kind === 'problem'
              ? fixing || deferred
                ? 'info'
                : lh
                  ? 'warn'
                  : 'alert'
              : 'neutral'
  // While checks run, a policy or direction hold is not final yet, so the pill says so.
  const holdLabel = parked
    ? parked.label(hold)
    : deferred
      ? 'session on it'
      : working && (hold?.kind === 'policy' || hold?.kind === 'direction')
        ? 're-checking'
        : hold?.kind === 'policy'
          ? 'needs your sign-off'
          : hold?.kind === 'direction'
            ? hold.decision
              ? 'needs your decision'
              : 'needs your direction'
            : hold?.kind === 'problem'
              ? fixing
                ? 'auto-fixing'
                : deferred
                  ? 'session on it'
                  : lh
                    ? 'held on purpose'
                    : 'needs a fix'
              : hold?.kind === 'waiting' && (p.waiting?.length ?? 0) > 0 && p.pending.length === 0
                ? 'waits on my plan approval'
                : 'lane working'
  // One state for the whole card (Needs you, In progress, Waiting, Stuck, Ready) with the cause and what
  // moves it next. The pill carries the state, the hold label says which kind.
  const st = olyPrState(p)
  const stLabel = PR_STATE_LABEL[st.state] + (hold && holdLabel !== 'lane working' ? `: ${holdLabel}` : '')
  // The raw rule list, plan counts and findings. Under a brief they sit in the collapsed Details.
  const details =
    rules.length > 0 || hold?.plan || p.blocking.length > 0 ? (
      <>
        {rules.length > 0 && (
          <Reasons
            tone="neutral"
            items={rules.map((r) => (
              <>
                <b>{r.plain}</b> {r.where && <code>{r.where}</code>}
              </>
            ))}
          />
        )}
        {hold?.plan && <Line>{hold.plan}</Line>}
        {p.blocking.length > 0 && (
          <Reasons
            items={p.blocking.map((x) => (
              <>
                {x.id}: {x.title} <code>{x.location}</code>
              </>
            ))}
          />
        )}
      </>
    ) : null
  return (
    <ReviewItem
      pulse={p}
      state={st.state}
      working={working}
      top={
        <>
          <PrRef href={p.url}>#{p.pr}</PrRef>
          {dep && <DepTag v={dep} />}
          <Tag
            tone={st.state === 'waiting' && holdTone !== 'neutral' ? 'neutral' : (STATE_TONE[st.state] ?? holdTone)}
            live={st.state === 'in_progress'}
          >
            {stLabel}
          </Tag>
          {p.model_bump && <Tag tone="info">model bump</Tag>}
          <Tag tone={verdictTone(p.verdict)} live={reviewRunning}>
            PR review {p.verdict ? p.verdict : p.ai_result ? p.ai_result.toLowerCase() : p.pending.length ? 'running' : 'not run'}
          </Tag>
          {p.red.length > 0 && <Tag tone="alert">{p.red.length} red</Tag>}
          {p.pending.length > 0 && (
            <Tag tone="info" live>
              {p.pending.length} running
            </Tag>
          )}
          {p.red.length === 0 && p.pending.length === 0 && p.ai_result === 'SUCCESS' && <Tag tone="good">all green</Tag>}
          {(p.waiting?.length ?? 0) > 0 &&
            (parked ? (
              <Tag tone="neutral">{p.waiting?.length} plan checks after the gate</Tag>
            ) : (
              <Tag tone="warn">{p.waiting?.length} waiting on plan approval</Tag>
            ))}
        </>
      }
      title={p.title}
      meta={
        <>
          {p.branch} &middot; {p.head_sha.slice(0, 8)}
          {p.verdict && (
            <>
              {' '}
              &middot; {c.blocking || 0} blocking, {c.high || 0} high, {c.medium || 0} medium, {c.low || 0} low
            </>
          )}
        </>
      }
      actions={
        <>
          {/* While work is running on the PR, no action buttons, so nothing can disrupt it. */}
          {canTriage && !triaging && (
            <Button size="sm" variant="primary" onClick={() => setTriaging(true)}>
              Triage findings
            </Button>
          )}
          {!working && hold?.kind === 'policy' && (
            <Button size="sm" variant={dep ? 'secondary' : 'primary'} loading={busy} disabled={!confirmOk} onClick={approve}>
              {busy ? 'Working...' : dep ? 'Approve anyway' : 'Approve and merge'}
            </Button>
          )}
          {!working && !decision && p.can_accept_risk && (
            <Button size="sm" variant={canTriage ? 'secondary' : 'primary'} loading={busy} onClick={acceptRisk}>
              {busy ? 'Working...' : 'Accept the risk'}
            </Button>
          )}
          {!working && lh && (
            <Button size="sm" variant={lh.clear && !canTriage ? 'primary' : 'secondary'} loading={busy} onClick={removeHold}>
              {busy ? 'Working...' : 'Remove hold label'}
            </Button>
          )}
          {!working && hold && hold.kind !== 'waiting' && <DiscussPr repo="platform" pr={p.pr} />}
          {working && <Locked />}
          <LinkButton href={p.url}>Open PR</LinkButton>
        </>
      }
    >
      {dialog}
      {dep && <DepWaitLines v={dep} />}
      <UnblocksLine prs={firstFor} />
      <StateLine s={st} />
      {hold && !p.brief && hold.summary !== st.why && <Line>{hold.summary}</Line>}
      {hold?.gate && hold.gate.length > 0 && (
        <Reasons
          tone="neutral"
          items={hold.gate.map((g) => (
            <>
              <b>{g.ok ? 'Met' : 'Not yet'}:</b> {g.label} ({g.detail})
            </>
          ))}
        />
      )}
      {lh && (
        <Line>
          Why:{' '}
          {lh.why ? `${lh.why} (decisions log ${lh.why_at})` : 'no decisions-log entry names this PR. Discuss with ops_center to find out.'}
        </Line>
      )}
      {lh && lh.behind.length > 0 && (
        <Reasons
          tone="neutral"
          items={lh.behind.map((b) => (
            <>
              <b>{BEHIND_LABEL[b.kind]}:</b> {b.text}
            </>
          ))}
        />
      )}
      {hold?.plan_line && <Line>{hold.plan_line}</Line>}
      {(p.waiting?.length ?? 0) > 0 && !hold?.plan_wait && !hold?.plan_line && (
        <Line>
          {p.waiting?.length} terraform check(s) wait on the terraform-plan environment. The plan gate takes them within 2 minutes.
        </Line>
      )}
      {p.brief ? (
        <ApprovalBriefView repo="platform" pr={p.pr} brief={p.brief} reload={reload}>
          {hold && <Line>{hold.summary}</Line>}
          {details}
        </ApprovalBriefView>
      ) : (
        details
      )}
      {confirmName && !working && hold?.kind === 'policy' && (
        <div className="rh-rc">
          <Field
            label={`Type ${confirmName} to enable Approve and merge`}
            required
            hint="The roots this merge applies delete something or change Entra objects. The name I type here also covers the apply after the merge, as long as its plan matches this one."
          >
            <Input
              className="rh-mono"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              placeholder={confirmName}
              spellCheck={false}
              autoComplete="off"
            />
          </Field>
        </div>
      )}
      <ResultNote msg={msg} />
      {decision && (
        <DecisionCard
          p={p}
          decision={decision}
          onDone={(text) => {
            // In flight until the lane acts on the choice: the row locks and reloads.
            mutate((d) => ({
              ...d,
              my_prs: (d.my_prs || []).map((x) =>
                x.pr === p.pr && x.hold ? { ...x, hold: { ...x.hold, kind: 'waiting', summary: text, decision: undefined } } : x,
              ),
              counts: { ...d.counts, needs_me: Math.max(0, d.counts.needs_me - 1) },
            }))
            setMsg({ ok: true, text })
            setTimeout(reload, 1500)
          }}
        />
      )}
      {triaging && canTriage && (
        <TriagePr
          p={p}
          onCancel={() => setTriaging(false)}
          onDone={(text) => {
            setTriaging(false)
            setMsg({ ok: true, text })
            setTimeout(reload, 1500)
          }}
        />
      )}
    </ReviewItem>
  )
}

function MyPrs() {
  const { data, error } = useplatformReviews()
  if (error && !data) return <ErrorCard title="Could not load platform reviews" error={error} />
  if (!data) return <LoadingCard label="Loading my PRs" />
  const mine = data.my_prs || []
  return (
    <Card as="section">
      <CardHead
        title="My PRs"
        subtitle={`My open platform PRs. The lane merges each one once it is green. Only a change a policy rule reserves for me gets Approve and merge. Status checked ${relTime(data.my_prs_refreshed ? data.my_prs_refreshed * 1000 : null)}. It refreshes in the background while this page is open.`}
      />
      {data.my_prs_error && <ErrorLine>Could not load my PRs: {data.my_prs_error}</ErrorLine>}
      {mine.length === 0 ? (
        <EmptyState compact title="No open PRs of mine." />
      ) : (
        <div className="rh-list">
          {mine.map((p) => (
            <MyPrRow key={p.pr} p={p} />
          ))}
        </div>
      )}
    </Card>
  )
}

function InProgress() {
  const { data } = useplatformReviews()
  const now = useNow(60_000)
  if (!data) return <LoadingCard label="Loading the review loop" />
  const held = data.held_for_window || []
  return (
    <div className="rh-stack">
      <Card as="section">
        <CardHead
          title="Waiting for the maintenance window"
          subtitle={`${held.length} PR(s). Engineer changes that take a production system down when they merge (an app deploy restarts it, or the plan replaces or restarts a serving resource) are approved by day and merge inside their window. Merge now (ECR override) is for emergencies only.`}
        />
        {data.held_for_window_error && <ErrorLine>Held list unreadable: {data.held_for_window_error}</ErrorLine>}
        {held.length === 0 ? (
          <EmptyState compact title="Nothing is waiting for a window." />
        ) : (
          <div className="rh-list">
            {held.map((h) => (
              <HeldItem key={`held-${h.pr}`} it={h} now={now} />
            ))}
          </div>
        )}
      </Card>
      <InProgressLoop />
    </div>
  )
}

function InProgressLoop() {
  const { data } = useplatformReviews()
  if (!data) return null
  return (
    <Card as="section">
      <CardHead title="In progress" subtitle="Engineer PRs the review loop is iterating on with the author" />
      {data.in_progress.length === 0 ? (
        <EmptyState compact title="No engineer PRs in the review loop." />
      ) : (
        <div className="rh-list">
          {data.in_progress.map((p) => (
            <ReviewItem
              pulse={p}
              key={p.pr}
              state="waiting"
              top={
                <>
                  <PrRef href={p.url}>#{p.pr}</PrRef>
                  <Tag tone={p.open_findings ? 'warn' : 'good'}>{p.open_findings || 0} open finding(s)</Tag>
                  {p.status === 'changes_requested' && <Tag tone="alert">changes requested</Tag>}
                  {p.rounds ? <Tag tone="neutral">round {p.rounds}</Tag> : null}
                </>
              }
              title={p.title}
              meta={
                <>
                  {p.author} &middot; {(p.head_sha || '').slice(0, 8)} &middot; {p.last_action || 'reviewing'}
                  {p.last_action_at ? ` \u00b7 ${relTime(p.last_action_at)}` : ''}
                </>
              }
            />
          ))}
        </div>
      )}
    </Card>
  )
}

const approvedLabel = (p: OlyShipped) =>
  p.approved_by === 'github_user' ? 'approved by me' : p.approved_by === 'auto-merge' ? 'my PR, auto-merged' : 'auto-approved'

const SHIPPED_COLS: TableColumn<OlyShipped>[] = [
  { key: 'pr', header: 'PR', value: (p) => p.pr, render: (p) => <PrRef href={p.url}>#{p.pr}</PrRef>, width: '84px' },
  { key: 'title', header: 'Title', value: (p) => p.title, render: (p) => <span className="rh-cell-title">{p.title}</span> },
  {
    key: 'status',
    header: 'Status',
    value: (p) => p.status,
    render: (p) => <Tag tone={p.status === 'merged' ? 'good' : 'info'}>{p.status}</Tag>,
    width: '110px',
  },
  { key: 'approved', header: 'Approval', value: approvedLabel, render: (p) => <Tag>{approvedLabel(p)}</Tag>, width: '170px' },
  { key: 'author', header: 'Author', value: (p) => p.author, width: '130px' },
  { key: 'when', header: 'When', value: (p) => p.when, render: (p) => relTime(p.when), width: '110px' },
]

function Shipped() {
  const { data } = useplatformReviews()
  const [q, setQ] = useState('')
  if (!data) return <LoadingCard label="Loading recently shipped" />
  return (
    <Card as="section">
      <CardHead
        title="Recently shipped"
        subtitle="Approved or merged in the last 14 days"
        controls={
          data.shipped.length > 0 ? (
            <Input
              className="rh-filter"
              type="search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Filter"
              aria-label="Filter shipped PRs"
            />
          ) : undefined
        }
      />
      <Table
        caption="platform PRs approved or merged in the last 14 days"
        columns={SHIPPED_COLS}
        rows={data.shipped}
        rowKey={(p) => String(p.pr)}
        filter={q}
        defaultSort={{ key: 'when', dir: 'desc' }}
        empty={<EmptyState compact title="Nothing shipped through review in the last 14 days." />}
        noMatch={<EmptyState compact title="No matching PRs" body="Try a shorter or different filter." />}
      />
    </Card>
  )
}

export function PlatformSection({ tab }: { tab?: string }) {
  const { data } = useplatformReviews()
  const c = data?.counts
  const { olyWorking } = useActionCounts()
  const gateBad = (data?.gate.failures || 0) >= 3
  const privBad = (data?.privileged_health?.failures || 0) >= 3
  return (
    <>
      <Tabs
        small
        label="platform reviews"
        tabs={[
          {
            to: '/reviews/platform',
            label: 'Needs me',
            n: c?.needs_me,
            end: true,
          },
          {
            to: '/reviews/platform/progress',
            label: 'In progress',
            n: c ? c.in_progress + (c.held_for_window || 0) : undefined,
          },
          {
            to: '/reviews/platform/mine',
            label: 'My PRs',
            n: c?.my_prs,
            live: olyWorking > 0,
          },
          { to: '/reviews/platform/shipped', label: 'Recently shipped' },
        ]}
      />
      {(gateBad || privBad) && (
        <div className="rh-alerts">
          {gateBad && <AlertBanner title={`Review gate failing (${data?.gate.failures} in a row)`}>{data?.gate.last_error}</AlertBanner>}
          {privBad && (
            <AlertBanner title={`Privileged-environment lane failing (${data?.privileged_health?.failures} in a row)`}>
              {data?.privileged_health?.last_error}
            </AlertBanner>
          )}
        </div>
      )}
      <div className="rh-body">
        {tab === 'progress' ? <InProgress /> : tab === 'shipped' ? <Shipped /> : tab === 'mine' ? <MyPrs /> : <NeedsMe />}
      </div>
      {data && (
        <p className="rh-foot">
          queue updated {data.queue_updated ? relTime(data.queue_updated) : 'never'} &middot; policy v{data.policy.version} &middot;{' '}
          <code>{data.policy.path.replace(/^\/Users\/[^/]+/, '~')}</code>
        </p>
      )}
    </>
  )
}
