#!/usr/bin/env python3
"""
yearly_reviews.py - Annual review store for the ops center (the people slot, off by default).

Purpose: Durable, year-keyed review records for each person, edited on the Team Performance > Yearly review tab.
         One record per (year, person). Nothing is ever deleted: a reset snapshots the record first, a redraft
         keeps the prior text as a version, and Undo or Restore brings it back.

         Sections come from review-template.json (the template is a config change). Drafting and per-section
         refinement run as detached jobs of a drafter command (the `drafter_cmd` parameter; the core ships no
         drafter: it reads the evidence and may call a model, so it is the consumer's). This module launches the
         job and applies its result under its own lock, so a draft can never clobber a concurrent manual edit.

         Export renders a .docx per person and year and archives a copy under
         state/team-performance/yearly-reviews/<year>/. Private notes, the owner's working analysis and evidence
         lists never export. The export is the one place a non stdlib package is needed (python-docx, imported
         lazily); the exception is recorded with the scripting standard (DESIGN.md 12.6). People data stays local
         (DESIGN.md section 11 item 5).

Parameters (the people parameters file, one_on_ones.py): owner_name, team_name, drafter_cmd (a command list that
takes `--job <job file>` and includes its interpreter).
"""

import copy
import datetime as dt
import io
import json
import os
import re
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path

ROOT = Path(os.environ.get("OPSCENTER_ROOT") or Path.home() / ".opscenter")
STATE = Path(os.environ.get("OPSCENTER_STATE_DIR") or ROOT / "state")


def _params():
    f = os.environ.get("OPSCENTER_PEOPLE_PARAMS") or str(STATE / "people-params.json")
    try:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    return d if isinstance(d, dict) else {}


_P = _params()
TP_DIR = STATE / "team-performance"
STORE = TP_DIR / "yearly-reviews.json"
ARCHIVE = TP_DIR / "yearly-reviews"
HISTORY = TP_DIR / "history-master.json"
TP_PATH = TP_DIR / "team-performance.json"
TARGETS = TP_DIR / "targets.json"
TEMPLATE = TP_DIR / "review-template.json"
JOBS_DIR = TP_DIR / "review-jobs"
EVID = TP_DIR / "evidence"
# The drafter is a command list (consumer supplied); none configured means a draft cannot start.
DRAFTER = [str(a) for a in _P["drafter_cmd"]] if isinstance(_P.get("drafter_cmd"), list) else None

TEAM = str(_P.get("team_name") or "Team")
AUTHOR = str(_P.get("owner_name") or "the owner")
STATUSES = ("draft", "final")
MODES = ("full", "refine", "evidence")
ACTIVE = ("starting", "queued", "evidence", "drafting")
MAX_TEXT = 20000
MAX_GUIDE = 4000
# The Undo stack per section shows the newest MAX_VERSIONS. Older versions,
# undone text and every reset snapshot are kept (trash, snapshots), never dropped.
MAX_VERSIONS = 10
JOB_KEEP_S = 7 * 86400
YEAR_RE = re.compile(r"20\d\d")
CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_LOCK = threading.RLock()

# Used only when review-template.json is missing or unreadable.
FALLBACK_TEMPLATE = {
    "version": 0,
    "name": "Fallback format",
    "ratings": {
        "": "Not set",
        "outstanding": "Outstanding",
        "exceeds": "Exceeds expectations",
        "meets": "Meets expectations",
        "partially_meets": "Partially meets expectations",
        "does_not_meet": "Does not meet expectations",
    },
    "sections": [
        {
            "key": "summary",
            "title": "Overall summary",
            "hint": "The year in two or three sentences.",
            "rows": 5,
            "export": True,
        },
        {
            "key": "accomplishments",
            "title": "Key accomplishments",
            "hint": "One per line.",
            "rows": 7,
            "export": True,
        },
        {
            "key": "growth",
            "title": "Areas for development",
            "hint": "One per line.",
            "rows": 6,
            "export": True,
        },
        {
            "key": "goals",
            "title": "Goals for next year",
            "hint": "Measurable goals.",
            "rows": 6,
            "export": True,
        },
        {
            "key": "private_notes",
            "title": "Private notes",
            "hint": "Never exported.",
            "rows": 4,
            "export": False,
            "private": True,
        },
    ],
}


