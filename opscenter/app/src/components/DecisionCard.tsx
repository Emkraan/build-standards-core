// Decision card for one of my PRs (pipeline v2, ). The fix session stopped on a choice only
// I can make and left a question, two to four options and its recommendation. Each option is one
// button. My click is the sign-off for this head only: "fix" starts a directed fix session, "override"
// applies the override label and posts the prepared triage reply as me, "hold" adds do-not-merge.
import { Button, useConfirm } from '@kit'
import { useState } from 'react'
import type { OwnDecision } from '../lib/data'
import { postAresDecideFix, postplatformDecideFix } from '../lib/data'
import { ErrorLine, Tag } from '../pages/reviews/parts'
import { confirmText } from './confirmText'

const VERB: Record<OwnDecision['options'][number]['action'], string> = {
  fix: 'A fix session makes this change on the branch.',
  override: 'Applies the override label and posts this reply on the PR as you.',
  hold: 'Adds do-not-merge. Nothing else changes.',
}

export function DecisionCard({
  p,
  decision,
  repo = 'platform',
  onDone,
}: {
  p: { pr: number; head_sha: string }
  decision: OwnDecision
  repo?: 'platform' | 'team'
  onDone: (text: string) => void
}) {
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const { confirm: ask, dialog } = useConfirm()
  const pick = async (id: string) => {
    const o = decision.options.find((x) => x.id === id)
    if (!o) return
    const body = [VERB[o.action], o.effect, o.reply ? `Reply:\n${o.reply}` : ''].filter(Boolean).join('\n\n')
    const ok = await ask({
      ...confirmText(`${o.label} on PR #${p.pr} at ${p.head_sha.slice(0, 8)}?\n\n${body}`),
      confirmLabel: o.label,
      danger: o.action === 'override',
    })
    if (!ok) return
    setBusy(id)
    setErr(null)
    try {
      const r = await (repo === 'team' ? postAresDecideFix : postplatformDecideFix)(p.pr, p.head_sha, id)
      onDone(r.done.join(', '))
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }
  return (
    <section className="rh-tri-form" aria-label={`Decision on PR #${p.pr}`}>
      {dialog}
      <p className="rh-tri-head">
        <b>{decision.question}</b>
      </p>
      {decision.options.map((o) => (
        <div key={o.id} className="rh-tri-row">
          <div className="rh-tri-title">
            <b>{o.id}</b> {o.label} {o.id === decision.recommend && <Tag tone="good">recommended</Tag>}
          </div>
          {o.effect && <p className="rh-line">{o.effect}</p>}
          <div className="rh-tri-btns">
            <Button
              size="sm"
              variant={o.id === decision.recommend ? 'primary' : 'ghost'}
              loading={busy === o.id}
              disabled={busy !== null}
              onClick={() => pick(o.id)}
            >
              {busy === o.id ? 'Working...' : o.label}
            </Button>
          </div>
        </div>
      ))}
      {err && <ErrorLine>{err}</ErrorLine>}
    </section>
  )
}
