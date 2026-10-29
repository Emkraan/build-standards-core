"""
tf_context.py
Purpose: Plain-language facts for Terraform apply cards on the Reviews pages (owner applies, privileged deployments,
         runbook delete releases). Used by approval_brief.py.
           - open PRs that change the same root (gh pr list plus gh pr diff --name-only, root paths from the roots spec
             file on origin/main of the infrastructure clone), with a check of whether a PR removes something the plan
             would create. Applying from main while such a PR is open undoes or pre-empts it.
           - the plan text parsed into resources with their attributes, and one plain sentence per resource (who gets
             what access, on what, and what that access lets it do)
           - principal ids resolved to display names through the consumer's provider (read only)
         Every read on a page GET is local and cached. The code host and the provider run only in background threads
         (single flight) or in the brief generator, so a page load never waits on them. A failed read is reported as
         unknown, never as "no overlap".

         Configuration: the repo is `plan_repo` in review_config; TF_CONTEXT_REPO is the local clone; TF_CONTEXT_SPEC the
         roots spec path inside it (default .github/terraform-roots.json). Provider: TF_CONTEXT_PROVIDER=path/to/file.py:Class
         with an optional resolve_principal(id) -> {"name", "kind"} or None (null default: no names are resolved).
Date:    2026-10-15
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

import paths
import review_config as cfg

HOME = Path.home()
REPO_DIR = Path(os.environ.get("TF_CONTEXT_REPO", str(paths.repos_dir() / "infra")))
SPEC_FILE = os.environ.get("TF_CONTEXT_SPEC", ".github/terraform-roots.json")
CACHE = Path(
    os.environ.get("TF_CONTEXT_CACHE", str(paths.agent_home() / "cache" / "approval-briefs"))
)
GH = os.environ.get("OPRG_GH_BIN", paths.which("gh"))
GIT = os.environ.get("TF_CONTEXT_GIT") or paths.which("git")
OWNER_LOGS = (
    Path(os.environ.get("OWNER_ROOTS_CACHE", str(paths.agent_home() / "cache" / "owner-roots")))
    / "logs"
)

OV_TTL_S = 120  # refresh the open PR list in the background once it is this old
OV_MAX_AGE_S = 900  # older than this, the overlap check counts as unknown (fail closed)
SPEC_TTL_S = 300
NAME_TTL_S = 7 * 86400
DIFF_KEEP = 60
CODE_MAX = 30000

_GUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_RES_HEAD = re.compile(
    r"^\s*# (\S+) (will be created|will be updated in-place|will be destroyed|must be replaced|"
    r"will be read during apply|will be imported|has moved to \S+)"
)
_ACTION = {
    "will be created": "add",
    "will be updated in-place": "change",
    "will be destroyed": "destroy",
    "must be replaced": "replace",
    "will be read during apply": "read",
    "will be imported": "import",
}

_lock = threading.Lock()
_ov = {"at": 0.0, "prs": None, "error": None, "busy": False, "loaded": False}
_names = {"busy": False, "queue": set()}
_spec = {"at": 0.0, "main": None, "roots": None}
_mem = {}  # small per-key memo: (kind, key) -> value


class CtxError(Exception):
    pass


def _repo():
    return cfg.plan_repo()


def _provider():
    spec = os.environ.get("TF_CONTEXT_PROVIDER", "").strip()
    path, _, cls_name = spec.rpartition(":")
    if not spec or not path or not Path(path).is_file():
        return None
    ms = importlib.util.spec_from_file_location("tf_context_provider", path)
    mod = importlib.util.module_from_spec(ms)
    try:
        ms.loader.exec_module(mod)
        return getattr(mod, cls_name)()
    except (OSError, ImportError, AttributeError, TypeError, SyntaxError):
        return None


def _now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(argv, timeout=60, cwd=None):
    """One external command with a timeout. Returns stdout or raises CtxError (tests patch this)."""
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    except subprocess.TimeoutExpired:
        raise CtxError(f"{Path(argv[0]).name} timed out after {timeout}s") from None
    except OSError as e:
        raise CtxError(f"{Path(argv[0]).name} could not start: {e}") from e
    if r.returncode != 0:
        tail = " ".join((r.stderr or r.stdout or "").strip().splitlines()[-2:])[:200]
        raise CtxError(f"{Path(argv[0]).name} exit {r.returncode}: {tail}")
    return r.stdout


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    with open(tmp, "w") as f:
        f.write(json.dumps(data, indent=1, sort_keys=True))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _read_json(path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def _epoch(iso):
    try:
        return (
            dt.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
            .replace(tzinfo=dt.timezone.utc)
            .timestamp()
        )
    except (TypeError, ValueError):
        return 0.0


# ---- the roots and their files on origin/main ----


def _git(*args, timeout=30):
    return _run([GIT, "-C", str(REPO_DIR), *args], timeout=timeout)


def roots_spec():
    """{name: {"applied_by", "tiers": {tier: {"root", "vars", "key"}}}} from origin/main. Local git,
    cached per main sha for SPEC_TTL_S. Raises CtxError when the clone cannot be read."""
    if _spec["roots"] is not None and time.time() - _spec["at"] < SPEC_TTL_S:
        return _spec["roots"]
    main = _git("rev-parse", "origin/main").strip()
    data = json.loads(_git("show", "origin/main:" + SPEC_FILE))
    out = {}
    for r in data.get("roots") or []:
        out[r["name"]] = {
            "applied_by": r.get("applied_by") or ("tfapply" if r.get("apply") else "owner"),
            "tiers": {t: dict(v) for t, v in (r.get("tiers") or {}).items()},
        }
    _spec.update(at=time.time(), main=main, roots=out)
    return out


def root_paths(name, tier):
    """The files a plan of this root reads: its directory, its tier vars file and the local modules
    it calls. {"dir", "vars", "modules": [dir]}. None when the root is not in the roots spec."""
    spec = roots_spec().get(name)
    ts = (spec or {}).get("tiers", {}).get(tier)
    if not ts:
        return None
    key = ("paths", _spec["main"], name, tier)
    if key in _mem:
        return _mem[key]
    d = ts["root"].rstrip("/")
    mods = set()
    try:
        files = [
            f
            for f in _git("ls-tree", "-r", "--name-only", "origin/main", d).splitlines()
            if f.endswith(".tf")
        ]
        for f in files:
            src = _git("show", f"origin/main:{f}")
            for m in re.finditer(r'source\s*=\s*"(\.{1,2}/[^"]+)"', src):
                mods.add(os.path.normpath(os.path.join(os.path.dirname(f), m.group(1))))
    except CtxError:
        pass
    out = {"dir": d, "vars": f"{d}/{ts['vars']}" if ts.get("vars") else "", "modules": sorted(mods)}
    _mem[key] = out
    return out


def touches(files, paths):
    """The files from `files` a plan of the root with `paths` reads."""
    if not paths:
        return []
    dirs = [paths["dir"]] + list(paths.get("modules") or [])
    hit = []
    for f in files or []:
        if any(f.startswith(x + "/") for x in dirs):
            hit.append(f)
    return hit


def files_defining(resources):
    """The .tf files on origin/main that declare these plan resources (resource "<type>" "<name>"),
    so a privileged run is tied to the roots its plan really changes, not only the PR it started
    from. [] when none is found or git cannot be read."""
    pats = set()
    for r in resources or []:
        addr = re.sub(r"\[[^\]]*\]", "", r.get("address") or "")
        parts = [p for p in addr.split(".") if p]
        if len(parts) >= 2 and not parts[-2].startswith("data"):
            pats.add(f'resource "{parts[-2]}" "{parts[-1]}"')
    if not pats:
        return []
    key = ("defining", tuple(sorted(pats)))
    hit = _mem.get(key)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    out = set()
    for p in sorted(pats):
        try:
            hits = _git("grep", "-l", "-F", p, "origin/main", "--", "*.tf", timeout=30)
        except CtxError:
            continue
        for ln in hits.splitlines():
            out.add(ln.split(":", 1)[1] if ln.startswith("origin/main:") else ln)
    _mem[key] = (time.time(), sorted(out))
    return sorted(out)


def roots_for_files(files):
    """[(name, tier)] of every root whose directory one of these files sits in (a merged PR's files
    for a privileged run). Tiers that share a directory both count."""
    out = []
    try:
        spec = roots_spec()
    except (CtxError, ValueError):
        return out
    for name, sp in spec.items():
        for tier, ts in sp["tiers"].items():
            d = ts["root"].rstrip("/")
            if any(f.startswith(d + "/") for f in files or []):
                out.append((name, tier))
    return out


def root_code(name, tier, limit=CODE_MAX):
    """The root's .tf files on origin/main (tfvars left out), for the model."""
    p = root_paths(name, tier)
    if not p:
        return ""
    parts, total = [], 0
    for f in _git("ls-tree", "-r", "--name-only", "origin/main", p["dir"]).splitlines():
        if not f.endswith(".tf"):
            continue
        body = _git("show", f"origin/main:{f}")
        chunk = f"### {f}\n{body}\n"
        if total + len(chunk) > limit:
            parts.append(f"[code truncated before {f}]\n")
            break
        parts.append(chunk)
        total += len(chunk)
    return "".join(parts)


