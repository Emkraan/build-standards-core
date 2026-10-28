"""
reviews_visibility.py
Purpose: Prove that every open item behind the ops center Reviews pages (the primary and secondary lane) sits in a tab with an
         action, and that the card agrees with the lane that owns it (opscenter/DESIGN.md section 12.3, item 24).
         Each run reads the live Reviews bundles from the ops center and the lane truths (own-PR lane state and live check,
         open PRs and waiting deployments on the code host, owner roots status) and raises one board item per finding:
           contradiction  the lane says a PR needs the owner but the card is not on Needs me, or the card says waiting while
                          the lane holds it (high)
           invisible      an open item that appears in no tab (high when it waits on the owner, medium for an engineer PR)
           stuck          an item in flight or waiting longer than its lane allows (medium)
         Items are keyed per finding (object plus version), updated in place, and closed when the condition clears.
Usage:   reviews_visibility.py [--dry-run] [--json]
Exit:    0 normally (items carry the findings), 2 when the ops center bundle cannot be read (a "cannot read the ops center" item
         is raised after 3 failures in a row).
Lane parameters (environment RV_LANES, a JSON object, or local/params.json `reviews_visibility.lanes`):
           {"primary":   {"repo": "owner/name", "own_state": "<path of the lane's own-pr-merge.json>"},
            "secondary": {"repo": "owner/name", "own_state": "<path>"}}
         The primary lane also carries the privileged plans, owner roots and runbook releases; the secondary lane is a plain
         pull request lane. A consumer with one lane leaves `secondary` out and its checks are skipped.
Env:     RV_BASE (the ops center base URL, default http://127.0.0.1:8766), RV_STATE, RV_LOCK, RV_GH_BIN, RV_LANES,
         RV_SELF_LOGIN (the owner's login), RV_OWNER (board item owner), RV_OWN_CHECK (the lane's live check command with {pr} and {lane}),
         RV_OWNER_STATUS, RV_REFRESH (a command that refreshes the ops center data, optional), RV_NO_REFRESH=1, RV_NOW (epoch,
         tests), OPSCENTER_ROOT (item store).
Notes:   Read only on the code host and the ops center. Writes only its own state file and the automation board store.
         System python3 is 3.9, stdlib only.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

AGENT_HOME = Path(os.environ.get("OPSCENTER_AGENT_HOME") or Path.home() / ".opscenter" / "agent")
BASE = os.environ.get("RV_BASE", "http://127.0.0.1:8766")
STATE = Path(os.environ.get("RV_STATE", str(AGENT_HOME / "cache/reviews-visibility/state.json")))
LOCK = Path(os.environ.get("RV_LOCK", str(STATE.parent / "check.lock")))
GH = os.environ.get("RV_GH_BIN") or shutil.which("gh") or "gh"
APP = Path(
    os.environ.get("RV_APP", str(Path(__file__).resolve().parent.parent / "server" / "modules"))
)  # automation_actions


def _lanes():
    raw = os.environ.get("RV_LANES")
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


LANES = _lanes()
OWN = {
    k: Path(v["own_state"]) for k, v in LANES.items() if isinstance(v, dict) and v.get("own_state")
}
REPOS = {k: v["repo"] for k, v in LANES.items() if isinstance(v, dict) and v.get("repo")}
OWN_CHECK = os.environ.get("RV_OWN_CHECK", "")
OWNER_STATUS = Path(
    os.environ.get("RV_OWNER_STATUS", str(AGENT_HOME / "cache/owner-roots/status.json"))
)
REFRESH_CMD = os.environ.get("RV_REFRESH", "")
SELF = os.environ.get("RV_SELF_LOGIN", "owner-login")
SKIP_AUTHORS = re.compile(r"(\[bot\]$|^dependabot|^renovate|^github-actions|^copilot)", re.I)
SOURCE = "Reviews visibility check"
OWNER = os.environ.get("RV_OWNER", "owner")
ITEM_PREFIX = "reviews-vis-"
ITEM_BLOCKED = "reviews-vis-cannot-read"
ITEM_GH_BLOCKED = "reviews-vis-cannot-read-github"
BLOCK_AFTER = 3
NEVER_SIGNOFF = {"plan-destroy", "plan-replace"}

# Thresholds in seconds.
PRIV_ASSESS_S = 20 * 60  # privileged assessment not written
PLAN_SOURCE_S = 10 * 60  # privileged plan never parsed
FLIGHT_S = 20 * 60  # engineer escalation or privileged item in flight
MY_WAIT_S = 30 * 60  # the owner's PR "waiting" with nothing running
RECHECK_S = 10 * 60  # the owner's PR card stuck on "Re-checking this head"
OWNER_FLIGHT_S = 30 * 60  # Owner root planning, applying or re-planning
RELEASE_S = 60 * 60  # runbook release waiting or releasing
DEPLOY_S = 6 * 60  # a waiting deployment the gate has had three passes to place
MY_NEW_S = 20 * 60  # a new PR of mine the The owner's PRs list has not picked up
ENG_NEW_S = 15 * 60  # a new engineer PR the review lane has not picked up


class ReadError(Exception):
    pass


# --------------------------------------------------------------------------- helpers
def now():
    return float(os.environ.get("RV_NOW") or time.time())


def epoch(s):
    if s is None or s == "":
        return 0.0
    if isinstance(s, (int, float)):
        return float(s)
    try:
        return (
            dt.datetime.strptime(str(s)[:19], "%Y-%m-%dT%H:%M:%S")
            .replace(tzinfo=dt.timezone.utc)
            .timestamp()
        )
    except ValueError:
        return 0.0


def mins(sec):
    m = int(sec // 60)
    if m < 120:
        return "%d minutes" % m  # noqa: UP031
    return "%.1f hours" % (m / 60.0)


def _run(args, timeout=120):
    """The one subprocess helper. Returns stdout, raises ReadError on any failure."""
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ReadError(f"{Path(args[0]).name}: {e}") from None
    if p.returncode != 0:
        raise ReadError(
            "{} {}: {}".format(
                Path(args[0]).name, " ".join(args[1:3]), (p.stderr or p.stdout).strip()[:200]
            )
        )
    return p.stdout


def gh_json(args, timeout=120):
    out = _run([GH] + args, timeout)
    try:
        return json.loads(out or "null")
    except ValueError as e:
        raise ReadError("gh {}: bad json ({})".format(" ".join(args[:2]), e)) from None


def fetch(path, timeout=120):
    try:
        with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
            data = json.loads(r.read())
    except Exception as e:  # noqa: BLE001 - any failure is a failed read, reported by the caller
        raise ReadError(f"GET {path}: {str(e)[:200]}") from None
    if not isinstance(data, dict):
        raise ReadError(f"GET {path}: not a JSON object")
    return data


def load_json(p, default):
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return default


def load_state():
    s = load_json(STATE, {})
    for k, v in (("seen", {}), ("raised", {}), ("fails", 0), ("gh_fails", 0)):
        s.setdefault(k, v)
    return s


def save_state(s):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        f.write(json.dumps(s, indent=2, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(str(tmp), str(STATE))


def actions():
    sys.path.insert(0, str(APP))
    import automation_actions  # noqa: E402

    return automation_actions


def item_id(key):
    return ITEM_PREFIX + hashlib.sha1(key.encode()).hexdigest()[:12]


def pr_link(repo, n):
    return {"label": f"PR #{n}", "url": f"https://github.com/{REPOS[repo]}/pull/{n}"}


def page_link(repo):
    return {"label": f"{repo.capitalize()} reviews", "url": f"{BASE}/#/reviews/{repo}"}


# --------------------------------------------------------------------------- lane truth
def lane_rec(repo, n, head):
    st = load_json(OWN[repo], {})
    rec = (st.get("prs") or {}).get(str(n)) or {}
    fix = (st.get("fix") or {}).get(str(n)) or {}
    g = fix.get("gave_up") or {}
    gave_up = bool(g and g.get("head") == head and not g.get("waits_on"))
    return {
        "status": rec.get("status") if rec.get("head") == head else None,
        "reason": rec.get("reason", "") if rec.get("head") == head else "",
        "gave_up": gave_up,
        "gave_up_why": g.get("why", "") if gave_up else "",
        "updated": st.get("updated"),
    }


def signoff(repo, n, head):
    rec = (load_json(OWN[repo].parent / "own-pr-signoffs.json", {}).get("prs") or {}).get(
        str(n)
    ) or {}
    return rec if rec.get("head") == head and rec.get("at") else None


def needs_rules(reason):
    if not reason.startswith("needs me:"):
        return set()
    return {r.strip() for r in reason.split(":", 1)[1].split(",") if r.strip()}


def lane_needs_me(repo, n, head, lane):
    """(True, why) when the lane says this head waits on me and nothing the owner already chose covers it."""
    rules = needs_rules(lane["reason"]) if lane["status"] == "held" else set()
    if lane["gave_up"]:
        return True, "auto-fix gave up on it (%s)" % (lane["gave_up_why"] or "no reason recorded")
    if not rules:
        return False, ""
    so = signoff(repo, n, head)
    if so and not rules & NEVER_SIGNOFF and rules <= set(so.get("rules") or []):
        return False, ""  # every rule signed off for this head, the lane merges it next pass
    return True, "the own-PR lane holds it for the owner's sign-off ({})".format(lane["reason"])


def live_lane(repo, n):
    """The lane's live verdict for one PR (a read only check): the RV_OWN_CHECK command with {pr} and {lane} filled in, which
    prints the lane's JSON verdict. None when no command is set or it cannot run."""
    if not OWN_CHECK:
        return None
    try:
        return json.loads(_run(shlex.split(OWN_CHECK.format(pr=n, lane=repo)), timeout=300))
    except (ReadError, ValueError):
        return None


