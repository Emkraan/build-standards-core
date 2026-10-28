"""Model accounts, spend and limits for the Spend page (`/api/infra/accounts`).

The core owns the page contract and everything that does not depend on a vendor: response shaping, routing and cooldown, stale while
revalidate caching, the last good copy, spend snapshots and history, the token ledger reader and the token windows. What the accounts
are, and how each one is read, is a provider (`ModelAccountsProvider`, below). With no provider the page is empty and the routes answer.

This module makes no network call and reads no credential store. A provider that needs to read a credential pool says so with
`needs_credential_pool_read = True`, and the loader refuses it unless the consumer sets `OPSCENTER_MODEL_ACCOUNTS_ALLOW_POOL_READ=1`.

Parameters (environment):
  OPSCENTER_MODEL_ACCOUNTS_PROVIDER         `path/to/file.py:ClassName` of the provider (default: none, the null provider)
  OPSCENTER_MODEL_ACCOUNTS_ALLOW_POOL_READ  `1` lets a provider that declares a pool read load
  OPSCENTER_MODEL_LEDGER                    the per call usage JSONL (default <state>/usage/model-ledger.jsonl)
  OPSCENTER_DISPLAY_UTC_OFFSET_HOURS        offset for day and month boundaries (default 0)

Provider contract (all methods are called from server threads and must not block for long):
  credentials()          list of {cred_id, credential (label), priority, status, status_error, status_reset_at (epoch, epoch ms or
                         ISO), status_at (epoch), unavailable (a reason string when no live read is possible, optional)}
  read_usage(cred_id)    {billing_model: "usage" | "seat", kind, kind_label, org, seat_tier, rate_limit_tier, limits[], spend}
                         limits[] rows {kind, group, label, percent, severity, resets_at, is_active, window_s}; spend {enabled,
                         used_usd, limit_usd, percent, severity, currency, spend_limit_reached} or None. Raise ProviderUnavailable
                         for a per account problem; core keeps the last good reading and marks it stale.
  set_fallback_order(ids)  optional; absent means the order is changed outside the ops center
  stale_host()             optional; a dict describing a stale agent host, or None
"""

import datetime as dt
import importlib.util
import json
import os
import threading
import time
from pathlib import Path

import paths
import swr

USAGE_TTL = 60
SNAPSHOT_EVERY_S = 3600
LEDGER_KEEP_S = 40 * 86400
USAGE, SEAT = "usage", "seat"
LIMIT_LABEL = {
    "session": "Current session",
    "weekly_all": "Weekly, all models",
    "weekly_scoped": "Weekly",
}
DEFAULT_WINDOW_S = {"session": 5 * 3600, "weekly_all": 7 * 86400}

_lock = threading.Lock()
_ledger = {"path": None, "offset": 0, "inode": None, "rows": []}
_provider = {"spec": None, "obj": None}


class ProviderUnavailable(Exception):
    """A per account problem the provider reports; the account shows its last good reading, marked stale."""


class ProviderRefused(RuntimeError):
    """The configured provider was not loaded (a credential pool read the consumer has not enabled, or a bad spec)."""

    status = 403


class NullProvider:
    """No accounts: the page renders empty and every route still answers."""

    needs_credential_pool_read = False

    def credentials(self):
        return []

    def read_usage(self, cred_id):
        raise ProviderUnavailable("no provider configured")


# ---- provider loading -------------------------------------------------------------------------------------------------------


