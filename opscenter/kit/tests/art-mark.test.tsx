import { act, render } from '@testing-library/react';
import axe from 'axe-core';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { useRef } from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import { ART_EFFECTS, ArtMark, PageHeader, artAnchorVars, artEffectFor, useArtPaused } from '../src/index';

describe('ArtMark', () => {
  it('renders three layers and a still picture without an effect', () => {
    const { container } = render(<ArtMark src="/a.png" />);
    const root = container.querySelector('.art-mark');
    expect(root).not.toBeNull();
    expect(root?.getAttribute('aria-hidden')).toBe('true');
    expect(container.querySelector('.am-glow')).not.toBeNull();
    expect(container.querySelector('img.am-img')?.getAttribute('alt')).toBe('');
    expect(container.querySelectorAll('.am-fx > *').length).toBe(0);
  });

  it('draws the layers of each recipe', () => {
    for (const [name, def] of Object.entries(ART_EFFECTS)) {
      const { container, unmount } = render(<ArtMark src="/a.png" effect={name} />);
      const total = Object.values(def.layers).reduce((a, b) => a + b, 0);
      expect(container.querySelectorAll('.am-fx > *').length).toBe(total);
      expect(container.querySelector('.art-mark')?.getAttribute('data-effect')).toBe(name);
      unmount();
    }
  });

  it('treats an unknown recipe as a still picture', () => {
    expect(artEffectFor('nope')).toBeUndefined();
    expect(artEffectFor('toString')).toBeUndefined();
    const { container } = render(<ArtMark src="/a.png" effect="nope" />);
    expect(container.querySelector('.art-mark')?.hasAttribute('data-effect')).toBe(false);
  });

  it('carries hue, intensity, size and anchors as custom properties', () => {
    const { container } = render(
      <ArtMark src="/a.png" effect="beacon" hue="amber" hot="red" intensity={0.5} size={40} anchors={{ focus: [30, 40], reach: 20 }} />,
    );
    const el = container.querySelector('.art-mark') as HTMLElement;
    expect(el.style.getPropertyValue('--am-fx')).toBe('var(--hue-amber)');
    expect(el.style.getPropertyValue('--am-fx-hot')).toBe('var(--hue-red)');
    expect(el.style.getPropertyValue('--am-intensity')).toBe('0.5');
    expect(el.style.getPropertyValue('--am-fx-x')).toBe('30%');
    expect(el.style.width).toBe('40px');
  });

  it('maps every anchor kind', () => {
    const v = artAnchorVars({
      spark: [1, 2],
      pivot: [3, 4],
      arcs: { radii: [5, 6], from: 10, span: 20 },
      box: [1, 2, 3, 4],
      feed: { rect: [10, 20, 50, 50], slide: [5, 0] },
    });
    expect(v['--am-sp-x']).toBe('1%');
    expect(v['--am-pivot']).toBe('3% 4%');
    expect(v['--am-r1']).toBe(6);
    expect(v['--am-bh']).toBe('4%');
    expect(v['--am-fd-iw']).toBe('200%');
  });

  it('is an image when titled and passes axe', async () => {
    const { container } = render(
      <main>
        <ArtMark src="/a.png" effect="fire" title="Sample" />
      </main>,
    );
    expect(container.querySelector('[role="img"]')?.getAttribute('aria-label')).toBe('Sample');
    expect((await axe.run(container)).violations).toEqual([]);
  });
});

