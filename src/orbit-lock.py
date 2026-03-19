#!/usr/bin/env python3
"""
orbit-lock — WS-1 공통 락 모듈
파일락(O_CREAT|O_EXCL 원자적) + DB lock_lease 이중 기록.
- acquire(): 원자적 파일 생성 + DB lease 등록
- release(): 파일 삭제 + DB lease 제거
- check_stale(): expire_at 초과 orphan lock 감지
- heartbeat(): lock_lease.heartbeat_at 갱신

PostgreSQL 백엔드: pg_advisory_lock 기반 (파일락 없음)
SQLite 백엔드: 파일락 + DB dual lock 기존 동작 유지
"""

import os
import json
import time
from datetime import datetime, timezone

from orbit_db import get_db, BACKEND, now_utc, close_db

LOCK_DIR = "/tmp"
LOCK_TTL_SEC = 600  # 10분


def _lock_path(lock_key: str) -> str:
    safe = lock_key.replace("/", "_").replace(":", "_")
    return os.path.join(LOCK_DIR, f"orbit-{safe}.lock")


def _lock_id(lock_key: str) -> int:
    """lock_key → 안정적 hash int (pg_advisory_lock용)."""
    return hash(lock_key) & 0x7FFFFFFF


class OrbitLock:
    """단일 lock key에 대한 통합 락.

    PostgreSQL: pg_advisory_lock 기반 (파일락 불필요)
    SQLite: 파일락 + DB dual lock
    """

    def __init__(self, db_path: str, lock_key: str, ttl_sec: int = LOCK_TTL_SEC):
        # db_path는 SQLite 호환성을 위해 수용하되, postgres에서는 무시됨
        self.db_path = db_path
        self.lock_key = lock_key
        self.ttl_sec = ttl_sec
        self.lock_file_path = _lock_path(lock_key)
        self._fd = None
        self._pg_conn = None  # postgres 세션 커넥션 유지용

    # ── PostgreSQL path ─────────────────────────────────────────

    def _pg_acquire(self) -> tuple[bool, str]:
        """pg_try_advisory_lock으로 락 획득 시도."""
        conn = get_db()
        lid = _lock_id(self.lock_key)
        row = conn.execute(
            "SELECT pg_try_advisory_lock(%s) AS acquired", (lid,)
        ).fetchone()
        if row["acquired"]:
            # 커넥션을 열어 둬야 advisory lock이 유지됨
            self._pg_conn = conn
            return True, "ok"
        else:
            conn.close()
            return False, "lock held by another session"

    def _pg_release(self):
        if self._pg_conn is not None:
            try:
                lid = _lock_id(self.lock_key)
                self._pg_conn.execute("SELECT pg_advisory_unlock(%s)", (lid,))
                self._pg_conn.commit()
            except Exception:
                pass
            finally:
                self._pg_conn.close()
                self._pg_conn = None

    def _pg_get_info(self) -> dict:
        """pg_locks를 통해 현재 advisory lock 보유 여부 확인."""
        try:
            conn = get_db()
            lid = _lock_id(self.lock_key)
            row = conn.execute("""
                SELECT pid FROM pg_locks
                WHERE locktype='advisory'
                  AND objid=%s
                  AND granted=true
                LIMIT 1
            """, (lid,)).fetchone()
            conn.close()
            if row:
                return {"held": True, "pid": row["pid"], "stale": False}
            return {"held": False}
        except Exception:
            return {"held": False}

    # ── SQLite path ─────────────────────────────────────────────

    def _sqlite_get_db(self):
        return get_db()

    def _sqlite_acquire(self) -> tuple[bool, str]:
        """원자적 파일 생성(O_CREAT|O_EXCL) + DB lease 등록."""
        try:
            fd = os.open(
                self.lock_file_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600
            )
        except FileExistsError:
            stale, info = self._check_file_stale()
            if stale:
                try:
                    os.remove(self.lock_file_path)
                except OSError:
                    pass
                try:
                    fd = os.open(
                        self.lock_file_path,
                        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                        0o600
                    )
                except FileExistsError:
                    return False, f"lock file exists (stale removed but re-created): {info}"
            else:
                return False, f"lock held: {info}"

        pid = os.getpid()
        expire_at = time.time() + self.ttl_sec
        meta = json.dumps({
            "pid": pid,
            "lock_key": self.lock_key,
            "acquired_at": time.time(),
            "expire_at": expire_at,
        })
        os.write(fd, meta.encode())
        os.close(fd)
        self._fd = fd

        try:
            conn = self._sqlite_get_db()
            expire_dt = datetime.fromtimestamp(expire_at, tz=timezone.utc).isoformat()
            conn.execute("""
                INSERT INTO lock_lease(lock_key, holder, acquired_at, expire_at, heartbeat_at)
                VALUES (?, ?, datetime('now'), ?, datetime('now'))
                ON CONFLICT(lock_key) DO UPDATE SET
                    holder=excluded.holder,
                    acquired_at=excluded.acquired_at,
                    expire_at=excluded.expire_at,
                    heartbeat_at=excluded.heartbeat_at
            """, (self.lock_key, str(pid), expire_dt))
            conn.commit()
            conn.close()
        except Exception:
            pass

        return True, "ok"

    def _sqlite_release(self):
        try:
            os.remove(self.lock_file_path)
        except OSError:
            pass

        try:
            conn = self._sqlite_get_db()
            conn.execute("DELETE FROM lock_lease WHERE lock_key=?", (self.lock_key,))
            conn.commit()
            conn.close()
        except Exception:
            pass

    def _sqlite_heartbeat(self):
        try:
            conn = self._sqlite_get_db()
            conn.execute("""
                UPDATE lock_lease SET heartbeat_at=datetime('now') WHERE lock_key=?
            """, (self.lock_key,))
            conn.commit()
            conn.close()
        except Exception:
            pass

    # ── Public API ──────────────────────────────────────────────

    def acquire(self) -> tuple[bool, str]:
        if BACKEND == "postgres":
            return self._pg_acquire()
        return self._sqlite_acquire()

    def release(self):
        if BACKEND == "postgres":
            self._pg_release()
        else:
            self._sqlite_release()

    def heartbeat(self):
        """DB lock_lease.heartbeat_at 갱신 (SQLite only; PG advisory lock은 세션 기반)."""
        if BACKEND == "postgres":
            return  # advisory lock은 세션이 살아 있는 한 유효
        self._sqlite_heartbeat()

    def _check_file_stale(self) -> tuple[bool, str]:
        """파일락이 stale(만료)인지 확인 (SQLite 전용)."""
        try:
            with open(self.lock_file_path) as f:
                data = json.load(f)
            expire_at = data.get("expire_at", 0)
            pid = data.get("pid")
            if time.time() > expire_at:
                age = int(time.time() - expire_at)
                return True, f"expired {age}s ago (PID {pid})"
            remaining = int(expire_at - time.time())
            return False, f"PID {pid}, expires in {remaining}s"
        except Exception as e:
            return True, f"unreadable ({e})"

    def get_info(self) -> dict:
        """현재 lock 상태 반환."""
        if BACKEND == "postgres":
            return self._pg_get_info()
        # SQLite: 파일 기반
        if not os.path.exists(self.lock_file_path):
            return {"held": False}
        try:
            with open(self.lock_file_path) as f:
                data = json.load(f)
            age_ms = int((time.time() - data.get("acquired_at", time.time())) * 1000)
            stale = time.time() > data.get("expire_at", 0)
            return {
                "held": True,
                "pid": data.get("pid"),
                "age_ms": age_ms,
                "stale": stale,
                "expire_at": data.get("expire_at"),
            }
        except Exception:
            return {"held": True, "stale": True, "error": "unreadable"}