def load_provider(spec=None):
    """The provider named by `spec` (default OPSCENTER_MODEL_ACCOUNTS_PROVIDER), or the null provider when none is set."""
    spec = spec if spec is not None else os.environ.get("OPSCENTER_MODEL_ACCOUNTS_PROVIDER", "")
    spec = spec.strip()
    if not spec:
        return NullProvider()
    path, _, cls_name = spec.rpartition(":")
    if not path or not cls_name:
        raise ProviderRefused("provider must be `path/to/file.py:ClassName`")
    file = Path(path)
    if not file.is_file():
        raise ProviderRefused(f"provider file not found: {file.name}")
    mod_spec = importlib.util.spec_from_file_location(f"model_accounts_provider_{file.stem}", file)
    module = importlib.util.module_from_spec(mod_spec)
    try:
        mod_spec.loader.exec_module(module)
        obj = getattr(module, cls_name)()
    except (OSError, ImportError, AttributeError, TypeError, SyntaxError) as exc:
        raise ProviderRefused(f"provider could not be loaded: {type(exc).__name__}") from exc
    for need in ("credentials", "read_usage"):
        if not callable(getattr(obj, need, None)):
            raise ProviderRefused(f"provider lacks {need}()")
    if (
        getattr(obj, "needs_credential_pool_read", False)
        and os.environ.get("OPSCENTER_MODEL_ACCOUNTS_ALLOW_POOL_READ") != "1"
    ):
        raise ProviderRefused(
            "provider declares needs_credential_pool_read; set OPSCENTER_MODEL_ACCOUNTS_ALLOW_POOL_READ=1 to allow it"
        )
    return obj


def provider():
    spec = (
        os.environ.get("OPSCENTER_MODEL_ACCOUNTS_PROVIDER", "")
        + "|"
        + os.environ.get("OPSCENTER_MODEL_ACCOUNTS_ALLOW_POOL_READ", "")
    )
    if _provider["spec"] != spec:
        _provider["obj"] = load_provider()
        _provider["spec"] = spec
    return _provider["obj"]


def reset():
    """Forget the loaded provider, the cache and the ledger position (tests, and after a configuration change)."""
    _provider.update(spec=None, obj=None)
    _ledger.update(path=None, offset=0, inode=None, rows=[])
    swr.invalidate_prefix("model:")


# ---- files ------------------------------------------------------------------------------------------------------------------


def usage_dir():
    return paths.state_dir() / "usage"


def _kinds_file():
    return usage_dir() / "account-kinds.json"


def _last_file():
    return usage_dir() / "account-last.json"


def _snapshots_file():
    return usage_dir() / "spend-snapshots.jsonl"


def ledger_path():
    return Path(os.environ.get("OPSCENTER_MODEL_LEDGER") or usage_dir() / "model-ledger.jsonl")


def display_tz():
    try:
        hours = float(os.environ.get("OPSCENTER_DISPLAY_UTC_OFFSET_HOURS") or 0)
    except ValueError:
        hours = 0.0
    return dt.timezone(dt.timedelta(hours=hours))


def _read_json(path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def _write_json(path, obj):
    tmp = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(obj, indent=1))
        tmp.replace(path)
    except OSError as exc:
        print(f"model_accounts: cannot persist {path.name}: {exc}")


def _utc_now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso(epoch):
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch(value):
    """Epoch seconds, epoch milliseconds or ISO 8601 to epoch seconds."""
    if value in (None, ""):
        return None
    try:
        num = float(value)
        return num / 1000.0 if num > 1_000_000_000_000 else (num if num > 0 else None)
    except (TypeError, ValueError):
        pass
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


# ---- shaping the provider's reading ----------------------------------------------------------------------------------------


def clean_limits(rows):
    out = []
    for lim in rows or []:
        kind = str(lim.get("kind") or "")
        out.append(
            {
                "kind": kind,
                "group": lim.get("group"),
                "label": lim.get("label")
                or LIMIT_LABEL.get(kind, kind.replace("_", " ").capitalize()),
                "percent": lim.get("percent") or 0,
                "severity": lim.get("severity") or "normal",
                "resets_at": lim.get("resets_at"),
                "is_active": bool(lim.get("is_active")),
                "window_s": lim.get("window_s") or DEFAULT_WINDOW_S.get(kind),
            }
        )
    return out


def clean_spend(sp):
    if not sp:
        return None
    return {
        "enabled": bool(sp.get("enabled")),
        "used_usd": sp.get("used_usd") or 0.0,
        "limit_usd": sp.get("limit_usd"),
        "percent": sp.get("percent") or 0,
        "severity": sp.get("severity") or "normal",
        "currency": sp.get("currency") or "USD",
        "spend_limit_reached": bool(sp.get("spend_limit_reached")),
    }


_LAST_KEYS = (
    "kind",
    "kind_label",
    "billing_model",
    "org",
    "seat_tier",
    "rate_limit_tier",
    "limits",
    "spend",
    "fetched_utc",
)


