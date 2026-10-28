"""Model accounts: the null provider, the provider loader and its refusal of a pool read, shaping, routing and cooldown, the last good copy,
spend history, the token ledger, and the fallback watch. A fake provider stands in for the consumer's."""

import json
import os
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

import model_accounts as ma
import model_fallback as mf

PROVIDER = textwrap.dedent(
    """
    import json, os
    from pathlib import Path
    import model_accounts as ma

    class Fake:
        needs_credential_pool_read = NEEDS
        calls = []

        def credentials(self):
            return json.loads(Path(os.environ["FAKE_CREDS"]).read_text())

        def read_usage(self, cred_id):
            Fake.calls.append(cred_id)
            data = json.loads(Path(os.environ["FAKE_USAGE"]).read_text())[cred_id]
            if data.get("raise"):
                raise ma.ProviderUnavailable(data["raise"])
            return data

        def stale_host(self):
            return {"pid": 1}
    """
)

SEAT_USAGE = {
    "billing_model": "seat",
    "kind": "team",
    "kind_label": "Team",
    "org": "org-b",
    "limits": [
        {"kind": "session", "percent": 40, "resets_at": "2099-01-01T05:00:00Z"},
        {"kind": "weekly_all", "percent": 20, "resets_at": "2099-01-07T00:00:00Z"},
    ],
    "spend": None,
}
USAGE_USAGE = {
    "billing_model": "usage",
    "kind": "enterprise",
    "kind_label": "Enterprise",
    "org": "org-a",
    "limits": [],
    "spend": {"enabled": True, "used_usd": 12.5, "limit_usd": 100, "percent": 12},
}


class Base(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="model-accounts-"))
        self._env = dict(os.environ)
        os.environ.update(
            OPSCENTER_STATE_DIR=str(self.d / "state"),
            FAKE_CREDS=str(self.d / "creds.json"),
            FAKE_USAGE=str(self.d / "usage.json"),
            LLMFB_STATE=str(self.d / "fb.json"),
        )
        for k in (
            "OPSCENTER_MODEL_ACCOUNTS_PROVIDER",
            "OPSCENTER_MODEL_ACCOUNTS_ALLOW_POOL_READ",
            "OPSCENTER_MODEL_LEDGER",
            "OPSCENTER_MODEL_RATES",
            "LLMFB_LEDGER",
            "LLMFB_TEAM_JSON",
            "LLMFB_NOW",
            "OPSCENTER_DISPLAY_UTC_OFFSET_HOURS",
        ):
            os.environ.pop(k, None)
        ma.reset()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        ma.reset()

    def provider_file(self, needs=False):
        p = self.d / "provider.py"
        p.write_text(PROVIDER.replace("NEEDS", str(needs)))
        os.environ["OPSCENTER_MODEL_ACCOUNTS_PROVIDER"] = f"{p}:Fake"
        return p

    def set(self, creds, usage):
        (self.d / "creds.json").write_text(json.dumps(creds))
        (self.d / "usage.json").write_text(json.dumps(usage))

    def ledger(self, rows):
        p = self.d / "ledger.jsonl"
        with p.open("a") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        os.environ["OPSCENTER_MODEL_LEDGER"] = str(p)
        return p


