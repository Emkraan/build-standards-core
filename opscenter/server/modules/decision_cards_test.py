import base64
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import decision_cards as dc  # noqa: E402

HEAD = "c" * 40
REPLY = "Triaged: the flagged line is a test fixture and never runs in production."


class Closed(Exception):
    merged = False


class Fake:
    """A fake code host (gh) plus the cfg the module wants."""

    def __init__(self, d, login="owner", verdict=None, decision=None, reason=""):
        self.calls, self.log, self.dropped = [], [], 0
        self.login = login
        self.verdict = (
            verdict
            if verdict is not None
            else {"head_sha": HEAD, "counts": {"high": 2, "blocking": 1}}
        )
        self.dir = Path(d)
        options = [
            {"id": "a", "action": "fix", "label": "Fix it", "effect": "start a fix session"},
            {
                "id": "b",
                "action": "override",
                "label": "Override",
                "effect": "post the reply",
                "reply": REPLY,
            },
            {"id": "c", "action": "hold", "label": "Hold"},
        ]
        dec = decision or {"question": "Which way?", "options": options}
        lane = {"fix": {"7": {"gave_up": {"head": HEAD, "decision": dec}}}}
        if reason:
            lane["prs"] = {"7": {"head": HEAD, "reason": reason}}
        self.lane_state = self.dir / "own-pr-merge.json"
        self.lane_state.write_text(json.dumps(lane))

    def gh(self, args, raw=False):
        self.calls.append(args)
        return ""

    def cfg(self):
        return {
            "repo": "o/r",
            "self_login": "owner",
            "lane_state": self.lane_state,
            "gh": self.gh,
            "verify_head": lambda pr, head: {"user": {"login": self.login}},
            "closed_exc": Closed,
            "log": self.log.append,
            "drop_cache": lambda: setattr(self, "dropped", self.dropped + 1),
            "review_verdict": lambda pr: self.verdict,
        }


def pay(option, **kw):
    return dict({"pr": 7, "head_sha": HEAD, "option": option}, **kw)


