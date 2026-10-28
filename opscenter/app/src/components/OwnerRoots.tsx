// Owner-applied platform roots (pipeline-identities, state-backend). No pipeline identity
// can apply them, so a pending plan, a failed run, or an expired sign-in is my action. Apply runs
// the exact saved plan shown here as owner_admin_account, then re-plans to prove it landed.
// 2026-10-15: the card opens with the approval brief (what this is, what the click does, risks and
// my recommendation), the visible meta line explains every datum in words, and the plan counts and
// resource list sit in Details. When an open PR changes the same root, the brief warns that
// applying from main would undo or pre-empt it and Apply is de-emphasised (never removed).
// Sign in to Azure runs one prompt at a time and re-plans by itself once it lands, and the
// card shows that sign-in (open, signed in and re-planning, or how it failed) instead of the old error.
import { Button, Field, Input } from '@kit'
import { useState } from 'react'
import type { OwnerRoot, OwnerSignin } from '../lib/data'
import { postOwnerRoot, relTime, useplatformReviews, useVisibleInterval } from '../lib/data'
import { ErrorLine, Line, Locked, ResultNote, ReviewItem, Tag } from '../pages/reviews/parts'
import { ApprovalBriefView } from './ApprovalBrief'

const ACT_CLASS: Record<string, string> = {
  add: 'create',
  change: 'update',
  destroy: 'delete',
  replace: 'replace',
  import: 'update',
}

// While a root re-plans or applies, poll every 10 s so the card returns the moment it is actionable.
export function OwnerFlightPoll() {
  const { reload } = useplatformReviews()
  useVisibleInterval(reload, 10_000)
  return null
}

const TIER: Record<string, string> = { dev_tier: 'dev tier', platform: 'production tier' }

