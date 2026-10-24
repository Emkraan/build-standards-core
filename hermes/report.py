#!/usr/bin/env python3
"""Keep the account's upward report on the core current: one issue, one machine-owned section.

Called by hermes/nightly.py once per nightly with every UI consumer that has a local clone, when
apply.report is on; each section is computed for all of them in one pass, grouped per repo under a
hashed label, and written in at most one issue edit. Each
account has one open issue labelled `consumer-report` on the core, authored by that account. This
module keeps the text between the markers

    <!-- nightly:candidates:start -->  ...  <!-- nightly:candidates:end -->

current: local parts that duplicate or extend a kit role, local tokens or classes the UI lint flags,
and local additions since the last run. A second machine-owned section,

    <!-- nightly:changes:start -->  ...  <!-- nightly:changes:end -->

holds, per registered UI repo, what changed since the previous nightly: local parts added, removed or
with a changed signature, the count of local tokens and kit-class restyles the lint flags, the
core-status count deltas, and new local parts that match a kit role (update_changes). State for it is
kept under ~/.config/build-standards-core/. Text outside the markers belongs to the people and is
never touched. The rules, each with its reason:

- Update only when the section changed. An unchanged section is not rewritten, so the issue shows
  no nightly noise and the notification stream stays quiet. Test: tests/test_nightly_report.py.
- Sanitise first. The text goes through checks/check-sanitised.py --file before it is posted, and a
  hit holds the update and is reported locally, so a business name never leaves the machine through
  the report. A body that names the owner account or core repo is held the same way
  (checks/check-consumer-neutral.py --file).
- One issue per run. The issue list lags a create by seconds, so the nightly passes one run dict to
  both sections: the section that creates the issue records its number there, and the other reads
  that number directly instead of listing again. A create whose number cannot be read is never
  followed by a second create in the same run. Test: tests/test_nightly_report.py.
- Never open a PR. The owner approves items in the issue; the owning account then opens the core PR
  and links the issue. Labels: `consumer-report` (the report) and `settling` (a proposal that is not
  ready yet, set by people, never by this module).

Python 3.9, stdlib only. Network access only through the gh CLI.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Callable

START = "<!-- nightly:candidates:start -->"
END = "<!-- nightly:candidates:end -->"
LABEL = "consumer-report"
UI_THEME_RULES = ("UI007", "UI008", "UI010")
EXPORT = re.compile(r"export\s+(?:default\s+)?(?:function|const|class)\s+([A-Z][A-Za-z0-9]+)")
SOURCE = (".tsx", ".ts", ".jsx", ".js")

Sh = Callable[..., "tuple[int, str]"]


def local_parts(clone: Path, overlay: str) -> dict[str, str]:
    """Capitalised exports in the paths the consumer's UI lint covers, as {name: relative file}."""
    base = clone / overlay if overlay else clone
    try:
        cfg = json.loads((base / "standards-local" / "ui-lint.json").read_text(encoding="utf8"))
    except (OSError, ValueError):
        cfg = {}
    root = (base / cfg.get("root", ".")).resolve()
    found: dict = {}
    for p in cfg.get("paths", ["src"]):
        target = root / p
        files = (
            [target] if target.is_file() else sorted(target.rglob("*")) if target.is_dir() else []
        )
        for f in files:
            if f.suffix not in SOURCE or "node_modules" in f.parts or ".test." in f.name:
                continue
            try:
                text = f.read_text(encoding="utf8", errors="replace")
            except OSError:
                continue
            for name in EXPORT.findall(text):
                found.setdefault(
                    name, f.relative_to(base).as_posix() if str(f).startswith(str(base)) else f.name
                )
    return found