# --------------------------------------------------------------------------- findings
class Findings:
    def __init__(self, state, t):
        self.items = {}
        self.state = state
        self.t = t
        self.seen_now = set()

    def add(self, key, kind, priority, title, why, action, links=None, refs=None):
        self.items[key] = {
            "key": key,
            "kind": kind,
            "priority": priority,
            "title": title,
            "why": why,
            "action": action,
            "links": links or [],
            "refs": refs or [],
        }

    def age(self, key, since=None):
        """Seconds this condition has held. Uses the item's own timestamp when it has one,
        else the first run that saw it."""
        self.seen_now.add(key)
        first = self.state["seen"].setdefault(key, self.t)
        start = epoch(since) if since else 0.0
        return self.t - (start or first)


def check_primary(b, f, gh_ok, open_prs, t):
    mine = b.get("my_prs") or []
    acted = {a.get("pr") for a in b.get("acted") or []}
    cards = {m.get("pr"): m for m in mine}
    # (b) invisible: an open PR of mine that the The owner's PRs list does not carry.
    if gh_ok:
        refreshed = float(b.get("my_prs_refreshed") or 0)
        for p in open_prs:
            if (
                (p.get("author") or {}).get("login") != SELF
                or p["number"] in cards
                or p["number"] in acted
            ):
                continue
            created = epoch(p.get("createdAt"))
            if not (created and refreshed > created + 60) and t - created < MY_NEW_S:
                continue  # the list was built before this PR existed, the next refresh carries it
            err = b.get("my_prs_error")
            f.add(
                "invisible:platform:mine:{}".format(p["number"]),
                "invisible",
                "high",
                "platform PR #{} of mine is on no Reviews tab".format(p["number"]),
                "The owner's open platform PR #{} ({}) is not on The owner's PRs or Needs me. {}"
                "Anything the lane holds for me on it, a sign-off or a fix decision, cannot reach me from the ops center.".format(
                    p["number"],
                    p.get("title", ""),
                    (f"The The owner's PRs list failed to load: {err}. ") if err else "",
                ),
                "Run platform_own_pr_merge.py check {} to see what the lane decided, then find why the The owner's PRs list "
                "dropped it (platform_reviews.my_prs).".format(p["number"]),
                [pr_link("primary", p["number"]), page_link("primary")],
            )
    open_nums = {p["number"] for p in open_prs} if gh_ok else None
    for m in mine:
        n, head, hold = m.get("pr"), m.get("head_sha") or "", m.get("hold") or {}
        if open_nums is not None and n not in open_nums:
            continue  # merged or closed since the list was built
        kind = hold.get("kind")
        lane = lane_rec("primary", n, head)
        summary = hold.get("summary") or ""
        recheck = summary.startswith("Re-checking this head")
        # (a) contradiction
        need, need_why = lane_needs_me("primary", n, head, lane)
        so = signoff("primary", n, head)
        af = hold.get("autofix") or {}
        held_problem = lane["status"] == "held" and not need
        bad = None
        if need and kind not in ("policy", "direction") and not recheck:
            bad = f'says {need_why}, but its card on The owner\'s PRs says "{summary[:160]}" (kind {kind}), so it is not on Needs me'
        elif (
            held_problem
            and kind == "waiting"
            and not recheck
            and af.get("state") != "waiting_on"
            and not so
        ):
            bad = 'holds it ({}), but its card on The owner\'s PRs says "{}", as if the lane were still working'.format(
                lane["reason"],
                summary[:160],
            )
        if bad:
            live = live_lane("primary", n)
            if live and live.get("head") == head and live.get("status") != "held":
                bad = (
                    None  # the live check no longer holds this head, the card catches up on refresh
                )
        if bad:
            f.add(
                f"contradiction:platform:{n}@{head[:12]}",
                "contradiction",
                "high",
                f"platform PR #{n} waits on me but the card says otherwise",
                f"The own-PR lane {bad}. It sits on no actionable tab, so it would wait on me with nobody seeing it. "
                f"Head {head[:8]}.",
                f"Open the platform The owner's PRs tab and act on #{n} from the lane's reason (Approve and merge if the rules "
                "are fine). Then fix the card logic in platform_reviews._hold so this hold maps to Needs me.",
                [pr_link("primary", n), page_link("primary")],
            )
            continue
        # (c) stuck
        if recheck:
            key = f"stuck:platform:recheck:{n}@{head[:12]}"
            a = f.age(key)
            if a >= RECHECK_S:
                f.add(
                    key,
                    "stuck",
                    "medium",
                    f'platform PR #{n} has said "Re-checking" for {mins(a)}',
                    f'The card for the owner\'s PR #{n} has shown "Re-checking this head" for {mins(a)}. The live lane check for '
                    "this head is not finishing, so the card cannot show whether it needs me.",
                    f"Run platform_own_pr_merge.py check {n} and look at engine-check-fails.json for the failure.",
                    [pr_link("primary", n), page_link("primary")],
                )
        elif (
            kind == "waiting"
            and not m.get("pending")
            and not m.get("waiting")
            and not m.get("draft")
        ):
            key = f"stuck:platform:waiting:{n}@{head[:12]}"
            a = f.age(key)
            if a >= MY_WAIT_S:
                f.add(
                    key,
                    "stuck",
                    "medium",
                    f'platform PR #{n} has been "waiting" for {mins(a)} with nothing running',
                    'The owner\'s PR #{} has shown "{}" for {}, and no check is running on head {}. The lane says {}. '
                    "Something it waits on is not moving.".format(
                        n,
                        summary[:160],
                        mins(a),
                        head[:8],
                        lane["status"] or "nothing for this head",
                    ),
                    f"Run platform_own_pr_merge.py check {n} for the live reason and clear what it waits on.",
                    [pr_link("primary", n), page_link("primary")],
                )
    # Engineer PRs.
    eng_tabs = set()
    # PRs approved but held for the maintenance window sit on In progress
    # ("Waiting for the maintenance window"), so they are expected and visible.
    # cards whose PR waits on another PR sit on Needs me under "Waiting on another PR".
    for k in ("needs_me", "needs_in_flight", "needs_waiting", "in_progress", "held_for_window"):
        eng_tabs |= {x.get("pr") for x in b.get(k) or []}
    eng_tabs |= {x.get("pr") for x in b.get("shipped") or [] if x.get("status") == "approved"}
    if gh_ok:
        for p in open_prs:
            login = (p.get("author") or {}).get("login") or ""
            if (
                login == SELF
                or SKIP_AUTHORS.search(login)
                or (p.get("author") or {}).get("is_bot")
                or p.get("isDraft")
            ):
                continue
            if p["number"] in eng_tabs or p["number"] in acted:
                continue
            if t - epoch(p.get("createdAt")) < ENG_NEW_S:
                continue
            f.add(
                "invisible:platform:eng:{}".format(p["number"]),
                "invisible",
                "medium",
                "Engineer PR #{} by {} is on no platform Reviews tab".format(p["number"], login),
                "platform PR #{} ({}) by {} is open and ready for review but is not on Needs me, In progress or "
                "Recently shipped. The review lane has not queued it, so an escalation on it would never reach me.".format(
                    p["number"], p.get("title", ""), login
                ),
                "Check the review gate (platform_pr_review.py) health and its queue for #{}.".format(
                    p["number"]
                ),
                [pr_link("primary", p["number"]), page_link("primary")],
            )
    # a held PR still unmerged after a full window of its class passed (the card's
    # window.stale, computed with the same window module the lane uses).
    for h in b.get("held_for_window") or []:
        w = h.get("window") or {}
        if h.get("phase") != "held" or not w.get("stale"):
            continue
        f.add(
            "stuck:platform:held:{}@{}".format(h.get("pr"), (h.get("head_sha") or "")[:12]),
            "stuck",
            "medium",
            "platform PR #{} is still held after a full {} maintenance window".format(
                h.get("pr"), w.get("class_label") or ""
            ),
            "PR #{} ({}) by {} was approved and held for the {} maintenance window at {}. A full window opened and "
            "closed since then and it is still not merged. The last re-check inside the window said: {}.".format(
                h.get("pr"),
                h.get("title") or "",
                h.get("author") or "",
                w.get("class_label") or "",
                h.get("held_at") or "",
                (h.get("last_check") or "nothing (the gate never re-checked it)").replace(
                    chr(59), ","
                ),
            ),
            "Open Reviews > platform > In progress, read the card, and fix what blocks it or use Merge now (ECR override).",
            [pr_link("primary", h.get("pr")), page_link("primary")],
        )
    for n in b.get("needs_in_flight") or []:
        key = "stuck:platform:need-flight:{}@{}".format(
            n.get("key"), (n.get("head_sha") or "")[:12]
        )
        a = f.age(key)
        if a >= FLIGHT_S:
            f.add(
                key,
                "stuck",
                "medium",
                "platform review item {} has been in flight for {}".format(
                    n.get("pr") or n.get("key"), mins(a)
                ),
                'The Needs me item for {} has sat under "Working" for {} because {}. The lane should clear or '
                "re-queue it within one pass.".format(
                    ("PR #{}".format(n["pr"])) if n.get("pr") else n.get("key"),
                    mins(a),
                    n.get("blocked") or "it is in flight",
                ),
                "Check the review gate log and the run it names, then let the gate re-queue it.",
                [page_link("primary")] + ([pr_link("primary", n["pr"])] if n.get("pr") else []),
            )


