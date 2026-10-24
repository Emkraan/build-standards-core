#!/usr/bin/env python3
"""Build every token output from the one source, tokens/tokens.json, and certify its contrast.

Usage (from anywhere, paths resolve from this file):
  python3 tokens/build.py                 write tokens.css, tokens.ts, tailwind.preset.cjs,
                                          wpf/Tokens.*.xaml and CONTRAST.md (core repo only)
  python3 tokens/build.py --check         exit 1 if an output is stale or a certification fails (CI)
  python3 tokens/build.py --accent NAME=#RRGGBB
                                          print a certified accent block (CSS) for a custom accent
  python3 tokens/build.py --wpf-accent NAME --mode dark|light
                                          print a WPF ResourceDictionary for a named accent

Standard library only. The source format is modelled on the W3C design token format: every token
has $type, $value and $description. $light holds the light-mode value when it differs from the
dark (base) value. {name} is an alias to another token. Names are flat and unique across groups,
and each becomes the CSS custom property --name.
"""

import json
import math
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE / "tokens.json"
OUT_CSS = HERE / "tokens.css"
OUT_TS = HERE / "tokens.ts"
OUT_WPF = HERE / "wpf"
OUT_REPORT = HERE / "CONTRAST.md"
OUT_TW = HERE / "tailwind.preset.cjs"
STEPS = ["50", "100", "200", "300", "400", "500", "600", "700", "800"]
WHITE = (255.0, 255.0, 255.0, 1.0)
WRAP = 96

# ---------------------------------------------------------------- colour maths


def parse_color(s):
    """Hex, rgb()/rgba() (comma or space syntax) or a bare 'R G B' triplet -> (r, g, b, a)."""
    s = s.strip().lower()
    m = re.fullmatch(r"#([0-9a-f]{6})([0-9a-f]{2})?", s)
    if m:
        h = m.group(1)
        a = int(m.group(2), 16) / 255 if m.group(2) else 1.0
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)
    m = re.fullmatch(r"#([0-9a-f])([0-9a-f])([0-9a-f])", s)
    if m:
        return tuple(int(x * 2, 16) for x in m.groups()) + (1.0,)
    m = re.fullmatch(
        r"rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)\s*(?:[,/]\s*([\d.]+%?))?\s*\)", s
    )
    if m:
        a = m.group(4)
        a = 1.0 if a is None else (float(a[:-1]) / 100 if a.endswith("%") else float(a))
        return (float(m.group(1)), float(m.group(2)), float(m.group(3)), a)
    m = re.fullmatch(r"([\d.]+)\s+([\d.]+)\s+([\d.]+)", s)
    if m:
        return (float(m.group(1)), float(m.group(2)), float(m.group(3)), 1.0)
    return None


def colors_in(value):
    """Every colour literal inside a composite value (shadow, gradient), in order."""
    pat = r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?\b|#[0-9a-fA-F]{3}\b|rgba?\([^)]*\)"
    return [c for c in (parse_color(x) for x in re.findall(pat, value)) if c]


def _lin(c):
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _delin(x):
    x = max(0.0, x)
    return 12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055


def luminance(c):
    return 0.2126 * _lin(c[0]) + 0.7152 * _lin(c[1]) + 0.0722 * _lin(c[2])


def over(fg, bg):
    a = fg[3]
    return tuple(fg[i] * a + bg[i] * (1 - a) for i in range(3)) + (1.0,)


def contrast(fg, bg):
    """WCAG 2 contrast ratio. A translucent foreground is composited over the background first."""
    if bg[3] < 1:
        bg = over(bg, WHITE)
    if fg[3] < 1:
        fg = over(fg, bg)
    hi, lo = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def oklch(c):
    r, g, b = (_lin(x) for x in c[:3])
    lms = (
        0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b,
        0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b,
        0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b,
    )
    l_, m_, s_ = (math.copysign(abs(x) ** (1 / 3), x) for x in lms)
    L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    b2 = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    return (L, math.hypot(a, b2), math.degrees(math.atan2(b2, a)) % 360)


def _oklch_linear(L, C, h):
    a, b = C * math.cos(math.radians(h)), C * math.sin(math.radians(h))
    l_, m_, s_ = (
        L + 0.3963377774 * a + 0.2158037573 * b,
        L - 0.1055613458 * a - 0.0638541728 * b,
        L - 0.0894841775 * a - 1.2914855480 * b,
    )
    l, m, s = l_**3, m_**3, s_**3  # noqa: E741 - l, m, s are the LMS cone responses of the OKLab conversion
    return (
        4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
    )


