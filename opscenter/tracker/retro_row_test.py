"""The retro row drafter: cell validation, ticket citations, the scan (wake or stay quiet), propose and the guarded write,
against a fake tracker and wiki and a scratch state root. No real page, ticket or pull request is touched."""

import copy
import datetime as dt
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TMP = Path(tempfile.mkdtemp(prefix="retro-row-test-"))
PARAMS_FILE = str(TMP / "tracker-params.json")
os.environ.update(
    OPSCENTER_ROOT=str(TMP),
    OPSCENTER_STATE_DIR=str(TMP / "state"),
    OPSCENTER_AGENT_HOME=str(TMP / "agent"),
    OPSCENTER_TRACKER_PARAMS=str(TMP / "tracker-params.json"),
)
(TMP / "tracker-params.json").write_text(
    json.dumps(
        {
            "owner_name": "Owen Owner",
            "project": "ABC",
            "site_id": "site-1",
            "retro": {
                "parent_page": "900",
                "board_id": 7,
                "row_name": "Owen",
                "repos": ["acme/primary", "acme/secondary"],
                "title_match": "Team Retro",
                "page_url": "https://wiki.example/pages/",
                "banned_words": ["internal-tool"],
            },
        }
    )
)
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "server" / "modules"))
import automation_actions as aa  # noqa: E402
import params  # noqa: E402
import retro_row as rr  # noqa: E402

importlib.reload(params)
importlib.reload(aa)
importlib.reload(rr)

