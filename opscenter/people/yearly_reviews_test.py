"""The yearly review store: edits, steer, reset and undo, the final lock, a drafting job through a fake drafter command,
and the .docx export (skipped when python-docx is not installed)."""

import importlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

PERSON = "Report One"
YEAR = "2098"


class Reviews(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.state = self.root / "state"
        tp = self.state / "team-performance"
        tp.mkdir(parents=True)
        (tp / "team-performance.json").write_text(json.dumps({"engineers": [PERSON]}))
        self._env = {
            k: os.environ.get(k)
            for k in ("OPSCENTER_ROOT", "OPSCENTER_STATE_DIR", "OPSCENTER_PEOPLE_PARAMS")
        }
        os.environ.update(
            OPSCENTER_ROOT=str(self.root),
            OPSCENTER_STATE_DIR=str(self.state),
            OPSCENTER_PEOPLE_PARAMS=str(self.root / "params.json"),
        )
        self.params({"owner_name": "Owen Owner", "team_name": "Team Example"})

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def params(self, d):
        (self.root / "params.json").write_text(json.dumps(d))
        import yearly_reviews

        self.y = importlib.reload(yearly_reviews)

    def keys(self):
        return [s["key"] for s in self.y.template()["sections"]]

    def test_unknown_person_and_year_are_refused(self):
        with self.assertRaises(ValueError):
            self.y.upsert({"year": YEAR, "person": "Nobody", "sections": {}})
        with self.assertRaises(ValueError):
            self.y.upsert({"year": "x", "person": PERSON, "sections": {}})

    def test_the_first_manual_edit_over_drafted_text_keeps_a_version_and_undo_restores_it(self):
        k = self.keys()[0]
        self.y.upsert({"year": YEAR, "person": PERSON, "sections": {k: "drafted"}})
        data = self.y.load()
        data["reviews"][YEAR][PERSON]["meta"][k] = {
            "source": "draft"
        }  # as if a draft job had written it
        self.y._save(data)
        self.y.upsert({"year": YEAR, "person": PERSON, "sections": {k: "my edit"}})
        self.y.upsert(
            {"year": YEAR, "person": PERSON, "sections": {k: "my edit again"}}
        )  # autosave: no new version
        self.assertEqual(len(self.y.load()["reviews"][YEAR][PERSON]["versions"][k]), 1)
        self.y.upsert({"year": YEAR, "person": PERSON, "op": "undo", "section": k})
        self.assertEqual(self.y.load()["reviews"][YEAR][PERSON]["sections"][k], "drafted")

    def test_unknown_section_and_overlong_text_are_refused(self):
        with self.assertRaises(ValueError):
            self.y.upsert({"year": YEAR, "person": PERSON, "sections": {"nope": "x"}})
        with self.assertRaises(ValueError):
            self.y.upsert(
                {
                    "year": YEAR,
                    "person": PERSON,
                    "sections": {self.keys()[0]: "x" * (self.y.MAX_TEXT + 1)},
                }
            )

    def test_final_locks_edits_until_reopened(self):
        k = self.keys()[0]
        self.y.upsert({"year": YEAR, "person": PERSON, "sections": {k: "text"}, "status": "final"})
        with self.assertRaises(self.y.Conflict):
            self.y.upsert({"year": YEAR, "person": PERSON, "sections": {k: "more"}})
        self.y.upsert({"year": YEAR, "person": PERSON, "status": "draft"})
        self.y.upsert({"year": YEAR, "person": PERSON, "sections": {k: "more"}})
        self.assertEqual(self.y.load()["reviews"][YEAR][PERSON]["sections"][k], "more")

    def test_reset_snapshots_first_and_never_deletes(self):
        k = self.keys()[0]
        self.y.upsert({"year": YEAR, "person": PERSON, "sections": {k: "keep me"}})
        self.y.upsert({"year": YEAR, "person": PERSON, "op": "reset"})
        rec = self.y.load()["reviews"][YEAR][PERSON]
        self.assertEqual(rec["sections"].get(k) or "", "")
        self.assertEqual(rec["snapshots"][-1]["record"]["sections"][k], "keep me")

    def test_a_draft_cannot_start_without_a_drafter(self):
        with self.assertRaises(ValueError) as cm:
            self.y.start_job({"year": YEAR, "person": PERSON, "mode": "full"})
        self.assertIn("no drafter is configured", str(cm.exception))

    def test_a_drafting_job_runs_and_its_result_is_applied_under_the_lock(self):
        drafter = self.root / "drafter.py"
        drafter.write_text(
            "import json, os, sys\n"  # noqa: UP031
            "p = sys.argv[sys.argv.index('--job') + 1]\n"
            "j = json.load(open(p))\n"
            "j.update(pid=os.getpid(), state='drafted', result={'sections': {'%s': {'text': 'drafted text', 'evidence': ['e1']}}})\n"
            "json.dump(j, open(p, 'w'))\n" % self.keys()[0]
        )
        self.params({"drafter_cmd": [sys.executable, str(drafter)]})
        job = self.y.start_job({"year": YEAR, "person": PERSON, "mode": "full"})
        jid = job["id"]
        deadline = time.time() + 15
        while time.time() < deadline:
            self.y.apply_finished()
            rec = self.y.load()["reviews"].get(YEAR, {}).get(PERSON)
            if rec and rec["sections"].get(self.keys()[0]) == "drafted text":
                break
            time.sleep(0.2)
        rec = self.y.load()["reviews"][YEAR][PERSON]
        self.assertEqual(rec["sections"][self.keys()[0]], "drafted text")
        self.assertEqual(rec["meta"][self.keys()[0]]["source"], "draft")
        self.assertEqual(rec["draft"]["job"], jid)

    def test_a_dead_drafting_process_fails_its_job(self):
        drafter = self.root / "die.py"
        drafter.write_text(
            "import json, sys\np = sys.argv[sys.argv.index('--job') + 1]\nj = json.load(open(p))\nj.update(pid=99999999, state='drafting')\njson.dump(j, open(p, 'w'))\n"
        )
        self.params({"drafter_cmd": [sys.executable, str(drafter)]})
        job = self.y.start_job({"year": YEAR, "person": PERSON, "mode": "evidence"})
        deadline = time.time() + 15
        state = None
        while time.time() < deadline:
            self.y.apply_finished()
            state = next(j["state"] for j in self.y.jobs()["jobs"] if j["id"] == job["id"])
            if state == "failed":
                break
            time.sleep(0.2)
        self.assertEqual(state, "failed")

    def test_export_docx_names_the_file_and_archives_a_copy(self):
        try:
            import docx  # noqa: F401
        except ImportError:
            if os.environ.get("CI"):
                self.fail("python-docx must be installed in CI (opscenter/people/requirements.txt)")
            self.skipTest("python-docx is not installed")
        k = self.keys()[0]
        self.y.upsert({"year": YEAR, "person": PERSON, "sections": {k: "A line"}})
        name, data = self.y.export_docx(YEAR, PERSON)
        self.assertTrue(name.endswith(".docx") and name.startswith(YEAR))
        self.assertTrue(data[:2] == b"PK")
        self.assertTrue((self.state / "team-performance" / "yearly-reviews" / YEAR / name).exists())


if __name__ == "__main__":
    unittest.main()
