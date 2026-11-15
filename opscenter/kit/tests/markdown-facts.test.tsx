/* Markdown reader (safe by default) and the Facts parts (FactRow, FactList, Disclosure). */
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axe from 'axe-core';
import { describe, expect, it, vi } from 'vitest';
import { Disclosure, FactList, FactRow, Markdown, classifyLink } from '../src';

async function noAxe(el: Element) {
  const r = await axe.run(el, { rules: { region: { enabled: false }, 'color-contrast': { enabled: false } } });
  expect(r.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(' ')}`)).toEqual([]);
}

describe('Markdown safety', () => {
  it('shows raw html as text and never creates an element from it', () => {
    const { container } = render(<Markdown body={'<img src=x onerror="alert(1)"> and <script>alert(1)</script> and <b>bold</b>'} />);
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('b')).toBeNull();
    expect(container.textContent).toContain('<script>alert(1)</script>');
    expect(container.textContent).toContain('<b>bold</b>');
  });

  it('renders no image from image syntax', () => {
    const { container } = render(<Markdown body="![x](https://example.com/a.png)" />);
    expect(container.querySelector('img')).toBeNull();
  });

  it.each([
    'javascript:alert(1)',
    'JaVaScRiPt:alert(1)',
    'java\tscript:alert(1)',
    'data:text/html;base64,AAAA',
    'vbscript:msgbox(1)',
    'file:///etc/passwd',
    '//evil.example/x',
  ])('renders %j as its label with no href and no button', (target) => {
    const onLink = vi.fn();
    const { container } = render(<Markdown body={`[label](${target})`} onLink={onLink} />);
    expect(container.querySelector('a')).toBeNull();
    expect(container.querySelector('button')).toBeNull();
    expect(container.querySelector('[href]')).toBeNull();
    expect(container.textContent).toContain('label');
    expect(onLink).not.toHaveBeenCalled();
  });

  it('keeps one level of parentheses inside a link target, so no bracket leaks into the text', () => {
    const { container } = render(<Markdown body="A [script link](javascript:alert(1)) and [page](https://example.com/a_(b)) end." />);
    expect(container.textContent).toBe('A script link and page end.');
    expect(screen.getByRole('link', { name: 'page' }).getAttribute('href')).toBe('https://example.com/a_(b)');
    expect(container.querySelectorAll('[href]').length).toBe(1);
  });

  it('opens external links in a new tab with noopener noreferrer', () => {
    render(<Markdown body="[site](https://example.com/a) and https://example.org/b and [mail](mailto:a@example.com)" />);
    const site = screen.getByRole('link', { name: 'site' });
    expect(site.getAttribute('href')).toBe('https://example.com/a');
    expect(site.getAttribute('target')).toBe('_blank');
    expect(site.getAttribute('rel')).toBe('noopener noreferrer');
    expect(screen.getByRole('link', { name: 'https://example.org/b' }).getAttribute('href')).toBe('https://example.org/b');
    expect(screen.getByRole('link', { name: 'mail' }).getAttribute('href')).toBe('mailto:a@example.com');
  });

  it('sends a relative link to onLink without the fragment, and as text without a handler', () => {
    const onLink = vi.fn();
    const { unmount } = render(<Markdown body="[next](docs/next.md#part)" onLink={onLink} />);
    fireEvent.click(screen.getByRole('button', { name: 'next' }));
    expect(onLink).toHaveBeenCalledWith('docs/next.md');
    unmount();
    const { container } = render(<Markdown body="[next](docs/next.md)" />);
    expect(container.querySelector('a, button')).toBeNull();
  });

  it('classifyLink sorts targets', () => {
    expect(classifyLink('https://example.com').kind).toBe('external');
    expect(classifyLink('docs/a.md').kind).toBe('relative');
    expect(classifyLink('#top').kind).toBe('relative');
    expect(classifyLink('javascript:x').kind).toBe('blocked');
    expect(classifyLink('').kind).toBe('blocked');
    expect(classifyLink('\\\\host\\share').kind).toBe('blocked');
  });

  it('keeps code content literal', () => {
    const { container } = render(<Markdown body={'`<b>x</b>`\n\n```\n<script>1</script>\n```'} />);
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelectorAll('code').length).toBe(2);
  });

  it('copes with non-string and empty input', () => {
    const { container } = render(<Markdown body={undefined as unknown as string} />);
    expect(container.querySelector('.md')).toBeTruthy();
  });
});

describe('Markdown blocks', () => {
  const body = ['# Title', 'Text with **bold** and *it*.', '- [x] done', '- [ ] open', '1. one', '> quote', '| A | B |', '| --- | --- |', '| 1 | 2 |', '---', '```', 'code', '```'].join('\n');

  it('offsets headings so the page keeps its h1, and honours headingOffset', () => {
    const { unmount } = render(<Markdown body="# Title" />);
    expect(screen.getByRole('heading', { level: 2, name: 'Title' })).toBeTruthy();
    unmount();
    render(<Markdown body="# Title" headingOffset={0} />);
    expect(screen.getByRole('heading', { level: 1, name: 'Title' })).toBeTruthy();
  });

  it('renders lists, task boxes, a table, a quote, a rule and a focusable code block', async () => {
    const { container } = render(<Markdown body={body} />);
    expect(screen.getByRole('img', { name: 'Done' })).toBeTruthy();
    expect(screen.getByRole('img', { name: 'Open' })).toBeTruthy();
    expect(screen.getByRole('table')).toBeTruthy();
    expect(screen.getByRole('columnheader', { name: 'A' })).toBeTruthy();
    expect(container.querySelector('blockquote')).toBeTruthy();
    expect(container.querySelector('hr')).toBeTruthy();
    expect(container.querySelector('ol')).toBeTruthy();
    expect(container.querySelector('strong')?.textContent).toBe('bold');
    expect(container.querySelector('em')?.textContent).toBe('it');
    expect(container.querySelector('pre')?.getAttribute('tabindex')).toBe('0');
    expect(screen.getByRole('region', { name: 'Table' }).getAttribute('tabindex')).toBe('0');
    await noAxe(container);
  });
});

describe('FactRow and FactList', () => {
  it('is a description list that pairs each label with its value', async () => {
    const { container } = render(
      <FactList label="Facts">
        <FactRow label="Name" value="Alpha" />
        <FactRow label="Id" mono>
          <span>abc</span>
        </FactRow>
      </FactList>,
    );
    const list = screen.getByLabelText('Facts');
    expect(list.tagName).toBe('DL');
    expect(container.querySelectorAll('dt').length).toBe(2);
    expect(container.querySelectorAll('dd').length).toBe(2);
    expect(container.querySelectorAll('dd')[1]?.hasAttribute('data-mono')).toBe(true);
    await noAxe(container);
  });

  it('shows a dash announced as None for an empty value, but not for zero', () => {
    const { container } = render(
      <FactList>
        <FactRow label="Owner" value={null} />
        <FactRow label="Count" value={0} />
      </FactList>,
    );
    const [owner, count] = Array.from(container.querySelectorAll('dd'));
    expect(owner?.hasAttribute('data-empty')).toBe(true);
    expect(owner?.textContent).toContain('None');
    expect(count?.hasAttribute('data-empty')).toBe(false);
    expect(count?.textContent).toBe('0');
  });

  it('works on its own, with a hint and a fixed label width', async () => {
    const { container } = render(<FactRow label="Path" value="/a/b" hint="Full path" labelWidth={96} />);
    expect(container.querySelector('dl')).toBeTruthy();
    const row = container.querySelector('.fact-row') as HTMLElement;
    expect(row.getAttribute('title')).toBe('Full path');
    expect(row.style.getPropertyValue('--fact-label-width')).toBe('96px');
    await noAxe(container);
  });

  it('sets the row gap from the gap prop', () => {
    const { container } = render(<FactList gap={12} />);
    expect((container.querySelector('dl') as HTMLElement).style.getPropertyValue('--fact-gap')).toBe('12px');
  });
});

describe('Disclosure', () => {
  it('toggles from the keyboard and keeps aria-expanded and the panel in step', async () => {
    const user = userEvent.setup();
    const { container } = render(
      <Disclosure label="More" count={3}>
        <p>Hidden detail</p>
      </Disclosure>,
    );
    const button = screen.getByRole('button', { name: /More/ });
    const panel = container.querySelector('.disclosure-panel') as HTMLElement;
    expect(button.getAttribute('aria-expanded')).toBe('false');
    expect(panel.hidden).toBe(true);
    expect(button.getAttribute('aria-controls')).toBe(panel.id);
    button.focus();
    await user.keyboard('{Enter}');
    expect(button.getAttribute('aria-expanded')).toBe('true');
    expect(panel.hidden).toBe(false);
    await user.keyboard(' ');
    expect(button.getAttribute('aria-expanded')).toBe('false');
    await noAxe(container);
  });

  it('starts open with defaultOpen and can be controlled', async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    const { rerender } = render(<Disclosure label="Controlled" open={false} onOpenChange={onOpenChange} />);
    const button = screen.getByRole('button', { name: 'Controlled' });
    await user.click(button);
    expect(onOpenChange).toHaveBeenCalledWith(true);
    expect(button.getAttribute('aria-expanded')).toBe('false');
    rerender(<Disclosure label="Controlled" open onOpenChange={onOpenChange} />);
    expect(button.getAttribute('aria-expanded')).toBe('true');
    const { unmount } = render(<Disclosure label="Default" defaultOpen />);
    expect(screen.getByRole('button', { name: 'Default' }).getAttribute('aria-expanded')).toBe('true');
    unmount();
  });
});

describe('Disclosure lazy', () => {
  it('mounts the children after the first open and unmounts them on close', async () => {
    const user = userEvent.setup();
    const mounted = vi.fn();
    function Probe() {
      mounted();
      return <p>Heavy detail</p>;
    }
    const { container } = render(
      <Disclosure label="Lazy" lazy>
        <Probe />
      </Disclosure>,
    );
    const button = screen.getByRole('button', { name: 'Lazy' });
    const panel = container.querySelector('.disclosure-panel') as HTMLElement;
    expect(mounted).not.toHaveBeenCalled();
    expect(screen.queryByText('Heavy detail')).toBeNull();
    expect(panel.hidden).toBe(true);
    expect(document.getElementById(button.getAttribute('aria-controls') as string)).toBe(panel);
    await user.click(button);
    expect(screen.getByText('Heavy detail')).toBeTruthy();
    expect(panel.hidden).toBe(false);
    await user.click(button);
    expect(screen.queryByText('Heavy detail')).toBeNull();
    expect(panel.hidden).toBe(true);
    await user.click(button);
    expect(mounted).toHaveBeenCalledTimes(2);
    await noAxe(container);
  });

  it('mounts at once with defaultOpen and follows a controlled open', () => {
    const { rerender } = render(
      <Disclosure label="Lazy" lazy defaultOpen>
        <p>Now</p>
      </Disclosure>,
    );
    expect(screen.getByText('Now')).toBeTruthy();
    rerender(
      <Disclosure label="Lazy" lazy open={false}>
        <p>Now</p>
      </Disclosure>,
    );
    expect(screen.queryByText('Now')).toBeNull();
  });

  it('keeps the children in the document while closed when not lazy', () => {
    render(
      <Disclosure label="Eager">
        <p>Kept</p>
      </Disclosure>,
    );
    expect(screen.getByText('Kept')).toBeTruthy();
  });
});

describe('Facts tones and layout hook', () => {
  it.each(['primary', 'secondary', 'tertiary', 'success', 'warning', 'urgent', 'danger', 'info'] as const)('sets data-tone %s on the value', (tone) => {
    const { container } = render(<FactRow label="State" value="Value" tone={tone} />);
    expect(container.querySelector('.fact-value')?.getAttribute('data-tone')).toBe(tone);
  });

  it('keeps the value text a word, so a warning tone is never the only signal', async () => {
    const { container } = render(<FactRow label="Disk" value="Almost full" tone="warning" />);
    expect(container.textContent).toContain('Almost full');
    await noAxe(container);
  });

  it('merges a style passthrough over the row, list and disclosure custom properties', () => {
    const { container } = render(
      <div>
        <FactList gap={4} style={{ ['--fact-gap' as string]: '20px', marginTop: 8 }}>
          <FactRow label="A" value="1" labelWidth={90} style={{ ['--fact-label-width' as string]: '120px', paddingTop: 2 }} />
        </FactList>
        <Disclosure label="D" style={{ ['--disclosure-gap' as string]: '14px' }} />
      </div>,
    );
    const list = container.querySelector('dl') as HTMLElement;
    expect(list.style.getPropertyValue('--fact-gap')).toBe('20px');
    expect(list.style.marginTop).toBe('8px');
    const row = container.querySelector('.fact-row') as HTMLElement;
    expect(row.style.getPropertyValue('--fact-label-width')).toBe('120px');
    expect(row.style.paddingTop).toBe('2px');
    expect((container.querySelector('.disclosure-wrap') as HTMLElement).style.getPropertyValue('--disclosure-gap')).toBe('14px');
  });

  it('adds no style attribute by default', () => {
    const { container } = render(<FactList><FactRow label="A" value="1" /></FactList>);
    expect(container.querySelector('dl')?.getAttribute('style')).toBeNull();
    expect(container.querySelector('.fact-row')?.getAttribute('style')).toBeNull();
  });
});
