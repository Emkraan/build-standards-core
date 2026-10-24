#!/usr/bin/env python3
"""Bring a consumer's Hermes setup in line with the core decisions in hermes/tools.json.

    python3 hermes/apply_setup.py [--hermes-home DIR] [--check] [--no-binaries] [--safe-restart] [--quiet]

For every required tool it checks the consumer and, unless --check is given, installs what is
missing with the registry's own commands:
  binary   installed with the first package manager present (brew, then cargo), then verified
  plugin   the registry install command (for rtk: rtk init -g --agent hermes), then enabled
  skill    hermes skills install <source> --yes (Hermes scans it before install)
  setting  hermes config set <key> <value> when the current value differs
The safe restart job (hermes/safe-restart/) is installed only with --safe-restart: it adds a launchd
agent and a paused cron job, which a consumer must ask for. It never hand-edits config.yaml, never
removes anything and never restarts Hermes. A change to a
plugin or setting only loads after Hermes restarts, so the report says RESTART when one was made.

Report lines: CHANGED, RESTART, MISSING (could not fix, with the manual command). Plugins with no
decision in tools.json are ignored: the standard governs only what it lists. Silent when nothing
needed doing and --quiet is set. Exit 0 in line, 3 MISSING remains, 2 bad arguments.
Honours HERMES_HOME, so it can be exercised against a scratch Hermes home. Python 3.9, stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "hermes" / "tools.json"
SKIP_SKILL_DIRS = {"core"}
TIMEOUT = 900


class Setup:
    def __init__(self, home: Path, apply: bool, binaries: bool, safe_restart: bool = False):
        self.home = home
        self.apply = apply
        self.binaries = binaries
        self.safe_restart = safe_restart
        self.changed: list[str] = []
        self.missing: list[str] = []
        self.restart = False

    # environment ---------------------------------------------------------------------------
    def env(self) -> dict:
        """A clean environment: the Hermes CLI misbehaves when it inherits a parent agent's state."""
        keep = ("HOME", "PATH", "LANG", "LC_ALL", "USER", "GH_TOKEN", "GITHUB_TOKEN", "TMPDIR")
        env = {k: os.environ[k] for k in keep if k in os.environ}
        env["HERMES_HOME"] = str(self.home)
        env["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
        return env

    def run(self, cmd: list[str]) -> tuple[int, str]:
        try:
            r = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=TIMEOUT,
                env=self.env(),
                stdin=subprocess.DEVNULL,
            )
            return r.returncode, (r.stdout + r.stderr).strip()
        except (OSError, subprocess.SubprocessError) as exc:
            return 127, str(exc)

    # state ---------------------------------------------------------------------------------
    def enabled_plugins(self) -> set[str]:
        try:
            text = (self.home / "config.yaml").read_text(encoding="utf8")
        except OSError:
            return set()
        block = re.search(r"^plugins:\n((?:[ ].*\n|\n)*)", text, re.M)
        if not block:
            return set()
        en = re.search(r"^  enabled:\n((?:    - .*\n)+)", block.group(1), re.M)
        if not en:
            return set()
        return {
            m.group(1).strip().strip("'\"") for m in re.finditer(r"^    - (.+)$", en.group(1), re.M)
        }

    def installed_skills(self) -> set[str]:
        root = self.home / "skills"
        out: set[str] = set()
        if root.is_dir():
            for md in root.rglob("SKILL.md"):
                rel = md.relative_to(root).parts
                if rel and rel[0] not in SKIP_SKILL_DIRS:
                    out.add(md.parent.name)
        return out

    def binary_ok(self, spec: dict) -> bool:
        if not shutil.which(spec["name"], path=self.env()["PATH"]):
            return False
        rc, _ = self.run(spec.get("verify", [spec["name"], "--version"]))
        return rc == 0

    # actions -------------------------------------------------------------------------------
    def ensure_binary(self, tid: str, spec: dict) -> bool:
        if self.binary_ok(spec):
            return True
        if not (self.apply and self.binaries):
            self.missing.append(f"{tid}: binary {spec['name']} not installed")
            return False
        for manager, cmd in spec.get("install", {}).items():
            if shutil.which(manager, path=self.env()["PATH"]):
                rc, out = self.run(cmd)
                if rc == 0 and self.binary_ok(spec):
                    self.changed.append(f"{tid}: installed binary {spec['name']} with {manager}")
                    return True
                self.missing.append(f"{tid}: {' '.join(cmd)} failed (exit {rc}): {out[-300:]}")
                return False
        self.missing.append(
            f"{tid}: no supported package manager for {spec['name']} "
            f"(tried {', '.join(spec.get('install', {}))})"
        )
        return False

    def ensure_plugin(self, t: dict) -> None:
        names = {t["plugin"], *t.get("alt_plugins", [])}
        if self.enabled_plugins() & names:
            return
        if not self.apply:
            self.missing.append(f"{t['id']}: plugin {t['plugin']} not enabled. {t['install_hint']}")
            return
        if "binary" in t and not self.ensure_binary(t["id"], t["binary"]):
            return
        if t.get("install") and not (self.home / "plugins" / t["plugin"]).is_dir():
            rc, out = self.run(t["install"])
            if rc != 0:
                self.missing.append(
                    f"{t['id']}: {' '.join(t['install'])} failed (exit {rc}): {out[-300:]}"
                )
                return
        if t["plugin"] not in self.enabled_plugins():
            rc, out = self.run(["hermes", "plugins", "enable", t["plugin"]])
            if rc != 0 and t["plugin"] not in self.enabled_plugins():
                self.missing.append(
                    f"{t['id']}: hermes plugins enable {t['plugin']} failed: {out[-300:]}"
                )
                return
        self.changed.append(f"{t['id']}: plugin {t['plugin']} installed and enabled")
        self.restart = True

    def ensure_skill(self, t: dict) -> None:
        if t["skill"] in self.installed_skills():
            return
        if not (self.apply and t.get("install")):
            self.missing.append(f"{t['id']}: skill {t['skill']} not installed. {t['install_hint']}")
            return
        rc, out = self.run(t["install"])
        if rc == 0 and t["skill"] in self.installed_skills():
            self.changed.append(f"{t['id']}: skill {t['skill']} installed")
        else:
            self.missing.append(
                f"{t['id']}: {' '.join(t['install'])} failed (exit {rc}): {out[-300:]}"
            )

    def ensure_setting(self, s: dict) -> None:
        rc, cur = self.run(["hermes", "config", "get", s["key"]])
        cur = cur.strip().splitlines()[-1].strip().lower() if cur.strip() else ""
        if rc == 0 and cur == str(s["value"]).lower():
            return
        if not self.apply:
            self.missing.append(f"setting {s['key']} is {cur or 'unset'}, core wants {s['value']}")
            return
        rc, out = self.run(["hermes", "config", "set", s["key"], str(s["value"])])
        if rc == 0:
            self.changed.append(f"setting {s['key']} set to {s['value']} (was {cur or 'unset'})")
            self.restart = True
        else:
            self.missing.append(f"setting {s['key']}: hermes config set failed: {out[-300:]}")

    def ensure_safe_restart(self) -> None:
        """Keep the safe restart job (hermes/safe-restart/) installed and current: both scripts, the
        launchd agent that runs the restart outside the gateway, and the job itself, created paused.
        macOS only: the agent is launchd. Never enables the job; the operator does."""
        src = ROOT / "hermes" / "safe-restart"
        if sys.platform != "darwin":
            return
        scripts = self.home / "scripts"
        for name in ("safe_hermes_restart.py", "safe_hermes_restart_exec.py"):
            want = (src / name).read_text(encoding="utf8")
            dst = scripts / name
            have = dst.read_text(encoding="utf8") if dst.exists() else None
            if have == want:
                continue
            if not self.apply:
                self.missing.append(
                    f"safe restart script {name} is {'stale' if have else 'absent'}"
                )
                continue
            scripts.mkdir(parents=True, exist_ok=True)
            dst.write_text(want, encoding="utf8")
            self.changed.append(f"safe restart script {name} installed")
        user_home = str(Path.home())
        agent = Path(user_home) / "Library" / "LaunchAgents" / "ai.hermes.safe-restart.plist"
        plist = (
            (src / "ai.hermes.safe-restart.plist")
            .read_text(encoding="utf8")
            .replace("__HOME__", user_home)
        )
        have = agent.read_text(encoding="utf8") if agent.exists() else None
        target = f"gui/{os.getuid()}"
        loaded = (
            subprocess.run(
                ["launchctl", "print", f"{target}/ai.hermes.safe-restart"], capture_output=True
            ).returncode
            == 0
        )
        if have != plist or not loaded:
            if not self.apply:
                self.missing.append("safe restart launchd agent is not installed or is stale")
            else:
                agent.parent.mkdir(parents=True, exist_ok=True)
                agent.write_text(plist, encoding="utf8")
                subprocess.run(
                    ["launchctl", "bootout", f"{target}/ai.hermes.safe-restart"],
                    capture_output=True,
                )
                rc = subprocess.run(
                    ["launchctl", "bootstrap", target, str(agent)], capture_output=True
                ).returncode
                (self.changed if rc == 0 else self.missing).append(
                    "safe restart launchd agent installed"
                    if rc == 0
                    else "safe restart launchd agent failed to load"
                )
        rc, out = self.run(["hermes", "cron", "list"])
        if rc == 0 and "safe-hermes-restart" not in out:
            if not self.apply:
                self.missing.append("safe restart job is absent")
                return
            rc, out = self.run(
                [
                    "hermes",
                    "cron",
                    "create",
                    "--name",
                    "safe-hermes-restart",
                    "--no-agent",
                    "--script",
                    "safe_hermes_restart.py",
                    "--deliver",
                    "local",
                    "--paused",
                    "every 5m",
                ]
            )
            (self.changed if rc == 0 else self.missing).append(
                "safe restart job created paused"
                if rc == 0
                else f"safe restart job create failed: {out[-200:]}"
            )

    def run_all(self) -> Setup:
        reg = json.loads(REGISTRY.read_text(encoding="utf8"))
        for t in reg["tools"]:
            if not t.get("required") or t.get("decision") == "reject":
                continue
            if t["kind"] == "plugin":
                self.ensure_plugin(t)
            else:
                self.ensure_skill(t)
        for s in reg.get("settings", []):
            self.ensure_setting(s)
        if self.safe_restart:
            self.ensure_safe_restart()
        return self

    def lines(self) -> list[str]:
        out = [f"CHANGED {c}" for c in self.changed]
        if self.restart:
            out.append(
                "RESTART Hermes (desktop app and gateway) to load the plugin or setting changes above"
            )
        out += [f"MISSING {m}" for m in self.missing]
        return out

    @property
    def ok(self) -> bool:
        return not self.missing


def default_home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or "~/.hermes").expanduser()


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--hermes-home", default=None)
    ap.add_argument("--check", action="store_true", help="report only, install nothing")
    ap.add_argument("--no-binaries", action="store_true", help="never run a package manager")
    ap.add_argument(
        "--safe-restart",
        action="store_true",
        help="also keep the safe restart job and its launchd agent installed (off by default)",
    )
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    home = Path(a.hermes_home).expanduser() if a.hermes_home else default_home()
    s = Setup(
        home, apply=not a.check, binaries=not a.no_binaries, safe_restart=a.safe_restart
    ).run_all()
    lines = s.lines()
    if lines:
        print("\n".join(lines))
    elif not a.quiet:
        print("hermes setup matches the core decisions")
    return 0 if s.ok else 3


if __name__ == "__main__":
    sys.exit(main())