NOW = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
START = (NOW - dt.timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
END = (NOW + dt.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def para(t):
    return {"type": "paragraph", "content": [{"type": "text", "text": t}] if t else []}


def cell(t=""):
    return {"type": "tableCell", "content": [para(t)]}


def page_doc(mine=("", "", ""), name="Owen"):
    return {
        "type": "doc",
        "content": [
            {
                "type": "table",
                "content": [
                    {
                        "type": "tableRow",
                        "content": [cell("Who"), cell("Well"), cell("Bad"), cell("Change")],
                    },
                    {
                        "type": "tableRow",
                        "content": [cell("Someone"), cell("a"), cell("b"), cell("c")],
                    },
                    {"type": "tableRow", "content": [cell(name), *[cell(t) for t in mine]]},
                ],
            }
        ],
    }


class Fake:
    """A tiny wiki and tracker behind rr.call."""

    def __init__(self):
        self.doc = page_doc()
        self.version = 3
        self.title = "Team Retro 2099-01-01"
        self.calls = []
        self.search_results = [{"content": {"id": "42", "title": self.title}}]
        self.race = False

    def call(self, tool, args, retried=False):
        self.calls.append(tool)
        if tool == "searchConfluenceUsingCql":
            return {"results": self.search_results}
        if tool == "getConfluencePage":
            v = self.version + (1 if self.race and args.get("contentFormat") == "markdown" else 0)
            return {
                "id": args["pageId"],
                "title": self.title,
                "createdAt": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "version": {"number": v},
                "body": json.dumps(self.doc),
            }
        if tool == "updateConfluencePage":
            self.doc = json.loads(args["body"])
            self.version += 1
            return {}
        raise AssertionError("unexpected tool " + tool)


ISSUES = [
    {
        "key": "ABC-1",
        "fields": {
            "summary": "Build the pool",
            "status": {"name": "Done", "statusCategory": {"name": "Done"}},
            "created": START,
            "parent": None,
            "issuetype": {"name": "Task"},
            "issuelinks": [],
            "customfield_10016": 3,
            "customfield_10020": [
                {"id": 5, "name": "Sprint 5", "boardId": 7, "startDate": START, "endDate": END}
            ],
        },
    },
    {
        "key": "ABC-2",
        "fields": {
            "summary": "Fix the roll",
            "status": {"name": "In Progress", "statusCategory": {"name": "In Progress"}},
            "created": START,
            "parent": None,
            "issuetype": {"name": "Task"},
            "issuelinks": [],
            "customfield_10016": 2,
            "customfield_10020": [
                {"id": 4, "name": "Sprint 4", "boardId": 7, "startDate": START, "endDate": START},
                {"id": 5, "name": "Sprint 5", "boardId": 7, "startDate": START, "endDate": END},
            ],
        },
    },
]


class RetroRow(unittest.TestCase):
    def setUp(self):
        # Another test module may have pointed the shared params module at its own file: point it back.
        os.environ["OPSCENTER_TRACKER_PARAMS"] = PARAMS_FILE
        importlib.reload(params)
        for p in (rr.STORE_PATH,):
            p.unlink(missing_ok=True)
        self.fake = Fake()
        self._orig = (rr.call, rr.jql_all, rr.merged_prs)
        rr.call = self.fake.call
        rr.jql_all = lambda jql, fields: copy.deepcopy(ISSUES)
        rr.merged_prs = lambda start, end: [
            {"repo": "primary", "number": 11, "title": "ABC-2 fix the roll"}
        ]
        aa_store = aa.STORE_PATH
        aa_store.unlink(missing_ok=True)

    def tearDown(self):
        rr.call, rr.jql_all, rr.merged_prs = self._orig

    CELLS = {"well": "We built the pool (ABC-1).", "bad": "The roll slipped (ABC-2).", "change": ""}

    # validation
    def test_good_cells_pass_and_each_bad_form_is_refused(self):
        self.assertEqual(rr.validate_cells(self.CELLS)["well"], "We built the pool (ABC-1).")
        for bad in (
            {"well": "a; b"},
            {"well": "a \u2014 b"},
            {"well": "caf\u00e9"},
            {"well": "uses internal-tool"},
            {"well": "x" * (rr.MAX_CELL + 1)},
            {},
        ):
            with self.assertRaises(ValueError, msg=str(bad)[:30]):
                rr.validate_cells(bad)

    def test_cited_keys_expand_shorthand_lists_for_the_project_only(self):
        self.assertEqual(
            rr.cited_keys("ABC-5547, 5548 and 5552 shipped, XYZ-1 too"),
            ["ABC-5547", "ABC-5548", "ABC-5552"],
        )

    def test_default_rules_name_no_estate(self):
        self.assertTrue(rr.RULES and all("Hermes" not in r for r in rr.RULES))

    # scan
    def test_scan_with_no_page_stays_quiet(self):
        self.fake.search_results = []
        self.assertEqual(rr.cmd_scan()["wake"], False)

    def test_scan_wakes_for_a_blank_row_and_writes_the_facts_file(self):
        out = rr.cmd_scan()
        self.assertTrue(out["wake"])
        facts = json.loads(Path(out["path"]).read_text())
        self.assertEqual(facts["totals"]["tickets"], 2)
        self.assertEqual(facts["closures_owed"], ["ABC-2"])
        self.assertEqual(facts["rolled_over_open"], ["ABC-2"])
        self.assertEqual(facts["page"]["url"], "https://wiki.example/pages/42")
        # a second scan inside the rewake window stays quiet
        self.assertFalse(rr.cmd_scan()["wake"])

    def test_scan_skips_a_row_that_is_already_filled_and_a_page_with_no_row(self):
        self.fake.doc = page_doc(("done", "", ""))
        self.assertEqual(rr.cmd_scan()["why"], "the owner's row already has content")
        rr.STORE_PATH.unlink()
        self.fake.doc = page_doc(name="Nobody")
        self.assertIn("no Owen row", rr.cmd_scan()["why"])

    # propose and write
    def test_propose_stores_the_draft_and_raises_one_card_and_approve_writes_only_the_row(self):
        rr.cmd_scan()
        out = rr.cmd_propose("42", self.CELLS)
        self.assertEqual(out["card"], "auto-retro-42")
        self.assertIn("retro-42", aa._load()["items"])
        res = rr.cmd_write("42", None, force=True)
        self.assertEqual(res["version"], 4)
        mine = rr.my_row(self.fake.doc)
        self.assertEqual(rr.row_cells_text(mine)[0], "We built the pool (ABC-1).")
        other = self.fake.doc["content"][0]["content"][1]
        self.assertEqual(rr.row_cells_text(other), ["a", "b", "c"])  # nobody else's row changes
        self.assertEqual(rr.load_store()["pages"]["42"]["state"], "written")
        self.assertTrue(aa._load()["items"]["retro-42"].get("closed"))

    def test_the_write_refuses_when_the_page_changed_meanwhile_or_the_row_has_content(self):
        rr.cmd_scan()
        rr.cmd_propose("42", self.CELLS)
        self.fake.race = True
        with self.assertRaises(ValueError) as cm:
            rr.cmd_write("42", None, force=True)
        self.assertIn("changed while writing", str(cm.exception))
        self.fake.race = False
        self.fake.doc = page_doc(("typed by hand", "", ""))
        with self.assertRaises(ValueError) as cm:
            rr.cmd_write("42", None, force=True)
        self.assertIn("already has content", str(cm.exception))

    def test_propose_for_a_page_never_scanned_is_refused(self):
        with self.assertRaises(ValueError):
            rr.cmd_propose("nope", self.CELLS)


if __name__ == "__main__":
    unittest.main()
