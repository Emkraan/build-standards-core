"""
export_xlsx_test.py
Purpose: The workbook export: a Summary tab and one tab per panel; each panel tab is a real table (an Excel table with its header, a
         ref that matches the rows, unique column names); text is always an inline string and never a formula (a value like =1+1 has
         no <f>); control characters invalid in XML are removed; sheet and table names are made valid and unique; numbers and
         booleans keep their types; the pre-built pivot flag stays off and no pivot part is written; the output is deterministic and a
         standard zip and XML reader opens every part.
Run:     python3 export_xlsx_test.py
"""

import io
import sys
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))

import export_xlsx as x

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
CELL = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c"
PANELS = [
    {
        "name": "Posts per day",
        "header": ["day", "posts", "ok"],
        "rows": [["2026-11-01", 5, True], ["2026-11-02", 2.5, False]],
    },
    {"name": "Devices", "header": ["device", "user"], "rows": [["pc-1", "=1+1"], ["pc-2", None]]},
]
SUMMARY = [["Report", "Fleet"], ["Generated", "2026-11-07"]]


def open_zip(data):
    return zipfile.ZipFile(io.BytesIO(data))


def parse(z, path):
    return ET.fromstring(z.read(path))


class Workbook(unittest.TestCase):
    def setUp(self):
        self.data = x.build_workbook(SUMMARY, PANELS)
        self.z = open_zip(self.data)

    def test_every_part_is_well_formed_xml_and_the_zip_is_sound(self):
        self.assertIsNone(self.z.testzip())
        for n in self.z.namelist():
            ET.fromstring(self.z.read(n))

    def test_a_summary_tab_and_one_tab_per_panel(self):
        wb = parse(self.z, "xl/workbook.xml")
        names = [s.get("name") for s in wb.find("m:sheets", NS)]
        self.assertEqual(names, ["Summary", "Posts per day", "Devices"])
        self.assertEqual(
            sorted(n for n in self.z.namelist() if n.startswith("xl/worksheets/sheet")),
            ["xl/worksheets/sheet1.xml", "xl/worksheets/sheet2.xml", "xl/worksheets/sheet3.xml"],
        )

    def test_each_panel_tab_is_a_real_table_whose_ref_matches_its_rows(self):
        t1 = parse(self.z, "xl/tables/table1.xml")
        self.assertEqual((t1.get("ref"), t1.get("name")), ("A1:C3", "Posts_per_day"))
        self.assertEqual(
            [c.get("name") for c in t1.find("m:tableColumns", NS)], ["day", "posts", "ok"]
        )
        t2 = parse(self.z, "xl/tables/table2.xml")
        self.assertEqual(t2.get("ref"), "A1:B3")
        sheet2 = parse(self.z, "xl/worksheets/sheet2.xml")
        self.assertIsNotNone(sheet2.find("m:tableParts", NS))
        self.assertIn("table1.xml", self.z.read("xl/worksheets/_rels/sheet2.xml.rels").decode())
        # the Summary tab is plain cells, not a table
        self.assertIsNone(parse(self.z, "xl/worksheets/sheet1.xml").find("m:tableParts", NS))

    def test_text_is_always_text_and_never_a_formula(self):
        sheet = self.z.read("xl/worksheets/sheet3.xml").decode()
        self.assertIn("=1+1", sheet)
        self.assertNotIn("<f>", sheet)
        cell = next(
            c for c in parse(self.z, "xl/worksheets/sheet3.xml").iter(CELL) if c.get("r") == "B2"
        )
        self.assertEqual(cell.get("t"), "inlineStr")
        for n in self.z.namelist():
            self.assertNotIn(b"<f>", self.z.read(n), n)

    def test_numbers_and_booleans_keep_their_types_and_none_is_empty(self):
        cells = {c.get("r"): c for c in parse(self.z, "xl/worksheets/sheet2.xml").iter(CELL)}
        self.assertIsNone(cells["B2"].get("t"))
        self.assertEqual(cells["B2"].find("m:v", NS).text, "5")
        self.assertEqual(cells["B3"].find("m:v", NS).text, "2.5")
        self.assertEqual((cells["C2"].get("t"), cells["C2"].find("m:v", NS).text), ("b", "1"))
        self.assertEqual(cells["C3"].find("m:v", NS).text, "0")
        empty = next(
            c for c in parse(self.z, "xl/worksheets/sheet3.xml").iter(CELL) if c.get("r") == "B3"
        )
        self.assertEqual(len(list(empty)), 0)

    def test_the_header_row_is_bold(self):
        cells = {c.get("r"): c for c in parse(self.z, "xl/worksheets/sheet2.xml").iter(CELL)}
        self.assertEqual(cells["A1"].get("s"), "1")
        self.assertIsNone(cells["A2"].get("s"))

    def test_the_pivot_flag_stays_off_and_no_pivot_part_is_written(self):
        self.assertIs(x.PREBUILT_PIVOTS, False)
        self.assertFalse([n for n in self.z.namelist() if "pivot" in n.lower()])
        self.assertNotIn(b"pivot", self.z.read("[Content_Types].xml").lower())

    def test_the_output_is_deterministic(self):
        self.assertEqual(self.data, x.build_workbook(SUMMARY, PANELS))

    def test_write_workbook_writes_the_same_bytes(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "out.xlsx"
            self.assertEqual(x.write_workbook(p, SUMMARY, PANELS), len(self.data))
            self.assertEqual(p.read_bytes(), self.data)


class Names(unittest.TestCase):
    def test_sheet_names_are_valid_and_unique(self):
        taken = set()
        self.assertEqual(x.sheet_name("A/B:C?[x]*\\", taken), "A B C  x")
        self.assertEqual(x.sheet_name("A/B:C?[x]*\\", taken), "A B C  x (2)")
        long = "n" * 40
        out = x.sheet_name(long, set())
        self.assertEqual(len(out), 31)
        self.assertEqual(x.sheet_name("", set()), "Sheet")
        t = set()
        self.assertEqual((x.sheet_name("Data", t), x.sheet_name("DATA", t)), ("Data", "DATA (2)"))

    def test_table_names_are_identifiers_and_unique(self):
        taken = set()
        self.assertEqual(x.table_name("Posts per day", taken), "Posts_per_day")
        self.assertEqual(x.table_name("Posts per day", taken), "Posts_per_day_2")
        self.assertEqual(x.table_name("2026 totals", set()), "T_2026_totals")
        self.assertEqual(x.table_name("***", set()), "Table")

    def test_same_named_panels_still_make_a_valid_workbook(self):
        data = x.build_workbook(
            [],
            [
                {"name": "Same", "header": ["a"], "rows": [[1]]},
                {"name": "Same", "header": ["a", "a", ""], "rows": [[1, 2, 3]]},
            ],
        )
        z = open_zip(data)
        names = [s.get("name") for s in parse(z, "xl/workbook.xml").find("m:sheets", NS)]
        self.assertEqual(names, ["Summary", "Same", "Same (2)"])
        cols = [c.get("name") for c in parse(z, "xl/tables/table2.xml").find("m:tableColumns", NS)]
        self.assertEqual(cols, ["a", "a_2", "Column3"])
        self.assertNotEqual(
            parse(z, "xl/tables/table1.xml").get("name"),
            parse(z, "xl/tables/table2.xml").get("name"),
        )

    def test_column_letters(self):
        self.assertEqual(
            [x.col(n) for n in (1, 26, 27, 52, 53, 702, 703)],
            ["A", "Z", "AA", "AZ", "BA", "ZZ", "AAA"],
        )


class Input(unittest.TestCase):
    def test_control_characters_are_removed_and_xml_is_escaped(self):
        data = x.build_workbook([['a\x00b\x07c <&> "q"']], [])
        z = open_zip(data)
        sheet = z.read("xl/worksheets/sheet1.xml").decode()
        self.assertIn("abc &lt;&amp;&gt;", sheet)
        ET.fromstring(sheet)

    def test_a_panel_with_no_header_is_refused(self):
        with self.assertRaises(ValueError):
            x.build_workbook([], [{"name": "x", "header": [], "rows": []}])

    def test_short_and_long_rows_are_fitted_to_the_header(self):
        z = open_zip(
            x.build_workbook([], [{"name": "p", "header": ["a", "b"], "rows": [[1], [1, 2, 3]]}])
        )
        self.assertEqual(parse(z, "xl/tables/table1.xml").get("ref"), "A1:B3")
        refs = [c.get("r") for c in parse(z, "xl/worksheets/sheet2.xml").iter(CELL)]
        self.assertNotIn("C3", refs)

    def test_a_panel_with_no_rows_is_a_table_with_only_a_header(self):
        z = open_zip(x.build_workbook([], [{"name": "p", "header": ["a"], "rows": []}]))
        self.assertEqual(parse(z, "xl/tables/table1.xml").get("ref"), "A1:A1")

    def test_a_workbook_with_no_panels_is_just_the_summary(self):
        z = open_zip(x.build_workbook([["x"]], []))
        self.assertFalse([n for n in z.namelist() if n.startswith("xl/tables")])


if __name__ == "__main__":
    unittest.main()
