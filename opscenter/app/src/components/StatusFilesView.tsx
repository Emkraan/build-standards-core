// Status files and freshness (Platform, Host and access): every state file the ops center reads, oldest first, with its size and age. The server says which are stale;
// this page holds no threshold of its own (DESIGN.md 12.101). Names, sizes and times only, never contents.
import type { TableColumn } from '@kit'
import { Alert, Card, CardHead, EmptyState, Pill, Skeleton, Table } from '@kit'
import type { StatusFile } from '../lib/data'
import { relTime, useStatusFiles } from '../lib/data'
import { StatRow } from './StatRow'

const COLS: TableColumn<StatusFile>[] = [
  { key: 'name', header: 'File', render: (f) => <code>{f.name}</code> },
  { key: 'state', header: 'State', width: '110px', render: (f) => <Pill tone={f.state === 'stale' ? 'warning' : 'success'}>{f.state === 'stale' ? 'Stale' : 'Fresh'}</Pill> },
  { key: 'age_min', header: 'Last written', width: '160px', numeric: true, render: (f) => relTime(f.updated_utc) },
  { key: 'size', header: 'Size', width: '100px', numeric: true, render: (f) => (f.size < 1024 ? `${f.size} B` : `${Math.round(f.size / 1024)} KB`) },
]

export default function StatusFilesView() {
  const { data, error } = useStatusFiles()
  if (!data) return error ? <Alert tone="danger">The status files did not load: {error}</Alert> : <Skeleton variant="table" count={4} columns={4} label="Loading status files" />
  return (
    <div className="infra-stack">
      <StatRow
        label="Freshness summary"
        stats={[
          { key: 'fresh', label: 'Fresh', value: data.counts.fresh },
          { key: 'stale', label: 'Stale', value: data.counts.stale, sub: `older than ${data.stale_after_min} min` },
        ]}
      />
      <Card>
        <CardHead title="Status files" subtitle="The data files the pages read, oldest first. Contents are never shown." />
        {data.files.length === 0 ? (
          <EmptyState compact title="No status file yet." />
        ) : (
          <Table caption="Status files" columns={COLS} rows={data.files} rowKey={(f) => f.name} defaultSort={null} />
        )}
      </Card>
    </div>
  )
}
