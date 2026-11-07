"""
export_csv.py
Purpose: The one shared export helper for CSV downloads (reports module R9). It quotes cells and neutralises a value that a spreadsheet
         program would read as a formula: a text value whose first character is `=`, `+`, `-`, `@`, a tab or a carriage return gets a
         leading apostrophe, so opening the file never runs anything. Every CSV download of a tool goes through `to_csv`; nothing
         builds a CSV line by hand. Numbers and booleans are not text and are written as they are, so a negative number stays a number.
Date:    2026-11-07

API:     guard(value)            a cell as safe text (the formula guard only, no quoting)
         cell(value)             a cell as one CSV field: guarded, then quoted when it needs quoting
         to_csv(header, rows)    the whole file as text, lines ended with CRLF; `header` may be None
         `value` may be str, int, float, bool or None (None is an empty cell); anything else is written through str().
No dependencies, no side effects on import.
"""

FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")
NEEDS_QUOTES = (",", '"', "\n", "\r")


def guard(value):
    """The cell as text with the formula guard applied: None is empty, numbers and booleans are written as they are, and a text
    value that starts with a formula character gets a leading apostrophe."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value) if isinstance(value, float) else str(value)
    text = value if isinstance(value, str) else str(value)
    return "'" + text if text.startswith(FORMULA_STARTS) else text


def cell(value):
    """One CSV field: guarded first (so the apostrophe is inside the quotes), then quoted and its quotes doubled when needed."""
    text = guard(value)
    if any(c in text for c in NEEDS_QUOTES):
        return '"' + text.replace('"', '""') + '"'
    return text


def to_csv(header, rows):
    """The file: an optional header row and the data rows, CRLF line ends, every cell through `cell`."""
    lines = []
    if header is not None:
        lines.append(",".join(cell(h) for h in header))
    lines += [",".join(cell(v) for v in row) for row in rows]
    return "\r\n".join(lines) + ("\r\n" if lines else "")
