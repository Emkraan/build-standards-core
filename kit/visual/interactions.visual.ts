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

test('a LaneBoard card moves to another lane by pointer drag and by keyboard', async ({ page }) => {
  const specimen = page.locator('#specimen-lane-board');
  const todo = specimen.getByRole('region', { name: /^To do,/ });
  const doing = specimen.getByRole('region', { name: /^In progress,/ });
  const done = specimen.getByRole('region', { name: /^Done,/ });
  await specimen.scrollIntoViewIfNeeded();
  await expect(done).toHaveAccessibleName('Done, 0 cards');

  await specimen.locator('[data-card-id="a"]').dragTo(done);
  await expect(done).toHaveAccessibleName('Done, 1 card');
  await expect(todo).toHaveAccessibleName('To do, 1 card');
  await expect(done.locator('[data-card-id="a"]')).toHaveCount(1);

  const card = specimen.locator('[data-card-id="b"]');
  await card.focus();
  await page.keyboard.press('Space');
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('Space');
  await expect(doing).toHaveAccessibleName('In progress, 2 cards');
  await expect(todo).toHaveAccessibleName('To do, 0 cards');
  await expect(specimen.getByRole('status')).not.toHaveText('');
});

test('the shell mounts one tip layer: a disabled reason and a term meaning show on hover and on keyboard focus', async ({ page }) => {
  const specimen = page.locator('#specimen-tips');
  const tip = page.locator('.tooltip');
  const scale = specimen.getByRole('button', { name: 'Scale pool' });
  await specimen.scrollIntoViewIfNeeded();
  await expect(scale).toHaveAttribute('aria-disabled', 'true');
  await expect(scale).not.toHaveAttribute('disabled', /.*/);

  await scale.hover();
  await expect(tip).toHaveCount(1);
  await expect(tip).toHaveText('Choose a host pool first. The size applies to that pool.');
  await page.keyboard.press('Escape');
  await expect(tip).toHaveCount(0);

  // The button is a tab stop, so the reason reaches a keyboard user as well.
  await scale.focus();
  await expect(scale).toBeFocused();
  await expect(tip).toHaveCount(1);
  await expect(tip).toHaveText(/Choose a host pool first/);

  const term = specimen.locator('.term').first();
  await term.focus();
  await expect(tip).toHaveCount(1);
  await expect(tip).toHaveText('A group of machines that share one image and settings.');
});

test('the Help button opens the page help drawer, and Escape closes it and returns focus to the button', async ({ page }) => {
  const help = page.getByRole('button', { name: 'Help', exact: true });
  await expect(help).toHaveAttribute('aria-expanded', 'false');
  await help.click();
  const drawer = page.getByRole('dialog', { name: 'Help: Kit gallery' });
  await expect(drawer).toBeVisible();
  await expect(help).toHaveAttribute('aria-expanded', 'true');
  await expect(drawer.getByText('Every shared component on one page, in both themes.')).toBeVisible();
  await expect(drawer.getByText('host pool', { exact: true })).toBeVisible();
  await expect(drawer.getByRole('link', { name: /Kit documentation/ })).toHaveAttribute('href', 'https://example.com/docs/kit');

  await page.keyboard.press('Escape');
  await expect(drawer).toBeHidden();
  await expect(help).toBeFocused();
});

test('search lists the help of the page and its words, and choosing one opens the drawer', async ({ page }) => {
  await page.locator('body').click({ position: { x: 1, y: 1 } });
  await page.keyboard.press('ControlOrMeta+k');
  const palette = page.getByRole('dialog', { name: 'Search' });
  await expect(palette).toBeVisible();
  await palette.getByRole('combobox').fill('host pool');
  const row = palette.getByRole('option', { name: /host pool/i });
  await expect(row).toHaveCount(1);
  await row.click();
  await expect(page.getByRole('dialog', { name: 'Help: Kit gallery' })).toBeVisible();
});
