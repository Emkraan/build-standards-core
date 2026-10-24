#!/usr/bin/env python3
"""Script lint: the mechanical checks behind the PowerShell and Python scripting rules.

Usage (from anywhere, paths resolve from the config file):
  python3 lint-core/script_lint.py                     lint the paths in standards-local/script-lint.json
                                                       (no config: prints one skip line, exit 0)
  python3 lint-core/script_lint.py --config FILE       use another config
  python3 lint-core/script_lint.py PATH [PATH ...]     lint these paths with default settings
  python3 lint-core/script_lint.py --json              machine-readable result (core-status, nightly tooling)
  python3 lint-core/script_lint.py --write-baseline    record today's counts as a ratchet baseline, each
                                                       rule tied to the active exception that names it
  python3 lint/script_lint.py --self-test              run the fixtures (core CI)

Exit codes: 0 clean or within the baseline, 1 violations, 2 configuration error.

Rules (each names the doc rule an exception must name):
  PS001  a non-ASCII character in a PowerShell file                    scripting-powershell.md 1.7
  PS002  header block fields missing, or a function name that is not   scripting-powershell.md 1.6
         an approved Verb-Noun
  PS003  an empty catch block (comments do not count as a statement)   scripting-powershell.md 1.4
  PY001  shell=True, os.system, os.popen or subprocess.getoutput       scripting-python.md 1.8
  PY002  a ruff config whose target-version is missing or not the      scripting-python.md 1.10
         interpreter floor

What stays with review or the overlay's own CI: edition compatibility (PSUseCompatibleSyntax),
specific catch types and silenced calls, parameter and variable naming, the subprocess helper,
atomic state writes, locks and environment overrides. Static text cannot prove those reliably.

Suppression is the same as the UI lint: `core-exception: EXC-NNN` on the line or the line above,
where EXC-NNN is an active row in standards-local/exceptions.md naming this finding's rule. The
ratchet baseline works the same way. Standard library only.
"""

from __future__ import annotations

import ast
import datetime
import fnmatch
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from ui_lint import EXC_RE, active_exceptions, counts  # noqa: E402

RULES = {
    "PS001": (
        "non-ASCII character",
        "scripting-powershell.md 1.7",
        "PowerShell scripts are plain ASCII. Windows PowerShell 5.1 reads a curly quote or dash as another character",
    ),
    "PS002": (
        "header or function name",
        "scripting-powershell.md 1.6",
        "every script starts with the section 5 header block and every function has an approved Verb-Noun name",
    ),
    "PS003": (
        "empty catch",
        "scripting-powershell.md 1.4",
        "a catch logs and rethrows or sets a failing exit code, it never swallows the error",
    ),
    "PY001": (
        "shell command line",
        "scripting-python.md 1.8",
        "call external commands with an argument list through one helper, never through a shell",
    ),
    "PY002": (
        "ruff target-version",
        "scripting-python.md 1.10",
        "the committed ruff config sets target-version to the interpreter floor",
    ),
}

DEFAULTS = {
    "paths": ["."],
    "exclude": [
        "**/node_modules/**",
        "**/.git/**",
        "**/.venv/**",
        "**/venv/**",
        "**/dist/**",
        "**/build/**",
        "**/__pycache__/**",
        "**/tokens-core/**",
        "**/lint-core/**",
        "**/kit-core/**",
        "**/standards-core/**",
    ],
    "python_floor": None,
    "baseline": None,
}
PS_EXTS = {".ps1", ".psm1", ".psd1"}
RUFF_FILES = {"pyproject.toml", "ruff.toml", ".ruff.toml"}

