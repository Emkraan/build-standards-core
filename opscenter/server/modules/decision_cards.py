"""
decision_cards.py
Purpose: Decision cards for the own pull request lane, shared by every review lane's page. When an
         auto-fix session on one of the owner's pull requests stops on a decision only the owner can
         make, it leaves a question, two to four options and a recommendation in the own-PR lane
         state. The owner's click on one option is the sign-off for that head only:
           fix      -> own-pr-directions.json, the fixer starts a directed-fix session
           override -> applies the override label as the owner, posts the prepared triage reply with
                       the head marker naming every high and blocking id of the review (the lane clears
                       only the ids a marker names), and records the owner's sign-off of that rule, plus
                       any other held rule the card names by id, in own-pr-signoffs.json (the lane
                       merges once the review check is green and nothing else holds it)
           hold     -> adds the do-not-merge label
         Both side files are written only here (atomic, 0600) and read by the lane scripts.
"""

import base64
import datetime as dt
import json
import os
import re
import threading
from pathlib import Path

DATA_PREFIX = "<!-- ai-review-data:v2 "
DATA_SUFFIX = " -->"
OVERRIDE_LABEL = "ai-review-override"
NEVER_SIGNOFF = {"plan-destroy", "plan-replace"}  # deletes go through Approve and merge
FORBIDDEN = re.compile(r"hermes|ops ?center|\bbot\b|\bAI\b|assistant|co-authored-by|claude", re.I)


class DecisionError(Exception):
    def __init__(self, msg, code=409):
        super().__init__(msg)
        self.code = code


def _now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def side_paths(lane_state_file):
    d = Path(lane_state_file).parent
    return d / "own-pr-directions.json", d / "own-pr-signoffs.json"


