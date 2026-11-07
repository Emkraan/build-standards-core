"""
lookup_db.py
Purpose: The reports module's small SQLite database (`OPSCENTER_REPORTS_DB`, default `<state>/reports.db`) for the lookup caches. Opened only when a
         function that needs it is called; importing this file creates nothing.
Date:    2026-11-07
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import paths

SCHEMA = """
CREATE TABLE IF NOT EXISTS log_directory (
  account TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  display_name TEXT,
  upn TEXT,
  email TEXT,
  department TEXT,
  job_title TEXT,
  enabled INTEGER,
  resolved_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS log_catalog (
  entry_id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  store TEXT,
  name TEXT,
  publisher TEXT,
  installs INTEGER,
  resolved_at TEXT NOT NULL,
  manual INTEGER NOT NULL DEFAULT 0
);
"""


def path():
    return Path(os.environ.get("OPSCENTER_REPORTS_DB") or paths.state_dir() / "reports.db")


def connect():
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p), timeout=30)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con
