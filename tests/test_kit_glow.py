"""web-ui.0.3: the kit's own CSS carries a glow only in the allowed places. This scans the kit stylesheets
for a glow token, a text-shadow or a coloured blurred shadow and fails outside the allowed selectors."""

import re
import unittest

from support import ROOT

FILES = ["kit/src/styles/kit.css", "kit/src/graph/graph.css"]
# Hero stat tile, the progress bar fill, the search focus, selected cards and nodes, chart bars, the active nav marker, and the art mark's own
# picture effect layers (an art asset, not chrome).
ALLOWED = re.compile(
    r"^\.progress-fill$|search-field\[data-focus|kpi-tile|is-selected|data-selected|health-bar|chart-bar|nav-glider|nav-item\[aria-current|\.am-|\.art-mark|am-ember"
)
TOKEN = re.compile(r"--accent-glow|--shadow-glow|--shadow-accent|text-shadow")


def blocks(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", text):
        yield m.group(1).strip(), m.group(2)


class KitGlow(unittest.TestCase):
    def test_no_glow_outside_allowed_selectors(self):
        bad = []
        for rel in FILES:
            for sel, body in blocks((ROOT / rel).read_text()):
                if ALLOWED.search(sel) or re.fullmatch(
                    r"[\d.%,\s]+|from|to", sel.split("}")[-1].strip()
                ):
                    continue
                for decl in body.split(";"):
                    if TOKEN.search(decl) or (
                        re.match(r"\s*(box-shadow|filter)\s*:", decl)
                        and re.search(r"\b0\s+0\s+\d+px", decl)
                        and "inset" not in decl
                        and "var(--focus-ring)" not in decl
                    ):
                        bad.append(f"{rel}: {sel[:50]} -> {decl.strip()[:70]}")
        self.assertEqual(bad, [], "glow outside the allowed uses (web-ui.0.3)")

    def test_search_focus_is_glow_only_ring_on_keyboard(self):
        css = (ROOT / "kit/src/styles/kit.css").read_text()
        m = re.search(r'\.search-field\[data-focus="true"\]\s*\{([^}]*)\}', css)
        self.assertNotIn("var(--focus-ring)", m.group(1))
        self.assertIn("0 0 0 3px var(--accent-glow)", m.group(1))
        keyboard = re.search(
            r'\.search-field\[data-focus="true"\]:has\(:focus-visible\)\s*\{([^}]*)\}', css
        )
        self.assertIn("var(--focus-ring)", keyboard.group(1))

    def test_progress_fill_glow_only_on_the_plain_fill(self):
        css = (ROOT / "kit/src/styles/kit.css").read_text()
        m = re.search(r"\n\.progress-fill\s*\{([^}]*)\}", css)
        self.assertIn("var(--shadow-glow)", m.group(1))
        m = re.search(r"\.progress\.meter \.progress-fill\s*\{([^}]*)\}", css)
        self.assertNotIn("box-shadow", m.group(1))


if __name__ == "__main__":
    unittest.main()
