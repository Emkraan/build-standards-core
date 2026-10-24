#!/usr/bin/env python3
"""Merge a pull request so only a GitHub noreply author email lands in history, whatever the
contributors' account settings are.

Usage: python3 scripts/merge-pr.py <number> [-R OWNER/NAME] [--match-head-commit SHA] [--timeout MIN] [--dry-run]

A GitHub squash merge writes the opener's PRIMARY account email unless that account keeps its email
private, and the merge API's author hint is then ignored. So this wrapper never lets GitHub pick the
author. Where the repo allows rebase merging, it builds the squash commit itself: one commit on the
base branch tip, holding the pull request's merged tree, titled "<title> (#<n>)" with the pull
request body, authored and committed by the signed-in gh account's <id>+<login>@users.noreply.github.com.
It pushes that commit to the pull request branch (--force-with-lease on the head it read), waits for
the repo's checks on it with scripts/core-ci.py wait-checks, then merges it with --rebase, which keeps
the author. A branch already in that shape is merged without a new push. No contributor turns on any
account setting, and their other repositories are untouched (pr-review-and-merge.md 1.18).

Run it from a clone of the repo (any worktree): it fetches the two branches into refs/merge-pr/* and
uses plumbing only (git 2.38 or later), so the work tree is never touched. A pull request from a fork, a head that moved
from --match-head-commit, or a branch that conflicts with the base is refused (exit 2).

Where the repo does not allow rebase merging, it falls back to a squash merge with the noreply author
hint, and first refuses (exit 2) a pull request whose commits carry an email that is not a noreply
address. Either way it reads the merge commit back and exits 1 with the exact recovery when its author
or committer email is not a noreply address.
Exit codes: 0 merged and verified, 1 merged with a bad email or a verification problem, 2 refused.

The merge itself is remote only: gh is never asked to delete the branch, because gh's local step
(switch to the base branch, delete the local branch) fails from a worktree whose base branch is
checked out elsewhere or from a detached HEAD, and gh then exits non-zero after the merge already
landed. The remote branch is deleted through the API, and the local branch is deleted only when this
checkout has it and no worktree has it checked out; otherwise one line says why it was left. If gh
still exits non-zero, the PR state is read back, and a merged PR is never reported as refused.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

OK_SUFFIX = "@users.noreply.github.com"
OK_EXACT = {"noreply@github.com"}
REMOTE = "https://github.com/{slug}.git"


def run(cmd, env=None, stdin=None, timeout=300):
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, env=env, input=stdin
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def gh(*args):
    return run(["gh", *args])


def git(*args, env=None, stdin=None):
    return run(["git", *args], env=env, stdin=stdin)


TRANSIENT = (
    "unexpected disconnect",
    "remote end hung up",
    "rpc failed",
    "timed out",
    "early eof",
    "connection reset",
    "http 500",
    "http 502",
    "http 503",
    "http 504",
    "could not resolve host",
)


def push(*args, attempts=3, pause=10):
    """git push with a large HTTP buffer, retried on a transient network failure (a large binary such
    as a screenshot baseline can drop the connection). A rejection, such as a failed lease, is never
    retried. Returns (rc, out, err) of the last attempt."""
    import time

    for i in range(attempts):
        rc, out, err = git("-c", "http.postBuffer=524288000", "push", *args)
        if rc == 0 or not any(t in (err or "").lower() for t in TRANSIENT) or i == attempts - 1:
            return rc, out, err
        print(
            f"merge-pr: push failed ({err.splitlines()[-1] if err else 'no output'}); retrying",
            file=sys.stderr,
        )
        time.sleep(pause)
    return rc, out, err


def wait_checks(sha, slug, timeout):
    """Exit code of scripts/core-ci.py wait-checks on sha; its lines stream to this output."""
    script = Path(__file__).resolve().parent / "core-ci.py"
    if not script.exists():
        print(f"merge-pr: {script} is missing, cannot wait for the checks", file=sys.stderr)
        return 1
    try:
        return subprocess.run(
            [
                sys.executable,
                str(script),
                "wait-checks",
                sha,
                "--repo",
                slug,
                "--timeout",
                str(timeout),
            ],
            timeout=timeout * 60 + 120,
        ).returncode
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"merge-pr: wait-checks failed: {e}", file=sys.stderr)
        return 1


def squash_commit(slug, pr, login, email):
    """(sha, error): the noreply squash commit for pr, built with plumbing only. sha equals the head
    when the branch is already one noreply commit on the base tip."""
    base, head, oid = pr["baseRefName"], pr["headRefName"], pr["headRefOid"]
    url = REMOTE.format(slug=slug)
    rc, _, err = git(
        "fetch",
        "-q",
        "--no-tags",
        url,
        f"+refs/heads/{base}:refs/merge-pr/base",
        f"+refs/heads/{head}:refs/merge-pr/head",
    )
    if rc != 0:
        return "", f"cannot fetch {base} and {head} from {slug}: {err}"
    _, base_sha, _ = git("rev-parse", "refs/merge-pr/base")
    _, head_sha, _ = git("rev-parse", "refs/merge-pr/head")
    if head_sha != oid:
        return (
            "",
            f"the head moved while reading it ({oid[:8]} on GitHub, {head_sha[:8]} fetched); rerun",
        )
    rc, out, _ = git("log", "-1", "--format=%P%x09%ae%x09%ce", head_sha)
    parent, ae, ce = (out.split("\t") + ["", "", ""])[:3]
    if rc == 0 and parent == base_sha and allowed(ae) and allowed(ce):
        return head_sha, ""
    if git("merge-base", "--is-ancestor", base_sha, head_sha)[0] == 0:
        tree = git("rev-parse", f"{head_sha}^{{tree}}")[1]
    else:
        rc, out, err = git("merge-tree", "--write-tree", base_sha, head_sha)
        if rc != 0:
            return "", f"the branch conflicts with {base}; update it from {base} first"
        tree = out.splitlines()[0]
    msg = f"{pr['title']} (#{pr['number']})"
    if (pr.get("body") or "").strip():
        msg += "\n\n" + pr["body"].strip()
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_AUTHOR_NAME=login,
        GIT_AUTHOR_EMAIL=email,
        GIT_COMMITTER_NAME=login,
        GIT_COMMITTER_EMAIL=email,
    )
    rc, sha, err = git("commit-tree", tree, "-p", base_sha, "-F", "-", env=env, stdin=msg + "\n")
    if rc != 0 or not sha:
        return "", f"cannot build the squash commit: {err}"
    return sha, ""


def local_cleanup(branch):
    """Delete the local branch when it is safe from here; return one line saying what happened."""
    if not branch:
        return "local branch: unknown head branch, left alone"
    rc, _, _ = git("rev-parse", "--git-dir")
    if rc != 0:
        return "local branch: not in a git checkout, nothing to clean"
    rc, _, _ = git("show-ref", "--verify", "--quiet", f"refs/heads/{branch}")
    if rc != 0:
        return f"local branch: {branch} does not exist here"
    rc, out, _ = git("worktree", "list", "--porcelain")
    if rc == 0 and f"branch refs/heads/{branch}" in out.splitlines():
        return f"local branch: {branch} is checked out in a worktree, left in place (remove the worktree, then git branch -D {branch})"
    rc, _, err = git("branch", "-D", branch)
    return (
        f"local branch: deleted {branch}"
        if rc == 0
        else f"local branch: {branch} left in place ({err})"
    )


def allowed(email):
    e = (email or "").lower()
    return e.endswith(OK_SUFFIX) or e in OK_EXACT


def pr_commit_problems(slug, number):
    """(problems, error): one line per pull request commit whose author or committer email is not a
    noreply address, naming the commit and the account (or "no account") and the email's domain only."""
    rc, out, err = gh(
        "api",
        "--paginate",
        f"repos/{slug}/pulls/{number}/commits",
        "--jq",
        '.[] | [.sha, (.author.login // ""), .commit.author.email, (.committer.login // ""), '
        ".commit.committer.email] | @tsv",
    )
    if rc != 0:
        return [], f"cannot read the commits of #{number}: {err or out}"
    problems = []
    for line in out.splitlines():
        cells = (line.split("\t") + [""] * 5)[:5]
        sha, alogin, aemail, clogin, cemail = cells
        for who, login, email in (("author", alogin, aemail), ("committer", clogin, cemail)):
            if email and not allowed(email):
                problems.append(
                    f"commit {sha[:8]} {who} ({login or 'no account'}) uses an email on "
                    f"{email.split('@')[-1]}"
                )
    return problems, ""


