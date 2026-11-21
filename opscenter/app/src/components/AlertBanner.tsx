// A system notice above a page: the kit Notice row (tone icon, one line title, one action, a chevron that opens the detail), the same
// row the notice tray draws (ops-center-layout rule 18). The old name stays because every alert in the app already calls it. A notice
// clears itself when the condition ends, so there is no dismiss control.
import { Notice } from '@kit'
import type { ReactNode } from 'react'

export default function AlertBanner({
  tone = 'critical',
  title,
  children,
  action,
}: {
  tone?: 'critical' | 'warning' | 'info'
  title: ReactNode
  children?: ReactNode
  action?: ReactNode
}) {
  return <Notice tone={tone} title={title} detail={children} action={action} />
}
