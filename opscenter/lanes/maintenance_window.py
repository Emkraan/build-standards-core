#!/usr/bin/env python3
# =====================================================================
# maintenance_window.py
# Purpose: Downtime classifier and maintenance-window math for the
#          <platform> engineer-PR review lane (platform_pr_review.py) and the Ops
#          Center (platform_reviews.py). Stdlib only, Python 3.9.
#
#          A PR is "downtime" when merging it to main takes a production system
#          down, even for seconds:
#            (a) it changes a deployable app whose kind restarts a running
#                service on deploy (app-service, function-app, container-app).
#                The selection mirrors .github/scripts/tf-discover.py
#                cmd_deploy exactly (watch globs, shared/packages/, the kind's
#                reusable deploy workflow, Markdown never deploys).
#            (b) its terraform-ci plan for an <platform> tier root replaces or
#                deletes a serving or data resource, or updates an attribute
#                Azure applies with a restart.
#            (c) a Terraform PR whose plan cannot be read (fail closed).
#          Engineer PRs that are downtime merge only inside the maintenance
#          window of their change class (policy.json maintenance_window).
#          <owner>'s own PRs are never held (the own-PR lane never calls this).
# Date:    2026-10-15
# =====================================================================
from __future__ import annotations

import datetime as dt
import fnmatch
import re

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - 3.9+ always has it
    ZoneInfo = None

UTC = dt.timezone.utc
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

# ---------------------------------------------------------------------
# Mirror of tf-discover.py (origin/main). maintenance_window_test.py checks
# these against the repo copy so a change there fails the parity test.
# ---------------------------------------------------------------------
DEPLOYABLE_KINDS = ("app-service", "function-app", "container-app")
SHARED_CODE = ("shared/packages/",)
PIPELINE_FILES = {
    "app-service": (".github/workflows/_deploy-app-service.yml",),
    "function-app": (".github/workflows/_deploy-function-app.yml",),
    "container-app": (".github/workflows/_deploy-container-app.yml",),
}


def touches(files, prefixes):
    return any(f == p or (p.endswith("/") and f.startswith(p)) for f in files for p in prefixes)


def glob_match(rel, pattern):
    if pattern.endswith("/**"):
        return rel.startswith(pattern[:-2])
    return fnmatch.fnmatchcase(rel, pattern)


def include_prefixes(dep):
    """tf-discover include_prefixes: each deploy.include entry and everything below it."""
    out = []
    for p in dep.get("include") or []:
        norm = p[:-1] if p.endswith("/") else p
        out += [norm, norm + "/"]
    return out


def deployed_apps(files, specs, tier=None):
    """The deploy.json specs a push of `files` to main redeploys (tf-discover cmd_deploy): watch globs,
    shared code and the kind's pipeline, deploy.include paths, and a change to the app's own
    deploy.json (tf-discover ships it when the deploy block changed. Without a base to compare
    any change counts any change, fail closed). tier='<platform>' mirrors the per-tier skip: an app whose
    deploy target declares infra with no such tier never deploys there. A missing or odd infra block
    counts as deploying (fail closed)."""
    code = [f for f in files if not f.endswith(".md")]
    by_tool = {d.get("tool"): d for d in specs}
    out = []
    for d in specs:
        dep = d.get("deploy")
        if dep is None or d.get("retired") or d.get("kind") not in DEPLOYABLE_KINDS:
            continue
        if not touches(code, SHARED_CODE + PIPELINE_FILES[d["kind"]]):
            rel = [f[len(d["_dir"]) + 1 :] for f in code if f.startswith(d["_dir"] + "/")]
            if not (
                any(glob_match(f, w) for f in rel for w in dep.get("watch") or [])
                or touches(code, tuple(include_prefixes(dep)))
                or (d.get("_file") and d["_file"] in code)
            ):
                continue
        if tier:
            infra = (by_tool.get(dep.get("tool", d.get("tool"))) or {}).get("infra")
            if isinstance(infra, dict) and infra and not isinstance(infra.get(tier), dict):
                continue
        out.append(d)
    return out


