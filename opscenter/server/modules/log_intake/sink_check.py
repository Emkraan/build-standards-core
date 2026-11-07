"""
sink_check.py
Purpose: What the module's own identity can do at the sink, checked without changing anything, and a marked test row sent through a stream's real
         sink path (log intake E6). Nothing here assigns a role or a right: a missing right is reported with the role and the scope that would grant
         it, for the owner of the sink to apply. The sink is a slot; this file holds the generic parts (the check shape, the permission matcher, the
         rights checks, the test row) and a provider supplies what is specific to its cloud.
Date:    2026-11-07
Notes:   Ported from the reference implementation. Its cloud calls, resource id patterns and role names are the provider's; the generic algorithm is here.
Check:   {"id", "label", "ok": True | False | None, "detail", "fix"?}   None means "could not be read", never a pass.
Sink slot (all optional): sink.diagnose() -> [Check], sink.has_table(table) -> bool, sink.send(table, rows), sink.find_marker(table, marker) -> bool
"""

from __future__ import annotations

import datetime as dt
import re
import secrets

from . import stream_store
from . import streams as st

TEST_SOURCE = "intake-test"
MARKER_RE = re.compile(r"^test-[0-9a-f]{12}$")


def _pattern(p):
    return re.compile("^" + ".*".join(re.escape(part) for part in p.split("*")) + "$", re.I)


def _matches(patterns, action):
    return any(_pattern(p).match(action) for p in (patterns or []))


def action_allowed(perms, action, data=False):
    """True when some role grants the action and none of its exclusions removes it. `perms` is a list of
    {actions, notActions, dataActions, notDataActions}; `*` in a pattern matches any text; matching ignores case."""
    for p in perms:
        allow = p.get("dataActions") if data else p.get("actions")
        deny = p.get("notDataActions") if data else p.get("notActions")
        if _matches(allow, action) and not _matches(deny, action):
            return True
    return False


def grant_fix(role, scope):
    return f'Assign "{role}" to the module\'s identity on {scope}.'


def check_actions(perms, needs):
    """Checks for the actions an identity needs. `perms` is the list from `action_allowed`, or {"error": text} when the rights could not be
    read (every check is then ok None with the reason, never a pass). `needs` is [(id, label, action, data, role, scope)]."""
    out = []
    for cid, label, action, data, role, scope in needs:
        if isinstance(perms, dict) and "error" in perms:
            out.append(
                {
                    "id": cid,
                    "label": label,
                    "ok": None,
                    "detail": f"Could not read the identity's rights ({perms['error']}).",
                }
            )
            continue
        ok = action_allowed(perms, action, data)
        c = {
            "id": cid,
            "label": label,
            "ok": ok,
            "detail": "Allowed." if ok else f"Missing {action}.",
        }
        if not ok:
            c["fix"] = grant_fix(role, scope)
        out.append(c)
    return out


def diagnose(sink):
    """The checks a sink reports, normalised: every check has an id, a label, ok True, False or None and a detail, and a failed check always
    has a fix line. No sink, or a sink that cannot diagnose, is one failed check saying so."""
    fn = getattr(sink, "diagnose", None)
    if sink is None or not callable(fn):
        return [
            {
                "id": "sink",
                "label": "A sink is configured",
                "ok": False,
                "detail": "No sink is configured, or it cannot run checks.",
                "fix": "Configure a sink.",
            }
        ]
    try:
        raw = list(fn())
    except Exception as e:  # noqa: BLE001 - a sink that cannot be checked is not a pass
        return [
            {
                "id": "sink",
                "label": "The sink answered",
                "ok": None,
                "detail": f"The checks could not run: {str(e)[:200]}",
            }
        ]
    out = []
    for c in raw:
        ok = c.get("ok")
        item = {
            "id": str(c.get("id")),
            "label": str(c.get("label")),
            "ok": ok if ok in (True, False) else None,
            "detail": str(c.get("detail") or ""),
        }
        if item["ok"] is False:
            item["fix"] = str(c.get("fix") or "See the detail.")
        out.append(item)
    return out


def send_test_row(stream_key, actor, sink):
    """One marked row through the stream's real sink path. The marker never matches a device, so reports ignore it. A stream whose table is not
    created at the sink yet is refused. Returns {table, marker}."""
    stream = stream_store.get_stream(stream_key)
    if not stream:
        raise KeyError("Stream not found")
    st.assert_stream_table(stream["table"])
    has = getattr(sink, "has_table", None)
    if sink is None or not callable(has) or not has(stream["table"]):
        raise ValueError(f"{stream['table']} is not created at the sink yet")
    marker = "test-" + secrets.token_hex(6)
    sink.send(
        stream["table"],
        [
            {
                "Source": TEST_SOURCE,
                "SnapshotId": marker,
                "CollectedAt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            }
        ],
    )
    stream_store.audit(
        actor,
        "log-intake.sink.test-row",
        {"stream": stream_key, "table": stream["table"], "marker": marker},
    )
    return {"table": stream["table"], "marker": marker}


def verify_test_row(stream_key, marker, sink):
    """Whether the marked row has reached the sink (new rows can take a few minutes). The marker must be one this module made."""
    stream = stream_store.get_stream(stream_key)
    if not stream:
        raise KeyError("Stream not found")
    st.assert_stream_table(stream["table"])
    if not MARKER_RE.match(str(marker)):
        raise ValueError("Not a test marker")
    find = getattr(sink, "find_marker", None)
    if not callable(find):
        raise ValueError("The sink cannot look for a test row")
    return {"found": bool(find(stream["table"], marker))}
