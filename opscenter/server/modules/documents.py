"""
documents.py
Purpose: Local documents a row or a plan entry can link to, served read only from folders the consumer names and nowhere else. A page
         row (`doc`) or a library entry (`path`) holds a file path, the core checks it, and the link it draws points at one route here.
Date:    2026-11-25
Settings: OPSCENTER_DOCUMENT_ROOTS   the folders documents may be served from, separated by the platform path separator (`:` on macOS and
          Linux). Unset or empty: the feature is off, no route exists and a path is never turned into a link.
Rules:   A document is served only when all of these hold, checked again on every request and never taken from the browser as a path.
         1 the real path (links followed) is inside one root, so a link or `..` cannot leave it
         2 no part of the path under the root starts with a dot
         3 it is a regular file with one of the types below, at most 50 MB
         The address names a root by number and a path under it, so the browser never learns where a root lives. A file is sent with its own
         content type only for pdf and plain text types. Every other type is sent as a download. Html, svg and scripts are not on the list,
         so a document can never run in the ops center's own origin.
API:     roots() -> [Path]   resolve(path) -> (root number, relative path) or None   link_for(path) -> address or None
         register(registry)  adds GET /api/documents/file?root=<n>&path=<relative path>
"""

import mimetypes
import os
import re
import urllib.parse
from pathlib import Path

MAX_BYTES = 50 * 1024 * 1024
MAX_ROOTS = 8
MAX_PATH = 400
ROUTE = "/api/documents/file"

# extension -> (content type, shown in the browser). Anything not here is refused.
TYPES = {
    ".pdf": ("application/pdf", True),
    ".txt": ("text/plain; charset=utf-8", True),
    ".md": ("text/plain; charset=utf-8", True),
    ".csv": ("text/plain; charset=utf-8", True),
    ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", False),
    ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", False),
    ".pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", False),
    ".doc": ("application/msword", False),
    ".xls": ("application/vnd.ms-excel", False),
    ".ppt": ("application/vnd.ms-powerpoint", False),
}


def roots():
    """The resolved folders documents may come from, at most eight, in the order they were named. Empty when the setting is off."""
    out = []
    for part in (os.environ.get("OPSCENTER_DOCUMENT_ROOTS") or "").split(os.pathsep):
        part = part.strip()
        if not part:
            continue
        try:
            p = Path(part).expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if p.is_dir() and p not in out:
            out.append(p)
    return out[:MAX_ROOTS]


def _inside(root, rel):
    """The real file `rel` names under `root`, or None. `rel` is relative and is never trusted: the result is resolved and compared."""
    if not rel or "\x00" in rel or len(rel) > MAX_PATH:
        return None
    parts = Path(rel).parts
    if Path(rel).is_absolute() or any(p.startswith(".") or p == ".." for p in parts):
        return None
    try:
        real = (root / rel).resolve(strict=True)
        under = real.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None
    if any(p.startswith(".") for p in under.parts):
        return None
    try:
        if not real.is_file() or real.stat().st_size > MAX_BYTES:
            return None
    except OSError:
        return None
    return real if real.suffix.lower() in TYPES else None


def resolve(path):
    """(root number, relative path) for a document a consumer named, or None. `path` is relative to a root or absolute inside one."""
    text = str(path or "").strip()
    if not text or "\x00" in text or len(text) > MAX_PATH:
        return None
    found = roots()
    if Path(text).is_absolute():
        try:
            real = Path(text).resolve(strict=True)
        except (OSError, RuntimeError):
            return None
        for n, root in enumerate(found):
            try:
                rel = real.relative_to(root).as_posix()
            except ValueError:
                continue
            if _inside(root, rel):
                return n, rel
        return None
    for n, root in enumerate(found):
        if _inside(root, text):
            return n, Path(text).as_posix()
    return None


def link_for(path):
    """The address that serves a document, or None when it is not one the roots allow. Safe to put in an href."""
    got = resolve(path)
    if not got:
        return None
    return f"{ROUTE}?root={got[0]}&path={urllib.parse.quote(got[1], safe='/')}"


def is_link(value):
    """True for an address this module made. The client and the server both use it to tell a document address from a web address."""
    return (
        isinstance(value, str)
        and re.match(r"^" + re.escape(ROUTE) + r"\?root=\d&path=[^\s]+$", value) is not None
    )


def read(root_number, rel):
    """(name, content type, shown in the browser, bytes) or raises KeyError for anything that is not an allowed document."""
    found = roots()
    if not 0 <= root_number < len(found):
        raise KeyError("no such document")
    real = _inside(found[root_number], rel)
    if real is None:
        raise KeyError("no such document")
    ctype, inline = TYPES[real.suffix.lower()]
    with open(real, "rb") as fh:
        data = fh.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise KeyError("no such document")
    return (
        real.name,
        ctype or mimetypes.guess_type(real.name)[0] or "application/octet-stream",
        inline,
        data,
    )


def register(r):
    def serve(q):
        try:
            number = int(q.arg("root"))
        except ValueError:
            raise ValueError("root must be a whole number") from None
        name, ctype, inline, data = read(number, q.arg("path"))
        safe = re.sub(r"[^A-Za-z0-9._ -]", "_", name)[:120]
        kind = "inline" if inline else "attachment"
        extra = {"Content-Disposition": f'{kind}; filename="{safe}"'}
        return 200, data, ctype, extra

    r.add("GET", ROUTE, serve, name="documents.file")
