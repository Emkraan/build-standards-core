// Shared building blocks of the Reviews hub (platform and team), all on the kit: status tags with
// the live spinner, the PR reference chip, the review item layout, result notes, the inline text
// toggle, and the loading and error states. Styles live in ../ReviewsHub.css (rh-*).
import type { CategoricalHue, StatusTone } from '@kit'
import { Card, cx, EmptyState, IconAlert, Pill, Skeleton, StatusDot } from '@kit'
import type { ReactNode } from 'react'
import '../../components/StateLegend.css'
import { useJob, WatcherChip } from '../../components/Watcher'
import type { CardWatch, ReviewActed } from '../../lib/data'

export type Tone = 'good' | 'warn' | 'alert' | 'info' | 'neutral'

// One colour per card state, the same on every review card in the Ops Center, so the board reads at a
// glance: red nothing moves it on its own, amber it waits on me, blue something runs now, grey it is
// parked on a named event, green it ships next pass. Live work always wins (blue) over the rest.
export type CardState = 'stuck' | 'needs_you' | 'in_progress' | 'waiting' | 'ready'
export const CARD_STATE_HUE: Record<CardState, CategoricalHue | 'ink'> = {
  stuck: 'red',
  needs_you: 'amber',
  in_progress: 'blue',
  waiting: 'ink',
  ready: 'green',
}
export const CARD_STATE_LABEL: Record<CardState, string> = {
  stuck: 'Stuck, nothing moves it on its own',
  needs_you: 'Waiting on me',
  in_progress: 'In progress',
  waiting: 'Parked on a named event',
  ready: 'Ready, ships next pass',
}

/** The colour key for card states, shown once above a list. A page can rename states for its own
    items and leave out states it never shows. */
export function StateLegend({
  labels,
  states = ['stuck', 'needs_you', 'in_progress', 'waiting', 'ready'],
}: {
  labels?: Partial<Record<CardState, string>>
  states?: CardState[]
} = {}) {
  return (
    <ul className="rh-legend" aria-label="State colours">
      {states.map((s) => (
        <li key={s} className={cx('rh-legend-item', `hue-${CARD_STATE_HUE[s]}`)}>
          <span className="rh-legend-swatch" aria-hidden="true" />
          {labels?.[s] ?? CARD_STATE_LABEL[s]}
        </li>
      ))}
    </ul>
  )
}

const STATUS: Record<Tone, StatusTone> = { good: 'success', warn: 'warning', alert: 'danger', info: 'info', neutral: 'neutral' }

export const riskTone = (r?: string | null): Tone => (r === 'high' ? 'alert' : r === 'medium' ? 'warn' : r === 'low' ? 'good' : 'neutral')
export const recTone = (r?: string | null): Tone => (r === 'approve' ? 'good' : r === 'reject' ? 'alert' : 'warn')

/** Waiting age as 12m, 5h or 3d. Old = over two hours, the point it turns red. */
export function age(iso: string | undefined | null, now: number): { text: string; old: boolean } {
  if (!iso) return { text: '?', old: false }
  const h = (now - new Date(iso).getTime()) / 36e5
  const text = h < 1 ? `${Math.max(1, Math.round(h * 60))}m` : h < 48 ? `${Math.round(h)}h` : `${Math.round(h / 24)}d`
  return { text, old: h > 2 }
}

/** A status tag (kit Pill). live = work is running right now, so a spinner ring leads the label. */
export function Tag({ tone = 'neutral', live, children }: { tone?: Tone; live?: boolean; children: ReactNode }) {
  return (
    <Pill tone={STATUS[tone]} className={live ? 'rh-tag-live' : undefined}>
      {live && <span className="rh-spin" aria-hidden="true" />}
      {children}
    </Pill>
  )
}

/** The PR or run number as a mono chip that opens it on GitHub. */
export function PrRef({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a className="rh-ref" href={href} target="_blank" rel="noreferrer">
      {children}
    </a>
  )
}

/** A link styled as a small secondary kit button (Open PR, Open run, Open discussion). */
export function LinkButton({ href, children, external = true }: { href: string; children: ReactNode; external?: boolean }) {
  return (
    <a
      className="btn rh-linkbtn-solid"
      data-variant="secondary"
      data-size="sm"
      href={href}
      target={external ? '_blank' : undefined}
      rel={external ? 'noreferrer' : undefined}
    >
      {children}
    </a>
  )
}

/** An inline text toggle inside a sentence (show files, hide resources). */
export function TextToggle({ onClick, children, expanded }: { onClick: () => void; children: ReactNode; expanded?: boolean }) {
  return (
    <button type="button" className="rh-textbtn" onClick={onClick} aria-expanded={expanded}>
      {children}
    </button>
  )
}

/**
 * One review item: the reference chip and status tags, the title, a meta line, the detail, and the
 * action column on the right. tone washes the item in a hue (the .tone recipe, never an edge bar).
 */
