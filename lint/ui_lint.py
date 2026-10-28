#!/usr/bin/env python3
"""UI lint: the static checks behind the web-ui rules, for any app on this standard.

Usage (from anywhere, paths resolve from the config file):
  python3 lint-core/ui_lint.py                         lint the paths in standards-local/ui-lint.json
  python3 lint-core/ui_lint.py --config FILE           use another config
  python3 lint-core/ui_lint.py PATH [PATH ...]         lint these paths with default settings
  python3 lint-core/ui_lint.py --json                  machine-readable result (nightly tooling)
  python3 lint-core/ui_lint.py --write-baseline       record today's counts as a ratchet baseline, each
                                                       rule tied to the active exception that names it
  python3 lint/ui_lint.py --self-test                  run the fixtures (core CI)

Exit codes: 0 clean or within the baseline, 1 violations, 2 configuration error.

Data palettes and neutral dividers: files matched by "data_palettes" (globs in the config: a chart theme,
a table of category colours) are exempt from the colour-literal rule UI003, because their colours are data.
A one-sided border under 2px in a neutral grey is a hairline divider, not an edge bar, so UI001 does not
flag it. A coloured or 2px+ one-sided border, and a colour literal outside a data palette, still fail.

Suppression is deliberate and traceable, never a blanket switch:
  edge-ok                 on the line or the line above, UI001 only, for data marks that look like
                          bars (a chart today line, a timeline connector)
  core-exception: EXC-NNN on the line or the line above. The ID must be an active row in
                          standards-local/exceptions.md and that row must name this finding's rule
A baseline (the adoption ratchet) ties each rule's counts to the active exception that names the
rule. CI fails when any file and rule count rises above the baseline, and a rule's baseline stops
counting the day its exception expires.
Standard library only.
"""

import datetime
import fnmatch
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent

RULES = {
    "UI001": (
        "edge-bar accent",
        "web-ui.md 0.1",
        "a coloured or thick single-side border, inset side stripe, thin edge pseudo-element, narrow "
        "edge grid track or narrow painted element. "
        "Use .tone, .is-selected, a tinted fill, a full outline or a status dot",
    ),
    "UI002": (
        "native dialog",
        "web-ui.md 0.7",
        "window.alert, confirm or prompt, or a bare call the file never binds. Use useConfirm, usePrompt or toast",
    ),
    "UI003": (
        "colour literal",
        "web-ui.md 2",
        "a colour outside the token files. Use a token from tokens.css",
    ),
    "UI004": (
        "raw z-index",
        "web-ui.md 5",
        "a z-index number. Use a --z-* token (0 and -1 are allowed for local stacking)",
    ),
    "UI005": (
        "raw duration",
        "web-ui.md 14",
        "a transition or animation time literal. Use a --dur-* token",
    ),
    "UI006": (
        "typographic character",
        "web-ui.md 4",
        "an em or en dash, curly quote, NBSP, zero-width character or ellipsis character in UI source",
    ),
    "UI007": (
        "accent set outside the root",
        "web-ui.md 16",
        "data-app-accent set more than once, or an accent token set in app CSS",
    ),
    "UI008": (
        "theme branching",
        "web-ui.md 1",
        "a [data-theme] or prefers-color-scheme selector in app CSS. A theme is a token swap",
    ),
    "UI009": (
        "kit class restyled inline",
        "web-ui.md 0.10",
        "an element borrows a kit control class (btn, badge, tab, input...) and restyles its box inline, so the "
        "kit recipe (fixed sizing, nowrap, centring) still applies under the app style and content escapes. "
        "Use the kit component as is, or an app class of your own",
    ),
    "UI010": (
        "local theme or token",
        "web-ui.md 0.11",
        "an app stylesheet declares a core token (--surface-1, --text-primary, --radius-md...). The tokens come "
        "from tokens-core as shipped. Build on them with an app class, never redefine one",
    ),
    "UI011": (
        "disabled control without a reason",
        "web-ui.md 27.2",
        "a kit Button or IconButton with disabled and no disabledReason, so nobody learns why it is off or "
        "how to turn it on. Use disabledReason (the button stays focusable and the reason is its tip)",
    ),
    "UI012": (
        "icon-only control without a name and tip",
        "web-ui.md 27.1",
        "a control that holds only an icon and carries no accessible name or no tip. Use IconButton, whose "
        "label is required and is both",
    ),
    "UI013": (
        "tip too long",
        "web-ui.md 27.4",
        "a tip or disabledReason written as a literal over 200 characters or in three or more sentences. "
        "A tip is one or two short plain sentences, and anything longer belongs on the page or in an "
        "InfoTip popover",
    ),
}