describe('ArtMark hardening', () => {
  const style = (container: HTMLElement) => container.querySelector('.art-mark') as HTMLElement;

  it.each(['Blue', 'a b', 'a)b', '1red', '', 'x;y', 'x}y', 'x"y', '-x', 'a_b', 'a/b'])('falls back to the default hue for %j', (bad) => {
    const { container } = render(<ArtMark src="/a.png" hue={bad} hot={bad} />);
    expect(style(container).style.getPropertyValue('--am-fx')).toBe('var(--hue-blue)');
    expect(style(container).style.getPropertyValue('--am-fx-hot')).toBe('var(--hue-blue)');
  });

  it('keeps a valid hue when only hot is rejected, and accepts digits and hyphens', () => {
    const { container } = render(<ArtMark src="/a.png" hue="amber-2" hot="bad)" />);
    expect(style(container).style.getPropertyValue('--am-fx')).toBe('var(--hue-amber-2)');
    expect(style(container).style.getPropertyValue('--am-fx-hot')).toBe('var(--hue-amber-2)');
  });

  it.each([
    ['a double quote', '/a".png'],
    ['a single quote', "/a'.png"],
    ['an opening parenthesis', '/a(.png'],
    ['a closing parenthesis', '/a).png'],
    ['a backslash', '/a\\.png'],
    ['a line break', '/a\n.png'],
    ['a carriage return', '/a\r.png'],
    ['a tab', '/a\t.png'],
    ['a null byte', '/a\u0000.png'],
    ['a way out of the url', '/a"); background: url("//x'],
  ])('keeps a src with %s out of the mask variable', (_name, bad) => {
    const { container } = render(<ArtMark src={bad} effect="glint" />);
    const root = style(container);
    expect(root.style.getPropertyValue('--am-art')).toBe('');
    expect(root.hasAttribute('data-nomask')).toBe(true);
    expect(container.querySelector('img.am-img')).not.toBeNull();
  });

  it('sets the mask variable for a plain src', () => {
    const { container } = render(<ArtMark src="/art/a-1.png?v=2" />);
    expect(style(container).style.getPropertyValue('--am-art')).toContain('/art/a-1.png?v=2');
    expect(style(container).hasAttribute('data-nomask')).toBe(false);
  });

  it('skips a feed window with no area', () => {
    for (const rect of [[0, 0, 0, 50], [0, 0, 50, 0], [0, 0, -5, 50], [0, 0, 50, -5], [0, 0, Number.NaN, 5]] as const) {
      const v = artAnchorVars({ feed: { rect, slide: [5, 0] } });
      expect(Object.keys(v).filter((k) => k.startsWith('--am-fd') || k.startsWith('--am-slide'))).toEqual([]);
      for (const value of Object.values(v)) expect(String(value)).not.toMatch(/Infinity|NaN/);
    }
  });

  it('skips non-finite anchors and keeps the finite ones', () => {
    const v = artAnchorVars({ focus: [Number.NaN, 4], reach: Number.POSITIVE_INFINITY, spark: [1, 2], box: [1, 2, 3, Number.NaN] });
    expect(v['--am-fx-x']).toBeUndefined();
    expect(v['--am-reach']).toBeUndefined();
    expect(v['--am-sp-x']).toBe('1%');
    expect(v['--am-bx']).toBeUndefined();
  });

  it('clamps size and intensity', () => {
    const cases: Array<[number, string]> = [
      [-4, '1px'],
      [0, '1px'],
      [Number.NaN, '28px'],
      [Number.POSITIVE_INFINITY, '28px'],
      [99999, '1024px'],
    ];
    for (const [size, width] of cases) {
      const { container, unmount } = render(<ArtMark src="/a.png" size={size} />);
      expect(style(container).style.width).toBe(width);
      unmount();
    }
    const intensities: Array<[number, string]> = [
      [-2, '0'],
      [Number.NaN, '1'],
      [Number.NEGATIVE_INFINITY, '1'],
      [50, '3'],
      [0.5, '0.5'],
    ];
    for (const [intensity, expected] of intensities) {
      const { container, unmount } = render(<ArtMark src="/a.png" intensity={intensity} />);
      expect(style(container).style.getPropertyValue('--am-intensity')).toBe(expected);
      unmount();
    }
  });
});

