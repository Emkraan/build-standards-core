"""The routing API: read the rules with hit counts, preview a rule, add (idempotent), disable and delete."""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "engine"))


class RoutingApi(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="routing-api-test-"))
        self.state = self.d / "state"
        (self.state / "dashboard").mkdir(parents=True)
        self._env = dict(os.environ)
        self._mods = {m: sys.modules.get(m) for m in ("collect", "routing_api", "paths")}
        os.environ.update(
            OPSCENTER_ROOT=str(self.d),
            OPSCENTER_STATE_DIR=str(self.state),
            OPSCENTER_AGENT_HOME=str(self.d / "agent"),
            OPSCENTER_COLLECT_CONFIG=str(self.d / "none.json"),
        )
        os.environ.pop("OPSCENTER_REFRESH_CMD", None)
        import routing

        self.R = routing
        self._rules = (routing.RULES_PATH, routing.LOCK_PATH)
        routing.RULES_PATH = self.state / "dashboard" / "ac-routing.json"
        routing.LOCK_PATH = routing.RULES_PATH.parent / ".ac-routing.lock"
        seed = HERE.parent.parent / "engine" / "fixtures" / "routing-seed.json"
        shutil.copy(seed, routing.RULES_PATH)
        for m in self._mods:
            sys.modules.pop(m, None)
        import routing_api

        self.api = routing_api

    def tearDown(self):
        self.R.RULES_PATH, self.R.LOCK_PATH = self._rules
        for m, v in self._mods.items():
            if v is None:
                sys.modules.pop(m, None)
            else:
                sys.modules[m] = v
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self.d, ignore_errors=True)

    def test_get_lists_rules_sources_defaults_and_hit_counts(self):
        (self.state / "dashboard" / "ac-routing-report.json").write_text(
            json.dumps(
                {"routed_away": [{"rule": "seed-doc-gap-candidates"}], "items_routed_away": []}
            )
        )
        got = self.api.get()
        by = {r["id"]: r for r in got["rules"]}
        self.assertEqual(by["seed-doc-gap-candidates"]["hits"], 1)
        self.assertIn("mail.direct", got["sources"])
        self.assertIsNone(got["error"])

    def test_a_broken_rules_file_is_reported_not_raised(self):
        self.R.RULES_PATH.write_text("{not json")
        got = self.api.get()
        self.assertEqual(got["rules"], [])
        self.assertIn("not JSON", got["error"])

    def test_add_is_idempotent_then_disable_and_delete(self):
        r1 = self.api.add(
            {
                "match": {"actor": "Pat Example"},
                "route": "elsewhere",
                "where": "Service desk",
                "from_fp": "ac_1",
            }
        )
        r2 = self.api.add(
            {"match": {"actor": "Pat Example"}, "route": "elsewhere", "where": "Service desk"}
        )
        self.assertEqual((r1["already"], r2["already"]), (False, True))
        rid = r1["rule"]["id"]
        self.assertTrue(self.api.disable({"id": rid, "disabled": True})["rule"]["disabled"])
        self.assertEqual(self.api.delete({"id": rid}), {"ok": True, "already": False})
        self.assertEqual(self.api.delete({"id": rid})["already"], True)

    def test_validation_errors_are_raised_for_the_server_to_map(self):
        with self.assertRaises(self.R.RoutingError):
            self.api.add({"match": "nope", "route": "nowhere"})
        with self.assertRaises(self.R.RoutingError):
            self.api.add({"match": {"actor": "x"}, "route": "elsewhere"})  # elsewhere needs a where

    def test_preview_counts_candidates_and_items(self):
        self.api._cache["cands"] = [
            {
                "cid": "a",
                "source": "mail.other",
                "actor": "Pat Example",
                "actor_role": "other",
                "addressed": "none",
                "title": "t",
                "text": "",
            }
        ]
        (self.state / "dashboard" / "action-center.json").write_text(
            json.dumps({"items": [{"key": "k", "title": "x"}]})
        )
        self.api._cache["at"] = __import__("time").time()
        out = self.api.preview({"match": {"actor": "Pat Example"}, "route": "nowhere"})
        self.assertEqual((out["candidate_count"], out["item_count"]), (1, 0))


if __name__ == "__main__":
    unittest.main()
