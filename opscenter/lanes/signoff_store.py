"""
signoff_store.py

Purpose: Reference sign-off store for the plan gate (tfplan_gate.set_signoff_store). One owner sign-off per
         pull request and lane records the head that was signed and the held hits it covers, with their
         content fingerprints. The gate reads it to carry an approval to a later head whose held content is
         identical; the plan card and the Approve and merge helper write it.

Lanes: OWN (the owner's own pull requests: a sign-off carries to later heads, the plan check at merge time
       guards the plan) and ENGINEER (other authors: a sign-off applies to the exact head only).
File:  <TFGATE_STATE_DIR>/pr-signoffs.json  {"prs": {"<pr>": [record, ...]}}, newest last, KEEP_PER_PR kept,
       written atomically, mode 0600. A record: {head_sha, lane, source, signed_at, hits, revoked}.
"""

import json
import os
import tempfile
import time
from pathlib import Path

OWN = "own"
ENGINEER = "engineer"
KEEP_PER_PR = 5
GITHUB_PREFIX = "changes .github/"


def _path():
    base = os.environ.get("TFGATE_STATE_DIR") or str(
        Path.home() / ".opscenter" / "state" / "tf-review"
    )
    return Path(base) / "pr-signoffs.json"


def _load():
    try:
        data = json.loads(_path().read_text())
        return data if isinstance(data, dict) and isinstance(data.get("prs"), dict) else {"prs": {}}
    except (OSError, ValueError):
        return {"prs": {}}


def _save(data):
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".pr-signoffs.")
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh, indent=1, sort_keys=True)
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def record(pr, head_sha, lane, source, hits, extra=None, now=None):
    """Sign off PR `pr` in `lane` at `head_sha`, covering `hits` (each {fp, cfp, reason, path, rule})."""
    if lane not in (OWN, ENGINEER):
        raise ValueError(f"unknown lane {lane!r}")
    rec = {
        "head_sha": head_sha,
        "lane": lane,
        "source": source,
        "signed_at": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(now if now is not None else time.time())
        ),
        "hits": [dict(h) for h in (hits or [])],
        "revoked": False,
    }
    if extra:
        rec["extra"] = extra
    data = _load()
    rows = data["prs"].setdefault(str(int(pr)), [])
    rows.append(rec)
    data["prs"][str(int(pr))] = rows[-KEEP_PER_PR:]
    _save(data)
    return rec


def revoke(pr, by=""):
    """Revoke every live sign-off of the PR (kept in the history, never carries). True when any was live."""
    data = _load()
    n = 0
    for rec in data["prs"].get(str(int(pr)), []):
        if not rec.get("revoked"):
            rec["revoked"] = True
            rec["revoked_by"] = by
            n += 1
    if n:
        _save(data)
    return bool(n)


def active(pr, lane=OWN, head_sha=None):
    """The newest live sign-off of the PR in `lane`, or None. With head_sha it must be for that exact head."""
    for rec in reversed(_load()["prs"].get(str(int(pr)), [])):
        if rec.get("lane") != lane or rec.get("revoked"):
            continue
        if head_sha is not None and rec.get("head_sha") != head_sha:
            continue
        return rec
    return None


def _is_github_hit(h):
    return str(h.get("path") or "").startswith(".github/") and str(
        h.get("reason") or ""
    ).startswith(GITHUB_PREFIX)


def covers(rec, hit):
    """True when the sign-off covers this held hit: the same content fingerprint, or (for a .github file, which
    the policy card and the plan card both report under different rules) the same file content fingerprint."""
    if not rec or not hit or not hit.get("fp"):
        return False
    for h in rec.get("hits") or []:
        if h.get("fp") and h["fp"] == hit["fp"]:
            return True
        if (
            _is_github_hit(h)
            and _is_github_hit(hit)
            and h.get("cfp")
            and h["cfp"] == hit.get("cfp")
        ):
            return True
    return False
