/* Header (every page), PageHeader (the page title block) and Toolbar (the actions row above the
   content it acts on). Rules by shape: the header holds the one way home (rule 9), the page header
   takes no actions (rule 6), and Refresh comes first among the toolbar actions. */

import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { IconHome, IconMenu, IconRefresh } from '../icons/icons';
import { cx } from '../lib/env';
import { CLOCK_TICK } from '../lib/timing';
import { DefaultLink, GuardedLink, useShell } from './context';
import { HelpButton } from './HelpButton';

export interface HeaderProps {
  /** The current tool or area name. Plain text, never a link. */
  title: string;
  subtitle?: string | undefined;
  /** The only route home (rule 9). Logos, breadcrumbs and grid icons are never links. */
  home?: { href: string; label?: string | undefined } | undefined;
  /** Middle slot, for example a search trigger. */
  children?: ReactNode;
  /** Right slot: copy link, theme toggle. */
  actions?: ReactNode;
  menuLabel?: string | undefined;
  /** Shows the Help button while the page on screen registered help with usePageHelp. Default true. */
  help?: boolean | undefined;
  helpLabel?: string | undefined;
}

export function Header({ title, subtitle, home, children, actions, menuLabel = 'Open navigation', help = true, helpLabel }: HeaderProps) {
  const shell = useShell();
  const Link = shell?.Link ?? DefaultLink;
  return (
    <header className="app-header">
      {shell ? (
        <button
          ref={shell.menuButtonRef}
          type="button"
          className="btn menu-btn"
          data-variant="ghost"
          data-icon-only=""
          aria-label={menuLabel}
          data-tip={menuLabel}
          aria-expanded={shell.mobileOpen}
          aria-controls={shell.sidebarId}
          onClick={() => shell.setMobileOpen(true)}
        >
          <IconMenu />
        </button>
      ) : null}
      <div className="header-titles">
        <p className="header-title">{title}</p>
        {subtitle ? <p className="header-sub">{subtitle}</p> : null}
      </div>
      {children ? <div className="header-center">{children}</div> : null}
      <div className="header-actions">
        {home ? (
          <GuardedLink Link={Link} href={home.href} className="hub-btn">
            <IconHome />
            <span>{home.label ?? 'Home'}</span>
          </GuardedLink>
        ) : null}
        {help ? <HelpButton label={helpLabel} /> : null}
        {actions}
      </div>
    </header>
  );
}

export interface PageHeaderProps {
  title: string;
  /** One line saying what the page is for. */
  subtitle?: string | undefined;
  eyebrow?: string | undefined;
  /** Status badges only (for example "Webhook configured"). Actions go in a Toolbar. */
  status?: ReactNode;
  /** Opt in to the tinted header: the accent wash, a hairline accent ring and a top light. Off by default, so a plain header looks as before. */
  wash?: boolean | undefined;
}

/** The page title block. It takes no actions by design (rule 6). */
export function PageHeader({ title, subtitle, eyebrow, status, wash }: PageHeaderProps) {
  return (
    <div className="page-header" data-wash={wash ? '' : undefined}>
      <div className="page-header-text">
        {eyebrow ? <p className="page-eyebrow">{eyebrow}</p> : null}
        <h1 className="page-title">{title}</h1>
        {subtitle ? <p className="page-sub">{subtitle}</p> : null}
      </div>
      {status ? <div className="page-status">{status}</div> : null}
    </div>
  );
}

/** "updated just now", "updated 12s ago", "updated 4 min ago", "updated 2 h ago". */
export function formatUpdated(elapsedMs: number): string {
  const s = Math.max(0, Math.floor(elapsedMs / 1000));
  if (s < 2) return 'Updated just now';
  if (s < 90) return `Updated ${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 90) return `Updated ${m} min ago`;
  return `Updated ${Math.round(m / 60)} h ago`;
}

/** The current time, refreshed every `interval` ms while `active`. An interval under one second
    is raised to one second, and one that is not a finite number falls back to the default. */
export function useNow(active: boolean, interval: number = CLOCK_TICK): number {
  const [now, setNow] = useState(() => Date.now());
  const every = Number.isFinite(interval) ? Math.max(1000, interval) : CLOCK_TICK;
  useEffect(() => {
    if (!active) return undefined;
    setNow(Date.now());
    const t = window.setInterval(() => setNow(Date.now()), every);
    return () => window.clearInterval(t);
  }, [active, every]);
  return now;
}

export interface ToolbarProps {
  /** Filters and search, on the left. */
  children?: ReactNode;
  /** Add, Import, Export and the like, on the right after Refresh. */
  actions?: ReactNode;
  onRefresh?: (() => void) | undefined;
  refreshing?: boolean | undefined;
  /** When the data last arrived. Shows a ticking freshness label. */
  updatedAt?: Date | number | null | undefined;
  refreshLabel?: string | undefined;
  /** Accessible name of the toolbar group. */
  label?: string | undefined;
  className?: string | undefined;
}

/** The actions row directly above a table, card grid or list. Refresh is first and icon-only. */
export function Toolbar({
  children,
  actions,
  onRefresh,
  refreshing = false,
  updatedAt,
  refreshLabel = 'Refresh',
  label = 'Actions',
  className,
}: ToolbarProps) {
  const at = updatedAt instanceof Date ? updatedAt.getTime() : updatedAt ?? null;
  const now = useNow(at !== null);
  return (
    <div className={cx('toolbar', className)} role="group" aria-label={label}>
      {children ? <div className="toolbar-start">{children}</div> : null}
      <span className="toolbar-sp" />
      {at !== null ? (
        <span className="toolbar-updated" aria-live="off">
          {formatUpdated(now - at)}
        </span>
      ) : null}
      {onRefresh || actions ? (
        <div className="toolbar-actions">
          {onRefresh ? (
            <button
              type="button"
              className="btn"
              data-variant="secondary"
              data-size="sm"
              data-icon-only=""
              aria-label={refreshLabel}
              data-tip={refreshLabel}
              disabled={refreshing}
              aria-busy={refreshing || undefined}
              onClick={onRefresh}
            >
              <IconRefresh className={refreshing ? 'is-spinning' : undefined} />
            </button>
          ) : null}
          {actions}
        </div>
      ) : null}
    </div>
  );
}
