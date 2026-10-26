"""The UI lint advisory notes: reported, never a change to the findings or the exit code."""

import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lint"))
import ui_lint  # noqa: E402  # pyright: ignore[reportMissingImports]


def run_lint(files, config, extra=()):
    root = pathlib.Path(tempfile.mkdtemp())
    (root / "standards-local").mkdir()
    (root / "src").mkdir()
    for name, text in files.items():
        (root / "src" / name).write_text(text)
    cfg = root / "standards-local" / "ui-lint.json"
    cfg.write_text(json.dumps(config))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = ui_lint.main(["--config", str(cfg), *extra])
    return code, out.getvalue()


class AdvisoryTests(unittest.TestCase):
    def test_neutral_hairline_is_noted_and_exit_is_unchanged(self):
        css = {"a.css": ".d { border-left: 1px solid #e5e5e5; }\n"}
        code, text = run_lint(css, {"paths": ["src"]})
        self.assertEqual(code, 1)  # the finding still fails, exactly as before
        self.assertIn("::error file=src/a.css,line=1::UI001", text)
        self.assertIn("::notice file=src/a.css,line=1::UI001 advisory (neutral-divider)", text)
        self.assertIn("1 advisory", text)

    def test_coloured_or_thick_border_has_no_note(self):
        css = {
            "a.css": ".d { border-left: 1px solid #ff0000; }\n.e { border-left: 2px solid #e5e5e5; }\n"
        }
        code, text = run_lint(css, {"paths": ["src"]})
        self.assertEqual(code, 1)
        self.assertNotIn("advisory", text)

    def test_data_palette_notes_colour_literals_only_in_declared_files(self):
        files = {
            "chart.css": ".a { background: #3366cc; }\n",
            "app.css": ".b { background: #3366cc; }\n",
        }
        code, text = run_lint(
            files, {"paths": ["src"], "data_palettes": ["src/chart.css"]}, ["--json"]
        )
        data = json.loads(text)
        self.assertEqual(code, 1)
        self.assertEqual(len(data["findings"]), 2)
        self.assertEqual(
            [(a["file"], a["advisory"]) for a in data["advisories"]],
            [("src/chart.css", "data-palette")],
        )

    def test_notes_never_hide_or_add_findings(self):
        files = {"chart.css": ".a { background: #3366cc; }\n"}
        _, plain = run_lint(files, {"paths": ["src"]}, ["--json"])
        _, marked = run_lint(
            files, {"paths": ["src"], "data_palettes": ["src/chart.css"]}, ["--json"]
        )
        strip = lambda d: [{k: v for k, v in f.items() if k != "advisory"} for f in d["findings"]]  # noqa: E731
        self.assertEqual(strip(json.loads(plain)), strip(json.loads(marked)))

    def test_clean_input_exits_zero_with_no_advisories(self):
        code, text = run_lint({"a.css": ".a { color: var(--text-primary); }\n"}, {"paths": ["src"]})
        self.assertEqual(code, 0)
        self.assertNotIn("advisory", text)


if __name__ == "__main__":
    unittest.main()
