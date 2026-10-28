#!/usr/bin/env python3
"""
model_bump.py
Purpose: Model bumps for the PR review workflow, for a primary repository and an optional secondary one
         (Claude only).
         1) Discovery (hourly): read the newest successful
            ai-review-model-check.yml run on main. If it proposes a bump that
            passed its smoke test, open a PR as the owner account that changes only the
            model IDs in .github/ai-review/models.json.
         2) Every tick: if a bump PR is open, verify its shape (only that file,
            only the claude/openai values, newer models in the same family),
            wait for every check, then rebase-merge it with the owner's bypass when all
            checks (including `ai-review result`) are green. Anything else
            (red check, shape violation, conflict) is reported once per head
            and left for the owner; the PR shows in the ops center under the owner's PRs.

Usage:   model_bump.py tick [--target primary|secondary]
         model_bump.py status [--target primary|secondary]
Output:  nothing when there is nothing to report; otherwise lines starting with
         the target's tag, such as [primary MODEL BUMP], that the gate passes to the
         review cron agent.
Exit:    0 always for tick (failures are reported, never raised).
System python3 is 3.9: no 3.10+ syntax.
"""

import base64
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import paths

HOME = Path.home()
GH = os.environ.get("OPRG_GH_BIN", paths.which("gh"))
SELF = os.environ.get(
    "OPSCENTER_SELF_LOGIN", "owner-account"
)  # the account the bump PR is opened as
MODELS_PATH = ".github/ai-review/models.json"
CHECK_WORKFLOW = "ai-review-model-check.yml"


# Per-repo settings come from the targets file (OPSCENTER_REVIEW_TARGETS, JSON), one entry per target:
#   {"primary": {"repo": "owner/name", "tag": "[primary MODEL BUMP]", "ticket": "123",
#                "state_dir": "...", "cache_dir": "..."},
#    "secondary": {"repo": "owner/other", "tag": "...", "ticket": "...", "state_dir": "...", "cache_dir": "...",
#                  "config_file": "secondary-model-bump.json", "state_file": "secondary-model-bump-state.json"}}
# The primary target keeps its kill switch under the policy "model_bump" key. A target with a config_file has
# no policy: its kill switch and ticket live in that file next to its cache ({"enabled": false}).
# "ticket" is the work reference that prefixes the bump branch and the commit message.
def _targets():
    f = os.environ.get("OPSCENTER_REVIEW_TARGETS")
    cfg = json.loads(Path(f).read_text()) if f and Path(f).is_file() else {}
    state = paths.state_dir() / "review"
    cache = paths.agent_home() / "cache" / "primary-pr-review"
    out = {
        "primary": {
            "repo": "owner/primary-repo",
            "state_dir": os.environ.get("OPRG_STATE_DIR", str(state)),
            "cache_dir": os.environ.get("OPRG_CACHE_DIR", str(cache)),
            "state_file": "model-bump.json",
            "tag": "[primary MODEL BUMP]",
            "ticket": "bump",
        },
        "secondary": {
            "repo": "owner/secondary-repo",
            "state_dir": str(paths.agent_home() / "cache" / "secondary-pr-review"),
            "cache_dir": str(paths.agent_home() / "cache" / "secondary-pr-review"),
            "state_file": "secondary-model-bump-state.json",
            "tag": "[secondary MODEL BUMP]",
            "ticket": "bump",
            "config_file": "secondary-model-bump.json",
        },
    }
    for name, over in cfg.items():
        if name in out and isinstance(over, dict):
            out[name].update(over)
    return out


TARGETS = _targets()


def _target_from_argv():
    if "--target" in sys.argv:
        i = sys.argv.index("--target")
        if i + 1 < len(sys.argv) and sys.argv[i + 1] in TARGETS:
            return sys.argv[i + 1]
        raise SystemExit("--target must be one of: " + ", ".join(sorted(TARGETS)))
    return "primary"