def check_privileged(b, f, t):
    for p in b.get("privileged") or []:
        since = p.get("since")
        tag = "{} run {}".format(
            p.get("env_label") or p.get("environment") or "deployment", p.get("run_id")
        )
        link = (
            [{"label": "Run {}".format(p.get("run_id")), "url": p.get("run_url")}]
            if p.get("run_url")
            else []
        )
        if not p.get("plan_source"):
            key = "stuck:priv:plan:{}@{}".format(p.get("key"), p.get("run_attempt"))
            a = f.age(key, since)
            if a >= PLAN_SOURCE_S:
                f.add(
                    key,
                    "stuck",
                    "medium",
                    f"Privileged {tag}: no plan was read after {mins(a)}",
                    f"The privileged lane has had the {tag} for {mins(a)} and has no plan for it (plan_source is empty). The "
                    "assessment and the approval card depend on that plan, so the deployment waits with nothing for "
                    "me to judge. An outputs-only or unusual plan log is the usual cause.",
                    "Read the run's plan job log and fix the plan parser in the privileged lane so it reads this plan. "
                    "Decide the deployment in GitHub meanwhile if it is urgent.",
                    link + [page_link("primary")],
                )
        if p.get("phase") == "in_flight":
            blocked = p.get("blocked") or "it is in flight"
            assess = "assessment" in blocked
            key = "stuck:priv:flight:{}@{}".format(p.get("key"), p.get("run_attempt"))
            a = f.age(key, since)
            if a >= (PRIV_ASSESS_S if assess else FLIGHT_S):
                f.add(
                    key,
                    "stuck",
                    "medium",
                    f"Privileged {tag} has been in flight for {mins(a)}",
                    f'The {tag} has sat under "Working" on Needs me for {mins(a)} because {blocked}. Until that clears the card has '
                    "no buttons and the deployment waits on me with no way to act from the ops center.",
                    "Check the privileged lane (tf-review gate log, privileged-queue.json) for why the assessment "
                    "or the re-queue is not landing.",
                    link + [page_link("primary")],
                )


