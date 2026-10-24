/* Markdown reader: a small, dependency-free renderer for trusted-looking but untrusted text such as a
   plan, a note or a release body. Safe by default: it builds React elements only (never an HTML
   string, never dangerouslySetInnerHTML), so raw HTML in the source shows as plain text. A link is an
   anchor only for http, https, mailto and tel. A relative document link calls `onLink` (the host opens
   it in place) and renders as plain text when the host gave none. Every other scheme (javascript,
   data, vbscript, file) renders as its label with no href. Images are not rendered. Supports
   headings, paragraphs, bold, italic, code, fenced code, quotes, rules, ordered and bullet lists with
   task checkboxes, and tables. */

import type { ReactNode } from 'react';
import { Fragment } from 'react';
import { cx } from '../lib/env';
import { safeHref } from '../lib/url';

export interface MarkdownProps {
  /** The markdown source. */
  body: string;
  /** Called with a relative link target (fragment removed) when the reader clicks it. */
  onLink?: ((href: string) => void) | undefined;
  /** Added to the source heading level so the page heading stays the only h1. Default 1 (# becomes h2). */
  headingOffset?: number | undefined;
  className?: string | undefined;
}

const EXTERNAL = /^(https?:|mailto:|tel:)/i;
const SCHEME = /^[a-z][a-z0-9+.-]*:/i;
// C0 and C1 controls: a browser drops them inside a URL, so "java\tscript:" is a script URL.
// eslint-disable-next-line no-control-regex
const CONTROL = /[\u0000-\u001f\u007f-\u009f]/g;

/** What a link target is: an external anchor, a relative document, or not allowed. */
export function classifyLink(raw: string): { kind: 'external'; href: string } | { kind: 'relative'; href: string } | { kind: 'blocked' } {
  const clean = raw.replace(CONTROL, '').trim();
  if (!clean) return { kind: 'blocked' };
  if (EXTERNAL.test(clean)) {
    const href = safeHref(clean);
    return href ? { kind: 'external', href } : { kind: 'blocked' };
  }
  // Any other scheme, and a protocol-relative URL (//host), is blocked.
  if (SCHEME.test(clean) || clean.startsWith('//') || clean.startsWith('\\')) return { kind: 'blocked' };
  return { kind: 'relative', href: clean };
}

const INLINE = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*\s][^*]*\*|\[[^\]]+\]\((?:[^()\s]|\([^()\s]*\))+\)|https?:\/\/[^\s<>)]+)/g;

function inline(text: string, keyBase: string, onLink?: (href: string) => void): ReactNode[] {
  const out: ReactNode[] = [];
  const re = new RegExp(INLINE.source, 'g');
  let last = 0;
  let n = 0;
  for (let m = re.exec(text); m !== null; m = re.exec(text)) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const token = m[0];
    const key = `${keyBase}-${n++}`;
    if (token.startsWith('`')) out.push(<code key={key}>{token.slice(1, -1)}</code>);
    else if (token.startsWith('**')) out.push(<strong key={key}>{token.slice(2, -2)}</strong>);
    else if (token.startsWith('*')) out.push(<em key={key}>{token.slice(1, -1)}</em>);
    else if (token.startsWith('[')) {
      const parts = /^\[([^\]]+)\]\(((?:[^()\s]|\([^()\s]*\))+)\)$/.exec(token);
      const label = parts?.[1] ?? token;
      const target = classifyLink(parts?.[2] ?? '');
      if (target.kind === 'external')
        out.push(
          <a key={key} className="md-link" href={target.href} target="_blank" rel="noopener noreferrer">
            {label}
          </a>,
        );
      else if (target.kind === 'relative' && onLink)
        out.push(
          <button key={key} type="button" className="md-link md-rel" onClick={() => onLink(target.href.split('#')[0] ?? '')}>
            {label}
          </button>,
        );
      else out.push(<Fragment key={key}>{label}</Fragment>);
    } else {
      const target = classifyLink(token);
      if (target.kind === 'external')
        out.push(
          <a key={key} className="md-link" href={target.href} target="_blank" rel="noopener noreferrer">
            {token}
          </a>,
        );
      else out.push(<Fragment key={key}>{token}</Fragment>);
    }
    last = m.index + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

const LIST_RE = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;
const TABLE_SEP = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;
const RULE = /^\s*(-{3,}|\*{3,})\s*$/;

