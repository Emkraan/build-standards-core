"""The work tracker parameters, one JSON file for the tracker module and its three users (sprint close, needs me, ticket
progress, retro row). OPSCENTER_TRACKER_PARAMS names it (default <state>/tracker-params.json); every key is optional and no
default names an estate. A missing site or driver makes a call fail with a clear error and the page hides itself.

  site_id            the tracker site (cloud) id the driver calls are scoped to
  browse_url         the browse URL prefix for an issue key
  driver_cmd         the command list that runs one call: `<cmd> <tool> '<json args>'` prints the JSON-RPC result
                     (default: the reference driver beside this file, configured by TRACKER_ENDPOINT and TRACKER_TOKEN_FILE)
  project            the tracker project key the active sprint is read from (empty: no project filter)
  team_clause        a JQL clause that scopes a view to the owner's team (empty: none)
  sprint_field       the Sprint custom field id (default customfield_10020)
  points_field       the story points custom field id (default customfield_10016)
  email_domain       the address domain a roster email must have to be used in a query (empty: any)
  owner_name         the owner's display name (assignee match, tracker owner match, card owner)
  change_jql, change_pending_statuses, change_inflight_statuses, change_fields, portal_url_template
                     the changes pending the owner's approval (read only); no change_jql means no changes page data
  intake_parent      the epic key whose children are intake tickets (never commented by ticket progress)
  retro              the retro row settings (retro_row.py)
"""

import importlib.util
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("OPSCENTER_ROOT") or Path.home() / ".opscenter")
STATE = Path(os.environ.get("OPSCENTER_STATE_DIR") or ROOT / "state")


def load():
    f = os.environ.get("OPSCENTER_TRACKER_PARAMS") or str(STATE / "tracker-params.json")
    try:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    return d if isinstance(d, dict) else {}


P = load()


def get(key, default=None):
    v = P.get(key)
    return default if v in (None, "") else v


def driver_cmd():
    c = P.get("driver_cmd")
    if isinstance(c, list) and c:
        return [str(a) for a in c]
    return [sys.executable, str(HERE / "driver.py")]


def people():
    """The people plug-in (OPSCENTER_PEOPLE, a file path) or None: used for the roster."""
    p = os.environ.get("OPSCENTER_PEOPLE")
    if not p:
        return None
    spec = importlib.util.spec_from_file_location("tracker_people_plugin", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
