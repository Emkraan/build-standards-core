/* ContextPanel and AppShell contextPanel: the second navigation level beside the rail. */
import { fireEvent, render, screen } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import axe from 'axe-core';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { AppShell, ContextPanel, NavGroup, NavItem, Rail } from '../src';
import { installMatchMedia, resetMedia } from './helpers';

beforeEach(() => {
  resetMedia();
  installMatchMedia();
});

const panel = (
  <ContextPanel title="Timeline" subtitle="Q4 plan" footer={<span>Synced</span>}>
    <NavGroup label="Views">
      <NavItem href="/timeline/projects" label="Projects" active />
      <NavItem href="/timeline/gantt" label="Gantt" />
    </NavGroup>
  </ContextPanel>
);

const rail = (
  <Rail brandMark="K" brandName="Kit">
    <NavGroup label="Tools">
      <NavItem href="/timeline" label="Timeline" active />
    </NavGroup>
  </Rail>
);

describe('AppShell contextPanel', () => {
  it('renders exactly as before without the prop', () => {
    const { container } = render(<AppShell rail={rail}>page</AppShell>);
    expect(container.querySelector('.shell-split')).toBeNull();
    expect(container.querySelector('.context-panel')).toBeNull();
    expect(container.querySelector('.shell > .shell-main')).not.toBeNull();
  });

  it('lays the panel out next to the page inside the shell', () => {
    const { container } = render(
      <AppShell rail={rail} contextPanel={panel}>
        page
      </AppShell>,
    );
    const split = container.querySelector('.shell > .shell-split') as HTMLElement;
    expect(split.children[0]?.classList.contains('context-panel')).toBe(true);
    expect(split.children[1]?.classList.contains('shell-main')).toBe(true);
    expect(split.querySelector('main')?.textContent).toBe('page');
  });
});

describe('ContextPanel', () => {
  it('names the panel and its navigation, and marks the active item', async () => {
    const { container } = render(
      <AppShell rail={rail} contextPanel={panel}>
        page
      </AppShell>,
    );
    expect(screen.getByRole('complementary', { name: 'Timeline' })).toBeTruthy();
    expect(screen.getByRole('navigation', { name: 'Timeline sections' })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Projects' }).getAttribute('aria-current')).toBe('page');
    expect(screen.getByRole('link', { name: 'Gantt' }).getAttribute('aria-current')).toBeNull();
    expect(screen.getByText('Synced')).toBeTruthy();
    const r = await axe.run(container, { rules: { 'color-contrast': { enabled: false } } });
    expect(r.violations.map((v) => v.id)).toEqual([]);
  });

  it('takes its own nav label and fold label', () => {
    render(
      <ContextPanel title="Admin" navLabel="Admin pages" toggleLabel="Pages">
        <NavItem href="/admin" label="Access" />
      </ContextPanel>,
    );
    expect(screen.getByRole('navigation', { name: 'Admin pages' })).toBeTruthy();
    expect(screen.getByRole('button', { name: /Pages/ })).toBeTruthy();
  });

  it('folds with the button, starting closed unless defaultOpen', () => {
    const { rerender } = render(panel);
    const btn = screen.getByRole('button', { name: /Sections/ });
    const aside = screen.getByRole('complementary');
    expect(btn.getAttribute('aria-expanded')).toBe('false');
    expect(aside.hasAttribute('data-open')).toBe(false);
    fireEvent.click(btn);
    expect(btn.getAttribute('aria-expanded')).toBe('true');
    expect(aside.hasAttribute('data-open')).toBe(true);
    expect(document.getElementById(btn.getAttribute('aria-controls') as string)).not.toBeNull();
    rerender(<ContextPanel title="Open" defaultOpen />);
    expect(screen.getAllByRole('complementary').some((a) => a.hasAttribute('data-open'))).toBe(true);
  });

  it('works outside a shell with plain links', () => {
    render(
      <ContextPanel title="Solo">
        <NavItem href="/a" label="A" />
      </ContextPanel>,
    );
    expect(screen.getByRole('link', { name: 'A' }).getAttribute('href')).toBe('/a');
  });
});

describe('ContextPanel glider and layout', () => {
  const sizes = ['offsetWidth', 'offsetHeight', 'offsetLeft', 'offsetTop'] as const;
  const saved = sizes.map((k) => [k, Object.getOwnPropertyDescriptor(HTMLElement.prototype, k)] as const);
  afterEach(() => {
    for (const [k, d] of saved) {
      if (d) Object.defineProperty(HTMLElement.prototype, k, d);
      else delete (HTMLElement.prototype as unknown as Record<string, unknown>)[k];
    }
  });

  it('places the glider again when the folded list opens, not while it is hidden', () => {
    // A hidden list has no layout: every offset reads 0 until the panel is open.
    for (const k of sizes) {
      Object.defineProperty(HTMLElement.prototype, k, {
        configurable: true,
        get(this: HTMLElement) {
          return this.closest('.context-panel')?.hasAttribute('data-open') ? 120 : 0;
        },
      });
    }
    const { container } = render(panel);
    const glider = container.querySelector('.context-panel .nav-glider') as HTMLElement;
    expect(glider.style.width).toBe('0px');
    fireEvent.click(screen.getByRole('button', { name: 'Sections' }));
    expect(glider.style.width).toBe('120px');
    expect(glider.style.height).toBe('120px');
  });

  it('lets the page column shrink beside the panel', () => {
    const css = readFileSync(resolve(__dirname, '../src/styles/kit.css'), 'utf8');
    expect(css).toMatch(/\.shell-main \{[^}]*min-width: 0/);
    expect(css).toMatch(/\.shell-split > \.shell-main \{[^}]*min-width: 0/);
  });
});
