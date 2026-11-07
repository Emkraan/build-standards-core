"""
owner_roots_ahead_test.py
Purpose: A root a pull request applied from its branch is ahead of main: main's plan that would destroy what the PR applied is
         marked "ahead of main, waiting on #N", Apply is refused by the server and the worker, and the owner apply guard
         refuses a delete of a branch-applied address even when the card was never marked; the hold clears when main contains
         the PR merge commit or the PR closes; an unread PR keeps the hold; a PR left ahead of main for more than two days
         becomes an Action Center item; with no provider nothing is held back.
Run:     python3 owner_roots_ahead_test.py
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

SCRATCH = Path(tempfile.mkdtemp(prefix="owner-roots-ahead-test-", dir=os.environ.get("TMPDIR")))
os.environ["OWNER_ROOTS_CACHE"] = str(SCRATCH / "cache")
os.environ["OWNER_ROOTS_DECISIONS"] = str(SCRATCH / "decisions.jsonl")
(SCRATCH / "cache").mkdir(parents=True, exist_ok=True)

import owner_roots as o  # noqa: E402

DAY = 86400
NOW = o._epoch("2026-10-31T18:00:00Z")
KEY = "ident:dev"
RES = [
    {"address": "a.keep", "action": "add"},
    {"address": "a.gone", "action": "destroy"},
    {"address": "b.swap", "action": "replace"},
    {"address": "c.other", "action": "destroy"},
]


class Provider:
    """pr_state, contains, pr_url and owner_name as the consumer would supply them."""

    def __init__(self):
        self.prs = {513: ("open", None)}
        self.merged_in = set()

    def pr_state(self, pr):
        return self.prs.get(pr, ("unknown", None))

    def contains(self, oid, sha):
        return (oid, sha) in self.merged_in

    def pr_url(self, pr):
        return f"https://example.invalid/pull/{pr}"

    def owner_name(self):
        return "Owner"


def hold(pr, **kw):
    rec = {
        "pr": pr,
        "head": "a" * 40,
        "addresses": ["a.gone", "b.swap"],
        "pr_state": "open",
        "applied_at": None,
    }
    rec.update(kw)
    return rec


class Base(unittest.TestCase):
    def setUp(self):
        o._set_top(pr_applied={})
        o._load_status().get("items", {}).clear()
        self.prov = Provider()
        self._provider = o.provider
        o.provider = lambda: self.prov

    def tearDown(self):
        o.provider = self._provider


class Hold(Base):
    def test_set_pr_hold_records_only_what_the_pr_added_or_changed(self):
        rec = o.set_pr_hold(
            "ident",
            "dev",
            513,
            "h" * 40,
            "d" * 64,
            [*RES, {"address": "z.imp", "action": "import"}],
        )
        self.assertEqual(rec["addresses"], ["a.keep", "b.swap", "z.imp"])
        self.assertEqual(o._holds()[KEY]["pr"], 513)

    def test_main_plan_that_destroys_the_prs_resources_is_ahead_of_main(self):
        o.set_pr_hold(
            "ident",
            "dev",
            513,
            "h" * 40,
            "d" * 64,
            [{"address": "a.gone", "action": "add"}, {"address": "b.swap", "action": "add"}],
        )
        ahead = o._hold_check("ident", "dev", RES, "m" * 40)
        self.assertEqual((ahead["pr"], ahead["addresses"]), (513, ["a.gone", "b.swap"]))
        self.assertIn("Ahead of main, waiting on #513", o._ahead_text(ahead))
        self.assertIsNone(
            o._hold_check("ident", "dev", [{"address": "c.other", "action": "destroy"}], "m" * 40)
        )

    def test_the_hold_clears_when_main_contains_the_merge_commit(self):
        o._set_hold(KEY, hold(513))
        self.prov.prs[513] = ("merged", "c" * 40)
        self.assertIsNotNone(
            o._hold_check("ident", "dev", RES, "m" * 40)
        )  # merged but main does not have it yet
        self.prov.merged_in.add(("c" * 40, "m" * 40))
        self.assertIsNone(o._hold_check("ident", "dev", RES, "m" * 40))
        self.assertNotIn(KEY, o._holds())

    def test_a_pr_closed_unmerged_releases_the_hold(self):
        o._set_hold(KEY, hold(513))
        self.prov.prs[513] = ("closed", None)
        self.assertIsNone(o._hold_check("ident", "dev", RES, "m" * 40))
        self.assertNotIn(KEY, o._holds())

    def test_an_unreadable_pr_keeps_the_hold(self):
        o._set_hold(KEY, hold(999))  # the provider knows nothing of #999
        self.assertIsNotNone(o._hold_check("ident", "dev", RES, "m" * 40))
        self.assertIn(KEY, o._holds())

    def test_refresh_holds_records_the_pr_state_and_releases_a_closed_pr(self):
        o._set_hold(KEY, hold(513))
        o._set_hold("b:dev", hold(514))
        self.prov.prs.update({513: ("merged", "c" * 40), 514: ("closed", None)})
        o._update("b:dev", ahead_of_main={"pr": 514, "addresses": ["x"]})
        o.refresh_holds(force=True)
        self.assertEqual(o._holds()[KEY]["pr_state"], "merged")
        self.assertNotIn("b:dev", o._holds())
        self.assertIsNone(o._load_status()["items"]["b:dev"]["ahead_of_main"])

    def test_with_no_provider_a_hold_is_kept(self):
        o.provider = lambda: None
        o._set_hold(KEY, hold(513))
        self.assertEqual(o._pr_state(513), ("unknown", None))
        self.assertIsNotNone(o._hold_check("ident", "dev", RES, "m" * 40))


class Refusals(Base):
    def pending(self, resources=RES, ahead=True, digest="d" * 64):
        o._update(
            KEY,
            name="ident",
            tier="dev",
            state="pending",
            plan_sha256=digest,
            resources=resources,
            main_sha="m" * 40,
            planned_at=o._now(),
            ahead_of_main={"pr": 513, "head": "a" * 40, "addresses": ["a.gone"]} if ahead else None,
        )
        (o.PLANS).mkdir(parents=True, exist_ok=True)
        (o.PLANS / "ident-dev.tfplan").write_bytes(b"x")

    def test_the_worker_refuses_apply_while_ahead_and_leaves_the_plan_unapplied(self):
        o._set_hold(KEY, hold(513))
        import hashlib

        digest = hashlib.sha256(b"x").hexdigest()
        self.pending(digest=digest)
        o.apply("ident", "dev", digest)
        it = o._load_status()["items"][KEY]
        self.assertEqual(it["state"], "error")
        self.assertIn("Ahead of main, waiting on #513", it["error"])
        self.assertFalse((o.PLANS / "ident-dev.tfplan").exists())

    def test_the_server_refuses_apply_while_ahead(self):
        o._set_hold(KEY, hold(513))
        self.pending()
        code, body = o.request(
            {"name": "ident", "tier": "dev", "plan_sha256": "d" * 64, "confirm": "ident"}, "apply"
        )
        self.assertEqual(code, 409)
        self.assertIn("waiting on #513", body["error"])

    def test_the_guard_refuses_a_delete_of_a_branch_applied_address_even_with_no_mark(self):
        o._set_hold(KEY, hold(513))
        self.pending(ahead=False)
        why = o.guard_refusal("ident", "dev", o._load_status()["items"][KEY])
        self.assertIn("waiting on #513", why)
        self.assertEqual(o.main(["guard", "ident", "dev"]), 3)

    def test_the_guard_passes_when_no_delete_touches_what_the_pr_applied(self):
        o._set_hold(KEY, hold(513, addresses=["unrelated.x"]))
        self.pending(ahead=False)
        self.assertIsNone(o.guard_refusal("ident", "dev", o._load_status()["items"][KEY]))
        self.assertEqual(o.main(["guard", "ident", "dev"]), 0)

    def test_the_guard_ignores_a_merged_or_closed_pr_and_a_root_with_no_hold(self):
        self.pending(ahead=False)
        it = o._load_status()["items"][KEY]
        self.assertIsNone(o.guard_refusal("ident", "dev", it))
        o._set_hold(KEY, hold(513, pr_state="merged"))
        self.assertIsNone(o.guard_refusal("ident", "dev", it))

    def test_the_card_shows_the_ahead_text_only_while_pending_and_held(self):
        o._set_hold(KEY, hold(513))
        self.pending()
        card = {x["key"]: x for x in o.get()["items"]}[KEY]
        self.assertIn("waiting on #513", card["ahead_text"])
        o._set_hold(KEY, None)
        card = {x["key"]: x for x in o.get()["items"]}[KEY]
        self.assertIsNone(card["ahead_text"])


class AheadCard(Base):
    def test_applied_more_than_two_days_ago_is_a_card(self):
        o._set_hold(KEY, hold(513, applied_at="2026-10-29T02:00:00Z"))
        items = o.ahead_items(NOW)
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it["key"], "ahead-ident-dev-pr513")
        self.assertIn("2 days", it["title"])
        self.assertIn("applied from its branch", it["why"])
        self.assertIn("Merge PR #513", it["action"])
        self.assertEqual(
            (it["owner"], it["links"][0]["url"]), ("Owner", "https://example.invalid/pull/513")
        )

    def test_younger_than_two_days_is_not(self):
        o._set_hold(KEY, hold(521, applied_at="2026-10-30T19:00:00Z"))
        self.assertEqual(o.ahead_items(NOW), [])

    def test_detected_hold_counts_from_detection(self):
        o._set_hold(KEY, hold(513, source="detected", detected_at="2026-10-28T12:00:00Z"))
        it = o.ahead_items(NOW)[0]
        self.assertIn("3 days", it["title"])
        self.assertIn("found live", it["why"])

    def test_hold_without_a_time_is_stamped_not_carded(self):
        o._set_hold(KEY, hold(513, source="detected"))
        self.assertEqual(o.ahead_items(NOW), [])
        self.assertTrue(o._holds()[KEY].get("detected_at"))

    def test_merged_and_closed_prs_are_skipped(self):
        o._set_hold("a:dev", hold(1, applied_at="2026-10-01T00:00:00Z", pr_state="merged"))
        o._set_hold("b:dev", hold(2, applied_at="2026-10-01T00:00:00Z", pr_state="closed"))
        self.assertEqual(o.ahead_items(NOW), [])

    def test_threshold_is_configurable_and_no_url_means_no_link(self):
        o._set_hold(KEY, hold(521, applied_at="2026-10-31T17:00:00Z"))
        self.prov.pr_url = lambda pr: None
        old = o.AHEAD_CARD_S
        try:
            o.AHEAD_CARD_S = 1800
            items = o.ahead_items(NOW)
            self.assertEqual((len(items), items[0]["links"]), (1, []))
        finally:
            o.AHEAD_CARD_S = old


if __name__ == "__main__":
    unittest.main()