def check_deployments(b, f, runs, t):
    """Every waiting deployment the owner can approve must be on a tab."""
    placed = set()
    for p in b.get("privileged") or []:
        placed.add(str(p.get("run_id")))
    for k in ("needs_me", "needs_in_flight", "needs_waiting"):
        for n in b.get(k) or []:
            for r in (n.get("tfplan") or {}).get("run_ids") or []:
                placed.add(str(r))
    # runs of a superseded head are hidden on purpose (only the current head's runs show).
    for r in b.get("superseded_runs") or []:
        placed.add(str(r))
    for r in b.get("runbook_releases") or []:
        if (r.get("run") or {}).get("id"):
            placed.add(str(r["run"]["id"]))
        if r.get("plan_run_id"):
            placed.add(str(r["plan_run_id"]))
    # plan waits on the owner's own draft PR leave Needs me on purpose and show as the plan line on
    # its The owner's PRs row. Only terraform-plan, only when the row is a draft at the run's head and
    # actually carries that line. Privileged environments are never parked.
    parked_heads = {
        m.get("head_sha")
        for m in b.get("my_prs") or []
        if m.get("draft") and m.get("head_sha") and (m.get("hold") or {}).get("plan_line")
    }
    for run, pend in runs:
        mine = [d for d in pend if d.get("current_user_can_approve")]
        if not mine or str(run.get("id")) in placed:
            continue
        if run.get("head_sha") in parked_heads and all(
            (d.get("environment") or {}).get("name") == "terraform-plan" for d in mine
        ):
            continue
        envs = sorted({(d.get("environment") or {}).get("name", "?") for d in mine})
        started = min(
            [epoch(d.get("wait_timer_started_at")) for d in mine if d.get("wait_timer_started_at")]
            or [epoch(run.get("updated_at")) or epoch(run.get("created_at"))]
        )
        a = t - started
        if a < DEPLOY_S:
            continue
        f.add(
            "invisible:deploy:{}@{}".format(run.get("id"), run.get("run_attempt")),
            "invisible",
            "high",
            "GitHub run {} waits on the owner's approval but is on no Reviews tab".format(
                run.get("id")
            ),
            "The {} run {} on {} has waited on the owner's approval for {} (environment {}), and no platform Reviews card "
            "carries it. The gate should have placed it on Needs me within one pass.".format(
                run.get("name", "?"),
                run.get("id"),
                run.get("head_branch", "?"),
                mins(a),
                ", ".join(envs),
            ),
            "Open the run and decide it in GitHub, then check why the tf-review or privileged gate did not queue it.",
            [
                {"label": "Run {}".format(run.get("id")), "url": run.get("html_url") or ""},
                page_link("primary"),
            ],
        )