def commit_subject(sha):
    """First line of a commit message from the local clone (cached). '' when unknown."""
    if not sha:
        return ""
    key = ("subject", sha)
    if key not in _mem:
        try:
            _mem[key] = _git("log", "-1", "--format=%s", sha, timeout=10).strip()
        except CtxError:
            return ""
    return _mem[key]


def code_comments(name, tier):
    """{for_each key: comment text} from the '#   <key>  text' comment lines in the root's code on
    origin/main, so a key like code-publishing reads as what it is."""
    p = None
    try:
        p = root_paths(name, tier)
    except (CtxError, ValueError):
        return {}
    if not p:
        return {}
    key = ("comments", _spec["main"], name)
    if key in _mem:
        return _mem[key]
    out = {}
    try:
        for f in _git("ls-tree", "-r", "--name-only", "origin/main", p["dir"]).splitlines():
            if not f.endswith(".tf"):
                continue
            last = None
            for ln in _git("show", f"origin/main:{f}").splitlines():
                m = re.match(r"^\s*#\s{1,4}([a-z0-9][a-z0-9-]+)\s{1,}(\S.*)$", ln)
                if m and m.group(1) not in out:
                    out[m.group(1)] = m.group(2).strip()
                    last = m.group(1)
                    continue
                c = re.match(r"^\s*#\s{6,}(\S.*)$", ln)
                if c and last:
                    out[last] += " " + c.group(1).strip()
                else:
                    last = None
    except CtxError:
        pass
    _mem[key] = out
    return out