export function OwnerRootItem({
  it,
  running,
  liveMain,
  signin,
  now,
}: {
  it: OwnerRoot
  running: boolean
  liveMain: string | null
  signin?: OwnerSignin | null
  now: number
}) {
  const { reload } = useplatformReviews()
  // Server truth: only a needs_me card can act. Main moved or a plan running = locked, no buttons.
  const locked = running || it.phase === 'in_flight'
  const moved = !!it.main_moved
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const c = it.counts
  const destroys = (it.resources || []).filter((r) => r.action === 'destroy' || r.action === 'replace')
  const waitFor = it.brief?.wait_for || []
  const unchecked = !!it.brief?.overlap_status && it.brief.overlap_status !== 'ok'
  const act = async (a: 'plan' | 'apply' | 'signin', body: Record<string, string> = {}) => {
    setBusy(true)
    setMsg(null)
    try {
      const r = await postOwnerRoot(a, body)
      setMsg({ ok: true, text: r.done.join(', ') })
      setConfirm('')
      setTimeout(reload, 2000)
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusy(false)
    }
  }
  const since = it.pending_since ? new Date(it.pending_since).getTime() : 0
  const old = since && now - since > 2 * 3600_000
  const label = moved
    ? 'main moved, re-planning'
    : it.state === 'applying'
      ? 'applying'
      : it.state === 'planning'
        ? 're-planning'
        : it.state === 'pending'
          ? 'owner apply waiting'
          : it.state === 'auth'
            ? 'sign-in needed'
            : it.state === 'error'
              ? it.last_apply_error
                ? 'Apply failed'
                : 'Plan failed'
              : it.state
  const tone = it.state === 'pending' ? 'warn' : 'alert'
  // A failed apply stays on the card across the re-plans that follow it, until an apply lands.
  const applyErr = it.last_apply_error
  const showApplyErr = !!applyErr && it.state !== 'applying' && it.state !== 'planning'
  const locksOut = !!applyErr && applyErr.message.startsWith('LOCKS NOT RESTORED')
  const sha = it.main_sha ? it.main_sha.slice(0, 8) : ''
  // The shared sign-in, shown on cards that need it. A failure only counts when it is newer than this card's last plan.
  const signinOpen = it.state === 'auth' && signin?.state === 'waiting'
  const signinReplan = signin?.state === 'replanning'
  const signinFailed =
    it.state === 'auth' &&
    signin?.state === 'failed' &&
    !!signin.finished &&
    (!it.finished || new Date(signin.finished).getTime() >= new Date(it.finished).getTime())
  // The raw plan data. Under a brief it sits in the collapsed Details, every line is explained above.
  const details =
    it.state === 'pending' && c ? (
      <>
        <div className="rh-plan">
          Plan counts: {c.add} to add, {c.change} to change, {c.destroy} to destroy
          {c.replace ? `, ${c.replace} to replace` : ''}
          {c.import ? `, ${c.import} to import` : ''}. Plan file fingerprint <code>{(it.plan_sha256 || '').slice(0, 16)}</code>, made from
          main commit <code>{it.main_sha}</code>.
        </div>
        <ul className="rh-res">
          {(it.resources || []).map((r) => (
            <li key={r.address} data-act={ACT_CLASS[r.action] || 'update'}>
              <span className="rh-act">{r.action}</span> <code>{r.address}</code>
            </li>
          ))}
        </ul>
      </>
    ) : null
  return (
    <ReviewItem
      pulse={it}
      state="needs_you"
      working={locked}
      top={
        <>
          <Tag tone={tone}>{label}</Tag>
          {showApplyErr && it.state === 'pending' && <Tag tone="alert">Apply failed</Tag>}
          {showApplyErr && locksOut && <Tag tone="alert">Locks not restored</Tag>}
          <Tag tone="info">Owner apply</Tag>
          {waitFor.map((w) => (
            <Tag key={w.number} tone="alert">
              wait for #{w.number}
            </Tag>
          ))}
          {destroys.length > 0 && <Tag tone="alert">{destroys.length} delete</Tag>}
          {it.stale && <Tag tone="warn">plan over a day old</Tag>}
          {signinOpen && !locked && (
            <Tag tone="info" live>
              waiting for your sign-in
            </Tag>
          )}
          {locked && (
            <Tag tone="info" live>
              {it.state === 'applying' ? 'applying' : 're-planning'}
            </Tag>
          )}
        </>
      }
      title={
        <>
          {it.name} ({it.tier}
          {TIER[it.tier] ? `, our ${TIER[it.tier]}` : ''})
        </>
      }
      meta={
        <>
          A Terraform root only a subscription Owner applies, from a plan I save, never from GitHub Actions.
          {sha && (
            <>
              {' '}
              The plan was made {it.planned_at ? relTime(it.planned_at) : 'at an unknown time'} from{' '}
              {moved ? 'an older' : it.main_latest ? 'the latest' : 'a'} main commit, {sha}
              {it.main_subject ? ` (${it.main_subject})` : ''}
              {moved && liveMain ? `, and main is now at ${liveMain.slice(0, 8)}` : ''}.
            </>
          )}
          {it.pending_since && (
            <>
              {' '}
              <span className={old ? 'rh-bad' : ''}>
                Changes on this root have waited to be applied since {relTime(it.pending_since)}, across re-plans.
              </span>
            </>
          )}
        </>
      }
      actions={
        locked ? (
          <Locked />
        ) : (
          <>
            {it.state === 'pending' && (
              <Button
                size="sm"
                // An open PR on this root, or an unfinished check, makes Apply the wrong default.
                variant={waitFor.length || unchecked ? 'secondary' : 'primary'}
                disabled={confirm.trim() !== it.name || !!it.stale}
                loading={busy}
                onClick={() =>
                  act('apply', {
                    name: it.name,
                    tier: it.tier,
                    plan_sha256: it.plan_sha256 || '',
                    confirm,
                  })
                }
              >
                {busy ? 'Working...' : 'Apply as owner_admin_account'}
              </Button>
            )}
            {it.state === 'auth' && (
              <Button size="sm" variant={signinOpen ? 'secondary' : 'primary'} loading={busy} onClick={() => act('signin')}>
                {signinOpen ? 'Open a fresh sign-in' : 'Sign in to Azure'}
              </Button>
            )}
            <Button size="sm" disabled={busy} onClick={() => act('plan', { name: it.name, tier: it.tier })}>
              Re-plan
            </Button>
          </>
        )
      }
    >
      {it.brief ? (
        <ApprovalBriefView
          repo="platform"
          card={`owner:${it.name}:${it.tier}`}
          brief={it.brief}
          reload={reload}
          detailsLabel="Details: plan counts, plan fingerprint and the raw resource list"
        >
          {details}
        </ApprovalBriefView>
      ) : (
        details
      )}
      {it.error && !signinOpen && !signinReplan && <ErrorLine>{it.error}</ErrorLine>}
      {showApplyErr && applyErr && it.error !== applyErr.message && (
        <ErrorLine>
          The last apply of this root failed {relTime(applyErr.at)}: {applyErr.message}
          {it.state === 'pending' && ' The plan above is a fresh one made after that failure, read the error before applying it.'}
        </ErrorLine>
      )}
      {signinOpen && (
        <Line>
          The Azure sign-in is open in the browser{signin?.started ? ` (opened ${relTime(signin.started)})` : ''}. Sign in as owner_admin_account and
          I re-plan every Owner root by myself once it lands. Open a fresh sign-in closes that prompt and opens a new one.
        </Line>
      )}
      {signinReplan && <Line>You are signed in as {signin?.user || 'owner_admin_account'}, and I am re-planning every Owner root now.</Line>}
      {signinFailed && signin?.error && <ErrorLine>The last sign-in did not land: {signin.error}</ErrorLine>}
      {it.state === 'auth' && !signinOpen && !signinFailed && (
        <Line>Sign in opens the Azure prompt in the browser. Sign in as owner_admin_account, and the re-plan starts by itself once it lands.</Line>
      )}
      {it.last_apply && (
        <Line>
          The last apply of this root ran {relTime(it.last_apply.at)} and Terraform reported: {it.last_apply.result}
          {it.last_apply.verified === true && ' The re-plan right after came back clean, so it landed.'}
          {it.last_apply.verified === false && ' The re-plan right after still showed changes.'}
        </Line>
      )}
      {moved && <Line>Main moved since this plan, so I am re-planning it from the new main. Apply returns when the fresh plan lands.</Line>}
      {it.state === 'pending' && !locked && (
        <div className="rh-confirm">
          {waitFor.length > 0 && (
            <p className="rh-apply-warn" role="note">
              Not recommended now. Open PR {waitFor.map((w) => `#${w.number}`).join(', ')} changes this root, so applying from main would
              undo or pre-empt it. Wait for it to merge.
            </p>
          )}
          {!waitFor.length && unchecked && (
            <p className="rh-apply-warn" role="note">
              Not recommended until the open PR check on this root finishes.
            </p>
          )}
          <Field
            label={`Type ${it.name} to confirm`}
            hint="Apply runs exactly this saved plan as owner_admin_account, then re-plans to verify it landed."
          >
            <Input
              className="rh-confirm-input"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              placeholder={it.name}
              spellCheck={false}
              autoComplete="off"
            />
          </Field>
        </div>
      )}
      <ResultNote msg={msg} />
    </ReviewItem>
  )
}
