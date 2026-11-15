/* The `export` entry: formula-safe CSV, the store-only zip, and the workbook writer. */
import { crc32 as nodeCrc32, inflateRawSync } from 'node:zlib';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import { buildXlsx, colName, crc32, csvCell, datedName, downloadCsv, downloadXlsx, sheetNames, toCsv, zipStore } from '../src/export';

/** Reads every entry of a zip (stored or deflated) by its central directory. */
function unzip(bytes: Uint8Array): Record<string, string> {
  const v = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let end = bytes.length - 22;
  while (v.getUint32(end, true) !== 0x06054b50) end--;
  const count = v.getUint16(end + 10, true);
  let p = v.getUint32(end + 16, true);
  const out: Record<string, string> = {};
  for (let i = 0; i < count; i++) {
    const method = v.getUint16(p + 10, true);
    const crc = v.getUint32(p + 16, true);
    const size = v.getUint32(p + 20, true);
    const nameLen = v.getUint16(p + 28, true);
    const extra = v.getUint16(p + 30, true);
    const comment = v.getUint16(p + 32, true);
    const local = v.getUint32(p + 42, true);
    const name = new TextDecoder().decode(bytes.subarray(p + 46, p + 46 + nameLen));
    const dataAt = local + 30 + v.getUint16(local + 26, true) + v.getUint16(local + 28, true);
    const raw = bytes.subarray(dataAt, dataAt + size);
    const data = method === 0 ? raw : new Uint8Array(inflateRawSync(raw));
    expect(nodeCrc32(data)).toBe(crc);
    out[name] = new TextDecoder().decode(data);
    p += 46 + nameLen + extra + comment;
  }
  return out;
}

describe('csv cells', () => {
  it('quotes values and doubles inner quotes', () => {
    expect(csvCell('say "hi"')).toBe('"say ""hi"""');
  });
  it('turns missing values into empty cells', () => {
    expect(csvCell(null)).toBe('""');
    expect(csvCell(undefined)).toBe('""');
  });
  it.each(['=1+1', '+SUM(A1)', '-2+3', '@cmd', '\tx', '\rx'])('neutralises a leading formula character in %j', (v) => {
    expect(csvCell(v).startsWith(`"'`)).toBe(true);
  });
  it('leaves ordinary text, dates and numbers alone', () => {
    expect(csvCell('2026-10-28')).toBe('"2026-10-28"');
    expect(csvCell(42)).toBe('"42"');
    expect(csvCell('a=b')).toBe('"a=b"');
  });
  it('keeps real negative numbers numeric but still guards negative-looking text', () => {
    expect(csvCell(-25.8)).toBe('"-25.8"');
    expect(csvCell('-25.8')).toBe('"\'-25.8"');
  });
  it('joins rows and cells', () => {
    expect(toCsv([['a', 'b'], ['=x', 'c']])).toBe('"a","b"\n"\'=x","c"');
  });
});

describe('downloads', () => {
  it('names a file with a safe base and the local date', () => {
    const now = new Date(2026, 10, 7, 23, 59);
    expect(datedName('Q4 report / final', 'csv', now)).toBe('Q4-report-final-2026-11-07.csv');
    expect(datedName('', 'xlsx', now)).toBe('export-2026-11-07.xlsx');
  });

  it('offers a CSV with a byte order mark and the guard applied, and an xlsx, as dated downloads', async () => {
    let blob: Blob | undefined;
    const names: string[] = [];
    URL.createObjectURL = vi.fn((b: Blob | MediaSource) => ((blob = b as Blob), 'blob:x'));
    URL.revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      names.push(this.download);
    });
    downloadCsv('rows', [['a'], ['=1+1']], new Date(2026, 0, 2));
    const bytes = new Uint8Array((await blob?.arrayBuffer()) ?? new ArrayBuffer(0));
    expect([...bytes.subarray(0, 3)]).toEqual([0xef, 0xbb, 0xbf]);
    expect(await blob?.text()).toBe('"a"\n"\'=1+1"');
    downloadXlsx('book', [{ name: 'S', rows: [['x']] }], { now: new Date(2026, 0, 2) });
    expect(blob?.type).toContain('spreadsheetml.sheet');
    expect(names).toEqual(['rows-2026-01-02.csv', 'book-2026-01-02.xlsx']);
    click.mockRestore();
  });
});

