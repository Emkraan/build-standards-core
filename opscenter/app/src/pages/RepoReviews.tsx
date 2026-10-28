// One Reviews hub tab per repo outside platform and team (ops_center backup, Core standards), laid out
// exactly like the team tab: Needs me, In progress and Recently shipped, each row saying why it is
// there. Needs me holds PRs nothing automated can move (lane hold, auto-fix gave up, red checks,
// review requested) and issues with a reply waiting or gone quiet. In progress holds PRs a
// lane is working (checks running, auto-fix, the core owner's queue) and issues waiting on the other
// side. Writes: re-run failed jobs, pinned to the head shown.
import type { TableColumn } from '@kit'
import { Button, Card, CardHead, EmptyState, Input, StatusDot, Table, useToast } from '@kit'
import { useState } from 'react'
import AlertBanner from '../components/AlertBanner'
import { DiscussPr } from '../components/DiscussPr'
import { Tabs } from '../components/Tabs'
import { postRepoRerun, type RepoIssue, type RepoPr, type RepoShipped, relTime, useRepoReviews } from '../lib/data'
import { ErrorCard, JustActed, Line, LinkButton, LoadingCard, Locked, PrRef, ResultNote, ReviewItem, Tag, type Tone } from './reviews/parts'

const KIND: Record<string, [Tone, string]> = {
  checks: ['alert', 'checks failing'],
  review: ['warn', 'review requested'],
  stale: ['warn', 'green, not merged'],
  conflict: ['alert', 'merge conflict'],
}

const ISSUE_KIND: Record<string, [Tone, string]> = {
  replied: ['warn', 'issue: reply waiting'],
  quiet: ['neutral', 'issue: gone quiet'],
}

const isWorking = (p: RepoPr) => !!p.working
const sentence = (s?: string) => (s ? `${s.charAt(0).toUpperCase()}${s.slice(1)}${/[.!?]$/.test(s) ? '' : '.'}` : '')

function ChecksPill({ p }: { p: RepoPr }) {
  const c = p.checks
  if (c.red) return <Tag tone="alert">{c.red} red</Tag>
  if (c.pending)
    return (
      <Tag tone="info" live>
        {c.pending} running
      </Tag>
    )
  if (c.total) return <Tag tone="good">all green</Tag>
  return <Tag tone="neutral">no checks</Tag>
}

function AutofixPill({ p }: { p: RepoPr }) {
  const s = p.autofix?.state
  if (s !== 'running' && s !== 'deferred') return null
  return (
    <Tag tone="info" live>
      {s === 'running' ? 'auto-fixing' : 'session on it'}
    </Tag>
  )
}

function OwnerQueue({ p }: { p: RepoPr }) {
  const q = p.owner_queue
  if (!q) return null
  return (
    <Tag tone="neutral">
      owner queue {q.place}/{q.of}
    </Tag>
  )
}

function useRepo(slug: string) {
  const q = useRepoReviews()
  return { ...q, repo: q.data?.repos.find((r) => r.slug === slug) }
}

