"""Build a throwaway HOME so a test never reads or writes the machine's real agent home or state tree.

Several lane and gate scripts resolve their siblings and state files through the agent home
(`<home>/<agent_dir>/scripts`, `skills`) and the state tree (`<home>/<ops_dir>/state`). A test that
calls install() before it imports those scripts sees only this checkout and the fixtures it passes,
so it behaves the same on a CI runner with an empty home. Test support only: nothing in the
product imports it.
"""

import os
import shutil
import tempfile
from pathlib import Path


def install(
    scripts=None, skills=None, state_fixtures=None, agent_dir=".agent", ops_dir="ops"
) -> Path:
    """Create the temp HOME, point HOME at it and return it. Call once per process.

    scripts, skills   folders linked as <agent_dir>/scripts and <agent_dir>/skills (optional)
    state_fixtures    {relative path under <ops_dir>/state: fixture file to copy there}
    """
    home = Path(tempfile.mkdtemp(prefix="hermetic-home-", dir=os.environ.get("TMPDIR")))
    agent = home / agent_dir
    (agent / "cache" / "scratch").mkdir(parents=True)
    for name, target in (("scripts", scripts), ("skills", skills)):
        if target:
            (agent / name).symlink_to(Path(target).resolve(), target_is_directory=True)
    state = home / ops_dir / "state"
    state.mkdir(parents=True)
    for rel, fixture in (state_fixtures or {}).items():
        dest = state / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(fixture, dest)
    os.environ["HOME"] = str(home)
    return home