class Loading(Base):
    def test_no_provider_is_the_null_provider_and_the_page_is_empty(self):
        doc = ma.list_accounts()
        self.assertEqual((doc["accounts"], doc["ledger"]), ([], None))
        self.assertEqual(ma.fallback_order(), [])
        self.assertFalse(ma.order_get()["writable"])
        self.assertEqual(mf.get()["active"], None)

    def test_a_provider_that_declares_a_credential_pool_read_is_refused_unless_enabled(self):
        self.provider_file(needs=True)
        self.set([], {})
        with self.assertRaises(ma.ProviderRefused) as cm:
            ma.list_accounts()
        self.assertEqual(cm.exception.status, 403)
        self.assertIn("ALLOW_POOL_READ", str(cm.exception))
        os.environ["OPSCENTER_MODEL_ACCOUNTS_ALLOW_POOL_READ"] = "0"
        with self.assertRaises(ma.ProviderRefused):
            ma.list_accounts()
        os.environ["OPSCENTER_MODEL_ACCOUNTS_ALLOW_POOL_READ"] = "1"
        self.assertEqual(ma.list_accounts()["accounts"], [])

    def test_a_provider_without_the_declaration_loads(self):
        self.provider_file(needs=False)
        self.set([], {})
        self.assertEqual(ma.list_accounts()["accounts"], [])

    def test_bad_specs_are_refused_with_a_reason_that_names_no_path(self):
        for spec in ("nocolon", str(self.d / "missing.py") + ":X", str(self.d) + ":X"):
            os.environ["OPSCENTER_MODEL_ACCOUNTS_PROVIDER"] = spec
            ma.reset()
            with self.assertRaises(ma.ProviderRefused) as cm:
                ma.provider()
            self.assertNotIn(str(self.d), str(cm.exception))
        bad = self.d / "bad.py"
        bad.write_text("class X:\n    pass\n")
        os.environ["OPSCENTER_MODEL_ACCOUNTS_PROVIDER"] = f"{bad}:X"
        ma.reset()
        with self.assertRaises(ma.ProviderRefused):
            ma.provider()

    def test_the_core_modules_make_no_network_call_and_read_no_credential_store(self):
        for name in ("model_accounts.py", "model_fallback.py"):
            src = (Path(__file__).parent / name).read_text().lower()
            for word in (
                "urllib",
                "http.client",
                "socket",
                "requests",
                "bearer",
                "auth.json",
                "oauth",
                "user-agent",
            ):
                self.assertNotIn(word, src, f"{name} mentions {word}")