def from_oklch(L, C, h):
    """OKLCH -> sRGB, reducing chroma until the colour is inside the sRGB gamut."""

    def ok(c):
        return all(-1e-7 <= x <= 1 + 1e-7 for x in _oklch_linear(L, c, h))

    lo, hi = 0.0, C
    if not ok(C):
        for _ in range(48):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if ok(mid) else (lo, mid)
        C = lo
    return tuple(round(min(1.0, _delin(x)) * 255) for x in _oklch_linear(L, C, h)) + (1.0,)


def hexs(c):
    return "#{:02x}{:02x}{:02x}".format(*tuple(int(round(x)) for x in c[:3]))


def triplet(c):
    return "{} {} {}".format(*(int(round(x)) for x in c[:3]))


def rgba(c, a):
    return "rgba({}, {}, {}, {})".format(*(int(round(x)) for x in c[:3]), _num(a))


def _num(x):
    return (f"{x:.3f}").rstrip("0").rstrip(".")


def hue_distance(h1, h2):
    d = abs(h1 - h2) % 360
    return min(d, 360 - d)


# ---------------------------------------------------------------- the model


class Model:
    def __init__(self, data):
        self.data = data
        self.groups = []  # (gid, group dict, [names])
        self.tokens = {}  # name -> token dict
        for gid, g in data["groups"].items():
            names = list(g["tokens"])
            self.groups.append((gid, g, names))
            for n, t in g["tokens"].items():
                if n in self.tokens:
                    raise SystemExit(f"tokens.json: token {n} is defined twice")
                self.tokens[n] = t
        self.accents = data["accents"]
        self.certify = data["certify"]

    def value(self, name, mode):
        t = self.tokens[name]
        return t.get("$light", t["$value"]) if mode == "light" else t["$value"]

    def varies(self, name):
        t = self.tokens[name]
        return "$light" in t and t["$light"] != t["$value"]


def css_value(v):
    """{name} aliases become var(--name)."""
    return re.sub(r"\{([a-z0-9-]+)\}", r"var(--\1)", v)


def resolve(values, name, depth=0):
    """Resolve a token to a final string: aliases and var() references replaced recursively."""
    if depth > 20:
        raise SystemExit(f"tokens.json: alias loop at {name}")
    v = values[name]
    return re.sub(
        r"\{([a-z0-9-]+)\}|var\(--([a-z0-9-]+)\)",
        lambda m: resolve(values, m.group(1) or m.group(2), depth + 1),
        v,
    )


def mode_values(model, mode, overrides=None):
    vals = {n: model.value(n, mode) for n in model.tokens}
    if overrides:
        vals.update(overrides)
    return vals


# ---------------------------------------------------------------- accents