# Get-Verb on PowerShell 7 (the approved verbs). Embedded so the lint needs no pwsh.
APPROVED_VERBS = {
    v.lower()
    for v in [
        "Add",
        "Clear",
        "Close",
        "Copy",
        "Enter",
        "Exit",
        "Find",
        "Format",
        "Get",
        "Hide",
        "Join",
        "Lock",
        "Move",
        "New",
        "Open",
        "Optimize",
        "Pop",
        "Push",
        "Redo",
        "Remove",
        "Rename",
        "Reset",
        "Resize",
        "Search",
        "Select",
        "Set",
        "Show",
        "Skip",
        "Split",
        "Step",
        "Switch",
        "Undo",
        "Unlock",
        "Watch",
        "Connect",
        "Disconnect",
        "Read",
        "Receive",
        "Send",
        "Write",
        "Backup",
        "Checkpoint",
        "Compare",
        "Compress",
        "Convert",
        "ConvertFrom",
        "ConvertTo",
        "Dismount",
        "Edit",
        "Expand",
        "Export",
        "Group",
        "Import",
        "Initialize",
        "Limit",
        "Merge",
        "Mount",
        "Out",
        "Publish",
        "Restore",
        "Save",
        "Sync",
        "Unpublish",
        "Update",
        "Debug",
        "Measure",
        "Ping",
        "Repair",
        "Resolve",
        "Test",
        "Trace",
        "Approve",
        "Assert",
        "Build",
        "Complete",
        "Confirm",
        "Deny",
        "Deploy",
        "Disable",
        "Enable",
        "Install",
        "Invoke",
        "Register",
        "Request",
        "Restart",
        "Resume",
        "Start",
        "Stop",
        "Submit",
        "Suspend",
        "Uninstall",
        "Unregister",
        "Wait",
        "Block",
        "Grant",
        "Protect",
        "Revoke",
        "Unblock",
        "Unprotect",
        "Use",
    ]
}

# The section 5 header fields: (label, pattern searched inside the leading comment-based help block).
HEADER_FIELDS = (
    (".SYNOPSIS", re.compile(r"^\s*\.SYNOPSIS\s*$\s*^\s*\S", re.M | re.I)),
    (".DESCRIPTION", re.compile(r"^\s*\.DESCRIPTION\b", re.M | re.I)),
    ("Author", re.compile(r"^\s*Author\s*:\s*\S", re.M | re.I)),
    ("Created: YYYY-MM-DD", re.compile(r"^\s*Created\s*:\s*\d{4}-\d{2}-\d{2}\b", re.M | re.I)),
    ("Version", re.compile(r"^\s*Version\s*:\s*\S", re.M | re.I)),
    ("Exit codes", re.compile(r"^\s*Exit codes?\s*:\s*\S", re.M | re.I)),
)

# ------------------------------------------------------------------ PowerShell


