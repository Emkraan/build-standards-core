/* AppShell: icon rail + header + optional feed strip + content, with the mobile drawer below 900px
   (UI standard sections 6, 11, 19 and 25). The shell carries data-rail="collapsed|open|pinned". */

import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import type { FocusEvent, ReactNode } from 'react';
import { STORAGE_KEYS, cx, isTypingTarget, mediaQuery, onMediaChange, readStorage, writeStorage } from '../lib/env';
import { focusables, isDialogOpen, isTopLayer, lockScroll, pushLayer, removeLayer, trapTab, unlockScroll } from '../lib/layers';
import { StorageScope } from '../lib/scope';
import { RAIL_CLOSE_DELAY, RAIL_OPEN_DELAY } from '../lib/timing';
import { GlossaryProvider } from '../primitives/Glossary';
import type { Glossary } from '../primitives/Glossary';
import { TooltipLayer } from '../primitives/Tooltip';
import { DefaultLink, ShellContext } from './context';
import type { LinkComponent, RailHandlers, RailState, ShellContextValue } from './context';

export interface AppShellProps {
  /** A <Rail>. It renders the sidebar as a direct child of the shell. */
  rail: ReactNode;
  /** A <Header>. */
  header?: ReactNode;
  /** The live feed strip (<FeedStrip>), shown under the header on every page. */
  strip?: ReactNode;
  children?: ReactNode;
  /** The current route. A change closes the mobile drawer. */
  pathname?: string | undefined;
  /** Router adapter for nav links. Receives `href`. Default: a plain anchor. */
  linkComponent?: LinkComponent | undefined;
  /** localStorage key for the pin preference. */
  railStorageKey?: string | undefined;
  skipLinkLabel?: string | undefined;
  /** id of the <main> element, the skip link target. */
  mainId?: string | undefined;
  className?: string | undefined;
  /**
   * Stable id of this app. Set it when several apps share one origin (path-mounted), so the
   * build card and announcement state get keys of their own (`shell.<appId>.build.seen`,
   * `shell.<appId>.announce.dismissed`). Theme and rail pin stay shared. Default: no scope.
   */
  appId?: string | undefined;
  /**
   * Mounts the page's tooltip layer, so every `data-tip` and native `title` in the app shows the kit
   * tip. Default false, so an app that does not ask sees nothing change: it keeps mounting its own
   * `TooltipLayer` or none. Only the first layer mounted is active, so a tip never shows twice when an
   * app turns this on and still mounts its own.
   */
  tooltipLayer?: boolean | undefined;
  /**
   * The app's glossary, by id (see GlossaryProvider). Registers it for every page, so <Term id> and
   * InfoTip resolve anywhere with no further wiring. Default none: nothing is registered and a Term
   * renders its plain text.
   */
  glossary?: Glossary | undefined;
}

