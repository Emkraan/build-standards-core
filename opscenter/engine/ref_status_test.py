#!/usr/bin/env python3
"""Tests for ref_status.py: repo prefixes, approve-the-apply check and the
auto- card close rule. Fake gh and Jira binaries, synthetic records only (the numbers
mirror primary #437 and the 10/21 auto- cards)."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest

os.environ["REF_STATUS_NO_CACHE"] = "1"
PRI, SEC = "acme/primary", "acme/secondary"
os.environ["REF_STATUS_REPOS"] = json.dumps(
    {
        "default": PRI,
        "primary": PRI,
        "secondary": SEC,
        "secondary-1": SEC,
        "alt-one": SEC,
        "alt-two": SEC,
        "endpoint": PRI,
    }
)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ref_status as R  # noqa: E402

FAKE_GH = r"""#!/usr/bin/env python3
import json, os, re, sys
cfg = json.load(open(os.environ["FAKE_GH_CFG"]))
a = sys.argv[1:]
if a[:2] == ["api", "graphql"]:
    q = a[-1]
    repo = re.search(r'name: "([^"]+)"', q).group(1)
    out = {}
    for n in re.findall(r"n(\d+): pullRequest", q):
        st = cfg.get("prs", {}).get(repo + "#" + n)
        out["n" + n] = None if st is None else {"state": st, "mergedAt": "2026-10-15T00:00:00Z", "closedAt": None, "title": "t" + n}
    print(json.dumps({"data": {"repository": out}}))
elif a[0] == "api" and "/pulls/" in a[1]:
    n = a[1].rsplit("/", 1)[1]
    m = cfg.get("merge_sha", {}).get(n)
    print(json.dumps({"merged": bool(m), "merge_commit_sha": m}))
elif a[0] == "run":
    sha = a[a.index("--commit") + 1]
    print(json.dumps(cfg.get("runs", {}).get(sha, [])))
elif a[0] == "api" and a[1].endswith("pending_deployments"):
    if cfg.get("fail_pending"):
        sys.stderr.write("boom")
        sys.exit(1)
    rid = a[1].split("/")[-2]
    print(json.dumps(cfg.get("pending", {}).get(rid, [])))
else:
    sys.exit(2)
"""

FAKE_JIRA = r"""#!/usr/bin/env python3
import json, os, re, sys
cfg = json.load(open(os.environ["FAKE_GH_CFG"]))
keys = re.findall(r"[A-Z]+-\d+", sys.argv[2])
issues = [{"key": k, "fields": {"status": {"name": cfg["jira"][k]}, "summary": "s"}} for k in keys if k in cfg.get("jira", {})]
print(json.dumps({"result": {"content": [{"text": json.dumps({"issues": issues})}]}}))
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.cfg_path = os.path.join(d, "cfg.json")
        for name, body in (("gh", FAKE_GH), ("jira", FAKE_JIRA)):
            p = os.path.join(d, name)
            with open(p, "w") as fh:
                fh.write(body)
            os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
        R.GH = os.path.join(d, "gh")
        R.TRACKER_CMD = [os.path.join(d, "jira")]
        os.environ["FAKE_GH_CFG"] = self.cfg_path
        self.set_cfg({})

    def tearDown(self):
        self.tmp.cleanup()

    def set_cfg(self, cfg):
        with open(self.cfg_path, "w") as fh:
            json.dump(cfg, fh)


class PrefixTest(unittest.TestCase):
    def test_prefixes_resolve_to_their_repo(self):
        for name in ("alt-one", "alt-two"):
            prs, _ = R.extract_refs("Sign off on %s PR #9" % name)  # noqa: UP031
            self.assertEqual(prs, {(SEC, 9)}, name)

    def test_existing_prefixes_unchanged(self):
        self.assertEqual(R.extract_refs("primary PR #215")[0], {(PRI, 215)})
        self.assertEqual(R.extract_refs("secondary PR #233")[0], {(SEC, 233)})
        self.assertEqual(R.extract_refs("secondary-1 PR #7")[0], {(SEC, 7)})
        self.assertEqual(R.extract_refs("PR #215")[0], {(PRI, 215)})
        self.assertEqual(R.extract_refs("endpoint PR #5")[0], {(PRI, 5)})

    def test_prefix_does_not_swallow_unrelated_words(self):
        self.assertEqual(R.extract_refs("the other rollout is slow, see #9")[0], set())

    def test_loose_prs(self):
        self.assertEqual(
            R.extract_loose_prs("merged (#333, #334) and PR 229, PRs 12 and 13"),
            {(PRI, n) for n in (333, 334, 229, 12, 13)},
        )
        self.assertEqual(R.extract_loose_prs("issue C#5 and a&#39; entity"), set())


