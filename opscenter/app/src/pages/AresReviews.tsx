// team sub-tab of the Reviews hub (private): what in the team monorepo waits on me,
// what is moving, and what shipped in the last 14 days. Live from GitHub plus the
// team PR review lane's escalations. Writes go through server.py as github_user, pinned
// to the head shown here.
import type { TableColumn } from '@kit'
import { Button, Card, CardHead, EmptyState, Input, StatusDot, Table, useConfirm, useToast } from '@kit'
import { useState } from 'react'
import AlertBanner from '../components/AlertBanner'
import { ApprovalBriefView } from '../components/ApprovalBrief'
import { confirmText } from '../components/confirmText'
import { DecisionCard } from '../components/DecisionCard'
import { DiscussPr } from '../components/DiscussPr'
import { Tabs } from '../components/Tabs'
import { aresPrWorking, useActionCounts } from '../lib/counts'
import type { AresPr, AresShipped } from '../lib/data'
import { postAresReview, relTime, useAresReviews } from '../lib/data'
import type { Tone } from './reviews/parts'
import {
  actedNow,
  ErrorCard,
  JustActed,
  Line,
  LinkButton,
  LoadingCard,
  Locked,
  PrRef,
  Reasons,
  ResultNote,
  ReviewItem,
  Tag,
} from './reviews/parts'

function ChecksPill({ p }: { p: AresPr }) {
  const c = p.checks
  if (c.red.length) return <Tag tone="alert">{c.red.length} red</Tag>
  if (c.pending.length)
    return (
      <Tag tone="info" live>
        {c.pending.length} running
      </Tag>
    )
  if (c.total) return <Tag tone="good">all green</Tag>
  return <Tag tone="neutral">no checks</Tag>
}

// Auto-fix is the one working state ChecksPill cannot show, so it gets its own spinner pill
// (same words as the platform tab).
function AutofixPill({ p }: { p: AresPr }) {
  const s = p.autofix?.state
  if (s !== 'running' && s !== 'deferred') return null
  return (
    <Tag tone="info" live>
      {s === 'running' ? 'auto-fixing' : 'session on it'}
    </Tag>
  )
}

const KIND: Record<string, [Tone, string]> = {
  escalated: ['warn', 'escalated by review'],
  signoff: ['warn', 'needs your sign-off'],
  direction: ['alert', 'needs your direction'],
  ready_to_merge: ['info', 'my PR, ready to merge'],
}

