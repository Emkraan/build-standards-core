/* axe-core on the gallery, which renders every kit component, in both themes and with the
   overlays open. jsdom has no layout or paint, so axe cannot compute colour contrast there: the
   color-contrast rule is disabled here and contrast is certified on the tokens instead
   (tokens/build.py --check). Every other rule runs.

   Each axe pass walks the whole ~4800 node gallery document and takes 2 to 5 seconds, so the
   cases are one test per overlay (each well under the 20 second default timeout) and the two
   themes live in separate files (a11y.light.test.tsx, a11y.dark.test.tsx) so vitest runs them in
   parallel workers instead of one 60 second test that CI load pushed past its limit. */
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

type User = ReturnType<typeof userEvent.setup>;

const SCENARIOS: Array<[string, (user: User) => Promise<void>]> = [
  ['the composite', async () => {}],
  ['the dialog', async (user) => {
    await user.click(screen.getByRole('button', { name: 'Open dialog' }));
    expect(screen.getByRole('dialog', { name: 'Edit device' })).toBeTruthy();
  }],
  ['the confirm alertdialog', async (user) => {
    await user.click(screen.getByRole('button', { name: 'Delete schedule' }));
    expect(await screen.findByRole('alertdialog')).toBeTruthy();
  }],
  ['the search palette', async () => {
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true });
    expect(screen.getByRole('dialog', { name: 'Search' })).toBeTruthy();
  }],
  ['the row actions menu', async (user) => {
    await user.click(screen.getByRole('button', { name: 'Archive with Undo' }));
    await user.click(screen.getByRole('button', { name: 'Row actions' }));
    expect(screen.getByRole('menu', { name: 'Row actions' })).toBeTruthy();
  }],
  ['the whats-new dialog', async (user) => {
    const cards = document.querySelectorAll<HTMLButtonElement>('.build-card');
    await user.click(cards[cards.length - 1] as HTMLButtonElement);
    expect(screen.getByRole('dialog', { name: /What's new/ })).toBeTruthy();
  }],
  ['the keyboard shortcuts dialog', async () => {
    act(() => {
      fireEvent.keyDown(document.body, { key: '?' });
    });
    expect(screen.getByRole('dialog', { name: 'Keyboard shortcuts' })).toBeTruthy();
  }],
  ['the help drawer', async (user) => {
    // The page registers help, so the Header has a Help button and the drawer opens from it.
    await user.click(screen.getByRole('button', { name: 'Help' }));
    expect(screen.getByRole('dialog', { name: 'Help: Kit gallery' })).toBeTruthy();
  }],
];

export function runA11y(theme: 'light' | 'dark'): void {
  describe(`axe in the ${theme} theme`, () => {
    beforeAll(() => {
      document.title = 'Kit gallery';
      document.documentElement.lang = 'en';
    });

    it.each(SCENARIOS)('finds no violations on %s', async (_name, open) => {
      const user = userEvent.setup();
      window.localStorage.setItem('gallery.theme', theme);
      render(<GalleryApp />);
      expect(document.documentElement.getAttribute('data-theme')).toBe(theme);
      await open(user);
      expect(await violations()).toEqual([]);
    });
  });
}