def kit_parts(clone: Path, overlay: str, kit_src: str | None = None) -> set[str]:
    """Kit part names: the consumer's synced kit copy, or kit_src (the core clone's kit for a vendored
    repo, whose scrubbed copy carries no kit-core folder)."""
    src = Path(kit_src) if kit_src else (clone / overlay if overlay else clone) / "kit-core" / "src"
    names: set = set()
    if src.is_dir():
        for f in src.rglob("*"):
            if f.suffix in SOURCE and ".test." not in f.name:
                with contextlib.suppress(OSError):
                    names.update(EXPORT.findall(f.read_text(encoding="utf8", errors="replace")))
    return names


def relation(name: str, kit: set[str]) -> str:
    """duplicate: same name as a kit part. extends: a kit part's name inside the name (a wrapper)."""
    if name in kit:
        return "duplicates"
    for k in sorted(kit, key=len, reverse=True):
        if len(k) > 3 and k in name:
            return f"extends {k}"
    return ""


def lint_flags(clone: Path, overlay: str, sh: Sh) -> list[str]:
    """Local tokens or classes the core's UI lint flags, as `RULE file:line` lines (capped at 25)."""
    base = clone / overlay if overlay else clone
    lint = base / "lint-core" / "ui_lint.py"
    if not lint.is_file():
        return []
    rc, out = sh([sys.executable, str(lint), "--json"], cwd=base)
    try:
        findings = json.loads(out).get("findings", [])
    except ValueError:
        return []
    rows = sorted(
        {
            f"{f['rule']} {f.get('file', '?')}:{f.get('line', '?')}"
            for f in findings
            if f.get("rule") in UI_THEME_RULES
        }
    )
    return rows[:25]


def render_section(groups: dict[str, tuple]) -> str:
    """The text between the markers, markers included, grouped per repo label.
    groups: {label: (duplicates, flags, new)}. Stable: same input, same bytes."""
    out = [
        START,
        "",
        "Candidates for the core, kept current by the nightly, per registered UI repo. Approve, "
        "reject or mark each one in a comment; the owning account opens the core pull request.",
        "",
    ]
    for label in sorted(groups):
        duplicates, flags, new = groups[label]
        out += [f"### {label}", ""]
        for title, items in (
            ("Local parts that duplicate or extend a kit role", duplicates),
            ("Local tokens or classes the UI lint flags", flags),
            ("New local additions since the last run", new),
        ):
            out += [f"#### {title}", ""]
            out += [f"- {i}" for i in sorted(items)] or ["- none"]
            out.append("")
    out.append(END)
    return "\n".join(out)


def replace_section(body: str, section: str) -> str:
    """Put section between the markers of body, or append it when the markers are missing."""
    a, b = body.find(START), body.find(END)
    if a != -1 and b > a:
        return body[:a] + section + body[b + len(END) :]
    return (body.rstrip() + "\n\n" if body.strip() else "") + section + "\n"


def section_of(body: str) -> str:
    a, b = body.find(START), body.find(END)
    return body[a : b + len(END)] if a != -1 and b > a else ""


def sanitise(core: Path, body: str, sh: Sh) -> str:
    """ "" when the body passes both gates, otherwise the reason it must be held."""
    with tempfile.TemporaryDirectory(dir=str(core.parent)) as d:
        f = Path(d) / "report.md"
        f.write_text(body, encoding="utf8")
        for script in ("check-sanitised.py", "check-consumer-neutral.py"):
            check = core / "checks" / script
            if not check.is_file():
                return f"{script} missing in the core clone, report held"
            rc, out = sh([sys.executable, str(check), "--file", str(f)], cwd=core)
            if rc != 0:
                hits = [ln for ln in out.splitlines() if ln and not ln.startswith("check-")]
                return f"{script} flagged the report ({len(hits)} hit(s)), held: {' | '.join(hits[:3])[:300]}"
    return ""