class Accounts(Base):
    def setUp(self):
        super().setUp()
        self.provider_file()

    def two(self, usage=None, **over):
        creds = [
            {"cred_id": "b", "credential": "seat", "priority": 1},
            {"cred_id": "a", "credential": "metered", "priority": 0},
        ]
        creds[1].update(over)
        self.set(creds, usage or {"a": USAGE_USAGE, "b": SEAT_USAGE})

    def test_the_document_is_shaped_for_the_page_and_sorted_by_priority(self):
        self.two()
        doc = ma.list_accounts()
        a, b = doc["accounts"]
        self.assertEqual((a["credential"], b["credential"]), ("metered", "seat"))
        self.assertEqual(
            (a["billing_model"], a["kind_label"], a["org"]), ("usage", "Enterprise", "org-a")
        )
        self.assertEqual(a["spend"]["used_usd"], 12.5)
        self.assertEqual(a["spend"]["currency"], "USD")
        self.assertEqual(b["limits"][0]["label"], "Current session")
        self.assertEqual(b["limits"][0]["window_s"], 18000)
        for key in (
            "cred_id",
            "tokens",
            "routing",
            "cooling_down",
            "pool_status",
            "fetched_utc",
            "stale",
            "error",
        ):
            self.assertIn(key, a)
        self.assertEqual(
            doc["ledger"],
            {
                "since_utc": None,
                "rows": 0,
                "unattributed_d7": {"calls": 0, "total": 0, "aux_calls": 0},
            },
        )

    def test_the_lowest_priority_account_that_is_not_cooling_routes(self):
        self.two()
        self.assertEqual([a["routing"] for a in ma.list_accounts()["accounts"]], [True, False])
        self.assertEqual(
            ma.fallback_order()[0],
            {"cred_id": "a", "priority": 0, "routing": True, "cooling_down": False},
        )

    def test_an_exhausted_status_with_a_future_reset_cools_and_a_past_one_does_not(self):
        future = time.time() + 3600
        self.two(status="exhausted", status_reset_at=future)
        a, b = ma.list_accounts()["accounts"]
        self.assertEqual((a["cooling_down"], a["routing"], b["routing"]), (True, False, True))
        self.assertTrue(a["pool_reset_at"])
        ma.reset()
        self.two(status="exhausted", status_reset_at=time.time() - 10)
        self.assertFalse(ma.list_accounts()["accounts"][0]["cooling_down"])

    def test_an_exhausted_status_with_no_reset_is_assumed_to_last_an_hour(self):
        self.two(status="exhausted", status_at=time.time() - 60)
        self.assertTrue(ma.list_accounts()["accounts"][0]["cooling_down"])
        ma.reset()
        self.two(status="exhausted", status_at=time.time() - 7200)
        self.assertFalse(ma.list_accounts()["accounts"][0]["cooling_down"])

    def test_a_limit_at_100_percent_with_a_future_reset_cools_the_account(self):
        full = dict(
            SEAT_USAGE,
            limits=[{"kind": "weekly_all", "percent": 100, "resets_at": "2099-01-07T00:00:00Z"}],
        )
        self.two({"a": USAGE_USAGE, "b": full})
        self.set(
            [
                {"cred_id": "b", "credential": "seat", "priority": 0},
                {"cred_id": "a", "credential": "metered", "priority": 1},
            ],
            {"a": USAGE_USAGE, "b": full},
        )
        b, a = ma.list_accounts()["accounts"]
        self.assertEqual((b["cooling_down"], b["routing"], a["routing"]), (True, False, True))

    def test_an_account_with_no_reading_and_no_last_copy_shows_the_error_and_does_not_route(self):
        self.two({"a": {"raise": "token rejected"}, "b": SEAT_USAGE})
        a, b = ma.list_accounts()["accounts"]
        self.assertEqual(
            (a["error"], a["stale"], a["routing"], b["routing"]),
            ("token rejected", None, False, True),
        )

    def test_the_last_good_reading_is_served_stale_and_the_kind_survives(self):
        self.two()
        ma.list_accounts()
        ma.reset()
        self.two({"a": {"raise": "offline"}, "b": SEAT_USAGE})
        a = ma.list_accounts()["accounts"][0]
        self.assertEqual(
            (a["stale"], a["error"], a["org"], a["spend"]["used_usd"]),
            ("offline", None, "org-a", 12.5),
        )
        self.assertTrue(a["routing"])
        self.assertEqual(ma.account_kinds(), {"a": "usage", "b": "seat"})

    def test_an_unavailable_credential_never_calls_the_provider_and_a_provider_crash_is_contained(
        self,
    ):
        self.two(unavailable="no live read for this entry")
        a = ma.list_accounts()["accounts"][0]
        self.assertEqual(a["error"], "no live read for this entry")
        ma.reset()
        self.two()
        (self.d / "usage.json").write_text("not json")
        a = ma.list_accounts()["accounts"][0]
        self.assertIn("usage lookup failed", a["error"])

    def test_reads_are_cached_within_the_ttl(self):
        self.two()
        ma.list_accounts()
        ma.list_accounts()
        mod = ma.provider().__class__
        self.assertEqual(sorted(mod.calls), ["a", "b"])

    def test_fallback_order_write_is_unsupported_without_a_setter(self):
        self.two()
        with self.assertRaises(RuntimeError) as cm:
            ma.order_set({"ids": ["a"]})
        self.assertEqual(cm.exception.status, 501)
        with self.assertRaises(ValueError):
            ma.order_set({"ids": "a"})


class Spend(Base):
    def snap(self, rows):
        p = ma._snapshots_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            "".join(json.dumps({"ts": t, "cred_id": "a", "used_usd": u}) + "\n" for t, u in rows)
        )

    def test_history_has_daily_charges_a_partial_first_day_and_a_rollover(self):
        now = time.time()
        d = 86400
        base = now - 4 * d
        self.snap([(base, 10.0), (base + d, 14.0), (base + 2 * d, 20.0), (base + 3 * d, 3.0)])
        h = ma.spend_history("a", now=now)
        self.assertEqual([x["usd"] for x in h["daily"]], [0.0, 4.0, 6.0, 3.0])
        self.assertTrue(h["daily"][0]["partial"])
        self.assertEqual(h["rate_basis_days"], 3.0)
        self.assertEqual(h["rate_per_day"], round((4.0 + 6.0 + 3.0) / 3.0, 2))

    def test_no_snapshots_and_a_short_history_give_no_rate(self):
        self.assertEqual(ma.spend_history("a")["daily"], [])
        now = time.time()
        self.snap([(now - 3600, 1.0), (now, 2.0)])
        self.assertIsNone(ma.spend_history("a", now=now)["rate_per_day"])

    def test_a_snapshot_is_written_when_the_figure_moves_or_hourly_only(self):
        ma._snapshot_spend("a", 5.0, 1000.0)
        ma._snapshot_spend("a", 5.0, 1100.0)
        ma._snapshot_spend("a", 6.0, 1200.0)
        ma._snapshot_spend("a", 6.0, 1200.0 + ma.SNAPSHOT_EVERY_S + 1)
        self.assertEqual(len(ma._snapshots("a")), 3)

    def test_the_day_boundary_follows_the_display_offset(self):
        ts = 1_800_000_000.0  # 2027-01-15 08:00:00 UTC
        self.snap([(ts, 1.0)])
        self.assertEqual(ma.spend_history("a", now=ts)["daily"][0]["date"], "2027-01-15")
        os.environ["OPSCENTER_DISPLAY_UTC_OFFSET_HOURS"] = "-10"
        self.assertEqual(ma.spend_history("a", now=ts)["daily"][0]["date"], "2027-01-14")


