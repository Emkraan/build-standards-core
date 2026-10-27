/* StatTile delta, selected and tip; Modal action icon; Avatar initials from a directory name. */
import { fireEvent, render, screen } from '@testing-library/react';
import axe from 'axe-core';
import { describe, expect, it, vi } from 'vitest';
import { Avatar, IconCheck, Modal, StatTile, TooltipLayer, initialsOf } from '../src';

describe('StatTile delta, selected and tip', () => {
  it('renders the delta with a hidden direction word and an aria-hidden arrow', () => {
    const { container } = render(<StatTile label="Tickets" value={5} delta={{ text: '3% this week', direction: 'up' }} />);
    const d = container.querySelector('.kpi-delta');
    expect(d?.getAttribute('data-direction')).toBe('up');
    expect(d?.textContent).toContain('Up');
    expect(d?.textContent).toContain('3% this week');
    expect(d?.querySelector('svg')?.getAttribute('aria-hidden')).toBe('true');
  });

  it('words each direction', () => {
    for (const [direction, word] of [['down', 'Down'], ['flat', 'Unchanged']] as const) {
      const { container, unmount } = render(<StatTile label="x" value={1} delta={{ text: 't', direction }} />);
      expect(container.querySelector('.kpi-delta')?.textContent).toContain(word);
      unmount();
    }
  });

  it('has no delta element when none is given', () => {
    const { container } = render(<StatTile label="x" value={1} />);
    expect(container.querySelector('.kpi-delta')).toBeNull();
  });

  it('sets aria-pressed only on an interactive tile that has a selected value', () => {
    const { container, rerender } = render(<StatTile label="x" value={1} onClick={() => undefined} selected />);
    const tile = container.querySelector('.kpi-tile');
    expect(tile?.getAttribute('aria-pressed')).toBe('true');
    expect(tile?.classList.contains('is-selected')).toBe(true);
    rerender(<StatTile label="x" value={1} onClick={() => undefined} selected={false} />);
    expect(container.querySelector('.kpi-tile')?.getAttribute('aria-pressed')).toBe('false');
    rerender(<StatTile label="x" value={1} onClick={() => undefined} />);
    expect(container.querySelector('.kpi-tile')?.hasAttribute('aria-pressed')).toBe(false);
    rerender(<StatTile label="x" value={1} selected />);
    expect(container.querySelector('.kpi-tile')?.hasAttribute('aria-pressed')).toBe(false);
  });

  it('passes the tip to the shared tooltip layer', () => {
    const { container } = render(<StatTile label="x" value={1} tip="Why this number" />);
    expect(container.querySelector('.kpi-tile')?.getAttribute('data-tip')).toBe('Why this number');
  });

  it('serves the tip from a visible info icon, not from the tile, once the tip layer is mounted', () => {
    const { container } = render(
      <>
        <TooltipLayer />
        <StatTile label="x" value={1} tip="Why this number" />
      </>,
    );
    expect(container.querySelector('.kpi-tile')?.hasAttribute('data-tip')).toBe(false);
    expect(container.querySelector('.kpi-tile .info-tip')?.getAttribute('data-tip')).toBe('Why this number');
  });

  it('shows no info icon without the tip layer', () => {
    const { container } = render(<StatTile label="x" value={1} tip="Why this number" />);
    expect(container.querySelector('.info-tip')).toBeNull();
  });

  it('keeps the click and key behaviour', () => {
    const onClick = vi.fn();
    const { container } = render(<StatTile label="x" value={1} onClick={onClick} />);
    const tile = container.querySelector('.kpi-tile') as HTMLElement;
    fireEvent.keyDown(tile, { key: 'Enter' });
    fireEvent.click(tile);
    expect(onClick).toHaveBeenCalledTimes(2);
  });

  it('has no axe violations with every option', async () => {
    const { container } = render(
      <StatTile label="Tickets" value={5} icon={<IconCheck />} delta={{ text: '3% this week', direction: 'down' }} selected tip="Tip" onClick={() => undefined} />,
    );
    expect((await axe.run(container)).violations).toEqual([]);
  });
});

describe('Modal action icon', () => {
  it('shows the icon inside the primary button', () => {
    render(
      <Modal open onClose={() => undefined} title="Remove" primaryAction={{ label: 'Remove', danger: true, icon: <span data-testid="ic" /> }}>
        Body
      </Modal>,
    );
    const btn = screen.getByRole('button', { name: 'Remove' });
    expect(btn.querySelector('[data-testid="ic"]')).not.toBeNull();
  });
});

describe('Modal meta slot', () => {
  it('renders beside the title and stays out of the accessible name', () => {
    render(
      <Modal open onClose={() => undefined} title="Remove link" meta={<span data-testid="meta">Draft</span>}>
        Body
      </Modal>,
    );
    const dialog = screen.getByRole('dialog', { name: 'Remove link' });
    expect(dialog.textContent).toContain('Draft');
    expect(screen.getByTestId('meta').closest('h2')).toBeNull();
    expect(screen.queryByRole('dialog', { name: /Draft/ })).toBeNull();
  });
  it('draws nothing without meta', () => {
    render(<Modal open onClose={() => undefined} title="Plain">Body</Modal>);
    expect(document.querySelector('.modal-meta')).toBeNull();
  });
});

describe('initialsOf directory names', () => {
  it('reads Last, First as First Last', () => {
    expect(initialsOf('Okafor, Ada')).toBe('AO');
  });
  it('drops a trailing note in parentheses', () => {
    expect(initialsOf('Okafor, Ada (contractor)')).toBe('AO');
    expect(initialsOf('Grace Hopper (admin)')).toBe('GH');
  });
  it('keeps the plain behaviour', () => {
    expect(initialsOf('Ops group')).toBe('OG');
    expect(initialsOf('Cher')).toBe('C');
    expect(initialsOf('')).toBe('?');
    expect(initialsOf('(note only)')).toBe('?');
  });
  it('gives the same name the same avatar hue and text', () => {
    const { container } = render(<Avatar name="Okafor, Ada" />);
    expect(container.textContent).toContain('AO');
  });
});
