// runbook-root deletes I approved with Approve and merge. The runbooks root is applied by
// deploy-automation-runbooks, so its push run on main stops on the destroy guard. Release deletes
// re-checks that run live and dispatches allow_destroy=true on main. prod has no reviewers, so the
// click is the sign-off and the run applies at once.
import { Button, useConfirm } from '@kit'
import { useState } from 'react'
import type { RunbookRelease } from '../lib/data'
import { postRunbookRelease, relTime, useplatformReviews } from '../lib/data'
import type { Tone } from '../pages/reviews/parts'
import { ErrorLine, LinkButton, Locked, PrRef, ResultNote, ReviewItem, Tag } from '../pages/reviews/parts'
import { ApprovalBriefView } from './ApprovalBrief'
import { confirmText } from './confirmText'
import { DiscussPr } from './DiscussPr'

const LABEL: Record<string, { text: string; tone: Tone }> = {
  ready: { text: 'deletes waiting on me', tone: 'warn' },
  waiting: { text: 'main deploy running', tone: 'info' },
  releasing: { text: 'releasing', tone: 'info' },
  released: { text: 'released', tone: 'good' },
  done: { text: 'nothing left', tone: 'good' },
  mismatch: { text: 'plan does not match', tone: 'alert' },
  error: { text: 'approved set unknown', tone: 'alert' },
  failed: { text: 'release failed', tone: 'alert' },
  unknown: { text: 'status unknown', tone: 'warn' },
}

export const releaseWorking = (r: RunbookRelease) => r.state === 'waiting' || r.state === 'releasing'

export function needsRelease(r: RunbookRelease): boolean {
  if (['ready', 'mismatch', 'error', 'failed'].includes(r.state)) return true
  return r.state === 'released' && ((r.extra?.length ?? 0) > 0 || (r.missing?.length ?? 0) > 0)
}

export function RunbookReleaseItem({ it }: { it: RunbookRelease }) {
  const { reload } = useplatformReviews()
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const { confirm: ask, dialog } = useConfirm()
  const lab = LABEL[it.state] || { text: it.state, tone: 'neutral' as Tone }
  const working = releaseWorking(it)
  const n = it.approved?.length ?? 0
  const approvedList =
    (it.approved || []).length > 0 ? (
      <ul className="rh-res">
        {(it.approved || []).map((a) => (
          <li key={a} data-act="delete">
            <span className="rh-act">destroy</span> <code>{a}</code>
          </li>
        ))}
      </ul>
    ) : null
  const release = async () => {
    if (!it.run) return
    const ok = await ask({
      ...confirmText(
        `Delete ${n} runbook(s) from prod_prefix-automation-aa now? This starts deploy-automation-runbooks on main with allow_destroy. ` +
          'The prod environment has no approval step, so it applies right away.',
      ),
      confirmLabel: 'Release deletes',
      danger: true,
    })
    if (!ok) return
    setBusy(true)
    setMsg(null)
    try {
      const r = await postRunbookRelease(it.pr, it.run.id)
      setMsg({ ok: true, text: r.done.join(', ') })
      setTimeout(reload, 2000)
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusy(false)
    }
  }
  return (
    <ReviewItem
      pulse={it}
      state={needsRelease(it) ? 'needs_you' : 'waiting'}
      working={working}
      top={
        <>
          <Tag tone={lab.tone} live={working}>
            {lab.text}
          </Tag>
          <Tag tone="info">Runbook deletes</Tag>
          {(it.brief?.wait_for || []).map((w) => (
            <Tag key={w.number} tone="alert">
              wait for #{w.number}
            </Tag>
          ))}
          {n > 0 && <Tag tone="alert">{n} delete</Tag>}
          <PrRef href={it.url}>#{it.pr}</PrRef>
        </>
      }
      title={it.title}
      meta={
        <>
          Runbook deletes in the runbooks Terraform root ({it.tier}) that you approved {relTime(it.approved_at)} when you merged this PR.
          {it.why && <> Right now: {it.why}.</>}
          {it.run && (
            <>
              {' '}
              The{' '}
              <a href={it.run.url} target="_blank" rel="noreferrer">
                {it.run.event === 'workflow_dispatch' ? 'release run' : 'latest deploy run on main'}
              </a>{' '}
              {it.run.status === 'completed' ? `finished as ${it.run.conclusion}` : `is ${it.run.status}`}.
            </>
          )}
        </>
      }
      actions={
        <>
          {working ? (
            <Locked />
          ) : (
            it.state === 'ready' && (
              <Button size="sm" variant="danger" loading={busy} onClick={release}>
                {busy ? 'Working...' : 'Release deletes'}
              </Button>
            )
          )}
          {/* A card on Needs me always carries a way forward: no release button means discuss it. */}
          {!working && it.state !== 'ready' && needsRelease(it) && <DiscussPr repo="platform" pr={it.pr} />}
          {it.run && <LinkButton href={it.run.url}>Open run</LinkButton>}
        </>
      }
    >
      {dialog}
      {it.brief ? (
        <ApprovalBriefView
          repo="platform"
          card={`release:${it.pr}`}
          brief={it.brief}
          reload={reload}
          detailsLabel="Details: the approved delete list as Terraform addresses"
        >
          {approvedList}
        </ApprovalBriefView>
      ) : (
        approvedList
      )}
      {(it.extra?.length ?? 0) > 0 && <ErrorLine>Not in what I approved: {it.extra?.join(', ')}</ErrorLine>}
      {(it.missing?.length ?? 0) > 0 && <ErrorLine>Approved but not in the plan: {it.missing?.join(', ')}</ErrorLine>}
      {(it.errors || []).map((e) => (
        <ErrorLine key={e}>{e}</ErrorLine>
      ))}
      <ResultNote msg={msg} />
    </ReviewItem>
  )
}
