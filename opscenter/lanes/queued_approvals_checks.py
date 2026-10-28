"""Synthetic tests for queued_approvals.py duplicate protection. Scratch dirs and fake binaries only."""

import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "queued_approvals.py")


def write(path, text, mode="w"):
    with open(path, mode) as fh:
        fh.write(text)


def lines(path):
    with open(path) as fh:
        return fh.readlines()


def load(path):
    with open(path) as fh:
        return json.load(fh)


def dump(obj, path):
    with open(path, "w") as fh:
        json.dump(obj, fh)


root = tempfile.mkdtemp(prefix="aqa-test-")
dash = os.path.join(root, "dash")
os.makedirs(os.path.join(dash, "proposals"))
calls = os.path.join(root, "calls.log")
write(
    os.path.join(root, "guard-config.json"),
    json.dumps({"allowed_roots": {"4800": "tree a", "6200": "tree b"}}),
)

# Fake driver: CQL behaviour keyed on title, getConfluencePage echoes what the fake guard "created".
write(
    os.path.join(root, "driver.py"),
    r"""
import json, sys, os
tool, args = sys.argv[1], json.loads(sys.argv[2])
open(os.environ["CALLS"], "a").write(tool + " " + json.dumps(args)[:200] + "\n")
def out(o): print(json.dumps({"result": {"content": [{"text": json.dumps(o)}]}}))
if tool == "searchConfluenceUsingCql":
    q = args["cql"]
    if "LOOKUPFAIL" in q: print("garbage"); sys.exit(0)
    if '"Existing Page"' in q: out({"results": [{"content": {"id": "111", "title": "Existing Page", "status": "current"}}]}); sys.exit(0)
    if '"Phrase Page"' in q: out({"results": [{"content": {"id": "222", "title": "Phrase Page - Extra", "status": "current"}}]}); sys.exit(0)
    out({"results": []})
elif tool == "getConfluencePage":
    titles = {"900": "New Page", "901": "Clash Page (2)", "902": "Phrase Page", "903": "Upd Page"}
    out({"status": "current", "parentId": "5", "title": titles[args["pageId"]]})
""",
)
write(
    os.path.join(root, "guard.py"),
    r"""
import json, sys, os
tool, args = sys.argv[2], json.loads(sys.argv[3])
open(os.environ["CALLS"], "a").write("GUARD " + tool + " " + args["title"] + "\n")
ids = {"New Page": "900", "Clash Page": "901", "Phrase Page": "902", "Upd Page": "903"}
print(json.dumps({"verdict": "ALLOW", "written": {"id": ids[args["title"]]}}))
""",
)

# fake doc audit. Logs its argv, fails with exit 2 when AUDIT_FAIL exists.
write(
    os.path.join(root, "audit.py"),
    r"""
import os, sys
open(os.environ["CALLS"], "a").write("AUDIT " + " ".join(sys.argv[1:]) + "\n")
if os.path.exists(os.environ["AUDIT_FAIL"]):
    print("Documentation audit FAILED, previous gap store kept: synthetic")
    sys.exit(2)
""",
)
AUDIT_FAIL = os.path.join(root, "audit-fail")

props, inbox = [], []
for i, t in enumerate(["New Page", "Existing Page", "LOOKUPFAIL", "Clash Page", "Phrase Page"]):
    fp = f"kc_test{i}"
    body = f"<p>synthetic {t}</p>"
    write(os.path.join(dash, "proposals", fp + ".body"), body)
    props.append({"fp": fp, "kind": "create", "target_title": t, "parent_id": "5"})
    inbox.append({"fp": fp, "act": "approved", "body_sha": hashlib.sha1(body.encode()).hexdigest()})
dump({"proposals": props}, os.path.join(dash, "docs-proposals.json"))
write(os.path.join(dash, "approve-inbox.jsonl"), "".join(json.dumps(q) + "\n" for q in inbox))

e = dict(
    os.environ,
    AQA_DASH=dash,
    AQA_GUARD=os.path.join(root, "guard.py"),
    DOCS_HOME_CMD=json.dumps([sys.executable, os.path.join(root, "driver.py")]),
    DOCS_GUARD_CONFIG=os.path.join(root, "guard-config.json"),
    AQA_AUDIT=os.path.join(root, "audit.py"),
    AUDIT_FAIL=AUDIT_FAIL,
    CALLS=calls,
)


