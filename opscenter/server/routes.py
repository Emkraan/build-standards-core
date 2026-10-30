"""The route table: which module function answers which path. build() returns a Registry holding the routes of every module that is
present; a module that is not in the tree (its slot is off) simply adds no routes, and its page hides itself.

Each entry is (method, path, module, function, adapter). The adapter turns a Request into the call (default: no arguments for a GET, the
payload for a POST). The shapes are the ones the app already reads (plain JSON objects). Writes are POST only and go through the gate's
Origin check. Routes that start an agent session (tackle, discuss, the review approve and decide routes of the review lanes) are not here:
they need the runtime slot (DESIGN.md 12.21).
"""

import importlib
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OPS = HERE.parent
for sub in ("server/modules", "engine", "people", "tracker", "lanes", "server"):
    p = str(OPS / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import registry as reg  # noqa: E402
import stores  # noqa: E402


def _fresh(req):
    return req.arg("fresh") == "1"


def _payload(req):
    return req.payload()


def _link_state(link_health):
    return link_health.read_state()


def _search(mod):
    def h(req):
        return mod.search(req.arg("q"))

    return h


def _decorate_repos(data):
    cron = load("cron_pulse")
    return (
        cron.decorate_repos(data) if cron is not None and hasattr(cron, "decorate_repos") else data
    )


def _decorate_other(data):
    cron = load("cron_pulse")
    return (
        cron.decorate_secondary(data)
        if cron is not None and hasattr(cron, "decorate_secondary")
        else data
    )


def _priv_decide(act):
    def adapter(mod):
        def h(req):
            guard = getattr(load("platform_reviews"), "dep_guard", None)
            return mod.decide(req.payload(), act, guard=guard)

        return h

    return adapter


def _tackles():
    import runtime_slot as rt

    return rt.get()["sessions"]


def _doc_tackle(mod):
    import runtime_slot as rt

    def h(req):
        rt._need()
        p = req.payload()
        item = mod.tackle_item(str(p.get("id") or ""), os.environ.get("DOC_AUDIT_WIKI_URL", ""))
        fp = item["refs"][0]
        return dict(rt.start(fp, "doc", item["title"], item, str(p.get("context") or "")), fp=fp)

    return h


def _eng_tackle(mod):
    import runtime_slot as rt

    def h(req):
        rt._need()
        p = req.payload()
        row = mod.find(str(p.get("uid") or ""))
        item = mod.tackle_item(row)
        fp = f"eng-{row['uid']}"
        return dict(rt.start(fp, "debt", item["title"], item, str(p.get("context") or "")), fp=fp)

    return h


def _plan_move(fn, p):
    if not isinstance(p.get("path"), str):
        raise ValueError("path required")
    return fn(p["path"], p.get("version"), what_if=bool(p.get("what_if")))


def _key(p):
    if not isinstance(p.get("key"), str):
        raise ValueError("key required")
    return p["key"]


def _decorate(data, brief_fn, cron_fn):
    """The approval brief's and the cron pulse's additions to a page payload, each only when its module is present."""
    for mod, fn in (("approval_brief", brief_fn), ("cron_pulse", cron_fn)):
        m = load(mod)
        if m is not None and hasattr(m, fn):
            data = getattr(m, fn)(data)
    return data


def _decorate_platform(data):
    return _decorate(data, "decorate_plan", "decorate_primary")


# (method, path, module, function, adapter(module) -> handler(req) or None for the default)
def _table():
    G, P = "GET", "POST"
    return [
        (G, "/api/builds", "builds", "get", None),
        (G, "/api/browser-status", "browser_status", "get", None),
        (P, "/api/browser/hide", "browser_status", "hide", None),
        (G, "/api/alerts", "alerts", "get", None),
        (G, "/api/dark-launches", "dark_launches", "get", None),
        (
            P,
            "/api/dark-launches/dry-run",
            "dark_launches",
            "dry_run",
            lambda m: lambda r: m.dry_run(_payload(r)),
        ),
        (
            P,
            "/api/dark-launches/enable",
            "dark_launches",
            "enable",
            lambda m: lambda r: m.enable(_payload(r)),
        ),
        (
            P,
            "/api/dark-launches/disable",
            "dark_launches",
            "disable",
            lambda m: lambda r: m.disable(_payload(r)),
        ),
        (G, "/api/ac-routing", "routing_api", "get", None),
        (
            P,
            "/api/ac-routing/preview",
            "routing_api",
            "preview",
            lambda m: lambda r: m.preview(_payload(r)),
        ),
        (P, "/api/ac-routing/rule", "routing_api", "add", lambda m: lambda r: m.add(_payload(r))),
        (
            P,
            "/api/ac-routing/disable",
            "routing_api",
            "disable",
            lambda m: lambda r: m.disable(_payload(r)),
        ),
        (
            P,
            "/api/ac-routing/delete",
            "routing_api",
            "delete",
            lambda m: lambda r: m.delete(_payload(r)),
        ),
        (
            P,
            "/api/builds/dispatch",
            "builds",
            "dispatch",
            lambda m: lambda r: m.dispatch(_payload(r)),
        ),
        (
            P,
            "/api/builds/update-from-main",
            "builds",
            "update_from_main",
            lambda m: lambda r: m.update_from_main(_payload(r)),
        ),
        (G, "/api/links/health", "link_health", "read_state", lambda m: lambda r: m.read_state()),
        (
            P,
            "/api/links/check",
            "link_health",
            "run_check",
            lambda m: lambda r: (m.run_check(), m.read_state())[1],
        ),
        (
            P,
            "/api/links/edit",
            "link_health",
            "edit_link",
            lambda m: (
                lambda r: m.edit_link(
                    _payload(r).get("action"),
                    str(_payload(r).get("url") or ""),
                    _payload(r).get("new_url"),
                )
            ),
        ),
        (
            P,
            "/api/runbook-releases/release",
            "runbook_releases",
            "release",
            lambda m: lambda r: m.release(_payload(r)),
        ),
        (G, "/api/search", "ops_search", "search", lambda m: _search(m)),
        (G, "/api/cron-pulse", "cron_pulse", "pulse", lambda m: lambda r: m.pulse(fresh=_fresh(r))),
        (
            P,
            "/api/alerts/ack",
            "alerts",
            "ack",
            lambda m: (
                lambda r: (m.ack(_payload(r).get("ids"), _payload(r).get("act") or "ack"), m.get())[
                    1
                ]
            ),
        ),
        # work tracker (tracker/)
        (G, "/api/jira/sprint", "work", "sprint", lambda m: lambda r: m.sprint(_fresh(r))),
        (G, "/api/jira/backlog", "work", "backlog", lambda m: lambda r: m.backlog(_fresh(r))),
        (G, "/api/jira/approvals", "work", "approvals", lambda m: lambda r: m.approvals(_fresh(r))),
        (
            G,
            "/api/jira/transitions",
            "work",
            "transitions",
            lambda m: lambda r: m.transitions(r.arg("key")),
        ),
        (G, "/api/jira/needs-me", "needs_me", "items", lambda m: lambda r: m.items(_fresh(r))),
        (
            P,
            "/api/sprint-move",
            "work",
            "sprint_move",
            lambda m: lambda r: m.sprint_move(_payload(r).get("key")),
        ),
        (
            P,
            "/api/jira/sprint-remove",
            "work",
            "sprint_remove",
            lambda m: (
                lambda r: m.sprint_remove(_payload(r).get("key"), bool(_payload(r).get("what_if")))
            ),
        ),
        (
            P,
            "/api/jira/transition",
            "work",
            "transition",
            lambda m: (
                lambda r: m.transition(
                    _payload(r).get("key"), _payload(r).get("id"), bool(_payload(r).get("what_if"))
                )
            ),
        ),
        (
            P,
            "/api/jira/needs-me/decide",
            "needs_me",
            "decide",
            lambda m: (
                lambda r: m.decide(
                    _payload(r).get("key"),
                    _payload(r).get("decision"),
                    _payload(r).get("question") or "",
                    _payload(r).get("note") or "",
                    bool(_payload(r).get("what_if")),
                )
            ),
        ),
        # debt and improvements (server/modules/eng_backlog.py)
        (G, "/api/eng-backlog", "eng_backlog", "items", None),
        (
            P,
            "/api/eng-backlog/decide",
            "eng_backlog",
            "set_status",
            lambda m: (
                lambda r: m.set_status(
                    str(_payload(r).get("uid") or ""),
                    str(_payload(r).get("act") or ""),
                    str(_payload(r).get("note") or ""),
                )
            ),
        ),
        (
            P,
            "/api/eng-backlog/handle",
            "eng_backlog",
            "handle",
            lambda m: (
                lambda r: m.handle(
                    str(_payload(r).get("uid") or ""), str(_payload(r).get("act") or "")
                )
            ),
        ),
        (P, "/api/eng-backlog/tackle", "eng_backlog", "tackle_item", lambda m: _eng_tackle(m)),
        # runtime restart card (server/modules/runtime_restart.py; the path is the one the app calls)
        (G, "/api/hermes-restart", "runtime_restart", "get", None),
        (P, "/api/hermes-restart", "runtime_restart", "post", None),
        # the other repo's reviews (server/modules/other_reviews.py; the path is the one the app calls)
        (
            G,
            "/api/team_prefix-reviews",
            "other_reviews",
            "get",
            lambda m: lambda r: _decorate_other(m.get(force=_fresh(r))),
        ),
        (P, "/api/team_prefix-reviews/merge", "other_reviews", "merge", None),
        (P, "/api/team_prefix-reviews/approve", "other_reviews", "approve", None),
        (P, "/api/team_prefix-reviews/decide-fix", "other_reviews", "decide_fix", None),
        # plan reviews (server/modules/tf_reviews.py)
        (G, "/api/tf-reviews", "tf_reviews", "get", None),
        (
            P,
            "/api/tf-reviews/approve",
            "tf_reviews",
            "decide",
            lambda m: lambda r: m.decide(_payload(r).get("pr"), "approved"),
        ),
        (
            P,
            "/api/tf-reviews/reject",
            "tf_reviews",
            "decide",
            lambda m: lambda r: m.decide(_payload(r).get("pr"), "rejected"),
        ),
        # other repos (server/modules/repo_reviews.py)
        (
            G,
            "/api/repo-reviews",
            "repo_reviews",
            "get",
            lambda m: lambda r: _decorate_repos(m.get(force=_fresh(r))),
        ),
        (P, "/api/repo-reviews/rerun", "repo_reviews", "rerun", None),
        # privileged deployments (server/modules/privileged_reviews.py; the estate values are review_config.py)
        (G, "/api/privileged-reviews", "privileged_reviews", "get", None),
        (
            P,
            "/api/platform-reviews/deployment/approve",
            "privileged_reviews",
            "decide",
            _priv_decide("approve"),
        ),
        (
            P,
            "/api/platform-reviews/deployment/reject",
            "privileged_reviews",
            "decide",
            _priv_decide("reject"),
        ),
        (
            P,
            "/api/platform-reviews/deployment/retry",
            "privileged_reviews",
            "decide",
            _priv_decide("retry"),
        ),
        # approval briefs (server/modules/approval_brief.py; the model is the consumer's command)
        (P, "/api/reviews/brief", "approval_brief", "request", None),
        # plan reviews (server/modules/tf_reviews.py)
        (G, "/api/tf-reviews", "tf_reviews", "get", None),
        (
            P,
            "/api/tf-reviews/approve",
            "tf_reviews",
            "decide",
            lambda m: lambda r: m.decide(_payload(r).get("pr"), "approved"),
        ),
        (
            P,
            "/api/tf-reviews/reject",
            "tf_reviews",
            "decide",
            lambda m: lambda r: m.decide(_payload(r).get("pr"), "rejected"),
        ),
        # plans (server/modules/plans.py)
        (G, "/api/plans", "plans", "items", None),
        (G, "/api/plans/file", "plans", "read", lambda m: lambda r: m.read(r.arg("path"))),
        (
            P,
            "/api/plans/archive",
            "plans",
            "archive",
            lambda m: lambda r: _plan_move(m.archive, _payload(r)),
        ),
        (
            P,
            "/api/plans/restore",
            "plans",
            "restore",
            lambda m: lambda r: _plan_move(m.restore, _payload(r)),
        ),
        (
            P,
            "/api/plans/create",
            "plans",
            "create_tracker",
            lambda m: (
                lambda r: m.create_tracker(
                    _key(_payload(r)),
                    _payload(r).get("slug"),
                    _payload(r).get("title", ""),
                    what_if=bool(_payload(r).get("what_if")),
                )
            ),
        ),
        (
            P,
            "/api/plans/dismiss",
            "plans",
            "dismiss_untracked",
            lambda m: (
                lambda r: m.dismiss_untracked(
                    _key(_payload(r)), what_if=bool(_payload(r).get("what_if"))
                )
            ),
        ),
        # infrastructure (server/modules/infra.py; spend, cron, the VM and the log come from its provider)
        (G, "/api/infra/spend", "infra", "spend", None),
        (G, "/api/infra/cron", "infra", "cron", None),
        (G, "/api/infra/github", "infra", "github", None),
        (G, "/api/infra/runners", "infra", "runners", None),
        (G, "/api/infra/live-jobs", "infra", "live_jobs", None),
        (
            G,
            "/api/infra/job-log",
            "infra",
            "job_log",
            lambda m: lambda r: m.job_log(r.arg("runner"), r.arg("lines") or "60"),
        ),
        (G, "/api/infra/badge", "infra", "badge_problems", None),
        (G, "/api/infra/tasks", "infra", "tasks", None),
        (P, "/api/infra/backup/run", "infra", "task_run", None),
        (P, "/api/infra/tasks/run", "infra", "task_run", None),
        # owner-applied roots (server/modules/owner_roots.py; the cloud is its provider slot)
        (G, "/api/owner-roots", "owner_roots", "get", None),
        (
            P,
            "/api/owner-roots/plan",
            "owner_roots",
            "request",
            lambda m: lambda r: m.request(_payload(r), "plan"),
        ),
        (
            P,
            "/api/owner-roots/plan-all",
            "owner_roots",
            "request",
            lambda m: lambda r: m.request(_payload(r), "plan-all"),
        ),
        (
            P,
            "/api/owner-roots/apply",
            "owner_roots",
            "request",
            lambda m: lambda r: m.request(_payload(r), "apply"),
        ),
        (
            P,
            "/api/owner-roots/signin",
            "owner_roots",
            "request",
            lambda m: lambda r: m.request(_payload(r), "signin"),
        ),
        # sidebar badges (server/modules/badges.py)
        (G, "/api/badges", "badges", "get", None),
        # platform reviews (server/modules/platform_reviews.py; the estate values are the review config `platform` object)
        (
            G,
            "/api/platform-reviews",
            "platform_reviews",
            "get",
            lambda m: lambda r: _decorate_platform(m.get()),
        ),
        (
            P,
            "/api/platform-reviews/approve",
            "platform_reviews",
            "decide",
            lambda m: lambda r: m.decide(_payload(r), "approve"),
        ),
        (
            P,
            "/api/platform-reviews/request-changes",
            "platform_reviews",
            "decide",
            lambda m: lambda r: m.decide(_payload(r), "request-changes"),
        ),
        (P, "/api/platform-reviews/window-override", "platform_reviews", "window_override", None),
        (P, "/api/platform-reviews/resolve-thread", "platform_reviews", "resolve_thread", None),
        (P, "/api/platform-reviews/triage", "platform_reviews", "triage", None),
        (P, "/api/platform-reviews/decide-fix", "platform_reviews", "decide_fix", None),
        (
            P,
            "/api/platform-reviews/remove-hold-label",
            "platform_reviews",
            "remove_hold_label",
            None,
        ),
        (P, "/api/platform-reviews/accept-risk", "platform_reviews", "accept_risk", None),
        (P, "/api/platform-reviews/approve-merge", "platform_reviews", "approve_merge", None),
        (P, "/api/platform-reviews/release-deletes", "runbook_releases", "release", None),
        # documentation coverage (server/modules/doc_coverage.py; the audit is engine/doc_audit.py)
        (G, "/api/doc-coverage", "doc_coverage", "get", lambda m: lambda r: m.get(_tackles())),
        (
            P,
            "/api/doc-coverage/handle",
            "doc_coverage",
            "handle",
            lambda m: (
                lambda r: m.handle(
                    str(_payload(r).get("id") or ""), str(_payload(r).get("act") or "")
                )
            ),
        ),
        (P, "/api/doc-coverage/tackle", "doc_coverage", "tackle_item", lambda m: _doc_tackle(m)),
        # core consumption panel (server/modules/core_consumption.py)
        (
            G,
            "/api/core-consumption",
            "core_consumption",
            "get",
            lambda m: lambda r: m.get(fresh=_fresh(r)),
        ),
        (P, "/api/core-consumption/approve-pr", "core_consumption", "approve_pr", None),
        (P, "/api/core-consumption/approve-item", "core_consumption", "approve_item", None),
        # model accounts (server/modules/model_accounts.py, provider slot)
        (G, "/api/infra/accounts", "model_accounts", "get", None),
        (G, "/api/llm-fallback", "model_fallback", "get", None),
        (G, "/api/infra/fallback-order", "model_accounts", "order_get", None),
        (P, "/api/infra/fallback-order", "model_accounts", "order_set", None),
        # people slot (people/)
        (G, "/api/one-on-ones", "one_on_ones", "board", None),
        (
            G,
            "/api/one-on-ones/availability",
            "one_on_ones",
            "availability",
            lambda m: lambda r: m.availability(r.arg("person"), r.arg("minutes", "30")),
        ),
        (
            P,
            "/api/one-on-ones/schedule",
            "one_on_ones",
            "schedule",
            lambda m: lambda r: m.schedule(_payload(r)),
        ),
        (
            P,
            "/api/one-on-ones/status",
            "one_on_ones",
            "set_status",
            lambda m: (
                lambda r: m.set_status(
                    _payload(r).get("fp"), _payload(r).get("state"), _payload(r).get("note")
                )
            ),
        ),
        (P, "/api/one-on-ones/topic", "one_on_ones", "add_topic", lambda m: _topic(m)),
        (
            G,
            "/api/action-center/replied",
            "one_on_ones",
            "agenda_replied_items",
            lambda m: lambda r: {"replied": m.agenda_replied_items()},
        ),
        (
            P,
            "/api/action-center/replied/reopen",
            "one_on_ones",
            "reopen_replied",
            lambda m: (
                lambda r: (
                    m.reopen_replied(str(_payload(r).get("id") or "")),
                    {"replied": m.agenda_replied_items()},
                )[1]
            ),
        ),
        (G, "/api/yearly-reviews", "yearly_reviews", "get_all", None),
        (G, "/api/yearly-reviews/jobs", "yearly_reviews", "jobs", None),
        (
            G,
            "/api/yearly-reviews/evidence",
            "yearly_reviews",
            "evidence",
            lambda m: lambda r: m.evidence(r.arg("year"), r.arg("person")),
        ),
        (G, "/api/yearly-reviews/export", "yearly_reviews", "export_docx", lambda m: _export(m)),
        (
            P,
            "/api/yearly-reviews",
            "yearly_reviews",
            "upsert",
            lambda m: lambda r: {"review": m.upsert(_payload(r))},
        ),
        (
            P,
            "/api/yearly-reviews/draft",
            "yearly_reviews",
            "start_job",
            lambda m: lambda r: {"job": m.start_job(_payload(r))},
        ),
    ]


def _topic(m):
    def h(r):
        p = _payload(r)
        if p.get("remove"):
            return {"removed": m.remove_topic(p.get("fp"))}
        return {"fp": m.add_topic(p.get("person"), p.get("title", ""), p.get("detail", ""))}

    return h


def _export(m):
    def h(r):
        name, data = m.export_docx(r.arg("year"), r.arg("person"))
        disp = {"Content-Disposition": f'attachment; filename="{name}"'}
        return (
            200,
            data,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            disp,
        )

    return h


def load(name):
    """The module, or None when it is not in the tree."""
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


def _health(req):
    return {"ok": True}


def build(registry=None):
    r = registry or reg.Registry()
    r.get("/api/health", _health, "health")
    # the action handled store and the approvals inbox are the server's own writers
    r.get("/api/action-handled", lambda q: {"handled": stores.load_handled()}, "action-handled")

    def handled_post(q):
        return {"handled": stores.merge_handled(q.payload())}

    r.post("/api/action-handled", handled_post, "action-handled-write")

    def approve(q):
        decisions = q.payload().get("decisions")
        if not isinstance(decisions, list):
            raise ValueError("decisions must be a list")
        return {"queued": stores.queue_decisions(decisions)}

    r.post("/api/approve", approve, "approve")
    for method, path, mod, fn, adapter in _table():
        m = load(mod)
        if m is None or not hasattr(m, fn):
            continue
        if adapter is not None:
            handler = adapter(m)
        elif method == "GET":
            handler = (lambda f: lambda q: f())(getattr(m, fn))
        else:
            handler = (lambda f: lambda q: f(q.payload()))(getattr(m, fn))
        r.add(method, path, handler, name=f"{mod}.{fn}")
    cron = load("cron_pulse")
    if cron is not None and hasattr(cron, "run"):
        r.add(
            "POST",
            re.compile(r"/api/cron-pulse/([0-9a-f]{12})/run"),
            lambda q: cron.run(q.groups[0], q.payload().get("note")),
            name="cron_pulse.run",
        )
    import runtime_slot as rt

    r.get("/api/tackle", lambda q: rt.get(), name="runtime_slot.get")
    r.post("/api/tackle", lambda q: rt.post_tackle(q.payload()), name="runtime_slot.post_tackle")
    r.post(
        "/api/tackle/resolve",
        lambda q: rt.post_resolve(q.payload()),
        name="runtime_slot.post_resolve",
    )
    r.post("/api/jira/tackle", lambda q: rt.post_jira(q.payload()), name="runtime_slot.post_jira")
    r.post(
        "/api/pr/discuss", lambda q: rt.post_discuss(q.payload()), name="runtime_slot.post_discuss"
    )
    acc = load("model_accounts")
    if acc is not None and hasattr(acc, "sample"):
        r.background.append((acc.sample, 600))
    return r


if __name__ == "__main__":
    print(json.dumps(sorted(f"{m} {p}" for m, p in build().paths()), indent=1))
