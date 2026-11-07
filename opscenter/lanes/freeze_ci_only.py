#!/usr/bin/env python3
"""
freeze_ci_only.py

Purpose: Decide whether a pull request only changes how CI checks pull requests, so a change freeze need not hold it. A freeze
         exists because a merge to main can deploy; a pull request that changes nothing but CI deploys nothing. The check is
         conservative and fails closed: a file the classifier cannot read, a changed path outside the CI paths, or a workflow
         that can run on anything but a pull request, makes the answer "held".

Rules:   1. Every changed file is a CI file: it matches a glob of `ci_paths` (default `.github/workflows/*`, `.github/scripts/*`,
            `.github/actions/*`). Anything else is held.
         2. A changed workflow is judged on both sides, the pull request head and the base. If either side can be triggered by
            anything other than pull_request or merge_group (a push, a schedule, a release, a manual run, another workflow,
            pull_request_target, which runs with the base branch's permissions and secrets), it is held: it can run on main
            or with write access. A workflow whose file name starts with _ (a reusable workflow a deploy can call) is held by
            name. A workflow that names a deployment environment outside `environments_allowed` (default only
            DEFAULT_CI_ENVIRONMENTS, a plan-only name) is held, and so is an environment block or expression it cannot read.
         3. A changed script is judged by who runs it. Every workflow on either side that names the script, directly or through
            another script that names it, must be pull request only. A script that no workflow names is held (its use is unknown).
         4. Anything unreadable, unparseable or too deep to follow is held, with the reason. There is no YAML library here, so
            the `on:` reader is strict: an unclosed flow list, an open quote, a repeated `on:` key or uneven indentation
            reads as unparseable.

The reader is a slot: `fetch_and_classify(gh, repo, number, head, base)` reads the file list and both sides through the code host
(`gh api`), `classify(files, read_head, read_base)` is the pure part and takes two callables `read(path) -> text | None`.
Nothing here names an estate.
"""

import fnmatch
import json
import re

DEFAULT_CI_PATHS = (".github/workflows/*", ".github/scripts/*", ".github/actions/*")
# pull_request_target is not here: it runs with the base branch's permissions and secrets, so it is held.
PR_ONLY = {"pull_request", "merge_group"}
# The deployment environments a CI-only workflow may name. A plan-only name by default; the consumer sets its own
# (own_pr_merge policy `freeze_ci_environments`). An expression that may resolve to no environment ('') is allowed.
DEFAULT_CI_ENVIRONMENTS = ("terraform-plan",)
MAX_DEPTH = 4
_EVENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ON_KEY = re.compile(r"""^(?:on|"on"|'on')\s*:(.*)$""")


def _strip_comment(s):
    """The text before a YAML comment (a # at the start or after white space, outside quotes), or None when a quote is
    left open."""
    quote = None
    for i, ch in enumerate(s):
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or s[i - 1] in " \t"):
            return s[:i].rstrip()
    return None if quote else s.rstrip()


def _split_flow(s, opener, closer):
    """The items of one flow collection `[a, b]` or `{a: x, b: y}` written on one line, or None when it is not exactly one
    balanced collection (unclosed, unbalanced, an open quote, text after the closing bracket)."""
    if not (s.startswith(opener) and s.endswith(closer)):
        return None
    items, depth, quote, cur = [], 0, None, ""
    for i, ch in enumerate(s):
        if quote:
            cur += ch
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "[{":
            depth += 1
            if depth == 1:
                continue
        elif ch in "]}":
            depth -= 1
            if depth < 0:
                return None
            if depth == 0:
                if i != len(s) - 1:
                    return None  # text after the collection closed
                continue
        elif ch == "," and depth == 1:
            items.append(cur.strip())
            cur = ""
            continue
        cur += ch
    if quote or depth != 0:
        return None
    if cur.strip():
        items.append(cur.strip())
    return items


def _balanced(value):
    """False when a value opens a flow collection or a quote it does not close on the same line."""
    if value is None:
        return False
    if value.startswith("["):
        return _split_flow(value, "[", "]") is not None
    if value.startswith("{"):
        return _split_flow(value, "{", "}") is not None
    return True


def _event(raw):
    """An event name with its quotes removed, or None when it is not a plain event name."""
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        raw = raw[1:-1]
    return raw if _EVENT.match(raw) else None


def _events(items, mapping):
    out = set()
    for it in items:
        if mapping:
            key, sep, value = it.partition(":")
            if sep and not _balanced(value.strip()):
                return None
            name = _event(key)
        else:
            name = _event(it)
        if name is None:
            return None
        out.add(name)
    return out or None


