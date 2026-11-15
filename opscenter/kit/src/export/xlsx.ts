/* Hands data to a spreadsheet as a real workbook (the `export` entry): one tab per table, a bold frozen header,
   sized columns, numbers that stay numbers, and optionally an Excel table (filter buttons, banding) on a rows tab.
   Text is written as inline strings, never as formulas, so a value starting with = + - @ cannot run.
   No pivot tables: a hand-written pivot part can pass the Open XML schema check and still crash the spreadsheet app
   on open, so none ships until a generated file has been opened in the app itself on Mac and Windows without a
   repair prompt. The same bar applies to any new hand-written workbook part. */

import { datedName, saveBlob } from './download';
import { zipStore } from './zip';
import type { Zipper } from './zip';

export interface Sheet {
  name: string;
  rows: readonly (readonly unknown[])[];
  /** The first row is a header (bold, frozen). Default true. */
  header?: boolean | undefined;
  /** Make it an Excel table. Needs a header row and at least one data row. */
  table?: boolean | undefined;
}

export interface XlsxOptions {
  /** Replaces the store-only zip (for example with a compressing one). Gets the files by path. */
  zip?: Zipper | undefined;
}

const NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main';
const NS_R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships';
const HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>';

const esc = (s: string) =>
  // XML 1.0 forbids the control characters stripped here.
  // eslint-disable-next-line no-control-regex
  s.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, '').replace(/[&<>"]/g, (c) => `&#${c.charCodeAt(0)};`);

/** Column letters: 0 is A, 25 is Z, 26 is AA. */
export function colName(i: number): string {
  let n = i + 1;
  let out = '';
  while (n > 0) {
    out = String.fromCharCode(65 + ((n - 1) % 26)) + out;
    n = Math.floor((n - 1) / 26);
  }
  return out;
}

/** Tab names a spreadsheet accepts: at most 31 characters, none of []:*?/\, unique ignoring case. */
export function sheetNames(raw: readonly string[]): string[] {
  const used = new Set<string>();
  return raw.map((r, i) => {
    const base = (r.replace(/[[\]:*?/\\]/g, ' ').replace(/\s+/g, ' ').trim() || `Sheet ${i + 1}`).slice(0, 31);
    let name = base;
    for (let n = 2; used.has(name.toLowerCase()); n++) name = `${base.slice(0, 31 - String(n).length - 1)} ${n}`;
    used.add(name.toLowerCase());
    return name;
  });
}

/** Header cells of a table must be unique text. */
function tableHeader(row: readonly unknown[]): string[] {
  const seen = new Set<string>();
  return row.map((v, i) => {
    const base = String(v ?? '').trim() || `Column ${i + 1}`;
    let n = base;
    for (let k = 2; seen.has(n.toLowerCase()); k++) n = `${base} ${k}`;
    seen.add(n.toLowerCase());
    return n;
  });
}

const wantsTable = (s: Sheet) => s.table === true && s.header !== false && s.rows.length >= 2 && (s.rows[0]?.length ?? 0) >= 1;

function sheetXml(s: Sheet, tableRid?: string): string {
  const header = s.header !== false;
  const widths: number[] = [];
  const rowsXml = s.rows
    .map((row, r) => {
      const cells = row
        .map((v, c) => {
          if (v === null || v === undefined || v === '') return '';
          const ref = `${colName(c)}${r + 1}`;
          const text = String(v);
          widths[c] = Math.max(widths[c] ?? 8, Math.min(60, text.length + 2));
          const style = header && r === 0 ? ' s="1"' : '';
          if (typeof v === 'number' && Number.isFinite(v)) return `<c r="${ref}"${style}><v>${v}</v></c>`;
          if (typeof v === 'boolean') return `<c r="${ref}" t="b"${style}><v>${v ? 1 : 0}</v></c>`;
          return `<c r="${ref}" t="inlineStr"${style}><is><t xml:space="preserve">${esc(text)}</t></is></c>`;
        })
        .join('');
      return `<row r="${r + 1}">${cells}</row>`;
    })
    .join('');
  const cols = widths.length ? `<cols>${widths.map((w, i) => `<col min="${i + 1}" max="${i + 1}" width="${w}" customWidth="1"/>`).join('')}</cols>` : '';
  const pane = header && s.rows.length > 1 ? '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>' : '';
  const parts = tableRid ? `<tableParts count="1"><tablePart r:id="${tableRid}"/></tableParts>` : '';
  return `${HEAD}<worksheet xmlns="${NS}" xmlns:r="${NS_R}">${pane}${cols}<sheetData>${rowsXml}</sheetData>${parts}</worksheet>`;
}

const REL = 'http://schemas.openxmlformats.org/package/2006/relationships';
const CT_SHEET = 'application/vnd.openxmlformats-officedocument.spreadsheetml';

/** The workbook as bytes. */
export function buildXlsx(sheets: readonly Sheet[], options: XlsxOptions = {}): Uint8Array {
  const enc = new TextEncoder();
  const list: Sheet[] = (sheets.length ? [...sheets] : [{ name: 'Data', rows: [] }]).map((s) => (wantsTable(s) ? { ...s, rows: [tableHeader(s.rows[0] ?? []), ...s.rows.slice(1)] } : s));
  const names = sheetNames(list.map((s) => s.name));
  const files: Record<string, Uint8Array> = {
    '[Content_Types].xml': enc.encode(
      `${HEAD}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="${CT_SHEET}.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="${CT_SHEET}.styles+xml"/>${list
        .map((s, i) => (wantsTable(s) ? `<Override PartName="/xl/tables/table${i + 1}.xml" ContentType="${CT_SHEET}.table+xml"/>` : ''))
        .join('')}${list.map((_, i) => `<Override PartName="/xl/worksheets/sheet${i + 1}.xml" ContentType="${CT_SHEET}.worksheet+xml"/>`).join('')}</Types>`,
    ),
    '_rels/.rels': enc.encode(`${HEAD}<Relationships xmlns="${REL}"><Relationship Id="rId1" Type="${NS_R}/officeDocument" Target="xl/workbook.xml"/></Relationships>`),
    'xl/workbook.xml': enc.encode(`${HEAD}<workbook xmlns="${NS}" xmlns:r="${NS_R}"><sheets>${names.map((n, i) => `<sheet name="${esc(n)}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`).join('')}</sheets></workbook>`),
    'xl/_rels/workbook.xml.rels': enc.encode(
      `${HEAD}<Relationships xmlns="${REL}">${list.map((_, i) => `<Relationship Id="rId${i + 1}" Type="${NS_R}/worksheet" Target="worksheets/sheet${i + 1}.xml"/>`).join('')}<Relationship Id="rId${list.length + 1}" Type="${NS_R}/styles" Target="styles.xml"/></Relationships>`,
    ),
    'xl/styles.xml': enc.encode(
      `${HEAD}<styleSheet xmlns="${NS}"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>`,
    ),
  };
  list.forEach((s, i) => {
    const n = i + 1;
    if (wantsTable(s)) {
      const cols = (s.rows[0] ?? []).map(String);
      const ref = `A1:${colName(cols.length - 1)}${s.rows.length}`;
      files[`xl/tables/table${n}.xml`] = enc.encode(
        `${HEAD}<table xmlns="${NS}" id="${n}" name="Data${n}" displayName="Data${n}" ref="${ref}" totalsRowShown="0"><autoFilter ref="${ref}"/><tableColumns count="${cols.length}">${cols.map((c, k) => `<tableColumn id="${k + 1}" name="${esc(c)}"/>`).join('')}</tableColumns><tableStyleInfo name="TableStyleMedium2" showFirstColumn="0" showLastColumn="0" showRowStripes="1" showColumnStripes="0"/></table>`,
      );
      files[`xl/worksheets/_rels/sheet${n}.xml.rels`] = enc.encode(`${HEAD}<Relationships xmlns="${REL}"><Relationship Id="rId1" Type="${NS_R}/table" Target="../tables/table${n}.xml"/></Relationships>`);
    }
    files[`xl/worksheets/sheet${n}.xml`] = enc.encode(sheetXml(s, wantsTable(s) ? 'rId1' : undefined));
  });
  return (options.zip ?? zipStore)(files);
}

/** Hands the workbook to the browser as a dated `.xlsx`. */
export function downloadXlsx(name: string, sheets: readonly Sheet[], options: XlsxOptions & { now?: Date | undefined } = {}): void {
  const bytes = buildXlsx(sheets, options);
  saveBlob(new Blob([bytes as BlobPart], { type: `${CT_SHEET}.sheet` }), datedName(name, 'xlsx', options.now));
}
