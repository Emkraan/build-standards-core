import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import review_acted as ra  # noqa: E402

HEAD = "a" * 40


class ReviewActed(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self._old = ra.STORE
        ra.STORE = Path(self._d.name) / "review-acted.json"

    def tearDown(self):
        ra.STORE = self._old
        self._d.cleanup()

    def test_a_merged_pr_is_hidden_at_its_head_and_comes_back_on_a_new_push(self):
        ra.record("o/r", 7, HEAD, "merged", note="done", title="t")
        tomb = ra.active("o/r")
        self.assertTrue(ra.hides(tomb, 7, HEAD))
        self.assertTrue(ra.hides(tomb, 7, None))
        self.assertFalse(ra.hides(tomb, 7, "b" * 40))  # a different head is new work
        self.assertFalse(ra.hides(tomb, 8, HEAD))
        self.assertFalse(ra.hides(tomb, "x", HEAD))

    def test_tombstones_are_per_repo(self):
        ra.record("o/a", 7, HEAD, "approved")
        self.assertEqual(list(ra.active("o/a")), [7])
        self.assertEqual(ra.active("o/b"), {})

    def test_a_tombstone_expires_after_its_ttl(self):
        ra.record("o/r", 7, HEAD, "merged")
        old = dict(ra.TTL_S)
        ra.TTL_S["merged"] = 0.01
        try:
            time.sleep(0.05)
            self.assertEqual(ra.active("o/r"), {})
            self.assertEqual(list(ra.missed("o/r")), [7])  # expired with the PR possibly still open
        finally:
            ra.TTL_S.clear()
            ra.TTL_S.update(old)

    def test_every_write_bumps_the_generation(self):
        g = ra.generation()
        ra.record("o/r", 7, HEAD, "closed")
        self.assertEqual(ra.generation(), g + 1)

    def test_note_and_title_are_bounded(self):
        ra.record("o/r", 7, HEAD, "merged", note="n" * 999, title="t" * 999)
        rec = ra.active("o/r")[7]
        self.assertEqual((len(rec["note"]), len(rec["title"])), (300, 200))

    def test_a_damaged_store_reads_as_empty(self):
        ra.STORE.write_text("{nope")
        self.assertEqual(ra.active("o/r"), {})
        ra.record("o/r", 7, HEAD, "merged")
        self.assertEqual(list(ra.active("o/r")), [7])


if __name__ == "__main__":
    unittest.main()
