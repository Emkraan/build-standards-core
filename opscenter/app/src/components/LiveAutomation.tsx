// Live automation (OC-20): the dark launches that were enabled and now act on their own (unattended deletes, applies, lock
// lifts, access changes). An enabled launch leaves the Action Center, where it waited on a dry run and an Enable, and lives here
// with its Disable switch. Turning it off sets the code host variable back to false (the safe direction, no gate), after a
// confirmation; the server re-reads the live variable before and after, and the launch returns to the Action Center as dark.
// The tab is hidden when no dark launch is registered (Operations sections, pages/operations/sections.ts).
import { Alert, Card, CardHead, EmptyState, Pill, Skeleton, Switch, useConfirm } from '@kit'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { DarkLaunch } from '../lib/data'
import { postDarkLaunch, relTime, useDarkLaunches } from '../lib/data'
import { splitLaunches } from '../lib/darkLaunches'
import { LinkButton, LoadError } from './StateBlocks'

function Row({ it, onDone }: { it: DarkLaunch; onDone: () => void }) {
  const { confirm: ask, dialog } = useConfirm()
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null)
  const unreadable = it.live === 'unknown'
  const turnOff = async () => {
    const ok = await ask({
      title: `Disable ${it.title}?`,
      body: `This sets ${it.variable} to false${it.environment ? ` in the ${it.environment} environment` : ''}. The next run of ${it.workflow} reports instead of acting, and the launch goes back to the Action Center.`,
      confirmLabel: 'Disable',
    })
    if (!ok) return
    setBusy(true)
    setMsg(null)
    try {
      const r = await postDarkLaunch('disable', it.id)
      setMsg({ tone: 'success', text: r.done.length ? r.done.join(', ') : 'Disabled.' })
      onDone()
    } catch (e) {
      setMsg({ tone: 'danger', text: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusy(false)
    }
  }
  return (
    <Card>
      {dialog}
      <CardHead
        title={it.title}
        subtitle={`Runs in ${it.workflow} on ${it.repo}${it.environment ? `, ${it.environment} environment` : ''}.`}
        controls={
          <>
            <Pill tone={unreadable ? 'warning' : 'info'}>{unreadable ? 'switch unreadable' : 'enabled, acting'}</Pill>
            <Switch
              label={`${it.title}: acting`}
              hideLabel
              checked
              disabled={!it.can_disable || busy}
              onChange={(on) => {
                if (!on) void turnOff()
              }}
            />
            {it.dry_run.url && <LinkButton href={it.dry_run.url} external>Last dry run</LinkButton>}
          </>
        }
      />
      <dl className="la-facts">
        <div>
          <dt>Switch</dt>
          <dd>
            <code>{it.variable}</code> is {unreadable ? 'unreadable, so it is treated as on' : 'true'}
          </dd>
        </div>
        <div>
          <dt>Last dry run</dt>
          <dd>{it.dry_run.at ? `started ${relTime(it.dry_run.at)}` : 'none on record'}</dd>
        </div>
      </dl>
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
    </Card>
  )
}

/** The Live automation page. The caller has already checked that a dark launch registry exists. */
export default function LiveAutomation() {
  const { data, error, reload } = useDarkLaunches()
  if (!data) return error ? <LoadError title="Live automation did not load" error={error} /> : <Skeleton variant="lines" count={4} label="Loading live automation" />
  const { acting } = splitLaunches(data.launches)
  return (
    <div className="la-stack">
      <p className="la-lede">
        Automation that was enabled and now acts without asking: deletes, applies, lock lifts and access changes. The switch turns one
        off at once. Launches that are still dark, waiting for a dry run or an Enable, are in the Action Center.
      </p>
      {data.error && <Alert tone="warning" title="The dark launch registry reported a problem">{data.error}</Alert>}
      {acting.length === 0 ? (
        <EmptyState compact pose="idle" title="Nothing is acting on its own." body={<Link to="/action">Open the Action Center</Link>} />
      ) : (
        acting.map((l) => <Row key={l.id} it={l} onDone={() => setTimeout(reload, 500)} />)
      )}
    </div>
  )
}