DEFAULTS = {
    "paths": ["src"],
    "exclude": [
        "**/node_modules/**",
        "**/dist/**",
        "**/build/**",
        "**/*.min.*",
        "**/tokens-core/**",
        "**/lint-core/**",
        "**/kit-core/**",
        "**/standards-core/**",
    ],
    "token_files": ["**/tokens.css", "**/tokens.ts", "**/tailwind.preset.cjs"],
    "data_palettes": [],
    "baseline": None,
}
EXTS = {".css", ".tsx", ".ts", ".jsx", ".js", ".mjs", ".html"}
NAMED = {
    "white",
    "black",
    "red",
    "green",
    "blue",
    "gray",
    "grey",
    "orange",
    "yellow",
    "purple",
    "pink",
    "silver",
    "navy",
    "teal",
    "maroon",
    "olive",
    "lime",
    "aqua",
    "fuchsia",
    "brown",
    "gold",
    "indigo",
    "violet",
}
COLOUR_PROPS = re.compile(
    r"^(color|background(-color)?|background-image|border(-[a-z-]+)?-color|border(-(top|right|bottom|left|inline|block)(-(start|end))?)?|outline(-color)?|fill|stroke|box-shadow|text-shadow|caret-color|accent-color|text-decoration(-color)?|column-rule(-color)?|stop-color|flood-color|lighting-color)$"
)
TYPO = re.compile("[\u2013\u2014\u2018\u2019\u201c\u201d\u00a0\u200b\u200c\u200d\ufeff\u2026]")
EXC_RE = re.compile(r"core-exception:\s*(EXC-\d{3})")

# ------------------------------------------------------------------ helpers


def strip_comments(text, kind):
    """Blank comments out (newlines kept) so line numbers stay true."""

    def blank(m):
        return re.sub(r"[^\n]", " ", m.group(0))

    if kind == "css":
        return re.sub(r"/\*.*?\*/", blank, text, flags=re.S)
    text = re.sub(r"/\*.*?\*/", blank, text, flags=re.S)
    text = re.sub(r'(?<![:\'"\\])//[^\n]*', blank, text)
    return re.sub(r"<!--.*?-->", blank, text, flags=re.S)


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def active_exceptions(root):
    """{exception id: rule ref} for rows in standards-local/exceptions.md whose review date has not passed."""
    f = root / "standards-local" / "exceptions.md"
    out = {}
    if not f.is_file():
        return out
    today = datetime.date.today()
    for line in f.read_text(encoding="utf8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 8 and re.fullmatch(r"EXC-\d{3}", cells[0]):
            try:
                if datetime.date.fromisoformat(cells[7]) >= today:
                    out[cells[0]] = cells[1]
            except ValueError:
                pass
    return out


def css_blocks(clean):
    """Yield (selector, selector_pos, body, body_pos) for every innermost rule block."""
    stack = []
    for i, ch in enumerate(clean):
        if ch == "{":
            stack.append(i)
        elif ch == "}" and stack:
            start = stack.pop()
            body = clean[start + 1 : i]
            if "{" in body:
                continue
            j = start - 1
            while j >= 0 and clean[j] not in "{};":
                j -= 1
            sel = clean[j + 1 : start]
            yield sel.strip(), j + 1 + (len(sel) - len(sel.lstrip())), body, start + 1


def css_decls(body, body_pos):
    """(property, value, absolute position) for each declaration in a block body."""
    pos = 0
    for part in re.split(r"(;)", body):
        if part == ";":
            pos += 1
            continue
        if ":" in part:
            prop, _, val = part.partition(":")
            lead = len(part) - len(part.lstrip())
            yield prop.strip().lower(), val.strip(), body_pos + pos + lead
        pos += len(part)


# ------------------------------------------------------------------ checks


def neutral_hairline(val):
    """True for a border value that is a hairline (under 2px) in a neutral grey: a divider, not an accent."""
    px = re.search(r"(\d+(?:\.\d+)?)px", val)
    if not px or float(px.group(1)) >= 2:
        return False
    if re.search(r"accent|hue|success|warning|danger|info", val):
        return False
    cols = []
    for m in re.finditer(r"#([0-9a-fA-F]{3,8})\b", val):
        h = m.group(1)
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h[:3])
        if len(h) not in (6, 8):
            return False
        ch = [int(h[i : i + 2], 16) for i in (0, 2, 4)]
        cols.append(max(ch) - min(ch) <= 16)
    for m in re.finditer(r"rgba?\(([^)]*)\)", val):
        nums = re.findall(r"\d*\.?\d+", m.group(1))[:3]
        if len(nums) < 3:
            return False
        ch = [float(n) for n in nums]
        cols.append(max(ch) - min(ch) <= 16)
    for m in re.finditer(r"hsla?\(\s*[\d.]+(?:deg)?[\s,]+([\d.]+)%", val):
        cols.append(float(m.group(1)) <= 10)
    return bool(cols) and all(cols)


