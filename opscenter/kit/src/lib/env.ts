/* Small shared helpers: class names, environment checks and safe storage. */

export type ClassValue = string | false | null | undefined | 0;

/** Joins truthy class names with a space. */
export function cx(...parts: ClassValue[]): string {
  return parts.filter(Boolean).join(' ');
}

export const isBrowser: boolean = typeof window !== 'undefined' && typeof document !== 'undefined';

// Bundlers replace process.env.NODE_ENV at build time. Where nothing replaced it, reading it
// throws and the code counts as development.
declare const process: { env: { NODE_ENV?: string | undefined } };

/** True in a production build. Any other build, and one where nothing replaced NODE_ENV, counts as development. */
export function isProduction(): boolean {
  try {
    return process.env.NODE_ENV === 'production';
  } catch {
    return false;
  }
}

const warned = new Set<string>();

/** A console warning for development builds only, once per key. A production build stays silent. */
export function devWarn(key: string, message: string): void {
  if (isProduction() || warned.has(key) || typeof console === 'undefined') return;
  warned.add(key);
  console.warn(`kit: ${message}`);
}

/** Test hook: lets every development warning fire again. */
export function resetDevWarnings(): void {
  warned.clear();
}

/** matchMedia that returns null where it does not exist (server render, old test DOMs). */
export function mediaQuery(query: string): MediaQueryList | null {
  if (!isBrowser || typeof window.matchMedia !== 'function') return null;
  return window.matchMedia(query);
}

export function prefersReducedMotion(): boolean {
  return mediaQuery('(prefers-reduced-motion: reduce)')?.matches ?? false;
}

export function prefersLightScheme(): boolean {
  return mediaQuery('(prefers-color-scheme: light)')?.matches ?? false;
}

/** True on macOS and iOS, where the command key replaces control in shortcuts. */
export function isMacLike(): boolean {
  if (!isBrowser) return false;
  const nav = navigator as Navigator & { userAgentData?: { platform?: string } };
  const platform = nav.userAgentData?.platform ?? nav.platform ?? '';
  return /mac|iphone|ipad|ipod/i.test(platform);
}

const TEXT_INPUT_TYPES = new Set([
  'text', 'search', 'email', 'url', 'tel', 'password', 'number', 'date', 'datetime-local', 'month',
  'time', 'week',
]);

/** True when a key press lands in a field where the user is typing text. */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!target || !(target instanceof Element)) return false;
  const el = target as HTMLElement;
  if (el.isContentEditable) return true;
  // jsdom and some embedded views do not compute isContentEditable: read the attribute as well.
  const editable = el.closest?.('[contenteditable]');
  if (editable && editable.getAttribute('contenteditable')?.toLowerCase() !== 'false') return true;
  if (el.tagName === 'TEXTAREA' || el.tagName === 'SELECT') return true;
  if (el.tagName === 'INPUT') return TEXT_INPUT_TYPES.has((el as HTMLInputElement).type || 'text');
  return false;
}

/** Reads a string from localStorage. Storage can be blocked (private mode, policy): then null. */
export function readStorage(key: string): string | null {
  if (!isBrowser) return null;
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

/** Writes or removes a localStorage key. A blocked store keeps the choice for this page only. */
export function writeStorage(key: string, value: string | null): void {
  if (!isBrowser) return;
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    // Storage is unavailable. The in-memory state still applies until the page closes.
  }
}

export function readJson<T>(key: string, fallback: T): T {
  const raw = readStorage(key);
  if (raw === null) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export function writeJson(key: string, value: unknown): void {
  writeStorage(key, JSON.stringify(value));
}

/** Storage keys used by the kit. One preference per browser, shared by every app on the origin. */
export const STORAGE_KEYS = {
  theme: 'shell.theme',
  railPinned: 'shell.sidebar.pinned',
  buildSeen: 'shell.build.seen',
  announcementsDismissed: 'shell.announce.dismissed',
} as const;

export interface StorageKeys {
  theme: string;
  railPinned: string;
  buildSeen: string;
  announcementsDismissed: string;
}

/** Allowed app ids: a letter or digit, then letters, digits, `-` or `_`, at most 64 characters. */
export const APP_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;

/**
 * The kit's storage keys for one app. Apps that share an origin (mounted under different paths)
 * pass an app id so the per-app state stays apart: `shell.<appId>.build.seen` and
 * `shell.<appId>.announce.dismissed`. Theme and rail pin stay one preference per browser. No id,
 * or an empty one, returns STORAGE_KEYS unchanged. An id outside APP_ID_PATTERN (a dot, a space,
 * a slash) throws, so two apps can never build overlapping keys.
 */
export function storageKeys(appId?: string | null): StorageKeys {
  const id = (appId ?? '').trim();
  if (!id) return { ...STORAGE_KEYS };
  if (!APP_ID_PATTERN.test(id)) {
    throw new Error(`Invalid appId "${id}": use letters, digits, "-" or "_" (at most 64 characters).`);
  }
  return {
    theme: STORAGE_KEYS.theme,
    railPinned: STORAGE_KEYS.railPinned,
    buildSeen: `shell.${id}.build.seen`,
    announcementsDismissed: `shell.${id}.announce.dismissed`,
  };
}

/** Media query change subscription that also works where only addListener exists (older Safari). */
export function onMediaChange(mq: MediaQueryList, listener: () => void): () => void {
  if (typeof mq.addEventListener === 'function') {
    mq.addEventListener('change', listener);
    return () => mq.removeEventListener('change', listener);
  }
  const legacy = mq as MediaQueryList & { addListener?: (l: () => void) => void; removeListener?: (l: () => void) => void };
  legacy.addListener?.(listener);
  return () => legacy.removeListener?.(listener);
}