def check_owner_roots(b, f, status, t):
    view = {x.get("key"): x for x in ((b.get("owner_roots") or {}).get("items") or [])}
    for k, it in sorted((status.get("items") or {}).items()):
        st = it.get("state")
        v = view.get(k)
        if st in ("pending", "error", "auth"):
            shown = v and (
                v.get("phase") == "needs_me"
                or (
                    v.get("phase") == "in_flight"
                    and (
                        v.get("pending_since")
                        or v.get("main_moved")
                        or v.get("state") == "applying"
                    )
                )
            )
            if not shown:
                f.add(
                    "invisible:owner:{}@{}".format(
                        k, it.get("pending_since") or it.get("finished") or ""
                    ),
                    "invisible",
                    "high",
                    f"Owner root {k} needs me but is on no Reviews tab",
                    "The Owner roots status says {} is {}, which only the owner can act on, but the platform Needs me tab does "
                    "not show it (served phase {}). A pending Owner apply would wait with nobody seeing it.".format(
                        k, st, (v or {}).get("phase", "missing")
                    ),
                    "Open platform Needs me, then compare owner_roots.get() with agent-home/cache/owner-roots/status.json.",
                    [page_link("primary")],
                )
        if (v and v.get("phase") == "in_flight") or st in ("planning", "applying"):
            since = it.get("started") if st in ("planning", "applying") else None
            key = f"stuck:owner:{k}@{st}"
            a = f.age(key, since)
            if a >= OWNER_FLIGHT_S:
                f.add(
                    key,
                    "stuck",
                    "medium",
                    "Owner root {} has been {} for {}".format(
                        k, st if st in ("planning", "applying") else "in flight", mins(a)
                    ),
                    "The Owner root {} has been {} for {}. A plan or apply that long has hung or died, so its card "
                    "cannot reach Needs me.".format(
                        k,
                        "re-planning after main moved"
                        if st not in ("planning", "applying")
                        else st,
                        mins(a),
                    ),
                    "Read agent-home/cache/owner-roots/logs/{}.log and the owner_roots runner, then re-plan from the "
                    "Owner card.".format(k.replace(":", "-")),
                    [page_link("primary")],
                )


