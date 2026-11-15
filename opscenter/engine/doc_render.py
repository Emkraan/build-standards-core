#!/usr/bin/env python3
"""
doc_render.py - render repo markdown docs into HTML pages for the docs home.

Date:    2026-11-06
Purpose: The documentation standard keeps the repo as the engineering source and generates the docs home pages from it. This module
         turns a markdown file (or a section of one) into the HTML a docs home accepts, enforces text rules (ASCII only, no semicolons
         in prose), and stamps each page with the repo path and commit it was generated from. Code blocks and inline code are kept
         byte-exact apart from ASCII normalization, because they are commands people copy. The footer panel uses the storage
         format's `data-type="panel-info"` markup; another docs home changes `stamp()` only.

Configuration (optional): DOC_RENDER_INTERNAL_TERMS, a JSON list of lowercase terms that must not appear in a published page
         (internal tool or path names); `sanitize_check` reports each one. Default none.

Library use: from doc_render import render, section, sanitize_check, stamp
CLI:         doc_render.py <markdown-file> [--from "<heading>"] [--to "<heading>"]
"""

import html
import json
import os
import re
import sys

ASCII_MAP = {
    "\u2014": " - ",
    "\u2013": "-",
    "\u2026": "...",
    "\u2192": "->",
    "\u2190": "<-",
    "\u2264": "<=",
    "\u2265": ">=",
    "\u2502": "|",
    "\u2500": "-",
    "\u250c": "+",
    "\u2510": "+",
    "\u2514": "+",
    "\u2518": "+",
    "\u251c": "+",
    "\u2524": "+",
    "\u25bc": "v",
    "\u25b2": "^",
    "\u26a0": "WARNING:",
    "\u2705": "[OK]",
    "\u274c": "[X]",
    "\ufe0f": "",
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u00a0": " ",
    "\u2022": "-",
    "\u00d7": "x",
    "\u00b7": "-",
    "\u21d2": "=>",
    "\u222a": "union",
}


def to_ascii(text):
    for k, v in ASCII_MAP.items():
        text = text.replace(k, v)
    return text


def prose(text):
    """Text rules for prose: ASCII plus no semicolons (a comma reads closest)."""
    return re.sub(r"\s*;\s*", ", ", to_ascii(text))


def inline(text):
    """Render inline markdown (code spans, links, bold, italics) to HTML. Code spans become
    placeholders first so bold or links that wrap code still pair up."""
    codes = []

    def keep(m):
        codes.append("<code>" + html.escape(to_ascii(m.group(1)), quote=False) + "</code>")
        return f"\x00{len(codes) - 1}\x00"

    s = re.sub(r"`([^`]+)`", keep, text)
    s = html.escape(prose(s), quote=False)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', s)
    s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r"\1", s)  # relative repo links become plain text
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r"(?<![\w_\x00])_(?!\s)(.+?)(?<!\s)_(?![\w_])", r"<em>\1</em>", s)
    s = re.sub(r" {2,}", " ", s)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], s)


def section(md, start=None, end=None):
    """Lines from the heading matching `start` (inclusive) up to the next heading matching `end`."""
    lines = md.splitlines()
    i = 0
    if start:
        rx = re.compile(start)
        i = next((n for n, ln in enumerate(lines) if ln.startswith("#") and rx.search(ln)), None)
        if i is None:
            raise ValueError(f"heading not found: {start}")
    j = len(lines)
    if end:
        rx = re.compile(end)
        j = next(
            (n for n, ln in enumerate(lines) if n > i and ln.startswith("#") and rx.search(ln)),
            len(lines),
        )
    return "\n".join(lines[i:j])


def _table(rows):
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    head, body = cells[0], [r for r in cells[2:]]
    h = (
        "<table><thead><tr>"
        + "".join(f"<th>{inline(c)}</th>" for c in head)
        + "</tr></thead><tbody>"
    )
    for r in body:
        h += "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>"
    return h + "</tbody></table>"


