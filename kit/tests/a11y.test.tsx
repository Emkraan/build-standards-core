/* axe-core on the gallery, which renders every kit component, in both themes and with the
   overlays open. jsdom has no layout or paint, so axe cannot compute colour contrast there: the
   color-contrast rule is disabled here and contrast is certified on the tokens instead
   (tokens/build.py --check). Every other rule runs. */
import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axe from 'axe-core';
import { beforeAll, describe, expect, it } from 'vitest';
import { GalleryApp } from '../gallery/App';

const OPTIONS: axe.RunOptions = {
  rules: {
    // jsdom cannot compute rendered colours (see the note at the top of this file).
    'color-contrast': { enabled: false },
  },
  resultTypes: ['violations'],
};

async function violations(): Promise<string[]> {
  const result = await axe.run(document, OPTIONS);
  return result.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(' ')).join(', ')})`);
}

beforeAll(() => {
  document.title = 'Kit gallery';
  document.documentElement.lang = 'en';
});

describe.each(['light', 'dark'] as const)('axe in the %s theme', (theme) => {
  it('finds no violations on the composite and with each overlay open', async () => {
    const user = userEvent.setup();
    window.localStorage.setItem('gallery.theme', theme);
    render(<GalleryApp />);
    expect(document.documentElement.getAttribute('data-theme')).toBe(theme);
    expect(await violations()).toEqual([]);

    await user.click(screen.getByRole('button', { name: 'Open dialog' }));
    expect(screen.getByRole('dialog', { name: 'Edit device' })).toBeTruthy();
    expect(await violations()).toEqual([]);
    await user.keyboard('{Escape}');

    await user.click(screen.getByRole('button', { name: 'Delete schedule' }));
    expect(await screen.findByRole('alertdialog')).toBeTruthy();
    expect(await violations()).toEqual([]);
    await user.keyboard('{Escape}');

    fireEvent.keyDown(document, { key: 'k', ctrlKey: true });
    expect(screen.getByRole('dialog', { name: 'Search' })).toBeTruthy();
    expect(await violations()).toEqual([]);
    await user.keyboard('{Escape}');

    await user.click(screen.getByRole('button', { name: 'Archive with Undo' }));
    await user.click(screen.getByRole('button', { name: 'Row actions' }));
    expect(screen.getByRole('menu', { name: 'Row actions' })).toBeTruthy();
    expect(await violations()).toEqual([]);
    await user.keyboard('{Escape}');

    const cards = document.querySelectorAll<HTMLButtonElement>('.build-card');
    await user.click(cards[cards.length - 1] as HTMLButtonElement);
    expect(screen.getByRole('dialog', { name: /What's new/ })).toBeTruthy();
    expect(await violations()).toEqual([]);
    await user.keyboard('{Escape}');

    act(() => {
      fireEvent.keyDown(document.body, { key: '?' });
    });
    expect(screen.getByRole('dialog', { name: 'Keyboard shortcuts' })).toBeTruthy();
    expect(await violations()).toEqual([]);
  }, 60000);
});
