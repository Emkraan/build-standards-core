"""
export_csv_test.py
Purpose: The shared CSV export: a text value starting with =, +, -, @, a tab or a carriage return is neutralised with a leading
         apostrophe (inside the quotes when the cell is quoted); numbers, booleans and None are not text and are never mangled (a
         negative number stays a number); commas, quotes and line breaks are quoted with the quotes doubled; the header goes through
         the same path; the file has CRLF line ends; importing the module has no side effect.
Run:     python3 export_csv_test.py
"""

import csv
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import export_csv as e


class Guard(unittest.TestCase):
    def test_every_formula_start_is_neutralised(self):
        for start in ("=", "+", "-", "@", "\t", "\r"):
            with self.subTest(start=repr(start)):
                self.assertEqual(
                    e.guard(start + "cmd|' /C calc'!A0"), "'" + start + "cmd|' /C calc'!A0"
                )

    def test_the_classic_payloads(self):
        for p in (
            '=HYPERLINK("http://x.example","a")',
            "+1+1",
            "-2+3",
            "@SUM(1+1)",
            "=cmd|' /C calc'!A0",
        ):
            self.assertTrue(e.guard(p).startswith("'"), p)

    def test_a_formula_character_that_is_not_first_is_left_alone(self):
        self.assertEqual(e.guard("a=b"), "a=b")
        self.assertEqual(e.guard("1 + 1"), "1 + 1")
        self.assertEqual(e.guard("user@example.com"), "user@example.com")

    def test_numbers_booleans_and_none_are_not_text(self):
        self.assertEqual(e.guard(-5), "-5")
        self.assertEqual(e.guard(-1.5), "-1.5")
        self.assertEqual(e.guard(3), "3")
        self.assertEqual(e.guard(True), "TRUE")
        self.assertEqual(e.guard(False), "FALSE")
        self.assertEqual(e.guard(None), "")

    def test_other_objects_are_written_through_str_and_guarded_too(self):
        class Id:
            def __str__(self):
                return "=ID()"

        self.assertEqual(e.guard(Id()), "'=ID()")

    def test_a_dash_text_value_is_guarded_but_a_negative_number_as_text_is_too(self):
        # a string "-5" cannot be told from "-5+cmd"; text is guarded, only real numbers are exempt
        self.assertEqual(e.guard("-5"), "'-5")


class Cell(unittest.TestCase):
    def test_quoting_and_doubling_quotes(self):
        self.assertEqual(e.cell("plain"), "plain")
        self.assertEqual(e.cell("a,b"), '"a,b"')
        self.assertEqual(e.cell('say "hi"'), '"say ""hi"""')
        self.assertEqual(e.cell("two\nlines"), '"two\nlines"')

    def test_the_apostrophe_is_inside_the_quotes(self):
        self.assertEqual(e.cell("=A1,B1"), '"\'=A1,B1"')
        self.assertEqual(e.cell("\tx"), "'\tx")  # a tab alone needs no quotes
        self.assertEqual(e.cell("\rx"), '"\'\rx"')  # a carriage return forces quotes


class File(unittest.TestCase):
    def test_header_rows_and_crlf(self):
        out = e.to_csv(["name", "note"], [["a", "=1+1"], ["b", None], [3, -4]])
        self.assertEqual(out, "name,note\r\na,'=1+1\r\nb,\r\n3,-4\r\n")

    def test_the_header_is_guarded_too(self):
        self.assertEqual(e.to_csv(["=x"], []), "'=x\r\n")

    def test_no_header_and_no_rows(self):
        self.assertEqual(e.to_csv(None, [["a"]]), "a\r\n")
        self.assertEqual(e.to_csv(None, []), "")

    def test_a_standard_csv_reader_round_trips_every_cell(self):
        rows = [["=cmd", 'a "quoted", cell', "line\nbreak", "+x", "-y", "@z"]]
        back = list(csv.reader(io.StringIO(e.to_csv(None, rows), newline="")))
        self.assertEqual(back[0], ["'=cmd", 'a "quoted", cell', "line\nbreak", "'+x", "'-y", "'@z"])

    def test_importing_the_module_has_no_side_effect(self):
        self.assertEqual(
            sorted(
                n
                for n in vars(e)
                if not n.startswith("_")
                and callable(getattr(e, n))
                and getattr(e, n).__module__ == "export_csv"
            ),
            ["cell", "guard", "to_csv"],
        )


if __name__ == "__main__":
    unittest.main()