def report_target(report_repo: str, core_repo: str, sh: Sh) -> tuple[str, str]:
    """(repo, "") when the upward report may be filed in report_repo, else ("", reason).

    A report carries one account's design inventory and evidence, so it is filed only in a PRIVATE
    intake repository named in the machine config (report_repo), never in the core itself, which may
    be public. No intake configured, the intake equal to the core, an intake that is not private or
    whose visibility cannot be read: nothing is filed."""
    target = (report_repo or "").strip()
    if not target:
        return "", "no report_repo configured (a private intake repository); nothing filed"
    if core_repo and target.lower() == core_repo.strip().lower():
        return (
            "",
            f"report_repo {target} is the core repository; reports go to a private intake only",
        )
    rc, out = sh(["gh", "repo", "view", target, "--json", "visibility", "--jq", ".visibility"])
    if rc != 0:
        return "", f"cannot confirm {target} is private ({out.strip()[-120:]}); nothing filed"
    if out.strip().upper() != "PRIVATE":
        return (
            "",
            f"report_repo {target} is {out.strip() or 'not private'}; reports go to a private repository only",
        )
    return target, ""


def find_issue(core_repo: str, sh: Sh) -> dict | None:
    rc, out = sh(
        [
            "gh",
            "issue",
            "list",
            "-R",
            core_repo,
            "--label",
            LABEL,
            "--author",
            "@me",
            "--state",
            "open",
            "--json",
            "number,body,url",
            "-L",
            "5",
        ]
    )
    if rc != 0:
        raise RuntimeError(f"cannot list report issues: {out[-200:]}")
    issues = json.loads(out or "[]")
    return issues[0] if issues else None


def current_issue(core_repo: str, sh: Sh, run: dict | None) -> dict | None:
    """The account's open report issue: the one this run created, read by number, else the list."""
    if run and run.get("number"):
        rc, out = sh(
            [
                "gh",
                "issue",
                "view",
                str(run["number"]),
                "-R",
                core_repo,
                "--json",
                "number,body,url",
            ]
        )
        if rc == 0:
            try:
                return json.loads(out)
            except ValueError:
                pass
    return find_issue(core_repo, sh)


def create_issue(core_repo: str, body: str, sh: Sh, run: dict | None) -> tuple[int, str]:
    """Create the report issue at most once per run and record its number in run."""
    if run is not None and run.get("created"):
        return (
            1,
            "the report issue was created earlier in this run but is not readable yet; next run",
        )
    rc, out = sh(
        [
            "gh",
            "issue",
            "create",
            "-R",
            core_repo,
            "--label",
            LABEL,
            "--title",
            "Consumer report: candidates for the core",
            "--body",
            body,
        ]
    )
    if rc == 0 and run is not None:
        run["created"] = True
        m = re.search(r"/issues/(\d+)", out)
        if m:
            run["number"] = int(m.group(1))
    return rc, out


def candidates(
    clone: Path, overlay: str, repo: str, sh: Sh, state_dir: Path, kit_src: str | None = None
) -> tuple:
    """(duplicates, flags, new, parts, seen_file) for one repo."""
    parts, kit = local_parts(clone, overlay), kit_parts(clone, overlay, kit_src)
    duplicates = [f"`{n}` ({f}) {rel}" for n, f in parts.items() if (rel := relation(n, kit))]
    flags = lint_flags(clone, overlay, sh)
    seen_file = state_dir / ("report__" + re.sub(r"[^A-Za-z0-9_.-]", "__", repo) + ".json")
    try:
        seen = set(json.loads(seen_file.read_text(encoding="utf8")).get("parts", []))
    except (OSError, ValueError):
        seen = None
    new = [] if seen is None else [f"`{n}` ({f})" for n, f in parts.items() if n not in seen]
    return duplicates, flags, new, parts, seen_file


