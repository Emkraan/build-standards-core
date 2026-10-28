// Small kit compositions shared by the Jira, Debt, Knowledge, Search and Completed pages: the
// load-failure block, the working pill (kit Pill plus the app spinner) and an external-link
// button that takes the kit Button look.
import type { StatusTone } from '@kit'
import { EmptyState, IconAlert, Pill } from '@kit'
import type { AnchorHTMLAttributes, ReactNode } from 'react'
import './StateBlocks.css'

/** A failed load inside a card: alert tile, a plain title, the error and an optional hint. */
export function LoadError({ title, error, hint }: { title: string; error?: string | null; hint?: ReactNode }) {
  return (
    <EmptyState
      compact
      icon={<IconAlert />}
      hue="red"
      title={title}
      body={
        <>
          {error ? <span className="sb-err">{error}</span> : null}
          {hint ? <span className="sb-hint">{hint}</span> : null}
        </>
      }
    />
  )
}

/** Something is working right now: the spinner ring before the label. */
export function LivePill({ children, tone = 'neutral' }: { children: ReactNode; tone?: StatusTone }) {
  return (
    <Pill tone={tone} className="ui-pill-live">
      <span className="spin" aria-hidden="true" />
      {children}
    </Pill>
  )
}

type LinkButtonProps = AnchorHTMLAttributes<HTMLAnchorElement> & {
  variant?: 'primary' | 'secondary' | 'ghost'
  size?: 'sm' | 'md'
  external?: boolean
}

/** A link styled as a kit Button (deep links to Jira, Confluence, the portal or a Hermes thread). */
export function LinkButton({ variant = 'secondary', size = 'sm', external = false, className, children, ...rest }: LinkButtonProps) {
  return (
    <a
      {...rest}
      className={className ? `btn ${className}` : 'btn'}
      data-variant={variant}
      data-size={size}
      target={external ? '_blank' : rest.target}
      rel={external ? 'noreferrer' : rest.rel}
    >
      {children}
    </a>
  )
}
