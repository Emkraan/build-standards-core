"""
merge_queue.py
Purpose: Put a pull request into main's merge queue and prove it got there.
         A stale auto-merge request (for example SQUASH, left from before the queue existed) makes
         `gh pr merge --auto` a silent no-op, so the PR sits clean and never enqueues. enqueue()
         reads the PR, cancels a stale request, enqueues, then re-reads until the PR is in the
         queue, merged, or (repo with no merge queue only) has an auto-merge request. Anything
         else raises MergeQueueError. Admin merges do not use this helper.
         main requires every conversation resolved, so a PR with the owner's own open review
         threads (nits) never enqueues. With accept_own_threads=<login> the owner's approval accepts
         them: enqueue() resolves unresolved threads that login started and refuses, naming them, on any
         thread someone else started. When auto-merge arms but GitHub does not enqueue, it calls
         enqueuePullRequest directly so the error names GitHub's real reason.
"""

from __future__ import annotations

import json
import time

READ_TRIES = 6
READ_DELAY_S = 3.0

_PR_FIELDS = "state headRefOid baseRefName isInMergeQueue autoMergeRequest { mergeMethod } mergeQueueEntry { position state }"
_PR_QUERY = (
    "query($owner:String!,$name:String!,$n:Int!){repository(owner:$owner,name:$name)"
    "{pullRequest(number:$n){" + _PR_FIELDS + "}}}"
)
_THREADS_QUERY = (
    "query($owner:String!,$name:String!,$n:Int!){repository(owner:$owner,name:$name){pullRequest(number:$n)"
    "{id reviewThreads(first:100){nodes{id isResolved path line comments(first:1){nodes{author{login}}}}}}}}"
)
_RESOLVE_MUTATION = "mutation($t:ID!){resolveReviewThread(input:{threadId:$t}){thread{isResolved}}}"
_ENQUEUE_MUTATION = (
    "mutation($id:ID!,$h:GitObjectID!){enqueuePullRequest(input:{pullRequestId:$id,expectedHeadOid:$h})"
    "{mergeQueueEntry{position state}}}"
)
_QUEUE_QUERY = "query($owner:String!,$name:String!,$b:String!){repository(owner:$owner,name:$name){mergeQueue(branch:$b){id}}}"


class MergeQueueError(Exception):
    pass


def _graphql(gh, query, repo, **vars_):
    owner, name = repo.split("/", 1)
    args = ["api", "graphql", "-f", f"query={query}", "-f", f"owner={owner}", "-f", f"name={name}"]
    for k, v in vars_.items():
        args += ["-F" if isinstance(v, int) else "-f", f"{k}={v}"]
    try:
        out = gh(args, raw=True)
        data = json.loads(out) if isinstance(out, str) else out
        return data["data"]["repository"]
    except Exception as e:  # noqa: BLE001 - any read failure fails closed
        raise MergeQueueError(f"could not read the PR from GitHub: {str(e)[:200]}") from e


def read(gh, repo, pr):
    node = _graphql(gh, _PR_QUERY, repo, n=int(pr)).get("pullRequest")
    if not node:
        raise MergeQueueError(f"PR #{pr} was not found in {repo}")
    return node


def _has_queue(gh, repo, branch):
    node = _graphql(gh, _QUEUE_QUERY, repo, b=branch)
    return bool(node.get("mergeQueue"))


def _gh_json(gh, args):
    out = gh(args, raw=True)
    return json.loads(out) if isinstance(out, str) else out


