#!/usr/bin/env python3
"""
queued_approvals.py (the queued docs approvals applier, ops center item 7)

Purpose:
  Drain the dashboard approval inbox (approve-inbox.jsonl) and apply each queued docs approval THROUGH docs_write_guard.py,
  then verify each write landed by reading the page back. Run on a short cron cadence so a dashboard click takes effect within
  about a minute.

  This is the ONLY component that writes to the docs home. The listener just queues, the guard enforces scope and
  directionality, this applier verifies shas and reads back every page.

  Duplicate page protection:
    1. One run at a time. The whole run holds an exclusive non blocking flock on .apply-queued-approvals.lock. A second run
       exits 0 at once with one skip line on stderr.
    2. Each fp is recorded in approve-applied.jsonl the moment it publishes, not at the end of the run, so a crash mid run
       never re-publishes the earlier pages.
    3. Before every create, the title is looked up under the guard's allowed roots. A page that already exists is never
       created again: the fp is recorded as "exists" with the live page id and the owner is told to stage an update. A failed
       lookup fails closed (the decision stays queued for the next run).
    4. After every create, the read back title must equal the requested title. A docs home that suffixes a clashing title
       (" (2)") shows as a mismatch, recorded as "duplicate_created" and printed loudly.

  Re-staged updates: "finished" is decided per content, not per fp, by engine/applied_log.is_finished (shared with the
  Knowledge view). Outcome rows carry body_sha, so a corrected re-stage under a recorded fp publishes. An approval already done
  prints an ALREADY_APPLIED line instead of vanishing.

  Per class publish mode: knowledge-curation-config.json holds class_modes (engine/publish_mode.py). The one class is
  changelog_append. The default is staged, which changes nothing. When the owner sets it to auto, a staged changelog append is
  treated as approved when the live page is read, its version is known and the new body only ADDS lines to it. Anything else
  stays staged for the normal batch approval. All of it runs inside the same run lock, inbox lock and per fp recording.

  Coverage refresh: when a run writes a page, the optional AQA_AUDIT command (the consumer's documentation audit) re-runs right
  after the run lock is released, bounded by a timeout; a failure prints one DOC_AUDIT line without changing the exit code.

The docs home adapter (a slot that defaults to nothing): reads and title lookups go through DOCS_HOME_CMD, a JSON list that
runs one call (`<cmd> <tool> '<json args>'` prints the JSON-RPC result, the same driver contract as the work tracker, DESIGN.md
12.15), and writes go through the guard (AQA_GUARD, default the guard beside this file, configured by DOCS_GUARD_CONFIG and its
token provider). With no adapter every read fails, so nothing is applied: the inbox is left as it was. Silent when the inbox
is empty (cron friendly): prints nothing, exits 0.
"""

import datetime as dt
import fcntl
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "engine"))
import publish_mode as pm  # noqa: E402
from applied_log import is_finished, load_index, staged_utc  # noqa: E402

DASH = os.environ.get("AQA_DASH") or os.path.join(
    os.environ.get("OPSCENTER_STATE_DIR") or os.path.expanduser("~/.opscenter/state"), "dashboard"
)
INBOX = os.path.join(DASH, "approve-inbox.jsonl")
INBOX_LOCK = os.path.join(DASH, ".approve-inbox.lock")
RUN_LOCK = os.path.join(DASH, ".apply-queued-approvals.lock")
APPLIED = os.path.join(DASH, "approve-applied.jsonl")
PROP_DIR = os.path.join(DASH, "proposals")
PROPOSALS = os.path.join(DASH, "docs-proposals.json")
CONFIG = os.path.join(DASH, "knowledge-curation-config.json")
HELD = os.path.join(DASH, ".auto-publish-held.json")  # fp -> body_sha already reported as held
PROPOSALS_LOCK = os.path.join(DASH, ".docs-proposals.lock")  # the builders' lock
GUARD = os.environ.get("AQA_GUARD") or os.path.join(HERE, "docs_write_guard.py")
try:
    _cmd = json.loads(os.environ.get("DOCS_HOME_CMD") or "[]")
