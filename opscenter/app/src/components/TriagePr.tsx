// Triage reply for one of my PRs: a verdict and a reason for every blocking and high finding of
// the review on this head. The server posts it as me with the triage marker the own-PR lane
// reads, so a PR held on "no triage reply" (or one auto-fix gave up on) moves without GitHub.
import { Button, cx, Field, Textarea } from '@kit'
import { useState } from 'react'
import type { OlyMyPr, TriageVerdict } from '../lib/data'
import { postplatformTriage } from '../lib/data'
import { ErrorLine } from '../pages/reviews/parts'

const VERDICTS: { v: TriageVerdict; label: string }[] = [
  { v: 'accepted', label: 'Accept the risk' },
  { v: 'refuted', label: 'Refuted' },
  { v: 'fixed', label: 'Fixed on this branch' },
  { v: 'deferred', label: 'Accept for now, follow-up' },
]

export function TriagePr({ p, onDone, onCancel }: { p: OlyMyPr; onDone: (text: string) => void; onCancel: () => void }) {
  const findings = p.findings || []
  const [rows, setRows] = useState<Record<string, { verdict: TriageVerdict | ''; reason: string }>>(() =>
    Object.fromEntries(findings.map((f) => [f.id, { verdict: '', reason: '' }])),
  )
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const ready = findings.every((f) => rows[f.id]?.verdict && rows[f.id].reason.trim().length >= 10)
  const set = (id: string, patch: Partial<{ verdict: TriageVerdict | ''; reason: string }>) =>
    setRows((r) => ({ ...r, [id]: { ...r[id], ...patch } }))
  const submit = async () => {
    setBusy(true)
    setErr(null)
    try {
      const items = findings.map((f) => ({
        id: f.id,
        verdict: rows[f.id].verdict as TriageVerdict,
        reason: rows[f.id].reason,
      }))
      const r = await postplatformTriage(p.pr, p.head_sha, items)
      onDone(r.done.join(', '))
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className="rh-tri-form" aria-label={`Triage findings on PR #${p.pr}`}>
      <p className="rh-tri-head">
        Triage on {p.head_sha.slice(0, 8)}. It posts on the PR as me, and the lane merges once nothing else holds it.
      </p>
      {findings.map((f) => {
        const reason = rows[f.id]?.reason || ''
        return (
          <div key={f.id} className="rh-tri-row">
            <div className="rh-tri-title">
              <b>{f.id}</b> {f.title} <code>{f.location}</code>
            </div>
            <div className="rh-tri-verdicts" role="radiogroup" aria-label={`Verdict for ${f.id}`}>
              {VERDICTS.map((x) => {
                const on = rows[f.id]?.verdict === x.v
                return (
                  <label key={x.v} className={cx('rh-tri-choice', on && 'is-selected')}>
                    <input type="radio" name={`tri-${p.pr}-${f.id}`} checked={on} onChange={() => set(f.id, { verdict: x.v })} />
                    {x.label}
                  </label>
                )
              })}
            </div>
            <Field label="Reason" hint="At least 10 characters">
              <Textarea
                rows={2}
                placeholder="Why, in my words (goes on the PR)"
                value={reason}
                onChange={(e) => set(f.id, { reason: e.target.value })}
              />
            </Field>
          </div>
        )
      })}
      {err && <ErrorLine>{err}</ErrorLine>}
      <div className="rh-tri-btns">
        <Button size="sm" variant="primary" disabled={!ready} loading={busy} onClick={submit}>
          {busy ? 'Posting...' : 'Post triage'}
        </Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </section>
  )
}
