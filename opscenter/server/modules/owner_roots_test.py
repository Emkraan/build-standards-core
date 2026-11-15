"""
owner_roots_test.py
Purpose: The owner-applied roots flow against a real scratch git origin and a fake terraform script: plan keeps a saved plan
         and pins its digest, a clean plan clears the card, apply refuses a changed or wrong-digest plan, runs the
         provider's before and after hooks around the apply and verifies with a fresh plan, a failed apply stays on the
         card with its kind and repeats raise one item, a hook that cannot restore fails loudly, the identity check
         stops a plan, the request route validates, and with no provider nothing cloud specific happens.
Run:     python3 owner_roots_test.py
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

S = Path(tempfile.mkdtemp(prefix="owner-roots-test-"))
ORIGIN, CLONE, TF, STATE = S / "origin.git", S / "clone", S / "terraform", S / "tf-state"
PROVIDER = S / "provider.py"


def sh(*a, cwd=None):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True).stdout


SPEC = {
    "state_backend": {"container": "tfstate", "tiers": {"dev": {"account": "acct-dev"}}},
    "roots": [
        {
            "name": "ident",
            "applied_by": "owner",
            "tiers": {"dev": {"root": "roots/ident", "key": "ident.tfstate"}},
        },
        {
            "name": "other",
            "applied_by": "tfapply",
            "tiers": {"dev": {"root": "roots/other", "key": "o.tfstate"}},
        },
    ],
}
sh("git", "init", "-q", "--bare", "-b", "main", str(ORIGIN))
sh("git", "clone", "-q", str(ORIGIN), str(CLONE))
(CLONE / ".github").mkdir()
(CLONE / ".github" / "terraform-roots.json").write_text(json.dumps(SPEC))
(CLONE / "roots" / "ident").mkdir(parents=True)
(CLONE / "roots" / "ident" / "main.tf").write_text("# synthetic\n")
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

# fake terraform: plan exits 2 (changes) unless the state file says applied; apply marks it applied
TF.write_text(
    "#!/bin/sh\n"
    f"STATE={str(STATE)!r}\n"
    'case "$1" in\n'
    '  init) echo "$@" >> "$STATE.init"; exit 0;;\n'
    '  plan) out=""; for a in "$@"; do case "$a" in -out=*) out="${a#-out=}";; esac; done\n'
    '        if [ -f "$STATE.applied" ]; then exit 0; fi\n'
    '        echo "plan-bytes" > "$out"; exit 2;;\n'
    '  show) echo \'{"resource_changes":[{"address":"a.b","type":"a","change":{"actions":["create"]}},'
    '{"address":"c.d","type":"c","change":{"actions":["delete"],"before":{"id":"res-1|x"}}}]}\'; exit 0;;\n'
    '  apply) if [ -f "$STATE.fail" ]; then echo "Error: boom $(cat $STATE.fail)" >&2; exit 1; fi\n'
    '         touch "$STATE.applied"; echo "Apply complete! Resources: 1 added."; exit 0;;\n'
    "esac\n"
)
TF.chmod(TF.stat().st_mode | stat.S_IEXEC)
PROVIDER_SRC = """
import json, pathlib
LOG = pathlib.Path("@HOOKS@")


def _w(line):
    with LOG.open("a") as f:
        f.write(line + "\\n")


class P:
    expected_identity = "admin-account"

    def identity(self):
        return pathlib.Path("@WHO@").read_text().strip()

    def backend_args(self, ts, b):
        return ["-backend-config=account=" + b["account"], "-backend-config=container=" + b["container"]]

    def before_apply(self, deletes, log):
        _w("before " + json.dumps(deletes))
        return {"lifted": deletes}

    def after_apply(self, state, log):
        _w("after " + json.dumps(state))
        fail = pathlib.Path("@FAIL@").exists()
        return (len(state["lifted"]), ["could not restore x"] if fail else [])

    def error_kinds(self):
        return [("quota", "QuotaExceeded", "Raise the quota first.")]