class ApplyTest(Base):
    def cfg_437(self, runs, pending=None, **extra):
        self.set_cfg(
            {
                "prs": {"primary#437": "MERGED"},
                "merge_sha": {"437": "c7ca6a30abdb8ac2762308bec99eee91c1bba943"},
                "runs": {"c7ca6a30abdb8ac2762308bec99eee91c1bba943": runs},
                "pending": pending or {},
                **extra,
            }
        )

    ITEM = {
        "title": "Approve the PowerShell 7.6 production apply (debt-id)",
        "why": "primary PR #437 merged and the production apply for the rest sits on the owner's gated approval.",
        "action": "Approve the gated production apply so debt-id closes.",
    }

    def run_item(self, item=None):
        return R.resolve(json.dumps([item or self.ITEM]))

    def test_completed_run_with_no_pending_is_finished(self):
        self.cfg_437(
            [
                {
                    "databaseId": 39525507927,
                    "workflowName": "terraform-apply",
                    "status": "completed",
                    "conclusion": "success",
                    "createdAt": "2026-10-21T01:07:57Z",
                }
            ]
        )
        res = self.run_item()
        ref = res["refs"]["primary PR #437"]
        self.assertTrue(ref["finished_apply"])
        self.assertEqual(ref["apply"]["state"], "applied")
        self.assertEqual(ref["apply"]["run"], 39525507927)
        self.assertIn("primary PR #437", res["done"])

    def test_pending_deployment_keeps_it_open(self):
        self.cfg_437(
            [
                {
                    "databaseId": 1,
                    "workflowName": "terraform-apply",
                    "status": "completed",
                    "conclusion": "success",
                    "createdAt": "2026-10-21T01:07:57Z",
                }
            ],
            pending={"1": [{"environment": {"name": "prod"}}]},
        )
        ref = self.run_item()["refs"]["primary PR #437"]
        self.assertFalse(ref["finished_apply"])
        self.assertEqual(ref["apply"]["state"], "pending")

    def test_running_failed_and_missing_runs_stay_open(self):
        for runs, state in (
            (
                [
                    {
                        "databaseId": 2,
                        "workflowName": "terraform-apply",
                        "status": "in_progress",
                        "conclusion": None,
                        "createdAt": "x",
                    }
                ],
                "pending",
            ),
            (
                [
                    {
                        "databaseId": 3,
                        "workflowName": "terraform-apply",
                        "status": "completed",
                        "conclusion": "failure",
                        "createdAt": "x",
                    }
                ],
                "failed",
            ),
            (
                [
                    {
                        "databaseId": 4,
                        "workflowName": "deploy-web",
                        "status": "completed",
                        "conclusion": "success",
                        "createdAt": "x",
                    }
                ],
                "no_run",
            ),
        ):
            self.cfg_437(runs)
            ref = self.run_item()["refs"]["primary PR #437"]
            self.assertFalse(ref["finished_apply"], state)
            self.assertEqual(ref["apply"]["state"], state)

    def test_newest_apply_run_wins(self):
        self.cfg_437(
            [
                {
                    "databaseId": 5,
                    "workflowName": "terraform-apply",
                    "status": "completed",
                    "conclusion": "failure",
                    "createdAt": "2026-10-21T01:00:00Z",
                },
                {
                    "databaseId": 6,
                    "workflowName": "terraform-apply",
                    "status": "completed",
                    "conclusion": "success",
                    "createdAt": "2026-10-21T02:00:00Z",
                },
            ]
        )
        self.assertEqual(self.run_item()["refs"]["primary PR #437"]["apply"]["run"], 6)

    def test_read_error_never_marks_finished(self):
        self.cfg_437(
            [
                {
                    "databaseId": 7,
                    "workflowName": "terraform-apply",
                    "status": "completed",
                    "conclusion": "success",
                    "createdAt": "x",
                }
            ],
            fail_pending=True,
        )
        res = self.run_item()
        ref = res["refs"]["primary PR #437"]
        self.assertFalse(ref["finished_apply"])
        self.assertEqual(ref["apply"]["state"], "unknown")
        self.assertTrue(res["errors"])

    def test_only_approve_apply_next_steps_are_checked(self):
        self.cfg_437(
            [
                {
                    "databaseId": 8,
                    "workflowName": "terraform-apply",
                    "status": "completed",
                    "conclusion": "success",
                    "createdAt": "x",
                }
            ]
        )
        other = {
            "title": "Re-review",
            "why": "primary PR #437 merged",
            "action": "Review the follow-up PR #437 notes.",
        }
        ref = self.run_item(other)["refs"]["primary PR #437"]
        self.assertNotIn("apply", ref)

    def test_ares_prs_are_not_apply_checked(self):
        self.set_cfg({"prs": {"secondary#9": "MERGED"}})
        item = {
            "title": "t",
            "why": "alt-one PR #9 merged",
            "action": "Approve the deployment of alt-one PR #9.",
        }
        ref = self.run_item(item)["refs"]["secondary PR #9"]
        self.assertNotIn("apply", ref)
        self.assertTrue(ref["done"])


