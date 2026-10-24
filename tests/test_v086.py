"""Tests for v0.86.0: an ops center sync commits the targets.map copies outside the overlay, and a
repeated failure still prints a line."""

from support import Work, load

ops = load("ops_center_v086", "hermes/ops_center.py")


class TargetPaths(Work):
    def test_destinations_relative_to_the_repo(self):
        ov = self.dir / "standards-overlay"
        ov.mkdir()
        (ov / "targets.map").write_text(
            "# copies\ntokens-core/tokens.css = ../packages/ui/tokens.css\n\n"
            "x.css = ../../outside.css\nkit-core/a.css = kit-core/b.css\n"
        )
        self.assertEqual(
            ops.target_paths(self.dir, "standards-overlay"),
            ["packages/ui/tokens.css", "standards-overlay/kit-core/b.css"],
        )

    def test_no_map(self):
        self.assertEqual(ops.target_paths(self.dir, "standards-overlay"), [])

    def test_overlay_at_root(self):
        (self.dir / "targets.map").write_text("tokens-core/tokens.css = ui/tokens.css\n")
        self.assertEqual(ops.target_paths(self.dir, ""), ["ui/tokens.css"])


class RepeatFailure(Work):
    def test_repeat_failure_is_an_info_line(self):
        nightly = load("nightly_v086", "hermes/nightly.py")
        run = nightly.Run.__new__(nightly.Run)
        run.info, run.problems, run.bare, run.check = [], [], {}, False
        r = {"status": "failed", "report": False, "message": "ui o/r: boom", "bare": ""}
        orig = nightly.ops_center.apply
        nightly.ops_center.apply = lambda *a, **k: r
        try:
            run.ui_ops_center({"repo": "o/r", "path": str(self.dir)}, "v1")
        finally:
            nightly.ops_center.apply = orig
        self.assertEqual(run.problems, [])
        self.assertEqual(run.info, ["ui o/r: boom (still failing, reported before)"])
