"""Shared helpers for the overlay scripts: lock parsing, content hash, access error."""

import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
LOCK = ROOT / "standards.lock"
COPIES = ("standards-core", "tokens-core", "lint-core", "kit-core")
# Core folder -> synced copy in the overlay. A core folder that does not exist yet is skipped.
SYNC_MAP = (
    ("standards", "standards-core"),
    ("tokens", "tokens-core"),
    ("lint", "lint-core"),
    ("kit/src", "kit-core"),
)
# Overlay scripts are refreshed from the core template on every sync, so tooling fixes reach every overlay.
# Single core files copied into the overlay on every sync, refreshed like the overlay scripts.
SYNC_FILES = (
    ("kit/scripts/gen-changelog.mjs", "scripts/gen-changelog.mjs"),
    # Build tooling for a multi-module shell: the per-module CSS scope plugin and the registry generator.
    ("kit/scripts/scope-css.mjs", "scripts/scope-css.mjs"),
    ("kit/scripts/build-registry.mjs", "scripts/build-registry.mjs"),
    # Makes kit-core a workspace package, so an app library imports 'kit-core' with no path alias.
    ("kit/consumer/package.json", "kit-core/package.json"),
)
# Install and build output inside a synced copy (a workspace package gets its own node_modules) is
# not core content, so the hash never sees it.
HASH_SKIP_DIRS = (
    "node_modules",
    "dist",
    ".ruff_cache",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
)
HASH_SKIP_SUFFIXES = (".tsbuildinfo",)
OVERLAY_SCRIPTS = (
    "corehash.py",
    "sync-core.py",
    "check-core-sync.py",
    "update-core.py",
    "check-exceptions.py",
    "core-status.py",
    "merge-pr.py",
    "triage_marker.py",
    "core-ci.py",
    "repo_checks.py",
)


def read_lock():
    return dict(
        ln.split("=", 1)
        for ln in LOCK.read_text().splitlines()
        if "=" in ln and not ln.startswith("#")
    )


def core_repo():
    """Where the core lives, resolved on the machine that runs the script, never from a file in the overlay.

    Order: CORE_REPO in the environment (CI sets it from a repository variable), then core_repo in
    ~/.config/build-standards-core/consumer.json (written by hermes/setup.py from the core clone's own
    remote), then a legacy repo= line in an old lock, which is recorded in that file on first use because
    the next sync drops it. The lock itself carries no account or repo name, so
    nothing that names the source owner is ever committed to a consumer."""
    env = os.environ.get("CORE_REPO", "").strip()
    if env:
        return env
    cfg = pathlib.Path(
        os.environ.get("CORE_CONSUMER_CONFIG") or "~/.config/build-standards-core/consumer.json"
    ).expanduser()
    data = {}
    if cfg.is_file():
        try:
            data = json.loads(cfg.read_text(encoding="utf8"))
        except ValueError:
            data = None
        val = data.get("core_repo", "") if isinstance(data, dict) else ""
        if val:
            return val
    legacy = read_lock().get("repo", "")
    if legacy:
        # The next sync rewrites the lock without this line, so record it on this machine first.
        # Otherwise a later run (the sync handover, the next night) has no source left to read.
        if isinstance(data, dict):
            try:
                cfg.parent.mkdir(parents=True, exist_ok=True)
                cfg.write_text(
                    json.dumps({**data, "core_repo": legacy}, indent=2) + "\n", encoding="utf8"
                )
                print(
                    f"recorded core_repo in {cfg} (the next sync drops it from the lock)",
                    file=sys.stderr,
                )
            except OSError as exc:
                print(
                    f"could not record core_repo in {cfg}: {exc}. Set CORE_REPO or run hermes/setup.py.",
                    file=sys.stderr,
                )
        else:
            print(
                f"{cfg} is not valid JSON, core_repo not recorded. Fix it or run hermes/setup.py.",
                file=sys.stderr,
            )
        return legacy
    sys.exit(
        "Cannot tell where the core lives. Set CORE_REPO=OWNER/NAME in the environment, or run "
        "hermes/setup.py from the core clone on this machine (it records core_repo). The overlay "
        "never stores the source on purpose."
    )


