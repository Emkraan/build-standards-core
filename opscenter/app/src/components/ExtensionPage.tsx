// One extension page: a page a consumer declared in its manifest, drawn by the core. A list page shows the rows the consumer serves and a link
// page points at a tool the consumer runs. It reads and links only, with no button that changes anything, and all text is drawn as text
// (issue 308, item 22). The decisions live in lib/extensions.ts so a test can load them without the browser.

import { EmptyState, Pill, Skeleton } from '@kit'
import { HubHeader } from '../components/HubHeader'
import { LoadError } from '../components/StateBlocks'
import { useExtensionRows, useExtensions } from '../lib/data'
import { pageMode, safeHref } from '../lib/extensions'
import './ExtensionPage.css'

export default function ExtensionPage({ id }: { id: string }) {
  const { data: manifest } = useExtensions()
  const { data: rows, error } = useExtensionRows(id)
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
  return (
    <>
      {header}
      <ul className="ext-rows" aria-label={title}>
        {rows.rows.map((r) => {
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
              {r.detail && <span className="ext-detail muted">{r.detail}</span>}
              {r.at && <span className="ext-at muted">{r.at}</span>}
            </li>
          )
        })}
      </ul>
      {rows.truncated > 0 && <p className="muted">{rows.truncated} more rows are not shown.</p>}
    </>
  )
}