# ---------------------------------------------------------------------
# Defaults (policy.json maintenance_window overrides any of them)
# ---------------------------------------------------------------------
DEFAULT_SERVING_TYPES = (
    "azurerm_linux_web_app",
    "azurerm_windows_web_app",
    "azurerm_service_plan",
    "azurerm_app_service",
    "azurerm_container_app",
    "azurerm_container_app_environment",
    "azurerm_linux_function_app",
    "azurerm_windows_function_app",
    "azurerm_function_app_flex_consumption",
    "azurerm_logic_app_standard",
    "azurerm_postgresql_flexible_server",
    "azurerm_postgresql_flexible_server_database",
    "azurerm_cdn_frontdoor_",
    "azurerm_frontdoor",
    "azurerm_dns_",
    "azurerm_private_dns_",
    "azurerm_virtual_network",
    "azurerm_subnet",
    "azurerm_private_endpoint",
    "azurerm_key_vault",
    "azurerm_storage_account",
    "azurerm_api_management",
    "azapi_resource",
)
DEFAULT_RESTART_ATTRS = {
    "azurerm_service_plan": ["sku_name", "os_type", "worker_count", "zone_balancing_enabled"],
    "azurerm_linux_web_app": [
        "app_settings",
        "site_config",
        "virtual_network_subnet_id",
        "connection_string",
        "storage_account",
        "service_plan_id",
    ],
    "azurerm_windows_web_app": [
        "app_settings",
        "site_config",
        "virtual_network_subnet_id",
        "connection_string",
        "storage_account",
        "service_plan_id",
    ],
    "azurerm_linux_function_app": [
        "app_settings",
        "site_config",
        "virtual_network_subnet_id",
        "service_plan_id",
    ],
    "azurerm_windows_function_app": [
        "app_settings",
        "site_config",
        "virtual_network_subnet_id",
        "service_plan_id",
    ],
    "azurerm_function_app_flex_consumption": [
        "app_settings",
        "site_config",
        "virtual_network_subnet_id",
    ],
    "azurerm_container_app": ["template", "secret"],
    "azurerm_postgresql_flexible_server": [
        "sku_name",
        "version",
        "high_availability",
        "delegated_subnet_id",
        "private_dns_zone_id",
        "public_network_access_enabled",
        "zone",
    ],
    "azurerm_api_management": ["sku_name", "virtual_network_type", "virtual_network_configuration"],
}
DEFAULT_PG_STATIC = [
    "shared_preload_libraries",
    "max_connections",
    "max_worker_processes",
    "max_prepared_transactions",
    "max_locks_per_transaction",
    "max_wal_senders",
    "max_replication_slots",
    "wal_level",
    "shared_buffers",
    "huge_pages",
    "cron.database_name",
    "track_activity_query_size",
]
# Resources that patch a live object in place outside its own resource block (a create of one
# is a change to something already serving).
DEFAULT_PATCH_TYPES = ("azapi_update_resource",)
TF_SUFFIXES = (".tf", ".tf.json", ".tfvars", ".hcl")
CLASS_LABEL = {
    "standard": "standard",
    "restricted": "restricted",
    "both": "restricted and standard",
}

# Plain words for a Terraform resource type in a reason line.
TYPE_WORDS = (
    ("azurerm_service_plan", "App Service plan"),
    ("azurerm_linux_web_app", "App Service app"),
    ("azurerm_windows_web_app", "App Service app"),
    ("azurerm_container_app_environment", "Container Apps environment"),
    ("azurerm_container_app", "container app"),
    ("azurerm_postgresql_flexible_server_configuration", "Postgres server parameter"),
    ("azurerm_postgresql_flexible_server_database", "Postgres database"),
    ("azurerm_postgresql_flexible_server", "Postgres server"),
    ("azurerm_cdn_frontdoor_", "Front Door"),
    ("azurerm_frontdoor", "Front Door"),
    ("azurerm_private_dns_", "private DNS record"),
    ("azurerm_dns_", "DNS record"),
    ("azurerm_virtual_network", "virtual network"),
    ("azurerm_subnet", "subnet"),
    ("azurerm_private_endpoint", "private endpoint"),
    ("azurerm_key_vault", "Key Vault"),
    ("azurerm_storage_account", "storage account"),
    ("azurerm_api_management", "API Management"),
    ("azurerm_logic_app_standard", "Logic App"),
    ("function_app", "function app"),
    ("azapi_resource", "Azure resource"),
)


def type_words(rtype):
    for prefix, words in TYPE_WORDS:
        if rtype.startswith(prefix) or prefix in rtype:
            return words
    return rtype


def cfg_of(pol):
    return (pol or {}).get("maintenance_window") or {}


def tzinfo(cfg):
    return ZoneInfo(cfg.get("timezone") or "UTC")


