"""The optional modules at the server: absent unless a setting turns them on (no route, no background task, no file, no import), the device route
authenticates with a key through the provider slot and keeps Retry-After, every admin route is closed until the provider authorises it, the
dashboard routes save, list, run, reset, export and import (a bad definition refuses the whole batch), and a bad provider is a clean 500."""

import json
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import registry as reg  # noqa: E402
from server_test import Served  # noqa: E402

PROVIDER = textwrap.dedent(
    """
    class P:
        def verify_key(self, key, integration_key):
            return {"name": "k1"} if key == "good" else None

        def authorize(self, headers, action, key=None):
            who = headers.get("X-User")
            if who == "admin":
                return "admin"
            if who == "reader" and action.endswith(".read"):
                return "reader"
            return None

        def dashboards(self):
            return {"defaults": [SHIPPED], "version": 1}


    SHIPPED = {"key": "shipped", "title": "Shipped", "panels": [{"title": "P", "stream": "s1", "measure": "rows"}]}
    """
)
ADMIN = {"X-User": "admin"}
READER = {"X-User": "reader"}
STREAM = {
    "key": "browser",
    "name": "Browser",
    "tableName": "Browser",
    "fields": [{"name": "UserName", "kind": "string"}, {"name": "Ext", "kind": "string"}],
}


class Base(Served):
    settings = {}
    provider = True

    def make_registry(self):
        for k in ("OPSCENTER_LOG_INTAKE", "OPSCENTER_REPORTS"):
            os.environ.pop(k, None)
        self.state = self.d / "state"
        os.environ["OPSCENTER_STATE_DIR"] = str(self.state)
        os.environ["LOG_INTAKE_DB"] = str(self.d / "intake.db")
        os.environ["OPSCENTER_REPORTS_DB"] = str(self.d / "reports.db")
        pf = self.d / "provider.py"
        pf.write_text(PROVIDER)
        os.environ.update(self.settings)
        if self.provider:
            for k in self.settings:
                if k.startswith("OPSCENTER_") and not k.endswith("_PROVIDER"):
                    os.environ[k + "_PROVIDER"] = f"{pf}:P"
        import routes

        return routes.build()

    def post(self, path, body, headers=None):
        return self.js("POST", path, body, headers)


class Off(Base):
    def test_with_neither_setting_there_is_no_route_no_task_and_no_file(self):
        paths = {p for _, p in self.registry.paths()}
        self.assertFalse(
            [
                p
                for p in paths
                if p.startswith(
                    ("/api/log-streams", "/api/dashboards", "/api/reports", "/api/log-sink")
                )
            ]
        )
        self.assertEqual(self.js("GET", "/api/log-streams")[0], 404)
        self.assertEqual(self.js("GET", "/api/dashboards")[0], 404)
        self.assertFalse((self.d / "intake.db").exists() or (self.d / "reports.db").exists())
        self.assertFalse((self.state / "dashboards.json").exists())

    def test_the_background_list_is_the_same_as_without_the_modules(self):
        import optional

        probe = reg.Registry()
        self.assertEqual(optional.register(probe), [])
        self.assertEqual((probe.routes, probe.background), ([], []))

    def test_nothing_is_imported_either(self):
        code = (
            f"import sys; sys.path.insert(0, {str(HERE)!r}); import routes; routes.build(); "
            "print([m for m in ('log_intake', 'reports') if m in sys.modules])"
        )
        env = {k: v for k, v in os.environ.items() if not k.startswith("OPSCENTER_")}
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True
        )
        self.assertEqual(out.stdout.strip(), "[]")

    def test_a_setting_of_off_or_zero_is_off(self):
        import optional

        for v in ("0", "false", "off", "no", ""):
            os.environ["OPSCENTER_REPORTS"] = v
            self.assertEqual(optional.register(reg.Registry()), [])
        os.environ.pop("OPSCENTER_REPORTS")


