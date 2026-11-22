import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import drafts as dr  # noqa: E402
import registry as reg  # noqa: E402


class Box:
    def __init__(self):
        self.items = [
            {
                "id": "m1",
                "title": "Re: budget",
                "kind": "reply",
                "thread": "t1",
                "updated": "2026-11-20",
            },
            {"id": "bad id"},
            {"id": "d2", "title": "", "kind": "weird"},
        ]
        self.calls = []
        self.allow = True

    def authorize(self, h, a, k=None):
        return "me" if self.allow else None

    def drafts(self):
        return self.items

    def archive(self, i):
        self.calls.append(("archive", i))
        return {"ok": True}

    def restore(self, i):
        self.calls.append(("restore", i))
        return {"ok": True}

    def reply(self, thread, text):
        self.calls.append(("reply", thread, text))
        return {"id": "new1"}


class Drafts(unittest.TestCase):
    def test_the_list_keeps_well_formed_drafts_and_a_failing_source_is_an_error(self):
        out = dr.read(Box())
        self.assertEqual(
            [(d["id"], d["kind"], d["title"]) for d in out["drafts"]],
            [("m1", "reply", "Re: budget"), ("d2", "doc", "(no subject)")],
        )

        class Broken(Box):
            def drafts(self):
                raise RuntimeError("x")

        bad = dr.read(Broken())
        self.assertTrue(bad["error"])
        self.assertEqual(bad["drafts"], [])

    def test_archive_and_restore_need_confirm_and_call_the_provider_once(self):
        b = Box()
        for fn in (dr.archive,):
            with self.assertRaises(ValueError):
                fn(b, {"id": "m1"})
        self.assertEqual(dr.archive(b, {"id": "m1", "confirm": True})["archived"], True)
        self.assertEqual(dr.archive(b, {"id": "m1", "confirm": True}, True)["archived"], False)
        self.assertEqual(b.calls, [("archive", "m1"), ("restore", "m1")])
        with self.assertRaises(ValueError):
            dr.archive(b, {"id": "../x", "confirm": True})

    def test_a_reply_is_a_threaded_draft_that_is_never_sent(self):
        b = Box()
        out = dr.reply(b, {"thread": "t1", "text": " thanks ", "confirm": True})
        self.assertEqual(out, {"id": "new1", "thread": "t1", "sent": False})
        self.assertEqual(b.calls, [("reply", "t1", "thanks")])
        for body in (
            {"thread": "t1", "text": "x"},
            {"thread": "t 1", "text": "x", "confirm": True},
            {"thread": "t1", "text": "  ", "confirm": True},
        ):
            with self.assertRaises(ValueError):
                dr.reply(b, body)

    def test_there_is_no_send_route_and_no_delete_route(self):
        r = reg.Registry()
        dr.register(r, Box())
        routes = {(x.method, x.path) for x in r.routes}
        self.assertEqual(
            routes,
            {
                ("GET", "/api/drafts"),
                ("POST", "/api/drafts/archive"),
                ("POST", "/api/drafts/restore"),
                ("POST", "/api/drafts/reply"),
            },
        )
        text = Path(dr.__file__).read_text()
        for word in ("send(", "delete(", "remove(", "unlink("):
            self.assertNotIn(word, text, word)

    def test_a_missing_method_is_a_501_and_everything_needs_authorisation(self):
        class Bare:
            def authorize(self, h, a, k=None):
                return "me"

        with self.assertRaises(dr.Refused) as e:
            dr.archive(Bare(), {"id": "m1", "confirm": True})
        self.assertEqual(e.exception.status, 501)
        r = reg.Registry()
        b = Box()
        b.allow = False
        dr.register(r, b)
        h = next(x.handler for x in r.routes if x.name == "drafts.get")
        with self.assertRaises(PermissionError):
            h(reg.Request("GET", "/x", headers={}))


if __name__ == "__main__":
    unittest.main()
