"""Where the ops center keeps things, from environment variables, never from a literal home path.

OPSCENTER_STATE_DIR  the state tree (default ~/.opscenter/state); its `dashboard` folder holds the board files
OPSCENTER_ROOT       the parent of the state tree and the runtime folders (default ~/.opscenter)
OPSCENTER_AGENT_HOME the agent runtime's home: its cron folder, scripts and logs (default ~/.opscenter/agent)
OPSCENTER_REPOS      where local clones live (default: a repos folder in the home directory)
Binaries (gh, az, git) are found on PATH unless a module's own override variable names one.
"""

import os
import shutil
from pathlib import Path


def root():
    return Path(os.environ.get("OPSCENTER_ROOT") or Path.home() / ".opscenter")


def state_dir():
    return Path(os.environ.get("OPSCENTER_STATE_DIR") or root() / "state")


def dashboard_dir():
    return state_dir() / "dashboard"


def agent_home():
    return Path(os.environ.get("OPSCENTER_AGENT_HOME") or root() / "agent")


def repos_dir():
    return Path(os.environ.get("OPSCENTER_REPOS") or Path.home() / "repos")


def which(name, override_env=None):
    """The binary `name`: the override variable when set, else the one on PATH, else the bare name."""
    if override_env and os.environ.get(override_env):
        return os.environ[override_env]
    return shutil.which(name) or name
