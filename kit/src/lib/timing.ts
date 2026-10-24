/* Behavioural timings named by the standard (UI standard sections 7, 19 and 20). They are
   interaction delays and lifetimes in milliseconds, not motion. Every CSS transition and animation
   in the kit takes its duration from a --dur-* token, and script-driven motion reads the token at
   run time through tokenDuration(). */

import { isBrowser } from './env';

/** Section 19: hovering the rail opens it after this delay. */
export const RAIL_OPEN_DELAY = 90;
/** Section 19: leaving the rail closes it after this delay. */
export const RAIL_CLOSE_DELAY = 240;
/** Section 7: a tooltip shows after this hover delay. */
export const TOOLTIP_DELAY = 380;
/** Section 7: moving from one tip to the next shows the next one after this delay. */
export const TOOLTIP_SKIP_DELAY = 60;
/** How long after a tip hides the short skip delay still applies. */
export const TOOLTIP_SKIP_WINDOW = 300;
/** Count-up length when the --dur-chart token cannot be read (no token sheet, server render). */
export const COUNT_UP_FALLBACK = 700;
/** Extra time before the count-up lands on the real value when frames are throttled. */
export const COUNT_UP_LAND_MARGIN = 120;
/** Section 7: toast lifetime, and the longer one for a toast that offers an action. */
export const TOAST_DURATION = 5000;
export const TOAST_ACTION_DURATION = 8000;
/** Feed strip: how long each presenter item stays before the next one. */
export const FEED_INTERVAL = 7000;
/** Freshness labels ("Updated 12s ago") tick once a second. */
export const CLOCK_TICK = 1000;
/** Two-key shortcuts ("G then H") wait this long for the second key. */
export const SEQUENCE_TIMEOUT = 1000;

/** Reads a CSS custom property from the root (or an element) as trimmed text. */
export function tokenValue(name: string, el?: Element): string {
  if (!isBrowser) return '';
  return getComputedStyle(el ?? document.documentElement).getPropertyValue(name).trim();
}

/** Reads a --dur-* token in milliseconds. Returns 0 when the token sheet is not loaded. */
export function tokenDuration(name: string, el?: Element): number {
  const raw = tokenValue(name, el);
  const match = /^(\d*\.?\d+)(ms|s)$/.exec(raw);
  if (!match || match[1] === undefined) return 0;
  const n = Number.parseFloat(match[1]);
  return match[2] === 's' ? n * 1000 : n;
}
