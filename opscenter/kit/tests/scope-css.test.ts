/* The per-module CSS scope plugin (web shell standard, section 5). Runs the plugin through real
   PostCSS, and applies the output in jsdom to prove one module's rules never reach another. */
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import postcss from 'postcss';
import { describe, expect, it } from 'vitest';
import { scopeModuleCss, scopeOf, scopeSelector } from '../scripts/scope-css.mjs';

const FILE = resolve(tmpdir(), 'kit-scope', 'a.css');

async function scope(css: string, id = 'alpha', options: { strictKeyframes?: boolean } = {}, from = FILE) {
  const plugin = scopeModuleCss({ [FILE]: id }, options);
  const result = await postcss([plugin as never]).process(css, { from });
  return { css: result.css, warnings: result.warnings().map((w) => w.text) };
}

describe('scopeSelector', () => {
  it('prefixes an ordinary selector with a zero-specificity scope', () => {
    expect(scopeSelector('.card', 'alpha')).toBe(':where([data-module="alpha"]) .card');
    expect(scopeSelector('a:hover > b', 'alpha')).toBe(':where([data-module="alpha"]) a:hover > b');
  });

  it('maps :root, html, body and #root onto the scope element itself', () => {
    const scoped = ':where([data-module="alpha"])';
    expect(scopeSelector(':root', 'alpha')).toBe(scoped);
    expect(scopeSelector('html', 'alpha')).toBe(scoped);
    expect(scopeSelector('body', 'alpha')).toBe(scoped);
    expect(scopeSelector('#root', 'alpha')).toBe(scoped);
    expect(scopeSelector('body > main', 'alpha')).toBe(`${scoped} > main`);
    expect(scopeSelector('body.compact .row', 'alpha')).toBe(`${scoped}.compact .row`);
    expect(scopeSelector('html body .row', 'alpha')).toBe(`${scoped} .row`);
    expect(scopeSelector(':root[data-density="tight"]', 'alpha')).toBe(`${scoped}[data-density="tight"]`);
  });

  it('does not treat a longer name as a root token', () => {
    expect(scopeSelector('body-bg', 'alpha')).toBe(':where([data-module="alpha"]) body-bg');
    expect(scopeSelector('html5-video', 'alpha')).toBe(':where([data-module="alpha"]) html5-video');
    expect(scopeSelector('#root-note', 'alpha')).toBe(':where([data-module="alpha"]) #root-note');
  });

  it('is idempotent and ignores blanks', () => {
    const once = scopeSelector('.x', 'alpha');
    expect(scopeSelector(once, 'alpha')).toBe(once);
    expect(scopeSelector('  ', 'alpha')).toBe('');
  });

  it('rejects an id that is not a plain slug', () => {
    for (const id of ['', 'A', 'a b', 'a"]x', '-a', 'a'.repeat(65)]) expect(() => scopeOf(id)).toThrow(/slug/);
    expect(scopeOf('a_1-b')).toBe(':where([data-module="a_1-b"])');
  });
});