"""
PROVIDER.write_text(
    PROVIDER_SRC.replace("@HOOKS@", str(S / "hooks.log"))
    .replace("@WHO@", str(S / "who"))
    .replace("@FAIL@", str(S / "hooks.fail"))
)

ENV = {
    "OWNER_ROOTS_CACHE": str(S / "cache"),
    "OWNER_ROOTS_REPO": str(CLONE),
    "OWNER_ROOTS_TF": str(TF),
    "OWNER_ROOTS_DECISIONS": str(S / "decisions.jsonl"),
    "OWNER_ROOTS_RETRY_S": "0",
}
import importlib  # noqa: E402

o = None
_saved = {}


def setUpModule():
    """The module reads its environment at import: set it, load the module fresh, undo all of it afterwards."""
    global o
    for k in list(ENV) + ["OWNER_ROOTS_PROVIDER"]:
        _saved[k] = os.environ.get(k)
    os.environ.update(ENV)
    for k in ["OWNER_ROOTS_PROVIDER"]:
        os.environ.pop(k, None)
    import owner_roots

    o = importlib.reload(owner_roots)


def tearDownModule():
    for k, v in _saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    import owner_roots

    importlib.reload(owner_roots)


DIGEST = "pending"


def reset():
    for p in S.glob("tf-state*"):
        p.unlink()
    for n in ("hooks.log", "hooks.fail", "decisions.jsonl"):
        (S / n).unlink(missing_ok=True)
    o.STATUS.unlink(missing_ok=True)
    (S / "who").write_text("admin-account")


class Flow(unittest.TestCase):
    def setUp(self):
        reset()
        os.environ["OWNER_ROOTS_PROVIDER"] = f"{PROVIDER}:P"

    def item(self):
        return o._load_status()["items"]["ident:dev"]

    def test_plan_keeps_the_saved_plan_and_pins_its_digest(self):
        o.plan_all()
        it = self.item()
        self.assertEqual(
            (it["state"], it["counts"]["add"], it["counts"]["destroy"]), ("pending", 1, 1)
        )
        self.assertEqual(len(it["plan_sha256"]), 64)
        self.assertNotIn("other:dev", o._load_status()["items"])  # not applied_by owner
        self.assertTrue((o.PLANS / "ident-dev.tfplan").exists())
        init = Path(str(STATE) + ".init").read_text()
        self.assertIn("-backend-config=account=acct-dev", init)
        self.assertIn("-backend-config=key=ident.tfstate", init)

    def test_a_wrong_identity_stops_the_plan(self):
        (S / "who").write_text("other-account")
        o.plan_all()
        it = self.item()
        self.assertEqual(it["state"], "auth")
        self.assertIn("not admin-account", it["error"])

    def test_apply_runs_the_hooks_applies_exactly_the_saved_plan_and_verifies(self):
        o.plan_all()
        it = self.item()
        o.apply("ident", "dev", it["plan_sha256"])
        after = self.item()
        self.assertEqual(after["state"], "clean")
        self.assertTrue(after["last_apply"]["verified"])
        self.assertEqual(after["last_apply"]["locks_restored"], 1)
        self.assertEqual(
            (S / "hooks.log").read_text().splitlines(),
            ['before ["res-1"]', 'after {"lifted": ["res-1"]}'],
        )
        decisions = [
            json.loads(x)["decision"] for x in (S / "decisions.jsonl").read_text().splitlines()
        ]
        self.assertEqual(
            decisions, ["owner_apply_started", "owner_apply_done", "owner_apply_verified"]
        )

    def test_a_wrong_digest_or_a_changed_plan_file_is_refused(self):
        o.plan_all()
        o.apply("ident", "dev", "0" * 64)
        self.assertEqual(self.item()["state"], "error")
        self.assertIn("saved plan changed", self.item()["error"])
        o.plan_all()
        digest = self.item()["plan_sha256"]
        (o.PLANS / "ident-dev.tfplan").write_text("tampered")
        o.apply("ident", "dev", digest)
        self.assertIn("does not match what the owner reviewed", self.item()["error"])
        self.assertFalse((Path(str(STATE) + ".applied")).exists())

    def test_a_failed_apply_stays_on_the_card_and_a_repeat_raises_one_alert(self):
        raised = []
        import automation_actions

        saved = automation_actions.raise_item
        automation_actions.raise_item = lambda *a, **k: raised.append((a, k))
        try:
            Path(str(STATE) + ".fail").write_text("QuotaExceeded in region")
            for _ in range(2):
                o.plan_all()
                o.apply("ident", "dev", self.item()["plan_sha256"])
            it = self.item()
            self.assertEqual(
                (it["state"], it["apply_failures"]["kind"], it["apply_failures"]["count"]),
                ("error", "quota", 2),
            )
            self.assertIn("QuotaExceeded", it["last_apply_error"]["message"])
            self.assertEqual(len(raised), 1)
            view = [x for x in o.get()["items"] if x["key"] == "ident:dev"][0]
            self.assertEqual(
                (view["error_kind"], view["error_next"]), ("quota", "Raise the quota first.")
            )
        finally:
            automation_actions.raise_item = saved

    def test_a_hook_that_cannot_restore_fails_loudly_and_wins_over_the_apply_result(self):
        (S / "hooks.fail").write_text("x")
        o.plan_all()
        o.apply("ident", "dev", self.item()["plan_sha256"])
        it = self.item()
        self.assertEqual(it["state"], "error")
        self.assertIn("LOCKS NOT RESTORED", it["error"])
        self.assertEqual(o.classify_error(it["error"])[0], "locks_not_restored")

    def test_a_clean_plan_clears_the_card(self):
        Path(str(STATE) + ".applied").write_text("")
        o.plan_all()
        self.assertEqual(self.item()["state"], "clean")
        self.assertIsNone(self.item()["plan_sha256"])


class Requests(unittest.TestCase):
    def setUp(self):
        reset()
        os.environ["OWNER_ROOTS_PROVIDER"] = f"{PROVIDER}:P"
        o.plan_all()

    def test_apply_needs_the_digest_the_typed_name_and_a_known_root(self):
        it = o._load_status()["items"]["ident:dev"]
        self.assertEqual(o.request({"name": "nope", "tier": "dev"}, "apply")[0], 404)
        self.assertEqual(
            o.request({"name": "ident", "tier": "dev", "plan_sha256": "x"}, "apply")[0], 409
        )
        code, body = o.request(
            {"name": "ident", "tier": "dev", "plan_sha256": it["plan_sha256"], "confirm": "wrong"},
            "apply",
        )
        self.assertEqual(code, 400)
        self.assertIn("ident", body["error"])
        self.assertEqual(o.request({}, "unknown")[0], 404)

    def test_get_phases_a_pending_plan_as_needs_me(self):
        view = o.get()
        self.assertEqual([x["phase"] for x in view["items"]], ["needs_me"])
        self.assertEqual(len(o.needs_me(view)), 1)


class NullDefault(unittest.TestCase):
    def setUp(self):
        reset()
        os.environ.pop("OWNER_ROOTS_PROVIDER", None)

    def test_no_provider_means_no_identity_check_no_backend_args_and_no_hooks(self):
        o.plan_all()
        it = o._load_status()["items"]["ident:dev"]
        self.assertEqual(it["state"], "pending")
        self.assertEqual(
            Path(str(STATE) + ".init").read_text().strip(),
            "init -input=false -reconfigure -no-color -backend-config=key=ident.tfstate",
        )
        o.apply("ident", "dev", it["plan_sha256"])
        self.assertEqual(o._load_status()["items"]["ident:dev"]["state"], "clean")
        self.assertFalse((S / "hooks.log").exists())

    def test_a_bad_provider_is_refused(self):
        os.environ["OWNER_ROOTS_PROVIDER"] = "no-colon"
        with self.assertRaises(o.ProviderRefused):
            o.provider()
        os.environ.pop("OWNER_ROOTS_PROVIDER")

    def test_error_classes_are_generic(self):
        self.assertEqual(o.classify_error("sign-in expired")[0], "signin")
        self.assertEqual(o.classify_error("Error acquiring the state lock")[0], "state_lock")
        self.assertEqual(o.classify_error("HTTP 403 Forbidden")[0], "forbidden")
        self.assertEqual(o.classify_error("something else")[0], "other")


class StaleSavedPlan(unittest.TestCase):
    """Layout standard rule 12: a stale saved plan re-plans at once and is only a failure if changes remain."""

    key = "ident:dev"

    def setUp(self):
        reset()
        os.environ["OWNER_ROOTS_PROVIDER"] = f"{PROVIDER}:P"
        self.saved = (o.plan, o._close_alert, o._log)
        self.closed, self.logged, self.plans = [], [], []
        o._close_alert = lambda n, t, reason: self.closed.append((n, t))
        o._log = lambda rec: self.logged.append(rec)
        o._update(self.key, name="ident", tier="dev", state="pending", last_apply_error=None)

    def tearDown(self):
        o.plan, o._close_alert, o._log = self.saved

    def fake_plan(self, state):
        def run(name, tier, sha=None):
            self.plans.append((name, tier))
            o._update(o._key(name, tier), state=state)

        o.plan = run

    def item(self):
        return o._load_status()["items"][self.key]

    def test_clean_replan_clears_the_card_and_closes_the_alert(self):
        self.fake_plan("clean")
        msg = "terraform apply failed: Error: Saved plan is stale"
        self.assertTrue(o._replan_after_stale("ident", "dev", self.key, msg))
        it = self.item()
        self.assertEqual(it["state"], "clean")
        self.assertIsNone(it["last_apply_error"])
        self.assertIsNone(it["apply_failures"])
        self.assertEqual(self.plans, [("ident", "dev")])
        self.assertEqual(self.closed, [("ident", "dev")])
        self.assertEqual(self.logged[0]["decision"], "owner_apply_stale_replanned")

    def test_a_replan_with_changes_keeps_one_plain_line_asking_for_a_review(self):
        self.fake_plan("pending")
        self.assertTrue(
            o._replan_after_stale(
                "ident", "dev", self.key, "the worktree moved since the plan. Re-plan."
            )
        )
        it = self.item()
        self.assertEqual(it["state"], "pending")
        self.assertEqual(it["last_apply_error"]["message"], o.STALE_PENDING_MSG)
        self.assertIsNone(it["apply_failures"])  # a stale plan never counts toward the repeat alert
        self.assertEqual(self.closed, [])

    def test_real_failures_never_take_the_stale_path(self):
        self.fake_plan("clean")
        for msg in (
            "LOCKS NOT RESTORED, check them now (apply: Saved plan is stale)",
            "Error: AuthorizationFailed",
            "The saved plan file does not match what the owner reviewed. Re-plan.",
        ):
            self.assertFalse(o._replan_after_stale("ident", "dev", self.key, msg), msg)
        self.assertEqual(self.plans, [])

    def test_a_failed_replan_falls_back_to_the_normal_failure(self):
        self.fake_plan("error")
        self.assertFalse(
            o._replan_after_stale("ident", "dev", self.key, "Error: Saved plan is stale")
        )

    def test_an_apply_that_hits_a_stale_plan_heals_without_a_failure(self):
        o.plan, o._close_alert, o._log = self.saved
        o._close_alert = lambda n, t, reason: self.closed.append((n, t))
        o.plan_all()
        digest = self.item()["plan_sha256"]
        Path(str(STATE) + ".fail").write_text("Saved plan is stale")
        try:
            o.apply("ident", "dev", digest)
        finally:
            Path(str(STATE) + ".fail").unlink(missing_ok=True)
        it = self.item()
        self.assertIsNone(it.get("apply_failures"))
        self.assertIn(it["state"], ("pending", "clean"))
        self.assertNotEqual(it["state"], "error")


if __name__ == "__main__":
    unittest.main()
