// Action buttons coloured by purpose: page and toolbar buttons are tagged data-act (create, link, transfer) so the
// action hierarchy can colour them (kit.css, "Action buttons coloured by purpose").
// Fails when a primary or secondary Button (or a <button> with the kit's btn class) whose label starts with an
// action verb has no data-act. Opt a button out with data-act="none" (a button that is not a page action).
// Usage: node scripts/check-action-buttons.mjs [dir ...]   (default: src)
import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';

export const VERBS = [
  /^(add|new|create|invite|schedule|request|generate|publish|unpublish)\b/,
  /^(import|export|download|upload|sync|send|copy|print|share|back up)\b/,
  /^(link|assign|manage|edit|open|view|configure|map|connect|move|merge|bulk|review|swap|find|force|compare|set|done editing)\b/,
];

// The visible text of a literal in a label expression: the last quoted string, so {n ? 'Add' : 'Adding...'} reads as the last.
const lit = (m) => {
  const q = [...m.matchAll(/'([^']+)'|"([^"]+)"|`([^`]+)`/g)];
  const last = q[q.length - 1];
  return ` ${last ? (last[1] ?? last[2] ?? last[3]) : ''} `;
};

/** Every <Button ...>label</Button> and <button ...>label</button> in a source: [openingTag, body, line]. */
export function buttons(s) {
  const out = [];
  let i = 0;
  for (;;) {
    const m = /<(Button|button)(?=[\s>])/g;
    m.lastIndex = i;
    const hit = m.exec(s);
    if (!hit) return out;
    const name = hit[1];
    i = hit.index;
    let j = i + hit[0].length;
    let depth = 0;
    let quote = null;
    for (; j < s.length; j++) {
      const c = s[j];
      if (quote) {
        if (c === quote) quote = null;
      } else if ((c === '"' || c === "'") && depth === 0) quote = c;
      else if (c === '{') depth++;
      else if (c === '}') depth--;
      else if (c === '>' && depth === 0 && s[j - 1] !== '=') break;
    }
    if (s[j - 1] === '/') {
      i = j;
      continue;
    }
    const k = s.indexOf(`</${name}>`, j);
    if (k < 0) return out;
    out.push([s.slice(i, j + 1), s.slice(j + 1, k), s.slice(0, i).split('\n').length]);
    i = k;
  }
}

/** The problems in one source: strings naming the line and the label. */
export function scan(file, source) {
  const bad = [];
  for (const [tag, body, line] of buttons(source)) {
    if (tag.includes('data-act')) continue;
    const isComponent = tag.startsWith('<Button');
    const variant = /variant=(?:"([^"]*)"|\{'([^']*)'\})/.exec(tag);
    const v = variant ? (variant[1] ?? variant[2]) : isComponent ? 'secondary' : '';
    if (isComponent ? !(v === 'primary' || v === 'secondary') : !/className="[^"]*\bbtn\b/.test(tag) || !/data-variant="(primary|secondary)"/.test(tag)) continue;
    let t = body.replace(/<[^>]*>/g, ' ');
    t = t.replace(/\{[^{}]*\}/g, (m) => lit(m)).replace(/\{[^{}]*\}/g, (m) => lit(m));
    t = t.replace(/\s+/g, ' ').trim().toLowerCase();
    if (VERBS.some((r) => r.test(t))) bad.push(`${file}:${line}: "${t}" needs data-act="create|link|transfer" (or "none")`);
  }
  return bad;
}

function walk(dir, found) {
  for (const n of readdirSync(dir)) {
    const p = path.join(dir, n);
    if (statSync(p).isDirectory()) {
      if (n !== 'node_modules') walk(p, found);
    } else if (p.endsWith('.tsx')) found.push(p);
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const dirs = process.argv.slice(2);
  const files = [];
  for (const d of dirs.length ? dirs : ['src']) walk(d, files);
  const bad = files.flatMap((f) => scan(f, readFileSync(f, 'utf8')));
  if (bad.length) {
    console.error(bad.join('\n'));
    process.exit(1);
  }
  console.log('Action button scan passed.');
}
