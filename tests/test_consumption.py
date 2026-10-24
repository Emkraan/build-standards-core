"""Tests for v0.59.0: the consumption feed (hermes/consumption.py), the consumption classes in setup
and core-update.yml, G-031 (a report-only vendored repo gets its record and reaches the report
sections) and G-032 (the raw gist link to a moved .md table). Fixtures only, no network: gh is a test
double. Fixtures live under .test-work, never /tmp."""

import json
import os
import sys
import unittest

from support import ROOT, Work, load, sh

consumption = load("consumption_t", "hermes/consumption.py")
nightly = load("nightly_consumption", "hermes/nightly.py")
report = load("report_consumption", "hermes/report.py")
setup = load("setup_consumption", "hermes/setup.py")

CHANGELOG = """# Changelog

## 2026-10-22 (v0.60.0, kit parts)

- A list layout on the kit Table (#115 D-004) and a resize handle (#117 D-018).

## 2026-10-21 (v0.59.0, consumption classes)

- Report-only vendored repos (#117 G-031, G-032).
"""

MINE = {
    "number": 117,
    "url": "https://example.invalid/117",
    "author": {"login": "me-acct"},
    "body": (
        "**D-015 Status board** (ready)\n**D-018 Resize handle** (ready)\n"
        "**D-027 New thing** (ready)\n**G-031 Vendored report** (ready)\n"
        "| Part | Risk |\n|---|---|\n| `DataTable` | low |\n| `StatusPill` | high |\n"
    ),
    "comments": [
        {"author": {"login": "owner"}, "body": "Approved: D-015, D-018 (with resize), G-031."},
        {"author": {"login": "someone"}, "body": "approve D-027"},
    ],
}
PEER = {
    "number": 115,
    "url": "https://example.invalid/115",
    "author": {"login": "peer-acct"},
    "body": "**D-004 List layout** (ready)\n**P-002 Lane** (settling: open question)\n**G-009 Gap** (ready)\n",
    "comments": [{"author": {"login": "owner"}, "body": "reject G-009: local only"}],
}


def fake_gh(issues, prs_by_repo=None, core_prs=None, login="me-acct"):
    calls = []

    def sh_(cmd, cwd=None, timeout=600):
        calls.append(list(map(str, cmd)))
        if cmd[:2] == ["gh", "issue"]:
            state = cmd[cmd.index("--state") + 1] if "--state" in cmd else "open"
            rows = [i for i in issues if state == "all" or i.get("state", "OPEN") == "OPEN"]
            if "--author" in cmd:
                rows = [i for i in rows if i["author"]["login"] == login]
            return 0, json.dumps(rows)
        if cmd[:3] == ["gh", "api", "user"]:
            return 0, json.dumps({"login": login})
        if cmd[:3] == ["gh", "pr", "list"]:
            repo = cmd[cmd.index("-R") + 1]
            if repo == "owner/core":
                return 0, json.dumps(core_prs or [])
            return 0, json.dumps((prs_by_repo or {}).get(repo, []))
        if cmd[:2] == ["git", "-C"] and "tag" in cmd:
            return 0, "v0.60.0\nv0.59.0\nv0.58.0\nv0.57.0"
        if cmd[0] == "gh":
            return 1, "unexpected"
        return 1, ""

    sh_.calls = calls
    return sh_