function cells(row: string): string[] {
  return row
    .trim()
    .replace(/^\||\|$/g, '')
    .split('|')
    .map((c) => c.trim());
}

/** Renders markdown source as safe React elements. */
export function Markdown({ body, onLink, headingOffset = 1, className }: MarkdownProps) {
  const lines = String(body ?? '')
    .replace(/\r\n?/g, '\n')
    .split('\n');
  const blocks: ReactNode[] = [];
  let i = 0;
  let n = 0;
  const startsBlock = (l: string) => !l.trim() || /^(#{1,6}\s|```|>|\s*\|)/.test(l) || LIST_RE.test(l) || RULE.test(l);
  const ink = (text: string, key: string) => inline(text, key, onLink);
  while (i < lines.length) {
    const line = lines[i] ?? '';
    const key = `b${n++}`;
    if (!line.trim()) {
      i++;
      continue;
    }
    if (line.startsWith('```')) {
      const code: string[] = [];
      i++;
      while (i < lines.length && !(lines[i] ?? '').startsWith('```')) code.push(lines[i++] ?? '');
      i++;
      // A scrollable region has to be reachable by keyboard.
      blocks.push(
        <pre key={key} className="md-pre" tabIndex={0}>
          <code>{code.join('\n')}</code>
        </pre>,
      );
      continue;
    }
    const heading = /^(#{1,6})\s+(.*?)\s*#*\s*$/.exec(line);
    if (heading) {
      const source = (heading[1] ?? '#').length;
      const level = Math.min(Math.max(source + headingOffset, 1), 6);
      const Tag = `h${level}` as 'h2';
      blocks.push(
        <Tag key={key} className="md-h" data-level={source}>
          {ink(heading[2] ?? '', key)}
        </Tag>,
      );
      i++;
      continue;
    }
    if (RULE.test(line)) {
      blocks.push(<hr key={key} className="md-hr" />);
      i++;
      continue;
    }
    if (line.trim().startsWith('|') && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1] ?? '')) {
      const head = cells(line);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && (lines[i] ?? '').trim().startsWith('|')) rows.push(cells(lines[i++] ?? ''));
      blocks.push(
        <div key={key} className="md-table-wrap" role="region" aria-label="Table" tabIndex={0}>
          <table className="md-table">
            <thead>
              <tr>
                {head.map((c, ci) => (
                  <th key={ci} scope="col">
                    {ink(c, `${key}h${ci}`)}
                  </th>
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
      );
      continue;
    }
    if (line.startsWith('>')) {
      const quote: string[] = [];
      while (i < lines.length && (lines[i] ?? '').startsWith('>')) quote.push((lines[i++] ?? '').replace(/^>\s?/, ''));
      blocks.push(
        <blockquote key={key} className="md-quote">
          {ink(quote.join(' '), key)}
        </blockquote>,
      );
      continue;
    }
    if (LIST_RE.test(line)) {
      const ordered = /^\s*\d/.test(line);
      const items: ReactNode[] = [];
      while (i < lines.length && LIST_RE.test(lines[i] ?? '') && /^\s*\d/.test(lines[i] ?? '') === ordered) {
        const m = LIST_RE.exec(lines[i] ?? '');
        const depth = Math.min(Math.floor((m?.[1]?.length ?? 0) / 2), 3);
        const text = m?.[3] ?? '';
        const box = /^\[( |x|X)\]\s+(.*)$/.exec(text);
        const itemKey = `${key}l${items.length}`;
        const done = Boolean(box?.[1]?.trim());
        items.push(
          <li key={items.length} data-depth={depth || undefined}>
            {box ? (
              <>
                <span className={cx('md-box', done && 'is-done')} role="img" aria-label={done ? 'Done' : 'Open'} />
                {ink(box[2] ?? '', itemKey)}
              </>
            ) : (
              ink(text, itemKey)
            )}
          </li>,
        );
        i++;
      }
      blocks.push(
        ordered ? (
          <ol key={key} className="md-list">
            {items}
          </ol>
        ) : (
          <ul key={key} className="md-list">
            {items}
          </ul>
        ),
      );
      continue;
    }
    const para: string[] = [line];
    i++;
    while (i < lines.length && !startsBlock(lines[i] ?? '')) para.push(lines[i++] ?? '');
    blocks.push(
      <p key={key} className="md-p">
        {ink(para.join(' '), key)}
      </p>,
    );
  }
  return <div className={cx('md', className)}>{blocks}</div>;
}
