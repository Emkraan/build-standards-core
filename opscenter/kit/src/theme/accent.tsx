/* Per-app accent (UI standard sections 12 and 16). An app picks one named accent, set once on the
   root as data-app-accent. No attribute is the default accent (cobalt). Components never set an
   accent token. */

import type { ReactNode } from 'react';
import { isBrowser } from '../lib/env';
import { useIsoLayoutEffect } from '../lib/layers';

import accentData from './accents.json';

/** The accent names, from `accents.json` (also exported as `@.../accents.json` for tools that read data). */
export const APP_ACCENTS = accentData.accents as unknown as readonly [
  'cobalt', 'blue', 'indigo', 'violet', 'fuchsia', 'rose', 'red', 'orange', 'hub', 'amber', 'gold',
  'green', 'teal', 'cyan',
];
export type AppAccent = (typeof APP_ACCENTS)[number];
export const DEFAULT_ACCENT: AppAccent = 'cobalt';

export function isAppAccent(value: string): value is AppAccent {
  return (APP_ACCENTS as readonly string[]).includes(value);
}

/** The one place in the kit that writes data-app-accent. Cobalt (or null) removes the attribute. */
export function setAppAccent(accent: AppAccent | null | undefined): void {
  if (!isBrowser) return;
  const root = document.documentElement;
  if (!accent || accent === DEFAULT_ACCENT) {
    root.removeAttribute('data-app-accent');
    return;
  }
  root.setAttribute('data-app-accent', accent);
}

export function getAppAccent(): AppAccent {
  if (!isBrowser) return DEFAULT_ACCENT;
  const v = document.documentElement.getAttribute('data-app-accent') ?? '';
  return isAppAccent(v) ? v : DEFAULT_ACCENT;
}

export interface AccentProviderProps {
  accent: AppAccent;
  children?: ReactNode;
}

/** Sets the app accent on the root once, before paint, and puts the previous one back on unmount.
    Mount it at the top of the app. */
export function AccentProvider({ accent, children }: AccentProviderProps) {
  useIsoLayoutEffect(() => {
    if (!isBrowser) return undefined;
    const previous = getAppAccent();
    setAppAccent(accent);
    return () => setAppAccent(previous);
  }, [accent]);
  return <>{children}</>;
}