class Conflict(Exception):
    """A request that clashes with current state (job already running, final review)."""


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def template():
    t = _load_json(TEMPLATE, None)
    if not isinstance(t, dict) or not isinstance(t.get("sections"), list) or not t["sections"]:
        t = copy.deepcopy(FALLBACK_TEMPLATE)
    t.setdefault("ratings", FALLBACK_TEMPLATE["ratings"])
    if not isinstance(t.get("scale"), dict):
        # Without point values there is no weighted score, only the manual overall rating.
        t["scale"] = {}
    return t


def _rated(tpl):
    """Competency sections that carry their own rating (HR form, template v2)."""
    return [s for s in tpl["sections"] if s.get("rated")]


def _score(rec, tpl):
    """Weighted overall score from the competency ratings, the way the HR form rolls it up.
    Returns None when the template has no rated sections."""
    rated = _rated(tpl)
    if not rated:
        return None
    scale = tpl.get("scale") or {}
    ratings = rec.get("section_ratings") or {}
    total_w = sum(float(s.get("weight") or 0) for s in rated) or float(len(rated))
    got_w, acc, done = 0.0, 0.0, 0
    for s in rated:
        v = scale.get(ratings.get(s["key"]) or "")
        if v is None:
            continue
        w = float(s.get("weight") or 0) or 1.0
        acc += w * float(v)
        got_w += w
        done += 1
    value = round(acc / got_w, 2) if got_w else None
    key = ""
    if value is not None and done == len(rated):
        # Round half up to the nearest point on the scale.
        pts = int(value + 0.5)
        key = next((k for k, p in scale.items() if p == pts), "")
    return {
        "value": value,
        "rated": done,
        "total": len(rated),
        "weight_rated": got_w,
        "weight_total": total_w,
        "rating": key,
        "complete": done == len(rated),
    }


def _sync_rating(rec, tpl):
    """On the competency format the overall rating is derived, never typed."""
    sc = _score(rec, tpl)
    if sc is None:
        return
    rec["rating"] = sc["rating"]
    rec["rating_source"] = "computed" if sc["rating"] else ""


def _missing_for_final(rec, tpl):
    """HR returns a review with any rating lacking its comment, so final needs both."""
    out = []
    for s in tpl["sections"]:
        if not s.get("export", True) or s.get("private"):
            continue
        if not (rec["sections"].get(s["key"]) or "").strip():
            out.append("%s comment" % s["title"])  # noqa: UP031
        if s.get("rated") and not (rec.get("section_ratings") or {}).get(s["key"]):
            out.append("%s rating" % s["title"])  # noqa: UP031
    return out


def _keys(tpl=None):
    return [s["key"] for s in (tpl or template())["sections"]]


def _titles(tpl=None):
    return {s["key"]: s["title"] for s in (tpl or template())["sections"]}


def _title(key):
    return _titles().get(key, key)


def load():
    data = _load_json(STORE, None)
    if not isinstance(data, dict) or not isinstance(data.get("reviews"), dict):
        data = {"schema": 2, "created_utc": _now(), "reviews": {}}
    return data


def _save(data):
    data["schema"] = 2
    data["updated_utc"] = _now()
    STORE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(STORE.parent), prefix=".yearly-reviews.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, STORE)
    except OSError:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def people():
    """Everyone with assessment history, plus the current roster."""
    names = set()
    for run in _load_json(HISTORY, {}).get("runs", []):
        for e in run.get("engineers", []):
            if e.get("name"):
                names.add(e["name"])
    names.update(_load_json(TP_PATH, {}).get("engineers", []) or [])
    for t in _load_json(TARGETS, {}).get("targets", []) or []:
        if t.get("jira_name"):
            names.add(t["jira_name"])
    return sorted(names)


def _blank():
    return {
        "rating": "",
        "rating_source": "",
        "rating_suggestion": None,
        # Competency format (template v2): one rating per rated section.
        # section_rating_meta[key] = {"source": "draft"|"manager", "at", "suggested"}
        "section_ratings": {},
        "section_rating_meta": {},
        "status": "draft",
        "sections": {},
        "evidence": {},
        "meta": {},
        "versions": {},
        "guidance": {},
        "analysis": None,
        "draft": None,
        "snapshots": [],
        "trash": [],
        "created_utc": None,
        "updated_utc": None,
        "finalized_utc": None,
        "events": [],
    }