export function ReviewItem({
  state,
  working,
  top,
  title,
  meta,
  children,
  actions,
  pulse,
}: {
  // Where the card is at. Live work on it (working, or its cron watcher running) shows blue whatever
  // this says, so a card never looks parked while something acts on it.
  state?: CardState
  working?: boolean
  // The card itself: carries the cron watcher the server attached.
  pulse?: CardWatch
  top: ReactNode
  title: ReactNode
  meta?: ReactNode
  children?: ReactNode
  actions?: ReactNode
}) {
  const job = useJob(pulse?.watcher)
  const busy = working || job.working
  const shown: CardState | undefined = busy ? 'in_progress' : state
  return (
    <article
      className={cx('rh-item', shown && `tone hue-${CARD_STATE_HUE[shown]}`)}
      data-state={shown}
      title={shown ? CARD_STATE_LABEL[shown] : undefined}
      aria-busy={busy || undefined}
    >
      <div className="rh-item-main">
        <div className="rh-item-top">
          {top}
          {job.working && !working && (
            <Tag tone="info" live>
              session on it
            </Tag>
          )}
        </div>
        <h3 className="rh-item-title">{title}</h3>
        {meta && <div className="rh-meta">{meta}</div>}
        {pulse && <WatcherChip pulse={pulse} />}
        {children}
      </div>
      {actions && <div className="rh-item-actions">{actions}</div>}
    </article>
  )
}

/** A secondary line under the meta line (hold summary, Next, recommendation). */
export function Line({ children }: { children: ReactNode }) {
  return <p className="rh-line">{children}</p>
}

/** The result of an action, next to the item it acted on. */
export function ResultNote({ msg }: { msg: { ok: boolean; text: string } | null }) {
  if (!msg) return null
  return <ErrorLine ok={msg.ok}>{msg.text}</ErrorLine>
}

export function ErrorLine({ ok = false, children }: { ok?: boolean; children: ReactNode }) {
  return (
    <p className="rh-note" data-tone={ok ? 'success' : 'danger'} role={ok ? 'status' : 'alert'}>
      <StatusDot tone={ok ? 'success' : 'danger'} pulse={false} />
      <span>{children}</span>
    </p>
  )
}

/** Shown in place of the actions while work runs on the PR, so nothing can disrupt it. */
export function Locked() {
  return <span className="rh-locked">Actions return when this finishes</span>
}

/** Bulleted reasons. tone alert = a hold or an error, neutral = what I am signing off on. */
export function Reasons({ items, tone = 'alert' }: { items: ReactNode[]; tone?: 'alert' | 'neutral' }) {
  if (!items.length) return null
  return (
    <ul className="rh-reasons" data-tone={tone}>
      {items.map((r, i) => (
        <li key={i}>{r}</li>
      ))}
    </ul>
  )
}

export function LoadingCard({ label }: { label: string }) {
  return (
    <Card>
      <Skeleton variant="lines" count={5} label={label} />
    </Card>
  )
}

export function ErrorCard({ title, error }: { title: string; error: string }) {
  return (
    <Card>
      <EmptyState compact icon={<IconAlert />} hue="red" title={title} body={error} />
    </Card>
  )
}

/** Labels for what I just did, while GitHub and the lanes catch up. */
const ACTED_TEXT: Record<ReviewActed['outcome'], string> = {
  merged: 'Merged',
  approved: 'Approved',
  closed: 'Closed',
}

/** Optimistic entry for a PR I just acted on, so it never flickers back before the server agrees. */
export function actedNow(pr: number, title: string, outcome: ReviewActed['outcome'], note = ''): ReviewActed {
  return { pr, title, outcome, note, age_s: 0 }
}

/** never say a PR merges while its merge sign-off is still open on Needs me. */
export function actedMeta(a: ReviewActed): string {
  if (a.outcome === 'approved') {
    if (a.still_needs_me) return ', the merge still needs your sign-off (Needs me)'
    return a.what === 'plan' ? ', the PR itself is not merged yet' : ', merges when checks pass'
  }
  return a.confirmed ? ', done' : ', GitHub catching up'
}

/** PRs I acted on in the last few minutes. They leave Needs me at once and show here instead. */
export function JustActed({ items }: { items?: ReviewActed[] }) {
  if (!items?.length) return null
  return (
    <div className="rh-acted" aria-live="polite">
      <h3 className="rh-subhead">Just acted on</h3>
      <ul>
        {items.map((a) => (
          <li key={`${a.pr}-${a.outcome}`}>
            <StatusDot tone={a.outcome === 'closed' ? 'neutral' : 'success'} pulse={false} />
            <span>
              {a.what === 'plan' ? 'Approved the terraform plan run for' : ACTED_TEXT[a.outcome] || a.outcome} #{a.pr}
              {a.title ? ` ${a.title}` : ''}
            </span>
            <span className="rh-acted-meta">
              {a.age_s < 60 ? 'just now' : `${Math.round(a.age_s / 60)}m ago`}
              {actedMeta(a)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
