// Bundle size budget check (web-client-runtime.md 4.1).
// Reads dist/index.html, finds the entry script and its eagerly loaded modulepreload chunks, and fails
// when the gzip size of the entry chunk or the first-load total passes the budget below.
// Run after the build: node tools/check-bundle-size.mjs (the build script runs it).
// Exit codes: 0 within budget, 1 over budget, 2 no build output found.
import { existsSync, readFileSync } from 'node:fs'
import { gzipSync } from 'node:zlib'
import { dirname, join, normalize } from 'node:path'
import { fileURLToPath } from 'node:url'

const DIST = join(dirname(fileURLToPath(import.meta.url)), '..', 'dist')
// Budgets in KB of gzip. Entry chunk is the app code that loads first. First load adds the vendor
// chunks the page preloads. Raise a budget only in a PR that says why.
const BUDGET_ENTRY_GZIP_KB = Number(process.env.BUNDLE_BUDGET_ENTRY_KB || 70)
const BUDGET_FIRST_LOAD_GZIP_KB = Number(process.env.BUNDLE_BUDGET_FIRST_LOAD_KB || 150)

const indexPath = join(DIST, 'index.html')
if (!existsSync(indexPath)) {
  console.error('check-bundle-size: dist/index.html not found, run the build first')
  process.exit(2)
}
const html = readFileSync(indexPath, 'utf8')
const refs = (re) => [...html.matchAll(re)].map((m) => normalize(join(DIST, m[1])))
const entry = refs(/<script[^>]*type="module"[^>]*src="([^"]+\.js)"/g)
const preload = refs(/<link[^>]*rel="modulepreload"[^>]*href="([^"]+\.js)"/g)
if (entry.length === 0) {
  console.error('check-bundle-size: no module entry script in dist/index.html')
  process.exit(2)
}
const gzipKb = (file) => gzipSync(readFileSync(file)).length / 1024
const entryKb = entry.reduce((n, f) => n + gzipKb(f), 0)
const firstLoadKb = [...new Set([...entry, ...preload])].reduce((n, f) => n + gzipKb(f), 0)

let failed = false
const report = (label, kb, budget) => {
  const over = kb > budget
  failed ||= over
  console.log(`${over ? 'FAIL' : 'ok  '} ${label}: ${kb.toFixed(1)} KB gzip (budget ${budget} KB)`)
}
report('entry chunk', entryKb, BUDGET_ENTRY_GZIP_KB)
report('first load (entry + preloaded chunks)', firstLoadKb, BUDGET_FIRST_LOAD_GZIP_KB)
process.exit(failed ? 1 : 0)
