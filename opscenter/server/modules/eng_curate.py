"""Debt and improvements curation: keep the TD/IMP backlog small and current on its own.

Date: 2026-11-06
Purpose: one front door for new entries and one scheduled pass that tidies the list, so new findings fold
into the work they belong to instead of piling up as new rows, and finished work leaves the open lists.

Front door (sessions and crons):
  backlog.py add --kind IMP --title "..." --text "..." [--goal G3] [--effort S] [--status suggested]
                 [--severity Medium] [--into IMP-313] [--new]
    Scores the finding against every open entry. A close match (or --into) is appended to that entry as a
    dated Update line. Otherwise a new entry is written with the next free id (ids are reserved under a
    lock, so two sessions never hand out the same id). --new forces a new entry.
  backlog.py similar --title "..." --text "..."   prints the closest open entries, writes nothing.
  backlog.py run [--dry-run]                       the scheduled curation pass.

Scheduled pass (auto actions are logged and undoable from the page, nothing is deleted):
  1. Auto-close an open entry whose own status already says SHIPPED, RESOLVED, DONE or done, unless the
     text says part of it is still open.
  2. Auto-fold an open entry into its clear best match (score at least SUGGEST_FOLD and FOLD_MARGIN times the
     runner-up) of the same kind and lane (Needs decision and To do together, Parked with Parked): into a
     workstream, else the newer entry into the older. No shared reference needed (every fold
     suggestion in the calibration run was right, the point is no sprawl). Undo on the page, Dismiss on a hint blocks it.
  3. Hints, one click each on the page: close because every cited PR merged,
     mentions a retired system, stale for 60 days, status word the page cannot read, duplicate open id.
"""

import argparse
import datetime as dt
import fcntl
import json
import math
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eng_backlog as eb  # noqa: E402

ROOT = eb.ROOT
CURATION = Path(
    os.environ.get("ENGBL_CURATION", ROOT / "state" / "dashboard" / "eng-curation.json")
)
ID_SCAN_DIRS = [ROOT / "state", ROOT / "engineering-state", ROOT / "references"]

# Scores are TF-IDF cosine plus a small bonus per shared hard reference. A short new finding against a
# long entry scores low in absolute terms, so a match needs a floor AND a clear lead over the runner-up.
SUGGEST_FOLD = 0.30  # a clear winner at this score folds on its own, a tie stays a one-click hint
UPDATE_MATCH = 0.22  # add: append to the matched entry instead of writing a new one
MARGIN = 1.8  # add: best must be this multiple of the runner-up (a wrong update is hard to spot)
FOLD_MARGIN = 1.4  # scheduled pass, same kind and lane only, undoable from the strip (10/30 calibration)  # best score must be at least this multiple of the runner-up
STALE_DAYS = 60
PR_CHECKS_PER_RUN = 40


def _json_env(name, default):
    try:
        d = json.loads(os.environ.get(name) or "null")
    except ValueError:
        return default
    return d if isinstance(d, type(default)) else default


# What the consumer retired: ENGBL_RETIRED_TERMS, a JSON {"term": "why it is retired"}; an open entry that still names one gets a hint.
RETIRED_TERMS = _json_env("ENGBL_RETIRED_TERMS", {})
# Extra reference patterns (ticket ids, repo aliases) the similarity score counts as hard references: ENGBL_REF_PATTERNS, a JSON list of regexes.
# Repo aliases for PR references in free text: ENGBL_PR_ALIASES, a JSON {"alias": "owner/repo"} read as "alias #N" or "alias PR #N".
PR_ALIASES = _json_env("ENGBL_PR_ALIASES", {})
OWNER = os.environ.get("ENGBL_OWNER", "")
STOP = set(
    [
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "into",
        "are",
        "was",
        "were",
        "not",
        "but",
        "all",
        "any",
        "its",
        "our",
        "their",
        "them",
        "they",
        "then",
        "than",
        "when",
        "what",
        "which",
        "who",
        "will",
        "would",
        "should",
        "could",
        "can",
        "has",
        "have",
        "had",
        "been",
        "being",
        "one",
        "two",
        "three",
        "per",
        "via",
        "out",
        "off",
        "only",
        "also",
        "each",
        "every",
        "more",
        "most",
        "less",
        "same",
        "new",
        "old",
        "use",
        "used",
        "uses",
        "using",
        "make",
        "makes",
        "made",
        "get",
        "gets",
        "got",
        "see",
        "there",
        "here",
        "after",
        "before",
        "over",
        "under",
        "about",
        "between",
        "still",
        "just",
        "like",
        "does",
        "done",
        "open",
        "status",
        "note",
        "imp",
        "td",
        "pierre",
        "suggested",
        "proposed",
        "approved",
    ]
)
TERMINAL_RE = re.compile(r"(?<![a-z] )\b(SHIPPED|RESOLVED|DONE|Done)\b[ .,:]")
PARTIAL_RE = re.compile(
    r"\b(part|half|leg|wave|phase|step)\s+(\d+\s+)?(resolved|shipped|done)\b|still open|open:|residual|remaining|"
    r"not yet|not built|follows|follow-up pr|waiting on|awaiting|pending|to do\b",
    re.I,
)
REF_RES = [
    *[re.compile(p) for p in _json_env("ENGBL_REF_PATTERNS", [])],
    re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b"),
    re.compile(r"\bPR #\d+\b"),
    re.compile(r"\b[\w.-]+\.(?:py|tsx?|ps1|json|ya?ml|sh|mjs)\b"),
    re.compile(r"\b[0-9a-f]{12}\b"),
    re.compile(r"\b(?:TD|IMP)-\d{3}\b"),
]


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _today():
    return _now().strftime("%Y-%m-%d")


