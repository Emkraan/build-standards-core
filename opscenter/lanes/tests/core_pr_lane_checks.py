#!/usr/bin/env python3
"""
tests/core_pr_lane_checks.py
Purpose: Synthetic tests for core_pr_lane.py. Each scenario builds a scratch bare origin with tags,
         a CHANGELOG and checks/*.py, a local clone, PR heads under refs/pull/N/head and a fake gh
         that answers pr list, pr merge, pr view and release create from files. No network.
Date:    2026-10-14
Usage:   /usr/bin/python3 tests/core_pr_lane_checks.py   (exit 0 when every expectation passes)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent  # the lanes folder
LANE = HERE / "core_pr_lane.py"
ROOT = Path(tempfile.mkdtemp(prefix="corelane-test-"))
NOW = "2026-10-14T12:00:00Z"
OLD = "2026-10-14T11:00:00+00:00"
NEW = "2026-10-14T11:55:00+00:00"
fails = 0

FAKE_GH = r"""#!/usr/bin/env python3
import json, os, subprocess, sys
d = os.environ["FAKE_DIR"]
a = sys.argv[1:]
open(os.path.join(d, "calls.log"), "a").write(json.dumps(a) + "\n")
if os.environ.get("FAKE_FAIL"):
    sys.stderr.write("HTTP 502")
    sys.exit(1)
merged_f = os.path.join(d, "merged.json")
merged = json.load(open(merged_f)) if os.path.exists(merged_f) else {}
origin = os.environ["FAKE_ORIGIN"]
if a[:2] == ["pr", "list"]:
    prs = json.load(open(os.path.join(d, "prs.json")))
    print(json.dumps([p for p in prs if str(p["number"]) not in merged]))
elif a[:2] == ["pr", "merge"]:
    if os.environ.get("FAKE_MERGE_FAIL"):
        sys.stderr.write("Pull request is not mergeable")
        sys.exit(1)
    sha = a[a.index("--match-head-commit") + 1]
    subprocess.run(["git", "-C", origin, "update-ref", "refs/heads/main", sha], check=True)
    merged[a[2]] = sha
    json.dump(merged, open(merged_f, "w"))
elif a[:2] == ["pr", "view"]:
    state = os.environ.get("FAKE_VIEW_STATE") or ("MERGED" if a[2] in merged else "OPEN")
    print(json.dumps({"state": state, "mergeCommit": {"oid": merged.get(a[2], "")} if a[2] in merged else None}))
elif a[:2] == ["release", "create"]:
    subprocess.run(["git", "-C", origin, "tag", a[2], "refs/heads/main"], check=True)
elif a[:2] == ["pr", "edit"]:
    if os.environ.get("FAKE_EDIT_FAIL"):
        sys.stderr.write("HTTP 403")
        sys.exit(1)
    prs = json.load(open(os.path.join(d, "prs.json")))
    for p in prs:
        if str(p["number"]) == a[2]:
            p.setdefault("labels", []).append({"name": a[a.index("--add-label") + 1]})
    json.dump(prs, open(os.path.join(d, "prs.json"), "w"))
else:
    sys.stderr.write("unexpected gh call")
    sys.exit(9)
"""

CHECK_SANITISED = """import subprocess, sys
bad = []
for f in subprocess.run(['git', 'ls-files'], capture_output=True, text=True).stdout.split():
    if not f.startswith('checks/') and 'ACMECORP' in open(f).read():
        bad.append(f)
print('hits', bad)
sys.exit(1 if bad else 0)
"""
CHECK_ASCII = """import subprocess, sys
bad = [f for f in subprocess.run(['git', 'ls-files'], capture_output=True, text=True).stdout.split()
       if any(ord(c) > 127 for c in open(f, encoding='utf8').read())]
