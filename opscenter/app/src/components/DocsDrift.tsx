// Docs drift (OC-10): the documentation pages that are behind the code they document, and each app's README and
// changelog facts. Report only: nothing here writes to the docs home or the code host. The server
// (server/modules/docs_drift.py) answers from its cache and refreshes in the background; "Check again" forces a read of the
// source and "Run now" asks the consumer to start a new drift run when it has a way to. The tab exists only when the
// server has a provider (a 404 hides it, see Knowledge.tsx).
import type { StatusTone, TableColumn } from '@kit'
import { Alert, Button, Card, CardHead, EmptyState, Pill, Skeleton, StatTile, Table } from '@kit'
import { useState } from 'react'
import type { DocsDrift as DocsDriftData, DriftFacts, DriftRow } from '../lib/data'
import { postDocsDrift, relTime, useDocsDrift } from '../lib/data'
import { LinkButton, LivePill, LoadError } from './StateBlocks'

// The server's closed set of statuses; an unknown value is drawn neutral.
const STATUS_TONE: Record<string, StatusTone> = {
  behind: 'warning',
  current: 'success',
  'current-unverified': 'neutral',
  'sha-missing': 'neutral',
  'no-footer': 'neutral',
}
const STATUS_LABEL: Record<string, string> = {
  behind: 'behind',
  current: 'current',
  'current-unverified': 'current, unverified',
  'sha-missing': 'commit not found',
  'no-footer': 'no footer',
}
const BASIS_LABEL: Record<string, string> = {
  'footer-commit': 'footer commit',
  'footer-date': 'footer date',
  'edit-date': 'last edit',
  none: 'none',
}
const README_LABEL: Record<string, string> = {
  missing: 'missing',
  'stale-version': 'names an old version',
  'no-confluence-link': 'no docs link',
  current: 'current',
}
const CHANGELOG_LABEL: Record<string, string> = {
  'changelog-page-unreadable': 'page unreadable',
  'no-changelog-page': 'no changelog page',
  'no-changelog-file': 'no changelog file',
  gaps: 'gaps',
  complete: 'complete',
}
const FACT_TONE: Record<string, StatusTone> = { current: 'success', complete: 'success' }