def _norm(rec):
    """Bring a schema 1 record (sections + rating only) up to the current shape."""
    out = _blank()
    out.update(rec or {})
    for k in (
        "sections",
        "evidence",
        "meta",
        "versions",
        "guidance",
        "section_ratings",
        "section_rating_meta",
    ):
        if not isinstance(out.get(k), dict):
            out[k] = {}
    for k in ("snapshots", "trash", "events"):
        if not isinstance(out.get(k), list):
            out[k] = []
    if out["rating"] and not out.get("rating_source"):
        out["rating_source"] = "manager"
    return out


def _slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _public(rec, tpl=None):
    """Record as the UI sees it: version and snapshot history as metadata only."""
    r = _norm(copy.deepcopy(rec))
    r["score"] = _score(r, tpl or template())
    r["versions"] = {
        k: [
            {"at": v.get("at"), "source": v.get("source"), "chars": len(v.get("text") or "")}
            for v in vs
        ]
        for k, vs in r["versions"].items()
        if vs
    }
    r["snapshots"] = [{"at": s.get("at"), "reason": s.get("reason")} for s in r["snapshots"]]
    r.pop("trash", None)
    return r


def get_all():
    apply_finished()
    data = load()
    tpl = template()
    return {
        "schema": 2,
        "updated_utc": data.get("updated_utc"),
        "reviews": {
            y: {n: _public(r, tpl) for n, r in ppl.items()} for y, ppl in data["reviews"].items()
        },
        "people": people(),
        "ratings": tpl["ratings"],
        "scale": tpl.get("scale") or {},
        "sections": _titles(tpl),
        "template": {
            "name": tpl.get("name"),
            "version": tpl.get("version"),
            "sections": [
                {
                    k: s.get(k)
                    for k in (
                        "key",
                        "title",
                        "hint",
                        "rows",
                        "export",
                        "private",
                        "rated",
                        "weight",
                        "definition",
                    )
                }
                for s in tpl["sections"]
            ],
        },
        "jobs": _public_jobs(),
    }


def _validate_who(year, person):
    year = str(year or "")
    if not YEAR_RE.fullmatch(year):
        raise ValueError("year must be YYYY")
    if person not in people():
        raise ValueError("unknown person")
    return year, person


def _clean(v):
    return CTRL_RE.sub("", v)


def _push_version(rec, key, source):
    old = rec["sections"].get(key) or ""
    if not old.strip():
        return
    vs = rec["versions"].setdefault(key, [])
    if vs and vs[-1].get("text") == old:
        return
    vs.append({"text": old, "at": _now(), "source": source})
    if len(vs) > MAX_VERSIONS:
        spill = vs[:-MAX_VERSIONS]
        del vs[:-MAX_VERSIONS]
        rec["trash"] = rec.get("trash", []) + [
            {
                "section": key,
                "text": v.get("text") or "",
                "at": v.get("at"),
                "meta": {"source": v.get("source")},
                "why": "aged out of undo",
            }
            for v in spill
        ]


