"""Weekly reachability check for the Links page catalog (opscenter/DESIGN.md section 12.3, item 20).

Purpose: Resolve every catalog host and send one HEAD per link (redirects not followed, so a sign in
         redirect counts as alive). A link is dead at once when its host does not resolve or it answers
         404 or 410. A timeout, refused connection or TLS failure only counts as dead when the previous
         run also failed for that link, so one network blip never raises an item. Links noted On network
         are skipped because the host is not always on the corporate network.
         Results go to <state>/dashboard/link-health.json. The Links page shows a Not reachable pill on the
         link and a Link health card where each dead link has Swap (correct the address) and Remove. Both
         re-check first, then edit the catalog on a fresh branch off origin/main and open the pull request
         in the consumer's repository (the automerge lane takes it, the deploy ships it). Pending edits are
         kept in <state>/dashboard/link-edits.json so the badge drops at once.
Parameters (local/params.json `links`, or the environment variable in brackets):
  catalog_file     the catalog in the consumer's repo [LINKS_CATALOG], default <root>/local/links-catalog.json
  catalog_rel      its path inside the repo, for the edit pull request [LINKS_CATALOG_REL]
  repo             owner/name of the repo the edit pull request opens in [LINKS_GH_REPO]
  repo_dir         local clone [LINKS_REPO]
  changelog_tool   optional script in the repo with `new --staged --pr N --title T --summary S` and
                   `check --staged --pr N`, run before the commit [LINKS_CHANGELOG_TOOL]; unset means none
  git_name, git_email  the identity of the edit commit (a noreply address) [LINKS_GIT_NAME, LINKS_GIT_EMAIL]
The catalog is the consumer's data, never core: {"groups": [{"id", "title", "links": [{"name", "url", "note"?}]}]}.
Usage:
  python3 link_health.py check [--catalog PATH] [--out PATH] [--dry-run]
      Run the check. Prints one line per dead link (job output, empty when all are alive).
Exit codes: 0 check ran (dead links are reported, not a failure), 1 catalog missing or unreadable.
"""

import argparse
import datetime as dt
import http.client
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import paths

CATALOG = Path(os.environ.get("LINKS_CATALOG") or paths.root() / "local" / "links-catalog.json")
OUT = paths.dashboard_dir() / "link-health.json"
TIMEOUT_S = 10
SKIP_NOTES = ("on network",)
HARD_DEAD_CODES = (404, 410)
USER_AGENT = "ops-center-link-health/1.0"
EDITS = paths.dashboard_dir() / "link-edits.json"
EDIT_TTL_S = 2 * 86400  # a pending edit hides its link for 2 days, the merge lane needs minutes
REPO = Path(os.environ.get("LINKS_REPO") or paths.repos_dir() / "ops-center")
CATALOG_REL = os.environ.get("LINKS_CATALOG_REL", "local/links-catalog.json")
CHANGELOG_TOOL = os.environ.get(
    "LINKS_CHANGELOG_TOOL", ""
)  # path in the repo; empty means no changelog step
GH = os.environ.get("LINKS_GH_BIN", paths.which("gh"))
GIT = os.environ.get("LINKS_GIT_BIN", "git")
GH_REPO = os.environ.get("LINKS_GH_REPO", "owner/ops-center")
IDENT = [
    "-c",
    "user.name=" + os.environ.get("LINKS_GIT_NAME", "ops-center"),
    "-c",
    "user.email=" + os.environ.get("LINKS_GIT_EMAIL", "ops-center@users.noreply.github.com"),
]
_EDIT_LOCK = threading.Lock()


