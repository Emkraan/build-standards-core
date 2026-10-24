/* Theme: light, dark or follow the OS. The choice is persisted per browser and applied as
   data-theme on <html> (no attribute follows the OS). Switching reveals the new theme with a circle
   that grows from the toggle (View Transitions API), and swaps instantly under reduced motion or
   where the API is missing (UI standard sections 6, 24 and 25). */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { flushSync } from 'react-dom';
import { IconMoon, IconSun } from '../icons/icons';
import { STORAGE_KEYS, cx, isBrowser, mediaQuery, onMediaChange, prefersLightScheme, prefersReducedMotion, readStorage, writeStorage } from '../lib/env';
import { useIsoLayoutEffect } from '../lib/layers';
import { tokenDuration, tokenValue } from '../lib/timing';

export type ThemeChoice = 'light' | 'dark' | 'system';
export type ResolvedTheme = 'light' | 'dark';

export interface RevealOrigin {
  x: number;
  y: number;
}

export interface ThemeContextValue {
  /** What the user picked. `system` follows the OS. */
  choice: ThemeChoice;
  /** What is on screen now. */
  resolved: ResolvedTheme;
  setChoice: (choice: ThemeChoice, origin?: RevealOrigin) => void;
  /** Flips between light and dark, revealing from `origin` when given. */
  toggle: (origin?: RevealOrigin) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function storedChoice(key: string): ThemeChoice | null {
  const v = readStorage(key);
  return v === 'light' || v === 'dark' || v === 'system' ? v : null;
}

/** Writes the choice to <html>. `system` removes the attribute so the OS decides. */
export function applyThemeAttribute(choice: ThemeChoice): void {
  if (!isBrowser) return;
  const root = document.documentElement;
  if (choice === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', choice);
}

interface ViewTransitionLike {
  ready: Promise<void>;
}
type DocumentWithTransitions = Document & {
  startViewTransition?: (update: () => void) => ViewTransitionLike;
};

/**
 * Runs `apply` inside a view transition and clips the new theme in as a growing circle from
 * `origin`. Falls back to calling `apply` at once when the API is missing or motion is reduced.
 */
export function revealTheme(apply: () => void, origin?: RevealOrigin): void {
  if (!isBrowser) return;
  const doc = document as DocumentWithTransitions;
  if (typeof doc.startViewTransition !== 'function' || prefersReducedMotion()) {
    apply();
    return;
  }
  const x = origin?.x ?? window.innerWidth / 2;
  const y = origin?.y ?? 0;
  const radius = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y));
  const transition = doc.startViewTransition.call(document, apply);
  transition.ready
    .then(() => {
      const easing = tokenValue('--ease-out');
      const options: KeyframeAnimationOptions & { pseudoElement?: string } = {
        duration: tokenDuration('--dur-page'),
        pseudoElement: '::view-transition-new(root)',
      };
      if (easing) options.easing = easing;
      document.documentElement.animate(
        { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`] },
        options,
      );
    })
    .catch(() => {
      // The browser skipped the transition. The theme is already applied, so nothing is lost.
    });
}

export interface ThemeProviderProps {
  children?: ReactNode;
  /** localStorage key. One preference per browser by default. */
  storageKey?: string | undefined;
  /** Used when nothing is stored. Default `system`. An app may default to `dark` or `light`: a
      user who then picks System keeps it, because that pick is stored as `system`. Pass the same
      default to themeInitScript so the first paint matches. */
  defaultChoice?: ThemeChoice | undefined;
}

export function ThemeProvider({ children, storageKey = STORAGE_KEYS.theme, defaultChoice = 'system' }: ThemeProviderProps) {
  const [choice, setChoiceState] = useState<ThemeChoice>(() => storedChoice(storageKey) ?? defaultChoice);
  const [system, setSystem] = useState<ResolvedTheme>(() => (prefersLightScheme() ? 'light' : 'dark'));

  useEffect(() => {
    const mq = mediaQuery('(prefers-color-scheme: light)');
    if (!mq) return undefined;
    const onChange = () => setSystem(mq.matches ? 'light' : 'dark');
    return onMediaChange(mq, onChange);
  }, []);

  useIsoLayoutEffect(() => {
    applyThemeAttribute(choice);
  }, [choice]);

  const resolved: ResolvedTheme = choice === 'system' ? system : choice;

  const setChoice = useCallback(
    (next: ThemeChoice, origin?: RevealOrigin) => {
      // `system` is stored explicitly, so it survives an app default other than system.
      writeStorage(storageKey, next);
      revealTheme(() => {
        applyThemeAttribute(next);
        flushSync(() => setChoiceState(next));
      }, origin);
    },
    [storageKey],
  );

  const toggle = useCallback(
    (origin?: RevealOrigin) => setChoice(resolved === 'dark' ? 'light' : 'dark', origin),
    [resolved, setChoice],
  );

  const value = useMemo<ThemeContextValue>(() => ({ choice, resolved, setChoice, toggle }), [choice, resolved, setChoice, toggle]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used inside <ThemeProvider>.');
  return ctx;
}

export interface ThemeToggleProps {
  className?: string | undefined;
  /** Accessible names. The label says what a click does. */
  toLightLabel?: string | undefined;
  toDarkLabel?: string | undefined;
}

/** Icon button that flips the theme with the circle reveal from the button itself. */
export function ThemeToggle({ className, toLightLabel = 'Switch to light theme', toDarkLabel = 'Switch to dark theme' }: ThemeToggleProps) {
  const { resolved, toggle } = useTheme();
  const label = resolved === 'dark' ? toLightLabel : toDarkLabel;
  return (
    <button
      type="button"
      className={cx('btn theme-toggle', className)}
      data-variant="ghost"
      data-icon-only=""
      aria-label={label}
      data-tip={label}
      onClick={(event) => {
        const r = event.currentTarget.getBoundingClientRect();
        toggle({ x: r.left + r.width / 2, y: r.top + r.height / 2 });
      }}
    >
      {resolved === 'dark' ? <IconSun /> : <IconMoon />}
    </button>
  );
}

// The pre-paint script lives in init.ts so a build config can import it without React.
export { themeInitScript } from './init';
