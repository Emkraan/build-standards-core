/* Build-time delivery of the pre-paint theme script (the UI standard, section 12): a Vite plugin that
   injects the kit's own script into index.html, and a drift check for a build that cannot inject. */
import { themeInitScript, type InitThemeChoice } from './init';

export interface ThemeInitOptions {
  storageKey?: string;
  defaultChoice?: InitThemeChoice;
}

interface HtmlTag {
  tag: 'script';
  children: string;
  injectTo: 'head-prepend';
}

/** A Vite plugin (structurally typed, so the kit needs no Vite types) that puts the kit's script first in <head>. */
export function kitThemeInit(options: ThemeInitOptions = {}): {
  name: string;
  transformIndexHtml: { order: 'pre'; handler: () => HtmlTag[] };
} {
  const script = themeInitScript(options.storageKey, options.defaultChoice);
  return {
    name: 'kit-theme-init',
    transformIndexHtml: { order: 'pre', handler: () => [{ tag: 'script', children: script, injectTo: 'head-prepend' }] },
  };
}

/** True when the HTML carries the kit's script byte for byte. CI fails a hand-pasted copy that drifted. */
export function hasCurrentThemeInit(html: string, options: ThemeInitOptions = {}): boolean {
  return html.includes(themeInitScript(options.storageKey, options.defaultChoice));
}
