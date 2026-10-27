import json
import unittest

from support import load

report = load("report_mod_find", "hermes/report.py")


def fake(search=None, rest=None, view=None, login="rpoh25"):
    """A gh stand-in: search list, REST listing, and view by number."""
    calls = []

    def sh(cmd, cwd=None, timeout=60):
        calls.append(list(map(str, cmd)))
        if cmd[1:3] == ["issue", "view"]:
            return (0, json.dumps(view)) if view else (1, "not found")
        if cmd[1:3] == ["issue", "list"]:
            return 0, json.dumps(search or [])
        if cmd[1:3] == ["api", "user"]:
            return 0, login + "\n"
        if cmd[1] == "api":
            return 0, json.dumps(rest or [])
        return 0, ""

    return sh, calls


class FindIssue(unittest.TestCase):
    def test_configured_number_wins_over_the_search(self):
        sh, _ = fake(search=[{"number": 184}], view={"number": 115, "state": "OPEN", "body": "b"})
        self.assertEqual(report.find_issue("o/intake", sh, 115)["number"], 115)

    def test_closed_configured_issue_falls_through(self):
        sh, _ = fake(search=[{"number": 9}], view={"number": 115, "state": "CLOSED"})
        self.assertEqual(report.find_issue("o/intake", sh, "#115")["number"], 9)

    def test_search_lag_falls_back_to_the_rest_listing_not_a_new_issue(self):
        rows = [
            {"number": 115, "title": "consumer report: local ops center", "body": "b"},
            {"number": 120, "title": report.TITLE, "body": "b"},
        ]
        sh, calls = fake(search=[], rest=rows)
        self.assertEqual(report.find_issue("o/intake", sh)["number"], 120)
        self.assertTrue(any("creator=rpoh25" in " ".join(c) for c in calls))

    def test_rest_fallback_takes_the_existing_report_when_no_title_matches(self):
        sh, _ = fake(rest=[{"number": 115, "title": "consumer report: x", "body": "b"}])
        self.assertEqual(report.find_issue("o/intake", sh)["number"], 115)

    def test_nothing_found_returns_none(self):
        sh, _ = fake()
        self.assertIsNone(report.find_issue("o/intake", sh))

    def test_current_issue_passes_the_configured_number(self):
        sh, _ = fake(view={"number": 115, "state": "OPEN", "body": "b"})
        self.assertEqual(report.current_issue("o/intake", sh, {"configured": 115})["number"], 115)


if __name__ == "__main__":
    unittest.main()
