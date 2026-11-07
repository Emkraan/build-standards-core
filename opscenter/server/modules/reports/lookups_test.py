"""
lookups_test.py
Purpose: The R6 lookup layers. Directory: account names are keyed trimmed and lowercased, the bare name is taken out of DOMAIN\\sam and a UPN, computer
         and service accounts and the posting device are "not a person", a single match is found and two matches or none is not found (never
         guessed), each name is looked up once and cached, an outage pauses lookups and never fails the caller, any other failure is stored as an
         error and retried later. Catalog: ids not matching the pattern are ignored, ids are looked up once, an outage caches nothing and pauses,
         a person's publisher is never overwritten and never expires, and removing it sends the id back to the lookup.
Run:     python3 lookups_test.py
"""

import datetime as dt
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reports import catalog as cat  # noqa: E402
from reports import directory as d  # noqa: E402
from reports import lookup_db  # noqa: E402

T0 = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
PERSON = {
    "displayName": "Pat Example",
    "userPrincipalName": "pat@corp.example",
    "mail": "pat@corp.example",
    "department": "Ops",
    "jobTitle": "Analyst",
    "accountEnabled": True,
}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["OPSCENTER_REPORTS_DB"] = str(Path(self.tmp.name) / "r.db")
        d.reset_pause()

    def tearDown(self):
        os.environ.pop("OPSCENTER_REPORTS_DB", None)
        self.tmp.cleanup()


class Names(unittest.TestCase):
    def test_the_key_is_trimmed_and_lowercased(self):
        self.assertEqual(d.account_key("  CORP\\Pat "), "corp\\pat")
        self.assertEqual(d.account_key(None), "")

    def test_the_bare_name_comes_out_of_a_domain_or_a_upn(self):
        self.assertEqual(d.bare_account("CORP\\Pat"), "pat")
        self.assertEqual(d.bare_account("Pat@corp.example"), "pat")
        self.assertEqual(d.bare_account("pat"), "pat")

    def test_not_a_person_classes(self):
        for raw in ["", "SYSTEM", "Local Service", "CORP\\Administrator", "PC01$", "CORP\\PC01$"]:
            self.assertTrue(d.is_not_person(raw), raw)
        self.assertFalse(d.is_not_person("CORP\\pat"))
        self.assertTrue(d.is_not_person("CORP\\pc01", device="PC01"))
        self.assertFalse(d.is_not_person("CORP\\pat", device="PC01"))


class Resolve(unittest.TestCase):
    def test_a_single_account_match_is_found(self):
        e = d.resolve_account(
            "CORP\\pat", lambda kind, v: [PERSON] if kind == "account" and v == "pat" else []
        )
        self.assertEqual(
            (e["status"], e["displayName"], e["email"], e["enabled"]),
            ("found", "Pat Example", "pat@corp.example", True),
        )

    def test_the_principal_name_is_the_second_try(self):
        calls = []

        def lookup(kind, v):
            calls.append((kind, v))
            return [PERSON] if kind == "principal" else []

        self.assertEqual(d.resolve_account("pat", lookup)["status"], "found")
        self.assertEqual(calls, [("account", "pat"), ("principal", "pat@")])

    def test_two_matches_are_not_found_never_a_guess(self):
        calls = []

        def lookup(kind, v):
            calls.append(kind)
            return [PERSON, PERSON]

        self.assertEqual(d.resolve_account("pat", lookup)["status"], "not_found")
        self.assertEqual(calls, ["account"])

    def test_no_match_is_not_found(self):
        self.assertEqual(d.resolve_account("pat", lambda k, v: [])["status"], "not_found")


class Enrich(Base):
    def test_each_name_is_looked_up_once_and_cached(self):
        calls = []

        def lookup(kind, v):
            calls.append(v)
            return [PERSON] if kind == "account" else []

        self.assertEqual(
            d.enrich_accounts(["CORP\\Pat", "corp\\pat", " CORP\\PAT"], "PC01", lookup, T0), 1
        )
        self.assertEqual(
            d.enrich_accounts(["CORP\\Pat"], "PC01", lookup, T0 + dt.timedelta(days=1)), 0
        )
        self.assertEqual(calls, ["pat"])
        self.assertEqual(d.get_entry("CORP\\PAT")["displayName"], "Pat Example")

    def test_computers_and_the_device_are_stored_without_a_lookup(self):
        def lookup(kind, v):
            raise AssertionError("no lookup for a non person")

        d.enrich_accounts(["PC01$", "CORP\\pc01", "system"], "PC01", lookup, T0)
        self.assertEqual(d.directory_stats()["notUser"], 3)

    def test_ttls_found_30_days_miss_1_day(self):
        d.enrich_accounts(["a", "b"], None, lambda k, v: [PERSON] if v.startswith("a") else [], T0)
        self.assertEqual(d.stale_accounts(["a", "b"], T0 + dt.timedelta(hours=23)), [])
        self.assertEqual(d.stale_accounts(["a", "b"], T0 + dt.timedelta(days=2)), ["b"])
        self.assertEqual(d.stale_accounts(["a", "b"], T0 + dt.timedelta(days=31)), ["a", "b"])

    def test_an_outage_pauses_ten_minutes_and_never_raises(self):
        def down(kind, v):
            raise d.DirectoryUnavailable()

        self.assertEqual(d.enrich_accounts(["a"], None, down, T0), 0)
        self.assertEqual(d.directory_stats(), {"found": 0, "notFound": 0, "notUser": 0, "error": 0})
        ok = lambda k, v: [PERSON]  # noqa: E731
        self.assertEqual(d.enrich_accounts(["a"], None, ok, T0 + dt.timedelta(minutes=5)), 0)
        self.assertEqual(d.enrich_accounts(["a"], None, ok, T0 + dt.timedelta(minutes=11)), 1)

    def test_another_failure_is_an_error_retried_after_an_hour(self):
        def boom(kind, v):
            raise RuntimeError("x")

        d.enrich_accounts(["a"], None, boom, T0)
        self.assertEqual(d.directory_stats()["error"], 1)
        self.assertEqual(d.stale_accounts(["a"], T0 + dt.timedelta(minutes=30)), [])
        self.assertEqual(d.stale_accounts(["a"], T0 + dt.timedelta(hours=2)), ["a"])

    def test_at_most_200_per_run(self):
        names = [f"u{i}" for i in range(250)]
        self.assertEqual(d.enrich_accounts(names, None, lambda k, v: [], T0), 200)
        self.assertEqual(d.enrich_accounts(names, None, lambda k, v: [], T0), 50)

    def test_expire_marks_everything_stale(self):
        d.enrich_accounts(["a"], None, lambda k, v: [PERSON], T0)
        self.assertEqual(d.expire_directory(), 1)
        self.assertEqual(d.stale_accounts(["a"], T0), ["a"])


