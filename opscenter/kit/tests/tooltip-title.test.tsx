/* The tooltip layer adopts a native title: one styled tooltip, no browser tooltip, and an icon-only
   control keeps its accessible name. */
import { act, fireEvent, render, screen } from '@testing-library/react';
import axe from 'axe-core';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TooltipLayer } from '../src';

describe('TooltipLayer adopts title', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('moves the title to data-tip on hover and shows it in the layer', () => {
    render(
      <>
        <TooltipLayer />
        <button type="button" title="Refresh the list">
          Refresh
        </button>
      </>,
    );
    const btn = screen.getByRole('button', { name: 'Refresh' });
    fireEvent.pointerOver(btn);
    expect(btn.hasAttribute('title')).toBe(false);
    expect(btn.getAttribute('data-tip')).toBe('Refresh the list');
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(document.querySelector('.tooltip')?.textContent).toContain('Refresh the list');
  });

  it('keeps an icon-only control named, by aria-label from the title', async () => {
    const { container } = render(
      <>
        <TooltipLayer />
        <button type="button" title="Delete row">
          <svg aria-hidden="true" width="12" height="12" />
        </button>
      </>,
    );
    const btn = container.querySelector('button') as HTMLElement;
    fireEvent.pointerOver(btn);
    expect(btn.getAttribute('aria-label')).toBe('Delete row');
    vi.useRealTimers();
    expect((await axe.run(container)).violations).toEqual([]);
  });

  it('does not overwrite an existing label or text name', () => {
    const { container } = render(
      <>
        <TooltipLayer />
        <button type="button" aria-label="Close" title="Close the dialog" />
        <button type="button" title="Hint">
          Save
        </button>
      </>,
    );
    const [a, b] = Array.from(container.querySelectorAll('button')) as HTMLElement[];
    fireEvent.pointerOver(a as HTMLElement);
    fireEvent.pointerOver(b as HTMLElement);
    expect(a?.getAttribute('aria-label')).toBe('Close');
    expect(b?.hasAttribute('aria-label')).toBe(false);
    expect(b?.getAttribute('data-tip')).toBe('Hint');
  });

  it('adopts on keyboard focus too', () => {
    render(
      <>
        <TooltipLayer />
        <button type="button" title="Open menu">
          Menu
        </button>
      </>,
    );
    const btn = screen.getByRole('button', { name: 'Menu' });
    fireEvent.focusIn(btn);
    expect(btn.getAttribute('data-tip')).toBe('Open menu');
  });

  it('leaves an element that already has data-tip alone and drops an empty title', () => {
    const { container } = render(
      <>
        <TooltipLayer />
        <span data-tip="Own tip" title="Native" tabIndex={0}>
          a
        </span>
        <span title="" tabIndex={0}>
          b
        </span>
      </>,
    );
    const [a, b] = Array.from(container.querySelectorAll('span')) as HTMLElement[];
    fireEvent.pointerOver(a as HTMLElement);
    fireEvent.pointerOver(b as HTMLElement);
    expect(a?.getAttribute('data-tip')).toBe('Own tip');
    expect(b?.hasAttribute('data-tip')).toBe(false);
    expect(b?.hasAttribute('title')).toBe(false);
  });
});