def update(
    core: Path,
    core_repo: str,
    consumers: list[dict],
    sh: Sh,
    state_dir: Path,
    check: bool = False,
    run: dict | None = None,
) -> tuple[list[str], list[str]]:
    """Refresh the candidates section for every registered UI repo with a clone, in one pass and at
    most one issue edit. consumers: [{repo, path, overlay?}]. Returns (info lines, problem lines)."""
    groups: dict = {}
    remember: list = []
    problems: list = []
    any_new = False
    for c in consumers:
        try:
            dup, flags, new, parts, seen_file = candidates(
                Path(c["path"]).expanduser(),
                c.get("overlay", "standards-overlay"),
                c["repo"],
                sh,
                state_dir,
                c.get("kit_src"),
            )
        except Exception as exc:  # one broken repo must not hide the others
            problems.append(f"report {repo_label(c.get('repo', '?'))}: {exc}")
            continue
        groups[repo_label(c["repo"])] = (dup, flags, new)
        remember.append((seen_file, parts))
        any_new = any_new or bool(new)
    if not groups:
        return [], problems
    section = render_section(groups)
    issue = current_issue(core_repo, sh, run)
    current = section_of(issue["body"]) if issue else ""
    # "New additions" differ every run by design; compare the rest, so a quiet night stays quiet.
    if issue and _stable(current) == _stable(section) and not any_new:
        for f, parts in remember:
            _remember(f, parts, check)
        return [], problems
    body = replace_section(
        issue["body"] if issue else "Upward report from this account.\n", section
    )
    held = sanitise(core, body, sh)
    if held:
        return [], problems + [f"report candidates: {held}"]
    if check:
        return [
            "report candidates: section changed; would update the consumer-report issue"
        ], problems
    if issue:
        rc, out = sh(["gh", "issue", "edit", str(issue["number"]), "-R", core_repo, "--body", body])
        verb = "updated"
    else:
        rc, out = create_issue(core_repo, body, sh, run)
        verb = "opened"
    if rc != 0:
        return [], problems + [f"report candidates: could not update the issue: {out[-200:]}"]
    for f, parts in remember:
        _remember(f, parts, check)
    return [f"report candidates: {verb} the consumer-report issue"], problems


def _stable(section: str) -> str:
    """The section without its 'new additions' blocks, so only real changes trigger an edit."""
    return re.sub(
        r"#### New local additions since the last run\n.*?(?=\n<!-- nightly:candidates:end|\n### |\n#### )",
        "",
        section,
        flags=re.S,
    )


def _remember(f: Path, parts: dict, check: bool) -> None:
    if check:
        return
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"parts": sorted(parts)}) + "\n", encoding="utf8")


# ---------------------------------------------------------------------------------------------------
# Changes since the last nightly (the second machine-owned section).
# Pure functions first (tested with fixtures in tests/test_nightly_changes.py), then the I/O around them.

CH_START = "<!-- nightly:changes:start -->"
CH_END = "<!-- nightly:changes:end -->"
LINT_RULES = {
    "UI007": "accent set outside the root",
    "UI009": "kit class restyled inline",
    "UI010": "local theme or token",
}
STATUS_KEYS = ("pass", "proved", "fail", "unverified")
DECL = re.compile(r"export\s+(?:default\s+)?(function|const|class)\s+([A-Z][A-Za-z0-9]+)")


def _balanced(text: str, i: int) -> str:
    """The parenthesised group that opens at text[i] == '(' (unbalanced input: up to 400 chars)."""
    depth = 0
    for j in range(i, min(len(text), i + 2000)):
        depth += {"(": 1, ")": -1}.get(text[j], 0)
        if depth == 0:
            return text[i : j + 1]
    return text[i : i + 400]


def signatures(text: str) -> dict[str, str]:
    """{exported capitalised name: normalised signature}. A function's or arrow's parameter list with
    its types; a class's heritage clause; a plain const has an empty signature. Whitespace is
    collapsed so formatting alone is never a change."""
    out: dict = {}
    for m in DECL.finditer(text):
        kind, name = m.group(1), m.group(2)
        rest = text[m.end() : m.end() + 400]
        sig = ""
        if kind == "class":
            sig = rest.split("{", 1)[0]
        else:
            stop = re.search(r"[(;\n]", rest) if kind == "const" else re.search(r"\(", rest)
            if stop and stop.group(0) == "(":
                sig = _balanced(text, m.end() + stop.start())
            elif kind == "const":
                head = rest.split("\n", 1)[0]
                sig = head.split("=", 1)[0] if "=" in head else ""
        out.setdefault(name, " ".join(sig.split()))
    return out