def generate_accent(model, name, seed_hex):
    """A certified accent: a nine-step ramp in the seed's hue, plus the role tokens for both modes."""
    spec = model.accents
    prof_l, prof_c = spec["profile"]["lightness"], spec["profile"]["chroma"]
    seed = parse_color(seed_hex)
    _, sc, sh = oklch(seed)
    ramp = {s: from_oklch(prof_l[s], sc * prof_c[s], sh) for s in STEPS}

    dark = mode_values(model, "dark")
    light = mode_values(model, "light")
    sets = model.certify["sets"]
    content_d = [parse_color(resolve(dark, n)) for n in sets["content"]]
    content_l = [parse_color(resolve(light, n)) for n in sets["content"]]
    every_d = [parse_color(resolve(dark, n)) for n in sets["all"]]
    every_l = [parse_color(resolve(light, n)) for n in sets["all"]]
    s1d, s1l = parse_color(resolve(dark, "surface-1")), parse_color(resolve(light, "surface-1"))

    def nudge(c, ok, direction):
        L, C, h = oklch(c)
        for _ in range(600):
            if ok(c):
                return c
            L += 0.001 * direction
            c = from_oklch(L, C, h)
        raise SystemExit(f"accent {name}: could not certify {hexs(c)}")

    def lift(c, d):
        L, C, h = oklch(c)
        return from_oklch(L + d, C, h)

    # Fill: white text on the face, on the dark-mode hover (lighter) and on the gradient's top stop.
    def fill_ok(c):
        return (
            min(
                contrast(WHITE, c), contrast(WHITE, lift(c, 0.025)), contrast(WHITE, lift(c, 0.012))
            )
            >= 4.5
        )

    ramp["600"] = nudge(ramp["600"], fill_ok, -1)
    l6, c6, h6 = oklch(ramp["600"])
    ramp["700"] = from_oklch(min(prof_l["700"], l6 - 0.07), sc * prof_c["700"], sh)
    ramp["800"] = from_oklch(min(prof_l["800"], l6 - 0.125), sc * prof_c["800"], sh)
    dim_d = over(ramp["600"][:3] + (0.14,), s1d)
    dim_l = over(ramp["600"][:3] + (0.12,), s1l)
    # Text inks: 400 in dark, 800 in light, on every content surface and on the accent chip.
    ramp["400"] = nudge(
        ramp["400"],
        lambda c: min([contrast(c, s) for s in content_d] + [contrast(c, dim_d)]) >= 4.55,
        +1,
    )
    ramp["800"] = nudge(
        ramp["800"],
        lambda c: min([contrast(c, s) for s in content_l] + [contrast(c, dim_l)]) >= 4.55,
        -1,
    )
    hover_d, top = lift(ramp["600"], 0.025), lift(ramp["600"], 0.012)
    # Focus ring: the outer ring clears 3:1 on every surface in both modes.
    ring_d = nudge(
        ramp["400"], lambda c: min(contrast(c[:3] + (0.9,), s) for s in every_d) >= 3.0, +1
    )
    ring_l = nudge(
        ramp["700"], lambda c: min(contrast(c[:3] + (0.92,), s) for s in every_l) >= 3.0, -1
    )

    withheld = ""
    best = 999.0
    for hue in model.data["categorical_order"]:
        d = hue_distance(sh, oklch(parse_color(model.value(f"hue-{hue}", "dark")))[2])
        if d < spec["withhold_within_degrees"] and d < best:
            withheld, best = hue, d

    common = {f"accent-{s}": hexs(ramp[s]) for s in STEPS}
    common.update(
        {
            "accent": "{accent-600}",
            "accent-seed": hexs(seed),
            "accent-rgb": triplet(ramp["500"]),
            "accent-rgb-d": triplet(ramp["700"]),
            "accent-fill": triplet(ramp["600"]),
            "accent-fill-d": triplet(ramp["700"]),
            "accent-grad": f"linear-gradient(180deg, {hexs(top)} 0%, {hexs(ramp['600'])} 100%)",
            "accent-withheld-hue": withheld or "none",
            "body-wash": f"radial-gradient(120% 75% at 50% -10%, {rgba(ramp['500'], 0.1)}, transparent 55%)",
        }
    )
    d = dict(common)
    d.update(
        {
            "accent-hover": hexs(hover_d),
            "accent-bright": "{accent-400}",
            "accent-dim": hexs(dim_d),
            "accent-veil": rgba(ramp["600"], 0.1),
            "accent-glow": rgba(ramp["500"], 0.34),
            "border-accent": rgba(ramp["500"], 0.45),
            "border-accent-strong": rgba(ramp["500"], 0.72),
            "focus-ring": f"0 0 0 2px var(--surface-1), 0 0 0 4px {rgba(ring_d, 0.9)}",
        }
    )
    li = dict(common)
    li.update(
        {
            "accent-hover": "{accent-700}",
            "accent-bright": "{accent-800}",
            "accent-dim": hexs(dim_l),
            "accent-veil": rgba(ramp["600"], 0.07),
            "accent-glow": rgba(ramp["500"], 0.26),
            "border-accent": rgba(ramp["700"], 0.55),
            "border-accent-strong": rgba(ramp["700"], 0.8),
            "focus-ring": f"0 0 0 2px var(--surface-1), 0 0 0 4px {rgba(ring_l, 0.92)}",
        }
    )
    return {"seed": hexs(seed), "withheld": withheld or "none", "dark": d, "light": li}


def all_accents(model):
    out = {}
    for name, a in model.accents["named"].items():
        if name == model.accents["default"]:
            continue
        out[name] = generate_accent(model, name, a["seed"])
    return out


# ---------------------------------------------------------------- certification


def _pick(values, ref):
    """'name', 'name@0' (first colour in a composite), 'name@-1' (last), a literal colour, or
    'base+overlay' (overlay composited over base, for example a deep tile under its gloss)."""
    if "+" in ref:
        base, _, top = ref.partition("+")
        b, t = _pick(values, base), _pick(values, top)
        return None if b is None or t is None else over(t, b)
    if ref.startswith("#") or ref.startswith("rgb"):
        return parse_color(ref)
    name, _, idx = ref.partition("@")
    v = resolve(values, name)
    if idx:
        cs = colors_in(v)
        return cs[int(idx)] if cs else None
    return parse_color(v)


