"""
platform_reviews_config_test.py
Purpose: The platform reviews page with nothing configured and with its settings: the null default is an empty page and a
         501 on a write; the review script, the destroy workflow, the markers and the label are all settings, so unset they
         switch their feature off instead of naming an estate; tiers, the guard job pattern, the forbidden-text filter and
         the merge flags follow the config.
Run:     python3 platform_reviews_config_test.py
"""

from __future__ import annotations

import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="oprev-config-"))
for _d in ("", "../../lanes", "../../engine"):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), _d))

import platform_reviews as o  # noqa: E402
import platform_reviews_testenv as te  # noqa: E402

_ENV = {
    "TFGATE_STATE_DIR": str(TMP / "tfstate"),
    "TFGATE_CACHE_DIR": str(TMP / "tfcache"),
    "OPRG_CACHE_DIR": str(TMP / "cache"),
    "OPRG_STATE_DIR": str(TMP / "state"),
}


def setUpModule():
    te.apply(_ENV, TMP)


def tearDownModule():
    te.restore()


def configure(**platform):
    cfg = copy.deepcopy(te.CONFIG)
    cfg["platform"].update(platform)
    te.apply(_ENV, TMP, cfg)


class NullDefault(unittest.TestCase):
    def setUp(self):
        te.apply(_ENV, TMP, {})

    def tearDown(self):
        te.apply(_ENV, TMP)

    def test_an_unconfigured_page_is_empty(self):
        page = o.get()
        self.assertEqual(
            (page["configured"], page["needs_me"], page["counts"]["needs_me"]), (False, [], 0)
        )
        self.assertEqual(page["privileged"], [])

    def test_a_write_is_501(self):
        for fn, args in (
            (o.decide, ({"pr": 1, "head_sha": "a" * 40}, "approve")),
            (o.approve_merge, ({"pr": 1, "head_sha": "a" * 40},)),
        ):
            with self.assertRaises(Exception) as e:
                fn(*args)
            self.assertEqual(
                getattr(e.exception, "status", None) or getattr(e.exception, "code", None), 501
            )

    def test_every_estate_setting_is_off_by_default(self):
        self.assertEqual(
            (
                o._P("review_script_path", ""),
                o._P("destroy_workflow", ""),
                o.AI_MARKER,
                o.OVERRIDE_LABEL,
            ),
            ("", "", "", ""),
        )
        self.assertIsNone(o._engine_check(7, "a" * 40))
        self.assertFalse(o._forbidden("anything at all"))
        self.assertEqual((o._tier("prod"), o._tier("dev")), ("prod", "dev"))
        self.assertEqual(o._applier_text("owner"), "owner applies it")

    def test_destroys_are_not_dispatched_without_a_workflow(self):
        done = o._dispatch_destroys(7, [{"tool": "t", "tier": "prod"}])
        self.assertIn("no destroy workflow is configured", done[0])


class Configured(unittest.TestCase):
    def tearDown(self):
        te.apply(_ENV, TMP)

    def test_tier_names_and_the_guard_job_pattern_follow_the_config(self):
        configure(tiers={"prod": "live", "dev": "stage"})
        self.assertEqual((o._tier("prod"), o._tier("dev")), ("live", "stage"))
        m = o._guard_job().match("terraform plan (apps stage)")
        self.assertEqual(m.groups(), ("apps", "stage"))
        self.assertIsNone(o._guard_job().match("terraform plan (apps prod)"))
        configure(guard_job_regex=r"^plan \((\S+) ({tiers})\)$")
        self.assertTrue(o._guard_job().match("plan (apps prod)"))

    def test_the_forbidden_text_filter_and_the_default_changes_text_are_settings(self):
        self.assertTrue(o._forbidden("written by the assistant"))
        self.assertFalse(o._forbidden("plain words"))
        self.assertEqual(o._default_changes_text(), "Holding this for now.")

    def test_destroys_dispatch_only_for_the_configured_tiers_with_the_configured_workflow(self):
        calls = []
        saved = o._gh
        o._gh = lambda args, timeout=60, raw=False: calls.append(args) or ""
        o._log = lambda rec: None
        try:
            done = o._dispatch_destroys(
                7, [{"tool": "a", "tier": "prod"}, {"tool": "b", "tier": "dev"}]
            )
        finally:
            o._gh = saved
        self.assertEqual(len(calls), 1)
        self.assertIn("destroy.yml", calls[0])
        self.assertIn("tool=a", calls[0])
        self.assertIn("main", calls[0])
        self.assertIn("that tier's destroys run from the branch", done[1])

    def test_the_applier_text_and_the_merge_flags_are_settings(self):
        self.assertEqual(o._applier_text("owner"), "the owner applies it from a saved plan")
        self.assertEqual(o._applier_text("other"), "other applies it")
        configure(merge_flags=["--squash"])
        calls = []
        saved = o._gh
        o._gh = lambda args, timeout=60, raw=False: calls.append(args) or ""
        try:
            o._gh(["pr", "merge", "1", "-R", "x", *o._P("merge_flags"), "--match-head-commit", "h"])
        finally:
            o._gh = saved
        self.assertIn("--squash", calls[0])

    def test_the_ai_verdict_needs_its_markers(self):
        self.assertIsNotNone(o.AI_MARKER)
        configure(ai_review_marker="", ai_review_data_prefix="")
        self.assertIsNone(o._ai_verdict(7))


if __name__ == "__main__":
    unittest.main()