def diff_parts(old: dict[str, list], new: dict[str, list]) -> dict[str, list]:
    """old/new: {name: [file, signature]}. Returns sorted added, removed and changed name lists."""
    return {
        "added": sorted(set(new) - set(old)),
        "removed": sorted(set(old) - set(new)),
        "changed": sorted(n for n in set(old) & set(new) if old[n][1] != new[n][1]),
    }


def diff_counts(old: dict[str, int], new: dict[str, int]) -> dict[str, list]:
    """{key: [before, after]} for every key whose count moved."""
    return {
        k: [old.get(k, 0), new.get(k, 0)]
        for k in sorted(set(old) | set(new))
        if old.get(k, 0) != new.get(k, 0)
    }


def repo_label(repo: str) -> str:
    """A stable label that names no repo: the report must not carry a consumer's repo name."""
    return "repo-" + hashlib.sha256(repo.encode("utf8")).hexdigest()[:8]


def change_lines(old: dict | None, new: dict, kit: set[str]) -> list[str]:
    """Bullet lines for one repo, [] when nothing moved. old None: the first run, a baseline."""
    if old is None:
        return ["baseline recorded; changes are listed from the next nightly"]
    lines = []
    d = diff_parts(old.get("parts", {}), new["parts"])
    for verb in ("added", "removed", "changed"):
        for n in d[verb]:
            src = (new["parts"].get(n) or old["parts"].get(n))[0]
            what = "signature changed" if verb == "changed" else verb
            lines.append(f"local part `{n}` ({src}) {what}")
    for n in d["added"]:
        rel = relation(n, kit)
        if rel:
            lines.append(f"new local part `{n}` matches a kit role: {rel}")
    for k, (a, b) in diff_counts(old.get("flags", {}), new["flags"]).items():
        lines.append(f"lint {k} ({LINT_RULES.get(k, k)}): {a} -> {b}")
    for k, (a, b) in diff_counts(old.get("status", {}), new["status"]).items():
        lines.append(f"core-status {k}: {a} -> {b}")
    if old.get("release") != new.get("release") and new.get("release"):
        lines.append(f"vendored copy release: {old.get('release') or 'none'} -> {new['release']}")
    if old.get("ui") != new.get("ui") and new.get("ui"):
        lines.append(f"core-status ui verdict: {old.get('ui') or 'none'} -> {new['ui']}")
    return lines


def render_changes(blocks: dict[str, list[str]]) -> str:
    """The changes section, markers included. blocks: {label: lines}. Stable for the same input."""
    out = [
        CH_START,
        "",
        "Changes since the previous nightly, per registered UI repo, kept current by the "
        "nightly. Each repo keeps its latest change set until a newer one replaces it.",
        "",
    ]
    for label in sorted(blocks):
        out += [f"### {label}", ""]
        out += [f"- {ln}" for ln in blocks[label]] or ["- no change recorded"]
        out.append("")
    out.append(CH_END)
    return "\n".join(out)


def replace_marked(body: str, section: str, start: str, end: str) -> str:
    """Put section between start and end in body; append it when the markers are missing."""
    a, b = body.find(start), body.find(end)
    if a != -1 and b > a:
        return body[:a] + section + body[b + len(end) :]
    return (body.rstrip() + "\n\n" if body.strip() else "") + section + "\n"


def marked(body: str, start: str, end: str) -> str:
    a, b = body.find(start), body.find(end)
    return body[a : b + len(end)] if a != -1 and b > a else ""