export function AppShell({
  rail,
  header,
  strip,
  children,
  pathname,
  linkComponent,
  railStorageKey = STORAGE_KEYS.railPinned,
  skipLinkLabel = 'Skip to content',
  mainId = 'kit-main',
  className,
  appId,
  tooltipLayer = false,
  glossary,
}: AppShellProps) {
  const sidebarId = `${useId()}-sidebar`;
  const [pinned, setPinned] = useState(() => readStorage(railStorageKey) === 'true');
  const [hoverOpen, setHoverOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement | null>(null);
  const pinnedRef = useRef(pinned);
  const pointerInside = useRef(false);
  const timer = useRef<number | null>(null);

  const clearTimer = useCallback(() => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
  }, []);
  useEffect(() => clearTimer, [clearTimer]);

  const togglePin = useCallback(() => {
    const next = !pinnedRef.current;
    pinnedRef.current = next;
    writeStorage(railStorageKey, next ? 'true' : null);
    setPinned(next);
  }, [railStorageKey]);

  const sidebarHasFocus = useCallback(() => {
    const sidebar = document.getElementById(sidebarId);
    return Boolean(sidebar && document.activeElement && sidebar.contains(document.activeElement));
  }, [sidebarId]);

  const railHandlers = useMemo<RailHandlers>(
    () => ({
      onPointerEnter: () => {
        pointerInside.current = true;
        clearTimer();
        timer.current = window.setTimeout(() => setHoverOpen(true), RAIL_OPEN_DELAY);
      },
      onPointerLeave: () => {
        pointerInside.current = false;
        clearTimer();
        timer.current = window.setTimeout(() => {
          if (!sidebarHasFocus()) setHoverOpen(false);
        }, RAIL_CLOSE_DELAY);
      },
      onFocus: () => {
        clearTimer();
        setHoverOpen(true);
      },
      onBlur: (event: FocusEvent<HTMLElement>) => {
        const next = event.relatedTarget;
        if (next instanceof Node && event.currentTarget.contains(next)) return;
        if (pointerInside.current) return;
        clearTimer();
        timer.current = window.setTimeout(() => setHoverOpen(false), RAIL_CLOSE_DELAY);
      },
    }),
    [clearTimer, sidebarHasFocus],
  );

  // The [ key pins and unpins the rail, outside text fields and while no dialog is open.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== '[' || event.metaKey || event.ctrlKey || event.altKey || event.defaultPrevented) return;
      if (isTypingTarget(event.target) || isDialogOpen()) return;
      event.preventDefault();
      togglePin();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [togglePin]);

  // The mobile drawer closes on route change, on Escape, and when the window grows to desktop.
  const lastPath = useRef(pathname);
  useEffect(() => {
    if (pathname === lastPath.current) return;
    lastPath.current = pathname;
    setMobileOpen(false);
  }, [pathname]);

  useEffect(() => {
    const mq = mediaQuery('(min-width: 901px)');
    if (!mq) return undefined;
    const onChange = () => {
      if (mq.matches) setMobileOpen(false);
    };
    return onMediaChange(mq, onChange);
  }, []);

  const wasOpen = useRef(false);
  useEffect(() => {
    const sidebar = document.getElementById(sidebarId);
    if (mobileOpen) {
      wasOpen.current = true;
      const close = sidebar?.querySelector<HTMLElement>('.drawer-close');
      (close ?? (sidebar ? focusables(sidebar)[0] : undefined))?.focus();
      // The open drawer is a modal layer: Tab stays inside it, the page behind it does not
      // scroll, and global shortcuts (isDialogOpen) pause until it closes.
      const layerId = `${sidebarId}-drawer`;
      pushLayer(layerId, true);
      lockScroll();
      const onKey = (event: KeyboardEvent) => {
        if (!isTopLayer(layerId)) return;
        if (event.key === 'Escape') {
          event.preventDefault();
          setMobileOpen(false);
        } else if (event.key === 'Tab' && sidebar) {
          trapTab(event, sidebar);
        }
      };
      document.addEventListener('keydown', onKey);
      return () => {
        document.removeEventListener('keydown', onKey);
        unlockScroll();
        removeLayer(layerId, true);
      };
    }
    if (wasOpen.current) {
      wasOpen.current = false;
      if (!sidebar || !document.activeElement || sidebar.contains(document.activeElement) || document.activeElement === document.body) {
        menuButtonRef.current?.focus();
      }
    }
    return undefined;
  }, [mobileOpen, sidebarId]);

  const railState: RailState = pinned ? 'pinned' : hoverOpen ? 'open' : 'collapsed';

  const ctx = useMemo<ShellContextValue>(
    () => ({
      rail: railState,
      pinned,
      togglePin,
      railHandlers,
      mobileOpen,
      setMobileOpen,
      sidebarId,
      menuButtonRef,
      Link: linkComponent ?? DefaultLink,
    }),
    [railState, pinned, togglePin, railHandlers, mobileOpen, sidebarId, linkComponent],
  );

  const shell = (
    <ShellContext.Provider value={ctx}>
      <div className={cx('shell', className)} data-rail={railState} data-mobile-nav={mobileOpen ? 'open' : 'closed'}>
        <a className="skip-link" href={`#${mainId}`}>
          {skipLinkLabel}
        </a>
        {rail}
        {mobileOpen ? <div className="drawer-backdrop" aria-hidden="true" onClick={() => setMobileOpen(false)} /> : null}
        <div className="shell-main">
          {header}
          {strip}
          <main id={mainId} className="shell-content" tabIndex={-1}>
            {children}
          </main>
        </div>
        {tooltipLayer ? <TooltipLayer /> : null}
      </div>
    </ShellContext.Provider>
  );
  const scoped = appId ? <StorageScope appId={appId}>{shell}</StorageScope> : shell;
  return glossary ? <GlossaryProvider glossary={glossary}>{scoped}</GlossaryProvider> : scoped;
}
