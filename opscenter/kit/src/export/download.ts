/* Saving a file in the browser, and the dated file name every export uses. */

/** A safe base name (letters, digits, dot, dash, underscore) and the local date: `report-2026-11-07.csv`. */
export function datedName(name: string, ext: string, now: Date = new Date()): string {
  const safe = (name || 'export').replace(/[^\w.-]+/g, '-').replace(/^-+|-+$/g, '') || 'export';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${safe}-${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}.${ext}`;
}

/** Offers a blob to the user as a download. */
export function saveBlob(blob: Blob, filename: string): void {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}
