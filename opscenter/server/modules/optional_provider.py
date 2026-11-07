"""
optional_provider.py
Purpose: Loads the provider object of an optional module (log intake, reports) from `path/to/file.py:ClassName` named by an environment variable,
         the same contract as the other ops center provider slots. Every method of the object is optional; a missing one is the null default.
Date:    2026-11-07
API:     load(env_name) -> object | None     the file is read once per distinct value; a bad spec raises ProviderRefused (status 500, a short reason)
"""

import importlib.util
import os
import threading
from pathlib import Path

_lock = threading.Lock()
_cache = {}


class ProviderRefused(Exception):
    status = 500


def load(env_name):
    spec = os.environ.get(env_name, "").strip()
    if not spec:
        return None
    with _lock:
        if spec in _cache:
            return _cache[spec]
    path, _, cls_name = spec.rpartition(":")
    if not path or not cls_name:
        raise ProviderRefused(f"{env_name} must be `path/to/file.py:ClassName`")
    file = Path(path)
    if not file.is_file():
        raise ProviderRefused(f"provider file not found: {file.name}")
    ms = importlib.util.spec_from_file_location(f"optional_provider_{file.stem}", file)
    mod = importlib.util.module_from_spec(ms)
    try:
        ms.loader.exec_module(mod)
        obj = getattr(mod, cls_name)()
    except (OSError, ImportError, AttributeError, TypeError, SyntaxError) as exc:
        raise ProviderRefused(f"provider could not be loaded: {type(exc).__name__}") from exc
    with _lock:
        _cache[spec] = obj
    return obj


def method(provider, name):
    fn = getattr(provider, name, None) if provider is not None else None
    return fn if callable(fn) else None


def header(headers, name):
    """A request header by name, whatever case the client sent."""
    low = name.lower()
    for k, v in (headers or {}).items():
        if k.lower() == low:
            return v
    return ""


def actor_of(headers, provider, action, key=None):
    """Authorise one request through the provider's `authorize(headers, action, key) -> actor name | {name} | falsy`. With no provider or no
    method nothing is allowed: an admin route is closed until a consumer says who may use it. Returns the actor name."""
    fn = method(provider, "authorize")
    who = fn(headers, action, key) if fn else None
    if not who:
        raise PermissionError("not allowed: no authorizer grants this" if not fn else "not allowed")
    return who if isinstance(who, str) else str(who.get("name") or "user")