function NeedRow({ p }: { p: AresPr }) {
  const { reload, mutate } = useAresReviews()
  const { toast } = useToast()
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  // Only these kinds get a button. 'direction' (auto-fix gave up) never does.
  const act: 'merge' | 'approve' | null =
    p.kind === 'signoff' || p.kind === 'ready_to_merge' ? 'merge' : p.kind === 'escalated' ? 'approve' : null
  const label = p.kind === 'signoff' ? 'Approve and merge' : act === 'merge' ? 'Merge' : 'Approve as me'
  const [tone, text] = KIND[p.kind || 'escalated'] || KIND.escalated
  const working = aresPrWorking(p)
  const { confirm: ask, dialog } = useConfirm()
  const run = async () => {
    if (!act) return
    const q =
      p.kind === 'signoff'
        ? `APPROVE AND MERGE team PR #${p.pr} at ${p.head_sha.slice(0, 8)}?\n\n${p.brief?.approving || `You are signing off on: ${(p.rules || []).join('. ')}`}`
        : act === 'merge'
          ? `MERGE team PR #${p.pr} now with your maintainer bypass at ${p.head_sha.slice(0, 8)}?`
          : `APPROVE team PR #${p.pr} by ${p.author} at ${p.head_sha.slice(0, 8)}? The review lane merges it on its next pass.`
    // Merges are destructive (danger styling, Cancel takes focus). Approving an engineer's PR is not.
    const ok = await ask({ ...confirmText(q), confirmLabel: label, danger: act === 'merge' })
    if (!ok) return
    setBusy(true)
    setMsg(null)
    try {
      const r = await postAresReview(act, p.pr, p.head_sha, p.unknown)
      // Gone at once. The server keeps it hidden until GitHub and the review lane catch up.
      mutate((d) => ({
        ...d,
        needs_me: d.needs_me.filter((x) => x.pr !== p.pr),
        in_progress: d.in_progress.filter((x) => x.pr !== p.pr),
        acted: [actedNow(p.pr, p.title, act === 'merge' ? 'merged' : 'approved'), ...(d.acted || [])],
        counts: { ...d.counts, needs_me: Math.max(0, d.counts.needs_me - 1) },
      }))
      toast('success', `PR #${p.pr}: ${r.done.join('; ')}`)
      setTimeout(reload, 1500)
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusy(false)
    }
  }
  return (
    <ReviewItem
      pulse={p}
      state={p.kind === 'direction' ? 'stuck' : 'needs_you'}
      working={working}
      top={
        <>
          <PrRef href={p.url}>#{p.pr}</PrRef>
          <Tag tone={p.unknown ? 'warn' : tone}>{p.unknown ? 'escalation unknown' : text}</Tag>
          <ChecksPill p={p} />
          <AutofixPill p={p} />
          {p.mergeable === 'CONFLICTING' && <Tag tone="alert">conflict</Tag>}
        </>
      }
      title={p.title}
      meta={
        <>
          {p.author} &middot; {p.branch} &middot; {p.head_sha.slice(0, 8)}
          {p.updated ? ` \u00b7 updated ${relTime(p.updated)}` : ''}
        </>
      }
      actions={
        <>
          {/* While work is running on the PR, no action buttons, so nothing can disrupt it. */}
          {!working && act && (
            <Button size="sm" variant="primary" loading={busy} onClick={run}>
              {busy ? 'Working...' : label}
            </Button>
          )}
          {!working && <DiscussPr repo="team" pr={p.pr} />}
          {working && <Locked />}
          <LinkButton href={p.url}>Open PR</LinkButton>
        </>
      }
    >
      {dialog}
      {p.brief ? (
        <ApprovalBriefView repo="team" pr={p.pr} brief={p.brief} reload={reload}>
          {p.why && <Line>{p.why}</Line>}
          <Reasons tone="neutral" items={(p.rules || []).map((r) => <b key={r}>{r}</b>)} />
          {p.kind === 'escalated' && p.recommendation && <Line>Recommendation: {p.recommendation}</Line>}
        </ApprovalBriefView>
      ) : (
        <>
          {p.why && <Line>{p.why}</Line>}
          <Reasons tone="neutral" items={(p.rules || []).map((r) => <b key={r}>{r}</b>)} />
        </>
      )}
      {p.recommendation && (!p.brief || p.kind !== 'escalated') && (
        <Line>
          {p.kind === 'escalated' ? 'Recommendation: ' : 'Next: '}
          {p.recommendation}
        </Line>
      )}
      <ResultNote msg={msg} />
      {!working && p.kind === 'direction' && p.decision && (
        <DecisionCard
          p={p}
          decision={p.decision}
          repo="team"
          onDone={(done) => {
            // In flight until the lane acts on the choice.
            mutate((d) => ({
              ...d,
              needs_me: d.needs_me.filter((x) => x.pr !== p.pr),
              in_progress: [{ ...p, kind: undefined, decision: undefined, state: done }, ...d.in_progress],
              counts: { ...d.counts, needs_me: Math.max(0, d.counts.needs_me - 1) },
            }))
            setMsg({ ok: true, text: done })
            setTimeout(reload, 1500)
          }}
        />
      )}
    </ReviewItem>
  )
}

function NeedsMe() {
  const { data, error } = useAresReviews()
  if (error && !data) return <ErrorCard title="Could not load team reviews" error={error} />
  if (!data) return <LoadingCard label="Loading team reviews" />
  const n = data.needs_me.length
  return (
    <Card as="section">
      <CardHead
        title={
          <span className="rh-title-dot">
            <StatusDot tone={n ? 'danger' : 'success'} label={n ? 'Waiting on me' : 'All clear'} pulse={false} />
            Needs me
          </span>
        }
        subtitle="Escalated engineer PRs, my PRs waiting on my sign-off, and my PRs auto-fix could not clear"
      />
      {n === 0 ? (
        <EmptyState compact pose="celebrate" title="Nothing in team waits on me." />
      ) : (
        <div className="rh-list">
          {data.needs_me.map((p) => (
            <NeedRow key={p.pr} p={p} />
          ))}
        </div>
      )}
      <JustActed items={data.acted} />
    </Card>
  )
}

