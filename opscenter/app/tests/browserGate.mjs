// Shared gate for the browser tests (axe, live actions).
// A browser test may skip only on a machine that was never given a browser, such as a laptop with no
// Chrome. In CI (CI=true) it never skips, and when CHROME_BIN is set it never skips either, so a
// missing dist/ or a CHROME_BIN that points at nothing fails the run instead of passing silently.
// A browser that exists but cannot start fails inside the test (the DevTools connection times out).
import { existsSync } from 'node:fs'
import { join } from 'node:path'

export function browserGate({ chrome, dist }) {
  // Never open a browser on a developer's desktop by accident: locally the suite runs only when asked for (OPSCENTER_BROWSER_TESTS=1, with CHROME_BIN
  // pointing at a headless capable Chrome or Chromium). CI always runs it.
  const ci0 = process.env.CI === 'true' || process.env.CI === '1'
  if (!ci0 && process.env.OPSCENTER_BROWSER_TESTS !== '1') return 'browser tests run on CI; set OPSCENTER_BROWSER_TESTS=1 to run them here'
  const problem = !existsSync(join(dist, 'index.html'))
    ? 'dist/ is missing, run npm run build first'
    : !existsSync(chrome)
      ? process.env.CHROME_BIN
        ? `CHROME_BIN points at ${chrome}, which does not exist`
        : 'Chrome is not installed (set CHROME_BIN)'
      : ''
  if (!problem) return false
  const ci = process.env.CI === 'true' || process.env.CI === '1'
  if (ci || process.env.CHROME_BIN) throw new Error(`browser tests cannot run: ${problem}`)
  return problem
}

// Chrome flags shared by the browser tests. The sandbox stays on unless the runner cannot give
// Chrome user namespaces (Ubuntu 24.04 restricts them), which the workflow states with CHROME_NO_SANDBOX=1.
export function chromeArgs({ port, profile }) {
  return [
    '--headless=new',
    '--disable-gpu',
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-extensions',
    ...(process.env.CHROME_NO_SANDBOX === '1' ? ['--no-sandbox'] : []),
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profile}`,
    '--window-size=1440,1000',
    'about:blank',
  ]
}