def upsert(payload):
    """One edit. ops: edit (default), guidance, reset, restore, undo.
    Final reviews are locked for everything except reopening."""
    if not isinstance(payload, dict):
        raise ValueError("object required")
    year, person = _validate_who(payload.get("year"), payload.get("person"))
    op = payload.get("op") or "edit"
    tpl = template()
    with _LOCK:
        data = load()
        rec = _norm(data["reviews"].setdefault(year, {}).get(person))
        known = set(_keys(tpl)) | set(rec["sections"])
        now = _now()
        final = rec.get("status") == "final"

        if op == "edit":
            sections = payload.get("sections")
            rating = payload.get("rating")
            sratings = payload.get("section_ratings")
            status = payload.get("status")
            rated_keys = {s["key"] for s in _rated(tpl)}
            if sections is not None:
                if not isinstance(sections, dict) or any(k not in known for k in sections):
                    raise ValueError("unknown section")
                if any(not isinstance(v, str) or len(v) > MAX_TEXT for v in sections.values()):
                    raise ValueError("section text must be a string under %d chars" % MAX_TEXT)  # noqa: UP031
            if rating is not None and rating not in tpl["ratings"]:
                raise ValueError("unknown rating")
            if rating is not None and rated_keys:
                raise ValueError(
                    "the overall rating is the weighted result of the competency ratings, rate each competency instead"
                )
            if sratings is not None:
                if not isinstance(sratings, dict) or any(k not in rated_keys for k in sratings):
                    raise ValueError("unknown competency")
                if any(v not in tpl["ratings"] for v in sratings.values()):
                    raise ValueError("unknown rating")
            if status is not None and status not in STATUSES:
                raise ValueError("unknown status")
            if final and status != "draft" and (sections or rating is not None or sratings):
                raise Conflict("this review is final, reopen it before editing")
            for k, v in (sections or {}).items():
                v = _clean(v)
                if v != (rec["sections"].get(k) or ""):
                    # Autosave fires every few seconds, so only the first manual
                    # edit over drafted or restored text keeps a version. Undo
                    # then brings the draft back without a version per keystroke.
                    if (rec["meta"].get(k) or {}).get("source") != "manual":
                        _push_version(rec, k, (rec["meta"].get(k) or {}).get("source") or "manual")
                    rec["sections"][k] = v
                    rec["meta"][k] = {"source": "manual", "at": now}
            if rating is not None and rating != rec["rating"]:
                rec["rating"] = rating
                rec["rating_source"] = "manager" if rating else ""
            for k, v in (sratings or {}).items():
                if v != (rec["section_ratings"].get(k) or ""):
                    if v:
                        rec["section_ratings"][k] = v
                    else:
                        rec["section_ratings"].pop(k, None)
                    prev = rec["section_rating_meta"].get(k) or {}
                    rec["section_rating_meta"][k] = {
                        "source": "manager" if v else "",
                        "at": now,
                        "suggested": prev.get("suggested") or "",
                    }
            _sync_rating(rec, tpl)
            if status == "final" and not final:
                gaps = _missing_for_final(rec, tpl) if rated_keys else []
                if gaps:
                    raise ValueError(
                        "HR needs a rating and a comment on every competency. Missing: "
                        + ", ".join(gaps)
                    )
            if status is not None and status != rec.get("status"):
                rec["status"] = status
                rec["events"].append(
                    {"at": now, "event": "finalized" if status == "final" else "reopened"}
                )
                if status == "final":
                    rec["finalized_utc"] = now
        elif op == "guidance":
            g = payload.get("guidance")
            if not isinstance(g, dict) or any(k not in known and k != "_all" for k in g):
                raise ValueError("guidance must map section keys to text")
            for k, v in g.items():
                if not isinstance(v, str) or len(v) > MAX_GUIDE:
                    raise ValueError("guidance must be text under %d chars" % MAX_GUIDE)  # noqa: UP031
                v = _clean(v).strip()
                if v == rec["guidance"].get(k, ""):
                    continue
                if v:
                    rec["guidance"][k] = v
                else:
                    rec["guidance"].pop(k, None)
                rec["events"].append(
                    {
                        "at": now,
                        "event": "%s steer %s"  # noqa: UP031
                        % ("overall" if k == "_all" else _title(k), "saved" if v else "cleared"),  # noqa: UP031
                    }
                )
        elif op == "reset":
            if final:
                raise Conflict("this review is final, reopen it before resetting")
            if _active_job(year, person):
                raise Conflict("a draft is running for this review, wait for it to finish")
            snap = {k: v for k, v in rec.items() if k not in ("snapshots", "trash", "events")}
            snaps = rec["snapshots"] + [{"at": now, "reason": "reset", "record": snap}]
            fresh = _blank()
            fresh.update(
                created_utc=rec.get("created_utc") or now,
                snapshots=snaps,
                trash=rec["trash"],
                events=rec["events"] + [{"at": now, "event": "reset"}],
            )
            rec = fresh
        elif op == "restore":
            if final:
                raise Conflict("this review is final, reopen it before restoring")
            if not rec["snapshots"]:
                raise ValueError("nothing to restore")
            snap = rec["snapshots"].pop()
            back = _norm(snap.get("record") or {})
            back.update(
                snapshots=rec["snapshots"],
                trash=rec["trash"],
                events=rec["events"]
                + [
                    {
                        "at": now,
                        "event": "restored the %s from %s"  # noqa: UP031
                        % (snap.get("reason") or "snapshot", (snap.get("at") or "")[:16]),
                    }
                ],
                status="draft",
            )
            rec = back
        elif op == "undo":
            key = payload.get("section")
            if key not in known:
                raise ValueError("unknown section")
            if final:
                raise Conflict("this review is final, reopen it before editing")
            vs = rec["versions"].get(key) or []
            if not vs:
                raise ValueError("no earlier version of this section")
            prev = vs.pop()
            cur = rec["sections"].get(key) or ""
            if cur.strip():
                rec["trash"] = rec["trash"] + [
                    {
                        "section": key,
                        "text": cur,
                        "at": now,
                        "meta": rec["meta"].get(key),
                        "why": "undone",
                    }
                ]
            rec["sections"][key] = prev.get("text") or ""
            rec["meta"][key] = {
                "source": "undo",
                "at": now,
                "restored": prev.get("at"),
                "was": prev.get("source"),
            }
            rec["evidence"].pop(key, None)
            rec["events"].append({"at": now, "event": "undo: %s" % _title(key)})  # noqa: UP031
        else:
            raise ValueError("unknown op")

        rec["created_utc"] = rec.get("created_utc") or now
        rec["updated_utc"] = now
        data["reviews"][year][person] = rec
        _save(data)
        return _public(rec)