NARROW_PX = 6
LEN_PX = re.compile(r"(\d*\.?\d+)px")


def narrow_px(val):
    """The px value of a fixed length of NARROW_PX or less (and above zero), else None."""
    m = LEN_PX.fullmatch(val.strip())
    if m and 0 < float(m.group(1)) <= NARROW_PX:
        return float(m.group(1))
    return None


def grid_tracks(val):
    """Top-level track tokens of a grid-template-columns value, line names dropped."""
    out, depth, cur = [], 0, ""
    for ch in val:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch.isspace() and depth == 0:
            if cur:
                out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur:
        out.append(cur)
    return [t for t in out if not t.startswith("[")]


def painted_bg(props):
    for k in ("background", "background-color", "background-image"):
        v = props.get(k, "").strip().lower()
        if v and v not in ("none", "transparent", "inherit", "initial", "unset"):
            return True
    return False


def core_tokens():
    """Names of the tokens the core defines, read from the sheet that ships beside this linter."""
    for d in ("tokens-core", "tokens"):
        f = HERE.parent / d / "tokens.css"
        if f.is_file():
            return set(re.findall(r"(--[a-z0-9-]+)\s*:", f.read_text(encoding="utf8")))
    return set()


CORE_TOKENS = core_tokens()


def check_css(text, clean, hit, is_token_file, allow_accent_block):
    themed = not is_token_file and not allow_accent_block
    if themed:
        for m in re.finditer(r"@media[^{;]*prefers-color-scheme", clean):
            hit("UI008", m.start(), m.group(0).strip()[:60])
    blocks = [
        (sel, sel_pos, list(css_decls(body, body_pos)))
        for sel, sel_pos, body, body_pos in css_blocks(clean)
    ]
    # A narrow grid track only paints a bar when some cell fills it: a rule in the same file with a
    # background that stretches or takes the full height.
    stretched_fill = False
    for _, _, decls in blocks:
        props = {p: v for p, v, _ in decls}
        tall = props.get("align-self", "").strip() == "stretch" or any(
            props.get(k, "").strip() == "100%" for k in ("height", "block-size")
        )
        if tall and painted_bg(props):
            stretched_fill = True
            break
    for sel, sel_pos, decls in blocks:
        props = {p: v for p, v, _ in decls}
        if stretched_fill:
            for prop, val, pos in decls:
                cols = (
                    val.split("/", 1)[1]
                    if prop == "grid-template" and "/" in val
                    else val
                    if prop == "grid-template-columns"
                    else None
                )
                tracks = grid_tracks(cols) if cols else []
                if len(tracks) > 1:
                    for edge, t in (("first", tracks[0]), ("last", tracks[-1])):
                        if narrow_px(t) is not None:
                            hit(
                                "UI001",
                                pos,
                                f"narrow {edge} grid track {t} on {sel[:40]} (an edge bar built from layout)",
                            )
                            break
        if not re.search(
            r"::?(before|after|marker|placeholder|selection|backdrop|first-line|first-letter)", sel
        ):
            for prop, val, pos in decls:
                if prop not in ("width", "inline-size"):
                    continue
                w = narrow_px(val)
                if w is None or not painted_bg(props):
                    continue
                h = props.get("height") or props.get("block-size") or ""
                hm = LEN_PX.fullmatch(h.strip())
                if hm and float(hm.group(1)) <= 2 * w:
                    continue  # a dot or a small square mark, not a bar
                hit("UI001", pos, f"narrow painted element {prop}: {val} on {sel[:40]}")
        if themed and not sel.startswith("@") and "[data-theme" in sel:
            hit("UI008", sel_pos, sel[:60])
        if re.search(r"::?(before|after)", sel):
            w, h = props.get("width", ""), props.get("height", "")
            thin_w = re.fullmatch(r"[1-4](\.\d+)?px", w or "") is not None
            thin_h = re.fullmatch(r"[1-4](\.\d+)?px", h or "") is not None
            tall = (
                h in ("100%", "auto")
                or ("top" in props and "bottom" in props)
                or "inset-block" in props
            )
            wide = (
                w in ("100%", "auto")
                or ("left" in props and "right" in props)
                or "inset-inline" in props
            )
            painted = any(
                k in props
                for k in ("background", "background-color", "background-image", "border-color")
            )
            if painted and ((thin_w and tall) or (thin_h and wide)):
                hit("UI001", sel_pos, f"thin edge pseudo-element on {sel[:50]}")
        for prop, val, pos in decls:
            m = re.fullmatch(
                r"border-(left|right|top|bottom|inline-start|inline-end|block-start|block-end)(-width)?",
                prop,
            )
            if m:
                px = re.search(r"(\d+(?:\.\d+)?)px", val)
                coloured = re.search(r"accent|hue|success|warning|danger|info|#|rgb|hsl", val)
                if not neutral_hairline(val) and (
                    (px and float(px.group(1)) >= 2)
                    or (coloured and not re.search(r"transparent", val))
                ):
                    hit("UI001", pos, f"{prop}: {val[:40]}")
            if prop == "box-shadow":
                for sm in re.finditer(
                    r"inset\s+(-?\d+(?:\.\d+)?)(?:px)?\s+(-?\d+(?:\.\d+)?)(?:px)?\s+0(?:px)?(?:\s+0(?:px)?)?\s",
                    val + " ",
                ):
                    x, y = float(sm.group(1)), float(sm.group(2))
                    if (x == 0) != (y == 0) and max(abs(x), abs(y)) >= 2:
                        hit("UI001", pos, f"inset side stripe {sm.group(0).strip()}")
            if prop == "z-index" and re.fullmatch(r"-?\d+", val) and val not in ("0", "-1"):
                hit("UI004", pos, f"z-index: {val}")
            if prop in (
                "transition",
                "transition-duration",
                "transition-delay",
                "animation",
                "animation-duration",
                "animation-delay",
            ):
                no_vars = re.sub(r"var\([^)]*\)", "", val)
                for t in re.findall(r"(?<![\w.-])(\d*\.?\d+)(ms|s)\b", no_vars):
                    if float(t[0]) != 0:
                        hit("UI005", pos, f"{prop}: {t[0]}{t[1]}")
                        break
            if prop.startswith("--accent") or prop in (
                "--focus-ring",
                "--border-accent",
                "--border-accent-strong",
            ):
                if not allow_accent_block:
                    hit("UI007", pos, f"{prop} set in app CSS")
            elif prop in CORE_TOKENS and not is_token_file and not allow_accent_block:
                hit("UI010", pos, f"{prop} redefined in app CSS")
            if not is_token_file and not prop.startswith("--") and COLOUR_PROPS.match(prop):
                v = re.sub(r"var\([^)]*\)", "", val)
                if re.search(
                    r"#[0-9a-fA-F]{3,8}\b|\b(rgba?|hsla?|oklch|oklab|lab|lch|hwb)\(\s*[\d.]", v
                ):
                    hit("UI003", pos, f"{prop}: {val[:40]}")
                elif any(re.search(rf"(?<![\w-]){n}(?![\w-])", v.lower()) for n in NAMED):
                    hit("UI003", pos, f"{prop}: {val[:40]} (named colour)")
            elif not is_token_file and prop.startswith("--"):
                v = re.sub(r"var\([^)]*\)", "", val)
                if (
                    re.search(r"#[0-9a-fA-F]{3,8}\b|\b(rgba?|hsla?|oklch)\(\s*[\d.]", v)
                    and not allow_accent_block
                ):
                    hit(
                        "UI003",
                        pos,
                        f"{prop}: {val[:40]} (colour in a custom property outside the token files)",
                    )


