"""Shared pytest fixtures for ORBIT."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ORBIT_ROOT = Path(__file__).resolve().parent.parent
ORBIT_SRC = ORBIT_ROOT / "src"
SCHEMA_SQL_PATH = ORBIT_SRC / "schema.sql"


@pytest.fixture
def orbit_db_sqlite(tmp_path, monkeypatch):
    """Point orbit_db at a temporary SQLite file and return a freshly loaded module."""
    db_path = tmp_path / "orbit_test.db"
    monkeypatch.setenv("ORBIT_DB_BACKEND", "sqlite")
    monkeypatch.setenv("ORBIT_SQLITE_PATH", str(db_path))
    monkeypatch.delenv("ORBIT_HOME", raising=False)

    sys.modules.pop("orbit_db", None)
    import orbit_db

    return orbit_db


@pytest.fixture
def schema_sql_path() -> Path:
    return SCHEMA_SQL_PATH
