#!/usr/bin/env python3
"""
orbit-checkpoint — WAL checkpoint 전용 (WS-6)
실행 주기: */30 크론 권장
동작: WAL 파일을 메인 DB로 병합, 크기 제어

PostgreSQL 백엔드: WAL 체크포인트가 자동 관리되므로 불필요 — 즉시 종료.
SQLite 백엔드: PRAGMA wal_checkpoint 기존 동작 유지.
"""

import os
import sys
from datetime import datetime, timezone

from orbit_db import BACKEND, now_utc

SQLITE_PATH = os.path.expanduser("~/.openclaw/data/orbit/orbit.db")


def run_checkpoint():
    if BACKEND == "postgres":
        ts = now_utc()
        print(f"[orbit-checkpoint] {ts}")
        print("  PostgreSQL 백엔드: WAL checkpoint는 PG가 자동 관리합니다 — 작업 없음.")
        return True

    # SQLite path
    try:
        import sqlite3
        conn = sqlite3.connect(SQLITE_PATH, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=1000")

        # PASSIVE checkpoint: 실행 중인 reader/writer 방해 없이 병합
        result = conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        # result: (busy, log, checkpointed)
        busy, log_pages, checkpointed = result

        # WAL 파일 크기 확인
        wal_path = SQLITE_PATH + "-wal"
        wal_size_kb = 0
        if os.path.exists(wal_path):
            wal_size_kb = os.path.getsize(wal_path) // 1024

        conn.close()

        ts = now_utc()
        print(f"[orbit-checkpoint] {ts}")
        print(f"  WAL: log={log_pages} pages, checkpointed={checkpointed}, busy={busy}")
        print(f"  WAL file: {wal_size_kb} KB")

        if busy > 0:
            print(f"  ⚠️  {busy} pages busy (active readers) — TRUNCATE 건너뜀")
        elif wal_size_kb > 4096:
            # WAL > 4MB면 TRUNCATE로 완전 병합
            conn2 = sqlite3.connect(SQLITE_PATH, timeout=10)
            conn2.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn2.close()
            print(f"  ✅ TRUNCATE checkpoint 실행 (WAL {wal_size_kb}KB → 0)")
        else:
            print(f"  ✅ PASSIVE checkpoint 완료")

        return True
    except Exception as e:
        print(f"[orbit-checkpoint ERROR] {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    ok = run_checkpoint()
    sys.exit(0 if ok else 1)
