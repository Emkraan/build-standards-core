import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { FeedStrip, PALETTE_OPEN_EVENT, SearchTrigger, onPaletteOpen, openScopedPalette } from '../src/index';

describe('search routing (D-003)', () => {
  it('exports the event name, and onPaletteOpen hears every open request with its scope', () => {
    expect(PALETTE_OPEN_EVENT).toBe('kit:open-palette');
    const heard = vi.fn();
    const stop = onPaletteOpen(heard);
    render(<SearchTrigger />);
    fireEvent.click(screen.getByRole('button', { name: /Search/ }));
    openScopedPalette('docs');
    expect(heard).toHaveBeenNthCalledWith(1, {});
    expect(heard).toHaveBeenNthCalledWith(2, { scope: 'docs' });
    stop();
    openScopedPalette('docs');
    expect(heard).toHaveBeenCalledTimes(2);
  });

  it('without onSearch the trigger still dispatches the palette event (default unchanged)', () => {
    const heard = vi.fn();
    document.addEventListener(PALETTE_OPEN_EVENT, heard);
    render(<SearchTrigger />);
    fireEvent.click(screen.getByRole('button', { name: /Search/ }));
    expect(heard).toHaveBeenCalledTimes(1);
    document.removeEventListener(PALETTE_OPEN_EVENT, heard);
  });

  it('onSearch replaces the event, on the trigger and through the feed strip', () => {
    const heard = vi.fn();
    document.addEventListener(PALETTE_OPEN_EVENT, heard);
    const own = vi.fn();
    const { unmount } = render(<SearchTrigger onSearch={own} />);
    fireEvent.click(screen.getByRole('button', { name: /Search/ }));
    unmount();
    render(<FeedStrip health={{ status: 'ok', label: 'All systems normal' }} onSearch={own} />);
    fireEvent.click(screen.getByRole('button', { name: /Search/ }));
    expect(own).toHaveBeenCalledTimes(2);
    expect(heard).not.toHaveBeenCalled();
    document.removeEventListener(PALETTE_OPEN_EVENT, heard);
  });
});