class Catalog(Base):
    def setUp(self):
        super().setUp()
        self.c = cat.Catalog(r"^[a-p]{32}$")

    def hit(self, i):
        return {
            "status": "found",
            "store": "Store",
            "name": "Ext",
            "publisher": "Pub",
            "installs": 5,
        }

    def test_junk_ids_are_ignored(self):
        self.assertEqual(self.c.stale(["nope", "", None, "a" * 32, "A" * 32, "q" * 32]), ["a" * 32])

    def test_each_id_is_looked_up_once(self):
        calls = []
        ids = ["a" * 32, "b" * 32]

        def fetch(i):
            calls.append(i)
            return self.hit(i)

        self.assertEqual(self.c.enrich(ids + ids, fetch, T0), 2)
        self.assertEqual(self.c.enrich(ids, fetch, T0 + dt.timedelta(days=1)), 0)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.c.get("a" * 32)["publisher"], "Pub")
        self.assertEqual(self.c.stats(), {"found": 2, "notFound": 0})

    def test_ttls_found_30_days_miss_7_days(self):
        a, b = "a" * 32, "b" * 32
        self.c.enrich([a, b], lambda i: self.hit(i) if i == a else {"status": "not_found"}, T0)
        self.assertEqual(self.c.stale([a, b], T0 + dt.timedelta(days=6)), [])
        self.assertEqual(self.c.stale([a, b], T0 + dt.timedelta(days=8)), [b])
        self.assertEqual(self.c.stale([a, b], T0 + dt.timedelta(days=31)), [a, b])

    def test_an_outage_caches_nothing_and_pauses_an_hour(self):
        a = "a" * 32

        def down(i):
            raise cat.CatalogUnavailable()

        self.assertEqual(self.c.enrich([a], down, T0), 0)
        self.assertIsNone(self.c.get(a))
        self.assertEqual(self.c.enrich([a], self.hit, T0 + dt.timedelta(minutes=30)), 0)
        self.assertEqual(self.c.enrich([a], self.hit, T0 + dt.timedelta(minutes=61)), 1)

    def test_a_known_publisher_is_never_overwritten_or_expired(self):
        a = "a" * 32
        self.c.save_known_publisher(a, "Typed Pub", "Typed Name")
        self.assertEqual(self.c.stale([a], T0 + dt.timedelta(days=400)), [])
        self.assertEqual(self.c.enrich([a], self.hit, T0), 0)
        self.assertEqual(self.c.expire(), 0)
        self.assertEqual(self.c.get(a)["publisher"], "Typed Pub")
        self.assertEqual([k["id"] for k in self.c.list_known_publishers()], [a])

    def test_a_known_publisher_beats_a_lookup_that_was_already_cached(self):
        a = "a" * 32
        self.c.enrich([a], self.hit, T0)
        self.c.save_known_publisher(a, "Typed Pub")
        self.assertEqual(self.c.get(a)["manual"], True)
        self.assertEqual(self.c.get(a)["name"], "Ext")

    def test_removing_it_sends_the_id_back_to_the_lookup(self):
        a = "a" * 32
        self.c.save_known_publisher(a, "Typed Pub")
        self.assertTrue(self.c.remove_known_publisher(a))
        self.assertFalse(self.c.remove_known_publisher(a))
        self.assertEqual(self.c.stale([a], T0), [a])

    def test_a_bad_id_or_empty_publisher_is_refused(self):
        with self.assertRaises(ValueError):
            self.c.save_known_publisher("bad", "Pub")
        with self.assertRaises(ValueError):
            self.c.save_known_publisher("a" * 32, "  ")

    def test_expire_marks_looked_up_entries_stale(self):
        a = "a" * 32
        self.c.enrich([a], self.hit, T0)
        self.assertEqual(self.c.expire(), 1)
        self.assertEqual(self.c.stale([a], T0), [a])


class Off(unittest.TestCase):
    def test_importing_creates_no_file(self):
        with tempfile.TemporaryDirectory() as t:
            os.environ["OPSCENTER_REPORTS_DB"] = str(Path(t) / "r.db")
            try:
                import importlib

                importlib.reload(lookup_db)
                importlib.reload(d)
                importlib.reload(cat)
                self.assertEqual(list(Path(t).iterdir()), [])
            finally:
                os.environ.pop("OPSCENTER_REPORTS_DB", None)


if __name__ == "__main__":
    unittest.main()
