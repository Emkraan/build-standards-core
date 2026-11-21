import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import phone_pairing as pp  # noqa: E402
import registry as reg  # noqa: E402


class Source:
    def __init__(self, devices=None, boom=None, allow=True):
        self.devs, self.boom, self.allow, self.calls = devices, boom, allow, []

    def authorize(self, headers, action, key):
        return "me" if self.allow else None

    def status(self):
        return {
            "api_reachable": True,
            "edge_covers_host": False,
            "plugin_pinned": "yes",
            "only_api_connected": None,
        }

    def devices(self):
        if self.boom:
            raise self.boom
        return self.devs

    def pair(self):
        return {"link": "app://pair?code=SECRET"}

    def test(self, ident):
        self.calls.append(("test", ident))
        return {"ok": True, "detail": "sent"}

    def remove(self, ident):
        self.calls.append(("remove", ident))
        return {"ok": True}


def handler(provider, name):
    r = reg.Registry()
    pp.register(r, provider)
    return next(x.handler for x in r.routes if x.name == f"phone_pairing.{name}")


def req(body=None, headers=None):
    return reg.Request("POST", "/x", body=body, headers=headers or {})


class Pairing(unittest.TestCase):
    def test_read_keeps_known_status_as_true_false_or_unknown_and_cleans_devices(self):
        out = pp.read(Source([{"id": "d1", "name": " Phone  A "}, {"id": "bad id"}, "x"]))
        self.assertEqual(out["status"]["api_reachable"], True)
        self.assertEqual(out["status"]["edge_covers_host"], False)
        self.assertIsNone(out["status"]["plugin_pinned"])
        self.assertEqual([d["id"] for d in out["devices"]], ["d1"])
        self.assertEqual(out["devices"][0]["name"], "Phone A")

    def test_a_failing_source_is_an_error_never_an_empty_list(self):
        out = pp.read(Source(boom=RuntimeError("x")))
        self.assertTrue(out["error"])
        self.assertEqual(pp.read(Source("not a list"))["error"] is None, False)

    def test_no_provider_methods_is_an_all_unknown_empty_answer(self):
        out = pp.read(object())
        self.assertEqual((out["devices"], out["error"]), ([], None))
        self.assertTrue(all(v is None for v in out["status"].values()))

    def test_the_link_is_issued_on_the_host_only_with_no_store_and_a_proxied_request_gets_403(self):
        pair = handler(Source(), "pair")
        status, body, ctype, headers = pair(req())
        self.assertEqual((status, headers["Cache-Control"]), (200, "no-store"))
        self.assertIn(b'"expires_in": 60', body)
        for h in ("X-Forwarded-For", "x-real-ip", "Forwarded", "Via"):
            with self.assertRaises(pp.Refused) as e:
                pair(req(headers={h: "192.0.2.7"}))
            self.assertEqual(e.exception.status, 403)

    def test_everything_is_refused_until_the_provider_authorises(self):
        for name in ("get", "pair"):
            with self.assertRaises(PermissionError):
                handler(Source(allow=False), name)(req())

    def test_test_and_remove_need_a_device_id_and_confirm_true(self):
        src = Source()
        for name in ("test", "remove"):
            h = handler(src, name)
            for bad in (
                {},
                {"id": "d1"},
                {"id": "d1", "confirm": "yes"},
                {"id": "../x", "confirm": True},
            ):
                with self.assertRaises(ValueError):
                    h(req(bad))
            self.assertEqual(h(req({"id": "d1", "confirm": True}))["ok"], True)
        self.assertEqual(src.calls, [("test", "d1"), ("remove", "d1")])

    def test_a_provider_without_pair_is_a_501(self):
        class NoPair:
            def authorize(self, h, a, k):
                return "me"

        with self.assertRaises(pp.Refused) as e:
            handler(NoPair(), "pair")(req())
        self.assertEqual(e.exception.status, 501)


if __name__ == "__main__":
    unittest.main()
