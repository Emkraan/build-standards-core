/* Panel and Row. Panel is the one card surface (radius, border and padding from tokens). Row is the
   one dense list row: a leading status dot or icon, a title, one line of meta, a right side (a time,
   a badge, an action), hover and focus states, and the whole row clickable when it links. Rows link
   through the shell's link component, so the kit stays router agnostic. */

import type { ElementType, HTMLAttributes, ReactNode } from 'react';
import { IconChevronRight } from '../icons/icons';
import { cx } from '../lib/env';
import { StatusDot } from '../primitives/marks';
import type { DotTone } from '../primitives/marks';
import { DefaultLink, GuardedLink, useShell } from '../shell/context';

export interface PanelProps extends Omit<HTMLAttributes<HTMLElement>, 'className'> {
  as?: ElementType | undefined;
  /** A state tone wash (stuck, waiting, ready). Never an accent. */
  tone?: 'danger' | 'warning' | 'info' | 'success' | undefined;
  /** No inner padding, for a Panel that holds a table or a Row list. */
  flush?: boolean | undefined;
  /** The whole Panel is a button or a link: hover, focus ring, pointer. */
  interactive?: boolean | undefined;
  /** The picked one of a set of interactive Panels. */
  selected?: boolean | undefined;
  className?: string | undefined;
  children?: ReactNode;
}

export function Panel({ as: Tag = 'div', tone, flush, interactive, selected, className, children, ...rest }: PanelProps) {
  return (
    <Tag
      {...rest}
      className={cx('hp-panel', className)}
      data-tone={tone}
      data-flush={flush ? '' : undefined}
      data-interactive={interactive ? '' : undefined}
      data-selected={selected ? '' : undefined}
    >
      {children}
    </Tag>
  );
}

export interface RowProps {
  title: ReactNode;
  /** One line under the title. */
  meta?: ReactNode;
  /** A leading state dot. It carries its own text for assistive technology. */
  dot?: DotTone | undefined;
  /** Or a leading icon. */
  icon?: ReactNode;
  /** The right side: a time, a Badge or StatusPill, an action. */
  right?: ReactNode;
  /** Wrapping detail under the title and meta (what it is, what happens next, links). */
  detail?: ReactNode;
  /** Makes the whole row a link inside the app. */
  to?: string | undefined;
  /** Or an external link. */
  href?: string | undefined;
  onClick?: (() => void) | undefined;
  className?: string | undefined;
}

export function Row({ title, meta, dot, icon, right, detail, to, href, onClick, className }: RowProps) {
  const shell = useShell();
  const inner = (
    <>
      {dot ? (
        <span className="hp-row-lead">
          <StatusDot tone={dot} label={dot} pulse={false} />
        </span>
      ) : icon ? (
        <span className="hp-row-icon">{icon}</span>
      ) : null}
      <span className="hp-row-main">
        <span className="hp-row-title">{title}</span>
        {meta ? <span className="hp-row-meta">{meta}</span> : null}
        {detail ? <span className="hp-row-detail">{detail}</span> : null}
      </span>
      {right ? <span className="hp-row-right">{right}</span> : null}
      {to || href || onClick ? (
        <span className="hp-row-chev" aria-hidden="true">
          <IconChevronRight size={14} />
        </span>
      ) : null}
    </>
  );
  const cls = cx('hp-row', detail ? 'hp-row-tall' : undefined, className);
  if (to) {
    return (
      <GuardedLink Link={shell?.Link ?? DefaultLink} className={cls} href={to}>
        {inner}
      </GuardedLink>
    );
  }
  if (href) {
    return (
      <GuardedLink Link={DefaultLink} className={cls} href={href} target="_blank" rel="noreferrer">
        {inner}
      </GuardedLink>
    );
  }
  if (onClick) {
    return (
      <button type="button" className={cls} onClick={onClick}>
        {inner}
      </button>
    );
  }
  return <div className={cls}>{inner}</div>;
}
