import { render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it } from 'vitest';
import accentData from '../src/theme/accents.json';
import { APP_ACCENTS, AnnouncementBanner, AppShell, ButtonLink, NavItem, Rail, Table } from '../src/index';

describe('critical banner', () => {
  it('has role=alert only when critical', () => {
    const { container, rerender } = render(<AnnouncementBanner id="a" tone="critical" title="Down" />);
    expect(container.querySelector('section')?.getAttribute('role')).toBe('alert');
    rerender(<AnnouncementBanner id="a" tone="warning" title="Soon" />);
    expect(container.querySelector('section')?.hasAttribute('role')).toBe(false);
  });
});

describe('numeric table header', () => {
  it('puts cell-num on the th', () => {
    render(<Table caption="t" rows={[{ id: 'a', n: 1 }]} rowKey={(r) => r.id} columns={[{ key: 'n', header: 'Count', numeric: true }]} />);
    expect(screen.getByRole('columnheader', { name: /Count/ }).className).toContain('cell-num');
  });
});

describe('rail', () => {
  const rail = (item: ReactNode) => (
    <AppShell pathname="/" rail={<Rail brandMark="K" brandName="App" brandSlot={<span>Switcher</span>}>{item}</Rail>} header={null}>
      x
    </AppShell>
  );
  it('mirrors a numeric badge on the icon, or shows a dot, or nothing', () => {
    const { container, rerender } = render(rail(<NavItem href="/a" label="A" badge={3} />));
    expect(container.querySelector('.nav-icon-count')?.textContent).toBe('3');
    rerender(rail(<NavItem href="/a" label="A" badge="New" iconBadge="dot" />));
    expect(container.querySelector('.nav-icon-count[data-dot]')).not.toBeNull();
    rerender(rail(<NavItem href="/a" label="A" badge={3} iconBadge={false} />));
    expect(container.querySelector('.nav-icon-count')).toBeNull();
  });
  it('renders the brand slot inside the brand row', () => {
    const { container } = render(rail(null));
    expect(container.querySelector('.sidebar-brand .sidebar-brand-slot')?.textContent).toBe('Switcher');
  });
});

describe('ButtonLink', () => {
  it('renders a safe href as an anchor with button classes', () => {
    render(<ButtonLink href="/x">Go</ButtonLink>);
    const a = screen.getByRole('link', { name: 'Go' });
    expect(a.getAttribute('href')).toBe('/x');
    expect(a.className).toContain('btn');
  });
  it('drops an unsafe href', () => {
    render(<ButtonLink href="javascript:alert(1)">Bad</ButtonLink>);
    expect(screen.getByText('Bad').hasAttribute('href')).toBe(false);
  });
});

describe('accent data', () => {
  it('matches APP_ACCENTS', () => {
    expect([...APP_ACCENTS]).toEqual(accentData.accents);
    expect(accentData.default).toBe('cobalt');
  });
});
