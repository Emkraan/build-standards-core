"""
platform_reviews_testenv.py
Purpose: Shared set-up for the platform reviews tests. The modules read their state directories and settings when they are
         imported, so a test file applies its environment and a review config here, reloads the modules, and restores
         everything afterwards (the whole suite shares one interpreter).
"""

import importlib
import json
import os
from pathlib import Path

MODULES = ("review_acted", "tf_reviews", "privileged_reviews", "platform_reviews")
CONFIG = {
    "owner": "owner1",
    "plan_repo": "acme/infra",
    "plan_env": "plan",
    "privileged_envs": {"governance": "Governance", "destroy": "Destroy"},
    "typed_confirm": ["destroy"],
    "platform": {
        "tiers": {"prod": "prod", "dev": "dev"},
        "plan_environment": "plan",
        "destroy_workflow": "destroy.yml",
        "privileged_label": "Privileged",
        "default_branch": "main",
        "ai_review_marker": "<!-- review:v1 -->",
        "ai_review_data_prefix": "<!-- review-data:v2 ",
        "ai_review_check_name": "review result",
        "override_label": "review-override",
        "app_manifest_name": "deploy.json",
        "assistant_name": "the assistant",
        "operator_display_name": "Owner",
        "default_changes_text": "Holding this for now.",
        "forbidden_text_pattern": r"ops-center|\bbot\b|assistant",
        "applier_texts": {"owner": "the owner applies it from a saved plan"},
    },
}
_saved = {}


def _reload():
    for name in MODULES:
        importlib.reload(importlib.import_module(name))


def apply(env, tmp, config=None):
    """Set `env` and a review config under `tmp`, reload the modules."""
    cfg = Path(tmp) / "reviews-config.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps(CONFIG if config is None else config))
    env = dict(env, OPSCENTER_REVIEWS_CONFIG=str(cfg))
    for k in env:
        _saved.setdefault(k, os.environ.get(k))
    os.environ.update(env)
    _reload()


def restore():
    for k, v in _saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    _saved.clear()
    _reload()
