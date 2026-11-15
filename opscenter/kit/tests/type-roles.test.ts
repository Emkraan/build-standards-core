/* The type role tokens: declared once in tokens.css, theme independent, and used by the kit parts
   that set monospace text. */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const read = (p: string) => readFileSync(resolve(__dirname, p), 'utf8');
const tokens = read('../../tokens/tokens.css');
const kit = read('../src/styles/kit.css') + read('../src/graph/graph.css');

const ROLES: Record<string, string> = {
  'fs-title': '24px',
  'fs-stat': '18px',
  'fs-subtitle': '15px',
  'fs-caption': '11px',
  'fs-mono': '12px',
  'fs-mono-caption': '11px',
  'lh-display': '1.04',
  'lh-title': '1.15',
  'lh-stat': '1.1',
  'lh-subtitle': '1.3',
  'lh-label': '1.35',
  'lh-caption': '1.4',
  'track-stat': '-0.018em',
  'track-subtitle': '-0.010em',
  'track-label': '0.004em',
  'track-caption': '0.008em',
  'track-eyebrow': '0.10em',
};

/** The block of tokens.css that is not under a light theme selector. */
const base = tokens.split(/\[data-theme="light"\]/)[0] ?? tokens;

describe('type role tokens', () => {
  for (const [name, value] of Object.entries(ROLES)) {
    it(`--${name} is ${value} in the base block`, () => {
      expect(base).toContain(`--${name}: ${value};`);
    });
  }

  it('is declared once and not redeclared per theme', () => {
    for (const name of Object.keys(ROLES)) {
      const count = tokens.split(`--${name}:`).length - 1;
      expect(count, `--${name} declarations`).toBe(1);
    }
  });

  it('the kit sets monospace text from the mono role tokens', () => {
    expect(kit).not.toMatch(/font-family: var\(--font-mono\); font-size: var\(--fs-(micro|label)\)/);
    expect(kit).toContain('font-size: var(--fs-mono-caption)');
    expect(kit).toContain('font-size: var(--fs-mono)');
  });
});

const WEIGHTS: Record<string, string> = { 'fw-medium': '500', 'fw-semibold': '600', 'fw-bold': '700', 'fw-extrabold': '800' };

describe('font weight tokens', () => {
  for (const [name, value] of Object.entries(WEIGHTS)) {
    it(`--${name} is ${value}, declared once and theme independent`, () => {
      expect(base).toContain(`--${name}: ${value};`);
      expect(tokens.split(`--${name}:`).length - 1).toBe(1);
    });
  }

  it('the kit sets its weights from the tokens, not bare numbers', () => {
    expect(kit).not.toMatch(/font-weight: (500|600|700|800)\b/);
    expect(kit).toContain('font-weight: var(--fw-semibold)');
  });

  it('the generated outputs carry the weights', () => {
    const ts = read('../../tokens/tokens.ts');
    const tw = read('../../tokens/tailwind.preset.cjs');
    const xaml = read('../../tokens/wpf/Tokens.Dark.xaml');
    for (const [name, value] of Object.entries(WEIGHTS)) {
      expect(ts).toContain(`"${name}": "${value}"`);
      expect(tw).toContain(`"${name.slice(3)}": "var(--${name})"`);
    }
    expect(xaml).toContain('<FontWeight x:Key="Weight.FwSemibold">SemiBold</FontWeight>');
  });
});
