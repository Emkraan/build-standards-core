/* The pre-paint theme script, kept free of React so a build config can import it. */
import { STORAGE_KEYS } from '../lib/env';

export type InitThemeChoice = 'light' | 'dark' | 'system';

/**
 * A one-line script for <head> that applies the stored theme before first paint, so a light
 * choice never flashes dark. Inject it with `kitThemeInit()` (theme-init) rather than pasting it.
 * `defaultChoice` matches ThemeProvider's: with nothing stored, a `dark` or `light` default is
 * applied, and a stored `system` always follows the OS.
 */
export function themeInitScript(storageKey: string = STORAGE_KEYS.theme, defaultChoice: InitThemeChoice = 'system'): string {
  // Escape < so a key can never close the inline script tag it is placed in.
  const key = JSON.stringify(storageKey).replace(/</g, '\\u003c');
  const fallback = defaultChoice === 'light' || defaultChoice === 'dark' ? `'${defaultChoice}'` : 'null';
  return `(function(){try{var t=localStorage.getItem(${key});if(t!=='light'&&t!=='dark'&&t!=='system'){t=${fallback};}if(t==='light'||t==='dark'){document.documentElement.setAttribute('data-theme',t);}}catch(e){}})();`;
}
