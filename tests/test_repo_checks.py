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

    def test_rc002_sha_in_body_built_on_neighbouring_line(self):
        self.passes(
            "RC002",
            {
                "ops/m.sh": 'body=$(jq -n --arg sha "$HEAD" \'{merge_method:"squash",sha:$sha}\')\n'
                'gh api -X PUT repos/o/r/pulls/1/merge --input - <<< "$body"\n',
                "ops/n.sh": "gh api -X PUT repos/o/r/pulls/1/merge \\\n  --input <(jq -n --arg sha \"$H\" '{sha:$sha}')\n",
            },
        )

    def test_rc002_sha_not_adjacent_is_still_flagged(self):
        self.fails(
            "RC002",
            {
                "ops/m.sh": "sha=abc\n\ngh api -X PUT repos/o/r/pulls/1/merge -f merge_method=squash\n"
            },
        )

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

    def test_rc012_httpx_is_declared(self):
        self.passes(
            "RC012",
            {"app/main.py": "import httpx\n", "requirements.txt": "# http client\nhttpx==0.27.0\n"},
        )

    def test_rc012_tomllib_is_standard_library_on_any_interpreter(self):
        self.passes("RC012", {"app/main.py": "import tomllib\n"})

    def test_rc012_url_lines_skipped_not_names(self):
        self.put(
            {
                "app/main.py": "import httpx\n",
                "requirements.txt": "https://example.test/x.whl\n-r other.txt\ngit+https://example.test/r.git\n",
            }
        )
        self.assertIn("import httpx", self.run_check("RC012")[0][2])

    def test_rc012_pyproject_extras_bracket(self):
        pyproject = (
            "[project]\nname = 'x'\ndependencies = [\n"
            '  "uvicorn[standard]>=0.30",  # server\n  "httpx>=0.27",\n  \'pydantic[email]>=2\',\n]\n'
            '[project.optional-dependencies]\ndev = ["pytest>=8"]\n'
            '[dependency-groups]\nlint = ["ruff"]\n'
        )
        self.passes(
            "RC012",
            {
                "app/main.py": "import uvicorn, httpx, pydantic, pytest, ruff\n",
                "pyproject.toml": pyproject,
                "uv.lock": "",
            },
        )

    def test_rc012_pyproject_fallback_parser(self):
        text = (
            '[project]\ndependencies = [\n  "uvicorn[standard]>=0.30",\n  "httpx>=0.27", # c\n]\n'
            '[project.optional-dependencies]\nx = ["aaa[b,c]"]\n[dependency-groups]\ng = ["ggg"]\n'
        )
        data = rc._pyproject_fallback(text)
        self.assertEqual(
            data["project"]["dependencies"], ["uvicorn[standard]>=0.30", "httpx>=0.27"]
        )
        self.assertEqual(data["project.optional-dependencies"]["x"], ["aaa[b,c]"])
        self.assertEqual(data["dependency-groups"]["g"], ["ggg"])

    def test_rc012_pywin32_alias(self):
        self.passes(
            "RC012",
            {
                "svc/run.py": "import win32serviceutil, win32api, win32con, pythoncom\n",
                "requirements.txt": "# windows service\nPyWin32==306\n",
            },
        )

    def test_rc012_alias_needs_the_distribution(self):
        self.fails("RC012", {"svc/run.py": "import win32api\nimport yaml\n"})

    def test_rc012_google_family_alias(self):
        self.passes(
            "RC012",
            {
                "a/m.py": "from google.cloud import storage\n",
                "requirements.txt": "# gcs\ngoogle-cloud-storage==2.0\n",
            },
        )

    def test_rc012_hashed_pip_tools_file_is_a_lock(self):
        hashed = (
            "# autogenerated by pip-compile\nhttpx==0.27.0 \\\n    --hash=sha256:aa \\\n    --hash=sha256:bb\n"
            "    # via -r requirements.in\nidna==3.0 \\\n    --hash=sha256:cc\n"
        )
        pyproject = "[project]\nname = 'x'\ndependencies = ['httpx>=0.27']\n"
        for home in ("requirements.txt", "requirements/prod.txt", "locks/app.lock.txt"):
            self.put({"app/main.py": "import httpx\n", "pyproject.toml": pyproject, home: hashed})
            self.assertEqual(self.run_check("RC012"), [], home)
            (self.dir / home).unlink()

    def test_rc012_partly_hashed_file_is_not_a_lock(self):
        partial = "httpx==0.27.0 \\\n    --hash=sha256:aa\nidna==3.0\n"
        pyproject = "[project]\nname = 'x'\ndependencies = ['httpx>=0.27']\n"
        self.put(
            {
                "app/main.py": "import httpx\n",
                "pyproject.toml": pyproject,
                "constraints.txt": partial,
            }
        )
        self.assertIn("no lock file", self.run_check("RC012")[0][2])

    def test_rc012_plain_requirements_is_not_a_lock(self):
        pyproject = "[project]\nname = 'x'\ndependencies = ['httpx>=0.27']\n"
        self.put(
            {
                "app/main.py": "import httpx\n",
                "pyproject.toml": pyproject,
                "requirements.txt": "# http\nhttpx==0.27.0\n",
            }
        )
        self.assertIn("no lock file", self.run_check("RC012")[0][2])

    def test_rc012_docx_and_more_aliases(self):
        pairs = {
            "docx": "python-docx",
            "pptx": "python-pptx",
            "fitz": "pymupdf",
            "zmq": "pyzmq",
            "nacl": "pynacl",
            "dns": "dnspython",
            "grpc": "grpcio",
            "slugify": "python-slugify",
            "websocket": "websocket-client",
            "PIL": "pillow",
            "yaml": "pyyaml",
        }
        for mod, dist in pairs.items():
            self.put(
                {
                    "app/main.py": f"import {mod}\n",
                    "requirements.txt": f"# reason\n{dist}==1.0\n",
                }
            )
            self.assertEqual(self.run_check("RC012"), [], mod)

    def test_rc002_test_files_are_not_production(self):
        bad = "import subprocess\nsubprocess.run(['gh', 'pr', 'merge', '1'])\n"
        files = {
            "pkg/foo_test.py": bad,
            "pkg/test_foo.py": bad,
            "pkg/conftest.py": bad,
            "test/a.py": bad,
            "tests/b.py": bad,
        }
        self.passes("RC002", files)
        self.fails("RC002", {"pkg/prod.py": bad})

    def test_rc012_import_alias_gaps(self):
        pairs = {
            "googleapiclient": "google-api-python-client",
            "google_auth_oauthlib": "google-auth-oauthlib",
            "google_auth_httplib2": "google-auth-httplib2",
            "oauth2client": "oauth2client",
            "httplib2": "httplib2",
            "markdown": "Markdown",
            "magic": "python-magic",
            "Crypto": "pycryptodome",
            "git": "GitPython",
            "ldap": "python-ldap",
            "pkg_resources": "setuptools",
            "mpl_toolkits": "matplotlib",
            "skimage": "scikit-image",
            "google.protobuf": "protobuf",
            "google.oauth2": "google-auth",
            "google.auth": "google-auth",
            "google.cloud.storage": "google-cloud-storage",
        }
        for mod, dist in pairs.items():
            self.put(
                {
                    "app/main.py": f"import {mod}\n",
                    "requirements.txt": f"# reason\n{dist}==1.0\n",
                }
            )
            self.assertEqual(self.run_check("RC012"), [], mod)

    def test_rc012_google_protobuf_needs_protobuf(self):
        self.fails(
            "RC012",
            {
                "a/m.py": "from google.protobuf import message\n",
                "requirements.txt": "# x\nrequests==2\n",
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


class TestBatch3(Tree):
    UI = {"src/App.tsx": "export const A = () => <AppShell rail={<BuildCard />} />;\n"}

    def test_rc014_needs_axe_and_both_themes(self):
        self.put(self.UI)
        self.assertTrue(self.run_check("RC014"))
        self.fails("RC014", {"e2e/a.spec.ts": "test('x', () => { page.goto('/') })\n"})
        self.put(
            {"e2e/a.spec.ts": "import AxeBuilder from '@axe-core/playwright';\nconst t = 'dark';\n"}
        )
        self.assertIn("both", self.run_check("RC014")[0][2])

    def test_rc014_clean_and_no_ui(self):
        self.passes(
            "RC014",
            {
                **self.UI,
                "e2e/a.spec.ts": "import AxeBuilder from 'x/axe-core';\nfor (const t of ['light', 'dark']) {}\n",
            },
        )
        shutil.rmtree(self.dir / "src")
        shutil.rmtree(self.dir / "e2e")
        self.assertEqual(self.run_check("RC014"), [])

    def test_rc015_shell_without_build_card(self):
        self.fails("RC015", {"src/App.tsx": "export const A = () => <AppShell />;\n"})

    def test_rc015_clean(self):
        self.passes("RC015", {**self.UI})

    def test_rc016_verify_script(self):
        self.fails("RC016", {"package.json": json.dumps({"scripts": {"build": "x"}})})
        self.put(
            {
                "package.json": json.dumps(
                    {"scripts": {"verify": "npm run build", "check:unicode": "x", "test": "y"}}
                )
            }
        )
        found = self.run_check("RC016")
        self.assertEqual(
            sorted(f[2] for f in found),
            ["the verify script does not run check:unicode", "the verify script does not run test"],
        )

    def test_rc016_clean_with_script_file(self):
        self.passes(
            "RC016",
            {
                "package.json": json.dumps(
                    {"scripts": {"verify": "node scripts/verify.mjs", "check:a": "x", "build": "y"}}
                ),
                "scripts/verify.mjs": "run('pnpm run check:a'); run('pnpm run build');\n",
            },
        )

    def test_rc017_secret_in_argv(self):
        self.fails(
            "RC017", {"t.py": "import subprocess\nsubprocess.run(['tool', '--password', pw])\n"}
        )
        self.fails("RC017", {"t.py": "import subprocess\nsubprocess.run(['tool', api_token])\n"})

    def test_rc017_wrapped_safe_suffix_names_pass(self):
        self.passes(
            "RC017",
            {
                "t.py": "import subprocess, os\nfrom pathlib import Path\nsubprocess.run(['cp', str(SECRETS_SRC), Path(SECRETS_DIR), os.fspath(TOKEN_FILE), os.path.join(SECRETS_DIR, TOKEN_PATH)])\n"
            },
        )

    def test_rc017_wrapped_secret_still_fails(self):
        self.fails(
            "RC017", {"t.py": "import subprocess\nsubprocess.run(['tool', str(api_token)])\n"}
        )

    def test_rc017_secret_name_is_not_the_secret(self):
        self.passes(
            "RC017",
            {
                "t.py": "import subprocess\n"
                'subprocess.run(["az", "keyvault", "secret", "show", "--vault-name", v, "-n", args.secret])\n'
                'subprocess.run(["tool", "--secret-name", args.secret, "--secret_name", token_name, secret_id])\n'
            },
        )
        self.fails(
            "RC017",
            {"t.py": "import subprocess\nsubprocess.run(['tool', '-x', args.secret])\n"},
        )

    def test_rc017_fstring_per_expression(self):
        self.passes(
            "RC017",
            {
                "t.py": "import subprocess\n"
                'subprocess.run(["git", "show", f"origin/main:{SECRETS_PATH}"])\n'
            },
        )
        self.fails(
            "RC017", {"t.py": 'import subprocess\nsubprocess.run(["tool", f"{api_token}"])\n'}
        )
        self.fails(
            "RC017", {"t.py": 'import subprocess\nsubprocess.run(["tool", f"x:{api_token}"])\n'}
        )

    def test_rc002_prose_is_not_a_command(self):
        self.passes(
            "RC002",
            {
                "t.py": '"""Run gh pr merge 1 by hand."""\n\n\ndef f():\n    """Never gh pr merge --auto."""\n'
                '    # gh pr merge 2\n    "gh pr merge 3"\n'
            },
        )
        self.fails(
            "RC002",
            {
                "t.py": '"""doc"""\nimport subprocess\nsubprocess.run(["gh", "pr", "merge", "1"])\n',
                "s.sh": "gh pr merge 1 --squash\n",
            },
        )

    def test_rc002_implicit_concatenation_is_one_string(self):
        self.passes(
            "RC002",
            {
                "t.py": "import subprocess\nsubprocess.run(\n    'gh pr merge 1 --squash '\n    '--match-head-commit abc',\n    shell=True,\n)\n"
            },
        )
        self.fails(
            "RC002",
            {
                "t.py": "import subprocess\nsubprocess.run(\n    'gh pr merge 1 '\n    '--squash',\n    shell=True,\n)\n"
            },
        )

    def test_rc017_clean(self):
        self.passes(
            "RC017",
            {
                "t.py": "import subprocess\nsubprocess.run(['tool', '--password-stdin'], input=pw)\nsubprocess.run(['tool', '--token-file', path])\nsubprocess.run(['ls', name])\n"
            },
        )

    def test_rc018_vendor_chunks(self):
        self.fails("RC018", {"vite.config.ts": "export default {};\n"})
        self.passes(
            "RC018",
            {
                "vite.config.ts": "export default { build: { rollupOptions: { output: { manualChunks: {} } } } };\n"
            },
        )


class TestBatch4(Tree):
    def test_rc019_budget(self):
        self.fails("RC019", {"vite.config.ts": "export default {};\n"})
        self.passes(
            "RC019",
            {
                "vite.config.ts": "x\n",
                "package.json": json.dumps({"scripts": {"check:size": "size-limit"}}),
            },
        )
        shutil.rmtree(self.dir / "package.json", ignore_errors=True)

    def test_rc019_no_bundler(self):
        self.passes("RC019", {"package.json": "{}"})

    def test_rc020_inline_limit(self):
        self.fails("RC020", {"vite.config.ts": "export default {};\n"})
        self.passes(
            "RC020", {"vite.config.ts": "export default { build: { assetsInlineLimit: 0 } };\n"}
        )

    def test_rc021_bearer_in_many_client_files(self):
        h = "fetch(u, { headers: { Authorization: `Bearer ${t}` } });\n"
        self.fails("RC021", {"apps/a/src/api.ts": h, "apps/a/src/other.ts": h})

    def test_rc021_clean(self):
        h = "fetch(u, { headers: { Authorization: `Bearer ${t}` } });\n"
        self.passes(
            "RC021",
            {
                "apps/a/src/api.ts": h,
                "apps/b/src/api.ts": h,
                "apps/a/server/x.ts": h,
                "apps/a/server/y.ts": h,
            },
        )

    def test_rc022_permissions_by_hand(self):
        h = "if (user.permissions.includes('x')) {}\n"
        self.fails("RC022", {"apps/a/src/a.ts": h, "apps/a/src/b.ts": h})
        shutil.rmtree(self.dir / "apps")
        self.passes("RC022", {"apps/a/src/a.ts": h, "apps/b/src/b.ts": h})


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
        self.assertEqual(len(kit), 9)
        self.assertTrue(all(r["check"]["kind"] == "core-ci" for r in kit))

    def test_enforced_tag_drops_an_untagged_test_proof(self):
        st = load("core_status_tag", "templates/overlay/scripts/core-status.py")
        (self.dir / "t.py").write_text("# nothing\n")
        (self.dir / "standards-local").mkdir()
        (self.dir / "standards-local" / "proofs.json").write_text(
            json.dumps({"a.1": {"kind": "test", "ref": "t.py"}})
        )
        st.repo_root = lambda: self.dir
        st.PROOFS = self.dir / "standards-local" / "proofs.json"
        reg = {"rules": [{"id": "a.1", "check": {"kind": "test"}}]}
        good, problems = st.load_proofs(reg)
        self.assertEqual((sorted(good), problems, len(st.PROOF_WARNINGS)), (["a.1"], [], 1))
        st.PROOF_TAG_ENFORCED = True
        good, problems = st.load_proofs(reg)
        self.assertEqual((good, len(problems)), ({}, 1))

    def test_unknown_check_is_unverified_not_pass(self):
        st = load("core_status_rc2", "templates/overlay/scripts/core-status.py")
        rule = {"ref": "a.md 1", "check": {"kind": "repo-check", "id": "RC999"}}
        self.assertEqual(st.repo_check_status(rule, {})[0], "unverified")


if __name__ == "__main__":
    unittest.main()
