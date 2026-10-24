/* The overflow detector behind web-ui.md rule 0.10 (content stays inside its box). It runs inside
   a page, so it must stay self-contained: no imports and no closures over module scope, because
   Playwright and the DevTools probe both send its source text to the browser.

   For every visible text node it walks up to the nearest ancestor that either paints a box (a
   border or a fill) or clips (overflow other than visible), and reports:
   - escapes: the text sticks out of the nearest painted box by more than the tolerance,
   - clipped: a clipping box that is not a scroll container cuts the text off without an ellipsis
     or a line clamp.
   Visually hidden text (display none, visibility hidden, opacity 0, clip or clip-path) is skipped.
   Findings are deduplicated per box, so a repeated pattern is reported once. */

export interface OverflowFinding {
  kind: 'escapes' | 'clipped';
  /** A short path to the box: tag, id, first classes and label of up to four ancestors. */
  box: string;
  /** The first 80 characters of the text that does not fit. */
  text: string;
  /** How far the text reaches past the box edge, in CSS pixels. */
  over: number;
}

export function findOverflow(tolerance = 1.5): OverflowFinding[] {
  const out: OverflowFinding[] = [];
  const seen = new Set<string>();
  const label = (el: Element): string => {
    let s = el.tagName.toLowerCase();
    if (el.id) s += `#${el.id}`;
    const classes = (el.getAttribute('class') ?? '').trim().split(/\s+/).filter(Boolean).slice(0, 3);
    if (classes.length) s += `.${classes.join('.')}`;
    const name = el.getAttribute('aria-label') ?? el.getAttribute('title');
    if (name) s += `[${name.slice(0, 40)}]`;
    return s;
  };
  const path = (el: Element): string => {
    const parts: string[] = [];
    let e: Element | null = el;
    for (let i = 0; e && e !== document.body && i < 4; i += 1, e = e.parentElement) parts.unshift(label(e));
    return parts.join(' > ');
  };
  const prop = (cs: CSSStyleDeclaration, name: string): string => cs.getPropertyValue(name);
  const transparent = (c: string): boolean => c === 'transparent' || /rgba\(.*,\s*0\)$/.test(c);
  const paintsBox = (cs: CSSStyleDeclaration): boolean => {
    const bordered = ['top', 'right', 'bottom', 'left'].some(
      (side) => parseFloat(prop(cs, `border-${side}-width`)) > 0 && prop(cs, `border-${side}-style`) !== 'none',
    );
    return bordered || !transparent(prop(cs, 'background-color')) || prop(cs, 'background-image') !== 'none';
  };
  const hidden = (el: Element): boolean => {
    for (let e: Element | null = el; e && e !== document.documentElement; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) return true;
      const clip = prop(cs, 'clip');
      if (clip && clip !== 'auto') return true;
      const clipPath = prop(cs, 'clip-path');
      if (clipPath && clipPath !== 'none') return true;
    }
    return false;
  };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = (node.textContent ?? '').replace(/\s+/g, ' ').trim();
    const el = node.parentElement;
    if (!text || !el || ['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEXTAREA', 'OPTION'].includes(el.tagName)) continue;
    const range = document.createRange();
    range.selectNodeContents(node);
    const rects = Array.from(range.getClientRects()).filter((r) => r.width > 0 && r.height > 0);
    if (!rects.length) continue;
    const top = Math.min(...rects.map((r) => r.top));
    const bottom = Math.max(...rects.map((r) => r.bottom));
    const left = Math.min(...rects.map((r) => r.left));
    const right = Math.max(...rects.map((r) => r.right));
    if (right - left <= 1 || bottom - top <= 1 || hidden(el)) continue;
    let ellipsis = false;
    for (let a: Element | null = el; a && a !== document.body; a = a.parentElement) {
      const cs = getComputedStyle(a);
      if (prop(cs, 'text-overflow') === 'ellipsis' || parseInt(prop(cs, '-webkit-line-clamp') || '0', 10) > 0) ellipsis = true;
      const clips = cs.overflowX !== 'visible' || cs.overflowY !== 'visible';
      if (!clips && !paintsBox(cs)) continue;
      const b = a.getBoundingClientRect();
      if (b.width < 2 || b.height < 2) break;
      const over = Math.max(b.top - top, bottom - b.bottom, b.left - left, right - b.right);
      const scrolls = /auto|scroll/.test(`${cs.overflowX} ${cs.overflowY}`);
      const kind = clips ? (scrolls || ellipsis ? null : 'clipped') : 'escapes';
      if (kind && over > tolerance) {
        const key = `${kind}|${path(a)}`;
        if (!seen.has(key)) {
          seen.add(key);
          out.push({ kind, box: path(a), text: text.slice(0, 80), over: Math.round(over * 10) / 10 });
        }
      }
      break;
    }
  }
  return out;
}
