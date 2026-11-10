import { describe, expect, it } from 'vitest';
import { accents, categoricalHues, defaultAccent, tokens } from '../../tokens/tokens';
import { CATEGORICAL_HUES, categoricalHueNames, categoricalPalette, chartTheme, resolveColor, withheldHue } from '../src/index';

function setVar(name: string, value: string): void {
  document.documentElement.style.setProperty(name, value);
}

describe('categoricalPalette', () => {
  it('matches the categorical hues in the token source', () => {
    expect([...CATEGORICAL_HUES]).toEqual([...categoricalHues]);
  });

  it('withholds the hue named by --accent-withheld-hue', () => {
    setVar('--accent-withheld-hue', 'blue');
    setVar('--hue-green', '34 197 94');
    expect(withheldHue()).toBe('blue');
    const palette = categoricalPalette();
    expect(palette.map((s) => s.name)).toEqual(['green', 'amber', 'red', 'violet', 'teal']);
    expect(palette[0]?.color).toBe('rgb(34, 197, 94)');
  });

  it("treats 'none' and an unset value as no withheld hue", () => {
    setVar('--accent-withheld-hue', 'none');
    expect(withheldHue()).toBeNull();
    expect(categoricalHueNames()).toHaveLength(6);
    document.documentElement.style.removeProperty('--accent-withheld-hue');
    expect(categoricalHueNames()).toEqual([...CATEGORICAL_HUES]);
  });

  it('withholds the right hue for every named accent in the token source', () => {
    const all = { [defaultAccent]: { withheld: tokens.dark['accent-withheld-hue'] }, ...accents } as Record<string, { withheld: string }>;
    expect(Object.keys(all)).toHaveLength(14);
    for (const [name, accent] of Object.entries(all)) {
      setVar('--accent-withheld-hue', accent.withheld);
      const names = categoricalHueNames();
      if (accent.withheld === 'none') expect(names, name).toHaveLength(6);
      else {
        expect(names, name).toHaveLength(5);
        expect(names, name).not.toContain(accent.withheld);
      }
    }
  });
});

describe('chartTheme', () => {
  it('reads computed variables and leaves the accent out of the series', () => {
    setVar('--accent-withheld-hue', 'violet');
    setVar('--accent-rgb', '139 92 246');
    setVar('--border-default', 'rgba(255, 255, 255, 0.1)');
    const theme = chartTheme();
    expect(theme.accent).toBe('rgb(139, 92, 246)');
    expect(theme.grid).toBe('rgba(255, 255, 255, 0.1)');
    expect(theme.series).toHaveLength(5);
    expect(theme.status.inProgress).toBe(theme.accent);
  });

  it('resolves triplets and passes other colours through', () => {
    expect(resolveColor('1 2 3')).toBe('rgb(1, 2, 3)');
    expect(resolveColor('')).toBe('');
    expect(resolveColor('currentColor')).toBe('currentColor');
  });
});