def recovery(slug, sha, email):
    """The exact recovery for a merge commit that leaked an address. Every step needs the owner's
    approval: it rewrites shared history."""
    return "\n".join(
        [
            f"merge-pr: recovery (owner-approved history rewrite of {slug}, pr-review-and-merge.md 1.18):",
            '  1. Turn on "Allow rebase merging" in the repo settings, so merge-pr.py builds the squash commit',
            "     itself with the noreply author and no account setting matters again.",
            "  2. Get the owner's approval for a rewrite of main. Then, from a clone of the repo:",
            f"       git fetch origin && git switch --detach {sha}",
            f"       git -c user.email={email} commit --amend --no-edit --reset-author",
            f"       git push --force-with-lease=main:{sha} origin HEAD:main",
            "     (only while the merge commit is still the tip of main; when later commits landed on top, rewrite",
            f"     with git filter-repo --mailmap, mapping the leaked address to {email}, and push main with",
            "     --force-with-lease after the owner approves).",
            "  3. Move every release tag that points at a rewritten commit (git tag -f vX.Y.Z <new-sha> &&",
            "     git push -f origin vX.Y.Z) and tell every clone to fetch --force --tags and reset to origin/main.",
        ]
    )


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("number")
    ap.add_argument("-R", "--repo")
    ap.add_argument("--match-head-commit")
    ap.add_argument(
        "--timeout", type=int, default=60, help="minutes to wait for the checks (rebase path)"
    )
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    repo = ["-R", a.repo] if a.repo else []

    rc, out, err = gh("api", "user", "--jq", "[.id, .login] | @tsv")
    if rc != 0 or "\t" not in out:
        print(f"merge-pr: cannot read the signed-in gh account: {err}", file=sys.stderr)
        return 2
    uid, login = out.split("\t")
    email = f"{uid}+{login}{OK_SUFFIX}"

    rc, out, _ = gh(
        "pr",
        "view",
        a.number,
        *repo,
        "--json",
        "number,title,body,headRefName,headRefOid,baseRefName,isCrossRepository,author",
    )
    try:
        pr = json.loads(out) if rc == 0 else {}
    except ValueError:
        pr = {}
    branch, opener = pr.get("headRefName", ""), (pr.get("author") or {}).get("login", "")
    try:
        slug = (
            a.repo or json.loads(gh("repo", "view", "--json", "nameWithOwner")[1])["nameWithOwner"]
        )
    except (ValueError, KeyError):
        print("merge-pr: the repo is not readable, refusing to merge unchecked", file=sys.stderr)
        return 2
    if not pr.get("headRefOid"):
        print(f"merge-pr: cannot read #{a.number}, refusing to merge unchecked", file=sys.stderr)
        return 2
    if a.match_head_commit and pr["headRefOid"] != a.match_head_commit:
        print(
            f"merge-pr: refusing #{a.number}: its head is {pr['headRefOid'][:8]}, not {a.match_head_commit[:8]}",
            file=sys.stderr,
        )
        return 2
    rc, out, _ = gh("api", f"repos/{slug}", "--jq", ".allow_rebase_merge")
    rebase = rc == 0 and out == "true"

    if rebase:
        if pr.get("isCrossRepository"):
            print(
                f"merge-pr: refusing #{a.number}: a branch on a fork cannot be rewritten from here; open it "
                "from a branch of this repo",
                file=sys.stderr,
            )
            return 2
        if git("rev-parse", "--git-dir")[0] != 0:
            print(
                "merge-pr: run it from a clone of the repo (it builds the squash commit locally)",
                file=sys.stderr,
            )
            return 2
        sha, why = squash_commit(slug, pr, login, email)
        if why:
            print(f"merge-pr: refusing #{a.number}: {why}", file=sys.stderr)
            return 2
        fresh = sha != pr["headRefOid"]
        if a.dry_run:
            print(
                f"would {'push squash commit ' + sha[:8] + ' to ' + branch + ', wait for its checks, then ' if fresh else ''}"
                f"merge #{a.number} with --rebase as {email}"
            )
            return 0
        if fresh:
            rc, _, err = push(
                "-q",
                REMOTE.format(slug=slug),
                f"{sha}:refs/heads/{branch}",
                f"--force-with-lease=refs/heads/{branch}:{pr['headRefOid']}",
            )
            if rc != 0:
                print(
                    f"merge-pr: refusing #{a.number}: cannot push the squash commit: {err}",
                    file=sys.stderr,
                )
                return 2
            print(f"merge-pr: pushed squash commit {sha[:8]} to {branch}; waiting for its checks")
            if wait_checks(sha, slug, a.timeout) != 0:
                print(
                    f"merge-pr: not merged: the checks on {sha[:8]} did not pass; #{a.number} stays open with "
                    "the squash commit as its head",
                    file=sys.stderr,
                )
                return 2
        cmd = ["pr", "merge", a.number, *repo, "--rebase", "--match-head-commit", sha]
    else:
        problems, why = pr_commit_problems(slug, a.number)
        if why:
            print(f"merge-pr: {why}; refusing to merge unchecked", file=sys.stderr)
            return 2
        if problems:
            print(
                f"merge-pr: refusing #{a.number} (opened by {opener or 'unknown'}): its commits carry an email that "
                "is not a noreply address, and a squash merge would write it into history:\n  "
                + "\n  ".join(problems)
                + "\n"
                'Fix: turn on "Allow rebase merging" in the repo settings, so merge-pr.py builds the squash commit '
                "itself with the noreply author (pr-review-and-merge.md 1.18).",
                file=sys.stderr,
            )
            return 2
        cmd = ["pr", "merge", a.number, *repo, "--squash", "--author-email", email]
        if a.match_head_commit:
            cmd += ["--match-head-commit", a.match_head_commit]
        if a.dry_run:
            print("would run: gh " + " ".join(cmd))
            return 0
    rc, out, err = gh(*cmd)
    if rc != 0:
        src, state, _ = gh("pr", "view", a.number, *repo, "--json", "state", "--jq", ".state")
        if src != 0 or state != "MERGED":
            print(f"merge-pr: merge refused: {err or out}", file=sys.stderr)
            return 2
        print(
            f"merge-pr: gh exited {rc} but the PR is merged; continuing ({err or out})",
            file=sys.stderr,
        )

    rc, out, err = gh(
        "pr", "view", a.number, *repo, "--json", "mergeCommit", "--jq", ".mergeCommit.oid"
    )
    sha = out
    if rc != 0 or not sha:
        print(
            "merge-pr: merged, but the merge commit is not readable yet; verify its author email by hand",
            file=sys.stderr,
        )
        return 1
    if branch and not pr.get("isCrossRepository"):
        drc, _, derr = gh("api", "-X", "DELETE", f"repos/{slug}/git/refs/heads/{branch}")
        print(
            f"merge-pr: remote branch {branch} "
            + ("deleted" if drc == 0 else f"not deleted ({derr})")
        )
    print("merge-pr: " + local_cleanup(branch))
    rc, out, err = gh(
        "api",
        f"repos/{slug}/commits/{sha}",
        "--jq",
        "[.commit.author.email, .commit.committer.email] | @tsv",
    )
    emails = out.split("\t") if rc == 0 else []
    bad = [e for e in emails if not allowed(e)]
    if not emails or bad:
        print(
            f"merge-pr: MERGED {sha[:8]} but its email is not a noreply address ({', '.join(bad) or 'unreadable'}). "
            "Tell the repo owner now: history is shared.",
            file=sys.stderr,
        )
        print(recovery(slug, sha, email), file=sys.stderr)
        return 1
    print(f"merge-pr: merged {sha[:8]} with {email}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
