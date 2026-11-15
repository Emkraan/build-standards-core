"""
grants_test.py
Purpose: Effective rights are the union across every matched role plus the user's own grants (a role only adds); reports and dashboards
         have separate global rights and per-object rights named by key; a grant is removed when its object is deleted and swept when
         it outlived its object (global rights are never touched, an unknown kind is left alone); a recreated key does not inherit an
         old grant; a broken store reads as empty.
Run:     python3 grants_test.py
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import grants as g

ROLES = {
    "viewer": ["reports.view"],
    "analyst": ["dashboards.view", "report:sales"],
    "ops": ["dashboard:health"],
}


class Effective(unittest.TestCase):
    def test_the_union_of_every_matched_role_and_the_user_grants(self):
        self.assertEqual(
            g.effective(["viewer", "analyst"], ["report:extra"], ROLES),
            {"reports.view", "dashboards.view", "report:sales", "report:extra"},
        )

    def test_a_role_only_adds(self):
        base = g.effective(["viewer"], [], ROLES)
        more = g.effective(["viewer", "ops"], [], ROLES)
        self.assertTrue(base <= more)

    def test_an_unknown_role_or_no_roles_adds_nothing(self):
        self.assertEqual(g.effective(["ghost"], [], ROLES), set())
        self.assertEqual(g.effective([], None, ROLES), set())

    def test_reports_and_dashboards_have_separate_global_rights(self):
        self.assertTrue(g.can_view("report", {"reports.view"}, "any"))
        self.assertFalse(g.can_view("dashboard", {"reports.view"}, "any"))
        self.assertTrue(g.can_view("dashboard", {"dashboards.view"}, "any"))
        self.assertFalse(g.can_view("report", {"dashboards.view"}, "any"))

    def test_a_per_object_right_opens_only_that_key_and_that_kind(self):
        rights = {"report:sales"}
        self.assertTrue(g.can_view("report", rights, "sales"))
        self.assertFalse(g.can_view("report", rights, "other"))
        self.assertFalse(g.can_view("dashboard", rights, "sales"))
        with self.assertRaises(ValueError):
            g.can_view("page", rights, "x")


class Store(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "grants.json"
        self.s = g.GrantStore(self.path)
        for role, rights in ROLES.items():
            for r in rights:
                self.s.grant(role, r)

    def tearDown(self):
        self.tmp.cleanup()

    def test_grant_and_revoke(self):
        self.assertEqual(self.s.role_grants()["analyst"], ["dashboards.view", "report:sales"])
        self.s.grant("analyst", "report:sales")  # idempotent
        self.assertEqual(self.s.role_grants()["analyst"], ["dashboards.view", "report:sales"])
        self.s.revoke("analyst", "report:sales")
        self.assertEqual(self.s.role_grants()["analyst"], ["dashboards.view"])
        self.s.revoke("ops", "dashboard:health")
        self.assertNotIn("ops", self.s.role_grants())
        with self.assertRaises(ValueError):
            self.s.grant("", "x")

    def test_deleting_a_report_removes_its_grants_from_every_role(self):
        self.s.grant("viewer", "report:sales")
        removed = self.s.on_delete("report", "sales")
        self.assertEqual(sorted(removed), [("analyst", "report:sales"), ("viewer", "report:sales")])
        self.assertNotIn("report:sales", self.s.role_grants()["analyst"])
        self.assertIn("reports.view", self.s.role_grants()["viewer"])  # a global right is untouched

    def test_a_recreated_key_does_not_inherit_an_old_grant(self):
        self.s.on_delete("report", "sales")
        self.assertFalse(
            g.can_view("report", g.effective(["analyst"], [], self.s.role_grants()), "sales")
        )

    def test_sweep_removes_grants_that_outlived_their_object_and_keeps_live_ones(self):
        removed = self.s.sweep({"report": {"other"}, "dashboard": {"health"}})
        self.assertEqual(removed, [("analyst", "report:sales")])
        grants = self.s.role_grants()
        self.assertIn("dashboard:health", grants["ops"])
        self.assertEqual(grants["viewer"], ["reports.view"])

    def test_sweep_leaves_a_kind_it_was_not_told_about_alone(self):
        self.assertEqual(
            self.s.sweep({"report": {"sales"}}), []
        )  # dashboards are not in `live`: nothing removed for them
        self.assertIn("dashboard:health", self.s.role_grants()["ops"])

    def test_a_missing_or_broken_store_reads_as_empty(self):
        other = g.GrantStore(Path(self.tmp.name) / "none.json")
        self.assertEqual(other.role_grants(), {})
        self.path.write_text("{broken")
        self.assertEqual(self.s.role_grants(), {})
        self.assertEqual(self.s.sweep({"report": set()}), [])


if __name__ == "__main__":
    unittest.main()