TARGET = _target_from_argv()
_T = TARGETS[TARGET]
REPO = _T["repo"]
STATE_DIR = Path(_T["state_dir"])
CACHE_DIR = Path(_T["cache_dir"])
STATE_FILE = CACHE_DIR / _T["state_file"]
POLICY = STATE_DIR / _T.get("config_file", "policy.json")
DECISIONS = STATE_DIR / (
    "decisions.jsonl" if TARGET == "primary" else "secondary-model-bump-decisions.jsonl"
)
DISCOVERY_INTERVAL_S = 3600
FAMILY = {
    "claude": re.compile(r"^claude-opus-(\d+)(?:-(\d+))?$"),
    "openai": re.compile(r"^gpt-(\d+)(?:\.(\d+))?$"),
}
OK_CONCLUSIONS = {"SUCCESS", "NEUTRAL", "SKIPPED"}
FORBIDDEN = re.compile(
    "|".join(
        filter(
            None,
            [r"\bbot\b|assistant|co-authored-by", os.environ.get("OPSCENTER_FORBIDDEN_WORDS", "")],
        )
    ),
    re.I,
)
FORBIDDEN_CS = re.compile(r"\bAI\b")  # case-sensitive: "ai-review" paths are fine
NOW = dt.datetime.now(dt.timezone.utc)
NOW_ISO = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
TAG = _T["tag"]


class GhError(Exception):
    pass


def gh(args, raw=False, timeout=90, stdin=None):
    try:
        p = subprocess.run(
            [GH] + args, capture_output=True, text=True, timeout=timeout, input=stdin
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise GhError(f"gh failed: {e}")  # noqa: B904
    if p.returncode != 0:
        raise GhError(f"gh {' '.join(args[:3])}: {p.stderr.strip()[:300]}")
    if raw:
        return p.stdout
    return json.loads(p.stdout) if p.stdout.strip() else {}


def load_json(p, default):
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return default


def save_state(st):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=2) + "\n")
    os.replace(tmp, STATE_FILE)


def log_decision(rec):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(DECISIONS, "a") as f:
        f.write(json.dumps(dict({"ts": NOW_ISO, "lane": "model-bump"}, **rec)) + "\n")


def version(provider, model_id):
    m = FAMILY[provider].match(model_id or "")
    return (int(m.group(1)), int(m.group(2) or 0)) if m else None


def bump_config():
    pol = load_json(POLICY, {})
    cfg = (pol.get("model_bump") or {}) if TARGET == "primary" else pol
    return {"ticket": str(cfg.get("ticket", _T["ticket"])), "enabled": cfg.get("enabled", True)}


def models_at(ref):
    d = gh(["api", f"repos/{REPO}/contents/{MODELS_PATH}?ref={ref}"])
    text = base64.b64decode(d["content"]).decode("utf-8")
    return text, json.loads(text), d["sha"]


# ---------------------------------------------------------------------
# Shape check (pure)
# ---------------------------------------------------------------------
def shape_problems(files, base, head):
    """Reasons a bump PR is not a plain model bump. Empty list = OK."""
    problems = []
    if files != [MODELS_PATH]:
        problems.append(
            f"changes files other than {MODELS_PATH}: {', '.join(f for f in files if f != MODELS_PATH)[:200]}"
        )
    if set(base) != set(head):
        problems.append("adds or removes keys in models.json")
    changed = sorted(k for k in set(base) & set(head) if base[k] != head[k])
    other = [k for k in changed if k not in FAMILY]
    if other:
        problems.append(f"changes non-model settings: {', '.join(other)}")
    if not any(k in FAMILY for k in changed):
        problems.append("does not change a model ID")
    for k in changed:
        if k not in FAMILY:
            continue
        old_v, new_v = version(k, base[k]), version(k, head[k])
        if new_v is None:
            problems.append(f"{k}: {head[k]!r} is outside the pinned family")
        elif old_v is not None and new_v <= old_v:
            problems.append(f"{k}: {head[k]} is not newer than {base[k]}")
    return problems


def checks_state(rollup):
    """(green, red_names, pending_names, ai_review_result) from statusCheckRollup."""
    best = {}
    for c in rollup or []:
        name = c.get("name") or c.get("context") or "?"
        val = (c.get("conclusion") or c.get("state") or c.get("status") or "PENDING").upper()
        ts = c.get("startedAt") or c.get("startedat") or ""
        if name not in best or ts >= best[name][0]:
            best[name] = (ts, val)
    vals = {k: v for k, (_, v) in best.items()}
    red = sorted(
        k
        for k, v in vals.items()
        if v in ("FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE", "ERROR")
    )
    pending = sorted(k for k, v in vals.items() if v not in OK_CONCLUSIONS and k not in red)
    ai = vals.get("ai-review result")
    green = not red and not pending and ai == "SUCCESS"
    return green, red, pending, ai


