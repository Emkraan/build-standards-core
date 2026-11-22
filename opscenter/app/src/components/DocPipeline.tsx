// The document pipeline tab of Knowledge (DESIGN.md 12.97): what needs a document, its draft, a Word-style preview, suggested changes in place, approve or reject, restore,
// and the guarded publish. Every button that changes something asks a confirmation; Publish names the version it will publish and the server refuses a draft that moved on.
import { Alert, Button, Card, CardHead, EmptyState, Modal, Pill, Skeleton, useConfirm } from '@kit'
import { useState } from 'react'
import type { PipelineDoc } from '../lib/data'
import {
  fetchDocPreview,
  postDocDecide,
  postDocDraft,
  postDocPublish,
  postDocRestore,
  postDocSuggest,
  useDocPipeline,
} from '../lib/data'

const TONE: Record<PipelineDoc['state'], 'neutral' | 'info' | 'warning' | 'success' | 'danger'> = {
  queued: 'neutral',
  drafted: 'info',
  suggested: 'warning',
  approved: 'success',
  rejected: 'danger',
  published: 'success',
}

export default function DocPipeline() {
  const { data, error, refresh } = useDocPipeline()
  const { confirm, dialog } = useConfirm()
  const [open, setOpen] = useState<{ doc: PipelineDoc; version: string; text: string } | null>(null)
  const [note, setNote] = useState('')
  const [msg, setMsg] = useState('')
  if (!data) return error ? <Alert tone="danger">The document pipeline did not load: {error}</Alert> : <Skeleton variant="lines" count={4} label="Loading documents" />
  if (!data.configured) return null
  const run = async (what: () => Promise<unknown>, done: string) => {
    try {
      await what()
      setMsg(done)
      refresh()
    } catch (e) {
      setMsg(String(e).replace(/^Error: /, ''))
    }
  }
  const view = async (doc: PipelineDoc) => {
    try {
      const p = await fetchDocPreview(doc.id)
      setOpen({ doc, version: p.version, text: p.text })
      setNote('')
    } catch (e) {
      setMsg(String(e).replace(/^Error: /, ''))
    }
  }
  const decide = async (d: 'approve' | 'reject') => {
    if (!open) return
    if (!(await confirm({ title: `${d === 'approve' ? 'Approve' : 'Reject'} this draft?`, body: open.doc.title, confirmLabel: d === 'approve' ? 'Approve' : 'Reject' }))) return
    await run(() => postDocDecide(open.doc.id, d, open.version), d === 'approve' ? 'Approved. It can be published now.' : 'Rejected.')
    setOpen(null)
  }
  const publish = async (doc: PipelineDoc) => {
    if (!doc.version) return
    if (!(await confirm({ title: 'Publish to the library?', body: `${doc.title}, version ${doc.version}. Nothing is written if the draft changed after the approval.`, confirmLabel: 'Publish' }))) return
    await run(async () => {
      const r = await postDocPublish(doc.id, doc.version as string)
      if (!r.ok) throw new Error(r.detail || 'The library did not take it.')
    }, 'Published.')
  }
  return (
    <Card>
      <CardHead title="Documents" subtitle="What needs writing, its draft, and the approval that lets it reach the library." />
      {data.error && <Alert tone="danger">{data.error}. This is not the same as nothing waiting.</Alert>}
      {msg && <p role="status">{msg}</p>}
      {data.docs.length === 0 && !data.error ? (
        <EmptyState compact title="No document is waiting." />
      ) : (
        <ul className="dp-rows">
          {data.docs.map((d) => (
            <li key={d.id}>
              <Pill tone={TONE[d.state]}>{d.state}</Pill> <strong>{d.title}</strong> {d.source && <span className="muted">from {d.source}</span>}
              <span className="dp-actions">
                {(d.state === 'queued' || d.state === 'suggested') && (
                  <Button size="sm" variant="secondary" onClick={() => run(() => postDocDraft(d.id), 'Drafted.')}>
                    {d.state === 'queued' ? 'Draft' : 'Redraft'}
                  </Button>
                )}
                {(d.state === 'drafted' || d.state === 'suggested' || d.state === 'approved') && (
                  <Button size="sm" variant="ghost" onClick={() => view(d)}>
                    Preview
                  </Button>
                )}
                {d.state === 'approved' && (
                  <Button size="sm" onClick={() => publish(d)}>
                    Publish
                  </Button>
                )}
                {(d.state === 'rejected' || d.state === 'published') && (
                  <Button size="sm" variant="ghost" onClick={async () => (await confirm({ title: 'Restore this document to a draft?', confirmLabel: 'Restore' })) && run(() => postDocRestore(d.id), 'Restored to a draft.')}>
                    Restore
                  </Button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      <Modal open={!!open} onClose={() => setOpen(null)} size="lg" title={open?.doc.title ?? ''}>
        {open && (
          <>
            <article className="dp-page" aria-label="Draft preview">
              {open.text.split(/\n{2,}/).map((p, i) => (
                <p key={i}>{p}</p>
              ))}
            </article>
            {open.doc.suggestion && <p className="muted">Suggested change on file: {open.doc.suggestion}</p>}
            <label className="dp-suggest">
              Suggest a change
              <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} />
            </label>
            <div className="dp-actions">
              <Button variant="secondary" disabled={!note.trim()} onClick={() => run(() => postDocSuggest(open.doc.id, note), 'Suggestion sent.').then(() => setOpen(null))}>
                Send suggestion
              </Button>
              {open.doc.state === 'drafted' && (
                <>
                  <Button onClick={() => decide('approve')}>Approve</Button>
                  <Button variant="ghost" onClick={() => decide('reject')}>
                    Reject
                  </Button>
                </>
              )}
            </div>
          </>
        )}
      </Modal>
      {dialog}
    </Card>
  )
}