except ValueError:
    _cmd = []
DRIVER_CMD = [str(a) for a in _cmd] if isinstance(_cmd, list) else []
# The coverage refresh command (the consumer's documentation audit), none by default, and never for a synthetic AQA_DASH.
AUDIT = os.environ.get("AQA_AUDIT") or None
AUDIT_TIMEOUT = 900
WROTE_RESULTS = ("published", "duplicate_created")
CID = os.environ.get("DOCS_CLOUD_ID", "")


def _guard_roots():
    """The guard's allowed roots: a create can only land under one of them, so a title lookup is scoped to them."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "docs_write_guard_cfg", os.path.join(HERE, "docs_write_guard.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return tuple(mod.load_config()["allowed_roots"])


def env():
    return dict(os.environ)


def now_utc():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_inbox():
    if not os.path.exists(INBOX):
        return []
    out = []
    for ln in Path(INBOX).read_text().splitlines(True):
        ln = ln.strip()
        if ln:
            try:  # noqa: SIM105
                out.append(json.loads(ln))
            except ValueError:
                pass
    return out


def load_proposals():
    try:
        return {p["fp"]: p for p in json.load(open(PROPOSALS))["proposals"]}
    except (OSError, ValueError, KeyError):
        return {}


def prune_finished(idx):
    """Drop proposals whose content already has an outcome from the staged store, under the
    builders' lock, so nothing published or rejected keeps showing as pending anywhere. A
    re-stage under a recorded fp (new body) stays. Returns the fps removed."""
    if not idx or not os.path.exists(PROPOSALS):
        return []
    with open(PROPOSALS_LOCK, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            with open(PROPOSALS) as fh:
                store = json.load(fh)
        except (OSError, ValueError) as exc:
            print(f"queued_approvals: prune skipped, proposals unreadable: {exc}", file=sys.stderr)
            return []
        props = store.get("proposals", []) if isinstance(store, dict) else []

        def done(p):
            return is_finished(idx, p.get("fp"), p.get("body_sha"), staged_utc(p))

        removed = [p.get("fp") for p in props if done(p)]
        if not removed:
            return []
        store["proposals"] = [p for p in props if not done(p)]
        tmp = PROPOSALS + ".tmp"
        with open(tmp, "w") as f:
            json.dump(store, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, PROPOSALS)
    return removed


def record_applied(row):
    """Append one result row immediately (flush + fsync) so a crash cannot lose it."""
    with open(APPLIED, "a") as f:
        f.write(json.dumps(row) + "\n")
        f.flush()
        os.fsync(f.fileno())


def driver_text(tool, args):
    """Call the docs home driver (DOCS_HOME_CMD) and return the parsed inner JSON, or raise."""
    if not DRIVER_CMD:
        raise RuntimeError("no docs home adapter is configured (DOCS_HOME_CMD)")
    p = subprocess.run(
        [*DRIVER_CMD, tool, json.dumps(args)],
        capture_output=True,
        text=True,
        env=env(),
        timeout=120,
    )
    return json.loads(json.loads(p.stdout)["result"]["content"][0]["text"])


def verify_page(page_id):
    """Read the page back. Return (ok, title/parent/status) or (False, err)."""
    try:
        o = driver_text("getConfluencePage", {"cloudId": CID, "pageId": str(page_id)})
    except Exception as e:  # noqa: BLE001 - any failure is a failed read-back
        return False, f"readback parse error: {e}"
    if o.get("error"):
        return False, o.get("message", "")[:120]
    return True, {
        "status": o.get("status"),
        "parent": o.get("parentId"),
        "title": o.get("title"),
        "version": pm.version_number(o),
    }


def live_page_html(page_id):
    """(ok, page dict or error text). The live page as HTML, for the auto-publish checks."""
    try:
        o = driver_text(
            "getConfluencePage", {"cloudId": CID, "pageId": str(page_id), "contentFormat": "html"}
        )
    except Exception as e:  # noqa: BLE001 - any failure is a failed read
        return False, f"live read failed: {e}"
    if not isinstance(o, dict) or o.get("error") or not isinstance(o.get("body"), str):
        return False, f"live read returned no body: {str(o)[:100]}"
    return True, o


def auto_candidates(proposals, idx, queued_fps):
    """Synthetic approvals for staged proposals whose class is set to auto. Empty (so nothing
    changes) unless the config says auto, and a config that cannot be read means staged."""
    modes = pm.class_modes(CONFIG)
    out = []
    for fp, p in proposals.items():
        cls = pm.classify(p)
        if not cls or modes.get(cls) != "auto" or fp in queued_fps:
            continue
        sha = p.get("body_sha")
        if not sha or is_finished(idx, fp, sha, staged_utc(p)):
            continue
        out.append({"fp": fp, "act": "approved", "body_sha": sha, "auto": True, "class": cls})
    return out


def held_note(fp, sha, why, results):
    """Report an auto candidate that stays staged, once per content (the cron runs every minute)."""
    try:
        with open(HELD) as fh:
            held = json.load(fh)
    except (OSError, ValueError):
        held = {}
    if held.get(fp) == sha + why[:40]:
        return
    held[fp] = sha + why[:40]
    tmp = HELD + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(held, fh)
    os.replace(tmp, HELD)
    results.append((fp, "AUTO_HELD", f"stays staged for a batch approval: {why}"[:160]))


def find_existing(title):
    """Return (ok, [page ids]) of current pages titled exactly `title` in the guarded trees.
    ok=False on any read failure (callers fail closed)."""
    safe = title.replace("\\", "\\\\").replace('"', '\\"')
    scope = _guard_roots()
    if not scope:
        return False, "title lookup failed: the guard has no allowed roots"
    roots = " OR ".join(f"ancestor = {r}" for r in scope)
    cql = f'type = page AND title = "{safe}" AND ({roots})'
    try:
        o = driver_text("searchConfluenceUsingCql", {"cloudId": CID, "cql": cql, "limit": 25})
    except Exception as e:  # noqa: BLE001
        return False, f"title lookup failed: {e}"
    if not isinstance(o, dict) or "results" not in o:
        return False, f"title lookup returned no results field: {str(o)[:120]}"
    ids = []
    for r in o["results"]:
        c = r.get("content", r)
        # CQL title = is a phrase match, so confirm the exact title before treating it as a clash.
        if c.get("title", "").strip() == title.strip() and c.get("status", "current") == "current":
            ids.append(str(c.get("id")))
    return True, ids


def main():
    # The run lock is held for the whole run and released when the handle closes.
    with open(RUN_LOCK, "w") as lk:
        try:
            fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("queued_approvals: another run holds the lock, skipping", file=sys.stderr)
            return 0
        rc, wrote = _run_locked()
    if wrote:
        refresh_doc_audit()
    return rc


def refresh_doc_audit():
    """re-run the doc audit after a page write so coverage matches the publish."""
    if not AUDIT:
        return
    stamp = dt.datetime.now().isoformat(timespec="seconds")
    try:
        p = subprocess.run(
            ([sys.executable, AUDIT] if AUDIT.endswith(".py") else AUDIT.split()) + ["--wait-lock"],
            capture_output=True,
            text=True,
            env=env(),
            timeout=AUDIT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        print(
            f"[queued_approvals {stamp}] DOC_AUDIT FAILED: timed out after {AUDIT_TIMEOUT}s, gap store kept"
        )
        return
    except OSError as e:
        print(f"[queued_approvals {stamp}] DOC_AUDIT FAILED: {e}")
        return
    if p.returncode != 0:
        why = (p.stdout.strip() or p.stderr.strip() or f"exit {p.returncode}").splitlines()[-1][
            :200
        ]
        print(f"[queued_approvals {stamp}] DOC_AUDIT FAILED (exit {p.returncode}): {why}")
        return
    print(f"[queued_approvals {stamp}] DOC_AUDIT refreshed after publish")


def _run_locked():
    queued = read_inbox()
    proposals = load_proposals()
    idx = load_index(APPLIED)
    # staged proposals of a class set to auto join the run as synthetic approvals. They
    # are never written to the inbox, so a failed or held one simply stays staged.
    auto = auto_candidates(proposals, idx, {q.get("fp") for q in queued})
    if not queued and not auto:
        prune_finished(load_index(APPLIED))  # silent: also clears anything finished by an older run
        return 0, False
    queued = queued + auto

    results = []
    wrote = False  # any page written this run triggers the coverage refresh
    done_fps = set()  # fps to remove from the inbox (finished, one way or another)
    for q in queued:
        fp = q.get("fp")
        if not fp:
            continue
        prop = proposals.get(fp)
        if is_finished(idx, fp, q.get("body_sha"), staged_utc(prop)):
            done_fps.add(fp)
            rows = idx.get(fp, [])
            last = rows[-1] if rows else {}
            results.append(
                (
                    fp,
                    "ALREADY_APPLIED",
                    f"{last.get('result')} {last.get('page_id', '')} at {last.get('when')}".strip(),
                )
            )
            continue
        act = q.get("act", "approved")
        if act == "rejected":
            row = {
                "fp": fp,
                "result": "rejected",
                "when": q.get("queued_utc") or now_utc(),
                "reason": q.get("reason", ""),
            }
            row["body_sha"] = q.get("body_sha")
            record_applied(row)
            idx.setdefault(fp, []).append(row)
            done_fps.add(fp)
            continue
        bp = os.path.join(PROP_DIR, fp + ".body")
        if q.get("auto") and (
            not prop
            or not os.path.exists(bp)
            or hashlib.sha1(Path(bp).read_bytes()).hexdigest() != q.get("body_sha")
        ):
            continue  # an auto candidate with no usable body just stays staged, silently
        if not prop or not os.path.exists(bp):
            results.append((fp, "SKIP", "no matching proposal/body (already applied or cleared)"))
            done_fps.add(fp)
            continue
        body = Path(bp).read_text()
        if hashlib.sha1(body.encode()).hexdigest() != q.get("body_sha"):
            results.append((fp, "SKIP", "body_sha mismatch: proposal changed since approval"))
            done_fps.add(fp)
            continue
        title = prop["target_title"]
        auto_meta = {}
        if q.get("auto"):
            # Fail closed: the live page must read, carry a version and gain lines only.
            ok, live = live_page_html(prop["target_id"])
            if not ok:
                held_note(fp, q["body_sha"], str(live), results)
                continue
            before = pm.version_number(live)
            if before is None:
                held_note(fp, q["body_sha"], "live page version unreadable", results)
                continue
            if (live.get("title") or "").strip() != title.strip():
                held_note(fp, q["body_sha"], "live title differs from the proposal", results)
                continue
            ok, why = pm.is_append_only(live["body"], body)
            if not ok:
                held_note(fp, q["body_sha"], why, results)
                continue
            auto_meta = {
                "auto": True,
                "class": q["class"],
                "version_before": before,
                "revert_url": pm.version_url(prop["target_id"], before),
                "history_url": pm.history_url(prop["target_id"]),
            }
        tool = "createConfluencePage" if prop["kind"] == "create" else "updateConfluencePage"
        args = {"title": title, "body": body}
        if prop["kind"] == "create":
            ok, existing = find_existing(title)
            if not ok:
                # Fail closed: leave the decision queued and try again next run.
                results.append((fp, "RETRY", str(existing)[:120]))
                continue
            if existing:
                row = {
                    "fp": fp,
                    "result": "exists",
                    "page_id": existing[0],
                    "title": title,
                    "when": now_utc(),
                }
                row["body_sha"] = q.get("body_sha")
                record_applied(row)
                idx.setdefault(fp, []).append(row)
                done_fps.add(fp)
                results.append(
                    (
                        fp,
                        "EXISTS",
                        f"'{title}' already published as {','.join(existing)}, not created again. "
                        "Stage an update keyed on that page id instead.",
                    )
                )
                continue
            args["parentId"] = prop["parent_id"]
        else:
            args["pageId"] = prop["target_id"]
            # A move rides on an update (the guard checks the page and the new parent).
            if prop.get("new_parent_id"):
                args["parentId"] = prop["new_parent_id"]
        p = subprocess.run(
            [sys.executable, GUARD, "execute", tool, json.dumps(args)],
            capture_output=True,
            text=True,
            env=env(),
        )
        try:
            out = json.loads(p.stdout)
        except ValueError:
            out = {"verdict": "PARSE_ERR", "raw": p.stdout[:200] + p.stderr[:200]}
        verdict = out.get("verdict")
        if verdict != "ALLOW":
            results.append((fp, verdict, str(out.get("write_error") or out.get("reason"))[:100]))
            done_fps.add(fp)
            continue
        written = out.get("written", {})
        pid = written.get("id") if isinstance(written, dict) else None
        ok, info = verify_page(pid) if pid else (False, "no id returned")
        if not ok:
            results.append((fp, "VERIFY_FAILED", str(info)[:100]))
            done_fps.add(fp)
            continue
        got_title = (info.get("title") or "").strip()
        result = "published" if got_title == title.strip() else "duplicate_created"
        row = {"fp": fp, "result": result, "page_id": pid, "title": title, "when": now_utc()}
        row["body_sha"] = q.get("body_sha")
        if auto_meta:
            row.update(auto_meta)
            row["version_after"] = info.get("version")
            va, vb = row["version_after"], row["version_before"]
            if va is None or va != vb + 1:
                row["concurrent_edit"] = True  # someone else saved between our read and write
        record_applied(row)
        idx.setdefault(fp, []).append(row)
        done_fps.add(fp)
        wrote = wrote or result in WROTE_RESULTS
        if result == "published":
            tag = "AUTO_PUBLISHED" if auto_meta else "PUBLISHED"
            note = f" versions {row['version_before']}->{row['version_after']}" if auto_meta else ""
            if row.get("concurrent_edit"):
                note += " CONCURRENT_EDIT (check the page history)"
            results.append((fp, tag, f"id={pid} {info}{note}"))
        else:
            results.append(
                (
                    fp,
                    "DUPLICATE_CREATED",
                    f"The docs home titled it '{got_title}' (id={pid}), so '{title}' already "
                    "existed. Delete the copy and stage an update instead.",
                )
            )
        try:  # noqa: SIM105
            os.remove(bp)  # clear the applied body file
        except OSError:
            pass

    # Re-read the inbox under the shared lock before rewriting it. Decisions the ops center
    # appended while this run was publishing must survive (an earlier version rewrote the
    # file from its start-of-run snapshot and silently dropped them).
    with open(INBOX_LOCK, "w") as ilk:
        fcntl.flock(ilk, fcntl.LOCK_EX)
        remaining = [q for q in read_inbox() if q.get("fp") not in done_fps]
        tmp = INBOX + ".tmp"
        with open(tmp, "w") as f:
            for q in remaining:
                f.write(json.dumps(q) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, INBOX)

    pruned = prune_finished(load_index(APPLIED))
    if pruned:
        results.append(
            ("-", "PRUNED", f"{len(pruned)} finished proposal(s) dropped from the staged store")
        )

    if results:
        print(f"[queued_approvals {dt.datetime.now().isoformat(timespec='seconds')}]")
        for r in results:
            print("  ", r)
    return 0, wrote


if __name__ == "__main__":
    sys.exit(main())