class Pure(unittest.TestCase):
    def test_marker_ids_orders_highs_then_blocking_and_dedupes_extras(self):
        self.assertEqual(dc.marker_ids({"high": 2, "blocking": 1}), ["H1", "H2", "B1"])
        self.assertEqual(dc.marker_ids({"high": 1}, ["h1", "B3", "x9"]), ["H1", "B3"])
        self.assertEqual(dc.marker_ids(None), [])

    def test_triage_marker(self):
        self.assertEqual(dc.triage_marker("abc", ["H1", "B1"]), "<!-- triage:abc H1 B1 -->")

    def test_review_verdict_takes_the_newest_blob(self):
        def blob(sha):
            data = base64.b64encode(json.dumps({"head_sha": sha, "counts": {}}).encode()).decode()
            return json.dumps({"body": f"{dc.DATA_PREFIX}{data}{dc.DATA_SUFFIX}"})

        out = "\n".join([blob("1" * 40), json.dumps({"body": "chatter"}), "", blob("2" * 40)])
        self.assertEqual(dc.review_head(lambda *a, **k: out, "o/r", 7), "2" * 40)
        self.assertIsNone(dc.review_head(lambda *a, **k: "", "o/r", 7))

    def test_write_side_is_private_and_upserts(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "side.json"
            dc.write_side(p, 7, {"head": HEAD})
            dc.write_side(p, 8, {"head": OTHER})
            self.assertEqual(oct(p.stat().st_mode & 0o777), "0o600")
            self.assertEqual(sorted(json.loads(p.read_text())["prs"]), ["7", "8"])

    def test_covered_rules_cover_only_what_the_card_names(self):
        lane = {
            "prs": {
                "7": {
                    "head": HEAD,
                    "reason": "needs me: ai-review-override, rbac-grant, plan-destroy",
                }
            }
        }
        dec = {"question": "Also grant rbac-grant?"}
        covered, rest = dc.covered_rules(
            lane, 7, HEAD, dec, {"effect": "", "reply": "plan-destroy is fine"}
        )
        self.assertEqual(covered, ["ai-review-override", "rbac-grant"])
        self.assertEqual(rest, ["plan-destroy"])  # never signed off by a click


OTHER = "d" * 40


class Decide(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.f = Fake(self._d.name)

    def tearDown(self):
        self._d.cleanup()

    def test_input_is_validated(self):
        for bad in ({"pr": "x", "head_sha": HEAD}, {"pr": 7, "head_sha": "abc"}):
            with self.assertRaises(dc.DecisionError) as cm:
                dc.decide(self.f.cfg(), bad)
            self.assertEqual(cm.exception.code, 400)

    def test_someone_elses_pr_is_refused(self):
        self.f.login = "other"
        with self.assertRaises(dc.DecisionError) as cm:
            dc.decide(self.f.cfg(), pay("a"))
        self.assertEqual(cm.exception.code, 403)

    def test_a_closed_pr_is_reported_not_acted_on(self):
        cfg = self.f.cfg()

        def closed(pr, head):
            raise Closed()

        cfg["verify_head"] = closed
        r = dc.decide(cfg, pay("a"))
        self.assertTrue(r["already"])
        self.assertEqual(self.f.calls, [])

    def test_no_open_decision_for_another_head_or_unknown_option(self):
        with self.assertRaises(dc.DecisionError):
            dc.decide(self.f.cfg(), dict(pay("a"), head_sha=OTHER))
        with self.assertRaises(dc.DecisionError) as cm:
            dc.decide(self.f.cfg(), pay("zzz"))
        self.assertEqual(cm.exception.code, 409)

    def test_fix_records_a_direction_and_calls_nothing(self):
        r = dc.decide(self.f.cfg(), pay("a"))
        self.assertTrue(r["pending"])
        self.assertEqual(self.f.calls, [])
        side = json.loads((self.f.dir / "own-pr-directions.json").read_text())
        self.assertEqual(side["prs"]["7"]["option_id"], "a")
        self.assertEqual(self.f.log[0]["action"], "fix")
        self.assertEqual(self.f.dropped, 1)

    def test_hold_adds_the_label(self):
        dc.decide(self.f.cfg(), pay("c"))
        self.assertIn("labels[]=do-not-merge", self.f.calls[0])

    def test_override_labels_comments_with_the_marker_and_records_the_signoff(self):
        r = dc.decide(self.f.cfg(), pay("b"))
        labels, comment = self.f.calls
        self.assertIn(f"labels[]={dc.OVERRIDE_LABEL}", labels)
        body = comment[-1]
        self.assertIn(REPLY, body)
        self.assertIn(f"<!-- triage:{HEAD} H1 H2 B1 -->", body)
        side = json.loads((self.f.dir / "own-pr-signoffs.json").read_text())
        self.assertEqual(side["prs"]["7"]["rules"], [dc.OVERRIDE_LABEL])
        self.assertIn("lane merges it", r["done"][-1])

    def test_override_lists_held_rules_it_does_not_cover(self):
        self.f = Fake(self._d.name, reason="needs me: ai-review-override, rbac-grant")
        r = dc.decide(self.f.cfg(), pay("b"))
        self.assertIn("rbac-grant", r["done"][-1])

    def test_override_needs_a_review_on_this_head_with_findings(self):
        self.f.verdict = {"head_sha": OTHER, "counts": {"high": 1}}
        with self.assertRaises(dc.DecisionError):
            dc.decide(self.f.cfg(), pay("b"))
        self.f.verdict = {"head_sha": HEAD, "counts": {}}
        with self.assertRaises(dc.DecisionError):
            dc.decide(self.f.cfg(), pay("b"))
        self.assertEqual(self.f.calls, [])

    def test_an_unsafe_reply_is_never_posted(self):
        for reply in (
            "too short",
            "Written by the assistant, see the review here ok",
            REPLY + "; more",
            REPLY + " caf\u00e9",
        ):
            self._d.cleanup()
            self._d = tempfile.TemporaryDirectory()
            dec = {
                "question": "q",
                "options": [{"id": "b", "action": "override", "label": "O", "reply": reply}],
            }
            f = Fake(self._d.name, decision=dec)
            with self.assertRaises(dc.DecisionError, msg=reply):
                dc.decide(f.cfg(), pay("b"))
            self.assertEqual(f.calls, [])

    def test_unknown_action_is_refused(self):
        dec = {"question": "q", "options": [{"id": "x", "action": "merge", "label": "M"}]}
        f = Fake(self._d.name, decision=dec)
        with self.assertRaises(dc.DecisionError):
            dc.decide(f.cfg(), pay("x"))

    def test_unreadable_lane_state_is_503(self):
        self.f.lane_state.write_text("{nope")
        with self.assertRaises(dc.DecisionError) as cm:
            dc.decide(self.f.cfg(), pay("a"))
        self.assertEqual(cm.exception.code, 503)


if __name__ == "__main__":
    os.environ.setdefault("TZ", "UTC")
    unittest.main()
