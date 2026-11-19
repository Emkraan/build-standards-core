"""Knowledge curation: staged proposals, the applied log, the preview page and the publish mode, over synthetic state files."""

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import knowledge as kn


def sha(text):
    return hashlib.sha1(text.encode()).hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="knowledge-test-"))
        self.dash = self.d / "state" / "dashboard"
        (self.dash / "proposals").mkdir(parents=True)
        self._env = dict(os.environ)
        os.environ.update(
            OPSCENTER_ROOT=str(self.d),
            OPSCENTER_STATE_DIR=str(self.d / "state"),
            KC_DASH=str(self.dash),
        )
        kn.publish_mode.DASH = str(self.dash)
        kn.publish_mode.CONFIG = str(self.dash / "knowledge-curation-config.json")
        kn.publish_mode.CONFIG_LOCK = str(self.dash / ".knowledge-curation-config.lock")

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self.d, ignore_errors=True)

    def stage(self, fp, body="<p>text</p>", **extra):
        (self.dash / "proposals" / f"{fp}.body").write_text(body)
        prop = {"fp": fp, "kind": "create", "target_title": fp, "body_sha": sha(body), **extra}
        path = self.dash / "docs-proposals.json"
        cur = json.loads(path.read_text()) if path.exists() else {"proposals": []}
        cur["proposals"].append(prop)
        path.write_text(json.dumps(cur))
        return prop

    def applied_line(self, row):
        with open(self.dash / "approve-applied.jsonl", "a") as f:
            f.write(json.dumps(row) + "\n")


class Empty(Base):
    def test_a_consumer_that_never_ran_the_job_gets_empty_answers_not_errors(self):
        self.assertEqual(kn.applied(), {"applied": []})
        c = kn.curation()
        self.assertEqual((c["proposals"], c["mode"]), ([], "staged"))
        m = kn.publish_modes()
        self.assertTrue(m["classes"])
        self.assertTrue(all(x["mode"] == "staged" for x in m["classes"]))
        self.assertEqual(m["digest"], [])


class Curation(Base):
    def test_a_staged_proposal_is_listed_with_its_fields(self):
        self.stage("kc_a", target_title="Page A", summary="adds a row")
        p = kn.curation()["proposals"]
        self.assertEqual([x["fp"] for x in p], ["kc_a"])
        self.assertEqual(p[0]["summary"], "adds a row")

    def test_a_decision_the_applier_recorded_for_this_content_is_not_pending_again(self):
        prop = self.stage("kc_done")
        self.stage("kc_open")
        self.applied_line({"fp": "kc_done", "result": "published", "body_sha": prop["body_sha"]})
        self.assertEqual([x["fp"] for x in kn.curation()["proposals"]], ["kc_open"])

    def test_a_restaged_body_comes_back_after_an_outcome_for_the_old_one(self):
        self.stage("kc_re", body="<p>new</p>")
        self.applied_line({"fp": "kc_re", "result": "published", "body_sha": sha("<p>old</p>")})
        self.assertEqual([x["fp"] for x in kn.curation()["proposals"]], ["kc_re"])

    def test_a_send_back_note_rides_on_its_proposal_and_marks_it_pending(self):
        self.stage("kc_fb")
        (self.dash / "proposal-feedback.json").write_text(
            json.dumps(
                {
                    "feedback": {
                        "kc_fb": {
                            "reason": "shorter",
                            "at": "2026-11-18T10:00:00Z",
                            "status": "open",
                        }
                    }
                }
            )
        )
        fb = kn.curation()["proposals"][0]["feedback"]
        self.assertEqual((fb["reason"], fb["pending"]), ("shorter", True))

    def test_unreadable_files_read_as_empty(self):
        (self.dash / "docs-proposals.json").write_text("{not json")
        (self.dash / "approve-applied.jsonl").write_text(
            "garbage\n" + json.dumps({"fp": "x", "result": "ok"}) + "\n"
        )
        self.assertEqual(kn.curation()["proposals"], [])
        self.assertEqual([r["fp"] for r in kn.applied()["applied"]], ["x"])


class Preview(Base):
    def test_the_preview_is_an_html_page_with_a_policy_that_runs_nothing(self):
        self.stage("kc_p", body="<p>hello</p><script>alert(1)</script>")
        code, data, ctype, headers = kn.preview("kc_p")
        self.assertEqual((code, ctype), (200, "text/html; charset=utf-8"))
        self.assertIn(b"<p>hello</p>", data)
        csp = headers["Content-Security-Policy"]
        self.assertIn("default-src 'none'", csp)
        self.assertNotIn("script-src", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

    def test_an_unknown_or_hostile_fp_is_a_key_error(self):
        (self.d / "secret.body").write_text("secret")
        for bad in ("", "nope", "../secret", "..%2Fsecret", ".hidden", "a/b", "a\\b"):
            with self.assertRaises(KeyError, msg=bad):
                kn.preview(bad)


class Modes(Base):
    def test_setting_a_mode_persists_and_returns_the_new_state(self):
        cls = kn.publish_modes()["classes"][0]["id"]
        out = kn.set_publish_mode({"class": cls, "mode": "auto"})
        self.assertEqual({x["id"]: x["mode"] for x in out["classes"]}[cls], "auto")
        self.assertEqual({x["id"]: x["mode"] for x in kn.publish_modes()["classes"]}[cls], "auto")

    def test_a_bad_mode_is_a_value_error_and_an_unknown_class_a_key_error(self):
        cls = kn.publish_modes()["classes"][0]["id"]
        with self.assertRaises(ValueError):
            kn.set_publish_mode({"class": cls, "mode": "yolo"})
        with self.assertRaises(KeyError):
            kn.set_publish_mode({"class": "nope", "mode": "auto"})

    def test_the_digest_lists_what_auto_published(self):
        cls = kn.publish_modes()["classes"][0]["id"]
        self.applied_line(
            {
                "fp": "kc_x",
                "result": "published",
                "title": "Changelog",
                "when": "2026-11-18T09:00:00Z",
                "mode": "auto",
                "class": cls,
            }
        )
        self.assertIn("digest", kn.publish_modes())


if __name__ == "__main__":
    unittest.main()
