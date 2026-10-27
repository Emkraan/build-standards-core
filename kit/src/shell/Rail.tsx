/* The desktop icon rail (UI standard sections 6 and 19): 58px of icons at rest, opens over the page
   on hover or focus, pins with the pin button or the [ key, and marks the active link with one
   gliding highlight. Below 900px the same sidebar is the mobile drawer. */

import { useRef } from 'react';
import type { ReactNode, RefObject } from 'react';
import { IconClose, IconPin } from '../icons/icons';
import { useIsoLayoutEffect } from '../lib/layers';
import { useShortcut } from '../lib/shortcuts';
import { Badge } from '../primitives/marks';
import { useShell } from './context';

/** Slides one marker (.nav-glider) to the link with aria-current="page". */
export function useNavGlider(containerRef: RefObject<HTMLElement | null>, gliderRef: RefObject<HTMLElement | null>): void {
  useIsoLayoutEffect(() => {
    const container = containerRef.current;
    const glider = gliderRef.current;
    if (!container || !glider) return undefined;
    const place = () => {
      const active = container.querySelector<HTMLElement>('.nav-item[aria-current="page"]');
      if (!active) {
        glider.style.opacity = '0';
        return;
      }
      glider.style.opacity = '1';
      glider.style.transform = `translate(${active.offsetLeft}px, ${active.offsetTop}px)`;
      glider.style.width = `${active.offsetWidth}px`;
      glider.style.height = `${active.offsetHeight}px`;
    };
    place();
    const mo = new MutationObserver(place);
    mo.observe(container, { subtree: true, childList: true, attributes: true, attributeFilter: ['aria-current'] });
    const ro = typeof ResizeObserver === 'function' ? new ResizeObserver(place) : null;
    ro?.observe(container);
    return () => {
      mo.disconnect();
      ro?.disconnect();
    };
  }, []);
}

export interface RailProps {
  /** Logo or monogram. Decorative: the name carries the label. */
  brandMark: ReactNode;
  /** App name, plain text. The brand row is never a link (rule 9). */
  brandName: string;
  /** NavGroup and NavItem elements. */
  children?: ReactNode;
  /** Optional content in the brand row, after the name and before the pin control (a tool or
      workspace switcher, for example). Hidden while the rail is collapsed. The kit owns the row's
      markup, so a consumer never reaches into it by class. Hidden while the rail is collapsed
      unless `keepBrandSlotCollapsed` is set. */
  brandSlot?: ReactNode;
  /** Keeps the `brandSlot` visible in the collapsed rail, centred on its own line under the brand
      mark. Default false, so the slot is hidden there. Put a control in it that has a collapsed
      form (`ToolSwitchButton` with `collapsible`), because the collapsed rail is only the width of
      one icon. */
  keepBrandSlotCollapsed?: boolean | undefined;
  /** Foot of the sidebar: the BuildCard and anything else that belongs there. */
  footer?: ReactNode;
  /** One short status line under the build card, for example "Data refreshed 2 min ago". Plain
      text or a small inline node. Hidden with the build card while the rail is collapsed. It is
      rendered exactly as given: the kit adds nothing to it, so an app that writes its own version
      here never shows it twice. Takes precedence over `environment` and `statusText`. */
  status?: ReactNode;
  /** Environment name for the built-in status line, shown as an accent badge (for example
      "Production"). */
  environment?: ReactNode;
  /** App text for the built-in status line, after the version (for example the organisation). */
  statusText?: ReactNode;
  /** Puts v<version> in the built-in status line. Default true. Turn it off when the footer
      already shows the version (a BuildCard), so it never appears twice. The line is built only
      when `environment` or `statusText` is set: a version alone shows as the collapsed pill. */
  showVersion?: boolean | undefined;
  /** App version. The collapsed rail shows v<major> as a small pill. */
  version?: string | undefined;
  navLabel?: string | undefined;
  sidebarLabel?: string | undefined;
  pinLabel?: string | undefined;
  closeLabel?: string | undefined;
}

export function Rail({
  brandMark,
  brandSlot,
  keepBrandSlotCollapsed = false,
  brandName,
  children,
  footer,
  status,
  environment,
  statusText,
  showVersion = true,
  version,
  navLabel = 'Primary',
  sidebarLabel = 'Sidebar',
  pinLabel = 'Pin sidebar',
  closeLabel = 'Close navigation',
}: RailProps) {
  const shell = useShell();
  const glideRef = useRef<HTMLDivElement | null>(null);
  const gliderRef = useRef<HTMLSpanElement | null>(null);
  useNavGlider(glideRef, gliderRef);
  useShortcut({ id: 'kit.rail.pin', keys: '[', description: 'Pin or unpin the sidebar', group: 'Navigation' });
  if (!shell) throw new Error('<Rail> must be passed to <AppShell rail={...}>.');
  const bare = version ? version.trim().replace(/^v/i, '') : '';
  const major = bare ? bare.split('.')[0] : undefined;
  const hasNode = (n: ReactNode) => n !== undefined && n !== null && n !== false && n !== '';
  const versionText = showVersion && bare ? `v${bare}` : null;
  const line = hasNode(status)
    ? status
    : hasNode(environment) || hasNode(statusText)
      ? (
          <span className="rail-status-line">
            {hasNode(environment) ? <Badge tone="accent">{environment}</Badge> : null}
            {versionText || hasNode(statusText) ? (
              <span className="rail-status-text">
                {versionText}
                {versionText && hasNode(statusText) ? ' . ' : null}
                {statusText}
              </span>
            ) : null}
          </span>
        )
      : null;

  return (
    <aside id={shell.sidebarId} className="sidebar" aria-label={sidebarLabel} {...shell.railHandlers}>
      <div className="sidebar-brand">
        <span className="sidebar-brand-mark" aria-hidden="true">
          {brandMark}
        </span>
        <span className="sidebar-label sidebar-brand-name">{brandName}</span>
        {brandSlot ? <div className="sidebar-brand-slot" data-keep={keepBrandSlotCollapsed ? '' : undefined}>
            {brandSlot}
          </div> : null}
        <button
          type="button"
          className="rail-pin"
          aria-pressed={shell.pinned}
          aria-label={pinLabel}
          data-tip={pinLabel}
          data-tip-kbd="["
          onClick={shell.togglePin}
        >
          <IconPin />
        </button>
        <button
          type="button"
          className="btn drawer-close"
          data-variant="ghost"
          data-icon-only=""
          aria-label={closeLabel}
          data-tip={closeLabel}
          onClick={() => shell.setMobileOpen(false)}
        >
          <IconClose />
        </button>
      </div>
      <nav className="sidebar-nav" aria-label={navLabel}>
        <div className="nav-glide" ref={glideRef}>
          <span className="nav-glider" ref={gliderRef} aria-hidden="true" />
          {children}
        </div>
      </nav>
      {major ? (
        <span className="rail-ver" aria-hidden="true">
          v{major}
        </span>
      ) : null}
      {footer || line ? (
        <div className="build-wrap">
          {footer}
          {line ? <p className="rail-status">{line}</p> : null}
        </div>
      ) : null}
    </aside>
  );
}
