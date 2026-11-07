"""
export_xlsx.py
Purpose: One spreadsheet workbook for a dashboard (reports module R5), written with the standard library only (zipfile and XML).
         The workbook has a Summary tab and one tab per panel; each panel tab is a real table (an Excel table with a header row, so
         it filters and sorts), not loose cells. Text is always written as text: a value such as `=1+1` is a string cell and never a
         formula, so opening the file runs nothing. Pre-built pivot tables are OFF (`PREBUILT_PIVOTS = False`): hand-written pivot parts
         pass the Open XML schema check but crash the spreadsheet application for Mac on open, so no hand-written workbook part
         beyond the ones here ships until a generated file has been opened in the application itself, on Mac and Windows, without a
         repair prompt or a crash. CSV downloads stay available (export_csv.py).
Date:    2026-11-07

API:     build_workbook(summary, panels) -> bytes     summary: rows (lists) for the Summary tab; panels: [{"name", "header", "rows"}]
         write_workbook(path, summary, panels)
         sheet names are made valid (31 characters, none of []:*?/\\, unique); table names are unique identifiers.
Cells: str (inline string), int and float (numbers), bool, None (empty). Control characters invalid in XML are removed. The output
       is deterministic (fixed zip timestamps), so the same input gives the same bytes.
"""

from __future__ import annotations

import io
import re
import zipfile
from xml.sax.saxutils import escape

PREBUILT_PIVOTS = False  # stays False until a generated workbook was opened on Mac and Windows without a repair prompt or a crash

MAX_ROWS = 1_048_575  # the sheet limit, minus the header row
_INVALID_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")
_BAD_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")
_ZIP_DATE = (2026, 1, 1, 0, 0, 0)
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def col(n):
    """The column letters of a 1-based column number (1 is A, 27 is AA)."""
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _text(s):
    return escape(_INVALID_XML.sub("", str(s)))


def sheet_name(name, taken):
    """A valid, unique sheet name: bad characters become a space, at most 31 characters, never empty, case-insensitively unique."""
    base = _BAD_SHEET_CHARS.sub(" ", str(name)).strip().strip("'") or "Sheet"
    base = base[:31]
    out, i = base, 2
    while out.lower() in taken:
        suffix = f" ({i})"
        out = base[: 31 - len(suffix)] + suffix
        i += 1
    taken.add(out.lower())
    return out


def table_name(name, taken):
    """A valid, unique table name: letters, digits and underscores, starting with a letter."""
    base = re.sub(r"[^A-Za-z0-9_]", "_", str(name)).strip("_") or "Table"
    if not base[0].isalpha():
        base = "T_" + base
    out, i = base, 2
    while out.lower() in taken:
        out = f"{base}_{i}"
        i += 1
    taken.add(out.lower())
    return out


def _cell(ref, value, style=None):
    s = f' s="{style}"' if style else ""
    if value is None:
        return f'<c r="{ref}"{s}/>'
    if isinstance(value, bool):
        return f'<c r="{ref}"{s} t="b"><v>{int(value)}</v></c>'
    if isinstance(value, (int, float)):
        return f'<c r="{ref}"{s}><v>{value!r}</v></c>'
    return f'<c r="{ref}"{s} t="inlineStr"><is><t xml:space="preserve">{_text(value)}</t></is></c>'


def _sheet_xml(rows, header_style=None, table_rid=None, width=None):
    out = [
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<worksheet xmlns="{NS}" xmlns:r="{REL}"><sheetData>'
    ]
    for r, row in enumerate(rows, 1):
        cells = "".join(
            _cell(f"{col(c)}{r}", v, header_style if r == 1 and header_style else None)
            for c, v in enumerate(row, 1)
        )
        out.append(f'<row r="{r}">{cells}</row>')
    out.append("</sheetData>")
    if table_rid:
        out.append(f'<tableParts count="1"><tablePart r:id="{table_rid}"/></tableParts>')
    out.append("</worksheet>")
    return "".join(out)


