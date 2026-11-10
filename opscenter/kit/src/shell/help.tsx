/* Page help state. A page describes itself once with usePageHelp, and the shell's Help button and
   help drawer read that description. The state lives in the shell, so a page needs no wiring. */

import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';

export interface HelpLinkItem {
  label: string;
  href: string;
}

/** What a page tells its user: what it is for, how to use it and which words it uses. */
export interface PageHelp {
  /** The page name. The drawer is headed "Help: <title>". */
  title: string;
  /** What the page is for, one or two sentences. */
  summary?: string | undefined;
  /** The common task on this page as short steps in plain sentences. */
  steps?: readonly string[] | undefined;
  /** Glossary ids of the words this page uses. The drawer lists each with its long text. */
  terms?: readonly string[] | undefined;
  /** Further reading. */
  links?: readonly HelpLinkItem[] | undefined;
}

export interface HelpContextValue {
  /** The help of the page on screen, or null while no page registered any. */
  page: PageHelp | null;
  open: boolean;
  setOpen: (open: boolean) => void;
  /** Registers a page's help under a key. Returns the call that removes it. The latest one wins. */
  register: (key: string, help: PageHelp) => () => void;
}

const HelpContext = createContext<HelpContextValue | null>(null);

export interface HelpProviderProps {
  children?: ReactNode;
  /** The current route. A change closes the drawer, so help never stays open over the next page. */
  pathname?: string | undefined;
}

/**
 * Holds the page help and the drawer's open state. AppShell mounts one, so an app does not. An app whose
 * command palette sits outside the shell mounts one above both, so the palette can list the help of the
 * page on screen (useHelpPaletteItems): the shell then keeps that provider as the only one, so pass the
 * current route as `pathname` to it.
 */
export function HelpProvider({ children, pathname }: HelpProviderProps) {
  const outer = useContext(HelpContext);
  if (outer) return <>{children}</>;
  return <HelpState pathname={pathname}>{children}</HelpState>;
}

function HelpState({ children, pathname }: HelpProviderProps) {
  const [entries, setEntries] = useState<ReadonlyArray<{ key: string; help: PageHelp }>>([]);
  const [open, setOpen] = useState(false);
  const register = useCallback((key: string, help: PageHelp) => {
    setEntries((list) => [...list.filter((entry) => entry.key !== key), { key, help }]);
    return () => setEntries((list) => list.filter((entry) => entry.key !== key));
  }, []);
  const page = entries.at(-1)?.help ?? null;

  const lastPath = useRef(pathname);
  useEffect(() => {
    if (pathname === lastPath.current) return;
    lastPath.current = pathname;
    setOpen(false);
  }, [pathname]);
  useEffect(() => {
    if (!page) setOpen(false);
  }, [page]);

  const value = useMemo<HelpContextValue>(() => ({ page, open: open && page !== null, setOpen, register }), [page, open, register]);
  return <HelpContext.Provider value={value}>{children}</HelpContext.Provider>;
}

/** The page help state, or null outside a shell (a Help button then has nothing to open). */
export function useHelp(): HelpContextValue | null {
  return useContext(HelpContext);
}

/**
 * Registers the help of the page that calls it. The shell's Help button appears while a page has help,
 * and the drawer shows it. Pass null to register nothing. The object may be built inline: only a change
 * in its content registers again.
 */
export function usePageHelp(help: PageHelp | null | undefined): void {
  const ctx = useHelp();
  const register = ctx?.register;
  const key = useId();
  const serial = help ? JSON.stringify(help) : '';
  useEffect(() => {
    if (!register || !serial) return undefined;
    return register(key, JSON.parse(serial) as PageHelp);
  }, [register, key, serial]);
}
