import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import docs_write_guard as g  # noqa: E402

CFG_RAW = {
    "allowed_roots": {"100": "team root", "200": "platform root"},
    "excluded_roots": {"900": "restricted folder"},
    "cloud_id": "cloud-1",
    "endpoint": "https://connector.example.invalid/mcp",
    "forbidden": [r"retired-wiki", r"\[\[[a-z0-9-]+\]\]"],
}


class Fake:
    """A fake connector: pages {id: {id, title, parentId, spaceId}}, folders {id: ancestor ids under which it sits}."""

    def __init__(self, cfg, pages, folders=None, fail_folder_query=False, write_error=None):
        self.cfg, self.pages, self.folders = cfg, pages, folders or {}
        self.fail_folder_query, self.write_error = fail_folder_query, write_error
        self.calls = []

    def get_page(self, pid):
        p = self.pages.get(str(pid))
        return (True, p) if p else (False, "404")

    def descendant_ids(self, ancestor, node_type):
        if self.fail_folder_query:
            return None
        if node_type == "folder":
            return {f for f, anc in self.folders.items() if str(ancestor) in anc}
        return {p for p, o in self.pages.items() if o.get("under") == str(ancestor)}

    def folder_in_scope(self, fid):
        return g.Connector.folder_in_scope(self, fid)

    def call(self, tool, args):
        self.calls.append((tool, args))
        if self.write_error:
            return {
                "result": {
                    "isError": True,
                    "content": [{"text": json.dumps({"error": True, "message": self.write_error})}],
                }
            }
        return {
            "result": {
                "content": [
                    {
                        "text": json.dumps(
                            {
                                "id": "77",
                                "title": args.get("title"),
                                "status": "current",
                                "version": 2,
                            }
                        )
                    }
                ]
            }
        }


def page(pid, parent, **kw):
    return dict({"id": pid, "title": f"Page {pid}", "parentId": parent, "spaceId": "sp1"}, **kw)


PAGES = {
    "10": page("10", "100"),  # directly under the team root
    "11": page("11", "10"),  # two levels down
    "20": page("20", "200"),
    "30": page("30", "900"),  # directly under the excluded folder
    "31": page("31", "30"),
    "40": page("40", None),  # top of the space, no allowed root
    "50": page("50", "999"),  # parent cannot be fetched
}