def res_type(address):
    """azurerm_linux_web_app from module.x.azurerm_linux_web_app.this["k"]."""
    parts = [p for p in re.sub(r"\[[^\]]*\]", "", address).split(".") if p]
    i = 0
    while i < len(parts) and parts[i] == "module":
        i += 2
    if i < len(parts) and parts[i] == "data":
        i += 1
    return parts[i] if i < len(parts) else address


def app_name(spec):
    names = ((spec.get("edge") or {}).get("apim") or {}).get("display_name") or {}
    base = names.get("prod") or names.get("dev") or spec.get("tool")
    return base if base.lower().endswith(("api", "app")) else f"{base} API"


# ---------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------
def classify(pol, files, plan, specs, specs_error=None):
    """Downtime hits for a PR. Each hit: kind, system (tool or root name, None when unknown),
    reason (plain English naming the system), where."""
    cfg = cfg_of(pol)
    hits = []
    kinds = tuple(cfg.get("restart_kinds") or DEPLOYABLE_KINDS)
    code = [f for f in files if not f.endswith(".md")]
    if specs_error is not None:
        if code:
            hits.append(
                {
                    "kind": "deploy-map-unreadable",
                    "system": None,
                    "reason": "Could not read which apps this change deploys, so it is treated as taking a system down",
                    "where": str(specs_error)[:200],
                }
            )
    else:
        for d in deployed_apps(files, specs, tier="prod"):
            if d["kind"] not in kinds:
                continue
            what = {
                "app-service": "restarts it for a few seconds",
                "function-app": "restarts its function host for a few seconds",
                "container-app": "restarts it on a new container revision",
            }.get(d["kind"], "restarts it on deploy")
            hits.append(
                {
                    "kind": "app-deploy",
                    "system": d.get("tool"),
                    "reason": f"deploys the {app_name(d)}, which {what}",
                    "where": f"{d.get('_dir', '')} ({d['kind']} {d.get('tool')})",
                }
            )
    for x in cfg.get("extra_deploys") or []:
        if x.get("enabled") and touches(code, tuple(x.get("paths") or [])):
            hits.append(
                {
                    "kind": "extra-deploy",
                    "system": x.get("system"),
                    "reason": x.get("reason") or f"deploys {x.get('system')}, which restarts it",
                    "where": ", ".join(x.get("paths") or []),
                }
            )
    hits += plan_hits(cfg, files, plan)
    return hits


def plan_hits(cfg, files, plan):
    tier = cfg.get("tier") or "prod"
    serving = tuple(cfg.get("serving_types") or DEFAULT_SERVING_TYPES)
    restart = cfg.get("restart_attrs") or DEFAULT_RESTART_ATTRS
    pg_static = set(cfg.get("postgres_static_parameters") or DEFAULT_PG_STATIC)
    patch_types = set(cfg.get("patch_types") or DEFAULT_PATCH_TYPES)
    tf_files = [f for f in files if f.endswith(TF_SUFFIXES)]
    plan = plan or {}
    hits = []

    def unreadable(why, system=None):
        hits.append(
            {
                "kind": "plan-unreadable",
                "system": system,
                "reason": f"Could not read its Terraform plan ({why}), so it is treated as taking a system down",
                "where": plan.get("run_url") or "",
            }
        )

    if not plan.get("ran"):
        if tf_files:
            unreadable("terraform-ci did not report a plan for this head")
        return hits
    if plan.get("status") and plan.get("status") != "completed":
        unreadable(f"terraform-ci is {plan.get('status')}")
        return hits
    if plan.get("read_error"):
        unreadable(plan["read_error"][:120])
        return hits
    roots = plan.get("roots") or []
    if "resources" not in plan:
        # A plan from before the resource parser existed: fail closed when it changed anything.
        if any(
            r.get("tier") in (None, tier)
            and not str(r.get("summary") or "").startswith("No changes")
            for r in roots
        ):
            unreadable("the plan has no resource detail")
        return hits
    for r in roots:
        if r.get("tier") != tier:
            continue
        if r.get("conclusion") not in ("success", "failure"):
            continue
        if not r.get("parsed"):
            unreadable(f"no plan summary in the {r.get('root')} {tier} job", r.get("root"))
    for res in plan.get("resources") or []:
        if res.get("tier") != tier:
            continue
        rtype = res_type(res.get("address", ""))
        action = res.get("action")
        root = res.get("root")
        words = type_words(rtype)
        if rtype in patch_types and action in ("create", "update", "replace"):
            hits.append(
                {
                    "kind": "tf-patch",
                    "system": root,
                    "reason": f"patches a live Azure resource directly ({res.get('address')}) in the {root} root, which can restart what it patches",
                    "where": res.get("address", ""),
                }
            )
        elif action in ("destroy", "replace") and rtype.startswith(serving):
            verb = "deletes" if action == "destroy" else "replaces"
            hits.append(
                {
                    "kind": f"tf-{action}",
                    "system": root,
                    "reason": f"{verb} the {words} {res.get('address')} in the {root} root, which takes it offline while it happens",
                    "where": res.get("address", ""),
                }
            )
        elif action == "update":
            attrs = set(res.get("attrs") or [])
            if rtype == "azurerm_postgresql_flexible_server_configuration":
                names = set(res.get("names") or [])
                static = sorted(names & pg_static)
                if static:
                    hits.append(
                        {
                            "kind": "tf-restart",
                            "system": root,
                            "reason": f"changes the static Postgres parameter {', '.join(static)} in the {root} root, which restarts the Postgres server",
                            "where": res.get("address", ""),
                        }
                    )
                continue
            want = restart.get(rtype) or []
            changed = sorted(attrs & set(want))
            if changed:
                hits.append(
                    {
                        "kind": "tf-restart",
                        "system": root,
                        "reason": f"changes {', '.join(changed)} on the {words} {res.get('address')} in the {root} root, which Azure applies with a restart",
                        "where": res.get("address", ""),
                    }
                )
    return hits


