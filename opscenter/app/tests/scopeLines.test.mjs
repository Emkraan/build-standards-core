// Item 28 of the Ops Center parity issue: every core page states its own scope in one line under the title.
// A page that draws a HubHeader must give it a subtitle, and the line must read as plain words.

import assert from 'node:assert/strict'
import { readdirSync, readFileSync } from 'node:fs'
import { test } from 'node:test'

const PAGES = new URL('../src/pages/', import.meta.url)
const files = readdirSync(PAGES).filter((f) => f.endsWith('.tsx'))

// The page files that draw their own HubHeader. A tab body rendered inside a hub (ActionCenter) has none of its own.
const headers = files
  .map((f) => ({ f, src: readFileSync(new URL(f, PAGES), 'utf8') }))
  .map(({ f, src }) => ({ f, tag: src.match(/<HubHeader\b[\s\S]*?\/>/)?.[0] ?? null }))
  .filter((x) => x.tag)

test('the page files that draw a header are found, so this guard cannot pass by looking at nothing', () => {
  assert.ok(headers.length >= 10, `expected the core hub pages, found ${headers.length}`)
  for (const name of ['ActionHub.tsx', 'Knowledge.tsx', 'Operations.tsx', 'TeamHub.tsx', 'JiraHub.tsx']) {
    assert.ok(headers.some((h) => h.f === name), `${name} draws a HubHeader`)
  }
})

test('every core page header carries a subtitle, which is its one line scope statement', () => {
  const missing = headers.filter((h) => !/\bsubtitle=/.test(h.tag)).map((h) => h.f)
  assert.deepEqual(missing, [], `these pages draw a header with no scope line: ${missing.join(', ')}`)
})

test('a literal scope line is a sentence long enough to say something and has no semicolon or em dash', () => {
  for (const h of headers) {
    const m = h.tag.match(/subtitle=(?:"([^"]*)"|\{'([^']*)'\})/)
    if (!m) continue // a computed subtitle is checked in the browser test
    const line = (m[1] ?? m[2]).trim()
    assert.ok(line.length > 20, `${h.f}: the scope line is too short to say anything: ${JSON.stringify(line)}`)
    assert.equal(/[;\u2014]/.test(line), false, `${h.f}: no semicolon or em dash in the scope line`)
  }
})