def certify(model, overrides_by_mode=None, only_tokens=None):
    """Evaluate every rule in both modes. Returns rows: (rule, mode, fg, bg, ratio, min, ok)."""
    rows = []
    sets = model.certify["sets"]
    for mode in ("dark", "light"):
        vals = mode_values(model, mode, (overrides_by_mode or {}).get(mode))
        for rule in model.certify["rules"]:
            bgs = sets[rule["on"]] if isinstance(rule["on"], str) else rule["on"]
            if only_tokens and not any(
                part.split("@")[0] in only_tokens for r in rule["fg"] + bgs for part in r.split("+")
            ):
                continue
            for fg in rule["fg"]:
                for bg in bgs:
                    f, b = _pick(vals, fg), _pick(vals, bg)
                    if f is None or b is None:
                        raise SystemExit(
                            f"certify: cannot read a colour from {fg} or {bg} ({mode})"
                        )
                    r = contrast(f, b)
                    rows.append(
                        (rule["why"], mode, fg, bg, r, rule["min"], r + 1e-9 >= rule["min"])
                    )
    return rows


# ---------------------------------------------------------------- emitters


def _wrap_comment(text, indent):
    if not text:
        return []
    words, lines, cur = text.split(), [], ""
    width = WRAP - len(indent) - 3
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    lines.append(cur)
    if len(lines) == 1:
        return [f"{indent}/* {lines[0]} */"]
    return (
        [f"{indent}/* {lines[0]}"]
        + [f"{indent}   {x}" for x in lines[1:-1]]
        + [f"{indent}   {lines[-1]} */"]
    )


def _decl(name, value, indent):
    return f"{indent}--{name}: {css_value(value)};"


def _block(selector, decls, indent=""):
    return [f"{indent}{selector} {{"] + decls + [f"{indent}}}"]


def emit_css(model, accents):
    head = model.data["$description"]
    out = ["/* " + "=" * 75]
    out += ["   " + x for x in _wrap_lines(head, WRAP - 3)]
    out += [
        "",
        "   GENERATED by tokens/build.py from tokens/tokens.json. Do not edit this file: edit the JSON and",
        "   run `python3 tokens/build.py`. CI fails when this file is stale.",
        "   " + "=" * 75 + " */",
        "",
    ]

    base = []
    for _gid, g, names in model.groups:
        base.append("")
        base += _wrap_comment(f"{g['$title']}. {g['$description']}".strip(), "  ")
        for n in names:
            t = model.tokens[n]
            base += _wrap_comment(t.get("$description", ""), "  ")
            base.append(_decl(n, t["$value"], "  "))
    out += _block(":root", base[1:] if base and base[0] == "" else base)

    # The light declarations are built once as data and emitted four times. Only the first copy
    # carries comments, so no comment text can ever leak into a repeated block.
    commented, light_pairs, dark_pairs = [], [], []
    for _gid, g, names in model.groups:
        vary = [n for n in names if model.varies(n)]
        if not vary:
            continue
        commented.append("")
        commented += _wrap_comment(
            f"{g['$title']} (light). {g.get('$light_description', '')}".strip(), "    "
        )
        for n in vary:
            t = model.tokens[n]
            commented += _wrap_comment(t.get("$light_description", ""), "    ")
            commented.append(_decl(n, t["$light"], "    "))
            light_pairs.append((n, t["$light"]))
            dark_pairs.append((n, t["$value"]))
    out += [
        "",
        '/* Light mode, from the OS signal. :not([data-theme="dark"]) keeps an explicit dark choice winning. */',
    ]
    out += (
        ["@media (prefers-color-scheme: light) {"]
        + _block(':root:not([data-theme="dark"])', commented[1:], "  ")
        + ["}"]
    )
    out += ["", "/* Light mode, explicit choice. Same declarations as above, generated. */"]
    out += _block(':root[data-theme="light"]', [_decl(n, v, "  ") for n, v in light_pairs])
    out += ["", "/* Dark mode, explicit choice. Wins over the OS light signal. Generated. */"]
    out += _block(':root[data-theme="dark"]', [_decl(n, v, "  ") for n, v in dark_pairs])
    out += ["", "/* Paper is always light: browsers drop backgrounds when printing. Generated. */"]
    out += (
        ["@media print {"]
        + _block(
            ':root,\n  :root[data-theme="light"],\n  :root[data-theme="dark"]',
            [_decl(n, v, "    ") for n, v in light_pairs],
            "  ",
        )
        + ["}"]
    )
    out += [
        "",
        '/* Native controls follow the mode. "dark light" puts dark first so an unset UA paints dark. */',
        ":root {",
        "  color-scheme: dark light;",
        "}",
        ':root[data-theme="light"] {',
        "  color-scheme: light;",
        "}",
        ':root[data-theme="dark"] {',
        "  color-scheme: dark;",
        "}",
        "@media print {",
        "  :root,",
        '  :root[data-theme="light"],',
        '  :root[data-theme="dark"] {',
        "    color-scheme: light;",
        "  }",
        "}",
    ]

    out += [
        "",
        "/* " + "=" * 75,
        '   NAMED ACCENTS. Set once on the root: <html data-app-accent="NAME">. Each accent is generated',
        "   from a seed colour and certified by build.py (white on the fill, the text ink on every content",
        "   surface and on the accent chip, the focus ring on every surface, in both modes). The default",
        f"   accent, {model.accents['default']}, needs no attribute. CONTRAST.md lists every result.",
        "   " + "=" * 75 + " */",
    ]
    for name, a in accents.items():
        sel = f':root[data-app-accent="{name}"]'
        d, li = a["dark"], a["light"]
        vary = [k for k in li if li[k] != d.get(k)]
        out += [
            "",
            f'/* {name}: seed {a["seed"]}, withholds categorical hue "{a["withheld"]}" from data */',
        ]
        out += _block(sel, [_decl(k, v, "  ") for k, v in d.items()])
        out += (
            ["@media (prefers-color-scheme: light) {"]
            + _block(
                f'{sel}:not([data-theme="dark"])', [_decl(k, li[k], "    ") for k in vary], "  "
            )
            + ["}"]
        )
        out += _block(f'{sel}[data-theme="light"]', [_decl(k, li[k], "  ") for k in vary])
        out += _block(f'{sel}[data-theme="dark"]', [_decl(k, d[k], "  ") for k in vary])
        out += (
            ["@media print {"]
            + _block(
                f'{sel},\n  {sel}[data-theme="light"],\n  {sel}[data-theme="dark"]',
                [_decl(k, li[k], "    ") for k in vary],
                "  ",
            )
            + ["}"]
        )
    return "\n".join(out) + "\n"


