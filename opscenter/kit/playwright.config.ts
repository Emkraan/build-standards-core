import { defineConfig, devices } from '@playwright/test';

// The visual gate: screenshots of every gallery specimen in both themes plus axe with
// color-contrast on, in a real browser. It serves the built gallery (npm run gallery:build), so
// run it through npm run visual. Baselines live per platform under visual/baselines. Only the
// linux set is committed and CI compares against it, inside the pinned Playwright image.
const port = 4179;

export default defineConfig({
  testDir: './visual',
  testMatch: '*.visual.ts',
  outputDir: './visual/results',
  snapshotPathTemplate: '{testDir}/baselines/{platform}/{arg}{ext}',
  fullyParallel: true,
  forbidOnly: !!process.env['CI'],
  retries: 0,
  reporter: process.env['CI'] ? [['list'], ['html', { open: 'never', outputFolder: './visual/report' }]] : 'list',
  expect: {
    toHaveScreenshot: {
      // Anti-aliasing noise only. A real change moves far more pixels than this.
      threshold: 0.2,
      maxDiffPixelRatio: 0.001,
      animations: 'disabled',
      caret: 'hide',
      scale: 'css',
    },
  },
  use: {
    baseURL: `http://127.0.0.1:${port}/`,
    ...devices['Desktop Chrome'],
    viewport: { width: 1280, height: 900 },
    deviceScaleFactor: 1,
    locale: 'en-US',
    timezoneId: 'UTC',
    reducedMotion: 'reduce',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium' }],
  webServer: {
    command: `npx vite preview --config vite.gallery.config.ts --host 127.0.0.1 --port ${port} --strictPort`,
    url: `http://127.0.0.1:${port}/`,
    reuseExistingServer: !process.env['CI'],
    timeout: 60_000,
  },
});