# ---- open PRs and their diffs (background refresh, local reads) ----


def _ov_file():
    return CACHE / "open-prs.json"


def _diff_file(head):
    return CACHE / "pr-diffs" / f"{head}.diff"


def refresh_open_prs():
    """Read every open PR with its changed files (and keep the full diff of each, by head sha, for
    the removal check). Blocking. Raises CtxError on any read failure: a partial list never
    replaces the last good one. Each PR also carries same_files, the changed files whose content
    at its head equals origin/main (same_main), see _same_as_main."""
    main = _fresh_main()
    if main and main != _spec.get("main"):
        _spec["at"] = 0.0  # re-read the roots at the main the comparison used
    raw = _run(
        [
            GH,
            "pr",
            "list",
            "-R",
            _repo(),
            "--state",
            "open",
            "--limit",
            "100",
            "--json",
            "number,title,url,headRefName,headRefOid,author,isDraft",
        ],
        timeout=60,
    )
    prs = []
    for p in json.loads(raw or "[]"):
        head = p.get("headRefOid") or ""
        df = _diff_file(head)
        if head and df.exists():
            diff = df.read_text()
        else:
            diff = _run([GH, "pr", "diff", str(p["number"]), "-R", _repo()], timeout=90)
            if head:
                df.parent.mkdir(parents=True, exist_ok=True)
                df.write_text(diff)
        files = sorted(set(re.findall(r"(?m)^diff --git a/\S+ b/(\S+)", diff)))
        same_main, same_files = _same_as_main(head, files, main)
        prs.append(
            {
                "number": p["number"],
                "title": p.get("title") or "",
                "url": p.get("url") or f"https://github.com/{_repo()}/pull/{p['number']}",
                "branch": p.get("headRefName") or "",
                "head": head,
                "author": (p.get("author") or {}).get("login") or "",
                "draft": bool(p.get("isDraft")),
                "files": files,
                "same_main": same_main,
                "same_files": same_files,
            }
        )
    # Keep the newest DIFF_KEEP diff files.
    try:
        ds = sorted((CACHE / "pr-diffs").glob("*.diff"), key=lambda x: x.stat().st_mtime)
        for old in ds[:-DIFF_KEEP]:
            old.unlink()
    except OSError:
        pass
    return prs


def _fresh_main():
    """origin/main after one fetch, or "" when the fetch or read fails (then nothing counts as landed)."""
    try:
        _git("fetch", "-q", "origin", "main", timeout=90)
        return _git("rev-parse", "origin/main").strip()
    except CtxError:
        return ""


def _same_as_main(head, files, main):
    """(main, files) where files are the PR's changed files that are byte-identical at its head
    and at main. gh pr diff compares with the merge base, so a PR stacked on a merged parent still lists
    the parent's files although main already has them, and a card would warn that applying main undoes
    it. Two-dot git diff main..head names the files that really differ. Cached per (head, main). Any
    read failure (head not fetchable, git error) returns ("", []), so every file still counts."""
    if not (head and main and files):
        return "", []
    key = ("same", head, main)
    if key in _mem:
        return _mem[key]
    try:
        try:
            _git("cat-file", "-e", f"{head}^{{commit}}")
        except CtxError:
            _git("fetch", "-q", "origin", head, timeout=90)
        differ = set(
            _git(
                "diff", "--name-only", "--no-renames", main, head, "--", *files, timeout=60
            ).split()
        )
    except CtxError:
        return "", []
    out = (main, sorted(f for f in files if f not in differ))
    _mem[key] = out
    return out


def _landed(p):
    """The PR's files already on main, trusted only when they were compared with the current main."""
    if not p.get("same_files") or not p.get("same_main"):
        return set()
    return set(p["same_files"]) if p["same_main"] == _spec.get("main") else set()


