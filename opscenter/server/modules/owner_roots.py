"""
owner_roots.py
Purpose: Owner-applied Terraform roots (a root whose spec says applied_by owner: no pipeline identity can apply it, so the
         owner applies it from a saved plan). This module plans each root from origin/main in a private worktree, keeps the
         saved plan, and applies exactly that plan when the owner approves it in the Ops Center.

         CLI (run detached by the server, one operation at a time under a lock):
           owner_roots.py signin    (one interactive sign-in, then plan-all once signed in)
           owner_roots.py plan-all
           owner_roots.py plan <name> <tier>
           owner_roots.py apply <name> <tier> <plan_sha256>
         Status: <cache>/status.json (OWNER_ROOTS_CACHE). Decisions: OWNER_ROOTS_DECISIONS (decision owner_apply_*).

         Nothing about a cloud is in this module. The roots spec is a JSON file in the clone (OWNER_ROOTS_SPEC, default
         .github/terraform-roots.json): {"roots": [{"name", "applied_by", "tiers": {tier: {"root", "vars", "key"}}}],
         "state_backend": {"tiers": {tier: {...}}, ...}}. Everything that depends on the cloud or on who is signed in is
         the consumer's provider (OWNER_ROOTS_PROVIDER=path/to/file.py:ClassName), every method optional:
           expected_identity (str) and identity() -> str   the signed-in account must equal it before a plan or an apply
           signin_cmd() -> [argv]                           the interactive sign-in the Sign in button runs
           backend_args(tier_spec, backend) -> [str]        extra `terraform init` arguments for the tier's state backend
           before_apply(deletes, log) -> state              e.g. lift the resource locks the plan's deletes need
           after_apply(state, log) -> (restored, [errors])  restore them; any error fails the apply loudly
           error_kinds() -> [(kind, regex, next step)]      extra failure classes, checked before the built-in ones
         With no provider there is no identity check, no sign-in, no backend arguments and no lock handling.
Date:    2026-10-12
"""

import contextlib
import datetime as dt
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import paths

HOME = Path.home()
CACHE = Path(os.environ.get("OWNER_ROOTS_CACHE", str(paths.agent_home() / "cache" / "owner-roots")))
STATUS = CACHE / "status.json"
LOCK = CACHE / "op.lock"
STATUS_LOCK = CACHE / "status.lock"
WT = CACHE / "wt"
PLANS = CACHE / "plans"
LOGS = CACHE / "logs"
SIGNIN = CACHE / "signin.json"
SIGNIN_TIMEOUT_S = int(os.environ.get("OWNER_ROOTS_SIGNIN_TIMEOUT_S", "600"))
SIGNIN_LOCK_WAIT_S = 1800
SIGNIN_POLL_S = float(os.environ.get("OWNER_ROOTS_SIGNIN_POLL_S", "10"))
SRC_REPO = Path(os.environ.get("OWNER_ROOTS_REPO", str(paths.repos_dir() / "infra")))
SPEC_FILE = os.environ.get("OWNER_ROOTS_SPEC", ".github/terraform-roots.json")
DECISIONS = Path(
    os.environ.get(
        "OWNER_ROOTS_DECISIONS", str(paths.state_dir() / "owner-roots" / "decisions.jsonl")
    )
)
TF = os.environ.get("OWNER_ROOTS_TF") or paths.which("terraform")
GIT = os.environ.get("OWNER_ROOTS_GIT") or paths.which("git")
REFRESH_S = 2 * 3600
STALE_S = 24 * 3600
MAIN_TTL_S = 30
AUTH_RE = re.compile(
    r"not signed in|sign-?in (has )?expired|login (has )?expired|token (has )?expired|expired token|unauthenticated|"
    r"please (run|log ?in)|InteractionRequired",
    re.I,
)
REPEAT_ALERT = (
    2  # the same failure this many times in a row on the same main raises an Action Center item
)
ALERT_PREFIX = "owner-apply-"
APPLY_TRIES = 3

_provider = {"spec": None, "obj": None}


class ProviderRefused(Exception):
    status = 403


