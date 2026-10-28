"""
applied_log.py
Purpose:
  One answer to "is this Knowledge proposal finished?", shared by the applier and the Knowledge view.

  approve-applied.jsonl records one row per outcome (published, rejected, exists, duplicate_created).
  Update proposals are keyed fp = update:<pageId>, so a corrected re-stage of a page reuses an fp that
  already has a row. Deciding "finished" on the fp alone hid such a re-stage from the Knowledge page,
  pruned it from the store and made the applier drop its approval without a word.

  Rule: a proposal is finished only when a recorded outcome covers THIS content.
    - Rows carry body_sha: finished when a row's body_sha equals the proposal's.
    - Older rows have no body_sha: finished unless the proposal was staged (restaged_utc, else
      created_utc) after the newest such row, which marks it as a re-stage.
    - No proposal content to compare (body_sha unknown): any row means finished.
  Standard library only (the applier runs on the system python, 3.9 floor).
"""

from __future__ import annotations

import json
import os


def load_index(path):
    """Map fp -> list of outcome rows. A missing file is an empty log. Unreadable lines are
    skipped, as the old fp-set readers did."""
    idx = {}
    if not os.path.exists(path):
        return idx
    with open(path, encoding="utf-8") as fh:
        for ln in fh:
            try:
                row = json.loads(ln)
                fp = row["fp"]
            except (ValueError, KeyError, TypeError):
                continue
            idx.setdefault(fp, []).append(row)
    return idx


def staged_utc(proposal):
    """When this proposal content was staged (re-stage time wins)."""
    if not isinstance(proposal, dict):
        return ""
    return proposal.get("restaged_utc") or proposal.get("created_utc") or ""


def is_finished(idx, fp, body_sha=None, staged=None):
    """True when a recorded outcome covers this fp with this content (rules above)."""
    rows = idx.get(fp)
    if not rows:
        return False
    if not body_sha:
        return True
    if any(r.get("body_sha") == body_sha for r in rows):
        return True
    legacy = [str(r.get("when") or "") for r in rows if not r.get("body_sha")]
    if not legacy:
        return False  # every row is for other content: this is a re-stage
    if not staged or not all(legacy):
        return True  # cannot tell, keep the old behaviour (never re-publish blind)
    return staged <= max(legacy)