def check_releases(b, f, t):
    if b.get("runbook_releases_error"):
        f.add(
            "invisible:releases:error",
            "invisible",
            "high",
            "Runbook delete releases cannot be read",
            "The platform Reviews page could not read the runbook release lane ({}). A release waiting on the owner's sign-off "
            "would not show on Needs me.".format(str(b["runbook_releases_error"])[:200]),
            "Check runbook_releases.py and agent-home/cache/platform-pr-review/runbook-releases.json.",
            [page_link("primary")],
        )
    for r in b.get("runbook_releases") or []:
        st = r.get("state")
        if st not in ("waiting", "releasing", "unknown"):
            continue
        key = "stuck:release:{}@{}".format(r.get("pr"), st)
        a = f.age(key)
        if a >= (RELEASE_S if st != "unknown" else FLIGHT_S):
            f.add(
                key,
                "stuck",
                "medium",
                "Runbook release for PR #{} has been {} for {}".format(r.get("pr"), st, mins(a)),
                "The runbook delete release for PR #{} has been {} for {} ({}). It shows without an action, so "
                "nothing moves it forward on its own.".format(
                    r.get("pr"), st, mins(a), r.get("why") or "no reason"
                ),
                "Check the deploy-automation-runbooks runs on main for this PR.",
                [pr_link("primary", r.get("pr")), page_link("primary")],
            )


