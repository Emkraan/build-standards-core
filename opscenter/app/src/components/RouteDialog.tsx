/*
 * RouteDialog - "Route elsewhere" on an Action Center item.
 *
 *
 * My click becomes a routing rule in ac-routing.json, so a "this does not belong on my board"
 * call never needs a prompt or code edit. I pick what to route (this item, every ask from the
 * same person, anything on the same ticket, or anything mentioning a phrase), where it goes
 * (owned elsewhere, with a where, or dropped), and see a live preview of what else the rule
 * would catch before it applies. A rule is reversible (disable on the Routing tab, or Undo on
 * the toast), so it applies at once instead of asking are-you-sure.
 */

import type { SegmentedOption } from '@kit'
import { Field, Input, Modal, Segmented, Select, Textarea } from '@kit'
import { useEffect, useMemo, useState } from 'react'
import type { AcMatch, AcPreview, AcRoute, AcRule, AcScope } from '../lib/data'
import { postAcPreview, postAcRule } from '../lib/data'
import type { ActionItem } from './ActionTable'

type Dest = 'elsewhere' | 'nowhere'
interface Scope {
  id: string
  label: string
  match: AcMatch
  scope: AcScope
}

const DESTS: SegmentedOption<Dest>[] = [
  { value: 'elsewhere', label: 'Lives elsewhere', tip: 'Another surface or person owns it. Say where.' },
  { value: 'nowhere', label: 'Drop it', tip: 'Never show it anywhere.' },
]

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

function scopesFor(it: ActionItem, phrase: string): Scope[] {
  const out: Scope[] = []
  if (it.key) out.push({ id: 'item', label: 'This item only', match: { key: it.key }, scope: 'items' })
  const ask = /^ask-([a-z]+)-/.exec(it.key || '')
  if (ask) {
    const first = ask[1].charAt(0).toUpperCase() + ask[1].slice(1)
    out.push({ id: 'person', label: `Every ask from ${first}`, match: { key_prefix: `ask-${ask[1]}-` }, scope: 'items' })
  }
  const ref = (it.refs || [])[0]
  if (ref) out.push({ id: 'ref', label: `Anything about ${ref}`, match: { refs: [ref] }, scope: 'all' })
  const p = phrase.trim()
  out.push({
    id: 'phrase',
    label: p ? `Anything mentioning "${p}"` : 'Anything mentioning a phrase',
    match: p ? { text: `\\b${escapeRe(p)}\\b`, fields: ['key', 'title', 'action'] } : {},
    scope: 'all',
  })
  return out
}

export default function RouteDialog({
  item,
  onClose,
  onRouted,
}: {
  item: ActionItem | null
  onClose: () => void
  onRouted: (item: ActionItem, rule: AcRule) => void
}) {
  const [dest, setDest] = useState<Dest>('elsewhere')
  const [where, setWhere] = useState('')
  const [reason, setReason] = useState('')
  const [phrase, setPhrase] = useState('')
  const [scopeId, setScopeId] = useState('item')
  const [pv, setPv] = useState<AcPreview | null>(null)
  const [pvErr, setPvErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  // Reset only when a different item opens, not when the same item's fields re-render.
  // biome-ignore lint/correctness/useExhaustiveDependencies: keyed on the item fingerprint on purpose
  useEffect(() => {
    setDest('elsewhere')
    setWhere(item?.owner ? `${item.owner} owns it` : '')
    setReason('')
    setPhrase('')
    setScopeId(item?.key ? 'item' : 'phrase')
    setPv(null)
    setErr('')
  }, [item?.fp])

  const scopes = useMemo(() => (item ? scopesFor(item, phrase) : []), [item, phrase])
  const chosen = scopes.find((s) => s.id === scopeId) || scopes[0]
  const ready = !!chosen && Object.keys(chosen.match).length > 0 && (dest === 'nowhere' || where.trim().length > 0)
  const route: AcRoute = dest

  // Live preview, debounced, so I see what else the rule would catch before it applies.
  useEffect(() => {
    if (!item || !chosen || !Object.keys(chosen.match).length) {
      setPv(null)
      return
    }
    let alive = true
    const t = setTimeout(() => {
      postAcPreview(chosen.match, route, chosen.scope)
        .then((r) => {
          if (alive) {
            setPv(r)
            setPvErr('')
          }
        })
        .catch((e: Error) => alive && setPvErr(e.message))
    }, 300)
    return () => {
      alive = false
      clearTimeout(t)
    }
  }, [item, chosen, route])

  const submit = () => {
    if (!item || !chosen || !ready) return
    setBusy(true)
    setErr('')
    postAcRule({ match: chosen.match, route, where: dest === 'elsewhere' ? where : '', reason, scope: chosen.scope, from_fp: item.fp })
      .then((r) => {
        setBusy(false)
        onRouted(item, r.rule)
      })
      .catch((e: Error) => {
        setBusy(false)
        setErr(e.message)
      })
  }

  const others = pv ? pv.items.filter((i) => i.key !== item?.key) : []
  return (
    <Modal
      open={!!item}
      onClose={onClose}
      size="md"
      busy={busy}
      title="Route elsewhere"
      subtitle={item?.title}
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
      primaryAction={{ label: 'Route', loading: busy, disabled: !ready }}
    >
      <Field label="Where it belongs">
        <Segmented label="Where it belongs" options={DESTS} value={dest} onChange={setDest} />
      </Field>
      {dest === 'elsewhere' && (
        <Field
          label="Where it lives or who owns it"
          required
          hint="Shown on the Routing tab, for example: person owns it, Grafana app_e dashboards."
        >
          <Input value={where} onChange={(e) => setWhere(e.target.value)} data-autofocus />
        </Field>
      )}
      <Field label="What to route">
        <Select
          value={chosen?.id || ''}
          onChange={(e) => setScopeId(e.target.value)}
          options={scopes.map((s) => ({ value: s.id, label: s.label }))}
        />
      </Field>
      {chosen?.id === 'phrase' && (
        <Field label="Phrase" hint="Whole words, matched in an item's key, title and action, and in inbound subjects.">
          <Input value={phrase} onChange={(e) => setPhrase(e.target.value)} />
        </Field>
      )}
      <Field label="Why" optional>
        <Textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
      <div className="rt-preview" aria-live="polite">
        {pvErr && <p className="at-m-hint err">Preview failed: {pvErr}</p>}
        {pv && (
          <>
            <p className="at-m-hint">
              {others.length
                ? `Also routes ${others.length} other current item${others.length === 1 ? '' : 's'}`
                : 'No other current items'}
              {chosen?.scope !== 'items' ? `, and ${pv.candidate_count} recent inbound item${pv.candidate_count === 1 ? '' : 's'}.` : '.'}
            </p>
            {(others.length > 0 || (chosen?.scope !== 'items' && pv.candidates.length > 0)) && (
              <ul className="rt-list">
                {others.slice(0, 5).map((i) => (
                  <li key={i.key}>{i.title}</li>
                ))}
                {chosen?.scope !== 'items' &&
                  pv.candidates.slice(0, 5).map((c) => (
                    <li key={c.cid}>
                      {c.title} <span className="muted">({c.source})</span>
                    </li>
                  ))}
              </ul>
            )}
          </>
        )}
      </div>
      {err && <p className="at-m-hint err">{err}</p>}
    </Modal>
  )
}