# ---------------------------------------------------------------- drafting jobs
def _job_path(jid):
    if not re.fullmatch(r"[a-z0-9-]{8,64}", jid or ""):
        raise ValueError("bad job id")
    return JOBS_DIR / ("%s.json" % jid)  # noqa: UP031


def _write_job(job):
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(JOBS_DIR, 0o700)
    p = _job_path(job["id"])
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(job, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def _read_jobs():
    out = []
    if not JOBS_DIR.exists():
        return out
    for p in JOBS_DIR.glob("*.json"):
        j = _load_json(p, None)
        if isinstance(j, dict) and j.get("id"):
            out.append(j)
    return out


def _pid_alive(pid):
    if not pid:
        return False
    try:
        done, _ = os.waitpid(int(pid), os.WNOHANG)
        if done:
            return False
    except ChildProcessError:
        pass  # not our child (server restarted), fall through to kill(0)
    except OSError:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def _active_job(year, person):
    for j in _read_jobs():
        mine = (
            str(j.get("year")) == str(year)
            and j.get("person") == person
            and j.get("state") in ACTIVE
        )
        if mine and (_pid_alive(j.get("pid")) or j.get("state") == "starting"):
            return j
    return None


def _public_job(j):
    res = j.get("result") or {}
    return {
        "id": j["id"],
        "year": j.get("year"),
        "person": j.get("person"),
        "mode": j.get("mode"),
        "sections": j.get("sections") or [],
        "state": j.get("state"),
        "stage": j.get("stage") or "",
        "steps": (j.get("steps") or [])[-10:],
        "created_utc": j.get("created_utc"),
        "started_utc": j.get("started_utc"),
        "finished_utc": j.get("finished_utc"),
        "error": j.get("error"),
        "warnings": (res.get("warnings") or [])[:12],
        "applied_utc": j.get("applied_utc"),
    }


def _public_jobs():
    now = dt.datetime.now(dt.timezone.utc)
    out = []
    for j in _read_jobs():
        try:
            age = (now - dt.datetime.fromisoformat(j.get("created_utc"))).total_seconds()
        except (TypeError, ValueError):
            age = 0
        if j.get("state") in ACTIVE or age < 86400:
            out.append(_public_job(j))
    out.sort(key=lambda x: x.get("created_utc") or "", reverse=True)
    return out


def start_job(payload):
    """Launch a drafting job: full draft, refine listed sections, or evidence refresh."""
    if not isinstance(payload, dict):
        raise ValueError("object required")
    year, person = _validate_who(payload.get("year"), payload.get("person"))
    mode = payload.get("mode") or "full"
    if mode not in MODES:
        raise ValueError("unknown mode")
    tpl = template()
    keys = _keys(tpl)
    sections = payload.get("sections") or []
    if not isinstance(sections, list) or any(k not in keys for k in sections):
        raise ValueError("unknown section")
    if mode == "refine" and not sections:
        raise ValueError("refine needs at least one section")
    guidance = payload.get("guidance")
    if guidance is not None:
        upsert({"op": "guidance", "year": year, "person": person, "guidance": guidance})
    with _LOCK:
        if _active_job(year, person):
            raise Conflict("a draft is already running for %s" % str(person).split()[0])  # noqa: UP031
        data = load()
        rec = _norm(data["reviews"].get(year, {}).get(person))
        if mode != "evidence" and rec.get("status") == "final":
            raise Conflict("this review is final, reopen it before redrafting")
        jid = "%s-%s-%s" % (year, _slug(person), uuid.uuid4().hex[:8])  # noqa: UP031
        job = {
            "id": jid,
            "year": year,
            "person": person,
            "mode": mode,
            "sections": sections if mode == "refine" else [],
            "guidance": rec["guidance"],
            "current": {
                "sections": rec["sections"],
                "rating": rec["rating"],
                "section_ratings": rec["section_ratings"],
                "analysis": rec.get("analysis") or {},
            },
            "refresh_graph": bool(payload.get("refresh_graph")) or mode in ("full", "evidence"),
            "state": "starting",
            "stage": "Starting",
            "steps": [],
            "created_utc": _now(),
        }
        _write_job(job)
        log_path = JOBS_DIR / ("%s.log" % jid)  # noqa: UP031
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
        env["OPSCENTER_ROOT"] = str(ROOT)
        if not DRAFTER:
            raise ValueError("no drafter is configured (the drafter_cmd parameter)")
        with open(log_path, "ab") as log:
            os.chmod(log_path, 0o600)
            # Detached session: the draft survives a server restart and the
            # server picks the result up from the job file on its next poll.
            proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
                [*DRAFTER, "--job", str(_job_path(jid))],
                stdout=log,
                stderr=log,
                stdin=subprocess.DEVNULL,
                cwd=str(TP_DIR),
                env=env,
                start_new_session=True,
            )
        job = _load_json(_job_path(jid), job)
        if not job.get("pid"):
            # The drafter records its own pid on start. Only fill it in if it has not yet.
            job["pid"] = proc.pid
            job["started_utc"] = job.get("started_utc") or _now()
            _write_job(job)
        rec_events = data["reviews"].setdefault(year, {}).setdefault(person, rec)
        rec_events.setdefault("events", []).append(
            {
                "at": _now(),
                "event": {
                    "full": "draft started",
                    "refine": "refine started",
                    "evidence": "evidence refresh",
                }[mode],
            }
        )
        _save(data)
        return _public_job(job)


