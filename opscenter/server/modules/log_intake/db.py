"""
db.py
Purpose: The log intake module's SQLite database (`LOG_INTAKE_DB`, default `<state>/log-intake.db`). Opened only when a function that needs it
         is called; importing this file creates nothing. The schema is additive (create if missing), the connection waits on a busy
         database, and the file is only ever created by the module when it is on.
Date:    2026-11-07
Notes:   The tables are the stream, field, current-snapshot, event, buffer and post-count tables of the reference implementation; its sink, report and
         directory tables are not here.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import paths

SCHEMA = """
CREATE TABLE IF NOT EXISTS log_streams (
  key TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  table_name TEXT NOT NULL UNIQUE,
  integration_key TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  max_rows INTEGER NOT NULL DEFAULT 2000,
  max_bytes INTEGER NOT NULL DEFAULT 2097152,
  retention_days INTEGER NOT NULL DEFAULT 180,
  posts_per_device_hour INTEGER NOT NULL DEFAULT 6,
  mode TEXT NOT NULL DEFAULT 'latest',
  schema_version INTEGER NOT NULL DEFAULT 1,
  sync_state TEXT NOT NULL DEFAULT 'pending',
  sync_error TEXT,
  created_by TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS log_stream_fields (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  stream_key TEXT NOT NULL,
  name TEXT NOT NULL,
  column_name TEXT NOT NULL,
  kind TEXT NOT NULL,
  required INTEGER NOT NULL DEFAULT 0,
  retired INTEGER NOT NULL DEFAULT 0,
  position INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_log_stream_fields_stream ON log_stream_fields(stream_key, position);
CREATE TABLE IF NOT EXISTS log_stream_current (
  stream_key TEXT NOT NULL,
  source TEXT NOT NULL,
  snapshot_id TEXT NOT NULL,
  collected_at TEXT NOT NULL,
  received_at TEXT NOT NULL DEFAULT (datetime('now')),
  row_count INTEGER NOT NULL,
  rows_json TEXT NOT NULL,
  PRIMARY KEY (stream_key, source)
);
CREATE TABLE IF NOT EXISTS log_stream_events (
  stream_key TEXT NOT NULL,
  source TEXT NOT NULL,
  snapshot_id TEXT NOT NULL,
  collected_at TEXT NOT NULL,
  received_at TEXT NOT NULL DEFAULT (datetime('now')),
  row_count INTEGER NOT NULL,
  rows_json TEXT NOT NULL,
  PRIMARY KEY (stream_key, snapshot_id)
);
CREATE INDEX IF NOT EXISTS idx_log_stream_events_received ON log_stream_events (stream_key, received_at);
CREATE TABLE IF NOT EXISTS log_buffer (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  stream_key TEXT NOT NULL,
  device TEXT NOT NULL,
  snapshot_id TEXT NOT NULL,
  collected_at TEXT NOT NULL,
  received_at TEXT NOT NULL DEFAULT (datetime('now')),
  row_count INTEGER NOT NULL,
  rows_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  sent_at TEXT,
  bytes INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_log_buffer_status ON log_buffer(stream_key, status, id);
CREATE INDEX IF NOT EXISTS idx_log_buffer_device ON log_buffer(stream_key, device, received_at);
CREATE TABLE IF NOT EXISTS log_post_log (
  stream_key TEXT NOT NULL,
  device TEXT NOT NULL,
  received_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_log_post_log ON log_post_log(stream_key, device, received_at);
"""


def path():
    return Path(os.environ.get("LOG_INTAKE_DB") or paths.state_dir() / "log-intake.db")


def connect():
    """A connection to the module's database, created with its schema on first use. Rows are returned as sqlite3.Row."""
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p), timeout=30)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con