def provider():
    """The configured provider object, or None (the null default)."""
    spec = os.environ.get("OWNER_ROOTS_PROVIDER", "").strip()
    if _provider["spec"] == spec:
        return _provider["obj"]
    obj = None
    if spec:
        path, _, cls_name = spec.rpartition(":")
        if not path or not cls_name:
            raise ProviderRefused("provider must be `path/to/file.py:ClassName`")
        file = Path(path)
        if not file.is_file():
            raise ProviderRefused(f"provider file not found: {file.name}")
        ms = importlib.util.spec_from_file_location(f"owner_roots_provider_{file.stem}", file)
        mod = importlib.util.module_from_spec(ms)
        try:
            ms.loader.exec_module(mod)
            obj = getattr(mod, cls_name)()
        except (OSError, ImportError, AttributeError, TypeError, SyntaxError) as exc:
            raise ProviderRefused(f"provider could not be loaded: {type(exc).__name__}") from exc
    _provider.update(spec=spec, obj=obj)
    return obj


def _hook(name, *args, default=None):
    p = provider()
    fn = getattr(p, name, None) if p is not None else None
    return fn(*args) if callable(fn) else default


def _expected_identity():
    return str(getattr(provider(), "expected_identity", "") or "")


def _identity():
    return str(_hook("identity", default="") or "")


# Failed plan or apply -> (kind, the next step the card shows). First match wins, so the worst
# outcome (a lock left off) is checked first. A re-plan only helps the last two.
ERROR_KINDS = (
    (
        "locks_not_restored",
        re.compile(r"LOCKS NOT RESTORED", re.I),
        "A protection the owner lifted for this apply is still off. Check what the error names and put it "
        "back before anything else. Re-plan does not fix this.",
    ),
    (
        "forbidden",
        re.compile(
            r"not authorized|does not have authori[sz]ation|\b403\b|Forbidden|permission denied",
            re.I,
        ),
        "The signed-in account was refused (a missing role, an expired elevation or a policy). "
        "Re-plan will not change that. Get the access named in the error, then Re-plan.",
    ),
    (
        "signin",
        AUTH_RE,
        "The sign-in expired. Press Sign in and sign in as the expected account. The re-plan starts by itself once the "
        "sign-in lands.",
    ),
    (
        "state_lock",
        re.compile(r"Error acquiring the state lock|state blob is already locked", re.I),
        "Another plan or apply holds this root's Terraform state lock. Wait for it to finish, then Re-plan. "
        "If no run is active, the lock is stale and needs a force-unlock.",
    ),
    (
        "plan_changed",
        re.compile(
            r"saved plan changed|does not match what the owner reviewed|worktree moved|Saved plan is stale",
            re.I,
        ),
        "The saved plan went out of date before the apply. Re-plan, review the fresh plan and apply it.",
    ),
)
ERROR_DEFAULT = (
    "other",
    "Re-plan once. If it fails the same way, a re-plan will not fix it, so read the error above and this root's log.",
)


def classify_error(msg):
    """(kind, next step) for a failed plan or apply message: the provider's kinds first, then the built-in ones."""
    for kind, rx, step in list(_hook("error_kinds", default=None) or []) + [
        (k, r.pattern, st) for k, r, st in ERROR_KINDS
    ]:
        if re.search(rx, msg or "", re.I):
            return kind, step
    return ERROR_DEFAULT


def _now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _env():
    env = dict(os.environ)
    env["TF_IN_AUTOMATION"] = "1"
    env["TF_INPUT"] = "0"
    env.setdefault("TF_PLUGIN_CACHE_DIR", str(HOME / ".terraform.d" / "plugin-cache"))
    Path(env["TF_PLUGIN_CACHE_DIR"]).mkdir(parents=True, exist_ok=True)
    return env


def _run(args, cwd=None, timeout=1200, log=None):
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=_env())
    if log:
        with open(log, "a") as fh:
            fh.write(f"\n$ {' '.join(args)}\n{p.stdout}\n{p.stderr}\nrc={p.returncode}\n")
    return p


def _key(name, tier):
    return f"{name}:{tier}"


def _load_status():
    try:
        return json.loads(STATUS.read_text())
    except (OSError, ValueError):
        return {"items": {}}


def _update(key, **fields):
    CACHE.mkdir(parents=True, exist_ok=True)
    with open(STATUS_LOCK, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        st = _load_status()
        it = st.setdefault("items", {}).setdefault(key, {})
        it.update(fields)
        st["updated"] = _now()
        tmp = STATUS.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, indent=1))
        os.replace(tmp, STATUS)
        return it


def _log(rec):
    rec = dict(rec, ts=_now(), lane="owner")
    with open(DECISIONS, "a") as fh:
        fh.write(json.dumps(rec) + "\n")


