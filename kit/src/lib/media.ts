/* Reactive media queries. The kit CSS breaks at two widths: 640px (phone: one column, full-width
   toasts and dialogs) and 900px (shell: the rail collapses to a drawer). Use these hooks when a
   component has to branch in script at the same point the CSS does. */

import { useCallback, useSyncExternalStore } from 'react';
import { isBrowser, mediaQuery, onMediaChange, prefersLightScheme } from './env';

/** The phone breakpoint the kit CSS uses. */
export const PHONE_QUERY = '(max-width: 640px)';
/** The width at which the shell collapses the rail to a drawer. */
export const SHELL_QUERY = '(max-width: 900px)';

/** True while the media query matches; re-renders on each change. False on the server and where
    matchMedia does not exist. */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (notify: () => void) => {
      const mq = mediaQuery(query);
      return mq ? onMediaChange(mq, notify) : () => {};
    },
    [query],
  );
  return useSyncExternalStore(
    subscribe,
    () => mediaQuery(query)?.matches ?? false,
    () => false,
  );
}

/** True at or under the kit phone breakpoint. */
export function useIsPhone(): boolean {
  return useMediaQuery(PHONE_QUERY);
}

/** The colour scheme the page is painting in. */
export type ColorScheme = 'light' | 'dark';

/** The resolved scheme: an explicit choice on the root element (set by ThemeProvider) wins, else
    the OS signal, else dark, which is the token default. */
export function readColorScheme(): ColorScheme {
  if (!isBrowser) return 'dark';
  const chosen = document.documentElement.getAttribute('data-theme');
  if (chosen === 'light' || chosen === 'dark') return chosen;
  return prefersLightScheme() ? 'light' : 'dark';
}

function subscribeColorScheme(notify: () => void): () => void {
  if (!isBrowser) return () => {};
  const mo = new MutationObserver(notify);
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  const mq = mediaQuery('(prefers-color-scheme: light)');
  const offMedia = mq ? onMediaChange(mq, notify) : () => {};
  return () => {
    mo.disconnect();
    offMedia();
  };
}

/** The resolved colour scheme, live. For a vendor widget that takes a light or dark flag instead
    of reading the kit tokens (the API reference, the graph canvas). Works with or without a
    ThemeProvider; dark on the server. */
export function useColorScheme(): ColorScheme {
  return useSyncExternalStore(subscribeColorScheme, readColorScheme, () => 'dark');
}
