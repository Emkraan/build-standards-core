// A system alert banner in the kit's announcement look (tone corner wash, tinted hairline, hue
// tile with a severity glyph). The kit AnnouncementBanner takes plain text only, and these alerts
// carry a link or a fix button, so the app renders the same .announce recipe itself. Alerts clear
// themselves when the condition ends, so there is no dismiss control.
import { IconAlert, IconInfo, IconWarning } from '@kit'
import type { ReactNode } from 'react'

const TONE = {
  critical: { hue: 'red', icon: <IconAlert />, label: 'Critical' },
  warning: { hue: 'amber', icon: <IconWarning />, label: 'Warning' },
  info: { hue: 'blue', icon: <IconInfo />, label: 'Information' },
} as const

export default function AlertBanner({
  tone = 'critical',
  title,
  children,
  action,
}: {
  tone?: keyof typeof TONE
  title: ReactNode
  children?: ReactNode
  action?: ReactNode
}) {
  const t = TONE[tone]
  return (
    <section className={`announce oc-alert hue-${t.hue}`} data-tone={tone} role="alert">
      <span className={`announce-icon hue-tile hue-${t.hue}`} role="img" aria-label={t.label}>
        {t.icon}
      </span>
      <div className="oc-alert-text">
        <h2 className="announce-title">{title}</h2>
        {children ? <p className="announce-body">{children}</p> : null}
      </div>
      {action ? <div className="oc-alert-action">{action}</div> : null}
    </section>
  )
}