def validate_css(text):
    """Re-read the generated CSS: every declaration must be a well-formed property, every block balanced.

    Guards the generator itself, so a comment fragment can never end up as a declaration."""
    body = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    if body.count("{") != body.count("}"):
        raise SystemExit("build: generated CSS has unbalanced braces")
    for chunk in re.split(r"[{}]", body):
        for decl in chunk.split(";"):
            d = decl.strip()
            if (
                not d
                or d.startswith("@media")
                or d.startswith(":root")
                or d.startswith("[")
                or d.endswith(",")
            ):
                continue
            if "\n" in d and d.split("\n")[-1].strip().startswith(":root"):
                continue
            if not re.fullmatch(r"(--[a-z0-9-]+|color-scheme)\s*:\s*\S[^;]*", d, flags=re.S):
                raise SystemExit(f"build: generated CSS has a malformed declaration: {d[:80]!r}")
    return text


def _wrap_lines(text, width):
    out = []
    for para in text.split("\n\n"):
        words, cur = para.split(), ""
        for w in words:
            if cur and len(cur) + 1 + len(w) > width:
                out.append(cur)
                cur = w
            else:
                cur = f"{cur} {w}".strip()
        out.append(cur)
        out.append("")
    return out[:-1]


def emit_ts(model, accents):
    def dump(d):
        return (
            "{\n"
            + "".join(f"    {json.dumps(k)}: {json.dumps(v)},\n" for k, v in d.items())
            + "  }"
        )

    dark = mode_values(model, "dark")
    light = mode_values(model, "light")
    rd = {n: resolve(dark, n) for n in model.tokens}
    rl = {n: resolve(light, n) for n in model.tokens}
    acc = []
    for name, a in accents.items():
        ad = {**dark, **a["dark"]}
        al = {**light, **a["light"]}
        acc.append(
            f"  {json.dumps(name)}: {{\n    seed: {json.dumps(a['seed'])},\n    withheld: {json.dumps(a['withheld'])},\n"
            f"    dark: {dump({k: resolve(ad, k) for k in a['dark']}).replace(chr(10) + '    ', chr(10) + '      ').replace(chr(10) + '  }', chr(10) + '    }')},\n"
            f"    light: {dump({k: resolve(al, k) for k in a['light']}).replace(chr(10) + '    ', chr(10) + '      ').replace(chr(10) + '  }', chr(10) + '    }')},\n  }},\n"
        )
    cats = model.data["categorical_order"]
    extra = model.data.get("categorical_extra", [])
    return (
        "// GENERATED by tokens/build.py from tokens/tokens.json. Do not edit by hand.\n"
        "// Resolved values (aliases and var() references replaced) for code that cannot read CSS, such as\n"
        "// tests, canvas or chart code running outside the DOM. In the browser prefer the CSS variables.\n\n"
        "export type Mode = 'dark' | 'light';\n\n"
        f"export const tokens = {{\n  dark: {dump(rd)},\n  light: {dump(rl)},\n}} as const;\n\n"
        "export type TokenName = keyof typeof tokens.dark;\n\n"
        f"export const defaultAccent = {json.dumps(model.accents['default'])} as const;\n\n"
        f"export const accents = {{\n{''.join(acc)}}} as const;\n\n"
        f"export type AccentName = typeof defaultAccent | keyof typeof accents;\n\n"
        f"export const categoricalHues = {json.dumps(cats)} as const;\n\n"
        "export type CategoricalHue = (typeof categoricalHues)[number];\n\n"
        "// Extra hues: taken by name only, never in the series rotation or the avatar hash.\n"
        f"export const extraHues = {json.dumps(extra)} as const;\n\n"
        "export type ExtraHue = (typeof extraHues)[number];\n"
    )