def check_all_stale(db_path: str = None) -> list[dict]:
    """DB lock_lease에서 orphan lock(만료) 전체 조회."""
    try:
        conn = get_db()
        if BACKEND == "postgres":
            rows = conn.execute("""
                SELECT lock_key, holder, acquired_at, expire_at, heartbeat_at
                FROM lock_lease
                WHERE expire_at < NOW()
            """).fetchall()
        else:
            rows = conn.execute("""
                SELECT lock_key, holder, acquired_at, expire_at, heartbeat_at
                FROM lock_lease
                WHERE datetime(expire_at) < datetime('now')
            """).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def cleanup_stale(db_path: str = None) -> int:
    """만료된 DB lease 정리. 정리된 건수 반환."""
    orphans = check_all_stale(db_path)
    if not orphans:
        return 0
    try:
        conn = get_db()
        if BACKEND == "postgres":
            conn.execute("DELETE FROM lock_lease WHERE expire_at < NOW()")
        else:
            conn.execute("DELETE FROM lock_lease WHERE datetime(expire_at) < datetime('now')")
            # SQLite: 파일락도 정리
            for o in orphans:
                fp = _lock_path(o["lock_key"])
                try:
                    os.remove(fp)
                except OSError:
                    pass
        conn.commit()
        conn.close()
        return len(orphans)
    except Exception:
        return 0