class Ledger(Base):
    def test_windows_sum_the_ledger_and_unattributed_rows_are_counted_by_the_week(self):
        self.provider_file()
        usage = {"a": dict(USAGE_USAGE), "b": SEAT_USAGE}
        reset = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600))
        usage["b"] = dict(
            SEAT_USAGE, limits=[{"kind": "session", "percent": 5, "resets_at": reset}]
        )
        self.set([{"cred_id": "a", "priority": 0}, {"cred_id": "b", "priority": 1}], usage)
        now = time.time()
        self.ledger(
            [
                {
                    "ts": now - 60,
                    "cred_id": "b",
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cache_read_tokens": 1,
                    "cache_write_tokens": 2,
                },
                {"ts": now - 10 * 86400, "cred_id": "b", "input_tokens": 100},
                {"ts": now - 30, "cred_id": "zzz", "input_tokens": 7, "kind": "aux"},
            ]
        )
        doc = ma.list_accounts()
        b = doc["accounts"][1]
        self.assertEqual(b["tokens"]["d7"]["total"], 18)
        self.assertEqual(b["tokens"]["session"]["calls"], 1)
        self.assertEqual(b["tokens"]["month"]["calls"] >= 1, True)
        self.assertEqual(doc["ledger"]["unattributed_d7"], {"calls": 1, "total": 7, "aux_calls": 1})
        self.assertEqual(doc["ledger"]["rows"], 3)
        self.assertIn("spend_history", doc["accounts"][0])
        self.assertNotIn("spend_history", b)

    def test_a_half_written_last_line_waits_for_the_next_pass_and_a_truncated_file_restarts(self):
        p = self.ledger([{"ts": time.time(), "cred_id": "a", "input_tokens": 1}])
        with p.open("a") as fh:
            fh.write('{"ts": 1')
        self.assertEqual(len(ma._ledger_rows()), 1)
        with p.open("a") as fh:
            fh.write(f'{time.time()}, "cred_id": "a"' + "}\n")
        self.assertEqual(len(ma._ledger_rows()), 2)
        p.write_text(json.dumps({"ts": time.time(), "cred_id": "a"}) + "\n")
        self.assertEqual(len(ma._ledger_rows()), 1)


