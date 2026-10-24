import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// The redaction script lives in checks/ and is evaluated as one expression in the page, the way a
// browser tool loads it, so the test does the same with an indirect eval.
const script = readFileSync(resolve(__dirname, '../../checks/redact_page.js'), 'utf8');
const fixture = readFileSync(resolve(__dirname, 'fixtures/redact-page.html'), 'utf8');

type Result = { count: number; leftover: string[]; cssGenerated: string[] };
const redact = (): Result => (0, eval)(script) as Result;

// x and 0 are the filler the scrub writes, anything else alphanumeric is real text.
const REAL = /[A-WYZa-wyz1-9]/;

beforeEach(() => {
  vi.useFakeTimers();
  document.head.innerHTML = '';
  document.body.innerHTML = '';
  // The fixture's style element goes in the head, the rest in the body.
  const holder = document.createElement('div');
  holder.innerHTML = fixture;
  const style = holder.querySelector('style');
  if (style) document.head.appendChild(style);
  document.body.append(...Array.from(holder.childNodes));
});

afterEach(() => {
  vi.useRealTimers();
});

describe('redact_page.js', () => {
  it('replaces letters with x and digits with 0 in text, values, placeholders and attributes', () => {
    const result = redact();
    expect(result.count).toBe(0);
    expect(result.leftover).toEqual([]);
    expect(document.getElementById('count')?.textContent).toBe('xxxxx: 0,000 xxxxx xx 0000-00-00');
    expect(document.getElementById('name')?.getAttribute('placeholder')).toBe('xxxxxx xxxxxxxxx');
    expect((document.getElementById('name') as HTMLInputElement).value).toBe('xxxx xxx 00');
    expect((document.getElementById('note') as HTMLTextAreaElement).placeholder).toBe('xxxxx xxx xxxx 0');
    expect(document.getElementById('photo')?.getAttribute('alt')).toBe('xxxxxxxx xx xxxx');
    expect(document.querySelector('button')?.getAttribute('aria-label')).toBe('xxxxxx xxxxxx 0');
    expect(document.body.textContent ?? '').not.toMatch(REAL);
  });

  it('blurs images, canvases, iframes and every text-bearing element', () => {
    redact();
    const blurRule = Array.from(document.head.querySelectorAll('style')).map((s) => s.textContent).join('');
    expect(blurRule).toMatch(/img, canvas, video, picture, iframe \{ filter: blur\(8px\) !important \}/);
    expect((document.querySelector('h1') as HTMLElement).style.filter).toBe('blur(3.5px)');
    expect((document.getElementById('name') as HTMLElement).style.filter).toBe('blur(3.5px)');
  });

  it('reports stylesheet rules that draw text with attr() or counter(), nested ones included', () => {
    // jsdom's CSS parser drops attr() and counter() values from content, which a real browser keeps,
    // so the rules the fixture's style element declares are handed over as the objects a browser gives.
    const rule = (selectorText: string, content: string) => ({ selectorText, style: { content } });
    const sheets = [
      {
        cssRules: [
          rule('.field::before', 'attr(data-placeholder)'),
          rule('.plain::before', '"*"'),
          { cssRules: [rule('.step::after', 'counter(step)')] },
        ],
      },
      {
        get cssRules(): never {
          throw new Error('cross-origin sheet');
        },
      },
    ];
    vi.spyOn(document, 'styleSheets', 'get').mockReturnValue(sheets as unknown as StyleSheetList);
    const { cssGenerated } = redact();
    expect(cssGenerated).toEqual(['.field::before => attr(data-placeholder)', '.step::after => counter(step)']);
  });

  it('holds when the app re-renders real text after the redaction', () => {
    // A framework keeps a reference to its original nodes and rewrites them on a timer.
    const app = document.getElementById('app') as HTMLElement;
    const title = document.querySelector('h1') as HTMLElement;
    setInterval(() => {
      title.textContent = 'Real Customer Name 99';
      app.appendChild(document.createTextNode('Another Real Value 123'));
    }, 50);

    const before = document.body;
    const result = redact();
    expect(document.body).not.toBe(before);
    expect(result.count).toBe(0);

    vi.advanceTimersByTime(500);

    // The original (now detached) body took the writes, the live document did not.
    expect(title.textContent).toBe('Real Customer Name 99');
    expect(document.body.textContent ?? '').not.toMatch(REAL);
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) expect(walker.currentNode.nodeValue ?? '').not.toMatch(REAL);
  });

  it('is stable when run twice, the filler never counts as a leak', () => {
    redact();
    expect(redact().count).toBe(0);
  });
});
