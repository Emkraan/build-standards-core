import importlib.util
import unittest

from support import ROOT

spec = importlib.util.spec_from_file_location("check_changelog", ROOT / "checks/check-changelog.py")
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)

LOCK = ["opscenter/kit/package-lock.json", "opscenter/kit/package.json"]


class DependencyBump(unittest.TestCase):
    def test_a_renovate_manifest_only_change_is_exempt(self):
        self.assertTrue(cc.is_dependency_bump(LOCK, "renovate/python-(non-major)"))

    def test_a_human_branch_is_not_exempt(self):
        self.assertFalse(cc.is_dependency_bump(LOCK, "fix/some-change"))
        self.assertFalse(cc.is_dependency_bump(LOCK, ""))

    def test_a_renovate_branch_touching_other_content_is_not_exempt(self):
        self.assertFalse(cc.is_dependency_bump(LOCK + ["standards/ui.md"], "renovate/x"))

    def test_an_empty_diff_is_not_exempt(self):
        self.assertFalse(cc.is_dependency_bump([], "renovate/x"))


if __name__ == "__main__":
    unittest.main()