class Pure(unittest.TestCase):
    def test_classes(self):
        self.assertEqual(consumption.consumption_class("ops-center"), "apply-at-once")
        self.assertEqual(consumption.consumption_class("local"), "apply-at-once")
        for m in ("workflow", "vendored"):
            self.assertEqual(consumption.consumption_class(m), "approval-gated")

    def test_behind_and_ci(self):
        tags = ["v0.60.0", "v0.59.0", "v0.58.0"]
        self.assertEqual(consumption.behind_count("v0.58.0", "v0.60.0", tags), 2)
        self.assertEqual(consumption.behind_count("v0.60.0", "v0.60.0", tags), 0)
        self.assertIsNone(consumption.behind_count("v0.1.0", "v0.60.0", tags))
        self.assertEqual(consumption.ci_state([]), "none")
        self.assertEqual(
            consumption.ci_state([{"conclusion": "SUCCESS"}, {"status": "IN_PROGRESS"}]), "pending"
        )
        self.assertEqual(
            consumption.ci_state([{"conclusion": "SUCCESS"}, {"conclusion": "FAILURE"}]), "fail"
        )
        self.assertEqual(
            consumption.ci_state([{"conclusion": "SUCCESS"}, {"state": "SUCCESS"}]), "pass"
        )

    def test_shipped_and_decisions(self):
        shipped = consumption.shipped_ids(CHANGELOG)
        self.assertEqual(shipped[(115, "D-004")], "v0.60.0")
        self.assertEqual(shipped[(117, "G-032")], "v0.59.0")
        dec = consumption.decisions(MINE["comments"], "owner")
        self.assertEqual(
            dec, {"D-015": "approved", "D-018": "approved", "G-031": "approved"}
        )  # non-owner ignored
        self.assertEqual(consumption.decisions(PEER["comments"], "owner"), {"G-009": "rejected"})

    def test_issue_items_status(self):
        items = {
            i["id"]: i
            for i in consumption.issue_items(PEER, "owner", consumption.shipped_ids(CHANGELOG))
        }
        self.assertEqual(
            (items["D-004"]["status"], items["D-004"]["shipped_in"]), ("shipped", "v0.60.0")
        )
        self.assertEqual(items["P-002"]["status"], "held")
        self.assertEqual(items["G-009"]["status"], "rejected")
        mine = {
            i["id"]: i["status"]
            for i in consumption.issue_items(MINE, "owner", consumption.shipped_ids(CHANGELOG))
        }
        self.assertEqual(
            mine,
            {
                "D-015": "approved",
                "D-018": "shipped",
                "D-027": "awaiting decision",
                "G-031": "shipped",
            },
        )

    def test_peers_and_account(self):
        peers = consumption.peers_block([MINE, PEER], "me-acct", "owner", CHANGELOG, {})
        self.assertEqual([i["mine"] for i in peers["issues"]], [False, True])
        self.assertEqual(
            [(s["issue"], s["id"], s["new"]) for s in peers["suggestions"]], [(115, "D-004", False)]
        )
        again = consumption.peers_block(
            [MINE, PEER], "me-acct", "owner", CHANGELOG, {"peers": {"suggestions": []}}
        )
        self.assertTrue(again["suggestions"][0]["new"])  # shipped since the last run
        acct = consumption.account_block(peers, [])
        self.assertEqual([r["id"] for r in acct["awaiting_decision"]], ["D-027"])
        self.assertEqual([r["id"] for r in acct["approved_unopened"]], ["D-015"])
        linked = consumption.account_block(
            peers, [{"title": "feat(kit): status board", "body": "#117 D-015"}]
        )
        self.assertEqual(linked["approved_unopened"], [])

    def test_approved_on_a_closed_issue_still_owed(self):
        """#117 G-037: approvals on a closed report issue still appear in approved_unopened."""
        closed = {**MINE, "state": "CLOSED"}
        later = {
            "number": 134,
            "url": "https://example.invalid/134",
            "author": {"login": "me-acct"},
            "state": "CLOSED",
            "body": "**D-015 Status board** (ready)\n**G-033 Gap** (ready)\n",
            "comments": [],
        }
        peers = consumption.peers_block([PEER], "me-acct", "owner", CHANGELOG, {})
        own = consumption.own_items([closed, later], "owner", CHANGELOG)
        self.assertEqual([i["number"] for i in own], [134, 117])  # most recent first
        acct = consumption.account_block(peers, [], own)
        self.assertEqual(
            [(r["issue"], r["id"]) for r in acct["approved_unopened"]], [(117, "D-015")]
        )
        self.assertEqual(acct["awaiting_decision"], [])  # awaiting is read from open reports only
        self.assertEqual(acct["report_issue"], "https://example.invalid/134")

    def test_ci_counts_never_fail_an_unread_ci_rule(self):
        rules = [
            {"kind": "overlay-ci", "status": "fail", "note": "core-ci.yml job failed: lint"},
            {"kind": "overlay-ci", "status": "pass", "note": "lint-sweep.yml sweep succeeded"},
            {"kind": "lint", "status": "fail", "note": ""},
        ]
        counts, why = consumption.ci_counts(rules, [], True)
        self.assertEqual((counts["fail"], why), (2, []))  # results read: a red job is a real fail
        counts, why = consumption.ci_counts(
            rules, ["--ci: no run of core-ci.yml found on the default branch"], True
        )
        self.assertEqual((counts["fail"], counts["unverified"], counts["pass"]), (1, 1, 1))
        self.assertTrue(any("core-ci.yml" in w for w in why))
        counts, why = consumption.ci_counts(rules, [], False)
        self.assertEqual(counts["unverified"], 1)
        self.assertTrue(any("not collected" in w for w in why))

    def test_risk_and_adoption(self):
        risks = consumption.risk_levels(MINE["body"])
        self.assertEqual(risks, {"DataTable": "low", "StatusPill": "high"})
        rows = consumption.adoption(
            {"DataTable": "src/a.tsx", "FancyButton": "src/b.tsx", "Other": "src/c.tsx"},
            {"DataTable", "Button"},
            risks,
        )
        self.assertEqual(
            [(r["part"], r["kit_part"], r["relation"], r["risk"]) for r in rows],
            [
                ("DataTable", "DataTable", "duplicates", "low"),
                ("FancyButton", "Button", "extends", None),
            ],
        )


