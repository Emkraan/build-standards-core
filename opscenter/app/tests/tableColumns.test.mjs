// Date: 2026-11-25
// Purpose: item 10 of issue 376. Each table of the parity spec (issue 327, section 5) keeps its columns, in order, at its widths.
// The page source is the test input: the column arrays are read from the .tsx files, so the test needs no browser and no live data.
// Two lists. SPEC must match. DRIFT is the spec tables the app does not match yet, each with the reason, and the test fails when one
// of them starts to match, so the entry has to move to SPEC and the list cannot go stale.

import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { test } from 'node:test'

const SRC = new URL('../src/', import.meta.url)
const read = (p) => readFileSync(new URL(p, SRC), 'utf8')

// A width is a px or percent string the column declares, or FLEX when the column takes what is left (the spec's number for it is the
// measured result at 1208px, not a declared value).
const FLEX = 'flex'

const SPEC = [
  {
    table: 'Action Center table',
    file: 'components/ActionTable.tsx',
    columns: [
      ['Priority', '104px'],
      ['Item', FLEX],
      ['Person', '112px'],
      ['Source', '112px'],
      ['1:1 / status', '124px'],
      ['Tickets', '160px'],
      ['Since', '108px'],
    ],
  },
  {
    table: 'Routing, considered',
    file: 'pages/ActionRouting.tsx',
    columns: [
      ['Input', '42%'],
      ['What happened', '58%'],
    ],
  },
  {
    table: 'Backlog',
    file: 'pages/Backlog.tsx',
    columns: [
      ['Key', '140px'],
      ['Summary', FLEX],
      ['Priority', '108px'],
      ['Status', '170px'],
      ['Type', '96px'],
      ['Pts', '64px'],
      ['Actions', '310px'],
    ],
  },
  {
    table: 'Spend, token windows',
    file: 'pages/infra/Spend.tsx',
    columns: [
      ['Window', FLEX],
      ['Calls', FLEX],
      ['Input', FLEX],
      ['Output', FLEX],
      ['Cache read', FLEX],
      ['Cache write', FLEX],
      ['Total', FLEX],
    ],
  },
  {
    table: 'Spend, by cron job',
    file: 'pages/infra/Spend.tsx',
    columns: [
      ['Job', FLEX],
      ['Runs', FLEX],
      ['Fell back', FLEX],
      ['Billed today', FLEX],
      ['Billed 7d', FLEX],
      ['Team 7d', FLEX],
    ],
  },
  {
    table: 'Spend, by month',
    file: 'pages/infra/Spend.tsx',
    columns: [
      ['Month', FLEX],
      ['Billed', FLEX],
      ['Team', FLEX],
      ['Unattrib.', FLEX],
      ['List total', FLEX],
    ],
  },
  {
    table: 'Debt and improvements',
    file: 'pages/EngBacklog.tsx',
    columns: [
      ['Id', '120px'],
      ['Item', FLEX],
      ['Severity or goal / effort', '240px'],
      ['Status', '140px'],
      ['Date', '96px'],
    ],
  },
  {
    table: 'Team, throughput by sprint',
    file: 'pages/TeamPerformance.tsx',
    columns: [
      ['Sprint', '223px'],
      ['Done', '188px'],
      ['Points', '216px'],
    ],
  },
  {
    table: 'Team, open items',
    file: 'pages/TeamPerformance.tsx',
    columns: [
      ['Key', '120px'],
      ['Status', '140px'],
      ['Priority', '110px'],
      ['Summary', FLEX],
    ],
  },
  {
    table: 'Team, run ledger',
    file: 'pages/TeamHistory.tsx',
    columns: [
      ['Period', '152px'],
      ['Sprints', '208px'],
      ['Engineer', '201px'],
      ['Completion', '153px'],
      ['Pts deliv.', '133px'],
      ['Done', '101px'],
      ['Carry', '103px'],
      ['Intake', '110px'],
    ],
  },
]

// Tables the app draws as a plain table element, matched on the heading cells. The spec shows the headings in capitals, a style rule.
const HEAD_SPEC = [{ table: 'Reviews, grants', file: 'components/ApprovalBrief.tsx', marker: 'rh-grants rh-grants-why', headings: ['Kind', 'What', 'Severity', 'Where'] }]

const DRIFT = [
  {
    table: 'Scheduled jobs',
    file: 'pages/infra/Jobs.tsx',
    columns: [
      ['Job', FLEX],
      ['Type', '117px'],
      ['Schedule', '133px'],
      ['Last run', '88px'],
      ['Next', '78px'],
      ['Logs 7d', '86px'],
      ['Health', '103px'],
    ],
    why: 'the table adds an unlabelled row action column after Health that the spec does not list',
  },
  {
    table: 'Changes',
    file: 'components/Approvals.tsx',
    columns: [
      ['Change', '120px'],
      ['Summary', FLEX],
      ['Window', '150px'],
      ['Risk', '120px'],
      ['Type and status', '220px'],
      ['', '90px'],
    ],
    why: 'the table has no Type and status column and labels the last column Actions instead of leaving it unlabelled',
  },
  {
    table: 'Reviews, workflow runs',
    file: 'components/TfReviews.tsx',
    columns: [
      ['When', FLEX],
      ['PR', FLEX],
      ['Workflow', FLEX],
      ['Files', FLEX],
    ],
    why: 'the first heading reads When (UTC), the spec reads When',
  },
]

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