def write_lock(ref, commit, digest):
    LOCK.write_text(
        "# Pin of the shared core that this overlay tracks. The source is never recorded here.\n"
        f"ref={ref}\ncommit={commit}\ncontent_sha256={digest}\n"
    )


def checkout_pinned(core_dir, cfg):
    """Check out the pinned release in a core clone: the recorded commit when it still exists, else the
    tag in ref=. A rewritten core history gives a tag a new commit id, so the lock's commit is only a
    hint and the release is identified by its tag and the content hash. Returns 'commit', or a one-line
    note saying the tag was used and why. Exits with one plain message when neither resolves."""

    def ok(rev):
        return (
            subprocess.run(
                ["git", "-C", str(core_dir), "checkout", "--quiet", rev],
                capture_output=True,
                text=True,
            ).returncode
            == 0
        )

    commit, ref = cfg.get("commit", ""), cfg.get("ref", "")
    if commit and ok(commit):
        return "commit"
    if ref and ok(ref):
        return (
            f"pinned commit {commit[:12]} is not in the core (history rewritten); compared by tag {ref}"
            if commit
            else f"no pinned commit; compared by tag {ref}"
        )
    sys.exit(
        f"core sync: neither the pinned commit {commit[:12] or '(none)'} nor the tag {ref or '(none)'} "
        "exists in the core; run scripts/sync-core.py latest"
    )


def content_hash(root=ROOT):
    """Deterministic hash of the synced copies: sorted relative paths plus bytes, CRLF normalised."""
    h = hashlib.sha256()
    for name in COPIES:
        base = root / name
        if not base.is_dir():
            continue
        files = (p for p in base.rglob("*") if p.is_file())
        files = (
            p
            for p in files
            if not set(p.relative_to(base).parts) & set(HASH_SKIP_DIRS)
            and not p.name.endswith(HASH_SKIP_SUFFIXES)
        )
        for f in sorted(files):
            h.update(f"{name}/{f.relative_to(base).as_posix()}\n".encode())
            h.update(f.read_bytes().replace(b"\r\n", b"\n"))
            h.update(b"\0")
    return h.hexdigest()


def git_url(repo):
    """Anonymous HTTPS URL of the core. CORE_GIT_BASE overrides the host (tests point it at a local dir)."""
    base = os.environ.get("CORE_GIT_BASE", "https://github.com/")
    return f"{base.rstrip('/')}/{repo}.git"


def _semver(tag):
    m = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", tag)
    return tuple(int(x) for x in m.groups()) if m else None