def _checkout_main():
    """Fetch origin/main and put the private worktree on it. Returns the main sha."""
    r = _run([GIT, "-C", str(SRC_REPO), "fetch", "-q", "origin", "main"], timeout=120)
    if r.returncode:
        raise RuntimeError(f"git fetch failed: {r.stderr.strip()[:200]}")
    sha = _run([GIT, "-C", str(SRC_REPO), "rev-parse", "origin/main"]).stdout.strip()
    if not (WT / ".git").exists():
        _run([GIT, "-C", str(SRC_REPO), "worktree", "prune"])
        r = _run(
            [GIT, "-C", str(SRC_REPO), "worktree", "add", "-q", "--detach", str(WT), sha],
            timeout=120,
        )
        if r.returncode:
            raise RuntimeError(f"worktree add failed: {r.stderr.strip()[:200]}")
    r = _run([GIT, "-C", str(WT), "checkout", "-q", "--force", "--detach", sha], timeout=120)
    if r.returncode:
        raise RuntimeError(f"checkout failed: {r.stderr.strip()[:200]}")
    return sha


def owner_roots():
    """[(name, tier, spec, tier_spec, backend)] for every applied_by owner root, from the worktree. The backend is the
    spec's state_backend with the tier's own settings merged in; what it means is the provider's business."""
    data = json.loads((WT / SPEC_FILE).read_text())
    sb = data.get("state_backend") or {}
    out = []
    for r in data["roots"]:
        if r.get("applied_by", "tfapply" if r.get("apply") else "owner") != "owner":
            continue
        for tier, ts in sorted(r["tiers"].items()):
            b = {k: v for k, v in sb.items() if k != "tiers"}
            b.update((sb.get("tiers") or {}).get(tier) or {})
            out.append((r["name"], tier, r, ts, b))
    return out


def _summarize(show):
    """Counts and resource list from terraform show -json."""
    counts = {"add": 0, "change": 0, "destroy": 0, "replace": 0, "import": 0}
    resources = []
    for rc in show.get("resource_changes") or []:
        acts = (rc.get("change") or {}).get("actions") or []
        imp = bool((rc.get("change") or {}).get("importing"))
        if acts == ["no-op"] and not imp:
            continue
        if acts in (["delete", "create"], ["create", "delete"]):
            action = "replace"
        elif acts == ["create"]:
            action = "add"
        elif acts == ["update"]:
            action = "change"
        elif acts == ["delete"]:
            action = "destroy"
        elif imp:
            action = "import"
        else:
            action = "/".join(acts)
        if action in counts:
            counts[action] += 1
        if imp and action != "import":
            counts["import"] += 1
        resources.append({"address": rc.get("address"), "type": rc.get("type"), "action": action})
    return counts, resources


def plan(name, tier, sha=None):
    key = _key(name, tier)
    log = LOGS / f"{name}-{tier}.log"
    LOGS.mkdir(parents=True, exist_ok=True)
    PLANS.mkdir(parents=True, exist_ok=True)
    os.chmod(PLANS, 0o700)
    log.write_text(f"plan {key} at {_now()}\n")
    _update(key, name=name, tier=tier, state="planning", started=_now(), error=None)
    try:
        sha = sha or _checkout_main()
        roots = {(n, t): (ts, b) for n, t, _, ts, b in owner_roots()}
        if (name, tier) not in roots:
            _update(key, state="gone", finished=_now())
            return
        ts, b = roots[(name, tier)]
        want = _expected_identity()
        user = _identity() if want else ""
        if want and user.lower() != want.lower():
            _update(
                key,
                state="auth",
                finished=_now(),
                main_sha=sha,
                error=f"Signed in as {user or 'nobody'}, not {want}.",
            )
            return
        root = WT / ts["root"]
        planfile = PLANS / f"{name}-{tier}.tfplan"
        planfile.unlink(missing_ok=True)
        _init(root, ts, b, log)
        args = [
            TF,
            "plan",
            "-input=false",
            "-no-color",
            "-lock-timeout=120s",
            "-detailed-exitcode",
            f"-out={planfile}",
        ]
        if ts.get("vars"):
            args.append(f"-var-file={ts['vars']}")
        p = _run(args, cwd=root, log=log)
        if p.returncode == 0:
            planfile.unlink(missing_ok=True)
            _update(
                key,
                state="clean",
                finished=_now(),
                main_sha=sha,
                counts=None,
                resources=[],
                plan_sha256=None,
                apply_failures=None,
                error=None,
            )
            _close_alert(name, tier, "The root re-planned clean, nothing is left to apply.")
            return
        if p.returncode != 2:
            raise RuntimeError("terraform plan failed: " + _tail(p))
        show = _run([TF, "show", "-json", str(planfile)], cwd=root)
        counts, resources = _summarize(json.loads(show.stdout))
        digest = hashlib.sha256(planfile.read_bytes()).hexdigest()
        os.chmod(planfile, 0o600)
        it = _update(
            key,
            state="pending",
            finished=_now(),
            main_sha=sha,
            counts=counts,
            resources=resources,
            plan_sha256=digest,
            planned_at=_now(),
            error=None,
        )
        if not it.get("pending_since"):
            _update(key, pending_since=_now())
    except Exception as e:  # noqa: BLE001 - every failure lands on the card, never silent
        msg = str(e)[:600]
        _update(key, state="auth" if AUTH_RE.search(msg) else "error", finished=_now(), error=msg)


