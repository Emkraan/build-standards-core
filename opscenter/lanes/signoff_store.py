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

import hashlib
import json
import os
import re
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


def record(pr, head_sha, lane, source, hits, plan=None, extra=None, now=None):
    """Sign off PR `pr` in `lane` at `head_sha`, covering `hits` (each {fp, cfp, reason, path, rule}). `plan` is the
    plan_facts of the plan the owner saw (kept as `plan`); `extra` keys (apply_ok, apply_why, confirm_name, plan_head,
    grants) are kept under `extra` and also at the top of the record."""
    if lane not in (OWN, ENGINEER):
        raise ValueError(f"unknown lane {lane!r}")
    stamp = now if now is not None else time.time()
    rec = {
        "id": hashlib.sha1(f"{pr}:{head_sha}:{stamp}:{source}".encode()).hexdigest()[:12],
        "head_sha": head_sha,
        "lane": lane,
        "source": source,
        "signed_at": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(now if now is not None else time.time())
        ),
        "hits": [dict(h) for h in (hits or [])],
        "revoked": False,
    }
    if plan:
        rec["plan"] = plan
    if extra:
        rec["extra"] = extra
        for k, v in extra.items():
            rec.setdefault(k, v)
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
    return str(h.get("path") or "").startswith(".github/") and (
        h.get("rule") == "github-dir" or str(h.get("reason") or "").startswith(GITHUB_PREFIX)
    )


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


# A grant is a plan resource that widens who may do what: a role assignment or definition, an app role or
# delegated permission grant, a directory role or group membership. Matched on the resource address.
GRANT_RE = re.compile(
    r"role_assignment|role_definition|app_role_assignment|permission_grant|directory_role|group_member"
)


def path_of(where):
    """The file part of a hit's `where` ("a.tf:3" gives "a.tf")."""
    return re.sub(r":\d+$", "", str(where or "")) or None


def latest_epoch(pr):
    """Epoch seconds of the newest sign-off record of the PR in any lane, revoked or not, 0 when none."""
    rows = _load()["prs"].get(str(int(pr)), [])
    best = 0.0
    for rec in rows:
        try:
            t = (
                time.mktime(time.strptime(rec.get("signed_at", ""), "%Y-%m-%dT%H:%M:%SZ"))
                - time.timezone
            )
        except ValueError:
            continue
        best = max(best, t)
    return best


def plan_facts(plan):
    """What the owner saw in the plan when signing: the grant addresses it creates or changes, whether the plan is final
    and readable (completed, no errors; `unverifiable` when it is not), and its resources as [address, action]."""
    plan = plan or {}
    resources = plan.get("resources") or []
    grants = sorted(
        {
            r.get("address", "")
            for r in resources
            if GRANT_RE.search(r.get("address", ""))
            and r.get("action") in ("create", "update", "replace")
        }
    )
    final = (
        bool(plan)
        and plan.get("status") == "completed"
        and plan.get("conclusion") in (None, "success")
    )
    return {
        "grants": grants,
        "final": final,
        "unverifiable": bool(plan.get("errors")) or not plan,
        "resources": [[r.get("address", ""), r.get("action", "")] for r in resources],
        "destroy": int(plan.get("destroy") or 0),
        "replace": int(plan.get("replace") or 0),
    }


def confirm_needed(plan, pr=None):
    """The name the owner must type to cover the apply of this plan: the root of the first deleted or replaced resource,
    else None (a plan that deletes nothing needs no typed name)."""
    for r in (plan or {}).get("resources") or []:
        if r.get("action") in ("delete", "replace") and r.get("root"):
            return str(r["root"])
    return None


def review(rec, hits, plan):
    """Can the sign-off `rec` carry to a head that raises `hits` with `plan`? Returns
    {"ok": bool, "new": [hits the sign-off does not cover], "plan_new": [reasons the plan guard fails]}.
    The plan guard applies only when a plan exists: it must be final and error free, add no destroy or
    replace (a destroy count with no named object counts too) and no grant the signed plan did not hold."""
    new = [h for h in hits or [] if not covers(rec, h)]
    plan_new = []
    if plan:
        if plan.get("status") != "completed" or plan.get("conclusion") not in (None, "success"):
            plan_new.append("plan not final")
        if plan.get("errors"):
            plan_new.append("plan has errors")
        named = list(plan.get("destroyed") or []) + list(plan.get("replaced") or [])
        if named:
            plan_new.append("destroys " + ", ".join(named))
        elif int(plan.get("destroy") or 0) or int(plan.get("replace") or 0):
            plan_new.append("destroys or replaces")
        seen = set(
            ((rec.get("extra") or {}).get("grants"))
            or ((rec.get("plan") or {}).get("grants"))
            or []
        )
        grants = [g for g in plan_facts(plan)["grants"] if g not in seen]
        if grants:
            plan_new.append("plan adds grants: " + ", ".join(grants))
    carried = bool(rec) and (not hits or len(new) < len(hits))
    return {"ok": not new and not plan_new, "new": new, "plan_new": plan_new, "carried": carried}