def _label_of(kind):
    return (kind or "unknown").replace("_", " ").capitalize()


def account_kinds():
    """{account id: billing model} from the last successful reads."""
    return {
        k: v.get("billing_model")
        for k, v in _read_json(_kinds_file(), {}).items()
        if isinstance(v, dict)
    }


def _remember_kind(cid, rec):
    cur = _read_json(_kinds_file(), {})
    new = {
        "kind": rec["kind"],
        "kind_label": rec["kind_label"],
        "billing_model": rec["billing_model"],
    }
    if cur.get(cid) != new:
        cur[cid] = new
        _write_json(_kinds_file(), cur)


def _remember_last(cid, rec):
    cur = _read_json(_last_file(), {})
    cur[cid] = {k: rec.get(k) for k in _LAST_KEYS}
    _write_json(_last_file(), cur)


def _from_last(rec, why):
    """Fill rec from the last good reading; with none, show the remembered kind and the error."""
    cid = rec["cred_id"]
    last = _read_json(_last_file(), {}).get(cid)
    if last and last.get("fetched_utc"):
        rec.update({k: last.get(k) for k in _LAST_KEYS})
        rec["limits"] = rec.get("limits") or []
        rec["stale"] = why
        return rec
    known = _read_json(_kinds_file(), {}).get(cid)
    if known:
        rec.update({k: known.get(k) for k in ("kind", "kind_label", "billing_model")})
    rec["error"] = why
    return rec


def _account(prov, cred):
    cid = str(cred.get("cred_id") or "?")
    rec = {
        "cred_id": cid,
        "credential": cred.get("credential") or cid,
        "priority": cred.get("priority", 0),
        "pool_status": cred.get("status"),
        "pool_error": cred.get("status_error"),
        "pool_reset_at": cred.get("status_reset_at"),
        "kind": None,
        "kind_label": "Unknown",
        "billing_model": None,
        "org": None,
        "seat_tier": None,
        "rate_limit_tier": None,
        "limits": [],
        "spend": None,
        "fetched_utc": None,
        "error": None,
        "stale": None,
    }
    if cred.get("unavailable"):
        return _from_last(rec, str(cred["unavailable"])[:200])
    try:
        usage, at = swr.cached_at(f"model:usage:{cid}", USAGE_TTL, lambda: prov.read_usage(cid))
    except ProviderUnavailable as exc:
        return _from_last(rec, str(exc)[:200])
    except Exception as exc:  # a provider bug must not take the page down
        return _from_last(rec, f"usage lookup failed: {type(exc).__name__}: {str(exc)[:160]}")
    kind = usage.get("kind")
    rec.update(
        {
            "kind": kind,
            "kind_label": usage.get("kind_label") or _label_of(kind),
            "billing_model": USAGE if usage.get("billing_model") == USAGE else SEAT,
            "org": usage.get("org"),
            "seat_tier": usage.get("seat_tier"),
            "rate_limit_tier": usage.get("rate_limit_tier"),
            "limits": clean_limits(usage.get("limits")),
            "spend": clean_spend(usage.get("spend")),
            "fetched_utc": _iso(at),
        }
    )
    _remember_kind(cid, rec)
    _remember_last(cid, rec)
    if rec["spend"] and rec["billing_model"] == USAGE:
        _snapshot_spend(cid, rec["spend"]["used_usd"], at)
    return rec


# ---- spend snapshots and history --------------------------------------------------------------------------------------------


def _snapshots(cid=None):
    out = []
    try:
        with _snapshots_file().open() as fh:
            for line in fh:
                try:
                    s = json.loads(line)
                except ValueError:
                    continue
                if cid is None or s.get("cred_id") == cid:
                    out.append(s)
    except OSError:
        pass
    return out


def _snapshot_spend(cid, used_usd, at):
    """Append when the billed figure moves, or hourly, so day boundaries are covered."""
    with _lock:
        last = (_snapshots(cid)[-1:] or [None])[0]
        if (
            last
            and last.get("used_usd") == used_usd
            and at - float(last.get("ts") or 0) < SNAPSHOT_EVERY_S
        ):
            return
        try:
            _snapshots_file().parent.mkdir(parents=True, exist_ok=True)
            with _snapshots_file().open("a") as fh:
                fh.write(
                    json.dumps({"ts": round(at, 1), "cred_id": cid, "used_usd": used_usd}) + "\n"
                )
        except OSError as exc:
            print(f"model_accounts: cannot record spend snapshot: {exc}")


