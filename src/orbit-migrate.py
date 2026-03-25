#!/usr/bin/env python3
"""
orbit-migrate — ORBIT schema migration 멱등 래퍼
v2~v4: task_defs / system_config / watchdog_log / AgentHive 스키마를 순차·멱등 적용.
v4는 컬럼·테이블 보강을 매 실행 시 확인하고, 프로젝트 매핑·버전 기록은 최초 1회만 수행.

사용법:
  python3 orbit-migrate.py            # migration 실행
  python3 orbit-migrate.py --status   # 현재 schema 상태 확인
"""

import os
import sys

from orbit_db import get_db, BACKEND, SQLITE_PATH

P = "%s" if BACKEND == "postgres" else "?"


def get_columns(conn, table):
    if BACKEND == "postgres":
        rows = conn.execute("""
            SELECT column_name AS name
            FROM information_schema.columns
            WHERE table_schema = 'orbit' AND table_name = %s
        """, (table,)).fetchall()
    else:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r["name"] for r in rows}


def table_exists(conn, table):
    if BACKEND == "postgres":
        row = conn.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'orbit' AND table_name = %s
        """, (table,)).fetchone()
    else:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
    return row is not None


def migration_applied(conn, version):
    if not table_exists(conn, "schema_migrations"):
        return False
    row = conn.execute(
        f"SELECT version FROM schema_migrations WHERE version={P}", (version,)
    ).fetchone()
    return row is not None


def run_v2(conn):
    """Migration v2: cron_job_id, consecutive_successes, system_config 추가."""
    changed = []

    # task_defs 컬럼 추가 (멱등)
    existing = get_columns(conn, "task_defs")
    new_columns = [
        ("cron_job_id",            "TEXT"),
        ("consecutive_successes",  "INTEGER DEFAULT 0"),
        ("last_dispatched_at",     "TEXT"),
        ("orbit_managed",          "INTEGER DEFAULT 0"),
    ]
    for col, col_type in new_columns:
        if col not in existing:
            conn.execute(f"ALTER TABLE task_defs ADD COLUMN {col} {col_type}")
            changed.append(f"task_defs.{col} 추가")
        else:
            print(f"  skip: task_defs.{col} 이미 존재")

    # system_config 테이블 생성 (멱등)
    if BACKEND == "postgres":
        conn.execute("""
            CREATE TABLE IF NOT EXISTS system_config (
              key        TEXT PRIMARY KEY,
              value      TEXT NOT NULL,
              updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              note       TEXT
            )
        """)
    else:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS system_config (
              key        TEXT PRIMARY KEY,
              value      TEXT NOT NULL,
              updated_at TEXT NOT NULL DEFAULT (datetime('now')),
              note       TEXT
            )
        """)
    changed.append("system_config 테이블 생성(or skip)")

    # 기본값 INSERT (멱등)
    defaults = [
        ("orbit_mode",      "shadow",  "shadow=Week-1, active=Week-2+"),
        ("week",            "1",       "현재 week"),
        ("shadow_start_at", None,      "shadow 시작 시각"),  # None → NOW() or datetime('now')
        ("dispatch_tiers",  "",        "active 시 dispatch할 tier 목록 (예: 4,5)"),
        ("freeze_count",    "0",       "scheduler freeze 발생 횟수"),
        ("sla_miss_count",  "0",       "SLA miss 횟수"),
    ]
    for key, val, note in defaults:
        if val is None:
            # shadow_start_at: NOW() / datetime('now') — SQL 함수로 삽입
            if BACKEND == "postgres":
                conn.execute("""
                    INSERT INTO system_config(key, value, note)
                    VALUES (%s, NOW()::TEXT, %s)
                    ON CONFLICT DO NOTHING
                """, (key, note))
            else:
                conn.execute("""
                    INSERT OR IGNORE INTO system_config(key, value, note)
                    VALUES (?, datetime('now'), ?)
                """, (key, note))
        else:
            if BACKEND == "postgres":
                conn.execute("""
                    INSERT INTO system_config(key, value, note)
                    VALUES (%s, %s, %s)
                    ON CONFLICT DO NOTHING
                """, (key, val, note))
            else:
                conn.execute("""
                    INSERT OR IGNORE INTO system_config(key, value, note)
                    VALUES (?, ?, ?)
                """, (key, val, note))

    # cron_job_id 매핑 UPDATE
    mappings = [
        ("ops-anomaly-detection", "8d567769-8176-4b6c-a954-cb614215b217"),
        ("ops-alert-router",      "d625e54e-e013-4f04-bf9d-c4737d0531e3"),
        ("ha003-healthcheck",     "fc199d9c-4095-45b0-a6d1-3ee58d989f07"),
        ("ai-collection",         "b9501906-b56c-4889-9822-1c8a29c88960"),
        ("morning-checkin",       "51ea9815-abf0-4a51-b4f3-73b63dc5d924"),
        ("luca-ai-expert",        "929eb8b3-35e2-4abe-8f78-c8267b9c069c"),
        ("investment-monitor",    "343ed6a1-a19b-43b4-aab6-c192b95f9dd1"),
        ("daily-retrospective",   "744e339e-2495-4f25-b357-a9eed0f44bed"),
        ("sns-content",           "e8cc7735-ea06-4c5b-a06b-9c7e8fca3b26"),
        ("botmadang-activity",    "0bc7adf9-7025-4cb9-b3ad-823069aaf31e"),
        ("maltbook-activity",     "7db751e2-1719-4830-a073-690eab2ff46d"),
        ("x-twitter-activity",    "f5e8310c-26a8-4f7b-a680-0e5d2b8a3737"),
        ("ops-skill-audit",       "5fe03fb0-2db2-482c-9e0e-95d25c360d11"),
        ("infra-check",           "39e7688b-e32b-4e1d-a887-fe1000984899"),
        ("project-check",         "5e600d34-54ee-4049-9435-241ecf61f8bc"),
        ("drift-daily-checkin",   "16c8c1be-eba5-46a3-be20-876762c8d655"),
        ("drift-weekly-report",   "3616418c-a5e0-47cd-b48b-5d5f55b0a3a3"),
        ("drift-alert-check",     "d978afdc-ff2a-4951-a566-934a9539d13e"),
        ("ops-weekly-audit",      "8773e41a-bf22-4937-b539-2a1bd0aaad33"),
        ("cafe-backup",           "9c47d1f3-c993-4970-98ba-500f652f2dab"),
        ("exercise-rd",           "71329f0a-8ae5-4608-9255-4d4a19ac0976"),
        ("deepcron-manager",      "08b07f1e-2a1e-4e6a-8640-b39d09e76568"),
        ("deepwork-nexusops",     "e0e1e56c-f36d-4dd6-906f-e6b1b617efac"),
        ("deepwork-agent-300",    "940f3b00-2920-4e73-8021-a5487c1ba42e"),
        ("ha004-daily-report",    "ad404cf6-e0bd-48e4-9e54-dd5e3b7377b0"),
        ("ha004-weekly-report",   "58a439f0-eeb7-46a9-a1c3-b118e163fbd5"),
    ]
    for task_id, cron_id in mappings:
        conn.execute(
            f"UPDATE task_defs SET cron_job_id={P} WHERE id={P} AND cron_job_id IS NULL",
            (cron_id, task_id)
        )

    # migration 버전 기록
    if BACKEND == "postgres":
        conn.execute("""
            INSERT INTO schema_migrations(version, description)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
        """, (2, 'Week-2: cron_job_id mapping, consecutive_successes, system_config table'))
    else:
        conn.execute("""
            INSERT OR IGNORE INTO schema_migrations(version, description)
            VALUES (2, 'Week-2: cron_job_id mapping, consecutive_successes, system_config table')
        """)
    conn.commit()
    return changed


