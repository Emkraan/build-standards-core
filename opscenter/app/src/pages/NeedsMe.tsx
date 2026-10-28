// Jira hub > Needs me: tickets in my active sprint the nightly close-out could not settle on
// its own because it was not sure the work is done. Each row shows why it is waiting and for how
// long. Close it records my sign-off and fires the close-out job at once, which closes the
// ticket with a full closure comment within a few minutes. The row shows Closing now and polls
// until Jira reads Closed. Keep open takes it off this list until the close-out's reason changes. Both
// apply at once with Undo. Tackle opens a Hermes session to work it through first.
import type { TableColumn } from '@kit'
import { Button, Card, CardHead, EmptyState, Input, Pill, Skeleton, Spinner, StatTile, Table, Toolbar, useToast } from '@kit'
import { useEffect, useState } from 'react'
import { InHermes } from '../components/InHermes'
import { LoadError } from '../components/StateBlocks'
import { TackleJira } from '../components/TackleJira'
import type { NeedsMeDecisionKind, NeedsMeItem } from '../lib/data'
import { postNeedsMeDecide, useJiraNeedsMe } from '../lib/data'
import { TOKEN_HINT } from './Backlog'

function waited(days: number | null): string {
  if (days === null) return 'unknown'
  if (days === 0) return 'today'
  return days === 1 ? '1 day' : `${days} days`
}

