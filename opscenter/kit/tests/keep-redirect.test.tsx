/* KeepRedirect and redirectTarget: a moved route keeps its query string and hash (layout standard rule 9). */
import { render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { KeepRedirect, redirectTarget } from '../src';

describe('redirectTarget', () => {
  it('carries the query string and hash over to the new path', () => {
    expect(redirectTarget('/ops/builds/web', { search: '?tab=runs&q=x', hash: '#row-4' })).toBe('/ops/builds/web?tab=runs&q=x#row-4');
  });

  it('adds nothing when the old location had neither', () => {
    expect(redirectTarget('/ops/builds/web')).toBe('/ops/builds/web');
    expect(redirectTarget('/ops/builds/web', { search: '', hash: '' })).toBe('/ops/builds/web');
    expect(redirectTarget('/ops/builds/web', { search: '?', hash: '#' })).toBe('/ops/builds/web');
  });

  it('lets what the target already has win, and merges the rest', () => {
    expect(redirectTarget('/new?tab=a#top', { search: '?tab=b&q=1', hash: '#old' })).toBe('/new?tab=a&q=1#top');
  });

  it('accepts a search and hash with or without their marks', () => {
    expect(redirectTarget('/n', { search: 'a=1', hash: 'x' })).toBe('/n?a=1#x');
  });

  it('refuses anything that is not a path on this site', () => {
    for (const bad of ['https://evil.example/x', '//evil.example/x', '/\\evil.example', 'javascript:alert(1)', 'relative/path', '', '/a\nb']) {
      expect(redirectTarget(bad, { search: '?a=1' })).toBeNull();
    }
  });
});

describe('KeepRedirect', () => {
  it('redirects once on mount with the location it is given, and renders nothing', () => {
    const onRedirect = vi.fn();
    const { container, rerender } = render(<KeepRedirect to="/ops/ci" location={{ search: '?run=7', hash: '#log' }} onRedirect={onRedirect} />);
    expect(container.firstChild).toBeNull();
    expect(onRedirect).toHaveBeenCalledWith('/ops/ci?run=7#log');
    rerender(<KeepRedirect to="/ops/ci" location={{ search: '?run=8' }} onRedirect={onRedirect} />);
    expect(onRedirect).toHaveBeenCalledTimes(1);
  });

  it('reads the browser location when none is given', () => {
    window.history.replaceState(null, '', '/old?x=1#h');
    const onRedirect = vi.fn();
    render(<KeepRedirect to="/new" onRedirect={onRedirect} />);
    expect(onRedirect).toHaveBeenCalledWith('/new?x=1#h');
    window.history.replaceState(null, '', '/');
  });

  it('does nothing for a target that is not a path on this site', () => {
    const onRedirect = vi.fn();
    render(<KeepRedirect to="https://evil.example" onRedirect={onRedirect} />);
    expect(onRedirect).not.toHaveBeenCalled();
  });
});