def check_secondary(b, f, gh_ok, open_prs, t):
    needs = {r.get("pr"): r for r in b.get("needs_me") or []}
    prog = {r.get("pr"): r for r in b.get("in_progress") or []}
    acted = {a.get("pr") for a in b.get("acted") or []}
    if gh_ok:
        for p in open_prs:
            n = p["number"]
            if n in needs or n in prog or n in acted:
                continue
            mine = (p.get("author") or {}).get("login") == SELF
            if t - epoch(p.get("createdAt")) < (MY_NEW_S if mine else ENG_NEW_S):
                continue
            err = b.get("lane_error")
            f.add(
                f"invisible:team:{n}",
                "invisible",
                "high" if mine else "medium",
                f"team PR #{n} is on no Reviews tab",
                "team PR #{} ({}) by {} is open but is not on Needs me or In progress on the team Reviews page.{} "
                "Anything it needs from me cannot reach me there.".format(
                    n,
                    p.get("title", ""),
                    (p.get("author") or {}).get("login", "?"),
                    (f" The page build failed: {str(err)[:200]}.") if err else "",
                ),
                f"Open the secondary Reviews page with ?refresh=1 and check its reviews builder for why #{n} was dropped.",
                [pr_link("secondary", n), page_link("secondary")],
            )
    open_nums = {p["number"] for p in open_prs} if gh_ok else None
    for n, r in prog.items():
        if not r.get("mine") or (open_nums is not None and n not in open_nums):
            continue
        head = r.get("head_sha") or ""
        lane = lane_rec("secondary", n, head)
        need, need_why = lane_needs_me("secondary", n, head, lane)
        pending = (r.get("checks") or {}).get("pending") or []
        if need and not pending and not r.get("working"):
            live = live_lane("secondary", n)
            if not (live and live.get("head") == head and live.get("status") != "held"):
                f.add(
                    f"contradiction:team:{n}@{head[:12]}",
                    "contradiction",
                    "high",
                    f"team PR #{n} waits on me but sits in In progress",
                    'The own-PR lane says {}, but the team Reviews page shows it under In progress ("{}"), so it '
                    "is not on Needs me. Head {}.".format(
                        need_why, (r.get("state") or "")[:160], head[:8]
                    ),
                    f"Act on #{n} from the lane's reason, then fix the secondary builder so this hold maps to Needs me.",
                    [pr_link("secondary", n), page_link("secondary")],
                )
                continue
        state = r.get("state") or ""
        if (
            not pending
            and not r.get("draft")
            and state.startswith(("the auto-merge lane checks", "everything passes", "you chose"))
        ):
            key = f"stuck:team:waiting:{n}@{head[:12]}"
            a = f.age(key)
            if a >= MY_WAIT_S:
                f.add(
                    key,
                    "stuck",
                    "medium",
                    f"team PR #{n} has been waiting for {mins(a)} with nothing running",
                    f'The owner\'s team PR #{n} has shown "{state[:160]}" for {mins(a)} and no check is running. The lane is not moving it.',
                    f"Run platform_own_pr_merge.py check {n} --target team for the live reason.",
                    [pr_link("secondary", n), page_link("secondary")],
                )


# --------------------------------------------------------------------------- run
def gather_github():
    """(ok, error, primary open PRs, secondary open PRs, waiting runs with pending deployments)."""
    fields = "number,title,author,isDraft,headRefOid,createdAt"
    try:
        primary_list = gh_json(
            [
                "pr",
                "list",
                "-R",
                REPOS["primary"],
                "--state",
                "open",
                "--limit",
                "100",
                "--json",
                fields,
            ]
        )
        secondary_list = gh_json(
            [
                "pr",
                "list",
                "-R",
                REPOS["secondary"],
                "--state",
                "open",
                "--limit",
                "100",
                "--json",
                fields,
            ]
        )
        w = (
            gh_json(
                ["api", "repos/{}/actions/runs?status=waiting&per_page=50".format(REPOS["primary"])]
            )
            or {}
        )
        runs = []
        for run in w.get("workflow_runs") or []:
            pend = (
                gh_json(
                    [
                        "api",
                        "repos/{}/actions/runs/{}/pending_deployments".format(
                            REPOS["primary"], run["id"]
                        ),
                    ]
                )
                or []
            )
            runs.append((run, pend))
        return True, None, primary_list or [], secondary_list or [], runs
    except ReadError as e:
        return False, str(e), [], [], []


def evaluate(state, t, primary, secondary, gh):
    f = Findings(state, t)
    gh_ok, _gh_err, primary_prs, secondary_prs, runs = gh
    status = load_json(OWNER_STATUS, {})
    check_primary(primary, f, gh_ok, primary_prs, t)
    check_privileged(primary, f, t)
    if gh_ok:
        check_deployments(primary, f, runs, t)
    check_owner_roots(primary, f, status, t)
    check_releases(primary, f, t)
    check_secondary(secondary, f, gh_ok, secondary_prs, t)
    return f