def _init(root, ts, b, log):
    """terraform init against the tier's state backend (both tiers of a root share the directory,
    so every plan and apply re-inits for its own backend first)."""
    extra = [str(a) for a in (_hook("backend_args", ts, b, default=None) or [])]
    init = _run(
        [
            TF,
            "init",
            "-input=false",
            "-reconfigure",
            "-no-color",
            *extra,
            *([f"-backend-config=key={ts['key']}"] if ts.get("key") else []),
        ],
        cwd=root,
        log=log,
    )
    if init.returncode:
        raise RuntimeError("terraform init failed: " + _tail(init))


def _tail(p):
    lines = [x for x in (p.stderr + "\n" + p.stdout).splitlines() if x.strip()]
    errs = [x for x in lines if "Error" in x]
    return " | ".join((errs or lines)[-4:])[:500]


def _plan_deletes(show):
    """The ids a saved plan deletes (replaces included), from terraform show -json: what a provider needs to
    decide what to protect or unprotect around the apply."""
    ids = set()
    for rc in show.get("resource_changes") or []:
        change = rc.get("change") or {}
        if "delete" not in (change.get("actions") or []):
            continue
        before = change.get("before") or {}
        for field in ("id", "resource_id"):
            val = before.get(field)
            if isinstance(val, str) and val:
                ids.add(val.split("|")[0])
    return sorted(ids)


def log_event(rec):
    """A decision-log line a provider hook can write (same file and shape as the module's own)."""
    _log(rec)


def _apply_with_hooks(key, root, planfile, deletes, lock_state, log):
    """Run the provider's before_apply, apply the saved plan, then the provider's after_apply whatever happened. Returns
    (apply summary, restored). Raises when the apply fails, and also when after_apply reports an error (that one wins,
    it is worse)."""
    state, apply_err, summary = None, None, None
    try:
        state = _hook("before_apply", deletes, log, default=None)
        for attempt in range(APPLY_TRIES):
            p = _run(
                [TF, "apply", "-input=false", "-no-color", "-lock-timeout=120s", str(planfile)],
                cwd=root,
                log=log,
                timeout=3600,
            )
            if not p.returncode:
                summary = next(
                    (x for x in p.stdout.splitlines() if x.startswith("Apply complete!")),
                    "Apply complete.",
                )
                break
            # Terraform refuses a saved plan the state moved past, so a retry after a transient refusal cannot apply
            # anything twice.
            if (
                state is not None
                and "retry" in (p.stderr + p.stdout).lower()
                and attempt < APPLY_TRIES - 1
            ):
                time.sleep(float(os.environ.get("OWNER_ROOTS_RETRY_S", "10")))
                continue
            raise RuntimeError("terraform apply failed: " + _tail(p))
    except Exception as e:  # noqa: BLE001 - re-raised below after the provider has restored what it lifted
        apply_err = e
    finally:
        planfile.unlink(missing_ok=True)
    restored, errs = 0, []
    got = _hook("after_apply", state, log, default=None)
    if got:
        restored, errs = got
    if errs:
        _log({"decision": "owner_apply_lock_restore_failed", "root": key, "detail": errs})
        raise RuntimeError(
            "LOCKS NOT RESTORED, check them now: "
            + " | ".join(errs)
            + (f" (apply: {apply_err})" if apply_err else "")
        )
    if apply_err:
        raise apply_err
    return summary, restored


def _alert_id(name, tier):
    return re.sub(r"[^a-z0-9-]+", "-", f"{ALERT_PREFIX}{name}-{tier}".lower())[:81]


