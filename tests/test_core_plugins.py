"""Plugins that ship in the core (hermes/plugins, hermes/desktop-plugins) install from source."""

import json
import unittest

from support import ROOT, Work, load

apply_setup = load("apply_setup_core_plugins", "hermes/apply_setup.py")


class CorePlugins(Work):
    def setUp(self):
        super().setUp()
        self.agent_src = self.dir / "src" / "plugins"
        self.desktop_src = self.dir / "src" / "desktop-plugins"
        self.home = self.dir / "home"
        self.home.mkdir()
        (self.agent_src / "both").mkdir(parents=True)
        (self.agent_src / "both" / "plugin.yaml").write_text("name: both\n")
        (self.agent_src / "both" / "__init__.py").write_text("X = 1\n")
        (self.desktop_src / "both").mkdir(parents=True)
        (self.desktop_src / "both" / "plugin.js").write_text("// both\n")
        (self.desktop_src / "view").mkdir()
        (self.desktop_src / "view" / "plugin.js").write_text("// view\n")
        for name, value in (("PLUGIN_SRC", self.agent_src), ("DESKTOP_SRC", self.desktop_src)):
            old = getattr(apply_setup, name)
            setattr(apply_setup, name, value)
            self.addCleanup(setattr, apply_setup, name, old)

    def setup_for(self, apply):
        s = apply_setup.Setup(self.home, apply=apply, binaries=False)
        self.enabled = set()
        self.enable_calls = []

        def fake_run(cmd):
            self.enable_calls.append(cmd)
            self.enabled.add(cmd[-1])
            return 0, ""

        s.run = fake_run
        s.enabled_plugins = lambda: set(self.enabled)
        return s

    @staticmethod
    def entry(name):
        return {"id": name, "plugin": name, "kind": "plugin", "source": "core", "install_hint": "h"}

    def test_installs_both_halves_and_enables_the_agent_half(self):
        s = self.setup_for(True)
        s.ensure_core_plugin(self.entry("both"))
        self.assertEqual((self.home / "plugins" / "both" / "__init__.py").read_text(), "X = 1\n")
        self.assertEqual(
            (self.home / "desktop-plugins" / "both" / "plugin.js").read_text(), "// both\n"
        )
        self.assertEqual(self.enable_calls, [["hermes", "plugins", "enable", "both"]])
        self.assertTrue(s.restart)
        self.assertEqual(len(s.changed), 1)
        self.assertEqual(s.missing, [])

    def test_second_run_changes_nothing(self):
        self.setup_for(True).ensure_core_plugin(self.entry("both"))
        s = self.setup_for(True)
        self.enabled.add("both")
        s.ensure_core_plugin(self.entry("both"))
        self.assertEqual((s.changed, s.missing, s.restart), ([], [], False))

    def test_desktop_only_plugin_is_never_enabled(self):
        s = self.setup_for(True)
        s.ensure_core_plugin(self.entry("view"))
        self.assertTrue((self.home / "desktop-plugins" / "view" / "plugin.js").is_file())
        self.assertFalse((self.home / "plugins" / "view").exists())
        self.assertEqual(self.enable_calls, [])

    def test_check_mode_reports_and_writes_nothing(self):
        s = self.setup_for(False)
        s.ensure_core_plugin(self.entry("both"))
        self.assertEqual(len(s.missing), 1)
        self.assertIn("differs from the core copy", s.missing[0])
        self.assertFalse((self.home / "plugins").exists())
        self.assertFalse((self.home / "desktop-plugins").exists())

    def test_an_edited_installed_copy_is_replaced(self):
        self.setup_for(True).ensure_core_plugin(self.entry("view"))
        target = self.home / "desktop-plugins" / "view" / "plugin.js"
        target.write_text("// edited by hand\n")
        s = self.setup_for(True)
        s.ensure_core_plugin(self.entry("view"))
        self.assertEqual(target.read_text(), "// view\n")
        self.assertEqual(len(s.changed), 1)
        leftovers = [p.name for p in (self.home / "desktop-plugins").iterdir()]
        self.assertEqual(leftovers, ["view"])

    def test_bytecode_cache_does_not_count_as_a_difference(self):
        self.setup_for(True).ensure_core_plugin(self.entry("both"))
        cache = self.home / "plugins" / "both" / "__pycache__"
        cache.mkdir()
        (cache / "x.cpython-39.pyc").write_bytes(b"\0")
        s = self.setup_for(True)
        self.enabled.add("both")
        s.ensure_core_plugin(self.entry("both"))
        self.assertEqual((s.changed, s.missing), ([], []))

    def test_a_source_that_is_missing_is_reported(self):
        s = self.setup_for(True)
        s.ensure_core_plugin(self.entry("absent"))
        self.assertEqual(len(s.missing), 1)

    # opt-out ---------------------------------------------------------------------------------
    def opt_out_file(self, body):
        text = body if isinstance(body, str) else json.dumps(body)
        (self.home / "core-opt-out.json").write_text(text, encoding="utf8")

    def run_with_opt_out(self, apply=True, names=("both", "view")):
        s = self.setup_for(apply)
        s.load_opt_out(set(names))
        for name in names:
            s.ensure_core_plugin(self.entry(name))
        return s

    def test_an_opted_out_plugin_is_left_alone_and_reported_as_skipped(self):
        self.opt_out_file({"plugins": {"both": "we run our own"}})
        s = self.run_with_opt_out()
        self.assertFalse((self.home / "plugins" / "both").exists())
        self.assertFalse((self.home / "desktop-plugins" / "both").exists())
        self.assertTrue((self.home / "desktop-plugins" / "view" / "plugin.js").is_file())
        self.assertEqual(self.enable_calls, [])
        self.assertEqual(s.missing, [])
        self.assertTrue(s.ok)
        self.assertEqual(len(s.skipped), 1)
        self.assertIn("we run our own", s.skipped[0])
        self.assertIn("SKIPPED both: opted out", "\n".join(s.lines()))

    def test_an_opted_out_plugin_already_installed_is_not_touched(self):
        self.setup_for(True).ensure_core_plugin(self.entry("view"))
        target = self.home / "desktop-plugins" / "view" / "plugin.js"
        target.write_text("// local fork\n")
        self.opt_out_file({"plugins": {"view": "local fork"}})
        s = self.run_with_opt_out(names=("view",))
        self.assertEqual(target.read_text(), "// local fork\n")
        self.assertEqual((s.changed, s.restart), ([], False))

    def test_an_opt_out_applies_in_check_mode_too(self):
        self.opt_out_file({"plugins": {"both": "not here"}})
        s = self.run_with_opt_out(apply=False, names=("both",))
        self.assertEqual((s.missing, s.ok), ([], True))
        self.assertEqual(len(s.skipped), 1)

    def test_a_reason_is_required(self):
        for reason in ("", "   ", None, 3):
            self.opt_out_file({"plugins": {"both": reason}})
            s = self.run_with_opt_out()
            self.assertFalse(s.ok)
            self.assertIn("needs a reason", s.missing[0])
            self.assertFalse((self.home / "plugins").exists())
            self.assertFalse((self.home / "desktop-plugins").exists())

    def test_an_id_the_core_does_not_ship_is_reported_and_installs_nothing(self):
        self.opt_out_file({"plugins": {"typo-plugin": "reason"}})
        s = self.run_with_opt_out()
        self.assertFalse(s.ok)
        self.assertIn("typo-plugin is not a plugin the core ships", s.missing[0])
        self.assertFalse((self.home / "plugins").exists())

    def test_an_unreadable_file_is_reported_and_installs_nothing(self):
        for body in ("{not json", json.dumps({"other": 1}), json.dumps({"plugins": ["both"]})):
            self.opt_out_file(body)
            s = self.run_with_opt_out()
            self.assertFalse(s.ok, body)
            self.assertIn("cannot be read", s.missing[0])
            self.assertFalse((self.home / "plugins").exists(), body)

    def test_no_file_means_no_opt_out(self):
        s = self.run_with_opt_out()
        self.assertEqual((s.skipped, s.missing), ([], []))
        self.assertTrue((self.home / "plugins" / "both").is_dir())

    def test_the_real_plugin_ids_are_accepted_in_the_opt_out(self):
        self.opt_out_file({"plugins": {"session-children": "not run here"}})
        s = apply_setup.Setup(self.home, apply=False, binaries=False)
        s.run = lambda cmd: (1, "")
        s.load_opt_out({"session-children", "session-status"})
        self.assertEqual(s.opt_out, {"session-children": "not run here"})
        self.assertTrue(s.opt_out_ok)

    def test_the_real_registry_entries_resolve_to_shipped_sources(self):
        tools = json.loads((ROOT / "hermes" / "tools.json").read_text(encoding="utf8"))["tools"]
        shipped = [t for t in tools if t.get("source") == "core"]
        self.assertEqual({t["id"] for t in shipped}, {"session-status", "session-children"})
        for t in shipped:
            halves = [
                (ROOT / "hermes" / sub / t["plugin"]).is_dir()
                for sub in ("plugins", "desktop-plugins")
            ]
            self.assertTrue(any(halves), t["id"])
        self.assertTrue(
            (ROOT / "hermes" / "plugins" / "session-children" / "plugin.yaml").is_file()
        )


if __name__ == "__main__":
    unittest.main()