def change_class(pol, hits):
    """restricted when any hit touches a restricted system, both when a hit has no known
    system (fail closed: it must wait for a window open to both classes), else standard."""
    restricted = set(cfg_of(pol).get("restricted_systems") or [])
    systems = [h.get("system") for h in hits]
    if any(s in restricted for s in systems if s):
        return "restricted"
    if any(s is None for s in systems):
        return "both"
    return "standard"


# ---------------------------------------------------------------------
# Window math (DST safe: every comparison is in UTC, local wall times come
# from zoneinfo for each calendar date)
# ---------------------------------------------------------------------
def _hm(s):
    h, m = str(s).split(":")
    return int(h), int(m)


def _at(date, hm, tz):
    h, m = hm
    return dt.datetime(date.year, date.month, date.day, h, m, tzinfo=tz).astimezone(UTC)


def _class_intervals(cfg, cls, now, back=2, fwd=9):
    tz = tzinfo(cfg)
    wins = ((cfg.get("classes") or {}).get(cls) or {}).get("windows") or []
    local = now.astimezone(tz).date()
    out = []
    for off in range(-back, fwd + 1):
        d = local + dt.timedelta(days=off)
        for w in wins:
            if DAYS.index(w["start_day"][:3].title()) != d.weekday():
                continue
            s_hm, e_hm = _hm(w["start"]), _hm(w["end"])
            ed = d + dt.timedelta(days=1) if e_hm <= s_hm else d
            out.append((_at(d, s_hm, tz), _at(ed, e_hm, tz)))
    out.sort()
    merged = []
    for s, e in out:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def intervals(cfg, cls, now, back=2, fwd=9):
    """Open intervals (UTC) for a class around now. 'both' is the intersection."""
    if cls != "both":
        return _class_intervals(cfg, cls, now, back, fwd)
    a = _class_intervals(cfg, "restricted", now, back, fwd)
    b = _class_intervals(cfg, "standard", now, back, fwd)
    out = []
    for s1, e1 in a:
        for s2, e2 in b:
            s, e = max(s1, s2), min(e1, e2)
            if s < e:
                out.append((s, e))
    return sorted(out)


def _utc(now):
    if now is None:
        return dt.datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(UTC)


def current(cfg, cls, now=None):
    now = _utc(now)
    for s, e in intervals(cfg, cls, now):
        if s <= now < e:
            return (s, e)
    return None


def in_window(cfg, cls, now=None):
    return current(cfg, cls, now) is not None


def next_open(cfg, cls, now=None):
    """The next window (start, end) that opens after now, or None when none is configured."""
    now = _utc(now)
    for s, e in intervals(cfg, cls, now, back=0, fwd=15):
        if s > now:
            return (s, e)
    return None


def first_window_after(cfg, cls, t):
    """The window a hold placed at t waits for: the one open at t, else the next to open."""
    t = _utc(t)
    for s, e in intervals(cfg, cls, t, back=1, fwd=15):
        if e > t:
            return (s, e)
    return None