describe('useArtPaused', () => {
  const realIO = globalThis.IntersectionObserver;
  const realState = Object.getOwnPropertyDescriptor(Document.prototype, 'visibilityState');
  afterEach(() => {
    globalThis.IntersectionObserver = realIO;
    if (realState) Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' });
  });

  function Probe() {
    const ref = useRef<HTMLSpanElement | null>(null);
    const paused = useArtPaused(ref);
    return <span ref={ref} data-testid="probe" data-paused={paused ? 'yes' : 'no'} />;
  }

  it('starts paused when the tab is already hidden at mount', () => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' });
    const { getByTestId } = render(<Probe />);
    expect(getByTestId('probe').getAttribute('data-paused')).toBe('yes');
  });

  it('uses the latest entry of a batch', () => {
    let callback: IntersectionObserverCallback = () => undefined;
    class FakeIO {
      constructor(cb: IntersectionObserverCallback) {
        callback = cb;
      }
      observe() {}
      disconnect() {}
    }
    globalThis.IntersectionObserver = FakeIO as unknown as typeof IntersectionObserver;
    const { getByTestId } = render(<Probe />);
    const entry = (isIntersecting: boolean) => ({ isIntersecting }) as IntersectionObserverEntry;
    act(() => callback([entry(true), entry(false)], {} as IntersectionObserver));
    expect(getByTestId('probe').getAttribute('data-paused')).toBe('yes');
    act(() => callback([entry(false), entry(true)], {} as IntersectionObserver));
    expect(getByTestId('probe').getAttribute('data-paused')).toBe('no');
  });
});

describe('art mark and surface css', () => {
  const css = readFileSync(resolve(__dirname, '../src/styles/kit.css'), 'utf8');
  const tokens = readFileSync(resolve(__dirname, '../../tokens/tokens.css'), 'utf8');

  it('pauses every layer including pseudo-elements, and wins over recipe shorthands', () => {
    const rule = css.split('\n').find((l) => l.startsWith('.art-mark[data-paused]'));
    expect(rule).toBeDefined();
    expect(rule).toContain('*::before');
    expect(rule).toContain('*::after');
    expect(rule).toContain('!important');
  });

  it('animates the beacon picture only inside a live host or on host hover and focus', () => {
    const lines = css.split('\n').filter((l) => /\.am-img \{ animation: am-flash/.test(l));
    expect(lines.length).toBe(1);
    expect(lines[0]).toMatch(/^\[data-art-host\]:is\(\[data-art-live\], :hover, :focus-visible\)/);
  });

  it('makes the header wash opt-in', () => {
    expect(css).toMatch(/\.page-header\[data-wash\] \{[^}]*--header-wash/);
    const plain = css.split('\n').find((l) => l.startsWith('.page-header {'));
    expect(plain).toBeDefined();
    expect(plain).not.toContain('--header-wash');
    const { container, rerender } = render(<PageHeader title="T" />);
    expect(container.querySelector('.page-header')?.hasAttribute('data-wash')).toBe(false);
    rerender(<PageHeader title="T" wash />);
    expect(container.querySelector('.page-header')?.hasAttribute('data-wash')).toBe(true);
  });

  it('paints the canvas wash on a fixed layer, never with background-attachment fixed', () => {
    expect(css).not.toMatch(/no-repeat fixed|background-attachment:\s*fixed/);
    expect(css).toMatch(/\.shell::before \{[^}]*position: fixed[^}]*--canvas-wash/);
  });

  it('defines --accent-rgb for the default accent and every named accent', () => {
    const named = [...tokens.matchAll(/^:root\[data-app-accent="([a-z-]+)"\] \{([^}]*)\}/gm)];
    expect(named.length).toBeGreaterThan(5);
    for (const [, name, body] of named) expect(body, `accent ${name}`).toMatch(/--accent-rgb: \d+ \d+ \d+;/);
    expect(tokens).toMatch(/^\s+--accent-rgb: \d+ \d+ \d+;/m);
  });
});
