/* Navigation items for the rail. The icon carries the destination's categorical hue in every
   state (`brand` follows the app accent), and the gliding marker alone shows the active link. */

import { useId } from 'react';
import type { AnchorHTMLAttributes, MouseEvent, ReactNode } from 'react';
import { cx } from '../lib/env';
import type { NavHue } from '../lib/hues';
import { Spinner } from '../primitives/Spinner';
import { DefaultLink, GuardedLink, useShell } from './context';

export interface NavItemProps extends Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'children' | 'href'> {
  href: string;
  label: string;
  icon?: ReactNode;
  /** Destination hue. Identifies the place, never the selection. */
  hue?: NavHue | undefined;
  /** True for the current page. Sets aria-current="page". */
  active?: boolean | undefined;
  /** A small count or tag. Hidden while the rail is collapsed, where `iconBadge` stands in. */
  badge?: ReactNode;
  /** A secondary count in a quiet outline after the badge, for example items waiting on others.
      Hidden while the rail is collapsed. */
  softBadge?: ReactNode;
  /** A count or dot on the icon, shown only while the rail is collapsed (where the badge itself is
      hidden). Defaults to `badge` when that is a string or a number. `'dot'` shows a plain dot,
      `false` shows nothing. */
  iconBadge?: ReactNode | 'dot' | false;
  /** Shows a working spinner in the soft badge (on its own when there is no soft count). */
  working?: boolean | undefined;
  /** Screen reader text for `working`. Default "Working". */
  workingLabel?: string | undefined;
}

export function NavItem({
  href,
  label,
  icon,
  hue,
  active,
  badge,
  softBadge,
  iconBadge,
  working = false,
  workingLabel = 'Working',
  className,
  onClick,
  ...rest
}: NavItemProps) {
  const shell = useShell();
  const Link = shell?.Link ?? DefaultLink;
  const hasNode = (n: ReactNode) => n !== undefined && n !== null && n !== false && n !== '';
  const count = iconBadge === undefined ? (typeof badge === 'string' || typeof badge === 'number' ? badge : undefined) : iconBadge;
  const dot = count === 'dot' || (iconBadge === undefined && hasNode(badge) && !hasNode(count));
  const showCount = !dot && hasNode(count);
  return (
    <GuardedLink
      {...rest}
      Link={Link}
      href={href}
      className={cx('nav-item', className)}
      aria-current={active ? 'page' : undefined}
      onClick={(event: MouseEvent<HTMLAnchorElement>) => {
        onClick?.(event);
        // A handler that cancels the navigation (an unsaved changes guard) keeps the drawer open.
        if (event.defaultPrevented) return;
        shell?.setMobileOpen(false);
      }}
    >
      {icon ? (
        <span className="nav-icon" data-hue={hue} aria-hidden="true">
          {icon}
        </span>
      ) : null}
      <span className="nav-label">{label}</span>
      {dot ? <span className="nav-icon-count" data-dot="" /> : null}
      {showCount ? <span className="nav-icon-count">{count}</span> : null}
      {badge !== undefined && badge !== null ? <span className="badge nav-badge">{badge}</span> : null}
      {(softBadge !== undefined && softBadge !== null) || working ? ' ' : null}
      {(softBadge !== undefined && softBadge !== null) || working ? (
        <span className="badge nav-badge nav-badge-soft" data-working={working ? '' : undefined}>
          {working ? <Spinner size="xs" /> : null}
          {working ? <span className="kit-sr-only">{workingLabel}</span> : null}
          {working && softBadge !== undefined && softBadge !== null ? ' ' : null}
          {softBadge}
        </span>
      ) : null}
    </GuardedLink>
  );
}

export interface NavGroupProps {
  label: string;
  children?: ReactNode;
}

/** A labelled group of nav items. The label hides while the rail is collapsed. */
export function NavGroup({ label, children }: NavGroupProps) {
  const id = `${useId()}-group`;
  return (
    <div className="nav-section" role="group" aria-labelledby={id}>
      <div className="nav-group nav-group-label" id={id}>
        {label}
      </div>
      {children}
    </div>
  );
}
