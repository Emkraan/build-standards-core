#!/usr/bin/env node
/*
 * scope-css.mjs: per-module CSS scope for a multi-module shell (the web shell standard, section 5).
 *
 * A module's stylesheet is rewritten at build time so every rule applies only while that module
 * is mounted. Each selector is prefixed with :where([data-module="<id>"]). :where adds zero
 * specificity, so the cascade between the kit, the shell and the module is unchanged (unlayered
 * app CSS still beats the kit) and one module's CSS cannot restyle another.
 *
 *   :root, html, body, #root   map onto the element that carries data-module (that element wraps
 *                              the module's portal root, so dialogs and toasts still match)
 *   keyframes                  stay global: name each one <id>-<name> (checked, see below)
 *   font faces                 stay global (an at-rule with no selectors, left alone)
 *   media, supports, layer     the rules inside are scoped, the at-rule is kept
 *
 * Usage as a PostCSS plugin (a plain object, no postcss import needed). In the build config:
 *
 *   import { scopeModuleCss } from './scripts/scope-css.mjs';
 *   css: { postcss: { plugins: [scopeModuleCss({ [resolve('src/modules/a/index.css')]: 'a' })] } }
 *
 * Options (second argument):
 *   strictKeyframes  a keyframes name that does not start with "<id>-" is an error (default: a warning)
 *   keyframes        'warn' (default), 'strict' (same as strictKeyframes) or 'rename': prefix the name
 *                    with "<id>-" and rewrite the animation and animation-name references in the same
 *                    sheet. A reference in another sheet or a script is not seen, so name those
 *                    keyframes by hand.
 *   root             'wrapper' (default) maps :root, html, body and #root onto the data-module element.
 *                    'document' is for a host that puts data-module on the document element itself:
 *                    :root and html stay on that element (scoped to it) and body and #root stay
 *                    descendants of it.
 *
 * Limits: a root token is mapped only at the start of a selector (and when several are chained
 * with spaces, as in "html body .x"). A module sheet that styles a theme attribute on the root
 * should use the kit tokens instead, because the theme attribute lives on the document element.
 */
import { resolve } from 'node:path';

const ID = /^[a-z0-9][a-z0-9_-]{0,63}$/;
const ROOT_TOKEN = '(?::root|html|body|#root)(?![\\w-])';
const ROOT_CHAIN = new RegExp(`^${ROOT_TOKEN}(?:\\s+${ROOT_TOKEN})*`);

const DOC_ROOT = /^(:root|html)(?![\w-])/;
const ROOT_MODES = ['wrapper', 'document'];
const KEYFRAME_MODES = ['warn', 'strict', 'rename'];

/** The zero-specificity scope for a module id. Throws on an id that is not a plain slug. */
export function scopeOf(id) {
  if (typeof id !== 'string' || !ID.test(id)) {
    throw new Error(`module id "${String(id)}" is not a lowercase letters, digits, - or _ slug`);
  }
  return `:where([data-module="${id}"])`;
}

/** Scope one selector (no commas) to a module. Already scoped selectors are returned unchanged. */
export function scopeSelector(selector, id, options = {}) {
  const scope = scopeOf(id);
  const s = String(selector).trim();
  if (!s) return s;
  if (s.startsWith(scope)) return s;
  const mode = options.root || 'wrapper';
  if (!ROOT_MODES.includes(mode)) throw new Error(`root option "${String(mode)}" must be wrapper or document`);
  if (mode === 'document') {
    if (s.startsWith(`:where(:root[data-module="${id}"])`) || s.startsWith(`:where(html[data-module="${id}"])`)) return s;
    const top = DOC_ROOT.exec(s);
    if (top) return `:where(${top[1]}[data-module="${id}"])${s.slice(top[0].length)}`;
    return `${scope} ${s}`;
  }
  const root = ROOT_CHAIN.exec(s);
  if (root) return scope + s.slice(root[0].length);
  return `${scope} ${s}`;
}

