// One extension page: a page a consumer declared in its manifest, drawn by the core. A list page shows the rows the consumer serves and a link
// page points at a tool the consumer runs. It reads and links only, with no button that changes anything, and all text is drawn as text
// (issue 308, item 22). The decisions live in lib/extensions.ts so a test can load them without the browser.

import { Button, EmptyState, Modal, Pill, Segmented, Skeleton, useConfirm } from '@kit'
import { useState } from 'react'
import { HubHeader } from '../components/HubHeader'
import { LoadError } from '../components/StateBlocks'
import { fetchExtensionRows, postExtensionAction, useExtensionRows, useExtensions } from '../lib/data'
import type { ExtensionRow } from '../lib/extensions'
import { pageMode, rowLinks, rowsInState, safeHref, stateTabs } from '../lib/extensions'
import './ExtensionPage.css'

export default function ExtensionPage({ id }: { id: string }) {
  const { data: manifest } = useExtensions()
  const { data: rows, error } = useExtensionRows(id)
  const [state, setState] = useState('')
  const [openId, setOpenId] = useState<string | null>(null)
  const [msg, setMsg] = useState('')
  const { confirm, dialog } = useConfirm()
  // Windows after the first, loaded on request; the first window is the live store, so a refresh replaces it and drops these.
  const [more, setMore] = useState<{ id: string; rows: ExtensionRow[]; left: number; err: string; busy: boolean }>({ id, rows: [], left: -1, err: '', busy: false })
  const extra = more.id === id ? more : { id, rows: [], left: -1, err: '', busy: false }
  const page = rows?.page ?? (manifest && manifest.configured ? (manifest.pages.find((p) => p.id === id) ?? null) : null)
  const title = page?.title ?? 'Extension'
  const header = <HubHeader title={title} subtitle={page?.lede ?? undefined} />
  // A failed read is an error even while an earlier copy is held, so a stale list never reads as current.
  if (error) return <>{header}<LoadError title="I could not read this page" error={error} /></>
  if (!rows) return <>{header}<Skeleton variant="lines" count={4} label="Loading the page" /></>
  const mode = pageMode(rows)
  if (mode === 'error') return <>{header}<LoadError title="The source could not be read" error={`${rows.error}. This is not the same as nothing to show.`} /></>
  if (mode === 'link') {
    const href = safeHref(rows.page?.url)
    return (
      <>
        {header}
        {href ? (
          <p className="ext-link">
            <a href={href} target="_blank" rel="noreferrer noopener">
              Open {title}
            </a>
          </p>
        ) : (
          <EmptyState compact pose="idle" title="This page has no usable address." />
        )}
      </>
    )
  }
  if (mode === 'empty') return <>{header}<EmptyState compact pose="idle" title="Nothing to show yet." /></>
  const all = [...rows.rows, ...extra.rows]
  const tabs = stateTabs(all)
  const shown = rowsInState(all, tabs.some((t) => t.state === state) ? state : '')
  const open = openId ? all.find((r) => r.id === openId) : undefined
  const act = async (rowId: string, a: { id: string; label: string; confirm: string | null }) => {
    const ok = await confirm({ title: `${a.label}?`, body: a.confirm ?? undefined, confirmLabel: a.label })
    if (!ok) return
    try {
      const r = await postExtensionAction(id, rowId, a.id)
      setMsg(r.ok ? r.detail || `${a.label}: done.` : r.detail || `${a.label} did not go through.`)
    } catch (e) {
      setMsg(String(e).replace(/^Error: /, ''))
    }
  }
  return (
    <>
      {header}
      {tabs.length > 0 && (
        <Segmented
          label="State"
          value={tabs.some((t) => t.state === state) ? state : ''}
          onChange={setState}
          options={[{ value: '', label: `All ${all.length}` }, ...tabs.map((t) => ({ value: t.state, label: `${t.state} ${t.n}` }))]}
        />
      )}
      {msg && <p role="status">{msg}</p>}
      <ul className="ext-rows" aria-label={title}>
        {shown.map((r) => {
          const href = safeHref(r.url)
          return (
            <li key={r.id}>
              {r.state && <Pill tone="neutral">{r.state}</Pill>}
              <span className="ext-title">
                {href ? (
                  <a href={href} target="_blank" rel="noreferrer noopener">
                    {r.title}
                  </a>
                ) : (
                  r.title
                )}
              </span>
              {r.doc === 'missing' && <span className="ext-detail muted">Document not available</span>}
              {r.detail && <span className="ext-detail muted">{r.detail}</span>}
              {((r.fields?.length ?? 0) > 0 || (r.actions?.length ?? 0) > 0 || (r.links?.length ?? 0) > 0 || (r.links_missing ?? 0) > 0) && (
                <Button size="sm" variant="ghost" onClick={() => setOpenId(r.id)}>
                  Details
                </Button>
              )}
              {r.at && <span className="ext-at muted">{r.at}</span>}
            </li>
          )
        })}
      </ul>
      {(extra.left < 0 ? rows.truncated : extra.left) > 0 && (
        <p className="muted">
          {extra.left < 0 ? rows.truncated : extra.left} more rows.{' '}
          <Button
            size="sm"
            variant="secondary"
            loading={extra.busy}
            onClick={() => {
              setMore({ ...extra, busy: true, err: '' })
              fetchExtensionRows(id, (rows.offset ?? 0) + rows.rows.length + extra.rows.length)
                .then((r) => setMore({ id, rows: [...extra.rows, ...r.rows], left: r.truncated, err: r.error || '', busy: false }))
                .catch((e) => setMore({ ...extra, busy: false, err: String(e).replace(/^Error: /, '') }))
            }}
          >
            Show more
          </Button>
          {extra.err && ` ${extra.err}`}
        </p>
      )}
      <Modal open={!!open} onClose={() => setOpenId(null)} size="md" title={open?.title ?? ''}>
        {open && (
          <>
            {open.detail && <p>{open.detail}</p>}
            {(open.fields?.length ?? 0) > 0 && (
              <dl className="ext-fields">
                {open.fields?.map((f) => (
                  <div key={f.label}>
                    <dt>{f.label}</dt>
                    <dd>{f.value}</dd>
                  </div>
                ))}
              </dl>
            )}
            {(() => {
              const { links, missing } = rowLinks(open)
              return (
                (links.length > 0 || missing > 0) && (
                  <div className="ext-links">
                    <ul>
                      {links.map((l) => (
                        <li key={l.href}>
                          <a href={l.href} target="_blank" rel="noopener noreferrer">
                            {l.label}
                          </a>
                        </li>
                      ))}
                    </ul>
                    {missing > 0 && <p className="muted">{missing === 1 ? '1 link is not available.' : `${missing} links are not available.`}</p>}
                  </div>
                )
              )
            })()}
            <div className="ext-actions">
              {open.actions?.map((a) => (
                <Button key={a.id} variant="secondary" onClick={() => act(open.id, a)}>
                  {a.label}
                </Button>
              ))}
            </div>
          </>
        )}
      </Modal>
      {dialog}
    </>
  )
}
