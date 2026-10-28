#!/usr/bin/env python3
"""
pr_review_trust_checks.py
Purpose: Tests for trust_hits() / new_file_hits() in pr_review.py (new app, new function
         app and new runbook first-PR rules). gh is replaced by a fake that answers from a
         synthetic main tree. Never touches GitHub.
Date:    2026-10-16
Run:     /usr/bin/python3 pr_review_trust_checks.py
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "testing"))
import policy_env  # noqa: E402

STATE_ROOT = (
    policy_env.install()
)  # a scratch state tree holding the policy fixtures, so no live state is read

HERE = Path(__file__).resolve().parent
SCRATCH = tempfile.mkdtemp(prefix="oprt-", dir=os.environ.get("TMPDIR"))
os.environ["OPRG_STATE_DIR"] = SCRATCH
os.environ["OPRG_CACHE_DIR"] = SCRATCH
os.environ["OPRG_GH_BIN"] = "/usr/bin/false"
os.environ["OPRG_DRY_RUN"] = "1"

spec = importlib.util.spec_from_file_location("oprg", str(HERE / "pr_review.py"))
eng = importlib.util.module_from_spec(spec)
sys.modules["oprg"] = eng
spec.loader.exec_module(eng)

# Synthetic main: folders and the files directly inside them.
MAIN = {
    "apps": {"dirs": ["ucportal", "app-a"]},
    "services": {"dirs": []},
    "agents": {"dirs": []},
    "functions": {"dirs": ["intake-hooks"]},
    "runbooks/prod-prefix-automation-aa": {
        "files": ["team-prefix-cmdb-status-lookup.ps1", "manifest.json", "README.md"],
        "dirs": ["tests"],
    },
}

POL = {
    "self_login": "owner-account",
    "trust_rules": {
        "new_app_roots": ["apps", "services", "agents", "functions"],
        "new_file_roots": ["runbooks"],
        "new_file_extensions": [".ps1", ".py"],
        "first_prs_to_review": 0,
        "approval_paths": [],
    },
}


class FakeGh:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail or {}

    def __call__(self, args, timeout=60, raw=False):
        self.calls.append(args)
        url = args[1]
        path = url.split("/contents/", 1)[1].split("?", 1)[0]
        if path in self.fail:
            raise eng.GhError(self.fail[path])
        node = MAIN.get(path)
        if node is None:
            raise eng.GhError("api repos: rc=1 gh: Not Found (HTTP 404)")
        want = "dir" if '"dir"' in args[3] else "file"
        return "\n".join(node.get(want + "s", [])) + "\n"


def run(files, author="engineer1", fail=None, renamed=None):
    fake = FakeGh(fail)
    orig = eng.gh
    eng.gh = fake
    try:
        return eng.trust_hits(POL, "owner/primary-repo", author, files, renamed), fake
    finally:
        eng.gh = orig


def rules(hits):
    return sorted((h["rule"], h["where"]) for h in hits)


class TrustTests(unittest.TestCase):
    def test_new_function_app_folder(self):
        hits, _ = run(
            ["functions/payroll-hooks/deploy.json", "functions/payroll-hooks/src/index.ts"]
        )
        self.assertEqual(rules(hits), [("new-app-first-pr", "functions/payroll-hooks/")])

    def test_existing_function_app_is_clean(self):
        hits, _ = run(["functions/intake-hooks/src/index.ts"])
        self.assertEqual(hits, [])

    def test_functions_readme_is_not_an_app(self):
        hits, _ = run(["functions/README.md"])
        self.assertEqual(hits, [])

    def test_new_runbook_in_existing_account(self):
        hits, _ = run(
            [
                "runbooks/prod-prefix-automation-aa/team-prefix-new-thing.ps1",
                "runbooks/prod-prefix-automation-aa/manifest.json",
            ]
        )
        self.assertEqual(
            rules(hits),
            [
                (
                    "new-runbook-first-pr",
                    "runbooks/prod-prefix-automation-aa/team-prefix-new-thing.ps1",
                )
            ],
        )

    def test_python_runbook_counts(self):
        hits, _ = run(["runbooks/prod-prefix-automation-aa/team-prefix-sync.py"])
        self.assertEqual(
            rules(hits),
            [("new-runbook-first-pr", "runbooks/prod-prefix-automation-aa/team-prefix-sync.py")],
        )

    def test_edit_existing_runbook_is_clean(self):
        hits, _ = run(
            [
                "runbooks/prod-prefix-automation-aa/team-prefix-cmdb-status-lookup.ps1",
                "runbooks/prod-prefix-automation-aa/manifest.json",
            ]
        )
        self.assertEqual(hits, [])

    def test_new_test_file_is_not_a_runbook(self):
        hits, _ = run(["runbooks/prod-prefix-automation-aa/tests/team-prefix-new-thing.Tests.ps1"])
        self.assertEqual(hits, [])

    def test_new_account_folder_makes_every_runbook_new(self):
        hits, _ = run(
            [
                "runbooks/dev-prefix-automation-aa/manifest.json",
                "runbooks/dev-prefix-automation-aa/a.ps1",
                "runbooks/dev-prefix-automation-aa/b.ps1",
            ]
        )
        self.assertEqual(
            rules(hits),
            [
                ("new-runbook-first-pr", "runbooks/dev-prefix-automation-aa/a.ps1"),
                ("new-runbook-first-pr", "runbooks/dev-prefix-automation-aa/b.ps1"),
            ],
        )

    def test_rename_without_renamed_status_counts(self):
        # No 'renamed' status from the files API (e.g. a delete plus an add): the new path is new.
        hits, _ = run(
            [
                "runbooks/prod-prefix-automation-aa/team-prefix-cmdb-status-lookup.ps1",
                "runbooks/prod-prefix-automation-aa/team-prefix-cmdb-status-lookup-v2.ps1",
            ]
        )
        self.assertEqual(
            rules(hits),
            [
                (
                    "new-runbook-first-pr",
                    "runbooks/prod-prefix-automation-aa/team-prefix-cmdb-status-lookup-v2.ps1",
                )
            ],
        )

    def test_renamed_runbook_is_not_new(self):
        old = "runbooks/prod-prefix-automation-aa/team-prefix-cmdb-status-lookup.ps1"
        new = "runbooks/prod-prefix-automation-aa/team-prefix-cmdb-status-check.ps1"
        hits, fake = run([new, old], renamed={new: old})
        self.assertEqual(hits, [])
        # Only the previous name's folder (on main) is listed, as before.
        self.assertEqual(len(fake.calls), 1)

    def test_renamed_into_new_account_folder_is_not_new(self):
        old = "runbooks/prod-prefix-automation-aa/team-prefix-cmdb-status-lookup.ps1"
        new = "runbooks/dev-prefix-automation-aa/team-prefix-cmdb-status-lookup.ps1"
        hits, fake = run([new, old], renamed={new: old})
        self.assertEqual(hits, [])
        # The new account folder is never listed, only the previous name's folder on main.
        self.assertEqual(len(fake.calls), 1)
        self.assertNotIn("dev-prefix-automation-aa", " ".join(fake.calls[0]))

    def test_rename_from_tests_folder_counts(self):
        old = "runbooks/prod-prefix-automation-aa/tests/team-prefix-thing.Tests.ps1"
        new = "runbooks/prod-prefix-automation-aa/team-prefix-thing.ps1"
        hits, _ = run([new, old], renamed={new: old})
        self.assertEqual(rules(hits), [("new-runbook-first-pr", new)])

    def test_rename_from_outside_runbooks_counts(self):
        old = "scripts/team-prefix-thing.ps1"
        new = "runbooks/prod-prefix-automation-aa/team-prefix-thing.ps1"
        hits, _ = run([new, old], renamed={new: old})
        self.assertEqual(rules(hits), [("new-runbook-first-pr", new)])

    def test_added_runbook_next_to_a_rename_still_counts(self):
        old = "runbooks/prod-prefix-automation-aa/team-prefix-cmdb-status-lookup.ps1"
        new = "runbooks/prod-prefix-automation-aa/team-prefix-cmdb-status-check.ps1"
        added = "runbooks/prod-prefix-automation-aa/team-prefix-brand-new.ps1"
        hits, fake = run([new, old, added], renamed={new: old})
        self.assertEqual(rules(hits), [("new-runbook-first-pr", added)])
        self.assertEqual(len(fake.calls), 1)

    def test_rename_does_not_hide_a_listing_error(self):
        old = "runbooks/prod-prefix-automation-aa/team-prefix-cmdb-status-lookup.ps1"
        new = "runbooks/prod-prefix-automation-aa/team-prefix-cmdb-status-check.ps1"
        added = "runbooks/prod-prefix-automation-aa/team-prefix-brand-new.ps1"
        hits, _ = run(
            [new, old, added],
            renamed={new: old},
            fail={"runbooks/prod-prefix-automation-aa": "api repos: rc=1 HTTP 502 Bad Gateway"},
        )
        self.assertEqual(
            rules(hits), [("trust-check-failed", "runbooks/prod-prefix-automation-aa/")]
        )

    def test_parse_pr_files_maps_only_renamed_status(self):
        out = "\n".join(
            [
                '{"filename": "runbooks/a/new.ps1", "status": "renamed", "previous_filename": "runbooks/a/old.ps1"}',
                '{"filename": "runbooks/a/copy.ps1", "status": "copied", "previous_filename": "runbooks/a/src.ps1"}',
                '{"filename": "runbooks/a/added.ps1", "status": "added"}',
            ]
        )
        files, renamed = eng.parse_pr_files(out + "\n")
        self.assertEqual(renamed, {"runbooks/a/new.ps1": "runbooks/a/old.ps1"})
        self.assertIn("runbooks/a/old.ps1", files)
        self.assertIn("runbooks/a/src.ps1", files)

    def test_parse_pr_files_garbled_read_raises(self):
        with self.assertRaises(ValueError):
            eng.parse_pr_files('{"filename": "runbooks/a/x.ps1"\n')

    def test_copied_runbook_still_counts(self):
        # A copy is a second runbook. Only status 'renamed' is exempt, so check() passes no mapping.
        files, renamed = eng.parse_pr_files(
            '{"filename": "runbooks/prod-prefix-automation-aa/team-prefix-copy.ps1", "status": "copied",'
            ' "previous_filename": "runbooks/prod-prefix-automation-aa/team-prefix-cmdb-status-lookup.ps1"}\n'
        )
        hits, _ = run(files, renamed=renamed)
        self.assertEqual(
            rules(hits),
            [("new-runbook-first-pr", "runbooks/prod-prefix-automation-aa/team-prefix-copy.ps1")],
        )

    def test_runbook_listing_error_fails_closed(self):
        hits, _ = run(
            ["runbooks/prod-prefix-automation-aa/team-prefix-new-thing.ps1"],
            fail={"runbooks/prod-prefix-automation-aa": "api repos: rc=1 HTTP 502 Bad Gateway"},
        )
        self.assertEqual(
            rules(hits), [("trust-check-failed", "runbooks/prod-prefix-automation-aa/")]
        )

    def test_function_listing_error_fails_closed(self):
        hits, _ = run(["functions/x/deploy.json"], fail={"functions": "api repos: rc=1 timeout"})
        self.assertEqual(rules(hits), [("trust-check-failed", "functions")])

    def test_one_listing_per_account_folder(self):
        _, fake = run(
            [
                "runbooks/prod-prefix-automation-aa/a.ps1",
                "runbooks/prod-prefix-automation-aa/b.ps1",
                "runbooks/prod-prefix-automation-aa/c.ps1",
            ]
        )
        self.assertEqual(len(fake.calls), 1)

    def test_no_runbook_files_no_calls(self):
        _, fake = run(
            ["runbooks/README.md", "runbooks/naming.json", "infrastructure/terraform/x/main.tf"]
        )
        self.assertEqual(fake.calls, [])

    def test_my_own_pr_skips(self):
        hits, fake = run(
            ["runbooks/prod-prefix-automation-aa/new.ps1", "functions/new/deploy.json"],
            author="owner-account",
        )
        self.assertEqual(hits, [])
        self.assertEqual(fake.calls, [])

    def test_new_app_still_works(self):
        hits, _ = run(["apps/newtool/deploy.json"])
        self.assertEqual(rules(hits), [("new-app-first-pr", "apps/newtool/")])

    def test_live_policy_has_the_rules(self):
        live = eng.load_json(STATE_ROOT / "review" / "policy.json", {})
        tr = live.get("trust_rules") or {}
        self.assertIn("functions", tr.get("new_app_roots") or [])
        self.assertEqual(tr.get("new_file_roots"), ["runbooks"])


class TrustHoldKinds(unittest.TestCase):
    """pr-review-and-merge.4: each trust hold fires with its rule id even when every gate passes, an author at
    N merged PRs is not held as new, and a failed lookup holds with the lookup reason."""

    N = 3
    POL4 = {
        "self_login": "owner-account",
        "trust_rules": {
            "new_app_roots": ["apps"],
            "new_file_roots": [],
            "first_prs_to_review": 3,
            "approval_paths": ["apps/app-e/"],
        },
    }

    def run4(self, files, merged="9", author="engineer1", list_error=None, count_error=None):
        calls = []

        def fake(args, timeout=60, raw=False):
            calls.append(args)
            if (
                args[1] == "-X"
            ):  # the merged-PR count: gh api -X GET search/issues ... --jq .total_count
                if count_error:
                    raise eng.GhError(count_error)
                return merged + "\n"
            if list_error:
                raise eng.GhError(list_error)
            return "ucportal\napp-a\napp-e\n"  # the app folders already on main

        orig = eng.gh
        eng.gh = fake
        try:
            return eng.trust_hits(self.POL4, "owner/primary-repo", author, files), calls
        finally:
            eng.gh = orig

    def test_first_pr_of_a_new_app_is_held_with_its_rule(self):
        # core-rule: pr-review-and-merge.4
        hits, _ = self.run4(["apps/newtool/deploy.json"])
        self.assertEqual(rules(hits), [("new-app-first-pr", "apps/newtool/")])

    def test_author_with_fewer_than_n_merged_prs_is_held_as_new(self):
        # core-rule: pr-review-and-merge.4
        hits, _ = self.run4(["apps/app-a/src/a.ts"], merged=str(self.N - 1))
        self.assertEqual(rules(hits), [("new-contributor", "engineer1")])
        self.assertIn("has 2 merged PR(s), the first 3 go to owner", hits[0]["reason"])

    def test_author_at_n_merged_prs_is_not_held_as_new(self):
        # core-rule: pr-review-and-merge.4
        hits, calls = self.run4(["apps/app-a/src/a.ts"], merged=str(self.N))
        self.assertEqual(hits, [])
        self.assertTrue(any(c[1] == "-X" for c in calls), "the merged count was read")

    def test_device_shipped_path_is_held_even_for_a_trusted_author(self):
        # core-rule: pr-review-and-merge.4
        hits, _ = self.run4(["apps/app-e/agent/main.go"], merged="50")
        self.assertEqual(rules(hits), [("approval-path", "apps/app-e/agent/main.go")])

    def test_failed_merged_count_lookup_holds_with_the_lookup_reason(self):
        # core-rule: pr-review-and-merge.4
        hits, _ = self.run4(
            ["apps/app-a/src/a.ts"], count_error="api search: rc=1 HTTP 502 Bad Gateway"
        )
        self.assertEqual(rules(hits), [("trust-check-failed", "engineer1")])
        self.assertEqual(hits[0]["reason"], "could not count merged PRs for engineer1")

    def test_failed_app_listing_lookup_holds_with_the_lookup_reason(self):
        # core-rule: pr-review-and-merge.4
        hits, _ = self.run4(
            ["apps/newtool/deploy.json"],
            merged="50",
            list_error="api repos: rc=1 HTTP 502 Bad Gateway",
        )
        self.assertEqual(rules(hits), [("trust-check-failed", "apps")])
        self.assertEqual(hits[0]["reason"], "could not list apps/ on main to spot a new app")


if __name__ == "__main__":
    unittest.main(verbosity=1)
