"""
grants.py
Purpose: Role grants for reports and dashboards (reports module P1 and P4).
           P1  Effective rights are the UNION across every matched role plus the user's own grants: a role can only add. Rights are
               strings. Reports and dashboards have SEPARATE global rights (`reports.view`, `dashboards.view`); a single report or
               dashboard is shared by a per-object right named by its key (`report:<key>`, `dashboard:<key>`), granted to a role.
           P4  A grant follows its object: a per-object grant is removed when its report or dashboard is deleted or retired, and
               `sweep` removes any that outlived its object (run it after seeding and at start), so a grant never outlives the thing
               it names and a recreated key never inherits an old role's access.
Date:    2026-11-07

API:     effective(roles, user_grants, role_grants) -> set of rights
         can_view(kind, rights, key) -> bool          kind is "report" or "dashboard"
         GrantStore(path): .grant(role, right) .revoke(role, right) .role_grants() -> {role: [rights]}
                           .on_delete(kind, key) -> removed   .sweep(live) -> removed   (live = {"report": keys, "dashboard": keys})
One writer under a lock with an atomic replace. Pure Python, no import side effect.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
from pathlib import Path

GLOBAL = {"report": "reports.view", "dashboard": "dashboards.view"}
OBJECT_RIGHT = re.compile(r"^(report|dashboard):(.+)$")


def effective(roles, user_grants, role_grants):
    """The union of the rights of every matched role and the user's own grants. An unknown role adds nothing."""
    out = set(user_grants or ())
    for r in roles or ():
        out |= set(role_grants.get(r, ()))
    return out


def can_view(kind, rights, key):
    """A report is visible with the global reports right or the right for its own key; a dashboard likewise with its own global
    right. The two global rights are separate: reports.view never opens a dashboard."""
    if kind not in GLOBAL:
        raise ValueError(f"kind must be report or dashboard, not {kind!r}")
    return GLOBAL[kind] in rights or f"{kind}:{key}" in rights


class GrantStore:
    def __init__(self, path):
        self.path = Path(path)

    def _read(self):
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return (
            {str(k): sorted(set(v)) for k, v in d.items() if isinstance(v, list)}
            if isinstance(d, dict)
            else {}
        )

    def _mutate(self, fn):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path.with_suffix(".lock"), "w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            data = self._read()
            result = fn(data)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
            os.replace(tmp, self.path)
            return result

    def role_grants(self):
        return self._read()

    def grant(self, role, right):
        if not role or not isinstance(right, str) or not right:
            raise ValueError("a grant needs a role and a right")
        self._mutate(lambda d: d.__setitem__(role, sorted(set(d.get(role, [])) | {right})))

    def revoke(self, role, right):
        def go(d):
            d[role] = sorted(set(d.get(role, [])) - {right})
            if not d[role]:
                del d[role]

        self._mutate(go)

    def _drop(self, matches):
        def go(d):
            removed = []
            for role in list(d):
                keep = []
                for right in d[role]:
                    (removed if matches(right) else keep).append(
                        (role, right) if matches(right) else right
                    )
                if keep:
                    d[role] = keep
                else:
                    del d[role]
            return removed

        return self._mutate(go)

    def on_delete(self, kind, key):
        """Remove every role's per-object grant for a deleted or retired report or dashboard. Returns [(role, right)]."""
        target = f"{kind}:{key}"
        return self._drop(lambda right: right == target)

    def sweep(self, live):
        """Remove per-object grants whose object is not live. `live` is {"report": keys, "dashboard": keys}; a kind that is not in
        `live` is left alone (nothing is removed for an unknown kind). Global rights are never touched. Returns [(role, right)]."""
        sets = {k: set(v) for k, v in live.items()}

        def dead(right):
            m = OBJECT_RIGHT.match(right)
            return bool(m) and m.group(1) in sets and m.group(2) not in sets[m.group(1)]

        return self._drop(dead)
