"""architecture-article: derivation, fetching and the gate verdicts. The docs repository is an
injected fetch and its shape script a fixture module, so the real article rules are exercised where
they ship and nothing here touches the network."""

import os
import unittest
from unittest import mock

from support import Work, load

CI = load("core_ci_arch", "templates/overlay/scripts/core-ci.py")

SHAPE = """ROOT = None
STACK_SUPPORT_DIRS = {"templates", "scripts"}


def check_article(path):
    text = path.read_text(encoding="utf-8")
    return [] if "## Purpose" in text else [f"{path.stem}: missing Purpose"]
"""

GOOD = "one two ## Purpose three\n"

UNSET = object()  # run_check default; None is meaningful (the shape script is not there)


class ArchitectureArticle(Work):
    def checkout(self, kind, names):
        base = self.dir / "apps" if kind == "apps" else self.dir
        for n in names:
            (base / n).mkdir(parents=True)
        (self.dir / ".github").mkdir(exist_ok=True)
        return str(self.dir)

    def fetcher(self, articles, shape=UNSET):
        shape = SHAPE if shape is UNSET else shape

        def fetch(path):
            if path.endswith("architecture-docs-compliance.py"):
                return shape
            return articles.get(path)

        return fetch

    def run_check(self, kind, names, articles, shape=UNSET):
        root = self.checkout(kind, names)
        return CI.architecture_findings(
            kind,
            root,
            self.fetcher(articles, SHAPE if shape is UNSET else shape),
            "scripts/architecture-docs-compliance.py",
            "docs/architecture",
        )


class Derivation(ArchitectureArticle):
    def test_apps_derives_the_apps_folders(self):
        slugs, findings = self.run_check("apps", ["studio", "shell"], {})
        self.assertEqual(slugs, ["shell", "studio"])
        self.assertEqual(len(findings), 2)

    def test_stacks_skips_support_and_dot_folders(self):
        slugs, _ = self.run_check("stacks", ["kong", "litellm", "templates", "scripts"], {})
        self.assertEqual(slugs, ["kong", "litellm"])

    def test_a_missing_apps_folder_is_no_systems(self):
        slugs, findings = self.run_check("apps", [], {})
        self.assertEqual((slugs, findings), ([], []))


class Verdicts(ArchitectureArticle):
    def test_a_missing_article_is_a_finding(self):
        _, findings = self.run_check("apps", ["newapp"], {})
        self.assertEqual(len(findings), 1)
        self.assertIn("no architecture article", findings[0])
        self.assertIn("docs/architecture/newapp.md", findings[0])

    def test_a_good_article_passes(self):
        _, findings = self.run_check("apps", ["demo"], {"docs/architecture/demo.md": GOOD})
        self.assertEqual(findings, [])

    def test_a_malformed_article_reports_the_shape_findings(self):
        _, findings = self.run_check(
            "apps", ["demo"], {"docs/architecture/demo.md": "no heading here"}
        )
        self.assertEqual(findings, ["demo: missing Purpose"])

    def test_a_missing_shape_script_is_a_setup_error(self):
        with self.assertRaises(RuntimeError):
            self.run_check("apps", ["demo"], {}, shape=None)


class Command(ArchitectureArticle):
    def setUp(self):
        super().setUp()
        self.lines = []
        patcher = mock.patch.object(CI, "say", self.lines.append)
        patcher.start()
        self.addCleanup(patcher.stop)

    def api(self, articles):
        def one(repo, path, ref, token):
            if path.endswith("architecture-docs-compliance.py"):
                return SHAPE
            return articles.get(path)

        return one

    def test_usage_errors(self):
        self.assertEqual(CI.cmd_architecture_article([]), 2)
        self.assertEqual(CI.cmd_architecture_article(["--kind", "apps"]), 2)
        self.assertEqual(CI.cmd_architecture_article(["--kind", "nope", "--repo", "o/r"]), 2)

    def test_a_missing_token_is_a_setup_error(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(CI.cmd_architecture_article(["--kind", "apps", "--repo", "o/r"]), 2)

    def test_the_command_fails_on_a_missing_article_and_passes_without_one(self):
        root = self.checkout("apps", ["studio", "newapp"])
        env = {"GH_TOKEN": "t"}
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(CI, "api_file", self.api({"docs/architecture/studio.md": GOOD})),
        ):
            code = CI.cmd_architecture_article(["--kind", "apps", "--repo", "o/r", "--root", root])
        self.assertEqual(code, 1)
        self.assertTrue(any("newapp: no architecture article" in ln for ln in self.lines))
        self.lines.clear()
        clean = self.dir / "clean"  # a second checkout, so the first one's folders do not leak
        (clean / "apps" / "demo2").mkdir(parents=True)
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(CI, "api_file", self.api({"docs/architecture/demo2.md": GOOD})),
        ):
            code = CI.cmd_architecture_article(
                ["--kind", "apps", "--repo", "o/r", "--root", str(clean)]
            )
        self.assertEqual(code, 0)
        self.assertTrue(self.lines[-1].endswith("1 system(s), 0 finding(s)"))


if __name__ == "__main__":
    unittest.main()
