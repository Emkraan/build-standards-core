"""repo_checks.py: every check fails on a violation and passes on the clean case, core-status turns a
finding into a failing rule, and the registry binds each check to exactly one rule."""

import json
import shutil
import unittest

from support import ROOT, WORK, load

rc = load("repo_checks", "templates/overlay/scripts/repo_checks.py")
check_rules = load("check_rules_for_test", "checks/check-rules.py")
SCRIPTS = ROOT / "templates/overlay/scripts"
# Built from parts so no literal address on a real domain sits in the source.
PK = "p" + "kill"  # split so the repo does not match its own RC001 check
REAL = "mail" + "box" + ".io"


class Tree(unittest.TestCase):
    def setUp(self):
        self.dir = WORK / f"rc-{self.id().rsplit('.', 1)[-1]}"
        shutil.rmtree(self.dir, ignore_errors=True)
        self.dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def put(self, files):
        for k, v in files.items():
            p = self.dir / k
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(v, encoding="utf8")

    def run_check(self, cid):
        return rc.run(cid, self.dir)

    def fails(self, cid, files):
        self.put(files)
        found = self.run_check(cid)
        self.assertTrue(found, f"{cid} should report a finding")
        return found

    def passes(self, cid, files):
        self.put(files)
        self.assertEqual(self.run_check(cid), [], f"{cid} should be clean")


