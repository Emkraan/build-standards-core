import os
import sqlite3
import time
import unittest

from support import Work, load

sr = load("safe_hermes_restart", "hermes/safe-restart/safe_hermes_restart.py")


class TurnLeases(Work):
    def db(self, rows):
        path = self.dir / "state.db"
        c = sqlite3.connect(path)
        c.execute(
            "create table session_turn_leases (conversation_id text primary key, holder text, "
            "acquired_at real, expires_at real)"
        )
        c.executemany("insert into session_turn_leases values (?,?,?,?)", rows)
        c.commit()
        c.close()
        return str(path)

    def test_live_unexpired_lease_is_busy(self):
        now = time.time()
        path = self.db([("a", f"pid={os.getpid()}:turn=a:platform=desktop", now - 5, now + 60)])
        self.assertEqual(sr.turn_reasons(path, now), ["chat turn in flight: a"])

    def test_expired_or_dead_lease_is_idle(self):
        now = time.time()
        path = self.db(
            [
                ("old", f"pid={os.getpid()}:turn=old", now - 600, now - 1),
                ("dead", "pid=999999:turn=dead", now - 5, now + 60),
            ]
        )
        self.assertEqual(sr.turn_reasons(path, now), [])

    def test_unreadable_store_is_busy(self):
        path = self.dir / "state.db"
        path.write_text("not a database")
        reasons = sr.turn_reasons(str(path))
        self.assertEqual(len(reasons), 1)
        self.assertTrue(reasons[0].startswith("cannot read turn leases"))

    def test_missing_store_is_idle(self):
        self.assertEqual(sr.turn_reasons(str(self.dir / "absent.db")), [])


if __name__ == "__main__":
    unittest.main()
