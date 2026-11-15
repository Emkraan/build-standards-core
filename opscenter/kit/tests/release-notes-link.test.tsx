import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { BuildCard, ReleaseNotesDialog, safeReleaseLink } from '../src/index';

const dateless = [{ version: '2.1.0', title: 'Bug fixes', items: [{ type: 'fixed' as const, title: 'Bug fixes' }] }];

describe('release notes link and optional date (web-ui 22)', () => {
  it('renders a dateless release without a dangling separator', () => {
    render(<ReleaseNotesDialog open onClose={() => {}} releases={dateless} version="2.1.0" />);
    const group = screen.getByRole('region', { name: 'Version 2.1.0' });
    expect(group.textContent).toContain('v2.1.0');
    expect(group.textContent).not.toContain('|');
  });

  it('shows the full changelog link in the foot, opening in a new tab', () => {
    render(<ReleaseNotesDialog open onClose={() => {}} releases={dateless} link={{ href: 'https://docs.example.com/changelog', label: 'Full changelog' }} />);
    const a = screen.getByRole('link', { name: 'Full changelog' });
    expect(a.getAttribute('href')).toBe('https://docs.example.com/changelog');
    expect(a.getAttribute('target')).toBe('_blank');
    expect(a.getAttribute('rel')).toBe('noopener noreferrer');
  });

  it('drops a link that is not http or https', () => {
    render(<ReleaseNotesDialog open onClose={() => {}} releases={dateless} link={{ href: 'javascript:alert(1)', label: 'Full changelog' }} />);
    expect(screen.queryByRole('link', { name: 'Full changelog' })).toBeNull();
    expect(safeReleaseLink({ href: '/relative', label: 'x' })).toBeUndefined();
    expect(safeReleaseLink({ href: 'https://a.example/p', label: '  ' })).toBeUndefined();
    expect(safeReleaseLink({ href: 'http://a.example/p', label: 'Go' })).toEqual({ href: 'http://a.example/p', label: 'Go' });
  });

  it('passes the link through from the build card', () => {
    render(<BuildCard version="2.1.0" releases={dateless} link={{ href: 'https://docs.example.com/c', label: 'Full changelog' }} />);
    fireEvent.click(screen.getByRole('button', { name: /Version 2\.1\.0/ }));
    expect(screen.getByRole('link', { name: 'Full changelog' })).toBeTruthy();
  });

  it('renders a link per release, for a dialog that lists several tools', () => {
    const two = [
      { version: '1.4.0', title: 'Tool A', items: ['New features'], link: { href: 'https://docs.example.com/a', label: 'Tool A changelog' } },
      { version: '1.4.0', title: 'Tool B', items: ['Bug fixes'], link: { href: 'javascript:alert(1)', label: 'Tool B changelog' } },
    ];
    render(<ReleaseNotesDialog open onClose={() => {}} releases={two} />);
    expect(screen.getByRole('link', { name: 'Tool A changelog' }).getAttribute('href')).toBe('https://docs.example.com/a');
    expect(screen.queryByRole('link', { name: 'Tool B changelog' })).toBeNull();
    expect(screen.getAllByRole('region', { name: 'Version 1.4.0' })).toHaveLength(2);
  });

  it('shows New again only when the seen key changes', () => {
    window.localStorage.clear();
    const first = render(<BuildCard version="2.1.0" releases={dateless} seenKey="a" />);
    expect(screen.getByRole('button', { name: /new release notes/ })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /Version 2\.1\.0/ }));
    first.unmount();
    const again = render(<BuildCard version="2.1.0" releases={dateless} seenKey="a" />);
    expect(screen.queryByRole('button', { name: /new release notes/ })).toBeNull();
    again.unmount();
    render(<BuildCard version="2.1.0" releases={dateless} seenKey="b" />);
    expect(screen.getByRole('button', { name: /new release notes/ })).toBeTruthy();
  });
});