def write_side(path, n, rec):
    """Atomic upsert of one PR's record in a side file, mode 0600."""
    path = Path(path)
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        data = {}
    data.setdefault("prs", {})[str(n)] = rec
    data["updated"] = _now()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{threading.get_ident()}.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(json.dumps(data, indent=1))
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def review_verdict(gh, repo, pr):
    """The newest PR review verdict data blob ({head_sha, counts, ...}), or None."""
    out = gh(
        [
            "api",
            "--paginate",
            f"repos/{repo}/issues/{pr}/comments?per_page=100",
            "--jq",
            ".[] | @json",
        ],
        raw=True,
    )
    found = None
    for line in (out or "").splitlines():
        if not line.strip():
            continue
        body = json.loads(line).get("body") or ""
        if DATA_PREFIX in body:
            blob = body.split(DATA_PREFIX, 1)[1].split(DATA_SUFFIX, 1)[0]
            try:
                v = json.loads(base64.b64decode(blob).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(v, dict) and v.get("head_sha"):
                found = v
    return found


def review_head(gh, repo, pr):
    """head_sha of the newest PR review verdict comment, or None."""
    return (review_verdict(gh, repo, pr) or {}).get("head_sha")


def marker_ids(counts, extra=()):
    """Review table ids a full sign-off covers : H1..Hn then B1..Bn from the verdict
    counts, plus any extra ids (for example from the findings table), deduplicated in that order."""
    counts = counts or {}
    ids = [f"H{i}" for i in range(1, int(counts.get("high") or 0) + 1)]
    ids += [f"B{i}" for i in range(1, int(counts.get("blocking") or 0) + 1)]
    for x in extra:
        x = str(x).upper()
        if re.fullmatch(r"[HB]\d+", x) and x not in ids:
            ids.append(x)
    return ids


def covered_rules(lane, pr, head, dec, opt):
    """The sign-off-able rules the owner's override click covers: ai-review-override itself plus every other rule the
    lane holds this head for that the card names (question, this option's effect or reply) by its exact id.
    The recorded sign-off covers exactly these, never more. Returns (covered, uncovered) where uncovered is
    every other held rule, which stays on Needs me."""
    rec = (lane.get("prs") or {}).get(str(pr)) or {}
    reason = rec.get("reason") or "" if rec.get("head") == head else ""
    held = (
        [r.strip() for r in reason[len("needs me: ") :].split(",") if r.strip()]
        if reason.startswith("needs me: ")
        else []
    )
    text = " ".join(
        [str(dec.get("question") or ""), str(opt.get("effect") or ""), str(opt.get("reply") or "")]
    )
    covered, rest = [OVERRIDE_LABEL], []
    for r in held:
        if r == OVERRIDE_LABEL or r in covered:
            continue
        named = re.search(r"(?<![A-Za-z0-9-])" + re.escape(r) + r"(?![A-Za-z0-9-])", text)
        if named and r not in NEVER_SIGNOFF:
            covered.append(r)
        else:
            rest.append(r)
    return covered, rest


def triage_marker(head, ids):
    """The hidden marker the own-PR lane reads: <!-- triage:<head> H1 B1 -->."""
    return f"<!-- triage:{head}{''.join(' ' + i for i in ids)} -->"


def decide(cfg, payload):
    """cfg: repo, self_login, lane_state (Path), gh(args, raw=False), verify_head(pr, head) -> live
    pull JSON (raises cfg['closed_exc'] when closed), log(rec), drop_cache(), review_verdict(pr) ->
    newest verdict blob ({head_sha, counts}) or None. Returns {pr, done, pending}. Raises DecisionError(msg, code)."""
    try:
        pr = int(payload.get("pr"))
    except (TypeError, ValueError):
        raise DecisionError("pr required", 400) from None
    head = payload.get("head_sha") or ""
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise DecisionError("head_sha required (40 hex)", 400)
    opt_id = str(payload.get("option") or "")
    try:
        live = cfg["verify_head"](pr, head)
    except cfg["closed_exc"] as e:
        cfg["drop_cache"]()
        return {
            "pr": pr,
            "done": [f"#{pr} is already {'merged' if getattr(e, 'merged', False) else 'closed'}"],
            "already": True,
        }
    if (live.get("user") or {}).get("login") != cfg["self_login"]:
        raise DecisionError(
            f"PR #{pr} is not the owner's. Other authors' PRs get direction through Discuss.", 403
        )
    try:
        lane = json.loads(Path(cfg["lane_state"]).read_text())
    except (OSError, ValueError):
        raise DecisionError(
            "Could not read the auto-merge lane state. Refresh in a minute.", 503
        ) from None
    g = ((lane.get("fix") or {}).get(str(pr)) or {}).get("gave_up") or {}
    dec = g.get("decision") if g.get("head") == head else None
    if not dec:
        raise DecisionError(f"PR #{pr} has no open decision for {head[:8]}. Refresh first.", 409)
    opt = next((o for o in dec.get("options") or [] if o.get("id") == opt_id), None)
    if not opt:
        raise DecisionError(f"Option {opt_id!r} is not on this card. Refresh first.", 409)
    directions, signoffs = side_paths(cfg["lane_state"])
    rec = {
        "head": head,
        "option_id": opt["id"],
        "action": opt["action"],
        "label": opt["label"],
        "effect": opt.get("effect") or "",
        "question": dec.get("question") or "",
        "at": _now(),
    }
    repo, gh, done = cfg["repo"], cfg["gh"], []
    if opt["action"] == "fix":
        write_side(directions, pr, rec)
        done.append(
            f'recorded "{opt["label"]}" for #{pr} at {head[:8]}, a fix session starts on the next lane pass'
        )
    elif opt["action"] == "hold":
        gh(
            [
                "api",
                "-X",
                "POST",
                f"repos/{repo}/issues/{pr}/labels",
                "-f",
                "labels[]=do-not-merge",
            ],
            raw=True,
        )
        done.append(f"added do-not-merge to #{pr}")
    elif opt["action"] == "override":
        reply = " ".join(str(opt.get("reply") or "").split())
        if (
            len(reply) < 20
            or FORBIDDEN.search(reply)
            or not reply.isascii()
            or ";" in reply
            or "triage:" in reply
        ):
            raise DecisionError(
                "The prepared reply is not safe to post as the owner. Use Discuss to word it.", 409
            )
        rv = cfg["review_verdict"](pr) or {}
        if rv.get("head_sha") != head:
            raise DecisionError(
                f"The PR review has not run on {head[:8]} yet. Wait for it, then decide.", 409
            )
        ids = marker_ids(rv.get("counts"), rv.get("finding_ids") or ())
        if not ids:
            raise DecisionError(
                f"The PR review on {head[:8]} has no high or blocking finding to override.", 409
            )
        gh(
            [
                "api",
                "-X",
                "POST",
                f"repos/{repo}/issues/{pr}/labels",
                "-f",
                f"labels[]={OVERRIDE_LABEL}",
            ],
            raw=True,
        )
        body = f"{reply}\n\n{triage_marker(head, ids)}"
        gh(
            ["api", "-X", "POST", f"repos/{repo}/issues/{pr}/comments", "-f", f"body={body}"],
            raw=True,
        )
        covered, rest = covered_rules(lane, pr, head, dec, opt)
        write_side(signoffs, pr, dict(rec, rules=covered))
        done.append(
            f"applied {OVERRIDE_LABEL} and posted the owner's triage reply on #{pr} at {head[:8]}"
        )
        if rest:
            done.append("still needs your sign-off for: " + ", ".join(rest) + " (on Needs me)")
        else:
            done.append(
                "the lane merges it once the review check is green and nothing else holds it"
            )
    else:
        raise DecisionError(f"Unknown action {opt['action']!r}", 409)
    cfg["log"](
        {
            "pr": pr,
            "decision": "decision_card",
            "sha": head,
            "by": cfg["self_login"],
            "option": opt["id"],
            "action": opt["action"],
            "label": opt["label"],
        }
    )
    cfg["drop_cache"]()
    return {"pr": pr, "done": done, "pending": True}
