"""The work tracker adapter: driver call errors, the active sprint and the sprint and backlog views, the guarded writes
and the changes page, against a fake driver command and state file. No real tracker is called."""

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TMP = Path(tempfile.mkdtemp(prefix="work-test-"))
STATE = TMP / "fake-state.json"

FAKE = r"""
import json, os, sys
st_path = os.environ["FAKE_TRACKER"]
st = json.load(open(st_path))
tool, args = sys.argv[1], json.loads(sys.argv[2])
st.setdefault("calls", []).append([tool, args])
def done(obj):
    json.dump(st, open(st_path, "w"))
    print(json.dumps({"result": {"content": [{"text": json.dumps(obj)}]}}))
    sys.exit(0)
if st.get("mode") == "error":
    print(json.dumps({"result": {"isError": True, "content": [{"text": "boom"}]}}))
    sys.exit(0)
if st.get("mode") == "exit":
    sys.stderr.write("driver broke")
    sys.exit(3)
if st.get("mode") == "garbage":
    print("not json")
    sys.exit(0)
if tool == "atlassianUserInfo":
    done({"account_id": "me-1"})
if tool == "searchJiraIssuesUsingJql":
    jql = args["jql"]
    key = "changes" if "Approvers" in jql else ("backlog" if "futureSprints()" in jql and "assignee = currentUser()" in jql and "sprint =" not in jql and "openSprints() AND" not in jql else ("sprint" if "sprint = " in jql else "active"))
    done({"issues": st["search"].get(key, [])})
if tool == "getJiraIssue":
    done({"fields": st["issues"][args["issueIdOrKey"]]})
if tool == "editJiraIssue":
    f = st["issues"][args["issueIdOrKey"]]
    sp = args["fields"].get("customfield_10020", "x")
    f["customfield_10020"] = [] if sp is None else [{"id": sp, "state": "active", "name": "S1"}]
    done({})
if tool == "getTransitionsForJiraIssue":
    done({"transitions": st["transitions"]})
if tool == "transitionJiraIssue":
    f = st["issues"][args["issueIdOrKey"]]
    f["status"] = st["after_status"]
    done({})
done({"error": "unexpected tool " + tool})
"""
(TMP / "fake.py").write_text(FAKE)
PARAMS_FILE = str(TMP / "tracker-params.json")
os.environ.update(
    OPSCENTER_ROOT=str(TMP),
    OPSCENTER_STATE_DIR=str(TMP / "state"),
    OPSCENTER_TRACKER_PARAMS=str(TMP / "tracker-params.json"),
    FAKE_TRACKER=str(STATE),
)
(TMP / "tracker-params.json").write_text(
    json.dumps(
        {
            "driver_cmd": [sys.executable, str(TMP / "fake.py")],
            "site_id": "site-1",
            "browse_url": "https://tracker.example/browse/",
            "project": "ABC",
            "team_clause": 'cf[1] = "team-1"',
            "change_jql": "project = CHG AND Approvers = currentUser()",
            "change_pending_statuses": ["Awaiting approval"],
            "change_inflight_statuses": ["Implementing"],
            "change_fields": {
                "planned_start": "customfield_5",
                "planned_end": "customfield_6",
                "risk": "customfield_7",
            },
            "portal_url_template": "https://portal.example/{key}",
        }
    )
)
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "server" / "modules"))
import params  # noqa: E402
import swr  # noqa: E402
import work  # noqa: E402

importlib.reload(params)
importlib.reload(work)


def issue(key, status="To Do", cat="new", assignee="me-1", sprints=None, pts=None):
    return {
        "key": key,
        "fields": {
            "summary": "Summary " + key,
            "status": {"name": status, "statusCategory": {"key": cat}},
            "issuetype": {"name": "Task"},
            "priority": {"name": "High"},
            "assignee": {"displayName": "Someone", "accountId": assignee},
            "customfield_10020": sprints if sprints is not None else [],
            "customfield_10016": pts,
        },
    }


ACTIVE = {"id": 11, "name": "Sprint 11", "state": "active", "boardId": 3}