IDENT = r"[A-Za-z_$][\w$]*"


def local_bindings(clean):
    """Names the file binds itself (declarations, destructuring, imports, functions).

    A bare confirm(...) is the native dialog only when the file never binds the name, so
    `const { confirm, dialog } = useConfirm()` followed by `confirm(...)` is not flagged.
    """
    names = set(re.findall(rf"\b(?:const|let|var|function\*?|class)\s+({IDENT})", clean))
    for m in re.finditer(r"\b(?:const|let|var)\s*([{\[][^=;]*?[}\]])\s*=", clean):
        pat = re.sub(r"=[^,}\]]*", "", m.group(1))
        for name, colon in re.findall(rf"({IDENT})\s*(:)?", pat):
            if not colon:
                names.add(name)
    for m in re.finditer(r"\bimport\s+(?:type\s+)?([^;]*?)\s+from\b", clean, re.S):
        spec = m.group(1)
        brace = re.search(r"\{([^}]*)\}", spec)
        if brace:
            for part in brace.group(1).split(","):
                bits = part.split()
                if bits:
                    names.add(bits[-1])
        head = re.sub(r"\{[^}]*\}", "", spec)
        names.update(re.findall(rf"(?:^|,|\bas)\s*({IDENT})\s*(?=,|$)", head.strip()))
    return names


# Kit classes whose recipe sizes a single-line control (minimum height, nowrap, line-height 1,
# centring). An app element that carries one of these and restyles the box inline gets both, and the
# kit recipe wins where the inline style is silent (nowrap under a long label, centred two-line
# body). Containers such as .card size to their content, so a padding tweak there is not flagged.
KIT_BOX_CLASSES = {"btn", "hub-btn", "badge", "tab", "seg-btn", "input", "select", "kbd"}
BOX_STYLE_KEYS = {
    "padding",
    "paddingTop",
    "paddingBottom",
    "paddingBlock",
    "paddingInline",
    "height",
    "minHeight",
    "maxHeight",
    "lineHeight",
    "whiteSpace",
    "display",
    "flexDirection",
    "alignItems",
    "justifyContent",
    "background",
    "backgroundColor",
    "border",
    "borderColor",
    "borderRadius",
    "fontSize",
}


