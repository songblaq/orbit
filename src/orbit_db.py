#!/usr/bin/env python3
"""
orbit_db — ORBIT 듀얼 백엔드 DB 추상화 모듈
환경변수 ORBIT_DB_BACKEND=postgres|sqlite 로 전환 (기본: postgres)

사용법:
    from orbit_db import get_db, get_config, set_config, BACKEND
"""

import hashlib
import os
import json
from datetime import datetime, timezone


def _stable_lock_id(name: str) -> int:
    return int.from_bytes(
        hashlib.md5(name.encode()).digest()[:4], "big"
    ) & 0x7FFFFFFF


ORBIT_HOME_DEFAULT = "~/.aria/orbit"

BACKEND = os.environ.get("ORBIT_DB_BACKEND", "postgres").lower()
SQLITE_PATH = os.path.expanduser(
    os.environ.get("ORBIT_SQLITE_PATH", os.path.join(
        os.environ.get("ORBIT_HOME", ORBIT_HOME_DEFAULT), "orbit.db"
    ))
)
PG_DSN = os.environ.get("ORBIT_PG_DSN", "dbname=openclaw")
SCHEMA = "orbit"


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def get_db():
    """백엔드에 따른 DB 커넥션 반환.
    PostgreSQL: psycopg 커넥션 (dict row factory)
    SQLite: sqlite3 커넥션 (Row factory)
    """
    if BACKEND == "postgres":
        import psycopg
        from psycopg.rows import dict_row
        conn = psycopg.connect(PG_DSN, row_factory=dict_row)
        # search_path 설정으로 orbit. prefix 없이 사용 가능
        conn.execute("SET search_path TO orbit, public")
        return conn
    else:
        import sqlite3
        conn = sqlite3.connect(SQLITE_PATH, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn


def get_config(conn, key, default=None):
    """system_config에서 값 읽기."""
    if BACKEND == "postgres":
        row = conn.execute(
            "SELECT value FROM system_config WHERE key=%s", (key,)
        ).fetchone()
        return row["value"] if row else default
    else:
        row = conn.execute(
            "SELECT value FROM system_config WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row else default


def set_config(conn, key, value, note=None):
    """system_config에 값 쓰기 (upsert)."""
    if BACKEND == "postgres":
        conn.execute("""
            INSERT INTO system_config(key, value, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()
        """, (key, value))
        if note:
            conn.execute(
                "UPDATE system_config SET note=%s WHERE key=%s", (note, key)
            )
    else:
        conn.execute("""
            INSERT INTO system_config(key, value, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
        """, (key, value))
        if note:
            conn.execute(
                "UPDATE system_config SET note=? WHERE key=?", (note, key)
            )
    conn.commit()


def param(val):
    """파라미터 플레이스홀더: PG는 %s, SQLite는 ?"""
    return "%s" if BACKEND == "postgres" else "?"


def ph(n=1):
    """n개 파라미터 플레이스홀더 문자열 반환."""
    p = "%s" if BACKEND == "postgres" else "?"
    return ", ".join([p] * n)


def now_sql():
    """현재 시각 SQL 함수."""
    return "NOW()" if BACKEND == "postgres" else "datetime('now')"


def json_dumps(obj):
    """JSON 직렬화 (PG: str → JSONB 자동변환, SQLite: TEXT)."""
    if obj is None:
        return None
    if isinstance(obj, str):
        return obj
    return json.dumps(obj, ensure_ascii=False)


# ─── Advisory Lock (PG) / File Lock (SQLite) ───────────

def try_advisory_lock(conn, lock_name="orbit-master-tick"):
    """PG: pg_try_advisory_lock, SQLite: 파일 기반 (orbit-lock.py 위임)."""
    if BACKEND == "postgres":
        lock_id = _stable_lock_id(lock_name)
        row = conn.execute(
            "SELECT pg_try_advisory_lock(%s) AS acquired", (lock_id,)
        ).fetchone()
        return row["acquired"], "pg_advisory_lock"
    else:
        # SQLite: orbit-lock.py에 위임 (호출측에서 처리)
        return None, "delegate_to_orbit_lock"


def release_advisory_lock(conn, lock_name="orbit-master-tick"):
    """PG advisory lock 해제."""
    if BACKEND == "postgres":
        lock_id = _stable_lock_id(lock_name)
        conn.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))


def close_db(conn):
    """커넥션 종료."""
    conn.close()