def snapshot(clone: Path, overlay: str, sh: Sh, ci: bool = False) -> dict:
    """What the diff compares: local parts with signatures, lint counts, core-status counts.
    ci: run core-status with --ci, so CI rules carry the repo's real CI results, and also return the
    rules, the problems and whether the CI results were read (keys rules, problems, ci_read)."""
    base = clone / overlay if overlay else clone
    parts: dict = {}
    for name, rel in local_parts(clone, overlay).items():
        f = base / rel
        try:
            sig = signatures(f.read_text(encoding="utf8", errors="replace")).get(name, "")
        except OSError:
            sig = ""
        parts[name] = [rel, sig]
    flags: dict = {}
    lint = base / "lint-core" / "ui_lint.py"
    if lint.is_file():
        rc, out = sh([sys.executable, str(lint), "--json"], cwd=base)
        try:
            for f in json.loads(out).get("findings", []):
                if f.get("rule") in LINT_RULES:
                    flags[f["rule"]] = flags.get(f["rule"], 0) + 1
        except ValueError:
            pass
    status: dict = {}
    ui = ""
    extra: dict = {}
    for script in (clone / "scripts" / "core-status.py", base / "scripts" / "core-status.py"):
        if script.is_file():
            data = None
            for args in (["--json", "--ci"], ["--json"]) if ci else (["--json"],):
                rc, out = sh([sys.executable, str(script), *args], cwd=clone)
                try:
                    data = json.loads(out)
                    extra["ci_read"] = "--ci" in args
                    break
                except ValueError:
                    data = None
            try:
                status = {k: int(data.get("summary", {}).get(k, 0)) for k in STATUS_KEYS}
                ui = str((data.get("ui_adoption") or {}).get("status", ""))
                extra["rules"] = list(data.get("rules") or [])
                extra["problems"] = [str(p) for p in data.get("problems") or []]
            except (AttributeError, TypeError):
                pass
            break
    snap = {"parts": parts, "flags": flags, "status": status, "ui": ui}
    if ci:
        snap.update({"rules": [], "problems": [], "ci_read": False, **extra})
    return snap


def update_changes(
    core: Path,
    core_repo: str,
    consumers: list[dict],
    sh: Sh,
    state_dir: Path,
    check: bool = False,
    run: dict | None = None,
) -> tuple[list[str], list[str]]:
    """Refresh the changes section for every registered UI repo with a clone, in one issue edit."""
    blocks: dict = {}
    pending: list = []
    for c in consumers:
        clone, overlay = Path(c["path"]).expanduser(), c.get("overlay", "standards-overlay")
        label = repo_label(c["repo"])
        f = state_dir / f"changes__{label}.json"
        try:
            old = json.loads(f.read_text(encoding="utf8"))
        except (OSError, ValueError):
            old = None
        new = snapshot(clone, overlay, sh)
        if c.get("release"):
            new["release"] = c[
                "release"
            ]  # a vendored repo: the release its copy carries (#117 G-031)
        lines = change_lines(old, new, kit_parts(clone, overlay, c.get("kit_src")))
        new["last"] = lines if lines else (old or {}).get("last", [])
        blocks[label] = new["last"]
        pending.append((f, new))
    if not blocks:
        return [], []
    section = render_changes(blocks)
    issue = current_issue(core_repo, sh, run)
    if issue and marked(issue["body"], CH_START, CH_END) == section:
        _save(pending, check)
        return [], []
    body = replace_marked(
        issue["body"] if issue else "Upward report from this account.\n", section, CH_START, CH_END
    )
    held = sanitise(core, body, sh)
    if held:
        return [], [f"report changes: {held}"]
    if check:
        return ["report changes: section changed; would update the consumer-report issue"], []
    if issue:
        rc, out = sh(["gh", "issue", "edit", str(issue["number"]), "-R", core_repo, "--body", body])
    else:
        rc, out = create_issue(core_repo, body, sh, run)
    if rc != 0:
        return [], [f"report changes: could not update the issue: {out[-200:]}"]
    _save(pending, check)
    return ["report changes: updated the consumer-report issue"], []


def _save(pending: list, check: bool) -> None:
    if check:
        return
    for f, data in pending:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data, sort_keys=True) + "\n", encoding="utf8")


if __name__ == "__main__":
    sys.exit("hermes/report.py is called by hermes/nightly.py")