def run():
    return subprocess.run([sys.executable, APP], env=e, capture_output=True, text=True)


# core-rule: scripting-python.1.5
# E: a held run lock means a second run does nothing.
with open(os.path.join(dash, ".apply-queued-approvals.lock"), "w") as lk:
    fcntl.flock(lk, fcntl.LOCK_EX)
    r = run()
    assert r.returncode == 0 and "holds the lock" in r.stderr and not r.stdout, r
    assert not os.path.exists(calls), "locked run must make no calls"
    fcntl.flock(lk, fcntl.LOCK_UN)

r = run()
print(r.stdout, r.stderr)
applied = {}
for ln in lines(os.path.join(dash, "approve-applied.jsonl")):
    a = json.loads(ln)
    applied[a["fp"]] = a
assert applied["kc_test0"]["result"] == "published"  # A
assert applied["kc_test1"]["result"] == "exists" and applied["kc_test1"]["page_id"] == "111"  # B
assert "kc_test2" not in applied  # C fails closed
assert applied["kc_test3"]["result"] == "duplicate_created"  # D
assert applied["kc_test4"]["result"] == "published"  # phrase match is not a clash
guarded = [ln for ln in lines(calls) if ln.startswith("GUARD")]
assert not any("Existing Page" in ln for ln in guarded), "existing title must never reach the guard"
left = [json.loads(ln)["fp"] for ln in lines(os.path.join(dash, "approve-inbox.jsonl"))]
assert left == ["kc_test2"], left


# O: a run that publishes refreshes the doc audit once, after the run, waiting on its lock.
def audits():
    return [ln for ln in lines(calls) if ln.startswith("AUDIT")]


assert audits() == ["AUDIT --wait-lock\n"], audits()
assert "DOC_AUDIT refreshed" in r.stdout and r.returncode == 0, r.stdout
# M: outcome rows now carry the approved body_sha.
assert applied["kc_test0"]["body_sha"] == inbox[0]["body_sha"], applied["kc_test0"]

# F: a re-run publishes nothing new.
n_guard = len(guarded)
r = run()
assert len([ln for ln in lines(calls) if ln.startswith("GUARD")]) == n_guard, (
    "re-run must not create again"
)
assert len(audits()) == 1, "a run with no write must not re-run the audit"
# G: finished proposals leave the staged store, the failed-closed one stays pending.
store = [p["fp"] for p in load(os.path.join(dash, "docs-proposals.json"))["proposals"]]
assert store == ["kc_test2"], store

# H: an empty inbox still prunes a finished proposal left behind by an older run.
write(os.path.join(dash, "approve-inbox.jsonl"), "")
dump(
    {
        "proposals": [
            {"fp": "kc_test0", "kind": "create", "target_title": "New Page"},
            {"fp": "kc_fresh", "kind": "create", "target_title": "Fresh"},
        ],
        "note": "keep",
    },
    os.path.join(dash, "docs-proposals.json"),
)
r = run()
assert r.returncode == 0 and not r.stdout, r
st = load(os.path.join(dash, "docs-proposals.json"))
assert [p["fp"] for p in st["proposals"]] == ["kc_fresh"] and st["note"] == "keep", st
# a re-staged update under an fp that already has an outcome row.
APPLIED_F = os.path.join(dash, "approve-applied.jsonl")
STORE_F = os.path.join(dash, "docs-proposals.json")
INBOX_F = os.path.join(dash, "approve-inbox.jsonl")


def guards():
    return len([ln for ln in lines(calls) if ln.startswith("GUARD")])


def stage_upd(fp, body, created):
    write(os.path.join(dash, "proposals", fp + ".body"), body)
    sha = hashlib.sha1(body.encode()).hexdigest()
    st = load(STORE_F)
    st["proposals"] = [p for p in st["proposals"] if p["fp"] != fp] + [
        {
            "fp": fp,
            "kind": "update",
            "target_id": "903",
            "target_title": "Upd Page",
            "body_sha": sha,
            "created_utc": created,
        }
    ]
    dump(st, STORE_F)
    return sha


