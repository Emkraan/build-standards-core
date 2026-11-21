// Pairing and alerts (Platform, Host and access, Device access; standards/hermes-api-access.md sections 5 and 6): status of the API path,
// pair a device with a QR that shows for 60 seconds and never as text, the paired devices with Test and Remove (each confirmed), and the
// setup steps while no phone provider is configured. The link is held only long enough to draw the QR: it is never kept in state, stored,
// logged or put in a URL, and the QR clears when the time is up or the page goes away.
import { Alert, Button, Card, CardHead, EmptyState, Pill, Skeleton, useConfirm } from '@kit'
import { useEffect, useRef, useState } from 'react'
import type { PhoneStatus } from '../lib/data'
import { postPhonePair, postPhoneRemove, postPhoneTest, relTime, usePhoneAccess } from '../lib/data'

const CHECKS: { key: keyof PhoneStatus; label: string }[] = [
  { key: 'api_reachable', label: 'API server reachable' },
  { key: 'edge_covers_host', label: 'Edge certificate covers the host' },
  { key: 'plugin_pinned', label: 'Push plugin is pinned' },
  { key: 'plugin_matches_pin', label: 'Installed plugin matches the pin' },
  { key: 'only_api_connected', label: 'Only the API server is connected' },
]

export const SETUP_STEPS = [
  'Install the push plugin from its pinned commit: python3 hermes/phone_access.py plugin',
  'Stage the API server key once and create the private certificate authority and the edge certificate (hermes/api-access-setup.md).',
  'Set OPSCENTER_PHONE_PROVIDER to a provider file for the plugin (opscenter/DESIGN.md 12.77), then reload this page.',
]

function QrPair() {
  const [svg, setSvg] = useState<string | null>(null)
  const [left, setLeft] = useState(0)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const timer = useRef<number | null>(null)
  const clear = () => {
    if (timer.current) window.clearInterval(timer.current)
    timer.current = null
    setSvg(null)
    setLeft(0)
  }
  useEffect(() => () => {
    if (timer.current) window.clearInterval(timer.current)
  }, [])
  const pair = async () => {
    setBusy(true)
    setErr('')
    try {
      const { link, expires_in } = await postPhonePair()
      const { default: qrcode } = await import('qrcode-generator')
      const qr = qrcode(0, 'M')
      qr.addData(link)
      qr.make()
      setSvg(qr.createSvgTag({ cellSize: 5, margin: 4, scalable: true }))
      setLeft(expires_in)
      if (timer.current) window.clearInterval(timer.current)
      timer.current = window.setInterval(() => {
        setLeft((n) => {
          if (n <= 1) {
            window.setTimeout(clear, 0)
            return 0
          }
          return n - 1
        })
      }, 1000)
    } catch (e) {
      setErr(String(e).replace(/^Error: /, ''))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Card>
      <CardHead title="Pair a device" />
      <p className="infra-muted">
        The code is shown as a QR on this computer only, for 60 seconds. It is never written out as text, logged or kept. The push relay can see that a push
        happened and when.
      </p>
      {svg ? (
        <div className="pair-qr">
          <div role="img" aria-label="Pairing QR code" className="pair-qr-img" dangerouslySetInnerHTML={{ __html: svg }} />
          <p role="timer">Scan it now. It clears in {left} s.</p>
          <Button variant="secondary" size="sm" onClick={clear}>
            Hide now
          </Button>
        </div>
      ) : (
        <Button loading={busy} disabled={busy} onClick={pair}>
          Show pairing QR
        </Button>
      )}
      {err && <Alert tone="danger">{err}</Alert>}
    </Card>
  )
}

function Status({ status }: { status: PhoneStatus }) {
  return (
    <Card>
      <CardHead title="Status" />
      <ul className="pair-checks">
        {CHECKS.map((c) => {
          const v = status[c.key]
          return (
            <li key={c.key}>
              <span>{c.label}</span>
              <Pill tone={v === true ? 'success' : v === false ? 'danger' : 'neutral'}>{v === true ? 'OK' : v === false ? 'Not OK' : 'Unknown'}</Pill>
            </li>
          )
        })}
      </ul>
    </Card>
  )
}

export default function PhoneAccess() {
  const { data, error, refresh } = usePhoneAccess()
  const { confirm, dialog } = useConfirm()
  const [msg, setMsg] = useState('')
  if (!data) return error ? <Alert tone="danger">The phone access page did not load: {error}</Alert> : <Skeleton variant="lines" count={4} label="Loading device access" />
  if (!data.configured) {
    return (
      <EmptyState
        title="Device pairing is not set up"
        body="No push plugin is connected to this ops center yet."
        action={
          <ol className="pair-steps">
            {SETUP_STEPS.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ol>
        }
      />
    )
  }
  const run = async (what: 'test' | 'remove', id: string, name: string) => {
    const ok = await confirm({
      title: what === 'test' ? `Send a test notification to ${name}?` : `Remove ${name}?`,
      body: what === 'test' ? 'The device gets one notification now.' : 'The device stops getting alerts and must be paired again.',
      confirmLabel: what === 'test' ? 'Send test' : 'Remove',
      danger: what === 'remove',
    })
    if (!ok) return
    try {
      const r = what === 'test' ? await postPhoneTest(id) : await postPhoneRemove(id)
      setMsg(r.ok ? (what === 'test' ? 'Test notification sent.' : 'Device removed.') : 'The provider reported a failure.')
      refresh()
    } catch (e) {
      setMsg(String(e).replace(/^Error: /, ''))
    }
  }
  return (
    <div className="infra-stack">
      {data.error && <Alert tone="danger">{data.error}. This is not the same as nothing being paired.</Alert>}
      <Status status={data.status} />
      <QrPair />
      <Card>
        <CardHead title="Paired devices" />
        {data.devices.length === 0 ? (
          <p className="infra-muted">No device is paired.</p>
        ) : (
          <ul className="pair-devices">
            {data.devices.map((d) => (
              <li key={d.id}>
                <span>
                  <strong>{d.name || d.id}</strong>
                  <span className="infra-muted">
                    {d.paired_at ? ` paired ${relTime(d.paired_at)}` : ''}
                    {d.last_seen ? `, last seen ${relTime(d.last_seen)}` : ''}
                  </span>
                </span>
                <span className="pair-actions">
                  <Button size="sm" variant="secondary" onClick={() => run('test', d.id, d.name || d.id)}>
                    Test notification
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => run('remove', d.id, d.name || d.id)}>
                    Remove
                  </Button>
                </span>
              </li>
            ))}
          </ul>
        )}
        {msg && <p role="status">{msg}</p>}
      </Card>
      {dialog}
    </div>
  )
}
