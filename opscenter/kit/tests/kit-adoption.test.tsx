/* The kit pieces consumers hit when they adopt the UI whole: inline Alert, compact Select, a
   keyboard-operable clickable Card, the --text-on-accent token and the body font in the base layer. */
import { fireEvent, render, screen } from '@testing-library/react';
import axe from 'axe-core';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import { Alert, Card, Select } from '../src';

const css = (p: string) => readFileSync(resolve(__dirname, p), 'utf8');

describe('Alert', () => {
  it('announces warnings and errors, and is polite for info and success', () => {
    const { rerender } = render(<Alert tone="danger" title="Save failed">Try again.</Alert>);
    expect(screen.getByRole('alert').textContent).toContain('Save failed');
    rerender(<Alert tone="warning">Heads up</Alert>);
    expect(screen.getByRole('alert').getAttribute('data-tone')).toBe('warning');
    rerender(<Alert tone="success">Saved</Alert>);
    expect(screen.getByRole('status').getAttribute('data-tone')).toBe('success');
    rerender(<Alert>Plain</Alert>);
    expect(screen.getByRole('status').getAttribute('data-tone')).toBe('info');
  });

  it('renders an action and has no axe violations', async () => {
    const { container } = render(<Alert tone="info" title="Update" action={<button type="button">Review</button>}>New release.</Alert>);
    expect(screen.getByRole('button', { name: 'Review' })).toBeTruthy();
    const res = await axe.run(container, { rules: { 'color-contrast': { enabled: false } } });
    expect(res.violations).toEqual([]);
  });
});

describe('Select size', () => {
  it('marks the compact size and keeps the native control otherwise', () => {
    render(<Select aria-label="Filter" size="sm" options={[{ value: 'a', label: 'A' }]} />);
    const el = screen.getByLabelText('Filter');
    expect(el.getAttribute('data-size')).toBe('sm');
    expect(el.hasAttribute('size')).toBe(false);
  });
  it('has no size attribute by default', () => {
    render(<Select aria-label="Plain" options={[{ value: 'a', label: 'A' }]} />);
    expect(screen.getByLabelText('Plain').hasAttribute('data-size')).toBe(false);
  });
});

describe('clickable Card', () => {
  it('is a focusable button that Enter and Space activate', () => {
    const onClick = vi.fn();
    render(<Card interactive onClick={onClick}>Open</Card>);
    const card = screen.getByRole('button', { name: 'Open' });
    expect(card.getAttribute('tabindex')).toBe('0');
    fireEvent.keyDown(card, { key: 'Enter' });
    fireEvent.keyDown(card, { key: ' ' });
    fireEvent.click(card);
    expect(onClick).toHaveBeenCalledTimes(3);
  });
  it('stays plain without an onClick, and ignores keys from a control inside', () => {
    const onClick = vi.fn();
    const { rerender } = render(<Card interactive>Static</Card>);
    expect(screen.queryByRole('button')).toBeNull();
    rerender(<Card interactive onClick={onClick}><input aria-label="inner" /></Card>);
    fireEvent.keyDown(screen.getByLabelText('inner'), { key: ' ' });
    expect(onClick).not.toHaveBeenCalled();
  });
});

describe('base layer', () => {
  it('puts the app font on the body so portaled parts match', () => {
    expect(css('../src/styles/kit.css')).toMatch(/\nbody \{ font-family: var\(--font-sans\);/);
  });
  it('ships --text-on-accent as an alias of --text-inverse', () => {
    expect(css('../../tokens/tokens.css')).toMatch(/--text-on-accent:\s*var\(--text-inverse\)|--text-on-accent:\s*#ffffff/i);
  });
});
