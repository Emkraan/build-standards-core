/*
 * ActionRouting - the Action Center Routing tab.
 *
 *
 * Shows what decides my board, as data: the routing rules in ac-routing.json (seed rules
 * migrated from the old prompt, plus every rule my "Route elsewhere" clicks created), what the
 * collector considered this run and what became of each (item, dropped with a reason, or still
 * open), and what the rules routed away and where. Nothing reaches or leaves the board without
 * showing up here.
 */

import type { SegmentedOption, TableColumn } from '@kit'
import { Button, Card, CardHead, EmptyState, IconButton, IconRefresh, Pill, Segmented, Table, Toolbar, useConfirm, useToast } from '@kit'
import { useState } from 'react'
import { LoadError } from '../components/StateBlocks'
import type { AcAway, AcMatch, AcRule } from '../lib/data'
import { postAcDelete, postAcDisable, useAcRouting, useData } from '../lib/data'
import './ActionRouting.css'

interface AcFile {
  items?: { key?: string; title: string; cids?: string[] }[]
  dropped?: { cid: string; reason: string }[]
}

const ROUTE_LABEL: Record<string, string> = {
  action_center: 'Must consider',
  analysis: 'Context',
  elsewhere: 'Elsewhere',
  nowhere: 'Dropped',
}

function matchText(m: AcMatch): string {
  const parts: string[] = []
  if (m.source) parts.push(`source ${m.source}`)
  if (m.actor) parts.push(`from ${m.actor}`)
  if (m.actor_role) parts.push(`role ${m.actor_role}`)
  if (m.key) parts.push(`item ${m.key}`)
  if (m.key_prefix) parts.push(`key starts ${m.key_prefix}`)
  if (m.ref_prefix) parts.push(`ticket starts ${m.ref_prefix}`)
  if (m.refs?.length) parts.push(`about ${m.refs.join(', ')}`)
  if (m.owner) parts.push(`owner ${m.owner}`)
  if (m.sources_any?.length) parts.push(`source label ${m.sources_any.join(', ')}`)
  if (m.text) parts.push(`mentions /${m.text}/`)
  return parts.join(' and ')
}

type View = 'considered' | 'away' | 'rules'

