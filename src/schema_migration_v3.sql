-- ORBIT schema migration v3 — WS-2 watchdog_log 테이블
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS watchdog_log (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  checked_at     TEXT NOT NULL,
  owner_pid      INTEGER NOT NULL,
  lock_held      INTEGER DEFAULT 0,        -- 1=tick lock 점유 중
  lock_owner_pid INTEGER,
  lock_age_ms    INTEGER,
  bypass_reason  TEXT,                     -- null=정상, 'lock_bypass'=bypass 실행
  action         TEXT NOT NULL DEFAULT 'check'
                 CHECK(action IN ('check','bypass','alert','ok')),
  t1_task_ids    TEXT,                     -- JSON array: 점검한 T1 task ids
  alert_count    INTEGER DEFAULT 0,
  notes          TEXT,
  created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_watchdog_log_at ON watchdog_log(checked_at DESC);

INSERT OR IGNORE INTO schema_migrations(version, description)
VALUES (3, 'WS-2: watchdog_log table for T1 bypass audit trail');