class LogIntake(Base):
    settings = {"OPSCENTER_LOG_INTAKE": "1"}

    def make_stream(self):
        return self.post("/api/log-streams", STREAM, ADMIN)

    def body(self, **kw):
        b = {
            "schemaVersion": "1.0",
            "source": "PC1",
            "snapshotId": "s1",
            "collectedAt": "2026-11-07T10:00:00Z",
            "records": [{"UserName": "alice", "Ext": "Dash"}],
        }
        b.update(kw)
        return b

    def test_the_module_is_on_and_only_it(self):
        paths = {p for _, p in self.registry.paths()}
        self.assertIn("/api/log-sink/checks", paths)
        self.assertFalse([p for p in paths if p.startswith("/api/dashboards")])
        self.assertTrue(self.registry.background)

    def test_every_admin_route_is_closed_without_the_provider_saying_otherwise(self):
        self.assertEqual(self.js("GET", "/api/log-streams")[0], 403)
        self.assertEqual(self.post("/api/log-streams", STREAM)[0], 403)
        self.assertEqual(self.post("/api/log-streams", STREAM, {"X-User": "stranger"})[0], 403)
        self.assertEqual(self.js("GET", "/api/log-streams", headers=READER)[0], 200)
        self.assertEqual(self.post("/api/log-streams", STREAM, READER)[0], 403)

    def test_a_stream_is_created_read_updated_and_deleted(self):
        s, _, b = self.make_stream()
        self.assertEqual((s, b["success"], b["data"]["key"]), (200, True, "browser"))
        self.assertEqual(
            [x["key"] for x in self.js("GET", "/api/log-streams", headers=READER)[2]["data"]],
            ["browser"],
        )
        self.assertEqual(
            self.js("GET", "/api/log-streams/browser", headers=READER)[2]["data"]["table"],
            "Stream_Browser",
        )
        self.assertEqual(self.js("GET", "/api/log-streams/nope-x", headers=READER)[0], 404)
        upd = self.post("/api/log-streams/browser/update", {"retentionDays": 30}, ADMIN)
        self.assertEqual(upd[2]["data"]["retentionDays"], 30)
        self.assertEqual(
            self.post("/api/log-streams/browser/delete", {"confirmTable": "wrong"}, ADMIN)[0], 400
        )
        self.assertEqual(
            self.post("/api/log-streams/browser/delete", {"confirmTable": "Stream_Browser"}, ADMIN)[
                0
            ],
            200,
        )
        self.assertEqual(self.js("GET", "/api/log-streams/browser", headers=READER)[0], 404)

    def test_a_schema_dry_run_applies_nothing(self):
        self.make_stream()
        fields = STREAM["fields"] + [{"name": "Extra1", "kind": "string"}]
        r = self.post("/api/log-streams/browser/schema", {"fields": fields, "dryRun": True}, ADMIN)[
            2
        ]["data"]
        self.assertFalse(r["applied"])
        r = self.post("/api/log-streams/browser/schema", {"fields": fields}, ADMIN)[2]["data"]
        self.assertTrue(r["applied"])

    def test_a_device_post_needs_a_good_key_and_is_stored(self):
        self.make_stream()
        integ = self.js("GET", "/api/log-streams/browser", headers=READER)[2]["data"][
            "integrationKey"
        ]
        self.assertTrue(integ)
        self.assertEqual(self.post("/api/log-streams/browser/ingest", self.body())[0], 401)
        self.assertEqual(
            self.post("/api/log-streams/browser/ingest", self.body(), {"X-Api-Key": "bad"})[0], 401
        )
        s, _, b = self.post("/api/log-streams/browser/ingest", self.body(), {"X-Api-Key": "good"})
        self.assertEqual((s, b["accepted"]), (202, 1))
        from log_intake import current_store

        self.assertEqual(len(current_store.current_rows("browser")), 1)

    def test_the_hourly_limit_answers_429_with_retry_after(self):
        self.make_stream()
        self.post("/api/log-streams/browser/update", {"postsPerDevicePerHour": 1}, ADMIN)
        k = {"X-Api-Key": "good"}
        self.assertEqual(self.post("/api/log-streams/browser/ingest", self.body(), k)[0], 202)
        s, h, _ = self.post("/api/log-streams/browser/ingest", self.body(snapshotId="s2"), k)
        self.assertEqual((s, h.get("Retry-After")), (429, "3600"))

    def test_a_post_to_an_unknown_stream_is_404_and_a_get_is_not_ingest(self):
        self.assertEqual(
            self.post("/api/log-streams/none-x/ingest", self.body(), {"X-Api-Key": "good"})[0], 404
        )
        self.assertEqual(self.js("GET", "/api/log-streams/browser/ingest", headers=READER)[0], 405)

    def test_the_sink_checks_say_there_is_no_sink(self):
        c = self.js("GET", "/api/log-sink/checks", headers=READER)[2]["data"]
        self.assertEqual((c[0]["id"], c[0]["ok"]), ("sink", False))
        self.make_stream()
        self.assertEqual(self.post("/api/log-streams/browser/test-row", {}, ADMIN)[0], 400)