def spend_history(cid, days=31, now=None):
    """Billed dollars per day from the snapshots, plus a daily burn rate. A drop in the running total means the billing period
    rolled over, so that day's charge is the new total. The first tracked day is partial."""
    snaps = sorted(_snapshots(cid), key=lambda s: s["ts"])
    if not snaps:
        return {"since_utc": None, "daily": [], "rate_per_day": None, "rate_basis_days": 0}
    tz = display_tz()
    by_day = {}
    for s in snaps:
        by_day[dt.datetime.fromtimestamp(s["ts"], tz).date().isoformat()] = s
    daily, prev = [], None
    first_day = dt.datetime.fromtimestamp(snaps[0]["ts"], tz).date().isoformat()
    for day in sorted(by_day):
        end = float(by_day[day]["used_usd"])
        delta = (
            end - float(snaps[0]["used_usd"])
            if prev is None
            else (end - prev if end >= prev else end)
        )
        daily.append(
            {"date": day, "usd": round(delta, 2), "partial": day == first_day, "total": end}
        )
        prev = end
    now = time.time() if now is None else now
    window = [s for s in snaps if s["ts"] >= now - 7 * 86400]
    rate, basis = None, 0.0
    if len(window) >= 2 and window[-1]["ts"] - window[0]["ts"] >= 86400:
        burned = 0.0
        for a, b in zip(window, window[1:]):
            burned += (
                b["used_usd"] - a["used_usd"] if b["used_usd"] >= a["used_usd"] else b["used_usd"]
            )
        basis = (window[-1]["ts"] - window[0]["ts"]) / 86400
        rate = round(burned / basis, 2)
    return {
        "since_utc": _iso(snaps[0]["ts"]),
        "daily": daily[-days:],
        "rate_per_day": rate,
        "rate_basis_days": round(basis, 1),
    }


# ---- the local token ledger -------------------------------------------------------------------------------------------------


def _ledger_rows():
    """Incrementally tail the per call JSONL: ts, cred_id, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
    kind (main or aux)."""
    path = ledger_path()
    try:
        st = path.stat()
    except OSError:
        return []
    with _lock:
        if (
            _ledger["path"] != str(path)
            or _ledger["inode"] != st.st_ino
            or st.st_size < _ledger["offset"]
        ):
            _ledger.update(path=str(path), offset=0, inode=st.st_ino, rows=[])
        with path.open("rb") as fh:
            fh.seek(_ledger["offset"])
            chunk = fh.read()
        end = chunk.rfind(b"\n") + 1  # leave a half written last line for the next pass
        _ledger["offset"] += end
        for line in chunk[:end].splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            _ledger["rows"].append(
                (
                    float(r.get("ts") or 0),
                    r.get("cred_id"),
                    int(r.get("input_tokens") or 0),
                    int(r.get("output_tokens") or 0),
                    int(r.get("cache_read_tokens") or 0),
                    int(r.get("cache_write_tokens") or 0),
                    r.get("kind") or "main",
                )
            )
        cutoff = time.time() - LEDGER_KEEP_S
        if _ledger["rows"] and _ledger["rows"][0][0] < cutoff:
            _ledger["rows"] = [x for x in _ledger["rows"] if x[0] >= cutoff]
        return list(_ledger["rows"])