export default function ActionRouting() {
  const { data, error, reload, mutate } = useAcRouting()
  const { data: ac } = useData<AcFile>('action-center.json')
  const { confirm, dialog } = useConfirm()
  const { toast } = useToast()
  const [view, setView] = useState<View>('considered')
  const [busy, setBusy] = useState('')

  if (error && !data) return <LoadError title="Could not load routing" error={error} />
  if (!data) return <EmptyState compact title="Loading routing..." />

  const rep = data.report || {}
  const considered = rep.considered_list || []
  const dropped = new Map((ac?.dropped || []).map((d) => [d.cid, d.reason]))
  const itemByCid = new Map<string, string>()
  for (const it of ac?.items || []) for (const c of it.cids || []) itemByCid.set(c, it.title)
  const away: AcAway[] = [...(rep.items_routed_away || []), ...(rep.routed_away || [])]
  const active = data.rules.filter((r) => !r.disabled).length

  const toggle = (r: AcRule, disabled: boolean) => {
    setBusy(r.id)
    postAcDisable(r.id, disabled)
      .then(() => {
        mutate((d) => ({
          ...d,
          rules: d.rules.map((x) => (x.id === r.id ? { ...x, disabled: disabled ? new Date().toISOString() : undefined } : x)),
        }))
        toast('success', disabled ? 'Rule disabled' : 'Rule enabled', {
          description: matchText(r.match),
          action: { label: 'Undo', onClick: () => toggle(r, !disabled) },
        })
      })
      .catch((e: Error) => toast('error', 'Could not change the rule', { description: e.message }))
      .finally(() => setBusy(''))
  }
  const remove = async (r: AcRule) => {
    const ok = await confirm({
      title: 'Delete this routing rule?',
      body: `${matchText(r.match)}. Items it routed come back to the board on the next refresh. Disable keeps it for later instead.`,
      confirmLabel: 'Delete',
      danger: true,
    })
    if (!ok) return
    setBusy(r.id)
    postAcDelete(r.id)
      .then(() => {
        mutate((d) => ({ ...d, rules: d.rules.filter((x) => x.id !== r.id) }))
        toast('success', 'Rule deleted', { description: matchText(r.match) })
      })
      .catch((e: Error) => toast('error', 'Could not delete the rule', { description: e.message }))
      .finally(() => setBusy(''))
  }

  const ruleCols: TableColumn<AcRule>[] = [
    {
      key: 'match',
      header: 'When',
      value: (r) => matchText(r.match),
      render: (r) => (
        <span className="ar-rule">
          <span>{matchText(r.match)}</span>
          {r.reason && <span className="ar-faint">{r.reason}</span>}
        </span>
      ),
    },
    {
      key: 'route',
      header: 'Goes to',
      width: '260px',
      value: (r) => `${r.route} ${r.where || ''}`,
      render: (r) => (
        <span className="ar-rule">
          <span>{ROUTE_LABEL[r.route] || r.route}</span>
          {r.where && <span className="ar-faint">{r.where}</span>}
        </span>
      ),
    },
    {
      key: 'origin',
      header: 'From',
      width: '110px',
      value: (r) => r.origin,
      render: (r) => <Pill tone={r.origin === 'click' ? 'info' : 'neutral'}>{r.origin === 'click' ? 'my click' : 'migrated'}</Pill>,
    },
    { key: 'hits', header: 'This run', width: '90px', value: (r) => r.hits, render: (r) => (r.disabled ? 'off' : r.hits) },
    {
      key: 'act',
      header: '',
      width: '170px',
      value: () => 0,
      render: (r) => (
        <span className="ar-acts">
          <Button size="sm" variant="ghost" loading={busy === r.id} onClick={() => toggle(r, !r.disabled)}>
            {r.disabled ? 'Enable' : 'Disable'}
          </Button>
          {r.origin === 'click' && (
            <Button size="sm" variant="ghost" onClick={() => remove(r)}>
              Delete
            </Button>
          )}
        </span>
      ),
    },
  ]

  type CRow = (typeof considered)[number] & { fate: string; tone: 'success' | 'neutral' | 'warning' }
  const cRows: CRow[] = considered.map((c) => {
    const it = itemByCid.get(c.cid)
    const dr = dropped.get(c.cid)
    if (it) return { ...c, fate: `Item: ${it}`, tone: 'success' }
    if (dr) return { ...c, fate: `Dropped: ${dr}`, tone: 'neutral' }
    return { ...c, fate: 'Not accounted for by the last analysis', tone: 'warning' }
  })
  const consideredCols: TableColumn<CRow>[] = [
    {
      key: 'title',
      header: 'Input',
      value: (c) => `${c.title} ${c.actor || ''}`,
      render: (c) => (
        <span className="ar-rule">
          {c.link ? (
            <a href={c.link} target="_blank" rel="noreferrer">
              {c.title}
            </a>
          ) : (
            <span>{c.title}</span>
          )}
          <span className="ar-faint">
            {c.source}
            {c.actor ? ` \u00b7 ${c.actor}` : ''}
          </span>
        </span>
      ),
    },
    { key: 'fate', header: 'What happened', value: (c) => c.fate, render: (c) => <Pill tone={c.tone}>{c.fate}</Pill> },
  ]
  const awayCols: TableColumn<AcAway>[] = [
    {
      key: 'title',
      header: 'Item or input',
      value: (a) => a.title || '',
      render: (a) => (
        <span className="ar-rule">
          <span>{a.title}</span>
          <span className="ar-faint">{a.key ? `board item ${a.key}` : `${a.source || ''}${a.actor ? ` \u00b7 ${a.actor}` : ''}`}</span>
        </span>
      ),
    },
    { key: 'where', header: 'Went to', width: '280px', value: (a) => a.where || a.route, render: (a) => a.where || ROUTE_LABEL[a.route] },
    { key: 'rule', header: 'Rule', width: '200px', value: (a) => a.rule, render: (a) => <code>{a.rule}</code> },
  ]

  const unaccounted = cRows.filter((c) => c.tone === 'warning').length
  const views: SegmentedOption<View>[] = [
    { value: 'considered', label: 'Considered', badge: considered.length, tone: unaccounted ? 'warning' : undefined },
    { value: 'away', label: 'Routed away', badge: away.length },
    { value: 'rules', label: 'Rules', badge: active },
  ]

  return (
    <>
      <Card>
        <CardHead
          title="Routing"
          subtitle={`What decides my board. ${active} rules in force, ${Object.keys(data.sources).length} sources registered${rep.generated_utc ? `, collected ${rep.generated_utc.slice(11, 16)}Z` : ''}.`}
        />
        {Boolean(data.error || rep.errors?.length || rep.unregistered?.length) && (
          <div className="ar-banner tone hue-amber" role="status">
            {data.error && <div>Routing file problem: {data.error}. Every item stays visible until it is fixed.</div>}
            {rep.errors?.map((e) => (
              <div key={e}>Collector: {e}</div>
            ))}
            {rep.unregistered?.length ? (
              <div>Sources not registered yet: {rep.unregistered.join(', ')}. They still show by the defaults.</div>
            ) : null}
          </div>
        )}
        <Toolbar label="Routing view">
          <IconButton size="sm" label="Refresh" icon={<IconRefresh />} onClick={reload} />
          <Segmented label="Routing view" options={views} value={view} onChange={setView} />
        </Toolbar>
        {view === 'considered' && (
          <Table
            caption="Inputs the collector said I must consider, and what became of each"
            columns={consideredCols}
            rows={cRows}
            rowKey={(c) => c.cid}
            defaultSort={null}
            empty={<EmptyState compact title="Nothing addressed to me in the last three days." />}
          />
        )}
        {view === 'away' && (
          <Table
            caption="Items and inputs my routing rules sent elsewhere"
            columns={awayCols}
            rows={away}
            rowKey={(a) => `${a.key || a.cid}-${a.rule}`}
            defaultSort={null}
            empty={<EmptyState compact title="Nothing routed away this run." />}
          />
        )}
        {view === 'rules' && (
          <Table
            caption="Routing rules, first match wins, newest click first"
            columns={ruleCols}
            rows={data.rules}
            rowKey={(r) => r.id}
            defaultSort={null}
            empty={<EmptyState compact title="No routing rules." />}
          />
        )}
        <p className="ar-faint ar-foot">
          Anything a person sends me directly is considered by default, even from a source no rule names. Route elsewhere on any item adds a
          rule here.
        </p>
      </Card>
      {dialog}
    </>
  )
}
