"""
pr_landing.py
Purpose: The structured ask for PR cards on the review pages: what the owner is asked to approve, who asked, what
         lands at the merge per Terraform root, why it needs the owner, the risks and what the buttons do.
         Everything here comes from facts (the PR's changed files, the PR plan run, the roots spec on main, the hold
         and review data). The model never decides which root a merge applies.
         "Lands at merge" mirrors the consumer's apply workflow on main: it applies once per applier, and a root is
         picked when the PR changed a path the root watches (its folder plus the watch list in the roots spec), when
         deploy.json inputs the root reads changed, or, for an app root, when the PR changed a shared Terraform module
         or the app's own folder. Tiers other than the apply tier are applied before the merge and a root with no
         pipeline applier (owner) is applied by hand, so neither is applied by the merge.
         The estate values are data, `OPSCENTER_LANDING_CONFIG` (default <state>/landing-config.json), every key optional:
           apply_tier        the tier the merge applies (default "prod")
           shared_modules    path prefixes of shared Terraform modules (default none)
           gates             {applier: what follows the apply} (default: tfapply "none", anything else "applied by hand")
           destroy_gate      what follows an apply that destroys (default "destroy approval")
           destroy_appliers  the appliers the destroy gate covers (default ["tfapply"])
Date:    2026-10-22
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import paths


def _cfg():
    f = os.environ.get("OPSCENTER_LANDING_CONFIG") or str(paths.state_dir() / "landing-config.json")
    try:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _apply_tier():
    return str(_cfg().get("apply_tier") or "prod")


def _shared_modules():
    v = _cfg().get("shared_modules")
    return tuple(str(x) for x in v) if isinstance(v, list) else ()


def _gates():
    g = {"tfapply": "none, the apply needs no approval"}
    v = _cfg().get("gates")
    if isinstance(v, dict):
        g.update({str(k): str(x) for k, x in v.items()})
    return g


def _destroy_gate():
    return str(_cfg().get("destroy_gate") or "destroy approval")


def _destroy_appliers():
    v = _cfg().get("destroy_appliers")
    return tuple(str(x) for x in v) if isinstance(v, list) else ("tfapply",)


KIND_OWN = "pr_signoff"
KIND_ENGINEER = "pr_engineer"
KINDS = (KIND_OWN, KIND_ENGINEER)
RESOURCE_CAP = 300

# Same lists the sign-off store uses: a resource whose type grants access.
GRANT_RE = re.compile(
    r"role_assignment|role_definition|app_role_assignment|approleassignment|delegated_permission_grant|"
    r"oauth2_permission_grant|application_api_access|required_resource_access|directory_role|"
    r"pim_|group_member|access_policy|federated_identity_credential",
    re.I,
)
ENTRA_TYPE_RE = re.compile(
    r"^azuread_|^msgraph_|app_role_assignment|directory_role|application_api_access", re.I
)
PLAN_LINE = re.compile(
    r"Plan:\s*(?:(\d+) to import,\s*)?(\d+) to add,\s*(\d+) to change,\s*(\d+) to destroy"
)
JOB = re.compile(r"^terraform plan \((\S+) (\S+)\)$")
TICKET = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")


def _txt(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _sentence(s):
    s = _txt(s)
    return s if not s or s[-1] in ".!?" else s + "."


def _join(items):
    items = [str(i) for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _n(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def counts(summary):
    """(add, change, destroy) from a terraform Plan line, (0, 0, 0) for No changes, None when unreadable."""
    m = PLAN_LINE.search(summary or "")
    if m:
        return int(m.group(2)), int(m.group(3)), int(m.group(4))
    if str(summary or "").startswith("No changes"):
        return 0, 0, 0
    return None


def res_type(addr):
    a = re.sub(r"\[[^\]]*\]", "", addr or "")
    parts = [p for p in a.split(".") if p]
    i = 0
    while i < len(parts):
        if parts[i] == "module":
            i += 2
            continue
        if parts[i] == "data":
            return "data." + (parts[i + 1] if i + 1 < len(parts) else "")
        return parts[i]
    return ""


def compact_plan(plan):
    """Per-root counts and the resource list of a terraform-ci plan (the review lane's plan summary
    shape), small enough to ride on the card. None when terraform-ci did not run."""
    if not isinstance(plan, dict) or not plan.get("ran"):
        return None
    rows = []
    for r in plan.get("roots") or []:
        name, tier = r.get("root"), r.get("tier")
        if not name:
            m = JOB.match(r.get("job") or "")
            name, tier = (m.group(1), m.group(2)) if m else (None, None)
        if not name:
            continue
        c = counts(r.get("summary"))
        rows.append(
            {
                "root": name,
                "tier": tier,
                "add": c[0] if c else None,
                "change": c[1] if c else None,
                "destroy": c[2]
                if c
                else (r.get("destroy") if isinstance(r.get("destroy"), int) else None),
                "summary": _txt(r.get("summary"))[:160],
                "guard_only": bool(r.get("guard_only")),
                "ok": r.get("conclusion") in (None, "success") or bool(r.get("guard_only")),
            }
        )
    res = [
        {
            "root": x.get("root"),
            "tier": x.get("tier"),
            "address": x.get("address"),
            "action": x.get("action"),
        }
        for x in (plan.get("resources") or [])[:RESOURCE_CAP]
        if x.get("address")
    ]
    return {"rows": rows, "resources": res}


def _applier(spec):
    return spec.get("applied_by") or ("tfapply" if spec.get("apply") else "owner")


def _touches(files, prefixes):
    return any(f == p or (p.endswith("/") and f.startswith(p)) for f in files for p in prefixes)


def _decide(row, files, spec_all):
    """(lands, applier, reason) for one planned (root, tier) of the PR plan."""
    name, tier = row["root"], row["tier"]
    sp = spec_all.get(name)
    has_change = bool((row.get("add") or 0) + (row.get("change") or 0) + (row.get("destroy") or 0))
    if tier != _apply_tier():
        return (
            False,
            (_applier(sp) if sp else "tfapply"),
            f"the {tier} tier is applied from the branch before the merge, the merge applies only {_apply_tier()}",
        )
    if sp is None:
        shared = _touches(files, _shared_modules())
        own = any(f"/{name}/" in "/" + f for f in files)
        if shared or own:
            return (
                True,
                "tfapply",
                "an app root, picked because the PR changed "
                + ("a shared Terraform module" if shared and not own else "its own folder"),
            )
        return False, "tfapply", "an app root this PR does not change"
    applier = _applier(sp)
    if applier == "owner":
        return (
            False,
            applier,
            "no pipeline applies this root, the owner applies it by hand from a saved plan",
        )
    root = ((sp.get("tiers") or {}).get(tier) or {}).get("root", "").rstrip("/")
    watch = ([root + "/"] if root else []) + list(sp.get("watch") or [])
    if _touches(files, watch):
        return True, applier, "the PR changed a path this root watches"
    if sp.get("inputs") and any(f.endswith("deploy.json") for f in files) and has_change:
        return True, applier, "the PR changed deploy.json and this root reads those inputs"
    return False, applier, "the PR changes nothing this root watches"


def landing(plan_rows, files, spec_all, plan_unread=False):
    """What the merge applies, per root. files None means the PR file list could not be read.
    Returns {status, roots, not_applied, empty}. roots and not_applied rows carry
    root, tier, add, change, destroy, grants, entra, applier, gate and reason."""
    out = {"status": "ok", "roots": [], "not_applied": [], "empty": 0}
    if not plan_rows:
        # no rows because the plan result was never read is not the same as no plan.
        out["status"] = "plan_unread" if plan_unread else "no_plan"
        return out
    if files is None:
        out["status"] = "unknown"
        files = []
    rows, resources = plan_rows.get("rows") or [], plan_rows.get("resources") or []
    for r in rows:
        has = bool((r.get("add") or 0) + (r.get("change") or 0) + (r.get("destroy") or 0))
        lands, applier, why = _decide(r, files, spec_all)
        if out["status"] == "unknown":
            lands, why = False, "the PR file list could not be read, so this cannot be told"
        mine = [x for x in resources if x.get("root") == r["root"] and x.get("tier") == r["tier"]]
        grants = sum(
            1
            for x in mine
            if x.get("action") != "destroy" and GRANT_RE.search(res_type(x.get("address")))
        )
        entra = sum(
            1
            for x in mine
            if x.get("action") != "destroy" and ENTRA_TYPE_RE.search(res_type(x.get("address")))
        )
        destroys = r.get("destroy") or 0
        entry = {
            "root": r["root"],
            "tier": r["tier"],
            "add": r.get("add"),
            "change": r.get("change"),
            "destroy": r.get("destroy"),
            "grants": grants,
            "entra": entra,
            "applier": applier,
            "gate": (
                _destroy_gate()
                if destroys and applier in _destroy_appliers()
                else _gates().get(applier, "applied by hand")
            ),
            "reason": why,
            "destroys_named": sorted(
                x["address"]
                for x in mine
                if x.get("action") in ("destroy", "replace") and x.get("address")
            )[:12],
        }
        if lands:
            out["roots"].append(entry)
        elif has:
            out["not_applied"].append(entry)
        else:
            out["empty"] += 1
    return out


def needs_confirm(land):
    """True when the roots this merge applies delete something or grant identity types (or when that
    cannot be told). This is when the Approve and merge click asks for the typed name."""
    if land.get("status") in ("unknown",):
        return True
    return any(
        (r.get("destroy") or 0) > 0 or (r.get("entra") or 0) > 0 for r in land.get("roots") or []
    )


def land_text(land):
    """The per-root facts as plain lines for the model prompt, exact and complete."""
    st = land.get("status")
    if st == "no_plan":
        return "No Terraform plan ran for this commit, so no root is planned. The merge applies nothing from a plan."
    if st == "plan_unread":
        return (
            "The Terraform plan result for this commit could NOT be read here. Never say a plan did or did not run. "
            "Say the plan counts are not shown on this card and point to the PR's terraform plan checks."
        )
    if st == "unknown":
        return "The PR file list could not be read, so it is NOT KNOWN which roots the merge applies. Say that."
    lines = ["LANDS AT MERGE (the main terraform-apply run applies these roots after the merge):"]
    for r in land["roots"]:
        lines.append(f"- {_row_text(r)} Gate: {r['gate']}.")
    if not land["roots"]:
        lines.append("- none. The merge applies no planned root.")
    lines.append(
        "NOT APPLIED BY THIS MERGE (plan results only, never say these apply after the merge):"
    )
    for r in land["not_applied"]:
        lines.append(f"- {_row_text(r)} Not applied because {r['reason']}.")
    if not land["not_applied"]:
        lines.append("- none")
    return "\n".join(lines)


def _row_text(r):
    c = [r.get("add"), r.get("change"), r.get("destroy")]
    plan = (
        "plan not readable" if None in c else f"{c[0]} to add, {c[1]} to change, {c[2]} to destroy"
    )
    extra = f", {r['grants']} access grants" if r.get("grants") else ""
    return f"{r['root']} ({r['tier']}): {plan}{extra}."


# ---- the structured ask ----


def kind_of(lane):
    return KIND_OWN if lane == "mine" else KIND_ENGINEER


def _loc(x):
    return _txt(x.get("location") or x.get("where"))


def _why_rows(s):
    rows = []
    if s["lane"] == "mine":
        for r in s.get("rules") or []:
            rows.append(
                {
                    "kind": "rule",
                    "label": _txt(r.get("plain") or r.get("rule")),
                    "id": r.get("rule") or "",
                    "severity": "policy rule",
                    "where": _txt(r.get("where")),
                }
            )
    else:
        bd = (s.get("breakdown") or {}).get("rules") or []
        for r in bd:
            if isinstance(r, dict):
                rows.append(
                    {
                        "kind": "rule",
                        "label": _txt(r.get("reason") or r.get("rule")),
                        "id": r.get("rule") or "",
                        "severity": "policy rule",
                        "where": _txt(r.get("where")),
                    }
                )
            else:
                rows.append(
                    {
                        "kind": "rule",
                        "label": _txt(r),
                        "id": "",
                        "severity": "policy rule",
                        "where": "",
                    }
                )
        for t in s.get("tfplan_reasons") or []:
            rows.append(
                {
                    "kind": "rule",
                    "label": _txt(t),
                    "id": "",
                    "severity": "plan gate hold",
                    "where": "",
                }
            )
    for f in s.get("findings") or []:
        rows.append(
            {
                "kind": "finding",
                "label": _txt(f"{f.get('id') or ''} {f.get('title') or ''}"),
                "id": f.get("id") or "",
                "severity": _txt(f.get("severity")) or "finding",
                "where": _loc(f),
            }
        )
    return rows


def _asked_by(s):
    lane = s["lane"]
    branch = s.get("branch") or ""
    tickets = TICKET.findall(branch) + TICKET.findall(s.get("title") or "")
    ticket = tickets[0] if tickets else ""
    rows = [
        {"label": "Author", "value": _sentence(s.get("author") or "unknown")},
        {"label": "Branch", "value": _sentence(branch) if branch else "Not loaded yet."},
        {
            "label": "Ticket",
            "value": _sentence(ticket) if ticket else "None named in the branch or the title.",
        },
    ]
    if lane == "mine":
        h = s.get("kind")
        src = (
            "The owner's own PR. The own-PR lane found every check green and held it only on the policy rules below, which "
            "reserve the change for the owner's sign-off."
            if h == "policy"
            else "The owner's own PR. The own-PR lane gave up on it and needs the owner's direction."
        )
    else:
        have = s.get("sources") or []
        bits = ["The PR review lane escalated an engineer PR to me."]
        if "tfplan" in have:
            bits.append("The plan gate also holds its plan runs for the owner's approval.")
        src = " ".join(bits)
    rows.append({"label": "Real source", "value": src})
    return rows


def _ask(s, land):
    sha = (s.get("head") or "")[:8]
    pr = s.get("pr")
    what = f"Merge PR #{pr} into main at {sha}"
    if s["lane"] == "mine":
        what += " as a rebase merge with the owner's admin bypass"
    else:
        what += " by approving it as me, which queues a rebase auto-merge pinned to that commit"
    runs = ""
    if s["lane"] == "mine":
        runs = " and approve its plan runs on this head"
    elif "tfplan" in (s.get("sources") or []):
        runs = " and approve its held plan runs"
    n = len(land.get("roots") or [])
    landed = (
        f" The merge then applies {_n(n, 'root')} ({_join([r['root'] + ' ' + r['tier'] for r in land['roots']])})."
        if n
        else " The merge applies no Terraform root."
        if land.get("status") == "ok"
        else ""
    )
    return _sentence(what + runs) + landed


def _risks(s, land):
    out = []
    st = land.get("status")
    if st == "unknown":
        out.append(
            "it could not read the PR file list, so which roots the merge applies is not known."
        )
    for r in land.get("roots") or []:
        if (r.get("destroy") or 0) > 0:
            names = _join(r.get("destroys_named") or [])
            out.append(
                f"{r['root']} ({r['tier']}) destroys {_n(r['destroy'], 'resource')}"
                + (f" ({names})" if names else "")
                + f". Gate: {r['gate']}."
            )
        if (r.get("entra") or 0) > 0:
            out.append(
                f"{r['root']} ({r['tier']}) changes {_n(r['entra'], 'identity object')}. Gate: {r['gate']}."
            )
        elif (r.get("grants") or 0) > 0:
            out.append(f"{r['root']} ({r['tier']}) changes {_n(r['grants'], 'access grant')}.")
    for r in land.get("not_applied") or []:
        if (r.get("destroy") or 0) > 0:
            out.append(
                f"{r['root']} ({r['tier']}) shows {_n(r['destroy'], 'destroy')} in the plan, but this merge does not apply it."
            )
    if s["lane"] == "need":
        risk = (s.get("breakdown") or {}).get("risk") or {}
        if risk.get("level"):
            out.append(
                f"The review rates the risk {_txt(risk['level'])}. {_sentence(risk.get('why'))}"
            )
    c = s.get("counts") or {}
    if s["lane"] == "mine" and (c.get("blocking") or 0) > 0:
        out.append(
            f"The automated review still lists {_n(c['blocking'], 'blocking finding')}. "
            "Approving merges past them, you triaged them on this head."
        )
    return [_txt(x) for x in out]


def _why_you(s, land, rows):
    rules = [r for r in rows if r["kind"] == "rule"]
    finds = [r for r in rows if r["kind"] == "finding"]
    parts = []
    if rules:
        ids = sorted({r["id"] or r["label"] for r in rules})
        parts.append(
            f"The policy reserves this change for my sign-off. {_n(len(rules), 'rule match')} across "
            f"{_n(len(ids), 'rule')} hold it, listed below with where each matched."
            if s["lane"] == "mine"
            else f"The PR review escalated it to me on {_n(len(rules), 'rule')}, listed below."
        )
    if finds:
        parts.append(
            f"{_n(len(finds), 'finding')} from the automated review {'is' if len(finds) == 1 else 'are'} listed with severity and location."
        )
    if not parts:
        parts.append(
            "No rule or finding is recorded for this head, so the card has no stated reason to wait on me."
        )
    return " ".join(parts)


def _click(s, land, confirm):
    sha = (s.get("head") or "")[:8]
    if s["lane"] == "mine":
        bits = [
            f"Approve and merge re-checks the PR live and refuses if the head moved from {sha}. It then records my sign-off, "
            "approves the PR's plan runs on this head and merges the commit as a rebase merge with the owner's admin bypass."
        ]
        if confirm:
            bits.append(
                f"Because the roots that land delete something or change identity objects, the button stays off until I type {confirm['name']}. "
                "That also covers the post-merge apply of the same plan."
            )
    else:
        bits = [
            f"Approve as me posts an approving review as me on {sha} and queues a rebase auto-merge pinned to that commit.",
        ]
        if "tfplan" in (s.get("sources") or []):
            bits.append("It also approves the held plan runs for this PR.")
        bits.append(
            "Request changes posts a changes-requested review and rejects any held plan runs."
        )
        if confirm:
            bits.append(
                f"Typing {confirm['name']} first also covers the post-merge apply of the same plan. Left blank, the privileged card asks me again."
            )
    return _txt(" ".join(bits))


def structure(s, land):
    """The deterministic card fields for one PR subject (see approval_brief.subject)."""
    rows = _why_rows(s)
    need = s.get("confirm_name_needed")
    confirm = None
    if need and needs_confirm(land):
        why = []
        if any((r.get("destroy") or 0) > 0 for r in land.get("roots") or []):
            why.append("the roots that land delete resources")
        if any((r.get("entra") or 0) > 0 for r in land.get("roots") or []):
            why.append("the roots that land change identity objects")
        if land.get("status") == "unknown":
            why.append("it could not read the PR file list")
        confirm = {
            "name": need,
            "why": _sentence("Type the name because " + _join(why)),
            "required": s["lane"] == "mine",
        }
    return {
        "kind": kind_of(s["lane"]),
        "ask": _ask(s, land),
        "asked_by": _asked_by(s),
        "landing": land,
        "why_rows": rows,
        "why_you": _why_you(s, land, rows),
        "risks": _risks(s, land),
        "click": _click(s, land, confirm),
        **({"confirm": confirm} if confirm else {}),
    }


def check_prose(land, brief):
    """A model brief may not say a root this merge does not apply is applied by it. Returns a reason
    string or None."""
    names = [r["root"] for r in land.get("not_applied") or []]
    if not names:
        return None
    for k in ("does", "approving", "review"):
        for sent in re.split(r"(?<=[.!?])\s+", brief.get(k) or ""):
            low = sent.lower()
            if "appl" not in low and "after the merge" not in low:
                continue
            named = any(
                re.search(r"(?<![a-z0-9-])" + re.escape(n.lower()) + r"(?![a-z0-9-])", low)
                for n in names
            )
            if named and not re.search(
                r"\bnot\b|n't|\bno\b|\bnever\b|\bwithout\b|\bplan only\b|\bnor\b", low
            ):
                return f"{k} says a root this merge does not apply is applied: {sent[:120]}"
    return None