class TestChecks(Tree):
    def test_rc001_kill_by_name(self):
        self.fails("RC001", {"ops/stop.sh": PK + " -f worker\n"})

    def test_rc001_clean_and_marker(self):
        self.passes(
            "RC001",
            {
                "ops/stop.sh": 'kill "$(cat run.pid)"\n# ' + PK + " is banned here\n",
                "ops/legacy.sh": PK + " -f x  # core-exception: EXC-001\n",
            },
        )

    def test_rc002_gh_merge_without_sha(self):
        self.fails(
            "RC002",
            {
                ".github/workflows/m.yml": "jobs:\n  a:\n    steps:\n      - run: gh pr merge 1 --squash\n"
            },
        )

    def test_rc002_continuation_and_api(self):
        self.fails("RC002", {"ops/m.sh": "gh api repos/o/r/pulls/1/merge -X PUT\n"})

    def test_rc002_python_list(self):
        self.fails("RC002", {"tools/m.py": 'run(["gh", "pr", "merge", "1", "--squash"])\n'})

    def test_rc002_clean(self):
        self.passes(
            "RC002",
            {
                ".github/workflows/m.yml": '      - run: |\n          gh pr merge 1 --squash \\\n            --match-head-commit "$SHA"\n',
                "ops/m.sh": "gh api repos/o/r/pulls/1/merge -X PUT -f sha=$SHA\n",
                "tools/m.py": 'run(["gh", "pr", "merge", "1", "--match-head-commit", sha])\n',
                "docs.yml": "# gh pr merge --auto is never used\n",
                "tests/test_m.py": 'x = ["gh", "pr", "merge"]\n',
            },
        )

    def test_rc003_major_automerge(self):
        self.fails("RC003", {"renovate.json": json.dumps({"automerge": True})})
        self.fails(
            "RC003",
            {
                "renovate.json": json.dumps(
                    {"packageRules": [{"matchUpdateTypes": ["major", "minor"], "automerge": True}]}
                )
            },
        )

    def test_rc003_clean(self):
        self.passes(
            "RC003",
            {
                "renovate.json": json.dumps(
                    {
                        "automerge": True,
                        "packageRules": [{"matchUpdateTypes": ["major"], "automerge": False}],
                    }
                )
            },
        )
        self.put({"renovate.json": json.dumps({"major": {"automerge": False}, "automerge": True})})
        self.assertEqual(self.run_check("RC003"), [])

    def test_rc004_trusted_trigger_checks_out_pr(self):
        wf = (
            "on:\n  pull_request_target:\njobs:\n  a:\n    steps:\n"
            "      - uses: actions/checkout@abc\n        with:\n          ref: ${{ github.event.pull_request.head.sha }}\n"
        )
        self.fails("RC004", {".github/workflows/g.yml": wf})

    def test_rc004_clean(self):
        trusted = "on:\n  pull_request_target:\njobs:\n  a:\n    steps:\n      - uses: actions/checkout@abc\n"
        pr = (
            "on:\n  pull_request:\njobs:\n  a:\n    steps:\n      - uses: actions/checkout@abc\n"
            "        with:\n          ref: ${{ github.event.pull_request.head.sha }}\n"
        )
        self.passes("RC004", {".github/workflows/a.yml": trusted, ".github/workflows/b.yml": pr})

    def test_rc005_platform_cors(self):
        self.fails(
            "RC005",
            {
                "vercel.json": '{"headers":[{"headers":[{"key":"Access-Control-Allow-Origin","value":"*"}]}]}'
            },
        )
        self.fails(
            "RC005",
            {
                "infra/app.tf": 'site_config {\n  cors {\n    allowed_origins = ["https://x"]\n  }\n}\n'
            },
        )

    def test_rc005_clean(self):
        self.passes(
            "RC005",
            {"vercel.json": '{"headers":[{"headers":[{"key":"X-Frame-Options","value":"DENY"}]}]}'},
        )

    def test_rc006_deploy_needs_queue_and_health(self):
        self.put({"app/db.py": "import sqlite3\n"})
        self.fails(
            "RC006", {".github/workflows/deploy.yml": "name: deploy\njobs:\n  a:\n    steps: []\n"}
        )

    def test_rc006_cancel_in_progress(self):
        wf = "concurrency:\n  group: deploy\n  cancel-in-progress: true\njobs:\n  a:\n    steps:\n      - run: curl health | grep ${{ github.sha }}\n"
        self.put({"app/db.py": "import sqlite3\n"})
        found = self.fails("RC006", {".github/workflows/deploy.yml": wf})
        self.assertIn("queue", found[0][2])

    def test_rc006_clean_and_not_sqlite(self):
        wf = "concurrency:\n  group: deploy\n  cancel-in-progress: false\njobs:\n  a:\n    steps:\n      - run: curl health | grep ${{ github.sha }}\n"
        self.passes("RC006", {"app/db.py": "import sqlite3\n", ".github/workflows/deploy.yml": wf})
        shutil.rmtree(self.dir / "app")
        (self.dir / ".github/workflows/deploy.yml").write_text("name: deploy\n")
        self.assertEqual(self.run_check("RC006"), [])

    def test_rc006_static_vercel_deploy_is_carved_out_but_a_stateful_one_is_not(self):
        self.put({"app/db.py": "import sqlite3\n"})
        static = "name: deploy\njobs:\n  a:\n    steps:\n      - run: npx vercel deploy --prod\n"
        stateful = static + "      - run: docker compose up -d\n"
        self.passes("RC006", {".github/workflows/deploy-site.yml": static})
        self.fails("RC006", {".github/workflows/deploy-api.yml": stateful})

    def test_rc007_destructive_migrations(self):
        for sql in (
            "DROP TABLE users;",
            "ALTER TABLE t ADD COLUMN c TEXT NOT NULL;",
            "ALTER TABLE t RENAME COLUMN a TO b;",
            "DELETE FROM t;",
            "TRUNCATE t;",
        ):
            self.dir.joinpath("db").mkdir(exist_ok=True)
            self.put({"db/migrations/001.sql": sql + "\n"})
            self.assertTrue(self.run_check("RC007"), sql)

    def test_rc007_clean(self):
        self.passes(
            "RC007",
            {
                "db/migrations/001.sql": "-- DROP TABLE old;\nCREATE TABLE t (a TEXT);\nALTER TABLE t ADD COLUMN c TEXT NOT NULL DEFAULT '';\nDELETE FROM t WHERE a = 1;\n",
                "src/drop.sql": "DROP TABLE x;\n",
            },
        )

    def test_rc008_fixture_email(self):
        self.fails("RC008", {"tests/fixtures/people.json": '{"mail": "jane.doe@' + REAL + '"}'})

    def test_rc008_clean(self):
        self.passes(
            "RC008",
            {
                "tests/fixtures/people.json": '{"mail": "a@example'
                + ".test"
                + '", "b": "b@corp.example.com", "pkg": "x@1.2.3"}',
                "src/real.json": '{"mail": "a@' + REAL + '"}',
            },
        )

    def test_rc009_two_files_handle_redirect(self):
        self.fails(
            "RC009",
            {
                "apps/a/boot.ts": "await msal.handleRedirectPromise();\n",
                "apps/b/main.ts": "await app.handleRedirectPromise();\n",
            },
        )

    def test_rc009_clean(self):
        self.passes(
            "RC009",
            {
                "packages/boot/boot.ts": "await msal.handleRedirectPromise();\n",
                "apps/a/boot.test.ts": "handleRedirectPromise()\n",
            },
        )

    def test_rc010_undocumented_secret(self):
        self.fails(
            "RC010",
            {
                ".github/workflows/a.yml": "env:\n  K: ${{ secrets.MY_DEPLOY_KEY }}\n  T: ${{ secrets.GITHUB_TOKEN }}\n",
                "README.md": "none\n",
            },
        )

    def test_rc010_clean(self):
        self.passes(
            "RC010",
            {
                ".github/workflows/a.yml": "env:\n  K: ${{ secrets.MY_DEPLOY_KEY }}\n",
                "docs/ops.md": "| `MY_DEPLOY_KEY` | repo |\n",
            },
        )


