// Date: 2026-11-25
// Purpose: item 10 of issue 376. Each table of the parity spec (issue 327, section 5) keeps its columns, in order, at its widths.
// The page source is the test input: the column arrays are read from the .tsx files, so the test needs no browser and no live data.
// Two lists. SPEC must match. DRIFT is the spec tables the app does not match yet, each with the reason, and the test fails when one
// of them starts to match, so the entry has to move to SPEC and the list cannot go stale.

import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { test } from 'node:test'
import { DRIFT, FLEX, HEAD_SPEC, SPEC } from './tableSpec.mjs'

const SRC = new URL('../src/', import.meta.url)
const read = (p) => readFileSync(new URL(p, SRC), 'utf8')

// Every array literal whose items are column objects ({ key: ..., header: ... }), as a list of { header: [labels], width }.
function columnArrays(src) {
  const out = []
  const start = /\[\s*\{\s*key:/g
  let m
  while ((m = start.exec(src))) {
    let i = m.index
    let depth = 0
    while (i < src.length) {
      if (src[i] === '[') depth++
      else if (src[i] === ']' && --depth === 0) break
      i++
    }
    out.push(objects(src.slice(m.index + 1, i)))
  }
  return out
}

// The top level { ... } objects of an array body.
function objects(body) {
  const cols = []
  let depth = 0
  let from = -1
  for (const [i, ch] of [...body].entries()) {
    if (ch === '{') {
      if (depth++ === 0) from = i
    } else if (ch === '}' && --depth === 0) {
      const obj = body.slice(from, i + 1)
      const h = obj.match(/\bheader:\s*([\s\S]*?)(?=,\s*[A-Za-z_]+\s*:|\s*\}$)/)
      if (h) {
        const labels = [...h[1].matchAll(/'([^']*)'|"([^"]*)"|`([^`]*)`/g)].map((x) => x[1] ?? x[2] ?? x[3])
        const width = obj.match(/\bwidth:\s*'([^']+)'/)?.[1] ?? FLEX
        cols.push({ labels, width })
      }
    }
  }
  return cols
}

const matches = (cols, spec) =>
  cols.length === spec.length && spec.every(([label, width], i) => cols[i].labels.includes(label) && cols[i].width === width)

const headingsOf = (src, marker) => {
  const at = src.indexOf(`className="${marker}"`)
  if (at < 0) return null
  const head = src.slice(at, src.indexOf('</thead>', at))
  return [...head.matchAll(/<th[^>]*>([^<]*)<\/th>/g)].map((x) => x[1].trim())
}

test('every spec file is there and the lists are long enough that this cannot pass by checking nothing', () => {
  assert.ok(SPEC.length >= 10, `expected the spec tables, have ${SPEC.length}`)
  for (const t of [...SPEC, ...HEAD_SPEC, ...DRIFT]) assert.ok(existsSync(new URL(t.file, SRC)), `${t.table}: ${t.file} does not exist`)
  for (const t of SPEC) assert.ok(columnArrays(read(t.file)).length > 0, `${t.table}: no column array found in ${t.file}`)
})

for (const t of SPEC) {
  test(`${t.table} keeps the spec columns, in order, at the spec widths`, () => {
    const arrays = columnArrays(read(t.file))
    assert.ok(
      arrays.some((cols) => matches(cols, t.columns)),
      `${t.table}: no column array in ${t.file} matches [${t.columns.map(([l, w]) => `${l} ${w}`).join(', ')}]. Found: ` +
        arrays.map((cols) => `[${cols.map((c) => `${c.labels.join(' or ')} ${c.width}`).join(', ')}]`).join(' ')
    )
  })
}

for (const t of HEAD_SPEC) {
  test(`${t.table} keeps the spec headings, in order`, () => {
    const got = headingsOf(read(t.file), t.marker)
    assert.ok(got, `${t.table}: no table with class ${t.marker} in ${t.file}`)
    assert.deepEqual(got, t.headings)
  })
}

for (const t of DRIFT) {
  test(`${t.table} is a known drift from the spec and still is: ${t.why}`, () => {
    const arrays = columnArrays(read(t.file))
    assert.ok(arrays.length > 0, `${t.table}: no column array found in ${t.file}`)
    assert.equal(
      arrays.some((cols) => matches(cols, t.columns)),
      false,
      `${t.table} now matches the spec: move it from DRIFT to SPEC`
    )
  })
}
