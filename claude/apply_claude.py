#!/usr/bin/env python3
"""Bring a consumer's Claude Code setup in line with claude/tools.json.

    python3 claude/apply_claude.py [--check] [--quiet]

Idempotent and silent when nothing needs doing. For every required entry it checks and, unless
--check is given, fixes:
  hook         the user settings.json carries the entry's PreToolUse command (rtk init -g --auto-patch)
  plugin       claude plugin marketplace add + install, then enabled
  mcp          user-scope npm install, the vendor installer, config keys, a ~/.local/bin link that the
               installer's hooks expect
  rule         mcp-secrets: flags a literal token in ~/.claude.json (reported, never rewritten)
  memory-file  caveman-compress runs on the named file when it is new or changed since the last run
Never removes anything. Report lines: CHANGED, RESTART (new session needed), MISSING (with hint).
Python 3.9, stdlib only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "claude" / "tools.json"
HOME = Path.home()
STATE = (
    Path(os.environ.get("XDG_STATE_HOME") or HOME / ".local" / "state")
    / "build-standards-core"
    / "compressed.json"
)
SKILL = Path(
    os.environ.get("CAVEMAN_COMPRESS_DIR") or HOME / ".hermes" / "skills" / "caveman-compress"
)
TIMEOUT = 900


def run(cmd, **kw):
    env = dict(os.environ, OBJC_DISABLE_INITIALIZE_FORK_SAFETY="YES")
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT, env=env, **kw)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


class Apply:
    def __init__(self, check: bool):
        self.check, self.changed, self.missing, self.restart = check, [], [], False

    def settings_text(self) -> str:
        p = HOME / ".claude" / "settings.json"
        return p.read_text(encoding="utf8") if p.exists() else ""

    def fail(self, t, why):
        self.missing.append(f"{t['id']}: {why}. {t['install_hint']}")

    def hook(self, t):
        if not shutil.which(t["binary"]):
            return self.fail(t, f"{t['binary']} binary not installed")
        if t["verify_settings"] in self.settings_text():
            return
        if self.check:
            return self.fail(t, "hook absent from user settings")
        rc, out = run(t["install"])
        if rc == 0 and t["verify_settings"] in self.settings_text():
            self.changed.append(f"{t['id']}: hook installed")
            self.restart = True
        else:
            self.fail(t, f"install failed: {out[-200:]}")

    def plugin(self, t):
        if not shutil.which("claude"):
            return self.fail(t, "claude CLI not installed")
        rc, out = run(["claude", "plugin", "list"])
        name = t["plugin"].split("@")[0]
        if rc == 0 and name in out and "disabled" not in out.split(name, 1)[1][:200].lower():
            return
        if self.check:
            return self.fail(t, "plugin missing or disabled")
        run(["claude", "plugin", "marketplace", "add", t["marketplace"]])
        rc, out = run(["claude", "plugin", "install", t["plugin"]])
        run(["claude", "plugin", "enable", t["plugin"]])
        rc2, out2 = run(["claude", "plugin", "list"])
        if rc2 == 0 and name in out2:
            self.changed.append(f"{t['id']}: plugin installed")
            self.restart = True
        else:
            self.fail(t, f"install failed: {out[-200:]}")

    def mcp(self, t):
        cj = HOME / ".claude.json"
        have = cj.exists() and t["server"] in json.loads(cj.read_text(encoding="utf8")).get(
            "mcpServers", {}
        )
        link = HOME / ".local" / "bin" / t["server"]
        if have and (link.exists() or link.is_symlink()):
            return
        if self.check:
            return self.fail(t, "not registered at user scope")
        if not shutil.which(t["server"]):
            if not shutil.which("npm"):
                return self.fail(t, "npm not installed")
            rc, out = run(["npm", "install", "-g", t["npm"]])
            if rc != 0:
                return self.fail(t, f"npm install failed: {out[-200:]}")
        run(t["install"])
        for k, v in t.get("config", []):
            run([t["server"], "config", "set", k, v])
        exe = shutil.which(t["server"])
        if exe and not (link.exists() or link.is_symlink()):
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(exe)  # the vendor installer writes hooks that call this path
        have = cj.exists() and t["server"] in json.loads(cj.read_text(encoding="utf8")).get(
            "mcpServers", {}
        )
        if have:
            self.changed.append(f"{t['id']}: installed at user scope")
            self.restart = True
        else:
            self.fail(t, "installer did not register the server")

    def memory(self, t):
        state = json.loads(STATE.read_text()) if STATE.exists() else {}
        due = [
            p
            for p in (Path(f).expanduser() for f in t["files"])
            if p.exists() and p.stat().st_size >= t["min_bytes"] and state.get(str(p)) != sha(p)
        ]
        if not due:
            return  # nothing new, changed or large enough, so the tools are not needed tonight
        py = next(
            (
                p
                for p in (
                    shutil.which(x)
                    for x in ("python3.14", "python3.13", "python3.12", "python3.11", "python3.10")
                )
                if p
            ),
            None,
        )
        if not (SKILL / "scripts").is_dir() or not py or not shutil.which("claude"):
            names = ", ".join(p.name for p in due)
            return self.fail(
                t,
                f"{names} is due for compression but the caveman-compress skill, python 3.10+ or claude CLI is missing",
            )
        for p in due:
            if self.check:
                self.missing.append(f"{t['id']}: {p} not compressed")
                continue
            rc, out = run([py, "-m", "scripts", str(p)], cwd=SKILL)
            if rc == 0 and "completed successfully" in out:
                state[str(p)] = sha(p)
                STATE.parent.mkdir(parents=True, exist_ok=True)
                STATE.write_text(json.dumps(state, indent=1))
                self.changed.append(f"{t['id']}: compressed {p.name}")
            else:
                self.missing.append(
                    f"{t['id']}: compress of {p} failed, file untouched: {out[-200:]}"
                )

    def rule(self, t):
        if t["id"] != "mcp-secrets":
            return
        cj = HOME / ".claude.json"
        if not cj.exists():
            return
        servers = json.loads(cj.read_text(encoding="utf8")).get("mcpServers", {})
        for name, c in servers.items():
            for k, v in (c.get("headers") or {}).items():
                if (
                    isinstance(v, str)
                    and "${" not in v
                    and any(w in k.lower() for w in ("auth", "key", "token"))
                ):
                    self.missing.append(
                        f"{t['id']}: server '{name}' header '{k}' holds a literal secret in ~/.claude.json. {t['install_hint']}"
                    )
            for k, v in (c.get("env") or {}).items():
                if (
                    isinstance(v, str)
                    and "${" not in v
                    and any(w in k.upper() for w in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
                ):
                    self.missing.append(
                        f"{t['id']}: server '{name}' env '{k}' holds a literal secret in ~/.claude.json. {t['install_hint']}"
                    )

    def run_all(self):
        for t in json.loads(REGISTRY.read_text(encoding="utf8"))["tools"]:
            if t.get("required") and t["decision"] != "reject":
                getattr(
                    self,
                    {
                        "hook": "hook",
                        "plugin": "plugin",
                        "mcp": "mcp",
                        "memory-file": "memory",
                        "rule": "rule",
                    }[t["kind"]],
                )(t)
        return self

    def lines(self):
        out = [f"CHANGED {c}" for c in self.changed]
        if self.restart:
            out.append(
                "RESTART open Claude Code sessions to load the hook, plugin or server changes above"
            )
        return out + [f"MISSING {m}" for m in self.missing]


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    s = Apply(a.check).run_all()
    lines = s.lines()
    if lines:
        print("\n".join(lines))
    elif not a.quiet:
        print("claude setup matches the core decisions")
    return 3 if s.missing else 0


if __name__ == "__main__":
    sys.exit(main())