def _table_xml(tid, name, header, nrows):
    ncols = len(header)
    ref = f"A1:{col(ncols)}{nrows + 1}"
    cols = "".join(f'<tableColumn id="{i}" name="{_text(h)}"/>' for i, h in enumerate(header, 1))
    return (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<table xmlns="{NS}" id="{tid}" name="{name}" displayName="{name}" ref="{ref}" totalsRowShown="0">'
        f'<autoFilter ref="{ref}"/><tableColumns count="{ncols}">{cols}</tableColumns>'
        '<tableStyleInfo name="TableStyleMedium2" showFirstColumn="0" showLastColumn="0" showRowStripes="1" showColumnStripes="0"/></table>'
    )


def _unique_header(header):
    """Table column names must be unique and non-empty."""
    seen, out = set(), []
    for i, h in enumerate(header, 1):
        base = str(h).strip() or f"Column{i}"
        name, n = base, 2
        while name.lower() in seen:
            name = f"{base}_{n}"
            n += 1
        seen.add(name.lower())
        out.append(name)
    return out


def build_workbook(summary, panels):
    """The workbook as bytes. `summary` is a list of rows; `panels` is [{"name", "header", "rows"}], one table tab each."""
    sheets, taken_sheets, taken_tables = [], set(), set()
    first = sheet_name("Summary", taken_sheets)
    sheets.append({"name": first, "xml": _sheet_xml([list(r) for r in summary]), "table": None})
    for tid, p in enumerate(panels, 1):
        header = _unique_header(list(p.get("header") or []))
        if not header:
            raise ValueError(f"panel {p.get('name')!r} has no header, so it cannot be a table")
        rows = [
            list(r)[: len(header)] + [None] * (len(header) - len(r)) for r in p.get("rows") or []
        ]
        if len(rows) > MAX_ROWS:
            raise ValueError(f"panel {p.get('name')!r} has more rows than a sheet holds")
        name = sheet_name(p.get("name") or f"Panel {tid}", taken_sheets)
        tname = table_name(p.get("name") or f"Panel_{tid}", taken_tables)
        sheets.append(
            {
                "name": name,
                "xml": _sheet_xml([header] + rows, header_style=1, table_rid="rId1"),
                "table": (tid, _table_xml(tid, tname, header, len(rows))),
            }
        )
    zf_buf = io.BytesIO()
    with zipfile.ZipFile(zf_buf, "w", zipfile.ZIP_DEFLATED) as z:

        def put(path, text):
            info = zipfile.ZipInfo(path, _ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, text)

        overrides = "".join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, len(sheets) + 1)
        ) + "".join(
            f'<Override PartName="/xl/tables/table{s["table"][0]}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"/>'
            for s in sheets
            if s["table"]
        )
        put(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            f"{overrides}</Types>",
        )
        put(
            "_rels/.rels",
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="{PKG_REL}"><Relationship Id="rId1" Type="{REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        )
        sheet_tags = "".join(
            f'<sheet name="{_text(s["name"])}" sheetId="{i}" r:id="rId{i}"/>'
            for i, s in enumerate(sheets, 1)
        )
        put(
            "xl/workbook.xml",
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<workbook xmlns="{NS}" xmlns:r="{REL}"><sheets>{sheet_tags}</sheets></workbook>',
        )
        rels = "".join(
            f'<Relationship Id="rId{i}" Type="{REL}/worksheet" Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, len(sheets) + 1)
        )
        rels += f'<Relationship Id="rId{len(sheets) + 1}" Type="{REL}/styles" Target="styles.xml"/>'
        put(
            "xl/_rels/workbook.xml.rels",
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="{PKG_REL}">{rels}</Relationships>',
        )
        put(
            "xl/styles.xml",
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<styleSheet xmlns="{NS}"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
            '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
            '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs></styleSheet>',
        )
        for i, s in enumerate(sheets, 1):
            put(f"xl/worksheets/sheet{i}.xml", s["xml"])
            if s["table"]:
                tid, xml = s["table"]
                put(f"xl/tables/table{tid}.xml", xml)
                put(
                    f"xl/worksheets/_rels/sheet{i}.xml.rels",
                    f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="{PKG_REL}"><Relationship Id="rId1" Type="{REL}/table" Target="../tables/table{tid}.xml"/></Relationships>',
                )
    return zf_buf.getvalue()


def write_workbook(path, summary, panels):
    data = build_workbook(summary, panels)
    with open(path, "wb") as f:
        f.write(data)
    return len(data)