def _ov_refresh():
    try:
        prs = refresh_open_prs()
        rec = {"checked_at": _now(), "prs": prs, "error": None}
        _write_json(_ov_file(), rec)
        with _lock:
            _ov.update(at=time.time(), prs=prs, error=None)
    except (CtxError, ValueError, OSError) as e:
        with _lock:
            _ov.update(error=str(e)[:300])
    finally:
        with _lock:
            _ov["busy"] = False


def open_prs(kick=True):
    """(prs or None, checked_at epoch, error). Served from memory or the disk copy. A stale or cold
    list starts one background refresh. Never blocks."""
    with _lock:
        if not _ov["loaded"]:
            d = _read_json(_ov_file(), {})
            if isinstance(d.get("prs"), list):
                _ov.update(prs=d["prs"], at=_epoch(d.get("checked_at")))
            _ov["loaded"] = True
        stale = time.time() - _ov["at"] > OV_TTL_S
        start = kick and stale and not _ov["busy"]
        if start:
            _ov["busy"] = True
        out = (_ov["prs"], _ov["at"], _ov["error"], _ov["busy"])
    if start:
        threading.Thread(target=_ov_refresh, name="tf-open-prs", daemon=True).start()
    return out[0], out[1], out[2]


def _quoted_keys_net_removed(diff, keys):
    """Keys whose quoted form ("key") the diff removes more often than it adds, comments ignored."""
    out = []
    for k in keys:
        q = f'"{k}"'
        minus = plus = 0
        for ln in diff.splitlines():
            if ln.startswith(("---", "+++")):
                continue
            body = ln[1:].split("#", 1)[0]
            if ln.startswith("-") and q in body:
                minus += 1
            elif ln.startswith("+") and q in body:
                plus += 1
        if minus > plus:
            out.append(k)
    return out


def _root_diff(head, paths):
    """The part of a PR's diff that touches the root's files, without files already on main."""
    try:
        raw = _diff_file(head).read_text()
    except OSError:
        return ""
    with _lock:
        mine = [p for p in _ov.get("prs") or [] if p.get("head") == head]
    landed = _landed(mine[0]) if mine else set()
    keep = []
    for ch in re.split(r"(?m)^(?=diff --git )", raw):
        m = re.match(r"diff --git a/\S+ b/(\S+)", ch)
        if m and m.group(1) not in landed and touches([m.group(1)], paths):
            keep.append(ch)
    return "".join(keep)


