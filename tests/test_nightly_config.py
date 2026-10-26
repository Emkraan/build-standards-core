import json
import unittest

from support import Work, load

nightly = load("nightly_mod", "hermes/nightly.py")


class Migration(Work):
    def write(self, cfg):
        p = self.dir / "consumer.json"
        p.write_text(json.dumps(cfg))
        return p

    def test_v1_migrated_with_backup_and_note(self):
        v1 = {
            "core": "/c",
            "apply": {"hermes": True, "binaries": True, "ui": True},
            "ui_consumers": [{"repo": "o/r", "mode": "local", "path": "/p"}],
        }
        p = self.write(v1)
        notes = []
        cfg = nightly.load_config(p, notes)
        self.assertEqual(cfg["version"], 2)
        self.assertEqual(cfg["ui_consumers"][0]["mode"], "direct")
        self.assertEqual(json.loads(p.read_text())["version"], 2)
        self.assertEqual(json.loads((self.dir / "consumer.json.v1.bak").read_text()), v1)
        self.assertEqual(len(notes), 1)
        self.assertIn("migrated", notes[0])

    def test_v2_is_left_alone(self):
        p = self.write({"version": 2, "core": "/c", "apply": {"claude": True}, "ui_consumers": []})
        notes = []
        cfg = nightly.load_config(p, notes)
        self.assertEqual(notes, [])
        self.assertFalse((self.dir / "consumer.json.v1.bak").exists())
        self.assertTrue(cfg["apply"]["claude"])

    def test_missing_apply_defaults(self):
        cfg = nightly.load_config(self.dir / "absent.json")
        self.assertEqual(
            cfg["apply"],
            {
                "hermes": True,
                "binaries": True,
                "ui": True,
                "claude": False,
                "safe_restart": False,
                "report": True,
                "consumption": True,
            },
        )

    def test_explicit_v1_claude_choice_kept(self):
        p = self.write({"apply": {"claude": True}})
        self.assertTrue(nightly.load_config(p, [])["apply"]["claude"])


class Dispatch(unittest.TestCase):
    def run_ui(self, mode):
        run = nightly.Run(
            {
                "core": ".",
                "hermes_home": ".",
                "apply": dict(nightly.APPLY_DEFAULTS),
                "ui_consumers": [{"repo": "o/r", "mode": mode}],
            },
            True,
            0,
        )
        seen = []
        run.latest_tag = lambda: "v9"
        for m in ("workflow", "direct", "vendored"):
            setattr(run, "ui_" + m, lambda c, latest, m=m: seen.append(m))
        run.ui()
        return seen, run.problems

    def test_modes(self):
        self.assertEqual(self.run_ui("workflow")[0], ["workflow"])
        self.assertEqual(self.run_ui("direct")[0], ["direct"])
        self.assertEqual(self.run_ui("vendored")[0], ["vendored"])

    def test_local_alias(self):
        self.assertEqual(self.run_ui("local")[0], ["direct"])

    def test_unknown_mode_is_a_problem(self):
        seen, problems = self.run_ui("bogus")
        self.assertEqual(seen, [])
        self.assertIn("unknown mode", problems[0])

    def test_claude_skipped_quietly_without_cli(self):
        run = nightly.Run(
            {"core": ".", "hermes_home": ".", "apply": {"claude": True}, "ui_consumers": []},
            True,
            0,
        )
        nightly.shutil.which, real = (lambda n: None), nightly.shutil.which
        try:
            run.claude()
        finally:
            nightly.shutil.which = real
        self.assertEqual((run.info, run.problems), ([], []))

    def test_claude_off_by_default(self):
        cfg = nightly.load_config(__import__("pathlib").Path("absent.json"))
        self.assertFalse(cfg["apply"]["claude"])


class Vendored(Work):
    def test_record_written_on_machine_and_read_by_status(self):
        import os

        os.environ["CORE_VENDORED_DIR"] = str(self.dir / "vendored")
        self.addCleanup(os.environ.pop, "CORE_VENDORED_DIR")
        core = self.dir / "core"
        (core / "standards").mkdir(parents=True)
        (core / "standards" / "a.md").write_text("x")
        run = nightly.Run(
            {"core": str(core), "hermes_home": ".", "apply": {}, "ui_consumers": []}, False, 0
        )
        pin = self.dir / "pin.txt"
        pin.write_text("v1.2.3\n")  # the vendoring tool's pin: the release the copy carries
        entry = {"repo": "o/r", "path": str(self.dir), "pin": str(pin)}
        run.ui_vendored(entry, "v1.2.3")
        rec = json.loads((self.dir / "vendored" / "o__r.json").read_text())
        self.assertEqual((rec["release"], rec["behind"]), ("v1.2.3", False))
        status = load("core_status", "templates/overlay/scripts/core-status.py")
        self.assertEqual(status.vendored_record("o/r"), rec)
        self.assertIsNone(status.vendored_record("o/none"))
        run.info.clear()
        run.ui_vendored(entry, "v1.2.3")
        self.assertEqual(run.info, [])  # unchanged record, no output


class SetupLegacyScripts(Work):
    def test_only_core_written_wrappers_are_removed(self):
        setup = load("setup_mod", "hermes/setup.py")
        scripts = self.dir / "scripts"
        scripts.mkdir()
        (scripts / "core-skills-sync.sh").write_text(
            "# Written by build-standards-core hermes/setup.py\n"
        )
        (scripts / "core-lockstep.sh").write_text("# the consumer own script\n")
        self.assertEqual(setup.legacy_scripts(self.dir), [scripts / "core-skills-sync.sh"])


class SetupRequiredChecks(Work):
    def test_workflow_repo_without_required_checks_is_flagged(self):
        setup = load("setup_rc", "hermes/setup.py")
        entries = [
            {"repo": "o/gated", "mode": "workflow"},
            {"repo": "o/open", "mode": "workflow"},
            {"repo": "o/local", "mode": "direct"},
            {"repo": "o/err", "mode": "workflow"},
        ]

        def lookup(repo):
            if repo == "o/err":
                raise RuntimeError("no access")
            return ({"ascii"} if repo == "o/gated" else set()), []

        gaps = setup.unguarded(entries, lookup)
        self.assertEqual([g.split(":")[0] for g in gaps], ["o/open", "o/err"])


if __name__ == "__main__":
    unittest.main()