def _alert_repeat(name, tier, streak):
    """Raise one Action Center item once the same apply failure repeats on the same main.
    Never breaks the apply path: a store problem is only printed to the worker log."""
    if streak["count"] < REPEAT_ALERT and streak["kind"] != "locks_not_restored":
        return
    try:
        import automation_actions

        _, step = classify_error(streak["last"])
        automation_actions.raise_item(
            _alert_id(name, tier),
            title=f"Owner apply of {name} ({tier}) keeps failing the same way",
            why=(
                f"The Owner apply of {name} on {tier} failed {streak['count']} time(s) in a row on main "
                f"{(streak.get('main_sha') or '')[:8]} with the same {streak['kind']} error, so pressing Apply or Re-plan "
                f"again will not help. Last error: {streak['last'][:500]}"
            ),
            action=step,
            priority="high",
            owner="owner",
            refs=[f"owner root {name}:{tier}"],
            links=[{"label": "Open the reviews page", "url": base + "/#/platform"}]
            if (base := os.environ.get("OPSCENTER_BASE_URL", ""))
            else [],
            source="Alerts",
        )
    except Exception as e:  # noqa: BLE001 - the card already shows the failure
        print(f"owner apply alert not raised for {name}:{tier}: {e}", file=sys.stderr)


def _close_alert(name, tier, reason):
    try:
        import automation_actions

        automation_actions.close_item(_alert_id(name, tier), reason)
    except Exception as e:  # noqa: BLE001
        print(f"owner apply alert not closed for {name}:{tier}: {e}", file=sys.stderr)


def _apply_failed(key, msg, **extra):
    """One place an apply failure lands: state error, and last_apply_error that survives the
    re-plans that would otherwise turn the card back into a plain waiting Apply."""
    _update(
        key,
        state="error",
        finished=_now(),
        error=msg,
        last_apply_error={"at": _now(), "message": msg},
        **extra,
    )


def apply(name, tier, digest):
    key = _key(name, tier)
    it = _load_status().get("items", {}).get(key) or {}
    log = LOGS / f"{name}-{tier}.log"
    planfile = PLANS / f"{name}-{tier}.tfplan"
    if it.get("state") != "pending" or it.get("plan_sha256") != digest or not planfile.exists():
        _apply_failed(key, "The saved plan changed before apply. Re-plan and review it again.")
        return
    if hashlib.sha256(planfile.read_bytes()).hexdigest() != digest:
        _apply_failed(key, "The saved plan file does not match what the owner reviewed. Re-plan.")
        return
    _update(key, state="applying", started=_now(), error=None)
    _log(
        {
            "decision": "owner_apply_started",
            "root": key,
            "sha": it.get("main_sha"),
            "plan_sha256": digest,
            "counts": it.get("counts"),
            "by": _expected_identity(),
        }
    )
    try:
        head = _run([GIT, "-C", str(WT), "rev-parse", "HEAD"]).stdout.strip()
        if head != it.get("main_sha"):
            raise RuntimeError("the worktree moved since the plan. Re-plan.")
        roots = {(n, t): (ts, b) for n, t, _, ts, b in owner_roots()}
        ts, b = roots[(name, tier)]
        root = WT / ts["root"]
        _init(root, ts, b, log)
        # The provider may need to unprotect what the plan deletes (a lock, a policy) and must always restore it.
        show = _run([TF, "show", "-json", str(planfile)], cwd=root)
        if show.returncode:
            raise RuntimeError("terraform show failed: " + _tail(show))
        deletes = _plan_deletes(json.loads(show.stdout))
        lock_state = CACHE / "locks" / f"{name}-{tier}-{int(time.time())}"
        with open(log, "a") as fh:
            fh.write(f"\napply {key} at {_now()} plan {digest}\n")
        summary, locks = _apply_with_hooks(key, root, planfile, deletes, lock_state, log)
        _log(
            {
                "decision": "owner_apply_done",
                "root": key,
                "sha": it.get("main_sha"),
                "result": summary,
                "locks_restored": locks,
            }
        )
        _update(
            key,
            last_apply={
                "at": _now(),
                "result": summary,
                "sha": it.get("main_sha"),
                "locks_restored": locks,
            },
            last_apply_error=None,
            pending_since=None,
        )
    except Exception as e:  # noqa: BLE001
        msg = str(e)[:600]
        kind, _ = classify_error(msg)
        prev = it.get("apply_failures") or {}
        same = prev.get("kind") == kind and prev.get("main_sha") == it.get("main_sha")
        streak = {
            "kind": kind,
            "main_sha": it.get("main_sha"),
            "count": (prev.get("count") or 0) + 1 if same else 1,
            "since": prev.get("since") if same else _now(),
            "last": msg,
        }
        _log(
            {
                "decision": "owner_apply_failed",
                "root": key,
                "detail": msg,
                "kind": kind,
                "repeat": streak["count"],
            }
        )
        _apply_failed(key, msg, apply_failures=streak)
        planfile.unlink(missing_ok=True)
        _alert_repeat(name, tier, streak)
        return
    _update(key, apply_failures=None)
    _close_alert(name, tier, "The apply succeeded.")
    # Verify: a fresh plan of the same main must come back clean.
    plan(name, tier, sha=it.get("main_sha"))
    after = _load_status()["items"].get(key, {})
    verified = after.get("state") == "clean"
    _update(key, last_apply=dict(after.get("last_apply") or {}, verified=verified))
    _log(
        {
            "decision": "owner_apply_verified" if verified else "owner_apply_unverified",
            "root": key,
            "state": after.get("state"),
        }
    )


