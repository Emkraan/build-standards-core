"""The route table: which module function answers which path. build() returns a Registry holding the routes of every module that is
present; a module that is not in the tree (its slot is off) simply adds no routes, and its page hides itself.

Each entry is (method, path, module, function, adapter). The adapter turns a Request into the call (default: no arguments for a GET, the
payload for a POST). The shapes are the ones the app already reads (plain JSON objects). Writes are POST only and go through the gate's
Origin check. Routes that start an agent session (tackle, discuss, the review approve and decide routes of the review lanes) are not here:
they need the runtime slot (DESIGN.md 12.21).
"""

import importlib
import json
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
    acc = load("model_accounts")
    if acc is not None and hasattr(acc, "sample"):
        r.background.append((acc.sample, 600))
    return r


if __name__ == "__main__":
    print(json.dumps(sorted(f"{m} {p}" for m, p in build().paths()), indent=1))