def jsx_tags(clean):
    """Yield (start, text) for each JSX opening tag, skipping braces and strings inside attributes."""
    for m in re.finditer(r"<([A-Za-z][\w.]*)(?=[\s/>])", clean):
        i, depth, quote, n = m.end(), 0, None, len(clean)
        limit = min(n, m.start() + 4000)
        while i < limit:
            c = clean[i]
            if quote:
                if c == "\\":
                    i += 1
                elif c == quote:
                    quote = None
            elif c in "'\"`":
                quote = c
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            elif c == ">" and depth == 0:
                yield m.start(), clean[m.start() : i + 1]
                break
            elif c == "<" and depth == 0:
                break
            i += 1


def kit_class_restyles(clean):
    """UI009: a kit box class on an element whose inline style restyles that box."""
    out = []
    for start, tag in jsx_tags(clean):
        cm = re.search(
            r'\bclassName\s*=\s*(?:\{\s*)?(?:"([^"]*)"|\'([^\']*)\'|`((?:[^`\\]|\\.)*)`)', tag
        )
        if not cm:
            continue
        value = next(g for g in cm.groups() if g is not None)
        static = re.sub(r"\$\{[^}]*\}", " ", value).split()
        kit = sorted(set(static) & KIT_BOX_CLASSES)
        if not kit:
            continue
        sm = re.search(r"\bstyle\s*=\s*\{\{(.*)\}\}", tag, re.S)
        if not sm:
            continue
        keys = set(re.findall(r"(?:^|[{,])\s*([A-Za-z]+)\s*:", sm.group(1))) & BOX_STYLE_KEYS
        if keys:
            out.append(
                (start + cm.start(), f".{kit[0]} restyled inline ({', '.join(sorted(keys)[:4])})")
            )
    return out


def jsx_attrs(tag):
    """The attributes of one JSX opening tag: {name: value text, or None for a bare attribute}.

    A spread such as {...props} is recorded under the key "..." because it can carry any attribute.
    """
    m = re.match(r"<[A-Za-z][\w.]*", tag)
    i, n, out = (m.end() if m else 0), len(tag), {}

    def skip_braces(j):
        depth, quote = 0, None
        while j < n:
            c = tag[j]
            if quote:
                if c == "\\":
                    j += 1
                elif c == quote:
                    quote = None
            elif c in "'\"`":
                quote = c
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return j + 1
            j += 1
        return n

    while i < n:
        c = tag[i]
        if c.isspace() or c in "/>":
            i += 1
        elif c == "{":
            end = skip_braces(i)
            if tag[i + 1 : end - 1].lstrip().startswith("..."):
                out["..."] = tag[i:end]
            i = end
        else:
            nm = re.match(r"[A-Za-z_][\w:.-]*", tag[i:])
            if not nm:
                i += 1
                continue
            name, i = nm.group(0), i + nm.end()
            while i < n and tag[i].isspace():
                i += 1
            if i >= n or tag[i] != "=":
                out[name] = None
                continue
            i += 1
            while i < n and tag[i].isspace():
                i += 1
            start = i
            if i < n and tag[i] in "\"'":
                quote = tag[i]
                i += 1
                while i < n and tag[i] != quote:
                    i += 2 if tag[i] == "\\" else 1
                i += 1
            elif i < n and tag[i] == "{":
                i = skip_braces(i)
            else:
                while i < n and not tag[i].isspace() and tag[i] not in "/>":
                    i += 1
            out[name] = tag[start:i]
    return out


IMPORT_CLAUSE = re.compile(r"\bimport\s+(?:type\s+)?([^'\";]*?)\s*from\s*['\"]([^'\"]+)['\"]")


def kit_bindings(clean, names):
    """The local names under which the file imports one of `names` from a package or an alias.

    A relative import ("./Button", "../primitives/Button") is a file of the same project, which is either
    the kit's own internals or a consumer's wrapper. The rules about using the kit leave both alone, and so
    they leave a component the file declares itself. Returns {local name: imported name}.
    """
    out = {}
    for m in IMPORT_CLAUSE.finditer(clean):
        clause, spec = m.groups()
        braces = re.search(r"\{([^}]*)\}", clause)
        if spec.startswith((".", "/")) or not braces:
            continue
        for item in braces.group(1).split(","):
            bits = re.split(r"\s+as\s+", re.sub(r"^\s*type\s+", "", item.strip()))
            if bits[0].strip() in names:
                out[bits[-1].strip()] = bits[0].strip()
    return out