# ---------------------------------------------------------------------
# Open PR handling
# ---------------------------------------------------------------------
def open_bump_prs(prefix):
    prs = gh(
        [
            "pr",
            "list",
            "-R",
            REPO,
            "--state",
            "open",
            "--author",
            SELF,
            "--limit",
            "50",
            "--json",
            "number,headRefName,headRefOid,title,url",
        ]
    )
    return [p for p in prs if p["headRefName"].startswith(prefix)]


def progress_pr(st, pr, out):
    n = pr["number"]
    v = gh(
        [
            "pr",
            "view",
            str(n),
            "-R",
            REPO,
            "--json",
            "headRefOid,files,statusCheckRollup,mergeable,mergeStateStatus,state,isDraft",
        ]
    )
    head = v["headRefOid"]
    files = sorted(f["path"] for f in v.get("files") or [])
    _, base_json, _ = models_at("main")
    _, head_json, _ = models_at(head)
    problems = shape_problems(files, base_json, head_json)
    green, red, pending, ai = checks_state(v.get("statusCheckRollup"))
    rec = st.setdefault("prs", {}).setdefault(str(n), {})
    if v.get("mergeable") == "CONFLICTING":
        problems.append("merge conflict with main")

    def report_once(kind, text):
        key = f"{kind}:{head}"
        if rec.get("reported") != key:
            out.append(f"{TAG} PR #{n} {pr['title']}: {text} - {pr['url']}")
            rec["reported"] = key
            log_decision({"pr": n, "decision": kind, "sha": head, "detail": text})

    if problems:
        report_once(
            "held-shape", "held for you, not a plain model bump (" + "; ".join(problems)[:300] + ")"
        )
        return
    if red:
        report_once("held-checks", f"held for you, checks red: {', '.join(red)[:200]}")
        return
    if pending or not green:
        return  # wait for checks (ai-review result included)
    try:
        gh(
            ["pr", "merge", str(n), "-R", REPO, "--rebase", "--admin", "--match-head-commit", head],
            raw=True,
        )
    except GhError as e:
        report_once("merge-failed", f"all checks green but the merge failed: {str(e)[:200]}")
        return
    rec["merged"] = NOW_ISO
    changed = ", ".join(
        f"{k} {base_json[k]} -> {head_json[k]}"
        for k in FAMILY
        if base_json.get(k) != head_json.get(k)
    )
    log_decision({"pr": n, "decision": "merged", "sha": head, "detail": changed})
    out.append(
        f"{TAG} PR #{n}: merged ({changed}); all checks green incl. ai-review result - {pr['url']}"
    )


# ---------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------
def latest_check_report():
    try:
        runs = gh(
            [
                "run",
                "list",
                "-R",
                REPO,
                "--workflow",
                CHECK_WORKFLOW,
                "--branch",
                "main",
                "--status",
                "success",
                "--limit",
                "1",
                "--json",
                "databaseId,createdAt",
            ]
        )
    except GhError as e:
        if "not found" in str(e):
            return None, None  # workflow not on main (yet)
        raise
    if not runs:
        return None, None
    run_id = runs[0]["databaseId"]
    with tempfile.TemporaryDirectory() as tmp:
        gh(
            ["run", "download", str(run_id), "-R", REPO, "-n", "ai-review-model-check", "-D", tmp],
            raw=True,
        )
        return run_id, json.loads((Path(tmp) / "model-check.json").read_text())


def replace_value(text, key, old, new):
    pat = re.compile(r'("%s"\s*:\s*")%s(")' % (re.escape(key), re.escape(old)))  # noqa: UP031
    out, count = pat.subn(lambda m: m.group(1) + new + m.group(2), text)
    if count != 1:
        raise ValueError(f"could not find a single {key} pin to replace")
    return out