def sync_items(state, f, gh_ok, dry):
    """Raise or update one item per finding, close the ones that cleared. When GitHub could not
    be read, findings that depend on it are not judged, so their items stay as they are."""
    changed = False
    aa = None if dry else actions()
    current = f.items
    for key, it in sorted(current.items()):
        iid = item_id(key)
        sig = hashlib.sha1(
            json.dumps([it["priority"], it["title"], it["why"], it["action"]]).encode()
        ).hexdigest()
        prev = state["raised"].get(key)
        if prev and prev.get("sig") == sig:
            continue
        if dry:
            print("would raise {} [{}/{}] {}".format(iid, it["kind"], it["priority"], it["title"]))
            continue
        aa.raise_item(
            iid,
            it["title"],
            it["why"],
            it["action"],
            priority=it["priority"],
            owner=OWNER,
            refs=it.get("refs"),
            links=[x for x in it["links"] if x.get("url")],
            source=SOURCE,
        )
        state["raised"][key] = {"id": iid, "sig": sig, "kind": it["kind"], "at": f.t}
        changed = True
    gh_dependent = ("invisible:platform:", "invisible:team:", "invisible:deploy:", "contradiction:")
    for key in list(state["raised"]):
        if key in current:
            continue
        if not gh_ok and key.startswith(gh_dependent):
            continue
        if dry:
            print("would close {} ({})".format(state["raised"][key]["id"], key))
            continue
        aa.close_item(
            state["raised"][key]["id"],
            "The Reviews visibility check no longer finds this condition.",
        )
        del state["raised"][key]
        changed = True
    # Forget first-seen times of conditions that cleared.
    state["seen"] = {k: v for k, v in state["seen"].items() if k in f.seen_now}
    return changed


def refresh_board():
    """Refresh the ops center data after a change, through the optional RV_REFRESH command."""
    if os.environ.get("RV_NO_REFRESH") or not REFRESH_CMD:
        return
    try:
        _run(shlex.split(REFRESH_CMD), timeout=300)
    except ReadError as e:
        print(f"reviews visibility: board refresh failed: {e}")


def run(dry=False, as_json=False):
    t = now()
    state = load_state()
    try:
        primary = fetch(os.environ.get("RV_PRIMARY_PATH", "/api/platform-reviews"))
        secondary = fetch(os.environ.get("RV_SECONDARY_PATH", "/api/team_prefix-reviews"))
    except ReadError as e:
        state["fails"] = int(state.get("fails", 0)) + 1
        state["last_error"] = str(e)
        print(
            "reviews visibility: cannot read the ops center (%d in a row): %s" % (state["fails"], e)  # noqa: UP031
        )
        if not dry:
            if state["fails"] >= BLOCK_AFTER:
                actions().raise_item(
                    ITEM_BLOCKED,
                    "Reviews visibility check cannot read the ops center",
                    "The Reviews visibility check has failed to read the ops center Reviews data %d times in a row "  # noqa: UP031
                    "(%s). Until it can, nothing checks that the owner's PRs, engineer PRs, privileged runs and Owner roots "
                    "reach a tab the owner can act on." % (state["fails"], str(e)[:200]),
                    f"Check that the ops center server is running and answers {BASE}/api/platform-reviews.",
                    priority="high",
                    owner=OWNER,
                    source=SOURCE,
                )
                refresh_board()
            save_state(state)
        return 2
    if not dry and state.get("fails", 0) >= BLOCK_AFTER:
        actions().close_item(
            ITEM_BLOCKED, "The Reviews visibility check can read the ops center again."
        )
    state["fails"] = 0
    gh = gather_github()
    gh_ok = gh[0]
    if gh_ok:
        if not dry and state.get("gh_fails", 0) >= BLOCK_AFTER:
            actions().close_item(
                ITEM_GH_BLOCKED, "The Reviews visibility check can read GitHub again."
            )
        state["gh_fails"] = 0
    else:
        state["gh_fails"] = int(state.get("gh_fails", 0)) + 1
        print(
            "reviews visibility: GitHub read failed (%d in a row): %s" % (state["gh_fails"], gh[1])  # noqa: UP031
        )
        if not dry and state["gh_fails"] >= BLOCK_AFTER:
            actions().raise_item(
                ITEM_GH_BLOCKED,
                "Reviews visibility check cannot read GitHub",
                "The Reviews visibility check has failed to read GitHub %d times in a row (%s). Open PRs and waiting "  # noqa: UP031
                "deployments are not being checked against the Reviews tabs."
                % (state["gh_fails"], str(gh[1])[:200]),
                "Check the code host CLI's sign in (gh auth status) on this host.",
                priority="medium",
                owner=OWNER,
                source=SOURCE,
            )
    f = evaluate(state, t, primary, secondary, gh)
    changed = sync_items(state, f, gh_ok, dry)
    state["last_run"] = t
    state["last_findings"] = sorted(f.items)
    if as_json:
        print(json.dumps(list(f.items.values()), indent=2))
    elif f.items:
        for it in f.items.values():
            print("[REVIEWS VISIBILITY] {}: {}".format(it["kind"], it["title"]))
    if not dry:
        save_state(state)
        if changed:
            refresh_board()
    return 0


def main(argv):
    dry = "--dry-run" in argv
    as_json = "--json" in argv
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "w") as lk:
        try:
            fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("reviews visibility: another run holds the lock, skipping")
            return 0
        return run(dry, as_json)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