def stale(cfg, cls, held_at, now=None, grace_minutes=None):
    """True once a full window passed since the hold and the PR is still held."""
    now = _utc(now)
    w = first_window_after(cfg, cls, held_at)
    if not w:
        return False
    g = dt.timedelta(
        minutes=grace_minutes if grace_minutes is not None else cfg.get("stale_grace_minutes", 30)
    )
    return now > w[1] + g


def _clock(local):
    h = local.hour % 12 or 12
    return f"{h}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"


def when_words(cfg, t, now=None):
    """'tonight at 9:00 PM Eastern', 'tomorrow at 10:00 PM Eastern', 'Thursday at 10:00 PM Eastern' (the zone word is parameter `timezone_label`)."""
    now = _utc(now)
    tz = tzinfo(cfg)
    lt, ln = t.astimezone(tz), now.astimezone(tz)
    zone = cfg.get("timezone_label") or cfg.get("timezone") or "UTC"
    days = (lt.date() - ln.date()).days
    clock = f"{_clock(lt)} {zone}"
    if days == 0:
        return f"{'tonight' if lt.hour >= 17 else 'today'} at {clock}"
    if days == 1:
        return f"tomorrow {'night ' if lt.hour >= 17 else 'morning ' if lt.hour < 12 else ''}at {clock}".replace(
            "  ", " "
        )
    if days < 7:
        return f"{DAY_NAMES[lt.weekday()]} at {clock}"
    return f"{DAY_NAMES[lt.weekday()]}, {lt.strftime('%B')} {lt.day} at {clock}"


def windows_words(cfg, cls):
    """'Monday to Friday nights, 9:00 PM to 6:00 AM Eastern' from the configured windows."""
    wins = ((cfg.get("classes") or {}).get(cls) or {}).get("windows") or []
    if not wins:
        return "no window configured"
    zone = cfg.get("timezone_label") or cfg.get("timezone") or "UTC"
    idx = sorted({DAYS.index(w["start_day"][:3].title()) for w in wins})
    names = [DAY_NAMES[i] for i in idx]
    if len(idx) >= 3 and idx == list(range(idx[0], idx[-1] + 1)):
        days = f"{names[0]} to {names[-1]} nights"
    elif len(names) > 1:
        days = ", ".join(names[:-1]) + f" and {names[-1]} nights"
    else:
        days = f"{names[0]} nights"
    times = {(w["start"], w["end"]) for w in wins}
    if len(times) == 1:
        s_hm, e_hm = (_hm(x) for x in next(iter(times)))
        ref = dt.datetime(2000, 1, 1)
        return f"{days}, {_clock(ref.replace(hour=s_hm[0], minute=s_hm[1]))} to {_clock(ref.replace(hour=e_hm[0], minute=e_hm[1]))} {zone}"
    return f"{days} (times vary by night, {zone})"


def class_label(cls):
    return CLASS_LABEL.get(cls, cls)


def window_phrase(cfg, cls, now=None):
    """'the next standard window, tonight at 9:00 PM Eastern' (or the open one)."""
    now = _utc(now)
    cur = current(cfg, cls, now)
    label = class_label(cls)
    if cur:
        return f"the {label} window that is open now (until {when_words(cfg, cur[1], now)})"
    nxt = next_open(cfg, cls, now)
    if not nxt:
        return f"the next {label} window (none is configured yet)"
    return f"the next {label} window, {when_words(cfg, nxt[0], now)}"


def systems_phrase(hits, limit=3):
    reasons = [h["reason"] for h in hits[:limit]]
    more = len(hits) - limit
    text = ". It also ".join(reasons) if reasons else "takes a production system down"
    if more > 0:
        text += f", plus {more} more"
    return text


def pr_comment(cfg, cls, hits, now=None):
    """The one PR comment, in the reviewer's voice. No em dashes, no semicolons, no tool names."""
    now = _utc(now)
    first = hits[0]["reason"] if hits else "takes a production system down briefly"
    others = len(hits) - 1
    extra = (
        f" It also touches {others} more system{'s' if others != 1 else ''} the same way."
        if others > 0
        else ""
    )
    body = (
        f"Approved. This change {first}.{extra} Changes like this go in during our maintenance window, "
        f"so it will merge in {window_phrase(cfg, cls, now)}. A new push resets this and it will be reviewed again."
    )
    return body.replace(";", ",").replace("\u2014", ",").replace("\u2013", "-")
