/* CSV cells for spreadsheet exports (the `export` entry). A text value that starts with = + - @ tab or CR is read
   as a formula by Excel and Sheets, so it gets a leading apostrophe and shows as plain text. Every cell is quoted
   and inner quotes are doubled. A real number stays numeric (-25.8 is not a formula); only text is guarded, so the
   text "-25.8" is. All CSV downloads go through `toCsv` and `downloadCsv`, so no export skips the guard. */

import { datedName, saveBlob } from './download';

export function csvCell(value: unknown): string {
  let s = String(value ?? '');
  if (typeof value !== 'number' && /^[=+\-@\t\r]/.test(s)) s = `'${s}`;
  return `"${s.replace(/"/g, '""')}"`;
}

export function toCsv(rows: readonly (readonly unknown[])[]): string {
  return rows.map((r) => r.map(csvCell).join(',')).join('\n');
}

/** Hands rows to the browser as a dated `.csv`: formula safe, with a UTF-8 byte order mark so Excel reads accents. */
export function downloadCsv(name: string, rows: readonly (readonly unknown[])[], now: Date = new Date()): void {
  saveBlob(new Blob([`\uFEFF${toCsv(rows)}`], { type: 'text/csv;charset=utf-8' }), datedName(name, 'csv', now));
}
