#!/usr/bin/env python3
"""Fail if any tracked file names a specific business or carries a real email address.

Terms come from checks/denylist.sha256 (shared) plus any private denylists a contributor keeps
outside the repo, so the shared file does not have to name every business:
  - the file named by the CORE_PRIVATE_DENYLIST environment variable
  - ~/.config/build-standards-core/denylist.txt
The shared file holds only the sha256 of each lowercased term, so it never names what it protects;
every span of one to four words in a line is hashed and compared, and a shared hit is reported by
place only. Private lists hold one plain term per line. Matching is case-insensitive and on word
boundaries (so a short name does not hit inside an ordinary word). Blank lines and # comments are
ignored. `check-sanitised.py --hash TERM` prints the line to add to the shared file.
Email addresses are allowed only for GitHub noreply (including noreply@github.com), example.com,
example.org, example.net and the .invalid TLD.

File mode: `check-sanitised.py --file PATH ...` checks the given files instead of git ls-files, so a
text (an issue body, a report) can be checked before it is posted. Same terms, same boundaries.

Report screenshots and moved tables: in file mode only, the account login inside a raw gist URL
of an image or a markdown file
(`https://gist.githubusercontent.com/<login>/<gist id>/raw/<file>.png` or `.../raw/<file>.md`)
is the one allowed account name. It is the login of the account that posts the report, already public as the issue's author, so
the report skill hosts its layout-only screenshots and the tables it moves out of an oversized body
that way (CONTRIBUTING.md, "Sanitising
evidence"). The rest of the URL and everything else on the line is still checked. Shipped files
never get this allowance.
"""

import hashlib
import os
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).parent
SHARED = HERE / "denylist.sha256"
SOURCES = [
    pathlib.Path(os.environ.get("CORE_PRIVATE_DENYLIST", "/nonexistent")),
    pathlib.Path.home() / ".config" / "build-standards-core" / "denylist.txt",
]
WORD = re.compile(r"[a-z0-9]+")
SPAN = 4  # longest shared term, in words


def digest(term):
    return hashlib.sha256(term.strip().lower().encode("utf8")).hexdigest()


def shared_hashes():
    if not SHARED.is_file():
        return set()
    return {
        ln.strip()
        for ln in SHARED.read_text(encoding="utf8").splitlines()
        if ln.strip() and not ln.startswith("#")
    }


def shared_hit(low, hashes):
    """True when a span of one to SPAN whole words in the lowercased line hashes to a shared term."""
    if not hashes:
        return False
    words = [(m.start(), m.end()) for m in WORD.finditer(low)]
    for i in range(len(words)):
        for j in range(i, min(i + SPAN, len(words))):
            if hashlib.sha256(low[words[i][0] : words[j][1]].encode("utf8")).hexdigest() in hashes:
                return True
    return False


EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})")
ALLOWED_DOMAINS = ("users.noreply.github.com", "example.com", "example.org", "example.net")


def terms():
    out = []
    for src in SOURCES:
        if src.is_file():
            for line in src.read_text(encoding="utf8").splitlines():
                t = line.strip().lower()
                if t and not t.startswith("#"):
                    out.append((t, re.compile(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])")))
    return out


# The one allowed account name in a report file: the login segment of a raw gist image or
# moved-table (.md) URL.
GIST_RAW = re.compile(
    r"(https://gist\.githubusercontent\.com/)[A-Za-z0-9-]+(/[0-9a-f]{20,40}/raw/[A-Za-z0-9._/-]+\.(?:png|jpg|jpeg|gif|webp|md))"
)


def mask_gist_logins(text):
    return GIST_RAW.sub(r"\1login\2", text)


IDENTITY_FILES = ("LICENSE", "renovate.json", ".github/workflows/automerge.yml")


def main():
    if sys.argv[1:2] == ["--hash"]:
        if len(sys.argv) < 3:
            sys.exit("check-sanitised: --hash needs a term")
        print(digest(" ".join(sys.argv[2:])))
        return
    deny = terms()
    hashes = shared_hashes()
    bad = []
    file_mode = sys.argv[1:2] == ["--file"]
    if file_mode:
        files = sys.argv[2:]
        if not files:
            sys.exit("check-sanitised: --file needs a path")
    else:
        files = subprocess.run(
            ["git", "ls-files", "-co", "--exclude-standard"], capture_output=True, text=True
        ).stdout.split("\n")
    for f in files:
        if not f or f.startswith("checks/denylist") or not pathlib.Path(f).is_file():
            continue
        # Repo identity files name their owner by necessity, not as business content: the licence names its
        # copyright holder, renovate.json extends the owning org's shared config, and automerge.yml calls the
        # org's reusable merge workflow. They are the only files
        # exempt from the term lists (owner decisions 2026-10-24).
        if not file_mode and f in IDENTITY_FILES:
            continue
        try:
            lines = pathlib.Path(f).read_text(encoding="utf8").split("\n")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(lines, 1):
            if file_mode:
                line = mask_gist_logins(line)
            low = line.lower()
            if shared_hit(low, hashes):
                bad.append(f"::error file={f},line={i}::business-specific term (shared list)")
            for _d, rx in deny:
                if rx.search(low):
                    bad.append(f"::error file={f},line={i}::business-specific term (private list)")
            for m in EMAIL.finditer(line):
                dom = m.group(1).lower()
                if m.group(0).lower() == "noreply@github.com":
                    continue
                if not (dom.endswith(ALLOWED_DOMAINS) or dom.endswith(".invalid")):
                    bad.append(f"::error file={f},line={i}::email address on domain {dom}")
    print("\n".join(bad))
    print(
        f"check-sanitised: {len(bad)} hit(s), {len(hashes)} shared and {len(deny)} private term(s) checked"
    )
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
