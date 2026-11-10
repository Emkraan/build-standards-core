/* Test helpers: a controllable matchMedia for jsdom, which has none. */

export const media = {
  reducedMotion: false,
  light: false,
  desktop: true,
};

export function resetMedia(): void {
  media.reducedMotion = false;
  media.light = false;
  media.desktop = true;
}

function matches(query: string): boolean {
  if (query.includes('prefers-reduced-motion')) return media.reducedMotion;
  if (query.includes('prefers-color-scheme: light')) return media.light;
  if (query.includes('min-width: 901px')) return media.desktop;
  return false;
}

export function installMatchMedia(): void {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: (query: string): MediaQueryList =>
      ({
        media: query,
        get matches() {
          return matches(query);
        },
        onchange: null,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
        addListener: () => undefined,
        removeListener: () => undefined,
        dispatchEvent: () => false,
      }) as unknown as MediaQueryList,
  });
}
