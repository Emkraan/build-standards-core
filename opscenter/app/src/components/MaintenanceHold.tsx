// engineer PRs that take a production system down (an app deploy restarts it, or the
// Terraform plan replaces, deletes or restarts a serving resource) are approved by day but merge only
// inside the maintenance window of their change class (non-CCC or CCC). This file renders the plain
// prose for that hold, the "Waiting for the maintenance window" cards, and the ECR override form.
// Merge now (ECR override) is an emergency change: it needs a reason, is pinned to the held head,
// and the server records who, when and why.
import { Button, Field, Textarea, useConfirm, useToast } from '@kit'
import { useState } from 'react'
import type { OlyHeld, OlyWindow } from '../lib/data'
import { postplatformWindowOverride, relTime, useplatformReviews } from '../lib/data'
import { age, Line, LinkButton, Locked, PrRef, Reasons, ResultNote, ReviewItem, Tag } from '../pages/reviews/parts'
import { confirmText } from './confirmText'

const LABELS: { key: 'down' | 'when' | 'override'; label: string }[] = [
  { key: 'down', label: 'What goes down' },
  { key: 'when', label: 'When it merges' },
  { key: 'override', label: 'What the override does' },
]

export function WindowBrief({ w, pr }: { w: OlyWindow; pr: number }) {
  if (!w.brief) {
    return <Line>I could not work out what this change takes down. Approve treats it as downtime and holds it for a window.</Line>
  }
  const b = w.brief
  return (
    <section className="rh-brief" aria-label={`Maintenance window for PR ${pr}`}>
      {LABELS.map((l) => (
        <div key={l.key}>
          <h4 className="rh-h">{l.label}</h4>
          <p>{b[l.key]}</p>
        </div>
      ))}
    </section>
  )
}

/** The ECR reason box. The reason is required and stored with the override. */
export function EcrForm({ busy, onSubmit, onCancel }: { busy: boolean; onSubmit: (reason: string) => void; onCancel: () => void }) {
  const [reason, setReason] = useState('')
  const ok = reason.trim().length >= 8
  return (
    <div className="rh-rc">
      <Field
        label="ECR reason"
        hint="Why this cannot wait for the window, for example the ECR number and the outage it fixes. Stored with your name and the time."
      >
        <Textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={2}
          maxLength={300}
          placeholder="ECR-1234: intake API returns 500s until this ships"
        />
      </Field>
      <div className="rh-row">
        <Button size="sm" variant="danger" disabled={!ok || busy} loading={busy} onClick={() => onSubmit(reason.trim())}>
          Merge now (ECR override)
        </Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  )
}

export function HeldItem({ it, now }: { it: OlyHeld; now: number }) {
  const { reload, mutate } = useplatformReviews()
  const { toast } = useToast()
  const { confirm: ask, dialog } = useConfirm()
  const [busy, setBusy] = useState(false)
  const [ecr, setEcr] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const locked = it.phase !== 'held'
  const w = it.window
  const held = age(it.held_at, now)
  const submit = async (reason: string) => {
    const ok = await ask({
      ...confirmText(
        `Merge PR #${it.pr} now as an emergency change at ${it.head_sha.slice(0, 8)}?\n\n${w.brief?.down || ''} It merges outside the ${w.class_label} window. Your reason is recorded: ${reason}`,
      ),
      confirmLabel: 'Merge now',
      danger: true,
    })
    if (!ok) return
    setBusy(true)
    setMsg(null)
    try {
      const r = await postplatformWindowOverride(it.pr, it.head_sha, reason)
      mutate((d) => ({
        ...d,
        held_for_window: (d.held_for_window || []).filter((x) => x.pr !== it.pr),
        counts: { ...d.counts, held_for_window: Math.max(0, (d.counts.held_for_window || 0) - 1) },
      }))
      toast('success', `PR #${it.pr}: ${r.done.join(', ')}`)
      setTimeout(reload, 1500)
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusy(false)
    }
  }
  return (
    <ReviewItem
      state="waiting"
      working={locked}
      top={
        <>
          <PrRef href={it.url}>#{it.pr}</PrRef>
          {locked ? (
            <Tag tone="info" live>
              {it.phase === 'gone' ? 'clearing' : 'new push, re-reviewing'}
            </Tag>
          ) : w.in_window ? (
            <Tag tone="info" live>
              {w.class_label} window open, merging
            </Tag>
          ) : (
            <Tag tone="warn">waits for the {w.class_label} window</Tag>
          )}
          {w.stale && <Tag tone="alert">still held after a full window</Tag>}
          <Tag tone="neutral">approved {held.text} ago</Tag>
        </>
      }
      title={it.title}
      meta={
        <>
          {it.author} &middot; approved by {it.approved_by === 'github_user' ? 'me' : 'the review lane'} at {it.head_sha.slice(0, 8)}, the head
          that merges
        </>
      }
      actions={
        locked ? (
          <>
            <Locked />
            <LinkButton href={it.url}>Open PR</LinkButton>
          </>
        ) : (
          <>
            {!ecr && (
              <Button size="sm" variant="secondary" onClick={() => setEcr(true)}>
                Merge now (ECR override)
              </Button>
            )}
            <LinkButton href={it.url}>Open PR</LinkButton>
          </>
        )
      }
    >
      {dialog}
      {it.note && <Line>{it.note}</Line>}
      <WindowBrief w={w} pr={it.pr} />
      <details className="rh-details">
        <summary>Details: what the check found, last re-check, PR comment</summary>
        <div className="rh-details-body">
          <Reasons
            tone="neutral"
            items={it.hits.map((h) => (
              <>
                {h.reason} {h.where && <code>{h.where}</code>}
              </>
            ))}
          />
          {it.last_check && (
            <Line>
              Last re-check inside the window{it.last_check_at ? ` (${relTime(it.last_check_at)})` : ''} found it not ready yet:{' '}
              {it.last_check}
            </Line>
          )}
          <Line>
            {it.comment_posted_at
              ? `The PR comment telling the author when it merges went up ${relTime(it.comment_posted_at)}.`
              : 'The PR comment telling the author when it merges did not post. The approval stands.'}
          </Line>
        </div>
      </details>
      {ecr && !locked && <EcrForm busy={busy} onSubmit={submit} onCancel={() => setEcr(false)} />}
      <ResultNote msg={msg} />
    </ReviewItem>
  )
}