def resolve_own_threads(gh, repo, pr, login):
    """Resolve unresolved review threads on PR `pr` that `login` started. Returns the count
    resolved. Raises MergeQueueError naming any unresolved thread someone else started."""
    owner, name = repo.split("/", 1)
    try:
        data = _gh_json(
            gh,
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
        )
        nodes = data["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
    except Exception as e:  # noqa: BLE001 - fail closed
        raise MergeQueueError(
            f"PR #{pr} did not enter the merge queue: could not read review threads: {str(e)[:200]}"
        ) from e
    mine, others = [], []
    for t in nodes or []:
        if t.get("isResolved"):
            continue
        first = ((t.get("comments") or {}).get("nodes") or [{}])[0]
        who = ((first or {}).get("author") or {}).get("login") or "unknown"
        (mine if who.lower() == str(login).lower() else others).append((t, who))
    if others:
        where = ", ".join(f"{w} on {t.get('path')}:{t.get('line')}" for t, w in others[:5])
        raise MergeQueueError(
            f"PR #{pr} did not enter the merge queue: {len(others)} open review conversation(s) need an answer first ({where})"
        )
    for t, _ in mine:
        try:
            gh(
                ["api", "graphql", "-f", f"query={_RESOLVE_MUTATION}", "-f", f"t={t['id']}"],
                raw=True,
            )
        except Exception as e:  # noqa: BLE001
            raise MergeQueueError(
                f"PR #{pr} did not enter the merge queue: could not resolve the owner's thread on {t.get('path')}: {str(e)[:200]}"
            ) from e
    return len(mine)


def _direct_enqueue(gh, repo, pr, head):
    """Ask GitHub to enqueue directly. Returns None on success, else GitHub's error text."""
    owner, name = repo.split("/", 1)
    try:
        q = "query($owner:String!,$name:String!,$n:Int!){repository(owner:$owner,name:$name){pullRequest(number:$n){id}}}"
        data = _gh_json(
            gh,
            [
                "api",
                "graphql",
                "-f",
                f"query={q}",
                "-f",
                f"owner={owner}",
                "-f",
                f"name={name}",
                "-F",
                f"n={int(pr)}",
            ],
        )
        pid = data["data"]["repository"]["pullRequest"]["id"]
        out = _gh_json(
            gh,
            [
                "api",
                "graphql",
                "-f",
                f"query={_ENQUEUE_MUTATION}",
                "-f",
                f"id={pid}",
                "-f",
                f"h={head}",
            ],
        )
    except Exception as e:  # noqa: BLE001 - gh exits non-zero with GitHub's message
        return str(e)[:300]
    errs = (out or {}).get("errors") or []
    if errs:
        return " | ".join(str(x.get("message")) for x in errs)[:300]
    if not ((out or {}).get("data") or {}).get("enqueuePullRequest"):
        return "GitHub returned no queue entry"
    return None


def _done(kind, node):
    entry = node.get("mergeQueueEntry") or {}
    pos = entry.get("position")
    if kind == "merged":
        text = "already merged"
    elif kind == "queued":
        text = f"in merge queue (position {pos})" if pos else "in merge queue"
    else:
        text = "auto-merge armed (this repo has no merge queue)"
    return {"ok": True, "status": kind, "position": pos, "text": text}


def _classify(node, head):
    if node.get("state") == "MERGED":
        return "merged"
    if node.get("state") != "OPEN":
        return None
    if node.get("headRefOid") == head and node.get("isInMergeQueue"):
        return "queued"
    return None


def _with_resolved(res, n):
    if n:
        res = dict(
            res,
            resolved_threads=n,
            text=f"{res['text']}, resolved {n} of review thread(s) of the owner",
        )
    return res


def enqueue(repo, pr, head, gh, sleep=None, tries=None, delay=None, accept_own_threads=None):
    """Put PR `pr` of `repo` into the merge queue at `head`. gh is the caller's gh runner
    (args, raw=True) and may raise any exception. Returns {ok, status, position, text}.
    accept_own_threads=<login>: the caller is that login's approval, so threads it started are
    resolved first and anyone else's open thread refuses the enqueue.
    Raises MergeQueueError with 'PR #N did not enter the merge queue: <reason>'."""
    sleep = sleep or time.sleep
    tries = tries or READ_TRIES
    delay = READ_DELAY_S if delay is None else delay
    node = read(gh, repo, pr)
    kind = _classify(node, head)
    if kind:
        return _done(kind, node)
    if node.get("state") != "OPEN":
        raise MergeQueueError(f"PR #{pr} did not enter the merge queue: it is {node.get('state')}")
    if node.get("headRefOid") != head:
        raise MergeQueueError(
            f"PR #{pr} did not enter the merge queue: head moved to {str(node.get('headRefOid'))[:8]}, expected {head[:8]}"
        )
    resolved = resolve_own_threads(gh, repo, pr, accept_own_threads) if accept_own_threads else 0
    base = ["pr", "merge", str(pr), "-R", repo]
    try:
        if node.get("autoMergeRequest"):
            gh(base + ["--disable-auto"], raw=True)
    except Exception as e:  # noqa: BLE001
        raise MergeQueueError(
            f"PR #{pr} did not enter the merge queue: could not cancel the old auto-merge request: {str(e)[:200]}"
        ) from e
    try:
        gh(base + ["--auto", "--match-head-commit", head], raw=True)
    except Exception:  # noqa: BLE001 - a repo with no queue needs a method flag
        try:
            gh(base + ["--rebase", "--auto", "--match-head-commit", head], raw=True)
        except Exception as e:  # noqa: BLE001
            raise MergeQueueError(
                f"PR #{pr} did not enter the merge queue: gh refused the enqueue: {str(e)[:200]}"
            ) from e
    last = node
    for i in range(tries):
        if i:
            sleep(delay)
        last = read(gh, repo, pr)
        kind = _classify(last, head)
        if kind:
            return _with_resolved(_done(kind, last), resolved)
        if last.get("state") != "OPEN" or last.get("headRefOid") != head:
            break
    if (
        last.get("state") == "OPEN"
        and last.get("headRefOid") == head
        and last.get("autoMergeRequest")
    ):
        if not _has_queue(gh, repo, last.get("baseRefName") or "main"):
            return _with_resolved(_done("auto", last), resolved)
        # gh armed a request GitHub will not act on. Enqueue directly to get the real reason.
        why = _direct_enqueue(gh, repo, pr, head)
        if why is None:
            last = read(gh, repo, pr)
            if _classify(last, head):
                return _with_resolved(_done(_classify(last, head), last), resolved)
            why = "the direct enqueue returned but the PR is not in the queue"
        raise MergeQueueError(
            f"PR #{pr} did not enter the merge queue: auto-merge is armed but GitHub has not enqueued it "
            f"({last.get('autoMergeRequest', {}).get('mergeMethod')}). GitHub says: {why}"
        )
    if last.get("state") != "OPEN":
        raise MergeQueueError(f"PR #{pr} did not enter the merge queue: it is {last.get('state')}")
    if last.get("headRefOid") != head:
        raise MergeQueueError(
            f"PR #{pr} did not enter the merge queue: head moved during the enqueue"
        )
    raise MergeQueueError(
        f"PR #{pr} did not enter the merge queue: no auto-merge request and not queued after the enqueue"
    )
