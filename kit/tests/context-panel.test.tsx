/* ContextPanel and AppShell contextPanel: the second navigation level beside the rail. */
import { fireEvent, render, screen } from '@testing-library/react';
import axe from 'axe-core';
import { beforeEach, describe, expect, it } from 'vitest';
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
