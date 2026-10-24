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

test('a Table with mobile="cards" reflows to labelled cards on a phone and back on a desktop', async ({ page }) => {
  const specimen = page.locator('#specimen-phone-cards');
  const firstRow = specimen.locator('tbody tr').first();
  const firstCell = firstRow.locator('td').first();
  await page.setViewportSize({ width: 390, height: 900 });
  await specimen.scrollIntoViewIfNeeded();
  await expect(firstRow).toHaveCSS('display', 'block');
  await expect(firstCell).toHaveCSS('display', 'grid');
  const label = await firstCell.evaluate((el) => getComputedStyle(el, '::before').content);
  expect(label).toBe('"Host"');
  await expect(specimen.getByRole('columnheader', { name: 'Host' })).toHaveCount(1);
  await page.setViewportSize({ width: 1280, height: 900 });
  await expect(firstRow).toHaveCSS('display', 'table-row');
  await expect(specimen.locator('thead th').first()).toHaveCSS('position', 'static');
});