class Fallback(Base):
    NOW = 2_000_000_000.0

    def setUp(self):
        super().setUp()
        os.environ["LLMFB_NOW"] = str(self.NOW)
        os.environ["LLMFB_LEDGER"] = str(self.d / "fb-ledger.jsonl")
        ma._kinds_file().parent.mkdir(parents=True, exist_ok=True)
        ma._kinds_file().write_text(
            json.dumps({"m": {"billing_model": "usage"}, "s": {"billing_model": "seat"}})
        )
        mf.run()  # first run: checkpoint starts now

    def calls(self, n, cred="m", at=None, model="alpha-large"):
        p = self.d / "fb-ledger.jsonl"
        with p.open("a") as fh:
            for i in range(n):
                fh.write(
                    json.dumps(
                        {
                            "ts": (at or self.NOW) + 10 + i,
                            "cred_id": cred,
                            "model": model,
                            "input_tokens": 1_000_000,
                            "output_tokens": 0,
                            "session_id": "s1",
                            "platform": "chat",
                        }
                    )
                    + "\n"
                )

    def run_at(self, delta, team):
        os.environ["LLMFB_NOW"] = str(self.NOW + delta)
        os.environ["LLMFB_TEAM_JSON"] = json.dumps(team)
        return mf.run()

    ROOM = {"session_pct": 10, "weekly_pct": 20, "headroom": True, "error": None}
    TIGHT = {"session_pct": 95, "weekly_pct": 20, "headroom": False, "error": None}

    def test_a_usage_billed_call_with_headroom_opens_an_incident_once(self):
        rates = self.d / "rates.json"
        rates.write_text(json.dumps({"default": [1, 0, 0, 0], "match": {"large": [10, 0, 0, 0]}}))
        os.environ["OPSCENTER_MODEL_RATES"] = str(rates)
        self.calls(2)
        msg = self.run_at(60, self.ROOM)
        self.assertIn("2 call(s)", msg)
        self.assertIn("about $20.00", msg)
        act = mf.get()["active"]
        self.assertEqual(
            (act["calls"], act["est_usd"], act["sessions"]["s1"]["calls"]), (2, 20.0, 2)
        )
        self.calls(1, at=self.NOW + 100)
        self.assertEqual(self.run_at(200, self.ROOM), "")
        self.assertEqual(mf.get()["active"]["calls"], 3)

    def test_no_estimate_without_a_rates_file(self):
        self.calls(1)
        self.run_at(60, self.ROOM)
        self.assertEqual(mf.get()["active"]["est_usd"], 0.0)

    def test_no_incident_when_the_seat_plan_is_tight_or_the_call_is_not_usage_billed(self):
        self.calls(2)
        self.calls(2, cred="s", at=self.NOW + 50)
        self.assertEqual(self.run_at(60, self.TIGHT), "")
        self.assertIsNone(mf.get()["active"])
        self.calls(2, cred="s", at=self.NOW + 100)
        self.assertEqual(self.run_at(200, self.ROOM), "")
        self.assertIsNone(mf.get()["active"])

    def test_an_unknown_seat_plan_state_holds_the_checkpoint_so_the_calls_are_judged_later(self):
        self.calls(1)
        self.assertEqual(
            self.run_at(
                60, {"session_pct": None, "weekly_pct": None, "headroom": None, "error": "x"}
            ),
            "",
        )
        self.assertIn("1 call(s)", self.run_at(120, self.ROOM))
        self.assertEqual(mf.get()["active"]["calls"], 1)

    def test_an_incident_closes_after_the_quiet_period_into_the_history(self):
        self.calls(1)
        self.run_at(60, self.ROOM)
        self.run_at(60 + mf.QUIET_S + 100, self.ROOM)
        st = mf.get()
        self.assertIsNone(st["active"])
        self.assertEqual(len(st["history"]), 1)
        self.assertIn("closed_utc", st["history"][0])

    def test_team_usage_reads_the_first_seat_account_and_judges_headroom(self):
        Base.provider_file(self)
        os.environ.pop("LLMFB_TEAM_JSON", None)
        tight = dict(
            SEAT_USAGE,
            limits=[{"kind": "session", "percent": 95, "resets_at": "2099-01-01T00:00:00Z"}],
        )
        self.set(
            [{"cred_id": "a", "priority": 0}, {"cred_id": "b", "priority": 1}],
            {"a": USAGE_USAGE, "b": tight},
        )
        t = mf.team_usage()
        self.assertEqual((t["headroom"], t["session_pct"]), (False, 95))
        ma.reset()
        self.set(
            [{"cred_id": "a", "priority": 0}, {"cred_id": "b", "priority": 1}],
            {"a": USAGE_USAGE, "b": SEAT_USAGE},
        )
        self.assertTrue(mf.team_usage()["headroom"])
        ma.reset()
        self.set([{"cred_id": "a", "priority": 0}], {"a": USAGE_USAGE})
        self.assertEqual(mf.team_usage()["error"], "no seat plan account")
        os.environ["OPSCENTER_MODEL_ACCOUNTS_PROVIDER"] = "nocolon"
        ma.reset()
        self.assertIn("provider must be", mf.team_usage()["error"])

    def test_the_stale_host_comes_from_the_provider_when_it_has_one(self):
        self.assertIsNone(mf.get()["stale_host"])
        Base.provider_file(self)
        self.set([], {})
        self.assertEqual(mf.get()["stale_host"], {"pid": 1})


if __name__ == "__main__":
    unittest.main()
