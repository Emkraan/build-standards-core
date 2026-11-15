import { describe, expect, it } from 'vitest';
import { themeInitScript } from '../src/index';
import { hasCurrentThemeInit, kitThemeInit } from '../src/theme/theme-init';

describe('theme init delivery', () => {
  it('injects the kit script first in head', () => {
    const tags = kitThemeInit({ defaultChoice: 'dark' }).transformIndexHtml.handler();
    expect(tags).toEqual([{ tag: 'script', children: themeInitScript(undefined, 'dark'), injectTo: 'head-prepend' }]);
  });

  it('flags a hand-pasted copy that drifted', () => {
    const current = `<head><script>${themeInitScript()}</script></head>`;
    expect(hasCurrentThemeInit(current)).toBe(true);
    const shortened = `<head><script>try{var t=localStorage.getItem('theme');document.documentElement.setAttribute('data-theme',t)}catch(e){}</script></head>`;
    expect(hasCurrentThemeInit(shortened)).toBe(false);
    expect(hasCurrentThemeInit(current, { defaultChoice: 'light' })).toBe(false);
  });
});
