"""A scratch state tree holding the two review policy fixtures, for the review lane checks.

install() makes a temporary home and state root, copies the fixtures from opscenter/lanes/fixtures to
`review/policy.json` and `secondary-review/own-pr-policy.json` under it, points OPSCENTER_STATE_DIR and
OPSCENTER_AGENT_HOME at the scratch tree and returns the state root. A check that calls it before it imports a
lane module never reads the machine's real state, and the fixtures are the only policy it can see.
Test support only: nothing in the product imports it.
"""

import os
import shutil
import tempfile
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "lanes" / "fixtures"


def install() -> Path:
    home = Path(tempfile.mkdtemp(prefix="policy-env-", dir=os.environ.get("TMPDIR")))
    state = home / "state"
    (state / "review").mkdir(parents=True)
    (state / "secondary-review").mkdir(parents=True)
    shutil.copy(FIXTURES / "review-policy.json", state / "review" / "policy.json")
    shutil.copy(FIXTURES / "own-pr-policy.json", state / "secondary-review" / "own-pr-policy.json")
    (home / "agent" / "cache").mkdir(parents=True)
    os.environ["HOME"] = str(home)
    os.environ["OPSCENTER_ROOT"] = str(home)
    os.environ["OPSCENTER_STATE_DIR"] = str(state)
    os.environ["OPSCENTER_AGENT_HOME"] = str(home / "agent")
    return state