describe('scopeModuleCss', () => {
  it('scopes every selector of a comma list', async () => {
    const out = await scope('.a, .b > i, :root { color: red }');
    expect(out.css).toBe(
      ':where([data-module="alpha"]) .a, :where([data-module="alpha"]) .b > i, :where([data-module="alpha"]) { color: red }',
    );
  });

  it('scopes rules inside media, supports and layer at-rules and keeps the at-rule', async () => {
    const out = await scope(
      '@media (min-width: 40rem) { .a { top: 0 } } @supports (display: grid) { .b { top: 0 } } @layer base { .c { top: 0 } }',
    );
    expect(out.css).toContain('@media (min-width: 40rem) { :where([data-module="alpha"]) .a');
    expect(out.css).toContain('@supports (display: grid) { :where([data-module="alpha"]) .b');
    expect(out.css).toContain('@layer base { :where([data-module="alpha"]) .c');
  });

  it('keeps keyframes global: the name and the step selectors are untouched', async () => {
    const out = await scope('@keyframes alpha-fade { from { opacity: 0 } 50% { opacity: .5 } to { opacity: 1 } } .a { animation: alpha-fade 1s }');
    expect(out.css).toContain('@keyframes alpha-fade { from { opacity: 0 } 50% { opacity: .5 } to { opacity: 1 } }');
    expect(out.css).toContain(':where([data-module="alpha"]) .a { animation: alpha-fade 1s }');
    expect(out.warnings).toEqual([]);
  });

  it('keeps vendor-prefixed keyframes global as well', async () => {
    const out = await scope('@-webkit-keyframes alpha-spin { to { transform: rotate(1turn) } }');
    expect(out.css).toBe('@-webkit-keyframes alpha-spin { to { transform: rotate(1turn) } }');
  });

  it('keeps font faces global', async () => {
    const face = '@font-face { font-family: "Face"; src: url(face.woff2) format("woff2") }';
    const out = await scope(`${face} .a { font-family: "Face" }`);
    expect(out.css.startsWith(face)).toBe(true);
    expect(out.css).toContain(':where([data-module="alpha"]) .a');
  });

  it('warns about a keyframes name that is not prefixed with the module id', async () => {
    const out = await scope('@keyframes fade { to { opacity: 1 } }');
    expect(out.warnings).toHaveLength(1);
    expect(out.warnings[0]).toMatch(/must be named alpha-<name>/);
  });

  it('fails on a badly named keyframes in strict mode', async () => {
    await expect(scope('@keyframes beta-fade { to { opacity: 1 } }', 'alpha', { strictKeyframes: true })).rejects.toThrow(/alpha-<name>/);
  });

  it('leaves a sheet that is not listed alone', async () => {
    const css = '.a { color: red } body { margin: 0 }';
    const out = await scope(css, 'alpha', {}, resolve(tmpdir(), 'kit-scope', 'other.css'));
    expect(out.css).toBe(css);
  });

  it('resolves a sheet path that carries a query string', async () => {
    const out = await scope('.a { top: 0 }', 'alpha', {}, `${FILE}?inline`);
    expect(out.css).toContain(':where([data-module="alpha"]) .a');
  });

  it('rejects a bad module id when the plugin is created, not during a build', () => {
    expect(() => scopeModuleCss({ [FILE]: 'Not A Slug' })).toThrow(/slug/);
  });

  it('does not change specificity: the scope adds none', async () => {
    const out = await scope('.a { top: 0 }');
    const rule = postcss.parse(out.css).first as import('postcss').Rule;
    expect(rule.selector.startsWith(':where(')).toBe(true);
  });
});

describe('scoped output in a document', () => {
  function mount(css: string) {
    document.head.innerHTML = `<style>${css}</style>`;
    document.body.innerHTML = `
      <div id="m-alpha" data-module="alpha"><p class="note">a</p><div id="portal-a"><p class="note">dialog</p></div></div>
      <div id="m-beta" data-module="beta"><p class="note">b</p></div>
      <p class="note" id="outside">outside</p>`;
  }

  it('matches only inside the module that owns the rule, portal root included', async () => {
    const out = await scope('.note { color: red }');
    const selector = (postcss.parse(out.css).first as import('postcss').Rule).selector;
    mount(out.css);
    const hits = [...document.querySelectorAll(selector)].map((el) => el.textContent);
    expect(hits).toEqual(['a', 'dialog']);
    expect(document.querySelector('#m-beta .note')?.matches(selector)).toBe(false);
    expect(document.getElementById('outside')?.matches(selector)).toBe(false);
  });

  it('maps a body rule onto the module element and nothing else', async () => {
    const out = await scope('body { margin: 0 }');
    const selector = (postcss.parse(out.css).first as import('postcss').Rule).selector;
    mount(out.css);
    expect([...document.querySelectorAll(selector)].map((el) => el.id)).toEqual(['m-alpha']);
  });
});

type Opts = { strictKeyframes?: boolean; keyframes?: 'warn' | 'strict' | 'rename'; root?: 'wrapper' | 'document' };
async function run(css: string, options: Opts, id = 'alpha') {
  const result = await postcss([scopeModuleCss({ [FILE]: id }, options) as never]).process(css, { from: FILE });
  return { css: result.css, warnings: result.warnings().map((w) => w.text) };
}

