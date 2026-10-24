/* Interactions the jsdom tests cannot prove: real keyboard and pointer input in a browser, against
   the built gallery. No screenshots here, only behaviour. */

import { expect, test } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('./?gate');
  await expect(page.locator('#specimen-charts')).toBeVisible();
});

test('palette filter tabs cycle with Tab and Shift+Tab and narrow the rows', async ({ page }) => {
  await page.locator('body').click({ position: { x: 1, y: 1 } });
  await page.keyboard.press('ControlOrMeta+k');
  const dialog = page.getByRole('dialog', { name: 'Search' });
  await expect(dialog).toBeVisible();
  const tabs = dialog.getByRole('group', { name: 'Search filters' }).getByRole('button');
  const rows = dialog.getByRole('option');
  await expect(tabs.filter({ hasText: 'All' })).toHaveAttribute('aria-pressed', 'true');
  const all = await rows.count();

  await page.keyboard.press('Tab');
  await expect(tabs.filter({ hasText: 'Pages' })).toHaveAttribute('aria-pressed', 'true');
  await expect(dialog.getByRole('combobox')).toBeFocused();
  const pages = await rows.count();
  expect(pages).toBeGreaterThan(0);
  expect(pages).toBeLessThan(all);
  await expect(dialog.getByRole('option', { name: /Table/ })).toHaveCount(0);

  await page.keyboard.press('Tab');
  await expect(tabs.filter({ hasText: 'Data' })).toHaveAttribute('aria-pressed', 'true');
  await expect(dialog.getByRole('option', { name: /Table/ })).toHaveCount(1);

  await page.keyboard.press('Shift+Tab');
  await page.keyboard.press('Shift+Tab');
  await expect(tabs.filter({ hasText: 'All' })).toHaveAttribute('aria-pressed', 'true');
  await expect(rows).toHaveCount(all);

  await tabs.filter({ hasText: 'Data' }).click();
  await expect(tabs.filter({ hasText: 'Data' })).toHaveAttribute('aria-pressed', 'true');
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
});