KIT_BUTTONS = ("Button", "IconButton")
# An icon element as the whole body of a control: <IconTrash />, <TrashIcon />, or an inline <svg>.
ICON_ONLY_BODY = re.compile(
    r"\s*<(?:Icon[A-Za-z0-9]*|[A-Za-z0-9]+Icon)\b(?:[^<>{}]|\{[^{}]*\})*/>\s*</(?:button|a)>"
    r"|\s*<svg\b.*?</svg>\s*</(?:button|a)>",
    re.S,
)
TIP_ATTRS = ("data-tip", "tip", "disabledReason")
TIP_MAX = 200
FALSE_VALUE = re.compile(r"\{\s*(?:false|0|null|undefined)\s*\}")
STRING_VALUE = re.compile(
    r"\"([^\"]*)\"|'([^']*)'|\{\s*(?:\"([^\"]*)\"|'([^']*)'|`([^`$]*)`)\s*\}", re.S
)


def tag_name(tag):
    return re.match(r"<([\w.]+)", tag).group(1)


def disabled_without_reason(clean):
    """UI011: a kit Button that is disabled and gives no reason (web-ui 27.2)."""
    bound = kit_bindings(clean, KIT_BUTTONS)
    out = []
    for start, tag in jsx_tags(clean):
        name = tag_name(tag)
        if name not in bound:
            continue
        attrs = jsx_attrs(tag)
        if "disabled" not in attrs or "..." in attrs:
            continue
        if attrs["disabled"] and FALSE_VALUE.fullmatch(attrs["disabled"].strip()):
            continue
        if "disabledReason" in attrs or "loading" in attrs:
            continue
        out.append((start, f"<{name} disabled> has no disabledReason"))
    return out


def icon_only_without_name(clean):
    """UI012: a control that is only an icon and lacks an accessible name or a tip (web-ui 27.1)."""
    bound = kit_bindings(clean, ("Button",))
    out = []
    for start, tag in jsx_tags(clean):
        name = tag_name(tag)
        attrs = jsx_attrs(tag)
        if "..." in attrs:
            continue
        if name in bound:
            icon_only = tag.rstrip().endswith("/>") and bool({"icon", "iconEnd"} & attrs.keys())
        elif name in ("button", "a"):
            icon_only = bool(ICON_ONLY_BODY.match(clean, start + len(tag)))
        else:
            continue
        if not icon_only:
            continue
        named = {"aria-label", "aria-labelledby"} & attrs.keys()
        tipped = {"data-tip", "title"} & attrs.keys()
        if not (named and tipped):
            missing = " and no ".join(
                part for part, ok in (("name", named), ("tip", tipped)) if not ok
            )
            out.append((start, f"<{name}> holds only an icon and has no {missing}"))
    return out


def long_tips(clean):
    """UI013: a tip or reason written as a literal that is not one or two short sentences (web-ui 27.4)."""
    out = []
    for start, tag in jsx_tags(clean):
        attrs = jsx_attrs(tag)
        for key in TIP_ATTRS:
            m = STRING_VALUE.fullmatch((attrs.get(key) or "").strip())
            if not m:
                continue
            text = next(g for g in m.groups() if g is not None)
            sentences = len(re.findall(r"[.!?](?=\s+[A-Z])", text)) + 1
            if len(text) > TIP_MAX or sentences >= 3:
                out.append((start, f"{key} is {len(text)} characters in {sentences} sentence(s)"))
    return out


def check_script(text, clean, hit, is_token_file):
    bound = local_bindings(clean)
    for m in re.finditer(
        r"(?<![\w.$])((?:window|globalThis|self)\.)?(alert|confirm|prompt)\s*\(", clean
    ):
        if m.group(1) or m.group(2) not in bound:
            hit("UI002", m.start(), m.group(0))
    strings = list(
        re.finditer(r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'|`(?:[^`\\]|\\.)*`', clean)
    )
    if not is_token_file:
        hex_re = re.compile(
            r"(?<![\w/&])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})(?![\w-])"
        )
        fn_re = re.compile(r"\b(rgba?|hsla?|oklch|oklab|hwb)\(\s*[\d.]")
        for s in strings:
            inner = s.group(0)[1:-1]
            if hex_re.search(inner) or fn_re.search(inner):
                hit("UI003", s.start(), s.group(0)[:40])
    for m in re.finditer(
        r'\bborder(Left|Right|Top|Bottom|InlineStart|InlineEnd)(Width)?\s*:\s*[\'"`]?(\d+(?:\.\d+)?)px',
        clean,
    ):
        if float(m.group(3)) >= 2:
            hit("UI001", m.start(), m.group(0))
    for m in re.finditer(r"\bzIndex\s*:\s*(-?\d+)\b", clean):
        if m.group(1) not in ("0", "-1"):
            hit("UI004", m.start(), m.group(0))
    for m in re.finditer(
        r'\b(transition|animation)(Duration|Delay)?\s*:\s*([\'"`])([^\'"`]*)\3', clean
    ):
        if re.search(
            r"(?<![\w.-])(\d*\.?[1-9]\d*)(ms|s)\b", re.sub(r"var\([^)]*\)", "", m.group(4))
        ):
            hit("UI005", m.start(), m.group(0)[:50])
    for pos, detail in kit_class_restyles(clean):
        hit("UI009", pos, detail)
    for pos, detail in disabled_without_reason(clean):
        hit("UI011", pos, detail)
    for pos, detail in icon_only_without_name(clean):
        hit("UI012", pos, detail)
    for pos, detail in long_tips(clean):
        hit("UI013", pos, detail)
    return [
        m
        for m in re.finditer(
            r'data-app-accent\s*=|setAttribute\(\s*[\'"]data-app-accent|dataset\.appAccent\s*=',
            clean,
        )
    ]