describe('root option', () => {
  const wrapped = ':where([data-module="alpha"])';
  const doc = { root: 'document' as const };

  it('defaults to wrapper and gives the same output as passing wrapper', async () => {
    const css = ':root { a: b } html body .x { c: d } #root { e: f }';
    expect((await run(css, {})).css).toBe((await run(css, { root: 'wrapper' })).css);
    expect(scopeSelector('body', 'alpha', { root: 'wrapper' })).toBe(wrapped);
  });

  it('document mode keeps :root and html on the document element, scoped to it', () => {
    expect(scopeSelector(':root', 'alpha', doc)).toBe(':where(:root[data-module="alpha"])');
    expect(scopeSelector('html', 'alpha', doc)).toBe(':where(html[data-module="alpha"])');
    expect(scopeSelector(':root[data-density="tight"]', 'alpha', doc)).toBe(
      ':where(:root[data-module="alpha"])[data-density="tight"]',
    );
    expect(scopeSelector('html.dark .x', 'alpha', doc)).toBe(':where(html[data-module="alpha"]).dark .x');
  });

  it('document mode keeps body and #root as descendants of the scope element', () => {
    expect(scopeSelector('body', 'alpha', doc)).toBe(`${wrapped} body`);
    expect(scopeSelector('#root', 'alpha', doc)).toBe(`${wrapped} #root`);
    expect(scopeSelector('body.compact .row', 'alpha', doc)).toBe(`${wrapped} body.compact .row`);
    expect(scopeSelector('html body .row', 'alpha', doc)).toBe(':where(html[data-module="alpha"]) body .row');
    expect(scopeSelector('html > body', 'alpha', doc)).toBe(':where(html[data-module="alpha"]) > body');
  });

  it('document mode scopes ordinary selectors as descendants and ignores longer names', () => {
    expect(scopeSelector('.card', 'alpha', doc)).toBe(`${wrapped} .card`);
    expect(scopeSelector('html5-video', 'alpha', doc)).toBe(`${wrapped} html5-video`);
    expect(scopeSelector(':rooted', 'alpha', doc)).toBe(`${wrapped} :rooted`);
  });

  it('document mode is idempotent', () => {
    for (const sel of [':root', 'html', 'body', '.x', 'html body .y']) {
      const once = scopeSelector(sel, 'alpha', doc);
      expect(scopeSelector(once, 'alpha', doc)).toBe(once);
    }
  });

  it('document mode through PostCSS, inside media, with a comma list', async () => {
    const out = await run(':root, body { margin: 0 } @media (min-width: 40rem) { html { top: 0 } }', doc);
    expect(out.css).toBe(
      `:where(:root[data-module="alpha"]), ${wrapped} body { margin: 0 } @media (min-width: 40rem) { :where(html[data-module="alpha"]) { top: 0 } }`,
    );
  });

  it('rejects an unknown root mode', () => {
    expect(() => scopeModuleCss({ [FILE]: 'alpha' }, { root: 'x' as never })).toThrow(/wrapper or document/);
    expect(() => scopeSelector('a', 'alpha', { root: 'x' as never })).toThrow(/wrapper or document/);
  });

  it('applied in a document whose root element carries data-module', async () => {
    const out = await run(':root { color: red } body { color: blue } .note { color: green }', doc);
    const rules = postcss.parse(out.css).nodes as [import('postcss').Rule, import('postcss').Rule, import('postcss').Rule];
    document.documentElement.setAttribute('data-module', 'alpha');
    document.head.innerHTML = '';
    document.body.innerHTML = '<p class="note">n</p><div id="root"></div>';
    try {
      expect(document.documentElement.matches(rules[0].selector)).toBe(true);
      expect(document.body.matches(rules[0].selector)).toBe(false);
      expect(document.body.matches(rules[1].selector)).toBe(true);
      expect(document.documentElement.matches(rules[1].selector)).toBe(false);
      expect(document.querySelector('.note')?.matches(rules[2].selector)).toBe(true);
      document.documentElement.setAttribute('data-module', 'beta');
      expect(document.documentElement.matches(rules[0].selector)).toBe(false);
      expect(document.body.matches(rules[1].selector)).toBe(false);
    } finally {
      document.documentElement.removeAttribute('data-module');
    }
  });
});

