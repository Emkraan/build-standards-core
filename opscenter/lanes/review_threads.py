"""
review_threads.py
Purpose: Open review conversations on engineer <platform> PRs. main requires every
         conversation resolved before a merge. When the owner approve an engineer PR while a thread
         someone else started is still open, the owner's approval is not posted. The card waits on those
         conversations, one PR comment tags each thread author once, and the person who raised a
         concern resolves it (or the owner resolve it from the card). Once none are open the owner's held approval
         posts and the merge queues. Threads the owner started are resolved by merge_queue.enqueue.
         gh is the caller's runner gh(args, timeout=60, raw=False) and may raise any exception.
Date:    2026-10-22
"""

from __future__ import annotations

import json
import re

MARKER = "open-threads"
_MARKER_RE = re.compile(r"<!-- " + MARKER + r":[0-9a-f]{7,40}((?: [A-Za-z0-9_=-]+)*) -->")

_THREADS_QUERY = (
    "query($owner:String!,$name:String!,$n:Int!){repository(owner:$owner,name:$name){pullRequest(number:$n)"
    "{reviewThreads(first:100){nodes{id isResolved isOutdated path line originalLine "
    "comments(first:50){nodes{author{login __typename} body url}}}}}}}"
)
_RESOLVE = "mutation($t:ID!){resolveReviewThread(input:{threadId:$t}){thread{id isResolved}}}"


class ThreadError(Exception):
    pass


def _json(out):
    return json.loads(out) if isinstance(out, str) else out


def _one_line(text, n=160):
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: n - 3] + "..."


def read(gh, repo, pr):
    """Unresolved review threads on PR `pr`, oldest first. Raises ThreadError on any read failure."""
    owner, name = repo.split("/", 1)
    try:
        data = _json(
            gh(
                [
                    "api",
                    "graphql",
                    "-f",
                    f"query={_THREADS_QUERY}",
                    "-f",
                    f"owner={owner}",
                    "-f",
                    f"name={name}",
                    "-F",
                    f"n={int(pr)}",
                ],
                raw=True,
            )
        )
        nodes = data["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
    except Exception as e:  # noqa: BLE001 - fail closed, the caller posts nothing
        raise ThreadError(
            f"could not read the review conversations on #{pr}: {str(e)[:200]}"
        ) from e
    out = []
    for t in nodes or []:
        if t.get("isResolved"):
            continue
        comments = ((t.get("comments") or {}).get("nodes")) or [{}]
        first, last = comments[0] or {}, comments[-1] or {}
        author = first.get("author") or {}
        out.append(
            {
                "id": t.get("id"),
                "starter": author.get("login") or "unknown",
                "automated": author.get("__typename") == "Bot"
                or str(author.get("login") or "").endswith("[bot]"),
                "path": t.get("path"),
                "line": t.get("line") or t.get("originalLine"),
                "outdated": bool(t.get("isOutdated")),
                "url": first.get("url"),
                "last_author": (last.get("author") or {}).get("login") or "unknown",
                "last_text": _one_line(last.get("body")),
                "replies": len(comments),
            }
        )
    return out


def others(threads, self_login):
    """Threads someone other than me started. Mine are resolved by the enqueue."""
    me = str(self_login or "").lower()
    return [t for t in threads if str(t.get("starter") or "").lower() != me]


def announced(gh, repo, pr, self_login):
    """Thread ids the owner's earlier open-threads comments on this PR already named."""
    try:
        comments = (
            _json(gh(["api", f"repos/{repo}/issues/{int(pr)}/comments?per_page=100"], raw=True))
            or []
        )
    except Exception as e:  # noqa: BLE001
        raise ThreadError(f"could not read the PR comments on #{pr}: {str(e)[:200]}") from e
    me = str(self_login or "").lower()
    ids = set()
    for c in comments:
        if str(((c.get("user") or {}).get("login")) or "").lower() != me:
            continue
        for m in _MARKER_RE.finditer(c.get("body") or ""):
            ids.update(m.group(1).split())
    return ids


def _where(t):
    where = f"`{t.get('path')}`" if t.get("path") else "the PR"
    if t.get("line"):
        where += f" line {t['line']}"
    return where


def comment_body(threads, head, new_ids):
    """One comment in the owner's voice listing every open conversation. Authors of threads not named before
    are @-tagged (that is the notification). Automated threads are listed, never tagged."""
    lines = [
        "This is ready on the owner's side. It merges as soon as the open conversations below are resolved.",
        "",
    ]
    tagged = []
    for t in threads:
        link = f" ([conversation]({t['url']}))" if t.get("url") else ""
        if t.get("automated"):
            who = "Automated review"
        elif t["id"] in new_ids:
            who = f"@{t['starter']}"
            if t["starter"] not in tagged:
                tagged.append(t["starter"])
        else:
            who = t["starter"]
        lines.append(f"- {who} on {_where(t)}{link}")
    if tagged:
        lines += [
            "",
            f"{', '.join('@' + x for x in tagged)}, resolve your conversation once it is handled, "
            "or reply in it if it still needs a change.",
        ]
    lines += ["", f"<!-- {MARKER}:{head} {' '.join(t['id'] for t in threads)} -->"]
    return "\n".join(lines), tagged


def notify(gh, repo, pr, head, threads, self_login):
    """Post one comment when an open conversation has not been named in an earlier comment.
    Returns the logins tagged ([] when everything was already named, nothing posted)."""
    if not threads:
        return []
    seen = announced(gh, repo, pr, self_login)
    new_ids = {t["id"] for t in threads if t["id"] not in seen}
    if not new_ids:
        return []
    body, tagged = comment_body(threads, head, new_ids)
    try:
        gh(["pr", "comment", str(int(pr)), "-R", repo, "--body", body], raw=True)
    except Exception as e:  # noqa: BLE001
        raise ThreadError(
            f"could not post the conversation summary on #{pr}: {str(e)[:200]}"
        ) from e
    return tagged or ["(automated review only)"]


def resolve(gh, repo, pr, thread_id):
    """Resolve one open thread as me, only when it is an open thread on this PR."""
    if not re.fullmatch(r"[A-Za-z0-9_=-]{6,80}", str(thread_id or "")):
        raise ThreadError("thread_id required")
    open_ = {t["id"]: t for t in read(gh, repo, pr)}
    t = open_.get(thread_id)
    if not t:
        raise ThreadError(f"that conversation is not open on #{pr} any more")
    try:
        gh(["api", "graphql", "-f", f"query={_RESOLVE}", "-f", f"t={thread_id}"], raw=True)
    except Exception as e:  # noqa: BLE001
        raise ThreadError(
            f"could not resolve the conversation on {_where(t)}: {str(e)[:200]}"
        ) from e
    return t