describe('store-only zip', () => {
  it('writes entries whose CRC-32 matches the standard, readable by a normal zip tool', () => {
    expect(crc32(new TextEncoder().encode('123456789'))).toBe(0xcbf43926);
    expect(crc32(new Uint8Array())).toBe(0);
    const files = { 'a.txt': new TextEncoder().encode('hello'), 'dir/b.xml': new TextEncoder().encode('<x>\u00e9</x>') };
    const bytes = zipStore(files);
    expect(unzip(bytes)).toEqual({ 'a.txt': 'hello', 'dir/b.xml': '<x>\u00e9</x>' });
    const dir = mkdtempSync(join(tmpdir(), 'kit-zip-'));
    writeFileSync(join(dir, 'a.zip'), bytes);
    const test = spawnSync('python3', ['-c', 'import zipfile,sys; z=zipfile.ZipFile(sys.argv[1]); assert z.testzip() is None; print(sorted(z.namelist()))', join(dir, 'a.zip')]);
    expect(test.status).toBe(0);
    expect(String(test.stdout)).toContain("'a.txt'");
  });
});

describe('workbook', () => {
  it('writes one worksheet per tab with numbers numeric and text inert', () => {
    const f = unzip(buildXlsx([
      { name: 'Summary', rows: [['Measure', 'Value'], ['Resets', 21424], ['=1+1', '@x & <y>'], ['ok', true]] },
      { name: 'By version', rows: [['Version', 'Rows'], ['24.2', 69]] },
    ]));
    expect(Object.keys(f)).toEqual(expect.arrayContaining(['[Content_Types].xml', 'xl/workbook.xml', 'xl/worksheets/sheet1.xml', 'xl/worksheets/sheet2.xml', 'xl/styles.xml', '_rels/.rels']));
    expect(f['xl/workbook.xml']).toContain('name="By version"');
    const s1 = f['xl/worksheets/sheet1.xml'] as string;
    expect(s1).toContain('<c r="B2"><v>21424</v></c>');
    expect(s1).toContain('t="inlineStr"');
    expect(s1).toContain('t="b"');
    expect(s1).not.toContain('<f>');
    expect(s1).toContain('@x &#38; &#60;y&#62;');
    expect(s1).toContain('state="frozen"');
    expect(s1).toContain('s="1"');
  });

  it('makes a data tab an Excel table with unique header names', () => {
    const f = unzip(buildXlsx([{ name: 'Rows', table: true, rows: [['A', 'A', ''], [1, 2, 3]] }]));
    const t = f['xl/tables/table1.xml'] as string;
    expect(t).toContain('ref="A1:C2"');
    expect(t).toContain('name="A 2"');
    expect(t).toContain('name="Column 3"');
    expect(f['xl/worksheets/sheet1.xml']).toContain('<tablePart r:id="rId1"/>');
    expect(f['[Content_Types].xml']).toContain('/xl/tables/table1.xml');
    expect(f['xl/worksheets/_rels/sheet1.xml.rels']).toContain('../tables/table1.xml');
  });

  it('writes no table for a one row tab or a headerless tab, and never a pivot part', () => {
    const f = unzip(buildXlsx([{ name: 'A', table: true, rows: [['only']] }, { name: 'B', table: true, header: false, rows: [['x'], ['y']] }]));
    expect(Object.keys(f).some((k) => k.includes('table') || k.includes('pivot'))).toBe(false);
  });

  it('keeps tab names legal and unique, and names columns past Z', () => {
    expect(sheetNames(['A/B:C', 'a/b:c', 'x'.repeat(40)])).toEqual(['A B C', 'a b c 2', 'x'.repeat(31)]);
    expect([colName(0), colName(25), colName(26), colName(701)]).toEqual(['A', 'Z', 'AA', 'ZZ']);
  });

  it('writes an empty book as one empty Data tab, and takes a replacement zipper', () => {
    expect(unzip(buildXlsx([]))['xl/workbook.xml']).toContain('name="Data"');
    const seen: string[][] = [];
    const out = buildXlsx([{ name: 'S', rows: [['x']] }], { zip: (files) => (seen.push(Object.keys(files)), new Uint8Array([1])) });
    expect(out).toEqual(new Uint8Array([1]));
    expect(seen[0]).toContain('xl/workbook.xml');
  });

  it('passes the workbook through a real parser', () => {
    const dir = mkdtempSync(join(tmpdir(), 'kit-xlsx-'));
    writeFileSync(join(dir, 'b.xlsx'), buildXlsx([{ name: 'Rows', table: true, rows: [['a', 'b'], ['x', 1]] }]));
    const check = spawnSync('python3', ['-c', 'import zipfile,sys,xml.dom.minidom as m; z=zipfile.ZipFile(sys.argv[1]); [m.parseString(z.read(n)) for n in z.namelist()]; print("ok")', join(dir, 'b.xlsx')]);
    expect(String(check.stdout).trim()).toBe('ok');
  });
});