class Guard(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.cfg = g.load_config()
        self.cfg.update(
            {k: v for k, v in CFG_RAW.items() if k not in ("forbidden",)},
            forbidden=[
                __import__("re").compile(p, __import__("re").I) for p in CFG_RAW["forbidden"]
            ],
            log_path=os.path.join(self._d.name, "guard.log"),
        )

    def tearDown(self):
        self._d.cleanup()

    def conn(self, **kw):
        return Fake(self.cfg, PAGES, **kw)

    def run_guard(self, mode, tool, args, conn=None):
        return g.run(mode, tool, args, cfg=self.cfg, conn=conn or self.conn())

    def test_the_chain_is_walked_up_to_an_allowed_root(self):
        v, why, chain = g.resolve_scope(self.conn(), "11")
        self.assertEqual(v, "ALLOW")
        self.assertIn("team root", why)
        self.assertEqual([c[0] for c in chain][:2], ["11", "10"])
        self.assertEqual(g.resolve_scope(self.conn(), "20")[0], "ALLOW")
        self.assertEqual(g.resolve_scope(self.conn(), "100")[0], "ALLOW")  # the root itself

    def test_everything_unproven_is_refused(self):
        for start, needle in (
            ("31", "excluded"),
            ("30", "excluded"),
            ("900", "excluded"),
            ("40", "top of the space"),
            ("50", "cannot resolve"),
            ("777", "cannot resolve"),
        ):
            v, why, _ = g.resolve_scope(self.conn(), start)
            self.assertEqual(v, "REFUSE", start)
            self.assertIn(needle, why)

    def test_a_loop_is_cut_off_at_the_max_depth(self):
        loop = {"1": page("1", "2"), "2": page("2", "1")}
        v, why, _ = g.resolve_scope(Fake(self.cfg, loop), "1")
        self.assertEqual(v, "REFUSE")
        self.assertIn("max depth", why)

    def test_only_create_and_update_are_allowed(self):
        for tool in ("deleteConfluencePage", "addComment", "anything"):
            self.assertEqual(g.validate(self.conn(), tool, {})[0], "REFUSE")

    def test_create_needs_a_parent_inside_scope(self):
        self.assertEqual(
            g.validate(self.conn(), "createConfluencePage", {"title": "t"})[0], "REFUSE"
        )
        self.assertEqual(
            g.validate(self.conn(), "createConfluencePage", {"parentId": "10", "title": "t"})[0],
            "ALLOW",
        )
        self.assertEqual(
            g.validate(self.conn(), "createConfluencePage", {"parentId": "30", "title": "t"})[0],
            "REFUSE",
        )

    def test_update_needs_a_page_id_and_a_proven_page(self):
        self.assertEqual(g.validate(self.conn(), "updateConfluencePage", {})[0], "REFUSE")
        self.assertEqual(
            g.validate(self.conn(), "updateConfluencePage", {"pageId": "11"})[0], "ALLOW"
        )
        self.assertEqual(
            g.validate(self.conn(), "updateConfluencePage", {"pageId": "31"})[0], "REFUSE"
        )

    def test_a_move_needs_both_ends_and_a_folder_target_is_proven_downward(self):
        move = {"pageId": "11", "parentId": "20"}
        v, why, _, _ = g.validate(self.conn(), "updateConfluencePage", move)
        self.assertEqual(v, "ALLOW")
        self.assertIn("both in scope", why)
        out = {"pageId": "11", "parentId": "900"}
        self.assertEqual(g.validate(self.conn(), "updateConfluencePage", out)[0], "REFUSE")
        folders = {"555": ["100"], "556": ["100", "900"]}  # 556 sits under the excluded folder too
        ok = g.validate(
            self.conn(folders=folders), "updateConfluencePage", {"pageId": "11", "parentId": "555"}
        )
        self.assertEqual(ok[0], "ALLOW")
        self.assertIn("folder", ok[1])
        for fid in ("556", "999"):
            bad = g.validate(
                self.conn(folders=folders),
                "updateConfluencePage",
                {"pageId": "11", "parentId": fid},
            )
            self.assertEqual(bad[0], "REFUSE", fid)
        failing = g.validate(
            self.conn(folders=folders, fail_folder_query=True),
            "updateConfluencePage",
            {"pageId": "11", "parentId": "555"},
        )
        self.assertEqual(failing[0], "REFUSE")  # a failed query fails closed

    def test_a_forbidden_pattern_in_the_body_or_title_refuses(self):
        for args in (
            {"parentId": "10", "body": "see retired-wiki here"},
            {"parentId": "10", "title": "[[slug]]"},
            {"parentId": "10", "body": {"value": "x retired-wiki"}},
        ):
            v, why, _, _ = g.validate(self.conn(), "createConfluencePage", args)
            self.assertEqual(v, "REFUSE")
            self.assertIn("forbidden", why)

    def test_check_never_writes_and_execute_writes_once(self):
        c = self.conn()
        res, code = self.run_guard(
            "check", "updateConfluencePage", {"pageId": "11", "title": "t"}, c
        )
        self.assertEqual((res["verdict"], code), ("ALLOW", 0))
        self.assertEqual(c.calls, [])
        res, code = self.run_guard(
            "execute", "updateConfluencePage", {"pageId": "11", "title": "t"}, c
        )
        self.assertEqual((code, res["written"]["version"]), (0, 2))
        self.assertEqual(len(c.calls), 1)

    def test_execute_refuses_without_writing_out_of_scope(self):
        c = self.conn()
        res, code = self.run_guard("execute", "updateConfluencePage", {"pageId": "31"}, c)
        self.assertEqual((res["verdict"], code), ("REFUSE", 3))
        self.assertEqual(c.calls, [])

    def test_a_write_error_is_reported_not_swallowed(self):
        res, code = self.run_guard(
            "execute", "updateConfluencePage", {"pageId": "11"}, self.conn(write_error="locked")
        )
        self.assertEqual((res["verdict"], code), ("WRITE_FAILED", 4))
        self.assertIn("locked", res["write_error"])

    def test_create_derives_the_space_from_the_parent(self):
        c = self.conn()
        res, code = self.run_guard(
            "execute", "createConfluencePage", {"parentId": "10", "title": "t"}, c
        )
        self.assertEqual((code, res["derived_space_id"]), (0, "sp1"))
        self.assertEqual(c.calls[-1][1]["spaceId"], "sp1")

    def test_every_decision_is_logged(self):
        self.run_guard("check", "updateConfluencePage", {"pageId": "31"})
        self.run_guard("check", "updateConfluencePage", {"pageId": "11"})
        log = Path(self.cfg["log_path"]).read_text()
        self.assertIn("REFUSE", log)
        self.assertIn("ALLOW", log)

    def test_no_roots_or_no_token_provider_refuses_every_write(self):
        cfg = dict(self.cfg, allowed_roots={})
        self.assertEqual(g.run("execute", "updateConfluencePage", {"pageId": "11"}, cfg=cfg)[1], 3)
        old = g._token_provider
        g.set_token_provider(None)
        try:
            res, code = g.run("execute", "updateConfluencePage", {"pageId": "11"}, cfg=self.cfg)
        finally:
            g.set_token_provider(old)
        self.assertEqual(code, 3)
        self.assertIn("token provider", res["reason"])

    def test_main_usage_and_bad_json(self):
        self.assertEqual(g.main(["x"]), 2)
        self.assertEqual(g.main(["x", "check", "updateConfluencePage", "{nope"]), 2)

    def test_config_is_read_from_the_file(self):
        p = Path(self._d.name) / "cfg.json"
        p.write_text(json.dumps(CFG_RAW))
        os.environ["DOCS_GUARD_CONFIG"] = str(p)
        try:
            cfg = g.load_config()
        finally:
            os.environ.pop("DOCS_GUARD_CONFIG")
        self.assertEqual(cfg["allowed_roots"]["100"], "team root")
        self.assertEqual(len(cfg["forbidden"]), 2)
        self.assertEqual(
            g.load_config()["allowed_roots"], {}
        )  # nothing configured: nothing allowed


if __name__ == "__main__":
    unittest.main()
