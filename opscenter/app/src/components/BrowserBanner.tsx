import { Button } from '@kit'
import { useState } from 'react'
import { postBrowserHide, relTime, useBrowserStatus } from '../lib/data'
import AlertBanner from './AlertBanner'

// the shared automation Edge (CDP 9333) runs headless. `cdp-edge show`
// opens a visible window for an SSO or MFA sign-in, and `cdp-edge hide` puts it
// back. This line shows when a window has been left up past 15 minutes or the
// browser has been down past 2 minutes, with a one-click return to headless.
export default function BrowserBanner() {
  const { data, mutate } = useBrowserStatus()
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  if (!data?.alert) return null
  const fix = () => {
    setBusy(true)
    setErr('')
    postBrowserHide()
      .then((d) => mutate(() => d))
      .catch((e) => setErr(String(e).replace(/^Error: /, '')))
      .finally(() => setBusy(false))
  }
  const visible = data.alert === 'visible'
  return (
    <AlertBanner
      title={visible ? 'The automation browser is still showing a window' : 'The automation browser is down'}
      action={
        <Button size="sm" variant="secondary" loading={busy} disabled={busy} onClick={fix}>
          {busy ? 'Working...' : 'Return to headless'}
        </Button>
      }
    >
      {visible
        ? `Edge on port 9333 has been visible since ${relTime(data.since_utc)} (${data.pages} page${data.pages === 1 ? '' : 's'}). Sign-in windows should go back to headless when the sign-in is done.`
        : `Nothing has answered on port 9333 since ${relTime(data.since_utc)}, so browser work will fail. ${data.agent_loaded ? 'The keep-alive agent is loaded.' : 'The keep-alive agent is unloaded.'}`}
      {err && ` ${err}`}
    </AlertBanner>
  )
}