def open_bump_pr(cfg, report, out):
    text, pins, file_sha = models_at("main")
    bump = {}
    for provider, model in (report.get("bump") or {}).items():
        if provider not in FAMILY or pins.get(provider) == model:
            continue
        cur, new = version(provider, pins.get(provider, "")), version(provider, model)
        if new is None or (cur is not None and new <= cur):
            continue
        if report.get("current", {}).get(provider) != pins.get(provider):
            continue  # report is stale against main
        bump[provider] = model
    if not bump:
        return False
    for provider, model in bump.items():
        text = replace_value(text, provider, pins[provider], model)
    summary = ", ".join(f"{p} {pins[p]} -> {m}" for p, m in bump.items())
    msg = f"{cfg['ticket']}: bump PR review models ({summary})"
    lines = [
        "## What",
        "",
        f"Bumps the PR review models in `{MODELS_PATH}`: {summary}. Nothing else changes.",
        "",
        "## Why",
        "",
        "The weekly model check found a newer model in the pinned family, and it passed the smoke review"
        f" (flagged the planted credential in the fixture). Check run: {report.get('run_url', '')}",
        "",
        "## Verification",
        "",
    ]
    for p, m in bump.items():
        sm = (report.get("smoke") or {}).get(p) or {}
        lines.append(f"- {p} `{m}`: {sm.get('detail', 'smoke passed')}")
    lines += [
        "",
        "The review on this PR still runs on the current models (pins are read from main); the new ones take effect"
        " on PRs opened after this merges.",
    ]
    body = "\n".join(lines) + "\n"
    bad = [m.group(0) for m in FORBIDDEN.finditer(body + msg)] + [
        m.group(0) for m in FORBIDDEN_CS.finditer(body + msg)
    ]
    if bad or any(ord(c) > 127 for c in body + msg):
        raise ValueError(f"bump PR text failed the wording/ASCII guard: {bad[:3]}")
    date = NOW.strftime("%Y%m%d")
    branch = f"{cfg['ticket']}-review-model-bump-{date}"
    main_sha = gh(["api", f"repos/{REPO}/git/ref/heads/main"])["object"]["sha"]
    try:
        gh(["api", f"repos/{REPO}/git/ref/heads/{branch}"])
        # Leftover from a failed attempt; tick() only gets here with no open bump PR.
        gh(["api", "-X", "DELETE", f"repos/{REPO}/git/refs/heads/{branch}"], raw=True)
    except GhError:
        pass
    gh(
        [
            "api",
            "-X",
            "POST",
            f"repos/{REPO}/git/refs",
            "-f",
            f"ref=refs/heads/{branch}",
            "-f",
            f"sha={main_sha}",
        ]
    )
    payload = {
        "message": msg,
        "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
        "sha": file_sha,
        "branch": branch,
        "author": {"name": "owner-name", "email": "owner-upn"},
        "committer": {"name": "owner-name", "email": "owner-upn"},
    }
    gh(
        ["api", "-X", "PUT", f"repos/{REPO}/contents/{MODELS_PATH}", "--input", "-"],
        stdin=json.dumps(payload),
    )
    url = gh(
        [
            "pr",
            "create",
            "-R",
            REPO,
            "--base",
            "main",
            "--head",
            branch,
            "--title",
            msg,
            "--body",
            body,
        ],
        raw=True,
    ).strip()
    log_decision({"decision": "opened", "branch": branch, "detail": summary, "url": url})
    out.append(f"{TAG} opened {url} ({summary}); it merges on its own once every check is green")
    return True


def tick():
    cfg = bump_config()
    st = load_json(STATE_FILE, {"handled_runs": [], "prs": {}})
    out = []
    try:
        if not cfg["enabled"]:
            return
        prefix = f"{cfg['ticket']}-review-model-bump-"
        prs = open_bump_prs(prefix)
        for pr in prs:
            progress_pr(st, pr, out)
        due = NOW.timestamp() - float(st.get("last_discovery_epoch", 0)) >= DISCOVERY_INTERVAL_S
        if not prs and due:
            st["last_discovery_epoch"] = NOW.timestamp()
            run_id, report = latest_check_report()
            if run_id and run_id not in st["handled_runs"]:
                open_bump_pr(cfg, report, out)
                st["handled_runs"] = (st["handled_runs"] + [run_id])[-20:]
        st.pop("last_error", None)
        st["error_count"] = 0
    except (GhError, ValueError, KeyError, OSError) as e:
        st["error_count"] = int(st.get("error_count", 0)) + 1
        st["last_error"] = f"{type(e).__name__}: {str(e)[:300]}"
        if st["error_count"] in (3, 20):
            out.append(f"{TAG} failing ({st['error_count']} in a row): {st['last_error']}")
    finally:
        st["updated"] = NOW_ISO
        save_state(st)
        if out:
            print("\n".join(out))


def main():
    args = [a for a in sys.argv[1:] if a != "--target" and a not in TARGETS]
    cmd = args[0] if args else "tick"
    if cmd == "tick":
        tick()
    elif cmd == "status":
        print(json.dumps(load_json(STATE_FILE, {}), indent=2))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