def run_v3(conn):
    """Migration v3: watchdog_log 테이블, task_defs.p_lord (schema_migration_v3 + v3_add_plord)."""
    changed = []

    existing_td = get_columns(conn, "task_defs")
    if "p_lord" not in existing_td:
        if BACKEND == "postgres":
            conn.execute(
                "ALTER TABLE task_defs ADD COLUMN p_lord DOUBLE PRECISION DEFAULT 0.5"
            )
        else:
            conn.execute(
                "ALTER TABLE task_defs ADD COLUMN p_lord REAL DEFAULT 0.5"
            )
        changed.append("task_defs.p_lord 추가")
    else:
        print("  skip: task_defs.p_lord 이미 존재")

    if BACKEND == "postgres":
        conn.execute("""
            CREATE TABLE IF NOT EXISTS watchdog_log (
              id             SERIAL PRIMARY KEY,
              checked_at     TEXT NOT NULL,
              owner_pid      INTEGER NOT NULL,
              lock_held      INTEGER DEFAULT 0,
              lock_owner_pid INTEGER,
              lock_age_ms    INTEGER,
              bypass_reason  TEXT,
              action         TEXT NOT NULL DEFAULT 'check'
                             CHECK(action IN ('check','bypass','alert','ok')),
              t1_task_ids    TEXT,
              alert_count    INTEGER DEFAULT 0,
              notes          TEXT,
              created_at     TEXT NOT NULL DEFAULT (NOW()::TEXT)
            )
        """)
    else:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS watchdog_log (
              id             INTEGER PRIMARY KEY AUTOINCREMENT,
              checked_at     TEXT NOT NULL,
              owner_pid      INTEGER NOT NULL,
              lock_held      INTEGER DEFAULT 0,
              lock_owner_pid INTEGER,
              lock_age_ms    INTEGER,
              bypass_reason  TEXT,
              action         TEXT NOT NULL DEFAULT 'check'
                             CHECK(action IN ('check','bypass','alert','ok')),
              t1_task_ids    TEXT,
              alert_count    INTEGER DEFAULT 0,
              notes          TEXT,
              created_at     TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
    changed.append("watchdog_log 테이블 생성(or skip)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_watchdog_log_at ON watchdog_log(checked_at DESC)"
    )

    if BACKEND == "postgres":
        conn.execute("""
            INSERT INTO schema_migrations(version, description)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
        """, (3, 'WS-2: watchdog_log table, p_lord on task_defs'))
    else:
        conn.execute("""
            INSERT OR IGNORE INTO schema_migrations(version, description)
            VALUES (3, 'WS-2: watchdog_log table, p_lord on task_defs')
        """)
    conn.commit()
    return changed


def run_v4(conn):
    """Migration v4: AgentHive — schema_migration_v4.sql + v4_agenthive.sql 컬럼 통합."""
    changed = []
    v4_needs_record = not migration_applied(conn, 4)

    existing = get_columns(conn, "task_defs")
    new_columns = [
        ("agenthive_project",           "TEXT"),
        ("agenthive_task_id",           "TEXT"),
        ("agenthive_status",            "TEXT"),
        ("agenthive_synced_at",         "TEXT"),
        ("ah_sync_enabled",             "INTEGER DEFAULT 1"),
        ("ah_status_last_checked_at",   "TEXT"),
        ("ah_status_last_result",       "TEXT"),
    ]
    for col, col_type in new_columns:
        if col not in existing:
            conn.execute(f"ALTER TABLE task_defs ADD COLUMN {col} {col_type}")
            changed.append(f"task_defs.{col} 추가")
        else:
            print(f"  skip: task_defs.{col} 이미 존재")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_defs_ah_project ON task_defs(agenthive_project)")

    if BACKEND == "postgres":
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agenthive_sync_log (
              id                SERIAL PRIMARY KEY,
              task_id           TEXT NOT NULL,
              checked_at        TEXT NOT NULL,
              ah_project        TEXT,
              ah_task_id        TEXT,
              ah_status         TEXT,
              dispatch_decision TEXT CHECK(dispatch_decision IS NULL OR dispatch_decision IN ('proceeded', 'skipped', 'error')),
              reason            TEXT,
              error_message     TEXT,
              created_at        TEXT NOT NULL DEFAULT (NOW()::TEXT)
            )
        """)
    else:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agenthive_sync_log (
              id                INTEGER PRIMARY KEY AUTOINCREMENT,
              task_id           TEXT NOT NULL,
              checked_at        TEXT NOT NULL,
              ah_project        TEXT,
              ah_task_id        TEXT,
              ah_status         TEXT,
              dispatch_decision TEXT CHECK(dispatch_decision IN ('proceeded', 'skipped', 'error')),
              reason            TEXT,
              error_message     TEXT,
              created_at        TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
    changed.append("agenthive_sync_log 테이블 생성(or skip)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_agenthive_sync_log_task_id ON agenthive_sync_log(task_id, checked_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_agenthive_sync_log_at ON agenthive_sync_log(checked_at DESC)"
    )

    ah_cfg = [
        ("agenthive_api_url",           "http://localhost:8100",  "AgentHive API base URL (OpenJarvis default)"),
        ("agenthive_api_timeout_sec",   "5",                      "AH API request timeout in seconds"),
        ("agenthive_sync_interval_min", "30",                     "Minimum interval between AH status checks (minutes)"),
    ]
    for key, val, note in ah_cfg:
        if BACKEND == "postgres":
            conn.execute("""
                INSERT INTO system_config(key, value, note)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (key, val, note))
        else:
            conn.execute("""
                INSERT OR IGNORE INTO system_config(key, value, note)
                VALUES (?, ?, ?)
            """, (key, val, note))

    if v4_needs_record:
        # 기본 AgentHive 프로젝트 매핑 (Orbit task_id → AH project)
        ah_mappings = [
            ("ops-%",              "ops"),
            ("ha00%",              "ops"),
            ("infra-%",            "ops"),
            ("drift-%",            "ops"),
            ("deepcron-%",         "ops"),
            ("sns-%",              "content-factory"),
            ("botmadang-%",        "content-factory"),
            ("maltbook-%",         "content-factory"),
            ("x-twitter-%",        "content-factory"),
            ("exercise-%",         "smart-gym"),
            ("ai-%",               "research-lab"),
            ("investment-%",       "research-lab"),
            ("cafe-%",             "ops"),
            ("deepwork-%",         "research-lab"),
            ("morning-%",          "ops"),
            ("daily-%",            "ops"),
            ("project-%",          "openclaw"),
            ("luca-%",             "research-lab"),
        ]
        for pattern, ah_project in ah_mappings:
            if BACKEND == "postgres":
                conn.execute("""
                    UPDATE task_defs SET agenthive_project = %s
                    WHERE id LIKE %s AND agenthive_project IS NULL
                """, (ah_project, pattern))
            else:
                conn.execute("""
                    UPDATE task_defs SET agenthive_project = ?
                    WHERE id LIKE ? AND agenthive_project IS NULL
                """, (ah_project, pattern))

        if BACKEND == "postgres":
            conn.execute("""
                INSERT INTO schema_migrations(version, description)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
            """, (4, 'AgentHive: task_defs AH columns + ah_sync_* + agenthive_sync_log + system_config'))
        else:
            conn.execute("""
                INSERT OR IGNORE INTO schema_migrations(version, description)
                VALUES (4, 'AgentHive: task_defs AH columns + ah_sync_* + agenthive_sync_log + system_config')
            """)
        changed.append("v4 기본 프로젝트 매핑 + schema_migrations 기록")
    conn.commit()
    return changed


