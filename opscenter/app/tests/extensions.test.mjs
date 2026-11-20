import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { EXTENSION_GROUPS, extensionPath, extensionRoute, extensionsMode, pageMode, pagesAll, pagesIn, safeHref } from '../src/lib/extensions.ts'

const page = (id, group = 'Operate', over = {}) => ({ id, title: id, group, kind: 'list', url: null, lede: null, ...over })
const manifest = (pages, over = {}) => ({ configured: true, fetched_utc: 'x', pages, truncated: 0, error: null, ...over })
const rows = (over = {}) => ({ fetched_utc: 'x', page: page('reports'), rows: [], truncated: 0, error: null, ...over })
const row = (id) => ({ id, title: id, detail: null, state: null, url: null, at: null })

test('no provider adds nothing to the rail, and so does a state that has not loaded yet', () => {
  assert.equal(extensionsMode({ configured: false }), 'none')
  assert.equal(extensionsMode(null), 'none')
  assert.equal(extensionsMode(undefined), 'none')
})

test('a failed source is an error and never reads as no extra pages, even when it also lists none', () => {
  assert.equal(extensionsMode(manifest([], { error: 'the source failed (OSError)' })), 'error')
  assert.equal(extensionsMode(manifest([page('a1')], { error: 'x' })), 'error')
})

test('a working source with pages adds them, and a working source with none adds nothing', () => {
  assert.equal(extensionsMode(manifest([page('a1')])), 'pages')
  assert.equal(extensionsMode(manifest([])), 'none')
})

test('pagesIn gives the pages of one group in the order declared, and none while the source is failing or absent', () => {
  const s = manifest([page('a1', 'Operate'), page('a2', 'People'), page('a3', 'Operate')])
  assert.deepEqual(pagesIn(s, 'Operate').map((p) => p.id), ['a1', 'a3'])
  assert.deepEqual(pagesIn(s, 'People').map((p) => p.id), ['a2'])
  assert.deepEqual(pagesIn(s, 'Knowledge'), [])
  assert.deepEqual(pagesIn(manifest([page('a1')], { error: 'x' }), 'Operate'), [])
  assert.deepEqual(pagesIn({ configured: false }, 'Operate'), [])
  assert.deepEqual(pagesIn(null, 'Operate'), [])
})

test('the rail gets every page of a working source and none from a failing, absent or unloaded one', () => {
  const s = manifest([page('a1'), page('a2', 'People')])
  assert.deepEqual(pagesAll(s).map((p) => p.id), ['a1', 'a2'])
  assert.deepEqual(pagesAll(manifest([page('a1')], { error: 'the source failed (OSError)' })), [], 'a failing source adds nothing and invents nothing')
  assert.deepEqual(pagesAll({ configured: false }), [])
  assert.deepEqual(pagesAll(null), [])
})

test('the page route waits for the first answer, shows a named page, and leaves for any other case', () => {
  const s = manifest([page('reports')])
  assert.equal(extensionRoute(null, 'reports', false), 'wait', 'the first answer has not arrived')
  assert.equal(extensionRoute(null, 'reports', true), 'leave', 'an unreachable server shows nothing to open')
  assert.equal(extensionRoute(s, 'reports', false), 'show')
  assert.equal(extensionRoute(s, 'other', false), 'leave', 'a page the manifest does not name')
  assert.equal(extensionRoute({ configured: false }, 'reports', false), 'leave', 'no provider')
  assert.equal(extensionRoute(manifest([page('reports')], { error: 'x' }), 'reports', false), 'leave', 'a failing source')
})

test('the rail groups are the four the core has, so a page cannot invent one', () => {
  assert.deepEqual([...EXTENSION_GROUPS], ['Operate', 'People', 'Knowledge', 'Platform'])
})

test('an extension page lives under its own prefix, clear of every core route', () => {
  assert.equal(extensionPath('reports'), '/extensions/reports')
})

test('only an http or https address is a link, and anything else is dropped', () => {
  assert.equal(safeHref('https://t.test/x'), 'https://t.test/x')
  assert.equal(safeHref('http://t.test/x'), 'http://t.test/x')
  for (const bad of ['javascript:alert(1)', 'data:text/html,x', 'file:///etc/passwd', '//t.test', 'ftp://t.test', '', null, undefined, 7])
    assert.equal(safeHref(bad), null, String(bad))
})

test('a page is an error when its source failed, a link for a link page, and otherwise rows or an honest empty', () => {
  assert.equal(pageMode(rows({ error: 'the source failed (OSError)', rows: [row('r1')] })), 'error')
  assert.equal(pageMode(rows({ page: page('docs', 'Knowledge', { kind: 'link', url: 'https://t.test' }) })), 'link')
  assert.equal(pageMode(rows({ rows: [row('r1')] })), 'rows')
  assert.equal(pageMode(rows()), 'empty')
  assert.equal(pageMode(null), 'empty')
})

// The pages read and link. A button that changes something is a separate decision with its own confirmation (standards/automation-safety.md),
// so a regression that adds a write path here would quietly create it without that design.
test('the extension pages have no write path: no post function, no fetch, no button, no raw html', () => {
  for (const f of ['../src/lib/extensions.ts', '../src/components/ExtensionPage.tsx']) {
    let src
    try {
      src = readFileSync(new URL(f, import.meta.url), 'utf8').replace(/\/\/.*$/gm, '')
    } catch {
      continue
    }
    assert.equal(/\bpost[A-Z]\w*/.test(src), false, `${f} must not call a post function`)
    assert.equal(/fetch\(|method:\s*'(POST|DELETE|PUT)'/.test(src), false, `${f} must not send a request`)
    assert.equal(/<button|onClick=/.test(src), false, `${f} must not draw a button`)
    assert.equal(/dangerouslySetInnerHTML|innerHTML/.test(src), false, `${f} must not draw raw markup`)
  }
})