def plan_all():
    sha = _checkout_main()
    seen = set()
    for n, t, _, _, _ in owner_roots():
        seen.add(_key(n, t))
        plan(n, t, sha=sha)
    st = _load_status()
    for k in list(st.get("items", {})):
        if k not in seen:
            _update(k, state="gone")


# ---- sign-in ----
# Every Sign in click used to start another background sign-in prompt and leave the last one waiting, so
# five prompts sat open at once and nothing told me whether one had landed (2026-10-23). Now one
# worker owns the prompt: a new click ends the previous worker (by its process group, after
# checking its command line), the worker waits for sign-in prompt, checks the account, and re-plans
# every root itself. signin.json carries the state the card shows.


def _signin_load():
    try:
        return json.loads(SIGNIN.read_text())
    except (OSError, ValueError):
        return {}


def _signin_set(**fields):
    CACHE.mkdir(parents=True, exist_ok=True)
    st = _signin_load()
    st.update(fields)
    tmp = SIGNIN.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1))
    os.replace(tmp, SIGNIN)
    return st


def _is_signin_worker(pid):
    """True when pid is alive and is our sign-in worker (never kill a reused pid)."""
    if not pid:
        return False
    try:
        out = subprocess.run(
            ["ps", "-o", "command=", "-p", str(int(pid))],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return False
    cmd = out.stdout.strip()
    return out.returncode == 0 and "owner_roots.py" in cmd and cmd.rstrip().endswith(" signin")


def _take_op_lock(fh, wait_s):
    """Wait up to wait_s for the operation lock (a running plan or apply finishes first)."""
    end = time.time() + wait_s
    while True:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            if time.time() >= end:
                return False
            time.sleep(SIGNIN_POLL_S)


def signin_worker():
    """One sign-in prompt (the provider's command). On success as the expected account, re-plan every root under the
    operation lock."""
    LOGS.mkdir(parents=True, exist_ok=True)
    _signin_set(
        state="waiting", pid=os.getpid(), started=_now(), finished=None, user=None, error=None
    )
    argv = _hook("signin_cmd", default=None)
    if not argv:
        _signin_set(
            state="failed",
            finished=_now(),
            error="No sign-in is configured (OWNER_ROOTS_PROVIDER signin_cmd).",
        )
        return 1
    errlog = LOGS / "signin.log"
    with open(errlog, "w") as fh:
        # The prompt gets its own process group so ending it also ends anything it started.
        p = subprocess.Popen(
            [str(a) for a in argv],
            stdout=subprocess.DEVNULL,
            stderr=fh,
            stdin=subprocess.DEVNULL,
            env=_env(),
            preexec_fn=os.setpgrp,
        )

        def _end_prompt(*_):
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(p.pid, signal.SIGTERM)

        def _on_term(*_):
            _end_prompt()
            sys.exit(143)

        signal.signal(signal.SIGTERM, _on_term)
        try:
            code = p.wait(timeout=SIGNIN_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            _end_prompt()
            p.wait()
            _signin_set(
                state="failed",
                finished=_now(),
                error=f"The sign-in was not finished within {SIGNIN_TIMEOUT_S // 60} minutes. Press Sign in again.",
            )
            return 1
    if code != 0:
        tail = " ".join(errlog.read_text(errors="replace").split())[-400:]
        _signin_set(
            state="failed",
            finished=_now(),
            error=f"The sign-in failed (exit {code}). {tail}".strip(),
        )
        return 1
    want = _expected_identity()
    user = _identity()
    if want and user.lower() != want.lower():
        _signin_set(
            state="failed",
            finished=_now(),
            user=user,
            error=f"Signed in as {user or 'nobody'}, not {want}. Press Sign in and pick {want}.",
        )
        return 1
    _signin_set(state="replanning", user=user)
    with open(LOCK, "a") as lk:
        if not _take_op_lock(lk, SIGNIN_LOCK_WAIT_S):
            _signin_set(
                state="failed",
                finished=_now(),
                error="Signed in, but another plan or apply held the lock for 30 minutes. Press Re-plan.",
            )
            return 1
        plan_all()
    _signin_set(state="done", finished=_now())
    return 0


def signin_view():
    """What the card shows about the sign-in. A waiting or re-planning worker that died is failed."""
    st = _signin_load()
    if st.get("state") in ("waiting", "replanning") and not _is_signin_worker(st.get("pid")):
        st = dict(
            st, state="failed", error="The sign-in stopped before it finished. Press Sign in again."
        )
    return {k: st.get(k) for k in ("state", "started", "finished", "user", "error")} if st else None


def start_signin():
    """End our previous waiting sign-in worker (its whole process group, so its sign-in prompt too), then
    start one fresh prompt. A worker that already signed in and is re-planning is left alone."""
    prev = _signin_load()
    pid = prev.get("pid")
    if prev.get("state") == "replanning" and _is_signin_worker(pid):
        return False, "You are already signed in, and every Owner root is being re-planned now."
    ended = False
    if prev.get("state") == "waiting" and _is_signin_worker(pid):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(int(pid), signal.SIGTERM)
            ended = True
    LOGS.mkdir(parents=True, exist_ok=True)
    with open(LOGS / "worker.log", "a") as out:
        p = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "signin"],
            stdout=out,
            stderr=out,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=_env(),
        )
    threading.Thread(target=p.wait, daemon=True).start()  # reap it, the server is long-lived
    _signin_set(state="waiting", pid=p.pid, started=_now(), finished=None, user=None, error=None)
    note = " The earlier prompt was closed, so use the newest one." if ended else ""
    want = _expected_identity()
    who = f" as {want}" if want else ""
    return (
        True,
        f"Opened the sign-in. Sign in{who}. Every Owner root is re-planned by itself once it lands.{note}",
    )


