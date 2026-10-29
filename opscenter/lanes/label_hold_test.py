"""tests: a do-not-merge hold says who, why and what stands behind it.
Synthetic data only. Run: /usr/bin/python3 label_hold_test.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

_tmp = tempfile.mkdtemp()
os.environ.setdefault("OPRG_STATE_DIR", _tmp)
os.environ.setdefault("OPRG_CACHE_DIR", _tmp)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import label_hold as lh  # noqa: E402

HEAD = "abcdef0" + "1" * 33
LOG = """**2026-10-18 ~09:00 UTC** - Opened acme/infra #9001 held do-not-merge for an unrelated reason.

---

**2026-10-19 ~10:00 UTC** - acme/infra #9002 merged, nothing about the other one.

- 2026-10-20 | Tackle ac_x. Verified live. Opened acme/infra #9001 held do-not-merge: the webhook retires. No merge this run; tackle rules. Live delete waits on the owner's merge.

- 2026-10-21 | acme/infra #90011 something else held.
"""


def comment(login, body, ts):
    return json.dumps({"user": {"login": login}, "body": body, "created_at": ts, "updated_at": ts})


class Note(unittest.TestCase):
    def test_newest_entry_with_hold_words_wins_and_starts_at_the_pr(self):
        n = lh.note_from_text(LOG, 9001)
        self.assertEqual(n["at"], "2026-10-20")
        self.assertTrue(n["text"].startswith("Opened acme/infra #9001 held do-not-merge"))
        self.assertNotIn(";", n["text"])
        self.assertIn("Live delete waits on the owner's merge.", n["text"])

    def test_pr_number_prefix_does_not_match(self):
        self.assertIsNone(lh.note_from_text("- 2026-10-21 | acme/infra #90011 held.", 9001))

    def test_missing_log_is_none(self):
        self.assertIsNone(lh.note_for(9001, os.path.join(_tmp, "nope.md")))


class Triage(unittest.TestCase):
    def test_only_markers_after_the_review_for_this_head(self):
        lines = [
            comment("owner1", f"old <!-- triage:{HEAD} H1 -->", "2026-10-20T10:00:00Z"),
            comment(
                "github-actions[bot]",
                "<!-- ai-review:v1 -->\nhead `abcdef0` review",
                "2026-10-20T11:00:00Z",
            ),
            comment("owner1", f"<!-- triage:{HEAD[:12]} H2 -->", "2026-10-20T12:00:00Z"),
            comment("owner1", "<!-- triage:9999999 H1 -->", "2026-10-20T12:30:00Z"),
        ]
        self.assertEqual(lh.triaged_from_comments(lines, HEAD, "owner1"), {"H2"})

    def test_no_review_for_head_means_nothing_triaged(self):
        lines = [comment("owner1", f"<!-- triage:{HEAD} H1 -->", "2026-10-20T12:00:00Z")]
        self.assertEqual(lh.triaged_from_comments(lines, HEAD, "owner1"), set())


ITEM = {
    "pr": 9001,
    "head_sha": HEAD,
    "red": ["plan (runbooks app)"],
    "findings": [{"id": "H1"}, {"id": "H2"}],
}


class Behind(unittest.TestCase):
    def test_untriaged_highs_and_guard_only_red(self):
        c = {
            "head_sha": HEAD,
            "checks": {"red": ["plan (runbooks app)"], "destroy_guard_only": True},
        }
        rest = lh.behind(ITEM, c, {"H2"})
        self.assertEqual([r["kind"] for r in rest], ["problem", "signoff"])
        self.assertIn("H1 has no triage reply", rest[0]["text"])
        self.assertIn("destroy guard", rest[1]["text"])

    def test_all_clear(self):
        c = {"head_sha": HEAD, "checks": {"red": [], "green": True}}
        self.assertEqual(lh.behind(ITEM, c, {"H1", "H2"}), [])

    def test_no_live_check_never_hides_red(self):
        rest = lh.behind(ITEM, None, {"H1", "H2"})
        self.assertEqual(rest[0]["kind"], "unknown")

    def test_unreadable_triage_is_unknown_not_clear(self):
        rest = lh.behind(dict(ITEM, red=[]), {"checks": {}}, None)
        self.assertEqual(rest[0]["kind"], "unknown")

    def test_import_covered_red_is_dropped(self):
        c = {"checks": {"red": ["plan (x)"]}}
        self.assertEqual(lh.behind(dict(ITEM, findings=[]), c, set(), ["plan (x)"]), [])


class Describe(unittest.TestCase):
    def test_mine_reads_you_and_next_depends_on_what_stands(self):
        ev = {"actor": "owner1", "at": "2026-10-20T13:58:54Z"}
        s, nxt, b = lh.describe(
            ITEM, "do-not-merge", ev, {"at": "2026-10-20", "text": "why"}, [], "owner1"
        )
        self.assertIn("you added do-not-merge on 10/20", s)
        self.assertIn("within 3 minutes", nxt)
        self.assertTrue(b["clear"])
        _, nxt2, b2 = lh.describe(
            ITEM, "do-not-merge", ev, None, [{"kind": "signoff", "text": "x"}], "owner1"
        )
        self.assertIn("Approve and merge", nxt2)
        self.assertTrue(b2["signoff_after"])
        self.assertIsNone(b2["why"])
        _, nxt3, b3 = lh.describe(
            ITEM, "do-not-merge", None, None, [{"kind": "problem", "text": "x"}], "owner1"
        )
        self.assertIn("alone will not merge", nxt3)
        self.assertFalse(b3["clear"])

    def test_text_is_ascii_without_semicolons(self):
        for args in (
            (None, None, []),
            ({"actor": "kyle", "at": "bad"}, None, [{"kind": "problem", "text": "x"}]),
        ):
            s, nxt, _ = lh.describe(ITEM, "do-not-merge", *args, "owner1")
            for t in (s, nxt):
                self.assertTrue(t.isascii())
                self.assertNotIn(";", t)


class Configuration(unittest.TestCase):
    def test_labels_and_zone_are_not_estate_values(self):
        self.assertEqual(lh.hold_label(["x", "do-not-merge"]), "do-not-merge")
        self.assertIsNone(lh.hold_label(["other"]))
        self.assertEqual(lh.hold_label(None), None)

    def test_when_uses_the_configured_zone_name(self):
        self.assertEqual(lh._when("2026-10-20T13:58:54Z").split(" ")[0], "10/20")
        self.assertEqual(lh._when("garbage"), "")


if __name__ == "__main__":
    unittest.main()