def _pascal(name):
    return "".join(p.capitalize() if not p.isdigit() else p for p in name.split("-"))


def _argb(c):
    return f"#{int(round(c[3] * 255)):02X}{int(round(c[0])):02X}{int(round(c[1])):02X}{int(round(c[2])):02X}"


def token_type(model, name):
    """The $type of a token, following {alias} chains to the target. Accent-only names are colours."""
    t = model.tokens.get(name)
    if t is None:
        return "color"
    m = re.fullmatch(r"\{([a-z0-9-]+)\}", t["$value"])
    return token_type(model, m.group(1)) if m else t.get("$type")


# CSS weight to the WPF FontWeights name, for the --fw-* tokens.
WPF_WEIGHTS = {
    "400": "Normal",
    "500": "Medium",
    "600": "SemiBold",
    "700": "Bold",
    "800": "ExtraBold",
}


def emit_xaml(model, mode, accent=None):
    vals = mode_values(model, mode, accent[mode] if accent else None)
    names = list(accent[mode]) if accent else list(model.tokens)
    lines = [
        "<!-- GENERATED by tokens/build.py from tokens/tokens.json. Do not edit by hand. -->",
        f"<!-- {'Accent ' + accent['name'] if accent else 'Design tokens'}, {mode} mode. Merge into Application.Resources;",
        "     switch modes by swapping the dictionary. Shadows and gradients are web-only. -->",
        '<ResourceDictionary xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"',
        '                    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"',
        '                    xmlns:sys="clr-namespace:System;assembly=mscorlib">',
    ]
    for n in names:
        typ = token_type(model, n)
        v = resolve(vals, n)
        key = _pascal(n)
        if typ in ("color", "rgb"):
            c = parse_color(v)
            if c:
                lines.append(f'  <Color x:Key="Color.{key}">{_argb(c)}</Color>')
                lines.append(f'  <SolidColorBrush x:Key="Brush.{key}" Color="{_argb(c)}"/>')
        elif typ == "dimension" and v.endswith("px"):
            lines.append(f'  <sys:Double x:Key="Size.{key}">{v[:-2]}</sys:Double>')
        elif typ == "duration" and v.endswith("ms"):
            lines.append(
                f'  <Duration x:Key="Duration.{key}">0:0:{int(v[:-2]) / 1000:.3f}</Duration>'
            )
        elif typ == "fontWeight":
            name = WPF_WEIGHTS.get(v)
            if name:
                lines.append(f'  <FontWeight x:Key="Weight.{key}">{name}</FontWeight>')
        elif typ == "fontFamily":
            fam = ", ".join(
                x.strip().strip('"')
                for x in v.split(",")
                if x.strip()
                not in ("system-ui", "-apple-system", "sans-serif", "monospace", "ui-monospace")
            )
            lines.append(f'  <FontFamily x:Key="Font.{key}">{fam}</FontFamily>')
    lines.append("</ResourceDictionary>")
    return "\n".join(lines) + "\n"


