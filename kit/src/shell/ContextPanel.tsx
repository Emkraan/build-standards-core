/* ContextPanel: the second level of the shell navigation, a per-tool panel that sits next to the
   one-level Rail (UI standard section 19). The rail picks the tool, the panel lists that tool's own
   sections. The app passes it to AppShell `contextPanel`; the shell lays it out beside the header
   and the page, so the page reflows and nothing overlays it. It is a fixed width, never hovers
   open and has no pin: the rail keeps those. Its children are the same NavGroup and NavItem the
   rail takes, and the active item is marked by the same gliding highlight.
   Below 900px the panel stacks above the page and its list folds behind a button. */

import { useId, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { IconChevronDown } from '../icons/icons';
import { useNavGlider } from './Rail';

export interface ContextPanelProps {
  /** The tool's name, plain text. Names the panel for a screen reader. */
  title: string;
  /** One short line under the title, for example the tool's current scope. */
  subtitle?: ReactNode;
  /** NavGroup and NavItem elements. Set `iconBadge={false}` on an item: the count on the icon is for the collapsed rail. */
  children?: ReactNode;
  /** Foot of the panel, for example a secondary link or a status line. */
  footer?: ReactNode;
  /** Accessible name of the navigation list. Default `<title> sections`. */
  navLabel?: string | undefined;
  /** Label of the fold button below 900px. Default "Sections". */
  toggleLabel?: string | undefined;
  /** Whether the list starts unfolded below 900px. Default false. Wide screens always show it. */
  defaultOpen?: boolean | undefined;
}

export function ContextPanel({
  title,
  subtitle,
  children,
  footer,
  navLabel,
  toggleLabel = 'Sections',
  defaultOpen = false,
}: ContextPanelProps) {
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = `${useId()}-context`;
  const glideRef = useRef<HTMLDivElement | null>(null);
  const gliderRef = useRef<HTMLSpanElement | null>(null);
  useNavGlider(glideRef, gliderRef);
  const hasSubtitle = subtitle !== undefined && subtitle !== null && subtitle !== false && subtitle !== '';
  return (
    <aside className="context-panel" aria-label={title} data-open={open ? '' : undefined}>
      <div className="context-panel-head">
        <h2 className="context-panel-title">{title}</h2>
        {hasSubtitle ? <p className="context-panel-sub">{subtitle}</p> : null}
        <button
          type="button"
          className="btn context-panel-toggle"
          data-variant="ghost"
          aria-expanded={open}
          aria-controls={bodyId}
          onClick={() => setOpen((v) => !v)}
        >
          {toggleLabel}
          <IconChevronDown />
        </button>
      </div>
      <div className="context-panel-body" id={bodyId}>
        <nav className="context-panel-nav" aria-label={navLabel ?? `${title} sections`}>
          <div className="nav-glide" ref={glideRef}>
            <span className="nav-glider" ref={gliderRef} aria-hidden="true" />
            {children}
          </div>
        </nav>
        {footer ? <div className="context-panel-foot">{footer}</div> : null}
      </div>
    </aside>
  );
}
