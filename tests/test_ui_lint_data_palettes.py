"""UI lint: data palettes are exempt from the colour rule, neutral hairlines are not edge bars."""

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


class DataPaletteTests(unittest.TestCase):
    def test_neutral_hairline_is_not_a_finding(self):
        css = {
            "a.css": ".d { border-left: 1px solid var(--border-default); }\n.e { border-top: 1px solid hsl(220 5% 40%); }\n"
        }
        code, text = run_lint(css, {"paths": ["src"], "data_palettes": ["src/a.css"]})
        self.assertEqual(code, 0, text)

    def test_neutral_hairline_literal_is_no_edge_bar(self):
        css = {"a.css": ".d { border-left: 1px solid #e5e5e5; }\n"}
        _, text = run_lint(css, {"paths": ["src"]}, ["--json"])
        self.assertEqual([f["rule"] for f in json.loads(text)["findings"]], ["UI003"])

    def test_real_edge_bars_still_fail(self):
        css = {
            "a.css": ".a { border-left: 1px solid #ff0000; }\n.b { border-left: 2px solid #e5e5e5; }\n"
            ".c { border-left: 3px solid var(--accent); }\n.d { border-right: 1px solid var(--accent); }\n"
        }
        code, text = run_lint(css, {"paths": ["src"], "data_palettes": ["src/a.css"]}, ["--json"])
        rules = [f["rule"] for f in json.loads(text)["findings"]]
        self.assertEqual(code, 1)
        self.assertEqual(rules.count("UI001"), 4)

    def test_colour_literal_in_data_palette_is_exempt(self):
        files = {"chart.css": ".a { background: #3366cc; }\n"}
        code, text = run_lint(files, {"paths": ["src"], "data_palettes": ["src/chart.css"]})
        self.assertEqual(code, 0, text)

    def test_colour_literal_outside_data_palette_still_fails(self):
        files = {
            "chart.css": ".a { background: #3366cc; }\n",
            "app.css": ".b { background: #3366cc; }\n",
        }
        code, text = run_lint(
            files, {"paths": ["src"], "data_palettes": ["src/chart.css"]}, ["--json"]
        )
        self.assertEqual(code, 1)
        self.assertEqual([f["file"] for f in json.loads(text)["findings"]], ["src/app.css"])

    def test_data_palette_exempts_only_the_colour_rule(self):
        files = {"chart.css": ".a { background: #3366cc; z-index: 999; }\n"}
        code, text = run_lint(
            files, {"paths": ["src"], "data_palettes": ["src/chart.css"]}, ["--json"]
        )
        self.assertEqual(code, 1)
        self.assertEqual([f["rule"] for f in json.loads(text)["findings"]], ["UI004"])

    def test_clean_input_exits_zero(self):
        code, _ = run_lint({"a.css": ".a { color: var(--text-primary); }\n"}, {"paths": ["src"]})
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