def overlaps(name, tier, resources=(), exclude=(), kick=True):
    """Open PRs that change this root's files, and what each would lose if the owner applied main now.
    status ok (list current), checking (no list yet, a read is running) or unknown (the read
    failed or the list is too old). prs: [{number, title, url, author, draft, files, removes}],
    removes = for_each keys of resources this plan adds that the PR deletes from the code."""
    try:
        paths = root_paths(name, tier)
    except (CtxError, ValueError) as e:
        return {
            "status": "unknown",
            "error": f"could not read the root paths: {e}"[:300],
            "prs": [],
        }
    if not paths:
        return {
            "status": "unknown",
            "error": f"{name} ({tier}) is not in the roots spec",
            "prs": [],
        }
    prs, at, err = open_prs(kick=kick)
    age = time.time() - at if at else None
    if prs is None or age is None:
        return {
            "status": "unknown" if err else "checking",
            "error": err or "",
            "prs": [],
            "paths": paths,
        }
    status = "ok" if age <= OV_MAX_AGE_S else "unknown"
    adds = [r for r in resources or [] if r.get("action") in ("add", "create", "replace")]
    keys = sorted({k for r in adds for k in [_for_each_key(r.get("address") or "")] if k})
    hits = []
    for p in prs:
        if p.get("number") in exclude:
            continue
        landed = _landed(p)
        files = [f for f in touches(p.get("files") or [], paths) if f not in landed]
        if not files:
            continue
        diff = _root_diff(p.get("head") or "", paths)
        hits.append(
            dict(
                {
                    k: p.get(k)
                    for k in ("number", "title", "url", "author", "draft", "head", "branch")
                },
                files=files,
                removes=_quoted_keys_net_removed(diff, keys) if diff else [],
                diff_known=bool(diff),
            )
        )
    return {
        "status": status,
        "checked_at": dt.datetime.fromtimestamp(at, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "error": "" if status == "ok" else (err or "the open PR list is older than 15 minutes"),
        "prs": hits,
        "paths": paths,
    }


def overlap_diffs(ov, limit=12000):
    """The root part of each overlapping PR's diff, for the model."""
    out = []
    for p in ov.get("prs") or []:
        d = _root_diff(p.get("head") or "", ov.get("paths"))
        if d:
            out.append(f"### PR #{p['number']} {p.get('title')}\n{d[:limit]}")
    return "\n\n".join(out)


# ---- plan text ----


def owner_plan_text(item):
    """The 'Terraform will perform the following actions' block of an Owner root's saved plan, from
    the plan log owner_roots.py writes. '' unless the log belongs to this plan (its header names
    the plan run that produced plan_sha256)."""
    name, tier = item.get("name"), item.get("tier")
    try:
        text = (OWNER_LOGS / f"{name}-{tier}.log").read_text()
    except OSError:
        return ""
    head = text.splitlines()[0] if text else ""
    m = re.match(r"plan \S+ at (\S+)", head)
    if not m or (item.get("started") and m.group(1) != item.get("started")):
        return ""
    return actions_block(text)


def actions_block(text):
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if "Terraform will perform the following actions" in ln:
            start = i
    if start is None:
        return ""
    end = next(
        (i for i in range(start, len(lines)) if lines[i].startswith("Plan:")), len(lines) - 1
    )
    return "\n".join(lines[start : end + 1])


def _for_each_key(address):
    m = re.search(r'\["([^"]+)"\]$', address or "")
    return m.group(1) if m else ""


def _val(s):
    s = s.strip()
    if s.startswith('"') and s.endswith('"') and len(s) >= 2:
        return s[1:-1]
    return s


def parse_plan(text):
    """[{address, type, action, key, attrs, added_ids, removed_ids, changed}] from plan text.
    attrs = `name = value` lines of the resource, first occurrence wins (the new value for an
    in-place change), added_ids / removed_ids = GUIDs that appear only on + or only on - lines (a
    list of identities that grows or shrinks), changed = names of attributes or blocks marked ~."""
    out, cur = [], None
    plus_ids, minus_ids = set(), set()

    excl = {"on": False}

    def close():
        if cur is not None:
            # Only an in-place change has a before and after list. A create or delete prints every
            # id once (its own scope, the subscription), which is not a list that grows.
            ch = cur["action"] == "change"
            cur["added_ids"] = sorted(plus_ids - minus_ids) if ch else []
            cur["removed_ids"] = sorted(minus_ids - plus_ids) if ch else []
            cur["ids_excluded"] = bool(excl["on"]) and ch
            cur["changed"] = sorted(set(cur["changed"]))

    for ln in (text or "").splitlines():
        m = _RES_HEAD.match(ln)
        if m:
            close()
            act = _ACTION.get(
                m.group(2), "moved" if m.group(2).startswith("has moved") else m.group(2)
            )
            addr = m.group(1)
            base = re.sub(r"\[[^\]]*\]$", "", addr)
            cur = {
                "address": addr,
                "type": base.split(".")[-2] if "." in base else "",
                "action": act,
                "key": _for_each_key(addr),
                "attrs": {},
                "changed": [],
            }
            plus_ids, minus_ids = set(), set()
            excl["on"] = False
            out.append(cur)
            continue
        if cur is None or ln.startswith("Plan:"):
            continue
        stripped = ln.strip()
        if re.match(r"^[-+~/]+ resource ", stripped):
            continue
        sign = stripped[:1] if stripped[:1] in "+-~" else ""
        body = stripped[1:].strip() if sign else stripped
        if sign == "+":
            plus_ids.update(x.lower() for x in _GUID.findall(body))
            if "!in" in body and _GUID.search(body):
                excl["on"] = True
        elif sign == "-":
            minus_ids.update(x.lower() for x in _GUID.findall(body))
        a = re.match(r"^([a-z_][a-z0-9_]*)\s*=\s*(.*)$", body)
        if a:
            k, v = a.group(1), a.group(2)
            if sign == "~":
                cur["changed"].append(k)
                if "->" in v:
                    v = v.split("->", 1)[1]
            # A delete prints every attribute as `- name = value -> null`, so for a delete the old
            # value is the only value there is. Elsewhere a - line is the before side and is skipped.
            gone = sign == "-" and cur["action"] == "destroy"
            if gone:
                v = re.sub(r"\s*->\s*null\s*$", "", v)
            if (
                v.strip() not in ("<<-EOT", "{", "[")
                and k not in cur["attrs"]
                and (sign != "-" or gone)
            ):
                cur["attrs"][k] = _val(v)
            continue
        bm = re.match(r"^([a-z_][a-z0-9_]*)\s*\{$", body)
        if bm and sign == "~":
            cur["changed"].append(bm.group(1))
    close()
    return out


# ---- principal names (az, read only, cached) ----


def _names_file():
    return CACHE / "principals.json"


def resolve_principal(pid):
    """{name, kind} for an object id through the provider's resolve_principal, or None (the null default). Blocking."""
    fn = getattr(_provider(), "resolve_principal", None)
    if not callable(fn):
        return None
    try:
        got = fn(pid)
    except Exception:  # noqa: BLE001 - a provider failure is an unknown name, never an error
        return None
    return got if isinstance(got, dict) and got.get("name") else None


def _names_worker():
    try:
        while True:
            with _lock:
                if not _names["queue"]:
                    _names["busy"] = False
                    return
                pid = _names["queue"].pop()
            got = resolve_principal(pid)
            with _lock:
                d = _read_json(_names_file(), {})
                d[pid] = dict(got or {"name": "", "kind": "unknown"}, at=_now())
                _write_json(_names_file(), d)
    except Exception:  # noqa: BLE001 - a background lookup never takes the server down
        with _lock:
            _names["busy"] = False


def principal_names(ids, blocking=False):
    """{id: {name, kind}} from the cache. Missing or old ids are looked up in one background
    thread (or right here when blocking). Unknown ids are left out."""
    ids = sorted({i.lower() for i in ids or [] if _GUID.fullmatch(i or "")})
    d = _read_json(_names_file(), {})
    out, missing = {}, []
    for i in ids:
        ent = d.get(i)
        if ent and time.time() - _epoch(ent.get("at")) < NAME_TTL_S:
            if ent.get("name"):
                out[i] = {"name": ent["name"], "kind": ent.get("kind")}
        else:
            missing.append(i)
    if not missing:
        return out
    if blocking:
        for i in missing:
            got = resolve_principal(i)
            with _lock:
                d = _read_json(_names_file(), {})
                d[i] = dict(got or {"name": "", "kind": "unknown"}, at=_now())
                _write_json(_names_file(), d)
            if got:
                out[i] = got
        return out
    with _lock:
        _names["queue"].update(missing)
        start = not _names["busy"]
        if start:
            _names["busy"] = True
    if start:
        threading.Thread(target=_names_worker, name="tf-principals", daemon=True).start()
    return out


# ---- plain sentences ----

ROLE_MEANING = {
    "storage blob data contributor": "read, write and delete blobs",
    "storage blob data reader": "read blobs",
    "storage blob data owner": "read, write and delete blobs and set their access",
    "reader": "read the settings of everything in scope, but change nothing",
    "contributor": "create, change and delete everything in scope, but not grant access",
    "owner": "do anything in scope, including granting access to others",
    "user access administrator": "grant and remove access in scope",
    "role based access control administrator": "grant and remove access in scope",
    "key vault secrets user": "read secret values",
    "key vault secrets officer": "read, write and delete secrets",
    "key vault administrator": "manage everything in the vault, including secrets and access",
    "key vault certificates officer": "manage certificates",
    "key vault crypto user": "use keys to encrypt, decrypt, sign and verify",
    "monitoring metrics publisher": "send metrics and logs",
    "automation contributor": "manage the Automation account, its runbooks and jobs",
    "website contributor": "manage web apps and deploy code to them",
    "acrpush": "push and pull container images",
    "acrpull": "pull container images",
    "desktop virtualization user": "sign in to the desktops this application group publishes",
    "storage file data smb share contributor": "read, write and delete files on the share",
    "storage file data smb share elevated contributor": "read, write and delete files on the share and change their NTFS permissions",
    "storage file data smb share reader": "read files on the share",
    "virtual machine user login": "sign in to the VM as a standard user",
    "virtual machine administrator login": "sign in to the VM as a local administrator",
}

TYPE_PLAIN = {
    "azurerm_role_assignment": "Azure role assignment",
    "azurerm_monitor_scheduled_query_rules_alert_v2": "Log Analytics alert rule",
    "azurerm_federated_identity_credential": "federated credential on a managed identity",
    "azuread_application_federated_identity_credential": "federated credential on an app registration",
    "azurerm_key_vault_access_policy": "Key Vault access policy",
    "azuread_app_role_assignment": "Microsoft Graph application permission",
    "azurerm_user_assigned_identity": "managed identity",
    "azuread_application": "app registration",
    "azuread_service_principal": "service principal",
    "azurerm_storage_account": "storage account",
    "azurerm_storage_container": "storage container",
    "azurerm_management_lock": "delete lock",
    "azurerm_monitor_diagnostic_setting": "diagnostic setting (log forwarding)",
    "azurerm_automation_runbook": "Automation runbook",
}

ACCESS_TYPES = (
    "azurerm_role_assignment",
    "azurerm_federated_identity_credential",
    "azuread_application_federated_identity_credential",
    "azurerm_key_vault_access_policy",
    "azuread_app_role_assignment",
    "azuread_application_password",
    "azuread_service_principal_password",
)


_CHILD_KIND = {
    "secrets": "Secret",
    "keys": "Key",
    "certificates": "Certificate",
    "runbooks": "Runbook",
    "queues": "Queue",
    "tables": "Table",
    "extensions": "Extension",
}


def _child_scope(parts, parent_type, parent_text):
    """A scope below a resource (.../vaults/v/secrets/s) in words: the child leads and the parent
    follows, so a single secret never reads as the whole vault. Service segments named default
    (blobServices/default) are skipped. Returns parent_text when the scope ends at the parent."""
    low = [x.lower() for x in parts]
    if parent_type not in low:
        return parent_text
    i = low.index(parent_type) + 2
    pairs = [
        (parts[j], parts[j + 1])
        for j in range(i, len(parts) - 1, 2)
        if parts[j + 1].lower() != "default"
    ]
    if not pairs:
        return parent_text
    out = parent_text
    for typ, name in pairs:
        kind = _CHILD_KIND.get(typ.lower()) or typ.rstrip("s").lower() or typ
        out = f"{kind} {name} in {out}"
    return out


def scope_plain(scope):
    """An ARM id in words: the container, account, vault or group it names."""
    s = scope or ""
    parts = s.strip("/").split("/")
    kv = {}
    for i in range(0, len(parts) - 1, 2):
        kv[parts[i].lower()] = parts[i + 1]
    rg = kv.get("resourcegroups")
    if "fileshares" in kv and "storageaccounts" in kv:
        return f"file share {kv['fileshares']} in storage account {kv['storageaccounts']}"
    if "applicationgroups" in kv:
        return _child_scope(
            parts, "applicationgroups", f"desktop application group {kv['applicationgroups']}"
        )
    if "hostpools" in kv:
        return _child_scope(parts, "hostpools", f"host pool {kv['hostpools']}")
    if "virtualmachines" in kv:
        return _child_scope(parts, "virtualmachines", f"virtual machine {kv['virtualmachines']}")
    if "containers" in kv and "storageaccounts" in kv:
        return f"the {kv['containers']} container of storage account {kv['storageaccounts']}" + (
            f" (resource group {rg})" if rg else ""
        )
    if "storageaccounts" in kv:
        return _child_scope(
            parts,
            "storageaccounts",
            f"storage account {kv['storageaccounts']}" + (f" (resource group {rg})" if rg else ""),
        )
    if "vaults" in kv:
        return _child_scope(
            parts, "vaults", f"Key Vault {kv['vaults']}" + (f" (resource group {rg})" if rg else "")
        )
    if "automationaccounts" in kv:
        return _child_scope(
            parts,
            "automationaccounts",
            f"Automation account {kv['automationaccounts']}"
            + (f" (resource group {rg})" if rg else ""),
        )
    if rg and len(parts) <= 4:
        return f"the whole resource group {rg}"
    if rg:
        return f"{parts[-1]} in resource group {rg}"
    if "subscriptions" in kv and len(parts) <= 2:
        return f"the whole subscription {kv['subscriptions'][:8]}"
    return s or "an unknown scope"


def _who(pid, key, names, comments):
    n = (names.get((pid or "").lower()) or {}).get("name")
    bits = []
    if n:
        bits.append(n)
    if key:
        bits.append(f'the "{key}" entry in the code')
    if pid:
        bits.append(f"object id {pid[:8]}")
    if not n and pid:
        bits.append("name not resolved yet")
    return (
        ", ".join(bits[:1]) + (f" ({', '.join(bits[1:])})" if len(bits) > 1 else "")
        if bits
        else "an unknown identity"
    )


def explain(res, names=None, comments=None):
    """One plain sentence per resource: what it is and what the plan does to it, naming the
    identity, the scope and what the access lets it do for access resources. The Terraform address
    follows in parentheses so the raw data stays traceable."""
    names, comments = names or {}, comments or {}
    out = []
    for r in res or []:
        a, t, at = r.get("action"), r.get("type") or "", r.get("attrs") or {}
        what = TYPE_PLAIN.get(
            t, t.replace("azurerm_", "").replace("azuread_", "").replace("_", " ") or "resource"
        )
        nm = str(at.get("name") or "")
        named = nm if nm and "known after apply" not in nm else ""
        key = r.get("key") or ""
        ref = f"({r.get('address')})"
        if t == "azurerm_role_assignment":
            role = at.get("role_definition_name") or "an unknown role"
            who = _who(at.get("principal_id") or "", key, names, comments)
            scope = scope_plain(at.get("scope"))
            meaning = ROLE_MEANING.get(role.lower(), "")
            cond = re.findall(r"StringStartsWith '([^']+)'", at.get("condition") or "")
            if a == "destroy":
                s = f"A role assignment is deleted {ref}: {who} loses the {role} role on {scope}"
            elif a == "change":
                s = f"A role assignment changes {ref}: {who} keeps the {role} role on {scope}"
            else:
                s = f"A new role assignment is created {ref}: it gives {who} the {role} role on {scope}"
            if meaning:
                s += f", which lets it {meaning}"
            if cond:
                s += f", limited by a condition to paths starting with {_join(cond)}"
            if not at:
                s = f"A role assignment {ref} is {'deleted' if a == 'destroy' else 'created' if a == 'add' else 'changed'}, details in the plan"
            s += "."
            if at.get("description") and "known after apply" not in at["description"]:
                s += f' The assignment describes itself as "{at["description"]}".'
            if key and comments.get(key):
                s += f' The code describes {key} as "{comments[key]}".'
            out.append(s)
            continue
        if (
            t
            in (
                "azurerm_federated_identity_credential",
                "azuread_application_federated_identity_credential",
            )
            and at
        ):
            subj, iss = (
                at.get("subject") or "an unknown subject",
                at.get("issuer") or "an unknown issuer",
            )
            who = _who(at.get("parent_id") or at.get("application_id") or "", key, names, comments)
            verb = "is deleted, so" if a == "destroy" else "is created, so"
            out.append(
                f"A federated credential {verb} workloads presenting subject {subj} from {iss} "
                f"{'can no longer' if a == 'destroy' else 'can'} sign in as {who} without a secret {ref}."
            )
            continue
        if t == "azurerm_key_vault_access_policy" and at:
            who = _who(at.get("object_id") or "", key, names, comments)
            perms = at.get("secret_permissions") or at.get("key_permissions") or ""
            out.append(
                f"A Key Vault access policy for {who} is {'deleted' if a == 'destroy' else 'set'}"
                f"{' with ' + perms if perms else ''} {ref}."
            )
            continue
        verb = {
            "add": "is created",
            "change": "changes in place",
            "destroy": "is deleted",
            "replace": "is deleted and created again",
            "import": "is imported into state without changing it",
            "read": "is read",
        }.get(a, a or "is touched")
        lead = (
            f"The {what}" + (f" {named}" if named else "")
            if a != "add"
            else f"A new {what}" + (f" named {named}" if named else "")
        )
        s = f"{lead} {verb} {ref}."
        if a == "change" and r.get("changed"):
            s += f" What changes: {_join(r['changed'])}."
        for label, ids in (("adds", r.get("added_ids")), ("removes", r.get("removed_ids"))):
            if ids:
                s += (
                    f" It {label} "
                    + _join(
                        [
                            f"{(names.get(i) or {}).get('name') or 'an identity not resolved yet'} ({i[:8]})"
                            for i in ids
                        ]
                    )
                    + (" to" if label == "adds" else " from")
                    + (
                        " the list of identities its query ignores, so their activity no longer raises this alert"
                        if r.get("ids_excluded") and label == "adds"
                        else " the list of identities its query ignores, so their activity raises this alert again"
                        if r.get("ids_excluded")
                        else " a list of identity ids in its settings"
                    )
                    + "."
                )
        out.append(s)
    return out


def _join(items):
    items = [x for x in items if x]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def access_changes(res):
    """Resources that add or remove access (role assignments, federated credentials, Key Vault and
    Graph grants, secrets on app registrations)."""
    return [
        r
        for r in res or []
        if (r.get("type") or "") in ACCESS_TYPES
        and r.get("action") in ("add", "destroy", "replace", "create", "delete")
    ]


def access_rows(res, names=None):
    """The access a plan grants or takes away, one row per (change, identity, role) with every scope
    it lands on: {change add|remove, who, who_kind, principal_id, role, means, on[], keys[], move}.
    move is True when the same identity gets the same role in this plan where it also loses it
    (the grant moves to new resources, it does not widen). Rows the plan text does not detail keep
    who/role empty and say so, never a guess."""
    names = names or {}
    rows, idx = [], {}
    for r in access_changes(res):
        if (r.get("type") or "") != "azurerm_role_assignment":
            continue
        at = r.get("attrs") or {}
        change = "remove" if r.get("action") in ("destroy", "delete") else "add"
        pid = (at.get("principal_id") or "").lower()
        role = at.get("role_definition_name") or ""
        n = names.get(pid) or {}
        k = (change, pid, role.lower()) if pid and role else (change, r.get("address"), "")
        row = idx.get(k)
        if row is None:
            row = {
                "change": change,
                "who": n.get("name")
                or (
                    f"object id {pid[:8]} (name not resolved yet)"
                    if pid
                    else "not shown in the plan"
                ),
                "who_kind": at.get("principal_type") or n.get("kind") or "",
                "principal_id": pid,
                "role": role or "not shown in the plan",
                "means": ROLE_MEANING.get(role.lower(), ""),
                "on": [],
                "scopes": [],
                "keys": [],
                "move": False,
            }
            idx[k] = row
            rows.append(row)
        if at.get("scope") and at["scope"] not in row["scopes"]:
            row["scopes"].append(at["scope"])  # raw ARM id, used by the AVD scope check
        sc = scope_plain(at.get("scope")) if at.get("scope") else ""
        if sc and sc not in row["on"]:
            row["on"].append(sc)
        if r.get("key"):
            row["keys"].append(r["key"])
    held = {
        (r["principal_id"], r["role"].lower())
        for r in rows
        if r["change"] == "remove" and r["principal_id"]
    }
    got = {
        (r["principal_id"], r["role"].lower())
        for r in rows
        if r["change"] == "add" and r["principal_id"]
    }
    for r in rows:
        if r["principal_id"] and (r["principal_id"], r["role"].lower()) in (held & got):
            r["move"] = True
    return rows


def ids_in(res):
    ids = set()
    for r in res or []:
        at = r.get("attrs") or {}
        for k in ("principal_id", "object_id"):
            if _GUID.fullmatch(at.get(k) or ""):
                ids.add(at[k].lower())
        ids.update(r.get("added_ids") or [])
        ids.update(r.get("removed_ids") or [])
    return sorted(ids)