def emit_tailwind(model):
    """A Tailwind preset that maps theme keys onto the same CSS variables, so a Tailwind build and a
    CSS-token build share one palette. Opacity modifiers work through Tailwind's color-mix support."""

    def v(n):
        return f"var(--{n})"

    t = model.tokens
    colors = {
        "canvas": v("bg-canvas"),
        "surface": {
            **{str(i): v(f"surface-{i}") for i in range(1, 6)},
            "inset": v("surface-inset"),
        },
        "ink": {
            k: v(f"text-{k}") for k in ("primary", "secondary", "tertiary", "quaternary", "inverse")
        },
        "line": {
            "subtle": v("border-subtle"),
            "DEFAULT": v("border-default"),
            "strong": v("border-strong"),
            "field": v("border-field"),
            "accent": v("border-accent"),
            "accent-strong": v("border-accent-strong"),
        },
        "accent": {
            "DEFAULT": v("accent"),
            "hover": v("accent-hover"),
            "bright": v("accent-bright"),
            "dim": v("accent-dim"),
            "seed": v("accent-seed"),
            **{s: v(f"accent-{s}") for s in STEPS},
        },
    }
    for st in ("success", "warning", "urgent", "danger", "info"):
        colors[st] = {
            "DEFAULT": v(st),
            **{k: v(f"{st}-{k}") for k in ("dim", "border") if f"{st}-{k}" in t},
        }
    colors["danger"].update(
        {
            "hover": v("danger-hover"),
            "700": v("danger-700"),
            "800": v("danger-800"),
            "900": v("danger-900"),
        }
    )
    colors["hue"] = {}
    for h in model.data["categorical_order"] + model.data.get("categorical_extra", []):
        colors["hue"][h] = f"rgb(var(--hue-{h}) / <alpha-value>)"
        colors["hue"][f"{h}-d"] = f"rgb(var(--hue-{h}-d) / <alpha-value>)"

    def pick(prefix, strip=True):
        return {(n[len(prefix) :] if strip else n): v(n) for n in t if n.startswith(prefix)}

    theme = {
        "colors": colors,
        "borderRadius": {k if k != "pill" else "full": val for k, val in pick("radius-").items()},
        "boxShadow": {
            **pick("elev-", False),
            "glow": v("shadow-glow"),
            "focus": v("focus-ring"),
            "inset-top": v("shadow-inset-top"),
        },
        "transitionDuration": {**pick("dur-"), "DEFAULT": v("dur-base")},
        "transitionTimingFunction": {
            "DEFAULT": v("ease"),
            "out": v("ease-out"),
            "in": v("ease-in"),
            "in-out": v("ease-in-out"),
            "spring": v("ease-spring"),
        },
        "zIndex": pick("z-"),
        "fontFamily": {
            "display": v("font-display"),
            "sans": v("font-sans"),
            "mono": v("font-mono"),
        },
        "fontSize": pick("fs-"),
        "fontWeight": {k: val for k, val in pick("fw-").items()},
    }
    body = json.dumps({"theme": {"extend": theme}}, indent=2)
    return (
        "// GENERATED by tokens/build.py from tokens/tokens.json. Do not edit by hand.\n"
        "// Tailwind preset: every key maps onto the CSS variables in tokens.css, so import tokens.css too.\n"
        '// Usage: presets: [require("./tokens-core/tailwind.preset.cjs")]\n'
        f"module.exports = {body};\n"
    )


def emit_report(model, accents, rows):
    out = [
        "# Contrast certification",
        "",
        "GENERATED by `tokens/build.py` from `tokens/tokens.json`. Do not edit. Every ratio is WCAG 2,",
        "with translucent colours composited over the surface first. CI fails when any row fails.",
        "",
    ]
    rules = []
    for r in rows:
        if r[0] not in rules:
            rules.append(r[0])
    for rule in rules:
        sub = [r for r in rows if r[0] == rule]
        out += [
            f"## {rule}",
            "",
            f"Minimum {_num(sub[0][5])}:1.",
            "",
            "| Mode | Foreground | Background | Ratio | Result |",
            "|---|---|---|---|---|",
        ]
        for _, mode, fg, bg, ratio, _mn, ok in sub:
            out.append(f"| {mode} | `{fg}` | `{bg}` | {ratio:.2f} | {'pass' if ok else 'FAIL'} |")
        out.append("")
    out += [
        "## Named accents",
        "",
        "Worst ratio per check across both modes. The fill is the primary button face, the ink is",
        "accent text on every content surface and on the accent chip, the ring is the focus ring on every surface.",
        "",
        "| Accent | Seed | Withholds | White on fill | Ink | Ring |",
        "|---|---|---|---|---|---|",
    ]
    for name, a in accents.items():
        rs = certify(model, {"dark": a["dark"], "light": a["light"]}, only_tokens=set(a["dark"]))

        def worst(pred, rs=rs):
            vals = [r[4] for r in rs if pred(r)]
            return f"{min(vals):.2f}" if vals else "-"

        out.append(
            f"| {name} | `{a['seed']}` | {a['withheld']} | {worst(lambda r: r[2] == 'text-inverse' and r[3].startswith('accent'))} | "
            f"{worst(lambda r: r[2] == 'accent-bright')} | {worst(lambda r: r[2].startswith('focus-ring'))} |"
        )
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- main


