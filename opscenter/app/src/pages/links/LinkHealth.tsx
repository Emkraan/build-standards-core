// Link health on the Links page. Shown while the weekly check (link_health.py) has dead
// links. Each dead link has Swap (enter the corrected address) and Remove. Both re-check on the
// server first, then edit links/catalog.json on a fresh branch and open the PR in github_user/ops_center_repo,
// which the auto-merge lane takes and the deploy cron ships. A link with an open PR shows the PR
// instead of the buttons until the deploy drops the old address.
import { Button, Card, CardHead, Field, Input, Modal, Pill, useToast } from '@kit'
import { useState } from 'react'
import { LinkButton } from '../../components/StateBlocks'
import type { LinkHealthData } from '../../lib/data'
import { postLinkEdit, postLinksCheck, useLinkHealth } from '../../lib/data'
import { hostOf } from './catalog'

type Dead = LinkHealthData['dead'][number]
type Ask = { kind: 'swap' | 'remove'; row: Dead } | null

const day = (iso?: string | null) => (iso ? new Date(iso).toLocaleDateString([], { month: 'short', day: 'numeric' }) : '')

export function LinkHealth() {
  const { data, reload } = useLinkHealth()
  const { toast } = useToast()
  const [ask, setAsk] = useState<Ask>(null)
  const [newUrl, setNewUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [checking, setChecking] = useState(false)
  const [err, setErr] = useState('')
  const dead = data?.dead || []
  if (dead.length === 0) return null
  const open = dead.filter((d) => !d.edit).length

  const start = (kind: 'swap' | 'remove', row: Dead) => {
    setErr('')
    setNewUrl('')
    setAsk({ kind, row })
  }

  const submit = async () => {
    if (!ask) return
    setBusy(true)
    setErr('')
    try {
      const res = await postLinkEdit(ask.kind, ask.row.url, ask.kind === 'swap' ? newUrl.trim() : undefined)
      setAsk(null)
      toast(
        'success',
        res.message,
        res.pr_url ? { action: { label: `Open PR #${res.pr}`, onClick: () => window.open(res.pr_url, '_blank', 'noopener') } } : {},
      )
      reload()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const checkNow = async () => {
    setChecking(true)
    try {
      const res = await postLinksCheck()
      const n = res.dead.filter((d) => !d.edit).length
      toast(n ? 'warning' : 'success', n ? `${n} link${n === 1 ? '' : 's'} still not reachable` : 'Every link answered')
      reload()
    } catch (e) {
      toast('error', e instanceof Error ? e.message : String(e))
    } finally {
      setChecking(false)
    }
  }

  return (
    <Card as="section" className="lh-card" tone={open ? 'red' : undefined} aria-labelledby="lh-title">
      <CardHead
        level={2}
        title={<span id="lh-title">Link health</span>}
        count={open || undefined}
        controls={
          <Button size="sm" variant="ghost" loading={checking} onClick={checkNow} data-tip="Re-check every link now (about 15 seconds)">
            {checking ? 'Checking...' : 'Check now'}
          </Button>
        }
      />
      <p className="lh-lede">
        {open
          ? `${open} link${open === 1 ? '' : 's'} stopped working on the last check (${day(data?.checked_utc)}). Swap in the new address if the console moved, or remove it. Each opens a PR that the merge lane takes.`
          : `Every dead link has a PR open. They drop off this list once the PR deploys.`}
      </p>
      <ul className="lh-list">
        {dead.map((d) => (
          <li key={d.url} className="lh-row">
            <div className="lh-text">
              <a className="lh-name" href={d.url} target="_blank" rel="noopener noreferrer" data-tip={d.url}>
                {d.name}
              </a>
              <span className="lh-meta">
                {hostOf(d.url)} . {d.group} . {d.reason}
                {d.since ? `, failing since ${day(d.since)}` : ''}
              </span>
            </div>
            {d.edit ? (
              <div className="lh-actions">
                <Pill tone="info">{d.edit.action === 'swap' ? 'Swap PR open' : 'Removal PR open'}</Pill>
                <LinkButton href={d.edit.pr_url} target="_blank" rel="noopener noreferrer">
                  PR #{d.edit.pr}
                </LinkButton>
              </div>
            ) : (
              <div className="lh-actions">
                <Button size="sm" variant="primary" onClick={() => start('swap', d)} data-tip="Correct the address. Opens a PR.">
                  Swap
                </Button>
                <Button
                  size="sm"
                  variant="danger-subtle"
                  onClick={() => start('remove', d)}
                  data-tip="Take it off the Links page. Opens a PR."
                >
                  Remove
                </Button>
              </div>
            )}
          </li>
        ))}
      </ul>
      <Modal
        open={ask?.kind === 'swap'}
        onClose={() => setAsk(null)}
        title={`Swap the ${ask?.row.name || ''} link`}
        subtitle="I check the new address answers, then open the catalog PR."
        hue="green"
        size="md"
        busy={busy}
        onSubmit={submit}
        primaryAction={{ label: 'Open swap PR', loading: busy, disabled: !newUrl.trim() }}
      >
        <Field label="New address" error={err || undefined} hint={`Current address (not working): ${ask?.row.url || ''}`}>
          <Input
            type="url"
            value={newUrl}
            data-autofocus=""
            placeholder="Paste the corrected address, https://..."
            onChange={(e) => setNewUrl(e.target.value)}
            spellCheck={false}
          />
        </Field>
      </Modal>
      <Modal
        open={ask?.kind === 'remove'}
        onClose={() => setAsk(null)}
        title={`Remove ${ask?.row.name || ''}?`}
        subtitle="I re-check it first. If it answers again I leave it and clear the flag."
        hue="red"
        size="sm"
        role="alertdialog"
        busy={busy}
        onSubmit={submit}
        primaryAction={{ label: 'Open removal PR', danger: true, loading: busy }}
      >
        <p className="lh-confirm">{ask?.row.url} comes off the Links page and the Cmd K palette once the PR merges and deploys.</p>
        {err && (
          <p className="lh-err" role="alert">
            {err}
          </p>
        )}
      </Modal>
    </Card>
  )
}
