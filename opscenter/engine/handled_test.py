#!/usr/bin/env python3
"""Tests for handled.py. Synthetic records only (the titles mirror the 10/14 and 10/16 repeats)."""

from __future__ import annotations

import datetime as dt
import unittest

import handled as H

NOW = dt.datetime(2026, 10, 14, 23, 0, tzinfo=dt.timezone.utc)


def rec(
    act, title="", key=None, refs=None, at="2026-10-14T19:20:14Z", until=None, cids=None, why=""
):
    r = {
        "act": act,
        "at": at,
        "item": {"title": title, "key": key, "refs": refs or [], "cids": cids or [], "why": why},
    }
    if until:
        r["until"] = until
    return r


class AliasTest(unittest.TestCase):
    def test_rekeyed_reworded_repeat_of_an_ignore_aliases(self):
        handled = {
            "ac_old": rec(
                "ignored",
                "Active High-severity malware alert on database server host-01, ownership unconfirmed",
                key="host-01-malware-defender-alert",
            )
        }
        items = [
            {
                "fp": "ac_new",
                "key": "malware-alert-host-01-monitor",
                "title": "Active High-severity malware alert on host-01 (database server), ownership still unconfirmed",
            }
        ]
        moved = H.alias_items(items, handled, NOW)
        self.assertEqual(items[0]["fp"], "ac_old")
        self.assertEqual(items[0]["fp_alias_of"], "ac_new")
        self.assertTrue(moved[0][2].startswith("title"))

    def test_same_key_or_primary_ref_aliases(self):
        handled = {
            "ac_k": rec("ignored_forever", "x y z", key="vendor-b-xsm"),
            "ac_r": rec("ignored", "vendor-b XSM contract renewal number", refs=["ticket-id"]),
        }
        a = {"fp": "f1", "key": "vendor-b-xsm", "title": "totally different words here"}
        b = {
            "fp": "f2",
            "key": "other",
            "refs": ["ticket-id", "ticket-id"],
            "title": "Confirm the vendor-b XSM renewal number",
        }
        H.alias_items([a, b], handled, NOW)
        self.assertEqual((a["fp"], b["fp"]), ("ac_k", "ac_r"))

    def test_resolved_repeat_aliases_without_new_evidence(self):
        handled = {
            "ac_old": rec(
                "resolved",
                "vendor-b MPS API password expired, hub serving stale data",
                key="vendor-b-mps",
            )
        }
        it = {
            "fp": "ac_new",
            "key": "vendor-b-mps",
            "title": "vendor-b MPS API password expired, hub serving stale data",
        }
        H.alias_items([it], handled, NOW, evidence={})
        self.assertEqual(it["fp"], "ac_old")

    def test_resolved_repeat_shows_when_evidence_is_unknown(self):
        handled = {"ac_old": rec("resolved", "x", key="vendor-b-mps")}
        it = {"fp": "ac_new", "key": "vendor-b-mps", "title": "y"}
        H.alias_items([it], handled, NOW, evidence=None)
        self.assertEqual(it["fp"], "ac_new")

    def test_resolved_older_than_window_does_not_alias(self):
        handled = {"ac_old": rec("resolved", "x", key="k", at="2026-09-01T00:00:00Z")}
        it = {"fp": "n", "key": "k", "title": "y"}
        H.alias_items([it], handled, NOW, evidence={})
        self.assertEqual(it["fp"], "n")

    def test_new_message_after_decision_shows_the_repeat(self):
        handled = {"ac_old": rec("resolved", "x", key="k", cids=["teams.1on1:a"])}
        it = {"fp": "n", "key": "k2", "title": "y", "cids": ["teams.1on1:a"]}
        it2 = dict(it, key="k")
        H.alias_items([it2], handled, NOW, evidence={"teams.1on1:a": "2026-10-14T22:00:00Z"})
        self.assertEqual(it2["fp"], "n")

    def test_ignored_forever_ignores_new_evidence(self):
        handled = {"ac_old": rec("ignored_forever", "x", key="k", cids=["c1"])}
        it = {"fp": "n", "key": "k", "title": "y", "cids": ["c1"]}
        H.alias_items([it], handled, NOW, evidence={"c1": "2026-10-14T22:00:00Z"})
        self.assertEqual(it["fp"], "ac_old")

    def test_rekeyed_repeat_from_same_sources_aliases(self):
        # pilot pilot PC confirm, 10/16: four keys, same Slack messages, nothing new from Person A.
        handled = {
            "ac_old": rec(
                "resolved",
                "Person A needs a technical confirm on the pilot pre-provisioned PC",
                key="pilot-preprovisioned-pc-confirm",
                cids=["slack:C1:1", "slack:C1:2"],
                why="Person A re-ran the device registration registration on the pilot pilot PC and wants a confirm",
            )
        }
        it = {
            "fp": "n",
            "key": "pilot-device2-confirm",
            "title": "Confirm the pilot device registration pilot device looks right on the org side",
            "why": "Person A re-ran the org device registration registration script on the pilot pilot device",
            "cids": ["slack:C1:2"],
        }
        moved = H.alias_items([it], handled, NOW, evidence={"slack:C1:2": "2026-10-14T12:00:00Z"})
        self.assertEqual((it["fp"], moved[0][2]), ("ac_old", "source"))

    def test_unrelated_ask_in_the_same_thread_does_not_alias(self):
        # A person's 1:1 carried the video tool retention ask and, later, the function-app ask.
        handled = {
            "ac_old": rec(
                "resolved",
                "Video tool AI features off and a 30-day recording retention cut",
                cids=["teams.1on1:person-c"],
                why="person asked about Video tool AI features and recording retention",
            )
        }
        it = {
            "fp": "n",
            "key": "ask-person-c-app-deploy",
            "title": "Give person the go-ahead on deploying his Atlassian-support function app",
            "why": "person needs to deploy a function app for an Atlassian integration",
            "cids": ["teams.1on1:person-c"],
        }
        H.alias_items([it], handled, NOW, evidence={})
        self.assertEqual(it["fp"], "n")

    def test_source_match_needs_the_tickets_covered(self):
        # A plan approval re-cited another person's thread but names a ticket the decision never had.
        handled = {
            "ac_old": rec(
                "resolved",
                "Desktop catch-up call with Person E",
                cids=["mail:1", "teams:d"],
                why="Desktop call",
            )
        }
        it = {
            "fp": "n",
            "title": "Approve the desktop build plan",
            "refs": ["ticket-id"],
            "cids": ["mail:1", "teams:d"],
            "why": "desktop call plan",
        }
        H.alias_items([it], handled, NOW, evidence={})
        self.assertEqual(it["fp"], "n")

    def test_source_match_skips_an_item_already_on_the_board_before_the_decision(self):
        handled = {
            "ac_old": rec("resolved", "app-b duplicate Confluence pages cleanup", cids=["t:sam"])
        }
        it = {
            "fp": "n",
            "title": "app-b duplicate Confluence pages cleanup today",
            "key": "k2",
            "cids": ["t:sam"],
        }
        H.alias_items([it], handled, NOW, evidence={}, first_seen={"n": "2026-10-14T10:00:00Z"})
        self.assertEqual(it["fp"], "ac_old")  # title match still holds
        it3 = {
            "fp": "m",
            "title": "person wants the endpoint UAT form areas listed",
            "key": "k3",
            "cids": ["t:sam"],
        }
        H.alias_items([it3], handled, NOW, evidence={}, first_seen={"m": "2026-10-14T10:00:00Z"})
        self.assertEqual(it3["fp"], "m")

    def test_deterministic_items_never_alias(self):
        handled = {
            "ac_old": rec("resolved", "Review his Mail Flow Governance page", refs=["ticket-id"])
        }
        it = {
            "fp": "n",
            "key": "oo-2026-10-08-person-d-library",
            "title": "Review his Mail Flow Governance page",
            "refs": ["ticket-id"],
        }
        H.alias_items([it], handled, NOW, evidence={})
        self.assertEqual(it["fp"], "n")

    def test_expired_snooze_does_not_alias_live_one_does(self):
        t = "PaperCut future state strategy needs the owner's input"
        gone = {"ac_s": rec("snoozed", t, until="2026-10-13T00:00:00Z")}
        live = {"ac_s": rec("snoozed", t, until="2026-10-20T00:00:00Z")}
        a, b = {"fp": "n1", "title": t}, {"fp": "n2", "title": t}
        H.alias_items([a], gone, NOW)
        H.alias_items([b], live, NOW)
        self.assertEqual((a["fp"], b["fp"]), ("n1", "ac_s"))

    def test_resurface_marker_alone_does_not_bring_it_back(self):
        # 10/16: an ignored Person B ask came back as "[resurfaced: per today's state note]".
        handled = {
            "ac_old": rec(
                "ignored", "Malware alert on host-01 database server", key="k", cids=["c1"]
            )
        }
        it = {
            "fp": "n",
            "key": "k",
            "title": "Malware alert on host-01 database server",
            "why": "[resurfaced: now spreading] ...",
            "cids": ["c1"],
        }
        H.alias_items([it], handled, NOW, evidence={"c1": "2026-10-14T10:00:00Z"})
        self.assertEqual(it["fp"], "ac_old")

    def test_unrelated_titles_and_short_titles_do_not_alias(self):
        handled = {
            "ac_a": rec("ignored", "Teams federation ticket with mdwcg.com still unassigned"),
            "ac_b": rec("ignored", "UKG down"),
        }
        a = {"fp": "n1", "title": "vendor-a international dialing ticket still unassigned"}
        b = {"fp": "n2", "title": "UKG down"}
        H.alias_items([a, b], handled, NOW)
        self.assertEqual((a["fp"], b["fp"]), ("n1", "n2"))

    def test_old_title_only_decision_is_outside_the_window(self):
        handled = {
            "ac_a": rec(
                "ignored",
                "Legacy Azure Blob Storage v1 accounts need GPv2 migration",
                at="2026-08-01T00:00:00Z",
            )
        }
        it = {"fp": "n", "title": "Legacy Azure Blob Storage v1 accounts need GPv2 migration"}
        H.alias_items([it], handled, NOW)
        self.assertEqual(it["fp"], "n")

    def test_item_already_handled_by_exact_fp_is_untouched(self):
        handled = {
            "n": rec("ignored", "same"),
            "ac_x": rec("ignored", "Malware alert on host-01 database server"),
        }
        it = {"fp": "n", "title": "Malware alert on host-01 database server"}
        self.assertEqual(H.alias_items([it], handled, NOW), [])

    def test_compact_bundle_keeps_key_title_and_drops_old_resolved(self):
        handled = {
            "a": rec("ignored", "T1", key="k1"),
            "b": rec("resolved", "T2", at="2026-09-01T00:00:00Z"),
            "c": rec("snoozed", "T3", until="2026-10-01T00:00:00Z"),
        }
        out = H.compact_for_bundle(handled, NOW)
        self.assertEqual(list(out), ["a"])
        self.assertEqual(out["a"]["key"], "k1")
        self.assertNotIn("why", out["a"])


if __name__ == "__main__":
    unittest.main()