describe('keyframes rename mode', () => {
  const rename = { keyframes: 'rename' as const };

  it('prefixes the name and rewrites animation and animation-name in the sheet', async () => {
    const out = await run(
      '@keyframes fade { to { opacity: 1 } } .a { animation: fade 1s ease-in; animation-name: fade, other } .b { animation: 1s fade, 2s spin }',
      rename,
    );
    expect(out.css).toContain('@keyframes alpha-fade { to { opacity: 1 } }');
    expect(out.css).toContain('animation: alpha-fade 1s ease-in');
    expect(out.css).toContain('animation-name: alpha-fade, other');
    expect(out.css).toContain('animation: 1s alpha-fade, 2s spin');
    expect(out.warnings).toEqual([]);
  });

  it('leaves a name that is already prefixed, and only matches whole words', async () => {
    const out = await run(
      '@keyframes alpha-in { to { top: 0 } } @keyframes fade { to { top: 0 } } .a { animation: alpha-in 1s, fade-out 1s, fade 1s } .b { transition: fade 1s }',
      rename,
    );
    expect(out.css).toContain('animation: alpha-in 1s, fade-out 1s, alpha-fade 1s');
    expect(out.css).toContain('transition: fade 1s');
    expect(out.css).not.toContain('alpha-alpha');
  });

  it('handles vendor prefixes, nested at-rules and the prefixed animation property', async () => {
    const out = await run(
      '@-webkit-keyframes spin { to { top: 0 } } @media (min-width: 40rem) { .a { -webkit-animation: spin 1s } }',
      rename,
    );
    expect(out.css).toContain('@-webkit-keyframes alpha-spin');
    expect(out.css).toContain('-webkit-animation: alpha-spin 1s');
  });

  it('does not touch quoted text or function arguments', async () => {
    const out = await run('@keyframes fade { to { top: 0 } } .a { animation: fade 1s cubic-bezier(0, 0, 1, 1) } .b { content: "fade" }', rename);
    expect(out.css).toContain('animation: alpha-fade 1s cubic-bezier(0, 0, 1, 1)');
    expect(out.css).toContain('content: "fade"');
  });

  it('keeps keyframes steps unscoped', async () => {
    const out = await run('@keyframes fade { from { opacity: 0 } to { opacity: 1 } }', rename);
    expect(out.css).toBe('@keyframes alpha-fade { from { opacity: 0 } to { opacity: 1 } }');
  });

  it('fails when the renamed name already exists', async () => {
    await expect(run('@keyframes fade { to { top: 0 } } @keyframes alpha-fade { to { top: 1 } }', rename)).rejects.toThrow(/already exists/);
  });

  it('warns about a name that is not a plain identifier and leaves it', async () => {
    const out = await run('@keyframes "odd name" { to { top: 0 } }', rename);
    expect(out.warnings[0]).toMatch(/cannot be renamed/);
    expect(out.css).toContain('@keyframes "odd name"');
  });

  it('keyframes: strict equals strictKeyframes, warn is the default, junk is rejected', async () => {
    await expect(run('@keyframes fade { to { top: 0 } }', { keyframes: 'strict' })).rejects.toThrow(/alpha-<name>/);
    expect((await run('@keyframes fade { to { top: 0 } }', { keyframes: 'warn' })).warnings).toHaveLength(1);
    expect(() => scopeModuleCss({ [FILE]: 'alpha' }, { keyframes: 'x' as never })).toThrow(/warn, strict or rename/);
  });

  it('works together with the document root mode', async () => {
    const out = await run('@keyframes fade { to { top: 0 } } html { animation: fade 1s }', { ...rename, root: 'document' });
    expect(out.css).toContain(':where(html[data-module="alpha"]) { animation: alpha-fade 1s }');
  });
});