class Feed(Work):
    def make_clone(self, name, files):
        root = self.dir / name
        for rel, text in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        return root

    def setUp(self):
        super().setUp()
        self.core = self.make_clone(
            "core",
            {"CHANGELOG.md": CHANGELOG, "kit/src/Table.tsx": "export function DataTable() {}\n"},
        )
        self.ops = self.make_clone(
            "ops",
            {
                "standards-overlay/standards.lock": "ref=v0.60.0\n",
                "standards-overlay/src/X.tsx": "export function DataTable() {}\n",
            },
        )
        self.vend = self.make_clone("vend", {"src/StatusPill.tsx": "export const StatusPill = 1\n"})
        self.cfg = {
            "ui_consumers": [
                {"repo": "o/ops", "mode": "ops-center", "path": str(self.ops)},
                {"repo": "o/prod", "mode": "workflow"},
                {
                    "repo": "o/vend",
                    "mode": "vendored",
                    "path": str(self.vend),
                    "apply": False,
                    "sync_head": "vendor/",
                },
            ]
        }
        self.gh = fake_gh(
            [MINE, PEER],
            prs_by_repo={
                "o/prod": [
                    {
                        "number": 7,
                        "url": "u7",
                        "headRefName": "chore/core-v0.60.0",
                        "createdAt": "2026-10-21T00:00:00Z",
                        "statusCheckRollup": [{"conclusion": "SUCCESS"}],
                    },
                    {
                        "number": 8,
                        "url": "u8",
                        "headRefName": "feat/other",
                        "createdAt": "2026-10-21T00:00:00Z",
                    },
                ],
                "o/vend": [
                    {
                        "number": 3,
                        "url": "u3",
                        "headRefName": "vendor/core-v0.60.0",
                        "createdAt": "2026-10-21T00:00:00Z",
                        "statusCheckRollup": [{"conclusion": "FAILURE"}],
                    }
                ],
            },
        )
        self.pins = {"o/prod": "v0.58.0", "o/vend": "v0.57.0"}

    def build(self, previous=None):
        return consumption.build(
            self.cfg,
            self.core,
            "owner/core",
            "v0.60.0",
            self.gh,
            previous or {},
            lambda c: self.pins.get(c["repo"], ""),
        )

    def test_schema_and_rows(self):
        data = self.build()
        self.assertEqual(data["format"], "build-standards-consumption/1")
        rows = {r["repo"]: r for r in data["consumers"]}
        ops, prod, vend = rows["o/ops"], rows["o/prod"], rows["o/vend"]
        self.assertEqual(
            (ops["class"], ops["pinned"], ops["behind"], ops["sync_pr"]),
            ("apply-at-once", "v0.60.0", 0, None),
        )
        self.assertEqual(
            (prod["class"], prod["pinned"], prod["behind"]), ("approval-gated", "v0.58.0", 2)
        )
        self.assertEqual((prod["sync_pr"]["number"], prod["sync_pr"]["ci"]), (7, "pass"))
        self.assertIn("no local clone", prod["not_collected"][0])
        self.assertEqual(
            (vend["pinned"], vend["behind"], vend["report_only"]), ("v0.57.0", 3, True)
        )
        self.assertEqual((vend["sync_pr"]["number"], vend["sync_pr"]["ci"]), (3, "fail"))
        self.assertIsNone(vend["status"])
        self.assertEqual([(a["part"], a["risk"]) for a in ops["adoption"]], [("DataTable", "low")])
        self.assertEqual([a["part"] for a in vend["adoption"]], [])
        self.assertEqual([r["id"] for r in data["account"]["awaiting_decision"]], ["D-027"])
        self.assertEqual(data["peers"]["suggestions"][0]["id"], "D-004")

    def test_read_only_gh_calls(self):
        self.build()
        for cmd in self.gh.calls:
            if cmd[0] == "gh":
                self.assertIn(cmd[1:3], (["issue", "list"], ["pr", "list"], ["api", "user"]), cmd)

    def test_update_writes_atomically_and_check_writes_nothing(self):
        state = self.dir / "state"
        info, problems = consumption.update(
            self.cfg, self.core, "owner/core", "v0.60.0", self.gh, state, True, lambda c: ""
        )
        self.assertFalse((state / "consumption.json").exists())
        self.assertEqual(problems, [])
        consumption.update(
            self.cfg, self.core, "owner/core", "v0.60.0", self.gh, state, False, lambda c: ""
        )
        data = json.loads((state / "consumption.json").read_text())
        self.assertEqual(data["format"], consumption.FORMAT)
        self.assertEqual(
            [p.name for p in state.iterdir()], ["consumption.json"]
        )  # no temp file left
        info, _ = consumption.update(
            self.cfg,
            self.core,
            "owner/core",
            "v0.60.0",
            fake_gh(
                [MINE, {**PEER, "body": PEER["body"] + "**D-005 More** (closed by v0.60.0)\n"}]
            ),
            state,
            False,
            lambda c: "",
        )
        self.assertTrue(any("D-005" in i for i in info), info)

    def test_unreadable_gh_is_not_collected(self):
        def broken(cmd, cwd=None, timeout=600):
            return (1, "network down")

        data = consumption.build(
            self.cfg, self.core, "owner/core", "v0.60.0", broken, {}, lambda c: ""
        )
        self.assertTrue(any(n.startswith("peers:") for n in data["not_collected"]))
        self.assertEqual(len(data["consumers"]), 3)