def cmd_status(conn):
    print("─── schema_migrations ───")
    if table_exists(conn, "schema_migrations"):
        rows = conn.execute("SELECT version, description FROM schema_migrations ORDER BY version").fetchall()
        for r in rows:
            print(f"  v{r['version']}: {r['description']}")
    else:
        print("  (테이블 없음)")

    print("\n─── task_defs 컬럼 ───")
    if table_exists(conn, "task_defs"):
        cols = get_columns(conn, "task_defs")
        for c in sorted(cols):
            print(f"  {c}")

    print("\n─── system_config ───")
    if table_exists(conn, "system_config"):
        rows = conn.execute("SELECT key, value FROM system_config ORDER BY key").fetchall()
        for r in rows:
            print(f"  {r['key']:28s} = {str(r['value'])!r}")
    else:
        print("  (테이블 없음)")


def main():
    if BACKEND == "sqlite":
        db_path = SQLITE_PATH
        if not os.path.exists(db_path):
            print(f"DB 없음: {db_path}", file=sys.stderr)
            sys.exit(1)
        print(f"[orbit-migrate] DB: {db_path}")
    else:
        print(f"[orbit-migrate] DB: PostgreSQL (BACKEND=postgres)")

    conn = get_db()
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "--status":
            cmd_status(conn)
            return

        if not migration_applied(conn, 2):
            print("  v2 migration 실행 중...")
            changed = run_v2(conn)
            for c in changed:
                print(f"  ✅ {c}")
            print("  ✅ v2 migration 완료")
        else:
            print("  v2 이미 적용됨 — 건너뜀")

        if not migration_applied(conn, 3):
            print("  v3 migration 실행 중 (watchdog_log, p_lord)...")
            changed = run_v3(conn)
            for c in changed:
                print(f"  ✅ {c}")
            print("  ✅ v3 migration 완료")
        else:
            print("  v3 이미 적용됨 — 건너뜀")

        print("  v4 스키마 확인 (AgentHive, 멱등)...")
        changed = run_v4(conn)
        for c in changed:
            print(f"  ✅ {c}")
        print("  ✅ v4 확인 완료")

        cmd_status(conn)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
