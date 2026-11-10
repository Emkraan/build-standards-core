/* TextDiff: a read-only, line-level diff of two texts, for example a saved snapshot of a prompt,
   template or config against the current version. Removed lines sit on the danger tint with a
   leading "-", added lines on the success tint with a leading "+", unchanged lines muted. The
   markers are real text, so the diff reads correctly without colour and to a screen reader.
   diffLines is the pure core (a longest common subsequence walk), exported so callers can count
   or summarise changes without rendering. The lineNumbers option adds two gutters, the line number
   in the before text and in the after text. They are decoration for the eye (hidden from assistive
   technology, not selected on copy), because the markers and the text already carry the meaning. */

import type { CSSProperties, ReactNode } from 'react';
import { cx } from '../lib/env';

export type DiffLineKind = 'same' | 'add' | 'del';

export interface DiffLine {
  kind: DiffLineKind;
  text: string;
  /** 1-based line number in the before text, null for an added line. */
  oldNumber: number | null;
  /** 1-based line number in the after text, null for a removed line. */
  newNumber: number | null;
}

/** Split on any newline style. An empty text is zero lines, not one blank one. */
function toLines(text: string): string[] {
  return text === '' ? [] : text.replace(/\r\n?/g, '\n').split('\n');
}

/** Line diff of before to after, in reading order. */
export function diffLines(before: string, after: string): DiffLine[] {
  const a = toLines(before);
  const b = toLines(after);
  const n = a.length;
  const m = b.length;
  const lcs: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    const row = lcs[i] as number[];
    const next = lcs[i + 1] as number[];
    for (let j = m - 1; j >= 0; j--) {
      row[j] = a[i] === b[j] ? (next[j + 1] as number) + 1 : Math.max(next[j] as number, row[j + 1] as number);
    }
  }
  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      out.push({ kind: 'same', text: a[i] as string, oldNumber: i + 1, newNumber: j + 1 });
      i++;
      j++;
    } else if ((lcs[i + 1]?.[j] ?? 0) >= (lcs[i]?.[j + 1] ?? 0)) {
      out.push({ kind: 'del', text: a[i] as string, oldNumber: i + 1, newNumber: null });
      i++;
    } else {
      out.push({ kind: 'add', text: b[j] as string, oldNumber: null, newNumber: j + 1 });
      j++;
    }
  }
  while (i < n) out.push({ kind: 'del', text: a[i] as string, oldNumber: i++ + 1, newNumber: null });
  while (j < m) out.push({ kind: 'add', text: b[j] as string, oldNumber: null, newNumber: j++ + 1 });
  return out;
}

export interface TextDiffProps {
  before: string;
  after: string;
  /** Legend for the removed side, for example "When you customised it". */
  beforeLabel?: ReactNode;
  /** Legend for the added side, for example "Shipped now". */
  afterLabel?: ReactNode;
  /** Shown instead of the diff when the two texts are identical. */
  emptyMessage?: ReactNode;
  /** Show an old and a new line number gutter. Off by default. */
  lineNumbers?: boolean;
  className?: string | undefined;
}

const MARK: Record<DiffLineKind, string> = { same: ' ', add: '+', del: '-' };

export function TextDiff({ before, after, beforeLabel = 'Before', afterLabel = 'After', emptyMessage = 'No differences.', lineNumbers = false, className }: TextDiffProps) {
  const lines = diffLines(before, after);
  const changed = lines.some((l) => l.kind !== 'same');
  // The gutter is as wide as the largest number on either side, so the columns never shift.
  const digits = String(Math.max(1, ...lines.map((l) => Math.max(l.oldNumber ?? 0, l.newNumber ?? 0)))).length;
  const bodyStyle = lineNumbers ? ({ '--diff-gutter-digits': digits } as CSSProperties) : undefined;
  return (
    <div className={cx('text-diff', className)}>
      <div className="text-diff-legend">
        <span className="text-diff-key" data-kind="del">
          - {beforeLabel}
        </span>
        <span className="text-diff-key" data-kind="add">
          + {afterLabel}
        </span>
      </div>
      {changed ? (
        <pre className="text-diff-body" data-line-numbers={lineNumbers ? 'true' : undefined} style={bodyStyle}>
          {lines.map((l, idx) => (
            // Lines have no identity beyond their position in this diff.
            <span key={idx} className="text-diff-line" data-kind={l.kind}>
              {lineNumbers ? (
                <>
                  <span className="text-diff-num" data-side="old" aria-hidden="true">
                    {l.oldNumber ?? ''}
                  </span>
                  <span className="text-diff-num" data-side="new" aria-hidden="true">
                    {l.newNumber ?? ''}
                  </span>
                </>
              ) : null}
              <span className="text-diff-mark">{MARK[l.kind]}</span>
              {l.text}
              {'\n'}
            </span>
          ))}
        </pre>
      ) : (
        <p className="text-diff-empty">{emptyMessage}</p>
      )}
    </div>
  );
}