const label = (map: Record<string, string>, k?: string) => (k ? (map[k] ?? k) : '-')
const day = (iso?: string) => {
  if (!iso) return '-'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

const ROW_COLUMNS: TableColumn<DriftRow>[] = [
  {
    key: 'page',
    header: 'Page',
    value: (r) => r.title || r.page,
    render: (r) =>
      r.link ? (
        <a href={r.link} target="_blank" rel="noreferrer">
          {r.title || r.page}
        </a>
      ) : (
        <span>{r.title || r.page}</span>
      ),
  },
  { key: 'thing', header: 'Documents', value: (r) => r.thing || '' },
  {
    key: 'status',
    header: 'Status',
    value: (r) => r.status || '',
    render: (r) => <Pill tone={STATUS_TONE[r.status] ?? 'neutral'}>{label(STATUS_LABEL, r.status)}</Pill>,
  },
  { key: 'commits', header: 'Commits behind', numeric: true, value: (r) => Number(r.commits) || 0 },
  { key: 'since', header: 'Since', value: (r) => r.since || '', render: (r) => day(r.since) },
  { key: 'basis', header: 'Judged by', value: (r) => r.basis || '', render: (r) => label(BASIS_LABEL, r.basis) },
  {
    key: 'files',
    header: 'Files changed',
    numeric: true,
    value: (r) => Number(r.files_total) || r.files?.length || 0,
  },
]

const FACT_COLUMNS: TableColumn<DriftFacts>[] = [
  { key: 'name', header: 'App', value: (f) => f.name || f.thing || '' },
  { key: 'version', header: 'Version', value: (f) => f.version || '', render: (f) => f.version || '-' },
  { key: 'latest', header: 'Latest release', value: (f) => f.latest_release || '', render: (f) => f.latest_release || '-' },
  {
    key: 'readme',
    header: 'README',
    value: (f) => f.readme?.status || '',
    render: (f) =>
      f.readme?.status ? <Pill tone={FACT_TONE[f.readme.status] ?? 'neutral'}>{label(README_LABEL, f.readme.status)}</Pill> : '-',
  },
  {
    key: 'changelog',
    header: 'Changelog',
    value: (f) => f.changelog?.status || '',
    render: (f) =>
      f.changelog?.status ? <Pill tone={FACT_TONE[f.changelog.status] ?? 'neutral'}>{label(CHANGELOG_LABEL, f.changelog.status)}</Pill> : '-',
  },
]

function Summary({ d }: { d: DocsDriftData }) {
  const noVerdict = (d.counts['no-footer'] || 0) + (d.counts['sha-missing'] || 0)
  return (
    <div className="dd-tiles">
      <StatTile label="Pages checked" value={d.total} />
      <StatTile label="Behind the code" value={d.behind_total} tone="warning" />
      <StatTile label="No verdict" value={noVerdict} hint="no footer, or the footer's commit was not found" />
      <StatTile label="Read errors" value={d.errors} tone="danger" />
    </div>
  )
}

/** The docs drift page. The caller has already checked that the provider is configured. */
export default function DocsDrift() {
  const { data, error, reload } = useDocsDrift()
  const [busy, setBusy] = useState<'refresh' | 'run' | null>(null)
  const [note, setNote] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null)
  if (!data) return error ? <LoadError title="Docs drift did not load" error={error} /> : <Skeleton variant="lines" count={6} label="Loading docs drift" />
  if (!data.configured) return <EmptyState compact title="Docs drift is not configured." body="No provider is set on the server, so there is nothing to show." />
  const act = async (a: 'refresh' | 'run') => {
    setBusy(a)
    setNote(null)
    try {
      await postDocsDrift(a)
      setNote({ tone: 'success', text: a === 'run' ? 'A new drift run was started. This page picks it up when it finishes.' : 'Read the newest run again.' })
      reload()
    } catch (e) {
      setNote({ tone: 'danger', text: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusy(null)
    }
  }
  const pending = !!data.pending_run
  return (
    <div className="dd-stack">
      <p className="kc-lede">
        Documentation pages that are behind the code they document, and each app's README and changelog facts. This is report only: nothing
        here changes a page or the code.
      </p>
      {data.error && (
        <Alert tone="warning" title="The last read of the drift source failed">
          {data.error}. The figures below are from the last good read.
        </Alert>
      )}
      {note && <Alert tone={note.tone}>{note.text}</Alert>}
      <Card>
        <CardHead
          title={data.run ? `Run ${data.run.id ?? ''}`.trim() : 'No run yet'}
          subtitle={
            <>
              {data.run?.created ? `Started ${relTime(data.run.created)}. ` : ''}
              {data.run?.head ? `Code at ${String(data.run.head).slice(0, 7)}. ` : ''}
              {data.fetched_utc ? `Read ${relTime(data.fetched_utc)}.` : 'Not read yet.'}
            </>
          }
          controls={
            <>
              {(pending || data.refreshing) && <LivePill>{pending ? 'waiting for the new run' : 'reading'}</LivePill>}
              {data.run?.url && <LinkButton href={data.run.url} external>Open run</LinkButton>}
              <Button size="sm" variant="secondary" loading={busy === 'refresh'} disabled={busy !== null} onClick={() => act('refresh')}>
                Check again
              </Button>
              <Button size="sm" variant="secondary" loading={busy === 'run'} disabled={busy !== null || pending} onClick={() => act('run')}>
                Run now
              </Button>
            </>
          }
        />
      </Card>
      <Summary d={data} />
      <Card>
        <CardHead title="Pages behind the code" count={data.behind_total} subtitle="Most commits behind first." />
        {data.behind.length === 0 ? (
          <EmptyState compact pose="idle" title={data.total === 0 ? 'No pages were checked in the newest run.' : 'No page is behind the code.'} />
        ) : (
          <Table caption="Pages behind the code" columns={ROW_COLUMNS} rows={data.behind} rowKey={(r) => `${r.thing}/${r.page}`} defaultSort={null} />
        )}
        {data.behind_total > data.behind.length && (
          <p className="kc-faint">
            Showing the {data.behind.length} furthest behind of {data.behind_total}.
          </p>
        )}
      </Card>
      {data.no_verdict.length > 0 && (
        <Card>
          <CardHead title="Pages with no verdict" count={data.no_verdict.length} subtitle="The page carries no footer or its commit was not found, so it cannot be judged." />
          <Table caption="Pages with no verdict" columns={ROW_COLUMNS} rows={data.no_verdict} rowKey={(r) => `${r.thing}/${r.page}`} defaultSort={null} />
        </Card>
      )}
      {data.facts.length > 0 && (
        <Card>
          <CardHead title="README and changelog" count={data.facts.length} />
          <Table caption="README and changelog facts" columns={FACT_COLUMNS} rows={data.facts} rowKey={(f) => f.thing || f.name} defaultSort={null} />
        </Card>
      )}
    </div>
  )
}
