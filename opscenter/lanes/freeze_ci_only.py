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
            anything other than pull_request, pull_request_target or merge_group (a push, a schedule, a release, a manual run,
            another workflow), it is held: it can run on main.
         3. A changed script is judged by who runs it. Every workflow on either side that names the script, directly or through
            another script that names it, must be pull request only. A script that no workflow names is held (its use is unknown).
         4. Anything unreadable, unparseable or too deep to follow is held, with the reason.

The reader is a slot: `fetch_and_classify(gh, repo, number, head, base)` reads the file list and both sides through the code host
(`gh api`), `classify(files, read_head, read_base)` is the pure part and takes two callables `read(path) -> text | None`.
Nothing here names an estate.
"""

import fnmatch
import json
import re

DEFAULT_CI_PATHS = (".github/workflows/*", ".github/scripts/*", ".github/actions/*")
PR_ONLY = {"pull_request", "pull_request_target", "merge_group"}
MAX_DEPTH = 4


def triggers(text):
    """The set of event names a workflow runs on, or None when the `on:` block cannot be read."""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        m = re.match(r"""^["']?on["']?\s*:\s*(.*?)\s*(?:#.*)?$""", ln)
        if not m:
            continue
        rest = m.group(1)
        if rest.startswith("["):
            return {x.strip().strip("\"'") for x in rest.strip("[]").split(",") if x.strip()}
        if rest and not rest.startswith(("{", "|", ">")):
            return {rest.strip("\"'")}
        if rest.startswith("{"):
            return {
                x.split(":")[0].strip().strip("\"'")
                for x in rest.strip("{}").split(",")
                if x.strip()
            }
        out, indent = set(), None
        for nxt in lines[i + 1 :]:
            if not nxt.strip() or nxt.lstrip().startswith("#"):
                continue
            cur = len(nxt) - len(nxt.lstrip())
            if cur == 0:
                break
            if indent is None:
                indent = cur
            if cur == indent:
                key = re.match(r"""^\s*["']?([A-Za-z_]+)["']?\s*:""", nxt)
                if key:
                    out.add(key.group(1))
                elif nxt.strip().startswith("-"):
                    out.add(nxt.strip()[1:].strip().strip("\"'"))
        return out or None
    return None


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
    files, read_head, read_base, ci_paths=DEFAULT_CI_PATHS, list_workflows=None, list_scripts=None
):
    """(ok, why). `files` are the changed paths. `read_head(path)` and `read_base(path)` return the text or None.
    `list_workflows()` and `list_scripts()` return the paths of every workflow and CI script (the same on both sides is
    enough: a path added by the pull request is read on the head side only)."""
    if not files:
        return False, "no changed files listed"
    outside = [f for f in files if not is_ci_file(f, ci_paths)]
    if outside:
        return False, f"{outside[0]} is not a CI file"
    workflows = list(list_workflows() if list_workflows else [f for f in files if _workflow(f)])
    scripts = list(list_scripts() if list_scripts else [])

    def trigger_problem(path):
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


def fetch_and_classify(gh, repo, number, head, base, ci_paths=DEFAULT_CI_PATHS):
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
    )


if __name__ == "__main__":
    import sys

    data = json.load(sys.stdin)
    ok, why = classify(data["files"], data["head"].get, data["base"].get)
    print(json.dumps({"ci_only": ok, "why": why}))
    sys.exit(0 if ok else 10)
