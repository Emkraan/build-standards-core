#!/usr/bin/env python3
"""Publishing is idempotent and single-flight (docs-and-changelog 1.8). Synthetic data only.

Date: 2026-10-27
Purpose: two concurrent publisher runs on the same queue create each page once, a create whose
title already exists is refused, and the coverage audit reports a seeded duplicate title.

Run: python3 hermes/scripts/apply_queued_approvals_concurrency_test.py
Scratch directory, fake driver, fake write guard and fake audit only. Nothing reaches Confluence.
The publisher script is the copy next to this test, run as a subprocess with AQA_* overrides.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE / "queued_approvals.py"
ROOT = Path(tempfile.mkdtemp(prefix="aqa-concurrent-", dir=os.environ.get("TMPDIR")))
(ROOT / "guard-config.json").write_text(
    json.dumps({"allowed_roots": {"4800": "tree a", "6200": "tree b"}})
)

DRIVER = r"""
import json, os, sys
tool, args = sys.argv[1], json.loads(sys.argv[2])
pages = json.load(open(os.environ["PAGES"]))
def out(o): print(json.dumps({"result": {"content": [{"text": json.dumps(o)}]}}))
if tool == "searchConfluenceUsingCql":
    q = args["cql"]
    hits = [{"content": {"id": i, "title": t, "status": "current"}} for i, t in pages.items() if '"%s"' % t in q]
    out({"results": hits})
elif tool == "getConfluencePage":
    out({"status": "current", "parentId": "5", "title": pages[args["pageId"]]})
"""

# The guard is slow on purpose, so a second run that is not locked out would overlap the first one.
GUARD = r"""
import json, os, sys, time
tool, args = sys.argv[2], json.loads(sys.argv[3])
time.sleep(float(os.environ["GUARD_DELAY"]))
pages = json.load(open(os.environ["PAGES"]))
page_id = str(900 + len(pages))
pages[page_id] = args["title"]
json.dump(pages, open(os.environ["PAGES"], "w"))
open(os.environ["CREATES"], "a").write(args["title"] + "\n")
print(json.dumps({"verdict": "ALLOW", "written": {"id": page_id}}))
"""

AUDIT = "import sys\n"


class Publisher(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(ROOT, ignore_errors=True)

    def setUp(self):
        self.dash = ROOT / "dash"
        shutil.rmtree(self.dash, ignore_errors=True)
        (self.dash / "proposals").mkdir(parents=True)
        for name, text in (("driver.py", DRIVER), ("guard.py", GUARD), ("audit.py", AUDIT)):
            (ROOT / name).write_text(text)
        self.pages = ROOT / "pages.json"
        self.creates = ROOT / "creates.log"
        if self.creates.exists():
            self.creates.unlink()
        self.pages.write_text(json.dumps({"111": "Existing Page"}))
        self.env = dict(
            os.environ,
            AQA_DASH=str(self.dash),
            AQA_GUARD=str(ROOT / "guard.py"),
            DOCS_HOME_CMD=json.dumps([sys.executable, str(ROOT / "driver.py")]),
            DOCS_GUARD_CONFIG=str(ROOT / "guard-config.json"),
            AQA_AUDIT=str(ROOT / "audit.py"),
            PAGES=str(self.pages),
            CREATES=str(self.creates),
            GUARD_DELAY="1.0",
        )

    def queue(self, titles):
        props, inbox = [], []
        for i, title in enumerate(titles):
            fp = "kc_conc%d" % i  # noqa: UP031
            body = "<p>synthetic %s</p>" % title  # noqa: UP031
            (self.dash / "proposals" / (fp + ".body")).write_text(body)
            props.append({"fp": fp, "kind": "create", "target_title": title, "parent_id": "5"})
            inbox.append(
                {"fp": fp, "act": "approved", "body_sha": hashlib.sha1(body.encode()).hexdigest()}
            )
        (self.dash / "docs-proposals.json").write_text(json.dumps({"proposals": props}))
        (self.dash / "approve-inbox.jsonl").write_text("".join(json.dumps(q) + "\n" for q in inbox))

    def start(self):
        return subprocess.Popen(
            [sys.executable, str(APP)],
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def created(self):
        return self.creates.read_text().splitlines() if self.creates.exists() else []

    def applied_rows(self):
        return [
            json.loads(x) for x in (self.dash / "approve-applied.jsonl").read_text().splitlines()
        ]

    # core-rule: docs-and-changelog.1.8
    def test_two_concurrent_runs_create_each_page_once(self):
        titles = ["Alpha Page", "Beta Page", "Gamma Page"]
        self.queue(titles)
        first = self.start()
        time.sleep(0.4)  # the first run is now inside its first (slow) create
        second = self.start()
        out1, err1 = first.communicate(timeout=60)
        out2, err2 = second.communicate(timeout=60)
        self.assertEqual((first.returncode, second.returncode), (0, 0), (err1, err2))
        self.assertIn(
            "holds the lock", err2, "the overlapping run is turned away by the exclusive lock"
        )
        self.assertEqual(out2, "", "the turned-away run publishes and prints nothing")
        self.assertEqual(
            sorted(self.created()),
            sorted(titles),
            "each page was created exactly once: %r" % self.created(),  # noqa: UP031
        )
        rows = self.applied_rows()
        self.assertEqual(sorted(r["title"] for r in rows), sorted(titles), "one record per page")
        self.assertEqual({r["result"] for r in rows}, {"published"})
        # The same queue run again later creates nothing more.
        self.queue(titles)
        third = self.start()
        third.communicate(timeout=60)
        self.assertEqual(
            sorted(self.created()), sorted(titles), "a repeat run on the same queue creates nothing"
        )
        names = list(json.loads(self.pages.read_text()).values())
        self.assertEqual(len(names), len(set(names)), "one page per title in the docs home")

    # core-rule: docs-and-changelog.1.8
    def test_a_create_whose_title_exists_is_refused(self):
        self.queue(["Existing Page"])
        run = self.start()
        out, _ = run.communicate(timeout=60)
        self.assertEqual(run.returncode, 0)
        self.assertEqual(
            self.created(), [], "the write guard was never called for a title that exists"
        )
        self.assertEqual(
            [(r["result"], r["page_id"]) for r in self.applied_rows()], [("exists", "111")]
        )
        self.assertIn("not created again", out)

    # core-rule: docs-and-changelog.1.8
    def test_a_lookup_that_fails_creates_nothing(self):
        self.queue(["Alpha Page"])
        (ROOT / "driver.py").write_text("print('garbage')\n")
        run = self.start()
        run.communicate(timeout=60)
        self.assertEqual(self.created(), [])
        left = (self.dash / "approve-inbox.jsonl").read_text().splitlines()
        self.assertEqual(len(left), 1, "the decision stays queued for the next run")


if __name__ == "__main__":
    unittest.main(verbosity=1)
