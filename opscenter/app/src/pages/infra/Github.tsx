// GitHub tab: open pull requests and workflow runs across the repositories infra.py watches.
import type { TableColumn } from '@kit'
import { Card, CardHead, EmptyState, IconAlert, Segmented, StatTile, Table, Toolbar } from '@kit'
import { useState } from 'react'
import { relTime } from '../../lib/data'
import { prTone, runTone, short, ts, useGithub } from './data'
import { FeedPending, Note, StatePill } from './parts'
import type { PR, Run } from './types'

const PR_COLUMNS: TableColumn<PR>[] = [
  {
    key: 'pr',
    header: 'Pull request',
    value: (p) => `${short(p.repo)} ${p.number} ${p.title} ${p.author} ${p.branch}`,
    render: (p) => (
      <div className="infra-cell">
        <span className="infra-cell-title">
          <a href={p.url} target="_blank" rel="noreferrer">
            {short(p.repo)} #{p.number}
          </a>{' '}
          <span className="infra-cell-text">{p.title}</span>
        </span>
        <span className="infra-cell-sub">
          {p.author} &middot; {p.branch} &middot; updated {relTime(p.updated)}
        </span>
        {p.checks.failing.length > 0 && <span className="infra-cell-err">failing: {p.checks.failing.join(', ')}</span>}
      </div>
    ),
  },
  {
    key: 'checks',
    header: 'Checks',
    value: (p) => p.checks.fail * 1000 + p.checks.pending,
    render: (p) => (
      <div className="infra-pills infra-nowrap">
        {p.draft && <StatePill tone="neutral">draft</StatePill>}
        <StatePill tone={prTone(p)} live={p.checks.pending > 0 && !p.checks.fail}>
          {p.checks.pass} pass / {p.checks.fail} fail{p.checks.pending ? ` / ${p.checks.pending} running` : ''}
        </StatePill>
      </div>
    ),
  },
  {
    key: 'merge_state',
    header: 'Merge',
    render: (p) => (
      <StatePill tone={p.merge_state === 'CLEAN' ? 'success' : 'warning'}>{p.merge_state.toLowerCase() || 'unknown'}</StatePill>
    ),
  },
]

const RUN_COLUMNS: TableColumn<Run>[] = [
  {
    key: 'workflow',
    header: 'Workflow',
    value: (r) => `${r.workflow} ${short(r.repo)} ${r.branch} ${r.title}`,
    render: (r) => (
      <div className="infra-cell">
        <span className="infra-cell-title">
          <a href={r.url} target="_blank" rel="noreferrer">
            {r.workflow}
          </a>
        </span>
        <span className="infra-cell-sub">
          {short(r.repo)} &middot; {r.branch} &middot; {r.event}
        </span>
        <span className="infra-cell-sub infra-trunc">{r.title}</span>
      </div>
    ),
  },
  {
    key: 'status',
    header: 'Result',
    value: (r) => (r.status === 'completed' ? r.conclusion : r.status),
    render: (r) => (
      <StatePill tone={runTone(r)} live={r.status === 'in_progress'}>
        {r.status === 'completed' ? r.conclusion || 'done' : r.status.replace('_', ' ')}
      </StatePill>
    ),
  },
  {
    key: 'created',
    header: 'Started',
    value: (r) => ts(r.created),
    render: (r) => <span className="infra-muted">{relTime(r.created)}</span>,
  },
]

export default function GithubTab() {
  const { data, error, refresh, loading, at } = useGithub()
  const [repo, setRepo] = useState('all')
  if (!data) return <FeedPending title="GitHub" error={error} what="GitHub" tiles />
  const inRepo = (r: { repo: string }) => repo === 'all' || r.repo === repo
  const prs = data.prs.filter(inRepo)
  const runs = data.runs.filter(inRepo).slice(0, 30)
  const red = data.red_on_main.filter(inRepo)
  const errors = Object.entries(data.errors)
  return (
    <div className="infra-stack">
      <div className="stat-grid">
        <StatTile value={data.prs.length} label="open PRs" hue="blue" />
        <StatTile
          value={data.prs.filter((p) => p.checks.fail).length}
          label="PRs with failing checks"
          tone={data.prs.some((p) => p.checks.fail) ? 'danger' : 'success'}
        />
        <StatTile value={data.in_progress.length} label="workflows running" hue="violet" />
        <StatTile value={data.red_on_main.length} label="workflows red on main" tone={data.red_on_main.length ? 'danger' : 'success'} />
      </div>
      <Toolbar label="GitHub filters" onRefresh={refresh} refreshing={loading} updatedAt={at || null}>
        <Segmented
          label="Repository filter"
          value={repo}
          onChange={setRepo}
          options={['all', ...data.repos].map((r) => ({
            value: r,
            label: r === 'all' ? 'All repos' : short(r),
            tip: r === 'all' ? undefined : r,
          }))}
        />
      </Toolbar>
      {errors.length > 0 && (
        <p className="tone hue-red infra-alert" role="alert">
          <IconAlert />
          <span>{errors.map(([r, e]) => `${short(r)}: ${e}`).join(' | ')}</span>
        </p>
      )}
      <div className="infra-grid">
        <Card>
          <CardHead title="Open pull requests" subtitle={`${prs.length} open`} />
          <Table
            caption="Open pull requests"
            columns={PR_COLUMNS}
            rows={prs}
            rowKey={(p) => `${p.repo}#${p.number}`}
            defaultSort={null}
            empty={<EmptyState compact pose="celebrate" title="No open PRs." />}
          />
        </Card>
        <Card>
          <CardHead title="Workflow runs" subtitle="newest first" />
          {red.length > 0 && (
            <ul className="infra-red-list">
              {red.map((r) => (
                <li key={r.id} className="tone hue-red">
                  <StatePill tone="danger">red on main</StatePill>
                  <a href={r.url} target="_blank" rel="noreferrer">
                    {short(r.repo)} / {r.workflow}
                  </a>
                </li>
              ))}
            </ul>
          )}
          <Table
            caption="Workflow runs, newest first"
            columns={RUN_COLUMNS}
            rows={runs}
            rowKey={(r) => String(r.id)}
            defaultSort={{ key: 'created', dir: 'desc' }}
            maxHeight="560px"
            empty={<EmptyState compact title="No workflow runs yet." />}
          />
          <Note>Live from GitHub every 30 seconds. Refreshed {relTime(data.generated_utc)}.</Note>
        </Card>
      </div>
    </div>
  )
}
