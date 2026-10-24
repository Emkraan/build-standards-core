/* Static scan of kit/src: the shapes the standard forbids never reach the kit source. It mirrors
   the core UI lint (lint/ui_lint.py) so a regression fails here as well as in CI. */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC = resolve(__dirname, '../src');

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? files(p) : /\.(tsx?|css)$/.test(name) ? [p] : [];
  });
}

/** Blanks comments so prose about a rule never trips the rule. */
function stripComments(text: string, css: boolean): string {
  const blank = (m: string) => m.replace(/[^\n]/g, ' ');
  let out = text.replace(/\/\*[\s\S]*?\*\//g, blank);
  if (!css) out = out.replace(/(?<![:'"\\])\/\/[^\n]*/g, blank);
  return out;
}

interface Finding {
  file: string;
  line: number;
  rule: string;
  text: string;
}

function scan(): Finding[] {
  const found: Finding[] = [];
  for (const f of files(SRC)) {
    const css = f.endsWith('.css');
    const clean = stripComments(readFileSync(f, 'utf8'), css);
    const add = (rule: string, index: number, text: string) =>
      found.push({ file: relative(SRC, f), line: clean.slice(0, index).split('\n').length, rule, text: text.trim().slice(0, 60) });
    const each = (re: RegExp, rule: string, keep: (m: RegExpExecArray) => boolean = () => true) => {
      for (const m of clean.matchAll(re)) if (keep(m as RegExpExecArray)) add(rule, m.index ?? 0, m[0]);
    };
    // Colour literals: hex or functional colours with numbers. Token reads such as rgb(var(--x)) pass.
    each(/(?<![\w&/-])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])/g, 'colour literal');
    each(/\b(?:rgba?|hsla?|oklch|oklab|hwb)\(\s*[\d.]/g, 'colour literal');
    // Native dialogs.
    each(/(?<![\w.$])(?:window\.)?(?:alert|confirm|prompt)\s*\(/g, 'native dialog');
    if (css) {
      each(/z-index\s*:\s*(-?\d+)/g, 'raw z-index', (m) => m[1] !== '0' && m[1] !== '-1');
      for (const m of clean.matchAll(/(transition|animation)[\w-]*\s*:([^;}]*)/g)) {
        const value = (m[2] ?? '').replace(/var\([^)]*\)/g, '');
        if (/(?<![\w.-])(\d*\.?[1-9]\d*)(ms|s)\b/.test(value)) add('raw duration', m.index ?? 0, m[0]);
      }
      for (const m of clean.matchAll(/border-(left|right|top|bottom|inline-start|inline-end|block-start|block-end)(-width)?\s*:([^;}]*)/g)) {
        const value = m[3] ?? '';
        const px = /(\d+(?:\.\d+)?)px/.exec(value);
        const coloured = /accent|hue|success|warning|danger|info|#|rgb|hsl/.test(value) && !/transparent/.test(value);
        if ((px && Number(px[1]) >= 2) || coloured) add('single-side coloured border', m.index ?? 0, m[0]);
      }
      each(/\[data-theme|prefers-color-scheme/g, 'theme branching');
      each(/(?<![\w-])--(?:accent[\w-]*|focus-ring|border-accent(?:-strong)?)\s*:/g, 'accent token set outside the root');
    } else {
      each(/zIndex\s*:\s*(-?\d+)/g, 'raw z-index', (m) => m[1] !== '0' && m[1] !== '-1');
      each(/\b(?:transition|animation)(?:Duration|Delay)?\s*:\s*(['"`])[^'"`]*?(?<![\w.-])\d*\.?[1-9]\d*(?:ms|s)\b[^'"`]*\1/g, 'raw duration');
      each(/\bborder(?:Left|Right|Top|Bottom|InlineStart|InlineEnd)(?:Width|Color)?\s*:/g, 'single-side border');
    }
  }
  return found;
}

describe('kit source scan', () => {
  it('scans every source file', () => {
    expect(files(SRC).length).toBeGreaterThan(20);
  });

  it('has no colour literal, raw z-index, raw duration, native dialog, edge bar, theme branch or accent write', () => {
    expect(scan()).toEqual([]);
  });

  it('writes data-app-accent in exactly one place', () => {
    const writers = files(SRC).filter((f) => /setAttribute\(\s*['"]data-app-accent|dataset\.appAccent\s*=/.test(readFileSync(f, 'utf8')));
    expect(writers.map((f) => relative(SRC, f))).toEqual([join('theme', 'accent.tsx')]);
  });

  it('catches each forbidden shape (the scanner itself works)', () => {
    const samples = ['#1a2b3c', 'rgb(1, 2, 3)', 'window.alert(1)', 'confirm("x")'];
    const colour = /(?<![\w&/-])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])/;
    const fn = /\b(?:rgba?|hsla?|oklch|oklab|hwb)\(\s*[\d.]/;
    const dialog = /(?<![\w.$])(?:window\.)?(?:alert|confirm|prompt)\s*\(/;
    expect(colour.test(samples[0] ?? '')).toBe(true);
    expect(fn.test(samples[1] ?? '')).toBe(true);
    expect(dialog.test(samples[2] ?? '')).toBe(true);
    expect(dialog.test(samples[3] ?? '')).toBe(true);
    expect(dialog.test('api.confirm({})')).toBe(false);
  });
});