def triggers(text):
    """The set of event names a workflow runs on, or None when the `on:` block cannot be read. Strict and fail closed: no
    YAML library is used, so anything this reader is not sure of (a missing or repeated `on:` key, an unclosed flow
    list, an open quote, a block scalar, an anchor or tag, mixed or uneven indentation, a name that is not an event)
    reads as None, and the caller holds the pull request."""
    lines = (text or "").splitlines()
    found = [(i, m) for i, m in ((i, _ON_KEY.match(ln)) for i, ln in enumerate(lines)) if m]
    if len(found) != 1:
        return None  # no `on:` key, or more than one: unknown
    i, m = found[0]
    rest = _strip_comment(m.group(1))
    if rest is None:
        return None
    rest = rest.strip()
    if rest:
        if rest.startswith("["):
            items = _split_flow(rest, "[", "]")
            return None if items is None else _events(items, mapping=False)
        if rest.startswith("{"):
            items = _split_flow(rest, "{", "}")
            return None if items is None else _events(items, mapping=True)
        name = _event(rest)
        return {name} if name else None  # a block scalar, anchor, alias, tag or odd text is unknown
    out, indent, form = set(), None, None
    for nxt in lines[i + 1 :]:
        if not nxt.strip() or nxt.lstrip().startswith("#"):
            continue
        lead = nxt[: len(nxt) - len(nxt.lstrip())]
        if "\t" in lead:
            return None
        cur = len(lead)
        if cur == 0:
            break
        if indent is None:
            indent = cur
        if cur < indent:
            return None  # uneven indentation
        body = _strip_comment(nxt.strip())
        if body is None:
            return None
        if cur > indent:
            # settings under one event: only their brackets and quotes are checked
            value = body[2:].strip() if body.startswith("- ") else body.partition(":")[2].strip()
            if not _balanced(value):
                return None
            continue
        if body.startswith("-"):
            if form == "map" or not body.startswith("- "):
                return None
            form = "list"
            name = _event(body[2:])
        else:
            key, sep, value = body.partition(":")
            if form == "list" or not sep or not _balanced(value.strip()):
                return None
            form = "map"
            name = _event(key)
        if name is None:
            return None
        out.add(name)
    return out or None


def environments(text):
    """Every deployment environment a workflow names. In an expression the names are the quoted values after && or ||
    (never the compared operands); a block or an expression with no such value is unknown and reads as `<block>` or
    `<expr>`, which no allowlist holds."""
    envs = set()
    for m in re.finditer(r"^\s*(?:-\s+)?[\"']?environment[\"']?\s*:(.*)$", text or "", re.M):
        raw = (_strip_comment(m.group(1)) or "").strip()
        if raw.startswith(("'", '"')) and raw[-1:] == raw[0] and len(raw) >= 2:
            raw = raw[1:-1]
        if not raw:
            envs.add("<block>")
            continue
        if "${{" in raw:
            found = re.findall(r"(?:&&|\|\|)\s*'([^']*)'", raw)
            envs.update(found or ["<expr>"])
        else:
            envs.add(raw)
    return envs


def is_ci_file(path, ci_paths):
    return any(fnmatch.fnmatch(path, g) for g in ci_paths)


def _workflow(path):
    return path.startswith(".github/workflows/") and path.endswith((".yml", ".yaml"))


def _names(text, path):
    """Whether the text names the path (by full path or by its file name after a separator)."""
    base = path.rsplit("/", 1)[-1]
    return (
        path in text
        or re.search(r"(?:^|[\s/\"'])" + re.escape(base) + r"(?:$|[\s\"'])", text) is not None
    )