def _tok(rows, cred, since):
    out = {"calls": 0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    for ts, cid, i, o, cr, cw, _kind in rows:
        if ts >= since and cid == cred:
            out["calls"] += 1
            out["input"] += i
            out["output"] += o
            out["cache_read"] += cr
            out["cache_write"] += cw
    out["total"] = out["input"] + out["output"] + out["cache_read"] + out["cache_write"]
    return out


def _windows(acc, now=None):
    """Token windows: today, the last 7 days, the month, and, when the limits carry a reset and a window length, the session and
    the week that line up with what the account is metered on."""
    tz = display_tz()
    now = dt.datetime.now(tz) if now is None else now
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    win = {
        "today": day0.timestamp(),
        "d7": now.timestamp() - 7 * 86400,
        "month": day0.replace(day=1).timestamp(),
    }
    for lim in acc.get("limits") or []:
        reset = _epoch(lim.get("resets_at"))
        span = lim.get("window_s")
        if not reset or not span:
            continue
        if lim["kind"] == "session":
            win["session"] = reset - span
        elif lim["kind"] == "weekly_all":
            win["week"] = reset - span
    return win


# ---- the document -----------------------------------------------------------------------------------------------------------


def _route(creds, rows, now):
    """Routing owner: the lowest priority entry that is not cooling down and has no error. Cooling comes from an exhausted status
    with a reset in the future (or no reset, assumed an hour from the status time), or any limit at 100 percent with a future reset."""
    primary = None
    for cred, r in zip(creds, rows):
        reset = _epoch(cred.get("status_reset_at"))
        if reset is None and cred.get("status") == "exhausted" and cred.get("status_at"):
            reset = float(cred["status_at"]) + 3600
        r["pool_reset_at"] = _iso(reset) if reset else None
        cooling = cred.get("status") == "exhausted" and (reset is None or reset > now)
        capped = [
            lim
            for lim in r.get("limits") or []
            if lim.get("percent", 0) >= 100 and lim.get("resets_at")
        ]
        cap_reset = max((_epoch(lim["resets_at"]) or 0 for lim in capped), default=0)
        if cap_reset > now:
            cooling = True
            reset = max(reset or 0, cap_reset)
            r["pool_reset_at"] = _iso(reset)
        r["cooling_down"] = cooling
        if primary is None and not cooling and not r["error"]:
            primary = r["cred_id"]
    for r in rows:
        r["routing"] = r["cred_id"] == primary


def list_accounts():
    """The AccountsDoc the Spend page reads: {generated_utc, accounts[], ledger}."""
    prov = provider()
    creds = sorted(prov.credentials() or [], key=lambda c: c.get("priority", 0))
    rows = [_account(prov, c) for c in creds]
    _route(creds, rows, time.time())
    if isinstance(prov, NullProvider):
        return {"generated_utc": _utc_now(), "accounts": [], "ledger": None}
    led = _ledger_rows()
    first = min((x[0] for x in led), default=None)
    for r in rows:
        r["tokens"] = {k: _tok(led, r["cred_id"], since) for k, since in _windows(r).items()}
        if r["billing_model"] == USAGE:
            r["spend_history"] = spend_history(r["cred_id"])
    known = {r["cred_id"] for r in rows}
    d7 = time.time() - 7 * 86400
    ua = {"calls": 0, "total": 0, "aux_calls": 0}
    for ts, cid, i, o, cr, cw, kind in led:
        if cid not in known and ts >= d7:
            ua["calls"] += 1
            ua["total"] += i + o + cr + cw
            ua["aux_calls"] += kind == "aux"
    return {
        "generated_utc": _utc_now(),
        "accounts": rows,
        "ledger": {
            "since_utc": _iso(first) if first else None,
            "rows": len(led),
            "unattributed_d7": ua,
        },
    }


def get():
    return list_accounts()


def fallback_order():
    """Accounts in priority order with who routes now: [{cred_id, priority, routing, cooling_down}]."""
    return [
        {
            "cred_id": a["cred_id"],
            "priority": a["priority"],
            "routing": a["routing"],
            "cooling_down": a["cooling_down"],
        }
        for a in list_accounts()["accounts"]
    ]


def order_get():
    return {
        "order": fallback_order(),
        "writable": callable(getattr(provider(), "set_fallback_order", None)),
    }


def order_set(payload):
    ids = payload.get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise ValueError("ids must be a list of account ids")
    setter = getattr(provider(), "set_fallback_order", None)
    if not callable(setter):
        err = RuntimeError("this provider does not support changing the fallback order")
        err.status = 501
        raise err
    setter(ids)
    swr.invalidate_prefix("model:")
    return {"order": fallback_order()}


def sample():
    """For a background thread: reading the accounts is what records the spend snapshots, with the page closed."""
    try:
        list_accounts()
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"model_accounts: sample failed: {exc}")


if __name__ == "__main__":
    print(json.dumps(list_accounts(), indent=1))