function NeedRow({ p }: { p: RepoPr }) {
  const { reload } = useRepoReviews()
  const { toast } = useToast()
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [tone, text] = KIND[p.kind || 'checks'] || KIND.checks
  const working = isWorking(p)
  const rerun = async () => {
    setBusy(true)
    setMsg(null)
    try {
      const r = await postRepoRerun(p.slug, p.pr, p.head_sha)
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
      state={p.kind === 'checks' || p.kind === 'conflict' ? 'stuck' : 'needs_you'}
      working={working}
      top={
        <>
          <PrRef href={p.url}>#{p.pr}</PrRef>
          <Tag tone={tone}>{text}</Tag>
          <ChecksPill p={p} />
          <AutofixPill p={p} />
          {p.mine && <Tag tone="info">mine</Tag>}
        </>
      }
      title={p.title}
      meta={
        <>
          {p.author} &middot; {p.head_sha.slice(0, 8)}
          {p.updated ? ` \u00b7 updated ${relTime(p.updated)}` : ''}
        </>
      }
      actions={
        <>
          {!working && p.kind === 'checks' && (
            <Button size="sm" variant="secondary" loading={busy} onClick={rerun}>
              {busy ? 'Working...' : 'Re-run failed'}
            </Button>
          )}
          {!working && <DiscussPr repo={p.slug} pr={p.pr} />}
          {working && <Locked />}
          <LinkButton href={p.url}>Open PR</LinkButton>
        </>
      }
    >
      {p.why && <Line>{p.why}</Line>}
      {p.autofix && p.autofix.text !== p.why && <Line>{p.autofix.text}</Line>}
      {p.failing.map((f) => (
        <Line key={f.name}>
          <a href={f.url} target="_blank" rel="noreferrer">
            {f.name}
          </a>
          {f.files.length ? `: ${f.files.join(', ')}` : ': no file named in the log, open the job'}
        </Line>
      ))}
      <ResultNote msg={msg} />
    </ReviewItem>
  )
}

function IssueRow({ i, waiting }: { i: RepoIssue; waiting?: boolean }) {
  const [tone, text] = waiting ? (['neutral', 'issue'] as [Tone, string]) : ISSUE_KIND[i.kind || 'replied'] || ISSUE_KIND.replied
  return (
    <ReviewItem
      state={waiting || i.kind === 'quiet' ? 'waiting' : 'needs_you'}
      top={
        <>
          <PrRef href={i.url}>#{i.issue}</PrRef>
          <Tag tone={tone}>{text}</Tag>
        </>
      }
      title={i.title}
      meta={
        <>
          issue &middot; {i.comments} comments &middot; last {i.last_by}
          {i.last_at ? ` ${relTime(i.last_at)}` : ''}
        </>
      }
      actions={<LinkButton href={i.url}>Open issue</LinkButton>}
    >
      {waiting ? <Line>{sentence(i.state)}</Line> : i.why && <Line>{i.why}</Line>}
      {!waiting && i.excerpt && <Line>{i.excerpt}</Line>}
    </ReviewItem>
  )
}

function NeedsMe({ slug }: { slug: string }) {
  const { data, error, repo } = useRepo(slug)
  if (error && !data) return <ErrorCard title="Could not load repo reviews" error={error} />
  if (!data || !repo) return <LoadingCard label="Loading reviews" />
  const issues = repo.issues_need || []
  const n = repo.needs_me.length + issues.length
  return (
    <Card as="section">
      <CardHead
        title={
          <span className="rh-title-dot">
            <StatusDot tone={n ? 'danger' : 'success'} label={n ? 'Waiting on me' : 'All clear'} pulse={false} />
            Needs me
          </span>
        }
        subtitle="PRs no lane can move (lane hold, auto-fix gave up, red checks, review requested) and issues with a reply waiting or gone quiet"
      />
      {n === 0 ? (
        <EmptyState compact pose="celebrate" title={`Nothing in ${repo.label || slug} waits on me.`} />
      ) : (
        <div className="rh-list">
          {repo.needs_me.map((p) => (
            <NeedRow key={`p${p.pr}`} p={p} />
          ))}
          {issues.map((i) => (
            <IssueRow key={`i${i.issue}`} i={i} />
          ))}
        </div>
      )}
      <JustActed items={repo.acted} />
    </Card>
  )
}

function InProgress({ slug }: { slug: string }) {
  const { data, repo } = useRepo(slug)
  if (!data || !repo) return <LoadingCard label="Loading PRs in progress" />
  const issues = repo.issues_waiting || []
  const empty = repo.in_progress.length === 0 && issues.length === 0
  return (
    <Card as="section">
      <CardHead
        title="In progress"
        subtitle="PRs a lane is working (checks running, auto-fix, the core owner's queue) and issues waiting on the other side"
      />
      {empty ? (
        <EmptyState compact title={`No other open ${repo.label || slug} PRs or issues.`} />
      ) : (
        <div className="rh-list">
          {repo.in_progress.map((p) => (
            <ReviewItem
              pulse={p}
              key={`p${p.pr}`}
              state="waiting"
              working={isWorking(p)}
              top={
                <>
                  <PrRef href={p.url}>#{p.pr}</PrRef>
                  <ChecksPill p={p} />
                  <AutofixPill p={p} />
                  <OwnerQueue p={p} />
                  {p.draft && <Tag tone="neutral">draft</Tag>}
                  {p.mine && <Tag tone="info">mine</Tag>}
                </>
              }
              title={p.title}
              meta={
                <>
                  {p.author} &middot; {p.head_sha.slice(0, 8)}
                  {p.updated ? ` \u00b7 ${relTime(p.updated)}` : ''}
                </>
              }
              actions={<LinkButton href={p.url}>Open PR</LinkButton>}
            >
              {p.state && <Line>{sentence(p.state)}</Line>}
              {p.autofix && <Line>{p.autofix.text}</Line>}
              {p.owner_queue && p.owner_queue.blocked_by.length > 0 && (
                <Line>Lower versions still ahead: {p.owner_queue.blocked_by.map((x) => `#${x}`).join(', ')}.</Line>
              )}
            </ReviewItem>
          ))}
          {issues.map((i) => (
            <IssueRow key={`i${i.issue}`} i={i} waiting />
          ))}
        </div>
      )}
    </Card>
  )
}

const SHIPPED_COLS: TableColumn<RepoShipped>[] = [
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
  {
    key: 'merged',
    header: 'Merged',
    value: (p) => p.merged,
    render: (p) => (p.merged ? relTime(p.merged) : ''),
    width: '110px',
  },
]

function Shipped({ slug }: { slug: string }) {
  const { data, repo } = useRepo(slug)
  const [q, setQ] = useState('')
  if (!data || !repo) return <LoadingCard label="Loading recently shipped" />
  const rows = repo.shipped || []
  return (
    <Card as="section">
      <CardHead
        title="Recently shipped"
        subtitle="Merged in the last 14 days"
        controls={
          rows.length > 0 ? (
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
        caption={`${repo.repo} PRs merged in the last 14 days`}
        columns={SHIPPED_COLS}
        rows={rows}
        rowKey={(p) => String(p.pr)}
        filter={q}
        defaultSort={{ key: 'merged', dir: 'desc' }}
        empty={<EmptyState compact title="Nothing merged in the last 14 days." />}
        noMatch={<EmptyState compact title="No matching PRs" body="Try a shorter or different filter." />}
      />
    </Card>
  )
}

export default function RepoSection({ slug, tab }: { slug: string; tab?: string }) {
  const { data, repo } = useRepo(slug)
  const c = repo?.counts
  const working = (repo?.in_progress || []).some(isWorking)
  const base = `/reviews/${slug}`
  return (
    <>
      <Tabs
        small
        label={`${repo?.label || slug} reviews`}
        tabs={[
          { to: base, label: 'Needs me', n: c?.needs_me, end: true },
          { to: `${base}/progress`, label: 'In progress', n: c?.in_progress, live: working },
          { to: `${base}/shipped`, label: 'Recently shipped' },
        ]}
      />
      {repo && (repo.error || repo.issues_error || repo.lane?.error) && (
        <div className="rh-alerts">
          {repo.error && <AlertBanner title="GitHub read failed">{repo.error}</AlertBanner>}
          {repo.issues_error && (
            <AlertBanner tone="warning" title="Issues unreadable">
              {repo.issues_error}
            </AlertBanner>
          )}
          {repo.lane?.error && <AlertBanner tone="warning" title={repo.lane.error} />}
        </div>
      )}
      <div className="rh-body">
        {tab === 'progress' ? <InProgress slug={slug} /> : tab === 'shipped' ? <Shipped slug={slug} /> : <NeedsMe slug={slug} />}
      </div>
      {data?.generated_utc && (
        <p className="rh-foot">
          GitHub read {relTime(data.generated_utc)}
          {repo?.lane?.name ? ` \u00b7 worked by the ${repo.lane.name}` : ''}
          {repo?.lane?.updated ? `, last pass ${relTime(repo.lane.updated)}` : ''}
        </p>
      )}
    </>
  )
}