def ps_blank(text):
    """Blank PowerShell comments and string contents (newlines kept) so line numbers stay true.

    Returns (code, comments): code has comments and string bodies blanked, comments is the text of
    every comment with code blanked, so a header block can be read from it.
    """
    code, comm = list(text), [c if c == "\n" else " " for c in text]
    i, n = 0, len(text)

    def blank(a, b, keep_comment=False):
        for k in range(a, b):
            if text[k] != "\n":
                if keep_comment:
                    comm[k] = text[k]
                code[k] = " "

    while i < n:
        c = text[i]
        if text.startswith("<#", i):
            j = text.find("#>", i + 2)
            j = n if j < 0 else j + 2
            blank(i, j, keep_comment=True)
            i = j
        elif c == "#":
            j = text.find("\n", i)
            j = n if j < 0 else j
            blank(i, j, keep_comment=True)
            i = j
        elif text.startswith('@"', i) or text.startswith("@'", i):
            q = text[i + 1]
            m = re.compile(r"^\s*" + q + "@", re.M).search(text, i + 2)
            j = n if not m else m.end()
            blank(i + 2, j - 2 if m else j)
            i = j
        elif c == "'":
            j = i + 1
            while j < n:
                if text[j] == "'" and j + 1 < n and text[j + 1] == "'":
                    j += 2
                    continue
                if text[j] == "'":
                    break
                j += 1
            blank(i + 1, j)
            i = j + 1
        elif c == '"':
            j = i + 1
            while j < n:
                if text[j] == "`":
                    j += 2
                    continue
                if text[j] == '"' and j + 1 < n and text[j + 1] == '"':
                    j += 2
                    continue
                if text[j] == '"':
                    break
                j += 1
            blank(i + 1, j)
            i = j + 1
        elif c == "`":
            i += 2
        else:
            i += 1
    return "".join(code), "".join(comm)


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def check_powershell(path, text, hit):
    for no, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip("\ufeff") if no == 1 else line
        bad = next((ch for ch in stripped if ord(ch) > 127), None)
        if bad is not None:
            hit("PS001", no, f"U+{ord(bad):04X}")
    code, comments = ps_blank(text)
    if path.suffix == ".ps1" and not path.name.lower().endswith(".tests.ps1"):
        body = text.lstrip("\ufeff")
        lead = re.match(r"(?:\s*#requires[^\n]*\n|\s*#![^\n]*\n)*\s*", body, re.I)
        start = lead.end() if lead else 0
        if not body.startswith("<#", start):
            hit(
                "PS002",
                1,
                "no header block: the script does not start with a <# ... #> help block (section 5)",
            )
        else:
            end = body.find("#>", start)
            block = body[start : end if end > 0 else len(body)]
            missing = [label for label, pat in HEADER_FIELDS if not pat.search(block)]
            if missing:
                hit(
                    "PS002",
                    line_of(text, text.find("<#")),
                    "header block lacks " + ", ".join(missing),
                )
    for m in re.finditer(
        r"(?im)^[ \t]*(?:function|filter)\s+(?:(?:script|global|local|private):)?([\w-]+)", code
    ):
        name = m.group(1)
        verb, dash, noun = name.partition("-")
        if not dash or not noun or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", noun):
            hit("PS002", line_of(code, m.start(1)), f"function {name} is not Verb-Noun")
        elif verb.lower() not in APPROVED_VERBS:
            hit(
                "PS002",
                line_of(code, m.start(1)),
                f"function {name} uses the unapproved verb {verb}",
            )
    for m in re.finditer(r"(?i)\bcatch\b(\s*\[[^\]\n]*\]\s*,?)*\s*\{\s*\}", code):
        hit("PS003", line_of(code, m.start()), "empty catch block")


# ------------------------------------------------------------------ Python


SHELL_FUNCS = {
    ("os", "system"),
    ("os", "popen"),
    ("subprocess", "getoutput"),
    ("subprocess", "getstatusoutput"),
}


def check_python(path, text, hit):
    try:
        tree = ast.parse(text, filename=str(path))
    except (SyntaxError, ValueError):
        tree = None
    if tree is None:
        # Unparseable on this interpreter (for example newer syntax): fall back to the literal.
        for no, line in enumerate(text.splitlines(), 1):
            code = line.split("#", 1)[0]
            if re.search(r"\bshell\s*=\s*True\b", code):
                hit("PY001", no, "shell=True (file did not parse, text match)")
        return
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value:
                hit("PY001", node.lineno, "shell=True")
        f = node.func
        if (
            isinstance(f, ast.Attribute)
            and isinstance(f.value, ast.Name)
            and (f.value.id, f.attr) in SHELL_FUNCS
        ):
            hit("PY001", node.lineno, f"{f.value.id}.{f.attr}() runs a shell command line")


def ruff_target(text, name):
    """(line, value or None, has_ruff_section) for a ruff config file. Minimal TOML reading."""
    section, found_section, head = "", name != "pyproject.toml", 1
    for no, line in enumerate(text.splitlines(), 1):
        s = line.split("#", 1)[0].strip()
        m = re.fullmatch(r"\[+\s*([^\]]+?)\s*\]+", s)
        if m:
            section = m.group(1)
            if (section == "tool.ruff" or section.startswith("tool.ruff.")) and not found_section:
                found_section, head = True, no
            continue
        in_scope = section == "tool.ruff" if name == "pyproject.toml" else section == ""
        m = re.fullmatch(r'target-version\s*=\s*["\']([^"\']*)["\']', s)
        if m and in_scope:
            return no, m.group(1), True
    return head, None, found_section


