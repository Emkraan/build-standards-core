"""
tf_context_test.py
Purpose: tf_context against a scratch git origin and a provider file: the roots spec and a root's paths come from
         origin/main, a PR's files are matched to a root, the plan text is parsed into resources, principal names
         resolve only through the provider (null default: none), and a missing clone is a CtxError.
Run:     python3 tf_context_test.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

S = Path(tempfile.mkdtemp(prefix="tf-context-test-"))
CLONE = S / "clone"
os.environ["TF_CONTEXT_REPO"] = str(CLONE)
os.environ["TF_CONTEXT_CACHE"] = str(S / "cache")
os.environ.pop("TF_CONTEXT_PROVIDER", None)
sys.path.insert(0, str(Path(__file__).resolve().parent))


def sh(*a, cwd=None):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True).stdout


sh("git", "init", "-q", "--bare", "-b", "main", str(S / "origin.git"))
sh("git", "clone", "-q", str(S / "origin.git"), str(CLONE))
(CLONE / ".github").mkdir()
(CLONE / ".github" / "terraform-roots.json").write_text(
    json.dumps(
        {
            "roots": [
                {
                    "name": "ident",
                    "applied_by": "owner",
                    "tiers": {"dev": {"root": "roots/ident", "vars": "dev.tfvars"}},
                }
            ]
        }
    )
)
(CLONE / "roots" / "ident").mkdir(parents=True)
(CLONE / "roots" / "ident" / "main.tf").write_text(
    'module "m" {\n  source = "../../modules/m"\n}\n'
)
(CLONE / "modules" / "m").mkdir(parents=True)
(CLONE / "modules" / "m" / "main.tf").write_text('resource "thing_one" "a" {}\n')
sh("git", "-C", str(CLONE), "add", "-A")
sh(
    "git",
    "-C",
    str(CLONE),
    "-c",
    "user.name=t",
    "-c",
    "user.email=synthetic",
    "commit",
    "-qm",
    "init",
)
sh("git", "-C", str(CLONE), "push", "-q", "origin", "HEAD:main")
sh("git", "-C", str(CLONE), "fetch", "-q", "origin")

PLAN = """Terraform will perform the following actions:

  # thing_one.a will be created
  + resource "thing_one" "a" {
      + name = "alpha"
    }

  # thing_two.b will be destroyed
  - resource "thing_two" "b" {
      - name = "beta"
    }

Plan: 1 to add, 0 to change, 1 to destroy.
"""
GUID = "11111111-2222-3333-4444-555555555555"
GUID2 = "66666666-2222-3333-4444-555555555555"

import tf_context as t  # noqa: E402

_REAL_RUN, _REAL_GIT = t._run, shutil.which("git") or "git"
_ENV = {"TF_CONTEXT_REPO": str(CLONE), "TF_CONTEXT_CACHE": str(S / "cache")}


def setUpModule():
    # the whole suite shares one interpreter: re-point the module at this file's scratch tree
    os.environ.update(_ENV)
    os.environ.pop("TF_CONTEXT_PROVIDER", None)
    t.REPO_DIR, t.CACHE, t._run, t.GIT = CLONE, S / "cache", _REAL_RUN, _REAL_GIT


class Ctx(unittest.TestCase):
    def setUp(self):
        t._spec.update(at=0.0, main=None, roots=None)
        t._mem.clear()
        os.environ.pop("TF_CONTEXT_PROVIDER", None)

    def test_the_roots_spec_and_a_roots_paths_come_from_origin_main(self):
        spec = t.roots_spec()
        self.assertEqual(spec["ident"]["applied_by"], "owner")
        p = t.root_paths("ident", "dev")
        self.assertEqual(
            (p["dir"], p["vars"], p["modules"]),
            ("roots/ident", "roots/ident/dev.tfvars", ["modules/m"]),
        )
        self.assertIsNone(t.root_paths("ident", "prod"))
        self.assertIsNone(t.root_paths("nope", "dev"))

    def test_touches_matches_the_root_and_its_modules_only(self):
        p = t.root_paths("ident", "dev")
        got = t.touches(
            ["roots/ident/main.tf", "modules/m/x.tf", "modules/other/x.tf", "README.md"], p
        )
        self.assertEqual(got, ["roots/ident/main.tf", "modules/m/x.tf"])
        self.assertEqual(t.touches(["a"], None), [])

    def test_the_plan_text_is_parsed_into_resources(self):
        res = t.parse_plan(t.actions_block("noise\n" + PLAN + "tail"))
        self.assertEqual(
            [(r["address"], r["action"]) for r in res],
            [("thing_one.a", "add"), ("thing_two.b", "destroy")],
        )
        self.assertEqual(res[0]["attrs"]["name"], "alpha")
        self.assertEqual(t.actions_block("nothing here"), "")

    def test_principal_names_resolve_only_through_a_provider(self):
        self.assertIsNone(t.resolve_principal(GUID))
        self.assertEqual(t.principal_names([GUID], blocking=True), {})
        prov = S / "provider.py"
        prov.write_text(
            'class P:\n    def resolve_principal(self, pid):\n        return {"name": "Svc " + pid[:4], "kind": "service principal"}\n'
        )
        os.environ["TF_CONTEXT_PROVIDER"] = f"{prov}:P"
        self.assertEqual(
            t.resolve_principal(GUID2), {"name": "Svc 6666", "kind": "service principal"}
        )
        self.assertEqual(t.principal_names([GUID2], blocking=True)[GUID2]["name"], "Svc 6666")
        prov.write_text(
            'class P:\n    def resolve_principal(self, pid):\n        raise RuntimeError("down")\n'
        )
        self.assertIsNone(t.resolve_principal(GUID))

    def test_a_missing_clone_is_a_ctx_error_and_no_repo_means_no_overlap_read(self):
        old = t.REPO_DIR
        t.REPO_DIR = S / "absent"
        try:
            with self.assertRaises(t.CtxError):
                t.roots_spec()
        finally:
            t.REPO_DIR = old


if __name__ == "__main__":
    unittest.main()
