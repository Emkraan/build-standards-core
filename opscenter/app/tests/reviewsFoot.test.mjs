// Date: 2026-11-21
// Purpose: a server with no review config answers the platform reviews without a gate or a policy object; the page reads both as
// optional so that answer renders the empty page (issue 326 item 3: it threw while rendering and blanked the app).
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { gateFailures, policyFoot } from '../src/lib/reviewsFoot.ts'

const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8')

test('no gate reads as zero failures, and a gate reads its count', () => {
  assert.equal(gateFailures(undefined), 0)
  assert.equal(gateFailures(null), 0)
  assert.equal(gateFailures({}), 0)
  assert.equal(gateFailures({ failures: 4 }), 4)
})

test('no policy gives no footer, a policy gives its version and a home-relative path', () => {
  assert.equal(policyFoot(undefined), null)
  assert.equal(policyFoot({}), null)
  assert.deepEqual(policyFoot({ path: '/Users/someone/p/policy.json', version: 3 }), { version: '3', path: '~/p/policy.json' })
  assert.deepEqual(policyFoot({ path: '/etc/policy.json' }), { version: '', path: '/etc/policy.json' })
})

test('the page no longer dereferences gate or policy without a guard, and the app has a page error boundary', () => {
  const page = read('../src/pages/PlatformReviews.tsx')
  assert.doesNotMatch(page, /data\??\.gate\.[a-z]/)
  assert.doesNotMatch(page, /data\.policy\.[a-z]/)
  assert.match(read('../src/App.tsx'), /<PageErrorBoundary resetKey=\{pathname\}>/)
})