def lint_file(path, rel, root, cfg, active, findings, accent_writes):
    text = path.read_text(encoding="utf8", errors="replace")
    raw_lines = text.splitlines()
    kind = "css" if path.suffix == ".css" else "script"
    clean = strip_comments(text, kind)
    is_token = any(fnmatch.fnmatch(rel, g) for g in cfg["token_files"])

    def suppressed(rule, line):
        for ln in (line, line - 1):
            if 1 <= ln <= len(raw_lines):
                s = raw_lines[ln - 1]
                if rule == "UI001" and "edge-ok" in s:
                    return True
                for eid in EXC_RE.findall(s):
                    if active.get(eid) == RULES[rule][1]:
                        return True
        return False

    is_data = any(
        fnmatch.fnmatch(rel, g) or fnmatch.fnmatch("/" + rel, g)
        for g in cfg.get("data_palettes", [])
    )

    def hit(rule, pos, detail):
        if rule == "UI003" and is_data:
            return
        line = line_of(clean, pos)
        if not suppressed(rule, line):
            findings.append({"rule": rule, "file": rel, "line": line, "detail": detail.strip()})

    for i, ln in enumerate(raw_lines, 1):
        for m in TYPO.finditer(ln):
            if not suppressed("UI006", i):
                findings.append(
                    {"rule": "UI006", "file": rel, "line": i, "detail": f"U+{ord(m.group(0)):04X}"}
                )
    if kind == "css":
        check_css(text, clean, hit, is_token, "Generated by tokens/build.py --accent" in text)
    else:
        if path.suffix == ".html":
            styles = "".join(
                m.group(1) for m in re.finditer(r"<style[^>]*>(.*?)</style>", text, re.S)
            )
            if styles:
                check_css(styles, strip_comments(styles, "css"), hit, is_token, False)
        for m in check_script(text, clean, hit, is_token):
            accent_writes.append((rel, line_of(clean, m.start())))


# ------------------------------------------------------------------ driver


