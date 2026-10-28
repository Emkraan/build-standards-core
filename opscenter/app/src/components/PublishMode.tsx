import { Button, Card, CardHead, EmptyState, Pill, useConfirm, useToast } from '@kit'
import { useState } from 'react'
import { createLiveStore, fetchApi } from '../lib/data'
import { LoadError } from './StateBlocks'

// Per-class publish mode for Knowledge proposals. A class is staged (waits for a
// batch approval, the default) or auto (the applier publishes it without one and logs the page
// version before and after). The only class today is Changelog appends. I flip it here, never
// ops_center. Backend: GET /api/knowledge/publish-modes, POST /api/knowledge/publish-mode, logic in
// state/dashboard/publish_mode.py. The digest lists what auto published, newest day first, each
// with a link to the prior page version to revert to.

export interface PublishClass {
  id: string
  label: string
  mode: 'staged' | 'auto'
  what_auto_does: string
}
export interface DigestItem {
  fp: string
  title: string
  page_id?: string
  when: string
  version_before?: number | null
  version_after?: number | null
  revert_url?: string
  history_url?: string
}
export interface PublishModes {
  classes: PublishClass[]
  digest: { date: string; count: number; items: DigestItem[] }[]
  updated_utc?: string
}

const usePublishModes = createLiveStore(() => fetchApi<PublishModes>('api/knowledge/publish-modes'), 60_000)

async function postMode(cls: string, mode: 'staged' | 'auto'): Promise<PublishModes> {
  const res = await fetch(`${import.meta.env.BASE_URL || './'}api/knowledge/publish-mode`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ class: cls, mode }),
  })
  if (!res.ok) {
    const j = await res.json().catch(() => ({}))
    throw new Error((j as { error?: string }).error || `publish-mode -> ${res.status}`)
  }
  return (await res.json()) as PublishModes
}

const clock = (iso: string) => (iso ? `${iso.slice(11, 16)}Z` : '')

export function PublishModeCard() {
  const { data, error, mutate, reload } = usePublishModes()
  const { confirm: ask, dialog } = useConfirm()
  const { toast } = useToast()
  const [busy, setBusy] = useState<string | null>(null)

  const flip = async (c: PublishClass) => {
    const next = c.mode === 'auto' ? 'staged' : 'auto'
    if (next === 'auto') {
      const ok = await ask({
        title: `Publish ${c.label.toLowerCase()} without a batch approval?`,
        body: `${c.what_auto_does} I can switch it back to staged here at any time.`,
        confirmLabel: 'Turn on auto',
      })
      if (!ok) return
    }
    setBusy(c.id)
    try {
      const fresh = await postMode(c.id, next)
      mutate(() => fresh)
      toast('success', next === 'auto' ? `${c.label}: auto` : `${c.label}: staged`)
    } catch (e) {
      toast('error', 'Could not change the mode', { description: String(e) })
      reload()
    } finally {
      setBusy(null)
    }
  }

  if (error && !data) {
    return (
      <Card>
        <LoadError title="Could not load publish modes" error={error} />
      </Card>
    )
  }
  if (!data) return null
  return (
    <>
      {dialog}
      {data.classes.map((c) => (
        <Card key={c.id} className="kc-mode">
          <CardHead
            level={3}
            title={`Publish mode: ${c.label}`}
            controls={
              <Button size="sm" variant={c.mode === 'auto' ? 'ghost' : 'primary'} loading={busy === c.id} onClick={() => flip(c)}>
                {c.mode === 'auto' ? 'Switch to staged' : 'Switch to auto'}
              </Button>
            }
          />
          <p className="kc-note">
            <Pill tone={c.mode === 'auto' ? 'warning' : 'neutral'} dot>
              {c.mode}
            </Pill>{' '}
            {c.mode === 'auto'
              ? 'These publish on their own and appear in the digest on the History tab. Everything else still waits for me.'
              : 'Staged: these wait for my approval like everything else.'}{' '}
            Auto publishes an append to our own Changelog pages without a batch approval, logs the page version before and after, and lists
            it in a daily digest with a link to the prior version.
          </p>
        </Card>
      ))}
    </>
  )
}

export function AutoPublishDigest() {
  const { data } = usePublishModes()
  if (!data) return null
  const total = data.digest.reduce((n, d) => n + d.count, 0)
  return (
    <>
      <h2 className="kc-section">Auto-published digest</h2>
      {total === 0 ? (
        <Card>
          <EmptyState
            title="Nothing auto-published."
            body="Pages the applier publishes without a batch approval are listed here by day, with a link to revert."
          />
        </Card>
      ) : (
        <div className="kc-stack">
          {data.digest.map((d) => (
            <Card key={d.date} as="article">
              <CardHead level={3} title={d.date} subtitle={`${d.count} published`} />
              <ul className="kc-digest">
                {d.items.map((i) => (
                  <li key={i.fp + i.when}>
                    <span className="kc-strong">{i.title}</span>{' '}
                    <span className="kc-faint">
                      {clock(i.when)} &middot; version {i.version_before ?? '?'} to {i.version_after ?? '?'}
                    </span>{' '}
                    {i.revert_url && (
                      <a href={i.revert_url} target="_blank" rel="noreferrer">
                        Revert to version {i.version_before}
                      </a>
                    )}{' '}
                    {i.history_url && (
                      <a href={i.history_url} target="_blank" rel="noreferrer">
                        Page history
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            </Card>
          ))}
        </div>
      )}
    </>
  )
}
