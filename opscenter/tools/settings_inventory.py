#!/usr/bin/env python3
"""settings_inventory.py - list every setting the ops center code reads from the environment.

Reads the python source under server, engine, lanes, tools, gates, people and tracker with the syntax tree (no regular
expression, nothing is imported or run) and finds each environment variable the code reads: os.environ.get, os.environ[...],
os.environ.setdefault, os.getenv, and the helpers that take a variable name (the provider loader, the switch reader and the
binary finder). For each variable it records the default as written in the code and the files that read it.

The table is the one place a consumer looks to set every location once. The "Under the state dir" column is read from the
default expression: "yes" when the default is built from the state dir or the dashboard folder, "no, a path" when it is built
from a home, root, agent home or repos folder or a literal path (so a consumer who moves the state dir must set it too),
and "-" when the default is not a path.

Usage:
  python3 settings_inventory.py            print the table to stdout
  python3 settings_inventory.py --write    rewrite opscenter/SETTINGS.md
  python3 settings_inventory.py --check    exit 1 when opscenter/SETTINGS.md is not what the code says (the CI guard)

Exit codes: 0 ok, 1 the file is stale (--check), 2 a source file could not be parsed.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

OPSCENTER = Path(__file__).resolve().parent.parent
AREAS = ("server", "engine", "lanes", "tools", "gates", "people", "tracker")
OUT_FILE = OPSCENTER / "SETTINGS.md"
NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{3,}$")
# helpers whose first argument is a variable name (the provider loader and the switch reader), and the binary finder whose
# keyword or second argument names the override variable
NAME_FIRST = {"load", "enabled"}
STATE_HINT = re.compile(
    r"state_dir\(|dashboard_dir\(|\bSTATE\b|\bDASH\b|\bDASHBOARD\b|\bSTATE_DIR\b"
)
PATH_HINT = re.compile(
    r"Path\(|\.home\(|expanduser|\bROOT\b|root\(\)|agent_home|repos_dir|\bHOME\b|AGENT_HOME|\"/|'/|\"~|'~"
)


def _source_files() -> list[Path]:
    files = []
    for area in AREAS:
        for path in sorted((OPSCENTER / area).rglob("*.py")):
            parts = set(path.relative_to(OPSCENTER).parts)
            if path.name.endswith("_test.py") or parts & {"tests", "fixtures", "__pycache__"}:
                continue
            files.append(path)
    return files


def _const(node) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and NAME_RE.match(node.value):
        return node.value
    return None


def _is_environ(node) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "environ"
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
    )


def _default_text(node) -> str:
    try:
        return ast.unparse(node)
    except Exception:  # noqa: BLE001 - an expression the unparser cannot print is shown as unknown
        return "?"


def _or_default(call, parents) -> str | None:
    """The right side of `os.environ.get("X") or default`, when the read is the first operand of an or."""
    parent = parents.get(call)
    if (
        isinstance(parent, ast.BoolOp)
        and isinstance(parent.op, ast.Or)
        and parent.values[0] is call
    ):
        return " or ".join(_default_text(v) for v in parent.values[1:])
    return None


def reads_in_source(source: str) -> list[tuple[str, str]]:
    """Every (variable, default text) the source reads. The default is '(none)' when the read has none."""
    tree = ast.parse(source)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    found = []

    def add(name, call):
        has_default = len(call.args) > 1
        default = (
            _default_text(call.args[1]) if has_default else (_or_default(call, parents) or "(none)")
        )
        found.append((name, default))

    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and _is_environ(node.value):
            name = _const(node.slice)
            if name:
                found.append((name, "(none)"))
        elif isinstance(node, ast.Call):
            func = node.func
            attr = func.attr if isinstance(func, ast.Attribute) else None
            plain = func.id if isinstance(func, ast.Name) else None
            if (
                isinstance(func, ast.Attribute)
                and _is_environ(func.value)
                and attr in ("get", "setdefault")
            ):
                name = _const(node.args[0]) if node.args else None
                if name:
                    add(name, node)
            elif (attr == "getenv" or plain == "getenv") and node.args:
                name = _const(node.args[0])
                if name:
                    add(name, node)
            elif (attr or plain) in NAME_FIRST and node.args:
                name = _const(node.args[0])
                if name:
                    found.append((name, "(none)"))
            elif (attr or plain) == "which":
                over = [kw.value for kw in node.keywords if kw.arg == "override_env"]
                if len(node.args) > 1:
                    over.append(node.args[1])
                for value in over:
                    name = _const(value)
                    if name:
                        found.append((name, "(none)"))
    return found


def collect() -> dict[str, dict]:
    table: dict[str, dict] = {}
    for path in _source_files():
        rel = path.relative_to(OPSCENTER).as_posix()
        try:
            reads = reads_in_source(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError) as exc:
            print(f"settings_inventory: cannot parse {rel}: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
        for name, default in reads:
            row = table.setdefault(name, {"defaults": [], "files": []})
            if default not in row["defaults"]:
                row["defaults"].append(default)
            if rel not in row["files"]:
                row["files"].append(rel)
    return table


def under_state(defaults: list[str], name: str = "") -> str:
    """yes, no (a path), or - (not a path), from the default expressions as written. The state dir variable is the state dir."""
    if name == "OPSCENTER_STATE_DIR":
        return "is the state dir"
    shown = [d for d in defaults if d != "(none)"]
    if not shown:
        return "-"
    if all(STATE_HINT.search(d) for d in shown):
        return "yes"
    if any(PATH_HINT.search(d) for d in shown):
        return "no, a path"
    return "-"


def _cell(text: str) -> str:
    text = text.encode("ascii", "replace").decode("ascii").replace("|", "\\|").replace("\n", " ")
    return text if len(text) <= 90 else text[:87] + "..."


def render(table: dict[str, dict] | None = None) -> str:
    table = table if table is not None else collect()
    lines = [
        "# Ops center settings",
        "",
        "Generated by `opscenter/tools/settings_inventory.py` from the source, do not edit by hand. `python3 opscenter/tools/settings_inventory.py --write` rewrites it and",
        "`--check` (run by the unit tests) fails when it no longer matches the code, so a new setting cannot ship unlisted.",
        "",
        f"{len(table)} settings. Default is the expression as written in the code. A consumer that moves the state dir sets every row marked",
        '"no, a path" that it uses (design 12.104).',
        "",
        "| Variable | Default as written | Under the state dir | Read in |",
        "|---|---|---|---|",
    ]
    for name in sorted(table):
        row = table[name]
        defaults = " / ".join(f"`{_cell(d)}`" for d in row["defaults"])
        files = ", ".join(f"`{f}`" for f in row["files"][:3]) + (
            " and more" if len(row["files"]) > 3 else ""
        )
        lines.append(f"| `{name}` | {defaults} | {under_state(row['defaults'], name)} | {files} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--write", action="store_true", help="rewrite opscenter/SETTINGS.md")
    group.add_argument(
        "--check", action="store_true", help="exit 1 when opscenter/SETTINGS.md is stale"
    )
    args = parser.parse_args(argv)
    text = render()
    if args.write:
        OUT_FILE.write_text(text, encoding="utf-8")
        print(f"settings_inventory: wrote {OUT_FILE.name}")
        return 0
    if args.check:
        have = OUT_FILE.read_text(encoding="utf-8") if OUT_FILE.exists() else ""
        if have != text:
            print(
                "settings_inventory: SETTINGS.md is stale, run: python3 opscenter/tools/settings_inventory.py --write"
            )
            return 1
        print("settings_inventory: SETTINGS.md is current")
        return 0
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