class AutoCloseTest(Base):
    def auto(self, key, **kw):
        base = {"key": key, "title": "t", "why": "", "action": "", "refs": []}
        base.update(kw)
        return base

    def test_postgres_card_closes_when_every_pr_merged(self):
        self.set_cfg(
            {
                "prs": {
                    "primary#333": "MERGED",
                    "primary#334": "MERGED",
                    "primary#335": "MERGED",
                    "primary#340": "MERGED",
                }
            }
        )
        item = self.auto(
            "auto-postgres-private-endpoint",
            why="Prod APIs on the VNet since 10/15 (#333, #334 merged). Public access stays on until #340 lands and #335 flips it.",
            action="Nothing needed from me unless #340 or #335 is held.",
            refs=["debt-id"],
        )
        out = R.finished([item])
        self.assertEqual(list(out), ["auto-postgres-private-endpoint"])
        self.assertIn("primary PR #340 MERGED", out["auto-postgres-private-endpoint"])

    def test_loose_pr_n_form_closes(self):
        self.set_cfg({"prs": {"primary#229": "MERGED"}})
        item = self.auto(
            "auto-pipeline-identities-owner-apply",
            why="the owner applied the root after PR 229 merged: 9 added.",
        )
        self.assertIn("auto-pipeline-identities-owner-apply", R.finished([item]))

    def test_one_open_ref_keeps_it(self):
        self.set_cfg({"prs": {"primary#333": "MERGED", "primary#340": "OPEN"}})
        self.assertEqual(R.finished([self.auto("auto-x1", why="#333 merged, waits on #340")]), {})

    def test_closed_unmerged_pr_keeps_it(self):
        self.set_cfg({"prs": {"primary#12": "CLOSED"}})
        self.assertEqual(R.finished([self.auto("auto-x2", why="Waits on PR #12")]), {})

    def test_unresolvable_and_no_refs_never_close(self):
        self.set_cfg({"prs": {}})
        no_refs = self.auto("auto-x3", why="The canary failed", refs=["cron a651783603d5"])
        self.assertEqual(R.finished([no_refs]), {})
        not_found = self.auto("auto-x4", why="Waits on PR #99999")
        self.assertEqual(R.finished([not_found]), {})

    def test_read_error_keeps_item(self):
        # gh exits 2 for every call: nothing resolves, nothing closes.
        os.chmod(R.GH, 0o755)
        with open(R.GH, "w") as fh:
            fh.write("#!/bin/sh\nexit 1\n")
        self.assertEqual(R.finished([self.auto("auto-x5", why="Waits on PR #12")]), {})

    def test_jira_ref_done_closes_open_stays(self):
        self.set_cfg({"jira": {"TKT-11": "Done", "TKT-12": "In Progress"}})
        self.assertIn("auto-j1", R.finished([self.auto("auto-j1", refs=["TKT-11"])]))
        self.assertEqual(R.finished([self.auto("auto-j2", refs=["TKT-12"])]), {})
        self.assertEqual(R.finished([self.auto("auto-j3", refs=["TKT-11", "TKT-12"])]), {})

    def test_self_closing_and_button_cards_and_other_items_untouched(self):
        self.set_cfg({"prs": {"primary#12": "MERGED"}})
        items = [
            self.auto("auto-ui-standard-abc", why="PR #12"),
            self.auto("auto-alert-abc-1", why="PR #12"),
            self.auto("auto-gated", why="PR #12", approve={"label": "Approve"}),
            {"key": "oo-2026-10-13-sam", "title": "t", "why": "PR #12", "action": ""},
            {"key": "some-model-item", "title": "t", "why": "PR #12", "action": ""},
        ]
        self.assertEqual(R.finished(items), {})

    def test_ares_prefixed_ref_checks_the_ares_repo(self):
        # primary#9 is merged but unrelated, secondary #9 is open: the card must stay.
        self.set_cfg({"prs": {"primary#9": "MERGED", "secondary#9": "OPEN"}})
        self.assertEqual(R.finished([self.auto("auto-u1", why="Sign off on alt-one PR #9")]), {})
        self.set_cfg({"prs": {"primary#9": "OPEN", "secondary#9": "MERGED"}})
        self.assertIn(
            "auto-u1", R.finished([self.auto("auto-u1", why="Sign off on alt-one PR #9")])
        )


if __name__ == "__main__":
    unittest.main()