export default function NeedsMe() {
  const { data, error, loading, refresh, mutate } = useJiraNeedsMe()
  const { toast } = useToast()
  const [busy, setBusy] = useState<Record<string, boolean>>({})
  const [notes, setNotes] = useState<Record<string, string>>({})
  const anyClosing = !!data?.items.some((i) => i.phase === 'closing')
  // While a close is running, poll every 20s so the row drops as soon as Jira reads Closed.
  useEffect(() => {
    if (!anyClosing) return
    const t = window.setInterval(() => refresh(), 20_000)
    return () => window.clearInterval(t)
  }, [anyClosing, refresh])

  const setRow = (key: string, fn: (i: NeedsMeItem) => NeedsMeItem | null) =>
    mutate((d) => {
      const items = d.items.flatMap((i) => {
        if (i.key !== key) return [i]
        const n = fn(i)
        return n ? [n] : []
      })
      return { ...d, items, count: items.filter((i) => i.phase === 'needs_me').length }
    })

  const undo = async (item: NeedsMeItem) => {
    try {
      await postNeedsMeDecide(item.key, 'undo', item.question)
      toast('success', `${item.key} is back on Needs me`)
    } catch (e) {
      toast('error', `${item.key}: ${e instanceof Error ? e.message : String(e)}`, { persistent: true })
    }
    refresh()
  }

  const decide = async (item: NeedsMeItem, decision: NeedsMeDecisionKind) => {
    setBusy((b) => ({ ...b, [item.key]: true }))
    try {
      const r = await postNeedsMeDecide(item.key, decision, item.question, notes[item.key] || '')
      if (decision === 'keep') setRow(item.key, () => null)
      else setRow(item.key, (i) => ({ ...i, phase: 'closing', decision: r.decision }))
      if (r.trigger_error) toast('error', `${item.key}: ${r.trigger_error}`, { persistent: true })
      else if (decision === 'close')
        toast('success', `Closing ${item.key} now`, {
          description: 'The close-out is running. It posts the closure comment and closes the ticket.',
        })
      else toast('success', `${item.key} stays open, off this list`, { action: { label: 'Undo', onClick: () => undo(item) } })
    } catch (e) {
      toast('error', `${item.key}: ${e instanceof Error ? e.message : String(e)}`, { persistent: true })
      refresh()
    } finally {
      setBusy((b) => {
        const n = { ...b }
        delete n[item.key]
        return n
      })
    }
  }

  const columns: TableColumn<NeedsMeItem>[] = [
    {
      key: 'key',
      header: 'Key',
      width: '130px',
      render: (item) => (
        <span className="bk-key">
          <a className="tkt" href={item.url} target="_blank" rel="noreferrer">
            {item.key}
          </a>
          <InHermes ticket={item.key} />
        </span>
      ),
    },
    {
      key: 'question',
      header: 'Why it is waiting on me',
      value: (item) => `${item.summary} ${item.question}`,
      render: (item) => (
        <div className="bk-sum">
          <span className="bk-title">{item.summary || item.key}</span>
          <span className="nm-q">{item.question}</span>
          {item.decision?.note && <span className="bk-sub">My note: {item.decision.note}</span>}
        </div>
      ),
    },
    {
      key: 'days',
      header: 'Waiting',
      width: '104px',
      numeric: true,
      value: (item) => item.days ?? -1,
      render: (item) => (
        <Pill tone={(item.days ?? 0) >= 3 ? 'danger' : (item.days ?? 0) >= 1 ? 'warning' : 'neutral'}>{waited(item.days)}</Pill>
      ),
    },
    {
      key: 'actions',
      header: 'Actions',
      hideHeader: true,
      sortable: false,
      width: '340px',
      render: (item) =>
        item.phase === 'closing' ? (
          <div className="nm-act">
            <Pill tone="info" dot>
              <Spinner size="sm" /> Closing now
            </Pill>
          </div>
        ) : (
          <div className="nm-act">
            <Input
              size="sm"
              aria-label={`Note for ${item.key}`}
              placeholder="Optional note for the close-out"
              value={notes[item.key] || ''}
              onChange={(e) => setNotes((n) => ({ ...n, [item.key]: e.target.value }))}
            />
            <div className="bk-btns">
              <Button
                size="sm"
                variant="primary"
                loading={!!busy[item.key]}
                onClick={() => decide(item, 'close')}
                data-tip="The work is done. Closes it now with a full closure comment."
              >
                Close it
              </Button>
              <Button
                size="sm"
                disabled={!!busy[item.key]}
                onClick={() => decide(item, 'keep')}
                data-tip="Not done. Off this list until the close-out's reason changes."
              >
                Keep open
              </Button>
              <TackleJira issueKey={item.key} summary={item.summary} compact />
            </div>
          </div>
        ),
    },
  ]

  const waiting = data ? data.items.filter((i) => i.phase === 'needs_me') : []
  const oldest = waiting.reduce((m, i) => Math.max(m, i.days ?? 0), 0)
  const closing = data ? data.items.length - waiting.length : 0

  return (
    <div className="page">
      <p className="jr-lede">
        Sprint tickets the nightly close-out was not sure about. Done work closes on its own. These need my call, and Close it closes the
        ticket right away.
      </p>

      <div className="jr-stats kpi-strip">
        <StatTile value={data ? data.count : '-'} label="waiting on my call" tone={data?.count ? 'warning' : 'success'} />
        <StatTile value={waiting.length ? waited(oldest) : '-'} label="oldest wait" tone={oldest >= 3 ? 'danger' : 'info'} />
        <StatTile value={closing} label="closing now" tone="info" />
      </div>

      {error && !data && (
        <Card>
          <LoadError title="Could not load the tickets waiting on me" error={error} hint={TOKEN_HINT} />
        </Card>
      )}

      {!data && !error && (
        <Card>
          <Skeleton variant="table" count={3} columns={4} label="Loading the tickets waiting on me" />
        </Card>
      )}

      {data && data.items.length === 0 && (
        <Card>
          <EmptyState
            pose="celebrate"
            title="Nothing waiting on my call."
            body="Every open sprint ticket is either done and closing on its own or clearly still in progress."
          />
        </Card>
      )}

      {data && data.items.length > 0 && (
        <Card>
          <CardHead
            title="Waiting on my call"
            subtitle={data.live_ok ? undefined : `Live Jira read failed, showing every open ask: ${data.live_error}`}
          />
          <Toolbar
            label="Needs me controls"
            onRefresh={() => refresh()}
            refreshing={loading}
            updatedAt={Date.parse(data.generated_utc) || null}
          />
          <Table
            className="bk-table"
            caption="Sprint tickets waiting on my call"
            columns={columns}
            rows={data.items}
            rowKey={(r) => r.key}
            defaultSort={{ key: 'days', dir: 'desc' }}
            empty={<EmptyState compact title="Nothing waiting." />}
          />
        </Card>
      )}
    </div>
  )
}
