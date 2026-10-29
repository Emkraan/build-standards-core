"""
review_config.py
Purpose: The estate values the review pages need, read from one JSON file so no module carries a repo, a login or an
         environment name. File: OPSCENTER_REVIEWS_CONFIG, else <state>/reviews-config.json. Read on every call (a
         change applies without a restart). A missing or unreadable file is the null default: nothing configured,
         and each page answers its empty state and refuses a write with 501.
Keys:    owner            the owner's login on the code host (the identity every decision is made as)
         plan_repo        owner/name of the infrastructure repo whose plan runs the plan review waits on
         plan_env         the deployment environment a plan run waits on
         privileged_envs  {environment: label} for the privileged lane (the environments the owner decides by hand)
         typed_confirm    environments whose approval needs the confirm name typed
         other_repo       owner/name of a second repo with its own review page
         core_lane_repo   owner/name of the repo that is the core consumer lane (repo reviews)
         repo_reviews     list of owner/name the repo reviews page covers
Run:     python3 review_config_test.py
"""

import json
import os

import paths

_KEYS = (
    "owner",
    "plan_repo",
    "plan_env",
    "privileged_envs",
    "typed_confirm",
    "other_repo",
    "core_lane_repo",
    "repo_reviews",
)


class NotConfigured(Exception):
    """A write that needs a value the consumer has not supplied. status 501 maps to a clear answer in the server."""

    status = 501


def _path():
    return os.environ.get("OPSCENTER_REVIEWS_CONFIG") or str(
        paths.state_dir() / "reviews-config.json"
    )


def load():
    try:
        with open(_path()) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return {k: data[k] for k in _KEYS if isinstance(data, dict) and k in data}


def _str(key):
    v = load().get(key)
    return v.strip() if isinstance(v, str) else ""


def owner():
    return _str("owner")


def plan_repo():
    return _str("plan_repo")


def plan_env():
    return _str("plan_env")


def other_repo():
    return _str("other_repo")


def core_lane_repo():
    return _str("core_lane_repo")


def privileged_envs():
    v = load().get("privileged_envs")
    return {str(k): str(x) for k, x in v.items()} if isinstance(v, dict) else {}


def typed_confirm():
    v = load().get("typed_confirm")
    return tuple(str(x) for x in v) if isinstance(v, list) else ()


def repo_reviews():
    v = load().get("repo_reviews")
    return [str(x) for x in v if "/" in str(x)] if isinstance(v, list) else []


def need(value, what):
    """The value, or NotConfigured naming what to set."""
    if not value:
        raise NotConfigured(f"no {what} configured (OPSCENTER_REVIEWS_CONFIG)")
    return value
