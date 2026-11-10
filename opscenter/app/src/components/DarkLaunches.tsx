// acting automation (unattended deletes, applies, lock lifts, access changes) ships with its
// action off and reports only. One card per registered dark launch. Run dry run dispatches the workflow
// with dry_run=true, Enable sets the switch variable after a green dry run (typed variable name), and
// Disable puts it back. The server re-reads the live variable and the dry run before it acts, so this
// card only renders what it was told.
import { Button, usePrompt } from '@kit'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { DarkLaunch } from '../lib/data'
import { postDarkLaunch, relTime, useDarkLaunches } from '../lib/data'
import { LIVE_AUTOMATION_PATH, splitLaunches } from '../lib/darkLaunches'
import type { Tone } from '../pages/reviews/parts'
import { LinkButton, Locked, ResultNote, ReviewItem, Tag } from '../pages/reviews/parts'

const DRY: Record<DarkLaunch['dry_run']['state'], { text: string; tone: Tone }> = {
  none: { text: 'no dry run yet', tone: 'neutral' },
  running: { text: 'dry run running', tone: 'info' },
  passed: { text: 'dry run passed', tone: 'good' },
  failed: { text: 'dry run failed', tone: 'alert' },
  unknown: { text: 'dry run unknown', tone: 'warn' },
}

function DarkLaunchItem({ it, reload }: { it: DarkLaunch; reload: () => void }) {
  const [busy, setBusy] = useState<string | null>(null)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const { prompt, dialog } = usePrompt()
  const dry = DRY[it.dry_run.state]
  const running = it.dry_run.state === 'running'
  const live =
    it.live === 'on'
      ? { text: 'enabled, acting', tone: 'warn' as Tone }
      : it.live === 'off'
        ? { text: 'dark, reports only', tone: 'neutral' as Tone }
        : { text: 'switch unreadable', tone: 'warn' as Tone }
  const act = async (a: 'dry-run' | 'enable' | 'disable') => {
    let confirm: string | undefined
    if (a === 'enable') {
      const typed = await prompt({
        title: `Enable ${it.title}?`,
        label: `Type ${it.variable} to confirm`,
        body: `This sets ${it.variable} to true${it.environment ? ` in the ${it.environment} environment` : ''}. The next run of ${it.workflow} acts instead of reporting.`,
        confirmLabel: 'Enable',
        validate: (v) => (v === it.variable ? null : `Type ${it.variable} exactly.`),
      })
      if (typed === null) return
      confirm = typed
    }
    setBusy(a)
    setMsg(null)
    try {
      const r = await postDarkLaunch(a, it.id, confirm)
      setMsg({ ok: true, text: r.done.join(', ') })
      setTimeout(reload, 1500)
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusy(null)
    }
  }
  return (
    <ReviewItem
      state={it.live === 'on' ? 'waiting' : 'needs_you'}
      working={running}
      top={
        <>
          <Tag tone={live.tone}>{live.text}</Tag>
          <Tag tone={dry.tone} live={running}>
            {dry.text}
          </Tag>
          <Tag tone="info">Dark launch</Tag>
        </>
      }
      title={it.title}
      meta={
        <>
          Merged with its action off. It runs in report mode until {it.variable}
          {it.environment ? ` (${it.environment} environment)` : ''} is true in {it.repo}. Run a dry run, read what it would do, then
          Enable.
          {it.dry_run.at && <> Last dry run started {relTime(it.dry_run.at)}.</>}
        </>
      }
      actions={
        <>
          {running ? (
            <Locked />
          ) : (
            <>
              <Button
                size="sm"
                variant="secondary"
                loading={busy === 'dry-run'}
                disabled={!it.can_dry_run || busy !== null}
                onClick={() => act('dry-run')}
              >
                Run dry run
              </Button>
              {it.live !== 'on' && (
                <Button
                  size="sm"
                  variant="danger"
                  loading={busy === 'enable'}
                  disabled={!it.can_enable || busy !== null}
                  onClick={() => act('enable')}
                >
                  Enable
                </Button>
              )}
            </>
          )}
          {it.can_disable && (
            <Button size="sm" variant="secondary" loading={busy === 'disable'} disabled={busy !== null} onClick={() => act('disable')}>
              Disable
            </Button>
          )}
          {it.dry_run.url && <LinkButton href={it.dry_run.url}>Open dry run</LinkButton>}
        </>
      }
    >
      {dialog}
      <ResultNote msg={msg} />
    </ReviewItem>
  )
}

/** Cards for the dark launches still waiting on a dry run and an Enable. An enabled launch is acting and lives under Operations,
 *  Live automation (lib/darkLaunches.ts), so it leaves this page. Renders nothing when none is waiting and none is acting. */
export default function DarkLaunches() {
  const { data, reload } = useDarkLaunches()
  if (!data || (data.launches.length === 0 && !data.error)) return null
  const { acting, dark } = splitLaunches(data.launches)
  if (dark.length === 0 && acting.length === 0 && !data.error) return null
  return (
    <section aria-label="Dark launches" style={{ marginBottom: 18 }}>
      {data.error && <ResultNote msg={{ ok: false, text: `Dark launch registry: ${data.error}` }} />}
      {dark.map((l) => (
        <DarkLaunchItem key={l.id} it={l} reload={reload} />
      ))}
      {acting.length > 0 && (
        <p>
          <Link to={LIVE_AUTOMATION_PATH}>
            {acting.length} live automation{acting.length === 1 ? ' is' : 's are'} acting: see Live automation
          </Link>
        </p>
      )}
    </section>
  )
}