class FeedWithCi(Feed):
    """#117 G-036: the feed runs core-status with --ci, so a green CI never shows as failing rules."""

    def test_feed_runs_core_status_with_ci(self):
        script = self.ops / "standards-overlay" / "scripts" / "core-status.py"
        script.parent.mkdir(parents=True)
        script.write_text("")
        seen = []
        report_json = {
            "summary": {"pass": 3, "fail": 1},
            "ui_adoption": {"status": "adopted"},
            "rules": [
                {"kind": "overlay-ci", "status": "pass", "note": ""},
                {"kind": "overlay-ci", "status": "pass", "note": ""},
                {"kind": "overlay-ci", "status": "fail", "note": "core-ci.yml has no job lint"},
                {"kind": "lint", "status": "pass", "note": ""},
            ],
            "problems": [],
        }
        gh = self.gh

        def sh_(cmd, cwd=None, timeout=600):
            if str(cmd[1]).endswith("core-status.py"):
                seen.append(list(map(str, cmd[2:])))
                return 0, json.dumps(report_json)
            return gh(cmd, cwd, timeout)

        self.gh = sh_
        ops = {r["repo"]: r for r in self.build()["consumers"]}["o/ops"]
        self.assertIn(["--json", "--ci"], seen)
        self.assertEqual((ops["status"]["pass"], ops["status"]["fail"]), (3, 1))
        report_json["problems"] = ["--ci: no run of core-ci.yml found on the default branch"]
        ops = {r["repo"]: r for r in self.build()["consumers"]}["o/ops"]
        self.assertEqual((ops["status"]["fail"], ops["status"]["unverified"]), (0, 1))
        self.assertTrue(any("not collected" in n for n in ops["not_collected"]))


