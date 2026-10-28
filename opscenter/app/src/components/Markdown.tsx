// Shared markdown renderer for the Plans reader (no dependency): headings, lists with real
// checkboxes, tables, code, quotes and links. Relative .md links call onLink so the reader can open
// a sibling document in place. External links must be http(s). Classes use the pl- prefix (Plans.css).
import type { ReactNode } from 'react'
import { Fragment } from 'react'

const SAFE_URL = /^https?:\/\//i
const REL_MD = /^(?!\/)(?![a-z]+:)[\w./-]+\.md(#[\w-]*)?$/i

function inline(text: string, kb: string, onLink?: (href: string) => void): ReactNode[] {
  const out: ReactNode[] = []
  const re = /(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)\s]+\)|https?:\/\/[^\s<>)]+)/g
  let last = 0
  let i = 0
  for (let m = re.exec(text); m !== null; m = re.exec(text)) {
    if (m.index > last) out.push(text.slice(last, m.index))
    const t = m[0]
    const k = `${kb}-${i++}`
    if (t.startsWith('`')) out.push(<code key={k}>{t.slice(1, -1)}</code>)
    else if (t.startsWith('**')) out.push(<b key={k}>{t.slice(2, -2)}</b>)
    else if (t.startsWith('[')) {
      const lm = t.match(/^\[([^\]]+)\]\(([^)\s]+)\)$/)
      const label = lm?.[1] || t
      const href = lm?.[2] || ''
      if (SAFE_URL.test(href))
        out.push(
          <a key={k} href={href} target="_blank" rel="noreferrer noopener">
            {label}
          </a>,
        )
      else if (onLink && REL_MD.test(href))
        out.push(
          <button key={k} type="button" className="pl-rel" onClick={() => onLink(href.split('#')[0])}>
            {label}
          </button>,
        )
      else out.push(<Fragment key={k}>{label}</Fragment>)
    } else
      out.push(
        <a key={k} href={t} target="_blank" rel="noreferrer noopener">
          {t}
        </a>,
      )
    last = m.index + t.length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

const LIST_RE = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/
const TABLE_SEP = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/
function cells(row: string) {
  return row
    .trim()
    .replace(/^\||\|$/g, '')
    .split('|')
    .map((c) => c.trim())
}

export function Markdown({ body, onLink }: { body: string; onLink?: (href: string) => void }) {
  const lines = body.replace(/\r\n/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  let i = 0
  let n = 0
  const isBreak = (l: string) => !l.trim() || /^(#{1,6}\s|```|>|\s*\|)/.test(l) || LIST_RE.test(l) || /^\s*(-{3,}|\*{3,})\s*$/.test(l)
  const ink = (t: string, k: string) => inline(t, k, onLink)
  while (i < lines.length) {
    const line = lines[i]
    const key = `b${n++}`
    if (!line.trim()) {
      i++
      continue
    }
    if (line.startsWith('```')) {
      const code: string[] = []
      i++
      while (i < lines.length && !lines[i].startsWith('```')) code.push(lines[i++])
      i++
      blocks.push(
        <pre key={key} className="pl-pre">
          {code.join('\n')}
        </pre>,
      )
      continue
    }
    const h = line.match(/^(#{1,6})\s+(.*?)\s*#*\s*$/)
    if (h) {
      const level = Math.min(h[1].length + 1, 6)
      const Tag = `h${level}` as 'h2'
      blocks.push(
        <Tag key={key} className={`pl-h pl-h${h[1].length}`}>
          {ink(h[2], key)}
        </Tag>,
      )
      i++
      continue
    }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) {
      blocks.push(<hr key={key} className="pl-hr" />)
      i++
      continue
    }
    if (line.trim().startsWith('|') && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1])) {
      const head = cells(line)
      const rows: string[][] = []
      i += 2
      while (i < lines.length && lines[i].trim().startsWith('|')) rows.push(cells(lines[i++]))
      blocks.push(
        <div key={key} className="pl-table-wrap">
          <table className="pl-table">
            <thead>
              <tr>
                {head.map((c, ci) => (
                  <th key={ci}>{ink(c, `${key}h${ci}`)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, ri) => (
                <tr key={ri}>
                  {r.map((c, ci) => (
                    <td key={ci}>{ink(c, `${key}r${ri}c${ci}`)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      )
      continue
    }
    if (line.startsWith('>')) {
      const q: string[] = []
      while (i < lines.length && lines[i].startsWith('>')) q.push(lines[i++].replace(/^>\s?/, ''))
      blocks.push(
        <blockquote key={key} className="pl-quote">
          {ink(q.join(' '), key)}
        </blockquote>,
      )
      continue
    }
    if (LIST_RE.test(line)) {
      const ordered = /^\s*\d/.test(line)
      const items: ReactNode[] = []
      while (i < lines.length && LIST_RE.test(lines[i])) {
        const m = lines[i].match(LIST_RE)
        const depth = Math.min(Math.floor((m?.[1].length || 0) / 2), 3)
        const txt = m?.[3] || ''
        const box = txt.match(/^\[( |x|X)\]\s+(.*)$/)
        const k = `${key}l${items.length}`
        items.push(
          <li key={items.length} className={depth ? `pl-d${depth}` : undefined}>
            {box ? (
              <>
                <span className={`pl-box${box[1].trim() ? ' is-done' : ''}`} role="img" aria-label={box[1].trim() ? 'Done' : 'Open'} />
                {ink(box[2], k)}
              </>
            ) : (
              ink(txt, k)
            )}
          </li>,
        )
        i++
      }
      blocks.push(
        ordered ? (
          <ol key={key} className="pl-list">
            {items}
          </ol>
        ) : (
          <ul key={key} className="pl-list">
            {items}
          </ul>
        ),
      )
      continue
    }
    const para: string[] = [line]
    i++
    while (i < lines.length && !isBreak(lines[i])) para.push(lines[i++])
    blocks.push(
      <p key={key} className="pl-p">
        {ink(para.join(' '), key)}
      </p>,
    )
  }
  return <div className="pl-md">{blocks}</div>
}