def declared_floor(cfg):
    if cfg.get("python_floor"):
        return str(cfg["python_floor"])
    f = cfg["_overlay"] / "standards-local" / "parameters.md"
    if f.is_file():
        for line in f.read_text(encoding="utf8").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 2 and cells[0].lower().startswith("python interpreter floor"):
                m = re.search(r"\b3\.(\d+)\b", cells[1])
                if m:
                    return f"3.{m.group(1)}"
    return "3.9"


def check_ruff(path, text, hit, floor):
    no, value, has = ruff_target(text, path.name)
    if not has:
        return
    want = "py" + floor.replace(".", "")
    if value is None:
        hit("PY002", no, f'ruff config without target-version (expected "{want}")')
    elif value != want:
        hit("PY002", no, f'target-version "{value}", the floor is "{want}"')


# ------------------------------------------------------------------ driver


def load_config(argv):
    cfg = dict(DEFAULTS)
    root = pathlib.Path.cwd()
    cpath = None
    if "--config" in argv:
        cpath = pathlib.Path(argv[argv.index("--config") + 1]).resolve()
    else:
        cand = HERE.parent / "standards-local" / "script-lint.json"
        if cand.is_file():
            cpath = cand
    overlay = HERE.parent
    if cpath:
        try:
            user = json.loads(cpath.read_text(encoding="utf8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"script-lint: cannot read {cpath}: {e}")
            sys.exit(2)
        overlay = cpath.parent.parent if cpath.parent.name == "standards-local" else cpath.parent
        root = (overlay / user.get("root", ".")).resolve()
        for k in ("paths", "baseline", "python_floor"):
            if k in user:
                cfg[k] = user[k]
        cfg["exclude"] = DEFAULTS["exclude"] + user.get("exclude", [])
    cfg["_overlay"] = overlay
    cfg["_configured"] = cpath is not None
    positional = [
        a
        for i, a in enumerate(argv)
        if not a.startswith("--") and (i == 0 or argv[i - 1] != "--config")
    ]
    if positional:
        cfg["paths"] = positional
        cfg["_configured"] = True
        root = pathlib.Path.cwd()
    return cfg, root


def collect(cfg, root):
    files = []
    for p in cfg["paths"]:
        base = (root / p).resolve()
        cands = [base] if base.is_file() else sorted(base.rglob("*")) if base.is_dir() else []
        for f in cands:
            if not f.is_file() or not (
                f.suffix in PS_EXTS or f.suffix == ".py" or f.name in RUFF_FILES
            ):
                continue
            try:
                rel = f.relative_to(root).as_posix()
            except ValueError:
                rel = f.as_posix()
            if any(
                fnmatch.fnmatch(rel, g) or fnmatch.fnmatch("/" + rel, g) for g in cfg["exclude"]
            ):
                continue
            if (f, rel) not in files:
                files.append((f, rel))
    return files


def run(cfg, root):
    root = root.resolve()
    active = active_exceptions(cfg["_overlay"])
    floor = declared_floor(cfg)
    findings = []
    files = collect(cfg, root)
    for f, rel in files:
        text = f.read_text(encoding="utf8", errors="replace")
        raw = text.splitlines()

        def hit(rule, line, detail, rel=rel, raw=raw):
            for ln in (line, line - 1):
                if 1 <= ln <= len(raw):
                    for eid in EXC_RE.findall(raw[ln - 1]):
                        if active.get(eid) == RULES[rule][1]:
                            return
            findings.append({"rule": rule, "file": rel, "line": line, "detail": detail})

        if f.suffix in PS_EXTS:
            check_powershell(f, text, hit)
        elif f.suffix == ".py":
            check_python(f, text, hit)
        else:
            check_ruff(f, text, hit, floor)
    return files, findings, active, floor


def self_test():
    import shutil
    import tempfile

    src = HERE / "script-fixtures"
    expected = json.loads((src / "expected.json").read_text(encoding="utf8"))
    fx = pathlib.Path(tempfile.mkdtemp()) / "script-fixtures"
    shutil.copytree(src, fx)
    # Written at run time so the repo itself stays plain ASCII: a curly quote and an em dash.
    (fx / "Typo.ps1").write_text(
        "<#\n.SYNOPSIS\n    Fixture.\n.DESCRIPTION\n    Fixture.\n.NOTES\n    Author : Owner\n    Created: 2026-01-01\n"
        "    Version: 1.0.0\n    Exit codes: 0 success\n#>\nWrite-Output \u2018x\u2019\nWrite-Output 'a\u2014b'\n",
        encoding="utf8",
    )
    cfg = dict(DEFAULTS)
    cfg["_overlay"] = fx
    cfg["python_floor"] = "3.9"
    files, findings, _, _ = run(cfg, fx)
    got = counts(findings)
    bad = [
        f"{k}: expected {expected.get(k, 0)}, got {got.get(k, 0)}"
        for k in sorted(set(expected) | set(got))
        if expected.get(k, 0) != got.get(k, 0)
    ]
    for b in bad:
        print(f"::error::self-test {b}")
    for f in findings:
        print(f"  {f['rule']} {f['file']}:{f['line']} {f['detail']}")
    bad += _self_test_baseline()
    print(
        f"script-lint self-test: {len(files)} fixture file(s), {len(findings)} finding(s), {len(bad)} mismatch(es)"
    )
    return 1 if bad else 0


def _self_test_baseline():
    """The ratchet and the skip: write, hold, catch a new finding, refuse a rule with no exception, drop on expiry."""
    import contextlib
    import io
    import tempfile

    root = pathlib.Path(tempfile.mkdtemp())
    (root / "standards-local").mkdir()
    (root / "scripts").mkdir()
    cfg_file = root / "standards-local" / "script-lint.json"
    cfg_file.write_text(json.dumps({"paths": ["scripts"], "baseline": "standards-local/base.json"}))
    table = root / "standards-local" / "exceptions.md"
    head = "| ID | Rule | Scope | Deviation | Reason | Owner | Approved | Review by |\n|---|---|---|---|---|---|---|---|\n"
    row = "| EXC-001 | scripting-python.md 1.8 | scripts | Migration | Adopting | Owner | 2026-01-01 | {} |\n"
    table.write_text(head + row.format("2099-01-01"))
    py = root / "scripts" / "a.py"
    py.write_text('import subprocess\nsubprocess.run("ls", shell=True)\n')

    def run_quiet(*extra):
        with contextlib.redirect_stdout(io.StringIO()):
            return main(["--config", str(cfg_file), *extra])

    steps = [("write", run_quiet("--write-baseline"), 0), ("hold", run_quiet(), 0)]
    py.write_text(py.read_text() + 'subprocess.run("pwd", shell=True)\n')
    steps.append(("new finding", run_quiet(), 1))
    py.write_text('import subprocess\nsubprocess.run("ls", shell=True)\n')
    (root / "scripts" / "ruff.toml").write_text('target-version = "py312"\n')
    steps.append(("rule without exception", run_quiet("--write-baseline"), 2))
    (root / "scripts" / "ruff.toml").unlink()
    table.write_text(head + row.format("2020-01-01"))
    steps.append(("expired", run_quiet(), 1))
    probe = {"_configured": False}
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = report_unconfigured(probe, [])
    steps.append(("no config skips", code if "skipped" in out.getvalue() else 1, 0))
    return [
        f'baseline step "{name}": exit {got}, expected {want}'
        for name, got, want in steps
        if got != want
    ]


def report_unconfigured(cfg, argv):
    """No config and no paths: the overlay has not opted in, so say so and pass."""
    if "--json" in argv:
        print(
            json.dumps(
                {
                    "configured": False,
                    "files": 0,
                    "findings": [],
                    "over_baseline": {},
                    "fixed_since_baseline": 0,
                    "rules": {k: v[0] for k, v in RULES.items()},
                    "refs": {k: v[1] for k, v in RULES.items()},
                },
                indent=2,
            )
        )
    else:
        print("script-lint: no standards-local/script-lint.json, skipped (add one to lint scripts)")
    return 0


def main(argv):
    if "--self-test" in argv:
        return self_test()
    cfg, root = load_config(argv)
    if not cfg["_configured"]:
        return report_unconfigured(cfg, argv)
    files, findings, active, floor = run(cfg, root)
    now = counts(findings)
    base_file = (cfg["_overlay"] / cfg["baseline"]) if cfg.get("baseline") else None

    if "--write-baseline" in argv:
        if not base_file:
            print('script-lint: set "baseline" in the config to the file to write')
            return 2
        per_rule, missing = {}, []
        for f in findings:
            tally = per_rule.setdefault(f["rule"], {})
            tally[f["file"]] = tally.get(f["file"], 0) + 1
        out = {}
        for rid in sorted(per_rule):
            ref = RULES[rid][1]
            owners = sorted(e for e, r in active.items() if r == ref)
            if not owners:
                missing.append(f"{rid} ({ref})")
                continue
            out[rid] = {"exception": owners[0], "counts": dict(sorted(per_rule[rid].items()))}
        if missing:
            print(
                "script-lint: a baseline needs an active exception row naming each rule with findings. Missing: "
                + ", ".join(missing)
            )
            return 2
        base_file.write_text(
            json.dumps(
                {
                    "format": "script-lint-baseline/1",
                    "written": datetime.date.today().isoformat(),
                    "total": len(findings),
                    "rules": out,
                },
                indent=2,
            )
            + "\n"
        )
        print(
            f"script-lint: baseline of {len(findings)} finding(s) across {len(out)} rule(s) written to {base_file}"
        )
        return 0

    allowed, owners, ignored = {}, set(), []
    if base_file and base_file.is_file():
        b = json.loads(base_file.read_text(encoding="utf8"))
        for rid, entry in b.get("rules", {}).items():
            if rid in RULES and active.get(entry.get("exception")) == RULES[rid][1]:
                owners.add(entry["exception"])
                for fname, n in entry.get("counts", {}).items():
                    allowed[f"{fname}::{rid}"] = n
            else:
                ignored.append(
                    f"{rid} ({entry.get('exception')} missing, expired or naming another rule)"
                )
    note = f" (baseline under {', '.join(sorted(owners))})" if owners else ""
    if ignored:
        note += ". Baseline ignored for " + ", ".join(ignored)
    over = {k: n for k, n in now.items() if n > allowed.get(k, 0)}
    new_count = sum(n - allowed.get(k, 0) for k, n in over.items())
    shrunk = sum(max(0, allowed[k] - now.get(k, 0)) for k in allowed)
    failing = [f for f in findings if f"{f['file']}::{f['rule']}" in over]

    if "--json" in argv:
        print(
            json.dumps(
                {
                    "configured": True,
                    "files": len(files),
                    "python_floor": floor,
                    "findings": findings,
                    "over_baseline": over,
                    "fixed_since_baseline": shrunk,
                    "rules": {k: v[0] for k, v in RULES.items()},
                    "refs": {k: v[1] for k, v in RULES.items()},
                },
                indent=2,
            )
        )
    else:
        for f in failing:
            title, ref, why = RULES[f["rule"]]
            print(
                f"::error file={f['file']},line={f['line']}::{f['rule']} {title} ({ref}): {f['detail']}. Rule: {why}."
            )
        by_rule = {}
        for f in findings:
            by_rule[f["rule"]] = by_rule.get(f["rule"], 0) + 1
        summary = ", ".join(f"{k} {v}" for k, v in sorted(by_rule.items())) or "none"
        print(
            f"script-lint: {len(files)} file(s), {len(findings)} finding(s) [{summary}], "
            f"{new_count} new above the baseline{note}"
        )
        if shrunk:
            print(
                f"script-lint: {shrunk} finding(s) fixed since the baseline. Lock it in: --write-baseline"
            )
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