# ---------------------------------------------------------------- state file


def load_state():
    try:
        s = json.loads(CURATION.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        s = {}
    for k, v in (("hints", {}), ("log", []), ("dismissed", {}), ("prs", {}), ("reserved", {})):
        s.setdefault(k, v)
    return s


def save_state(s):
    CURATION.parent.mkdir(parents=True, exist_ok=True)
    tmp = CURATION.with_name(CURATION.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(s, indent=1), encoding="utf-8")
    os.replace(tmp, CURATION)


def _locked(fn):
    lock = CURATION.with_name("." + CURATION.name + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        s = load_state()
        out = fn(s)
        save_state(s)
        return out


# ---------------------------------------------------------------- ids


def max_id_in_use(kind):
    pat = re.compile(rf"\b{kind}-(\d{{3}})\b")
    top = 0
    for d in ID_SCAN_DIRS:
        if not d.exists():
            continue
        for p in d.rglob("*.md"):
            if "archive" in p.parts:
                continue
            try:
                for m in pat.finditer(p.read_text(encoding="utf-8", errors="ignore")):
                    top = max(top, int(m.group(1)))
            except OSError:
                continue
    for p in (eb.TD_FILE, eb.IMP_FILE):
        try:
            for m in pat.finditer(p.read_text(encoding="utf-8")):
                top = max(top, int(m.group(1)))
        except OSError:
            pass
    return top


def reserve_id(kind):
    """Next free id, reserved under the curation lock so parallel sessions never collide."""

    def go(s):
        n = max(max_id_in_use(kind), int(s["reserved"].get(kind, 0))) + 1
        s["reserved"][kind] = n
        return f"{kind}-{n:03d}"

    return _locked(go)


# ---------------------------------------------------------------- similarity


def _tokens(text):
    return [w for w in re.findall(r"[a-z][a-z0-9-]{2,}", text.lower()) if w not in STOP]


def hard_refs(text):
    refs = set()
    for rx in REF_RES:
        for m in rx.findall(text or ""):
            refs.add(re.sub(r"\s+", " ", m.lower()))
    return refs


class Index:
    """TF-IDF over title (weighted 3x) plus body for the rows given."""

    def __init__(self, rows):
        self.rows = rows
        self.docs = [self._doc(r["title"], r["body"]) for r in rows]
        df = Counter()
        for d in self.docs:
            df.update(set(d))
        self.n = max(len(self.docs), 1)
        self.idf = {w: math.log((1 + self.n) / (1 + c)) + 1 for w, c in df.items()}
        self.vecs = [self._vec(d) for d in self.docs]
        self.refs = [hard_refs(r["title"] + "\n" + r["body"]) - {r["id"].lower()} for r in rows]

    @staticmethod
    def _doc(title, body):
        body = re.sub(r"Earlier:.*", "", body or "")  # old statuses are history, not topic
        return _tokens(title) * 3 + _tokens(body)

    def _vec(self, doc):
        tf = Counter(doc)
        v = {
            w: (1 + math.log(c)) * self.idf.get(w, math.log(1 + self.n) + 1) for w, c in tf.items()
        }
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {w: x / norm for w, x in v.items()}

    def score(self, title, body, i):
        q = self._vec(self._doc(title, body))
        cos = sum(x * self.vecs[i].get(w, 0.0) for w, x in q.items())
        shared = (hard_refs(title + "\n" + body) & self.refs[i]) - {"pr #"}
        bonus = min(0.25, 0.1 * len(shared))
        return round(min(1.0, cos + bonus), 3), sorted(shared)

    def clear_winner(self, title, body, floor, skip_uid=None, only=None, margin=None):
        """(score, shared, row) when one entry clearly matches, else None."""
        top = self.best(title, body, skip_uid=skip_uid, limit=2, only=only)
        if not top or top[0][0] < floor:
            return None
        if len(top) > 1 and top[0][0] < (margin or MARGIN) * max(top[1][0], 0.01):
            return None
        return top[0]

    def best(self, title, body, skip_uid=None, limit=3, only=None):
        out = []
        for i, r in enumerate(self.rows):
            if r["uid"] == skip_uid or (only and not only(r)):
                continue
            s, shared = self.score(title, body, i)
            out.append((s, shared, r))
        out.sort(key=lambda t: -t[0])
        return out[:limit]


def _lane(r):
    """Open work (Needs decision, To do) folds together, Parked folds with Parked."""
    return "parked" if r["bucket"] == "parked" else "open"


def open_rows(rows=None):
    rows = rows if rows is not None else eb.all_rows()
    return [r for r in rows if r["bucket"] in ("decide", "todo", "parked") and not r.get("parent")]


# ---------------------------------------------------------------- writes


def _write_status(row, new_status, by):
    """Status line rewrite with the same lock and format as eng_backlog.set_status."""
    if row["status"]:
        new_status += f" Earlier: {row['status']}"
    eb.rewrite_status(row, new_status)
    return {
        "at": _now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "uid": row["uid"],
        "id": row["id"],
        "by": by,
    }


def append_update(row, title, text):
    """Append a dated Update bullet to an existing entry (above its Status line when it ends the TD block)."""
    path = Path(row["file"])
    line = (
        f"- **Update {_today()}**: {title.rstrip('.')}."
        + (f" {text.strip()}" if text and text.strip() else "")
        + "\n"
    )
    with eb.file_lock(path):
        lines = path.read_text(encoding="utf-8").splitlines(True)
        hits = [i for i, ln in enumerate(lines) if ln.rstrip("\n") == row["heading"]]
        if len(hits) != 1:
            raise RuntimeError(f"{row['id']} heading found {len(hits)} times, refusing to edit")
        j = hits[0] + 1
        while j < len(lines) and not eb.HEAD_RE.match(lines[j]) and lines[j].strip() != "---":
            j += 1
        k = j
        while k > hits[0] + 1 and not lines[k - 1].strip():
            k -= 1
        lines.insert(k, line)
        eb.atomic_write(path, "".join(lines))


def new_entry(kind, title, text, status, goal="", effort="", severity=""):
    eid = reserve_id(kind)
    path = eb.TD_FILE if kind == "TD" else eb.IMP_FILE
    status = status or ("OPEN" if kind == "TD" else "suggested")
    if kind == "IMP":
        block = [f"### {eid}: {title}", f"- **Status**: {status} {_today()}"]
        if goal:
            block.append(f"- **Goal**: {goal}")
        if effort:
            block.append(f"- **Effort**: {effort}")
        if text:
            block.append(f"- **Observed**: {text.strip()}")
        block += ["", ""]
    else:
        block = [f"## {eid}: {title} (NEW {_today()})", ""]
        if severity:
            block.append(f"- **Severity**: {severity}")
        if text:
            block.append(f"- **Description**: {text.strip()}")
        block += [
            *([f"- **Owner**: {OWNER}"] if OWNER else []),
            f"- **Status**: {status} {_today()}",
            "",
            "---",
            "",
            "",
        ]
    with eb.file_lock(path):
        lines = path.read_text(encoding="utf-8").splitlines(True)
        first = next((i for i, ln in enumerate(lines) if eb.HEAD_RE.match(ln)), len(lines))
        lines.insert(first, "\n".join(block))
        eb.atomic_write(path, "".join(lines))
    return eid


def add(kind, title, text="", status="", goal="", effort="", severity="", into="", force_new=False):
    """Front door. Returns a dict describing what was written."""
    rows = eb.all_rows()
    if into:
        target = eb.resolve_id(into, rows)
        append_update(target, title, text)
        return {"action": "update", "into": target["id"], "uid": target["uid"]}
    cands = open_rows(rows)
    idx = Index(cands)
    best = idx.best(title, text, limit=3)
    win = None if force_new else idx.clear_winner(title, text, UPDATE_MATCH)
    if win:
        s, shared, target = win
        append_update(target, title, text)
        return {
            "action": "update",
            "into": target["id"],
            "uid": target["uid"],
            "score": s,
            "shared": shared,
        }
    eid = new_entry(kind, title, text, status, goal, effort, severity)
    return {
        "action": "new",
        "id": eid,
        "near": [
            {"id": r["id"], "title": r["title"], "score": s}
            for s, _, r in best
            if s >= UPDATE_MATCH
        ],
    }


# ---------------------------------------------------------------- PR state


def _pr_refs(text):
    out = set()
    for m in re.finditer(r"github\.com/([\w-]+/[\w.-]+)/pull/(\d+)", text):
        out.add((m.group(1), int(m.group(2))))
    for alias, repo in PR_ALIASES.items():
        for m in re.finditer(rf"\b{re.escape(alias)}\s+(?:\[?PR\s+)?#(\d+)", text, re.I):
            out.add((repo, int(m.group(1))))
    return out


def _pr_state(s, repo, n, budget):
    key = f"{repo}#{n}"
    hit = s["prs"].get(key)
    if hit and hit.get("state") in ("MERGED", "CLOSED"):
        return hit["state"]
    if budget[0] <= 0:
        return hit.get("state") if hit else None
    budget[0] -= 1
    try:
        out = subprocess.run(
            ["gh", "pr", "view", str(n), "-R", repo, "--json", "state", "-q", ".state"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        state = out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        state = None
    if state:
        s["prs"][key] = {"state": state, "at": _now().strftime("%Y-%m-%dT%H:%M:%SZ")}
    return state


# ---------------------------------------------------------------- the pass


def _age_days(row):
    if not row["date"]:
        return None
    try:
        d = dt.date.fromisoformat(row["date"])
    except ValueError:
        return None
    return (_now().date() - d).days


def run(dry=False, gh=True):
    rows = eb.all_rows()
    s = load_state()
    actions, hints = [], {}
    budget = [PR_CHECKS_PER_RUN if gh else 0]
    opened = open_rows(rows)

    def hint(row, h):
        key = f"{h['type']}:{h.get('target', '')}"
        if key in s["dismissed"].get(row["uid"], []):
            return
        h["key"] = key
        hints.setdefault(row["uid"], []).append(h)

    # 1. statuses that already say the work is finished
    for r in opened:
        st = r["status"]
        if (
            r["bucket"] == "parked"
            or not TERMINAL_RE.search(st)
            or PARTIAL_RE.search(re.sub(r"Earlier:.*", "", st))
        ):
            continue
        word = "RESOLVED" if r["kind"] == "TD" else "shipped"
        hit = TERMINAL_RE.search(st)
        m = hit.group(1) if hit else "done"
        actions.append(
            ("close", r, f"{word} {_today()} (auto-curated: the status already said {m}).")
        )

    closing = {a[1]["uid"] for a in actions}
    idx = Index([r for r in opened if r["uid"] not in closing])
    folding, targets = set(), set()
    for r in opened:
        if r["uid"] in closing:
            continue
        # 2. a clear match of the same kind and lane folds on its own, into a workstream or the older entry.
        # One hop per pass: an entry that is being folded never receives, a receiver is never folded.
        if not r.get("children") and r["uid"] not in targets:
            kind, lane = r["kind"], _lane(r)
            win = idx.clear_winner(
                r["title"],
                r["body"],
                SUGGEST_FOLD,
                skip_uid=r["uid"],
                only=lambda x, k=kind, ln=lane: (
                    not x.get("parent") and x["kind"] == k and _lane(x) == ln
                ),
                margin=FOLD_MARGIN,
            )
            if win:
                sc, shared, p = win
                older = bool(p.get("children")) or ((p["date"] or ""), p["id"]) < (
                    (r["date"] or "9999"),
                    r["id"],
                )
                blocked = (
                    f"fold:{p['id']}" in s["dismissed"].get(r["uid"], []) or p["uid"] in folding
                )
                if older and not blocked:
                    folding.add(r["uid"])
                    targets.add(p["uid"])
                    why = f"shared {', '.join(shared[:3])}" if shared else "same kind and lane"
                    actions.append(
                        (
                            "fold",
                            r,
                            f"folded into {p['id']} ({p['title'][:70]}) {_today()} (auto-curated, match {sc}, {why}).",
                        )
                    )
                    continue
        # 3. hints. A close match that is not a clear winner (a tie, another lane) stays a one-click hint.
        best = idx.best(
            r["title"], r["body"], skip_uid=r["uid"], limit=1, only=lambda x: not x.get("parent")
        )
        if best and best[0][0] >= SUGGEST_FOLD and not r.get("children"):
            sc, shared, t = best[0]
            if t.get("children") or ((t["date"] or ""), t["id"]) < ((r["date"] or "9999"), r["id"]):
                hint(
                    r,
                    {
                        "type": "fold",
                        "target": t["id"],
                        "title": t["title"][:90],
                        "score": sc,
                        "shared": shared[:4],
                    },
                )
        if (
            r["bucket"] == "todo"
            and r["kind"] == "IMP"
            and not PARTIAL_RE.search(re.sub(r"Earlier:.*", "", r["status"]))
        ):
            prs = _pr_refs(r["status"])
            if prs:
                states = [_pr_state(s, repo, n, budget) for repo, n in sorted(prs)]
                if states and all(x == "MERGED" for x in states):
                    hint(
                        r,
                        {
                            "type": "close",
                            "target": "",
                            "reason": f"Every PR it cites is merged ({len(states)})",
                        },
                    )
        for term, why in RETIRED_TERMS.items():
            if re.search(rf"\b{re.escape(term)}\b", r["title"]):
                hint(r, {"type": "retired", "target": term, "reason": why})
                break
        age = _age_days(r)
        if r["bucket"] != "parked" and age is not None and age > STALE_DAYS:
            hint(r, {"type": "stale", "target": "", "reason": f"No dated change for {age} days"})
        if not r["date"] and r["bucket"] != "parked":
            hint(r, {"type": "stale", "target": "", "reason": "No date anywhere in the entry"})
        if r["status"] and not eb.canonical(r["kind"], r["status"]):
            hint(
                r,
                {
                    "type": "status",
                    "target": "",
                    "reason": f"Status word the page cannot read: {r['status'][:40]}",
                },
            )
    ids = Counter(r["id"] for r in opened)
    for r in opened:
        if ids[r["id"]] > 1:
            hint(
                r,
                {
                    "type": "dup-id",
                    "target": "",
                    "reason": f"{r['id']} is used by {ids[r['id']]} open entries",
                },
            )

    if not dry:
        for _kind, r, status in actions:
            entry = _write_status(r, status, "auto")
            entry.update({"what": _kind, "title": r["title"][:120], "status": status})
            s["log"].insert(0, entry)
        s["log"] = s["log"][:80]
        s["hints"] = hints
        s["generated_utc"] = _now().strftime("%Y-%m-%dT%H:%M:%SZ")
        s["last_actions"] = len(actions)
        s.pop("reserved_stale", None)
        _locked(
            lambda cur: cur.update(
                {k: s[k] for k in ("hints", "log", "prs", "generated_utc", "last_actions")}
            )
        )
    return {
        "actions": [(a, r["id"], st[:140]) for a, r, st in actions],
        "hints": sum(len(v) for v in hints.values()),
    }


def dismiss(uid, key):
    def go(s):
        s["dismissed"].setdefault(uid, [])
        if key not in s["dismissed"][uid]:
            s["dismissed"][uid].append(key)
        s["hints"][uid] = [h for h in s["hints"].get(uid, []) if h.get("key") != key]
        return {"uid": uid, "dismissed": key}

    return _locked(go)


def summary():
    s = load_state()
    week = (_now() - dt.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "generated_utc": s.get("generated_utc"),
        "auto_week": [e for e in s["log"] if e.get("at", "") >= week][:30],
        "hints": s["hints"],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(prog="backlog.py", description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser(
        "add", help="log a finding, folding it into a matching entry when there is one"
    )
    a.add_argument("--kind", choices=("IMP", "TD"), required=True)
    a.add_argument("--title", required=True)
    a.add_argument("--text", default="")
    a.add_argument("--status", default="")
    a.add_argument("--goal", default="")
    a.add_argument("--effort", default="")
    a.add_argument("--severity", default="")
    a.add_argument("--into", default="", help="append to this entry id")
    a.add_argument("--new", action="store_true", help="always write a new entry")
    m = sub.add_parser("similar", help="closest open entries, writes nothing")
    m.add_argument("--title", required=True)
    m.add_argument("--text", default="")
    r = sub.add_parser("run", help="scheduled curation pass")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--no-gh", action="store_true")
    sub.add_parser("next-id").add_argument("kind", choices=("IMP", "TD"))
    ns = ap.parse_args(argv)
    if ns.cmd == "add":
        out = add(
            ns.kind, ns.title, ns.text, ns.status, ns.goal, ns.effort, ns.severity, ns.into, ns.new
        )
    elif ns.cmd == "similar":
        idx = Index(open_rows())
        out = [
            {"id": r["id"], "title": r["title"], "score": sc, "shared": sh}
            for sc, sh, r in idx.best(ns.title, ns.text, limit=5)
        ]
    elif ns.cmd == "run":
        out = run(dry=ns.dry_run, gh=not ns.no_gh)
    else:
        out = {"id": reserve_id(ns.kind)}
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