def jobs():
    apply_finished()
    return {"jobs": _public_jobs()}


def apply_finished():
    """Apply drafted results and fail jobs whose process died. Idempotent."""
    with _LOCK:
        changed = False
        data = None
        now_dt = dt.datetime.now(dt.timezone.utc)
        for j in _read_jobs():
            st = j.get("state")
            if st in ACTIVE:
                if st == "starting" and not j.get("pid"):
                    continue
                if not _pid_alive(j.get("pid")):
                    fresh = _load_json(_job_path(j["id"]), j)
                    if fresh.get("state") in ACTIVE:
                        fresh.update(
                            state="failed",
                            error="the drafting process stopped before it finished",
                            finished_utc=_now(),
                        )
                        _write_job(fresh)
                    j = fresh
                    st = j.get("state")
            if st == "drafted" and not j.get("applied_utc"):
                if data is None:
                    data = load()
                try:
                    _apply(data, j)
                    j.update(state="done", applied_utc=_now())
                    changed = True
                except Conflict as exc:
                    j.update(state="failed", error=str(exc))
                _write_job(j)
            # Prune week-old finished jobs and their prompt/model logs.
            try:
                age = (now_dt - dt.datetime.fromisoformat(j.get("created_utc"))).total_seconds()
            except (TypeError, ValueError):
                age = 0
            if j.get("state") not in ACTIVE and age > JOB_KEEP_S:
                for suffix in (".json", ".log", ".prompt.md", ".model.log"):
                    try:  # noqa: SIM105
                        (JOBS_DIR / (j["id"] + suffix)).unlink()
                    except OSError:
                        pass
        if changed and data is not None:
            _save(data)


