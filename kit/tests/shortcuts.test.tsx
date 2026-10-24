import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ShortcutLayer, useShortcut } from '../src/index';

function Registers({ onGo }: { onGo: () => void }) {
  useShortcut({ id: 'test.go', keys: 'g h', description: 'Go home', group: 'Navigation', handler: onGo });
  useShortcut({ id: 'test.new', keys: 'shift+n', description: 'New item', handler: onGo });
  return <input aria-label="Note" />;
}

describe('ShortcutLayer', () => {
  it('opens the help dialog on ? and lists registered shortcuts', () => {
    render(
      <ShortcutLayer>
        <Registers onGo={() => undefined} />
      </ShortcutLayer>,
    );
    fireEvent.keyDown(document.body, { key: '?', shiftKey: true });
    const dialog = screen.getByRole('dialog', { name: 'Keyboard shortcuts' });
    expect(within(dialog).getByText('Go home')).toBeTruthy();
    expect(within(dialog).getByText('New item')).toBeTruthy();
    expect(within(dialog).getByText('then')).toBeTruthy();
  });

  it('runs sequences and single combos, but not while typing', () => {
    const onGo = vi.fn();
    render(
      <ShortcutLayer>
        <Registers onGo={onGo} />
      </ShortcutLayer>,
    );
    fireEvent.keyDown(document.body, { key: 'g' });
    fireEvent.keyDown(document.body, { key: 'h' });
    expect(onGo).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(document.body, { key: 'N', shiftKey: true });
    expect(onGo).toHaveBeenCalledTimes(2);
    const input = screen.getByRole('textbox', { name: 'Note' });
    fireEvent.keyDown(input, { key: 'g' });
    fireEvent.keyDown(input, { key: 'h' });
    fireEvent.keyDown(input, { key: '?' });
    expect(onGo).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
