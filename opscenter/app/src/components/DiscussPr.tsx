// "Discuss with the assistant" on a PR that needs me: opens a Hermes desktop chat that re-reads the
// PR, explains each concern with a recommendation, and waits for my direction before it acts.
// Session state comes from the shared tackle store (key pr-repo-<n>).
import { Button, Field, Textarea } from '@kit'
import { useState } from 'react'
import { hermesSessionUrl, postReviewDiscuss, useTackleSessions } from '../lib/data'
import { ErrorLine, LinkButton } from '../pages/reviews/parts'

export function DiscussPr({ repo, pr }: { repo: string; pr: number }) {
  const { data, reload } = useTackleSessions()
  const rec = data?.[`pr-${repo}-${pr}`]
  const [ask, setAsk] = useState(false)
  const [ctx, setCtx] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const opening = busy || rec?.state === 'launching' || rec?.state === 'claimed'
  const start = async () => {
    setBusy(true)
    setErr('')
    try {
      await postReviewDiscuss(repo, pr, ctx.trim())
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
    <div className="rh-discuss">
      {rec?.session_id && !opening && (
        <LinkButton href={hermesSessionUrl(rec.session_id)} external={false}>
          Open discussion
        </LinkButton>
      )}
      {opening ? (
        <Button size="sm" loading>
          Opening in Hermes...
        </Button>
      ) : (
        <Button size="sm" aria-expanded={ask} onClick={() => setAsk((a) => !a)}>
          {rec?.session_id ? 'Discuss again' : 'Discuss with the assistant'}
        </Button>
      )}
      {ask && !opening && (
        <div className="rh-discuss-ask">
          <Field label="Talking points" optional hint="Cmd or Ctrl and Enter starts it">
            <Textarea
              rows={3}
              value={ctx}
              onChange={(e) => setCtx(e.target.value)}
              placeholder="What do you want to talk through? (optional)"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) start()
              }}
            />
          </Field>
          <Button size="sm" variant="primary" onClick={start}>
            Start session
          </Button>
        </div>
      )}
      {(err || rec?.state === 'failed') && <ErrorLine>{err || rec?.error || 'Could not open Hermes.'}</ErrorLine>}
    </div>
  )
}
