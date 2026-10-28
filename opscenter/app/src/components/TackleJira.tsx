// "Tackle" on one of my open Jira items (Jira hub Sprint and Backlog): opens a Hermes desktop
// chat that pulls the live ticket, does the work read-only, drafts anything outbound, and asks
// before it comments, transitions or closes. Session state comes from the shared tackle store
// (key jira-<KEY>), same as Action Center tackles and PR discussions. The optional context step
// is a kit Modal (Cmd+Enter starts, Esc cancels).
import { Button, Field, Modal, Textarea } from '@kit'
import { useState } from 'react'
import { hermesSessionUrl, postJiraTackle, useTackleSessions } from '../lib/data'
import { sessionHint, useLiveTickets } from './InHermes'
import { LinkButton } from './StateBlocks'

export function TackleJira({ issueKey, compact = false, summary }: { issueKey: string; compact?: boolean; summary?: string }) {
  const { data, reload } = useTackleSessions()
  const rec = data?.[`jira-${issueKey}`]
  const [ask, setAsk] = useState(false)
  const [ctx, setCtx] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const opening = busy || rec?.state === 'launching' || rec?.state === 'claimed'
  const live = !!rec?.live && !!rec.session_id
  // an Action Center tackle may already be working this ticket. Point at it instead of
  // quietly starting a second session.
  const liveTickets = useLiveTickets()
  const other = liveTickets.get(issueKey)
  const elsewhere = other && other.fp !== `jira-${issueKey}` && other.session_id ? other : undefined
  const start = async () => {
    setBusy(true)
    setErr('')
    try {
      await postJiraTackle(issueKey, ctx.trim())
      setAsk(false)
      setCtx('')
      reload()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className={`tj${compact ? ' tj-compact' : ''}`}>
      <div className="tj-row">
        {opening ? (
          <Button size="sm" variant="primary" loading>
            Opening in Hermes...
          </Button>
        ) : (
          <Button
            size="sm"
            variant="primary"
            onClick={() => setAsk(true)}
            data-tip="Work this ticket in a Hermes session. Nothing is posted to Jira until I say so."
          >
            {rec?.session_id || elsewhere ? 'Tackle again' : 'Tackle'}
          </Button>
        )}
        {elsewhere && !opening && !live && (
          <LinkButton href={hermesSessionUrl(elsewhere.session_id ?? '')} data-tip={sessionHint(elsewhere)}>
            Open session
          </LinkButton>
        )}
        {rec?.session_id && !opening && (
          <LinkButton href={hermesSessionUrl(rec.session_id)}>
            {live ? 'Open session' : rec.state === 'resolved' ? 'Open thread (done)' : 'Open thread'}
          </LinkButton>
        )}
      </div>
      {(err || rec?.state === 'failed') && (
        <p className="tj-err" role="alert">
          {err || rec?.error || 'Could not open Hermes.'}
        </p>
      )}
      <Modal
        open={ask && !opening}
        onClose={() => setAsk(false)}
        title={`Tackle ${issueKey} in Hermes`}
        subtitle={summary || 'Work this ticket in a Hermes session. Nothing is posted to Jira until I say so.'}
        hue="violet"
        size="md"
        busy={busy}
        onSubmit={start}
        primaryAction={{ label: 'Start in Hermes', loading: busy }}
      >
        <Field label="Anything the assistant should know first?" optional hint="Cmd+Enter starts, Esc cancels.">
          <Textarea
            rows={4}
            value={ctx}
            data-autofocus=""
            onChange={(e) => setCtx(e.target.value)}
            placeholder="Anything the assistant should know first? (optional, Cmd+Enter starts)"
          />
        </Field>
      </Modal>
    </div>
  )
}