def _apply(data, job):
    year, person = str(job["year"]), job["person"]
    res = job.get("result") or {}
    mode = job.get("mode")
    rec = _norm(data["reviews"].setdefault(year, {}).get(person))
    now = _now()
    ev = res.get("evidence") or {}
    if mode == "evidence":
        rec["draft"] = {
            **(rec.get("draft") or {}),
            "evidence_utc": ev.get("generated_utc"),
            "datapoints": ev.get("datapoints"),
            "sources": ev.get("sources"),
        }
        rec["events"].append({"at": now, "event": "evidence refreshed"})
        rec["updated_utc"] = now
        data["reviews"][year][person] = rec
        return
    if rec.get("status") == "final":
        raise Conflict(
            "the review was marked final while the draft ran, so the draft was not applied"
        )
    titles = _titles()
    g = job.get("guidance") or {}
    for k, v in (res.get("sections") or {}).items():
        text = _clean(v.get("text") or "")[:MAX_TEXT]
        if (rec["sections"].get(k) or "") != text:
            _push_version(rec, k, (rec["meta"].get(k) or {}).get("source") or "earlier")
        rec["sections"][k] = text
        rec["evidence"][k] = [_clean(str(x))[:400] for x in v.get("evidence") or []][:12]
        rec["meta"][k] = {
            "source": "draft" if mode == "full" else "refine",
            "at": now,
            "job": job["id"],
            "steered": bool(g.get(k) or g.get("_all")),
        }
    if res.get("rating"):
        rec["rating_suggestion"] = {**res["rating"], "at": now}
        if rec.get("rating_source") != "manager":
            rec["rating"] = res["rating"]["value"]
            rec["rating_source"] = "draft"
    # Competency ratings: the draft suggests, a rating the owner set by hand always wins.
    tpl = template()
    rated_keys = {s["key"] for s in _rated(tpl)}
    for k, v in (res.get("ratings") or {}).items():
        val = (v or {}).get("value") if isinstance(v, dict) else v
        if k not in rated_keys or val not in tpl["ratings"] or not val:
            continue
        meta = rec["section_rating_meta"].get(k) or {}
        if meta.get("source") == "manager" and rec["section_ratings"].get(k):
            rec["section_rating_meta"][k] = {**meta, "suggested": val}
            continue
        rec["section_ratings"][k] = val
        rec["section_rating_meta"][k] = {"source": "draft", "at": now, "suggested": val}
    _sync_rating(rec, tpl)
    if res.get("analysis"):
        rec["analysis"] = {**res["analysis"], "generated_utc": now}
    rec["draft"] = {
        "generated_utc": now if mode == "full" else (rec.get("draft") or {}).get("generated_utc"),
        "refined_utc": now if mode == "refine" else (rec.get("draft") or {}).get("refined_utc"),
        "job": job["id"],
        "evidence_utc": ev.get("generated_utc"),
        "datapoints": ev.get("datapoints"),
        "sources": ev.get("sources"),
        "warnings": (ev.get("warnings") or []) + (res.get("warnings") or []),
    }
    label = (
        "full draft written"
        if mode == "full"
        else "refined: " + ", ".join(titles.get(k, k) for k in res.get("sections") or {})
    )
    rec["events"].append({"at": now, "event": label})
    rec["created_utc"] = rec.get("created_utc") or now
    rec["updated_utc"] = now
    data["reviews"][year][person] = rec


def evidence(year, person):
    """Deterministic year metrics behind the draft (counts only, no message text)."""
    year, person = _validate_who(year, person)
    m = _load_json(EVID / year / _slug(person) / "metrics.json", None)
    return {"metrics": m}


# ---------------------------------------------------------------- export
def _add_text(doc, text):
    """Plain paragraphs. Lines starting with '- ' or '* ' become bullets."""
    text = (text or "").strip()
    if not text:
        doc.add_paragraph("Not written yet.")
        return
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s[:2] in ("- ", "* "):
            doc.add_paragraph(s[2:].strip(), style="List Bullet")
        else:
            doc.add_paragraph(s)


def _table(doc, header, rows):
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    for i, h in enumerate(header):
        cell = t.rows[0].cells[i]
        cell.text = ""
        cell.paragraphs[0].add_run(h).bold = True
    for r in rows:
        cells = t.add_row().cells
        for i, v in enumerate(r):
            cells[i].text = CTRL_RE.sub("", str(v))
    return t


def _fmt_date(iso):
    try:
        d = dt.date.fromisoformat(str(iso)[:10])
    except ValueError:
        return str(iso or "")
    return d.strftime("%B %-d, %Y")