class NoProviderIntake(Base):
    settings = {"OPSCENTER_LOG_INTAKE": "1"}
    provider = False

    def test_no_provider_means_no_key_and_no_admin_works(self):
        self.assertEqual(self.js("GET", "/api/log-streams", headers=ADMIN)[0], 403)
        self.assertEqual(
            self.post("/api/log-streams/browser/ingest", {}, {"X-Api-Key": "good"})[0], 404
        )


class Reports(Base):
    settings = {"OPSCENTER_REPORTS": "1"}

    def dash(self, **kw):
        d = {
            "key": "mine",
            "title": "Mine",
            "panels": [
                {
                    "id": "p",
                    "title": "P",
                    "stream": "browser",
                    "type": "stat",
                    "w": 3,
                    "spec": {"metrics": ["rows"]},
                }
            ],
        }
        d.update(kw)
        return d

    def setUp(self):
        super().setUp()
        from log_intake import stream_store

        stream_store.create_stream(STREAM, "t")

    def test_only_reports_is_on(self):
        paths = {p for _, p in self.registry.paths()}
        self.assertIn("/api/dashboards/run", paths)
        self.assertFalse([p for p in paths if p.startswith("/api/log-streams")])

    def test_closed_without_the_provider_saying_otherwise(self):
        self.assertEqual(self.js("GET", "/api/dashboards")[0], 403)
        self.assertEqual(self.post("/api/dashboards/run", {"key": "shipped"})[0], 403)
        self.assertEqual(self.post("/api/reports/query", {})[0], 403)

    def test_the_shipped_dashboard_is_seeded_and_listed_as_a_default(self):
        rows = self.js("GET", "/api/dashboards", headers=READER)[2]["data"]
        self.assertEqual(
            [(r["key"], r["isDefault"], r["canEdit"]) for r in rows], [("shipped", True, False)]
        )
        self.assertEqual(
            set(rows[0]), {"key", "title", "description", "def", "isDefault", "modified", "canEdit"}
        )
        self.assertTrue(self.js("GET", "/api/dashboards", headers=ADMIN)[2]["data"][0]["canEdit"])

    def test_save_edit_reset_and_delete(self):
        self.assertEqual(
            self.post("/api/dashboards", {"def": self.dash()}, ADMIN)[2]["data"], {"key": "mine"}
        )
        self.assertEqual(
            self.post("/api/dashboards/mine", {"def": self.dash(title="Renamed")}, ADMIN)[0], 200
        )
        row = [
            r
            for r in self.js("GET", "/api/dashboards", headers=READER)[2]["data"]
            if r["key"] == "mine"
        ][0]
        self.assertEqual((row["title"], row["isDefault"]), ("Renamed", False))
        self.post(
            "/api/dashboards/shipped",
            {
                "def": self.dash(
                    key="shipped",
                    title="Edited",
                    panels=[
                        {
                            "id": "p",
                            "title": "P",
                            "stream": "browser",
                            "type": "stat",
                            "w": 3,
                            "measure": "rows",
                        }
                    ],
                )
            },
            ADMIN,
        )
        self.assertEqual(
            self.post("/api/dashboards/shipped/reset", {}, ADMIN)[2]["data"]["title"], "Shipped"
        )
        self.assertEqual(self.post("/api/dashboards/mine/delete", {}, ADMIN)[0], 200)
        self.assertEqual(self.post("/api/dashboards/mine/delete", {}, ADMIN)[0], 404)

    def test_a_bad_definition_is_refused_with_the_reason(self):
        s, _, b = self.post(
            "/api/dashboards",
            {
                "def": self.dash(
                    panels=[
                        {
                            "id": "p",
                            "title": "P",
                            "stream": "nope",
                            "type": "stat",
                            "w": 3,
                            "spec": {"metrics": ["rows"]},
                        }
                    ]
                )
            },
            ADMIN,
        )
        self.assertEqual(s, 400)
        self.assertIn("stream not found", json.dumps(b))
        for key in ("run", "import", "export"):
            self.assertEqual(
                self.post("/api/dashboards", {"def": self.dash(key=key)}, ADMIN)[0], 400
            )
        self.assertEqual(self.post("/api/dashboards", {"def": "x"}, ADMIN)[0], 400)

    def test_a_save_takes_the_whole_definition_as_the_body(self):
        self.assertEqual(self.post("/api/dashboards", self.dash(key="bare"), ADMIN)[0], 200)
        self.assertEqual(self.post("/api/dashboards/bare", self.dash(title="Again"), ADMIN)[0], 200)
        bad_type = self.dash(key="typed")
        bad_type["panels"][0]["type"] = "pie"
        self.assertEqual(self.post("/api/dashboards", bad_type, ADMIN)[0], 400)

    def test_export_is_a_list_and_an_import_reports_each_definition(self):
        self.post("/api/dashboards", {"def": self.dash()}, ADMIN)
        out = self.js("GET", "/api/dashboards/export", headers=READER)[2]["data"]
        self.assertEqual(sorted(d["key"] for d in out), ["mine", "shipped"])
        good, bad = self.dash(key="two"), self.dash(key="three", title="")
        items = [good, bad, self.dash(key="mine")]
        r = self.post("/api/dashboards/import", {"dashboards": items}, ADMIN)[2]["data"]
        self.assertEqual((r["created"], r["updated"]), (["two"], ["mine"]))
        self.assertEqual([(e["index"], e["key"]) for e in r["errors"]], [(1, "three")])
        keys = [x["key"] for x in self.js("GET", "/api/dashboards", headers=READER)[2]["data"]]
        self.assertIn("two", keys)
        self.assertNotIn("three", keys)
        self.assertEqual(self.post("/api/dashboards/import", {"dashboards": "x"}, ADMIN)[0], 400)

    def test_run_by_key_and_by_definition(self):
        from log_intake import current_store, stream_store
        from log_intake import streams as ls

        s = stream_store.get_stream("browser")
        current_store.save_current(
            "browser",
            "PC1",
            "a",
            "2026-11-07T10:00:00Z",
            ls.clean_records(s, [{"UserName": "u", "Ext": "x"}])["rows"],
            "latest",
        )
        self.post("/api/dashboards", {"def": self.dash()}, ADMIN)
        r = self.post("/api/dashboards/run", {"key": "mine", "range": "all"}, READER)[2]["data"]
        self.assertEqual(r["panels"]["p"]["rows"], [[1]])
        r = self.post("/api/dashboards/run", {"def": self.dash(), "selections": {}}, READER)[2][
            "data"
        ]
        self.assertEqual(r["panels"]["p"]["rows"], [[1]])
        self.assertEqual(self.post("/api/dashboards/run", {"key": "ghost"}, READER)[0], 404)
        self.assertEqual(self.post("/api/dashboards/run", {"def": {"panels": "x"}}, READER)[0], 400)

    def test_an_ad_hoc_report_query(self):
        ok = self.post(
            "/api/reports/query", {"stream": "browser", "spec": {"metrics": ["rows"]}}, ADMIN
        )
        self.assertEqual((ok[0], ok[2]["data"]["rows"]), (200, [[0]]))
        self.assertEqual(
            self.post("/api/reports/query", {"stream": "nope-x", "spec": {}}, ADMIN)[0], 404
        )
        self.assertEqual(
            self.post(
                "/api/reports/query",
                {"stream": "browser", "spec": {"groupBy": ["Nope"], "metrics": ["rows"]}},
                ADMIN,
            )[0],
            400,
        )


class BadProvider(Base):
    settings = {"OPSCENTER_REPORTS": "1"}
    provider = False

    def make_registry(self):
        os.environ["OPSCENTER_REPORTS_PROVIDER"] = "no/such/file.py:P"
        os.environ["OPSCENTER_STATE_DIR"] = str(self.d / "state")
        os.environ["OPSCENTER_REPORTS"] = "1"
        import routes

        try:
            return routes.build()
        except Exception as e:  # noqa: BLE001
            self.error = e
            return reg.Registry()

    def test_a_missing_provider_file_is_a_clean_refusal_at_start(self):
        self.assertEqual(self.error.status, 500)
        self.assertIn("not found", str(self.error))
        self.assertNotIn("/", str(self.error))


if __name__ == "__main__":
    unittest.main()
