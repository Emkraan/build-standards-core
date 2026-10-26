#!/usr/bin/env python3
"""Fail if anything that ships to a consumer names the core's owner account or repo.

Shipped means the folders and files an overlay copies (standards, tokens, lint, kit/src, the overlay
template, kit/scripts/gen-changelog.mjs) and the Hermes skills. A consumer must never learn which
account owns the core, so those paths may not contain the owner login or a core repo slug.

The owner comes from the origin remote of this clone, plus any terms in CORE_PRIVATE_DENYLIST or
~/.config/build-standards-core/denylist.txt. Run from the repo root. Exit 1 on a hit.

File mode: `check-consumer-neutral.py --file PATH ...` checks the given files (any path, not only
shipped ones) against the same terms, so a text can be checked before it is posted. Terms match whole
words only, so a term never hits inside an ordinary word.

Diff mode: `check-consumer-neutral.py --diff BASE` checks only the lines `git diff BASE...HEAD` adds to
shipped paths, and `--staged` only the staged ones. A hit already in a shipped file is not the change's to
fix; a new hit on an added line fails. The pre-commit hook uses `--staged`; CI runs `--diff` against the
pull request's base commit, so a commit made with `--no-verify` is caught there. With no argument the
whole shipped tree is checked (the default, and what the periodic sweep runs); that mode is unchanged.

Report screenshots and moved tables: in file mode only, the account login inside a raw gist URL
of an image or a markdown file
(`https://gist.githubusercontent.com/<login>/<gist id>/raw/<file>.png` or `.../raw/<file>.md`)
is the one allowed account name. It is the login of the account that posts the report, already public as the issue's author, so
the report skill hosts its layout-only screenshots and the tables it moves out of an oversized body
that way (CONTRIBUTING.md, "Sanitising
evidence"). The rest of the URL and everything else on the line is still checked. Shipped files
never get this allowance.
"""

import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import diffadded  # noqa: E402

SHIPPED = (
    "standards/",
    "tokens/",
    "lint/",
    "kit/src/",
    "kit/scripts/gen-changelog.mjs",
    "kit/scripts/scope-css.mjs",
    "kit/scripts/build-registry.mjs",
    "templates/overlay/",
    "hermes/skills/",
    "skills/",
)


def git(*a):
    return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True).stdout


def owner_terms():
    terms = set()
    url = git("remote", "get-url", "origin").strip().removesuffix(".git")
    m = re.search(r"github\.com[:/]+([^/]+)/([^/]+)$", url)
    if m:
        terms.update({m.group(1).lower(), f"{m.group(1)}/{m.group(2)}".lower()})
    for src in (
        os.environ.get("CORE_PRIVATE_DENYLIST", ""),
        str(pathlib.Path.home() / ".config/build-standards-core/denylist.txt"),
    ):
        if src and pathlib.Path(src).is_file():
            for line in pathlib.Path(src).read_text(encoding="utf8").splitlines():
                if line.strip() and not line.startswith("#"):
                    terms.add(line.strip().lower())
    return terms


# The one allowed account name in a report file: the login segment of a raw gist image or
# moved-table (.md) URL.
GIST_RAW = re.compile(
    r"(https://gist\.githubusercontent\.com/)[A-Za-z0-9-]+(/[0-9a-f]{20,40}/raw/[A-Za-z0-9._/-]+\.(?:png|jpg|jpeg|gif|webp|md))"
)


def mask_gist_logins(text):
    return GIST_RAW.sub(r"\1login\2", text)


def main():
    terms = owner_terms()
    hits = []
    base, staged, _rest = diffadded.parse_args(sys.argv[1:])
    if base is not None or staged:
        added = diffadded.added_lines(ROOT, base, staged)
        for rel, lines in sorted(added.items()):
            if not rel.startswith(SHIPPED):
                continue
            for n, line in lines:
                low = line.lower()
                for t in terms:
                    if re.search(r"(?<![a-z0-9-])" + re.escape(t) + r"(?![a-z0-9-])", low):
                        hits.append(f"{rel}:{n}: names the core source ({t})")
        print("\n".join(hits))
        print(
            f"check-consumer-neutral: {len(hits)} hit(s), {len(terms)} term(s) checked"
            " (diff mode: added lines only)"
        )
        sys.exit(1 if hits else 0)
    if sys.argv[1:2] == ["--file"]:
        paths = sys.argv[2:]
        if not paths:
            sys.exit("check-consumer-neutral: --file needs a path")
    else:
        paths = [r for r in git("ls-files").splitlines() if r.startswith(SHIPPED)]
    for rel in paths:
        p = pathlib.Path(rel) if sys.argv[1:2] == ["--file"] else ROOT / rel
        try:
            text = p.read_text(encoding="utf8")
            text = (mask_gist_logins(text) if sys.argv[1:2] == ["--file"] else text).lower()
        except (UnicodeDecodeError, OSError):
            continue
        for t in terms:
            if re.search(r"(?<![a-z0-9-])" + re.escape(t) + r"(?![a-z0-9-])", text):
                hits.append(f"{rel}: names the core source ({t})")
    print("\n".join(hits))
    print(f"check-consumer-neutral: {len(hits)} hit(s), {len(terms)} term(s) checked")
    sys.exit(1 if hits else 0)


if __name__ == "__main__":
    main()