def render(md, top=2, drop_h1=True):
    """Markdown to HTML. The shallowest heading in the input becomes <h{top}>."""
    lines = md.replace("\r\n", "\n").split("\n")
    levels, in_fence = [], False
    for ln in lines:
        if re.match(r"^\s*```", ln):
            in_fence = not in_fence
            continue
        m = None if in_fence else re.match(r"^(#{1,6})\s", ln)
        if m:
            levels.append(len(m.group(1)))
    if drop_h1 and levels and levels[0] == 1:
        levels = levels[1:]
    shift = (min(levels) - top) if levels else 0
    out = []
    para = []
    list_stack = []  # (indent, tag)
    i = 0

    def flush_para():
        if para:
            out.append("<p>" + inline(" ".join(s.strip() for s in para)) + "</p>")
            para.clear()

    def close_lists(to_indent=-1):
        while list_stack and list_stack[-1][0] > to_indent:
            out.append(f"</li></{list_stack.pop()[1]}>")

    while i < len(lines):
        ln = lines[i]
        fence = re.match(r"^(\s*)```(\w*)", ln)
        if fence:
            flush_para()
            close_lists()
            lang = fence.group(2) or "text"
            body = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                body.append(
                    lines[i][len(fence.group(1)) :]
                    if lines[i].startswith(fence.group(1))
                    else lines[i]
                )
                i += 1
            code = html.escape(to_ascii("\n".join(body)), quote=False)
            out.append(f'<pre><code class="language-{lang.lower()}">{code}</code></pre>')
            i += 1
            continue
        h = re.match(r"^(#{1,6})\s+(.*)$", ln)
        if h:
            flush_para()
            close_lists()
            lvl = len(h.group(1))
            if lvl == 1 and drop_h1:
                i += 1
                continue
            lvl = max(1, min(6, lvl - shift))
            out.append(f"<h{lvl}>{inline(h.group(2).strip())}</h{lvl}>")
            i += 1
            continue
        if (
            ln.strip().startswith("|")
            and i + 1 < len(lines)
            and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1])
        ):
            flush_para()
            close_lists()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append(_table(rows))
            continue
        if re.match(r"^\s*(---+|\*\*\*+)\s*$", ln):
            flush_para()
            close_lists()
            out.append("<hr>")
            i += 1
            continue
        if ln.startswith(">"):
            flush_para()
            close_lists()
            quote = []
            while i < len(lines) and lines[i].startswith(">"):
                quote.append(lines[i][1:].strip())
                i += 1
            out.append('<div data-type="panel-note"><p>' + inline(" ".join(quote)) + "</p></div>")
            continue
        li = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", ln)
        if li:
            flush_para()
            indent = len(li.group(1))
            tag = "ol" if li.group(2)[0].isdigit() else "ul"
            if list_stack and indent < list_stack[-1][0]:
                close_lists(indent)
            if not list_stack or indent > list_stack[-1][0]:
                out.append(f"<{tag}><li>")
                list_stack.append((indent, tag))
            else:
                out.append("</li><li>")
            text = [li.group(3)]
            i += 1
            while (
                i < len(lines)
                and lines[i].strip()
                and not re.match(r"^\s*([-*+]|\d+[.)])\s+", lines[i])
                and not lines[i].strip().startswith(("```", "|", "#", ">"))
                and lines[i].startswith(" ")
            ):
                text.append(lines[i].strip())
                i += 1
            out.append(inline(" ".join(text)))
            continue
        if not ln.strip():
            flush_para()
            if list_stack:
                nxt = next((x for x in lines[i + 1 :] if x.strip()), "")
                if not re.match(r"^\s*([-*+]|\d+[.)])\s+", nxt) and not nxt.startswith(" "):
                    close_lists()
            i += 1
            continue
        if list_stack and ln.startswith(" "):
            out.append("<br>" + inline(ln.strip()))
            i += 1
            continue
        close_lists()
        para.append(ln)
        i += 1
    flush_para()
    close_lists()
    # A doc that ends (or starts) with a --- rule would stack against the stamp() rule,
    # and back-to-back rules render as a double line. Trim edge rules, collapse repeats.
    while out and out[-1] == "<hr>":
        out.pop()
    while out and out[0] == "<hr>":
        out.pop(0)
    out = [x for k, x in enumerate(out) if not (x == "<hr>" and k and out[k - 1] == "<hr>")]
    return "\n".join(out)


def stamp(repo, paths, commit, home="the docs home"):
    """Verification footer. Starts with its own rule, so callers must not end the body with one. The docs home is the documentation
    record, never the repo, so the footer names what the page was verified against and never calls the repo the source."""
    files = ", ".join(f"<code>{html.escape(p)}</code>" for p in paths)
    return (
        '<hr><div data-type="panel-info"><p>This page is the documentation record and is maintained '
        f"in {html.escape(home)}. Last verified against "
        f"{html.escape(repo)} {files} at commit <code>{html.escape(commit)}</code>.</p></div>"
    )


def _internal_terms():
    try:
        d = json.loads(os.environ.get("DOC_RENDER_INTERNAL_TERMS") or "[]")
    except ValueError:
        return []
    return [str(x).lower() for x in d] if isinstance(d, list) else []


def sanitize_check(body):
    """Return a list of problems that would break the text rules or leak internal tooling."""
    probs = []
    if re.search(r"<hr\s*/?>\s*<hr\s*/?>", body):
        probs.append("back-to-back <hr> (renders as a double line)")
    bad = sorted({c for c in body if ord(c) > 127})
    if bad:
        probs.append(f"non-ASCII: {bad[:10]}")
    text = re.sub(r"<pre>.*?</pre>|<code>.*?</code>", "", body, flags=re.S)
    if ";" in re.sub(r"&\w+;|&#\d+;", "", text):
        probs.append("semicolon in prose")
    for w in _internal_terms():
        if w in body.lower():
            probs.append(f"internal reference: {w}")
    return probs


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    with open(sys.argv[1]) as fh:
        src = fh.read()
    a = sys.argv[2:]
    start = a[a.index("--from") + 1] if "--from" in a else None
    end = a[a.index("--to") + 1] if "--to" in a else None
    body = render(section(src, start, end))
    print(body)
    for p in sanitize_check(body):
        print("PROBLEM:", p, file=sys.stderr)