function InProgress() {
  const { data } = useAresReviews()
  if (!data) return <LoadingCard label="Loading team PRs in progress" />
  return (
    <Card as="section">
      <CardHead
        title="In progress"
        subtitle="Engineer PRs in the review loop, and my PRs the auto-merge lane is still working (checks running, or auto-fix on a problem)"
      />
      {data.in_progress.length === 0 ? (
        <EmptyState compact title="No other open team PRs." />
      ) : (
        <div className="rh-list">
          {data.in_progress.map((p) => {
            const working = p.mine && aresPrWorking(p)
            return (
              <ReviewItem
                pulse={p}
                key={p.pr}
                state="waiting"
                working={working}
                top={
                  <>
                    <PrRef href={p.url}>#{p.pr}</PrRef>
                    <ChecksPill p={p} />
                    {p.mine && <AutofixPill p={p} />}
                    {p.draft && <Tag tone="neutral">draft</Tag>}
                    {p.mine && <Tag tone="info">mine</Tag>}
                  </>
                }
                title={p.title}
                meta={
                  <>
                    {p.author} &middot; {p.head_sha.slice(0, 8)} &middot; {p.state}
                    {p.updated ? ` \u00b7 ${relTime(p.updated)}` : ''}
                  </>
                }
                actions={
                  p.mine && !aresPrWorking(p) && (p.checks.red.length > 0 || p.mergeable === 'CONFLICTING') ? (
                    <DiscussPr repo="team" pr={p.pr} />
                  ) : undefined
                }
              />
            )
          })}
        </div>
      )}
    </Card>
  )
}

const SHIPPED_COLS: TableColumn<AresShipped>[] = [
  { key: 'pr', header: 'PR', value: (p) => p.pr, render: (p) => <PrRef href={p.url}>#{p.pr}</PrRef>, width: '84px' },
  { key: 'title', header: 'Title', value: (p) => p.title, render: (p) => <span className="rh-cell-title">{p.title}</span> },
  { key: 'status', header: 'Status', sortable: false, render: () => <Tag tone="good">merged</Tag>, width: '100px' },
  {
    key: 'author',
    header: 'Author',
    value: (p) => (p.author === 'github_user' ? 'mine' : p.author),
    render: (p) => <Tag>{p.author === 'github_user' ? 'mine' : p.author}</Tag>,
    width: '140px',
  },
  { key: 'sha', header: 'Commit', value: (p) => p.sha, render: (p) => <code>{p.sha}</code>, width: '110px' },
  { key: 'merged', header: 'Merged', value: (p) => p.merged, render: (p) => (p.merged ? relTime(p.merged) : ''), width: '110px' },
]

function Shipped() {
  const { data } = useAresReviews()
  const [q, setQ] = useState('')
  if (!data) return <LoadingCard label="Loading recently shipped" />
  return (
    <Card as="section">
      <CardHead
        title="Recently shipped"
        subtitle="Merged in the last 14 days"
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
        caption="team PRs merged in the last 14 days"
        columns={SHIPPED_COLS}
        rows={data.shipped}
        rowKey={(p) => String(p.pr)}
        filter={q}
        defaultSort={{ key: 'merged', dir: 'desc' }}
        empty={<EmptyState compact title="Nothing merged in the last 14 days." />}
        noMatch={<EmptyState compact title="No matching PRs" body="Try a shorter or different filter." />}
      />
    </Card>
  )
}

export default function AresSection({ tab }: { tab?: string }) {
  const { data } = useAresReviews()
  const c = data?.counts
  const { aresWorking } = useActionCounts()
  const alerts = data && (data.error || data.lane_error || data.own_lane_error)
  return (
    <>
      <Tabs
        small
        label="team reviews"
        tabs={[
          { to: '/reviews/team', label: 'Needs me', n: c?.needs_me, end: true },
          { to: '/reviews/team/progress', label: 'In progress', n: c?.in_progress, live: aresWorking > 0 },
          { to: '/reviews/team/shipped', label: 'Recently shipped' },
        ]}
      />
      {alerts && (
        <div className="rh-alerts">
          {data.error && <AlertBanner title="GitHub read failed, showing the last good data">{data.error}</AlertBanner>}
          {data.lane_error && <AlertBanner title="team PR review lane state unreadable">{data.lane_error}</AlertBanner>}
          {data.own_lane_error && <AlertBanner tone="warning" title={data.own_lane_error} />}
        </div>
      )}
      <div className="rh-body">{tab === 'progress' ? <InProgress /> : tab === 'shipped' ? <Shipped /> : <NeedsMe />}</div>
      {data?.generated_utc && (
        <p className="rh-foot">GitHub read {relTime(data.generated_utc)} &middot; escalations from the team PR review lane</p>
      )}
    </>
  )
}
