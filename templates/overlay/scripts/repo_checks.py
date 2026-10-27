#!/usr/bin/env python3
"""Repo checks: static proofs of standards rules that a repo's own files can show, run by core-status.

Usage:
  python3 scripts/repo_checks.py [--root DIR] [--json]    run every check against a repo (default: the
                                                          repository around the current directory)
  python3 scripts/repo_checks.py --list                   print each check id and the rule it proves

A rule whose registry check is {"kind": "repo-check", "id": "RC0nn"} is proved by the check of that id:
no finding means pass, a finding means fail (or excepted while an active exception names the rule).
Every check is a pure read of the repo's tracked files. A check passes when the repo has nothing the rule
governs (no migrations, no deploy workflow) and fails only on a violation or, where the rule demands a
thing to exist, on its absence. A line carrying `core-exception: EXC-NNN` is skipped, the same marker the
lints honour; `scripts/check-exceptions.py` validates the id. Standard library only, Python 3.9.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys

# Synced copies of the core and build output are not the repo's own code.
SKIP_DIRS = {
    ".git",
    "node_modules",
    "standards-core",
    "kit-core",
    "lint-core",
    "tokens-core",
    "dist",
    "build",
    ".venv",
    "venv",
    "__pycache__",
    ".next",
    ".turbo",
}
MARK = "core-exception:"
TEST_PART = re.compile(
    r"(^|/)(tests?|__tests__|e2e|spec)(/|$)"
    r"|\.(test|spec)\.[A-Za-z]+$"
    r"|(^|/)(test_[^/]*|[^/]*_test|conftest)\.py$"
)


class Repo:
    """The tracked files of a repo (git), or its files on disk when it is not a git work tree."""

    def __init__(self, root):
        self.root = pathlib.Path(root).resolve()
        self.paths = self._list()
        self._cache = {}

    def _list(self):
        try:
            top = subprocess.run(
                ["git", "-C", str(self.root), "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            if pathlib.Path(top).resolve() != self.root:
                raise OSError("not the root of a work tree")
            r = subprocess.run(
                ["git", "-C", str(self.root), "ls-files", "-z"],
                capture_output=True,
                text=True,
                check=True,
            )
            names = [n for n in r.stdout.split("\0") if n]
        except (OSError, subprocess.CalledProcessError):
            names = []
            for dp, dns, fns in os.walk(self.root):
                dns[:] = [d for d in dns if d not in SKIP_DIRS]
                for f in fns:
                    names.append(
                        os.path.relpath(os.path.join(dp, f), self.root).replace(os.sep, "/")
                    )
        keep = []
        for n in names:
            if set(n.split("/")[:-1]) & SKIP_DIRS:
                continue
            if (self.root / n).is_file():
                keep.append(n)
        return sorted(keep)

    def text(self, rel):
        if rel not in self._cache:
            try:
                data = (self.root / rel).read_bytes()
                self._cache[rel] = data.decode("utf8") if b"\0" not in data[:4096] else ""
            except (OSError, UnicodeDecodeError):
                self._cache[rel] = ""
        return self._cache[rel]

    def select(self, *, exts=(), names=(), under=None, tests=True):
        out = []
        for p in self.paths:
            base = p.rsplit("/", 1)[-1]
            if exts and not p.lower().endswith(tuple(exts)) and base not in names:
                continue
            if not exts and names and base not in names:
                continue
            if under and not p.startswith(under):
                continue
            if not tests and TEST_PART.search(p):
                continue
            out.append(p)
        return out

    def workflows(self):
        return [
            p
            for p in self.paths
            if re.match(r"^\.github/(workflows|actions)/.+\.ya?ml$", p)
            or re.match(r"^\.github/actions/.+/action\.ya?ml$", p)
        ]


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def skipped(lines, i):
    """True when line i (0-based) or the line above carries the exception marker."""
    return MARK in lines[i] or (i > 0 and MARK in lines[i - 1])


def is_comment(line):
    return bool(re.match(r"^\s*(#|//|\*|/\*)", line))


# ---------------------------------------------------------------- RC001 kill only your own processes

# The names are split so this file, synced into every overlay, does not match its own check.
KILL = re.compile(
    r"\b(?:p" + "kill|kill" + r"all)\b"
    r"|\bkill\b[^\n]*\$\(\s*(?:pgrep|pidof)\b"
    r"|\bpgrep\b[^\n|]*\|\s*xargs\s+(?:-\S+\s+)*kill\b"
    r"|\btaskkill\b[^\n]*\s/IM\b"
    r"|Stop-Process\s+-Name\b",
    re.I,
)
KILL_EXTS = (
    ".sh",
    ".bash",
    ".zsh",
    ".py",
    ".ps1",
    ".psm1",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".yml",
    ".yaml",
    ".mk",
)


def rc001(repo):
    out = []
    for p in repo.select(exts=KILL_EXTS, names=("Makefile", "Dockerfile")):
        lines = repo.text(p).splitlines()
        for i, ln in enumerate(lines):
            if is_comment(ln) or skipped(lines, i):
                continue
            if KILL.search(ln):
                out.append(
                    (
                        p,
                        i + 1,
                        "kills by process name or pattern; stop a recorded process id instead",
                    )
                )
    return out


# ---------------------------------------------------------------- RC002 merges are pinned to the reviewed head

GH_MERGE = re.compile(r"\bgh\s+pr\s+merge\b(?:[^\n\\]|\\.)*", re.S)
GH_API_MERGE = re.compile(
    r"\bgh\s+api\b(?:[^\n\\]|\\.)*/pulls/[^\s\"']*/merge(?:[^\n\\]|\\.)*", re.S
)
LIST_MERGE = re.compile(r"[\"']pr[\"']\s*,\s*[\"']merge[\"']")
REST_MERGE = re.compile(r"/pulls/[^\"'\s`]*/merge\b")
MERGE_EXTS = (".yml", ".yaml", ".sh", ".bash", ".py", ".js", ".mjs", ".cjs", ".ts")


def rc002(repo):
    out = []
    for p in repo.select(exts=MERGE_EXTS, tests=False):
        raw = "\n".join("" if is_comment(ln) else ln for ln in repo.text(p).splitlines())
        if not re.search(r"merge", raw):
            continue
        lines = repo.text(p).splitlines()

        def ok_at(pos, raw=raw, lines=lines):
            i = line_of(raw, min(pos, len(raw))) - 1
            return i < len(lines) and skipped(lines, i)

        for m in GH_MERGE.finditer(raw):
            if "--match-head-commit" not in m.group(0) and not ok_at(m.start()):
                out.append((p, line_of(raw, m.start()), "gh pr merge without --match-head-commit"))
        for m in GH_API_MERGE.finditer(raw):
            if not re.search(r"\bsha\b\s*[=:]|\"sha\"", m.group(0)) and not ok_at(m.start()):
                out.append((p, line_of(raw, m.start()), "merge endpoint call without the head sha"))
        for rx, need, what in (
            (LIST_MERGE, "match-head-commit", "merge command list without --match-head-commit"),
            (REST_MERGE, "sha", "merge request without the head sha"),
        ):
            if rx is REST_MERGE and p.endswith((".yml", ".yaml", ".sh", ".bash")):
                continue
            for m in rx.finditer(raw):
                if need not in raw[m.start() : m.end() + 400] and not ok_at(m.start()):
                    out.append((p, line_of(raw, m.start()), what))
    return out


# ---------------------------------------------------------------- RC003 major updates never auto-merge

RENOVATE_FILES = (
    "renovate.json",
    "renovate.json5",
    ".renovaterc",
    ".renovaterc.json",
    ".renovaterc.json5",
    ".github/renovate.json",
    ".github/renovate.json5",
    ".gitlab/renovate.json",
)


def _json_loose(text):
    """Parse JSON, tolerating json5 line comments and trailing commas; None when it still fails."""
    try:
        return json.loads(text)
    except ValueError:
        pass
    t = re.sub(r"(?m)^\s*//.*$", "", text)
    t = re.sub(r",(\s*[}\]])", r"\1", t)
    try:
        return json.loads(t)
    except ValueError:
        return None


def _rule_blocks_major(rule):
    types = rule.get("matchUpdateTypes")
    return isinstance(types, list) and "major" in types


def rc003(repo):
    out = []
    for p in repo.paths:
        if p not in RENOVATE_FILES:
            continue
        cfg = _json_loose(repo.text(p))
        if not isinstance(cfg, dict):
            out.append(
                (
                    p,
                    1,
                    "the renovate config cannot be read as JSON, so major auto-merge cannot be ruled out",
                )
            )
            continue
        rules = [r for r in cfg.get("packageRules", []) if isinstance(r, dict)]
        for r in rules:
            if _rule_blocks_major(r) and r.get("automerge") is True:
                out.append((p, 1, "a packageRule auto-merges major updates"))
        major_off = (
            isinstance(cfg.get("major"), dict) and cfg["major"].get("automerge") is False
        ) or any(_rule_blocks_major(r) and r.get("automerge") is False for r in rules)
        if cfg.get("automerge") is True and not major_off:
            out.append(
                (
                    p,
                    1,
                    "automerge is on for every update type and no rule turns it off for major updates",
                )
            )
    return out


# ---------------------------------------------------------------- RC004 the merge gate never runs PR code

PR_REF = re.compile(
    r"github\.event\.pull_request\.head\.(?:sha|ref|repo)|github\.head_ref|refs/pull/|pull/[^\s/]*/(?:head|merge)"
    r"|github\.event\.workflow_run\.head_(?:sha|branch|repository)|github\.event\.issue\.pull_request"
)
UNTRUSTED_TRIGGER = re.compile(
    r"(?m)^\s*(?:-\s*)?(pull_request_target|issue_comment|workflow_run)\s*:?\s*(?:$|\[|#)"
)


def rc004(repo):
    out = []
    for p in repo.workflows():
        text = repo.text(p)
        head = text.split("\njobs:", 1)[0]
        if not UNTRUSTED_TRIGGER.search(head) and not re.search(
            r"on:\s*\[[^\]]*(pull_request_target|issue_comment)", head
        ):
            continue
        lines = text.splitlines()
        for i, ln in enumerate(lines):
            if is_comment(ln) or skipped(lines, i):
                continue
            checkout = re.match(r"^\s*(ref|repository)\s*:\s*(.*)$", ln) and PR_REF.search(ln)
            command = re.search(
                r"\bgh\s+pr\s+checkout\b|\bgit\s+(?:fetch|checkout|merge|pull)\b[^\n]*", ln
            ) and PR_REF.search(ln)
            if checkout or command or re.search(r"\bgh\s+pr\s+checkout\b", ln):
                out.append(
                    (
                        p,
                        i + 1,
                        "a workflow with a trusted trigger checks out or runs the pull request's code",
                    )
                )
    return out


# ---------------------------------------------------------------- RC005 CORS lives in the app only

CORS_FILES = (
    "vercel.json",
    "staticwebapp.config.json",
    "netlify.toml",
    "_headers",
    "web.config",
    "host.json",
    "firebase.json",
    "now.json",
)
CORS_HEADER = re.compile(r"access-control-allow-origin", re.I)
TF_CORS = re.compile(r"\bcors\s*\{[^}]*allowed_origins", re.S)
BICEP_CORS = re.compile(r"\bcors\s*:\s*\{[^}]*allowedOrigins", re.S | re.I)
WEB_CONFIG_CORS = re.compile(r"<\s*cors\b", re.I)


def rc005(repo):
    out = []
    for p in repo.paths:
        base = p.rsplit("/", 1)[-1]
        if base in CORS_FILES:
            text = repo.text(p)
            m = CORS_HEADER.search(text) or (
                WEB_CONFIG_CORS.search(text) if base == "web.config" else None
            )
            if m:
                out.append(
                    (
                        p,
                        line_of(text, m.start()),
                        "the hosting config sets a platform CORS origin; keep CORS in the app",
                    )
                )
        elif p.endswith(".tf") or p.endswith(".bicep"):
            text = repo.text(p)
            m = (TF_CORS if p.endswith(".tf") else BICEP_CORS).search(text)
            if m:
                out.append(
                    (
                        p,
                        line_of(text, m.start()),
                        "the infrastructure code sets a platform CORS origin list",
                    )
                )
    return out


# ---------------------------------------------------------------- RC006 deploys are serialised and health gated


def uses_sqlite(repo):
    for p in repo.select(
        exts=(".json", ".txt", ".toml", ".py", ".ts", ".tsx", ".js", ".mjs", ".cjs"), tests=False
    ):
        base = p.rsplit("/", 1)[-1]
        manifest = base in ("package.json", "pyproject.toml") or base.startswith("requirements")
        if (
            manifest or p.endswith((".py", ".ts", ".tsx", ".js", ".mjs", ".cjs"))
        ) and "sqlite" in repo.text(p).lower():
            return True
    return False


STATIC_DEPLOY = re.compile(
    r"\bvercel\b|actions/deploy-pages|pages-action|wrangler\s+pages|\bnetlify\b|surge\.sh|gh-pages",
    re.I,
)
STATEFUL_DEPLOY = re.compile(
    r"\bdocker\b|portainer|\bssh\b|rsync|webhook|webapps-deploy|az\s+webapp|kubectl|\bhelm\b|fly\s+deploy"
    r"|compose|systemctl|ecs\b|app\s*service",
    re.I,
)


def static_only_deploy(text):
    """A workflow that only publishes a static site or a Vercel app holds no state to serialise or probe."""
    return bool(STATIC_DEPLOY.search(text)) and not STATEFUL_DEPLOY.search(text)


def rc006(repo):
    out = []
    if not uses_sqlite(repo):
        return out
    for p in repo.workflows():
        base = p.rsplit("/", 1)[-1].lower()
        if not re.match(r"(deploy|rollback)", base) or "/actions/" in p:
            continue
        text = repo.text(p)
        if static_only_deploy(text):
            continue
        top = re.search(r"(?m)^concurrency:\s*(.*)$", text)
        if not top:
            out.append(
                (
                    p,
                    1,
                    "a deploy workflow declares no concurrency group, so two deploys can overlap",
                )
            )
        else:
            block = text[top.start() : top.start() + 300].split("\njobs:", 1)[0]
            inline = top.group(1).strip()
            if not inline and not re.search(r"\n\s+group\s*:", block):
                out.append((p, line_of(text, top.start()), "the concurrency block has no group"))
            if re.search(r"cancel-in-progress\s*:\s*true", block):
                out.append(
                    (
                        p,
                        line_of(text, top.start()),
                        "a deploy must queue, not cancel the deploy in progress",
                    )
                )
        if not (
            re.search(r"health", text, re.I)
            and re.search(r"github\.sha|GITHUB_SHA|\bsha\b", text, re.I)
        ):
            out.append(
                (
                    p,
                    1,
                    "a deploy workflow does not wait for a health endpoint to report the new sha",
                )
            )
    return out


# ---------------------------------------------------------------- RC007 migrations are forward-only and additive

MIGRATION_DIRS = {"migrations", "migration", "migrate"}
MIGRATION_EXTS = (".sql", ".py", ".ts", ".js", ".mjs", ".cjs")
DESTRUCTIVE = (
    (re.compile(r"\bDROP\s+(?:TABLE|COLUMN|SCHEMA|DATABASE)\b", re.I), "drops data"),
    (re.compile(r"\bTRUNCATE\b", re.I), "truncates a table"),
    (re.compile(r"\bRENAME\s+(?:COLUMN|TO)\b", re.I), "renames what running code still reads"),
    (
        re.compile(
            r"\bALTER\s+COLUMN\b[^;]*\b(?:TYPE|SET\s+DATA\s+TYPE)\b|\bMODIFY\s+COLUMN\b", re.I
        ),
        "changes a column type",
    ),
    (
        re.compile(r"\bALTER\s+COLUMN\b[^;]*\bSET\s+NOT\s+NULL\b", re.I),
        "tightens a column to NOT NULL",
    ),
    (
        re.compile(
            r"\b(?:op\.(?:drop_table|drop_column|alter_column|rename_table)|dropTable|dropColumn|renameColumn|renameTable)\s*\(",
            re.I,
        ),
        "a destructive schema call",
    ),
)
ADD_NOT_NULL = re.compile(r"\bADD\s+(?:COLUMN\s+)?[^;,]*?\bNOT\s+NULL\b[^;,]*", re.I)
DELETE_ALL = re.compile(r"\bDELETE\s+FROM\s+[\w.\"`\[\]]+\s*(?:;|$)", re.I | re.M)


def _strip_sql_comments(text):
    text = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)
    return re.sub(r"--[^\n]*", lambda m: " " * len(m.group(0)), text)


def rc007(repo):
    out = []
    for p in repo.select(exts=MIGRATION_EXTS):
        if not (set(p.split("/")[:-1]) & MIGRATION_DIRS):
            continue
        raw = repo.text(p)
        text = _strip_sql_comments(raw) if p.endswith(".sql") else raw
        lines = raw.splitlines()

        def add(pos, why, text=text, lines=lines, p=p):
            i = line_of(text, pos) - 1
            if i < len(lines) and not skipped(lines, i):
                out.append((p, i + 1, f"destructive or non-additive migration: {why}"))

        for rx, why in DESTRUCTIVE:
            for m in rx.finditer(text):
                add(m.start(), why)
        for m in DELETE_ALL.finditer(text):
            add(m.start(), "deletes every row")
        for m in ADD_NOT_NULL.finditer(text):
            if not re.search(r"\bDEFAULT\b", m.group(0), re.I):
                add(m.start(), "adds a NOT NULL column with no default")
    return out


# ---------------------------------------------------------------- RC008 test data is synthetic

FIXTURE_DIRS = {
    "fixtures",
    "fixture",
    "__fixtures__",
    "testdata",
    "test-data",
    "seed",
    "seeds",
    "__mocks__",
    "mocks",
}
FIXTURE_EXTS = (
    ".json",
    ".csv",
    ".sql",
    ".ts",
    ".tsx",
    ".js",
    ".mjs",
    ".py",
    ".yml",
    ".yaml",
    ".txt",
    ".tsv",
    ".xml",
)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})\b")
SYNTHETIC_TLDS = ("test", "invalid", "example", "localhost")
SYNTHETIC_DOMAINS = ("example.com", "example.org", "example.net")


def _synthetic(domain):
    d = domain.lower()
    return d.rsplit(".", 1)[-1] in SYNTHETIC_TLDS or any(
        d == s or d.endswith("." + s) for s in SYNTHETIC_DOMAINS
    )


def rc008(repo):
    out = []
    for p in repo.select(exts=FIXTURE_EXTS):
        parts = p.split("/")
        if not (set(parts[:-1]) & FIXTURE_DIRS) and not re.match(
            r"^(seed|fixtures?)[-_.]", parts[-1], re.I
        ):
            continue
        lines = repo.text(p).splitlines()
        for i, ln in enumerate(lines):
            if skipped(lines, i):
                continue
            for m in EMAIL.finditer(ln):
                if not _synthetic(m.group(1)):
                    out.append(
                        (
                            p,
                            i + 1,
                            f"fixture holds an email on a real-looking domain ({m.group(1)}); use example.test",
                        )
                    )
                    break
    return out


# ---------------------------------------------------------------- RC009 one boot module for every app

JS_EXTS = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx")
AUTH_REDIRECT = re.compile(r"\.handleRedirectPromise\s*\(")


def rc009(repo):
    hits = {}
    for p in repo.select(exts=JS_EXTS, tests=False):
        lines = repo.text(p).splitlines()
        for i, ln in enumerate(lines):
            if not is_comment(ln) and not skipped(lines, i) and AUTH_REDIRECT.search(ln):
                hits.setdefault(p, i + 1)
    if len(hits) <= 1:
        return []
    return [
        (p, n, f"the auth redirect is handled in {len(hits)} files; one boot module owns it")
        for p, n in sorted(hits.items())
    ]


# ---------------------------------------------------------------- RC010 every secret is documented

SECRET_REF = re.compile(
    r"\bsecrets\.([A-Za-z_][A-Za-z0-9_]*)|secrets\[\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\s*\]"
)
BUILT_IN_SECRETS = {"GITHUB_TOKEN"}


def rc010(repo):
    used = {}
    for p in repo.workflows():
        text = repo.text(p)
        for m in SECRET_REF.finditer(text):
            name = m.group(1) or m.group(2)
            if name not in BUILT_IN_SECRETS:
                used.setdefault(name, (p, line_of(text, m.start())))
    if not used:
        return []
    docs = "\n".join(repo.text(p) for p in repo.select(exts=(".md", ".mdx")))
    return [
        (p, n, f"secret {name} is read by a workflow and named in no documentation page")
        for name, (p, n) in sorted(used.items())
        if not re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", docs)
    ]


# ---------------------------------------------------------------- RC011 cross-repo CI reads use a deploy key

STEP_START = re.compile(r"^\s*-\s+(?:name|uses|run|id|if|env|with)\s*:")


def rc011(repo):
    out = []
    for p in repo.workflows():
        lines = repo.text(p).splitlines()
        for i, ln in enumerate(lines):
            if is_comment(ln) or "actions/checkout" not in ln or not re.search(r"\buses\s*:", ln):
                continue
            end = i + 1
            while end < len(lines) and not STEP_START.match(lines[end]):
                end += 1
            block = "\n".join(lines[i:end])
            m = re.search(r"(?m)^\s*repository\s*:\s*(.+)$", block)
            cross = m and "github.repository" not in m.group(1) and "ssh-key" not in block
            if cross and not skipped(lines, i):
                out.append(
                    (
                        p,
                        i + 1,
                        "a checkout of another repository has no ssh-key (a read-only deploy key)",
                    )
                )
    return out


# ---------------------------------------------------------------- RC012 standard library first

IMPORT_ALIASES = {
    "yaml": "pyyaml",
    "pil": "pillow",
    "dateutil": "python-dateutil",
    "cv2": "opencv-python",
    "bs4": "beautifulsoup4",
    "sklearn": "scikit-learn",
    "jwt": "pyjwt",
    "dotenv": "python-dotenv",
    "attr": "attrs",
    "openssl": "pyopenssl",
    "serial": "pyserial",
    "git": "gitpython",
    "multipart": "python-multipart",
    "jose": "python-jose",
    "usb": "pyusb",
    "googleapiclient": "google-api-python-client",
    "google_auth_oauthlib": "google-auth-oauthlib",
    "google_auth_httplib2": "google-auth-httplib2",
    "oauth2client": "oauth2client",
    "httplib2": "httplib2",
    "google.protobuf": "protobuf",
    "markdown": "Markdown",
    "magic": "python-magic",
    "crypto": "pycryptodome",
    "ldap": "python-ldap",
    "pkg_resources": "setuptools",
    "mpl_toolkits": "matplotlib",
    "skimage": "scikit-image",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "fitz": "pymupdf",
    "zmq": "pyzmq",
    "nacl": "pynacl",
    "dns": "dnspython",
    "socks": "pysocks",
    "slugify": "python-slugify",
    "grpc": "grpcio",
    "websocket": "websocket-client",
    "socketio": "python-socketio",
    "engineio": "python-engineio",
    "xlib": "python-xlib",
    "bson": "pymongo",
    "mysqldb": "mysqlclient",
    "faiss": "faiss-cpu",
    "gi": "pygobject",
    "cairo": "pycairo",
    "bluetooth": "pybluez",
    "jenkins": "python-jenkins",
    "pythonjsonlogger": "python-json-logger",
    "ruamel": "ruamel.yaml",
    "snappy": "python-snappy",
    "wx": "wxpython",
}
# modules provided by pywin32 (the distribution name differs from every import name)
for _m in [
    "win32serviceutil",
    "win32service",
    "win32api",
    "win32con",
    "win32event",
    "win32file",
    "win32gui",
    "win32pipe",
    "win32process",
    "win32security",
    "win32print",
    "win32ui",
    "win32clipboard",
    "win32com",
    "win32comext",
    "win32crypt",
    "win32net",
    "win32pdh",
    "win32evtlog",
    "win32evtlogutil",
    "win32console",
    "win32job",
    "win32profile",
    "win32ts",
    "win32timezone",
    "win32pdhutil",
    "win32uiole",
    "pythoncom",
    "pywintypes",
    "servicemanager",
    "winerror",
    "pythonwin",
    "win32typing",
    "win32trace",
    "win32wnet",
    "win32cred",
    "win32inet",
    "win32lz",
    "win32ras",
    "win32gui_struct",
]:
    IMPORT_ALIASES[_m] = "pywin32"
# import names whose distribution is any of a family sharing a prefix
IMPORT_PREFIX_ALIASES = {"google": "google-"}


# standard library on newer Pythons than the one running the check (tomllib arrived in 3.11)
NEWER_STDLIB = {"tomllib"}


def stdlib_names():
    return _stdlib_names() | NEWER_STDLIB


def _stdlib_names():
    names = getattr(sys, "stdlib_module_names", None)
    if names:
        return set(names)
    import sysconfig

    out = set(sys.builtin_module_names)
    std = pathlib.Path(sysconfig.get_paths()["stdlib"])
    for e in std.iterdir():
        if e.name in ("site-packages", "dist-packages"):
            continue
        out.add(e.name.split(".")[0])
    dyn = std / "lib-dynload"
    if dyn.is_dir():
        out.update(e.name.split(".")[0] for e in dyn.iterdir())
    return out


def norm_dist(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def _toml_strip(line):
    """Drop a trailing comment from a TOML line, respecting quotes."""
    q = None
    for i, ch in enumerate(line):
        if q:
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
        elif ch == "#":
            return line[:i]
    return line


def _toml_array_strings(body):
    """The quoted strings at the top level of a TOML array body (extras brackets stay inside)."""
    out, i, n = [], 0, len(body)
    while i < n:
        ch = body[i]
        if ch in "\"'":
            j = body.find(ch, i + 1)
            if j < 0:
                break
            out.append(body[i + 1 : j])
            i = j + 1
        elif ch == "#":
            j = body.find("\n", i)
            i = n if j < 0 else j
        else:
            i += 1
    return out


def _pyproject_fallback(text):
    """Minimal parse (Python 3.9, no tomllib): {section: {key: [strings]}} for array values."""
    data, section, lines, i = {}, "", text.splitlines(), 0
    while i < len(lines):
        ln = _toml_strip(lines[i]).strip()
        i += 1
        m = re.match(r"\[\[?\s*([^\]]+?)\s*\]\]?$", ln)
        if m:
            section = m.group(1).replace('"', "").replace("'", "")
            continue
        m = re.match(r"([A-Za-z0-9_.\"'-]+)\s*=\s*(.*)$", ln)
        if not m or not m.group(2).lstrip().startswith("["):
            continue
        buf = m.group(2).lstrip()
        while True:
            depth, q = 0, None
            for ch in buf:
                if q:
                    if ch == q:
                        q = None
                elif ch in "\"'":
                    q = ch
                elif ch == "[":
                    depth += 1
                elif ch == "]":
                    depth -= 1
            if depth <= 0 or i >= len(lines):
                break
            buf += "\n" + _toml_strip(lines[i])
            i += 1
        buf = buf.lstrip()[1:]
        end = buf.rfind("]")
        data.setdefault(section, {})[m.group(1).strip("\"'")] = _toml_array_strings(
            buf[:end] if end >= 0 else buf
        )
    return data


def pyproject_requirements(text):
    """Requirement strings from project dependencies, optional-dependencies and dependency-groups."""
    reqs = []
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        tomllib = None
    if tomllib is not None:
        try:
            d = tomllib.loads(text)
        except ValueError:
            d = None
        if d is not None:
            proj = d.get("project", {})
            reqs += [r for r in proj.get("dependencies", []) if isinstance(r, str)]
            for v in proj.get("optional-dependencies", {}).values():
                reqs += [r for r in v if isinstance(r, str)]
            for v in d.get("dependency-groups", {}).values():
                reqs += [r for r in v if isinstance(r, str)]
            return reqs
    data = _pyproject_fallback(text)
    reqs += data.get("project", {}).get("dependencies", [])
    for sec, kv in data.items():
        if sec == "project.optional-dependencies" or sec == "dependency-groups":
            for v in kv.values():
                reqs += v
    return reqs


def hashed_lock(text):
    """True for a pip-compile --generate-hashes style file: every requirement line carries a hash."""
    joined = re.sub(r"\\[ \t]*\r?\n", " ", text)
    reqs = 0
    for ln in joined.splitlines():
        t = ln.split(" #")[0].strip() if not ln.lstrip().startswith("#") else ""
        if not t or t.startswith("-"):
            continue
        reqs += 1
        if "--hash=sha256:" not in t:
            return False
    return reqs > 0


def _hashed_lock_beside(repo, d):
    """A hashed requirements/constraints file in project dir d or its requirements/ or locks/ subdirectory."""
    homes = {d, (d + "/" if d else "") + "requirements", (d + "/" if d else "") + "locks"}
    for p in repo.paths:
        head, _, base = p.rpartition("/")
        if head not in homes:
            continue
        named = re.match(r"(requirements|constraints).*\.txt$|.*\.lock\.txt$", base)
        if (named or (head != d and base.endswith(".txt"))) and hashed_lock(repo.text(p)):
            return True
    return False


def declared_deps(repo):
    """(names, unpinned or reasonless requirement lines) from requirements*.txt and pyproject.toml."""
    names, problems = set(), []
    locked = any(
        p.rsplit("/", 1)[-1] in ("uv.lock", "poetry.lock", "pylock.toml", "Pipfile.lock")
        for p in repo.paths
    )
    for p in repo.paths:
        base = p.rsplit("/", 1)[-1]
        if re.match(r"requirements.*\.txt$", base):
            if hashed_lock(repo.text(p)):
                lines = []  # a generated lock: names come from it, no reason comments are due
                for ln in repo.text(p).splitlines():
                    m = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)\s*(==|$|\\)", ln)
                    if m:
                        names.add(norm_dist(m.group(1)))
                continue
            lines = repo.text(p).splitlines()
            for i, ln in enumerate(lines):
                t = ln.split("#")[0].strip()
                if (
                    not t
                    or t.startswith(("-", "git+"))
                    or re.match(r"[A-Za-z][A-Za-z0-9+.-]*://", t)
                ):
                    continue
                m = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)", t)
                if not m:
                    continue
                names.add(norm_dist(m.group(1)))
                if "==" not in t and "--hash" not in t:
                    problems.append((p, i + 1, f"{m.group(1)} is not pinned with =="))
                elif "#" not in ln and not (i > 0 and lines[i - 1].lstrip().startswith("#")):
                    problems.append((p, i + 1, f"{m.group(1)} has no reason comment"))
        elif base == "pyproject.toml":
            text = repo.text(p)
            for req in pyproject_requirements(text):
                m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", req)
                if m:
                    names.add(norm_dist(m.group(1)))
            if (
                not locked
                and not _hashed_lock_beside(repo, p.rpartition("/")[0])
                and re.search(r"(?m)^\s*dependencies\s*=", text)
            ):
                problems.append((p, 1, "dependencies are declared with no lock file to pin them"))
    return names, problems


def _mod_key(dotted):
    """Top-level import name; google.protobuf keeps its second part (protobuf is a distribution)."""
    if dotted == "google.protobuf" or dotted.startswith("google.protobuf."):
        return "google.protobuf"
    return dotted.split(".")[0]


def import_declared(mod, declared):
    """True when an import name maps to a declared distribution (PEP 503 normalised)."""
    if norm_dist(mod) in declared or norm_dist(IMPORT_ALIASES.get(mod.lower(), mod)) in declared:
        return True
    pre = IMPORT_PREFIX_ALIASES.get(mod.lower())
    return bool(pre) and any(d.startswith(pre) for d in declared)


def rc012(repo):
    files = repo.select(exts=(".py",), tests=False)
    if not files:
        return []
    import ast

    local = set()
    for p in repo.paths:
        parts = p.split("/")
        local.update(parts[:-1])
        if p.endswith(".py"):
            local.add(parts[-1][:-3])
    std = stdlib_names()
    declared, out = declared_deps(repo)
    seen = {}
    for p in files:
        try:
            tree = ast.parse(repo.text(p))
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [_mod_key(a.name) for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods = [_mod_key(node.module)]
            for m in mods:
                if m in std or m in local or m == "__future__":
                    continue
                if not import_declared(m, declared):
                    seen.setdefault(m, (p, node.lineno))
    for m, (p, n) in sorted(seen.items()):
        out.append(
            (p, n, f"import {m} is outside the standard library and in no pinned requirements file")
        )
    return out


# ---------------------------------------------------------------- RC013 deploys re-run CI and are health gated

CI_GATE = re.compile(
    r"workflow_run|workflow_call|(?m:^\s+needs\s*:)|\bnpm\s+(?:run\s+)?(?:test|ci|check|verify)\b|\bpnpm\s+(?:run\s+)?(?:test|check|verify)\b"
    r"|\bpytest\b|unittest|\bvitest\b|\bmake\s+(?:test|check|verify)\b|scripts/verify|uses\s*:\s*\./\.github/workflows/",
)


def rc013(repo):
    out = []
    for p in repo.workflows():
        base = p.rsplit("/", 1)[-1].lower()
        if not re.match(r"deploy", base) or "/actions/" in p:
            continue
        text = repo.text(p)
        if static_only_deploy(text):
            continue
        if not CI_GATE.search(text):
            out.append(
                (p, 1, "a deploy workflow does not re-run CI or wait on a CI job before it deploys")
            )
        if not re.search(r"health", text, re.I):
            out.append((p, 1, "a deploy workflow has no health check after the deploy"))
    return out


# ---------------------------------------------------------------- RC014 verify in both themes

UI_EXTS = (".tsx", ".jsx", ".vue", ".svelte")


def has_ui(repo):
    return bool(repo.select(exts=UI_EXTS, tests=False)) or any(
        p.rsplit("/", 1)[-1] == "index.html" for p in repo.paths
    )


def rc014(repo):
    if not has_ui(repo):
        return []
    specs = [
        p
        for p in repo.select(exts=(".ts", ".js", ".mjs", ".tsx"))
        if TEST_PART.search(p) or re.search(r"(^|/)(visual|playwright)(/|$)", p)
    ]
    text = "\n".join(repo.text(p) for p in specs)
    if not specs:
        return [
            (
                "playwright.config.ts",
                1,
                "a web app has no test suite that could run axe in both themes",
            )
        ]
    out = []
    if not re.search(r"AxeBuilder|axe-core|@axe-core/playwright|checkA11y", text):
        out.append((specs[0], 1, "no test runs axe"))
    if not (re.search(r"[\"'`]dark[\"'`]", text) and re.search(r"[\"'`]light[\"'`]", text)):
        out.append((specs[0], 1, "no test covers both the light and the dark theme"))
    return out


# ---------------------------------------------------------------- RC015 required chrome is mounted


def rc015(repo):
    files = repo.select(exts=(".tsx", ".jsx"), tests=False)
    shells = [p for p in files if re.search(r"<AppShell\b", repo.text(p))]
    if not shells:
        return []
    if any(re.search(r"\bBuildCard\b", repo.text(p)) for p in files):
        return []
    return [(shells[0], 1, "an app shell is mounted and no file renders the build card")]


# ---------------------------------------------------------------- RC016 one local gate


def rc016(repo):
    if "package.json" not in repo.paths:
        return []
    try:
        scripts = json.loads(repo.text("package.json")).get("scripts", {})
    except ValueError:
        return [("package.json", 1, "package.json cannot be read")]
    if not isinstance(scripts, dict):
        return []
    verify = scripts.get("verify")
    if not verify:
        return [("package.json", 1, "no verify script: one local gate that runs what CI runs")]
    body = verify
    for m in re.finditer(r"(?:node|bash|sh|python3?|tsx)\s+(\S+\.(?:mjs|js|cjs|ts|sh|py))", verify):
        if m.group(1) in repo.paths:
            body += "\n" + repo.text(m.group(1))
    out = []
    wanted = [k for k in scripts if k.startswith("check:")] + [
        k for k in ("typecheck", "lint", "build", "test") if k in scripts
    ]
    for k in wanted:
        if not re.search(rf"(?<![\w:-]){re.escape(k)}(?![\w:-])", body):
            out.append(("package.json", 1, f"the verify script does not run {k}"))
    return out


# ---------------------------------------------------------------- RC017 no secret in a subprocess argument

SECRET_NAME = re.compile(r"password|passwd|secret|token|api[_-]?key|credential", re.I)
SAFE_SUFFIX = re.compile(r"(stdin|file|path|env|name|id|url|dir|src)$", re.I)
WRAPPERS = {"str", "Path", "PurePath", "fspath", "join", "abspath", "realpath", "expanduser"}


def unwrap_arg(el):
    """Strip simple wrapper calls (str, Path, os.fspath, os.path.join of such names) to the bare names."""
    import ast

    if isinstance(el, ast.Call):
        f = el.func
        fn = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        if fn in WRAPPERS and el.args and not el.keywords:
            return " ".join(unwrap_arg(a) for a in el.args)
    return ast.unparse(el)


SUBPROCESS_CALLS = {"run", "Popen", "call", "check_call", "check_output"}


def rc017(repo):
    import ast

    out = []
    for p in repo.select(exts=(".py",), tests=False):
        try:
            tree = ast.parse(repo.text(p))
        except (SyntaxError, ValueError):
            continue
        lines = repo.text(p).splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if (
                name not in SUBPROCESS_CALLS
                or not node.args
                or not isinstance(node.args[0], (ast.List, ast.Tuple))
            ):
                continue
            items = node.args[0].elts
            for i, el in enumerate(items):
                if isinstance(el, ast.Constant) and isinstance(el.value, str):
                    flag = (
                        el.value.startswith("-")
                        and SECRET_NAME.search(el.value)
                        and not SAFE_SUFFIX.search(el.value)
                    )
                    hit = bool(flag and i + 1 < len(items) and "=" not in el.value)
                else:
                    txt = unwrap_arg(el)
                    hit = bool(
                        SECRET_NAME.search(txt)
                        and not all(
                            SAFE_SUFFIX.search(t) or not SECRET_NAME.search(t) for t in txt.split()
                        )
                    )
                if hit and not skipped(lines, el.lineno - 1):
                    out.append(
                        (
                            p,
                            el.lineno,
                            "a secret is passed as a subprocess argument; use stdin or a file",
                        )
                    )
    return out


# ---------------------------------------------------------------- RC018 long-lived vendor chunks


def rc018(repo):
    out = []
    for p in repo.paths:
        if re.search(r"(^|/)vite\.config\.[a-z]+$", p) and "manualChunks" not in repo.text(p):
            out.append((p, 1, "the build config names no vendor chunks (manualChunks)"))
    return out


# ---------------------------------------------------------------- RC019 entry chunk budget

BUNDLER = re.compile(r"(^|/)(vite|webpack|rollup|rspack)\.config\.[a-z]+$")
BUDGET_FILE = re.compile(
    r"(^|/)(\.size-limit|size-limit\.config|bundlewatch\.config|\.bundlewatch)"
)
BUDGET_WORD = re.compile(
    r"size-limit|bundlewatch|bundlesize|bundle-size|check:size|check:bundle|budget", re.I
)


def rc019(repo):
    bundled = [p for p in repo.paths if BUNDLER.search(p)]
    if not bundled:
        return []
    if any(BUDGET_FILE.search(p) for p in repo.paths):
        return []
    for p in repo.paths:
        if p.rsplit("/", 1)[-1] == "package.json":
            try:
                scripts = json.loads(repo.text(p)).get("scripts", {})
            except ValueError:
                continue
            if isinstance(scripts, dict) and any(
                BUDGET_WORD.search(k) or BUDGET_WORD.search(str(v)) for k, v in scripts.items()
            ):
                return []
    return [(bundled[0], 1, "a bundled app has no bundle size budget check")]


# ---------------------------------------------------------------- RC020 large inline assets become files


def rc020(repo):
    out = []
    for p in repo.paths:
        if re.search(r"(^|/)vite\.config\.[a-z]+$", p) and "assetsInlineLimit" not in repo.text(p):
            out.append((p, 1, "the build config sets no assetsInlineLimit"))
    return out


# ---------------------------------------------------------------- RC021 one client package

BEARER = re.compile(r"[\"'`]Bearer\s|Authorization[\"']?\s*[:=]")


SERVER_PART = re.compile(r"(^|/)(server|backend|api|scripts|tools|functions|workers?|cli)/")


def app_root(path):
    """The app a file belongs to: apps/<name>, packages/<name>, services/<name>, else the top folder."""
    parts = path.split("/")
    return (
        "/".join(parts[:2])
        if parts[0] in ("apps", "packages", "services") and len(parts) > 2
        else parts[0]
    )


def many_files_per_app(hits, what):
    by_app = {}
    for p, n in sorted(hits.items()):
        by_app.setdefault(app_root(p), []).append((p, n))
    return [
        (p, n, f"{what} (seen in {len(files)} files of one app)")
        for files in by_app.values()
        if len(files) > 1
        for p, n in files
    ]


def rc021(repo):
    hits = {}
    for p in repo.select(exts=JS_EXTS, tests=False):
        if SERVER_PART.search(p):
            continue
        lines = repo.text(p).splitlines()
        for i, ln in enumerate(lines):
            if not is_comment(ln) and not skipped(lines, i) and BEARER.search(ln):
                hits.setdefault(p, i + 1)
    return many_files_per_app(hits, "the bearer header is built; one client package owns it")


# ---------------------------------------------------------------- RC022 guards come from one module

PERMISSION_TEST = re.compile(
    r"\b(?:permissions?|roles?|scopes?)\s*(?:\?\.|\.)\s*(?:includes|has|some|indexOf)\s*\(|\bhasPermission\s*\("
)


def rc022(repo):
    hits = {}
    for p in repo.select(exts=JS_EXTS + (".py",), tests=False):
        lines = repo.text(p).splitlines()
        for i, ln in enumerate(lines):
            if not is_comment(ln) and not skipped(lines, i) and PERMISSION_TEST.search(ln):
                hits.setdefault(p, i + 1)
    return many_files_per_app(hits, "permissions are compared by hand; one guard module owns it")


# id -> (title, doc rule ref, function)
CHECKS = {
    "RC001": ("kill by name or pattern", "automation-safety.md 1.9", rc001),
    "RC002": ("merge without the head sha", "pr-review-and-merge.md 1.6", rc002),
    "RC003": ("major updates auto-merge", "ci-cd-release.md 4", rc003),
    "RC004": ("merge gate runs PR code", "ci-cd-release.md 5", rc004),
    "RC005": ("platform CORS config", "web-api-runtime.md 3.3", rc005),
    "RC006": ("deploy not serialised or health gated", "data-safety-sqlite.md 2.10", rc006),
    "RC007": ("destructive migration", "data-safety-sqlite.md 2.12", rc007),
    "RC008": ("real-looking fixture address", "identity-and-people-data.md 1.7", rc008),
    "RC009": ("auth redirect handled outside one module", "web-client-runtime.md 1.2", rc009),
    "RC010": ("undocumented secret", "ci-cd-release.md 9", rc010),
    "RC011": ("cross-repo checkout without a deploy key", "secrets-and-credentials.md 1.4", rc011),
    "RC012": ("import outside the standard library not pinned", "scripting-python.md 1.2", rc012),
    "RC013": ("deploy without CI or health gate", "ci-cd-release.md 6", rc013),
    "RC014": ("no axe run in both themes", "web-ui.md 9", rc014),
    "RC015": ("app shell without the build card", "web-ui.md 25", rc015),
    "RC016": ("no complete verify script", "web-build.md 8.1", rc016),
    "RC017": ("secret in a subprocess argument", "scripting-python.md 1.3", rc017),
    "RC018": ("no vendor chunks", "web-client-runtime.md 4.2", rc018),
    "RC019": ("no bundle size budget", "web-client-runtime.md 4.1", rc019),
    "RC020": ("no inline asset limit", "web-client-runtime.md 4.3", rc020),
    "RC021": ("bearer header built in many files", "web-client-runtime.md 5.1", rc021),
    "RC022": ("permissions compared by hand in many files", "rbac.md 3", rc022),
}


def run(check_id, root):
    """Findings of one check against the repo at root: a list of (path, line, message)."""
    return CHECKS[check_id][2](Repo(root))


def run_all(root):
    repo = Repo(root)
    return {cid: fn(repo) for cid, (_, _, fn) in CHECKS.items()}


def main(argv):
    if "--list" in argv:
        for cid, (title, ref, _) in CHECKS.items():
            print(f"{cid}  {ref:<34} {title}")
        return 0
    root = "."
    if "--root" in argv:
        root = argv[argv.index("--root") + 1]
    try:
        top = subprocess.run(
            ["git", "-C", root, "rev-parse", "--show-toplevel"], capture_output=True, text=True
        ).stdout.strip()
    except OSError:
        top = ""
    result = run_all(top or root)
    if "--json" in argv:
        print(json.dumps({k: [list(f) for f in v] for k, v in result.items()}, indent=1))
    else:
        for cid, found in result.items():
            print(
                f"{cid} {CHECKS[cid][1]}: {'ok' if not found else str(len(found)) + ' finding(s)'}"
            )
            for p, n, msg in found:
                print(f"  {p}:{n}: {msg}")
    return 1 if any(result.values()) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