# ---- server side ----


def _running():
    """True when a worker holds the operation lock."""
    CACHE.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "a") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(fh, fcntl.LOCK_UN)
    return False


def spawn(*args):
    """Start a detached worker (survives a server restart). Refuses while one is running."""
    if _running():
        return False
    LOGS.mkdir(parents=True, exist_ok=True)
    with open(LOGS / "worker.log", "a") as out:
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), *args],
            stdout=out,
            stderr=out,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=_env(),
        )
    return True


_MAIN = {"at": 0.0, "sha": None, "busy": False}
_MAIN_LOCK = threading.Lock()


def _read_main():
    try:
        out = _run(
            [GIT, "-C", str(SRC_REPO), "ls-remote", "origin", "refs/heads/main"], timeout=30
        ).stdout.split()
        sha = out[0] if out else None
    except (OSError, subprocess.SubprocessError):
        sha = None
    with _MAIN_LOCK:
        if sha or time.time() - _MAIN["at"] > 3 * MAIN_TTL_S:
            _MAIN["sha"] = sha
        _MAIN["at"] = time.time()
        _MAIN["busy"] = False


def live_main():
    """origin/main sha from GitHub (ls-remote). Served from cache, refreshed in the background once it is
    MAIN_TTL_S old, so a page GET never waits on git. The first call blocks once. None when unknown."""
    with _MAIN_LOCK:
        cold = _MAIN["at"] == 0.0 and not _MAIN["busy"]
        stale = time.time() - _MAIN["at"] > MAIN_TTL_S and not _MAIN["busy"]
        if cold or stale:
            _MAIN["busy"] = True
    if cold:
        _read_main()
    elif stale:
        threading.Thread(target=_read_main, daemon=True).start()
    return _MAIN["sha"]


def get():
    """Items with a phase the UI renders as is: needs_me (the owner can act on it now), in_flight (a plan or
    apply runs, or main moved so the plan is being redone), idle (clean). A card is only actionable
    when the server could actually carry the action out. The server thread runs
    maybe_refresh() every 60 s, so this GET only reads."""
    st = _load_status()
    running = _running()
    live = live_main()
    items = []
    now = time.time()
    for k, it in sorted(st.get("items", {}).items()):
        state = it.get("state")
        if state == "gone":
            continue
        planned = it.get("planned_at") or it.get("finished")
        age = now - _epoch(planned) if planned else None
        moved = bool(
            live and it.get("main_sha") and it["main_sha"] != live and state in ("pending", "clean")
        )
        if (
            state in ("planning", "applying")
            or (state == "pending" and moved)
            or (running and state in ("pending", "error", "auth"))
        ):
            phase = "in_flight"
        elif state in ("pending", "error", "auth"):
            phase = "needs_me"
        else:
            phase = "idle"
        kind, step = classify_error(it.get("error")) if state in ("error", "auth") else (None, None)
        items.append(
            dict(
                it,
                key=k,
                stale=bool(age and age > STALE_S),
                plan_file=None,
                main_moved=moved,
                phase=phase,
                error_kind=kind,
                error_next=step,
            )
        )
    return {
        "items": items,
        "running": running,
        "live_main": live,
        "updated": st.get("updated"),
        "signin": signin_view(),
    }


