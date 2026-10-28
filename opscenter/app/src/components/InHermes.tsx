// "in Hermes" marker: shows on a Jira ticket (Sprint card, Backlog row, Action Center row)
// when a live Hermes session is working it, from either the Jira hub or the Action Center, and
// links straight to that session. Ops Center only: nothing is written to Jira.
import { type SyntheticEvent, useMemo } from 'react'
import type { TicketSession } from '../lib/data'
import { hermesSessionUrl, liveByTicket, useTackleSessions } from '../lib/data'

export function useLiveTickets() {
  const { data } = useTackleSessions()
  return useMemo(() => liveByTicket(data), [data])
}

function ago(iso?: string) {
  if (!iso) return ''
  const m = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60000))
  if (m < 1) return 'just now'
  if (m < 60) return `${m}m ago`
  const h = Math.round(m / 60)
  return h < 48 ? `${h}h ago` : `${Math.round(h / 24)}d ago`
}

export function sessionHint(s: TicketSession) {
  const where = s.from === 'jira' ? 'the Jira hub' : 'the Action Center'
  return `Started from ${where}. ${s.last_active ? `Last active ${ago(s.last_active)}.` : 'Opening now.'}`
}

export function InHermes({ ticket, session }: { ticket?: string; session?: TicketSession }) {
  const live = useLiveTickets()
  const s = session || (ticket ? live.get(ticket.toUpperCase()) : undefined)
  if (!s) return null
  const stop = (e: SyntheticEvent) => e.stopPropagation()
  if (!s.session_id)
    return (
      <span className="ih-pill opening" title={sessionHint(s)}>
        opening in Hermes
      </span>
    )
  return (
    <a className="ih-pill" href={hermesSessionUrl(s.session_id)} onClick={stop} onKeyDown={stop} title={`${sessionHint(s)} Click to open.`}>
      <span className="ih-dot" />
      in Hermes{s.last_active ? ` \u00b7 ${ago(s.last_active)}` : ''}
    </a>
  )
}