# the owner: legacy row (no body_sha, 2026-08-10) + re-stage staged later, approved -> publishes, with a visible line.
write(
    APPLIED_F,
    json.dumps(
        {"fp": "kc_upd", "result": "published", "page_id": "903", "when": "2026-08-10T14:25:15Z"}
    )
    + "\n",
    "a",
)
sha_i = stage_upd("kc_upd", "<p>restaged v2</p>", "2026-10-11T14:55:00Z")
# L: an empty-inbox run must NOT prune the re-stage (the 10/11 bug pruned it before anyone saw it).
write(INBOX_F, "")
r = run()
assert "kc_upd" in [p["fp"] for p in load(STORE_F)["proposals"]], "re-stage was pruned"
n = guards()
write(INBOX_F, json.dumps({"fp": "kc_upd", "act": "approved", "body_sha": sha_i}) + "\n")
r = run()
assert guards() == n + 1, ("re-stage must publish", r.stdout, r.stderr)
assert "PUBLISHED" in r.stdout, r.stdout
rows = [json.loads(x) for x in lines(APPLIED_F) if '"kc_upd"' in x]
assert rows[-1]["body_sha"] == sha_i and rows[-1]["result"] == "published", rows
# J: approving the same content again is ALREADY_APPLIED and loud, with no write.
n = guards()
write(INBOX_F, json.dumps({"fp": "kc_upd", "act": "approved", "body_sha": sha_i}) + "\n")
r = run()
assert guards() == n and "ALREADY_APPLIED" in r.stdout, r.stdout
assert lines(INBOX_F) == [], "finished decision must leave the inbox"
n_audit = len(audits())
# K: legacy row newer than the proposal (stale left-behind) -> finished, pruned, never published.
write(
    APPLIED_F,
    json.dumps(
        {"fp": "kc_old", "result": "published", "page_id": "903", "when": "2026-10-12T00:00:00Z"}
    )
    + "\n",
    "a",
)
sha_k = stage_upd("kc_old", "<p>old</p>", "2026-10-11T00:00:00Z")
n = guards()
write(INBOX_F, json.dumps({"fp": "kc_old", "act": "approved", "body_sha": sha_k}) + "\n")
r = run()
assert guards() == n and "ALREADY_APPLIED" in r.stdout, r.stdout
assert "kc_old" not in [p["fp"] for p in load(STORE_F)["proposals"]], (
    "stale proposal must be pruned"
)
assert len(audits()) == n_audit, "ALREADY_APPLIED and stale prune must not re-run the audit"
# N: second re-stage after a body_sha row -> new content publishes again.
sha_n = stage_upd("kc_upd", "<p>restaged v3</p>", "2026-10-15T13:00:00Z")
n = guards()
write(INBOX_F, json.dumps({"fp": "kc_upd", "act": "approved", "body_sha": sha_n}) + "\n")
write(AUDIT_FAIL, "1")  # P: a failed audit is one loud line, the publish still stands, exit 0
r = run()
assert guards() == n + 1, r.stdout
assert (
    len(audits()) == n_audit + 1 and "DOC_AUDIT FAILED (exit 2)" in r.stdout and r.returncode == 0
), r.stdout
os.remove(AUDIT_FAIL)

# Q: a synthetic dash with no AQA_AUDIT never reaches the real audit.
e_noaudit = {k: v for k, v in e.items() if k != "AQA_AUDIT"}
sha_q = stage_upd("kc_upd", "<p>restaged v4</p>", "2026-10-16T13:00:00Z")
write(INBOX_F, json.dumps({"fp": "kc_upd", "act": "approved", "body_sha": sha_q}) + "\n")
r = subprocess.run([sys.executable, APP], env=e_noaudit, capture_output=True, text=True)
assert "PUBLISHED" in r.stdout and "DOC_AUDIT" not in r.stdout, r.stdout

# Unit: shared predicate edge cases.
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "engine"))
from applied_log import is_finished  # noqa: E402

ix = {
    "a": [{"fp": "a", "result": "rejected", "when": None}],
    "b": [{"fp": "b", "body_sha": "x", "when": "2026-10-15T00:00:00Z"}],
}
assert is_finished(ix, "a", "s1", "2026-10-15T00:00:00Z"), (
    "legacy row with no time never re-publishes"
)
assert is_finished(ix, "a", None, None) and not is_finished(ix, "zz", "s", "t")
assert is_finished(ix, "b", "x", "2099") and not is_finished(ix, "b", "y", "2000")
print("ALL TESTS PASSED", root)
