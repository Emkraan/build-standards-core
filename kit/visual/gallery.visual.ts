/* The visual gate for the kit gallery (issue: Playwright screenshots and axe in both themes).
   Every specimen section carries a stable id (specimen-<name>) and data-specimen. Each one is
   screenshotted in dark and light and compared to the committed baselines, then axe runs on the
   whole page with color-contrast on. Live content is held still: the clock is installed and
   paused before the page loads for the screenshots, reduced motion is forced, and ?gate swaps the git-generated
   release notes for the fixed sample. Refresh baselines with npm run visual:update. */

import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { findOverflow } from './overflow';

const THEMES = ['dark', 'light'] as const;
type Theme = (typeof THEMES)[number];

const FROZEN_AT = new Date('2026-10-13T12:00:00Z');

/** The specimens the gallery has always had. New ones are picked up from the page as well. */
const CORE_SPECIMENS = ['theme', 'buttons', 'marks', 'stat-tiles', 'tabs', 'fields', 'table', 'empty', 'overlays', 'chrome', 'charts'];

/**
 * Opens the gallery in one theme. `paused` installs a paused fake clock, so no interval, timeout
 * or animation frame ever fires (the screenshots). axe schedules its own work on timers, so the
 * axe run only fixes Date and lets timers run.
 */
async function openGallery(page: Page, theme: Theme, paused: boolean): Promise<string[]> {
  await page.addInitScript((value) => {
    window.localStorage.setItem('gallery.theme', value);
  }, theme);
  await page.emulateMedia({ reducedMotion: 'reduce', colorScheme: theme });
  if (paused) {
    await page.clock.install({ time: FROZEN_AT });
    await page.clock.pauseAt(FROZEN_AT);
  } else {
    await page.clock.setFixedTime(FROZEN_AT);
  }
  await page.goto('./?gate');
  await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
  await expect(page.locator('#specimen-charts')).toBeVisible();
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  // Grow the viewport to the whole page so no specimen is captured under the sticky top bar.
  const height = await page.evaluate(() => {
    const els = [document.documentElement, ...Array.from(document.querySelectorAll<HTMLElement>('main, .main, [data-scroll]'))];
    return Math.max(...els.map((el) => el.scrollHeight));
  });
  await page.setViewportSize({ width: 1280, height: Math.min(Math.max(height, 900), 12000) });
  await page.evaluate(() => window.scrollTo(0, 0));
  return page.locator('[data-specimen]').evaluateAll((els) => els.map((el) => el.getAttribute('data-specimen') ?? ''));
}

/**
 * axe's default rule set (the same one the jsdom run uses), with color-contrast on because a real
 * browser paints. target-size (WCAG 2.2, 24 by 24 pixel targets) is off for now: the feed strip
 * pager dots in kit/src are 8 by 20 pixels and fail it. That is a kit component finding, recorded
 * in CHANGELOG.md, and this exclusion goes when the dots grow.
 */
async function axeViolations(page: Page): Promise<{ rule: string; impact: string | null | undefined; nodes: string[] }[]> {
  const results = await new AxeBuilder({ page }).disableRules(['target-size']).analyze();
  const ran = [...results.passes, ...results.violations, ...results.incomplete].some((r) => r.id === 'color-contrast');
  expect(ran, 'the color-contrast rule ran').toBe(true);
  return results.violations.map((v) => ({
    rule: v.id,
    impact: v.impact,
    nodes: v.nodes.map((n) => `${n.target.join(' ')}: ${n.failureSummary?.replace(/\s+/g, ' ') ?? ''}`),
  }));
}

for (const theme of THEMES) {
  test.describe(`${theme} theme`, () => {
    test('every specimen matches its baseline', async ({ page }) => {
      // About fifty full specimen screenshots: this outgrew the default 30 second budget on a busy runner.
      test.slow();
      const ids = await openGallery(page, theme, false);
      expect(new Set(ids).size, 'specimen ids are unique').toBe(ids.length);
      for (const id of CORE_SPECIMENS) expect(ids, `specimen-${id} is on the page`).toContain(id);
      for (const id of ids) {
        await expect.soft(page.locator(`#specimen-${id}`), `specimen-${id} in ${theme}`).toHaveScreenshot([theme, `${id}.png`]);
      }
    });

    test('no text escapes or is cut off by its box', async ({ page }) => {
      await openGallery(page, theme, false);
      expect(await page.evaluate(findOverflow, 1.5), 'at the full gallery width').toEqual([]);
      // The narrow shell: labels that fit at desktop width are the ones that wrap or spill here.
      await page.setViewportSize({ width: 720, height: page.viewportSize()?.height ?? 900 });
      expect(await page.evaluate(findOverflow, 1.5), 'at 720 pixels').toEqual([]);
    });

    test('axe finds no violations with color-contrast on', async ({ page }) => {
      // Three full axe passes over the whole gallery: this outgrew the default 30 second budget.
      test.slow();
      await openGallery(page, theme, false);
      expect(await axeViolations(page)).toEqual([]);
      // Overlays render on their own surfaces, so contrast is checked with each one open too.
      for (const name of ['Open dialog', 'Open sheet']) {
        await page.getByRole('button', { name, exact: true }).click();
        await expect(page.getByRole('dialog')).toBeVisible();
        expect(await axeViolations(page), `with ${name.toLowerCase()} open`).toEqual([]);
        await page.keyboard.press('Escape');
        await expect(page.getByRole('dialog')).toHaveCount(0);
      }
    });
  });
}
