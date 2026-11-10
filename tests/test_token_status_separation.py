"""Status inks stay distinguishable under simulated deuteranopia (tokens/build.py)."""

import json
import unittest

from support import ROOT, load

build = load("tokens_build", "tokens/build.py")


def model():
    return build.Model(json.loads((ROOT / "tokens" / "tokens.json").read_text(encoding="utf8")))


class CiedeTests(unittest.TestCase):
    def test_reference_pair_from_the_published_test_data(self):
        d = build.ciede2000((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485))
        self.assertAlmostEqual(d, 2.0425, places=3)

    def test_identical_colours_are_zero(self):
        self.assertEqual(build.ciede2000((60.0, 10.0, 10.0), (60.0, 10.0, 10.0)), 0.0)


class SeparationTests(unittest.TestCase):
    def test_every_status_pair_passes_in_both_modes(self):
        rows = build.status_separation(model())
        self.assertEqual(len(rows), 20)
        self.assertEqual([r for r in rows if not r[4]], [])

    def test_documented_light_mode_urgent_distances(self):
        rows = {(r[0], r[1], r[2]): r[3] for r in build.status_separation(model())}
        self.assertAlmostEqual(rows[("light", "warning", "urgent")], 5.2, delta=0.1)
        self.assertAlmostEqual(rows[("light", "urgent", "danger")], 5.7, delta=0.1)

    def test_a_pair_under_the_minimum_is_reported(self):
        saved = build.STATUS_MIN_SEPARATION
        build.STATUS_MIN_SEPARATION = 100.0
        try:
            rows = build.status_separation(model())
        finally:
            build.STATUS_MIN_SEPARATION = saved
        self.assertTrue(all(not r[4] for r in rows))


if __name__ == "__main__":
    unittest.main()
