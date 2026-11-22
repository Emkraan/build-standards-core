import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import registry as reg  # noqa: E402


class Lib:
    """A fake library: a draft text per document, a version that follows the text, and what got published."""

    def __init__(self):
        self.text = {"d1": "first draft", "d2": "other"}
        self.published = []
        self.suggested = []
        self.allow = True

    def authorize(self, headers, action, key=None):
        return "me" if self.allow else None

    def queue(self):
        return [
            {"id": "d1", "title": "Runbook", "source": "meeting"},
            {"id": "d2", "title": "Gap", "source": "gap"},
            {"id": "bad id"},
        ]

    def draft(self, i):
        return {"version": f"v{len(self.text[i])}", "text": self.text[i]}

    def preview(self, i):
        return {"version": f"v{len(self.text[i])}", "text": self.text[i]}

    def suggest(self, i, text):
        self.suggested.append((i, text))
        return {"ok": True}

    def publish(self, i, version):
        self.published.append((i, version))
        return {"ok": True, "detail": "in the library"}


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="docs-"))
        self._env = dict(os.environ)
        os.environ["OPSCENTER_STATE_DIR"] = str(self.d / "state")
        for m in ("stores", "doc_pipeline"):
            sys.modules.pop(m, None)
        import doc_pipeline

        self.dp = importlib.reload(doc_pipeline)
        self.lib = Lib()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)

    def state(self, i):
        return next(x for x in self.dp.read(self.lib)["docs"] if x["id"] == i)["state"]

    def drafted(self, i="d1"):
        return self.dp.draft(self.lib, {"id": i})["version"]

    def test_the_queue_lists_valid_documents_as_queued_and_a_failing_source_is_an_error(self):
        out = self.dp.read(self.lib)
        self.assertEqual(
            [(x["id"], x["state"], x["source"]) for x in out["docs"]],
            [("d1", "queued", "meeting"), ("d2", "queued", "gap")],
        )

        class Broken(Lib):
            def queue(self):
                raise RuntimeError("down")

        bad = self.dp.read(Broken())
        self.assertTrue(bad["error"])
        self.assertEqual(bad["docs"], [])

    def test_draft_approve_publish_is_the_only_road_to_the_library(self):
        v = self.drafted()
        with self.assertRaises(self.dp.Refused):
            self.dp.publish(self.lib, {"id": "d1", "version": v, "confirm": True})
        self.dp.decide({"id": "d1", "decision": "approve", "version": v, "confirm": True})
        self.assertEqual(self.state("d1"), "approved")
        out = self.dp.publish(self.lib, {"id": "d1", "version": v, "confirm": True})
        self.assertTrue(out["ok"])
        self.assertEqual(self.lib.published, [("d1", v)])
        self.assertEqual(self.state("d1"), "published")

    def test_a_draft_that_changed_after_the_approval_is_never_published(self):
        v = self.drafted()
        self.dp.decide({"id": "d1", "decision": "approve", "version": v, "confirm": True})
        self.lib.text["d1"] = "first draft, then edited"
        with self.assertRaises(self.dp.Refused) as e:
            self.dp.publish(self.lib, {"id": "d1", "version": v, "confirm": True})
        self.assertEqual(e.exception.status, 409)
        self.assertEqual(self.lib.published, [])

    def test_a_new_draft_drops_the_approval_and_a_stale_version_cannot_be_decided(self):
        v = self.drafted()
        self.dp.decide({"id": "d1", "decision": "approve", "version": v, "confirm": True})
        self.lib.text["d1"] = "rewritten"
        v2 = self.drafted()
        self.assertNotEqual(v, v2)
        self.assertEqual(self.state("d1"), "drafted")
        with self.assertRaises(self.dp.Refused):
            self.dp.decide({"id": "d1", "decision": "approve", "version": v, "confirm": True})

    def test_a_suggestion_is_recorded_forwarded_and_clears_the_approval(self):
        v = self.drafted()
        self.dp.decide({"id": "d1", "decision": "approve", "version": v, "confirm": True})
        self.dp.suggest(self.lib, {"id": "d1", "text": "  shorten   the intro "})
        self.assertEqual(self.lib.suggested, [("d1", "shorten the intro")])
        self.assertEqual(self.state("d1"), "suggested")
        with self.assertRaises(self.dp.Refused):
            self.dp.publish(self.lib, {"id": "d1", "version": v, "confirm": True})
        with self.assertRaises(self.dp.Refused):
            self.dp.suggest(self.lib, {"id": "d2", "text": "x"})

    def test_reject_then_restore_goes_back_to_drafted_and_only_those_can_be_restored(self):
        v = self.drafted()
        with self.assertRaises(self.dp.Refused):
            self.dp.restore({"id": "d1", "confirm": True})
        self.dp.decide({"id": "d1", "decision": "reject", "version": v, "confirm": True})
        self.assertEqual(self.state("d1"), "rejected")
        self.assertEqual(self.dp.restore({"id": "d1", "confirm": True})["state"], "drafted")

    def test_every_write_needs_confirm_and_bad_ids_and_decisions_are_refused(self):
        v = self.drafted()
        for fn, body in (
            (self.dp.decide, {"id": "d1", "decision": "approve", "version": v}),
            (self.dp.restore, {"id": "d1"}),
            (self.dp.decide, {"id": "d1", "decision": "maybe", "version": v, "confirm": True}),
            (self.dp.decide, {"id": "../x", "decision": "approve", "version": v, "confirm": True}),
        ):
            with self.assertRaises(ValueError):
                fn(body)
        with self.assertRaises(ValueError):
            self.dp.publish(self.lib, {"id": "d1", "version": v})

    def test_a_provider_without_a_method_is_a_501_and_the_routes_need_authorisation(self):
        class Bare:
            def authorize(self, h, a, k=None):
                return "me"

        with self.assertRaises(self.dp.Refused) as e:
            self.dp.draft(Bare(), {"id": "d1"})
        self.assertEqual(e.exception.status, 501)
        r = reg.Registry()
        self.lib.allow = False
        self.dp.register(r, self.lib)
        h = next(x.handler for x in r.routes if x.name == "doc_pipeline.get")
        with self.assertRaises(PermissionError):
            h(reg.Request("GET", "/x", headers={}))


if __name__ == "__main__":
    unittest.main()
