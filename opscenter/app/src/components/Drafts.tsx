// The Drafts tab of the Action Center (DESIGN.md 12.100): the drafts the owner keeps, with Archive and Restore. A draft is never deleted and never sent from here.
import { Alert, Button, Card, CardHead, EmptyState, Pill, Skeleton, useConfirm } from '@kit'
import { useState } from 'react'
import { postDraftArchive, useDrafts } from '../lib/data'

export default function Drafts() {
  const { data, error, refresh } = useDrafts()
  const { confirm, dialog } = useConfirm()
  const [archived, setArchived] = useState(false)
  const [msg, setMsg] = useState('')
  if (!data) return error ? <Alert tone="danger">The drafts did not load: {error}</Alert> : <Skeleton variant="lines" count={4} label="Loading drafts" />
  if (!data.configured) return null
  const rows = data.drafts.filter((d) => d.archived === archived)
  const move = async (id: string, title: string, restore: boolean) => {
    if (!(await confirm({ title: restore ? 'Bring this draft back?' : 'Archive this draft?', body: `${title}. It is kept, never deleted.`, confirmLabel: restore ? 'Restore' : 'Archive' }))) return
    try {
      await postDraftArchive(id, restore)
      setMsg(restore ? 'Restored.' : 'Archived.')
      refresh()
    } catch (e) {
      setMsg(String(e).replace(/^Error: /, ''))
    }
  }
  return (
    <Card>
      <CardHead title="Drafts" subtitle="Nothing here is sent by automation. A draft can be archived and brought back, never deleted." />
      {data.error && <Alert tone="danger">{data.error}. This is not the same as having no drafts.</Alert>}
      <Button size="sm" variant="ghost" aria-pressed={archived} onClick={() => setArchived((a) => !a)}>
        {archived ? 'Show active drafts' : `Show archived (${data.drafts.filter((d) => d.archived).length})`}
      </Button>
      {msg && <p role="status">{msg}</p>}
      {rows.length === 0 && !data.error ? (
        <EmptyState compact title={archived ? 'No archived drafts.' : 'No drafts.'} />
      ) : (
        <ul className="dr-rows">
          {rows.map((d) => (
            <li key={d.id}>
              <Pill tone="neutral">{d.kind === 'reply' ? 'Reply' : 'Draft'}</Pill> <strong>{d.title}</strong> {d.updated && <span className="muted">{d.updated}</span>}
              <Button size="sm" variant="ghost" onClick={() => move(d.id, d.title, archived)}>
                {archived ? 'Restore' : 'Archive'}
              </Button>
            </li>
          ))}
        </ul>
      )}
      {dialog}
    </Card>
  )
}