print('non-ascii', bad)
sys.exit(1 if bad else 0)
"""
CHANGELOG = "# Changelog\n\n## 2026-10-13 (v0.1.0, first)\n\n- First release.\n"


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + ("" if cond or not detail else f"  [{detail}]"))
    if not cond:
        fails += 1


def sh(args, cwd=None, env=None):
    e = dict(os.environ)
    e.update(env or {})
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, env=e)
    if p.returncode != 0:
        raise RuntimeError(f"{args}: {p.stderr}")
    return p.stdout.strip()


GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}


class Fx:
    """One scenario fixture: origin, seed work repo, local clone, fake gh, cache, policy."""

    count = 0

    def __init__(self):
        Fx.count += 1
        self.d = ROOT / f"s{Fx.count}"
        self.d.mkdir()
        self.origin = self.d / "origin.git"
        self.seed = self.d / "seed"
        self.clone = self.d / "clone"
        self.cache = self.d / "cache"
        self.policy = self.d / "lane-policy.json"
        (self.d / "autofix-targets.json").write_text(
            json.dumps(
                {
                    "skills": [],
                    "targets": {
                        "core": {
                            "repo": "owner/core",
                            "skill": "core-skill",
                            "notes": "This is the core standards repo. Use skill core-skill for how to change the code.",
                            "identity": "owner <user-id+owner-account@users.noreply.github.com>",
                            "extra_fixable": [
                                ["local checks fail", "local-checks"],
                                ["version needs a bump", "version-bump"],
                                ["changelog entry", "changelog"],
                            ],
                        }
                    },
                }
            )
        )
        self.synclog = self.d / "sync.log"
        self.prs = []
        sh(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)])
        sh(["git", "init", "-q", "-b", "main", str(self.seed)])
        (self.seed / "checks").mkdir()
        (self.seed / "checks" / "check-sanitised.py").write_text(CHECK_SANITISED)
        (self.seed / "checks" / "check-ascii.py").write_text(CHECK_ASCII)
        (self.seed / "CHANGELOG.md").write_text(CHANGELOG)
        (self.seed / "README.md").write_text("# Core\n\nPlain prose.\n")
        self.commit("chore: seed", OLD)
        sh(["git", "remote", "add", "origin", str(self.origin)], cwd=self.seed)
        sh(["git", "push", "-q", "origin", "main"], cwd=self.seed)
        sh(["git", "tag", "v0.1.0"], cwd=self.seed)
        sh(["git", "push", "-q", "origin", "v0.1.0"], cwd=self.seed)
        sh(["git", "clone", "-q", str(self.origin), str(self.clone)])
        gh = self.d / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(0o755)
        self.gh = gh
        sync = self.d / "sync.sh"
        sync.write_text(f"#!/bin/bash\necho synced >> '{self.synclog}'\n")
        self.sync = sync
        self.write_prs()

    def commit(self, msg, date):
        sh(["git", "add", "-A"], cwd=self.seed)
        sh(
            ["git", "commit", "-q", "-m", msg],
            cwd=self.seed,
            env=dict(GIT_ENV, GIT_COMMITTER_DATE=date),
        )
        return sh(["git", "rev-parse", "HEAD"], cwd=self.seed)

    def make_head(self, n, version, date=OLD, extra=None, base="main"):
        """A PR head off origin main: a CHANGELOG heading for version plus extra files, pushed to refs/pull/n/head."""
        sh(["git", "fetch", "-q", "origin"], cwd=self.seed)
        sh(["git", "checkout", "-q", "-B", f"pr{n}", f"origin/{base}"], cwd=self.seed)
        if version:
            text = (self.seed / "CHANGELOG.md").read_text()
            entry = f"## 2026-10-14 (v{version}, change {n})\n\n- Change {n} line one.\n- Change {n} line two.\n\n"
            (self.seed / "CHANGELOG.md").write_text(
                text.replace("## 2026-10-13", entry + "## 2026-10-13", 1)
            )
        for name, body in (extra or {}).items():
            (self.seed / name).write_text(body)
        if not version and not extra:
            (self.seed / f"note{n}.txt").write_text(f"pr {n}\n")
        sha = self.commit(f"feat: change {n}", date)
        sh(["git", "push", "-q", "-f", "origin", f"HEAD:refs/pull/{n}/head"], cwd=self.seed)
        return sha

    def pr(self, n, sha, **kw):
        p = {
            "number": n,
            "title": f"feat: change {n}",
            "url": f"https://github.com/x/core/pull/{n}",
            "author": {"login": kw.get("author", "owner-account")},
            "baseRefName": kw.get("base", "main"),
            "headRefName": kw.get("branch", f"feat/change-{n}"),
            "headRefOid": sha,
            "isDraft": kw.get("draft", False),
            "labels": [{"name": x} for x in kw.get("labels", [])],
            "mergeStateStatus": kw.get("mss", "CLEAN"),
            "statusCheckRollup": kw.get(
                "checks",
                [
                    {
                        "name": "ci",
                        "workflowName": "checks",
                        "status": "COMPLETED",
                        "conclusion": "SUCCESS",
                        "completedAt": "2026-10-14T11:10:00Z",
                    }
                ],
            ),
            "createdAt": "2026-10-14T10:00:00Z",
        }
        self.prs = [x for x in self.prs if x["number"] != n] + [p]
        self.write_prs()

    def write_prs(self):
        (self.d / "prs.json").write_text(json.dumps(self.prs))

    def run(self, *args, now=NOW, **env):
        e = dict(os.environ)
        for k in ("CORELANE_DRY_RUN", "FAKE_FAIL", "FAKE_MERGE_FAIL", "FAKE_VIEW_STATE"):
            e.pop(k, None)
        for k in [k for k in e if k.startswith("OWNPR_")]:
            e.pop(k)
        e.update(
            {
                "CORELANE_GH_BIN": str(self.gh),
                "CORELANE_REPO_DIR": str(self.clone),
                "CORELANE_CACHE_DIR": str(self.cache),
                "CORELANE_POLICY": str(self.policy),
                "CORELANE_NOW": now,
                "CORELANE_SYNC_CMD": f"/bin/bash {self.sync}",
                "CORELANE_FIXER": str(HERE / "autofix.py"),
                "AUTOFIX_TARGETS": str(self.d / "autofix-targets.json"),
                # The fixer never spawns a session here and never reads the real session database.
                "OWNPR_FIX_SPAWN": "record",
                "OWNPR_STATE_DB": str(self.d / "no-state.db"),
                "OWNPR_CATALOG": str(self.d / "no-catalog.md"),
                "FAKE_DIR": str(self.d),
                "FAKE_ORIGIN": str(self.origin),
            }
        )
        e.update(env)
        p = subprocess.run(
            [sys.executable, str(LANE)] + list(args or ["tick"]),
            capture_output=True,
            text=True,
            env=e,
        )
        return p.returncode, p.stdout.strip(), p.stderr.strip()

    def calls(self, verb=None):
        f = self.d / "calls.log"
        rows = [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []
        return [r for r in rows if verb is None or r[:2] == verb]

    def state(self):
        f = self.cache / "lane-state.json"
        return json.loads(f.read_text()) if f.exists() else {}

    def prstate(self, n):
        return (self.state().get("prs") or {}).get(str(n)) or {}

    def origin_ref(self, ref):
        return sh(["git", "-C", str(self.origin), "rev-parse", ref])


MERGE = ["pr", "merge"]
RELEASE = ["release", "create"]


def t_green_quiet():
    f = Fx()
    md = "# Doc\n\nPlain prose here.\n\n```css\na { color: red; }\n```\n\nInline `x; y` and &middot; entity.\n"
    sha = f.make_head(5, "0.2.0", extra={"doc.md": md})
    f.pr(5, sha)
    rc, out, err = f.run()
    check(
        "green: first pass is quiet (waits one pass)",
        rc == 0 and out == "" and not f.calls(MERGE),
        out + err,
    )
    check(
        "green: first pass recorded as quiet wait",
        f.prstate(5).get("kind") == "quiet",
        f.prstate(5),
    )
    rc, out, err = f.run()
    check(
        "green: second pass prints one merged line",
        out == "[CORE LANE] merged #5 v0.2.0 feat: change 5",
        out + err,
    )
    m = f.calls(MERGE)
    check(
        "green: merge is squash, deletes branch, pinned to head",
        len(m) == 1
        and "--squash" in m[0]
        and "--delete-branch" in m[0]
        and m[0][m[0].index("--match-head-commit") + 1] == sha,
        m,
    )
    r = f.calls(RELEASE)
    check(
        "green: release v0.2.0 from main with changelog notes",
        len(r) == 1
        and r[0][2] == "v0.2.0"
        and r[0][r[0].index("--target") + 1] == "main"
        and "Change 5 line one" in r[0][r[0].index("--notes") + 1],
        r,
    )
    check("green: tag points at the merge commit", f.origin_ref("refs/tags/v0.2.0") == sha)
    check(
        "green: core skills sync ran once",
        f.synclog.exists() and f.synclog.read_text().count("synced") == 1,
    )
    check(
        "green: clean main clone was pulled",
        sh(["git", "-C", str(f.clone), "rev-parse", "HEAD"]) == sha,
    )
    rc, out, err = f.run()
    check(
        "green: third pass merges and releases nothing more",
        out == "" and len(f.calls(MERGE)) == 1 and len(f.calls(RELEASE)) == 1,
    )
    refs = sh(["git", "-C", str(f.clone), "for-each-ref", "refs/corelane/"])
    wts = sh(["git", "-C", str(f.clone), "worktree", "list"]).splitlines()
    check(
        "green: no lane refs or worktrees left in the clone",
        refs == "" and len(wts) == 1,
        refs + str(wts),
    )
    dec = [json.loads(x) for x in (f.cache / "decisions.jsonl").read_text().splitlines()]
    check(
        "green: decisions log carries merged and released with sha",
        any(d["decision"] == "merged" and d["sha"] == sha for d in dec)
        and any(d["decision"] == "released" for d in dec),
    )


def two_ticks_no_merge(f, label, status, kind):
    f.run()
    rc, out, err = f.run()
    rec = f.prstate(5)
    check(
        f"{label}: no merge after two passes",
        not f.calls(MERGE) and not f.calls(RELEASE),
        out + err,
    )
    check(
        f"{label}: recorded {status}/{kind}",
        rec.get("status") == status and rec.get("kind") == kind,
        rec,
    )
    check(f"{label}: tick stays silent", out == "", out)


def t_pending():
    f = Fx()
    sha = f.make_head(5, "0.2.0")
    f.pr(
        5,
        sha,
        checks=[
            {"name": "ci", "workflowName": "checks", "status": "IN_PROGRESS", "conclusion": ""}
        ],
    )
    two_ticks_no_merge(f, "pending", "waiting", "checks-pending")


def t_red():
    f = Fx()
    sha = f.make_head(5, "0.2.0")
    f.pr(
        5,
        sha,
        checks=[
            {
                "name": "ci",
                "workflowName": "checks",
                "conclusion": "SUCCESS",
                "completedAt": "2026-10-14T11:10:00Z",
            },
            {
                "name": "visual",
                "workflowName": "visual",
                "conclusion": "FAILURE",
                "completedAt": "2026-10-14T11:11:00Z",
            },
        ],
    )
    two_ticks_no_merge(f, "red", "held", "checks-red")


def t_dirty():
    f = Fx()
    sha = f.make_head(5, "0.2.0")
    f.pr(5, sha, mss="DIRTY")
    two_ticks_no_merge(f, "dirty", "held", "merge-state")


def t_too_new():
    f = Fx()
    sha = f.make_head(5, "0.2.0", date=NEW)
    f.pr(5, sha)
    two_ticks_no_merge(f, "too-new head", "waiting", "quiet")


def t_push_between():
    f = Fx()
    sha = f.make_head(5, "0.2.0")
    f.pr(5, sha)
    f.run()
    sha2 = f.make_head(5, "0.2.0", extra={"more.txt": "more\n"})
    f.pr(5, sha2)
    rc, out, err = f.run()
    rec = f.prstate(5)
    check(
        "push between passes: held back",
        not f.calls(MERGE) and "new push" in rec.get("reason", ""),
        rec,
    )
    sh(["git", "-C", str(f.clone), "checkout", "-q", "-b", "work"])
    rc, out, err = f.run()
    check(
        "push between passes: merges once the new head was seen twice",
        len(f.calls(MERGE)) == 1 and "merged #5" in out,
        out + err,
    )
    m = f.calls(MERGE)[0]
    check(
        "push between passes: merge pinned to the new head",
        m[m.index("--match-head-commit") + 1] == sha2,
    )
    branch = sh(["git", "-C", str(f.clone), "symbolic-ref", "--short", "HEAD"])
    check(
        "clone on another branch: left there, pull skipped",
        branch == "work" and f.state()["merges"][-1].get("pull"),
        f.state().get("merges"),
    )


def t_sanitise():
    f = Fx()
    sha = f.make_head(5, "0.2.0", extra={"leak.md": "This names ACMECORP.\n"})
    f.pr(5, sha)
    two_ticks_no_merge(f, "sanitise hit", "held", "local-checks")
    check(
        "sanitise hit: reason names the check",
        "check-sanitised.py" in f.prstate(5).get("reason", ""),
        f.prstate(5),
    )


def t_semicolon():
    f = Fx()
    sha = f.make_head(5, "0.2.0", extra={"doc.md": "# Doc\n\nOne clause; another clause.\n"})
    f.pr(5, sha)
    two_ticks_no_merge(f, "semicolon in prose", "held", "local-checks")
    check(
        "semicolon in prose: reason names file and line",
        "doc.md:3" in f.prstate(5).get("reason", ""),
        f.prstate(5),
    )


def t_version_not_greater():
    f = Fx()
    sha = f.make_head(5, "0.0.9")
    f.pr(5, sha)
    two_ticks_no_merge(f, "version not greater", "held", "version")
    check(
        "version not greater: reason says so",
        "not greater" in f.prstate(5).get("reason", ""),
        f.prstate(5),
    )


def t_no_heading():
    f = Fx()
    sha = f.make_head(5, None, extra={"x.txt": "x\n"})
    f.pr(5, sha)
    two_ticks_no_merge(f, "no changelog heading", "held", "changelog")


def t_same_version():
    f = Fx()
    s5 = f.make_head(5, "0.2.0")
    s6 = f.make_head(6, "0.2.0", extra={"other.txt": "o\n"})
    f.pr(6, s6)
    f.pr(5, s5)
    f.run()
    rc, out, err = f.run()
    m = f.calls(MERGE)
    check("same version: only the older PR merges", len(m) == 1 and m[0][2] == "5", m)
    rec6 = f.prstate(6)
    check(
        "same version: newer held with taken message",
        rec6.get("status") == "held"
        and "version v0.2.0 taken by #5, rebase and bump" in rec6.get("reason", ""),
        rec6,
    )
    rc, out, err = f.run()
    check(
        "same version: newer never merges on the next pass",
        len(f.calls(MERGE)) == 1 and f.prstate(6).get("kind") == "version",
    )


def t_skipped():
    f = Fx()
    shas = {n: f.make_head(n, f"0.{n}.0") for n in (5, 6, 7, 8, 9)}
    f.pr(5, shas[5], draft=True)
    f.pr(6, shas[6], labels=["do-not-merge"])
    f.pr(7, shas[7], author="someone-else")
    f.pr(8, shas[8], base="release")
    f.pr(9, shas[9], branch="feat/denied")
    f.policy.write_text(json.dumps({"branch_deny": ["feat/denied"]}))
    f.run()
    rc, out, err = f.run()
    check(
        "draft, label, foreign author, other base, denied branch: all skipped",
        not f.calls(MERGE) and not f.state().get("prs"),
        f.state(),
    )
    rc, out, err = f.run("check", "6")
    check("check on a labelled PR says skip", '"skip"' in out and "do-not-merge" in out, out + err)


def t_not_merged_state():
    f = Fx()
    sha = f.make_head(5, "0.2.0")
    f.pr(5, sha)
    f.run()
    rc, out, err = f.run(FAKE_VIEW_STATE="OPEN")
    check(
        "merge reported, state OPEN: no release",
        len(f.calls(MERGE)) == 1 and not f.calls(RELEASE),
        f.calls(),
    )
    check("merge reported, state OPEN: reported", "release skipped" in out, out)
    check("merge reported, state OPEN: sync not run", not f.synclog.exists())
    rc, out, err = f.run(FAKE_VIEW_STATE="OPEN")
    check(
        "merge reported, state OPEN: never retried on the same head",
        len(f.calls(MERGE)) == 1,
        f.calls(MERGE),
    )


def t_merge_refused():
    f = Fx()
    sha = f.make_head(5, "0.2.0")
    f.pr(5, sha)
    f.run()
    rc, out, err = f.run(FAKE_MERGE_FAIL="1")
    rec = f.prstate(5)
    check(
        "merge refused: held, no release",
        rec.get("kind") == "merge-refused" and not f.calls(RELEASE),
        rec,
    )
    f.run(FAKE_MERGE_FAIL="1")
    check("merge refused: not retried on the same head", len(f.calls(MERGE)) == 1)
    rc, out, err = f.run(now="2026-10-14T14:05:00Z")
    check(
        "merge refused: one line after 2 hours held",
        out.startswith("[CORE LANE] #5") and "held 2h" in out,
        out,
    )
    rc, out, err = f.run(now="2026-10-14T15:00:00Z")
    check("merge refused: not repeated within 12 hours", out == "", out)
    rc, out, err = f.run(now="2026-10-15T02:10:00Z")
    check("merge refused: repeated after 12 hours", "held" in out, out)


def t_one_per_tick():
    f = Fx()
    s5 = f.make_head(5, "0.2.0")
    s6 = f.make_head(6, "0.3.0", extra={"six.txt": "6\n"})
    f.pr(5, s5)
    f.pr(6, s6)
    f.run()
    rc, out, err = f.run()
    check(
        "one merge per pass: exactly one merge",
        len(f.calls(MERGE)) == 1 and out.count("merged #") == 1,
        out,
    )
    check(
        "one merge per pass: the other is queued",
        f.prstate(6).get("kind") == "queued",
        f.prstate(6),
    )


def t_dry_run():
    f = Fx()
    sha = f.make_head(5, "0.2.0")
    f.pr(5, sha)
    f.run(CORELANE_DRY_RUN="1")
    rc, out, err = f.run(CORELANE_DRY_RUN="1")
    check(
        "dry run: prints would_merge",
        out == "[CORE LANE] would_merge #5 v0.2.0 feat: change 5",
        out + err,
    )
    check(
        "dry run: never merges, releases or syncs",
        not f.calls(MERGE) and not f.calls(RELEASE) and not f.synclog.exists(),
    )


def t_kill_switch():
    f = Fx()
    sha = f.make_head(5, "0.2.0")
    f.pr(5, sha)
    f.policy.write_text(json.dumps({"enabled": False}))
    f.run()
    rc, out, err = f.run()
    check("kill switch off: no gh call at all", rc == 0 and out == "" and not f.calls(), f.calls())
    check("kill switch off: state says disabled", f.state().get("disabled") is True)


def t_policy_unreadable():
    f = Fx()
    sha = f.make_head(5, "0.2.0")
    f.pr(5, sha)
    f.policy.write_text("{not json")
    outs = [f.run()[1] for _ in range(3)]
    check("policy unreadable: fails closed, no gh call", not f.calls(), f.calls())
    check(
        "policy unreadable: silent twice, one line on the third pass",
        outs[0] == "" and outs[1] == "" and "failing (3 passes" in outs[2],
        outs,
    )


def t_gh_down():
    f = Fx()
    outs = [f.run(FAKE_FAIL="1") for _ in range(3)]
    check("gh down: exit 0 every pass", all(o[0] == 0 for o in outs))
    check(
        "gh down: reported on the third pass only",
        outs[0][1] == "" and outs[1][1] == "" and "failing (3" in outs[2][1],
        outs,
    )
    f.run()
    check("gh down: error count resets on a good pass", f.state().get("error_count") == 0)


def t_check_readonly():
    f = Fx()
    sha = f.make_head(5, "0.2.0")
    f.pr(5, sha)
    f.run()
    before = (f.cache / "lane-state.json").read_text()
    rc, out, err = f.run("check", "5")
    j = json.loads(out)
    check(
        "check: ready decision printed",
        rc == 0 and j["status"] == "ready" and j["version"] == "0.2.0",
        out + err,
    )
    check(
        "check: no merge and state untouched",
        not f.calls(MERGE) and (f.cache / "lane-state.json").read_text() == before,
    )


# ---------------------------------------------------------------- auto-fix


def fixrec(f, n=5):
    return (f.state().get("fix") or {}).get(str(n)) or {}


def decisions(f):
    p = f.cache / "decisions.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def t_autofix_dirty():
    f = Fx()
    sha = f.make_head(5, "0.2.0")
    f.pr(5, sha, mss="DIRTY")
    rc, out, err = f.run()
    run = fixrec(f).get("running") or {}
    check(
        "autofix dirty: one session started for merge-conflict",
        run.get("problem") == "merge-conflict",
        fixrec(f),
    )
    check("autofix dirty: pass stays silent", rc == 0 and out == "", out + err)
    argv = run.get("argv") or []
    skills = argv[3] if len(argv) > 3 else ""
    check("autofix dirty: session loads the core skill", "core-skill" in skills.split(","), skills)
    brief = Path(run.get("brief", "/nonexistent")).read_text() if run.get("brief") else ""
    check(
        "autofix dirty: brief carries the core notes and noreply identity",
        "core standards repo" in brief
        and "user-id+owner-account@users.noreply.github.com" in brief
        and "skill core-skill for how to change the code" in brief,
        brief[:300],
    )
    check("autofix dirty: brief is ASCII", brief.isascii())
    check(
        "autofix dirty: autofix-started logged with the head",
        any(d["decision"] == "autofix-started" and d["sha"] == sha for d in decisions(f)),
    )
    check("autofix dirty: nothing merged", not f.calls(MERGE))


def t_autofix_behind():
    f = Fx()
    sha = f.make_head(5, "0.2.0")
    f.pr(5, sha, mss="BEHIND")
    f.run()
    check(
        "autofix behind: rebase session started",
        (fixrec(f).get("running") or {}).get("problem") == "merge-conflict",
    )


def t_autofix_blocked_is_mine():
    f = Fx()
    sha = f.make_head(5, "0.2.0")
    f.pr(5, sha, mss="BLOCKED")
    f.run()
    check(
        "autofix blocked merge state: no session (mine to clear)",
        not fixrec(f).get("running"),
        fixrec(f),
    )


def t_autofix_version():
    f = Fx()
    s5 = f.make_head(5, "0.2.0")
    s6 = f.make_head(6, "0.2.0", extra={"other.txt": "o\n"})
    f.pr(5, s5, mss="DIRTY")  # the older claim, held on its own conflict
    f.pr(6, s6)
    f.run()
    f.run()
    run = fixrec(f, 6).get("running") or {}
    hist = fixrec(f, 6).get("history") or []
    probs = {run.get("problem")} | {h.get("problem") for h in hist}
    check(
        "autofix version: taken version starts a version-bump session",
        "version-bump" in probs,
        fixrec(f, 6),
    )


def t_autofix_red_and_local():
    f = Fx()
    sha = f.make_head(5, "0.2.0", extra={"leak.md": "This names ACMECORP.\n"})
    f.pr(5, sha)
    f.run()
    f.run()
    hist = [h.get("problem") for h in fixrec(f).get("history") or []] + [
        (fixrec(f).get("running") or {}).get("problem")
    ]
    check("autofix local checks: local-checks session started", "local-checks" in hist, fixrec(f))
    g = Fx()
    sha = g.make_head(5, "0.2.0")
    g.pr(
        5,
        sha,
        checks=[
            {"name": "ci", "workflowName": "checks", "conclusion": "FAILURE", "completedAt": "x"}
        ],
    )
    g.run()
    check(
        "autofix red: red-checks session started",
        (fixrec(g).get("running") or {}).get("problem") == "red-checks",
    )


def t_autofix_refused_is_mine():
    f = Fx()
    sha = f.make_head(5, "0.2.0")
    f.pr(5, sha)
    f.run()
    f.run(FAKE_MERGE_FAIL="1")
    f.run(FAKE_MERGE_FAIL="1")
    check(
        "autofix merge refused: no session",
        not fixrec(f).get("running") and not fixrec(f).get("history"),
        fixrec(f),
    )


def t_autofix_kill_switch():
    f = Fx()
    sha = f.make_head(5, "0.2.0")
    f.pr(5, sha, mss="DIRTY")
    f.policy.write_text(json.dumps({"autofix": {"enabled": False}}))
    f.run()
    check("autofix off: no session", not fixrec(f).get("running"), fixrec(f))
    rc, out, err = f.run(now="2026-10-14T14:05:00Z")
    check("autofix off: held alert after 2 hours as before", "held 2h" in out, out)


def t_autofix_gave_up_once():
    f = Fx()
    sha = f.make_head(5, "0.2.0")
    f.pr(5, sha, mss="DIRTY")
    outs = [
        f.run(now=t)[1]
        for t in ("2026-10-14T12:00:00Z", "2026-10-14T12:05:00Z", "2026-10-14T12:10:00Z")
    ]
    check(
        "autofix gave up: silent twice, then one gave-up line",
        outs[0] == ""
        and outs[1] == ""
        and "auto-fix gave up" in outs[2]
        and outs[2].startswith("[CORE LANE] PR #5"),
        outs,
    )
    rc, out, err = f.run(now="2026-10-14T14:05:00Z")
    check("autofix gave up: no second line and no generic held alert", out == "", out)
    check("autofix gave up: logged", any(d["decision"] == "autofix-gave-up" for d in decisions(f)))


def t_autofix_dry_run():
    f = Fx()
    sha = f.make_head(5, "0.2.0")
    f.pr(5, sha, mss="DIRTY")
    rc, out, err = f.run(CORELANE_DRY_RUN="1")
    check(
        "autofix dry run: prints would_autofix",
        out == "[CORE LANE] would_autofix #5 (merge-conflict) feat: change 5",
        out,
    )
    check("autofix dry run: no session recorded", not fixrec(f).get("running"), fixrec(f))


def t_autofix_closed_cleanup():
    f = Fx()
    sha = f.make_head(5, "0.2.0")
    f.pr(5, sha, mss="DIRTY")
    f.run()
    f.prs = []
    f.write_prs()
    f.run()
    check(
        "autofix cleanup: closed PR drops its fix record",
        "5" not in (f.state().get("fix") or {}),
        f.state().get("fix"),
    )


def t_autofix_check_reports():
    f = Fx()
    sha = f.make_head(5, "0.2.0")
    f.pr(5, sha, mss="DIRTY")
    f.cache.mkdir(parents=True, exist_ok=True)
    rc, out, err = f.run("check", "5")
    j = json.loads(out) if rc == 0 else {}
    check(
        "autofix check: names the problem, starts nothing",
        j.get("autofix_problem") == "merge-conflict" and not fixrec(f).get("running"),
        out + err,
    )


# ---------------------------------------------------------------- owner mode (core issue 117)

OWNER_POLICY = {"merge_mode": "owner", "owner_label": "do-not-merge"}


def t_owner_ready_never_merges():
    f = Fx()
    sha = f.make_head(5, "0.2.0")
    f.pr(5, sha, labels=["do-not-merge"])
    f.policy.write_text(json.dumps(OWNER_POLICY))
    f.run()
    rc, out, err = f.run()
    rec = f.prstate(5)
    check(
        "owner mode: green PR is never merged or released",
        not f.calls(MERGE) and not f.calls(RELEASE),
        out + err,
    )
    check(
        "owner mode: recorded owner/owner-queue",
        rec.get("status") == "owner" and rec.get("kind") == "owner-queue",
        rec,
    )
    check(
        "owner mode: queue 1 of 1, next in order",
        rec.get("queue") == 1 and "next" in rec.get("queue_text", ""),
        rec,
    )
    check("owner mode: tick stays silent", out == "", out)
    check(
        "owner mode: state says owner",
        f.state().get("merge_mode") == "owner",
        f.state().get("merge_mode"),
    )


def t_owner_adds_missing_label():
    f = Fx()
    sha = f.make_head(5, "0.2.0")
    f.pr(5, sha)
    f.policy.write_text(json.dumps(OWNER_POLICY))
    rc, out, err = f.run()
    edits = f.calls(["pr", "edit"])
    check(
        "owner mode: missing label added once",
        len(edits) == 1 and "do-not-merge" in edits[0],
        edits,
    )
    f.run()
    check(
        "owner mode: label not added twice",
        len(f.calls(["pr", "edit"])) == 1,
        f.calls(["pr", "edit"]),
    )
    check("owner mode: other hold labels still skip", True)


def t_owner_label_fail_reports():
    f = Fx()
    sha = f.make_head(5, "0.2.0")
    f.pr(5, sha)
    f.policy.write_text(json.dumps(OWNER_POLICY))
    rc, out, err = f.run(FAKE_EDIT_FAIL="1")
    check(
        "owner mode: label failure prints one line",
        "could not add the do-not-merge label" in out,
        out + err,
    )
    check("owner mode: label failure merges nothing", not f.calls(MERGE), f.calls(MERGE))


def t_owner_hold_label_skips():
    f = Fx()
    sha = f.make_head(5, "0.2.0")
    f.pr(5, sha, labels=["do-not-merge", "hold"])
    f.policy.write_text(json.dumps(OWNER_POLICY))
    f.run()
    check("owner mode: hold label still skips the PR", not f.prstate(5), f.prstate(5))


def t_owner_version_order():
    f = Fx()
    s5 = f.make_head(5, "0.3.0")
    f.pr(5, s5, labels=["do-not-merge"])
    s6 = f.make_head(6, "0.2.0")
    f.pr(6, s6, labels=["do-not-merge"], mss="DIRTY")
    f.policy.write_text(json.dumps(OWNER_POLICY))
    f.run()
    f.run()
    r5, r6 = f.prstate(5), f.prstate(6)
    check(
        "owner order: lower version held is ahead",
        r6.get("status") == "held" and r5.get("status") == "owner",
        [r5, r6],
    )
    check(
        "owner order: #5 is 2 of 2, blocked by #6",
        r5.get("queue") == 2 and r5.get("queue_of") == 2 and r5.get("blocked_by") == [6],
        r5,
    )
    check("owner order: text names the blocker", "after #6" in r5.get("queue_text", ""), r5)
    check(
        "owner order: held PR still gets the auto-fix",
        (fixrec(f, 6) or {}).get("running"),
        fixrec(f, 6),
    )


def t_owner_dry_run_labels_nothing():
    f = Fx()
    sha = f.make_head(5, "0.2.0")
    f.pr(5, sha)
    f.policy.write_text(json.dumps(OWNER_POLICY))
    f.run(CORELANE_DRY_RUN="1")
    check(
        "owner mode dry run: no label written", not f.calls(["pr", "edit"]), f.calls(["pr", "edit"])
    )


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            try:
                fn()
            except Exception as e:  # noqa: BLE001 - a crashing scenario counts as a failure
                check(f"{name} crashed", False, f"{type(e).__name__}: {e}")
    print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'} (scratch {ROOT})")
    if not fails:
        shutil.rmtree(ROOT, ignore_errors=True)
    sys.exit(1 if fails else 0)
