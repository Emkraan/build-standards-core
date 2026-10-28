// Date: 2026-10-27
// Purpose: the 1:1 Board shows the stale marker when the roster came from the last-pull copy.
// The API side (what sets roster.stale) is tested in identity_roster_test.py. This pins the screen side:
// the page renders the app's AlertBanner from board.roster.stale with the copy's age.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

const page = readFileSync(new URL('../src/pages/OneOnOnes.tsx', import.meta.url), 'utf8')
const types = readFileSync(new URL('../src/lib/data.ts', import.meta.url), 'utf8')

test('core-rule: identity-and-people-data.1.1 the board banner follows roster.stale and shows the copy age', () => {
  assert.match(page, /import AlertBanner from '\.\.\/components\/AlertBanner'/)
  assert.match(page, /data\.roster\?\.stale && \(\s*<AlertBanner[\s\S]*?relTime\(data\.roster\.as_of\)/)
  assert.match(types, /roster\?: \{ stale: boolean; as_of: string \| null/)
})
