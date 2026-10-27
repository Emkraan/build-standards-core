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
  await expect(scale).toHaveAttribute('aria-disabled', 'true');
  await expect(scale).not.toHaveAttribute('disabled', /.*/);

  // Sections above this one finish rendering late on a slow runner and move the button, so wait for the
  // page height to hold, centre the button, and hover again from outside until the tip shows.
  await expect(async () => {
    const before = await page.evaluate(() => document.documentElement.scrollHeight);
    await page.waitForTimeout(700);
    expect(await page.evaluate(() => document.documentElement.scrollHeight)).toBe(before);
  }).toPass({ timeout: 20000 });
  await page.evaluate(() => {
    const w = window as unknown as { __log: string[] };
    w.__log = [];
    for (const type of ['pointerover', 'pointerout', 'pointerdown', 'scroll', 'focusin'])
      document.addEventListener(type, (e) => w.__log.push(`${type}:${(e.target as HTMLElement)?.className ?? 'doc'}`.slice(0, 40)), true);
  });
  try {
  await expect(async () => {
    await scale.evaluate((el) => el.scrollIntoView({ block: 'center' }));
    await page.mouse.move(1, 1);
    await scale.hover();
    await expect(tip).toHaveCount(1, { timeout: 2000 });
  }).toPass({ timeout: 8000 });
  } catch (error) {
    const info = await page.evaluate(() => {
      const b = document.querySelector('#specimen-tips .btn[aria-disabled]') as HTMLElement;
      const r = b.getBoundingClientRect();
      const top = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
      return JSON.stringify({ rect: [r.x, r.y, r.width, r.height], top: top?.className, tip: b.getAttribute('data-tip'), log: (window as unknown as { __log: string[] }).__log.slice(-14), vh: innerHeight });
    });
    throw new Error(`DIAG ${info}`);
  }
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