class Work(unittest.TestCase):
    def setUp(self):
        # Another test module may have pointed the shared params module at its own file: point it back.
        os.environ["OPSCENTER_TRACKER_PARAMS"] = PARAMS_FILE
        importlib.reload(params)
        for k in list(swr._cache) if hasattr(swr, "_cache") else []:
            swr._cache.pop(k, None)
        work._ME.clear()
        self.state = {
            "search": {
                "active": [issue("ABC-1", sprints=[ACTIVE])],
                "sprint": [
                    issue("ABC-1", sprints=[ACTIVE], pts=3),
                    issue("ABC-2", assignee="other", sprints=[ACTIVE]),
                ],
                "backlog": [issue("ABC-9")],
                "changes": [],
            },
            "issues": {
                "ABC-9": issue("ABC-9")["fields"],
                "ABC-1": issue("ABC-1", sprints=[ACTIVE])["fields"],
                "ABC-2": issue("ABC-2", assignee="other")["fields"],
                "ABC-3": issue("ABC-3", "Closed", "done", sprints=[ACTIVE])["fields"],
            },
            "transitions": [
                {
                    "id": "11",
                    "name": "Start",
                    "to": {"name": "In Progress", "statusCategory": {"key": "indeterminate"}},
                },
                {
                    "id": "21",
                    "name": "Close",
                    "to": {"name": "Done", "statusCategory": {"key": "done"}},
                },
            ],
            "after_status": {"name": "In Progress", "statusCategory": {"key": "indeterminate"}},
        }
        self.save()

    def save(self):
        STATE.write_text(json.dumps(self.state))

    def calls(self):
        return json.loads(STATE.read_text()).get("calls", [])

    def test_driver_failures_become_tracker_errors(self):
        for mode, text in (
            ("error", "tool error"),
            ("exit", "driver exit 3"),
            ("garbage", "non-JSON"),
        ):
            self.state["mode"] = mode
            self.save()
            with self.assertRaises(work.TrackerError) as cm:
                work.call("atlassianUserInfo", {})
            self.assertIn(text, str(cm.exception))

    def test_the_sprint_view_scopes_to_the_project_and_team_and_marks_mine(self):
        got = work.sprint(fresh=True)
        self.assertEqual(got["sprint"]["id"], 11)
        rows = {r["key"]: r for r in got["items"]}
        self.assertTrue(rows["ABC-1"]["mine"] and not rows["ABC-2"]["mine"])
        self.assertEqual(
            (rows["ABC-1"]["points"], rows["ABC-1"]["url"]),
            (3, "https://tracker.example/browse/ABC-1"),
        )
        jqls = [a["jql"] for t, a in self.calls() if t == "searchJiraIssuesUsingJql"]
        self.assertTrue(
            jqls[0].startswith('project = ABC AND cf[1] = "team-1" AND sprint in openSprints()')
        )
        self.assertTrue(
            any(
                "sprint = 11" in j and 'cf[1] = "team-1"' in j and "currentUser()" in j
                for j in jqls
            )
        )

    def test_the_backlog_view_and_my_open_item(self):
        b = work.backlog(fresh=True)
        self.assertEqual([i["key"] for i in b["items"]], ["ABC-9"])
        self.assertEqual(work.my_open_item("ABC-9")["view"], "backlog")
        with self.assertRaises(KeyError):
            work.my_open_item("ABC-404")

    def test_an_invalid_key_is_refused_before_any_call(self):
        with self.assertRaises(work.TrackerError) as cm:
            work.sprint_move("not a key")
        self.assertEqual(cm.exception.code, 400)

    def test_sprint_move_confirms_on_read_back(self):
        out = work.sprint_move("ABC-9")
        self.assertEqual(out["moved_to"]["id"], 11)
        self.assertIn("editJiraIssue", [t for t, _ in self.calls()])

    def test_remove_and_transition_only_touch_my_own_items_and_never_close(self):
        with self.assertRaises(work.TrackerError) as cm:
            work.sprint_remove("ABC-2")
        self.assertEqual(cm.exception.code, 403)
        with self.assertRaises(work.TrackerError) as cm:
            work.transition("ABC-2", "11")
        self.assertEqual(cm.exception.code, 403)
        self.assertTrue(work.sprint_remove("ABC-1", what_if=True)["what_if"])
        with self.assertRaises(work.TrackerError) as cm:
            work.transition(
                "ABC-1", "21"
            )  # a done category transition runs through the closure process
        self.assertEqual(cm.exception.code, 403)
        out = work.transition("ABC-1", "11")
        self.assertEqual(out["status"], "In Progress")
        with self.assertRaises(work.TrackerError) as cm:
            work.sprint_remove("ABC-3")
        self.assertEqual(cm.exception.code, 409)  # a closed item stays in the record

    def test_changes_pending_the_owner_come_from_the_configured_query_and_fields(self):
        row = issue("CHG-1", "Awaiting approval")
        row["fields"].update(
            reporter={"displayName": "Req"},
            created="2099-01-01T00:00:00Z",
            customfield_5="2099-02-01",
            customfield_6="2099-02-02",
            customfield_7={"value": "High"},
        )
        self.state["search"]["changes"] = [row]
        self.save()
        got = work.approvals(fresh=True)
        r = got["pending"][0]
        self.assertEqual(
            (r["key"], r["requester"], r["risk"], r["planned_start"]),
            ("CHG-1", "Req", "High", "2099-02-01"),
        )
        self.assertEqual(r["portal_url"], "https://portal.example/CHG-1")
        jql = next(a["jql"] for t, a in self.calls() if "Approvers" in a.get("jql", ""))
        self.assertIn('status in ("Awaiting approval")', jql)
        self.assertIn("ORDER BY customfield_5 ASC", jql)

    def test_no_change_query_means_empty_changes(self):
        saved = work.CHANGE_BASE_JQL
        work.CHANGE_BASE_JQL = ""
        try:
            self.assertEqual(work.approvals(fresh=True)["pending"], [])
        finally:
            work.CHANGE_BASE_JQL = saved


if __name__ == "__main__":
    unittest.main()