def load_config(argv):
    cfg = dict(DEFAULTS)
    root = pathlib.Path.cwd()
    cpath = None
    if "--config" in argv:
        cpath = pathlib.Path(argv[argv.index("--config") + 1]).resolve()
    else:
        cand = HERE.parent / "standards-local" / "ui-lint.json"
        if cand.is_file():
            cpath = cand
    if cpath:
        try:
            user = json.loads(cpath.read_text(encoding="utf8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"ui-lint: cannot read {cpath}: {e}")
            sys.exit(2)
        root = cpath.parent.parent if cpath.parent.name == "standards-local" else cpath.parent
        root = (root / user.get("root", ".")).resolve()
        for k in ("paths", "baseline"):
            if k in user:
                cfg[k] = user[k]
        cfg["exclude"] = DEFAULTS["exclude"] + user.get("exclude", [])
        cfg["token_files"] = DEFAULTS["token_files"] + user.get("token_files", [])
        cfg["data_palettes"] = list(user.get("data_palettes", []))
        cfg["_overlay"] = (
            cpath.parent.parent if cpath.parent.name == "standards-local" else cpath.parent
        )
    else:
        cfg["_overlay"] = HERE.parent
    positional = [
        a
        for a in argv
        if not a.startswith("--")
        and (argv.index(a) == 0 or argv[argv.index(a) - 1] not in ("--config", "--exception"))
    ]
    if positional:
        cfg["paths"] = positional
        root = pathlib.Path.cwd()
    return cfg, root


def collect(cfg, root):
    files = []
    for p in cfg["paths"]:
        base = (root / p).resolve()
        cands = [base] if base.is_file() else sorted(base.rglob("*")) if base.is_dir() else []
        for f in cands:
            if not f.is_file() or f.suffix not in EXTS:
                continue
            try:
                rel = f.relative_to(root).as_posix()
            except ValueError:
                rel = f.as_posix()
            if any(
                fnmatch.fnmatch(rel, g) or fnmatch.fnmatch("/" + rel, g) for g in cfg["exclude"]
            ):
                continue
            files.append((f, rel))
    return files


def run(cfg, root):
    root = root.resolve()
    active = active_exceptions(cfg["_overlay"])
    findings, accent_writes = [], []
    files = collect(cfg, root)
    for f, rel in files:
        lint_file(f, rel, root, cfg, active, findings, accent_writes)
    for rel, line in accent_writes[1:]:
        findings.append(
            {
                "rule": "UI007",
                "file": rel,
                "line": line,
                "detail": "data-app-accent set more than once",
            }
        )
    return files, findings, active


def counts(findings):
    out = {}
    for f in findings:
        k = f"{f['file']}::{f['rule']}"
        out[k] = out.get(k, 0) + 1
    return out


def self_test():
    import shutil
    import tempfile

    src = HERE / "fixtures"
    expected = json.loads((src / "expected.json").read_text(encoding="utf8"))
    fx = pathlib.Path(tempfile.mkdtemp()) / "fixtures"
    shutil.copytree(src, fx)
    # Written at run time so the repo itself stays plain ASCII: em dash, curly quotes, NBSP.
    (fx / "typo.tsx").write_text(
        "export const s = 'A\u2014B \u201cq\u201d\u00a0x';\n", encoding="utf8"
    )
    cfg = dict(DEFAULTS)
    cfg["exclude"] = ["**/expected.json"]
    cfg["_overlay"] = fx
    cfg["paths"] = ["."]
    cfg["data_palettes"] = ["**/data-palette.css"]
    files, findings, _ = run(cfg, fx)
    got = counts(findings)
    bad = []
    for k in sorted(set(expected) | set(got)):
        if expected.get(k, 0) != got.get(k, 0):
            bad.append(f"{k}: expected {expected.get(k, 0)}, got {got.get(k, 0)}")
    for b in bad:
        print(f"::error::self-test {b}")
    for f in findings:
        print(f"  {f['rule']} {f['file']}:{f['line']} {f['detail']}")
    bad += _self_test_baseline()
    print(
        f"ui-lint self-test: {len(files)} fixture file(s), {len(findings)} finding(s), {len(bad)} mismatch(es)"
    )
    return 1 if bad else 0


def _self_test_baseline():
    """A baseline is refused: a UI consumer fixes findings or records a named exception."""
    import contextlib
    import io
    import tempfile

    root = pathlib.Path(tempfile.mkdtemp())
    (root / "standards-local").mkdir()
    (root / "src").mkdir()
    (root / "src" / "a.css").write_text(".a { color: var(--text-primary); }\n")
    cfg_file = root / "standards-local" / "ui-lint.json"
    steps = []
    for name, cfg, want in (
        ("clean, no baseline", {"paths": ["src"]}, 0),
        ("clean, baseline set", {"paths": ["src"], "baseline": "standards-local/base.json"}, 1),
    ):
        cfg_file.write_text(json.dumps(cfg))
        with contextlib.redirect_stdout(io.StringIO()):
            steps.append((name, main(["--config", str(cfg_file)]), want))
    return [
        f'baseline step "{name}": exit {got}, expected {want}'
        for name, got, want in steps
        if got != want
    ]


def main(argv):
    if "--self-test" in argv:
        return self_test()
    cfg, root = load_config(argv)
    files, findings, active = run(cfg, root)
    now = counts(findings)
    baseline_set = bool(cfg.get("baseline"))
    base_msg = (
        "a baseline is not allowed for a UI consumer (web-ui.md 0.11). Fix the findings, or record a named "
        "exception (owner, reason, review date) in standards-local/exceptions.md and mark the line with "
        'core-exception. Remove "baseline" from ui-lint.json'
    )

    if "--json" in argv:
        print(
            json.dumps(
                {
                    "files": len(files),
                    "findings": findings,
                    "over_baseline": now,
                    "fixed_since_baseline": 0,
                    "baseline_set": baseline_set,
                    "rules": {k: v[0] for k, v in RULES.items()},
                    "refs": {k: v[1] for k, v in RULES.items()},
                },
                indent=2,
            )
        )
    else:
        for f in findings:
            title, ref, why = RULES[f["rule"]]
            print(
                f"::error file={f['file']},line={f['line']}::{f['rule']} {title} ({ref}): {f['detail']}. Not allowed: {why}."
            )
        if baseline_set:
            print(f"::error::ui-lint: {base_msg}.")
        by_rule = {}
        for f in findings:
            by_rule[f["rule"]] = by_rule.get(f["rule"], 0) + 1
        summary = ", ".join(f"{k} {v}" for k, v in sorted(by_rule.items())) or "none"
        print(f"ui-lint: {len(files)} file(s), {len(findings)} finding(s) [{summary}]")
    return 1 if findings or baseline_set else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