def classify(
    files,
    read_head,
    read_base,
    ci_paths=DEFAULT_CI_PATHS,
    list_workflows=None,
    list_scripts=None,
    environments_allowed=None,
):
    """(ok, why). `files` are the changed paths. `read_head(path)` and `read_base(path)` return the text or None.
    `list_workflows()` and `list_scripts()` return the paths of every workflow and CI script (the same on both sides is
    enough: a path added by the pull request is read on the head side only). `environments_allowed` is the list of
    deployment environments a CI-only workflow may name (None: DEFAULT_CI_ENVIRONMENTS)."""
    allowed = set(DEFAULT_CI_ENVIRONMENTS if environments_allowed is None else environments_allowed)
    allowed.add("")  # an expression that resolves to no environment
    if not files:
        return False, "no changed files listed"
    outside = [f for f in files if not is_ci_file(f, ci_paths)]
    if outside:
        return False, f"{outside[0]} is not a CI file"
    workflows = list(list_workflows() if list_workflows else [f for f in files if _workflow(f)])
    scripts = list(list_scripts() if list_scripts else [])

    def trigger_problem(path):
        if path.rsplit("/", 1)[-1].startswith("_"):
            return (
                f"{path} is a reusable workflow (its name starts with _), so a deploy can call it"
            )
        for side, read in (("head", read_head), ("base", read_base)):
            text = read(path)
            if text is None:
                if side == "base" and read_head(path) is not None:
                    continue  # a new workflow has no base side
                if side == "head" and read_base(path) is not None:
                    continue  # a deleted workflow has no head side
                return f"{path} could not be read"
            t = triggers(text)
            if t is None:
                return f"{path}: the triggers could not be read ({side})"
            extra = sorted(t - PR_ONLY)
            if extra:
                return f"{path} can run on {', '.join(extra)} ({side}), so it can run on main"
            envs = sorted(environments(text) - allowed)
            if envs:
                return f"{path} uses environment {', '.join(envs)} ({side}), which is not a CI environment"
        return None

    for f in files:
        if _workflow(f):
            why = trigger_problem(f)
            if why:
                return False, why
    changed_scripts = [f for f in files if not _workflow(f)]
    for s in changed_scripts:
        # every file, on either side, that runs this script, then who runs those, up to MAX_DEPTH
        users, frontier, seen, depth = set(), {s}, {s}, 0
        while frontier:
            depth += 1
            if depth > MAX_DEPTH:
                return False, f"{s}: used through too many scripts to follow"
            nxt = set()
            for target in frontier:
                for path in workflows + scripts:
                    if path in seen:
                        continue
                    texts = [t for t in (read_head(path), read_base(path)) if t is not None]
                    if not texts and path not in files:
                        return False, f"{path} could not be read"
                    if any(_names(t, target) for t in texts):
                        seen.add(path)
                        (users if _workflow(path) else nxt).add(path)
                        if not _workflow(path):
                            nxt.add(path)
            frontier = nxt
        if not users:
            return False, f"{s} is not named by any workflow, so its use is unknown"
        for w in sorted(users):
            why = trigger_problem(w)
            if why:
                return False, f"{s} is used by {why}"
    return True, "only changes how CI checks pull requests"


def fetch_and_classify(
    gh, repo, number, head, base, ci_paths=DEFAULT_CI_PATHS, environments_allowed=None
):
    """The code host part: list the changed files, read both sides, classify. `gh(args, raw=True)` returns text and raises on
    failure. Any failure to read is held."""
    try:
        out = gh(
            [
                "api",
                "--paginate",
                f"repos/{repo}/pulls/{number}/files?per_page=100",
                "--jq",
                ".[].filename",
            ],
            raw=True,
        )
        files = [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
    except Exception as e:  # noqa: BLE001 - unreadable means held
        return False, f"changed files could not be listed: {str(e)[:120]}"

    def read(ref):
        def one(path):
            try:
                body = gh(
                    ["api", f"repos/{repo}/contents/{path}?ref={ref}", "--jq", ".content"], raw=True
                )
            except Exception:  # noqa: BLE001
                return None
            try:
                import base64

                return base64.b64decode((body or "").strip()).decode("utf-8", "replace")
            except ValueError:
                return None

        return one

    def tree(ref):
        try:
            out = gh(
                ["api", f"repos/{repo}/git/trees/{ref}?recursive=1", "--jq", ".tree[].path"],
                raw=True,
            )
        except Exception:  # noqa: BLE001
            return None
        return [p.strip() for p in (out or "").splitlines() if p.strip()]

    paths = set()
    for ref in (head, base):
        t = tree(ref)
        if t is None:
            return False, "the file tree could not be read"
        paths |= set(t)
    return classify(
        files,
        read(head),
        read(base),
        ci_paths,
        list_workflows=lambda: sorted(p for p in paths if _workflow(p)),
        list_scripts=lambda: sorted(
            p for p in paths if is_ci_file(p, ci_paths) and not _workflow(p)
        ),
        environments_allowed=environments_allowed,
    )


if __name__ == "__main__":
    import sys

    data = json.load(sys.stdin)
    ok, why = classify(data["files"], data["head"].get, data["base"].get)
    print(json.dumps({"ci_only": ok, "why": why}))
    sys.exit(0 if ok else 10)