def latest_tag(repo):
    """Newest release tag of the core: gh when it is installed and signed in, else the newest vX.Y.Z tag
    read with plain git over anonymous HTTPS (the core is public, so neither needs an account). Exits
    with one plain message on failure."""
    try:
        r = subprocess.run(
            ["gh", "release", "view", "-R", repo, "--json", "tagName", "--jq", ".tagName"],
            capture_output=True,
            text=True,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
        gh_said = r.stderr.strip()
    except FileNotFoundError:
        gh_said = "gh is not installed"
    r = subprocess.run(
        ["git", "ls-remote", "--tags", "--refs", git_url(repo), "v*"],
        capture_output=True,
        text=True,
    )
    tags = [ln.rsplit("refs/tags/", 1)[-1] for ln in r.stdout.splitlines() if "refs/tags/" in ln]
    tags = [t for t in tags if _semver(t)]
    if r.returncode == 0 and tags:
        return max(tags, key=_semver)
    sys.exit(
        f"Could not read the latest release of {repo}: {gh_said or 'no release'}; "
        f"git said: {r.stderr.strip() or 'no vX.Y.Z tag'}"
    )


def read_targets():
    """Optional targets.map: lines `<copy path> = <destination>`, both relative to the overlay root.

    Lets a consumer keep generated files (for example a UI package's token stylesheet) identical to the
    synced copies. Blank lines and lines starting with # are ignored."""
    f = ROOT / "targets.map"
    if not f.is_file():
        return []
    out = []
    for line in f.read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            a, b = (x.strip() for x in line.split("=", 1))
            out.append((ROOT / a, (ROOT / b).resolve()))
    return out


def clone(repo, dest, ref=None):
    """Clone the core at ref, with one plain message on failure instead of a stack trace.

    Tries gh first (a signed-in account), then plain git over anonymous HTTPS (the core is public, so no
    account, token or key is needed). CORE_CHECKOUT=<path of an existing clone of the core> clones from
    that checkout instead, with no network: an offline restore or CI that already checked the core out.
    The checkout must hold the ref (fetch tags, for example actions/checkout with fetch-depth 0)."""
    local = os.environ.get("CORE_CHECKOUT")
    if local:
        args = ["git", "clone", "--quiet", str(pathlib.Path(local).resolve()), str(dest)] + (
            ["--branch", ref] if ref else []
        )
        r = subprocess.run(args, capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(
                f"Could not clone {ref or 'the default branch'} from CORE_CHECKOUT={local}: {r.stderr.strip()}"
            )
        return
    gh_said = ""
    args = ["gh", "repo", "clone", repo, str(dest), "--", "--quiet"] + (
        ["--branch", ref] if ref else []
    )
    try:
        r = subprocess.run(args, capture_output=True, text=True)
        if r.returncode == 0:
            return
        gh_said = r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "no output"
        shutil.rmtree(dest, ignore_errors=True)
    except FileNotFoundError:
        gh_said = "gh is not installed"
    args = ["git", "clone", "--quiet", git_url(repo), str(dest)] + (
        ["--branch", ref] if ref else []
    )
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode == 0:
        return
    sys.exit(
        f"Could not read {repo} at {ref or 'the default branch'}.\n"
        "Check that the ref exists and that this machine reaches github.com. The core is public: no\n"
        "invitation, token or key is needed.\n"
        f"gh said: {gh_said or 'not tried'}; git said: {r.stderr.strip().splitlines()[-1] if r.stderr.strip() else 'no output'}"
    )


PARAMETERS_TEMPLATE = "templates/overlay/standards-local/parameters.md"
PARAMETERS_LOCAL = "standards-local/parameters.md"
ROW_MARKER = "<!-- sync-core: row added from the template"


def _row_cells(line):
    s = line.strip()
    if not (s.startswith("|") and s.endswith("|")):
        return None
    cells = [c.strip() for c in s.strip("|").split("|")]
    if len(cells) < 2 or set(cells[0]) <= set("-: ") or cells[0].lower() == "parameter":
        return None
    return cells


def _row_key(label):
    """A row's identity: its label up to the first bracket or comma, lowercased, so a reworded
    explanation in the template still matches the consumer's row."""
    return label.split("(", 1)[0].split(",", 1)[0].strip().lower()


def add_parameter_rows(template_text, local_text, ref):
    """(new local text, labels added): every template parameters row whose label the local sheet lacks,
    appended after the local table's last row with the template's value cell and a marker comment.
    Existing rows are never changed. A local label matches when either label key starts with the other
    (scripts read a row by the prefix of its label)."""
    have = [_row_key(c[0]) for c in map(_row_cells, local_text.splitlines()) if c]
    missing = []
    for line in template_text.splitlines():
        cells = _row_cells(line)
        if not cells:
            continue
        key = _row_key(cells[0])
        if key and not any(h and (h.startswith(key) or key.startswith(h)) for h in have):
            used = cells[2] if len(cells) > 2 else ""
            missing.append(
                (
                    cells[0],
                    f"| {cells[0]} | {cells[1]} | {used} {ROW_MARKER} {ref}; set a value -->".rstrip()
                    + " |",
                )
            )
            have.append(key)
    if not missing:
        return local_text, []
    lines = local_text.splitlines()
    # The parameters table: the one whose header's first cell is Parameter, else the first table.
    starts = [i for i, ln in enumerate(lines) if ln.strip().startswith("|")]
    head = next(
        (
            i
            for i in starts
            if lines[i].strip().strip("|").split("|")[0].strip().lower() == "parameter"
        ),
        starts[0] if starts else None,
    )
    last = head
    while last is not None and last + 1 < len(lines) and lines[last + 1].strip().startswith("|"):
        last += 1
    rows = [r for _, r in missing]
    if last is None:
        lines += ["", "| Parameter | Value | Used by |", "|---|---|---|"] + rows
    else:
        lines[last + 1 : last + 1] = rows
    return "\n".join(lines) + "\n", [label for label, _ in missing]


def sync_parameters(core_dir, ref, root=ROOT):
    """Add the template's missing parameters rows to the overlay's sheet. Returns the labels added; the
    sheet is left alone when it does not exist (setup writes it from the template)."""
    tpl, local = pathlib.Path(core_dir) / PARAMETERS_TEMPLATE, pathlib.Path(root) / PARAMETERS_LOCAL
    if not tpl.is_file() or not local.is_file():
        return []
    old = local.read_text(encoding="utf8")
    new, added = add_parameter_rows(tpl.read_text(encoding="utf8"), old, ref)
    if added:
        local.write_text(new, encoding="utf8")
    return added


# The overlay's template workflows. A sync refreshes each one the consumer repo already has from the
# core's template, keeping the repo's own settings, and never touches any other workflow.
WORKFLOWS = ("core-ci.yml", "core-drift.yml", "core-update.yml", "lint-sweep.yml")
WORKFLOW_TEMPLATE = "templates/overlay/.github/workflows"
# A template line ending in this comment holds a per-repo value: a sync keeps the repo's value of that key.
KEEP_MARK = "# core-sync: keep"
# Keys whose repo value a sync always keeps (the documented per-repo settings), marked or not.
KEEP_KEYS = (("env", "OVERLAY"),)
# A workflow with relative overlay paths (core-drift.yml runs scripts/... from the repo root): a repo whose
# overlay is a subfolder writes the prefix in front of them, and a sync keeps it.
RELATIVE_PATH = r"(python3 )((?:scripts|lint-core)/)"
_KEY = r"^(\s*)(?:-\s+)?([A-Za-z0-9_.-]+):(?:\s+(.*?))?\s*$"
SETUP_JOB_NAMES = ("setup", "core-setup")


# A core-ci.yml that calls the core's reusable workflow instead of being a copy of the template.
REUSABLE_CALL = re.compile(
    r"^\s+uses:\s*[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/\.github/workflows/core-ci-reusable\.yml@\S+",
    re.M,
)


def repo_root(root=ROOT):
    """The git work tree the overlay lives in (its workflows are at its root), else the overlay itself."""
    r = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"], capture_output=True, text=True
    )
    top = r.stdout.strip() if r.returncode == 0 else ""
    return pathlib.Path(top) if top else pathlib.Path(root)


def _split_comment(rest):
    """(value, comment) of a YAML value: a # after whitespace outside quotes starts the comment."""
    quote = ""
    for i, c in enumerate(rest):
        if quote:
            if c == quote:
                quote = ""
        elif c in "'\"":
            quote = c
        elif c == "#" and (i == 0 or rest[i - 1] in " \t"):
            return rest[:i].rstrip(), rest[i:]
    return rest.rstrip(), ""


def _keyed_lines(text):
    """[(line index, key path, value, comment)] for every `key: value` line with a scalar value."""
    out, stack = [], []
    for i, line in enumerate(text.splitlines()):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(_KEY, line)
        if not m:
            continue
        indent = len(m.group(1)) + (2 if line.lstrip().startswith("- ") else 0)
        while stack and stack[-1][0] >= indent:
            stack.pop()
        stack.append((indent, m.group(2)))
        value, comment = _split_comment(m.group(3) or "")
        out.append((i, tuple(k for _, k in stack), value, comment))
    return out


_SCHEDULE = re.compile(r"^  schedule:[ \t]*\n(?:(?:    |  #).*\n|[ \t]*\n)*", re.M)
_DISPATCH = re.compile(r"^  workflow_dispatch:", re.M)


def keep_schedule(out, local_text):
    """A schedule block the repo added under `on:` survives a sync that ships none: the template's
    trigger is workflow_dispatch and a cron is optional, so the repo's own cron is its setting."""
    if re.search(r"^  schedule:", out, re.M):
        return out
    m = _SCHEDULE.search(local_text)
    d = _DISPATCH.search(out)
    if not m or not d:
        return out
    block = m.group(0).rstrip("\n") + "\n"
    return out[: d.start()] + block + out[d.start() :]


def merge_workflow(template_text, local_text):
    """The template workflow with the repo's per-repo settings kept: the value of every KEEP_KEYS key and
    of every template line marked KEEP_MARK, taken from the repo's copy by key path, and the overlay path
    prefix in front of relative overlay paths."""
    local = {}
    for _, path, value, _ in _keyed_lines(local_text):
        local.setdefault(path, value)
    lines = template_text.splitlines()
    for i, path, value, comment in _keyed_lines(template_text):
        if (
            not (path in KEEP_KEYS or KEEP_MARK in comment)
            or path not in local
            or local[path] == value
        ):
            continue
        line = lines[i]
        head = line[: line.index(":", len(line) - len(line.lstrip())) + 1]
        rest = line[len(head) :]
        at = rest.index(value) if value else len(rest) - len(rest.lstrip())
        lines[i] = head + (rest[:at] or " ") + local[path] + rest[at + len(value) :]
    out = "\n".join(lines) + ("\n" if template_text.endswith("\n") else "")
    out = keep_schedule(out, local_text)
    code = "\n".join(ln for ln in local_text.splitlines() if not ln.lstrip().startswith("#"))
    m = re.search(r"python3 ([A-Za-z0-9_.][A-Za-z0-9_./-]*/)?(?:scripts|lint-core)/", code)
    prefix = (m.group(1) or "") if m else ""
    if prefix and re.search(RELATIVE_PATH, template_text):
        out = re.sub(RELATIVE_PATH, lambda k: k.group(1) + prefix + k.group(2), out)
    return out


def check_names(text):
    """The check name of every job of a workflow (name: when set, else the id), setup helpers left out."""
    names, inside, current = [], False, None
    for line in text.splitlines():
        if re.match(r"^jobs:\s*$", line):
            inside = True
            continue
        if inside and re.match(r"^\S", line):
            inside = False
        if not inside:
            continue
        m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if m:
            current = len(names)
            names.append(m.group(1))
            continue
        m = re.match(r"^    name:\s*(.+?)\s*(#.*)?$", line)
        if m and current is not None:
            names[current] = m.group(1).strip("'\"")
            current = None
    return [n for n in names if n not in SETUP_JOB_NAMES]


def renamed_checks(old_text, new_text):
    """[(old, new)] for the core-ci.yml check names that changed: a renamed job pairs its old and new name
    (a new name that ends with the old one, as core-x for x), a removed one pairs with "(removed)" and an
    added one with "(new)"."""
    old, new = check_names(old_text), check_names(new_text)
    gone = [n for n in old if n not in new]
    added = [n for n in new if n not in old]
    pairs = []
    for o in gone:
        match = next((n for n in added if n.endswith("-" + o) or n == "core-" + o), None)
        if match:
            added.remove(match)
        pairs.append((o, match or "(removed)"))
    return pairs + [("(new)", n) for n in added]


def sync_workflows(core_dir, root=ROOT):
    """Refresh the template workflows the consumer repo has. Returns (refreshed file names, notes): the
    notes name the required-check changes of core-ci.yml, old -> new, so the merge gate is updated."""
    tpl_dir = pathlib.Path(core_dir) / WORKFLOW_TEMPLATE
    wf_dir = repo_root(root) / ".github" / "workflows"
    done, notes = [], []
    for name in WORKFLOWS:
        tpl, local = tpl_dir / name, wf_dir / name
        if not tpl.is_file() or not local.is_file():
            continue
        old = local.read_text(encoding="utf8")
        if name == "core-ci.yml" and REUSABLE_CALL.search(old):
            # A caller of the reusable workflow is pinned by its own ref, not copied from the template.
            notes.append(
                "core-ci.yml calls the reusable workflow: left as is (move its pinned ref to the new "
                "release yourself)"
            )
            continue
        new = merge_workflow(tpl.read_text(encoding="utf8"), old)
        if new == old:
            continue
        local.write_text(new, encoding="utf8")
        done.append(name)
        if name == "core-ci.yml":
            pairs = renamed_checks(old, new)
            if pairs:
                notes.append(
                    "required checks: core-ci.yml job names changed; update the merge gate "
                    "(scripts/core-ci.py required-checks --fix prints the commands):"
                )
                notes += [f"  {o} -> {n}" for o, n in pairs]
    return done, notes