class TestBatch2(Tree):
    def test_rc011_cross_repo_checkout_needs_ssh_key(self):
        bad = "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@abc\n        with:\n          repository: o/other\n      - run: x\n"
        self.fails("RC011", {".github/workflows/a.yml": bad})

    def test_rc011_clean(self):
        ok = (
            "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@abc\n        with:\n          repository: o/other\n          ssh-key: ${{ secrets.K }}\n"
            "      - uses: actions/checkout@abc\n        with:\n          repository: ${{ github.repository }}\n"
        )
        self.passes("RC011", {".github/workflows/a.yml": ok})

    def test_rc012_unlisted_third_party_import(self):
        self.fails("RC012", {"app/main.py": "import requests\nimport os\n"})

    def test_rc012_unpinned_and_reasonless(self):
        self.put({"app/main.py": "import requests\n", "requirements.txt": "requests\n"})
        self.assertIn("not pinned", self.run_check("RC012")[0][2])
        self.put({"requirements.txt": "requests==2.0\n"})
        self.assertIn("no reason", self.run_check("RC012")[0][2])

    def test_rc012_clean(self):
        self.passes(
            "RC012",
            {
                "app/main.py": "import os, yaml\nfrom app import util\nfrom . import x\n",
                "app/util.py": "",
                "requirements.txt": "# config files\nPyYAML==6.0\n",
            },
        )

    def test_rc013_deploy_needs_ci_and_health(self):
        self.fails(
            "RC013",
            {
                ".github/workflows/deploy-api.yml": "name: deploy\njobs:\n  a:\n    steps:\n      - run: docker compose up -d\n"
            },
        )

    def test_rc013_clean_and_static(self):
        ok = "name: deploy\njobs:\n  t:\n    steps:\n      - run: npm test\n  d:\n    needs: t\n    steps:\n      - run: docker compose up -d && curl health\n"
        self.passes(
            "RC013",
            {
                ".github/workflows/deploy-api.yml": ok,
                ".github/workflows/deploy-site.yml": "jobs:\n  a:\n    steps:\n      - run: npx vercel deploy\n",
            },
        )


class TestWiring(Tree):
    def test_every_check_is_registered_once_with_a_matching_ref(self):
        reg = json.loads((ROOT / "standards/rules.json").read_text(encoding="utf8"))["rules"]
        bound = {}
        for r in reg:
            if r["check"]["kind"] == "repo-check":
                bound.setdefault(r["check"]["id"], []).append(r["ref"])
        self.assertEqual(sorted(bound), sorted(rc.CHECKS))
        for cid, refs in bound.items():
            self.assertEqual(refs, [rc.CHECKS[cid][1]], cid)

    def test_the_shipped_overlay_and_the_core_pass_their_own_checks(self):
        # The overlay folder is copied into every consumer, so a check that flagged its own scripts would turn
        # every consumer red; the core is held to the rules it ships.
        for root in (ROOT / "templates" / "overlay", ROOT):
            found = {k: v for k, v in rc.run_all(root).items() if v}
            self.assertEqual(found, {}, str(root))

    def test_overlay_scripts_ship_repo_checks(self):
        corehash = load("corehash_rc", "templates/overlay/scripts/corehash.py")
        self.assertIn("repo_checks.py", corehash.OVERLAY_SCRIPTS)

    def test_core_ci_command_with_a_missing_test_file_is_caught(self):
        cmd = "npm --prefix kit test -- tests/does-not-exist.test.tsx"
        self.assertTrue(check_rules.core_ci_test_missing(cmd, ROOT))
        self.assertFalse(
            check_rules.core_ci_test_missing("npm --prefix kit test -- tests/toast.test.tsx", ROOT)
        )
        self.assertFalse(check_rules.core_ci_test_missing("python3 tokens/build.py --check", ROOT))

    def test_core_status_fails_then_passes_a_repo_check_rule(self):
        st = load("core_status_rc", "templates/overlay/scripts/core-status.py")
        rule = {"ref": "automation-safety.md 1.9", "check": {"kind": "repo-check", "id": "RC001"}}
        root = self.dir
        (root / "x.sh").write_text(PK + " -f a\n")
        st.repo_root = lambda: root
        status, n, note = st.repo_check_status(rule, {})
        self.assertEqual((status, n), ("fail", 1))
        self.assertIn("x.sh:1", note)
        self.assertEqual(st.repo_check_status(rule, {rule["ref"]: ["EXC-001"]})[0], "excepted")
        (root / "x.sh").write_text('kill "$PID"\n')
        self.assertEqual(st.repo_check_status(rule, {})[0], "pass")

    def test_registry_marks_the_kit_proofs_as_needing_adoption(self):
        reg = json.loads((ROOT / "standards/rules.json").read_text(encoding="utf8"))["rules"]
        kit = [r for r in reg if r["check"].get("requires") == "ui-adoption"]
        self.assertEqual(len(kit), 5)
        self.assertTrue(all(r["check"]["kind"] == "core-ci" for r in kit))

    def test_unknown_check_is_unverified_not_pass(self):
        st = load("core_status_rc2", "templates/overlay/scripts/core-status.py")
        rule = {"ref": "a.md 1", "check": {"kind": "repo-check", "id": "RC999"}}
        self.assertEqual(st.repo_check_status(rule, {})[0], "unverified")


if __name__ == "__main__":
    unittest.main()
