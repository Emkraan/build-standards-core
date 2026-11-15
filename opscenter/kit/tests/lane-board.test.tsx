/* LaneBoard: keyboard moves with announcements, pointer drop, empty lane, axe. */
import { fireEvent, render, screen } from '@testing-library/react';
import axe from 'axe-core';
import { describe, expect, it, vi } from 'vitest';
import { LaneBoard } from '../src';

const lanes = () => [
  { id: 'a', label: 'To do', cards: [{ id: '1', label: 'One' }, { id: '2', label: 'Two' }] },
  { id: 'b', label: 'Doing', cards: [] },
];

describe('LaneBoard', () => {
  it('shows the empty state and counts', () => {
    render(<LaneBoard lanes={lanes()} onMove={() => {}} emptyText="Nothing here" />);
    expect(screen.getByText('Nothing here')).toBeTruthy();
    expect(screen.getByRole('region', { name: 'To do, 2 cards' })).toBeTruthy();
  });

  it('moves by keyboard and announces', () => {
    const onMove = vi.fn();
    render(<LaneBoard lanes={lanes()} onMove={onMove} />);
    const card = screen.getByText('One');
    card.focus();
    fireEvent.keyDown(card, { key: ' ' });
    expect(screen.getByRole('status').textContent).toContain('Picked up One');
    fireEvent.keyDown(card, { key: 'ArrowRight' });
    expect(screen.getByRole('status').textContent).toContain('Doing');
    fireEvent.keyDown(card, { key: 'Enter' });
    expect(onMove).toHaveBeenCalledWith({ cardId: '1', from: 'a', to: 'b', index: 0 });
  });

  it('escape cancels and reorders inside a lane', () => {
    const onMove = vi.fn();
    render(<LaneBoard lanes={lanes()} onMove={onMove} />);
    const card = screen.getByText('One');
    fireEvent.keyDown(card, { key: 'Enter' });
    fireEvent.keyDown(card, { key: 'Escape' });
    expect(onMove).not.toHaveBeenCalled();
    fireEvent.keyDown(card, { key: 'Enter' });
    fireEvent.keyDown(card, { key: 'ArrowDown' });
    fireEvent.keyDown(card, { key: 'Enter' });
    expect(onMove).toHaveBeenCalledWith({ cardId: '1', from: 'a', to: 'a', index: 1 });
  });

  it('drops with the pointer', () => {
    const onMove = vi.fn();
    render(<LaneBoard lanes={lanes()} onMove={onMove} />);
    const dt = { getData: () => '2', setData: () => {}, effectAllowed: '' };
    fireEvent.dragStart(screen.getByText('Two'), { dataTransfer: dt });
    const lane = screen.getByRole('region', { name: 'Doing, 0 cards' });
    fireEvent.dragOver(lane, { dataTransfer: dt });
    expect(lane.hasAttribute('data-over')).toBe(true);
    fireEvent.drop(lane, { dataTransfer: dt });
    expect(onMove).toHaveBeenCalledWith({ cardId: '2', from: 'a', to: 'b', index: 0 });
  });

  it('has no axe violations', async () => {
    const { container } = render(<LaneBoard lanes={lanes()} onMove={() => {}} />);
    const r = await axe.run(container);
    expect(r.violations).toEqual([]);
  });
});