def _now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_catalog(path=CATALOG):
    """Flat list of {name, url, group, note} from the catalog."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    for g in data.get("groups", []):
        for link in g.get("links", []):
            out.append(
                {
                    "name": link["name"],
                    "url": link["url"],
                    "group": g.get("title", ""),
                    "note": link.get("note"),
                }
            )
    return out


def _resolves(host):
    try:
        socket.getaddrinfo(host, None)
        return True
    except (socket.gaierror, UnicodeError):
        return False


def _request(method, parts):
    if parts.scheme == "https":
        conn = http.client.HTTPSConnection(
            parts.hostname, parts.port, timeout=TIMEOUT_S, context=ssl.create_default_context()
        )
    else:
        conn = http.client.HTTPConnection(parts.hostname, parts.port, timeout=TIMEOUT_S)
    try:
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        conn.request(method, path, headers={"User-Agent": USER_AGENT})
        return conn.getresponse().status
    finally:
        conn.close()


def probe(url, resolves=_resolves, request=_request):
    """One link -> (kind, reason, code). kind is ok, hard (dead now) or soft (dead on a repeat)."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return "hard", "Not a web address", None
    if not resolves(parts.hostname):
        return "hard", "Host does not resolve", None
    try:
        code = request("HEAD", parts)
        if code in (405, 501):
            code = request("GET", parts)
    except (TimeoutError, socket.timeout):
        return "soft", "Timed out", None
    except ssl.SSLError as e:
        return "soft", f"TLS failed ({e.reason or 'handshake'})", None
    except (ConnectionError, OSError, http.client.HTTPException) as e:
        return "soft", f"Connection failed ({type(e).__name__})", None
    if code in HARD_DEAD_CODES:
        return "hard", f"HTTP {code}", code
    return "ok", f"HTTP {code}", code


def classify(links, prev, probe_fn=probe, now=None):
    """Probe every link and fold in the previous run. Returns the link-health document."""
    now = now or _now()
    prev_links = (prev or {}).get("links", {})
    todo = [x for x in links if not (x.get("note") or "").lower().startswith(SKIP_NOTES)]
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = dict(zip([x["url"] for x in todo], pool.map(lambda x: probe_fn(x["url"]), todo)))
    rows = {}
    for x in links:
        url = x["url"]
        before = prev_links.get(url) or {}
        if url not in results:
            rows[url] = {
                "name": x["name"],
                "group": x["group"],
                "state": "skipped",
                "reason": x.get("note") or "Skipped",
            }
            continue
        kind, reason, code = results[url]
        failed_before = before.get("state") in ("dead", "warn")
        if kind == "ok":
            state = "ok"
        elif kind == "hard" or failed_before:
            state = "dead"
        else:
            state = "warn"
        row = {
            "name": x["name"],
            "group": x["group"],
            "state": state,
            "reason": reason,
            "code": code,
        }
        if state != "ok":
            row["since"] = before.get("since") if failed_before and before.get("since") else now
        rows[url] = row
    dead = [dict(url=u, **r) for u, r in rows.items() if r["state"] == "dead"]
    return {
        "checked_utc": now,
        "total": len(links),
        "checked": len(todo),
        "skipped": len(links) - len(todo),
        "counts": {
            s: sum(1 for r in rows.values() if r["state"] == s)
            for s in ("ok", "warn", "dead", "skipped")
        },
        "links": rows,
        "dead": dead,
    }


EMPTY = {"checked_utc": None, "links": {}, "dead": [], "counts": {}}


