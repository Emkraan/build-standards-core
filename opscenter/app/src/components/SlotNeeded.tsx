// The page a disabled slot shows instead of a redirect (opscenter/DESIGN.md 12.72, replacing the redirect rule of 12.14 and 12.67):
// it names the slot, the switch that turns it on and the minimum a consumer supplies, so a disabled page is never mistaken for a broken route.
import { EmptyState } from '@kit'

const SLOTS = {
  tracker: {
    name: 'tracker',
    switch: 'OPSCENTER_TRACKER',
    body: 'Sprint, backlog, tickets that need my call and approvals come from a work tracker. The server serves them only while OPSCENTER_TRACKER is on and a tracker driver command is set (opscenter/DESIGN.md 12.67 and 12.15). A consumer on another tracker keeps the slot off and adds its own pages through the extension manifest (12.69).',
  },
  people: {
    name: 'people',
    switch: 'OPSCENTER_PEOPLE',
    body: 'The 1:1 topics, team performance, member reviews and yearly review come from a people provider. The server serves them only while OPSCENTER_PEOPLE names the provider file (opscenter/DESIGN.md 12.14). Without it the pages stay off and nothing else is affected.',
  },
} as const

export type SlotName = keyof typeof SLOTS

export default function SlotNeeded({ slot, page }: { slot: SlotName; page: string }) {
  const s = SLOTS[slot]
  return (
    <div className="slot-needed" data-slot={s.name}>
      <EmptyState title={`${page} needs the ${s.name} slot`} body={`This page is off because the ${s.name} slot is not on (${s.switch}). ${s.body}`} />
    </div>
  )
}
