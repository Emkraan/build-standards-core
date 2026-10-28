#!/usr/bin/env python3
"""Tests for destroy_followup.py. Fake gh, scratch dirs, never touches GitHub.

Date:    2026-10-13
Run:     /usr/bin/python3 destroy_followup_checks.py
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "testing"))
import policy_env  # noqa: E402

STATE_ROOT = (
    policy_env.install()
)  # a scratch state tree holding the policy fixtures, so no live state is read
SCRIPT = HERE / "destroy_followup.py"

FAKE_GH = r"""#!/usr/bin/env python3
import json
import os
import re
import sys
fx = json.load(open(os.environ["FAKE_FIX"]))
a = sys.argv[1:]
open(os.environ["FAKE_CALLS"], "a").write(json.dumps(a) + "\n")
if fx.get("fail"):
    sys.stderr.write("HTTP 502\n")
    sys.exit(1)
if a[:2] == ["run", "rerun"]:
    sys.exit(0)
path = a[1]
if "terraform-destroy.yml/runs" in path:
    print(json.dumps(fx.get("destroy_runs", [])))
    sys.exit(0)
if "terraform-apply.yml/runs" in path:
    print(json.dumps(fx.get("apply_runs", [])))
    sys.exit(0)
m = re.search(r"runs/(\d+)/jobs", path)
if m:
    print(json.dumps(fx.get("jobs", {}).get(m.group(1), [])))
    sys.exit(0)
m = re.search(r"jobs/(\d+)/logs", path)
if m:
    log = fx.get("logs", {}).get(m.group(1))
    if log is None:
        sys.stderr.write("HTTP 404\n")
        sys.exit(1)
    sys.stdout.write(log)
    sys.exit(0)
m = re.search(r"runs/(\d+)$", path)
if m:
    allr = fx.get("destroy_runs", []) + fx.get("apply_runs", [])
    print(json.dumps(next(r for r in allr if str(r["id"]) == m.group(1))))
    sys.exit(0)
