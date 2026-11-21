"""Ops center token parity (issue 327, acceptance 5): the dark root block of opscenter/tokens/tokens.css carries the values
of the reference ops center, so a token that drifts fails here before it reaches a consumer. The accent matrix is checked
the same way: every named accent defines the six per-theme variables in both the light and the dark theme."""

import re
import unittest

from support import ROOT

CSS = (ROOT / "opscenter/tokens/tokens.css").read_text(encoding="utf-8")

# Section 6 of the parity spec: the values read from the reference root (dark theme).
EXPECTED = {
    "--bg-canvas": "#070b14",
    "--surface-1": "#121a2d",
    "--surface-2": "#19243e",
    "--surface-3": "#1f2c4a",
    "--surface-4": "#21304f",
    "--surface-5": "#2a3d62",
    "--surface-inset": "#05080f",
    "--border-subtle": "#1d2842",
    "--border-default": "#33446d",
    "--border-strong": "#4a5f93",
    "--border-field": "#6f80ad",
    "--text-primary": "#fbfcfe",
    "--text-secondary": "#c9d0dc",
    "--text-tertiary": "#b0bacb",
    "--text-quaternary": "#929db1",
    "--success": "#5dd790",
    "--warning": "#e8a317",
    "--urgent": "#e97a33",
    "--danger": "#f56b72",
    "--info": "#4a9fe0",
    "--hue-blue": "59 130 246",
    "--hue-green": "34 197 94",
    "--hue-amber": "245 158 11",
    "--hue-red": "239 68 68",
    "--hue-violet": "139 92 246",
    "--hue-teal": "20 184 166",
    "--hue-yellow": "234 179 8",
    "--hue-ink": "203 213 225",
    "--radius-xs": "5px",
    "--radius-sm": "6px",
    "--radius-md": "10px",
    "--radius-lg": "12px",
    "--radius-xl": "16px",
    "--radius-2xl": "20px",
    "--radius-pill": "999px",
    "--fs-hero": "38px",
    "--fs-display": "34px",
    "--fs-h1": "24px",
    "--fs-h2": "18px",
    "--fs-h3": "15px",
    "--fs-label": "12px",
    "--fs-micro": "11px",
    "--fs-nano": "9px",
    "--sidebar-w": "224px",
    "--topbar-h": "54px",
    "--gutter": "24px",
    "--gutter-mobile": "16px",
    "--dur-fast": "120ms",
    "--dur-base": "180ms",
    "--ease": "cubic-bezier(0.4, 0, 0.2, 1)",
    "--font-sans": '"Geist", "Inter", "Segoe UI", system-ui, -apple-system, sans-serif',
}

# The default accent is the root block (indigo); the named accents are the rest of the ladder.
ACCENTS = ["blue", "indigo", "violet", "fuchsia", "rose", "red", "orange", "hub", "amber", "gold", "green", "teal", "cyan"]
PER_THEME = ["--accent-hover", "--accent-bright", "--accent-dim", "--accent-veil", "--accent-glow", "--border-accent"]


def decls(block):
    block = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
    return {m.group(1): " ".join(m.group(2).split()) for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;]+);", block)}


def first_root():
    m = re.search(r"^:root \{(.*?)^\}", CSS, flags=re.S | re.M)
    assert m, "no :root block"
    return decls(m.group(1))


def accent_block(name, theme):
    pattern = r'^:root\[data-app-accent="' + name + r'"\]\[data-theme="' + theme + r'"\] \{(.*?)^\}'
    m = re.search(pattern, CSS, flags=re.S | re.M)
    return decls(m.group(1)) if m else {}


class OpsTokenParity(unittest.TestCase):
    def test_dark_root_matches_the_reference(self):
        root = first_root()
        for name, want in EXPECTED.items():
            self.assertIn(name, root, name)
            self.assertEqual(root[name], want, name)

    def test_every_accent_defines_the_per_theme_variables_in_both_themes(self):
        for name in ACCENTS:
            for theme in ("light", "dark"):
                got = accent_block(name, theme)
                for var in PER_THEME:
                    self.assertIn(var, got, f"{name} {theme} {var}")

    def test_the_accents_differ_between_light_and_dark(self):
        # The ladder is not one set of values in two files: the dim and the veil change with the theme.
        for name in ACCENTS:
            light, dark = accent_block(name, "light"), accent_block(name, "dark")
            self.assertNotEqual(light["--accent-dim"], dark["--accent-dim"], name)

    def test_indigo_matches_the_reference_values(self):
        dark = accent_block("indigo", "dark")
        self.assertEqual(dark["--accent-hover"], "#5b5ce7")
        self.assertEqual(dark["--accent-dim"], "#1b2246")
        self.assertEqual(accent_block("indigo", "light")["--accent-dim"], "#ebeafb")

    def test_every_accent_is_named_once_in_the_ladder(self):
        found = sorted(set(re.findall(r'data-app-accent="([a-z]+)"', CSS)))
        self.assertEqual(found, sorted(ACCENTS))


if __name__ == "__main__":
    unittest.main()