class EditError(Exception):
    """A Swap or Remove that cannot go ahead. status is the HTTP status the server answers with."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _read_json(path, default):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    return data if isinstance(data, type(default)) else default


def _write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _age_s(iso):
    try:
        then = dt.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return float("inf")
    return (dt.datetime.now(dt.timezone.utc) - then).total_seconds()


def _live_edits(edits, live_urls):
    """Pending edits still worth showing: the old address is still in the catalog and the edit is recent."""
    return {
        u: e
        for u, e in _read_json(edits, {}).items()
        if (live_urls is None or u in live_urls) and _age_s(e.get("at")) < EDIT_TTL_S
    }


def read_state(out=OUT, edits=EDITS, catalog=CATALOG):
    """The last check for GET /api/links/health. Never raises: a missing file reads as not run yet.
    Dead links that left the catalog this server ships (a merged and deployed edit) drop out, and a
    dead link with a pending edit carries it as `edit`."""
    data = _read_json(out, dict(EMPTY))
    try:
        live = {x["url"] for x in load_catalog(catalog)}
    except (OSError, ValueError, KeyError):
        live = None
    pending = _live_edits(edits, live)
    data["dead"] = [
        dict(d, edit=pending[d["url"]]) if d.get("url") in pending else d
        for d in data.get("dead") or []
        if live is None or d.get("url") in live
    ]
    data["edits"] = pending
    return data


def dead_count(out=OUT, edits=EDITS, catalog=CATALOG):
    """Dead links nobody has acted on yet (the Links nav badge)."""
    return sum(1 for d in read_state(out, edits, catalog)["dead"] if not d.get("edit"))


def run_check(catalog=CATALOG, out=OUT):
    """Run the check now and write the state file. Returns the new document."""
    doc = classify(load_catalog(catalog), _read_json(out, dict(EMPTY)))
    _write_json(out, doc)
    return doc


def _run(args, cwd=None, check=True, timeout=120):
    try:
        p = subprocess.run(
            [str(a) for a in args], cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise EditError(f"{Path(str(args[0])).name} failed: {e}", 502) from e
    if check and p.returncode != 0:
        detail = (p.stderr or p.stdout).strip()[-300:]
        raise EditError(
            f"{Path(str(args[0])).name} {args[1] if len(args) > 1 else ''} failed: {detail}", 502
        )
    return p.stdout


def _find(data, url):
    for g in data.get("groups", []):
        for link in g.get("links", []):
            if link.get("url") == url:
                return g, link
    return None, None


def open_catalog_pr(mutate, title, summary, branch, repo=REPO, runner=_run):
    """Apply mutate(catalog dict) to the catalog on a fresh branch off origin/main, add the changelog
    entry for the PR number when a changelog tool is set, push and open the PR. Returns (number, url). The temp worktree and the
    local branch are always removed."""
    tmp = Path(tempfile.mkdtemp(prefix="links-edit-"))
    wt = tmp / "wt"
    runner([GIT, "-C", repo, "fetch", "-q", "origin", "main"])
    runner([GIT, "-C", repo, "worktree", "add", "-q", "-b", branch, wt, "origin/main"])
    try:
        cat = wt / CATALOG_REL
        data = json.loads(cat.read_text(encoding="utf-8"))
        mutate(data)
        cat.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        last = runner(
            [GH, "api", f"repos/{GH_REPO}/issues?state=all&per_page=1", "--jq", ".[0].number"]
        )
        num = int(last.strip()) + 1
        runner([GIT, "-C", wt, "add", "--", CATALOG_REL])
        if CHANGELOG_TOOL:
            cl = [sys.executable, CHANGELOG_TOOL]
            runner(
                cl + ["new", "--staged", "--pr", num, "--title", title, "--summary", summary],
                cwd=wt,
            )
            runner([GIT, "-C", wt, "add", "--", "CHANGELOG.md"])
            runner(cl + ["check", "--staged", "--pr", num], cwd=wt)
        runner([GIT, "-C", wt, *IDENT, "commit", "-q", "-m", title])
        runner([GIT, "-C", wt, "push", "-q", "-u", "origin", branch])
        body = f"{summary}\n\nOpened from the Links page (Link health). CI is the gate, the merge lane takes it."
        out = runner(
            [
                GH,
                "pr",
                "create",
                "-R",
                GH_REPO,
                "--base",
                "main",
                "--head",
                branch,
                "--title",
                title,
                "--body",
                body,
            ]
        )
        pr_url = out.strip().splitlines()[-1]
        actual = int(pr_url.rstrip("/").rsplit("/", 1)[1])
        if CHANGELOG_TOOL and actual != num:
            log = wt / "CHANGELOG.md"
            log.write_text(
                log.read_text(encoding="utf-8").replace(f"## [#{num}] ", f"## [#{actual}] ", 1),
                encoding="utf-8",
            )
            runner([GIT, "-C", wt, "add", "--", "CHANGELOG.md"])
            runner([GIT, "-C", wt, *IDENT, "commit", "-q", "--amend", "--no-edit"])
            runner([GIT, "-C", wt, "push", "-q", "--force-with-lease", "origin", branch])
        return actual, pr_url
    finally:
        runner([GIT, "-C", repo, "worktree", "remove", "--force", wt], check=False)
        runner([GIT, "-C", repo, "branch", "-D", branch], check=False)
        shutil.rmtree(tmp, ignore_errors=True)


def _slug(text):
    out = "".join(c if c.isalnum() else "-" for c in text.lower())
    return "-".join(p for p in out.split("-") if p)[:40]


def _pr_open(num, runner):
    try:
        return (
            runner(
                [GH, "pr", "view", num, "-R", GH_REPO, "--json", "state", "--jq", ".state"]
            ).strip()
            == "OPEN"
        )
    except EditError:
        return True  # cannot tell, so never stack a second PR on the same link


def edit_link(
    action,
    url,
    new_url=None,
    *,
    probe_fn=None,
    open_pr=open_catalog_pr,
    runner=_run,
    out=OUT,
    edits=EDITS,
    catalog=CATALOG,
):
    """Swap (correct the address) or Remove one link by PR. Re-checks before acting.
    Returns {status: 'pr', pr, pr_url, message} or {status: 'alive', message} when a link to remove
    answers again (its health row is cleared). Raises EditError when it cannot go ahead."""
    probe_fn = probe_fn or probe
    if action not in ("swap", "remove"):
        raise EditError("action must be swap or remove")
    links = load_catalog(catalog)
    target = next((x for x in links if x["url"] == url), None)
    if target is None:
        raise EditError("That link is not on the Links page", 404)
    if not _EDIT_LOCK.acquire(blocking=False):
        raise EditError("Another link change is being opened, try again in a minute", 409)
    try:
        pending = _read_json(edits, {})
        prior = pending.get(url)
        if prior and _age_s(prior.get("at")) < EDIT_TTL_S and _pr_open(prior.get("pr"), runner):
            raise EditError(f"PR #{prior.get('pr')} is already open for {target['name']}", 409)
        name = target["name"]
        if action == "swap":
            new_url = (new_url or "").strip()
            parts = urllib.parse.urlsplit(new_url)
            if parts.scheme not in ("http", "https") or not parts.hostname:
                raise EditError("The new address must start with https:// or http://")
            if new_url == url:
                raise EditError("The new address is the same as the old one")
            if any(x["url"] == new_url for x in links):
                raise EditError("That address is already on the Links page")
            kind, reason, _ = probe_fn(new_url)
            if kind != "ok":
                raise EditError(
                    f"The new address does not answer ({reason}). Nothing changed.", 422
                )
            title = f"fix(links): correct the {name} address"
            summary = f"I corrected the {name} link on the Links page to {new_url} (the old address {url} no longer works)."

            def mutate(data):
                _, link = _find(data, url)
                if link is None:
                    raise EditError(f"{name} already changed on main", 409)
                link["url"] = new_url
        else:
            kind, reason, code = probe_fn(url)
            if kind == "ok":
                health = _read_json(out, dict(EMPTY))
                health["dead"] = [d for d in health.get("dead") or [] if d.get("url") != url]
                if url in health.get("links", {}):
                    health["links"][url].update(state="ok", reason=reason, code=code)
                    health["links"][url].pop("since", None)
                _write_json(out, health)
                return {
                    "status": "alive",
                    "message": f"{name} answers again ({reason}), so I left it and cleared the flag.",
                }
            title = f"fix(links): remove {name}"
            summary = (
                f"I removed the {name} link from the Links page. {url} no longer works ({reason})."
            )

            def mutate(data):
                group, link = _find(data, url)
                if link is None:
                    raise EditError(f"{name} already changed on main", 409)
                group["links"].remove(link)
                data["groups"] = [g for g in data["groups"] if g.get("links")]

        branch = f"links/{action}-{_slug(name)}-{dt.datetime.now().strftime('%Y%m%d%H%M%S')}"
        num, pr_url = open_pr(mutate, title, summary, branch)
        pending = {
            u: e for u, e in _read_json(edits, {}).items() if _age_s(e.get("at")) < EDIT_TTL_S
        }
        pending[url] = {
            "action": action,
            "new_url": new_url if action == "swap" else None,
            "pr": num,
            "pr_url": pr_url,
            "at": _now(),
        }
        _write_json(edits, pending)
        verb = "Swap" if action == "swap" else "Removal"
        return {
            "status": "pr",
            "pr": num,
            "pr_url": pr_url,
            "message": f"{verb} of {name} is in PR #{num}. The merge lane takes it.",
        }
    finally:
        _EDIT_LOCK.release()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Links page reachability check (improvement-id)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--catalog", default=str(CATALOG))
    c.add_argument("--out", default=str(OUT))
    c.add_argument(
        "--dry-run", action="store_true", help="print the result, do not write the state file"
    )
    opts = ap.parse_args(argv)
    try:
        links = load_catalog(opts.catalog)
    except (OSError, ValueError, KeyError) as e:
        print(f"Link health check could not read the catalog {opts.catalog}: {e}")
        return 1
    doc = classify(links, _read_json(opts.out, dict(EMPTY)))
    if opts.dry_run:
        print(json.dumps(doc["counts"]))
        for url, r in doc["links"].items():
            if r["state"] in ("dead", "warn"):
                print(f"{r['state']:5} {r['name']}: {r['reason']} ({url})")
        return 0
    _write_json(opts.out, doc)
    if doc["dead"]:
        print(
            f"Links page: {len(doc['dead'])} dead link(s). Swap or remove them on the Ops Center Links page."
        )
        for d in doc["dead"]:
            print(f"- {d['name']}: {d['reason']} ({d['url']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