class G031ReportOnlyVendored(Work):
    def test_record_written_and_report_entry_scans_root(self):
        os.environ["CORE_VENDORED_DIR"] = str(self.dir / "vendored")
        self.addCleanup(os.environ.pop, "CORE_VENDORED_DIR")
        pin = self.dir / "pin.txt"
        pin.write_text("v1.0.0\n")
        entry = {
            "repo": "o/r",
            "mode": "vendored",
            "path": str(self.dir),
            "pin": str(pin),
            "apply": False,
        }
        run = nightly.Run(
            {
                "core": str(self.dir),
                "hermes_home": ".",
                "apply": dict(nightly.APPLY_DEFAULTS),
                "ui_consumers": [entry, {"repo": "o/w", "mode": "workflow", "apply": False}],
            },
            False,
            0,
        )
        run.latest_tag = lambda: "v1.1.0"
        seen = []
        run.ui_workflow = lambda c, latest: seen.append(c["repo"])
        run.ui()
        self.assertEqual(seen, [])  # a report-only workflow entry is still not applied
        rec = json.loads((self.dir / "vendored" / "o__r.json").read_text())
        self.assertEqual((rec["release"], rec["behind"]), ("v1.0.0", True))
        e = run.report_entry(entry)
        self.assertEqual((e["overlay"], e["release"]), ("", "v1.0.0"))
        self.assertTrue(e["kit_src"].endswith("kit/src"))
        self.assertEqual(run.pinned_of(entry), "v1.0.0")

    def test_changes_section_lists_the_vendored_release(self):
        old = {"parts": {}, "flags": {}, "status": {}, "ui": "", "release": "v1.0.0"}
        new = {"parts": {}, "flags": {}, "status": {}, "ui": "", "release": "v1.1.0"}
        self.assertEqual(
            report.change_lines(old, new, set()), ["vendored copy release: v1.0.0 -> v1.1.0"]
        )


class G032MovedTableLink(Work):
    def test_raw_gist_md_link_allowed_only_in_that_form(self):
        deny = self.dir / "deny.txt"
        deny.write_text("zebrafox\n")
        os.environ["CORE_PRIVATE_DENYLIST"] = str(deny)
        self.addCleanup(os.environ.pop, "CORE_PRIVATE_DENYLIST")
        ok, bad = self.dir / "ok.md", self.dir / "bad.md"
        ok.write_text(
            "Moved table (40 rows): https://gist.githubusercontent.com/zebrafox/0123456789abcdef0123/raw/c-diff.md\n"
        )
        bad.write_text(
            "https://gist.githubusercontent.com/zebrafox/0123456789abcdef0123/raw/c-diff.txt\n"
        )
        for script in ("check-sanitised.py", "check-consumer-neutral.py"):
            self.assertEqual(
                sh([sys.executable, ROOT / "checks" / script, "--file", ok], cwd=ROOT)[0], 0, script
            )
            self.assertEqual(
                sh([sys.executable, ROOT / "checks" / script, "--file", bad], cwd=ROOT)[0],
                1,
                script,
            )


class Classes(unittest.TestCase):
    def test_setup_names_the_class(self):
        self.assertIn("apply-at-once", setup.class_note({"repo": "o/a", "mode": "ops-center"}))
        for m in ("workflow", "vendored"):
            note = setup.class_note({"repo": "o/a", "mode": m})
            self.assertIn("approval-gated", note)
            self.assertIn("owner's approval", note)

    def test_update_workflow_defaults_to_approve_as_draft(self):
        text = (ROOT / "templates/overlay/.github/workflows/core-update.yml").read_text()
        self.assertIn("vars.CORE_UPDATE_MERGE || 'approve'", text)
        code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
        self.assertIn('if [ "$MERGE" = approve ]; then DRAFT="--draft"; fi', code)
        self.assertLess(code.index("approve) echo"), code.index("merge-pr.py"))

    def test_open_sync_pr_awaits_approval_unless_red(self):
        import datetime as dt

        old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=48)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        for rollup, problem in (
            ([{"conclusion": "SUCCESS"}], False),
            ([{"conclusion": "FAILURE"}], True),
        ):
            run = nightly.Run(
                {
                    "core": ".",
                    "hermes_home": ".",
                    "apply": dict(nightly.APPLY_DEFAULTS),
                    "ui_consumers": [],
                },
                True,
                0,
            )
            run.pinned_ref = lambda repo, overlay: "v1"
            pr = [{"number": 1, "url": "u", "createdAt": old, "statusCheckRollup": rollup}]
            orig = nightly.sh
            nightly.sh = lambda cmd, cwd=None, timeout=600, pr=pr: (0, json.dumps(pr))
            try:
                run.ui_workflow({"repo": "o/p"}, "v2")
            finally:
                nightly.sh = orig
            self.assertEqual(bool(run.problems), problem, (run.problems, run.info))
            if not problem:
                self.assertIn("awaiting owner approval", run.info[0])


if __name__ == "__main__":
    unittest.main()