def export_docx(year, person):
    """Render the review to .docx, archive a copy, return (filename, bytes)."""
    from docx import Document  # lazy: only the export path needs python-docx

    year, person = _validate_who(year, person)
    tpl = template()
    rec = _norm((load()["reviews"].get(year) or {}).get(person))
    m = _load_json(EVID / year / _slug(person) / "metrics.json", None) or {}
    title = m.get("title") or next(
        (
            t.get("title")
            for t in _load_json(TARGETS, {}).get("targets", []) or []
            if t.get("jira_name") == person
        ),
        "",
    )
    per = m.get("period") or {}

    doc = Document()
    cp = doc.core_properties
    cp.author = AUTHOR
    cp.title = f"{year} Annual Performance Review: {person}"
    cp.subject = TEAM
    sec = doc.sections[0]
    sec.header.paragraphs[0].text = TEAM
    sec.footer.paragraphs[0].text = f"{TEAM} | Prepared by {AUTHOR} | {year} annual review"

    doc.add_heading(f"{year} Annual Performance Review: {person}", 0)
    period = (
        f"{_fmt_date(per['start'])} to {_fmt_date(per['end'])}"
        if per.get("start")
        else f"Calendar year {year}"
    )
    status = (
        "Final" + (f" ({_fmt_date(rec.get('finalized_utc'))})" if rec.get("finalized_utc") else "")
        if rec.get("status") == "final"
        else "Draft"
    )
    score = _score(rec, tpl)
    overall = tpl["ratings"].get(rec.get("rating") or "", "Not set")
    if score and score.get("value") is not None:
        overall = (
            "%s (weighted score %.2f)" % (overall, score["value"])  # noqa: UP031
            if score["complete"]
            else "Not set (%d of %d competencies rated)" % (score["rated"], score["total"])  # noqa: UP031
        )
    _table(
        doc,
        ["Field", "Value"],
        [
            ("Employee", person),
            ("Title", title or "-"),
            ("Reviewer", f"{AUTHOR}, Manager, {TEAM}"),
            ("Review period", period + (" (partial year)" if per.get("partial") else "")),
            ("Overall rating", overall),
            ("Status", status),
        ],
    )

    sections = [s for s in tpl["sections"] if s.get("export", True) and not s.get("private")]
    rated = [s for s in sections if s.get("rated")]
    if rated:
        # Same layout as the HR Competencies page: rating summary, then each
        # competency with its definition, weight, rating and comment.
        doc.add_heading("Competency ratings (Five Point scale)", 1)
        _table(
            doc,
            ["Competency", "Weight", "Manager rating"],
            [
                (
                    s["title"],
                    "%s%%" % s.get("weight") if s.get("weight") is not None else "-",  # noqa: UP031
                    tpl["ratings"].get(rec["section_ratings"].get(s["key"]) or "", "Not set"),
                )
                for s in rated
            ],
        )
        for i, s in enumerate(sections, 1):
            doc.add_heading(f"{i}. {s['title']}", 1)
            if s.get("definition"):
                doc.add_paragraph(s["definition"]).runs[0].italic = True
            if s.get("rated"):
                doc.add_paragraph(
                    "Competency weight: %s%%. Manager rating: %s."  # noqa: UP031
                    % (
                        s.get("weight"),
                        tpl["ratings"].get(rec["section_ratings"].get(s["key"]) or "", "Not set"),
                    )
                )
            _add_text(doc, rec["sections"].get(s["key"]))
        sections = []
    first = sections[:1]
    rest = sections[1:]
    for s in first:
        doc.add_heading(s["title"], 1)
        _add_text(doc, rec["sections"].get(s["key"]))

    j = m.get("jira") or {}
    if j.get("closed"):
        doc.add_heading("Year at a glance", 1)
        rows = [
            ("Work items completed", j.get("closed")),
            (
                "High or urgent priority items completed",
                f"{j.get('high_closed')} of {j.get('high_touched')} handled this year",
            ),
        ]
        if j.get("median_days_new_work") is not None:
            rows.append(
                (
                    "Typical turnaround on new requests",
                    f"{j['median_days_new_work']:g} days (median)",
                )
            )
        if j.get("aged_cleared"):
            rows.append(("Long-standing items resolved (open 6+ months)", j.get("aged_cleared")))
        if j.get("reported_by_them"):
            rows.append(("Work items they identified and raised", j.get("reported_by_them")))
        qs = j.get("quarters") or {}
        if qs:
            rows.append(
                (
                    "Completed by quarter",
                    ", ".join(f"{q}: {v.get('closed')}" for q, v in qs.items()),
                )
            )
        _table(doc, ["Measure", "Value"], rows)

    for s in rest:
        doc.add_heading(s["title"], 1)
        _add_text(doc, rec["sections"].get(s["key"]))

    buf = io.BytesIO()
    doc.save(buf)
    data = buf.getvalue()
    name = f"{year}-annual-review-{_slug(person)}.docx"
    # Personnel record: owner-only, same as the review store itself.
    out_dir = ARCHIVE / year
    out_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(ARCHIVE, 0o700)
    os.chmod(out_dir, 0o700)
    out = out_dir / name
    tmp = out.with_suffix(".docx.tmp")
    tmp.write_bytes(data)
    os.chmod(tmp, 0o600)
    os.replace(tmp, out)
    return name, data


if __name__ == "__main__":
    print(json.dumps({k: v for k, v in get_all().items() if k != "reviews"}, indent=2))