/** True when a rule sits inside a keyframes at-rule, whose selectors are percentages. */
function inKeyframes(rule) {
  for (let p = rule.parent; p; p = p.parent) {
    if (p.type === 'atrule' && /keyframes$/i.test(p.name)) return true;
  }
  return false;
}

/** Rewrite a whole-word animation name in an animation or animation-name value. Quoted text is left alone. */
function renameInValue(value, names) {
  let out = '';
  let depth = 0;
  let quote = '';
  let i = 0;
  while (i < value.length) {
    const ch = value[i];
    if (quote) {
      out += ch;
      if (ch === '\\') out += value[++i] || '';
      else if (ch === quote) quote = '';
      i++;
    } else if (ch === '"' || ch === "'") {
      quote = ch;
      out += ch;
      i++;
    } else if (ch === '(') {
      depth++;
      out += ch;
      i++;
    } else if (ch === ')') {
      depth = Math.max(0, depth - 1);
      out += ch;
      i++;
    } else if (/[\w-]/.test(ch) && depth === 0) {
      let j = i;
      while (j < value.length && /[\w-]/.test(value[j])) j++;
      const word = value.slice(i, j);
      out += names.has(word) ? names.get(word) : word;
      i = j;
    } else {
      out += ch;
      i++;
    }
  }
  return out;
}

/**
 * A PostCSS plugin that scopes the listed sheets and leaves every other sheet alone.
 * @param {Record<string, string>} files absolute sheet path -> module id
 * @param {{ strictKeyframes?: boolean, keyframes?: 'warn' | 'strict' | 'rename', root?: 'wrapper' | 'document' }} [options]
 */
export function scopeModuleCss(files, options = {}) {
  const table = new Map(Object.entries(files).map(([path, id]) => [resolve(path), id]));
  for (const id of table.values()) scopeOf(id);
  const rootMode = options.root || 'wrapper';
  if (!ROOT_MODES.includes(rootMode)) throw new Error(`root option "${String(rootMode)}" must be wrapper or document`);
  const frames = options.keyframes || (options.strictKeyframes ? 'strict' : 'warn');
  if (!KEYFRAME_MODES.includes(frames)) throw new Error(`keyframes option "${String(frames)}" must be warn, strict or rename`);
  return {
    postcssPlugin: 'module-scope',
    Once(root, helpers) {
      const file = root.source && root.source.input && root.source.input.file;
      const id = file ? table.get(resolve(String(file).split('?')[0])) : undefined;
      if (!id) return;
      const renamed = new Map();
      const present = new Set();
      root.walkAtRules(/keyframes$/i, (atRule) => present.add(atRule.params));
      root.walkAtRules(/keyframes$/i, (atRule) => {
        if (atRule.params.startsWith(`${id}-`)) return;
        if (frames === 'rename') {
          const name = atRule.params.trim();
          const next = `${id}-${name}`;
          if (!/^-?[A-Za-z_][\w-]*$/.test(name)) {
            helpers.result.warn(`keyframes "${name}" cannot be renamed (not a plain identifier), name it ${id}-<name>`, { node: atRule });
            return;
          }
          if (present.has(next)) throw atRule.error(`keyframes "${name}" would be renamed to "${next}", which already exists`);
          renamed.set(name, next);
          atRule.params = next;
          return;
        }
        const text = `keyframes "${atRule.params}" must be named ${id}-<name> (keyframes cannot be scoped)`;
        if (frames === 'strict') throw atRule.error(text);
        helpers.result.warn(text, { node: atRule });
      });
      if (renamed.size) {
        root.walkDecls(/^(-\w+-)?animation(-name)?$/i, (decl) => {
          decl.value = renameInValue(decl.value, renamed);
        });
      }
      root.walkRules((rule) => {
        if (inKeyframes(rule)) return;
        rule.selectors = rule.selectors.map((sel) => scopeSelector(sel, id, { root: rootMode }));
      });
    },
  };
}