def needs_me(view):
    """Cards the owner can act on right now (see get() for the phase rules)."""
    return [x for x in view["items"] if x.get("phase") == "needs_me"]


def configured():
    """True when the clone of the infrastructure repo exists, so there is something to plan."""
    return (SRC_REPO / ".git").exists()


def maybe_refresh():
    """Re-plan every root when main moved past any plan (once per main sha) or the newest plan is
    older than REFRESH_S. Called by the server thread every minute and on every GET."""
    if not configured():
        return
    st = _load_status()
    items = [i for i in st.get("items", {}).values() if i.get("state") != "gone"]
    newest = max((_epoch(i.get("finished")) for i in items if i.get("finished")), default=0)
    live = live_main()
    moved = bool(live and any(i.get("main_sha") and i["main_sha"] != live for i in items))
    if moved and st.get("auto_planned_sha") != live:
        if spawn("plan-all"):
            _set_top(auto_planned_sha=live)
        return
    if time.time() - newest > REFRESH_S:
        spawn("plan-all")


def _set_top(**fields):
    with open(STATUS_LOCK, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        st = _load_status()
        st.update(fields)
        tmp = STATUS.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, indent=1))
        os.replace(tmp, STATUS)


def _epoch(s):
    try:
        return (
            dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
            .replace(tzinfo=dt.timezone.utc)
            .timestamp()
        )
    except (TypeError, ValueError):
        return 0


def request(payload, act):
    """Server entry for POST /api/owner-roots/<act>. Returns (code, body)."""
    st = _load_status().get("items", {})
    if act == "signin":
        _started, note = start_signin()
        return 202, {"done": [note]}
    if act == "plan-all":
        return (
            (202, {"done": ["re-planning every Owner root"]})
            if spawn("plan-all")
            else (409, {"error": "a plan or apply is already running"})
        )
    name, tier = str(payload.get("name") or ""), str(payload.get("tier") or "")
    key = _key(name, tier)
    if key not in st:
        return 404, {"error": f"{key} is not an Owner-applied root I track"}
    if act == "plan":
        return (
            (202, {"done": [f"re-planning {key}"]})
            if spawn("plan", name, tier)
            else (409, {"error": "a plan or apply is already running"})
        )
    if act == "apply":
        it = st[key]
        if it.get("state") != "pending":
            return 409, {"error": f"{key} has nothing to apply ({it.get('state')})."}
        if payload.get("plan_sha256") != it.get("plan_sha256"):
            return 409, {
                "error": "The plan changed since you loaded it. Refresh and review it again."
            }
        if str(payload.get("confirm") or "").strip() != name:
            return 400, {"error": f"Type {name} to confirm."}
        if time.time() - _epoch(it.get("planned_at")) > STALE_S:
            return 409, {"error": "The plan is more than a day old. Re-plan first."}
        live = _run(
            [GIT, "-C", str(SRC_REPO), "ls-remote", "origin", "refs/heads/main"], timeout=60
        ).stdout.split()
        if not live or live[0] != it.get("main_sha"):
            return 409, {"error": "main moved since this plan. Re-plan first."}
        if not spawn("apply", name, tier, it["plan_sha256"]):
            return 409, {"error": "a plan or apply is already running"}
        return 202, {"done": [f"applying the saved plan for {key}, then re-planning to verify"]}
    return 404, {"error": "unknown action"}


def main(argv):
    CACHE.mkdir(parents=True, exist_ok=True)
    if argv[:1] == ["signin"]:
        return signin_worker()  # takes the operation lock itself, only after the sign-in lands
    with open(LOCK, "a") as lk:
        try:
            fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("another owner-root operation is running")
            return 3
        if argv[:1] == ["plan-all"]:
            plan_all()
        elif argv[:1] == ["plan"] and len(argv) == 3:
            plan(argv[1], argv[2])
        elif argv[:1] == ["apply"] and len(argv) == 4:
            apply(argv[1], argv[2], argv[3])
        else:
            print(__doc__)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