def build(model):
    accents = all_accents(model)
    rows = certify(model)
    default = model.accents["default"]
    computed = generate_accent(model, default, model.accents["named"][default]["seed"])["withheld"]
    declared = model.value("accent-withheld-hue", "dark")
    rows.append(
        (
            "Default accent withheld hue matches its seed",
            "dark",
            "accent-withheld-hue",
            declared,
            1.0 if computed == declared else 0.0,
            1.0,
            computed == declared,
        )
    )
    for name, a in accents.items():
        rows_a = certify(
            model, {"dark": a["dark"], "light": a["light"]}, only_tokens=set(a["dark"])
        )
        rows += [(f"{r[0]} [accent {name}]",) + r[1:] for r in rows_a if not r[6]]
    files = {
        OUT_CSS: validate_css(emit_css(model, accents)),
        OUT_TS: emit_ts(model, accents),
        OUT_TW: emit_tailwind(model),
        OUT_WPF / "Tokens.Dark.xaml": emit_xaml(model, "dark"),
        OUT_WPF / "Tokens.Light.xaml": emit_xaml(model, "light"),
        OUT_REPORT: emit_report(model, accents, [r for r in rows if "[accent" not in r[0]]),
    }
    return files, rows


def main(argv):
    model = Model(json.loads(SRC.read_text(encoding="utf8")))
    if "--accent" in argv:
        name, _, seed = argv[argv.index("--accent") + 1].partition("=")
        a = generate_accent(model, name, seed)
        rs = certify(model, {"dark": a["dark"], "light": a["light"]}, only_tokens=set(a["dark"]))
        bad = [r for r in rs if not r[6]]
        print(emit_css_accent_only(name, a))
        print(f"/* certified: {len(rs) - len(bad)} of {len(rs)} checks pass */")
        return 1 if bad else 0
    if "--wpf-accent" in argv:
        name = argv[argv.index("--wpf-accent") + 1]
        mode = argv[argv.index("--mode") + 1] if "--mode" in argv else "dark"
        a = all_accents(model)[name]
        print(
            emit_xaml(model, mode, {"name": name, "dark": a["dark"], "light": a["light"]}), end=""
        )
        return 0
    files, rows = build(model)
    failed = [r for r in rows if not r[6]]
    in_overlay = (HERE.parent / "standards.lock").is_file()
    if in_overlay and "--check" not in argv:
        print(
            "tokens: this is a synced copy inside an overlay. It is read-only: change tokens in the core.\n"
            "Use --check, --accent NAME=#RRGGBB or --wpf-accent NAME here."
        )
        return 2
    for r in failed:
        print(
            f"::error::contrast {r[1]}: {r[2]} on {r[3]} is {r[4]:.2f}:1, needs {_num(r[5])}:1 ({r[0]})"
        )
    if "--check" in argv:
        stale = [
            p
            for p, text in files.items()
            if not p.is_file() or p.read_text(encoding="utf8") != text
        ]
        for p in stale:
            print(f"::error::{p.relative_to(HERE.parent)} is stale: run python3 tokens/build.py")
        print(
            f"tokens: {len(rows) - len(failed)} of {len(rows)} contrast checks pass, {len(stale)} stale output(s)"
        )
        return 1 if failed or stale else 0
    OUT_WPF.mkdir(exist_ok=True)
    for p, text in files.items():
        p.write_text(text, encoding="utf8")
    print(
        f"tokens: wrote {len(files)} files, {len(rows) - len(failed)} of {len(rows)} contrast checks pass"
    )
    return 1 if failed else 0


def emit_css_accent_only(name, a):
    sel = f':root[data-app-accent="{name}"]'
    d, li = a["dark"], a["light"]
    vary = [k for k in li if li[k] != d.get(k)]
    out = [
        f'/* {name}: seed {a["seed"]}, withholds categorical hue "{a["withheld"]}". Generated by tokens/build.py --accent. */'
    ]
    out += _block(sel, [_decl(k, v, "  ") for k, v in d.items()])
    out += (
        ["@media (prefers-color-scheme: light) {"]
        + _block(f'{sel}:not([data-theme="dark"])', [_decl(k, li[k], "    ") for k in vary], "  ")
        + ["}"]
    )
    out += _block(f'{sel}[data-theme="light"]', [_decl(k, li[k], "  ") for k in vary])
    out += _block(f'{sel}[data-theme="dark"]', [_decl(k, d[k], "  ") for k in vary])
    out += (
        ["@media print {"]
        + _block(
            f'{sel},\n  {sel}[data-theme="light"],\n  {sel}[data-theme="dark"]',
            [_decl(k, li[k], "    ") for k in vary],
            "  ",
        )
        + ["}"]
    )
    return "\n".join(out)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
