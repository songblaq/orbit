"""Tests for orbit_db (SQLite via env)."""

from __future__ import annotations

from pathlib import Path

import pytest

# src on path via pyproject [tool.pytest.ini_options] pythonpath
from orbit_db import _stable_lock_id

# system_config is created by migrations, not schema.sql; mirror v2 SQLite DDL for tests.
SYSTEM_CONFIG_SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS system_config (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  note       TEXT
);
"""


def test_stable_lock_id_deterministic():
    assert _stable_lock_id("orbit-master-tick") == _stable_lock_id("orbit-master-tick")


def test_stable_lock_id_different_inputs():
    a = _stable_lock_id("lock-a")
    b = _stable_lock_id("lock-b")
    assert a != b


def test_get_db_sqlite(orbit_db_sqlite):
    conn = orbit_db_sqlite.get_db()
    try:
        row = conn.execute("SELECT 1 AS n").fetchone()
        assert row["n"] == 1
    finally:
        orbit_db_sqlite.close_db(conn)


@pytest.mark.parametrize(
    "table",
    [
        "task_defs",
        "task_runs",
        "tick_log",
        "lock_lease",
        "system_metrics",
        "schema_migrations",
    ],
)
def test_schema_sql_creates_tables(orbit_db_sqlite, schema_sql_path: Path, table: str):
    conn = orbit_db_sqlite.get_db()
    try:
        conn.executescript(schema_sql_path.read_text(encoding="utf-8"))
        conn.commit()
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        assert row is not None, f"expected table {table!r}"
    finally:
        orbit_db_sqlite.close_db(conn)


def test_set_get_config_roundtrip(orbit_db_sqlite, schema_sql_path: Path):
    conn = orbit_db_sqlite.get_db()
    try:
        conn.executescript(schema_sql_path.read_text(encoding="utf-8"))
        conn.executescript(SYSTEM_CONFIG_SQLITE_DDL)
        conn.commit()
        orbit_db_sqlite.set_config(conn, "pytest_roundtrip_key", "pytest_roundtrip_value")
        assert (
            orbit_db_sqlite.get_config(conn, "pytest_roundtrip_key")
            == "pytest_roundtrip_value"
        )
    finally:
        orbit_db_sqlite.close_db(conn)
