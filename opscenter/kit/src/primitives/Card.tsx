/* Card with the title-left, controls-right head (UI standard section 7). Tone washes the card in a
   categorical hue, selection raises it with a full hairline ring. Never an edge bar. */

import type { ElementType, HTMLAttributes, KeyboardEvent, ReactNode } from 'react';
import { cx } from '../lib/env';
import { InfoTip } from '../overlays/InfoTip';
import type { MarkHue } from '../lib/hues';

export interface CardProps extends HTMLAttributes<HTMLElement> {
  as?: 'div' | 'section' | 'article' | 'li' | undefined;
  /** Identity, status or severity: the .tone corner wash and tinted hairline. */
  tone?: MarkHue | undefined;
  /** Selected state: raised neutral surface with a full hairline ring. */
  selected?: boolean | undefined;
  elevated?: boolean | undefined;
  /** Lifts on hover. With an onClick the card is a button for the keyboard too: it takes focus and
      Enter or Space activate it. Leave onClick off when the card holds its own link or button. */
  interactive?: boolean | undefined;
}

export function Card({ as = 'div', tone, selected, elevated, interactive, className, children, onKeyDown, ...rest }: CardProps) {
  const Tag = as as ElementType;
  const clickable = Boolean(interactive && rest.onClick);
  const keys = (e: KeyboardEvent<HTMLElement>) => {
    onKeyDown?.(e);
    if (clickable && !e.defaultPrevented && e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault();
      e.currentTarget.click();
    }
  };
  return (
    <Tag
      {...(clickable ? { role: 'button', tabIndex: 0 } : {})}
      {...rest}
      onKeyDown={keys}
      className={cx('card', elevated && 'card-elevated', tone && `tone hue-${tone}`, selected && 'is-selected', interactive && 'card-interactive', className)}
    >
      {children}
    </Tag>
  );
}

export type CardHeadVariant = 'card' | 'panel' | 'label';

export interface CardHeadProps {
  title: ReactNode;
  subtitle?: ReactNode;
  /** Filters, toggles and the card's own actions, on the right. */
  controls?: ReactNode;
  /** Optional icon tile before the title. */
  icon?: ReactNode;
  /** A count after the title, such as the rows in the group below. */
  count?: ReactNode;
  /** Help for this card. A string shows as a visible info icon beside the title (tip on hover or focus,
      the same text in a popover on click). A node is placed there as given. Off when empty. */
  info?: ReactNode;
  /** Heading level of the title. Default 2. */
  level?: 2 | 3 | 4 | undefined;
  /**
   * card (default): the head inside a Card.
   * panel: the head of a panel or tab region that sits on the page rather than in a Card; the title
   * is one step larger, as the region's own heading.
   * label: a small uppercase label over a group of content, with an optional icon and count. It is
   * still a heading of `level`, so the group stays in the page outline.
   */
  variant?: CardHeadVariant | undefined;
  className?: string | undefined;
}

export function CardHead({ title, subtitle, controls, icon, count, info, level = 2, variant = 'card', className }: CardHeadProps) {
  const Heading = `h${level}` as 'h2' | 'h3' | 'h4';
  const hasInfo = info !== undefined && info !== null && info !== false && info !== '';
  const heading = (
    <Heading className="card-title">
      {title}
      {count === undefined || count === null ? null : <span className="card-head-count">{count}</span>}
    </Heading>
  );
  return (
    <div className={cx('card-head', variant !== 'card' && `card-head-${variant}`, className)}>
      <div className="card-head-text">
        {icon}
        <div className="card-titles">
          {hasInfo ? (
            <div className="card-title-row">
              {heading}
              {typeof info === 'string' ? <InfoTip short={info} label={typeof title === 'string' ? `About ${title}` : undefined} /> : info}
            </div>
          ) : (
            heading
          )}
          {subtitle ? <p className="card-sub">{subtitle}</p> : null}
        </div>
      </div>
      {controls ? <div className="card-controls">{controls}</div> : null}
    </div>
  );
}

export function CardBody({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div {...rest} className={cx('card-body', className)} />;
}
