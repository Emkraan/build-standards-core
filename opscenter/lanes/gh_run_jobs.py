#!/usr/bin/env python3
"""Read every job of a GitHub Actions run, in pages of 50.

Purpose: GitHub answers the run jobs list with HTTP 502 for large runs when asked for 100 jobs per
         page (a run of 65 jobs: per_page=100 worked 1 of 5 times,
         per_page=50 worked 5 of 5). That 502 held an own-PR lane on a clean head. Every lane reads
         run jobs through run_jobs() so the page size and the retry live in one place.
Usage:   from gh_run_jobs import run_jobs
         jobs = run_jobs(gh, "owner/repo", run_id)   # gh = the caller's own gh(args) helper
"""

import time

PER_PAGE = 50
MAX_PAGES = 10  # 500 jobs, far above any run we have
RETRY_WAIT_S = 2


def _server_error(e):
    return "HTTP 5" in str(e)


def _page(gh, path):
    """One page. A GitHub 5xx is retried once, every other error is raised as is."""
    try:
        return gh(["api", path])
    except Exception as e:  # noqa: BLE001 - each caller has its own GhError class
        if not _server_error(e):
            raise
        time.sleep(RETRY_WAIT_S)
        return gh(["api", path])


def run_jobs(gh, repo, run_id, per_page=PER_PAGE, max_pages=MAX_PAGES):
    """Every job of the run (latest attempt), following pages. Raises the caller's gh error when
    a page still fails after the retry, so a failed read is never mistaken for a run with no jobs."""
    jobs = []
    for page in range(1, max_pages + 1):
        d = _page(gh, f"repos/{repo}/actions/runs/{run_id}/jobs?per_page={per_page}&page={page}")
        batch = d if isinstance(d, list) else (d or {}).get("jobs") or []
        jobs += batch
        if len(batch) < per_page:
            break
    return jobs
