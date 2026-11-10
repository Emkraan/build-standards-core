/* data-act: the check that a page action Button is tagged, and the stylesheet block that colours it. */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { buttons, scan } from '../scripts/check-action-buttons.mjs';

describe('check-action-buttons', () => {
  const src = (jsx: string) => scan('x.tsx', jsx);

  it('fails an untagged primary or secondary Button that starts with an action verb', () => {
    expect(src('<Button variant="primary">Add user</Button>')).toHaveLength(1);
    expect(src('<Button>Export CSV</Button>')).toHaveLength(1);
    expect(src('<button className="btn" data-variant="secondary">Open report</button>')).toHaveLength(1);
  });

  it('passes a tagged button, an opt-out, other variants, icon-only and non-action labels', () => {
    expect(src('<Button data-act="create" variant="primary">Add user</Button>')).toEqual([]);
    expect(src('<Button data-act="none">Edit</Button>')).toEqual([]);
    expect(src('<Button variant="ghost">Add user</Button>')).toEqual([]);
    expect(src('<Button variant="danger">Delete</Button>')).toEqual([]);
    expect(src('<Button icon={<X />} aria-label="Add" />')).toEqual([]);
    expect(src('<Button variant="primary">Save</Button>')).toEqual([]);
    expect(src('<ButtonGroup>Add</ButtonGroup>')).toEqual([]);
  });

  it('reads the last literal of a label expression and a nested tag', () => {
    expect(src(`<Button>{busy ? 'Working...' : 'Link account'}</Button>`)).toHaveLength(1);
    expect(src('<Button><span>Import</span> data</Button>')).toHaveLength(1);
    expect(buttons('line1\n<Button a={1}>Go</Button>')[0]?.[2]).toBe(2);
  });
});

describe('data-act stylesheet block', () => {
  const css = readFileSync(resolve(__dirname, '../src/styles/kit.css'), 'utf8');

  it('tints secondary actions by purpose and leaves forms and dialogs plain', () => {
    expect(css).toMatch(/\.btn\[data-variant="secondary"\]\[data-act\]:not\(form \.btn\[data-act\]\):not\(\[role="dialog"\] \.btn\[data-act\]\) \{[^}]*--act-hue: var\(--hue-teal\)/);
    expect(css).toMatch(/\[data-act="link"\][^{]*\{ --act-hue: var\(--hue-blue\)/);
    expect(css).toMatch(/\[data-act="transfer"\][^{]*\{ --act-hue: var\(--hue-violet\)/);
  });
});