sys.stderr.write("unrouted " + path + "\n")
sys.exit(1)
"""

ROOTS_LINE = (
    '2026-10-13T13:53:14Z   ROOTS: [{"name":"%s","tier":"prod","root":"x","destroy":false}]\n'
)
GUARD = (
    "2026-10-13T13:53:30Z ##[error]%s: plan deletes 34 resource(s). Deletes are applied only by "
    "terraform-destroy.yml (dispatch it with tool=%s tier=prod).\n"
    "2026-10-13T13:53:30Z ##[error]Process completed with exit code 1.\n"
)

PASS = 0
FAIL = []


def check(name, cond, detail=""):
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append(f"{name} {detail}")


def destroy_run(rid, created, status="completed", conclusion="success"):
    return {
        "id": rid,
        "created_at": created,
        "event": "workflow_dispatch",
        "head_branch": "main",
        "actor": {"login": "owner-account"},
        "status": status,
        "conclusion": conclusion,
    }


def apply_run(rid, created, status="completed", conclusion="failure", attempt=1):
    return {
        "id": rid,
        "created_at": created,
        "event": "push",
        "head_branch": "main",
        "status": status,
        "conclusion": conclusion,
        "run_attempt": attempt,
        "html_url": f"https://x/{rid}",
    }


def base_fix(tool="grafana"):
    return {
        "destroy_runs": [destroy_run(100, "2026-10-13T13:52:50Z")],
        "apply_runs": [apply_run(200, "2026-10-13T13:53:04Z")],
        "jobs": {
            "100": [
                {"id": 1001, "name": "plan (prod)", "status": "completed", "conclusion": "success"}
            ],
            "200": [
                {"id": 2001, "name": "discover changed roots and apps", "conclusion": "success"},
                {
                    "id": 2002,
                    "name": "apply (prod)",
                    "status": "completed",
                    "conclusion": "failure",
                },
                {"id": 2003, "name": "deploy apps", "conclusion": "skipped"},
            ],
        },
        "logs": {"1001": ROOTS_LINE % tool, "2002": "Plan: 0 to add\n" + GUARD % (tool, tool)},
    }


class Env:
    def __init__(self, fix, decisions, now="2026-10-13T14:10:00Z", dry=False, policy=None):
        self.d = Path(tempfile.mkdtemp(prefix="dfu-", dir=os.environ.get("TMPDIR")))
        (self.d / "gh").write_text(FAKE_GH)
        (self.d / "gh").chmod(0o755)
        self.fix = self.d / "fix.json"
        self.calls = self.d / "calls.jsonl"
        self.write(fix)
        (self.d / "decisions.jsonl").write_text("".join(json.dumps(x) + "\n" for x in decisions))
        if policy is not None:
            (self.d / "policy.json").write_text(json.dumps(policy))
        self.now, self.dry = now, dry

    def write(self, fix):
        self.fix.write_text(json.dumps(fix))

    def tick(self, now=None):
        env = dict(
            os.environ,
            OPRG_GH_BIN=str(self.d / "gh"),
            OPRG_STATE_DIR=str(self.d),
            OPRG_CACHE_DIR=str(self.d),
            OPRG_NOW=now or self.now,
            FAKE_FIX=str(self.fix),
            FAKE_CALLS=str(self.calls),
        )
        env.pop("OPRG_DRY_RUN", None)
        if self.dry:
            env["OPRG_DRY_RUN"] = "1"
        p = subprocess.run(
            [sys.executable, str(SCRIPT), "tick"], capture_output=True, text=True, env=env
        )
        return p.returncode, p.stdout.strip(), p.stderr.strip()

    def reruns(self):
        if not self.calls.exists():
            return []
        return [
            c
            for c in map(json.loads, self.calls.read_text().splitlines())
            if c[:2] == ["run", "rerun"]
        ]

    def state(self):
        return json.loads((self.d / "destroy-followup.json").read_text())["items"]

    def lane(self):
        return [
            json.loads(line)
            for line in (self.d / "decisions.jsonl").read_text().splitlines()
            if '"destroy-followup"' in line
        ]


DISPATCH = {
    "ts": "2026-10-13T13:52:50Z",
    "pr": 247,
    "decision": "destroy_dispatched",
    "tool": "grafana",
    "tier": "prod",
    "by": "owner-account",
}


def t_happy_path_reruns_once():
    e = Env(base_fix(), [DISPATCH])
    rc, out, err = e.tick()
    check("happy rc", rc == 0 and out == "", f"{rc} {out} {err}")
    check(
        "happy rerun",
        e.reruns() == [["run", "rerun", "200", "--failed", "-R", "owner/primary-repo"]],
        str(e.reruns()),
    )
    st = list(e.state().values())[0]
    check("happy state", st["status"] == "rerun" and st["rerun_attempt"] == 2, str(st))
    # Same tick again before the new attempt appears: no second rerun, no verdict.
    rc, out, _ = e.tick()
    check("no double rerun", len(e.reruns()) == 1 and out == "", str(e.reruns()))
    check("waits for attempt 2", list(e.state().values())[0]["status"] == "rerun")
    # Attempt 2 succeeded.
    f = base_fix()
    f["apply_runs"] = [apply_run(200, "2026-10-13T13:53:04Z", conclusion="success", attempt=2)]
    e.write(f)
    rc, out, _ = e.tick()
    check("rerun ok silent", out == "")
    check("rerun ok state", list(e.state().values())[0]["status"] == "rerun_ok")
    check("rerun ok logged", any(d["decision"] == "apply_rerun_ok" for d in e.lane()))


def t_rerun_failed_reports_once():
    e = Env(base_fix(), [DISPATCH])
    e.tick()
    f = base_fix()
    f["apply_runs"] = [apply_run(200, "2026-10-13T13:53:04Z", conclusion="failure", attempt=2)]
    e.write(f)
    _, out, _ = e.tick()
    check("rerun failed line", out.startswith("[primary DESTROY]") and "failed again" in out, out)
    _, out2, _ = e.tick()
    check("rerun failed once", out2 == "", out2)


def t_destroy_still_waiting():
    f = base_fix()
    f["destroy_runs"] = [
        destroy_run(100, "2026-10-13T13:52:50Z", status="waiting", conclusion=None)
    ]
    e = Env(f, [DISPATCH])
    _, out, _ = e.tick()
    check("waiting no rerun", e.reruns() == [] and out == "")
    check("waiting state", list(e.state().values())[0]["status"] == "waiting_destroy")


def t_destroy_failed_no_rerun():
    f = base_fix()
    f["destroy_runs"] = [destroy_run(100, "2026-10-13T13:52:50Z", conclusion="failure")]
    e = Env(f, [DISPATCH])
    _, out, _ = e.tick()
    check("destroy failed no rerun", e.reruns() == [] and out == "")
    check("destroy failed state", list(e.state().values())[0]["status"] == "destroy_failed")


def t_main_already_green():
    f = base_fix()
    f["apply_runs"] = [apply_run(200, "2026-10-13T13:53:04Z", conclusion="success")]
    e = Env(f, [DISPATCH])
    e.tick()
    check("green no rerun", e.reruns() == [])
    check("green state", list(e.state().values())[0]["status"] == "main_green")


def t_newer_apply_running_waits():
    f = base_fix()
    f["apply_runs"] = [
        apply_run(200, "2026-10-13T13:53:04Z"),
        apply_run(201, "2026-10-13T14:05:00Z", status="in_progress", conclusion=None),
    ]
    e = Env(f, [DISPATCH])
    e.tick()
    check("running no rerun", e.reruns() == [])
    check("running state", list(e.state().values())[0]["status"] == "waiting_apply")


def t_other_error_not_rerun():
    f = base_fix()
    f["logs"]["2002"] = GUARD % ("grafana", "grafana") + "2026 ##[error]apply failed for console\n"
    e = Env(f, [DISPATCH])
    _, out, _ = e.tick()
    check("other error no rerun", e.reruns() == [])
    check("other error line", "not the destroy guard" in out, out)
    _, out2, _ = e.tick()
    check("other error once", out2 == "", out2)


def t_other_job_failed_not_rerun():
    f = base_fix()
    f["jobs"]["200"].append({"id": 2004, "name": "governance plan", "conclusion": "failure"})
    e = Env(f, [DISPATCH])
    _, out, _ = e.tick()
    check("other job no rerun", e.reruns() == [] and "besides the apply" in out, out)


def t_guard_for_uncovered_root():
    f = base_fix()
    f["logs"]["2002"] = GUARD % ("console", "console")
    e = Env(f, [DISPATCH])
    _, out, _ = e.tick()
    check("uncovered no rerun", e.reruns() == [] and "no successful destroy" in out, out)


def t_second_destroy_pending_waits():
    second = dict(DISPATCH, ts="2026-10-13T13:52:52Z", tool="console", pr=250)
    f = base_fix()
    f["destroy_runs"].append(
        destroy_run(101, "2026-10-13T13:52:53Z", status="waiting", conclusion=None)
    )
    f["jobs"]["101"] = [
        {"id": 1011, "name": "plan (prod)", "status": "completed", "conclusion": "success"}
    ]
    f["logs"]["1011"] = ROOTS_LINE % "console"
    f["logs"]["2002"] = GUARD % ("console", "console")
    e = Env(f, [DISPATCH, second])
    _, out, _ = e.tick()
    check("pending second no rerun", e.reruns() == [] and out == "", out)
    st = {v["tool"]: v["status"] for v in e.state().values()}
    check(
        "pending second states",
        st == {"grafana": "waiting_apply", "console": "waiting_destroy"},
        str(st),
    )


def t_matches_by_root_not_time():
    other = destroy_run(99, "2026-10-13T13:52:49Z")  # another root's dispatch, earlier
    f = base_fix()
    f["destroy_runs"].insert(0, other)
    f["jobs"]["99"] = [
        {"id": 991, "name": "plan (prod)", "status": "completed", "conclusion": "success"}
    ]
    f["logs"]["991"] = ROOTS_LINE % "console"
    e = Env(f, [DISPATCH])
    e.tick()
    check("matched run 100", list(e.state().values())[0].get("destroy_run") == 100, str(e.state()))


def t_resolve_failed_run_never_matches():
    f = base_fix()
    f["destroy_runs"] = [destroy_run(100, "2026-10-13T13:52:50Z", conclusion="failure")]
    f["jobs"]["100"] = [
        {"id": 1001, "name": "resolve roots", "conclusion": "failure"},
        {"id": 1002, "name": "plan (prod)", "status": "completed", "conclusion": "skipped"},
    ]
    e = Env(f, [DISPATCH], now="2026-10-13T14:20:00Z")
    _, out, _ = e.tick()
    check("resolve failed no rerun", e.reruns() == [] and out == "")
    check(
        "resolve failed state",
        list(e.state().values())[0]["status"] == "no_destroy_run",
        str(e.state()),
    )


def t_dry_run_never_posts():
    e = Env(base_fix(), [DISPATCH], dry=True)
    e.tick()
    check("dry no rerun", e.reruns() == [])
    check("dry logged", any(d["decision"] == "would_rerun" for d in e.lane()))


def t_kill_switch():
    e = Env(base_fix(), [DISPATCH], policy={"destroy_followup": {"enabled": False}})
    e.tick()
    check("kill no calls", not e.calls.exists())


def t_old_dispatch_ignored():
    e = Env(base_fix(), [DISPATCH], now="2026-10-16T14:00:00Z")
    e.tick()
    check("old no calls", not e.calls.exists())


def t_dev_tier_ignored():
    e = Env(base_fix(), [dict(DISPATCH, tier="dev")])
    e.tick()
    check("dev no calls", not e.calls.exists())


def t_gh_failure_alerts_at_three():
    f = base_fix()
    f["fail"] = True
    e = Env(f, [DISPATCH])
    outs = [e.tick()[1] for _ in range(4)]
    check("fail silent 1-2", outs[0] == "" and outs[1] == "", str(outs))
    check(
        "fail alert 3", outs[2].startswith("[primary DESTROY] follow-up tick failed 3"), str(outs)
    )
    check("fail silent 4", outs[3] == "", str(outs))
    rcs = e.tick()[0]
    check("fail rc 0", rcs == 0)


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn()
    print(f"{PASS} passed, {len(FAIL)} failed")
    for f in FAIL:
        print("FAIL", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
